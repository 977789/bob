import re
from shutil import disk_usage
from asyncio import gather, sleep, create_subprocess_exec
from asyncio.subprocess import PIPE
from contextlib import suppress
from os import path as ospath, walk
from re import sub
from secrets import token_hex
from shlex import split
from natsort import natsorted

import aiohttp
from aiofiles.os import listdir, makedirs, remove, path as aiopath
from aioshutil import move, rmtree
from pyrogram.enums import ChatAction

from .. import (
    DOWNLOAD_DIR,
    LOGGER,
    cpu_eater_lock,
    cpu_no,
    excluded_extensions,
    intervals,
    multi_tags,
    task_dict,
    task_dict_lock,
    user_data,
)

# Global storage for multi-download video tools selections
multi_video_tools_selection = {}

# Track multi-downloads waiting for video tools selection to complete
pending_multi_downloads = {}
from ..core.config_manager import Config, BinConfig
from ..core.tg_client import TgClient
from .ext_utils.bot_utils import get_size_bytes, new_task, sync_to_async, cmd_exec
from .ext_utils.bulk_links import extract_bulk_links
from .ext_utils.files_utils import (
    SevenZ,
    get_base_name,
    get_path_size,
    is_archive,
    is_archive_split,
    is_first_archive_split,
    split_file,
)
from .ext_utils.links_utils import (
    is_gdrive_id,
    is_gdrive_link,
    is_gofile_upload,
    is_rclone_path,
    is_telegram_link,
    is_mega_link,
    is_url,
)
from .ext_utils.media_utils import (
    FFMpeg,
    create_thumb,
    get_document_type,
    take_ss,
    get_ss_grid_pdf,
    get_media_info,
)
from .mirror_leech_utils.gdrive_utils.list import GoogleDriveList
from .mirror_leech_utils.rclone_utils.list import RcloneList
from .mirror_leech_utils.status_utils.ffmpeg_status import FFmpegStatus
from .mirror_leech_utils.status_utils.sevenz_status import SevenZStatus
from .telegram_helper.bot_commands import BotCommands
from .telegram_helper.message_utils import (
    get_tg_link_message,
    send_message,
    send_status_message,
)


async def download_image_from_url(url: str) -> str:
    """Download an image from a URL and save it to the thumbnails directory.

    Args:
        url: The URL of the image to download

    Returns:
        The path to the saved image file

    Raises:
        ValueError: If the URL is invalid or the image cannot be downloaded
    """
    # Check if URL is valid
    if not is_url(url):
        raise ValueError("Invalid URL provided")

    # Create thumbnails directory if it doesn't exist
    thumbnails_dir = f"{DOWNLOAD_DIR}thumbnails"
    if not await aiopath.exists(thumbnails_dir):
        await makedirs(thumbnails_dir, exist_ok=True)

    # Generate a unique filename for the thumbnail
    from time import time

    filename = f"thumb_{int(time())}.jpg"
    file_path = ospath.join(thumbnails_dir, filename)

    try:
        # Download the image
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status != 200:
                    raise ValueError(
                        f"Failed to download image: HTTP {response.status}"
                    )

                # Check if content type is an image
                content_type = response.headers.get("content-type", "").lower()
                if not content_type.startswith("image/"):
                    raise ValueError(f"URL does not point to an image: {content_type}")

                # Read and save the image
                image_data = await response.read()

                # Write the image to file
                with open(file_path, "wb") as f:
                    f.write(image_data)

                return file_path

    except Exception as e:
        # Clean up the file if it was created
        if await aiopath.exists(file_path):
            await remove(file_path)
        raise ValueError(f"Failed to download image from URL: {str(e)}")


