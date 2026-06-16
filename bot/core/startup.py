from asyncio import create_subprocess_exec, create_subprocess_shell
from importlib import import_module
import os
from os import environ, getenv, path as ospath

from aiofiles import open as aiopen
from aiofiles.os import makedirs, remove, path as aiopath
from aioshutil import rmtree

from sabnzbdapi.exception import APIResponseError

from .. import (
    LOGGER,
    aria2_options,
    auth_chats,
    drives_ids,
    drives_names,
    index_urls,
    shortener_dict,
    var_list,
    user_data,
    excluded_extensions,
    nzb_options,
    qbit_options,
    rss_dict,
    sabnzbd_client,
    sudo_users,
)
from ..helper.ext_utils.db_handler import database
from .config_manager import Config, BinConfig
from .tg_client import TgClient
from .torrent_manager import TorrentManager


async def update_qb_options():
    if not qbit_options:
        if not TorrentManager.qbittorrent:
            LOGGER.warning(
                "qBittorrent is not initialized. Skipping qBittorrent options update."
            )
            return
        opt = await TorrentManager.qbittorrent.app.preferences()
        qbit_options.update(opt)
        del qbit_options["listen_port"]
        for k in list(qbit_options.keys()):
            if k.startswith("rss"):
                del qbit_options[k]
        qbit_options["web_ui_password"] = "admin"
        await TorrentManager.qbittorrent.app.set_preferences(
            {"web_ui_password": "admin"}
        )
    else:
        await TorrentManager.qbittorrent.app.set_preferences(qbit_options)


async def update_aria2_options():
    if not aria2_options:
        op = await TorrentManager.aria2.getGlobalOption()
        aria2_options.update(op)
    else:
        await TorrentManager.aria2.changeGlobalOption(aria2_options)


async def update_nzb_options():
    if Config.USENET_SERVERS:
        try:
            no = (await sabnzbd_client.get_config())["config"]["misc"]
            nzb_options.update(no)
        except (APIResponseError, Exception) as e:
            LOGGER.error(f"Error in NZB Options: {e}")


