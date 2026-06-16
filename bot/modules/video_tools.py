from asyncio import gather
from secrets import token_urlsafe
import gc  # Added for memory management
import os
import re

from aiofiles.os import path as aiopath, makedirs
from pyrogram import Client
from ..helper.ext_utils.task_manager import pre_task_check
from .. import LOGGER
from ..core.tg_client import TgClient
from ..core.config_manager import Config
from ..helper.ext_utils.bot_utils import new_task, arg_parser
from ..helper.ext_utils.db_handler import database
from ..helper.ext_utils.links_utils import is_url, get_link
from ..helper.ext_utils.media_utils import get_meta_video
from ..helper.ext_utils.files_utils import get_path_sizee as get_path_size
from ..helper.listeners.task_listener import TaskListener
from ..helper.telegram_helper.filters import CustomFilters
from ..helper.telegram_helper.message_utils import (
    send_messagee as send_message,
    edit_messagee as edit_message,
    delete_message,
    delete_links,
    auto_delete_message,
)
from ..helper.telegram_helper.sticker_utils import (
    send_start_sticker,
    send_success_sticker,
    send_error_sticker,
)
from ..helper.video_utils.executor import VideoToolsExecutor
from ..helper.ext_utils.video_tools_selector import VideoToolsSelector
from ..helper.video_utils.selector import SelectMode


