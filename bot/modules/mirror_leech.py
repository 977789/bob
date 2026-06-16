from base64 import b64encode
from re import (
    match as re_match,
    sub as re_sub,
    compile as re_compile,
    escape as re_escape,
    IGNORECASE,
)
from aiofiles.os import path as aiopath
from bot.core.config_manager import Config

from .. import DOWNLOAD_DIR, LOGGER, bot_loop, task_dict_lock, user_data
from ..helper.ext_utils.bot_utils import (
    COMMAND_USAGE,
    arg_parser,
    get_content_type,
    sync_to_async,
)
from ..helper.ext_utils.exceptions import DirectDownloadLinkException
from ..helper.ext_utils.links_utils import (
    is_gdrive_id,
    is_gdrive_link,
    is_mega_link,
    is_magnet,
    is_rclone_path,
    is_telegram_link,
    is_url,
)
from ..helper.ext_utils.task_manager import pre_task_check
from ..helper.ext_utils.nsfw_detector import NSFWDetector
from ..helper.listeners.task_listener import TaskListener
from ..helper.mirror_leech_utils.download_utils.aria2_download import (
    add_aria2_download,
)
from ..helper.mirror_leech_utils.download_utils.direct_downloader import (
    add_direct_download,
)
from .direct_selector import start_direct_select
from ..helper.mirror_leech_utils.download_utils.direct_link_generator import (
    direct_link_generator,
)
from ..helper.mirror_leech_utils.download_utils.gd_download import add_gd_download
from ..helper.mirror_leech_utils.download_utils.jd_download import add_jd_download
from ..helper.mirror_leech_utils.download_utils.mega_download import add_mega_download
from ..helper.mirror_leech_utils.download_utils.nzb_downloader import add_nzb
from ..helper.mirror_leech_utils.download_utils.qbit_download import add_qb_torrent
from ..helper.mirror_leech_utils.download_utils.rclone_download import (
    add_rclone_download,
)
from ..helper.mirror_leech_utils.download_utils.telegram_download import (
    TelegramDownloadHelper,
)
from ..helper.telegram_helper.message_utils import (
    auto_delete_message,
    delete_links,
    delete_message,
    get_tg_link_message,
    send_message,
)
from ..helper.video_utils.selector import SelectMode

# MODULE-LEVEL DEFINITIONS START
COMMON_EXTENSIONS = [
    ".mkv",
    ".mp4",
    ".avi",
    ".mov",
    ".wmv",
    ".flv",
    ".webm",
    ".mpeg",
    ".mpg",
    ".zip",
    ".rar",
    ".7z",
    ".tar.gz",
    ".tar.bz2",
    ".tar.xz",
    ".tar",
    ".gz",
    ".bz2",
    ".xz",
    ".iso",
    ".img",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".tiff",
    ".webp",
    ".mp3",
    ".aac",
    ".flac",
    ".ogg",
    ".wav",
    ".m4a",
    ".srt",
    ".sub",
    ".ass",
    ".vtt",
    ".txt",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".exe",
    ".apk",
    ".dmg",
    ".deb",
    ".rpm",
]
COMMON_EXTENSIONS.sort(
    key=len, reverse=True
)  # Sort by length for multi-part extensions


def extract_filename_from_caption_text(caption_text):
    """
    Extract filename from caption text using safe approach that preserves spaces.
    This function has been updated to address the inconsistent space-to-underscore issue.
    """
    # Use the new unified caption filename extraction
    from bot.helper.ext_utils.safe_filename import safe_caption_filename

    return safe_caption_filename(caption_text)


# MODULE-LEVEL DEFINITIONS END