async def load_settings():
    if not Config.DATABASE_URL:
        return
    # Ensure persistent directories exist; do not delete user data on startup
    for p in ["thumbnails", "tokens", "rclone", "cookies", "attachments"]:
        if not await aiopath.exists(p):
            await makedirs(p, exist_ok=True)
    await database.connect()
    if database.db is not None:
        BOT_ID = Config.BOT_TOKEN.split(":", 1)[0]
        try:
            settings = import_module("config")
            config_file = {
                key: value.strip() if isinstance(value, str) else value
                for key, value in vars(settings).items()
                if not key.startswith("__")
            }
        except ModuleNotFoundError:
            config_file = {}
        config_file.update(
            {
                key: value.strip() if isinstance(value, str) else value
                for key, value in environ.items()
                if key in var_list
            }
        )

        old_config = await database.db.settings.deployConfig.find_one(
            {"_id": BOT_ID}, {"_id": 0}
        )
        if old_config is None:
            await database.db.settings.deployConfig.replace_one(
                {"_id": BOT_ID}, config_file, upsert=True
            )
        if old_config and old_config != config_file:
            LOGGER.info("Saving.. Deploy Config imported from Bot")
            await database.db.settings.deployConfig.replace_one(
                {"_id": BOT_ID}, config_file, upsert=True
            )
            config_dict = (
                await database.db.settings.config.find_one({"_id": BOT_ID}, {"_id": 0})
                or {}
            )
            config_dict.update(config_file)
            if config_dict:
                Config.load_dict(config_dict)
        else:
            LOGGER.info("Updating.. Saved Config imported from MongoDB")
            config_dict = await database.db.settings.config.find_one(
                {"_id": BOT_ID}, {"_id": 0}
            )
            if config_dict:
                Config.load_dict(config_dict)

        if pf_dict := await database.db.settings.files.find_one(
            {"_id": BOT_ID}, {"_id": 0}
        ):
            for key, value in pf_dict.items():
                if value:
                    file_ = key.replace("__", ".")
                    async with aiopen(file_, "wb+") as f:
                        await f.write(value)

        if a2c_options := await database.db.settings.aria2c.find_one(
            {"_id": BOT_ID}, {"_id": 0}
        ):
            aria2_options.update(a2c_options)

        if not Config.DISABLE_TORRENTS:
            if qbit_opt := await database.db.settings.qbittorrent.find_one(
                {"_id": BOT_ID}, {"_id": 0}
            ):
                qbit_options.update(qbit_opt)

        if nzb_opt := await database.db.settings.nzb.find_one(
            {"_id": BOT_ID}, {"_id": 0}
        ):
            if await aiopath.exists("sabnzbd/SABnzbd.ini.bak"):
                await remove("sabnzbd/SABnzbd.ini.bak")
            ((key, value),) = nzb_opt.items()
            file_ = key.replace("__", ".")
            async with aiopen(f"sabnzbd/{file_}", "wb+") as f:
                await f.write(value)

        if await database.db.users[BOT_ID].find_one():
            rows = database.db.users[BOT_ID].find({})
            async for row in rows:
                uid = row["_id"]
                del row["_id"]
                paths = {
                    "THUMBNAIL": f"thumbnails/{uid}.jpg",
                    "RCLONE_CONFIG": f"rclone/{uid}.conf",
                    "TOKEN_PICKLE": f"tokens/{uid}.pickle",
                    "USER_ATTACHMENT_PHOTO_TARGET_PATH": f"attachments/{uid}.jpg",
                    "YTDLP_COOKIES": f"cookies/{uid}/cookies.txt",
                }

                async def save_file(file_path, content):
                    dir_path = ospath.dirname(file_path)
                    if not await aiopath.exists(dir_path):
                        await makedirs(dir_path)
                    async with aiopen(file_path, "wb+") as f:
                        if isinstance(content, str):
                            content = content.encode("utf8")
                        await f.write(content)

                for key in [
                    "THUMBNAIL",
                    "RCLONE_CONFIG",
                    "TOKEN_PICKLE",
                    "YTDLP_COOKIES",
                ]:
                    path_template = paths.get(key)
                    if not path_template:
                        continue
                    # Prefer binary content from *_CONTENT if available
                    content = row.get(f"{key}_CONTENT") or row.get(key)
                    if content:
                        await save_file(path_template, content)
                        # Update stored path for runtime use
                        row[key] = path_template

                attachment_photo_binary = row.get("USER_ATTACHMENT_PHOTO_CONTENT")
                attachment_photo_target_path = paths.get(
                    "USER_ATTACHMENT_PHOTO_TARGET_PATH"
                )

                if attachment_photo_binary and attachment_photo_target_path:
                    try:
                        await save_file(
                            attachment_photo_target_path, attachment_photo_binary
                        )
                        # Store as absolute path to avoid path resolution issues
                        absolute_path = os.path.join(
                            os.getcwd(), attachment_photo_target_path
                        )
                        row["USER_ATTACHMENT_PHOTO"] = absolute_path
                    except Exception:
                        if "USER_ATTACHMENT_PHOTO" in row:
                            del row["USER_ATTACHMENT_PHOTO"]
                elif row.get("USER_ATTACHMENT_PHOTO"):
                    # Check if the stored path exists, if not try to resolve it
                    stored_path = str(row.get("USER_ATTACHMENT_PHOTO"))
                    if not await aiopath.exists(stored_path):
                        # Try to resolve relative path to absolute
                        if not os.path.isabs(stored_path):
                            absolute_path = os.path.join(os.getcwd(), stored_path)
                            if await aiopath.exists(absolute_path):
                                row["USER_ATTACHMENT_PHOTO"] = absolute_path
                            else:
                                row["USER_ATTACHMENT_PHOTO"] = None
                        else:
                            row["USER_ATTACHMENT_PHOTO"] = None

                user_data[uid] = row

        if await database.db.rss[BOT_ID].find_one():
            rows = database.db.rss[BOT_ID].find({})
            async for row in rows:
                user_id = row["_id"]
                del row["_id"]
                rss_dict[user_id] = row


async def save_settings():
    if database.db is None:
        return
    config_file = Config.get_all()
    await database.db.settings.config.update_one(
        {"_id": TgClient.ID}, {"$set": config_file}, upsert=True
    )
    if await database.db.settings.aria2c.find_one({"_id": TgClient.ID}) is None:
        await database.db.settings.aria2c.update_one(
            {"_id": TgClient.ID}, {"$set": aria2_options}, upsert=True
        )
    if await database.db.settings.qbittorrent.find_one({"_id": TgClient.ID}) is None:
        await database.save_qbit_settings()
    if await database.db.settings.nzb.find_one({"_id": TgClient.ID}) is None:
        async with aiopen("sabnzbd/SABnzbd.ini", "rb+") as pf:
            nzb_conf = await pf.read()
        await database.db.settings.nzb.update_one(
            {"_id": TgClient.ID}, {"$set": {"SABnzbd__ini": nzb_conf}}, upsert=True
        )


