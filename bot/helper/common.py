import gc  # Added for memory management
import re
from asyncio import gather, sleep
from contextlib import suppress
from os import path as ospath, walk
from re import sub
from secrets import token_hex
from shlex import split
from shutil import disk_usage

from aiofiles.os import listdir, makedirs, remove, path as aiopath
from aioshutil import move, rmtree

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
from ..core.config_manager import Config, BinConfig  # Keep BinConfig from main
from ..core.tg_client import TgClient
from .ext_utils.bot_utils import get_size_bytes, new_task, sync_to_async
from .ext_utils.bulk_links import extract_bulk_links
from .ext_utils.files_utils import (
    SevenZ,
    get_base_name,
    get_path_size,
    is_archive,
    is_archive_split,
    is_first_archive_split,
    split_file,  # Used by reference proceed_split
)
from .ext_utils.links_utils import (
    is_gdrive_id,
    is_gdrive_link,
    is_gofile_upload,  # main uses this
    is_rclone_path,
    is_telegram_link,
    is_mega_link,  # main uses this
)
from .ext_utils.media_utils import (
    FFMpeg,  # Used by reference proceed_split
    create_thumb,
    get_document_type,  # Used by reference proceed_split
    take_ss,
    get_ss_grid_pdf,  # main specific
)
from .mirror_leech_utils.gdrive_utils.list import GoogleDriveList
from .mirror_leech_utils.rclone_utils.list import RcloneList
from .mirror_leech_utils.status_utils.ffmpeg_status import (
    FFMpegStatus,
)  # Used by reference proceed_split
from .mirror_leech_utils.status_utils.sevenz_status import SevenZStatus
from .telegram_helper.bot_commands import BotCommands
from .telegram_helper.message_utils import (
    get_tg_link_message,
    send_message,
    send_status_message,
)
from .ext_utils.status_utils import get_readable_file_size


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
        self.thumbnail_layout = (
            ""  # Main specific, reference uses thumb_layout from user_dict
        )
        self.folder_name = ""
        self.split_size = 0
        self.max_split_size = 0
        self.multi = 0
        self.size = 0
        self.subsize = 0
        self.proceed_count = 0
        self.is_leech = False
        self.is_yt = False  # main specific
        self.is_qbit = False
        self.is_mega = False  # main specific
        self.is_nzb = False  # main specific
        self.is_jd = False
        self.is_clone = False
        self.is_gdrive = False  # main specific
        self.is_rclone = False  # main specific
        self.is_ytdlp = False  # main specific (reference has is_playlist)
        self.equal_splits = False
        self.user_transmission = (
            False  # This will be set by main logic, then used by ref split logic
        )
        self.hybrid_leech = False  # main specific, ref has mixed_leech
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
        self.zip_metadata = False  # main specific
        self.is_cancelled = False
        self.force_run = False  # main specific
        self.force_download = False  # main specific
        self.force_upload = False  # main specific
        self.is_torrent = False  # main specific
        self.as_med = False
        self.as_doc = False
        self.is_file = False
        self.bot_trans = False  # main specific
        self.user_trans = False  # main specific
        self.progress = True
        self.ffmpeg_cmds = None
        self.chat_thread_id = None  # main specific
        self.subproc = None
        self.thumb = None
        self.excluded_extensions = []  # main specific, ref has extension_filter
        self.video_mode: list | None = None  # main specific
        self.files_to_proceed = []
        self.is_super_chat = self.message.chat.type.name in ["SUPERGROUP", "CHANNEL"]
        self.source_url = None  # main specific
        self.bot_pm = Config.BOT_PM or self.user_dict.get("BOT_PM")  # main specific
        self.pm_msg = None  # main specific
        self.file_details = {}  # main specific
        self.mode = tuple()  # main specific, ref has self.mode as string
        self.user_preferred_upload_service = self.user_dict.get(  # main specific
            "DEFAULT_UPLOAD_SERVICE", Config.DEFAULT_UPLOAD_SERVICE
        )
        # Attributes from reference TaskConfig not in main that might be needed by its funcs
        self.cookies = ""  # ref
        self.name_sub = ""  # ref
        self.remove_replace = ""  # ref
        # self.mode = "" # ref, already have tuple, might need to adapt if ref functions use string mode
        self.time = ""  # ref, seems for elapsed time, main calculates on the fly
        self.autorename = ""  # ref
        self.prefix = ""  # ref
        self.suffix = ""  # ref
        self.chat_id = ""  # ref, main uses self.message.chat.id directly
        self.get_chat = ""  # ref, main uses self.client.get_chat directly
        self.is_playlist = False  # ref
        self.metadata_flag = False  # ref
        self.attachment = False  # ref
        self.log_message = None  # ref
        self.extension_filter = []  # ref, main has excluded_extensions

    def _set_mode_engine(self):  # Main codebase version
        self.source_url = (
            self.link
            if len(self.link) > 0 and self.link.startswith("http")
            else (
                f"https://t.me/share/url?url={self.link}"
                if self.link
                else self.message.link
            )
        )

        out_mode = f"#{'Leech' if self.is_leech else 'Clone' if self.is_clone else 'RClone' if self.up_dest.startswith('mrcc:') or is_rclone_path(self.up_dest) else 'GDrive' if self.up_dest.startswith(('mtp:', 'tp:', 'sa:')) or is_gdrive_id(self.up_dest) else 'GoFile' if is_gofile_upload(self.up_dest) else 'UpHosters'}"
        out_mode += " (Zip)" if self.compress else " (Unzip)" if self.extract else ""

        self.is_rclone = is_rclone_path(self.link)
        self.is_gdrive = is_gdrive_link(self.source_url) if self.source_url else False
        self.is_mega = is_mega_link(self.link) if self.source_url else False

        in_mode = f"#{'Mega' if self.is_mega else 'qBit' if self.is_qbit else 'SABnzbd' if self.is_nzb else 'JDown' if self.is_jd else 'RCloneDL' if self.is_rclone else 'ytdlp' if self.is_ytdlp else 'GDrive' if (self.is_clone or self.is_gdrive) else 'Aria2' if (self.source_url and self.source_url != self.message.link) else 'TgMedia'}"

        self.mode = (in_mode, out_mode)

    def get_token_path(self, dest):  # Main codebase version (seems compatible with ref)
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

    def get_config_path(
        self, dest
    ):  # Main codebase version (seems compatible with ref)
        return (
            f"rclone/{self.user_id}.conf" if dest.startswith("mrcc:") else "rclone.conf"
        )

    async def is_token_exists(
        self, path, status
    ):  # Main codebase version (seems compatible with ref)
        if is_rclone_path(path):
            config_path = self.get_config_path(path)
            if config_path != "rclone.conf" and status == "up":
                self.private_link = True
            if not await aiopath.exists(config_path):
                error_message = (
                    f"Rclone Config file not found at '{config_path}'. "
                    "Please create it or provide it. "
                    "You can create it by following the rclone documentation or by using the /rclone command in the bot."
                )
                raise ValueError(error_message)
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
                error_message = (
                    f"Token file not found at '{token_path}'. "
                    "Please create it or provide it. "
                    "You can generate a token by following the documentation."
                )
                raise ValueError(error_message)

    async def before_start(
        self,
    ):  # Main codebase before_start, with leech split part modified
        self.name_swap = (
            self.name_swap
            or self.user_dict.get("NAME_SWAP", False)
            or (Config.NAME_SWAP if "NAME_SWAP" not in self.user_dict else "")
        )
        if self.name_swap:
            self.name_swap = [x.split(":") for x in self.name_swap.split("|")]

        # Use main's excluded_extensions, ref uses extension_filter
        self.excluded_extensions = self.user_dict.get("EXCLUDED_EXTENSIONS") or (
            excluded_extensions
            if "EXCLUDED_EXTENSIONS" not in self.user_dict
            else ["aria2", "!qB"]
        )
        # For reference logic compatibility if needed by other parts of its code not directly split related
        self.extension_filter = self.excluded_extensions

        self.zip_metadata = self.user_dict.get(
            "ZIP_METADATA", getattr(Config, "ZIP_METADATA", False)
        )

        if not self.rc_flags:
            if self.user_dict.get("RCLONE_FLAGS"):
                self.rc_flags = self.user_dict["RCLONE_FLAGS"]
            elif "RCLONE_FLAGS" not in self.user_dict and Config.RCLONE_FLAGS:
                self.rc_flags = Config.RCLONE_FLAGS
        if self.link not in ["rcl", "gdl"]:
            if not self.is_jd:  # is_jd is from main
                if is_rclone_path(self.link):
                    if not self.link.startswith("mrcc:") and self.user_dict.get(
                        "USER_TOKENS",
                        False,  # main uses USER_TOKENS
                    ):
                        self.link = f"mrcc:{self.link}"
                    await self.is_token_exists(self.link, "dl")
                elif is_gdrive_link(self.link):
                    if not self.link.startswith(
                        ("mtp:", "tp:", "sa:")
                    ) and self.user_dict.get(
                        "USER_TOKENS", False
                    ):  # main uses USER_TOKENS
                        self.link = f"mtp:{self.link}"
                    await self.is_token_exists(self.link, "dl")
        elif self.link == "rcl":
            if not self.is_ytdlp and not self.is_jd:  # main uses is_ytdlp
                self.link = await RcloneList(self).get_rclone_path("rcd")
                if not is_rclone_path(self.link):
                    raise ValueError(self.link)
        elif self.link == "gdl":
            if not self.is_ytdlp and not self.is_jd:  # main uses is_ytdlp
                self.link = await GoogleDriveList(self).get_target_id("gdd")
                if not is_gdrive_id(self.link):
                    raise ValueError(self.link)

        # Main codebase logic for user_transmission
        self.user_transmission = TgClient.IS_PREMIUM_USER and (
            self.user_dict.get("USER_TRANSMISSION")
            or Config.USER_TRANSMISSION
            and "USER_TRANSMISSION" not in self.user_dict
        )
        # Reference code sets self.mixed_leech = self.user_transmission = TgClient.IS_PREMIUM_USER
        # We will keep main's self.hybrid_leech logic below.

        if self.user_dict.get("UPLOAD_PATHS", False):  # main
            if self.up_dest in self.user_dict["UPLOAD_PATHS"]:
                self.up_dest = self.user_dict["UPLOAD_PATHS"][self.up_dest]
        elif "UPLOAD_PATHS" not in self.user_dict and Config.UPLOAD_PATHS:  # main
            if self.up_dest in Config.UPLOAD_PATHS:
                self.up_dest = Config.UPLOAD_PATHS[self.up_dest]

        if self.ffmpeg_cmds and not isinstance(self.ffmpeg_cmds, list):
            if self.user_dict.get("FFMPEG_CMDS", None):  # main
                ffmpeg_dict = self.user_dict["FFMPEG_CMDS"]
                self.ffmpeg_cmds = [
                    value
                    for key in list(self.ffmpeg_cmds)
                    if key in ffmpeg_dict
                    for value in ffmpeg_dict[key]
                ]
            elif "FFMPEG_CMDS" not in self.user_dict and Config.FFMPEG_CMDS:  # main
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
            self.stop_duplicate = (  # main
                self.user_dict.get("STOP_DUPLICATE")
                or "STOP_DUPLICATE" not in self.user_dict
                and Config.STOP_DUPLICATE
            )
            default_upload = (  # main
                self.user_dict.get("DEFAULT_UPLOAD", "") or Config.DEFAULT_UPLOAD
            )
            if not self.up_dest:  # main
                if self.user_preferred_upload_service == "gofile":
                    self.up_dest = "gofile"
                elif self.user_preferred_upload_service == "rc":
                    self.up_dest = (
                        self.user_dict.get("RCLONE_PATH") or Config.RCLONE_PATH  # main
                    )
                elif self.user_preferred_upload_service == "gd":
                    self.up_dest = (
                        self.user_dict.get("GDRIVE_ID") or Config.GDRIVE_ID
                    )  # main

            if not self.up_dest:  # main
                if default_upload == "rc":
                    self.up_dest = (
                        self.user_dict.get("RCLONE_PATH") or Config.RCLONE_PATH
                    )
                elif default_upload == "gd":
                    self.up_dest = self.user_dict.get("GDRIVE_ID") or Config.GDRIVE_ID
                elif default_upload == "gofile":
                    self.up_dest = "gofile"

            # Handle default upload destinations
            if not self.up_dest:  # main
                # Set default based on user preferences or config
                if self.user_dict.get("RCLONE_PATH") or Config.RCLONE_PATH:
                    self.up_dest = (
                        self.user_dict.get("RCLONE_PATH") or Config.RCLONE_PATH
                    )
                elif self.user_dict.get("GDRIVE_ID") or Config.GDRIVE_ID:
                    self.up_dest = self.user_dict.get("GDRIVE_ID") or Config.GDRIVE_ID
                elif self.user_dict.get("GOFILE_TOKEN") or Config.GOFILE_API:
                    self.up_dest = "gofile"
                else:
                    raise ValueError("No Upload Destination Specified or Defaulted!")
            elif self.up_dest == "rc":
                self.up_dest = self.user_dict.get("RCLONE_PATH") or Config.RCLONE_PATH
            elif self.up_dest == "gd":
                self.up_dest = self.user_dict.get("GDRIVE_ID") or Config.GDRIVE_ID
            elif self.up_dest in ["gofile", "gf"]:
                self.up_dest = "gofile"

            if not self.up_dest:  # main
                raise ValueError("No Upload Destination Specified or Defaulted!")

            if is_gdrive_id(self.up_dest):  # main
                if not self.up_dest.startswith(
                    ("mtp:", "tp:", "sa:")
                ) and self.user_dict.get("USER_TOKENS", False):
                    self.up_dest = f"mtp:{self.up_dest}"
            elif is_rclone_path(self.up_dest):  # main
                if not self.up_dest.startswith("mrcc:") and self.user_dict.get(
                    "USER_TOKENS", False
                ):
                    self.up_dest = f"mrcc:{self.up_dest}"
                self.up_dest = self.up_dest.strip("/")
            elif self.up_dest == "gofile":  # main
                user_token = self.user_dict.get("GOFILE_TOKEN")
                if not user_token and not Config.GOFILE_API:
                    raise ValueError(
                        "GoFile API token not configured! Please set your GoFile token in user settings or configure a global token."
                    )
            else:  # main
                raise ValueError("Wrong Upload Destination!")

            if self.up_dest not in ["rcl", "gdl", "gofile"]:  # main
                await self.is_token_exists(self.up_dest, "up")

            if self.up_dest == "rcl":  # main
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
            elif self.up_dest == "gdl":  # main
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
            elif self.is_clone:  # main
                if is_gdrive_link(self.link) and self.get_token_path(
                    self.link
                ) != self.get_token_path(self.up_dest):
                    raise ValueError("You must use the same token to clone!")
                elif is_rclone_path(self.link) and self.get_config_path(
                    self.link
                ) != self.get_config_path(self.up_dest):
                    raise ValueError("You must use the same config to clone!")
        else:  # This is self.is_leech == True block
            self.up_dest = (  # main
                self.up_dest
                or self.user_dict.get("LEECH_DUMP_CHAT")  # main uses LEECH_DUMP_CHAT
                or Config.LEECH_DUMP_CHAT
            )
            # Reference uses self.user_dict.get("leech_dest")

            # Main codebase hybrid_leech logic
            premium_user = TgClient.IS_PREMIUM_USER
            if not premium_user and Config.FORCE_PREMIUM_USER:
                premium_user = True
            self.hybrid_leech = premium_user and (
                self.user_dict.get("HYBRID_LEECH")
                or (Config.HYBRID_LEECH and "HYBRID_LEECH" not in self.user_dict)
            )
            if hasattr(self, "cmd_hybrid_leech") and self.cmd_hybrid_leech is not None:
                self.hybrid_leech = self.cmd_hybrid_leech

            if self.bot_trans:  # main specific
                self.user_transmission = False
                self.hybrid_leech = False  # Main ensures hybrid is off if bot_trans

            # This part is from main codebase, seems more detailed for leech destination handling
            if self.up_dest:
                if not isinstance(self.up_dest, int):
                    if self.up_dest.startswith("b:"):
                        self.up_dest = self.up_dest.replace("b:", "", 1)
                        self.user_transmission = False
                        self.hybrid_leech = False
                    elif self.up_dest.startswith("u:"):
                        self.up_dest = self.up_dest.replace("u:", "", 1)
                        self.user_transmission = TgClient.IS_PREMIUM_USER  # Main logic
                    elif self.up_dest.startswith("h:"):
                        self.up_dest = self.up_dest.replace("h:", "", 1)
                        self.user_transmission = TgClient.IS_PREMIUM_USER  # Main logic
                        self.hybrid_leech = self.user_transmission  # Main logic
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

                # Permission checks from main codebase
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
                if (
                    not self.user_transmission or self.hybrid_leech
                ):  # Check with bot account too
                    try:
                        chat = await self.client.get_chat(self.up_dest)
                    except Exception:
                        chat = None
                    if chat is None:
                        if self.user_transmission:
                            self.hybrid_leech = (
                                False  # If user session failed, disable hybrid too
                            )
                        else:
                            raise ValueError("Chat not found!")
                    # ... (rest of permission checks from main code for bot account)

            # --- Start of new split size logic for leech tasks ---
            if TgClient.IS_PREMIUM_USER and not self.bot_trans:
                self.max_split_size = TgClient.MAX_SPLIT_SIZE  # Typically 4GB
                self.split_size = self.max_split_size  # Force 4GB split size
                self.user_transmission = True  # Ensure user transmission is enabled
                self.hybrid_leech = True  # Enable hybrid for consistency
                LOGGER.info(
                    f"Premium user leech (non-bot_trans): Forcing split size to {get_readable_file_size(self.split_size)}"
                )
            else:
                # Logic for non-premium OR premium with bot_trans
                # For bot_trans with premium, they still get 2GB limit like non-premium for bot uploads.
                self.max_split_size = 2097152000  # 2GB

                # Determine initial split_size from command args, then user_dict, then config
                initial_split_size = (
                    self.split_size
                )  # Value from command line arg, if any

                if not initial_split_size:  # If not from command line
                    user_split_val = self.user_dict.get("split_size")  # Reference key
                    if (
                        user_split_val is None
                    ):  # If 'split_size' not found, try old 'LEECH_SPLIT_SIZE'
                        user_split_val = self.user_dict.get("LEECH_SPLIT_SIZE")

                    initial_split_size = user_split_val or Config.LEECH_SPLIT_SIZE

                # Convert to bytes if necessary
                if isinstance(initial_split_size, str):
                    if initial_split_size.isdigit():
                        initial_split_size = int(initial_split_size)
                    else:
                        initial_split_size = get_size_bytes(initial_split_size)

                # Apply logic: use defined split size if valid and positive, else default to max_split_size
                if initial_split_size and initial_split_size > 0:
                    self.split_size = min(initial_split_size, self.max_split_size)
                else:  # Handles 0, None, or negative values from config/user_settings
                    self.split_size = self.max_split_size
                LOGGER.info(
                    f"Non-premium or Bot_trans leech: Setting split size to {get_readable_file_size(self.split_size)} (Max: {get_readable_file_size(self.max_split_size)})"
                )

            self.equal_splits = bool(
                self.user_dict.get("equal_splits")
                or getattr(Config, "EQUAL_SPLITS", False)
            )
            # --- End of new split size logic ---

            LOGGER.info(
                f"Final leech split settings -> Split Size: {get_readable_file_size(self.split_size)}, Max Split Size: {get_readable_file_size(self.max_split_size)}, Equal Splits: {self.equal_splits}, User Transmission: {self.user_transmission}, Hybrid Leech: {self.hybrid_leech}"
            )

            # Determine the effective as_doc setting, prioritizing command flags, then user settings, then global.
            # self.as_doc and self.as_med might already be True/False if set by command-line flags like -d or -m.

            if self.as_med:  # If -m (force media) is used
                self.as_doc = False
                LOGGER.info(
                    "Leech as_doc: Forced False due to as_med=True (e.g., -m flag)."
                )
            elif (
                self.as_doc
            ):  # If -d (force document) is used, self.as_doc is already True
                LOGGER.info(
                    "Leech as_doc: Already True (e.g., -d flag). No change needed from user/global settings."
                )
            else:
                # No overriding command-line flag for document/media type was used.
                # Now, check user-specific settings from user_dict.
                # users_settings.py saves the toggle for "Leech Type" under the key "AS_DOCUMENT".
                if "AS_DOCUMENT" in self.user_dict:
                    self.as_doc = self.user_dict["AS_DOCUMENT"]
                    LOGGER.info(
                        f"Leech as_doc: Set from user_dict['AS_DOCUMENT']: {self.as_doc}"
                    )
                # Fallback for older/manual LEECH_TYPE string setting if AS_DOCUMENT (boolean) wasn't found
                elif "LEECH_TYPE" in self.user_dict:
                    user_leech_type_setting = self.user_dict.get(
                        "LEECH_TYPE", ""
                    ).upper()
                    if user_leech_type_setting == "DOCUMENT":
                        self.as_doc = True
                        LOGGER.info(
                            "Leech as_doc: Set True based on user_dict['LEECH_TYPE']='DOCUMENT'."
                        )
                    elif user_leech_type_setting == "MEDIA":
                        self.as_doc = False
                        LOGGER.info(
                            "Leech as_doc: Set False based on user_dict['LEECH_TYPE']='MEDIA'."
                        )
                    else:  # LEECH_TYPE is present but not DOCUMENT or MEDIA, fallback to global
                        self.as_doc = Config.AS_DOCUMENT
                        LOGGER.info(
                            f"Leech as_doc: LEECH_TYPE present but unrecognized ('{user_leech_type_setting}'). Using global Config.AS_DOCUMENT: {self.as_doc}"
                        )
                else:
                    # No user-specific setting found (neither AS_DOCUMENT nor LEECH_TYPE), use global default.
                    self.as_doc = Config.AS_DOCUMENT
                    LOGGER.info(
                        f"Leech as_doc: No user-specific setting. Using global Config.AS_DOCUMENT: {self.as_doc}"
                    )

            # Main codebase uses self.thumbnail_layout, reference uses self.user_dict.get("thumb_layout")
            # We will keep self.thumbnail_layout as is from main codebase
            self.thumbnail_layout = (
                self.thumbnail_layout
                or self.user_dict.get("THUMBNAIL_LAYOUT", False)
                or (
                    Config.THUMBNAIL_LAYOUT
                    if "THUMBNAIL_LAYOUT" not in self.user_dict
                    else ""
                )
            )

            if self.thumb != "none" and is_telegram_link(self.thumb):
                msg = (await get_tg_link_message(self.thumb))[0]
                # Create thumbnail from Telegram link
                if msg.photo or msg.document:
                    # Check if user already has a default thumbnail set
                    user_default_thumb_path = f"thumbnails/{self.user_id}.jpg"
                    has_existing_thumb = await aiopath.exists(user_default_thumb_path)

                    # Only overwrite user's default thumbnail if they don't have one
                    # Otherwise create a temporary thumbnail for this task only
                    if has_existing_thumb:
                        # User has a custom thumbnail set, create temporary one for this task
                        self.thumb = await create_thumb(msg, "")
                    else:
                        # User doesn't have a default thumbnail, save this as their default
                        self.thumb = await create_thumb(msg, self.user_id)
                else:
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
        if not self.multi_tag and self.multi > 1:
            self.multi_tag = token_hex(3)
            multi_tags.add(self.multi_tag)
        elif self.multi <= 1:
            if self.multi_tag in multi_tags:
                multi_tags.discard(self.multi_tag)
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
        if len(self.bulk) != 0:
            msg = input_list[:1]
            msg.append(f"{self.bulk[0]} -i {self.multi - 1} {self.options}")
            msgts = " ".join(msg)
            if self.multi > 2:  # Main uses this style for cancel message
                msgts += f"\n• <b>Cancel Multi:</b> <i>/{BotCommands.CancelTaskCommand[1]}_{self.multi_tag}</i>"
            nextmsg = await send_message(self.message, msgts)
        else:
            msg = [s.strip() for s in input_list]
            index = msg.index("-i")
            msg[index + 1] = f"{self.multi - 1}"
            nextmsg = await self.client.get_messages(
                chat_id=self.message.chat.id,
                message_ids=self.message.reply_to_message_id + 1,
            )
            msgts = " ".join(msg)
            if self.multi > 2:  # Main uses this style for cancel message
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
        # Adapting call to obj, main has more args like is_nzb, video_mode
        await obj(
            client=self.client,
            message=nextmsg,
            is_qbit=self.is_qbit,
            is_leech=self.is_leech,
            is_jd=self.is_jd,
            is_nzb=self.is_nzb,
            same_dir=self.same_dir,
            bulk=self.bulk,
            vid_mode=self.video_mode,
            multi_tag=self.multi_tag,
            options=self.options,
        ).new_event()

    async def init_bulk(self, input_list, bulk_start, bulk_end, obj):
        if Config.DISABLE_BULK:  # main
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
                self.multi_tag = token_hex(
                    3
                )  # main uses token_hex, ref uses token_urlsafe
                multi_tags.add(self.multi_tag)
                msg += f"\n• <b>Cancel Multi:</b> <i>/{BotCommands.CancelTaskCommand[1]}_{self.multi_tag}</i>"  # main style
            nextmsg = await send_message(self.message, msg)
            nextmsg = await self.client.get_messages(
                chat_id=self.message.chat.id, message_ids=nextmsg.id
            )
            if self.message.from_user:
                nextmsg.from_user = self.user
            else:
                nextmsg.sender_chat = self.user
            # Adapting call to obj
            await obj(
                client=self.client,
                message=nextmsg,
                is_qbit=self.is_qbit,
                is_leech=self.is_leech,
                is_jd=self.is_jd,
                is_nzb=self.is_nzb,
                same_dir=self.same_dir,
                bulk=self.bulk,
                vid_mode=self.video_mode,
                multi_tag=self.multi_tag,
                options=self.options,
            ).new_event()
        except Exception:
            await send_message(
                self.message,
                "Reply to text file or to telegram message that have links seperated by new line!",
            )

    async def proceed_extract(self, dl_path, gid):
        pswd = self.extract if isinstance(self.extract, str) else ""
        self.files_to_proceed = []
        t_path = None  # <-- FIX: Ensure t_path is always defined
        primary_extraction_path = None  # Track the main extraction result

        if self.is_file and is_archive(dl_path):
            self.files_to_proceed.append(dl_path)
        else:
            for dirpath, _, files in await sync_to_async(walk, dl_path, topdown=False):
                for file_ in files:
                    if is_first_archive_split(file_) or (
                        is_archive(file_) and not file_.strip().lower().endswith(".rar")
                    ):
                        f_path = ospath.join(dirpath, file_)
                        self.files_to_proceed.append(f_path)

        if not self.files_to_proceed:
            return dl_path

        sevenz = SevenZ(self)
        LOGGER.info(f"Extracting: {self.name}")
        async with task_dict_lock:
            task_dict[self.mid] = SevenZStatus(self, sevenz, gid, "Extract")

        walk_path = self.up_dir or self.dir

        for dirpath, _, files in await sync_to_async(walk, walk_path, topdown=False):
            code = 0
            for file_ in files:  # This loop is to find archives within the walked path
                if self.is_cancelled:
                    return False
                if is_first_archive_split(file_) or (
                    is_archive(file_) and not file_.strip().lower().endswith(".rar")
                ):
                    self.proceed_count += 1
                    f_path = ospath.join(dirpath, file_)
                    t_path = ospath.join(self.dir, get_base_name(file_))
                    if not self.is_file:
                        self.subname = file_
                    try:
                        code = await sevenz.extract(f_path, t_path, pswd)
                        if self.is_cancelled:
                            return code
                        # Track the first successful extraction path
                        if code == 0 and primary_extraction_path is None:
                            primary_extraction_path = t_path
                    except Exception as e:
                        LOGGER.error(f"Critical extraction error for {file_}: {e}")
                        # Try to handle specific error types
                        if "Future" in str(e) and "HttpError" in str(e):
                            LOGGER.error(
                                "Detected RetryError[Future...HttpError] - network/upload issue during extraction"
                            )
                            await self.on_upload_error(
                                f"Extraction failed due to network error: {str(e)[:200]}"
                            )
                            return False
                        elif "Memory" in str(e) or "allocation" in str(e).lower():
                            LOGGER.error("Memory allocation error during extraction")
                            await self.on_upload_error(
                                f"Extraction failed due to insufficient memory: {str(e)[:200]}"
                            )
                            return False
                        else:
                            # Generic extraction error
                            await self.on_upload_error(
                                f"Extraction process failed: {str(e)[:200]}"
                            )
                            return False

                    if code == 0:
                        # Remove the specific archive that was just extracted
                        try:
                            if await aiopath.exists(f_path):
                                await remove(f_path)
                        except Exception as e:
                            LOGGER.warning(
                                f"Failed to delete extracted archive {f_path}: {e}"
                            )
                        # Also remove any split parts or other archives in the same folder
                        for file_to_delete in files:
                            if is_archive_split(file_to_delete) or is_archive(
                                file_to_delete
                            ):
                                del_path = ospath.join(dirpath, file_to_delete)
                                if del_path == f_path:
                                    continue
                                try:
                                    await remove(del_path)
                                except Exception as e:
                                    LOGGER.warning(
                                        f"Failed to delete archive part {del_path}: {e}"
                                    )
        # Always safe final return
        if self.is_file and code == 0 and (primary_extraction_path or t_path):
            return primary_extraction_path or t_path
        else:
            return dl_path

    async def proceed_ffmpeg(self, dl_path, gid):  # Main codebase version
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
                    BinConfig.FFMPEG_NAME,  # Main uses BinConfig
                    "-hide_banner",
                    "-nostdin",
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
                if input_file.strip().endswith(".video"):  # main
                    ext = "video"
                elif input_file.strip().endswith(".audio"):  # main
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
                    ] and not dl_path.strip().lower().endswith(ext):  # main
                        break
                    new_folder = ospath.splitext(dl_path)[0]
                    name = ospath.basename(dl_path)
                    await makedirs(new_folder, exist_ok=True)
                    file_path = f"{new_folder}/{name}"
                    await move(dl_path, file_path)
                    if not checked:
                        checked = True
                        async with task_dict_lock:
                            task_dict[self.mid] = FFMpegStatus(
                                self, ffmpeg, gid, "FFmpeg"
                            )
                        self.progress = False
                        await cpu_eater_lock.acquire()
                        self.progress = True
                    LOGGER.info(f"Running ffmpeg cmd for: {file_path}")
                    cmd[index + 1] = file_path
                    self.subsize = self.size
                    res = await ffmpeg.ffmpeg_cmds(
                        cmd, file_path
                    )  # ref uses ffmpeg_cmds, main has default_ffmpeg_cmds too
                    if res:
                        if delete_files:
                            await remove(file_path)
                            if len(await listdir(new_folder)) == 1:
                                folder = new_folder.rsplit("/", 1)[0]
                                self.name = ospath.basename(res[0])
                                if self.name.startswith(BinConfig.FFMPEG_NAME):
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
                            ] and not f_path.strip().lower().endswith(ext):  # main
                                continue
                            self.proceed_count += 1
                            var_cmd[index + 1] = f_path
                            if not checked:
                                checked = True
                                async with task_dict_lock:
                                    task_dict[self.mid] = FFMpegStatus(
                                        self, ffmpeg, gid, "FFmpeg"
                                    )
                                self.progress = False
                                await cpu_eater_lock.acquire()
                                self.progress = True
                            LOGGER.info(f"Running ffmpeg cmd for: {f_path}")
                            self.subsize = await get_path_size(f_path)
                            self.subname = file_

                            # Force garbage collection before FFmpeg task
                            gc.collect()

                            res = await ffmpeg.ffmpeg_cmds(
                                var_cmd, f_path
                            )  # ref uses ffmpeg_cmds

                            # Force garbage collection after FFmpeg task
                            gc.collect()

                            if res and delete_files:
                                await remove(f_path)
                                if len(res) == 1:  # main
                                    file_name = ospath.basename(res[0])
                                    if file_name.startswith(BinConfig.FFMPEG_NAME):
                                        newname = file_name.split(".", 1)[-1]
                                        newres = ospath.join(dirpath, newname)
                                        await move(res[0], newres)
        finally:
            if checked:
                cpu_eater_lock.release()
        return dl_path

    async def substitute(self, dl_path):  # Main codebase version
        def perform_swap(original_name, swaps_config):
            # LOGGER.info(
            #     f"NameSwap: Original name received by perform_swap: '{original_name}'"
            # )
            name_part, extension_part = ospath.splitext(original_name)
            # LOGGER.info(
            #     f"NameSwap: Initial name_part: '{name_part}', extension_part: '{extension_part}'"
            # )

            # Process user-defined swaps first
            if swaps_config:
                # LOGGER.info(
                #     f"NameSwap: Processing {len(swaps_config)} user-defined swap rules."
                # )
                for i, swap_config_item in enumerate(
                    swaps_config
                ):  # e.g., swap_config_item is ["pattern", "replacement"] or ["pattern"]
                    # LOGGER.info(
                    #     f"NameSwap: Rule {i + 1}: Raw config item: {swap_config_item}"
                    # )

                    # This is the original parsing logic from the codebase
                    # It correctly assigns pattern, res, cnt_str, sen_str with defaults
                    pattern, res, cnt_str, sen_str = (
                        swap_config_item
                        + ["", "0", "NOFLAG"][min(len(swap_config_item) - 1, 2) :]
                    )[0:4]

                    # Check if this is a simple removal (should escape regex chars) or advanced regex
                    is_simple_removal = (
                        len(swap_config_item) == 1  # Just pattern
                        or (
                            len(swap_config_item) == 2 and swap_config_item[1] == ""
                        )  # Pattern with empty replacement
                    )

                    # For simple removals, escape regex special characters
                    if is_simple_removal:
                        pattern = re.escape(pattern)
                        # Default to case-insensitive for simple removals if no flag specified
                        # Check for default values that indicate no user-specified flag
                        if sen_str in ("NOFLAG", "0", ""):
                            sen_str = "IGNORECASE"

                    # LOGGER.info(
                    #     f"NameSwap: Rule {i + 1}: Parsed -> pattern='{pattern}', res='{res}', cnt_str='{cnt_str}', sen_str='{sen_str}'"
                    # )

                    count = (
                        0 if not cnt_str.isdigit() or cnt_str == "0" else int(cnt_str)
                    )
                    # getattr will default to 0 if sen_str.upper() is not a valid flag name (e.g. for "NOFLAG")
                    regex_flags = getattr(re, sen_str.upper(), 0)
                    # LOGGER.info(
                    #     f"NameSwap: Rule {i + 1}: count={count}, regex_flags={regex_flags}"
                    # )

                    try:
                        # escaped_pattern = re.escape(pattern)
                        # LOGGER.info(
                        #     f"NameSwap: Rule {i + 1}: Escaped pattern: '{escaped_pattern}'"
                        # )
                        # LOGGER.info(
                        #     f"NameSwap: Rule {i + 1}: Name_part BEFORE sub: '{name_part}'"
                        # )
                        name_part_before_sub = name_part
                        name_part = sub(
                            pattern,
                            res,  # replacement string
                            name_part,
                            count,
                            flags=regex_flags,
                        )
                        # LOGGER.info(
                        #     f"NameSwap: Rule {i + 1}: Name_part AFTER sub: '{name_part}'"
                        # )
                        if name_part == name_part_before_sub:
                            pass
                            # LOGGER.info(
                            #     f"NameSwap: Rule {i + 1}: No change made by this rule."
                            # )
                        else:
                            pass
                            # LOGGER.info(
                            #     f"NameSwap: Rule {i + 1}: Change made by this rule."
                            # )

                    except Exception as e:
                        LOGGER.error(
                            f"NameSwap: Rule {i + 1}: Swap Error: pattern: '{pattern}' res: '{res}'. Error: {e}"
                        )
                        return False  # Indicates an error in swapping this name

                    if (
                        len(name_part.encode()) > 255
                    ):  # Check length after each substitution
                        LOGGER.error(
                            f"NameSwap: Rule {i + 1}: Resulting name '{name_part}' is too long after swap for pattern '{pattern}'"
                        )
                        return False
            # else:
            #     LOGGER.info("NameSwap: No user-defined swap rules to process.")

            # Apply generic www removal AFTER specific swaps
            # LOGGER.info(
            #     f"NameSwap: Name_part BEFORE generic www removal: '{name_part}'"
            # )
            name_part_before_www_removal = name_part
            name_part = sub(r"www\S+", "", name_part)
            # LOGGER.info(f"NameSwap: Name_part AFTER generic www removal: '{name_part}'")
            if name_part == name_part_before_www_removal:
                pass
                # LOGGER.info("NameSwap: No change made by generic www removal.")
            else:
                pass
                # LOGGER.info("NameSwap: Change made by generic www removal.")

            final_filename = name_part + extension_part
            # LOGGER.info(f"NameSwap: perform_swap returning: '{final_filename}'")
            return final_filename

        if self.is_file:
            up_dir, current_filename = dl_path.rsplit("/", 1)
            # self.name_swap is the swaps_config
            new_filename_only = perform_swap(current_filename, self.name_swap)

            if not new_filename_only:  # perform_swap returned False due to an error
                LOGGER.error(
                    f"Failed to perform name substitution for {current_filename}. Keeping original name."
                )
                return dl_path  # Return original path if substitution failed

            new_path = ospath.join(up_dir, new_filename_only)
            if dl_path != new_path:  # Only move if name actually changed
                await move(dl_path, new_path)
            return new_path
        else:  # It's a directory
            for dirpath, _, files in await sync_to_async(walk, dl_path, topdown=False):
                for current_filename in files:
                    original_filepath = ospath.join(dirpath, current_filename)
                    # self.name_swap is the swaps_config
                    new_filename_only = perform_swap(current_filename, self.name_swap)

                    if not new_filename_only:  # perform_swap returned False
                        LOGGER.error(
                            f"Failed to perform name substitution for {current_filename} in {dirpath}. Skipping this file."
                        )
                        continue  # Skip this file and proceed with others

                    new_filepath = ospath.join(dirpath, new_filename_only)
                    if (
                        original_filepath != new_filepath
                    ):  # Only move if name actually changed
                        await move(original_filepath, new_filepath)
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

    async def generate_screenshots(self, dl_path):  # Main codebase version
        LOGGER.info(f"Screenshot generation requested for: {dl_path}")
        ss_nb = int(self.screen_shots) if isinstance(self.screen_shots, str) else 10
        LOGGER.info(f"Screenshot count: {ss_nb}")

        # Memory and disk space check before screenshot generation
        try:
            from shutil import disk_usage
            import psutil

            # Check available memory
            available_memory = psutil.virtual_memory().available
            min_required_memory = 200 * 1024 * 1024  # 200MB minimum

            if available_memory < min_required_memory:
                LOGGER.warning(
                    f"Insufficient memory for screenshot generation. Available: {get_readable_file_size(available_memory)}, Required: {get_readable_file_size(min_required_memory)}"
                )
                return dl_path  # Skip screenshot generation

            # Check disk space
            dirp = ospath.dirname(dl_path) if self.is_file else dl_path
            free_space = disk_usage(dirp).free
            min_required_space = 500 * 1024 * 1024  # 500MB minimum

            if free_space < min_required_space:
                LOGGER.warning(
                    f"Insufficient disk space for screenshot generation. Available: {get_readable_file_size(free_space)}, Required: {get_readable_file_size(min_required_space)}"
                )
                return dl_path  # Skip screenshot generation

        except ImportError:
            LOGGER.warning("psutil not available, skipping memory check")
        except Exception as e:
            LOGGER.warning(f"Could not check system resources: {e}")

        if not hasattr(self, "user_dict") or not isinstance(self.user_dict, dict):
            LOGGER.warning("User dict is not properly initialized, creating empty dict")
            self.user_dict = {}

        cmd_ss_grid = getattr(self, "ss_grid", False)
        user_ss_grid = self.user_dict.get("SS_GRID_ENABLED", False)
        ss_grid_enabled = cmd_ss_grid or user_ss_grid

        if isinstance(self.screen_shots, str) and not cmd_ss_grid:
            ss_grid_enabled = False

        if ss_grid_enabled:
            ss_grid_count = 0
            if hasattr(self, "ss_grid_count") and self.ss_grid_count > 0:
                ss_grid_count = self.ss_grid_count
            else:
                ss_grid_count = int(
                    getattr(self, "user_dict", {}).get(
                        "SS_GRID_COUNT",
                        getattr(self, "user_dict", {}).get("SS_GRID_SCREENSHOTS", 9),
                    )
                )
            if hasattr(self, "ss_grid_layout") and self.ss_grid_layout:
                ss_grid_layout = self.ss_grid_layout
            else:
                ss_grid_layout = getattr(self, "user_dict", {}).get(
                    "SS_GRID_LAYOUT", "3x3"
                )
            ss_grid_pdf_mode = getattr(self, "ss_grid_pdf", False) or getattr(
                self, "user_dict", {}
            ).get("SS_GRID_PDF_MODE", False)
            ss_grid_watermark = getattr(self, "ss_grid_watermark", "") or getattr(
                self, "user_dict", {}
            ).get("SS_GRID_WATERMARK", "")
            ss_grid_pdf_individual = self.user_dict.get(
                "SS_GRID_PDF_INDIVIDUAL_PAGES", True
            )
            try:
                import importlib.util

                has_reportlab = importlib.util.find_spec("reportlab") is not None
                if not has_reportlab:
                    raise ImportError("reportlab not available")
            except ImportError as e:
                LOGGER.error(f"Missing required packages for SS Grid: {str(e)}")
                return await take_ss(dl_path, ss_nb)  # Fallback

            if self.is_file:
                if (await get_document_type(dl_path))[0]:
                    ss_output = await get_ss_grid_pdf(
                        dl_path,
                        ss_grid_layout,
                        ss_grid_count,
                        ss_grid_pdf_mode,
                        ss_grid_watermark,
                        ss_grid_pdf_individual,
                    )
                    if ss_output:
                        ext = ospath.splitext(ss_output)[1]
                        output_name = ospath.splitext(dl_path)[0] + f"_ss_grid{ext}"
                        await move(ss_output, output_name)
                        return output_name
            else:  # directory
                for dirpath, _, files in await sync_to_async(
                    walk, dl_path, topdown=False
                ):
                    for file_ in files:
                        f_path = ospath.join(dirpath, file_)
                        if (await get_document_type(f_path))[0]:
                            ss_output = await get_ss_grid_pdf(
                                f_path,
                                ss_grid_layout,
                                ss_grid_count,
                                ss_grid_pdf_mode,
                                ss_grid_watermark,
                                ss_grid_pdf_individual,
                            )
                            if ss_output:
                                ext = ospath.splitext(ss_output)[1]
                                output_name = (
                                    ospath.splitext(file_)[0] + f"_ss_grid{ext}"
                                )
                                await move(ss_output, ospath.join(dirpath, output_name))
                return dl_path
        else:  # Original screenshot functionality from main
            if self.is_file:
                if (await get_document_type(dl_path))[0]:
                    res = await take_ss(dl_path, ss_nb)
                    if res:
                        new_folder = ospath.splitext(dl_path)[0]
                        name = ospath.basename(dl_path)
                        await makedirs(new_folder, exist_ok=True)
                        await gather(
                            move(dl_path, f"{new_folder}/{name}"), move(res, new_folder)
                        )
                        return new_folder
            else:
                for dirpath, _, files in await sync_to_async(
                    walk, dl_path, topdown=False
                ):
                    for file_ in files:
                        f_path = ospath.join(dirpath, file_)
                        if (await get_document_type(f_path))[0]:
                            await take_ss(f_path, ss_nb)
        return dl_path

    async def convert_media(self, dl_path, gid):  # Main codebase version
        fvext = []
        if self.convert_video:
            vdata = self.convert_video.split()
            vext = vdata[0].lower()
            if len(vdata) > 2:
                vstatus = "+" if "+" in vdata[1] else "-" if "-" in vdata[1] else ""
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
                astatus = "+" if "+" in adata[1] else "-" if "-" in adata[1] else ""
                faext.extend(f".{ext.lower()}" for ext in adata[2:])
            else:
                astatus = ""
        else:
            aext = ""
            astatus = ""

        self.files_to_proceed = {}
        all_files = (
            [dl_path]
            if self.is_file
            else [
                ospath.join(dp, f)
                for dp, _, fs in await sync_to_async(walk, dl_path, topdown=False)
                for f in fs
            ]
        )

        for f_path in all_files:
            is_video, is_audio, _ = await get_document_type(f_path)
            path_lower = f_path.strip().lower()
            if (
                is_video
                and vext
                and not path_lower.endswith(f".{vext}")
                and (
                    vstatus == "+"
                    and path_lower.endswith(tuple(fvext))
                    or vstatus == "-"
                    and not path_lower.endswith(tuple(fvext))
                    or not vstatus
                )
            ):
                self.files_to_proceed[f_path] = "video"
            elif (
                is_audio
                and aext
                and not is_video
                and not path_lower.endswith(f".{aext}")
                and (
                    astatus == "+"
                    and path_lower.endswith(tuple(faext))
                    or astatus == "-"
                    and not path_lower.endswith(tuple(faext))
                    or not astatus
                )
            ):
                self.files_to_proceed[f_path] = "audio"

        if self.files_to_proceed:
            # Memory check before video conversion to prevent R14 memory errors
            try:
                import psutil

                available_memory = psutil.virtual_memory().available
                min_memory_mb = 400 * 1024 * 1024  # 400MB minimum for video conversion
                if available_memory < min_memory_mb:
                    LOGGER.warning(
                        f"Low memory available ({available_memory / (1024 * 1024):.1f}MB) for video conversion, may cause memory issues"
                    )
            except ImportError:
                LOGGER.warning("psutil not available, skipping memory check")
            except Exception as e:
                LOGGER.warning(f"Error checking memory: {e}")

            ffmpeg = FFMpeg(self)
            async with task_dict_lock:
                task_dict[self.mid] = FFMpegStatus(self, ffmpeg, gid, "cv")
            self.progress = False
            async with cpu_eater_lock:
                self.progress = True
                for f_path, f_type in self.files_to_proceed.items():
                    self.proceed_count += 1
                    self.subsize = (
                        self.size if self.is_file else await get_path_size(f_path)
                    )
                    self.subname = ospath.basename(f_path) if not self.is_file else ""

                    # Force garbage collection before each conversion
                    gc.collect()

                    res = await (
                        ffmpeg.convert_video(f_path, vext)
                        if f_type == "video"
                        else ffmpeg.convert_audio(f_path, aext)
                    )
                    if res:
                        try:
                            await remove(f_path)
                        except Exception:
                            self.is_cancelled = True
                            return False
                        if self.is_file:
                            return res

                    # Force garbage collection after each conversion
                    gc.collect()

        # Final cleanup after all conversions
        gc.collect()
        return dl_path

    async def generate_sample_video(self, dl_path, gid):  # Enhanced with user settings
        # Get user settings for sample video
        user_dict = getattr(self, "user_dict", {})

        # Check if sample video is enabled in user settings
        if not user_dict.get("SAMPLE_VIDEO_ENABLED", False) and not hasattr(
            self, "sample_video"
        ):
            LOGGER.debug(
                "Sample video not enabled in settings and not requested via command"
            )
            return dl_path

        # Use user settings or command line values
        if hasattr(self, "sample_video") and isinstance(self.sample_video, str):
            # Command line format: duration:part_duration (legacy)
            data = self.sample_video.split(":")
            sample_duration = int(data[0]) if data and data[0] else 60
            part_duration = int(data[1]) if data and len(data) > 1 else 4
        else:
            # Use user settings
            sample_count = user_dict.get("SAMPLE_VIDEO_COUNT", 1)
            clip_duration = user_dict.get("SAMPLE_VIDEO_DURATION", 60)

            # Ensure values are integers to prevent TypeError in arithmetic/comparison operations
            try:
                sample_count = int(sample_count)
            except (ValueError, TypeError):
                sample_count = 1

            try:
                clip_duration = int(clip_duration)
            except (ValueError, TypeError):
                clip_duration = 60

            # Calculate total duration based on count and individual clip duration
            sample_duration = sample_count * clip_duration
            part_duration = clip_duration

        # Enforce memory safety limits on sample duration
        max_sample_duration = 300  # 5 minutes maximum to prevent excessive memory usage
        if sample_duration > max_sample_duration:
            LOGGER.warning(
                f"Sample duration {sample_duration}s exceeds maximum {max_sample_duration}s, "
                "reducing to prevent memory issues"
            )
            sample_duration = max_sample_duration

        # Also limit part duration to reasonable values
        if part_duration > 60:
            LOGGER.warning(
                f"Part duration {part_duration}s too high, limiting to 60s for memory efficiency"
            )
            part_duration = 60
        elif part_duration < 2:
            part_duration = 2  # Minimum 2 seconds to avoid too many tiny segments

        # Check if separate clips are preferred
        separate_clips = user_dict.get("SAMPLE_VIDEO_SEPARATE", False)

        self.files_to_proceed = {}
        if self.is_file and (await get_document_type(dl_path))[0]:
            self.files_to_proceed[dl_path] = ospath.basename(dl_path)
        else:
            for dirpath, _, files in await sync_to_async(walk, dl_path, topdown=False):
                for file_ in files:
                    f_path = ospath.join(dirpath, file_)
                    if (await get_document_type(f_path))[0]:
                        self.files_to_proceed[f_path] = file_

        if self.files_to_proceed:
            # Add disk space check before starting memory-intensive operations
            files_to_skip = []
            for f_path, file_ in self.files_to_proceed.items():
                try:
                    # Check available disk space
                    dirp = ospath.dirname(f_path)
                    free_space = disk_usage(dirp).free
                    video_size = await get_path_size(f_path)

                    # Estimate sample size (conservative estimate: 25% of original)
                    estimated_sample_size = int(video_size * 0.25)
                    required_space = (
                        estimated_sample_size + 100 * 1024 * 1024
                    )  # 100MB buffer

                    if free_space < required_space:
                        LOGGER.warning(
                            f"Skipping sample generation for {file_} due to insufficient disk space. "
                            f"Needed ~{required_space // (1024 * 1024)}MB, available {free_space // (1024 * 1024)}MB"
                        )
                        files_to_skip.append(f_path)
                        continue

                    LOGGER.info(
                        f"Disk space check passed for {file_}: {free_space // (1024 * 1024)}MB available"
                    )
                except Exception as e:
                    LOGGER.warning(f"Could not check disk space for {file_}: {e}")
                    # Continue processing but with caution

            # Remove files that failed disk space check
            for f_path in files_to_skip:
                self.files_to_proceed.pop(f_path, None)

            # Recheck if we have any files left to process after disk space filtering
            if not self.files_to_proceed:
                LOGGER.info(
                    "No files to process for sample video generation after disk space check"
                )
                return dl_path

            # Memory check before sample video generation
            try:
                import psutil

                available_memory = psutil.virtual_memory().available
                min_memory_mb = 250 * 1024 * 1024  # 250MB minimum for sample video
                if available_memory < min_memory_mb:
                    LOGGER.warning(
                        f"Low memory available ({available_memory / (1024 * 1024):.1f}MB) for sample video generation, may cause memory issues"
                    )
            except ImportError:
                LOGGER.warning("psutil not available, skipping memory check")
            except Exception as e:
                LOGGER.warning(f"Error checking memory: {e}")

            ffmpeg = FFMpeg(self)
            async with task_dict_lock:
                task_dict[self.mid] = FFMpegStatus(self, ffmpeg, gid, "sv")
            self.progress = False
            async with cpu_eater_lock:
                self.progress = True
                for f_path, file_ in self.files_to_proceed.items():
                    self.proceed_count += 1
                    self.subsize = (
                        self.size if self.is_file else await get_path_size(f_path)
                    )
                    self.subname = file_ if not self.is_file else ""

                    # Force garbage collection before sample generation
                    gc.collect()

                    # Additional memory check during processing
                    try:
                        dirp = ospath.dirname(f_path)
                        current_free_space = disk_usage(dirp).free
                        if current_free_space < 100 * 1024 * 1024:  # Less than 100MB
                            LOGGER.warning(
                                f"Low disk space detected during processing ({current_free_space // (1024 * 1024)}MB), "
                                "stopping sample generation to prevent system issues"
                            )
                            break
                    except Exception:
                        pass  # Continue processing if space check fails

                    res = await ffmpeg.sample_video(
                        f_path, sample_duration, part_duration
                    )

                    # Force garbage collection after sample generation
                    gc.collect()

                    if res and self.is_file:
                        new_folder = ospath.splitext(f_path)[0]
                        await makedirs(new_folder, exist_ok=True)
                        await gather(
                            move(f_path, f"{new_folder}/{file_}"),
                            move(res, f"{new_folder}/SAMPLE.{file_}"),
                        )
                        return new_folder
        return dl_path

    async def _proceed_compress_impl(self, dl_path, gid):
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
                            task_dict[self.mid] = FFMpegStatus(
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
                                    if await aiopath.exists(base_video):
                                        await remove(base_video)
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
                            task_dict[self.mid] = FFMpegStatus(
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
                                    if await aiopath.exists(base_video):
                                        await remove(base_video)
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
                            task_dict[self.mid] = FFMpegStatus(
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
                task_dict[self.mid] = FFMpegStatus(self, ffmpeg, gid, "Split")
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