class Mirror(TaskListener):
    def __init__(
        self,
        client,
        message,
        is_qbit=False,
        is_leech=False,
        is_jd=False,
        is_nzb=False,
        same_dir=None,
        bulk=None,
        vid_mode=None,
        multi_tag=None,
        options="",
    ):
        if same_dir is None:
            same_dir = {}
        if bulk is None:
            bulk = []
        self.message = message
        self.client = client
        self.multi_tag = multi_tag
        self.options = options
        self.same_dir = same_dir
        self.bulk = bulk
        super().__init__()
        self.is_qbit = is_qbit
        self.video_mode = vid_mode
        self.is_leech = is_leech
        self.is_jd = is_jd
        self.is_nzb = is_nzb
        self.user_id = (
            self.message.from_user.id
            if self.message.from_user
            else self.message.sender_chat.id
        )
        self.user_dict = user_data.get(self.user_id, {})

    async def new_event(self):
        try:
            text = (self.message.caption or self.message.text or "").strip()
            if not text and not self.message.reply_to_message:
                await send_message(
                    self.message,
                    "<i>No valid link/files found. Check /help if you don't know how to mirror/leech.</i>",
                )
                return
            self.pmsg = await send_message(
                self.message, "<b><i>Checking Your Request...</i></b>"
            )
            text = self.message.text.split("\n")
            input_list = text[0].split(" ")

            # Temporary parsing for -i and -vt to pass hint to pre_task_check
            early_multi_value = 0
            early_vt_value = False
            try:
                temp_input_list_for_check = text[0].split(" ")
                # Define a schema for the arguments we want to parse early
                early_check_schema = {"-i": 0, "-vt": False}
                # arg_parser will modify early_check_schema in place
                arg_parser(temp_input_list_for_check[1:], early_check_schema)

                i_val_from_parser = early_check_schema.get(
                    "-i"
                )  # This could be an int (if default) or string
                parsed_i_str_for_log = str(i_val_from_parser)  # For logging

                if isinstance(i_val_from_parser, str):
                    # Try to extract just the number part if it's like "2 -m"
                    # Handles cases where arg_parser might be greedy for non-boolean args
                    early_multi_value = int(i_val_from_parser.split()[0])
                elif isinstance(i_val_from_parser, int):
                    # If arg_parser correctly converted to int (e.g. if -i was not present, it's default 0)
                    early_multi_value = i_val_from_parser
                else:
                    # Should not happen if schema default is 0
                    early_multi_value = 0

                early_vt_value = early_check_schema.get("-vt", False)
            except ValueError as e:  # Specific error for int conversion
                LOGGER.warning(
                    f"Early arg parsing for -i failed (ValueError for int conversion of '{parsed_i_str_for_log}'): {e}. Defaulting -i to 0."
                )
                early_multi_value = 0  # Keep vt_value if it was parsed
                # Ensure early_vt_value is retrieved if -i parsing failed but -vt might have been parsed.
                early_vt_value = (
                    early_check_schema.get("-vt", False)
                    if "early_check_schema" in locals()
                    and isinstance(early_check_schema, dict)
                    else False
                )
            except Exception as e:
                LOGGER.warning(
                    f"General early arg parsing for pre-check failed: {e} (i_val: {parsed_i_str_for_log if 'parsed_i_str_for_log' in locals() else 'not parsed'})"
                )
                early_multi_value = 0
                early_vt_value = False

            is_potential_video_merge = early_multi_value >= 2 and early_vt_value

            if is_potential_video_merge:
                self.is_user_limit_exempt = True
            else:
                self.is_user_limit_exempt = False  # Ensure it's defined

            check_msg, check_button = await pre_task_check(
                self.message, is_video_merge_task=is_potential_video_merge
            )
            if check_msg:
                await delete_message(self.pmsg)
                await delete_links(self.message)
                reply_msg = await send_message(self.message, check_msg, check_button)
                await auto_delete_message(self.message, reply_msg)
                await self.remove_from_same_dir()
                return
            args = {
                "-doc": False,
                "-med": False,
                "-d": False,
                "-j": False,
                "-s": False,
                "-b": False,
                "-e": False,
                "-z": False,
                "-sv": False,
                "-ss": False,
                "-f": False,
                "-fd": False,
                "-vt": False,
                "-fu": False,
                "-hl": False,
                "-bt": False,
                "-ut": False,
                "-yt": False,
                "-i": 0,
                "-sp": 0,
                "link": "",
                "-n": "",
                "-m": "",
                "-up": "",
                "-rcf": "",
                "-au": "",
                "-ap": "",
                "-h": "",
                "-t": "",
                "-ca": "",
                "-cv": "",
                "-ns": "",
                "-tl": "",
                "-ff": set(),
                "-ssg": False,  # SS Grid toggle
                "-ssgc": 0,  # SS Grid count
                "-ssgl": "",  # SS Grid layout
                "-ssgp": False,  # SS Grid PDF mode
                "-ssgw": "",  # SS Grid watermark
                "-remname": "",  # Filename pattern removal
            }

            arg_parser(input_list[1:], args)

            if Config.DISABLE_BULK and args.get("-b", False):
                await send_message(
                    self.message, "Bulk downloads are currently disabled."
                )
                return

            if Config.DISABLE_MULTI and int(args.get("-i", 1)) > 1:
                await send_message(
                    self.message,
                    "Multi-downloads are currently disabled. Please try without the -i flag.",
                )
                return

            if Config.DISABLE_SEED and args.get("-d", False):
                await send_message(
                    self.message,
                    "Seeding is currently disabled. Please try without the -d flag.",
                )
                return

            if Config.DISABLE_FF_MODE and args.get("-ff"):
                await send_message(
                    self.message, "FFmpeg commands are currently disabled."
                )
                return

            self.select = args["-s"]
            self.seed = args["-d"]
            self.name = args["-n"]
            self.up_dest = args["-up"]
            self.rc_flags = args["-rcf"]
            self.link = args["link"]
            cmd = input_list[0].split("@")[0]
            self.extract = args["-e"] or "uz" in cmd or "unzip" in cmd
            self.compress = args["-z"] or (
                not self.extract and ("z" in cmd or "zip" in cmd)
            )
            self.join = args["-j"]
            self.thumb = args["-t"]
            self.split_size = args["-sp"]
            # Check for sample video: either from -sv arg or user setting
            if args["-sv"]:
                self.sample_video = True
            else:
                self.sample_video = (self.user_dict or {}).get(
                    "SAMPLE_VIDEO_ENABLED", False
                )
            self.screen_shots = args["-ss"]
            self.force_run = args["-f"]
            self.force_download = args["-fd"]
            self.force_upload = args["-fu"]
            self.convert_audio = args["-ca"]
            self.convert_video = args["-cv"]
            self.name_swap = args["-ns"]
            self.hybrid_leech = args["-hl"]
            self.thumbnail_layout = args["-tl"]
            self.as_doc = args["-doc"]
            self.as_med = args["-med"]
            self.folder_name = (
                f"/{args['-m']}".rstrip("/") if len(args["-m"]) > 0 else ""
            )
            self.bot_trans = args["-bt"]
            self.user_trans = args["-ut"]
            self.remname_patterns = args["-remname"]
            self.is_yt = args["-yt"]
            # SS Grid settings from command line
            self.ss_grid = args["-ssg"]
            self.ss_grid_count = args["-ssgc"]
            self.ss_grid_layout = args["-ssgl"]
            self.ss_grid_pdf = args[
                "-ssgp"
            ]  # Using ss_grid_pdf instead of ss_grid_pdf_mode
            self.ss_grid_watermark = args["-ssgw"]

            # Log SS Grid command line values
            if self.ss_grid:
                LOGGER.info(
                    f"SS Grid enabled from command line with options: count={self.ss_grid_count}, layout={self.ss_grid_layout}, pdf={self.ss_grid_pdf}, watermark={self.ss_grid_watermark}"
                )

            headers = args["-h"]
            vid_tool = args["-vt"]
            is_bulk = args["-b"]

            bulk_start = 0
            bulk_end = 0
            ratio = None
            seed_time = None
            reply_to = None
            # from os import path as ospath # Moved to top-level imports if needed, or ensure it is there.
            # It's already imported as aiopath for async operations, standard ospath might be needed for some sync calls.
            # Let's ensure it's available at the top of the file.

            file_ = None  # Correctly indented within new_event
            session = ""  # Correctly indented within new_event

            # Misplaced COMMON_EXTENSIONS and extract_filename_from_caption_text were here.
            # They are now at module level.
            # The erroneous file_ and session re-declarations after them were removed in the previous step.

            # Import unified filename sanitization functions
            from bot.helper.ext_utils.safe_filename import (
                safe_filename,
                safe_caption_filename,
                ensure_basename_consistency,
            )

            # Legacy compatibility functions that use the new unified approach
            def sanitize_filename(name):
                """Sanitize filename using unified approach that preserves spaces"""
                return safe_filename(name)

            def sanitize_caption_filename(name):
                """Sanitize caption filename using unified approach that preserves spaces"""
                return safe_caption_filename(name)

            try:  # This try should be at the same indentation level as file_ and session assignments
                self.multi = int(args["-i"])
            except Exception:
                self.multi = 0

            try:
                if args["-ff"]:
                    if isinstance(args["-ff"], set):
                        self.ffmpeg_cmds = args["-ff"]
                    else:
                        self.ffmpeg_cmds = eval(args["-ff"])
            except Exception as e:
                self.ffmpeg_cmds = None
                LOGGER.error(e)

            if not isinstance(self.seed, bool):
                dargs = self.seed.split(":")
                ratio = dargs[0] or None
                if len(dargs) == 2:
                    seed_time = dargs[1] or None
                self.seed = True

            if not isinstance(is_bulk, bool):
                dargs = is_bulk.split(":")
                bulk_start = dargs[0] or 0
                if len(dargs) == 2:
                    bulk_end = dargs[1] or 0
                is_bulk = True

            if not is_bulk:
                if self.multi > 0:
                    if self.folder_name:
                        async with task_dict_lock:
                            if self.folder_name in self.same_dir:
                                self.same_dir[self.folder_name]["tasks"].add(self.mid)
                                for fd_name in self.same_dir:
                                    if fd_name != self.folder_name:
                                        self.same_dir[fd_name]["total"] -= 1
                            elif self.same_dir:
                                self.same_dir[self.folder_name] = {
                                    "total": self.multi,
                                    "tasks": {self.mid},
                                }
                                for fd_name in self.same_dir:
                                    if fd_name != self.folder_name:
                                        self.same_dir[fd_name]["total"] -= 1
                            else:
                                self.same_dir = {
                                    self.folder_name: {
                                        "total": self.multi,
                                        "tasks": {self.mid},
                                    }
                                }
                elif self.same_dir:
                    async with task_dict_lock:
                        for fd_name in self.same_dir:
                            self.same_dir[fd_name]["total"] -= 1
            else:
                if vid_tool and not self.video_mode and self.same_dir:
                    self.video_mode = await SelectMode(self).get_buttons()
                    if not self.video_mode:
                        return
                await self.init_bulk(input_list, bulk_start, bulk_end, Mirror)
                return

            if len(self.bulk) != 0:
                del self.bulk[0]

            if vid_tool and (not self.video_mode or not self.same_dir):
                self.video_mode = await SelectMode(self).get_buttons()
                if not self.video_mode:
                    await self.remove_from_same_dir()
                    return

            await self.run_multi(input_list, Mirror)

            await self.get_tag(text)

            path = f"{DOWNLOAD_DIR}{self.mid}{self.folder_name}"

            if not self.link and (reply_to := self.message.reply_to_message):
                if reply_to.text:
                    self.link = reply_to.text.split("\n", 1)[0].strip()

            user_id = (
                self.message.from_user.id
                if self.message.from_user
                else self.message.sender_chat.id
            )

            # NSFW Content Detection
            if Config.NSFW_DETECTION_ENABLED:
                try:
                    # Check for NSFW content in URL and filename
                    filename_for_check = ""
                    if (
                        reply_to
                        and reply_to.document
                        and hasattr(reply_to.document, "file_name")
                    ):
                        filename_for_check = reply_to.document.file_name or ""
                    elif self.name:
                        filename_for_check = self.name

                    is_nsfw, nsfw_reason = NSFWDetector.is_nsfw_content(
                        self.link or "", filename_for_check
                    )

                    if is_nsfw:
                        content_category = NSFWDetector.get_content_category(
                            self.link or "", filename_for_check
                        )
                        LOGGER.warning(
                            f"NSFW content blocked for user {user_id}: {nsfw_reason}"
                        )

                        await delete_message(self.pmsg)
                        error_msg = (
                            f"🚫 <b>Content Blocked</b>\n\n"
                            f"<b>Category:</b> <code>{content_category}</code>\n"
                            f"<b>Reason:</b> <code>{nsfw_reason}</code>\n\n"
                            f"<i>NSFW detection is enabled to prevent inappropriate content.</i>\n\n"
                            f"cc: {self.tag}"
                        )
                        tmsg = await send_message(self.message, error_msg)
                        await auto_delete_message(self.message, tmsg)
                        await self.remove_from_same_dir()
                        return

                except Exception as e:
                    LOGGER.error(f"Error in NSFW detection: {e}")
                    # Continue processing if NSFW detection fails
                    pass
            user_dict = user_data.get(user_id, {})
            filename_source_setting = user_dict.get(
                "FILENAME_SOURCE", Config.FILENAME_SOURCE
            )

            if is_telegram_link(self.link):
                try:
                    reply_to, session = await get_tg_link_message(self.link)
                except Exception as e:
                    e = str(e)
                    await delete_message(self.pmsg)
                    if "group" in e:
                        tmsg = await send_message(
                            self.message,
                            f"ERROR: This is a TG invite link.\nUse media links to download.\n\ncc: {self.tag}",
                        )
                    tmsg = await send_message(
                        self.message, f"ERROR: {e}\n\ncc: {self.tag}"
                    )
                    await auto_delete_message(self.message, tmsg)
                    await self.remove_from_same_dir()
                    return

            if isinstance(reply_to, list):
                self.bulk = reply_to
                b_msg = input_list[:1]
                self.options = " ".join(input_list[1:])
                b_msg.append(f"{self.bulk[0]} -i {len(self.bulk)} {self.options}")
                nextmsg = await send_message(self.message, " ".join(b_msg))
                nextmsg = await self.client.get_messages(
                    chat_id=self.message.chat.id, message_ids=nextmsg.id
                )
                if self.message.from_user:
                    nextmsg.from_user = self.message.from_user
                else:
                    nextmsg.sender_chat = self.message.sender_chat
                await Mirror(
                    self.client,
                    nextmsg,
                    self.is_qbit,
                    self.is_leech,
                    self.is_jd,
                    self.is_nzb,
                    self.same_dir,
                    self.bulk,
                    self.video_mode,
                    self.multi_tag,
                    self.options,
                ).new_event()
                return

            if reply_to:
                file_ = (
                    reply_to.document
                    or reply_to.photo
                    or reply_to.video
                    or reply_to.audio
                    or reply_to.voice
                    or reply_to.video_note
                    or reply_to.sticker
                    or reply_to.animation
                    or None
                )
                self.file_details = {
                    "caption": reply_to.caption
                }  # Original caption stored

                if not self.name:  # Only proceed if -n is not used
                    if filename_source_setting == "caption" and reply_to.caption:
                        cap_name = reply_to.caption.strip()
                        if cap_name:  # Ensure caption is not empty after stripping
                            extracted_name = extract_filename_from_caption_text(
                                cap_name
                            )
                            self.name = sanitize_caption_filename(extracted_name)

                    if (
                        not self.name
                        and file_
                        and hasattr(file_, "file_name")
                        and file_.file_name
                    ):
                        # Fallback to file_name if caption not used or empty, or if filename_source is 'filename'
                        self.name = sanitize_filename(file_.file_name)

                if file_ is None:
                    if reply_text := reply_to.text:
                        self.link = reply_text.split("\n", 1)[0].strip()
                    else:
                        reply_to = None
                elif reply_to.document and (
                    file_.mime_type == "application/x-bittorrent"
                    or (
                        hasattr(file_, "file_name")
                        and file_.file_name
                        and file_.file_name.endswith((".torrent", ".dlc", ".nzb"))
                    )
                ):
                    # If it's a torrent/dlc/nzb file, self.name (if derived from caption) might not be suitable for the .torrent file itself.
                    # The content of the torrent will have its own name.
                    # Here, self.link becomes the path to the downloaded .torrent file.
                    # The original file_.file_name is more relevant for the torrent file itself.
                    torrent_file_name = (
                        sanitize_filename(file_.file_name)
                        if hasattr(file_, "file_name") and file_.file_name
                        else "downloaded.torrent"
                    )
                    self.link = await reply_to.download(file_name=torrent_file_name)
                    # self.name might be folder name for torrent contents, so we don't reset it here if already set by caption.
                    file_ = None

            if (
                not self.link
                and file_ is None
                or is_telegram_link(self.link)
                and reply_to is None
                or file_ is None
                and not is_url(self.link)
                and not is_magnet(self.link)
                and not await aiopath.exists(self.link)
                and not is_rclone_path(self.link)
                and not is_gdrive_id(self.link)
                and not is_gdrive_link(self.link)
                and not is_mega_link(self.link)
            ):
                await send_message(
                    self.message, COMMAND_USAGE["mirror"][0], COMMAND_USAGE["mirror"][1]
                )
                await self.remove_from_same_dir()
                await delete_links(self.message)
                return

            if len(self.link) > 0:
                LOGGER.info(self.link)

            bmsg = None
            if "youtube.com" in self.link or "youtu.be" in self.link:
                bmsg = "ERROR: Use ytdl cmds for Youtube links"
            if bmsg:
                await delete_message(self.pmsg)
                tmsg = await send_message(self.message, bmsg)
                await auto_delete_message(self.message, tmsg)
                return

            try:
                await self.before_start()
            except Exception as e:
                LOGGER.error(f"Error in before_start: {e}", exc_info=True)
                await send_message(self.message, f"<b>Error:</b> {e}")
                await self.remove_from_same_dir()
                await delete_links(self.message)
                return

            self._set_mode_engine()

            if (
                not self.is_jd
                and not self.is_nzb
                and not self.is_qbit
                and not is_magnet(self.link)
                and not is_rclone_path(self.link)
                and not is_gdrive_link(self.link)
                and not self.link.endswith(".torrent")
                and file_ is None
                and not is_gdrive_id(self.link)
                and not is_mega_link(self.link)
            ):
                content_type = await get_content_type(self.link)
                if content_type is None or re_match(
                    r"text/html|text/plain", content_type
                ):
                    try:
                        self.link = await sync_to_async(
                            direct_link_generator, self.link
                        )
                        if isinstance(self.link, tuple):
                            self.link, headers = self.link
                        elif isinstance(self.link, str):
                            LOGGER.info(f"Generated link: {self.link}")
                    except DirectDownloadLinkException as e:
                        e = str(e)
                        if "This link requires a password!" not in e:
                            LOGGER.info(e)
                        if e.startswith("ERROR:"):
                            await send_message(self.message, e)
                            await self.remove_from_same_dir()
                            await delete_links(self.message)
                            return
                    except Exception as e:
                        await send_message(self.message, e)
                        await self.remove_from_same_dir()
                        await delete_links(self.message)
                        return

            await delete_links(self.message)
            await delete_message(self.pmsg)

            if file_ is not None:
                await TelegramDownloadHelper(self).add_download(
                    reply_to, f"{path}/", session
                )
            elif isinstance(self.link, dict):
                if self.select and await start_direct_select(self, self.link, path):
                    return
                await add_direct_download(self, path)
            elif self.is_jd:
                await add_jd_download(self, path)
            elif self.is_qbit:
                await add_qb_torrent(self, path, ratio, seed_time)
            elif self.is_nzb:
                await add_nzb(self, path)
            elif is_rclone_path(self.link):
                await add_rclone_download(self, f"{path}/")
            elif is_gdrive_link(self.link) or is_gdrive_id(self.link):
                await add_gd_download(self, path)
            elif is_mega_link(self.link):
                await add_mega_download(self, f"{path}/")
            else:
                ussr = args["-au"]
                pssw = args["-ap"]
                if ussr or pssw:
                    auth = f"{ussr}:{pssw}"
                    headers += f" authorization: Basic {b64encode(auth.encode()).decode('ascii')}"
                await add_aria2_download(self, path, headers, ratio, seed_time)
            await delete_message(self.pmsg)
        except Exception as e:
            LOGGER.error(f"Mirror.new_event error: {e}")
            await delete_message(self.pmsg)
            await send_message(
                self.message, f"<i>Unexpected error. See /help for usage.</i>"
            )


async def mirror(client, message):
    bot_loop.create_task(Mirror(client, message).new_event())


async def qb_mirror(client, message):
    bot_loop.create_task(Mirror(client, message, is_qbit=True).new_event())


async def jd_mirror(client, message):
    bot_loop.create_task(Mirror(client, message, is_jd=True).new_event())


async def nzb_mirror(client, message):
    bot_loop.create_task(Mirror(client, message, is_nzb=True).new_event())


async def leech(client, message):
    if Config.DISABLE_LEECH:
        await message.reply("The Leech command is currently disabled.")
        return
    bot_loop.create_task(Mirror(client, message, is_leech=True).new_event())


async def qb_leech(client, message):
    bot_loop.create_task(
        Mirror(client, message, is_qbit=True, is_leech=True).new_event()
    )


async def jd_leech(client, message):
    bot_loop.create_task(Mirror(client, message, is_leech=True, is_jd=True).new_event())


async def nzb_leech(client, message):
    bot_loop.create_task(
        Mirror(client, message, is_leech=True, is_nzb=True).new_event()
    )