async def update_variables():
    # Set features based on premium status. This logic is now clearer.
    if TgClient.IS_PREMIUM_USER:
        Config.LEECH_SPLIT_SIZE = 4194304000  # 4GB for premium
        Config.HYBRID_LEECH = True
        Config.USER_TRANSMISSION = True
    else:
        Config.LEECH_SPLIT_SIZE = 2097152000  # 2GB for non-premium
        Config.HYBRID_LEECH = False
        Config.USER_TRANSMISSION = False

    if Config.AUTHORIZED_CHATS:
        # Remove all thread_ids logic for pyrogram compatibility
        for id_ in Config.AUTHORIZED_CHATS.split():
            chat_id = int(id_.strip())
            auth_chats[chat_id] = []

    if Config.SUDO_USERS:
        aid = Config.SUDO_USERS.split()
        for id_ in aid:
            sudo_users.append(int(id_.strip()))

    if Config.EXCLUDED_EXTENSIONS:
        fx = Config.EXCLUDED_EXTENSIONS.split()
        for x in fx:
            x = x.lstrip(".")
            excluded_extensions.append(x.strip().lower())

    if Config.GDRIVE_ID:
        drives_names.append("Main")
        drives_ids.append(Config.GDRIVE_ID)
        index_urls.append(Config.INDEX_URL)

    if not Config.IMDB_TEMPLATE:
        Config.IMDB_TEMPLATE = """
<b>Title: </b> {title} [{year}]
<b>Also Known As:</b> {aka}
<b>Rating ⭐️:</b> <i>{rating}</i>
<b>Release Info: </b> <a href="{url_releaseinfo}">{release_date}</a>
<b>Genre: </b>{genres}
<b>IMDb URL:</b> {url}
<b>Language: </b>{languages}
<b>Country of Origin : </b> {countries}

<b>Story Line: </b><code>{plot}</code>

<a href="{url_cast}">Read More ...</a>"""

    if await aiopath.exists("list_drives.txt"):
        async with aiopen("list_drives.txt", "r+") as f:
            lines = await f.readlines()
            for line in lines:
                temp = line.split()
                drives_ids.append(temp[1])
                drives_names.append(temp[0].replace("_", " "))
                if len(temp) > 2:
                    index_urls.append(temp[2])
                else:
                    index_urls.append("")

    if await aiopath.exists("shortener.txt"):
        async with aiopen("shortener.txt", "r+") as f:
            lines = await f.readlines()
            for line in lines:
                temp = line.strip().split()
                if len(temp) == 2:
                    shortener_dict[temp[0]] = temp[1]


async def load_configurations():
    if not await aiopath.exists(".netrc"):
        async with aiopen(".netrc", "w"):
            pass

    await (
        await create_subprocess_shell(
            f"chmod 600 .netrc && cp .netrc /root/.netrc && chmod +x setpkgs.sh && ./setpkgs.sh {BinConfig.ARIA2_NAME} {BinConfig.SABNZBD_NAME}"
        )
    ).wait()

    PORT = Config.BASE_URL_PORT if Config.VPS_DEPLOY else getenv("PORT", "")
    if PORT:
        await create_subprocess_shell(
            f"gunicorn -k uvicorn.workers.UvicornWorker -w 1 web.wserver:app --bind 0.0.0.0:{PORT}"
        )
        await create_subprocess_shell("python3 cron_boot.py")

    if await aiopath.exists("cfg.zip"):
        if await aiopath.exists("/JDownloader/cfg"):
            await rmtree("/JDownloader/cfg", ignore_errors=True)
        await (
            await create_subprocess_exec("7z", "x", "cfg.zip", "-o/JDownloader")
        ).wait()

    if await aiopath.exists("accounts.zip"):
        if await aiopath.exists("accounts"):
            await rmtree("accounts")
        await (
            await create_subprocess_exec(
                "7z", "x", "-o.", "-aoa", "accounts.zip", "accounts/*.json"
            )
        ).wait()
        await (await create_subprocess_exec("chmod", "-R", "777", "accounts")).wait()
        await remove("accounts.zip")

    if not await aiopath.exists("accounts"):
        Config.USE_SERVICE_ACCOUNTS = False

    await TorrentManager.initiate()

    if Config.DISABLE_TORRENTS:
        LOGGER.info("Torrents are disabled. Skipping qBittorrent initialization.")
    else:
        try:
            await TorrentManager.qbittorrent.app.set_preferences(qbit_options)
        except Exception as e:
            LOGGER.error(f"Failed to configure qBittorrent: {e}")

    # Configure defaults for stream utils and auto-start web server if configured
    try:
        # Defaults: use BASE_URL and BASE_URL_PORT when not provided; enable by default
        if not getattr(Config, "STREAM_BASE_URL", None):
            Config.STREAM_BASE_URL = Config.BASE_URL
        if Config.STREAM_BASE_URL and not Config.STREAM_BASE_URL.endswith("/"):
            Config.STREAM_BASE_URL = Config.STREAM_BASE_URL + "/"
        if not getattr(Config, "STREAM_PORT", None):
            Config.STREAM_PORT = Config.BASE_URL_PORT
        if not getattr(Config, "ENABLE_STREAM_LINK", None):
            Config.ENABLE_STREAM_LINK = True

        from ..helper.stream_utils.web_services import (
            start_server as start_stream_server,
        )

        # Avoid port conflict with the main web server; if same port, assume reverse-proxy will route
        if Config.ENABLE_STREAM_LINK and Config.STREAM_BASE_URL and Config.STREAM_PORT:
            if str(Config.STREAM_PORT) == str(Config.BASE_URL_PORT):
                LOGGER.info(
                    "Stream server not started to avoid port conflict (using BASE_URL port). Ensure reverse proxy routes /watch and /stream to stream app."
                )
            else:
                await start_stream_server()
                LOGGER.info(
                    f"Stream server started on port {Config.STREAM_PORT} with base URL {Config.STREAM_BASE_URL}"
                )
    except Exception as e:
        LOGGER.error(f"Failed to start stream server: {e}")
