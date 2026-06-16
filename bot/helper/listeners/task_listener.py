import asyncio
import os
import re
import random
from contextlib import suppress
from html import escape
from mimetypes import guess_type
from os import path as ospath
from time import time
from asyncio import create_subprocess_exec, gather, sleep
from asyncio.subprocess import PIPE
import gc  # Added for memory management
from urllib.parse import quote  # [FIX] Import 'quote' for URL encoding in index links

from aiofiles.os import listdir, path as aiopath, remove, rename as aiorename
from requests import utils as rutils

from ... import (
    DOWNLOAD_DIR,
    intervals,
    LOGGER,
    non_queued_dl,
    non_queued_up,
    queue_dict_lock,
    queued_dl,
    queued_up,
    same_directory_lock,
    task_dict,
    task_dict_lock,
    cached_dict,
    cpu_eater_lock,  # Added for CPU limiting
    user_data,
)
from ...core.config_manager import Config
from ...core.tg_client import TgClient
from ...core.torrent_manager import TorrentManager
from ..common import TaskConfig
from ..ext_utils import metadata_helper
from ..ext_utils.bot_utils import encode_slink, get_date_time, sync_to_async
from ..ext_utils.db_handler import database
from ..ext_utils.files_utils import (
    clean_download,
    clean_target,
    create_recursive_symlink,
    get_path_size,
    join_files,
    move_and_merge,
    remove_excluded_files,
)
from ..ext_utils.links_utils import is_gdrive_id, is_gofile_upload, is_rclone_path
from ..ext_utils.media_utils import FFProgress, get_media_info
from ..ext_utils.status_utils import (
    MirrorStatus,
    action,
    get_readable_file_size,
    get_readable_time,
)
from ..ext_utils.task_manager import (
    check_running_tasks,
    start_from_queued,
    limit_checker,
)
from ..ext_utils.telegraph_helper import TelePost
from ..mirror_leech_utils.gdrive_utils.upload import GoogleDriveUpload
from ..mirror_leech_utils.gofile_utils.upload import GoFileUpload
from ..mirror_leech_utils.rclone_utils.transfer import RcloneTransferHelper
from ..mirror_leech_utils.status_utils.ffmpeg_status import FFMpegStatus
from ..mirror_leech_utils.status_utils.gdrive_status import GoogleDriveStatus
from ..mirror_leech_utils.status_utils.gofile_status import GoFileStatus
from ..mirror_leech_utils.status_utils.sevenz_status import (
    SevenZStatus as SevenZipStatus,
)
from ..mirror_leech_utils.status_utils.queue_status import QueueStatus
from ..mirror_leech_utils.status_utils.rclone_status import RcloneStatus
from ..mirror_leech_utils.status_utils.telegram_status import TelegramStatus
from ..mirror_leech_utils.status_utils.yt_status import YtStatus
from ..mirror_leech_utils.upload_utils.telegram_uploader import TelegramUploader
from ..mirror_leech_utils.youtube_utils.youtube_upload import YouTubeUpload
from ..telegram_helper.button_build import ButtonMaker
from ..telegram_helper.message_utils import (
    delete_message,
    delete_status,
    send_message,
    update_status_message,
)
from ..telegram_helper.sticker_utils import send_success_sticker
from ..video_utils.executor import VideoToolsExecutor
from bot.helper.mhunt_utils.filename_processor import process_filename_for_upload


def get_random_image(image_config):
    """Get a random image URL from the image configuration"""
    try:
        if isinstance(image_config, str):
            # If it's a single string, split by spaces and filter out empty strings
            images = [img.strip() for img in image_config.split() if img.strip()]
        elif isinstance(image_config, (list, tuple)):
            # If it's a list/tuple, flatten it and split each string
            images = []
            for item in image_config:
                if isinstance(item, str):
                    images.extend([img.strip() for img in item.split() if img.strip()])
        else:
            return None

        if images:
            return random.choice(images)
        return None
    except Exception as e:
        LOGGER.error(f"Error getting random image: {e}")
        return None