class TaskConfig:
    def __init__(self):
        self.mid = self.message.id
        self.user = self.message.from_user or self.message.sender_chat
        self.user_id = self.user.id
        self.user_dict = user_data.get(self.user_id, {})
        self.dir = f"{DOWNLOAD_DIR}{self.mid}"
        self.up_dir = ""
        self.link = ""
        self.up_dest = ""
        self.rc_flags = ""
        self.tag = ""
        self.name = ""
        self.subname = ""
        self.name_swap = ""
        self.thumbnail_layout = ""
        self.folder_name = ""
        self.split_size = 0
        self.max_split_size = 0
        self.multi = 0
        self.size = 0
        self.subsize = 0
        self.proceed_count = 0
        self.is_leech = False
        self.is_yt = False
        self.is_qbit = False
        self.is_mega = False
        self.is_nzb = False
        self.is_jd = False
        self.is_clone = False
        self.is_gdrive = False
        self.is_rclone = False
        self.is_ytdlp = False
        self.equal_splits = False
        self.user_transmission = False
        self.hybrid_leech = False
        self.extract = False
        self.compress = False
        self.select = False
        self.seed = False
        self.join = False
        self.private_link = False
        self.stop_duplicate = False
        self.sample_video = False
        self.convert_audio = False
        self.convert_video = False
        self.screen_shots = False
        self.is_cancelled = False
        self.force_run = False
        self.force_download = False
        self.force_upload = False
        self.is_torrent = False
        self.as_med = False
        self.as_doc = False
        self.is_file = False
        self.bot_trans = False
        self.user_trans = False
        self.progress = True
        self.ffmpeg_cmds = None
        self.chat_thread_id = None
        self.subproc = None
        self.thumb = None
        self.excluded_extensions = []
        self.files_to_proceed = []
        self.is_super_chat = self.message.chat.type.name in ["SUPERGROUP", "CHANNEL"]
        self.source_url = None
        self.bot_pm = Config.BOT_PM or self.user_dict.get("BOT_PM")
        self.pm_msg = None
        self.file_details = {}
        self.mode = tuple()

    def _set_mode_engine(self):
        self.source_url = (
            self.link
            if len(self.link) > 0 and self.link.startswith("http")
            else (
                f"https://t.me/share/url?url={self.link}"
                if self.link
                else self.message.link
            )
        )

        out_mode = f"#{'Leech' if self.is_leech else 'Clone' if self.is_clone else 'RClone' if self.up_dest.startswith('mrcc:') or is_rclone_path(self.up_dest) else 'GDrive' if self.up_dest.startswith(('mtp:', 'tp:', 'sa:')) or is_gdrive_id(self.up_dest) else 'UpHosters'}"
        out_mode += " (Zip)" if self.compress else " (Unzip)" if self.extract else ""

        self.is_rclone = is_rclone_path(self.link)
        self.is_gdrive = is_gdrive_link(self.source_url) if self.source_url else False
        self.is_mega = is_mega_link(self.link) if self.source_url else False

        in_mode = f"#{'Mega' if self.is_mega else 'qBit' if self.is_qbit else 'SABnzbd' if self.is_nzb else 'JDown' if self.is_jd else 'RCloneDL' if self.is_rclone else 'ytdlp' if self.is_ytdlp else 'GDrive' if (self.is_clone or self.is_gdrive) else 'Aria2' if (self.source_url and self.source_url != self.message.link) else 'TgMedia'}"

        self.mode = (in_mode, out_mode)

    def get_token_path(self, dest):
        if dest.startswith("mtp:"):
            return f"tokens/{self.user_id}.pickle"
        elif (
            dest.startswith("sa:")
            or Config.USE_SERVICE_ACCOUNTS
            and not dest.startswith("tp:")
        ):
            return "accounts"
        else:
            return "token.pickle"

    def get_config_path(self, dest):
        return (
            f"rclone/{self.user_id}.conf" if dest.startswith("mrcc:") else "rclone.conf"
        )

    async def is_token_exists(self, path, status):
        if is_rclone_path(path):
            config_path = self.get_config_path(path)
            if config_path != "rclone.conf" and status == "up":
                self.private_link = True
            if not await aiopath.exists(config_path):
                raise ValueError(f"Rclone Config: {config_path} not Exists!")
        elif (
            status == "dl"
            and is_gdrive_link(path)
            or status == "up"
            and is_gdrive_id(path)
        ):
            token_path = self.get_token_path(path)
            if token_path.startswith("tokens/") and status == "up":
                self.private_link = True
            if not await aiopath.exists(token_path):
                raise ValueError(f"NO TOKEN! {token_path} not Exists!")

    async def before_start(self):
        self.name_swap = (
            self.name_swap
            or self.user_dict.get("NAME_SWAP", False)
            or (Config.NAME_SWAP if "NAME_SWAP" not in self.user_dict else "")
        )
        if self.name_swap:
            self.name_swap = [x.split(":") for x in self.name_swap.split("|")]
        self.excluded_extensions = self.user_dict.get("EXCLUDED_EXTENSIONS") or (
            excluded_extensions
            if "EXCLUDED_EXTENSIONS" not in self.user_dict
            else ["aria2", "!qB"]
        )
        if not self.rc_flags:
            if self.user_dict.get("RCLONE_FLAGS"):
                self.rc_flags = self.user_dict["RCLONE_FLAGS"]
            elif "RCLONE_FLAGS" not in self.user_dict and Config.RCLONE_FLAGS:
                self.rc_flags = Config.RCLONE_FLAGS
        if self.link not in ["rcl", "gdl"]:
            if not self.is_jd:
                if is_rclone_path(self.link):
                    if not self.link.startswith("mrcc:") and self.user_dict.get(
                        "USER_TOKENS", False
                    ):
                        self.link = f"mrcc:{self.link}"
                    await self.is_token_exists(self.link, "dl")
                elif is_gdrive_link(self.link):
                    if not self.link.startswith(
                        ("mtp:", "tp:", "sa:")
                    ) and self.user_dict.get("USER_TOKENS", False):
                        self.link = f"mtp:{self.link}"
                    await self.is_token_exists(self.link, "dl")
        elif self.link == "rcl":
            if not self.is_ytdlp and not self.is_jd:
                self.link = await RcloneList(self).get_rclone_path("rcd")
                if not is_rclone_path(self.link):
                    raise ValueError(self.link)
        elif self.link == "gdl":
            if not self.is_ytdlp and not self.is_jd:
                self.link = await GoogleDriveList(self).get_target_id("gdd")
                if not is_gdrive_id(self.link):
                    raise ValueError(self.link)

        self.user_transmission = TgClient.IS_PREMIUM_USER and (
            self.user_dict.get("USER_TRANSMISSION")
            or Config.USER_TRANSMISSION
            and "USER_TRANSMISSION" not in self.user_dict
        )

        if self.user_dict.get("UPLOAD_PATHS", False):
            if self.up_dest in self.user_dict["UPLOAD_PATHS"]:
                self.up_dest = self.user_dict["UPLOAD_PATHS"][self.up_dest]
        elif "UPLOAD_PATHS" not in self.user_dict and Config.UPLOAD_PATHS:
            if self.up_dest in Config.UPLOAD_PATHS:
                self.up_dest = Config.UPLOAD_PATHS[self.up_dest]

        if self.ffmpeg_cmds and not isinstance(self.ffmpeg_cmds, list):
            if self.user_dict.get("FFMPEG_CMDS", None):
                ffmpeg_dict = self.user_dict["FFMPEG_CMDS"]
                self.ffmpeg_cmds = [
                    value
                    for key in list(self.ffmpeg_cmds)
                    if key in ffmpeg_dict
                    for value in ffmpeg_dict[key]
                ]
            elif "FFMPEG_CMDS" not in self.user_dict and Config.FFMPEG_CMDS:
                ffmpeg_dict = Config.FFMPEG_CMDS
                self.ffmpeg_cmds = [
                    value
                    for key in list(self.ffmpeg_cmds)
                    if key in ffmpeg_dict
                    for value in ffmpeg_dict[key]
                ]
            else:
                self.ffmpeg_cmds = None

        if not self.is_leech:
            self.stop_duplicate = (
                self.user_dict.get("STOP_DUPLICATE")
                or "STOP_DUPLICATE" not in self.user_dict
                and Config.STOP_DUPLICATE
            )
            default_upload = (
                self.user_dict.get("DEFAULT_UPLOAD", "") or Config.DEFAULT_UPLOAD
            )
            if (not self.up_dest and default_upload == "rc") or self.up_dest == "rc":
                self.up_dest = self.user_dict.get("RCLONE_PATH") or Config.RCLONE_PATH
            elif (not self.up_dest and default_upload == "gd") or self.up_dest == "gd":
                self.up_dest = self.user_dict.get("GDRIVE_ID") or Config.GDRIVE_ID
            elif (not self.up_dest and default_upload == "gofile") or self.up_dest in [
                "gofile",
                "gf",
            ]:
                self.up_dest = "gofile"
            if not self.up_dest:
                raise ValueError("No Upload Destination!")
            if is_gdrive_id(self.up_dest):
                if not self.up_dest.startswith(
                    ("mtp:", "tp:", "sa:")
                ) and self.user_dict.get("USER_TOKENS", False):
                    self.up_dest = f"mtp:{self.up_dest}"
            elif is_rclone_path(self.up_dest):
                if not self.up_dest.startswith("mrcc:") and self.user_dict.get(
                    "USER_TOKENS", False
                ):
                    self.up_dest = f"mrcc:{self.up_dest}"
                self.up_dest = self.up_dest.strip("/")
            elif self.up_dest == "gofile":
                # Check if user has personal token or if global token is configured
                user_token = self.user_dict.get("GOFILE_TOKEN")
                if not user_token and not Config.GOFILE_API:
                    raise ValueError(
                        "GoFile API token not configured! Please set your GoFile token in user settings or configure a global token."
                    )
            else:
                raise ValueError("Wrong Upload Destination!")

            if self.up_dest not in ["rcl", "gdl", "gofile"]:
                await self.is_token_exists(self.up_dest, "up")

            if self.up_dest == "rcl":
                if self.is_clone:
                    if not is_rclone_path(self.link):
                        raise ValueError(
                            "You can't clone from different types of tools"
                        )
                    config_path = self.get_config_path(self.link)
                else:
                    config_path = None
                self.up_dest = await RcloneList(self).get_rclone_path(
                    "rcu", config_path
                )
                if not is_rclone_path(self.up_dest):
                    raise ValueError(self.up_dest)
            elif self.up_dest == "gdl":
                if self.is_clone:
                    if not is_gdrive_link(self.link):
                        raise ValueError(
                            "You can't clone from different types of tools"
                        )
                    token_path = self.get_token_path(self.link)
                else:
                    token_path = None
                self.up_dest = await GoogleDriveList(self).get_target_id(
                    "gdu", token_path
                )
                if not is_gdrive_id(self.up_dest):
                    raise ValueError(self.up_dest)
            elif self.is_clone:
                if is_gdrive_link(self.link) and self.get_token_path(
                    self.link
                ) != self.get_token_path(self.up_dest):
                    raise ValueError("You must use the same token to clone!")
                elif is_rclone_path(self.link) and self.get_config_path(
                    self.link
                ) != self.get_config_path(self.up_dest):
                    raise ValueError("You must use the same config to clone!")
        else:
            self.up_dest = (
                self.up_dest
                or self.user_dict.get("LEECH_DUMP_CHAT")
                or Config.LEECH_DUMP_CHAT
            )

            # Log premium user status
            LOGGER.info(f"TgClient.IS_PREMIUM_USER: {TgClient.IS_PREMIUM_USER}")
            LOGGER.info(f"Config.HYBRID_LEECH: {Config.HYBRID_LEECH}")
            LOGGER.info(f"User dict HYBRID_LEECH: {self.user_dict.get('HYBRID_LEECH')}")
            LOGGER.info(f"bot_trans flag: {self.bot_trans}")

            # Force premium user status if configured
            premium_user = TgClient.IS_PREMIUM_USER
            if not premium_user and Config.FORCE_PREMIUM_USER:
                LOGGER.warning("Forcing premium user status as per config")
                premium_user = True

            # Set hybrid_leech flag
            self.hybrid_leech = premium_user and (
                self.user_dict.get("HYBRID_LEECH")
                or (Config.HYBRID_LEECH and "HYBRID_LEECH" not in self.user_dict)
            )

            LOGGER.info(f"Final hybrid_leech setting: {self.hybrid_leech}")

            # Override with command-line flags if provided
            if hasattr(self, "cmd_hybrid_leech") and self.cmd_hybrid_leech is not None:
                old_value = self.hybrid_leech
                self.hybrid_leech = self.cmd_hybrid_leech
                LOGGER.info(
                    f"Hybrid leech overridden by command: {old_value} -> {self.hybrid_leech}"
                )

            if self.bot_trans:
                self.user_transmission = False
                self.hybrid_leech = False
                LOGGER.info(
                    "Bot transmission enabled: disabled user_transmission and hybrid_leech"
                )
            if self.up_dest:
                if not isinstance(self.up_dest, int):
                    if self.up_dest.startswith("b:"):
                        self.up_dest = self.up_dest.replace("b:", "", 1)
                        self.user_transmission = False
                        self.hybrid_leech = False
                    elif self.up_dest.startswith("u:"):
                        self.up_dest = self.up_dest.replace("u:", "", 1)
                        self.user_transmission = TgClient.IS_PREMIUM_USER
                    elif self.up_dest.startswith("h:"):
                        self.up_dest = self.up_dest.replace("h:", "", 1)
                        self.user_transmission = TgClient.IS_PREMIUM_USER
                        self.hybrid_leech = self.user_transmission
                    if "|" in self.up_dest:
                        self.up_dest, self.chat_thread_id = list(
                            map(
                                lambda x: int(x) if x.lstrip("-").isdigit() else x,
                                self.up_dest.split("|", 1),
                            )
                        )
                    elif self.up_dest.lstrip("-").isdigit():
                        self.up_dest = int(self.up_dest)
                    elif self.up_dest.lower() == "pm":
                        self.up_dest = self.user_id

                if self.user_transmission:
                    try:
                        chat = await TgClient.user.get_chat(self.up_dest)
                    except Exception:
                        chat = None
                    if chat is None:
                        self.user_transmission = False
                        self.hybrid_leech = False
                    else:
                        uploader_id = TgClient.user.me.id
                        if chat.type.name not in ["SUPERGROUP", "CHANNEL", "GROUP"]:
                            self.user_transmission = False
                            self.hybrid_leech = False
                        else:
                            member = await chat.get_member(uploader_id)
                            if (
                                not member.privileges.can_manage_chat
                                or not member.privileges.can_delete_messages
                            ):
                                self.user_transmission = False
                                self.hybrid_leech = False

                if not self.user_transmission or self.hybrid_leech:
                    try:
                        chat = await self.client.get_chat(self.up_dest)
                    except Exception:
                        chat = None
                    if chat is None:
                        if self.user_transmission:
                            self.hybrid_leech = False
                        else:
                            raise ValueError("Chat not found!")
                    else:
                        uploader_id = self.client.me.id
                        if chat.type.name in ["SUPERGROUP", "CHANNEL", "GROUP"]:
                            member = await chat.get_member(uploader_id)
                            if (
                                not member.privileges.can_manage_chat
                                or not member.privileges.can_delete_messages
                            ):
                                if not self.user_transmission:
                                    raise ValueError(
                                        "You don't have enough privileges in this chat!"
                                    )
                                else:
                                    self.hybrid_leech = False
                        else:
                            try:
                                await self.client.send_chat_action(
                                    self.up_dest, ChatAction.TYPING
                                )
                            except Exception:
                                raise ValueError("Start the bot and try again!")
            elif (
                self.user_transmission or self.hybrid_leech
            ) and not self.is_super_chat:
                # REMOVED: Don't disable hybrid_leech if not in super chat
                # This was causing the issue with premium uploads
                LOGGER.info(
                    f"Not in super chat but keeping hybrid_leech: {self.hybrid_leech}"
                )
                # self.user_transmission = False
                # self.hybrid_leech = False
            # Add extensive logging for split size calculation
            LOGGER.info(f"Initial split_size (raw): {self.split_size}")
            LOGGER.info(
                f"User transmission: {self.user_transmission}, Hybrid leech: {self.hybrid_leech}"
            )
            LOGGER.info(f"TgClient.IS_PREMIUM_USER: {TgClient.IS_PREMIUM_USER}")
            LOGGER.info(f"TgClient.MAX_SPLIT_SIZE: {TgClient.MAX_SPLIT_SIZE}")

            # Parse command-provided split size if present
            if self.split_size:
                if isinstance(self.split_size, int):
                    pass
                elif isinstance(self.split_size, str):
                    if self.split_size.isdigit():
                        self.split_size = int(self.split_size)
                    else:
                        self.split_size = get_size_bytes(self.split_size)
                else:
                    # Fallback: ignore unknown type
                    self.split_size = 0

            # Determine desired split size (command > user setting > config)
            desired_split = (
                self.split_size
                or self.user_dict.get("LEECH_SPLIT_SIZE")
                or Config.LEECH_SPLIT_SIZE
                or 0
            )

            # Set max split size based on client capability (2GB normal, 4GB premium)
            self.max_split_size = TgClient.MAX_SPLIT_SIZE

            # If nothing specified (0/None), default to the max allowed for this client
            if not desired_split or desired_split <= 0:
                desired_split = self.max_split_size

            # Clamp desired split to the maximum supported by client
            self.split_size = min(int(desired_split), int(self.max_split_size))

            # Equal split preference
            self.equal_splits = (
                self.user_dict.get("EQUAL_SPLITS")
                or Config.EQUAL_SPLITS
                and "EQUAL_SPLITS" not in self.user_dict
            )

            LOGGER.info(
                f"Resolved split_size: {self.split_size} bytes, max_split_size: {self.max_split_size} bytes"
            )

            if not self.as_doc:
                self.as_doc = (
                    not self.as_med
                    if self.as_med
                    else (
                        self.user_dict.get("AS_DOCUMENT", False)
                        or Config.AS_DOCUMENT
                        and "AS_DOCUMENT" not in self.user_dict
                    )
                )

            self.thumbnail_layout = (
                self.thumbnail_layout
                or self.user_dict.get("THUMBNAIL_LAYOUT", False)
                or (
                    Config.THUMBNAIL_LAYOUT
                    if "THUMBNAIL_LAYOUT" not in self.user_dict
                    else ""
                )
            )

            if self.thumb != "none":
                if is_telegram_link(self.thumb):
                    # Handle Telegram links (existing logic)
                    msg = (await get_tg_link_message(self.thumb))[0]
                    self.thumb = (
                        await create_thumb(msg) if msg.photo or msg.document else ""
                    )
                elif is_url(self.thumb):
                    # Handle direct image URLs (new logic)
                    try:
                        # Check if URL looks like an image (basic check)
                        url_lower = self.thumb.lower()
                        if (
                            any(
                                url_lower.endswith(ext)
                                for ext in [
                                    ".jpg",
                                    ".jpeg",
                                    ".png",
                                    ".gif",
                                    ".bmp",
                                    ".webp",
                                ]
                            )
                            or "image" in url_lower
                        ):
                            self.thumb = await download_image_from_url(self.thumb)
                            LOGGER.info(f"Downloaded thumbnail from URL: {self.thumb}")
                        else:
                            # Still try to download even if extension is not obvious
                            self.thumb = await download_image_from_url(self.thumb)
                            LOGGER.info(f"Downloaded thumbnail from URL: {self.thumb}")
                    except Exception as e:
                        LOGGER.error(
                            f"Failed to download thumbnail from URL {self.thumb}: {str(e)}"
                        )
                        self.thumb = ""

    async def get_tag(self, text: list):
        if len(text) > 1 and text[1].startswith("Tag: "):
            user_info = text[1].split("Tag: ")
            if len(user_info) >= 3:
                id_ = user_info[-1]
                self.tag = " ".join(user_info[:-1])
            else:
                self.tag, id_ = text[1].split("Tag: ")[1].split()
            self.user = self.message.from_user = await self.client.get_users(id_)
            self.user_id = self.user.id
            self.user_dict = user_data.get(self.user_id, {})
            with suppress(Exception):
                await self.message.unpin()
        if self.user:
            if username := self.user.username:
                self.tag = f"@{username}"
            elif hasattr(self.user, "mention"):
                self.tag = self.user.mention
            else:
                self.tag = self.user.title

    @new_task
    async def run_multi(self, input_list, obj):
        await sleep(7)
        LOGGER.info(f"[DEBUG-VT] 🚀 Starting run_multi with input_list: {input_list}")
        LOGGER.info(
            f"[DEBUG-VT] 📊 Multi count: {self.multi}, Current multi_tag: {self.multi_tag}"
        )

        # Check if this is a subsequent file in a multi-download that uses -ft flag
        is_ft_enabled = (
            "-ft" in " ".join(input_list)
            if isinstance(input_list, list)
            else "-ft" in str(input_list)
        )

        if not self.multi_tag and self.multi > 1:
            self.multi_tag = token_hex(3)
            multi_tags.add(self.multi_tag)
            LOGGER.info(
                f"[DEBUG-VT] 🏷️ Generated new multi-tag: {self.multi_tag} for {self.multi} files"
            )

            # If this multi-download uses -ft flag, mark it as pending video tools selection
            if is_ft_enabled:
                pending_multi_downloads[self.multi_tag] = {
                    "waiting_for_selection": True,
                    "queued_messages": [],
                }
                LOGGER.info(
                    f"[DEBUG-VT] 📋 Multi-download {self.multi_tag} marked as pending video tools selection"
                )

            # Check if there's a temp selection to transfer
            temp_keys_to_remove = []
            for key in list(multi_video_tools_selection.keys()):
                if key.startswith(f"temp_{self.user.id}_"):
                    # Transfer temp selection to real multi_tag
                    multi_video_tools_selection[self.multi_tag] = (
                        multi_video_tools_selection[key]
                    )
                    temp_keys_to_remove.append(key)
                    LOGGER.info(
                        f"[DEBUG-VT] 🔄 Transferred temp selection {key} to multi-tag {self.multi_tag}: {multi_video_tools_selection[self.multi_tag]}"
                    )

                    # Since we have a selection, no need to wait
                    if self.multi_tag in pending_multi_downloads:
                        pending_multi_downloads[self.multi_tag][
                            "waiting_for_selection"
                        ] = False
                        LOGGER.info(
                            f"[DEBUG-VT] ✅ Multi-download {self.multi_tag} no longer waiting - selection transferred"
                        )

            # Clean up temp keys
            for temp_key in temp_keys_to_remove:
                del multi_video_tools_selection[temp_key]

        elif self.multi <= 1:
            if self.multi_tag in multi_tags:
                multi_tags.discard(self.multi_tag)
                # Note: Video tools selection cleanup is now handled after upload completion
                # Clean up pending status
                if self.multi_tag in pending_multi_downloads:
                    del pending_multi_downloads[self.multi_tag]
                    LOGGER.info(
                        f"[DEBUG-VT] 🧹 Cleaned up pending status for completed multi-download: {self.multi_tag}"
                    )
            return

        if self.multi_tag and self.multi_tag not in multi_tags:
            await send_message(
                self.message, f"{self.tag} Multi Task has been cancelled!"
            )
            await send_status_message(self.message)
            async with task_dict_lock:
                for fd_name in self.same_dir:
                    self.same_dir[fd_name]["total"] -= self.multi
            return

        # Check if this multi-download is waiting for video tools selection
        if (
            self.multi_tag in pending_multi_downloads
            and pending_multi_downloads[self.multi_tag]["waiting_for_selection"]
        ):
            # This is a subsequent file - queue it and wait
            LOGGER.info(
                f"[DEBUG-VT] ⏳ Multi-download {self.multi_tag} is waiting for video tools selection - queuing file {self.multi}"
            )

            # Store the message info to process later
            pending_multi_downloads[self.multi_tag]["queued_messages"].append(
                {"input_list": input_list, "obj": obj, "task_config": self}
            )

            # Don't proceed with this file yet
            return
        if len(self.bulk) != 0:
            msg = input_list[:1]
            options = self.options
            # Remove -ft flag from subsequent multi-downloads if video tools selection is already done
            if (
                self.multi_tag
                and self.multi_tag in multi_video_tools_selection
                and "-ft" in options
            ):
                # Use regex to properly remove -ft and clean up extra spaces
                import re

                original_options = options
                options = re.sub(r"\s*-ft\s*", " ", options).strip()
                LOGGER.info(
                    f"[DEBUG-VT] 🔧 Removed -ft flag for subsequent multi-download {self.multi_tag}: '{original_options}' -> '{options}'"
                )
            msg.append(f"{self.bulk[0]} -i {self.multi - 1} {options}")
            msgts = " ".join(msg)
            if self.multi > 2:
                msgts += f"\n• <b>Cancel Multi:</b> <i>/{BotCommands.CancelTaskCommand[1]}_{self.multi_tag}</i>"
            nextmsg = await send_message(self.message, msgts)
        else:
            msg = [s.strip() for s in input_list]
            LOGGER.info(
                f"[DEBUG-VT] 📝 Processing non-bulk multi-download. Original msg: {msg}"
            )
            index = msg.index("-i")
            msg[index + 1] = f"{self.multi - 1}"
            LOGGER.info(f"[DEBUG-VT] 🔢 Updated multi count. New msg: {msg}")

            # Remove -ft flag from subsequent multi-downloads if video tools selection is already done
            if (
                self.multi_tag
                and self.multi_tag in multi_video_tools_selection
                and "-ft" in msg
            ):
                original_msg = msg.copy()
                msg = [arg for arg in msg if arg != "-ft"]
                LOGGER.info(
                    f"[DEBUG-VT] 🔧 Removed -ft flag from subsequent multi-download {self.multi_tag}: {original_msg} -> {msg}"
                )
            else:
                LOGGER.info(
                    f"[DEBUG-VT] ⚠️ Not removing -ft flag. Multi-tag: {self.multi_tag}, Has selection: {self.multi_tag in multi_video_tools_selection if self.multi_tag else False}, Has -ft: {'-ft' in msg}"
                )

            nextmsg = await self.client.get_messages(
                chat_id=self.message.chat.id,
                message_ids=self.message.reply_to_message_id + 1,
            )
            msgts = " ".join(msg)
            if self.multi > 2:
                msgts += f"\n• <b>Cancel Multi:</b> <i>/{BotCommands.CancelTaskCommand[1]}_{self.multi_tag}</i>"
            nextmsg = await send_message(nextmsg, msgts)
        nextmsg = await self.client.get_messages(
            chat_id=self.message.chat.id, message_ids=nextmsg.id
        )
        if self.message.from_user:
            nextmsg.from_user = self.user
        else:
            nextmsg.sender_chat = self.user
        if intervals["stopAll"]:
            return
        await obj(
            self.client,
            nextmsg,
            self.is_qbit,
            self.is_leech,
            self.is_jd,
            self.is_nzb,
            self.same_dir,
            self.bulk,
            self.multi_tag,
            self.options,
        ).new_event()

    async def init_bulk(self, input_list, bulk_start, bulk_end, obj):
        if Config.DISABLE_BULK:
            await send_message(self.message, "Bulk downloads are currently disabled.")
            return
        try:
            self.bulk = await extract_bulk_links(self.message, bulk_start, bulk_end)
            if len(self.bulk) == 0:
                raise ValueError("Bulk Empty!")
            b_msg = input_list[:1]
            self.options = input_list[1:]
            index = self.options.index("-b")
            del self.options[index]
            if bulk_start or bulk_end:
                del self.options[index + 1]
            self.options = " ".join(self.options)
            b_msg.append(f"{self.bulk[0]} -i {len(self.bulk)} {self.options}")
            msg = " ".join(b_msg)
            if len(self.bulk) > 2:
                self.multi_tag = token_hex(3)
                multi_tags.add(self.multi_tag)
                msg += f"\n• <b>Cancel Multi:</b> <i>/{BotCommands.CancelTaskCommand[1]}_{self.multi_tag}</i>"
            nextmsg = await send_message(self.message, msg)
            nextmsg = await self.client.get_messages(
                chat_id=self.message.chat.id, message_ids=nextmsg.id
            )
            if self.message.from_user:
                nextmsg.from_user = self.user
            else:
                nextmsg.sender_chat = self.user
            await obj(
                self.client,
                nextmsg,
                self.is_qbit,
                self.is_leech,
                self.is_jd,
                self.is_nzb,
                self.same_dir,
                self.bulk,
                self.multi_tag,
                self.options,
            ).new_event()
        except Exception:
            await send_message(
                self.message,
                "Reply to text file or to telegram message that have links seperated by new line!",
            )

    async def proceed_extract(self, dl_path, gid):
        # Extraction queue control (memory intensive step)
        from .ext_utils.task_manager import (
            check_extraction_tasks,
            finish_extraction_task,
        )
        from .. import (
            task_dict,
            task_dict_lock,
        )  # local import to avoid circular issues
        from .mirror_leech_utils.status_utils.queue_status import ExtractionQueueStatus

        queued = False
        event = None
        try:
            over, event = await check_extraction_tasks(self)
            if over:
                queued = True
                async with task_dict_lock:
                    task_dict[self.mid] = ExtractionQueueStatus(self, gid)
                if event:
                    await event.wait()
                if self.is_cancelled:
                    return dl_path
        except Exception as e:
            LOGGER.error(
                f"Extraction queue setup failed, proceeding without queue control: {e}"
            )

        pswd = self.extract if isinstance(self.extract, str) else ""
        self.files_to_proceed = []
        if self.is_file and is_archive(dl_path):
            self.files_to_proceed.append(dl_path)
        else:
            for dirpath, _, files in await sync_to_async(walk, dl_path, topdown=False):
                for file_ in files:
                    if (
                        is_first_archive_split(file_)
                        or is_archive(file_)
                        and not file_.strip().lower().endswith(".rar")
                    ):
                        f_path = ospath.join(dirpath, file_)
                        self.files_to_proceed.append(f_path)

        if not self.files_to_proceed:
            return dl_path
        sevenz = SevenZ(self)
        LOGGER.info(f"Extracting: {self.name}")
        async with task_dict_lock:
            task_dict[self.mid] = SevenZStatus(self, sevenz, gid, "Extract")
        for dirpath, _, files in await sync_to_async(
            walk, self.up_dir or self.dir, topdown=False
        ):
            code = 0
            for file_ in files:
                if self.is_cancelled:
                    return False
                if (
                    is_first_archive_split(file_)
                    or is_archive(file_)
                    and not file_.strip().lower().endswith(".rar")
                ):
                    self.proceed_count += 1
                    f_path = ospath.join(dirpath, file_)
                    t_path = get_base_name(f_path) if self.is_file else dirpath
                    if not self.is_file:
                        self.subname = file_
                    code = await sevenz.extract(f_path, t_path, pswd)
            if self.is_cancelled:
                return code
            if code == 0:
                for file_ in files:
                    if is_archive_split(file_) or is_archive(file_):
                        del_path = ospath.join(dirpath, file_)
                        try:
                            await remove(del_path)
                        except Exception:
                            self.is_cancelled = True
        # Mark extraction task finished
        try:
            await finish_extraction_task(self.mid)
        except Exception as e:
            LOGGER.error(f"Failed finishing extraction queue state: {e}")
        return t_path if self.is_file and code == 0 else dl_path

    async def proceed_ffmpeg(self, dl_path, gid):
        checked = False
        cmds = [
            [part.strip() for part in split(item) if part.strip()]
            for item in self.ffmpeg_cmds
        ]
        try:
            ffmpeg = FFMpeg(self)
            for ffmpeg_cmd in cmds:
                self.proceed_count = 0
                cmd = [
                    BinConfig.FFMPEG_NAME,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-progress",
                    "pipe:1",
                ] + ffmpeg_cmd
                if "-del" in cmd:
                    cmd.remove("-del")
                    delete_files = True
                else:
                    delete_files = False
                index = cmd.index("-i")
                input_file = cmd[index + 1]
                if input_file.strip().endswith(".video"):
                    ext = "video"
                elif input_file.strip().endswith(".audio"):
                    ext = "audio"
                elif "." not in input_file:
                    ext = "all"
                else:
                    ext = ospath.splitext(input_file)[-1].lower()
                if await aiopath.isfile(dl_path):
                    is_video, is_audio, _ = await get_document_type(dl_path)
                    if not is_video and not is_audio:
                        break
                    elif is_video and ext == "audio":
                        break
                    elif is_audio and not is_video and ext == "video":
                        break
                    elif ext not in [
                        "all",
                        "audio",
                        "video",
                    ] and not dl_path.strip().lower().endswith(ext):
                        break
                    new_folder = ospath.splitext(dl_path)[0]
                    name = ospath.basename(dl_path)
                    await makedirs(new_folder, exist_ok=True)
                    file_path = f"{new_folder}/{name}"
                    await move(dl_path, file_path)
                    if not checked:
                        checked = True
                        async with task_dict_lock:
                            task_dict[self.mid] = FFmpegStatus(
                                self, ffmpeg, gid, "FFmpeg"
                            )
                        self.progress = False
                        await cpu_eater_lock.acquire()
                        self.progress = True
                    LOGGER.info(f"Running ffmpeg cmd for: {file_path}")
                    cmd[index + 1] = file_path
                    self.subsize = self.size
                    res = await ffmpeg.ffmpeg_cmds(cmd, file_path)
                    if res:
                        if delete_files:
                            await remove(file_path)
                            if len(await listdir(new_folder)) == 1:
                                folder = new_folder.rsplit("/", 1)[0]
                                self.name = ospath.basename(res[0])
                                if self.name.startswith("ffmpeg"):
                                    self.name = self.name.split(".", 1)[-1]
                                dl_path = ospath.join(folder, self.name)
                                await move(res[0], dl_path)
                                await rmtree(new_folder)
                            else:
                                dl_path = new_folder
                                self.name = new_folder.rsplit("/", 1)[-1]
                        else:
                            dl_path = new_folder
                            self.name = new_folder.rsplit("/", 1)[-1]
                    else:
                        await move(file_path, dl_path)
                        await rmtree(new_folder)
                else:
                    for dirpath, _, files in await sync_to_async(
                        walk, dl_path, topdown=False
                    ):
                        for file_ in files:
                            var_cmd = cmd.copy()
                            if self.is_cancelled:
                                return False
                            f_path = ospath.join(dirpath, file_)
                            is_video, is_audio, _ = await get_document_type(f_path)
                            if not is_video and not is_audio:
                                continue
                            elif is_video and ext == "audio":
                                continue
                            elif is_audio and not is_video and ext == "video":
                                continue
                            elif ext not in [
                                "all",
                                "audio",
                                "video",
                            ] and not f_path.strip().lower().endswith(ext):
                                continue
                            self.proceed_count += 1
                            var_cmd[index + 1] = f_path
                            if not checked:
                                checked = True
                                async with task_dict_lock:
                                    task_dict[self.mid] = FFmpegStatus(
                                        self, ffmpeg, gid, "FFmpeg"
                                    )
                                self.progress = False
                                await cpu_eater_lock.acquire()
                                self.progress = True
                            LOGGER.info(f"Running ffmpeg cmd for: {f_path}")
                            self.subsize = await get_path_size(f_path)
                            self.subname = file_
                            res = await ffmpeg.ffmpeg_cmds(var_cmd, f_path)
                            if res and delete_files:
                                await remove(f_path)
                                if len(res) == 1:
                                    file_name = ospath.basename(res[0])
                                    if file_name.startswith("ffmpeg"):
                                        newname = file_name.split(".", 1)[-1]
                                        newres = ospath.join(dirpath, newname)
                                        await move(res[0], newres)
        finally:
            if checked:
                cpu_eater_lock.release()
        return dl_path

    async def substitute(self, dl_path):
        def perform_swap(name, swaps):
            name, ext = ospath.splitext(name)
            name = sub(r"www\S+", "", name)
            for swap in swaps:
                pattern, res, cnt, sen = (
                    swap + ["", "0", "NOFLAG"][min(len(swap) - 1, 2) :]
                )[0:4]
                cnt = 0 if len(cnt) == 0 else int(cnt)
                try:
                    name = sub(
                        rf"{pattern}", res, name, cnt, flags=getattr(re, sen.upper(), 0)
                    )
                except Exception as e:
                    LOGGER.error(
                        f"Swap Error: pattern: {pattern} res: {res}. Error: {e}"
                    )
                    return False
                if len(name.encode()) > 255:
                    LOGGER.error(f"Substitute: {name} is too long")
                    return False
            return name + ext

        if self.is_file:
            up_dir, name = dl_path.rsplit("/", 1)
            new_name = perform_swap(name, self.name_swap)
            if not new_name:
                return dl_path
            new_path = ospath.join(up_dir, new_name)
            await move(dl_path, new_path)
            return new_path
        else:
            for dirpath, _, files in await sync_to_async(walk, dl_path, topdown=False):
                for file_ in files:
                    f_path = ospath.join(dirpath, file_)
                    new_name = perform_swap(file_, self.name_swap)
                    if not new_name:
                        continue
                    await move(f_path, ospath.join(dirpath, new_name))
            return dl_path

    async def remove_filename_patterns(self, dl_path):
        """Apply filename pattern removal to all files in a directory or single file"""
        # Import here to avoid circular imports
        from .ext_utils.filename_utils import apply_filename_patterns_to_path

        # Check if we have patterns to remove
        command_patterns = getattr(self, "remname_patterns", "")
        user_patterns = self.user_dict.get("FILENAME_REMOVE_PATTERNS", "")

        LOGGER.info(
            f"Filename pattern removal check - Command patterns: '{command_patterns}', User patterns: '{user_patterns}'"
        )

        if not command_patterns and not user_patterns:
            LOGGER.info("No filename patterns to remove, skipping pattern removal")
            return dl_path

        LOGGER.info(f"Applying filename pattern removal to: {dl_path}")
        result = await apply_filename_patterns_to_path(
            dl_path, command_patterns, self.user_dict
        )
        if result != dl_path:
            LOGGER.info(
                f"Filename pattern removal completed: '{dl_path}' -> '{result}'"
            )
        return result

    async def generate_screenshots(self, dl_path):
        LOGGER.info(f"Screenshot generation requested for: {dl_path}")
        ss_nb = int(self.screen_shots) if isinstance(self.screen_shots, str) else 10
        LOGGER.info(f"Screenshot count: {ss_nb}")

        # Make sure user_dict is properly initialized
        if not hasattr(self, "user_dict") or not isinstance(self.user_dict, dict):
            LOGGER.warning("User dict is not properly initialized, creating empty dict")
            self.user_dict = {}

        # Check if SS Grid feature is enabled for this task
        # First check command line parameters, then fall back to user settings
        cmd_ss_grid = getattr(self, "ss_grid", False)
        user_ss_grid = self.user_dict.get("SS_GRID_ENABLED", False)
        ss_grid_enabled = cmd_ss_grid or user_ss_grid

        LOGGER.info(f"SS Grid enabled check - Final: {ss_grid_enabled}")
        LOGGER.info(
            f"SS Grid settings - Command line: {cmd_ss_grid}, User settings: {user_ss_grid}"
        )
        LOGGER.info(f"User dict contents: {self.user_dict}")

        # Check if screen_shots is a parameter from command line and SS Grid is not enabled from command line
        # If so, we shouldn't use SS Grid even if user settings have it enabled
        if isinstance(self.screen_shots, str) and not cmd_ss_grid:
            LOGGER.info(
                f"Screenshots requested with -ss parameter but -ssg not specified, disabling SS Grid"
            )
            ss_grid_enabled = False

        if ss_grid_enabled:
            # Get SS Grid settings from command line or user dict
            ss_grid_count = 0
            if hasattr(self, "ss_grid_count") and self.ss_grid_count > 0:
                ss_grid_count = self.ss_grid_count
            else:
                # Check both SS_GRID_COUNT and SS_GRID_SCREENSHOTS (for backward compatibility)
                ss_grid_count = int(
                    getattr(self, "user_dict", {}).get(
                        "SS_GRID_COUNT",
                        getattr(self, "user_dict", {}).get("SS_GRID_SCREENSHOTS", 9),
                    )
                )
                ss_grid_layout = ""
            if hasattr(self, "ss_grid_layout") and self.ss_grid_layout:
                ss_grid_layout = self.ss_grid_layout
            else:
                ss_grid_layout = getattr(self, "user_dict", {}).get(
                    "SS_GRID_LAYOUT", "3x3"
                )

            # Check both "ss_grid_pdf" (from command line) and "SS_GRID_PDF_MODE" (from user settings)
            ss_grid_pdf_mode = getattr(self, "ss_grid_pdf", False) or getattr(
                self, "user_dict", {}
            ).get("SS_GRID_PDF_MODE", False)

            ss_grid_watermark = ""
            if hasattr(self, "ss_grid_watermark") and self.ss_grid_watermark:
                ss_grid_watermark = self.ss_grid_watermark
            else:
                ss_grid_watermark = getattr(self, "user_dict", {}).get(
                    "SS_GRID_WATERMARK", ""
                )
            LOGGER.info(
                f"Final SS Grid parameters - Count: {ss_grid_count}, Layout: {ss_grid_layout}, PDF Mode: {ss_grid_pdf_mode}, Watermark: {repr(ss_grid_watermark)}"
            )
            # Make sure required packages are available
            try:
                from PIL import Image
                from reportlab.lib.pagesizes import A4
                from reportlab.pdfgen import canvas

                LOGGER.info("Required libraries for SS Grid are available")
            except ImportError as e:
                LOGGER.error(f"Missing required packages for SS Grid: {str(e)}")
                LOGGER.info("Falling back to regular screenshots")
                return await take_ss(dl_path, ss_nb)

            # Get individual pages setting
            ss_grid_pdf_individual = self.user_dict.get(
                "SS_GRID_PDF_INDIVIDUAL_PAGES", True
            )
            LOGGER.info(f"PDF Individual Pages: {ss_grid_pdf_individual}")

            if self.is_file:
                if (await get_document_type(dl_path))[0]:
                    LOGGER.info(f"Creating SS Grid for: {dl_path}")
                    ss_output = await get_ss_grid_pdf(
                        dl_path,
                        ss_grid_layout,
                        ss_grid_count,
                        ss_grid_pdf_mode,
                        ss_grid_watermark,
                        ss_grid_pdf_individual,
                    )
                    if ss_output:
                        # Get the extension (jpg or pdf)
                        ext = ospath.splitext(ss_output)[1]
                        output_name = ospath.splitext(dl_path)[0] + f"_ss_grid{ext}"
                        await move(ss_output, output_name)
                        return output_name
            else:
                LOGGER.info(f"Creating SS Grids for directory: {dl_path}")
                for dirpath, _, files in await sync_to_async(
                    walk, dl_path, topdown=False
                ):
                    for file_ in files:
                        f_path = ospath.join(dirpath, file_)
                        if (await get_document_type(f_path))[0]:
                            LOGGER.info(f"Creating SS Grid for: {f_path}")
                            ss_output = await get_ss_grid_pdf(
                                f_path,
                                ss_grid_layout,
                                ss_grid_count,
                                ss_grid_pdf_mode,
                                ss_grid_watermark,
                                ss_grid_pdf_individual,
                            )
                            if ss_output:
                                # Get the extension (jpg or pdf)
                                ext = ospath.splitext(ss_output)[1]
                                output_name = (
                                    ospath.splitext(file_)[0] + f"_ss_grid{ext}"
                                )
                                await move(ss_output, ospath.join(dirpath, output_name))
                return dl_path
        else:
            # Original screenshot functionality
            if self.is_file:
                if (await get_document_type(dl_path))[0]:
                    LOGGER.info(f"Creating Screenshot for: {dl_path}")
                    res = await take_ss(dl_path, ss_nb)
                    if res:
                        new_folder = ospath.splitext(dl_path)[0]
                        name = ospath.basename(dl_path)
                        await makedirs(new_folder, exist_ok=True)
                        await gather(
                            move(dl_path, f"{new_folder}/{name}"),
                            move(res, new_folder),
                        )
                        return new_folder
            else:
                LOGGER.info(f"Creating Screenshot for: {dl_path}")
                for dirpath, _, files in await sync_to_async(
                    walk, dl_path, topdown=False
                ):
                    for file_ in files:
                        f_path = ospath.join(dirpath, file_)
                        if (await get_document_type(f_path))[0]:
                            await take_ss(f_path, ss_nb)
        return dl_path

    async def convert_media(self, dl_path, gid):
        fvext = []
        if self.convert_video:
            vdata = self.convert_video.split()
            vext = vdata[0].lower()
            if len(vdata) > 2:
                if "+" in vdata[1].split():
                    vstatus = "+"
                elif "-" in vdata[1].split():
                    vstatus = "-"
                else:
                    vstatus = ""
                fvext.extend(f".{ext.lower()}" for ext in vdata[2:])
            else:
                vstatus = ""
        else:
            vext = ""
            vstatus = ""

        faext = []
        if self.convert_audio:
            adata = self.convert_audio.split()
            aext = adata[0].lower()
            if len(adata) > 2:
                if "+" in adata[1].split():
                    astatus = "+"
                elif "-" in adata[1].split():
                    astatus = "-"
                else:
                    astatus = ""
                faext.extend(f".{ext.lower()}" for ext in adata[2:])
            else:
                astatus = ""
        else:
            aext = ""
            astatus = ""

        self.files_to_proceed = {}
        all_files = []
        if self.is_file:
            all_files.append(dl_path)
        else:
            for dirpath, _, files in await sync_to_async(walk, dl_path, topdown=False):
                for file_ in files:
                    f_path = ospath.join(dirpath, file_)
                    all_files.append(f_path)

        for f_path in all_files:
            is_video, is_audio, _ = await get_document_type(f_path)
            if (
                is_video
                and vext
                and not f_path.strip().lower().endswith(f".{vext}")
                and (
                    vstatus == "+"
                    and f_path.strip().lower().endswith(tuple(fvext))
                    or vstatus == "-"
                    and not f_path.strip().lower().endswith(tuple(fvext))
                    or not vstatus
                )
            ):
                self.files_to_proceed[f_path] = "video"
            elif (
                is_audio
                and aext
                and not is_video
                and not f_path.strip().lower().endswith(f".{aext}")
                and (
                    astatus == "+"
                    and f_path.strip().lower().endswith(tuple(faext))
                    or astatus == "-"
                    and not f_path.strip().lower().endswith(tuple(faext))
                    or not astatus
                )
            ):
                self.files_to_proceed[f_path] = "audio"
        del all_files

        if self.files_to_proceed:
            ffmpeg = FFMpeg(self)
            async with task_dict_lock:
                task_dict[self.mid] = FFmpegStatus(self, ffmpeg, gid, "Convert")
            self.progress = False
            async with cpu_eater_lock:
                self.progress = True
                for f_path, f_type in self.files_to_proceed.items():
                    self.proceed_count += 1
                    LOGGER.info(f"Converting: {f_path}")
                    if self.is_file:
                        self.subsize = self.size
                    else:
                        self.subsize = await get_path_size(f_path)
                        self.subname = ospath.basename(f_path)
                    if f_type == "video":
                        res = await ffmpeg.convert_video(f_path, vext)
                    else:
                        res = await ffmpeg.convert_audio(f_path, aext)
                    if res:
                        try:
                            await remove(f_path)
                        except Exception:
                            self.is_cancelled = True
                            return False
                        if self.is_file:
                            return res
        return dl_path

    async def generate_sample_video(self, dl_path, gid):
        # Support legacy -sv param (total:segment) while adding user settings (count + duration)
        data = (
            self.sample_video.split(":") if isinstance(self.sample_video, str) else []
        )
        legacy_total = int(data[0]) if data and data[0].isdigit() else None
        legacy_part = int(data[1]) if len(data) > 1 and data[1].isdigit() else None

        # New settings
        sv_enabled = getattr(self, "user_dict", {}).get("SAMPLE_VIDEO_ENABLED", False)
        sv_count = getattr(self, "user_dict", {}).get("SAMPLE_VIDEO_COUNT", 1)
        sv_clip_dur = getattr(self, "user_dict", {}).get("SAMPLE_VIDEO_DURATION", 60)

        # Decide mode: legacy param takes precedence if provided in command
        if self.sample_video and legacy_total:
            # Reconstruct original logic using legacy values
            sample_duration = legacy_total
            part_duration = legacy_part or 4
            random_mode = False
        elif sv_enabled:
            random_mode = True
            sv_count = max(1, min(10, int(sv_count)))
            sv_clip_dur = max(5, min(600, int(sv_clip_dur)))  # 5s to 10m
        else:
            return dl_path  # Nothing to do

        self.files_to_proceed = {}
        if self.is_file and (await get_document_type(dl_path))[0]:
            file_ = ospath.basename(dl_path)
            self.files_to_proceed[dl_path] = file_
        else:
            for dirpath, _, files in await sync_to_async(walk, dl_path, topdown=False):
                for file_ in files:
                    f_path = ospath.join(dirpath, file_)
                    if (await get_document_type(f_path))[0]:
                        self.files_to_proceed[f_path] = file_
        if self.files_to_proceed:
            ffmpeg = FFMpeg(self)
            async with task_dict_lock:
                task_dict[self.mid] = FFmpegStatus(self, ffmpeg, gid, "Sample Video")
            self.progress = False
            async with cpu_eater_lock:
                self.progress = True
                LOGGER.info(f"Creating Sample video: {self.name}")
                for f_path, file_ in self.files_to_proceed.items():
                    self.proceed_count += 1
                    if self.is_file:
                        self.subsize = self.size
                    else:
                        self.subsize = await get_path_size(f_path)
                        self.subname = file_
                    if random_mode:
                        # Generate multiple random clips then concatenate
                        from random import randint

                        duration = (await get_media_info(f_path))[0]
                        clips = []
                        total_possible = min(
                            sv_count, max(1, duration // max(1, sv_clip_dur))
                        )
                        used_starts = set()
                        for _ in range(total_possible):
                            if duration <= sv_clip_dur + 10:
                                break
                            # Ensure unique-ish start times
                            for _ in range(5):
                                start = randint(5, max(5, duration - sv_clip_dur - 5))
                                bucket = start // 10
                                if bucket not in used_starts:
                                    used_starts.add(bucket)
                                    break
                            else:
                                start = max(0, duration // 2 - sv_clip_dur // 2)
                            clips.append((start, start + sv_clip_dur))
                        if not clips:
                            continue
                        # Sort clips by start for determinism
                        clips.sort()
                        separate = getattr(self, "user_dict", {}).get(
                            "SAMPLE_VIDEO_SEPARATE", False
                        )
                        # Enforce 25% max total sample duration ratio
                        total_requested = sv_clip_dur * len(clips)
                        max_allowed = int(duration * 0.25)
                        if total_requested > max_allowed and len(clips) > 0:
                            # Reduce number of clips proportionally
                            allowed_clips = max(1, max_allowed // sv_clip_dur)
                            if allowed_clips < len(clips):
                                clips = clips[:allowed_clips]
                                total_requested = sv_clip_dur * len(clips)
                                LOGGER.info(
                                    f"Sample clip count reduced to {len(clips)} to respect 25% duration cap"
                                )
                        # Disk space estimation
                        try:
                            video_size = await get_path_size(f_path)
                            expected_ratio = (
                                total_requested / duration if duration else 0.1
                            )
                            expected_sample_size = int(video_size * expected_ratio)
                        except Exception:
                            expected_sample_size = 0
                        # Check free space
                        try:
                            dirp = ospath.dirname(f_path)
                            free_space = disk_usage(dirp).free
                        except Exception:
                            free_space = None
                        if (
                            free_space is not None
                            and expected_sample_size
                            and free_space < expected_sample_size + 30 * 1024 * 1024
                        ):
                            LOGGER.warning(
                                f"Skipping sample generation due to low free space. Needed ~{expected_sample_size} bytes, free {free_space} bytes"
                            )
                            continue
                        if separate:
                            # Produce individual SAMPLE_xxx files
                            new_folder = ospath.splitext(f_path)[0]
                            try:
                                await makedirs(new_folder, exist_ok=True)
                            except OSError as e:
                                LOGGER.error(
                                    f"Cannot create sample folder (separate mode): {e}"
                                )
                                continue
                            idx = 1
                            for start, end in clips:
                                if self.is_cancelled:
                                    return False
                                # Adjust end if exceeds total
                                if end > duration:
                                    end = duration
                                # Use float precision for better accuracy
                                clip_len = float(end - start)
                                if clip_len < 0.25:  # ignore too tiny segments
                                    idx += 1
                                    continue
                                out_path = f"{new_folder}/SAMPLE_{idx:02}.{file_}"
                                # Precise trimming via filter_complex trim (ensures exact pts and duration)
                                # Start/end expressed with up to 3 decimals
                                start_f = f"{start:.3f}".rstrip("0").rstrip(".")
                                end_f = f"{end:.3f}".rstrip("0").rstrip(".")
                                filter_complex = (
                                    f"[0:v]trim=start={start_f}:end={end_f},setpts=PTS-STARTPTS[v];"
                                    f"[0:a]atrim=start={start_f}:end={end_f},asetpts=PTS-STARTPTS[a]"
                                )
                                cmd = [
                                    BinConfig.FFMPEG_NAME,
                                    "-hide_banner",
                                    "-loglevel",
                                    "error",
                                    "-progress",
                                    "pipe:1",
                                    "-i",
                                    f_path,
                                    "-filter_complex",
                                    filter_complex,
                                    "-map",
                                    "[v]",
                                    "-map",
                                    "[a]",
                                    "-c:v",
                                    "libx264",
                                    "-preset",
                                    "veryfast",
                                    "-c:a",
                                    "aac",
                                    "-movflags",
                                    "+faststart",
                                    "-pix_fmt",
                                    "yuv420p",
                                    "-shortest",
                                    "-threads",
                                    f"{max(1, cpu_no // 2)}",
                                    out_path,
                                ]
                                self.subproc = await create_subprocess_exec(
                                    *cmd, stdout=PIPE, stderr=PIPE
                                )
                                await self.subproc.wait()
                                # Optional: verify duration (best-effort)
                                try:
                                    real_dur = float(
                                        (await get_media_info(out_path))[0]
                                    )
                                    if abs(real_dur - clip_len) > 0.75:
                                        LOGGER.info(
                                            f"Sample clip duration mismatch: {out_path} expected {clip_len:.2f}s got {real_dur:.2f}s"
                                        )
                                except Exception:
                                    pass
                                # Re-check free space after each clip
                                try:
                                    if (
                                        disk_usage(new_folder).free < 500 * 1024 * 1024
                                    ):  # <50MB left
                                        LOGGER.warning(
                                            "Low disk space mid-generation, stopping further sample clips"
                                        )
                                        break
                                except Exception:
                                    pass
                                idx += 1
                            if self.is_file and await aiopath.exists(f_path):
                                await move(f_path, f"{new_folder}/{file_}")
                                return new_folder
                        else:
                            # Build single concatenated sample file via filter_complex
                            dirp, _ = f_path.rsplit("/", 1)
                            tmp_output = f"{dirp}/SAMPLE.{file_}"
                            filter_complex = ""
                            for i, (start, end) in enumerate(clips):
                                filter_complex += f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}]; "
                                filter_complex += f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}]; "
                            for i in range(len(clips)):
                                filter_complex += f"[v{i}][a{i}]"
                            filter_complex += (
                                f"concat=n={len(clips)}:v=1:a=1[vout][aout]"
                            )
                            cmd = [
                                BinConfig.FFMPEG_NAME,
                                "-hide_banner",
                                "-loglevel",
                                "error",
                                "-progress",
                                "pipe:1",
                                "-i",
                                f_path,
                                "-filter_complex",
                                filter_complex,
                                "-map",
                                "[vout]",
                                "-map",
                                "[aout]",
                                "-c:v",
                                "libx264",
                                "-c:a",
                                "aac",
                                "-threads",
                                f"{max(1, cpu_no // 2)}",
                                tmp_output,
                            ]
                            if self.is_cancelled:
                                return False
                            try:
                                self._total_time = sv_clip_dur * len(clips)
                            except Exception:
                                pass
                            self.subproc = await create_subprocess_exec(
                                *cmd, stdout=PIPE, stderr=PIPE
                            )
                            try:
                                await ffmpeg._ffmpeg_progress()
                            except Exception:
                                await self.subproc.wait()
                            code = self.subproc.returncode
                            if code == 0 and self.is_file:
                                new_folder = ospath.splitext(f_path)[0]
                                try:
                                    await makedirs(new_folder, exist_ok=True)
                                except OSError as e:
                                    LOGGER.error(
                                        f"Cannot create sample folder (merged mode): {e}"
                                    )
                                    if await aiopath.exists(tmp_output):
                                        await remove(tmp_output)
                                    continue
                                await gather(
                                    move(f_path, f"{new_folder}/{file_}"),
                                    move(tmp_output, f"{new_folder}/SAMPLE.{file_}"),
                                )
                                return new_folder
                            else:
                                if await aiopath.exists(tmp_output):
                                    await remove(tmp_output)
                                continue
                    else:
                        res = await ffmpeg.sample_video(
                            f_path, sample_duration, part_duration
                        )
                        if res and self.is_file:
                            new_folder = ospath.splitext(f_path)[0]
                            await makedirs(new_folder, exist_ok=True)
                            await gather(
                                move(f_path, f"{new_folder}/{file_}"),
                                move(res, f"{new_folder}/SAMPLE.{file_}"),
                            )
                            return new_folder
        return dl_path

    async def proceed_compress(self, dl_path, gid):
        pswd = self.compress if isinstance(self.compress, str) else ""
        if self.is_leech and self.is_file:
            new_folder = ospath.splitext(dl_path)[0]
            name = ospath.basename(dl_path)
            await makedirs(new_folder, exist_ok=True)
            new_dl_path = f"{new_folder}/{name}"
            await move(dl_path, new_dl_path)
            dl_path = new_dl_path
            up_path = f"{new_dl_path}.zip"
            self.is_file = False
        else:
            up_path = f"{dl_path}.zip"
        sevenz = SevenZ(self)
        async with task_dict_lock:
            task_dict[self.mid] = SevenZStatus(self, sevenz, gid, "Zip")
        return await sevenz.zip(dl_path, up_path, pswd)

    async def merge_video_subtitles(self, dl_path, gid):
        """
        Merge video files with separate subtitle files

        Parameters:
        dl_path (str): Path to the download directory or file
        gid (str): Task ID

        Returns:
        str: Path to the directory with merged files
        """
        if not self.user_dict.get("VIDEO_SUBTITLE_MERGE_ENABLED", False):
            return dl_path

        # Check if source files should be kept after merging
        keep_source_files = self.user_dict.get("KEEP_MERGE_SOURCE_FILES", False)
        LOGGER.info(f"Checking for video+subtitle files to merge in: {dl_path}")

        # Known subtitle file extensions
        subtitle_extensions = [
            ".srt",
            ".ass",
            ".ssa",
            ".sub",
            ".idx",
            ".vtt",
            ".smi",
            ".mka",
        ]

        try:
            # Get video and subtitle files in each directory
            dir_contents = await sync_to_async(walk, dl_path, topdown=False)
            for dirpath, _, files in dir_contents:
                video_files = []
                subtitle_files = []

                LOGGER.info(
                    f"Scanning directory: {dirpath} for video and subtitle files"
                )

                # Sort files naturally to ensure proper sequence
                sorted_files = natsorted(files)

                # Identify video and subtitle files
                for file_ in sorted_files:
                    try:
                        f_path = ospath.join(dirpath, file_)
                        file_ext = ospath.splitext(file_)[1].lower()

                        if file_ext in subtitle_extensions:
                            # Special handling for MKA files - check if they contain subtitle streams
                            if file_ext == ".mka":
                                try:
                                    LOGGER.info(
                                        f"Found potential subtitle in MKA format: {file_}, checking streams"
                                    )
                                    # Use ffprobe to examine the MKA file content
                                    mka_probe_cmd = [
                                        "ffprobe",
                                        "-v",
                                        "quiet",
                                        "-print_format",
                                        "json",
                                        "-show_streams",
                                        f_path,
                                    ]
                                    mka_process = await cmd_exec(mka_probe_cmd, True)
                                    if mka_process[0]:
                                        try:
                                            import json

                                            mka_info = json.loads(mka_process[0])
                                            mka_streams = mka_info.get("streams", [])

                                            # Check if any stream is a subtitle
                                            has_subtitle = False
                                            for stream in mka_streams:
                                                if (
                                                    stream.get("codec_type")
                                                    == "subtitle"
                                                ):
                                                    has_subtitle = True
                                                    LOGGER.info(
                                                        f"MKA file {file_} contains subtitle streams, adding to subtitle list"
                                                    )
                                                    break

                                            if has_subtitle:
                                                subtitle_files.append(f_path)
                                            else:
                                                LOGGER.info(
                                                    f"MKA file {file_} doesn't contain subtitle streams, skipping"
                                                )
                                        except Exception as e:
                                            LOGGER.warning(
                                                f"Error parsing MKA stream info: {str(e)}, adding it as subtitle anyway"
                                            )
                                            subtitle_files.append(f_path)
                                except Exception as e:
                                    LOGGER.warning(
                                        f"Error analyzing MKA file {file_}: {str(e)}, adding it as subtitle anyway"
                                    )
                                    subtitle_files.append(f_path)
                            else:
                                # Standard subtitle files
                                subtitle_files.append(f_path)
                                LOGGER.info(f"Found subtitle: {file_}")
                        else:
                            is_video, _, _ = await get_document_type(f_path)
                            if is_video:
                                video_files.append(f_path)
                                LOGGER.info(f"Found video: {file_}")
                    except Exception as e:
                        LOGGER.error(f"Error checking file type for {file_}: {e}")

                # Only proceed if we have at least one video and one subtitle file
                if len(video_files) >= 1 and len(subtitle_files) >= 1:
                    try:
                        # Use the first video file as the base
                        base_video = video_files[0]
                        base_name = ospath.basename(base_video)

                        # Output to the same directory
                        output_dir = dirpath
                        output_name = f"{base_name.split('.')[0]}.mkv"
                        output_file = ospath.join(output_dir, output_name)

                        ffmpeg = FFMpeg(self)
                        async with task_dict_lock:
                            task_dict[self.mid] = FFmpegStatus(
                                self, ffmpeg, gid, "Video+Subtitle Merge"
                            )

                        self.progress = False
                        async with cpu_eater_lock:
                            self.progress = True
                            LOGGER.info(
                                f"Merging video with {len(subtitle_files)} subtitle tracks in: {dirpath}"
                            )

                            # Calculate total size
                            video_size = await get_path_size(base_video)
                            subtitle_sizes = [
                                await get_path_size(f) for f in subtitle_files
                            ]
                            self.subsize = video_size + sum(subtitle_sizes)
                            self.subname = output_name

                            # Perform the merge
                            res = await ffmpeg.merge_video_subtitles(
                                base_video, subtitle_files, output_file
                            )

                            if not res:
                                LOGGER.error(
                                    f"Failed to merge video with subtitles in {dirpath}"
                                )
                            else:
                                LOGGER.info(
                                    f"Successfully merged video with subtitle tracks in {dirpath}"
                                )

                                # Delete source files if user doesn't want to keep them
                                if not keep_source_files:
                                    LOGGER.info(
                                        "Deleting source files as per user setting"
                                    )
                                    # Delete subtitle files (original video was replaced during merge)
                                    for subtitle_file in subtitle_files:
                                        if await aiopath.exists(subtitle_file):
                                            await remove(subtitle_file)
                    except Exception as e:
                        LOGGER.error(
                            f"Error during video+subtitle merge in {dirpath}: {str(e)}"
                        )
        except Exception as e:
            LOGGER.error(
                f"Error scanning directories for video+subtitle merging: {str(e)}"
            )

        return dl_path

    async def hardsub_video(self, dl_path, gid):
        """
        Burn subtitle files permanently into video files

        Parameters:
        dl_path (str): Path to the download directory or file
        gid (str): Task ID

        Returns:
        str: Path to the directory with hardsubbed files
        """
        if not self.user_dict.get("VIDEO_HARDSUB_ENABLED", False):
            return dl_path

        # Check if source files should be kept after hardsub
        keep_source_files = self.user_dict.get("KEEP_MERGE_SOURCE_FILES", False)
        LOGGER.info(f"Checking for video+subtitle files to hardsub in: {dl_path}")

        # Known subtitle file extensions
        subtitle_extensions = [".srt", ".ass", ".ssa", ".sub", ".vtt", ".smi"]

        try:
            # Get video and subtitle files in each directory
            dir_contents = await sync_to_async(walk, dl_path, topdown=False)
            for dirpath, _, files in dir_contents:
                video_files = []
                subtitle_files = []

                LOGGER.info(
                    f"Scanning directory: {dirpath} for video and subtitle files"
                )

                # Sort files naturally to ensure proper sequence
                sorted_files = natsorted(files)

                # Identify video and subtitle files
                for file_ in sorted_files:
                    try:
                        f_path = ospath.join(dirpath, file_)
                        file_ext = ospath.splitext(file_)[1].lower()

                        if file_ext in subtitle_extensions:
                            subtitle_files.append(f_path)
                            LOGGER.info(f"Found subtitle: {file_}")
                        else:
                            is_video, _, _ = await get_document_type(f_path)
                            if is_video:
                                video_files.append(f_path)
                                LOGGER.info(f"Found video: {file_}")
                    except Exception as e:
                        LOGGER.error(f"Error checking file type for {file_}: {e}")

                # Only proceed if we have at least one video and one subtitle file
                if len(video_files) >= 1 and len(subtitle_files) >= 1:
                    try:
                        # Use the first video file as the base
                        base_video = video_files[0]
                        base_name = ospath.basename(base_video)

                        # Output to the same directory with the same name (no _hardsub suffix)
                        output_dir = dirpath
                        output_name = base_name  # Keep original filename
                        output_file = ospath.join(output_dir, output_name)

                        ffmpeg = FFMpeg(self)
                        async with task_dict_lock:
                            task_dict[self.mid] = FFmpegStatus(
                                self, ffmpeg, gid, "Video Hardsub"
                            )

                        self.progress = False
                        async with cpu_eater_lock:
                            self.progress = True
                            LOGGER.info(
                                f"Burning {len(subtitle_files)} subtitle track(s) into video in: {dirpath}"
                            )

                            # Calculate total size
                            video_size = await get_path_size(base_video)
                            subtitle_sizes = [
                                await get_path_size(f) for f in subtitle_files
                            ]
                            self.subsize = video_size + sum(subtitle_sizes)
                            self.subname = output_name

                            # Perform the hardsub
                            res = await ffmpeg.hardsub_video(
                                base_video, subtitle_files, output_file, self.user_dict
                            )

                            if not res:
                                LOGGER.error(f"Failed to hardsub video: {base_video}")
                                # Remove from task dict
                                async with task_dict_lock:
                                    if self.mid in task_dict:
                                        del task_dict[self.mid]
                                continue

                            LOGGER.info(f"Successfully hardsubbed video: {output_name}")

                            # If not keeping source files, clean them up
                            if not keep_source_files:
                                try:
                                    # Note: The hardsub_video method already handles replacing the original video
                                    # with the hardsubbed version, so we only need to remove subtitle files

                                    # Remove subtitle files
                                    for subtitle_file in subtitle_files:
                                        await remove(subtitle_file)
                                        LOGGER.info(
                                            f"Removed subtitle: {ospath.basename(subtitle_file)}"
                                        )
                                except Exception as e:
                                    LOGGER.error(
                                        f"Error removing source files: {str(e)}"
                                    )

                        # Remove from task dict
                        async with task_dict_lock:
                            if self.mid in task_dict:
                                del task_dict[self.mid]

                    except Exception as e:
                        LOGGER.error(
                            f"Error during video hardsub in {dirpath}: {str(e)}"
                        )
                        # Remove from task dict in case of error
                        async with task_dict_lock:
                            if self.mid in task_dict:
                                del task_dict[self.mid]

        except Exception as e:
            LOGGER.error(f"Error scanning directories for video hardsub: {str(e)}")

        return dl_path

    async def merge_video_audio(self, dl_path, gid):
        """
        Merge video files with separate audio tracks

        Parameters:
        dl_path (str): Path to the download directory or file
        gid (str): Task ID

        Returns:
        str: Path to the directory with merged files
        """
        if not self.user_dict.get("VIDEO_AUDIO_MERGE_ENABLED", False):
            return dl_path

        # Check if source files should be kept after merging
        keep_source_files = self.user_dict.get("KEEP_MERGE_SOURCE_FILES", False)
        LOGGER.info(f"Checking for video+audio to merge in: {dl_path}")

        try:
            # Get video and audio files in each directory
            dir_contents = await sync_to_async(walk, dl_path, topdown=False)
            for dirpath, _, files in dir_contents:
                video_files = []
                audio_files = []

                LOGGER.info(f"Scanning directory: {dirpath} for video and audio files")

                # Sort files naturally to ensure proper sequence
                sorted_files = natsorted(files)

                # Identify video and audio files
                for file_ in sorted_files:
                    try:
                        f_path = ospath.join(dirpath, file_)
                        is_video, is_audio, _ = await get_document_type(f_path)

                        if is_video:
                            video_files.append(f_path)
                            LOGGER.info(f"Found video: {file_}")
                        elif is_audio:
                            audio_files.append(f_path)
                            LOGGER.info(f"Found audio: {file_}")
                    except Exception as e:
                        LOGGER.error(f"Error checking file type for {file_}: {e}")

                # Only proceed if we have at least one video and one audio file
                if len(video_files) >= 1 and len(audio_files) >= 1:
                    try:
                        # Use the first video file as the base
                        base_video = video_files[0]
                        base_name = ospath.basename(base_video)

                        # Output to the same directory
                        output_dir = dirpath
                        output_name = f"{base_name.split('.')[0]}.mkv"
                        output_file = ospath.join(output_dir, output_name)

                        ffmpeg = FFMpeg(self)
                        async with task_dict_lock:
                            task_dict[self.mid] = FFmpegStatus(
                                self, ffmpeg, gid, "Video+Audio Merge"
                            )

                        self.progress = False
                        async with cpu_eater_lock:
                            self.progress = True
                            LOGGER.info(
                                f"Merging video with {len(audio_files)} audio tracks in: {dirpath}"
                            )

                            # Calculate total size
                            video_size = await get_path_size(base_video)
                            audio_sizes = [await get_path_size(f) for f in audio_files]
                            self.subsize = video_size + sum(audio_sizes)
                            self.subname = output_name

                            # Perform the merge
                            res = await ffmpeg.merge_video_audio(
                                base_video, audio_files, output_file
                            )

                            if not res:
                                LOGGER.error(
                                    f"Failed to merge video with audio in {dirpath}"
                                )
                            else:
                                LOGGER.info(
                                    f"Successfully merged video with audio tracks in {dirpath}"
                                )

                                # Delete source files if user doesn't want to keep them
                                if not keep_source_files:
                                    LOGGER.info(
                                        "Deleting source files as per user setting"
                                    )
                                    # Delete audio files (original video was replaced during merge)
                                    for audio_file in audio_files:
                                        if await aiopath.exists(audio_file):
                                            await remove(audio_file)
                    except Exception as e:
                        LOGGER.error(
                            f"Error during video+audio merge in {dirpath}: {str(e)}"
                        )
        except Exception as e:
            LOGGER.error(
                f"Error scanning directories for video+audio merging: {str(e)}"
            )

        return dl_path

    async def merge_videos(self, dl_path, gid):
        """
        Merge multiple video files into a single output file

        Parameters:
        dl_path (str): Path to the download directory or file
        gid (str): Task ID

        Returns:
        str or bool: Path to the directory/file with merged video, or False if failed
        """
        if not self.user_dict.get("VIDEO_MERGE_ENABLED", False):
            return dl_path

        # Check if source files should be kept after merging
        keep_source_files = self.user_dict.get("KEEP_MERGE_SOURCE_FILES", False)
        LOGGER.info(f"Checking for videos to merge in: {dl_path}")

        # Collect all video files to merge

        # Find all video files in directory
        try:
            dir_contents = await sync_to_async(walk, dl_path, topdown=False)
            for dirpath, _, files in dir_contents:
                video_files_in_dir = []
                LOGGER.info(f"Scanning directory: {dirpath} for videos")

                # Sort files naturally to ensure proper sequence
                sorted_files = natsorted(files)

                # First pass - identify video files
                for file_ in sorted_files:
                    try:
                        f_path = ospath.join(dirpath, file_)
                        is_video = (await get_document_type(f_path))[0]
                        if is_video:  # Check if it's a video
                            video_files_in_dir.append(f_path)
                            LOGGER.info(f"Found video: {file_}")
                    except Exception as e:
                        LOGGER.error(f"Error checking file type for {file_}: {e}")

                if (
                    len(video_files_in_dir) > 1
                ):  # Only merge if there are multiple videos
                    try:
                        # Each subdirectory gets its own merged video
                        output_dir = dirpath
                        # Use MKV format instead of MP4 to support more codecs (especially subtitles)
                        output_name = f"{ospath.basename(dirpath)}.mkv"
                        output_file = ospath.join(output_dir, output_name)

                        ffmpeg = FFMpeg(self)
                        async with task_dict_lock:
                            task_dict[self.mid] = FFmpegStatus(
                                self, ffmpeg, gid, "Video Merge"
                            )

                        self.progress = False
                        async with cpu_eater_lock:
                            self.progress = True
                            LOGGER.info(
                                f"Merging {len(video_files_in_dir)} videos in: {dirpath}"
                            )

                            # Calculate total size properly by gathering all async results
                            size_tasks = [get_path_size(f) for f in video_files_in_dir]
                            sizes = await gather(*size_tasks)
                            self.subsize = sum(sizes)
                            self.subname = output_name

                            # Perform the merge
                            res = await ffmpeg.merge_videos(
                                video_files_in_dir, output_file
                            )

                            if not res:
                                LOGGER.error(f"Failed to merge videos in {dirpath}")
                            else:
                                LOGGER.info(f"Successfully merged videos in {dirpath}")

                                # Delete source files if user doesn't want to keep them
                                if not keep_source_files:
                                    LOGGER.info(
                                        f"Deleting source files as per user setting"
                                    )
                                    for video_file in video_files_in_dir:
                                        try:
                                            await remove(video_file)
                                            LOGGER.info(
                                                f"Deleted source file: {video_file}"
                                            )
                                        except Exception as e:
                                            LOGGER.error(
                                                f"Error deleting source file {video_file}: {str(e)}"
                                            )
                    except Exception as e:
                        LOGGER.error(
                            f"Error during merge operation in {dirpath}: {str(e)}"
                        )
        except Exception as e:
            LOGGER.error(f"Error scanning directories for video merging: {str(e)}")

        return dl_path

    async def proceed_split(self, dl_path, gid):
        self.files_to_proceed = {}
        if self.is_file:
            f_size = await get_path_size(dl_path)
            if f_size > self.split_size:
                self.files_to_proceed[dl_path] = [f_size, ospath.basename(dl_path)]
        else:
            for dirpath, _, files in await sync_to_async(walk, dl_path, topdown=False):
                for file_ in files:
                    f_path = ospath.join(dirpath, file_)
                    f_size = await get_path_size(f_path)
                    if f_size > self.split_size:
                        self.files_to_proceed[f_path] = [f_size, file_]
        if self.files_to_proceed:
            ffmpeg = FFMpeg(self)
            async with task_dict_lock:
                task_dict[self.mid] = FFmpegStatus(self, ffmpeg, gid, "Split")
            LOGGER.info(f"Splitting: {self.name}")
            for f_path, (f_size, file_) in self.files_to_proceed.items():
                self.proceed_count += 1
                if self.is_file:
                    self.subsize = self.size
                else:
                    self.subsize = f_size
                    self.subname = file_
                parts = -(-f_size // self.split_size)
                if self.equal_splits:
                    split_size = (f_size // parts) + (f_size % parts)
                else:
                    split_size = self.split_size
                if not self.as_doc and (await get_document_type(f_path))[0]:
                    self.progress = True
                    res = await ffmpeg.split(f_path, file_, parts, split_size)
                else:
                    self.progress = False
                    res = await split_file(f_path, split_size, self)
                if self.is_cancelled:
                    return False
                if res or f_size >= self.max_split_size:
                    try:
                        await remove(f_path)
                    except Exception:
                        self.is_cancelled = True
                        return False
        return dl_path
