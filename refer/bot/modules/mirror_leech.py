from base64 import b64encode
from re import match as re_match
import os
import uuid
from datetime import datetime

from aiofiles.os import path as aiopath
from bot.core.config_manager import Config
from ..helper.ext_utils.nsfw_detector import NSFWDetector

from .. import DOWNLOAD_DIR, LOGGER, bot_loop, task_dict_lock
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
from ..helper.listeners.task_listener import TaskListener
from ..helper.mirror_leech_utils.download_utils.aria2_download import (
    add_aria2_download,
)
from ..helper.mirror_leech_utils.download_utils.direct_downloader import (
    add_direct_download,
)
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
    get_tg_link_message,
    send_message,
)
from ..helper.telegram_helper.sticker_utils import send_start_sticker
from ..helper.ext_utils.video_tools_selector import VideoToolsSelector
from ..helper.common import multi_video_tools_selection


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
        self.is_leech = is_leech
        self.is_jd = is_jd
        self.is_nzb = is_nzb

    async def new_event(self):
        text = self.message.text.split("\n")
        input_list = text[0].split(" ")

        check_msg, check_button = await pre_task_check(self.message)
        if check_msg:
            await delete_links(self.message)
            await auto_delete_message(
                await send_message(self.message, check_msg, check_button)
            )
            return
        # Send a start sticker (if configured) when a valid command is initiated
        try:
            await send_start_sticker(self.message)
        except Exception:
            pass
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
            "-fu": False,
            "-hl": False,
            "-bt": False,
            "-ut": False,
            "-yt": False,
            "-ft": False,  # Force video tools
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
            await send_message(self.message, "Bulk downloads are currently disabled.")
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
            await send_message(self.message, "FFmpeg commands are currently disabled.")
            return

        self.select = args["-s"]
        self.seed = args["-d"]
        self.name = args["-n"]
        self.up_dest = args["-up"]
        self.rc_flags = args["-rcf"]
        self.link = args["link"]
        self.compress = args["-z"]
        self.extract = args["-e"]
        self.join = args[
            "-j"
        ]  # If we're returning from a thumbnail upload, don't overwrite self.thumb
        if not getattr(self, "returning_from_thumbnail", False):
            self.thumb = args["-t"]
            # Only prompt if -t is actually present in the command
            if "-t" in input_list and self.thumb == "":
                await self.request_thumbnail()
                return

        self.split_size = args["-sp"]
        self.sample_video = args["-sv"]
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
        self.folder_name = f"/{args['-m']}".rstrip("/") if len(args["-m"]) > 0 else ""
        self.bot_trans = args["-bt"]
        self.user_trans = args["-ut"]
        self.remname_patterns = args["-remname"]
        self.is_yt = args["-yt"]
        self.force_video_tools = args["-ft"]
        self.selected_video_tools = set()  # Will be populated by video tools selector
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

        self.headers = args["-h"]
        self.ussr = args["-au"]
        self.pssw = args["-ap"]
        is_bulk = args["-b"]

        bulk_start = 0
        bulk_end = 0
        ratio = None
        seed_time = None
        reply_to = None
        file_ = None
        session = ""

        try:
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
            self.ratio = dargs[0] or None
            if len(dargs) == 2:
                self.seed_time = dargs[1] or None
            self.seed = True
        else:
            self.ratio = None
            self.seed_time = None

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
            await self.init_bulk(input_list, bulk_start, bulk_end, Mirror)
            return

        if len(self.bulk) != 0:
            del self.bulk[0]

        await self.run_multi(input_list, Mirror)

        await self.get_tag(text)

        path = f"{DOWNLOAD_DIR}{self.mid}{self.folder_name}"

        if not self.link and (reply_to := self.message.reply_to_message):
            if reply_to.text:
                self.link = reply_to.text.split("\n", 1)[0].strip()
        if is_telegram_link(self.link):
            try:
                req_uid = self.message.from_user.id if self.message.from_user else None
                reply_to, session = await get_tg_link_message(
                    self.link, request_user_id=req_uid
                )
            except Exception as e:
                await send_message(self.message, f"ERROR: {e}")
                await self.remove_from_same_dir()
                await delete_links(self.message)
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
                nextmsg.from_user = self.user
            else:
                nextmsg.sender_chat = self.user
            await Mirror(
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
            self.file_details = {"caption": reply_to.caption}

            if file_ is None:
                if reply_text := reply_to.text:
                    self.link = reply_text.split("\n", 1)[0].strip()
                else:
                    reply_to = None
            elif reply_to.document and (
                file_.mime_type == "application/x-bittorrent"
                or file_.file_name.endswith((".torrent", ".dlc", ".nzb"))
            ):
                self.link = await reply_to.download()
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
                self.message, "There are no links or files found. Please try again."
            )
            await self.remove_from_same_dir()
            await delete_links(self.message)
            return

        if len(self.link) > 0:
            LOGGER.info(self.link)

        # Anti-NSFW content detection
        if Config.ANTI_NSFW:
            LOGGER.info(
                f"Anti-NSFW check enabled. Checking content for user {self.user_id}"
            )

            # Check the main link and name
            is_nsfw, nsfw_reason = NSFWDetector.is_nsfw_content(self.link, self.name)
            LOGGER.info(
                f"Initial NSFW check - Link: '{self.link}', Name: '{self.name}' - Result: {is_nsfw}"
            )

            # Also check file name if we have a file
            if (
                not is_nsfw
                and file_
                and hasattr(file_, "file_name")
                and file_.file_name
            ):
                is_nsfw, nsfw_reason = NSFWDetector.is_nsfw_content("", file_.file_name)
                LOGGER.info(
                    f"File name NSFW check - Filename: '{file_.file_name}' - Result: {is_nsfw}"
                )

            # Check caption if we have one
            if (
                not is_nsfw
                and hasattr(self, "file_details")
                and self.file_details.get("caption")
            ):
                is_nsfw, nsfw_reason = NSFWDetector.is_nsfw_content(
                    self.file_details["caption"], ""
                )
                LOGGER.info(
                    f"Caption NSFW check - Caption: '{self.file_details['caption']}' - Result: {is_nsfw}"
                )

            if is_nsfw:
                LOGGER.warning(
                    f"NSFW content detected from user {self.user_id}: {self.link}"
                )
                LOGGER.warning(f"Detection reason: {nsfw_reason}")

                # Notify owner if enabled
                if Config.NSFW_NOTIFY_OWNER:
                    LOGGER.info(
                        "NSFW_NOTIFY_OWNER is enabled, sending notifications..."
                    )
                    await self._notify_owner_nsfw_violation(nsfw_reason)
                else:
                    LOGGER.info(
                        "NSFW_NOTIFY_OWNER is disabled, skipping owner notification"
                    )

                # Send warning message to user
                category = NSFWDetector.get_content_category(self.link, self.name)
                await send_message(
                    self.message,
                    f"🚫 <b>Content Blocked</b>\n\n"
                    f"Your request has been blocked as it appears to contain adult content.\n\n"
                    f"<b>Category:</b> {category}\n"
                    f"<b>Reason:</b> {nsfw_reason}\n\n"
                    f"Please ensure you're only sharing appropriate content.",
                )

                # Clean up and return early
                await self.remove_from_same_dir()
                await delete_links(self.message)
                return
            else:
                LOGGER.info(f"Content passed NSFW check for user {self.user_id}")
        else:
            LOGGER.info("Anti-NSFW feature is disabled")

        try:
            await self.before_start()
        except Exception as e:
            await send_message(self.message, e)
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
            if content_type is None or re_match(r"text/html|text/plain", content_type):
                try:
                    self.link = await sync_to_async(direct_link_generator, self.link)
                    if isinstance(self.link, tuple):
                        self.link, headers = self.link
                        LOGGER.info(f"Generated link with headers: {self.link}")
                        LOGGER.info(f"Headers from direct link generator: {headers}")
                        # Store headers in self for later use
                        self.headers = headers
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

        # Check for video tools - either from -ft flag or stored selection from multi-download
        video_tools_needed = self.force_video_tools

        # Also check if there's a stored selection for this multi-download (even without -ft flag)
        if (
            not video_tools_needed
            and self.multi_tag
            and self.multi_tag in multi_video_tools_selection
        ):
            video_tools_needed = True
            LOGGER.info(
                f"[DEBUG-VT] Found stored video tools selection for multi-download {self.multi_tag}, enabling video tools processing"
            )

        # Show video tools selector if -ft flag is used, but only if we don't already have a selection for this multi-download
        if video_tools_needed:
            LOGGER.info(
                f"[DEBUG-VT] Video tools processing enabled. Multi-tag: {self.multi_tag}, Current selections: {list(multi_video_tools_selection.keys())}"
            )

            # Check if video tools selection has already been done for this multi-download
            if self.multi_tag and self.multi_tag in multi_video_tools_selection:
                # Use the previously selected video tools without showing the menu again
                self.selected_video_tools = multi_video_tools_selection[self.multi_tag]
                LOGGER.info(
                    f"[DEBUG-VT] ✅ Using previously selected video tools for multi-download {self.multi_tag}: {self.selected_video_tools}"
                )
            elif self.force_video_tools:
                # Only show video tools selector if -ft flag was explicitly used
                LOGGER.info(
                    f"[DEBUG-VT] 📝 Showing video tools selector for the first time. Multi-tag: {self.multi_tag}"
                )

                # For multi-downloads, we might not have the multi_tag yet on the first call
                # Store a temporary selection that will be moved to the proper multi_tag later
                from time import time

                temp_key = f"temp_{self.user_id}_{int(time())}"
                LOGGER.info(f"[DEBUG-VT] 📝 Using temp key: {temp_key}")

                # Show video tools selector for the first time
                video_selector = VideoToolsSelector(self, self.user_id)
                # Store the temp key for later use
                video_selector.temp_key = temp_key
                success = await video_selector.show_selection_menu()
                if not success:
                    # User cancelled or no tools available
                    LOGGER.info(
                        f"[DEBUG-VT] ❌ Video tools selector failed or cancelled"
                    )
                    await self.remove_from_same_dir()
                    return
                # Return early - the callback will handle continuing the download process
                LOGGER.info(
                    f"[DEBUG-VT] 🔄 Video tools selector shown, waiting for user selection..."
                )
                return
            else:
                # This shouldn't happen, but just in case
                LOGGER.warning(
                    f"[DEBUG-VT] ⚠️ Video tools needed but no -ft flag and no stored selection for {self.multi_tag}"
                )
                self.selected_video_tools = set()

        # Continue with download process
        if file_ is not None:
            await TelegramDownloadHelper(self).add_download(
                reply_to, f"{path}/", session
            )
        elif isinstance(self.link, dict):
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
            # Use headers from self.headers (which may include headers from direct_link_generator)
            headers = self.headers or ""
            LOGGER.info(f"Using headers for aria2 download: {headers}")
            if ussr or pssw:
                auth = f"{ussr}:{pssw}"
                headers += (
                    f" authorization: Basic {b64encode(auth.encode()).decode('ascii')}"
                )
            await add_aria2_download(self, path, headers, ratio, seed_time)

    async def _notify_owner_nsfw_violation(self, reason: str):
        """Notify the owner and sudo users about NSFW content violation"""
        try:
            from ..core.tg_client import TgClient
            from datetime import datetime
            from .. import sudo_users
            from pyrogram.enums import ParseMode

            # Get user information
            user = (
                self.message.from_user
                if self.message.from_user
                else self.message.sender_chat
            )
            user_id = user.id
            user_name = getattr(user, "first_name", "Unknown")
            user_last_name = getattr(user, "last_name", "")
            username = getattr(user, "username", "No username")

            # Build full name
            full_name = f"{user_name} {user_last_name}".strip()

            # Get file information if available
            file_info = ""
            if hasattr(self, "message") and self.message.reply_to_message:
                reply = self.message.reply_to_message
                if reply.document:
                    file_info = f"\n<b>File Name:</b> {reply.document.file_name}"
                elif reply.photo:
                    file_info = f"\n<b>Content Type:</b> Photo"
                elif reply.video:
                    file_info = f"\n<b>Content Type:</b> Video"
                elif reply.audio:
                    file_info = f"\n<b>Content Type:</b> Audio"

                # Add caption if available
                if reply.caption:
                    file_info += f"\n<b>Caption:</b> {reply.caption[:200]}..."

            # Format violation message
            violation_msg = (
                f"🚨 <b>NSFW Content Violation Detected</b>\n\n"
                f"<b>User ID:</b> <code>{user_id}</code>\n"
                f"<b>Name:</b> {full_name}\n"
                f"<b>Username:</b> @{username}\n"
                f"<b>Chat:</b> {self.message.chat.title or 'Private Chat'} (<code>{self.message.chat.id}</code>)\n"
                f"<b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"{file_info}\n\n"
                f"<b>Attempted Link:</b>\n<code>{self.link}</code>\n\n"
                f"<b>Detection Reason:</b> {reason}\n\n"
                f"<b>Category:</b> {NSFWDetector.get_content_category(self.link, self.name)}\n\n"
                f"<b>Action:</b> Task automatically cancelled and user notified."
            )

            # Collect all notification targets (owner + sudo users)
            notification_targets = []

            # Add owner
            if Config.OWNER_ID:
                notification_targets.append(Config.OWNER_ID)

            # Add sudo users
            if sudo_users:
                notification_targets.extend(sudo_users)

            # Remove duplicates (in case owner is also in sudo users)
            notification_targets = list(set(notification_targets))

            # Send notification to all targets
            successful_notifications = 0
            failed_notifications = 0

            for target_id in notification_targets:
                try:
                    await TgClient.bot.send_message(
                        chat_id=target_id, text=violation_msg, parse_mode=ParseMode.HTML
                    )
                    successful_notifications += 1
                    LOGGER.info(
                        f"NSFW violation notification sent to {target_id} for user {user_id}"
                    )
                except Exception as e:
                    failed_notifications += 1
                    LOGGER.error(
                        f"Failed to send NSFW notification to {target_id}: {e}"
                    )

            LOGGER.info(
                f"NSFW violation notifications: {successful_notifications} successful, {failed_notifications} failed"
            )

        except Exception as e:
            LOGGER.error(f"Failed to notify about NSFW violation: {e}")

    async def continue_download(self):
        """Continue the download process after video tools selection"""
        path = f"{DOWNLOAD_DIR}{self.mid}{self.folder_name}"

        # Get args for download methods
        args = {
            "-au": self.ussr,
            "-ap": self.pssw,
        }

        reply_to = None
        session = ""
        file_ = None

        # Check if we have a telegram file to download
        if self.message.reply_to_message:
            reply_to = self.message.reply_to_message
            if reply_to.document or reply_to.photo or reply_to.video or reply_to.audio:
                file_ = reply_to

        if file_ is not None:
            await TelegramDownloadHelper(self).add_download(
                reply_to, f"{path}/", session
            )
        elif isinstance(self.link, dict):
            await add_direct_download(self, path)
        elif self.is_jd:
            await add_jd_download(self, path)
        elif self.is_qbit:
            await add_qb_torrent(self, path, self.ratio, self.seed_time)
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
            # Use headers from self.headers (which may include headers from direct_link_generator)
            headers = self.headers or ""
            LOGGER.info(f"Using headers for continue_download aria2: {headers}")
            if ussr or pssw:
                auth = f"{ussr}:{pssw}"
                headers += (
                    f" authorization: Basic {b64encode(auth.encode()).decode('ascii')}"
                )
            await add_aria2_download(self, path, headers, self.ratio, self.seed_time)

    async def request_thumbnail(self):
        """Request user to upload a thumbnail image when -t is provided without URL"""
        # Set flag to avoid infinite loop
        self.returning_from_thumbnail = True
        self.original_message = self.message

        msg = await send_message(
            self.message,
            "You've used the `-t` flag without providing an image URL.\n\nPlease send an image that will be used as thumbnail.",
        )

        # Store message ID for future reference
        self.thumb_request_msg_id = msg.id

        # Import the thumbnail_waiters dictionary
        from ..helper.ext_utils.task_manager import thumbnail_waiters

        # We'll use user_id as key to find this object when user replies
        async with task_dict_lock:
            thumbnail_waiters[self.user_id] = self


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