class VideoTools(TaskListener):
    def __init__(
        self,
        client: Client,
        message,
        _=False,
        __=False,
        is_leech=False,
        ___=None,
        ____=None,
        bulk=None,
        multi_tag=None,
        options="",
    ):
        if bulk is None:
            bulk = []
        self.message = message
        self.client = client
        self.same_dir = {}
        self.multi_tag = multi_tag
        self.options = options
        self.bulk = bulk
        super().__init__()
        self.is_leech = is_leech
        # Memory management
        self._temp_files = []
        self._cleanup_tasks = []

    def __del__(self):
        """Cleanup when object is destroyed"""
        try:
            # Cleanup temporary files
            for temp_file in self._temp_files:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
        except Exception:
            pass

    async def _cleanup_resume_data(self, task_type: str = ""):
        """
        Clean up auto-resume data for video tools tasks.

        Args:
            task_type: Type of task completion (e.g., "cancelled", "no upload", "with upload")
                      Used for logging purposes only.
        """
        if not (
            Config.INCOMPLETE_TASK_NOTIFIER and Config.DATABASE_URL and self.message
        ):
            return

        try:
            # Remove from tasks collection (for supergroup/channel only)
            if self.is_super_chat:
                await database.rm_complete_task(self.message.link)

            # Remove from resume_tasks collection (for all chats)
            if (
                database.db
                and database.db.resume_tasks
                and database.db.resume_tasks.get(TgClient.ID)
            ):
                await database.db.resume_tasks[TgClient.ID].delete_one(
                    {"_id": self.message.link}
                )

            log_msg = f"Cleaned up resume data for video tools task"
            if task_type:
                log_msg += f" ({task_type})"
            log_msg += f": {self.message.link}"
            LOGGER.info(log_msg)

        except Exception as cleanup_e:
            error_msg = f"Failed to clean up resume data for video tools task"
            if task_type:
                error_msg += f" ({task_type})"
            error_msg += f": {cleanup_e}"
            LOGGER.error(error_msg)

    @new_task
    async def new_event(self):
        """Enhanced new_event with better memory management and error handling"""
        try:
            text = self.message.text.split("\n")
            input_list = text[0].split(" ")

            # Initial argument parsing to check for multi-input hint
            # We only care about "-i" for the pre_task_check hint
            try:
                parsed_early_args = {}
                temp_input_list = text[0].split(" ")
                arg_parser(temp_input_list[1:], parsed_early_args)
                early_multi_value = int(parsed_early_args.get("-i", 0))
            except Exception as e:
                LOGGER.warning(f"Error parsing early args: {e}")
                early_multi_value = 0

            # A task is considered a potential merge (and exempt from user limits) if -i is 2 or more.
            is_potential_video_merge = early_multi_value >= 2

            # Set exemption flag on the listener itself. This will be used to check RUNNING tasks.
            if is_potential_video_merge:
                self.is_user_limit_exempt = True
                LOGGER.info(
                    f"VideoTools listener {id(self)} marked as EXEMPT from user task limits."
                )
            else:
                self.is_user_limit_exempt = False

            # Pass the hint for the CURRENT task to pre_task_check.
            check_msg, check_button = await pre_task_check(
                self.message, is_video_merge_task=is_potential_video_merge
            )
            if check_msg:
                await delete_links(self.message)
                await auto_delete_message(
                    await send_message(self.message, check_msg, check_button)
                )
                return

            # Send start sticker for video tools operation
            await send_start_sticker(self.message)

            # Enhanced argument parsing with better defaults
            args = {
                "-i": 0,
                "-sp": 0,
                "-b": False,
                "-bz": False,
                "-doc": False,
                "-f": False,
                "-fd": False,
                "-fu": False,
                "-gofile": False,
                "-med": False,
                "-ndl": False,
                "-sv": False,
                "-z": False,
                "-mtd": "",
                "-n": "",
                "-ns": "",
                "-pfx": "",
                "-rcf": "",
                "-sfx": "",
                "-t": "",
                "-tl": "",
                "-up": "",
                "link": "",
            }

            input_list = text[0].split(" ")
            try:
                arg_parser(input_list[1:], args)
            except Exception as e:
                LOGGER.error(f"Error parsing arguments: {e}")
                await send_message(
                    self.message, f"Error parsing command arguments: {e}"
                )
                await send_error_sticker(self.message)
                return

            # Set attributes with validation
            self.as_doc = bool(args["-doc"])
            self.as_med = bool(args["-med"])
            self.compress = bool(args["-z"])
            self.is_buzzheavier = bool(args["-bz"])
            self.is_gofile = bool(args["-gofile"])
            self.link = args["link"] or ""
            self.metadata = args["-mtd"] or ""
            self.name = (args["-n"] or "").replace("/", "")
            self.name_prefix = args["-pfx"] or ""
            self.name_sub = args["-ns"] or ""
            self.name_suffix = args["-sfx"] or ""
            self.no_ddls = bool(args["-ndl"])
            self.rc_flags = args["-rcf"] or ""
            # Check for sample video: either from -sv arg or user setting
            if args["-sv"]:
                self.sample_video = True
            else:
                self.sample_video = (self.user_dict or {}).get(
                    "SAMPLE_VIDEO_ENABLED", False
                )
            self.split_size = int(args["-sp"]) if str(args["-sp"]).isdigit() else 0
            self.thumb = args["-t"] or ""
            self.thumbnail_layout = args["-tl"] or ""
            self.up_dest = args["-up"] or ""

            is_bulk = args["-b"]
            bulk_start = bulk_end = 0

            # Handle sudo privileges
            if await CustomFilters.sudo("", self.message):
                self.force_download = bool(args["-fd"])
                self.force_run = bool(args["-f"])
                self.force_upload = bool(args["-fu"])

            # Validate conflicting options
            if self.is_gofile and self.is_buzzheavier:
                self.is_buzzheavier = False
                LOGGER.info("Disabled buzzheavier as gofile is enabled")

            try:
                self.multi = int(args["-i"])
            except (ValueError, TypeError):
                self.multi = 0

            # Handle bulk processing
            if not isinstance(is_bulk, bool):
                try:
                    dargs = is_bulk.split(":")
                    bulk_start = dargs[0] or None
                    if len(dargs) == 2:
                        bulk_end = dargs[1] or None
                    is_bulk = True
                except Exception as e:
                    LOGGER.error(f"Error parsing bulk arguments: {e}")
                    is_bulk = False

            if is_bulk:
                try:
                    await self.init_bulk(input_list, bulk_start, bulk_end, VideoTools)
                    return
                except Exception as e:
                    LOGGER.error(f"Error in bulk initialization: {e}")
                    await send_message(
                        self.message, f"Error initializing bulk task: {e}"
                    )
                    return

            if self.bulk:
                del self.bulk[0]

            # Get link with validation
            self.link = self.link or get_link(self.message)

            if not is_url(self.link):
                await gather(
                    send_message(
                        "Send command along with link or by reply to the link!",
                        self.message,
                    ),
                    self.run_multi(input_list, VideoTools),
                )
                return

            # Get metadata with error handling
            try:
                metadata = await get_meta_video(self.link)
                if not metadata or not metadata[0]:
                    await gather(
                        send_message("Failed getting metadata!", self.message),
                        self.run_multi(input_list, VideoTools),
                    )
                    return
            except Exception as e:
                LOGGER.error(f"Error getting video metadata: {e}")
                await gather(
                    send_message(f"Error getting metadata: {e}", self.message),
                    self.run_multi(input_list, VideoTools),
                )
                return

            # Get video mode selection with error handling
            try:
                self.video_mode = await SelectMode(
                    self, True, metadata=metadata
                ).get_buttons()
                if not self.video_mode:
                    await self.run_multi(input_list, VideoTools)
                    return
            except Exception as e:
                LOGGER.error(f"Error in video mode selection: {e}")
                await send_message(self.message, f"Error in mode selection: {e}")
                return

            # Set name if not provided
            if not self.video_mode[1] and self.name:
                self.video_mode[1] = self.name

            await self.run_multi(input_list, "", VideoTools)

            # Send status message
            self.editable = await send_message(
                "<i>Request confirmed, preparing to process...</i>", self.message
            )

            # Pre-processing setup
            try:
                await self.before_start()
            except Exception as e:
                LOGGER.error(f"Error in before_start: {e}", exc_info=True)
                await edit_message(f"<b>Error:</b> {e}", self.editable)
                await self.remove_from_same_dir()
                return

            await delete_message(self.editable)
            LOGGER.info(
                f"Input link: {self.link}, Selected mode: {self.video_mode[0]}, Output name: {self.video_mode[1] or self.name}"
            )

            gid = token_urlsafe(6)

            # Create and execute video tools
            try:
                video_executor = VideoToolsExecutor(
                    self, self.link, gid, metadata=metadata
                )
                out_path = await video_executor.execute()

                if self.is_cancelled:
                    LOGGER.info("Video tools task was cancelled")
                    # Clean up auto-resume data for cancelled video tools task
                    await self._cleanup_resume_data("cancelled")
                    return

                # Validate output path
                if not await aiopath.exists(str(out_path)):
                    current_op_name = (
                        self.video_mode[1]
                        if self.video_mode
                        and len(self.video_mode) > 1
                        and self.video_mode[1]
                        else self.name
                    )
                    await self.on_upload_error(
                        f"Video processing failed for '{current_op_name}'. Output path not found: {out_path}"
                    )
                    await self.remove_from_same_dir()
                    return

                # Ensure proper directory setup for video tools like normal downloads
                from os import path as ospath
                from aioshutil import move

                # Create the download directory if it doesn't exist
                if not await aiopath.exists(self.dir):
                    try:
                        await makedirs(self.dir, exist_ok=True)
                        LOGGER.info(f"Created download directory: {self.dir}")
                    except Exception as e:
                        LOGGER.error(f"Failed to create directory {self.dir}: {e}")
                        await self.on_upload_error(f"Failed to create directory: {e}")
                        await self.remove_from_same_dir()
                        return

                # Move the output file to the proper download directory structure
                original_out_path = str(out_path)
                if not original_out_path.startswith(self.dir):
                    # Get the filename from the output path
                    output_filename = ospath.basename(original_out_path)
                    # Create the proper path in the download directory
                    proper_download_path = ospath.join(self.dir, output_filename)

                    try:
                        # Move the file to the proper location
                        await move(original_out_path, proper_download_path)
                        out_path = proper_download_path
                        LOGGER.info(
                            f"Moved video tools output from {original_out_path} to {proper_download_path}"
                        )
                    except Exception as e:
                        LOGGER.error(
                            f"Failed to move video tools output to download directory: {e}"
                        )
                        await self.on_upload_error(f"Failed to move output: {e}")
                        await self.remove_from_same_dir()
                        out_path = original_out_path

                # Set final attributes
                self.path = str(out_path)
                self.name = video_executor.listener.name or ospath.basename(self.path)

                try:
                    self.size = await get_path_size(self.path)
                except Exception as e:
                    LOGGER.error(f"Error getting file size: {e}")
                    self.size = 0

                self.gid = gid  # Set the gid for proper tracking like normal downloads
                self.video_tool_pre_executed = True

                LOGGER.info(
                    f"VideoToolsExecutor output: path='{self.path}', name='{self.name}', size={self.size}, gid='{self.gid}'"
                )
                LOGGER.info(
                    f"video_tool_pre_executed set to True. Original video_mode from SelectMode was: {self.video_mode}"
                )

                # Note: intro_sub auto-apply is now handled in post-processing flow
                # in task_listener.py after video tools complete, providing better separation

                # Start upload process
                if not self.is_leech and not self.up_dest:
                    from bot.helper.ext_utils.files_utils import clean_download

                    LOGGER.info(
                        f"Video tools task for {self.name} finished. No upload destination. Cleaning up."
                    )
                    await self.on_upload_complete(None, {self.name: "local"}, 1, 0)
                    await clean_download(self.dir)
                    # Send success sticker for completed video tools task
                    await send_success_sticker(self.message)

                    # IMPORTANT: Clean up auto-resume data for video tools tasks without upload
                    # This cleanup must happen here since we return early and skip the cleanup below
                    await self._cleanup_resume_data("no upload")
                    return

                await self.on_download_complete()
                # Send success sticker for download complete
                await send_success_sticker(self.message)

                # IMPORTANT: Clean up auto-resume data for video tools tasks with upload
                # Video tools tasks need special cleanup since they bypass normal upload flow
                await self._cleanup_resume_data("with upload")

            except Exception as e:
                LOGGER.error(f"Error in video tools execution: {e}", exc_info=True)
                await self.on_upload_error(f"Video processing failed: {e}")
                await send_error_sticker(self.message)
                return

            finally:
                # Cleanup
                self.video_mode = None
                if hasattr(self, "video_tool_pre_executed"):
                    del self.video_tool_pre_executed
                # Always clean up multi/bulk state
                if len(self.bulk) != 0:
                    del self.bulk[0]

                # Force garbage collection
                gc.collect()

        except Exception as e:
            LOGGER.error(f"Critical error in VideoTools.new_event: {e}", exc_info=True)
            try:
                await send_message(self.message, f"Critical error occurred: {e}")
                await send_error_sticker(self.message)
            except Exception:
                pass
        finally:
            # Final cleanup
            await self._cleanup()

    async def _cleanup(self):
        """Cleanup temporary files and resources"""
        try:
            # Clean up temporary files
            for temp_file in self._temp_files:
                if os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                        LOGGER.debug(f"Removed temporary file: {temp_file}")
                    except Exception as e:
                        LOGGER.warning(f"Failed to remove temp file {temp_file}: {e}")
            self._temp_files.clear()

            # Run cleanup tasks
            for cleanup_task in self._cleanup_tasks:
                try:
                    await cleanup_task()
                except Exception as e:
                    LOGGER.warning(f"Cleanup task failed: {e}")
            self._cleanup_tasks.clear()

        except Exception as e:
            LOGGER.error(f"Error during cleanup: {e}")
        finally:
            gc.collect()


async def mirror_vidtools(client: Client, message):
    """Mirror video tools with enhanced error handling"""
    video_tools = None
    try:
        video_tools = VideoTools(client, message)
        await video_tools.new_event()
    except Exception as e:
        LOGGER.error(f"Error in mirror_vidtools: {e}", exc_info=True)
        try:
            await send_message(message, f"Error in video tools: {e}")
        except Exception:
            pass
    finally:
        if video_tools:
            await video_tools._cleanup()


async def leech_vidtools(client: Client, message):
    """Leech video tools with enhanced error handling"""
    video_tools = None
    try:
        video_tools = VideoTools(client, message, is_leech=True)
        await video_tools.new_event()
    except Exception as e:
        LOGGER.error(f"Error in leech_vidtools: {e}", exc_info=True)
        try:
            await send_message(message, f"Error in video tools: {e}")
        except Exception:
            pass
    finally:
        if video_tools:
            await video_tools._cleanup()
