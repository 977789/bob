from base64 import b64encode
from os import path as ospath
from time import time
from urllib.parse import urljoin, quote_plus

from aiofiles import open as aiopen
from aiohttp import ClientSession

from ... import bot_start_time, LOGGER
from ...core.config_manager import Config
from ..ext_utils.exceptions import InvalidHash, FIleNotFound
from ..ext_utils.links_utils import get_url_name, get_link
from ..ext_utils.status_utils import get_readable_file_size, get_readable_time
from ..ext_utils.tmdb_utils import fetch_tmdb_data
from .file_properties import get_file_ids


async def render_page(
    chat_id: int,
    message_id: int,
    secure_hash: str,
    is_home: bool = False,
    ddl: str = "",
    client=None,
):
    template_path = ospath.join("bot", "helper", "stream_utils", "template")
    if is_home:
        channel = Config.CHANNEL_USERNAME
        info = (
            f"<h1 style='text-align: center'><a href='https://t.me/{channel}'>@{channel}</a></h1><br>"
            f"<h2 style='text-align: center'>Up Time: {get_readable_time(time() - bot_start_time)}</h2>"
        )
        async with aiopen(ospath.join(template_path, "home.html"), "r") as f:
            html = (await f.read()).replace("<!-- Print -->", info)
    else:
        if ddl:
            file_data = type(
                "file_id",
                (object,),
                {"file_name": get_url_name(ddl), "mime_type": secure_hash or "video"},
            )
            src = get_link(text=ddl) or urljoin(Config.RCLONE_SERVE_URL, ddl)
        else:
            encoded = b64encode(
                f"{secure_hash}/{chat_id}/{message_id}".encode()
            ).decode("utf-8")
            try:
                file_data = await get_file_ids(chat_id, message_id, client=client)
                if file_data.unique_id[:6] != secure_hash:
                    LOGGER.info(
                        "Link hash: %s - %s", secure_hash, file_data.unique_id[:6]
                    )
                    LOGGER.info("Invalid hash for message with - ID %s", message_id)
                    raise InvalidHash
                # Use absolute root path to avoid relative resolution under /watch
                src = f"/dl/{quote_plus(getattr(file_data, 'file_name', file_data.unique_id))}?id={encoded}"
            except Exception:
                # Fallback when client is unavailable: still build a playable src
                src = f"/dl/None?id={encoded}"
                file_data = type(
                    "file_id",
                    (object,),
                    {
                        "mime_type": "video/mp4",
                        "file_name": "Media",
                        "unique_id": secure_hash,
                    },
                )

        filename = getattr(file_data, "file_name", "Media")
        match getattr(file_data, "mime_type", "video/mp4").split("/")[0].strip():
            case "video" as tag:
                async with aiopen(ospath.join(template_path, "req.html")) as r:
                    heading = f"Watch: {filename}"
                    # Replace upstream thumbnail util with our tmdb_utils
                    thumb = None
                    try:
                        data = await fetch_tmdb_data(
                            str(filename), image_type="backdrop"
                        )
                        thumb = data.get("image_url") if data else None
                    except Exception:
                        thumb = None
                    html = (await r.read()).replace("tag", tag) % (
                        heading,
                        filename,
                        src,
                        thumb,
                    )
            case "audio" as tag:
                async with aiopen(ospath.join(template_path, "req.html")) as r:
                    heading = f"Listen {filename}"
                    html = (await r.read()).replace("tag", tag) % (
                        heading,
                        filename,
                        src,
                    )
            case _:
                if ddl:
                    raise FIleNotFound
                async with (
                    aiopen(ospath.join(template_path, "dl.html")) as r,
                    ClientSession() as s,
                    s.get(src, ssl=False) as u,
                ):
                    heading = f"Download: {filename}"
                    file_size = get_readable_file_size(
                        int(u.headers.get("Content-Length"))
                    )
                    html = (await r.read()) % (heading, filename, src, file_size)
    return html