async def handle_thumbnail_upload(client, message):
    """Handle when a user uploads a thumbnail in response to the request"""
    user_id = message.from_user.id

    from ..helper.ext_utils.task_manager import thumbnail_waiters

    # Use the lock to access the shared dictionary
    async with task_dict_lock:
        if user_id not in thumbnail_waiters:
            return

        mirror_obj = thumbnail_waiters[user_id]

        # Remove from waiters dict
        thumbnail_waiters.pop(user_id)
    # Check if the message contains a photo
    if message.photo:
        # Create thumbnails directory if it doesn't exist
        os.makedirs("thumbnails", exist_ok=True)

        # Generate unique filename
        file_id = f"{user_id}.jpg"
        thumb_path = f"thumbnails/{file_id}"

        # Download the photo
        await message.download(file_name=thumb_path)

        # Update the mirror object with the thumbnail path
        mirror_obj.thumb = thumb_path  # Inform user with auto-deletion after 5 seconds
        status_msg = await send_message(
            message,
            f"✅ Thumbnail set successfully! Continuing with your request...",
        )

        # Auto-delete the status message after 5 seconds
        from ..helper.telegram_helper.message_utils import auto_delete_message

        await auto_delete_message(status_msg, stime=5)

        # Delete the user's uploaded image message
        try:
            await client.delete_messages(
                chat_id=message.chat.id, message_ids=message.id
            )
        except Exception as e:
            LOGGER.error(f"Error deleting user's thumbnail image message: {e}")
        # Delete the thumbnail request message
        if hasattr(mirror_obj, "thumb_request_msg_id"):
            try:
                await client.delete_messages(
                    chat_id=message.chat.id, message_ids=mirror_obj.thumb_request_msg_id
                )
            except Exception as e:
                LOGGER.error(f"Error deleting thumbnail request message: {e}")

        # Also delete the original command message if it's in the same chat
        if (
            hasattr(mirror_obj, "original_message")
            and mirror_obj.original_message.chat.id == message.chat.id
        ):
            try:
                # Keep the original command message but delete our follow-up request
                pass
            except Exception as e:
                LOGGER.error(
                    f"Error deleting original message: {e}"
                )  # Set the thumb directly
        mirror_obj.message = mirror_obj.original_message
        mirror_obj.thumb = thumb_path

        # Set a flag to bypass the thumbnail check in new_event
        mirror_obj.returning_from_thumbnail = True

        # Check if this is for a YouTube download
        if hasattr(mirror_obj, "yt_obj"):
            # Set the thumb to the YouTube object too
            mirror_obj.yt_obj.thumb = thumb_path
            mirror_obj.yt_obj.returning_from_thumbnail = True
            mirror_obj.yt_obj.message = mirror_obj.original_message
            # Continue with YouTube processing
            await mirror_obj.yt_obj.new_event()
        else:
            # Continue with mirror processing
            await mirror_obj.new_event()
    else:
        await send_message(
            message,
            "❌ That's not a valid image. Please send an image file to use as thumbnail.",
        )