class TaskListener(TaskConfig):
    def __init__(self):
        super().__init__()
        self.data_from_video_tool_selection = False
        self.current_metadata_percentage = 0
        self.current_ffmpeg_speed = None
        self.current_ffmpeg_eta = 0
        # Initialize memory tracking
        self._memory_refs = []

    async def _sanitize_path(self, path):
        if await aiopath.isfile(path):
            base_name = ospath.basename(path)
            name_stem, name_ext = ospath.splitext(base_name)
            trailing_pattern = (
                r"([\s._-]*(?:intro|sample|merged|remove|reorder|convert))+\s*$"
            )
            import re as _re_task

            # Only remove special trailing operation tags (intro/sample/merged/remove/reorder/convert)
            # Do not alter dots/underscores/hyphens chosen by the user elsewhere
            cleared = _re_task.sub(
                trailing_pattern, "", name_stem, flags=_re_task.IGNORECASE
            )
            if cleared != name_stem:
                new_stem = cleared.strip()
            else:
                # No trailing op-tags found; keep original name stem as-is
                new_stem = name_stem
            new_name = f"{new_stem}{name_ext}"
            if new_name and new_name != base_name:
                from aiofiles.os import rename as _aiorename_task

                new_path = ospath.join(ospath.dirname(path), new_name)
                if not await aiopath.exists(new_path):
                    await _aiorename_task(path, new_path)
                    LOGGER.info(
                        f"Task {self.mid}: Sanitized filename: '{base_name}' -> '{new_name}'"
                    )
                    return new_path
        return path

    async def clean(self):
        """Enhanced cleanup with memory management"""
        try:
            # Clear status intervals
            if st := intervals.get("status"):
                for intvl in list(st.values()):
                    try:
                        intvl.cancel()
                    except Exception as e:
                        LOGGER.warning(f"Error cancelling interval: {e}")
                intervals["status"].clear()

            # Clean up aria2 and status
            cleanup_tasks = []
            try:
                cleanup_tasks.append(TorrentManager.aria2.purgeDownloadResult())
            except Exception as e:
                LOGGER.warning(f"Error purging aria2 results: {e}")

            try:
                cleanup_tasks.append(delete_status())
            except Exception as e:
                LOGGER.warning(f"Error deleting status: {e}")

            if cleanup_tasks:
                await gather(*cleanup_tasks, return_exceptions=True)

        except Exception as e:
            LOGGER.error(f"Error in clean(): {e}")

    def clear(self):
        """Basic clear function"""
        self.subname = ""
        self.subsize = 0
        self.files_to_proceed = []
        self.proceed_count = 0
        self.progress = True

    async def remove_from_same_dir(self):
        """Remove task from same directory tracking"""
        try:
            async with task_dict_lock:
                if (
                    self.folder_name
                    and self.same_dir
                    and self.mid
                    in self.same_dir.get(self.folder_name, {}).get("tasks", [])
                ):
                    self.same_dir[self.folder_name]["tasks"].remove(self.mid)
                    self.same_dir[self.folder_name]["total"] -= 1
        except Exception as e:
            LOGGER.error(f"Error removing from same dir: {e}")

    async def save_task_info(self):
        """Save task information for resuming on restart"""
        if Config.INCOMPLETE_TASK_NOTIFIER and Config.DATABASE_URL:
            from ..ext_utils.resume_utils import save_task_file

            task_info = {
                "link": self.link,
                "is_leech": self.is_leech,
                "extract": self.extract,
                "compress": self.compress,
                "select": self.select,
                "seed": self.seed,
                "name": self.name,
                "up_dest": self.up_dest,
                "message_link": self.message.link,
                "tag": self.tag,
                "chat_id": self.message.chat.id,
                "user_id": self.user_id,
                "ffmpeg_cmds": self.ffmpeg_cmds,
                "screen_shots": self.screen_shots,
                "thumb": self.thumb,
                "is_clone": self.is_clone,
                "is_qbit": self.is_qbit,
                "is_jd": self.is_jd,
                "is_nzb": self.is_nzb,
                "as_doc": self.as_doc,
            }
            await save_task_file(task_info)

    async def on_download_start(self):
        await self.save_task_info()
        mode_name = "Leech" if self.is_leech else "Mirror"
        if self.bot_pm and self.is_super_chat:
            self.pm_msg = await send_message(
                self.user_id,
                f"""➲ <b><u>Task Started :</u></b>
┃
╰ <b>Link:</b> <a href='{self.source_url}'>Click Here</a>
""",
            )
        if Config.LINKS_LOG_ID:
            await send_message(
                Config.LINKS_LOG_ID,
                f"""➲  <b><u>{mode_name} Started:</u></b>
 ┃
 ┠ <b>User :</b> {self.tag} ( #ID{self.user_id} )
 ┠ <b>Message Link :</b> <a href='{self.message.link}'>Click Here</a>
 ┗ <b>Link:</b> <a href='{self.source_url}'>Click Here</a>
 """,
            )
        if (
            self.is_super_chat
            and Config.INCOMPLETE_TASK_NOTIFIER
            and Config.DATABASE_URL
        ):
            await database.add_incomplete_task(
                self.message.chat.id, self.message.link, self.tag
            )

    async def on_download_complete(self):
        await sleep(2)
        if self.is_cancelled:
            return

        # Initialize variables
        multi_links = False
        gid = ""
        video_tool_was_pre_executed = getattr(self, "video_tool_pre_executed", False)

        try:
            if video_tool_was_pre_executed:
                gid = getattr(self, "gid", "")
                dl_path = self.path

                # Validate path exists
                if not await aiopath.exists(dl_path):
                    await self.on_upload_error(
                        f"Video tools output path does not exist: {dl_path}"
                    )
                    return

                # Set up path variables for video tools
                if await aiopath.isfile(dl_path):
                    up_dir = ospath.dirname(dl_path)
                    up_path = dl_path
                    # Preserve caption filename format when FILENAME_SOURCE is "caption"
                    filename_source = (
                        getattr(self, "user_dict", {}).get(
                            "FILENAME_SOURCE", Config.FILENAME_SOURCE
                        )
                        if hasattr(self, "user_dict")
                        else Config.FILENAME_SOURCE
                    )
                    if (
                        filename_source == "caption"
                        and hasattr(self, "file_details")
                        and self.file_details
                        and self.file_details.get("caption")
                    ):
                        # Keep the original caption-derived name for display
                        pass  # Don't overwrite self.name
                    else:
                        self.name = ospath.basename(dl_path)
                    self.is_file = True
                else:
                    up_dir = dl_path
                    up_path = dl_path
                    # Preserve caption filename format when FILENAME_SOURCE is "caption"
                    filename_source = (
                        getattr(self, "user_dict", {}).get(
                            "FILENAME_SOURCE", Config.FILENAME_SOURCE
                        )
                        if hasattr(self, "user_dict")
                        else Config.FILENAME_SOURCE
                    )
                    if (
                        filename_source == "caption"
                        and hasattr(self, "file_details")
                        and self.file_details
                        and self.file_details.get("caption")
                    ):
                        # Keep the original caption-derived name for display
                        pass  # Don't overwrite self.name
                    else:
                        self.name = ospath.basename(dl_path.rstrip(ospath.sep))
                    self.is_file = False

                self.size = await get_path_size(dl_path)
                LOGGER.info(
                    f"Task {self.mid}: Video tools setup - up_dir: {up_dir}, up_path: {up_path}, name: {self.name}, size: {self.size}"
                )

                # Process filename for upload
                try:
                    LOGGER.debug(
                        f"Task {self.mid}: Calling process_filename_for_upload (video-tools) with name={self.name}, up_path={up_path}"
                    )
                    processed_cloud_name, up_path = await process_filename_for_upload(
                        self, self.name, up_path
                    )
                    LOGGER.debug(
                        f"Task {self.mid}: Returned from process_filename_for_upload (video-tools) -> processed_cloud_name={processed_cloud_name}, up_path={up_path}"
                    )
                    if processed_cloud_name:
                        self.name = processed_cloud_name
                    LOGGER.info(
                        f"Task {self.mid}: Video tools - After process_filename_for_upload - final name: {self.name}, final up_path: {up_path}"
                    )
                except Exception as e:
                    LOGGER.error(f"Error processing filename for upload: {e}")
                    # Continue with original name if processing fails

                video_tools_processed = True

            else:
                video_tools_processed = False

            # Handle directory merging
            if video_tools_processed:
                pass  # Skip merge logic for video tools
            elif (
                self.folder_name
                and self.same_dir
                and self.mid in self.same_dir.get(self.folder_name, {}).get("tasks", [])
            ):
                async with same_directory_lock:
                    same_dir_data = self.same_dir.get(self.folder_name, {})
                    tasks = same_dir_data.get("tasks", [])

                    if len(tasks) > 1 and self.mid in tasks:
                        tasks.remove(self.mid)
                        same_dir_data["total"] -= 1
                        des_id = list(tasks)[0]

                        sanitized_folder_name = self.folder_name.lstrip("/")
                        spath = ospath.join(self.dir, sanitized_folder_name)
                        base_des_dir = ospath.join(DOWNLOAD_DIR, str(des_id))
                        des_path = ospath.join(base_des_dir, sanitized_folder_name)

                        try:
                            # Sanitize files before merging
                            for root, _, files in await sync_to_async(os.walk, spath):
                                for file in files:
                                    file_path = ospath.join(root, file)
                                    await self._sanitize_path(file_path)
                            merge_success = await move_and_merge(
                                spath, des_path, self.mid
                            )
                            if merge_success:
                                multi_links = True
                                LOGGER.info(
                                    f"Successfully merged files from {spath} to {des_path}"
                                )
                            else:
                                LOGGER.error(
                                    f"Failed to merge files from {spath} to {des_path}"
                                )
                        except Exception as e:
                            LOGGER.error(f"Error during file merge: {e}")

            # Main download completion logic
            if not video_tools_processed:
                async with task_dict_lock:
                    if self.is_cancelled or self.mid not in task_dict:
                        return

                    download = task_dict[self.mid]
                    self.name = download.name() or ""
                    self.original_display_name = self.name
                    gid = download.gid()

                if not (self.is_torrent or self.is_qbit):
                    self.seed = False

                if multi_links:
                    await send_message(
                        self.message,
                        f"✅ <b>{self.original_display_name}</b> has been merged.\n\nWaiting for other tasks to finish...",
                    )
                    async with task_dict_lock:
                        if self.mid in task_dict:
                            del task_dict[self.mid]
                    await update_status_message(self.message.chat.id)
                    return
                elif self.same_dir:
                    self.seed = False

                if self.folder_name:
                    self.name = self.folder_name.strip("/").split("/", 1)[0]

                dl_path = ospath.join(self.dir, self.name)

                # [ENHANCEMENT] Robust path validation after download
                if not await aiopath.exists(dl_path):
                    try:
                        LOGGER.warning(
                            f"Download path does not exist: {dl_path}. Searching directory..."
                        )
                        files_in_dir = await listdir(self.dir)
                        if files_in_dir:
                            main_content_name = files_in_dir[0]
                            if (
                                main_content_name == "yt-dlp-thumb"
                                and len(files_in_dir) > 1
                            ):
                                main_content_name = files_in_dir[1]
                            self.name = main_content_name
                            dl_path = ospath.join(self.dir, self.name)
                            LOGGER.info(f"Found content, new path: {dl_path}")
                        else:
                            await self.on_upload_error(
                                f"Download failed. No files found in download directory: {self.dir}"
                            )
                            return
                    except Exception as e:
                        await self.on_upload_error(
                            f"Error accessing download directory {self.dir}: {str(e)}"
                        )
                        return

            # Set up file properties
            self.size = await get_path_size(dl_path)
            self.is_file = await aiopath.isfile(dl_path)

            # Set up upload paths
            if self.seed and not video_tools_processed:
                up_dir = self.up_dir = f"{self.dir}10000"
                up_path = f"{self.up_dir}/{self.name}"
                await create_recursive_symlink(self.dir, self.up_dir)
            elif not video_tools_processed:
                up_dir = self.dir
                up_path = dl_path

            if not await aiopath.exists(up_path):
                await self.on_upload_error(
                    f"Processing Error: Path does not exist before upload: {up_path}"
                )
                return

            # Remove excluded files
            await remove_excluded_files(
                self.up_dir or self.dir, self.excluded_extensions
            )

            # Handle queue
            if not Config.QUEUE_ALL:
                async with queue_dict_lock:
                    if self.mid in non_queued_dl:
                        non_queued_dl.remove(self.mid)
                await start_from_queued()

            # Process joining
            if self.join and not self.is_file and not video_tools_processed:
                try:
                    join_results = await join_files(up_path)
                    if join_results:
                        LOGGER.info(
                            f"Successfully joined {len(join_results)} file(s) in {up_path}"
                        )
                    else:
                        LOGGER.warning(f"No files were joined in {up_path}")
                except Exception as e:
                    LOGGER.error(f"Error during file joining in {up_path}: {e}")

            # Process extraction (allow extraction even for video-tools-produced outputs)
            # Previously extraction was skipped when video tools had pre-executed (video_tools_processed=True),
            # which prevented prefix/suffix/REMNAME from being applied to extracted content. Remove that guard
            # so extraction and subsequent filename processing always run when requested.
            # Skip extraction if user has enabled video encoding (prevents "Extracting" message during encoding)

            if self.extract and not self.is_nzb:
                try:
                    # Perform extraction and validate the result
                    up_path = await self.proceed_extract(up_path, gid)

                    # If extraction returned a falsy value (e.g. False) treat it as failure
                    if not up_path or isinstance(up_path, bool):
                        raise RuntimeError("Extraction failed — invalid path returned.")

                    if self.is_cancelled:
                        return

                    # Update file properties after extraction
                    potential_name_after_extraction = ospath.basename(
                        up_path.rstrip("/")
                    )
                    self.name = potential_name_after_extraction
                    self.is_file = await aiopath.isfile(up_path)
                    self.size = await get_path_size(up_path)
                    self.clear()
                    await remove_excluded_files(up_path, self.excluded_extensions)

                    # Re-check size limits after extraction
                    try:
                        from bot.helper.ext_utils.task_manager import limit_checker

                        breach_msg = await limit_checker(self)
                        if breach_msg:
                            await self.on_download_error(breach_msg)
                            return
                    except Exception:
                        pass

                    # Handle auto-rename after extraction
                    if self.user_dict.get("AUTO_RENAME", False) and not self.is_file:
                        # Check if individual file processing was already done by top-level call
                        if getattr(self, "_individual_files_processed", False):
                            LOGGER.info(
                                f"Task {self.mid}: Skipping AutoRename - individual files already processed by directory-level call"
                            )
                        else:
                            for root, _, files in await sync_to_async(os.walk, up_path):
                                for file in files:
                                    original_path = ospath.join(root, file)
                                    if not await aiopath.exists(original_path):
                                        LOGGER.warning(
                                            f"[AutoRename] Skipping: File not found: {original_path}"
                                        )
                                        continue

                                    try:
                                        LOGGER.debug(
                                            f"Task {self.mid}: AutoRename - calling process_filename_for_upload with file={file}, original_path={original_path}"
                                        )
                                        (
                                            new_name,
                                            new_path,
                                        ) = await process_filename_for_upload(
                                            self, file, original_path
                                        )
                                        LOGGER.debug(
                                            f"Task {self.mid}: AutoRename - returned new_name={new_name}, new_path={new_path} for original={original_path}"
                                        )
                                        if new_name != file:
                                            # Check if file was already renamed by the processor
                                            if not await aiopath.exists(
                                                original_path
                                            ) and await aiopath.exists(new_path):
                                                LOGGER.info(
                                                    f"[AutoRename] File already renamed by processor: {file} -> {new_name}"
                                                )
                                            elif await aiopath.exists(original_path):
                                                # Check for name conflicts and handle them with task-specific suffix
                                                if await aiopath.exists(new_path):
                                                    base, ext = ospath.splitext(
                                                        new_name
                                                    )
                                                    new_name = f"{base}_{self.mid}{ext}"
                                                    new_path = ospath.join(
                                                        root, new_name
                                                    )
                                                await aiorename(original_path, new_path)
                                                LOGGER.info(
                                                    f"[AutoRename] Renamed: {file} -> {new_name}"
                                                )
                                            else:
                                                LOGGER.warning(
                                                    f"[AutoRename] Neither original nor target exists: {original_path} -> {new_path}"
                                                )
                                    except FileNotFoundError:
                                        LOGGER.warning(
                                            f"[AutoRename] Rename failed (file missing): {original_path}"
                                        )
                                    except Exception as e:
                                        LOGGER.error(f"[AutoRename] Rename error: {e}")

                    # If AUTO_RENAME is disabled, still apply prefix/suffix/REMNAME to all extracted files
                    elif not self.is_file:
                        # Check if individual file processing was already done by top-level call
                        if getattr(self, "_individual_files_processed", False):
                            LOGGER.info(
                                f"Task {self.mid}: Skipping NameProcess - individual files already processed by directory-level call"
                            )
                        else:
                            for root, _, files in await sync_to_async(os.walk, up_path):
                                for file in files:
                                    original_path = ospath.join(root, file)
                                    if not await aiopath.exists(original_path):
                                        LOGGER.warning(
                                            f"[NameProcess] Skipping: File not found: {original_path}"
                                        )
                                        continue

                                    try:
                                        LOGGER.debug(
                                            f"Task {self.mid}: NameProcess - calling process_filename_for_upload with file={file}, original_path={original_path}"
                                        )
                                        (
                                            new_name,
                                            new_path,
                                        ) = await process_filename_for_upload(
                                            self, file, original_path
                                        )
                                        LOGGER.debug(
                                            f"Task {self.mid}: NameProcess - returned new_name={new_name}, new_path={new_path} for original={original_path}"
                                        )
                                        if new_name != file:
                                            # Check if file was already renamed by the processor
                                            if not await aiopath.exists(
                                                original_path
                                            ) and await aiopath.exists(new_path):
                                                LOGGER.info(
                                                    f"[NameProcess] File already renamed by processor: {file} -> {new_name}"
                                                )
                                            elif await aiopath.exists(original_path):
                                                # Check for name conflicts and handle them with task-specific suffix
                                                if await aiopath.exists(new_path):
                                                    base, ext = ospath.splitext(
                                                        new_name
                                                    )
                                                    new_name = f"{base}_{self.mid}{ext}"
                                                    new_path = ospath.join(
                                                        root, new_name
                                                    )
                                                await aiorename(original_path, new_path)
                                                LOGGER.info(
                                                    f"[NameProcess] Renamed: {file} -> {new_name}"
                                                )
                                            else:
                                                LOGGER.warning(
                                                    f"[NameProcess] Neither original nor target exists: {original_path} -> {new_path}"
                                                )
                                    except FileNotFoundError:
                                        LOGGER.warning(
                                            f"[NameProcess] Rename failed (file missing): {original_path}"
                                        )
                                    except Exception as e:
                                        LOGGER.error(f"[NameProcess] Rename error: {e}")

                    # Apply filename processing (prefix/suffix/REMNAME) at top-level after extraction
                    try:
                        LOGGER.debug(
                            f"Task {self.mid}: Post-extract calling process_filename_for_upload with name={self.name}, up_path={up_path}"
                        )
                        (
                            processed_cloud_name_after_extract,
                            up_path,
                        ) = await process_filename_for_upload(self, self.name, up_path)
                        if processed_cloud_name_after_extract:
                            self.name = processed_cloud_name_after_extract
                        # Mark that post-extraction filename processing has been applied
                        setattr(self, "_post_extract_name_processed", True)
                        # Also mark that individual file processing has been done to prevent duplication
                        setattr(self, "_individual_files_processed", True)
                        LOGGER.debug(
                            f"Task {self.mid}: After post-extract filename processing - name: {self.name}, up_path: {up_path}"
                        )
                    except Exception as e:
                        LOGGER.error(f"Error processing filename after extraction: {e}")
                except Exception as e:
                    LOGGER.error(f"Error during extraction: {e}")
                    if self.is_cancelled:
                        return

            # Process FFmpeg commands
            if self.ffmpeg_cmds:
                try:
                    up_path = await self.proceed_ffmpeg(up_path, gid)
                    if self.is_cancelled:
                        return
                    self.is_file = await aiopath.isfile(up_path)
                    self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
                    self.size = await get_path_size(up_dir)
                    self.clear()
                except Exception as e:
                    LOGGER.error(f"Error during FFmpeg processing: {e}")
                    if self.is_cancelled:
                        return

            # Handle file details for leech
            if self.is_leech and self.is_file:
                try:
                    fname = ospath.basename(up_path)
                    self.file_details["filename"] = fname
                    self.file_details["mime_type"] = (guess_type(fname))[
                        0
                    ] or "application/octet-stream"
                except Exception as e:
                    LOGGER.error(f"Error setting file details: {e}")

            # Handle name substitution
            if self.name_swap:
                try:
                    up_path = await self.substitute(up_path)
                    if self.is_cancelled:
                        return
                    self.is_file = await aiopath.isfile(up_path)
                    self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
                except Exception as e:
                    LOGGER.error(f"Error during name substitution: {e}")

            # Apply filename pattern removal
            command_patterns = getattr(self, "remname_patterns", "")
            user_patterns = (
                self.user_dict.get("FILENAME_REMOVE_PATTERNS", "")
                if hasattr(self, "user_dict")
                else ""
            )

            if command_patterns or user_patterns:
                up_path = await self.remove_filename_patterns(up_path)
                if self.is_cancelled:
                    return
                self.is_file = await aiopath.isfile(up_path)
                self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]

            # Initialize metadata processing variables
            self.listener_processed_media = False
            # [FIX] Keep a reliable fallback path. This is set before any further modifications.
            original_path_for_fallback = up_path
            self.current_metadata_percentage = 0

            # Auto-rename (VT_RENAME_TO) applied late, before upload
            try:
                new_base = self.user_dict.get("VT_RENAME_TO")
                if new_base and await aiopath.exists(up_path):
                    if await aiopath.isfile(up_path):
                        dirn = ospath.dirname(up_path)
                        extn = ospath.splitext(up_path)[1]
                        target = ospath.join(dirn, f"{new_base}{extn}")
                        if target != up_path:
                            await aiorename(up_path, target)
                            up_path = target
                            self.name = ospath.basename(target)
                            LOGGER.info(
                                f"Task {self.mid}: Auto rename applied -> {self.name}"
                            )
            except Exception as e:
                LOGGER.error(f"Task {self.mid}: Auto rename error: {e}")

            # Process screenshots
            if self.screen_shots:
                try:
                    LOGGER.info(
                        f"Task {self.mid}: Starting screenshot generation for {up_path}."
                    )
                    if not hasattr(self, "user_dict"):
                        self.user_dict = {}

                    if getattr(self, "ss_grid", False) and not self.user_dict.get(
                        "SS_GRID_ENABLED", False
                    ):
                        self.user_dict["SS_GRID_ENABLED"] = True

                    up_path = await self.generate_screenshots(up_path)
                    if self.is_cancelled:
                        LOGGER.info(
                            f"Task {self.mid}: Cancelled during screenshot generation."
                        )
                        return

                    self.is_file = await aiopath.isfile(up_path)
                    self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
                    self.size = await get_path_size(up_dir)
                    LOGGER.info(
                        f"Task {self.mid}: After screenshots - up_path: {up_path}, name: {self.name}, size: {self.size}"
                    )
                except Exception as e:
                    LOGGER.error(f"Error during screenshot generation: {e}")

            # Process media conversion
            # Validate that conversion parameters are actually set with meaningful values
            has_valid_video_conversion = bool(
                self.convert_video
                and isinstance(self.convert_video, str)
                and self.convert_video.strip()
                and len(self.convert_video.split()) >= 1
                and self.convert_video.split()[0].strip()
            )
            has_valid_audio_conversion = bool(
                self.convert_audio
                and isinstance(self.convert_audio, str)
                and self.convert_audio.strip()
                and len(self.convert_audio.split()) >= 1
                and self.convert_audio.split()[0].strip()
            )

            if has_valid_video_conversion or has_valid_audio_conversion:
                try:
                    LOGGER.info(
                        f"Task {self.mid}: Starting media conversion for {up_path}. Video: {self.convert_video}, Audio: {self.convert_audio}"
                    )
                    up_path = await self.convert_media(up_path, gid)
                    if self.is_cancelled:
                        LOGGER.info(
                            f"Task {self.mid}: Cancelled during media conversion."
                        )
                        return

                    self.is_file = await aiopath.isfile(up_path)
                    self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
                    self.size = await get_path_size(up_dir)
                    self.clear()
                    LOGGER.info(
                        f"Task {self.mid}: After media conversion - up_path: {up_path}, name: {self.name}, size: {self.size}"
                    )
                except Exception as e:
                    LOGGER.error(f"Error during media conversion: {e}")

            # Initialize unwanted files list
            unwanted_files, unwanted_files_size, files_to_delete = [], [], []

            # Auto Video Tools from user settings (audio remove/reorder)
            try:
                if not video_tools_processed and not self.video_mode:
                    # Merge operations first if requested
                    if self.user_dict.get("VT_MERGE_VIDEOS"):
                        try:
                            self.video_mode = ("vid_vid", self.name, False, {})
                            LOGGER.info(
                                f"Task {self.mid}: Starting Auto VideoToolsExecutor (merge videos) for {up_path}."
                            )
                            executed_up_path = await VideoToolsExecutor(
                                self, up_path, gid, unwanted_files
                            ).execute()
                            if executed_up_path and executed_up_path != up_path:
                                up_path = executed_up_path
                                self.path = up_path
                                self.is_file = await aiopath.isfile(up_path)
                                self.name = ospath.basename(up_path.rstrip(ospath.sep))
                                self.size = await get_path_size(up_path)
                                self.seed = False
                                video_tools_processed = True
                        except Exception as e:
                            LOGGER.error(
                                f"Task {self.mid}: Auto merge videos error: {e}"
                            )
                        finally:
                            self.video_mode = None
                    if not self.video_mode and self.user_dict.get("VT_MERGE_AUDIOS"):
                        try:
                            self.video_mode = ("vid_aud", self.name, False, {})
                            LOGGER.info(
                                f"Task {self.mid}: Starting Auto VideoToolsExecutor (merge audios) for {up_path}."
                            )
                            executed_up_path = await VideoToolsExecutor(
                                self, up_path, gid, unwanted_files
                            ).execute()
                            if executed_up_path and executed_up_path != up_path:
                                up_path = executed_up_path
                                self.path = up_path
                                self.is_file = await aiopath.isfile(up_path)
                                self.name = ospath.basename(up_path.rstrip(ospath.sep))
                                self.size = await get_path_size(up_path)
                                self.seed = False
                                video_tools_processed = True
                        except Exception as e:
                            LOGGER.error(
                                f"Task {self.mid}: Auto merge audios error: {e}"
                            )
                        finally:
                            self.video_mode = None
                    if not self.video_mode and self.user_dict.get("VT_MERGE_SUBS"):
                        try:
                            self.video_mode = ("vid_sub", self.name, False, {})
                            LOGGER.info(
                                f"Task {self.mid}: Starting Auto VideoToolsExecutor (merge subs) for {up_path}."
                            )
                            executed_up_path = await VideoToolsExecutor(
                                self, up_path, gid, unwanted_files
                            ).execute()
                            if executed_up_path and executed_up_path != up_path:
                                up_path = executed_up_path
                                self.path = up_path
                                self.is_file = await aiopath.isfile(up_path)
                                self.name = ospath.basename(up_path.rstrip(ospath.sep))
                                self.size = await get_path_size(up_path)
                                self.seed = False
                                video_tools_processed = True
                        except Exception as e:
                            LOGGER.error(f"Task {self.mid}: Auto merge subs error: {e}")
                        finally:
                            self.video_mode = None

                    # Hardsub - burn subtitles permanently into video
                    if not self.video_mode and self.user_dict.get(
                        "VIDEO_HARDSUB_ENABLED"
                    ):
                        try:
                            # Get hardsub style from user settings
                            hardsub_style = self.user_dict.get(
                                "VIDEO_HARDSUB_STYLE", "default"
                            )

                            # Build kwargs for hardsub operation
                            kwargs = {
                                "font_name": self.user_dict.get(
                                    "VIDEO_HARDSUB_FONT_NAME", "Arial"
                                ),
                                "font_size": self.user_dict.get(
                                    "VIDEO_HARDSUB_FONT_SIZE", 22
                                ),
                                "font_colour": self.user_dict.get(
                                    "VIDEO_HARDSUB_FONT_COLOUR", "FFFFFF"
                                ),
                                "hardsub_style": hardsub_style,
                                "bold_style": hardsub_style
                                == "bold",  # For backwards compatibility
                            }

                            self.video_mode = ("hardsub", self.name, False, kwargs)
                            LOGGER.info(
                                f"Task {self.mid}: Starting Auto VideoToolsExecutor (hardsub) for {up_path} -> style: {hardsub_style}"
                            )
                            executed_up_path = await VideoToolsExecutor(
                                self, up_path, gid, unwanted_files
                            ).execute()
                            if executed_up_path and executed_up_path != up_path:
                                up_path = executed_up_path
                                self.path = up_path
                                self.is_file = await aiopath.isfile(up_path)
                                self.name = ospath.basename(up_path.rstrip(ospath.sep))
                                self.size = await get_path_size(up_path)
                                self.seed = False
                                video_tools_processed = True
                        except Exception as e:
                            LOGGER.error(f"Task {self.mid}: Auto hardsub error: {e}")
                        finally:
                            self.video_mode = None

                    # Trim
                    vt_trim = self.user_dict.get("VT_TRIM_RANGE")
                    if not self.video_mode and vt_trim:
                        try:
                            if "-" in vt_trim:
                                start_time, end_time = [
                                    x.strip() for x in vt_trim.split("-", 1)
                                ]
                                kwargs = {
                                    "start_time": start_time,
                                    "end_time": end_time,
                                }
                                self.video_mode = ("trim", self.name, False, kwargs)
                                LOGGER.info(
                                    f"Task {self.mid}: Auto VideoToolsExecutor (trim) for {up_path} -> {vt_trim}"
                                )
                                executed_up_path = await VideoToolsExecutor(
                                    self, up_path, gid, unwanted_files
                                ).execute()
                                if executed_up_path and executed_up_path != up_path:
                                    up_path = executed_up_path
                                    self.path = up_path
                                    self.is_file = await aiopath.isfile(up_path)
                                    self.name = ospath.basename(
                                        up_path.rstrip(ospath.sep)
                                    )
                                    self.size = await get_path_size(up_path)
                                    self.seed = False
                                    video_tools_processed = True
                        except Exception as e:
                            LOGGER.error(f"Task {self.mid}: Auto trim error: {e}")
                        finally:
                            self.video_mode = None

                    # Speed
                    vt_speed = self.user_dict.get("VT_SPEED")
                    if not self.video_mode and vt_speed:
                        try:
                            parts = [x.strip() for x in vt_speed.split(",")]
                            if len(parts) == 2:
                                speed_type = (
                                    parts[0] if parts[0] in ("up", "down") else "up"
                                )
                                try:
                                    speed_number = float(parts[1])
                                except Exception:
                                    speed_number = 1.0
                                kwargs = {
                                    "speed_number": speed_number,
                                    "speed_type": speed_type,
                                }
                                self.video_mode = ("speed", self.name, False, kwargs)
                                LOGGER.info(
                                    f"Task {self.mid}: Auto VideoToolsExecutor (speed) for {up_path} -> {vt_speed}"
                                )
                                executed_up_path = await VideoToolsExecutor(
                                    self, up_path, gid, unwanted_files
                                ).execute()
                                if executed_up_path and executed_up_path != up_path:
                                    up_path = executed_up_path
                                    self.path = up_path
                                    self.is_file = await aiopath.isfile(up_path)
                                    self.name = ospath.basename(
                                        up_path.rstrip(ospath.sep)
                                    )
                                    self.size = await get_path_size(up_path)
                                    self.seed = False
                                    video_tools_processed = True
                        except Exception as e:
                            LOGGER.error(f"Task {self.mid}: Auto speed error: {e}")
                        finally:
                            self.video_mode = None

                    # Compress
                    vt_compress = self.user_dict.get("VT_COMPRESS")
                    if not self.video_mode and vt_compress:
                        try:
                            kwargs = {}
                            for token in vt_compress.split(","):
                                if "=" in token:
                                    k, v = token.split("=", 1)
                                    k = k.strip()
                                    v = v.strip()
                                    if k in ("quality", "crf", "bitrate", "bitdepth"):
                                        if k in ("crf", "bitrate"):
                                            try:
                                                kwargs[k] = int(v)
                                            except Exception:
                                                kwargs[k] = v
                                        else:
                                            kwargs[k] = v
                            self.video_mode = ("compress", self.name, False, kwargs)
                            LOGGER.info(
                                f"Task {self.mid}: Auto VideoToolsExecutor (compress) for {up_path} -> {kwargs}"
                            )
                            executed_up_path = await VideoToolsExecutor(
                                self, up_path, gid, unwanted_files
                            ).execute()
                            if executed_up_path and executed_up_path != up_path:
                                up_path = executed_up_path
                                self.path = up_path
                                self.is_file = await aiopath.isfile(up_path)
                                self.name = ospath.basename(up_path.rstrip(ospath.sep))
                                self.size = await get_path_size(up_path)
                                self.seed = False
                                video_tools_processed = True
                        except Exception as e:
                            LOGGER.error(f"Task {self.mid}: Auto compress error: {e}")
                        finally:
                            self.video_mode = None

                    # Watermark
                    vt_wm = self.user_dict.get("VT_WATERMARK")
                    if not self.video_mode and vt_wm:
                        try:
                            kwargs = {}
                            for token in vt_wm.split(","):
                                if "=" in token:
                                    k, v = token.split("=", 1)
                                    k = k.strip()
                                    v = v.strip()
                                    if k == "popup":
                                        try:
                                            kwargs["wm_popup"] = int(v)
                                        except Exception:
                                            kwargs["wm_popup"] = v
                                    elif k == "hardsub":
                                        kwargs["hardsub"] = v.lower() in (
                                            "1",
                                            "true",
                                            "yes",
                                        )
                                    elif k == "size":
                                        try:
                                            kwargs["wm_size"] = int(v)
                                        except Exception:
                                            kwargs["wm_size"] = v
                                    elif k == "position":
                                        kwargs["wm_position"] = v
                                else:
                                    k = token.lower()
                                    if k == "hardsub":
                                        kwargs["hardsub"] = True
                            # Respect explicit toggle from user setting if provided and not set above
                            if "hardsub" not in kwargs:
                                try:
                                    hs_style = self.user_dict.get(
                                        "VT_HARDSUB_STYLE", "default"
                                    )
                                    # Enable hardsub if style is set to anything other than default
                                    kwargs["hardsub"] = hs_style != "default"
                                    # Pass the style to the executor
                                    if hs_style != "default":
                                        kwargs["hardsub_style"] = hs_style
                                except Exception:
                                    pass
                            # Only run watermark if there is an actual image or text configured
                            wm_img = self.user_dict.get("VT_WATERMARK_IMAGE")
                            has_img = bool(wm_img) and await aiopath.exists(wm_img)
                            has_text = bool(self.user_dict.get("VT_WATERMARK_TEXT"))
                            if not has_img and not has_text:
                                LOGGER.info(
                                    f"Task {self.mid}: Skipping auto watermark (no image/text configured)."
                                )
                            else:
                                self.video_mode = (
                                    "watermark",
                                    self.name,
                                    False,
                                    kwargs,
                                )
                                LOGGER.info(
                                    f"Task {self.mid}: Auto VideoToolsExecutor (watermark) for {up_path} -> {kwargs}"
                                )
                                executed_up_path = await VideoToolsExecutor(
                                    self, up_path, gid, unwanted_files
                                ).execute()
                                if executed_up_path and executed_up_path != up_path:
                                    up_path = executed_up_path
                                    self.path = up_path
                                    self.is_file = await aiopath.isfile(up_path)
                                    self.name = ospath.basename(
                                        up_path.rstrip(ospath.sep)
                                    )
                                    self.size = await get_path_size(up_path)
                                    self.seed = False
                                    video_tools_processed = True
                        except Exception as e:
                            LOGGER.error(f"Task {self.mid}: Auto watermark error: {e}")
                        finally:
                            self.video_mode = None

                    # Intro Subtitle (auto from user settings)
                    if not self.video_mode and self.user_dict.get(
                        "INTRO_SUBTITLE_ENABLED", False
                    ):
                        try:
                            self.video_mode = ("intro_sub", self.name, False, {})
                            LOGGER.info(
                                f"Task {self.mid}: Auto VideoToolsExecutor (intro_sub) for {up_path}."
                            )
                            executed_up_path = await VideoToolsExecutor(
                                self, up_path, gid, unwanted_files
                            ).execute()
                            if executed_up_path and executed_up_path != up_path:
                                up_path = executed_up_path
                                self.path = up_path
                                self.is_file = await aiopath.isfile(up_path)
                                self.name = ospath.basename(up_path.rstrip(ospath.sep))
                                self.size = await get_path_size(up_path)
                                self.seed = False
                                video_tools_processed = True
                                # Set flag to prevent duplicate intro_sub processing
                                self._intro_sub_applied = True
                                LOGGER.info(
                                    f"Task {self.mid}: Auto intro_sub completed, marked as processed"
                                )
                        except Exception as e:
                            LOGGER.error(f"Task {self.mid}: Auto intro_sub error: {e}")
                        finally:
                            self.video_mode = None

                    # Subsync
                    if (
                        not self.video_mode
                        and self.user_dict.get("VT_SUBSYNC")
                        and not await aiopath.isfile(up_path)
                    ):
                        try:
                            self.video_mode = (
                                "subsync",
                                self.name,
                                False,
                                {"sync_type": "sync_auto"},
                            )
                            LOGGER.info(
                                f"Task {self.mid}: Auto VideoToolsExecutor (subsync) for {up_path}"
                            )
                            executed_up_path = await VideoToolsExecutor(
                                self, up_path, gid, unwanted_files
                            ).execute()
                            if executed_up_path and executed_up_path != up_path:
                                up_path = executed_up_path
                                self.path = up_path
                                self.is_file = await aiopath.isfile(up_path)
                                self.name = ospath.basename(up_path.rstrip(ospath.sep))
                                self.size = await get_path_size(up_path)
                                self.seed = False
                                video_tools_processed = True
                        except Exception as e:
                            LOGGER.error(f"Task {self.mid}: Auto subsync error: {e}")
                        finally:
                            self.video_mode = None

                    # Convert (scale only) via VT_CONVERT_QUALITY
                    vt_convert = self.user_dict.get("VT_CONVERT_QUALITY")
                    if not self.video_mode and vt_convert:
                        try:
                            data_quality = str(vt_convert).strip()
                            # Support extended format: quality,crf=23,bitrate=1200,bitdepth=yuv420p10le
                            parts = [
                                p.strip() for p in data_quality.split(",") if p.strip()
                            ]
                            quality_only = None
                            extra_kwargs = {}
                            for part in parts:
                                if "=" in part:
                                    k, v = part.split("=", 1)
                                    k = k.strip().lower()
                                    v = v.strip()
                                    if k in ("crf", "bitrate"):
                                        try:
                                            extra_kwargs[k] = int(v)
                                        except Exception:
                                            extra_kwargs[k] = v
                                    elif k == "bitdepth":
                                        extra_kwargs[k] = v
                                else:
                                    # treat as quality token
                                    quality_only = part
                            if not quality_only:
                                # fallback: whole string could be quality only
                                if data_quality in (
                                    "1080p",
                                    "720p",
                                    "540p",
                                    "480p",
                                    "360p",
                                ):
                                    quality_only = data_quality
                            if quality_only in (
                                "1080p",
                                "720p",
                                "540p",
                                "480p",
                                "360p",
                            ):
                                # Pre-fill data for convert and mark auto
                                self.video_mode = (
                                    "convert",
                                    self.name,
                                    False,
                                    {"auto": True, **extra_kwargs},
                                )
                                # Pass desired quality to executor through listener shim
                                setattr(self, "video_convert_prefill", quality_only)
                                LOGGER.info(
                                    f"Task {self.mid}: Auto VideoToolsExecutor (convert) for {up_path} -> {quality_only}, kwargs={extra_kwargs}"
                                )
                                executed_up_path = await VideoToolsExecutor(
                                    self, up_path, gid, unwanted_files
                                ).execute()
                                # Clean prefill
                                if hasattr(self, "video_convert_prefill"):
                                    delattr(self, "video_convert_prefill")
                                if executed_up_path and executed_up_path != up_path:
                                    up_path = executed_up_path
                                    self.path = up_path
                                    self.is_file = await aiopath.isfile(up_path)
                                    self.name = ospath.basename(
                                        up_path.rstrip(ospath.sep)
                                    )
                                    self.size = await get_path_size(up_path)
                                    self.seed = False
                                    video_tools_processed = True
                        except Exception as e:
                            LOGGER.error(f"Task {self.mid}: Auto convert error: {e}")
                        finally:
                            self.video_mode = None

                    auto_remove = self.user_dict.get("VT_AUDIO_REMOVE")
                    auto_order = self.user_dict.get("VT_AUDIO_ORDER")
                    if auto_remove or auto_order:
                        LOGGER.info(
                            f"Task {self.mid}: Auto VideoTools from settings: remove={bool(auto_remove)} order={bool(auto_order)}"
                        )
                        # Run remove first, then reorder
                        for mode in (["rmstream"] if auto_remove else []) + (
                            ["reordertracks"] if auto_order else []
                        ):
                            try:
                                self.video_mode = (mode, self.name, False, {})
                                LOGGER.info(
                                    f"Task {self.mid}: Starting Auto VideoToolsExecutor ({mode}) for {up_path}."
                                )
                                executed_up_path = await VideoToolsExecutor(
                                    self, up_path, gid, unwanted_files
                                ).execute()
                                if self.is_cancelled:
                                    LOGGER.info(
                                        f"Task {self.mid}: Cancelled during Auto VideoToolsExecutor ({mode})."
                                    )
                                    return
                                if executed_up_path and executed_up_path != up_path:
                                    up_path = executed_up_path
                                    self.path = up_path
                                    self.is_file = await aiopath.isfile(up_path)
                                    self.name = ospath.basename(
                                        up_path.rstrip(ospath.sep)
                                    )
                                    self.size = await get_path_size(up_path)
                                    self.seed = False
                                    video_tools_processed = True
                                    LOGGER.info(
                                        f"Task {self.mid}: After Auto VideoToolsExecutor ({mode}) - up_path: {up_path}, name: {self.name}, size: {self.size}, seed: {self.seed}"
                                    )
                            except Exception as e:
                                LOGGER.error(
                                    f"Task {self.mid}: Auto VideoToolsExecutor ({mode}) error: {e}"
                                )
                            finally:
                                self.video_mode = None
            except Exception as e:
                LOGGER.error(
                    f"Task {self.mid}: Auto VideoTools settings handler error: {e}"
                )

            # Process video tools (if not pre-executed)
            if self.video_mode and not video_tools_processed:
                try:
                    LOGGER.info(
                        f"Task {self.mid}: Starting VideoToolsExecutor for {up_path}."
                    )
                    original_size_before_vidtools = self.size
                    original_is_file_before_vidtools = self.is_file
                    original_up_path_before_vidtools = up_path
                    original_name_before_vidtools = self.name

                    executed_up_path = await VideoToolsExecutor(
                        self, up_path, gid, unwanted_files
                    ).execute()

                    if self.is_cancelled:
                        LOGGER.info(
                            f"Task {self.mid}: Cancelled during VideoToolsExecutor."
                        )
                        return

                    # Handle video tools results
                    if (
                        executed_up_path == original_up_path_before_vidtools
                        and not self.data_from_video_tool_selection
                    ):
                        up_path = original_up_path_before_vidtools
                        self.is_file = original_is_file_before_vidtools
                        self.name = original_name_before_vidtools
                        self.size = original_size_before_vidtools
                        LOGGER.debug(
                            f"Task {self.mid}: VideoToolsExecutor same path; kept original attributes."
                        )
                    else:
                        up_path = executed_up_path
                        self.is_file = await aiopath.isfile(up_path)
                        self.name = ospath.basename(up_path.rstrip(ospath.sep))
                        self.size = await get_path_size(up_path)
                        if (
                            self.data_from_video_tool_selection
                            or up_path != original_up_path_before_vidtools
                        ):
                            self.seed = False

                        # If this was an intro_sub operation, mark it as processed
                        if (
                            hasattr(self, "video_mode")
                            and self.video_mode
                            and self.video_mode[0] == "intro_sub"
                        ):
                            self._intro_sub_applied = True
                            LOGGER.info(
                                f"Task {self.mid}: Manual intro_sub completed, marked as processed"
                            )

                        # [IMPROVEMENT] Consistently set video_tools_processed flag after any successful execution
                        video_tools_processed = True
                        LOGGER.info(
                            f"Task {self.mid}: After VideoToolsExecutor - up_path: {up_path}, name: {self.name}, size: {self.size}, seed: {self.seed}"
                        )
                except Exception as e:
                    LOGGER.error(f"Error during video tools processing: {e}")
            elif video_tools_processed:
                up_path = self.path
                LOGGER.info(
                    f"Task {self.mid}: Video tool was pre-executed. Using path: {up_path}"
                )

            # Process intro_sub AFTER video tools (if enabled in user settings)
            should_process_intro_sub = (
                self.user_dict.get("INTRO_SUBTITLE_ENABLED", False)
                and not self.is_cancelled
            )

            if should_process_intro_sub:
                try:
                    from ..ext_utils.intro_sub_processor import (
                        apply_intro_sub_processing,
                    )

                    # Check if intro_sub was already processed to avoid double processing
                    intro_already_processed = False

                    # Method 1: Check if video tools mode was intro_sub
                    if hasattr(self, "video_mode") and self.video_mode:
                        try:
                            intro_already_processed = bool(
                                self.video_mode[0] == "intro_sub"
                            )
                        except (IndexError, TypeError):
                            pass

                    # Method 2: Check if filename already contains "_intro" indicating previous processing
                    if not intro_already_processed:
                        file_basename = (
                            ospath.basename(up_path) if self.is_file else self.name
                        )
                        if "_intro" in file_basename and file_basename.endswith(
                            (".mkv", ".mp4")
                        ):
                            intro_already_processed = True
                            LOGGER.info(
                                f"Task {self.mid}: Detected already processed intro_sub file: {file_basename}"
                            )

                    # Method 3: Check if we have a flag indicating intro_sub was already applied
                    if not intro_already_processed and hasattr(
                        self, "_intro_sub_applied"
                    ):
                        intro_already_processed = self._intro_sub_applied
                        LOGGER.info(
                            f"Task {self.mid}: Detected intro_sub already applied via flag"
                        )

                    if not intro_already_processed:
                        LOGGER.info(
                            f"Task {self.mid}: Applying intro_sub post-processing as per user settings"
                        )

                        # Apply intro_sub processing
                        processed_path = await apply_intro_sub_processing(
                            self, up_path, self.user_id
                        )

                        if processed_path and processed_path != up_path:
                            # Update path if processing created new files
                            up_path = processed_path
                            LOGGER.info(
                                f"Task {self.mid}: intro_sub processing completed, updated path: {up_path}"
                            )

                            # Update size and file properties after intro_sub processing
                            try:
                                self.size = await get_path_size(up_path)
                                # Update is_file status as intro_sub might change file structure
                                self.is_file = await aiopath.isfile(up_path)
                                # Update name to reflect the new structure
                                if self.is_file:
                                    self.name = ospath.basename(up_path)
                                else:
                                    self.name = ospath.basename(
                                        up_path.rstrip(ospath.sep)
                                    )
                                LOGGER.info(
                                    f"Task {self.mid}: Updated properties after intro_sub - is_file: {self.is_file}, name: {self.name}, size: {self.size}"
                                )
                            except Exception as e:
                                LOGGER.warning(
                                    f"Task {self.mid}: Error updating properties after intro_sub: {e}"
                                )
                        else:
                            LOGGER.info(
                                f"Task {self.mid}: intro_sub processing completed (no path change)"
                            )

                        # Set flag to prevent future intro_sub processing on this task
                        self._intro_sub_applied = True
                    else:
                        LOGGER.info(
                            f"Task {self.mid}: Skipping intro_sub post-processing - already processed (detected via filename or mode)"
                        )

                except Exception as e:
                    LOGGER.warning(
                        f"Task {self.mid}: intro_sub post-processing failed: {e}"
                    )

                # Clear cached properties after intro_sub processing to ensure fresh values
                self.clear()
            else:
                LOGGER.debug(
                    f"Task {self.mid}: Skipping intro_sub post-processing (not enabled or cancelled)"
                )

            # Process metadata and attachments AFTER intro_sub
            # [FIX] Initialize current_processed_path here to ensure it has the latest up_path value
            current_processed_path = up_path

            # Get user settings for metadata/attachment processing
            self.user_dict = user_data.get(self.user_id, {})
            user_photo_path = self.user_dict.get("USER_ATTACHMENT_PHOTO")
            user_text_content = self.user_dict.get("USER_ATTACHMENT_TEXT")
            user_metadata_settings = self.user_dict.get("METADATA_SETTINGS", {})
            user_metadata_all = self.user_dict.get("metadata_all")
            cmd_line_thumb_path = self.thumb

            # Prepare metadata tags
            final_tags_to_apply = {}
            if isinstance(user_metadata_settings, dict):
                final_tags_to_apply.update(user_metadata_settings)

            #  if user_metadata_all and str(user_metadata_all).lower() not in [
            #      "false",
            #       "",
            #  ]:
            #     final_tags_to_apply["metadata_all"] = user_metadata_all

            # Filter out empty values
            final_tags_to_apply = {
                k: v
                for k, v in final_tags_to_apply.items()
                if v and str(v).lower() not in ["false", ""] and str(v).strip() != ""
            }

            # Determine thumbnail path
            actual_thumbnail_to_embed_path = None

            # Handle user attachment photo with path resolution
            if user_photo_path:
                # Try the path as-is first
                if await aiopath.exists(user_photo_path):
                    actual_thumbnail_to_embed_path = user_photo_path
                else:
                    # Try to resolve relative path to absolute
                    if not os.path.isabs(user_photo_path):
                        absolute_path = os.path.join(os.getcwd(), user_photo_path)
                        if await aiopath.exists(absolute_path):
                            actual_thumbnail_to_embed_path = absolute_path
                        else:
                            LOGGER.warning(
                                f"Task {self.mid}: User attachment photo not found at relative or absolute path: {user_photo_path}"
                            )
                    else:
                        LOGGER.warning(
                            f"Task {self.mid}: User attachment photo not found at absolute path: {user_photo_path}"
                        )

            # Fallback to command line thumbnail
            if (
                not actual_thumbnail_to_embed_path
                and cmd_line_thumb_path
                and await aiopath.exists(cmd_line_thumb_path)
            ):
                actual_thumbnail_to_embed_path = cmd_line_thumb_path

            # Fallback to default thumbnail only if EMBED_DEFAULT_USER_THUMBNAIL is enabled
            if not actual_thumbnail_to_embed_path:
                embed_default_thumb = self.user_dict.get(
                    "EMBED_DEFAULT_USER_THUMBNAIL", False
                )
                if embed_default_thumb:
                    default_thumb_path = f"thumbnails/{self.user_id}.jpg"
                    if await aiopath.exists(default_thumb_path):
                        actual_thumbnail_to_embed_path = default_thumb_path

            # Prepare text content
            text_for_attachment = user_text_content
            if (
                text_for_attachment
                and str(text_for_attachment).strip().lower() == "none"
            ):
                text_for_attachment = None

            # Determine if metadata processing is needed
            should_process_metadata_attachments = bool(
                final_tags_to_apply
                or actual_thumbnail_to_embed_path
                or text_for_attachment
            )

            # User's requested explicit check
            if not user_metadata_settings and not user_metadata_all:
                should_process_metadata_attachments = bool(
                    actual_thumbnail_to_embed_path or text_for_attachment
                )

            # Check compress settings for metadata
            if should_process_metadata_attachments and self.compress:
                apply_zip_meta = self.user_dict.get("ZIP_METADATA", Config.ZIP_METADATA)
                if not apply_zip_meta:
                    should_process_metadata_attachments = False

            # Process metadata and attachments
            if should_process_metadata_attachments and not self.is_cancelled:
                # For video tools processed files, use directory path for metadata to process all files
                if video_tools_processed and await aiopath.isdir(self.dir):
                    # [IMPROVEMENT] Use up_path for directory metadata to handle cases where path was modified
                    current_input_path = (
                        up_path if await aiopath.isdir(up_path) else self.dir
                    )
                    LOGGER.info(
                        f"Task {self.mid}: Video tools processed - applying metadata to directory: {current_input_path}"
                    )
                else:
                    current_input_path = current_processed_path  # Use the fresh path

                if not await aiopath.exists(current_input_path):
                    LOGGER.error(
                        f"Input file for metadata/attachment does not exist: {current_input_path}. Skipping."
                    )
                else:
                    try:
                        # Determine operation type
                        op_type = ""
                        has_meta = bool(final_tags_to_apply)
                        has_attach = bool(
                            actual_thumbnail_to_embed_path or text_for_attachment
                        )
                        if has_meta:
                            op_type = "meta"
                        elif has_attach:
                            op_type = "attach"

                        if op_type:
                            # Initialize progress handler
                            meta_progress_handler = FFProgress()
                            meta_progress_handler._start_time = time()

                            if self.is_file:
                                try:
                                    media_duration_seconds, _, _ = await get_media_info(
                                        current_input_path
                                    )
                                    meta_progress_handler._duration = (
                                        media_duration_seconds
                                        if media_duration_seconds > 0
                                        else self.size
                                    )
                                except Exception as e:
                                    LOGGER.warning(
                                        f"Error getting media info for metadata processing: {e}"
                                    )
                                    meta_progress_handler._duration = self.size
                            else:
                                meta_progress_handler._duration = self.size

                            # Set up status tracking
                            original_task_status_obj = None
                            async with task_dict_lock:
                                if self.mid in task_dict:
                                    original_task_status_obj = task_dict[self.mid]
                                task_dict[self.mid] = FFMpegStatus(
                                    self, meta_progress_handler, gid, op_type
                                )

                            # Prepare settings for metadata helper
                            settings_for_helper = final_tags_to_apply.copy()
                            if actual_thumbnail_to_embed_path:
                                settings_for_helper["attachment_thumbnail"] = (
                                    actual_thumbnail_to_embed_path
                                )
                            if text_for_attachment:
                                settings_for_helper["attachment_text"] = (
                                    text_for_attachment
                                )

                            # Define progress callback
                            async def _metadata_phase_progress_updater(
                                percentage,
                                speed_multiplier,
                                processed_bytes_val,
                                eta_seconds,
                            ):
                                if self.is_cancelled:
                                    return
                                try:
                                    await (
                                        meta_progress_handler.update_progress_from_pipe(
                                            percentage,
                                            processed_bytes_val,
                                            eta_seconds,
                                            speed_multiplier,
                                        )
                                    )

                                    # Update status less frequently to reduce load
                                    current_time = time()
                                    if not hasattr(self, "_last_status_update"):
                                        self._last_status_update = 0

                                    # Update status every 5 seconds or if significant progress change
                                    if (
                                        current_time - self._last_status_update > 5
                                        or percentage >= 99
                                        or percentage == 0
                                    ):
                                        self._last_status_update = current_time
                                        if (
                                            self.message
                                            and hasattr(self.message, "chat")
                                            and self.message.chat
                                        ):
                                            await update_status_message(
                                                self.message.chat.id
                                            )
                                except Exception as e:
                                    LOGGER.warning(
                                        f"Error updating metadata progress: {e}"
                                    )

                            # Apply metadata
                            apply_metadata_success = (
                                await metadata_helper.apply_metadata(
                                    file_path=current_input_path,
                                    metadata_settings=settings_for_helper,
                                    progress_callback=_metadata_phase_progress_updater,
                                )
                            )

                            if self.is_cancelled:
                                return

                            self.listener_processed_media = bool(apply_metadata_success)
                            LOGGER.info(
                                f"Task {self.mid}: Metadata/attachment processing {'successful' if apply_metadata_success else 'failed'}."
                            )

                            # Clean up status
                            async with task_dict_lock:
                                if (
                                    self.mid in task_dict
                                    and isinstance(task_dict[self.mid], FFMpegStatus)
                                    and task_dict[self.mid]._status
                                    in ["meta", "attach"]
                                ):
                                    del task_dict[self.mid]
                                    LOGGER.info(
                                        f"Task {self.mid}: Removed FFMpegStatus for metadata/attach from task_dict."
                                    )

                            # Final status update omitted to reduce noise

                    except Exception as e:
                        LOGGER.error(
                            f"Error during metadata/attachment processing: {e}"
                        )
                        self.listener_processed_media = False
            else:
                LOGGER.info(f"Task {self.mid}: Skipped metadata/attachment processing.")

            # [IMPROVEMENT] Simplified path finalization. up_path is already the source of truth.
            # No need for complex reassignment from current_processed_path.

            self.name = ospath.basename(up_path.rstrip(ospath.sep))
            self.is_file = await aiopath.isfile(up_path)

            LOGGER.info(
                f"Task {self.mid}: After metadata stage - up_path: {up_path}, name: {self.name}, is_file: {self.is_file}"
            )

            # [ENHANCEMENT] More robust path and size validation with recovery
            if await aiopath.exists(up_path):
                await asyncio.sleep(0.2)
                try:
                    if hasattr(os, "sync"):
                        os.sync()
                except Exception:
                    pass

                self.size = await get_path_size(up_path)
                LOGGER.info(f"Task {self.mid}: Size from up_path: {self.size}")

                # Check for zero-size file issue and try to recover
                if self.size == 0:
                    LOGGER.warning(
                        f"Task {self.mid}: Path {up_path} has zero size after processing. Retrying size check..."
                    )
                    for retry_attempt in range(3):
                        await asyncio.sleep(0.5 * (retry_attempt + 1))
                        retry_size = await get_path_size(up_path)
                        if retry_size > 0:
                            self.size = retry_size
                            LOGGER.info(
                                f"Task {self.mid}: Recovered size on attempt {retry_attempt + 1}: {get_readable_file_size(self.size)}"
                            )
                            break
                        else:
                            LOGGER.warning(
                                f"Task {self.mid}: Retry {retry_attempt + 1} still shows zero size."
                            )

                    # If still zero after retries, revert to original
                    if self.size == 0 and await aiopath.exists(
                        original_path_for_fallback
                    ):
                        LOGGER.error(
                            f"Task {self.mid}: Path is still zero size. Reverting to original path due to processing failure."
                        )
                        up_path = original_path_for_fallback
                        self.name = ospath.basename(up_path.rstrip(ospath.sep))
                        self.is_file = await aiopath.isfile(up_path)
                        self.size = await get_path_size(up_path)
                        LOGGER.info(
                            f"Task {self.mid}: Reverted to {up_path}, new size: {get_readable_file_size(self.size)}"
                        )
                    elif self.size == 0:
                        LOGGER.error(
                            f"Task {self.mid}: Path is zero bytes and original fallback path is missing."
                        )

            else:
                LOGGER.warning(
                    f"Task {self.mid}: Path {up_path} does not exist after processing."
                )
                if await aiopath.exists(original_path_for_fallback):
                    up_path = original_path_for_fallback
                    self.name = ospath.basename(up_path.rstrip(ospath.sep))
                    self.is_file = await aiopath.isfile(up_path)
                    self.size = await get_path_size(up_path)
                    LOGGER.info(
                        f"Task {self.mid}: Reverted to original path: {up_path}"
                    )
                else:
                    await self.on_upload_error(
                        f"CRITICAL: Final and original processing paths are missing. Cannot continue."
                    )
                    return

            # Re-check path existence before proceeding
            if not await aiopath.exists(up_path):
                await self.on_upload_error(
                    f"Upload path is missing before compression/split stage: {up_path}"
                )
                return
            else:
                self.is_file = await aiopath.isfile(up_path)

            # Process sample video
            if self.sample_video:
                try:
                    LOGGER.info(
                        f"Task {self.mid}: Starting sample video generation for {up_path}."
                    )
                    up_path = await self.generate_sample_video(up_path, gid)
                    if self.is_cancelled:
                        LOGGER.info(
                            f"Task {self.mid}: Cancelled during sample video generation."
                        )
                        return

                    self.is_file = await aiopath.isfile(up_path)
                    self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
                    self.size = await get_path_size(up_dir)
                    self.clear()
                    LOGGER.info(
                        f"Task {self.mid}: After sample video - up_path: {up_path}, name: {self.name}, size: {self.size}"
                    )
                except Exception as e:
                    LOGGER.error(f"Error during sample video generation: {e}")

            # Process compression
            if self.compress:
                try:
                    LOGGER.info(f"Task {self.mid}: Starting compression for {up_path}.")
                    up_path = await self.proceed_compress(up_path, gid)
                    self.is_file = await aiopath.isfile(up_path)
                    if self.is_cancelled:
                        LOGGER.info(f"Task {self.mid}: Cancelled during compression.")
                        return
                    self.clear()
                    LOGGER.info(
                        f"Task {self.mid}: After compression - up_path: {up_path}, name: {self.name}, is_file: {self.is_file}"
                    )
                except Exception as e:
                    LOGGER.error(f"Error during compression: {e}")

            # Sanitize trailing tags after all video processing
            try:
                up_path = await self._sanitize_path(up_path)
                self.name = ospath.basename(up_path.rstrip(ospath.sep))
                if hasattr(self, "path") and self.path == self.name:
                    self.path = up_path
            except Exception as _san_e:
                LOGGER.warning(
                    f"Task {self.mid}: Filename sanitization skipped after video tools due to error: {_san_e}"
                )

            # Update final properties
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_path)
            LOGGER.info(
                f"Task {self.mid}: After all pre-upload processing (except split) - name: {self.name}, size: {get_readable_file_size(self.size)}"
            )

            # Process filename for upload (final)
            try:
                # Skip final filename processing if already done right after extraction
                if not getattr(self, "_post_extract_name_processed", False):
                    LOGGER.debug(
                        f"Task {self.mid}: Final pass calling process_filename_for_upload with name={self.name}, up_path={up_path}"
                    )
                    processed_cloud_name, up_path = await process_filename_for_upload(
                        self, self.name, up_path
                    )
                    LOGGER.debug(
                        f"Task {self.mid}: Final pass returned processed_cloud_name={processed_cloud_name}, up_path={up_path}"
                    )
                    if processed_cloud_name:
                        self.name = processed_cloud_name
                    LOGGER.info(
                        f"Task {self.mid}: After final process_filename_for_upload - name: {self.name}, up_path: {up_path}"
                    )
            except Exception as e:
                LOGGER.error(f"Error in final filename processing: {e}")

            # Process directory items if needed
            if await aiopath.isdir(up_path):
                LOGGER.info(
                    f"Task {self.mid}: Path {up_path} is a directory. Processing items within for filename."
                )
                try:
                    items_in_dir = await listdir(up_path)
                    for item_name in items_in_dir:
                        if self.is_cancelled:
                            return
                        item_full_path = ospath.join(up_path, item_name)
                        try:
                            LOGGER.debug(
                                f"Task {self.mid}: Processing directory item for filename: item_name={item_name}, item_full_path={item_full_path}"
                            )
                            _, _ = await process_filename_for_upload(
                                self, item_name, item_full_path
                            )
                            LOGGER.debug(
                                f"Task {self.mid}: Finished processing directory item: {item_name}"
                            )
                        except Exception as e_proc_item:
                            LOGGER.error(
                                f"Error processing item {item_name} in {up_path}: {e_proc_item}"
                            )
                except Exception as e_proc_dir:
                    LOGGER.error(
                        f"Error processing directory items in {up_path}: {e_proc_dir}"
                    )

            # Handle splitting for leech tasks
            split_processing_successful = True
            if self.is_leech and self.split_size > 0:
                try:
                    LOGGER.info(
                        f"Task {self.mid}: Leech task with valid split size detected. Initiating split logic for path: {up_path}"
                    )
                    LOGGER.info(
                        f"Task {self.mid}: Current split settings: Size={get_readable_file_size(self.split_size)}, Max={get_readable_file_size(self.max_split_size)}, Equal={self.equal_splits}, AsDoc={self.as_doc}"
                    )

                    split_processing_successful = await self.proceed_split(up_path, gid)

                    if self.is_cancelled:
                        LOGGER.info(
                            f"Task {self.mid}: Cancelled during or after proceed_split."
                        )
                        return

                    if not split_processing_successful and self.max_split_size > 0:
                        current_size_after_split_attempt = await get_path_size(up_path)
                        if (
                            self.is_file
                            and current_size_after_split_attempt > self.max_split_size
                        ):
                            error_msg = (
                                f"File '{self.name}' ({get_readable_file_size(current_size_after_split_attempt)}) "
                                f"is still too large for Telegram upload (Max: {get_readable_file_size(self.max_split_size)}) "
                                f"after split attempt. Task cancelled."
                            )
                            LOGGER.error(f"Task {self.mid}: {error_msg}")
                            await self.on_upload_error(error_msg)
                            return
                        elif not self.is_file:
                            LOGGER.info(
                                f"Task {self.mid}: proceed_split returned False for directory {up_path}. Assuming contents are managed or no files needed splitting."
                            )
                        else:
                            LOGGER.info(
                                f"Task {self.mid}: proceed_split returned False for file {up_path}, but file is not too large. Proceeding with original."
                            )
                except Exception as e:
                    LOGGER.error(f"Error during splitting: {e}")
                    split_processing_successful = False
            else:
                LOGGER.info(
                    f"Task {self.mid}: Task is not a leech or split size is invalid (0). Skipping split."
                )

            self.clear()

            # Update final file properties
            if await aiopath.isdir(up_path):
                self.is_file = False
                if (
                    original_path_for_fallback == dl_path
                    and await aiopath.isfile(original_path_for_fallback)
                    and not await aiopath.exists(original_path_for_fallback)
                ):
                    self.name = ospath.basename(self.dir.rstrip(ospath.sep))
                    LOGGER.info(
                        f"Task {self.mid}: Original file split into parts. Upload name set to task directory: {self.name}"
                    )
                else:
                    self.name = ospath.basename(up_path.rstrip(ospath.sep))
                    LOGGER.info(
                        f"Task {self.mid}: Path is a directory. Upload name set to: {self.name}"
                    )
            else:
                self.is_file = True
                self.name = ospath.basename(up_path)

            self.size = await get_path_size(up_dir)
            # Check for zero-size file issue and try to recover
            if self.size == 0:
                LOGGER.warning(
                    f"Task {self.mid}: Path {up_path} has zero size after splitting. Retrying size check..."
                )
                for retry_attempt in range(3):
                    await asyncio.sleep(0.5 * (retry_attempt + 1))
                    retry_size = await get_path_size(up_path)
                    if retry_size > 0:
                        self.size = retry_size
                        LOGGER.info(
                            f"Task {self.mid}: Recovered size on attempt {retry_attempt + 1}: {get_readable_file_size(self.size)}"
                        )
                        break
                    else:
                        LOGGER.warning(
                            f"Task {self.mid}: Retry {retry_attempt + 1} still shows zero size."
                        )
            LOGGER.info(
                f"Task {self.mid}: Final upload properties - name: {self.name}, is_file: {self.is_file}, size: {get_readable_file_size(self.size)}"
            )

            self.subproc = None
            LOGGER.info(
                f"Task {self.mid}: All pre-upload processing finished. Final up_path: {up_path}, Final up_dir: {up_dir}"
            )

            # Handle upload queue
            add_to_queue, event = await check_running_tasks(self, "up")
            if add_to_queue:
                LOGGER.info(f"Task {self.mid}: Queued for upload. GID: {gid}")
                async with task_dict_lock:
                    task_dict[self.mid] = QueueStatus(self, gid, "Up")
                await event.wait()
                if self.is_cancelled:
                    LOGGER.info(f"Task {self.mid}: Cancelled while in upload queue.")
                    return
                LOGGER.info(f"Task {self.mid}: Dequeued for upload.")
            else:
                LOGGER.info(
                    f"Task {self.mid}: Not queued for upload, proceeding directly."
                )

            # Set up leech transmission settings
            if self.is_leech:
                BOT_MAX_SIZE = 2097152000
                self.user_transmission = False
                self.hybrid_leech = False
                self.bot_trans = True

                final_size = await get_path_size(up_dir)

                if final_size > BOT_MAX_SIZE:
                    if TgClient.user and TgClient.IS_PREMIUM_USER:
                        self.user_transmission = True
                        self.hybrid_leech = (
                            self.user_dict.get("HYBRID_LEECH") or Config.HYBRID_LEECH
                        )
                        if self.hybrid_leech:
                            self.bot_trans = True
                        else:
                            self.bot_trans = False
                        LOGGER.info(
                            f"User session forced: File size {get_readable_file_size(final_size)} > {get_readable_file_size(BOT_MAX_SIZE)}."
                        )
                    else:
                        LOGGER.warning(
                            f"File size {get_readable_file_size(final_size)} > {get_readable_file_size(BOT_MAX_SIZE)}, but no premium user account is available. Upload will rely on splitting."
                        )
                else:
                    LOGGER.info(
                        f"Bot session allowed: File size {get_readable_file_size(final_size)} <= {get_readable_file_size(BOT_MAX_SIZE)}."
                    )

            # Execute upload based on destination
            upload_tasks = []
            try:
                if self.is_yt:
                    LOGGER.info(
                        f"Task {self.mid}: Initiating YouTubeUpload with path {up_path}."
                    )
                    yt = YouTubeUpload(self, up_path)
                    async with task_dict_lock:
                        task_dict[self.mid] = YtStatus(self, yt, gid, "up")
                    upload_tasks = [
                        update_status_message(self.message.chat.id),
                        sync_to_async(yt.upload),
                    ]
                    await gather(*upload_tasks)
                    del yt
                    LOGGER.info(f"Task {self.mid}: YouTubeUpload finished.")

                elif self.is_leech:
                    LOGGER.info(
                        f"Task {self.mid}: Initiating TelegramUploader with directory {up_dir}."
                    )
                    tg = TelegramUploader(self, up_dir)
                    async with task_dict_lock:
                        LOGGER.info(
                            f"Task {self.mid}: Setting TelegramStatus for upload in task_dict."
                        )
                        task_dict[self.mid] = TelegramStatus(self, tg, gid, "up")
                    upload_tasks = [
                        update_status_message(self.message.chat.id),
                        tg.upload(),
                    ]
                    await gather(*upload_tasks)
                    del tg
                    LOGGER.info(f"Task {self.mid}: TelegramUploader finished.")

                elif self.up_dest and is_gofile_upload(self.up_dest):
                    LOGGER.info(
                        f"Task {self.mid}: Initiating GoFileUpload with path {up_path}."
                    )
                    gofile = GoFileUpload(self, up_path)
                    async with task_dict_lock:
                        task_dict[self.mid] = GoFileStatus(self, gofile, gid, "up")
                    upload_tasks = [
                        update_status_message(self.message.chat.id),
                        gofile.upload(),
                    ]
                    await gather(*upload_tasks)
                    del gofile

                elif self.up_dest and is_gdrive_id(self.up_dest):
                    drive = GoogleDriveUpload(self, up_path)
                    async with task_dict_lock:
                        task_dict[self.mid] = GoogleDriveStatus(self, drive, gid, "up")
                    upload_tasks = [
                        update_status_message(self.message.chat.id),
                        sync_to_async(drive.upload),
                    ]
                    await gather(*upload_tasks)
                    del drive

                elif self.up_dest and is_rclone_path(self.up_dest):
                    RCTransfer = RcloneTransferHelper(self)
                    async with task_dict_lock:
                        task_dict[self.mid] = RcloneStatus(self, RCTransfer, gid, "up")
                    upload_tasks = [
                        update_status_message(self.message.chat.id),
                        RCTransfer.upload(up_path),
                    ]
                    await gather(*upload_tasks)
                    del RCTransfer

                elif not self.up_dest:
                    # Handle default upload destinations
                    if self.user_preferred_upload_service == "gd":
                        drive = GoogleDriveUpload(self, up_path)
                        async with task_dict_lock:
                            task_dict[self.mid] = GoogleDriveStatus(
                                self, drive, gid, "up"
                            )
                        upload_tasks = [
                            update_status_message(self.message.chat.id),
                            sync_to_async(drive.upload),
                        ]
                        await gather(*upload_tasks)
                        del drive

                    elif self.user_preferred_upload_service == "rc":
                        RCTransfer = RcloneTransferHelper(self)
                        async with task_dict_lock:
                            task_dict[self.mid] = RcloneStatus(
                                self, RCTransfer, gid, "up"
                            )
                        upload_tasks = [
                            update_status_message(self.message.chat.id),
                            RCTransfer.upload(up_path),
                        ]
                        await gather(*upload_tasks)
                        del RCTransfer

                    elif self.user_preferred_upload_service == "yt":
                        if ospath.isfile(up_path) and (
                            guess_type(up_path)[0] or ""
                        ).startswith("video/"):
                            yt_uploader = YouTubeUpload(self, up_path)
                            async with task_dict_lock:
                                task_dict[self.mid] = YtStatus(
                                    self, yt_uploader, gid, "up"
                                )
                            upload_tasks = [
                                update_status_message(self.message.chat.id),
                                sync_to_async(yt_uploader.upload),
                            ]
                            await gather(*upload_tasks)
                            del yt_uploader
                        else:
                            LOGGER.warning(
                                f"User Default YouTube Upload for non-video file {self.name}. Falling back to global default ({Config.DEFAULT_UPLOAD})."
                            )
                            # Fallback logic for non-video files
                            if Config.DEFAULT_UPLOAD == "gd":
                                drive = GoogleDriveUpload(self, up_path)
                                async with task_dict_lock:
                                    task_dict[self.mid] = GoogleDriveStatus(
                                        self, drive, gid, "up"
                                    )
                                upload_tasks = [
                                    update_status_message(self.message.chat.id),
                                    sync_to_async(drive.upload),
                                ]
                                await gather(*upload_tasks)
                                del drive
                            elif Config.DEFAULT_UPLOAD == "gofile":
                                gofile = GoFileUpload(self, up_path)
                                async with task_dict_lock:
                                    task_dict[self.mid] = GoFileStatus(
                                        self, gofile, gid, "up"
                                    )
                                upload_tasks = [
                                    update_status_message(self.message.chat.id),
                                    gofile.upload(),
                                ]
                                await gather(*upload_tasks)
                                del gofile
                            else:
                                RCTransfer = RcloneTransferHelper(self)
                                async with task_dict_lock:
                                    task_dict[self.mid] = RcloneStatus(
                                        self, RCTransfer, gid, "up"
                                    )
                                upload_tasks = [
                                    update_status_message(self.message.chat.id),
                                    RCTransfer.upload(up_path),
                                ]
                                await gather(*upload_tasks)
                                del RCTransfer

                    elif self.user_preferred_upload_service == "gofile":
                        gofile = GoFileUpload(self, up_path)
                        async with task_dict_lock:
                            task_dict[self.mid] = GoFileStatus(self, gofile, gid, "up")
                        upload_tasks = [
                            update_status_message(self.message.chat.id),
                            gofile.upload(),
                        ]
                        await gather(*upload_tasks)
                        del gofile

                    else:
                        LOGGER.error(
                            f"Unknown user_preferred_upload_service: {self.user_preferred_upload_service}. Defaulting to Rclone."
                        )
                        RCTransfer = RcloneTransferHelper(self)
                        async with task_dict_lock:
                            task_dict[self.mid] = RcloneStatus(
                                self, RCTransfer, gid, "up"
                            )
                        upload_tasks = [
                            update_status_message(self.message.chat.id),
                            RCTransfer.upload(up_path),
                        ]
                        await gather(*upload_tasks)
                        del RCTransfer

                elif self.up_dest:
                    RCTransfer = RcloneTransferHelper(self)
                    async with task_dict_lock:
                        task_dict[self.mid] = RcloneStatus(self, RCTransfer, gid, "up")
                    upload_tasks = [
                        update_status_message(self.message.chat.id),
                        RCTransfer.upload(up_path),
                    ]
                    await gather(*upload_tasks)
                    del RCTransfer

            except Exception as e:
                LOGGER.error(f"Error during upload execution: {e}")
                await self.on_upload_error(str(e))
                return

        except Exception as e:
            LOGGER.error(f"Critical error in on_download_complete: {e}")
            await self.on_upload_error(f"Critical processing error: {str(e)}")

        finally:
            # Ensure cleanup
            try:
                self.clear()
            except:
                pass

    async def on_upload_complete(
        self, link, files, folders, mime_type, rclone_path="", dir_id="", index_url=None
    ):
        if self.message is None or self.message.chat is None:
            LOGGER.error("TaskListener: message or chat is None in on_upload_complete.")
            async with task_dict_lock:
                if self.mid in task_dict:
                    del task_dict[self.mid]
            return

        self.user_dict = user_data.get(self.user_id, {})
        # Filter out binary content from logging
        filtered_user_dict = {
            k: v
            for k, v in self.user_dict.items()
            if not k.endswith("_CONTENT") or not isinstance(v, bytes)
        }
        LOGGER.info(
            f"Task {self.mid}: User {self.user_id} settings for upload complete: {filtered_user_dict}"
        )
        if Config.INCOMPLETE_TASK_NOTIFIER and Config.DATABASE_URL:
            if self.is_super_chat:
                await database.rm_complete_task(self.message.link)
            with suppress(Exception):
                if (
                    database.db
                    and database.db.resume_tasks
                    and database.db.resume_tasks.get(TgClient.ID)
                ):
                    await database.db.resume_tasks[TgClient.ID].delete_one(
                        {"_id": self.message.link}
                    )

        # Get user thumbnail for completion message (simplified approach from refer)
        photo = None

        # Check custom thumbnail first (from -t parameter)
        if self.thumb and await aiopath.exists(self.thumb):
            photo = self.thumb
        else:
            # Check user default thumbnail from user settings
            user_thumb = self.user_dict.get("THUMBNAIL")
            if user_thumb and await aiopath.exists(user_thumb):
                photo = user_thumb
            else:
                # Fallback to default user thumbnail path
                user_thumb_path = f"thumbnails/{self.user_id}.jpg"
                if await aiopath.exists(user_thumb_path):
                    photo = user_thumb_path

        dt_date, dt_time = get_date_time(self.message.date.timestamp())
        tz_title = getattr(Config, "TIME_ZONE_TITLE", "Local")
        task_action = action(self.message)
        base_msg = f'<a href="https://t.me/MirrorHunterUpdates"><b><i>Bot OF Mirror Hunter</b></i></a>\n\n'
        base_msg += f"<code>{escape(self.name)}</code>\n"
        base_msg += f"<b>╭ Size: </b>{get_readable_file_size(self.size)}\n"
        base_msg += f"<b>├ Elapsed: </b>{get_readable_time(time() - self.message.date.timestamp())}\n"
        base_msg += f"<b>├ Add: </b>{dt_date}\n"

        if self.is_yt:
            buttons = ButtonMaker()
            msg = base_msg
            if mime_type == "Folder/Playlist":
                msg += "<b>├ Type: </b>Playlist\n"
                msg += f"<b>├ Total Videos: </b>{files}\n"
                if link:
                    buttons.url_button("🔗 View Playlist", link)
                user_message = f"{self.tag}\nYour playlist ({files} videos) has been uploaded to YouTube successfully!"
            else:
                msg += "<b>├ Type: </b>Video\n"
                if link:
                    buttons.url_button("🔗 View Video", link)
                user_message = (
                    f"{self.tag}\nYour video has been uploaded to YouTube successfully!"
                )

            msg += f"<b>├ Cc: </b>{self.tag}\n"
            msg += f"<b>├ Mode: </b>{task_action}\n"
            msg += f"<b>╰ At: </b>{dt_time} ({tz_title})\n\n"
            buttons.url_button("View File(s)", f"https://t.me/{TgClient.BNAME}")
            button = buttons.build_menu(1 if not link else 2)

            await send_message(self.user_id, msg, button, photo=photo)
            # Send to user-configured leech dump chat
            leech_dump_chat = (
                self.user_dict.get("LEECH_DUMP_CHAT") or Config.LEECH_DUMP_CHAT
            )
            if leech_dump_chat:
                try:
                    # Enhanced leech log handling with chat_id|topic_id support
                    log_chat_id = leech_dump_chat
                    topic_id = None

                    if isinstance(leech_dump_chat, str) and "|" in leech_dump_chat:
                        parts = leech_dump_chat.split("|", 1)
                        try:
                            log_chat_id = int(parts[0])
                            topic_id = int(parts[1]) if parts[1] else None
                        except ValueError:
                            LOGGER.error(
                                f"Invalid chat ID format in leech dump chat: {leech_dump_chat}"
                            )
                            log_chat_id = None  # Mark as invalid

                    # Ensure log_chat_id is an integer
                    if log_chat_id is not None and not isinstance(log_chat_id, int):
                        try:
                            log_chat_id = int(log_chat_id)
                        except ValueError:
                            LOGGER.error(
                                f"Invalid chat ID in leech dump chat: {log_chat_id}"
                            )
                            log_chat_id = None  # Mark as invalid

                    if log_chat_id is not None:
                        if topic_id:
                            await send_message(
                                log_chat_id,
                                msg,
                                button,
                                message_thread_id=topic_id,
                                photo=photo,
                            )
                        else:
                            await send_message(log_chat_id, msg, button, photo=photo)
                except Exception as e:
                    LOGGER.error(
                        f"Failed to send leech completion to dump chat {leech_dump_chat}: {e}"
                    )

            # Send to owner leech dump chat (global config) if different from user setting
            if Config.LEECH_DUMP_CHAT and Config.LEECH_DUMP_CHAT != leech_dump_chat:
                try:
                    owner_log_chat_id = Config.LEECH_DUMP_CHAT
                    owner_topic_id = None

                    if (
                        isinstance(Config.LEECH_DUMP_CHAT, str)
                        and "|" in Config.LEECH_DUMP_CHAT
                    ):
                        parts = Config.LEECH_DUMP_CHAT.split("|", 1)
                        try:
                            owner_log_chat_id = int(parts[0])
                            owner_topic_id = int(parts[1]) if parts[1] else None
                        except ValueError:
                            LOGGER.error(
                                f"Invalid owner chat ID format in LEECH_DUMP_CHAT: {Config.LEECH_DUMP_CHAT}"
                            )
                            owner_log_chat_id = None  # Mark as invalid

                    # Ensure owner_log_chat_id is an integer
                    if owner_log_chat_id is not None and not isinstance(
                        owner_log_chat_id, int
                    ):
                        try:
                            owner_log_chat_id = int(owner_log_chat_id)
                        except ValueError:
                            LOGGER.error(
                                f"Invalid owner chat ID in LEECH_DUMP_CHAT: {owner_log_chat_id}"
                            )
                            owner_log_chat_id = None  # Mark as invalid

                    if owner_log_chat_id is not None:
                        if owner_topic_id:
                            await send_message(
                                owner_log_chat_id,
                                msg,
                                button,
                                message_thread_id=owner_topic_id,
                                photo=photo,
                            )
                        else:
                            await send_message(
                                owner_log_chat_id, msg, button, photo=photo
                            )
                except Exception as e:
                    error_msg = str(e).lower()
                    if (
                        "chat not found" in error_msg
                        or "channel is private" in error_msg
                    ):
                        LOGGER.error(
                            f"Owner leech dump chat {Config.LEECH_DUMP_CHAT} is inaccessible. Bot may have been removed from the chat or the chat ID is invalid: {e}"
                        )
                    elif "forbidden" in error_msg or "not enough rights" in error_msg:
                        LOGGER.error(
                            f"Bot lacks permissions to send messages to owner leech dump chat {Config.LEECH_DUMP_CHAT}: {e}"
                        )
                    else:
                        LOGGER.error(
                            f"Failed to send leech completion to owner dump chat {Config.LEECH_DUMP_CHAT}: {e}"
                        )

            await send_message(self.message, user_message, button, photo=photo)

        elif self.is_leech:
            show_completion = self.user_dict.get("leech_completion_message", True)
            if not show_completion:
                # If completion messages are disabled, do nothing more for leech
                pass
            else:
                msg = base_msg
                msg += f"<b>├ Total Files: </b>{folders}\n"
                if mime_type != 0:
                    msg += f"<b>├ Corrupted Files: </b>{mime_type}\n"
                msg += f"<b>├ Cc: </b>{self.tag}\n"
                msg += f"<b>├ Mode: </b>{task_action}\n"
                msg += f"<b>╰ At: </b>{dt_time} ({tz_title})\n\n"
                # Build a PM-friendly header (without action notes) to prepend before files list in PM
                pm_header = msg
                msg += "〶 <b><u>Action Performed :</u></b>\n"
                msg += "⋗ <i>Leech complete. Files have been sent to your PM.</i>\n"
                msg += "⋗ <i>Main file links are listed below (these may also be in your PM or another specified/default chat).</i>\n\n"

                button_builder = ButtonMaker()
                if Config.BOT_PM and self.is_super_chat:
                    if TgClient.BNAME and isinstance(TgClient.BNAME, str):
                        button_builder.url_button(
                            "View File(s) in PM",
                            f"https://t.me/{TgClient.BNAME.strip()}",
                        )
                        # Build deep link to get all files for this task (no callbacks)
                        try:
                            # Collect message ids and chat ids from files dict
                            entries = []
                            for file_link in (files or {}).keys():
                                parts = file_link.split("/")
                                if len(parts) >= 2:
                                    msg_id_part = parts[-1]
                                    chat_id_part = parts[-2]
                                    # Determine chat id
                                    if "//t.me/" in file_link and "/c/" in file_link:
                                        # Supergroup/channel private link format: https://t.me/c/<id>/<msg_id>
                                        cid = (
                                            parts[parts.index("c") + 1]
                                            if "c" in parts
                                            else chat_id_part
                                        )
                                        chat_id = f"-100{cid}"
                                    elif (
                                        "//t.me/" in file_link
                                        and "/c/" not in file_link
                                        and len(parts) >= 5
                                    ):
                                        # Public username link format: https://t.me/<username>/<msg_id>
                                        chat_id = parts[3]
                                    else:
                                        chat_id = chat_id_part
                                    try:
                                        msg_id_int = int(msg_id_part)
                                    except Exception:
                                        continue
                                    entries.append((chat_id, msg_id_int))
                            if entries:
                                # Store a one-time token in cached_dict
                                from secrets import token_urlsafe

                                token = token_urlsafe(12)
                                cached_dict[token] = {
                                    "user_id": self.user_id,
                                    "entries": entries,
                                    "ts": time(),
                                }
                                start_token = encode_slink(f"files{token}")
                                deep_link = f"https://t.me/{TgClient.BNAME.strip()}?start={start_token}"
                                button_builder.url_button("Get All Files", deep_link)
                        except Exception:
                            pass

                final_markup = (
                    button_builder.build_menu(3) if button_builder.buttons else None
                )

                sent_summary_to_group = False
                # Get default leech image for group notifications
                group_leech_image = get_random_image(Config.IMAGE_LEECH)

                if self.is_super_chat:
                    try:
                        await send_message(
                            self.message,
                            msg,
                            final_markup,
                            photo=group_leech_image,
                            context="leech_summary_group_notification",
                        )
                        sent_summary_to_group = True
                    except Exception as e:
                        LOGGER.error(f"Failed to send leech summary to group: {e}")

                # Also send the same completion summary to user's PM if enabled
                if self.bot_pm and self.is_super_chat:
                    # Get user thumbnail for PM, fallback to default leech image
                    pm_leech_image = group_leech_image  # Default fallback

                    # Check user default thumbnail from user settings
                    user_thumb = self.user_dict.get("THUMBNAIL")
                    if user_thumb and await aiopath.exists(user_thumb):
                        pm_leech_image = user_thumb
                    else:
                        # Fallback to default user thumbnail path
                        user_thumb_path = f"thumbnails/{self.user_id}.jpg"
                        if await aiopath.exists(user_thumb_path):
                            pm_leech_image = user_thumb_path

                    # try:
                    #     await send_message(
                    #         self.user_id,
                    #         msg,
                    #         final_markup,
                    #         photo=pm_leech_image,
                    #         context="leech_summary_pm_notification",
                    #     )
                    # except Exception as e:
                    #     LOGGER.error(f"Failed to send leech summary to PM: {e}")

                if files:
                    log_chat_for_files_list = (
                        self.user_id
                        if (self.bot_pm and self.is_super_chat)
                        else self.message.chat.id
                    )
                    # If sending to user PM, include the base summary header; otherwise, a compact header
                    fmsg_header = (
                        pm_header + "〶 <b><u>Leech File(s):</u></b>\n\n"
                        if log_chat_for_files_list == self.user_id
                        else "〶 <b><u>Leech File(s):</u></b>\n"
                    )
                    fmsg_content = ""
                    for index, (file_link, file_name) in enumerate(
                        files.items(), start=1
                    ):
                        chat_id_part, msg_id_part, is_pm_link = "", "", False
                        if "/" in file_link:
                            parts = file_link.split("/")
                            if len(parts) >= 2:
                                msg_id_part = parts[-1]
                                chat_id_part = parts[-2]
                                if len(parts) > 3 and parts[-3] == "pm":
                                    is_pm_link = True

                        current_file_line = (
                            f"{index}. <a href='{file_link}'>{escape(file_name)}</a>\n"
                        )

                        # Build Media Store and Share links for quick access
                        store_link_line = ""
                        try:
                            store_chat_id = ""
                            store_msg_id = msg_id_part
                            if "//t.me/" in file_link and "/c/" in file_link:
                                # Supergroup/channel private link format: https://t.me/c/<id>/<msg_id>
                                # Telegram chat id is -100<id>
                                cid = (
                                    parts[parts.index("c") + 1]
                                    if "c" in parts
                                    else chat_id_part
                                )
                                store_chat_id = f"-100{cid}"
                            elif (
                                "//t.me/" in file_link
                                and "/c/" not in file_link
                                and len(parts) >= 5
                            ):
                                # Public username link format: https://t.me/<username>/<msg_id>
                                store_chat_id = parts[3]
                            # Encode start payload: file<chat_id>&&<msg_id>
                            if store_chat_id and store_msg_id:
                                payload = f"file{store_chat_id}&&{store_msg_id}"
                                start_token = encode_slink(payload)
                                store_url = (
                                    f"https://t.me/{TgClient.BNAME}?start={start_token}"
                                )
                                share_url = f"https://t.me/share/url?url={store_url}"
                                store_link_line = (
                                    f"╰ Get Media → <a href='{store_url}'>Store Link</a> | "
                                    f"<a href='{share_url}'>Share Link</a>\n"
                                )
                        except Exception:
                            # Best-effort: skip store/share line if parsing fails
                            store_link_line = ""
                        combined_line = current_file_line + (store_link_line or "")

                        if (
                            len((fmsg_header + fmsg_content + combined_line).encode())
                            > 4000
                        ):
                            # Message splitting logic (omitted for brevity, assuming it's correct)
                            await send_message(
                                log_chat_for_files_list,
                                fmsg_header + fmsg_content,
                                photo=photo,
                            )
                            fmsg_content = combined_line
                        else:
                            fmsg_content += combined_line

                    if fmsg_content:
                        await send_message(
                            log_chat_for_files_list,
                            fmsg_header + fmsg_content,
                            photo=photo,
                        )

                elif not sent_summary_to_group:
                    await send_message(
                        self.message.chat.id, msg, final_markup, photo=photo
                    )

                # Send success sticker for leech completion
                try:
                    await send_success_sticker(self.message)
                except Exception as e:
                    LOGGER.error(f"Failed to send success sticker for leech: {e}")

                # Send to user-configured leech dump chat
                leech_dump_chat = (
                    self.user_dict.get("LEECH_DUMP_CHAT") or Config.LEECH_DUMP_CHAT
                )
                if leech_dump_chat:
                    try:
                        # Enhanced leech log handling with chat_id|topic_id support
                        log_chat_id = leech_dump_chat
                        topic_id = None

                        if isinstance(leech_dump_chat, str) and "|" in leech_dump_chat:
                            parts = leech_dump_chat.split("|", 1)
                            try:
                                log_chat_id = int(parts[0])
                                topic_id = int(parts[1]) if parts[1] else None
                            except ValueError:
                                LOGGER.error(
                                    f"Invalid chat ID format in leech dump chat: {leech_dump_chat}"
                                )
                                log_chat_id = None  # Mark as invalid

                        # Ensure log_chat_id is an integer
                        if log_chat_id is not None and not isinstance(log_chat_id, int):
                            try:
                                log_chat_id = int(log_chat_id)
                            except ValueError:
                                LOGGER.error(
                                    f"Invalid chat ID in leech dump chat: {log_chat_id}"
                                )
                                log_chat_id = None  # Mark as invalid

                        if log_chat_id is not None:
                            if topic_id:
                                await send_message(
                                    log_chat_id,
                                    msg,
                                    final_markup,
                                    message_thread_id=topic_id,
                                    photo=photo,
                                )
                            else:
                                await send_message(
                                    log_chat_id, msg, final_markup, photo=photo
                                )
                    except Exception as e:
                        error_msg = str(e).lower()
                        if (
                            "chat not found" in error_msg
                            or "channel is private" in error_msg
                        ):
                            LOGGER.error(
                                f"Leech dump chat {leech_dump_chat} is inaccessible. Bot may have been removed from the chat or the chat ID is invalid: {e}"
                            )
                        elif (
                            "forbidden" in error_msg or "not enough rights" in error_msg
                        ):
                            LOGGER.error(
                                f"Bot lacks permissions to send messages to leech dump chat {leech_dump_chat}: {e}"
                            )
                        else:
                            LOGGER.error(
                                f"Failed to send leech completion to dump chat {leech_dump_chat}: {e}"
                            )

                # Send to owner leech dump chat (global config) if different from user setting
                if Config.LEECH_DUMP_CHAT and Config.LEECH_DUMP_CHAT != leech_dump_chat:
                    try:
                        owner_log_chat_id = Config.LEECH_DUMP_CHAT
                        owner_topic_id = None

                        if (
                            isinstance(Config.LEECH_DUMP_CHAT, str)
                            and "|" in Config.LEECH_DUMP_CHAT
                        ):
                            parts = Config.LEECH_DUMP_CHAT.split("|", 1)
                            try:
                                owner_log_chat_id = int(parts[0])
                                owner_topic_id = int(parts[1]) if parts[1] else None
                            except ValueError:
                                LOGGER.error(
                                    f"Invalid owner chat ID format in LEECH_DUMP_CHAT: {Config.LEECH_DUMP_CHAT}"
                                )
                                owner_log_chat_id = None  # Mark as invalid

                        # Ensure owner_log_chat_id is an integer
                        if owner_log_chat_id is not None and not isinstance(
                            owner_log_chat_id, int
                        ):
                            try:
                                owner_log_chat_id = int(owner_log_chat_id)
                            except ValueError:
                                LOGGER.error(
                                    f"Invalid owner chat ID in LEECH_DUMP_CHAT: {owner_log_chat_id}"
                                )
                                owner_log_chat_id = None  # Mark as invalid

                        if owner_log_chat_id is not None:
                            if owner_topic_id:
                                await send_message(
                                    owner_log_chat_id,
                                    msg,
                                    final_markup,
                                    message_thread_id=owner_topic_id,
                                    photo=photo,
                                )
                            else:
                                await send_message(
                                    owner_log_chat_id, msg, final_markup, photo=photo
                                )
                    except Exception as e:
                        error_msg = str(e).lower()
                        if (
                            "chat not found" in error_msg
                            or "channel is private" in error_msg
                        ):
                            LOGGER.error(
                                f"Owner leech dump chat {Config.LEECH_DUMP_CHAT} is inaccessible. Bot may have been removed from the chat or the chat ID is invalid: {e}"
                            )
                        elif (
                            "forbidden" in error_msg or "not enough rights" in error_msg
                        ):
                            LOGGER.error(
                                f"Bot lacks permissions to send messages to owner leech dump chat {Config.LEECH_DUMP_CHAT}: {e}"
                            )
                        else:
                            LOGGER.error(
                                f"Failed to send leech completion to owner dump chat {Config.LEECH_DUMP_CHAT}: {e}"
                            )

        else:  # This is for Mirror tasks
            msg = base_msg
            msg += f"<b>├ Type: </b>{mime_type}\n"
            if mime_type == "Folder":
                if folders:
                    msg += f"<b>├ SubFolders: </b>{folders}\n"
                msg += f"<b>├ Files: </b>{files if files else 'N/A'}\n"
            msg += f"<b>├ Cc: </b>{self.tag}\n"
            msg += f"<b>├ Mode: </b>{task_action}\n"
            msg += f"<b>╰ At: </b>{dt_time} ({tz_title})"

            buttons = ButtonMaker()
            if link:
                buttons.url_button("Cloud Link", link)

            from ..ext_utils.links_utils import is_share_link

            if (
                hasattr(self, "source_url")
                and self.source_url
                and is_share_link(self.source_url)
            ):
                buttons.url_button("Index Link", self.source_url)
            elif (
                index_url or (self.user_dict or {}).get("INDEX_URL") or Config.INDEX_URL
            ):
                try:
                    base = (
                        index_url
                        or (self.user_dict or {}).get("INDEX_URL")
                        or Config.INDEX_URL
                        or ""
                    ).strip()
                    index_link = None  # Initialize to None
                    if base:
                        is_path_style = (":/" in base) or base.rstrip("/").endswith(":")

                        # ID-based indexers (e.g., GDrive) take precedence if applicable
                        if not is_path_style and dir_id:
                            if not base.endswith("/"):
                                base += "/"
                            index_link = f"{base}findpath?id={dir_id}"
                        else:
                            # For all other cases, construct a path-based link.
                            path_to_append = self.name  # Fallback to the item name

                            # rclone_path is the best source for the full relative path.
                            if rclone_path:
                                # Split remote:path
                                path_parts = rclone_path.split(":", 1)
                                if len(path_parts) > 1 and path_parts[1]:
                                    # We have a remote and a path, use the path part.
                                    path_to_append = path_parts[1].lstrip("/")
                                elif ":" not in rclone_path:
                                    # rclone_path has no ':', so treat it as a pure path.
                                    path_to_append = rclone_path.lstrip("/")

                            if not base.endswith("/"):
                                base += "/"

                            index_link = f"{base}{quote(path_to_append)}"

                    if index_link:
                        buttons.url_button("Index Link", index_link)
                        # Add view link for ID-based indexers if content is media
                        if (
                            isinstance(mime_type, str)
                            and mime_type.startswith(("image", "video", "audio"))
                            and dir_id
                            and not is_path_style
                        ):
                            buttons.url_button(
                                "View Link", f"{base}findpath?id={dir_id}&view=true"
                            )
                except Exception as e:
                    LOGGER.error(f"Error building index link: {e}")
                    # Fallback to showing the base URL if construction fails
                    if index_url or Config.INDEX_URL:
                        buttons.url_button(
                            "Index Link", (index_url or Config.INDEX_URL).strip()
                        )

            # [ENHANCEMENT] Simplified path display logic
            if rclone_path:
                msg += f"\n\n<b>Path:</b> <code>{escape(rclone_path)}</code>"

            msg += "\n\n"

            send_pm = (
                self.user_dict.get("enable_pm") or Config.FORCE_SEND_PM
            ) and self.is_super_chat
            if send_pm:
                msg += "〶 <b><u>Action Performed :</u></b>\n"
                msg += "⋗ <i>Cloud link(s) sent to User PM & Logs Channel.</i>"
            else:
                msg += "〶 <b><u>Action Performed :</u></b>\n"
                msg += "⋗ <i>Cloud link(s) sent to Logs Channel.</i>"

            button = buttons.build_menu(2)
            mirror_image = photo or get_random_image(Config.IMAGE_MIRROR)

            if self.bot_pm:
                await send_message(self.user_id, msg, button, photo=mirror_image)

            if Config.MIRROR_LOG_ID:
                await send_message(
                    Config.MIRROR_LOG_ID, msg, button, photo=mirror_image
                )

            if mirror_log_chat_id := self.user_dict.get("enable_mirror_log"):
                await send_message(mirror_log_chat_id, msg, button, photo=mirror_image)

            # Send to user-configured mirror dump chat
            mirror_dump_chat = (
                self.user_dict.get("MIRROR_DUMP_CHAT") or Config.MIRROR_DUMP_CHAT
            )
            if mirror_dump_chat:
                try:
                    # Enhanced mirror log handling with chat_id|topic_id support
                    log_chat_id = mirror_dump_chat
                    topic_id = None

                    if isinstance(mirror_dump_chat, str) and "|" in mirror_dump_chat:
                        parts = mirror_dump_chat.split("|", 1)
                        try:
                            log_chat_id = int(parts[0])
                            topic_id = int(parts[1]) if parts[1] else None
                        except ValueError:
                            LOGGER.error(
                                f"Invalid chat ID format in mirror dump chat: {mirror_dump_chat}"
                            )
                            log_chat_id = None  # Mark as invalid

                    # Ensure log_chat_id is an integer
                    if log_chat_id is not None and not isinstance(log_chat_id, int):
                        try:
                            log_chat_id = int(log_chat_id)
                        except ValueError:
                            LOGGER.error(
                                f"Invalid chat ID in mirror dump chat: {log_chat_id}"
                            )
                            log_chat_id = None  # Mark as invalid

                    if log_chat_id is not None:
                        if topic_id:
                            await send_message(
                                log_chat_id,
                                msg,
                                button,
                                photo=mirror_image,
                                message_thread_id=topic_id,
                            )
                        else:
                            await send_message(
                                log_chat_id, msg, button, photo=mirror_image
                            )
                except Exception as e:
                    error_msg = str(e).lower()
                    if (
                        "chat not found" in error_msg
                        or "channel is private" in error_msg
                    ):
                        LOGGER.error(
                            f"Mirror dump chat {mirror_dump_chat} is inaccessible. Bot may have been removed from the chat or the chat ID is invalid: {e}"
                        )
                    elif "forbidden" in error_msg or "not enough rights" in error_msg:
                        LOGGER.error(
                            f"Bot lacks permissions to send messages to mirror dump chat {mirror_dump_chat}: {e}"
                        )
                    else:
                        LOGGER.error(
                            f"Failed to send mirror completion to dump chat {mirror_dump_chat}: {e}"
                        )

            # Send to owner mirror dump chat (global config) if different from user setting
            if Config.MIRROR_DUMP_CHAT and Config.MIRROR_DUMP_CHAT != mirror_dump_chat:
                try:
                    owner_log_chat_id = Config.MIRROR_DUMP_CHAT
                    owner_topic_id = None

                    if (
                        isinstance(Config.MIRROR_DUMP_CHAT, str)
                        and "|" in Config.MIRROR_DUMP_CHAT
                    ):
                        parts = Config.MIRROR_DUMP_CHAT.split("|", 1)
                        try:
                            owner_log_chat_id = int(parts[0])
                            owner_topic_id = int(parts[1]) if parts[1] else None
                        except ValueError:
                            LOGGER.error(
                                f"Invalid owner chat ID format in MIRROR_DUMP_CHAT: {Config.MIRROR_DUMP_CHAT}"
                            )
                            owner_log_chat_id = None  # Mark as invalid

                    # Ensure owner_log_chat_id is an integer
                    if owner_log_chat_id is not None and not isinstance(
                        owner_log_chat_id, int
                    ):
                        try:
                            owner_log_chat_id = int(owner_log_chat_id)
                        except ValueError:
                            LOGGER.error(
                                f"Invalid owner chat ID in MIRROR_DUMP_CHAT: {owner_log_chat_id}"
                            )
                            owner_log_chat_id = None  # Mark as invalid

                    if owner_log_chat_id is not None:
                        if owner_topic_id:
                            await send_message(
                                owner_log_chat_id,
                                msg,
                                button,
                                photo=mirror_image,
                                message_thread_id=owner_topic_id,
                            )
                        else:
                            await send_message(
                                owner_log_chat_id, msg, button, photo=mirror_image
                            )
                except Exception as e:
                    error_msg = str(e).lower()
                    if (
                        "chat not found" in error_msg
                        or "channel is private" in error_msg
                    ):
                        LOGGER.error(
                            f"Owner mirror dump chat {Config.MIRROR_DUMP_CHAT} is inaccessible. Bot may have been removed from the chat or the chat ID is invalid: {e}"
                        )
                    elif "forbidden" in error_msg or "not enough rights" in error_msg:
                        LOGGER.error(
                            f"Bot lacks permissions to send messages to owner mirror dump chat {Config.MIRROR_DUMP_CHAT}: {e}"
                        )
                    else:
                        LOGGER.error(
                            f"Failed to send mirror completion to owner dump chat {Config.MIRROR_DUMP_CHAT}: {e}"
                        )

            # Always send to original chat/group
            if self.is_super_chat:
                completion_photo = photo or mirror_image
                await send_message(self.message, msg, button, photo=completion_photo)

            try:
                await send_success_sticker(self.message)
            except Exception as e:
                LOGGER.error(f"Failed to send success sticker for mirror: {e}")

        if self.seed:
            await clean_target(self.up_dir)
            async with queue_dict_lock:
                if self.mid in non_queued_up:
                    non_queued_up.remove(self.mid)
            await start_from_queued()
            return

        if self.pm_msg and (not Config.DELETE_LINKS or Config.CLEAN_LOG_MSG):
            await delete_message(self.pm_msg)

        try:
            if self.message and Config.DELETE_LINKS:
                if getattr(self.message, "reply_to_message", None):
                    await delete_message(self.message.reply_to_message)
                await delete_message(self.message)
        except Exception as e:
            LOGGER.debug(f"Failed to delete user messages after completion: {e}")

        await clean_download(self.dir)
        async with task_dict_lock:
            if self.mid in task_dict:
                del task_dict[self.mid]
            count = len(task_dict)
        if count == 0:
            await self.clean()
        else:
            await update_status_message(self.message.chat.id)

        async with queue_dict_lock:
            if self.mid in non_queued_up:
                non_queued_up.remove(self.mid)

        await start_from_queued()

    async def on_download_error(self, error, button=None, is_limit=False):
        if self.message is None or self.message.chat is None:
            LOGGER.error(
                f"TaskListener: message or chat is None in on_download_error. Error: {error}"
            )
            async with task_dict_lock:
                if self.mid in task_dict:
                    del task_dict[self.mid]
            await clean_download(self.dir)
            if self.up_dir:
                await clean_download(self.up_dir)
            if self.thumb and await aiopath.exists(self.thumb):
                with suppress(Exception):
                    await remove(self.thumb)
            if (
                hasattr(self, "link")
                and self.link
                and Config.INCOMPLETE_TASK_NOTIFIER
                and Config.DATABASE_URL
            ):
                with suppress(Exception):
                    if (
                        database.db
                        and database.db.resume_tasks
                        and database.db.resume_tasks.get(TgClient.ID)
                    ):
                        await database.db.resume_tasks[TgClient.ID].delete_one(
                            {"_id": self.link}
                        )
            return

        async with task_dict_lock:
            if self.mid in task_dict:
                del task_dict[self.mid]
            count = len(task_dict)

        dt_date, dt_time = get_date_time(self.message.date.timestamp())
        tz_title = getattr(Config, "TIME_ZONE_TITLE", "Local")
        task_action = action(self.message)

        err_str = str(error)
        enable_image_mode = getattr(Config, "ENABLE_IMAGE_MODE", False)
        if len(err_str) > (1000 if enable_image_mode else 3800):
            telegraph_title = "Download Error"
            if self.name:
                telegraph_title = f"{self.name} - {telegraph_title}"
            post_url = await TelePost(telegraph_title).create_post(
                err_str.replace("\n", "<br>")
            )
            err_msg_display = (
                f'<a href="{post_url}"><b>Details</b></a>'
                if post_url
                else escape(err_str[:3800])
            )
        else:
            err_msg_display = escape(err_str)

        msg_to_user = (
            f"<b>{'Clone' if self.is_clone else 'Download'} Has Been Stopped!</b>\n"
        )
        if self.name:
            msg_to_user += f"<code>{escape(self.name)}</code>\n"
        msg_to_user += f"<b>╭ Elapsed: </b>{get_readable_time(time() - self.message.date.timestamp())}\n"
        msg_to_user += f"<b>├ Add: </b>{dt_date}\n"
        msg_to_user += f"<b>├ At: </b>{dt_time} ({tz_title})\n"
        msg_to_user += f"<b>├ {task_action} By: </b>{self.tag}\n"
        msg_to_user += f"<b>╰ Due to:</b> {err_msg_display}"

        error_image = (
            getattr(Config, "IMAGE_ERROR", None) if enable_image_mode else None
        )
        await send_message(self.message, msg_to_user, button, photo=error_image)

        try:
            sticker_message = None
            if "already in drive" in err_str.lower():
                from ..telegram_helper.sticker_utils import send_success_sticker

                sticker_message = await send_success_sticker(self.message)
            else:
                from ..telegram_helper.sticker_utils import send_error_sticker

                sticker_message = await send_error_sticker(self.message)
            if sticker_message and Config.DELETE_LINKS:
                from ..telegram_helper.message_utils import auto_delete_message

                await auto_delete_message(bot_message=sticker_message)
        except Exception as sticker_e:
            LOGGER.warning(f"Failed to send download error sticker: {sticker_e}")

        if count == 0:
            await self.clean()
        else:
            await update_status_message(self.message.chat.id)

        if Config.INCOMPLETE_TASK_NOTIFIER and Config.DATABASE_URL:
            if self.is_super_chat:
                await database.rm_complete_task(self.message.link)
            with suppress(Exception):
                if (
                    database.db
                    and database.db.resume_tasks
                    and database.db.resume_tasks.get(TgClient.ID)
                ):
                    await database.db.resume_tasks[TgClient.ID].delete_one(
                        {"_id": self.message.link}
                    )

        if hasattr(self, "log_message") and self.log_message:
            await send_message(self.log_message, msg_to_user, button)

        async with queue_dict_lock:
            if self.mid in queued_dl:
                queued_dl[self.mid].set()
                del queued_dl[self.mid]
            if self.mid in queued_up:
                queued_up[self.mid].set()
                del queued_up[self.mid]
            if self.mid in non_queued_dl:
                non_queued_dl.remove(self.mid)
            if self.mid in non_queued_up:
                non_queued_up.remove(self.mid)

        await start_from_queued()
        await sleep(3)
        await clean_download(self.dir)
        if self.up_dir:
            await clean_download(self.up_dir)
        if self.thumb and await aiopath.exists(self.thumb):
            await remove(self.thumb)

    async def on_upload_error(self, error):
        if self.message is None or self.message.chat is None:
            LOGGER.error(
                f"TaskListener: message or chat is None in on_upload_error. Error: {error}"
            )
            async with task_dict_lock:
                if self.mid in task_dict:
                    del task_dict[self.mid]
            await clean_download(self.dir)
            if self.up_dir:
                await clean_download(self.up_dir)
            if self.thumb and await aiopath.exists(self.thumb):
                with suppress(Exception):
                    await remove(self.thumb)
            if (
                hasattr(self, "link")
                and self.link
                and Config.INCOMPLETE_TASK_NOTIFIER
                and Config.DATABASE_URL
            ):
                with suppress(Exception):
                    if (
                        database.db
                        and database.db.resume_tasks
                        and database.db.resume_tasks.get(TgClient.ID)
                    ):
                        await database.db.resume_tasks[TgClient.ID].delete_one(
                            {"_id": self.link}
                        )
            return

        async with task_dict_lock:
            if self.mid in task_dict:
                del task_dict[self.mid]
            count = len(task_dict)

        dt_date, dt_time = get_date_time(self.message.date.timestamp())
        tz_title = getattr(Config, "TIME_ZONE_TITLE", "Local")
        task_action = action(self.message)
        is_done_message = any(
            x in str(error).lower() for x in ("downloaded!", "seeding")
        )

        err_str = str(error)
        enable_image_mode = getattr(Config, "ENABLE_IMAGE_MODE", False)
        if len(err_str) > (1000 if enable_image_mode else 3800):
            telegraph_title = "Upload Error"
            if self.name:
                telegraph_title = f"{self.name} - {telegraph_title}"
            post_url = await TelePost(telegraph_title).create_post(
                err_str.replace("\n", "<br>")
            )
            err_msg_display = (
                f'<a href="{post_url}"><b>Details</b></a>'
                if post_url
                else escape(err_str[:3800])
            )
        else:
            err_msg_display = escape(err_str)

        msg_to_user = (
            f"<b>{'Clone' if self.is_clone else 'Upload'} Has Been Stopped!</b>\n"
        )
        if self.name:
            msg_to_user += f"<code>{escape(self.name)}</code>\n"
        msg_to_user += f"<b>╭ Elapsed: </b>{get_readable_time(time() - self.message.date.timestamp())}\n"
        msg_to_user += f"<b>├ Cc:</b> {self.tag}\n"
        msg_to_user += f"<b>├ Mode: </b>{task_action}\n"
        msg_to_user += f"<b>├ Add: </b>{dt_date}\n"
        msg_to_user += f"<b>├ At: </b>{dt_time} ({tz_title})\n"
        msg_to_user += f"<b>╰ Due to:</b> {err_msg_display}"

        error_image = (
            getattr(Config, "IMAGE_ERROR", None) if enable_image_mode else None
        )
        await send_message(self.message, msg_to_user, photo=error_image)

        try:
            sticker_message = None
            if is_done_message:
                from ..telegram_helper.sticker_utils import send_success_sticker

                sticker_message = await send_success_sticker(self.message)
            else:
                from ..telegram_helper.sticker_utils import send_error_sticker

                sticker_message = await send_error_sticker(self.message)

            if sticker_message and Config.DELETE_LINKS:
                from ..telegram_helper.message_utils import auto_delete_message

                await auto_delete_message(bot_message=sticker_message)
        except Exception as sticker_e:
            LOGGER.warning(f"Failed to send upload error sticker: {sticker_e}")

        if count == 0:
            await self.clean()
        else:
            await update_status_message(self.message.chat.id)

        if Config.INCOMPLETE_TASK_NOTIFIER and Config.DATABASE_URL:
            if self.is_super_chat:
                await database.rm_complete_task(self.message.link)
            with suppress(Exception):
                if (
                    database.db
                    and database.db.resume_tasks
                    and database.db.resume_tasks.get(TgClient.ID)
                ):
                    await database.db.resume_tasks[TgClient.ID].delete_one(
                        {"_id": self.message.link}
                    )

        if hasattr(self, "log_message") and self.log_message:
            await send_message(self.log_message, msg_to_user)

        async with queue_dict_lock:
            if self.mid in queued_dl:
                queued_dl[self.mid].set()
                del queued_dl[self.mid]
            if self.mid in queued_up:
                queued_up[self.mid].set()
                del queued_up[self.mid]
            if self.mid in non_queued_dl:
                non_queued_dl.remove(self.mid)
            if self.mid in non_queued_up:
                non_queued_up.remove(self.mid)
        await start_from_queued()
        await sleep(3)
        await clean_download(self.dir)
        if self.up_dir:
            await clean_download(self.up_dir)
        if self.thumb and await aiopath.exists(self.thumb):
            await remove(self.thumb)

    async def proceed_compress(self, up_path, gid):
        """
        Compresses files/folders according to the user's ZIP_MODE setting,
        with live progress display.
        """
        from ..ext_utils.files_utils import SevenZ, get_path_size
        from os import path as ospath, walk as oswalk
        from aiofiles.os import path as aiopath

        zip_helper = SevenZ(self)
        user_dict = getattr(self, "user_dict", {})
        zip_mode = user_dict.get("ZIP_MODE", "folders")
        pswd = getattr(self, "password", None)

        # Store original split size to restore it later if modified by a specific mode
        original_split_size = self.split_size

        # Set up SevenZipStatus to show progress for the operation
        async with task_dict_lock:
            task_dict[self.mid] = SevenZipStatus(self, zip_helper, gid, "zip")

        LOGGER.info(f"Compression starting with mode: '{zip_mode}'")

        try:
            # Default mode: zips the whole folder/file. Respects user's -s split flag.
            # 'cloud_part' is functionally the same as 'folders' with a split size.
            if zip_mode in ["folders", "cloud_part"]:
                zip_path = f"{up_path.rstrip('/')}.zip"
                result_path = await zip_helper.zip(up_path, zip_path, pswd)
                if result_path != up_path:
                    self.name = ospath.basename(result_path)
                return result_path

            # The following modes only work on the contents of a directory
            if not await aiopath.isdir(up_path):
                LOGGER.warning(
                    f"Zip mode '{zip_mode}' is for directories. Using default 'folders' behavior."
                )
                zip_path = f"{up_path.rstrip('/')}.zip"
                result_path = await zip_helper.zip(up_path, zip_path, pswd)
                if result_path != up_path:
                    self.name = ospath.basename(result_path)
                return result_path

            # Get all files for directory-based modes
            all_files = [
                ospath.join(root, f)
                for root, _, files in await sync_to_async(oswalk, up_path)
                for f in files
            ]

            if not all_files:
                LOGGER.warning("No files found in the directory to zip.")
                return up_path

            if zip_mode in ["each_files", "part_mode"]:
                should_split = zip_mode == "part_mode"
                LOGGER.info(
                    f"Zip Mode: Zipping each file individually. Splitting enabled: {should_split}"
                )
                # Use original split size for part_mode, disable splitting for each_files
                self.split_size = original_split_size if should_split else 0
                for f_path in all_files:
                    if self.is_cancelled:
                        break
                    zip_path = f"{f_path}.zip"
                    await zip_helper.zip(f_path, zip_path, pswd)
                # After zipping, the directory contains the archives. Return the directory path.
                return up_path

            if zip_mode == "auto_mode":
                LOGGER.info("Zip Mode: Zipping only files larger than split size.")
                # The archives themselves should not be split in this mode
                self.split_size = 0
                leech_split_size = int(
                    user_dict.get("LEECH_SPLIT_SIZE", Config.LEECH_SPLIT_SIZE)
                )
                for f_path in all_files:
                    if self.is_cancelled:
                        break
                    if await get_path_size(f_path) > leech_split_size:
                        zip_path = f"{f_path}.zip"
                        await zip_helper.zip(f_path, zip_path, pswd)
                return up_path

            # Fallback for any unknown mode
            LOGGER.warning(f"Unknown ZIP_MODE: '{zip_mode}'. Using default behavior.")
            zip_path = f"{up_path.rstrip('/')}.zip"
            result_path = await zip_helper.zip(up_path, zip_path, pswd)
            if result_path != up_path:
                self.name = ospath.basename(result_path)
            return result_path

        finally:
            # Restore original split size in case it was modified
            self.split_size = original_split_size
            LOGGER.info("Compression process finished.")
