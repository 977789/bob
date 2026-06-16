from asyncio import (
    gather,
    sleep,
    Event,
    create_task,
    wait_for,
    TimeoutError as AsyncTimeoutError,
)
from html import escape
from time import time
from mimetypes import guess_type
from contextlib import suppress
from os import path as ospath
from re import search as re_search

from aiofiles.os import listdir, remove, path as aiopath
from requests import utils as rutils

from ... import (
    intervals,
    task_dict,
    task_dict_lock,
    LOGGER,
    non_queued_up,
    non_queued_dl,
    non_queued_media_processing,
    queued_up,
    queued_dl,
    queued_media_processing,
    queued_extract,
    queue_dict_lock,
    same_directory_lock,
    DOWNLOAD_DIR,
)
from ..common import TaskConfig, multi_video_tools_selection
from ...core.tg_client import TgClient
from ...core.config_manager import Config
from ...core.torrent_manager import TorrentManager
from ..ext_utils.bot_utils import encode_slink, sync_to_async
from ..ext_utils.db_handler import database
from ..ext_utils.files_utils import (
    clean_download,
    clean_target,
    create_recursive_symlink,
    get_path_size,
    join_files,
    remove_excluded_files,
    move_and_merge,
)
from ..ext_utils.links_utils import is_gdrive_id
from ..ext_utils.status_utils import get_readable_file_size, get_readable_time
from ..ext_utils.file_type_detector import (
    FileTypeDetector,
    is_video_file,
    is_audio_file,
)
from ..ext_utils.task_manager import (
    check_running_tasks,
    start_from_queued,
    check_media_processing_tasks,
    finish_media_processing_task,
)
from ..mirror_leech_utils.gdrive_utils.upload import GoogleDriveUpload
from ..mirror_leech_utils.gofile_utils.upload import GoFileUpload
from ..mirror_leech_utils.rclone_utils.transfer import RcloneTransferHelper
from ..mirror_leech_utils.status_utils.gdrive_status import (
    GoogleDriveStatus,
)
from ..mirror_leech_utils.status_utils.gofile_status import GoFileStatus
from ..mirror_leech_utils.status_utils.queue_status import (
    QueueStatus,
    MediaProcessingQueueStatus,
    ExtractionQueueStatus,
)
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
from ..telegram_helper.sticker_utils import (
    send_error_sticker,
    send_success_sticker,
)

# Define video file extensions - Enhanced with comprehensive list and case-insensitive handling
VIDEO_SUFFIXES = tuple(FileTypeDetector.get_all_video_extensions())


class TaskListener(TaskConfig):
    def __init__(self):
        super().__init__()

    async def clean(self):
        with suppress(Exception):
            if st := intervals["status"]:
                for intvl in list(st.values()):
                    intvl.cancel()
            intervals["status"].clear()
            await gather(TorrentManager.aria2.purgeDownloadResult(), delete_status())

    def clear(self):
        self.subname = ""
        self.subsize = 0
        self.files_to_proceed = []
        self.proceed_count = 0
        self.progress = True

    def is_video_tool_selected(self, tool_key):
        """
        Check if a specific video tool is selected by the user.
        Returns True if the tool is selected or if force_video_tools is True (legacy mode).
        """
        # If using new interactive selection system
        if (
            hasattr(self, "selected_video_tools")
            and self.selected_video_tools is not None
        ):
            return tool_key in self.selected_video_tools

        # Legacy mode: check if force_video_tools is enabled
        return getattr(self, "force_video_tools", False)

    async def is_video_file_enhanced(
        self, filepath: str, use_deep_check: bool = False
    ) -> bool:
        """
        Enhanced video file detection that handles:
        - Case-insensitive extensions (.mkv, .MKV, .Mkv, .mKv, etc.)
        - Files without extensions
        - More comprehensive video format support
        - Optional deep analysis using ffprobe for files without extensions

        Args:
            filepath: Path to the file to check
            use_deep_check: Use ffprobe for files without extensions or unknown types (slower but accurate)

        Returns:
            True if file is detected as video, False otherwise
        """
        try:
            # Quick extension-based check first (handles case sensitivity)
            if FileTypeDetector.is_video_by_extension(filepath):
                return True

            # If no extension or unknown extension, check MIME type
            if FileTypeDetector.is_video_by_mime(filepath):
                return True

            # For files without extensions or if deep check is requested
            if use_deep_check:
                return await is_video_file(filepath, deep_check=True)

            return False

        except Exception as e:
            LOGGER.debug(f"Enhanced video detection failed for {filepath}: {e}")
            # Fallback to original method
            return filepath.lower().endswith(tuple(VIDEO_SUFFIXES))

    async def get_media_info_enhanced(self, filepath: str) -> dict:
        """
        Get detailed media information including file type detection

        Returns:
            dict with keys: is_video, is_audio, detection_info, streams_info
        """
        try:
            (
                is_video,
                is_audio,
                detection_info,
            ) = await FileTypeDetector.detect_file_type(filepath, use_ffprobe=True)

            return {
                "is_video": is_video,
                "is_audio": is_audio,
                "detection_method": detection_info.get("detection_method", "unknown"),
                "has_extension": bool(FileTypeDetector.normalize_extension(filepath)),
                "extension": FileTypeDetector.normalize_extension(filepath),
                "streams_info": detection_info.get("video_streams", [])
                + detection_info.get("audio_streams", []),
            }
        except Exception as e:
            LOGGER.debug(f"Enhanced media info failed for {filepath}: {e}")
            return {
                "is_video": filepath.lower().endswith(tuple(VIDEO_SUFFIXES)),
                "is_audio": False,
                "detection_method": "fallback",
                "has_extension": bool(ospath.splitext(filepath)[1]),
                "extension": ospath.splitext(filepath)[1].lower(),
                "streams_info": [],
            }

    def apply_filename_modifications(self, filename):
        """
        Apply universal filename modifications (prefix, suffix, auto rename) for both mirror and leech operations.
        This ensures consistent filename processing across all upload types.
        """
        if not filename:
            return filename

        original_filename = filename

        # Apply auto rename if enabled
        if self.user_dict.get("AUTO_RENAME", False):
            try:
                from pathlib import Path

                name, ext = ospath.splitext(filename)

                # Get episode pattern and replacement from user settings
                episode_patterns = self.user_dict.get(
                    "AUTO_RENAME_EPISODE_PATTERNS",
                    "S\\d+E\\d+|Season \\d+ Episode \\d+|S\\d+ E\\d+|\\d+x\\d+",
                )
                replacement = self.user_dict.get(
                    "AUTO_RENAME_REPLACEMENT", "S{season:02d}E{episode:02d}"
                )

                import re

                # Apply episode pattern replacement (simplified version)
                for pattern in episode_patterns.split("|"):
                    if re.search(pattern.strip(), name, re.IGNORECASE):
                        # Extract season/episode numbers
                        match = re.search(r"[Ss](\d+)[Ee](\d+)", name)
                        if match:
                            season, episode = match.groups()
                            try:
                                # Apply replacement
                                new_episode = replacement.format(
                                    season=int(season), episode=int(episode)
                                )
                                name = re.sub(
                                    pattern.strip(),
                                    new_episode,
                                    name,
                                    flags=re.IGNORECASE,
                                )
                                filename = f"{name}{ext}"
                                LOGGER.info(
                                    f"Auto rename applied: '{original_filename}' -> '{filename}'"
                                )
                                break
                            except:
                                pass  # If formatting fails, keep original
                        break
            except Exception as e:
                LOGGER.warning(f"Auto rename failed: {e}")
                filename = original_filename

        # Get prefix and suffix from user settings with backward compatibility
        prefix = (
            self.user_dict.get("FILENAME_PREFIX")
            or self.user_dict.get("LEECH_PREFIX")
            or getattr(Config, "FILENAME_PREFIX", "")
            or getattr(Config, "LEECH_PREFIX", "")
        )

        suffix = (
            self.user_dict.get("FILENAME_SUFFIX")
            or self.user_dict.get("LEECH_SUFFIX")
            or getattr(Config, "FILENAME_SUFFIX", "")
            or getattr(Config, "LEECH_SUFFIX", "")
        )

        LOGGER.info(f"Filename modifications - Prefix: '{prefix}', Suffix: '{suffix}'")

        # Apply prefix
        if prefix:
            prefix_clean = prefix.replace(r"\s", " ")
            if not filename.startswith(prefix_clean):
                filename = f"{prefix_clean}{filename}"

        # Apply suffix
        if suffix:
            name, ext = ospath.splitext(filename)
            suffix_clean = suffix.replace(r"\s", " ")
            if not name.endswith(suffix_clean):
                filename = f"{name}{suffix_clean}{ext}"

        return filename

    async def embed_cover_art_universal(self, up_path):
        """
        Embed cover art into media files for both mirror and leech operations.
        This applies to video and audio files when EMBED_USER_IMAGE_AS_COVER is enabled.
        """
        from ..ext_utils.metadata_helper import embed_cover_art
        from ..ext_utils.media_utils import get_document_type

        if not self.user_dict.get("EMBED_USER_IMAGE_AS_COVER", False):
            return up_path

        LOGGER.info("Cover art embedding enabled - processing files")

        # Check if it's a single file or directory
        if await aiopath.isfile(up_path):
            return await self._embed_cover_single_file(up_path)
        elif await aiopath.isdir(up_path):
            return await self._embed_cover_directory(up_path)

        return up_path

    async def _embed_cover_single_file(self, file_path):
        """Embed cover art into a single file"""
        from ..ext_utils.metadata_helper import embed_cover_art
        from ..ext_utils.media_utils import get_document_type

        try:
            # Check if it's a video or audio file
            is_video, is_audio, _ = await get_document_type(file_path)
            if not (is_video or is_audio):
                LOGGER.info(
                    f"Skipping cover art for non-media file: {ospath.basename(file_path)}"
                )
                return file_path

            # Get cover image
            cover_img = await self._get_cover_image()
            if not cover_img:
                LOGGER.info("No cover image available for embedding")
                return file_path

            LOGGER.info(f"Embedding cover art into: {ospath.basename(file_path)}")
            return await embed_cover_art(file_path, cover_img)

        except Exception as e:
            LOGGER.warning(
                f"Failed to embed cover art in {ospath.basename(file_path)}: {e}"
            )
            return file_path

    async def _embed_cover_directory(self, dir_path):
        """Embed cover art into all media files in a directory"""
        from ..ext_utils.metadata_helper import embed_cover_art
        from ..ext_utils.media_utils import get_document_type
        import os

        try:
            cover_img = await self._get_cover_image()
            if not cover_img:
                LOGGER.info("No cover image available for embedding")
                return dir_path

            files_processed = 0
            # Use os.walk instead of aiopath.walk for compatibility
            for root, dirs, files in os.walk(dir_path):
                for file in files:
                    file_path = ospath.join(root, file)
                    try:
                        # Check if it's a video or audio file
                        is_video, is_audio, _ = await get_document_type(file_path)
                        if is_video or is_audio:
                            LOGGER.info(f"Embedding cover art into: {file}")
                            await embed_cover_art(file_path, cover_img)
                            files_processed += 1

                        if self.is_cancelled:
                            break
                    except Exception as e:
                        LOGGER.warning(f"Failed to embed cover art in {file}: {e}")
                        continue

                if self.is_cancelled:
                    break

            LOGGER.info(f"Cover art embedding completed for {files_processed} files")
            return dir_path

        except Exception as e:
            LOGGER.error(f"Cover art embedding failed for directory: {e}")
            return dir_path

    async def _get_cover_image(self):
        """Get the cover image to embed (user thumbnail or custom thumbnail)"""
        try:
            # Priority: custom thumbnail > user default thumbnail
            if hasattr(self, "thumb") and self.thumb and self.thumb != "none":
                if await aiopath.exists(self.thumb):
                    return self.thumb

            # Default user thumbnail path
            default_thumb = f"thumbnails/{self.user_id}.jpg"
            if await aiopath.exists(default_thumb):
                return default_thumb

            return None
        except Exception as e:
            LOGGER.warning(f"Error getting cover image: {e}")
            return None

    async def remove_from_same_dir(self):
        async with task_dict_lock:
            if (
                self.folder_name
                and self.same_dir
                and self.mid in self.same_dir[self.folder_name]["tasks"]
            ):
                self.same_dir[self.folder_name]["tasks"].remove(self.mid)
                self.same_dir[self.folder_name]["total"] -= 1

    async def on_download_start(self):
        mode_name = "Leech" if self.is_leech else "Mirror"
        if self.bot_pm and self.is_super_chat:
            self.pm_msg = await send_message(
                self.user_id,
                f"""» <b><u>Task Started :</u></b>
┊
╰<b>Link:</b> <a href='{self.source_url}'>Click Here</a>
""",
            )
        if Config.LINKS_LOG_ID:
            await send_message(
                Config.LINKS_LOG_ID,
                f"""»  <b><u>{mode_name} Started:</u></b>
 ┊
 ┊<b>User :</b> {self.tag} ( #ID{self.user_id} )
 ┊<b>Message Link :</b> <a href='{self.message.link}'>Click Here</a>
 ╰<b>Link:</b> <a href='{self.source_url}'>Click Here</a>
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

    async def execute_media_processing_with_queue(self, up_path, gid):
        """
        Execute heavy media processing tasks with queue management.
        Only queues: FFmpeg commands, Video Encoding, Video Watermarking
        Excludes: Merge operations and Stream operations (run immediately)
        Returns the processed path or None if cancelled.
        """

        # Check if we actually have any heavy media processing tasks to run
        has_heavy_tasks = await self._has_heavy_media_processing_tasks(up_path)

        if not has_heavy_tasks:
            # No heavy tasks to process, execute directly without queueing
            return await self._execute_media_processing_tasks(up_path, gid)

        if Config.QUEUE_MEDIA_PROCESSING == 0:
            # Queue disabled, execute directly
            return await self._execute_media_processing_tasks(up_path, gid)

        # Check if we need to queue this task
        add_to_queue, event = await check_media_processing_tasks(self)

        if add_to_queue:
            LOGGER.info(f"Added to Media Processing Queue: {self.name}")
            async with task_dict_lock:
                task_dict[self.mid] = MediaProcessingQueueStatus(self, gid)
            await event.wait()
            if self.is_cancelled:
                return None
            LOGGER.info(f"Start from Media Processing Queue: {self.name}")

        try:
            # Execute the actual media processing tasks (FFmpeg, Encoding, Watermarking only)
            result = await self._execute_media_processing_tasks(up_path, gid)
            return result
        finally:
            # Mark task as finished and start next from queue
            await finish_media_processing_task(self.mid)

    async def _has_heavy_media_processing_tasks(self, up_path):
        """Check if this task has any heavy media processing operations to perform"""
        # Check for FFmpeg commands
        if self.ffmpeg_cmds:
            return True

        # Check for video operations if dealing with video files
        is_video_file = await aiopath.isfile(
            up_path
        ) and await self.is_video_file_enhanced(up_path)
        is_directory = await aiopath.isdir(up_path)

        if is_video_file or is_directory:
            # Check for video encoding
            if (
                self.user_dict.get("VIDEO_ENCODE_ENABLED", False)
                and not Config.is_media_processing_disabled()
                and self.is_video_tool_selected("VIDEO_ENCODE")
            ):
                return True

            # Check for video watermarking
            if (
                self.user_dict.get("VIDEO_WATERMARK_ENABLED", False)
                and not Config.is_media_processing_disabled()
                and self.is_video_tool_selected("VIDEO_WATERMARK")
            ):
                return True

            # Check for intro subtitle (treat as queued if combined with others, otherwise still allow queue path)
            if self.user_dict.get(
                "INTRO_SUBTITLE_ENABLED", False
            ) and self.is_video_tool_selected("INTRO_SUBTITLE"):
                return True

        return False

    async def _execute_media_processing_tasks(self, up_path, gid):
        """Execute queued media processing tasks (FFmpeg, Encoding, Watermarking only)"""
        up_dir = self.up_dir

        # FFmpeg commands (QUEUED)
        if self.ffmpeg_cmds:
            up_path = await self.proceed_ffmpeg(up_path, gid)
            if self.is_cancelled:
                return None
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()

        # Check if we're dealing with a video file or a directory that might contain videos
        if not self.is_cancelled and (
            (
                await aiopath.isfile(up_path)
                and await self.is_video_file_enhanced(up_path)
            )
            or await aiopath.isdir(up_path)
        ):
            # Process video encoding if enabled and selected (QUEUED)
            if (
                not self.is_cancelled
                and self.user_dict.get("VIDEO_ENCODE_ENABLED", False)
                and not Config.is_media_processing_disabled()
                and self.is_video_tool_selected("VIDEO_ENCODE")
            ):
                try:
                    up_path = await self.encode_videos(up_path, gid)
                    if self.is_cancelled:
                        return None
                    self.is_file = await aiopath.isfile(up_path)
                    self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
                except Exception as e:
                    LOGGER.error(f"Error during video encoding: {str(e)}")
            elif (
                not self.is_cancelled
                and self.user_dict.get("VIDEO_ENCODE_ENABLED", False)
                and not self.is_video_tool_selected("VIDEO_ENCODE")
            ):
                LOGGER.info(
                    f"Video encoding enabled but not selected, skipping video encoding"
                )

            # Process video format conversion if enabled and selected (QUEUED)
            if (
                not self.is_cancelled
                and self.user_dict.get("VIDEO_CONVERT_ENABLED", False)
                and not Config.is_media_processing_disabled()
                and self.is_video_tool_selected("VIDEO_CONVERT")
            ):
                try:
                    up_path = await self.convert_videos(up_path, gid)
                    if self.is_cancelled:
                        return None
                    self.is_file = await aiopath.isfile(up_path)
                    self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
                except Exception as e:
                    LOGGER.error(f"Error during video format conversion: {str(e)}")
            elif (
                not self.is_cancelled
                and self.user_dict.get("VIDEO_CONVERT_ENABLED", False)
                and not self.is_video_tool_selected("VIDEO_CONVERT")
            ):
                LOGGER.info(
                    f"Video format conversion enabled but not selected, skipping video format conversion"
                )

            # Process video watermarking if enabled and selected (QUEUED)
            if (
                not self.is_cancelled
                and self.user_dict.get("VIDEO_WATERMARK_ENABLED", False)
                and not Config.is_media_processing_disabled()
                and self.is_video_tool_selected("VIDEO_WATERMARK")
            ):
                try:
                    up_path = await self.watermark_videos(up_path, gid)
                    if self.is_cancelled:
                        return None
                    self.is_file = await aiopath.isfile(up_path)
                    self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
                    self.size = await get_path_size(up_dir)
                    self.clear()
                except Exception as e:
                    LOGGER.error(f"Error in video watermarking process: {str(e)}")
            elif (
                not self.is_cancelled
                and self.user_dict.get("VIDEO_WATERMARK_ENABLED", False)
                and not self.is_video_tool_selected("VIDEO_WATERMARK")
            ):
                LOGGER.info(
                    f"Video watermarking enabled but not selected, skipping video watermarking"
                )

            # Intro subtitle soft mux (no re-encode) - treat as heavy only if enabled & selected
            if (
                not self.is_cancelled
                and self.user_dict.get("INTRO_SUBTITLE_ENABLED", False)
                and self.is_video_tool_selected("INTRO_SUBTITLE")
            ):
                try:
                    from ..ext_utils.intro_subtitle_utils import apply_intro_subtitle

                    if await aiopath.isfile(
                        up_path
                    ) and await self.is_video_file_enhanced(up_path):
                        LOGGER.info("Applying intro subtitle to single video file")
                        # Store original filename for later restoration
                        original_path = up_path
                        original_name = ospath.basename(original_path)

                        new_path = await apply_intro_subtitle(up_path, self.user_id)
                        if new_path and new_path != up_path:
                            # Try to rename intro subtitle file back to original filename
                            try:
                                from aiofiles.os import rename as aiorename
                                from pathlib import Path

                                intro_path_obj = Path(new_path)
                                original_path_obj = Path(original_path)

                                # Check if the intro subtitle file has a processing suffix
                                if "_intro" in intro_path_obj.stem:
                                    # Create new path with original filename in same directory
                                    restored_path = (
                                        intro_path_obj.parent
                                        / f"{original_path_obj.stem}{intro_path_obj.suffix}"
                                    )

                                    # Rename intro subtitle file to original filename
                                    await aiorename(new_path, str(restored_path))
                                    LOGGER.info(
                                        f"Intro subtitle file renamed back to original filename: {original_name}"
                                    )
                                    up_path = str(restored_path)
                                else:
                                    # No processing suffix, use as-is
                                    up_path = new_path
                            except Exception as rename_err:
                                LOGGER.warning(
                                    f"Could not rename intro subtitle file back to original name: {rename_err}"
                                )
                                up_path = new_path
                        else:
                            up_path = new_path or up_path
                    elif await aiopath.isdir(up_path):
                        # Apply to each video inside directory
                        from os import walk as oswalk

                        for root, _, files in await sync_to_async(oswalk, up_path):
                            for f in files:
                                fp = ospath.join(root, f)
                                if await self.is_video_file_enhanced(fp):
                                    LOGGER.info(f"Applying intro subtitle to {fp}")
                                    # Store original filename for restoration
                                    original_fp = fp
                                    original_fname = ospath.basename(original_fp)

                                    new_fp = await apply_intro_subtitle(
                                        fp, self.user_id
                                    )
                                    if new_fp and new_fp != fp:
                                        # Try to rename intro subtitle file back to original filename
                                        try:
                                            from aiofiles.os import rename as aiorename
                                            from pathlib import Path

                                            intro_fp_obj = Path(new_fp)
                                            original_fp_obj = Path(original_fp)

                                            # Check if the intro subtitle file has a processing suffix
                                            if "_intro" in intro_fp_obj.stem:
                                                # Create new path with original filename in same directory
                                                restored_fp = (
                                                    intro_fp_obj.parent
                                                    / f"{original_fp_obj.stem}{intro_fp_obj.suffix}"
                                                )

                                                # Rename intro subtitle file to original filename
                                                await aiorename(
                                                    new_fp, str(restored_fp)
                                                )
                                                LOGGER.info(
                                                    f"Intro subtitle file renamed back to original filename: {original_fname}"
                                                )
                                        except Exception as rename_err:
                                            LOGGER.warning(
                                                f"Could not rename intro subtitle file back to original name: {rename_err}"
                                            )
                    self.is_file = await aiopath.isfile(up_path)
                    self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
                    self.size = await get_path_size(up_dir)
                    self.clear()
                except Exception as e:
                    LOGGER.error(f"Error applying intro subtitle: {e}")
            elif (
                not self.is_cancelled
                and self.user_dict.get("INTRO_SUBTITLE_ENABLED", False)
                and not self.is_video_tool_selected("INTRO_SUBTITLE")
            ):
                LOGGER.info("Intro subtitle enabled but not selected, skipping")
        else:
            LOGGER.info(
                f"No video content found in {up_path}, skipping queued video processing features"
            )

        return up_path

    async def on_download_complete(self):
        await sleep(2)
        if self.is_cancelled:
            return
        multi_links = False
        if (
            self.folder_name
            and self.same_dir
            and self.mid in self.same_dir[self.folder_name]["tasks"]
        ):
            async with same_directory_lock:
                while True:
                    async with task_dict_lock:
                        if self.mid not in self.same_dir[self.folder_name]["tasks"]:
                            return
                        if (
                            self.same_dir[self.folder_name]["total"] <= 1
                            or len(self.same_dir[self.folder_name]["tasks"]) > 1
                        ):
                            if self.same_dir[self.folder_name]["total"] > 1:
                                self.same_dir[self.folder_name]["tasks"].remove(
                                    self.mid
                                )
                                self.same_dir[self.folder_name]["total"] -= 1
                                spath = f"{self.dir}{self.folder_name}"
                                des_id = list(self.same_dir[self.folder_name]["tasks"])[
                                    0
                                ]
                                des_path = f"{DOWNLOAD_DIR}{des_id}{self.folder_name}"
                                LOGGER.info(f"Moving files from {self.mid} to {des_id}")
                                await move_and_merge(spath, des_path, self.mid)
                                multi_links = True
                            break
                    await sleep(1)
        async with task_dict_lock:
            if self.is_cancelled:
                return
            if self.mid not in task_dict:
                return
            download = task_dict[self.mid]
            self.name = download.name()
            gid = download.gid()
        LOGGER.info(f"Download completed: {self.name}")

        if not (self.is_torrent or self.is_qbit):
            self.seed = False

        if multi_links:
            self.seed = False
            await self.on_upload_error(
                f"{self.name} Downloaded!\n\nWaiting for other tasks to finish..."
            )
            return
        elif self.same_dir:
            self.seed = False

        if self.folder_name:
            self.name = self.folder_name.strip("/").split("/", 1)[0]

        if not await aiopath.exists(f"{self.dir}/{self.name}"):
            try:
                files = await listdir(self.dir)
                self.name = files[-1]
                if self.name == "yt-dlp-thumb":
                    self.name = files[0]
            except Exception as e:
                await self.on_upload_error(str(e))
                return

        dl_path = f"{self.dir}/{self.name}"
        self.size = await get_path_size(dl_path)
        self.is_file = await aiopath.isfile(dl_path)

        # Apply video trim early if selected (only single file videos for now)
        try:
            if (
                self.is_video_tool_selected("VIDEO_TRIM")
                and getattr(self, "trim_times", None)
                and await aiopath.isfile(dl_path)
                and await self.is_video_file_enhanced(dl_path, use_deep_check=True)
            ):
                from ... import LOGGER as _L

                start_time, end_time = (
                    self.trim_times
                )  # end_time may be 00:00:00 meaning till end

                # Validate HH:MM:SS format and ensure end > start if end provided
                import re

                tpat = r"^\d{2}:\d{2}:\d{2}$"
                if not re.match(tpat, start_time) or not re.match(tpat, end_time):
                    _L.error(
                        f"Invalid trim times provided: {self.trim_times}, skipping trim"
                    )
                else:

                    def to_seconds(ts):
                        h, m, s = map(int, ts.split(":"))
                        return h * 3600 + m * 60 + s

                    s_start = to_seconds(start_time)
                    s_end = to_seconds(end_time)
                    if end_time != "00:00:00" and s_end <= s_start:
                        _L.error(
                            f"End time {end_time} not greater than start {start_time}; skipping trim"
                        )
                    else:
                        from asyncio import create_subprocess_exec
                        from os import path as osp
                        import uuid

                        # Store original filename for later restoration
                        original_path = dl_path
                        original_name = ospath.basename(original_path)
                        original_dir = ospath.dirname(original_path)

                        # Create a temporary filename using UUID to avoid conflicts
                        temp_name = f"temp_trim_{uuid.uuid4().hex}"
                        base, ext = osp.splitext(original_path)
                        temp_trimmed_path = ospath.join(
                            original_dir, f"{temp_name}{ext}"
                        )

                        # Build ffmpeg command preserving all streams, metadata, chapters
                        # Place -ss before -i for faster seek with copy; use -to only if not till end
                        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
                        if start_time != "00:00:00":
                            cmd.extend(["-ss", start_time])
                        cmd.extend(["-i", dl_path])
                        if end_time != "00:00:00":
                            # Use -to relative to start position
                            # If start_time used before -i, -to is relative to input start
                            # So compute duration = end-start for accuracy
                            duration = None
                            try:
                                if end_time != "00:00:00":
                                    duration = s_end - s_start
                            except Exception:
                                duration = None
                            if duration and duration > 0:
                                cmd.extend(["-t", str(duration)])
                        # Map all streams & metadata
                        cmd.extend(
                            [
                                "-map",
                                "0",
                                "-map_metadata",
                                "0",
                                "-map_chapters",
                                "0",
                                "-c",
                                "copy",
                                "-copy_unknown",
                                "-avoid_negative_ts",
                                "make_zero",
                                "-y",
                                temp_trimmed_path,
                            ]
                        )
                        _L.info(f"Trimming video preserving streams: {' '.join(cmd)}")
                        proc = await create_subprocess_exec(*cmd)
                        await proc.wait()
                        if proc.returncode == 0 and await aiopath.exists(
                            temp_trimmed_path
                        ):
                            from aiofiles.os import (
                                remove as aioremove,
                                rename as aiorename,
                            )

                            try:
                                # Remove original file
                                await aioremove(dl_path)
                                # Rename trimmed file back to original filename
                                await aiorename(temp_trimmed_path, original_path)
                                _L.info(
                                    f"Trimmed file renamed back to original filename: {original_name}"
                                )
                            except Exception as ie:
                                _L.warning(
                                    f"Could not rename trimmed file back to original name: {ie}"
                                )
                                # If renaming fails, use the temp file
                                dl_path = temp_trimmed_path
                                self.name = ospath.basename(dl_path)
                            else:
                                # Successfully renamed, keep original path and name
                                dl_path = original_path
                                self.name = original_name

                            self.size = await get_path_size(dl_path)
                            self.is_file = True
                            from ..telegram_helper.message_utils import (
                                send_message as _sm,
                            )

                            await _sm(
                                self.message,
                                f"✅ Video trimmed (streams preserved): {start_time} to {end_time if end_time != '00:00:00' else 'END'}",
                            )
                        else:
                            _L.error("Video trim failed; proceeding with original file")
                            # Clean up temp file if it exists
                            if await aiopath.exists(temp_trimmed_path):
                                try:
                                    await aioremove(temp_trimmed_path)
                                except Exception:
                                    pass
        except Exception as e:
            from ... import LOGGER as _L

            _L.error(f"Error during trimming: {e}")

        if self.seed:
            up_dir = self.up_dir = f"{self.dir}10000"
            up_path = f"{self.up_dir}/{self.name}"
            await create_recursive_symlink(self.dir, self.up_dir)
            LOGGER.info(f"Shortcut created: {dl_path} -> {up_path}")
        else:
            up_dir = self.dir
            up_path = dl_path

        await remove_excluded_files(self.up_dir or self.dir, self.excluded_extensions)

        if not Config.QUEUE_ALL:
            async with queue_dict_lock:
                if self.mid in non_queued_dl:
                    non_queued_dl.remove(self.mid)
            await start_from_queued()

        # Check if merge is enabled - if so, we need to handle join and extract in the right order
        merge_enabled = (
            self.user_dict.get("VIDEO_MERGE_ENABLED", False)
            and not Config.is_media_processing_disabled()
        )
        LOGGER.info(
            f"Processing options: extract={self.extract}, join={self.join}, merge_enabled={merge_enabled}"
        )

        if Config.is_media_processing_disabled() and merge_enabled:
            LOGGER.info("Media processing is disabled - skipping merge operations")
            merge_enabled = False

        if self.extract and not self.is_nzb:
            # If merge is enabled and join is also enabled, extract first then join
            # This ensures extracted files are joined properly for merging
            if self.join and not self.is_file and merge_enabled:
                LOGGER.info(
                    "Merge enabled: extracting first, then checking for files to join..."
                )
                up_path = await self.proceed_extract(up_path, gid)
                if self.is_cancelled:
                    return
                self.is_file = await aiopath.isfile(up_path)
                self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
                self.size = await get_path_size(up_dir)
                self.clear()
                await remove_excluded_files(up_dir, self.excluded_extensions)

                # Check if there are actually split files to join before calling join_files
                if await aiopath.isdir(up_path):
                    try:
                        files = await listdir(up_path)
                        has_split_files = any(
                            re_search(r"\.0+2$", file_) for file_ in files
                        )

                        if has_split_files:
                            LOGGER.info(
                                "Found split files after extraction, joining them for merge compatibility..."
                            )
                            await join_files(up_path)
                        else:
                            LOGGER.info(
                                "No split files found after extraction, skipping join operation"
                            )
                    except Exception as e:
                        LOGGER.warning(
                            f"Error checking for split files: {e}, proceeding with join anyway"
                        )
                        await join_files(up_path)
            else:
                # Standard extraction (when join is not needed for merge or merge is disabled)
                LOGGER.info("Extracting archives...")
                up_path = await self.proceed_extract(up_path, gid)
                if self.is_cancelled:
                    return
                self.is_file = await aiopath.isfile(up_path)
                self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
                self.size = await get_path_size(up_dir)
                self.clear()
                await remove_excluded_files(up_dir, self.excluded_extensions)

        # Handle join operation when extract is not enabled or when merge is not enabled
        if self.join and not self.is_file and not (self.extract and merge_enabled):
            LOGGER.info("Joining split files...")
            await join_files(up_path)

        # Process video+subtitle merging if enabled and selected (NOT QUEUED)
        if not self.is_cancelled and self.is_video_tool_selected(
            "VIDEO_SUBTITLE_MERGE"
        ):
            up_path = await self.merge_video_subtitles(up_path, gid)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()
        elif not self.is_cancelled and not self.is_video_tool_selected(
            "VIDEO_SUBTITLE_MERGE"
        ):
            LOGGER.info("Video+subtitle merge not selected, skipping")

        # Process video hardsub if enabled and selected (NOT QUEUED)
        if not self.is_cancelled and self.is_video_tool_selected("VIDEO_HARDSUB"):
            up_path = await self.hardsub_video(up_path, gid)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()
        elif not self.is_cancelled and not self.is_video_tool_selected("VIDEO_HARDSUB"):
            LOGGER.info("Video hardsub not selected, skipping")

        # Process video+audio merging if enabled and selected (NOT QUEUED)
        if not self.is_cancelled and self.is_video_tool_selected("VIDEO_AUDIO_MERGE"):
            up_path = await self.merge_video_audio(up_path, gid)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()
        elif not self.is_cancelled and not self.is_video_tool_selected(
            "VIDEO_AUDIO_MERGE"
        ):
            LOGGER.info("Video+audio merge not selected, skipping")

        # Process video merging if enabled and selected (NOT QUEUED)
        if not self.is_cancelled and self.is_video_tool_selected("VIDEO_MERGE"):
            up_path = await self.merge_videos(up_path, gid)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()
        elif not self.is_cancelled and not self.is_video_tool_selected("VIDEO_MERGE"):
            LOGGER.info("Video merge not selected, skipping")

        # Check if we're dealing with a video file or a directory that might contain videos
        if not self.is_cancelled and (
            (
                await aiopath.isfile(up_path)
                and await self.is_video_file_enhanced(up_path)
            )
            or await aiopath.isdir(up_path)
        ):
            # Process video stream extraction if enabled and selected (NOT QUEUED)
            if (
                not self.is_cancelled
                and self.user_dict.get("VIDEO_STREAM_EXTRACT_ENABLED", False)
                and not Config.is_media_processing_disabled()
                and self.is_video_tool_selected("STREAM_EXTRACT")
            ):
                try:
                    up_path = await self.extract_video_streams(up_path, gid)
                    if self.is_cancelled:
                        return
                    self.is_file = await aiopath.isfile(up_path)
                    self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
                    self.size = await get_path_size(up_dir)
                    self.clear()
                except Exception as e:
                    LOGGER.error(f"Error in stream extraction process: {str(e)}")
            elif (
                not self.is_cancelled
                and self.user_dict.get("VIDEO_STREAM_EXTRACT_ENABLED", False)
                and not self.is_video_tool_selected("STREAM_EXTRACT")
            ):
                LOGGER.info(
                    f"Video stream extraction enabled but not selected, skipping stream extraction"
                )

            # Process stream swapping if enabled and selected (NOT QUEUED)
            if (
                not self.is_cancelled
                and self.user_dict.get("STREAM_SWAP_ENABLED", False)
                and not Config.is_media_processing_disabled()
                and self.is_video_tool_selected("STREAM_SWAP")
            ):
                try:
                    up_path = await self.swap_video_streams(up_path, gid)
                    if self.is_cancelled:
                        return
                    self.is_file = await aiopath.isfile(up_path)
                    self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
                    self.size = await get_path_size(up_dir)
                    self.clear()
                except Exception as e:
                    LOGGER.error(f"Error in stream swap process: {str(e)}")
            elif (
                not self.is_cancelled
                and self.user_dict.get("STREAM_SWAP_ENABLED", False)
                and not self.is_video_tool_selected("STREAM_SWAP")
            ):
                LOGGER.info(
                    f"Stream swap enabled but not selected, skipping video stream swapping"
                )

            # Process stream removal if enabled and selected (NOT QUEUED)
            if (
                not self.is_cancelled
                and self.user_dict.get("STREAM_REMOVE_ENABLED", False)
                and not Config.is_media_processing_disabled()
                and self.is_video_tool_selected("STREAM_REMOVE")
            ):
                try:
                    up_path = await self.remove_video_streams(up_path, gid)
                    if self.is_cancelled:
                        return
                    self.is_file = await aiopath.isfile(up_path)
                    self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
                    self.size = await get_path_size(up_dir)
                    self.clear()
                except Exception as e:
                    LOGGER.error(f"Error in stream removal process: {str(e)}")
            elif (
                not self.is_cancelled
                and self.user_dict.get("STREAM_REMOVE_ENABLED", False)
                and not self.is_video_tool_selected("STREAM_REMOVE")
            ):
                LOGGER.info(
                    f"Stream removal enabled but -ft flag not present, skipping stream removal"
                )
        else:
            LOGGER.info(
                f"No video content found in {up_path}, skipping video processing features"
            )

        # Execute remaining media processing tasks through queue (FFmpeg, Encoding, Watermarking)
        up_path = await self.execute_media_processing_with_queue(up_path, gid)
        if self.is_cancelled or up_path is None:
            return

        if self.is_leech and self.is_file:
            fname = ospath.basename(up_path)
            self.file_details["filename"] = fname
            self.file_details["mime_type"] = (guess_type(fname))[
                0
            ] or "application/octet-stream"

        if self.name_swap:
            up_path = await self.substitute(up_path)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]

        # Apply filename pattern removal if specified (command line or user settings)
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
        if self.screen_shots:
            LOGGER.info(
                f"Screenshots requested. SS Grid enabled: {getattr(self, 'ss_grid', False)}, Screenshots: {self.screen_shots}"
            )

            # Log all SS Grid parameters and user settings
            LOGGER.info(f"SS Grid parameters and user settings check:")
            LOGGER.info(
                f"SS Grid command line enabled: {getattr(self, 'ss_grid', False)}"
            )
            LOGGER.info(f"SS Grid count: {getattr(self, 'ss_grid_count', 0)}")
            LOGGER.info(f"SS Grid layout: {getattr(self, 'ss_grid_layout', '')}")
            LOGGER.info(f"SS Grid PDF mode: {getattr(self, 'ss_grid_pdf', False)}")
            LOGGER.info(f"SS Grid watermark: {getattr(self, 'ss_grid_watermark', '')}")

            # Also check if user_dict is properly set
            if hasattr(self, "user_dict"):
                LOGGER.info(f"User dict found: {self.user_dict}")
                LOGGER.info(
                    f"User settings - SS_GRID_ENABLED: {self.user_dict.get('SS_GRID_ENABLED', False)}"
                )
                LOGGER.info(
                    f"User settings - SS_GRID_COUNT: {self.user_dict.get('SS_GRID_COUNT', 0)}"
                )
                LOGGER.info(
                    f"User settings - SS_GRID_LAYOUT: {self.user_dict.get('SS_GRID_LAYOUT', '')}"
                )
                LOGGER.info(
                    f"User settings - SS_GRID_PDF_MODE: {self.user_dict.get('SS_GRID_PDF_MODE', False)}"
                )
            else:
                LOGGER.warning("No user_dict attribute found in TaskListener instance")

            # Make sure user_dict is properly initialized if it doesn't exist
            if not hasattr(self, "user_dict"):
                LOGGER.info("Initializing empty user_dict")
                self.user_dict = {}

            # Explicitly set SS_GRID_ENABLED in user_dict if it's enabled from command line
            if getattr(self, "ss_grid", False) and not self.user_dict.get(
                "SS_GRID_ENABLED", False
            ):
                LOGGER.info(
                    "Setting SS_GRID_ENABLED in user_dict based on command line parameter"
                )
                self.user_dict["SS_GRID_ENABLED"] = True

            up_path = await self.generate_screenshots(up_path)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)

        if self.convert_audio or self.convert_video:
            up_path = await self.convert_media(
                up_path,
                gid,
            )
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()

        if self.sample_video:
            up_path = await self.generate_sample_video(up_path, gid)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()
        elif getattr(self, "user_dict", {}).get("SAMPLE_VIDEO_ENABLED", False):
            # Trigger sample video generation via user settings (random mode)
            self.sample_video = (
                True  # sentinel to pass check inside generate_sample_video
            )
            up_path = await self.generate_sample_video(up_path, gid)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()

        if self.compress:
            up_path = await self.proceed_compress(
                up_path,
                gid,
            )
            self.is_file = await aiopath.isfile(up_path)
            if self.is_cancelled:
                return
            self.clear()

        self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
        self.size = await get_path_size(up_dir)

        if self.is_leech and not self.compress:
            # Log relevant information before splitting
            LOGGER.info(f"Checking if file needs to be split: {self.name}")
            LOGGER.info(f"File size: {self.size}, Split size: {self.split_size}")
            LOGGER.info(
                f"Hybrid leech: {self.hybrid_leech}, User transmission: {self.user_transmission}"
            )
            LOGGER.info(f"Max split size: {self.max_split_size}")
            LOGGER.info(f"Premium user: {TgClient.IS_PREMIUM_USER}")

            # Calculate size in GB for easier debugging
            size_gb = self.size / (1024**3)
            split_size_gb = self.split_size / (1024**3)
            LOGGER.info(
                f"File size in GB: {size_gb:.2f}, Split size in GB: {split_size_gb:.2f}"
            )

            # Ensure split_size is not zero; if zero, use max_split_size
            eff_split = self.split_size or self.max_split_size

            if self.size > eff_split:
                LOGGER.info(
                    f"File size {self.size} exceeds effective split size {eff_split}. Splitting..."
                )
                await self.proceed_split(up_path, gid)
            else:
                LOGGER.info(
                    f"File size {self.size} is under or equal to effective split size {eff_split}. No splitting needed."
                )

            if self.is_cancelled:
                return
            self.clear()

        self.subproc = None

        add_to_queue, event = await check_running_tasks(self, "up")
        await start_from_queued()
        if add_to_queue:
            LOGGER.info(f"Added to Queue/Upload: {self.name}")
            async with task_dict_lock:
                task_dict[self.mid] = QueueStatus(self, gid, "Up")
            await event.wait()
            if self.is_cancelled:
                return
            LOGGER.info(f"Start from Queued/Upload: {self.name}")

        self.size = await get_path_size(up_dir)

        # Embed cover art for both mirror and leech operations (before filename modifications)
        if self.user_dict.get("EMBED_USER_IMAGE_AS_COVER", False):
            try:
                LOGGER.info(f"Cover art embedding enabled for user {self.user_id}")
                up_path = await self.embed_cover_art_universal(up_path)
                if self.is_cancelled:
                    return
                # Recalculate size after cover art embedding
                self.size = await get_path_size(up_dir)
                LOGGER.info("Cover art embedding process completed successfully")
            except Exception as e:
                LOGGER.warning(f"Cover art embedding failed: {e}")
        else:
            LOGGER.info("Cover art embedding disabled or not configured")

        # Apply Auto Rename for mirror operations (rename actual files on disk)
        if not self.is_leech and self.user_dict.get("AUTO_RENAME", False):
            try:
                LOGGER.info(
                    f"Auto Rename enabled for mirror operation - processing files at: {up_path}"
                )
                from ..ext_utils.filename_utils import apply_auto_rename_to_path

                original_up_path = up_path
                up_path = await apply_auto_rename_to_path(up_path, self)

                # Update self.name if the main file/folder was renamed
                if original_up_path != up_path:
                    import os

                    self.name = os.path.basename(up_path)
                    LOGGER.info(f"Updated task name after auto rename: {self.name}")

                if self.is_cancelled:
                    return
                # Recalculate size after auto rename
                self.size = await get_path_size(up_path)
                LOGGER.info(
                    "Auto Rename process completed successfully for mirror operation"
                )
            except Exception as e:
                LOGGER.warning(f"Auto Rename failed for mirror operation: {e}")
        else:
            if not self.is_leech:
                LOGGER.info(
                    "Auto Rename disabled or not configured for mirror operation"
                )

        # Apply universal filename modifications for all operations
        # For mirror operations, this ensures prefix/suffix are applied to the final upload name
        if not self.is_leech:
            original_name = self.name
            self.name = self.apply_filename_modifications(self.name)
            if original_name != self.name:
                LOGGER.info(
                    f"Applied filename modifications: '{original_name}' -> '{self.name}'"
                )

        if self.is_yt:
            LOGGER.info(f"Up to yt Name: {self.name}")
            yt = YouTubeUpload(self, up_path)
            async with task_dict_lock:
                task_dict[self.mid] = YtStatus(self, yt, gid, "up")
            await gather(
                update_status_message(self.message.chat.id),
                sync_to_async(yt.upload),
            )
            del yt
        elif self.is_leech:
            LOGGER.info(f"Leech Name: {self.name}")
            tg = TelegramUploader(self, up_dir)
            async with task_dict_lock:
                task_dict[self.mid] = TelegramStatus(self, tg, gid, "up")
            await gather(
                update_status_message(self.message.chat.id),
                tg.upload(),
            )
            del tg
        elif is_gdrive_id(self.up_dest):
            LOGGER.info(f"Gdrive Upload Name: {self.name}")
            drive = GoogleDriveUpload(self, up_path)
            async with task_dict_lock:
                task_dict[self.mid] = GoogleDriveStatus(self, drive, gid, "up")
            await gather(
                update_status_message(self.message.chat.id),
                sync_to_async(drive.upload),
            )
            del drive
        elif self.up_dest == "gofile":
            LOGGER.info(f"GoFile Upload Name: {self.name}")
            gofile = GoFileUpload(self, up_path)
            async with task_dict_lock:
                task_dict[self.mid] = GoFileStatus(self, gofile, gid, "up")
            await gather(
                update_status_message(self.message.chat.id),
                gofile.upload(),
            )
            del gofile
        else:
            LOGGER.info(f"Rclone Upload Name: {self.name}")
            RCTransfer = RcloneTransferHelper(self)
            async with task_dict_lock:
                task_dict[self.mid] = RcloneStatus(self, RCTransfer, gid, "up")
            await gather(
                update_status_message(self.message.chat.id),
                RCTransfer.upload(up_path),
            )
            del RCTransfer
        return

    async def on_upload_complete(
        self, link, files, folders, mime_type, rclone_path="", dir_id=""
    ):
        if (
            self.is_super_chat
            and Config.INCOMPLETE_TASK_NOTIFIER
            and Config.DATABASE_URL
        ):
            await database.rm_complete_task(self.message.link)

        # Get user thumbnail or use default
        user_thumb = self.user_dict.get("THUMBNAIL")
        if user_thumb and await aiopath.exists(user_thumb):
            photo = user_thumb
        else:
            photo = Config.BOT_IMAGE_PATH  # "assets/BHARTIYEE LEECH.png"

        msg = (
            f"<b><i>{escape(self.name)}</i></b>\n"
            f"\n╭<b>Task Size</b> » {get_readable_file_size(self.size)}"
            #   f"\n┊<b>Time Taken</b> » {get_readable_time(time() - self.message.date.timestamp())}"
            #  f"\n┊<b>In Mode</b> » {self.mode[0]}"
            #  f"\n┊<b>Out Mode</b> » {self.mode[1]}"
        )
        LOGGER.info(f"Task Done: {self.name}")
        if self.is_yt:
            buttons = ButtonMaker()
            if mime_type == "Folder/Playlist":
                msg += f"\n┊<b>Type</b> » Playlist"
                msg += f"\n╰<b>Total Videos</b> » {files}"
                if link:
                    buttons.url_button("🔗 View Playlist", link)
                user_message = f"{self.tag}\nYour playlist ({files} videos) has been uploaded to YouTube successfully!"
            else:
                msg += f"\n╰<b>Type</b> » Video"
                if link:
                    buttons.url_button("🔗 View Video", link)
                user_message = (
                    f"{self.tag}\nYour video has been uploaded to YouTube successfully!"
                )

            msg += f"\n<b>Task By: </b>{self.tag}"

            # Add BOT PM button
            buttons.url_button("View File's", f"https://t.me/{TgClient.BNAME}")
            button = buttons.build_menu(1 if not link else 2)

            await send_message(self.user_id, msg, button, photo=photo)
            if Config.LEECH_DUMP_CHAT:
                await send_message(
                    int(Config.LEECH_DUMP_CHAT), msg, button, photo=photo
                )
            await send_message(self.message, user_message, button, photo=photo)

        elif self.is_leech:
            msg += f"\n┊<b>Total Files: </b>{folders}"
            if mime_type != 0:
                msg += f"\n┊<b>Corrupted Files</b> » {mime_type}"
            msg += f"\n╰<b>Task By</b> » {self.tag}\n\n"

            # Create buttons for BOT PM
            buttons = ButtonMaker()
            buttons.url_button("View File's", f"https://t.me/{TgClient.BNAME}")
            button = buttons.build_menu(1)
            if self.bot_pm:
                pmsg = msg
                # pmsg += "<b><u>Action Performed :</u></b>\n"
                # pmsg += "<i>File(s) have been sent to User PM</i>\n\n"
                if self.is_super_chat:
                    await send_message(self.message, pmsg, button, photo=photo)

            if not files and not self.is_super_chat:
                await send_message(self.message, msg, button, photo=photo)
            else:
                log_chat = self.user_id if self.bot_pm else self.message
                msg += " <b>Files List :</b>\n"
                fmsg = ""
                for index, (link, name) in enumerate(files.items(), start=1):
                    chat_id, msg_id = link.split("/")[-2:]
                    fmsg += f"{index}. <a href='{link}'>{name}</a>"
                    if Config.MEDIA_STORE and (
                        self.is_super_chat or Config.LEECH_DUMP_CHAT
                    ):
                        if chat_id.isdigit():
                            chat_id = f"-100{chat_id}"
                        flink = f"https://t.me/{TgClient.BNAME}?start={encode_slink('file' + chat_id + '&&' + msg_id)}"
                        fmsg += f"\n╰<b>Get Media</b> » <a href='{flink}'>Store Link</a> | <a href='https://t.me/share/url?url={flink}'>Share Link</a>"
                    fmsg += "\n"
                    if len(fmsg.encode() + msg.encode()) > 4000:
                        await send_message(log_chat, msg + fmsg, photo=photo)
                        await sleep(1)
                        fmsg = ""
                if fmsg != "":
                    await send_message(log_chat, msg + fmsg, photo=photo)
        else:
            msg += f"\n╰<b>Type</b> » {mime_type}"
            if mime_type == "Folder":
                msg += f"\n┊<b>SubFolders</b> » {folders}"
                msg += f"\n┊<b>Files</b> » {files}"
            if (
                link
                or rclone_path
                and Config.RCLONE_SERVE_URL
                and not self.private_link
            ):
                # Create buttons for private messages (PM, MIRROR_LOG, MIRROR_DUMP_CHAT) with cloud link
                pm_buttons = ButtonMaker()
                if link and Config.SHOW_CLOUD_LINK:
                    pm_buttons.url_button("☁️ Cloud Link", link)
                else:
                    msg += f"\n\nPath: <code>{rclone_path}</code>"
                if rclone_path and Config.RCLONE_SERVE_URL and not self.private_link:
                    remote, rpath = rclone_path.split(":", 1)
                    url_path = rutils.quote(f"{rpath}")
                    share_url = f"{Config.RCLONE_SERVE_URL}/{remote}/{url_path}"
                    if mime_type == "Folder":
                        share_url += "/"
                    pm_buttons.url_button("🔗 Rclone Link", share_url)
                if not rclone_path and dir_id:
                    INDEX_URL = ""
                    if self.private_link:
                        INDEX_URL = self.user_dict.get("INDEX_URL", "") or ""
                    elif Config.INDEX_URL:
                        INDEX_URL = Config.INDEX_URL
                    if INDEX_URL:
                        # Use the base INDEX_URL directly instead of findpath
                        pm_buttons.url_button("⚡ Index Link", INDEX_URL)
                        if mime_type.startswith(("image", "video", "audio")):
                            share_urls = f"{INDEX_URL}findpath?id={dir_id}&view=true"
                            pm_buttons.url_button("🌐 View Link", share_urls)
                # Add BOT PM button
                pm_buttons.url_button("View File's", f"https://t.me/{TgClient.BNAME}")
                pm_button = pm_buttons.build_menu(2)

                # Create buttons for group message without cloud link and rclone link
                group_buttons = ButtonMaker()
                # Remove rclone link from group messages - commented out
                # if rclone_path and Config.RCLONE_SERVE_URL and not self.private_link:
                #     remote, rpath = rclone_path.split(":", 1)
                #     url_path = rutils.quote(f"{rpath}")
                #     share_url = f"{Config.RCLONE_SERVE_URL}/{remote}/{url_path}"
                #     if mime_type == "Folder":
                #         share_url += "/"
                #     group_buttons.url_button("🔗 Rclone Link", share_url)
                if not rclone_path and dir_id:
                    INDEX_URL = ""
                    if self.private_link:
                        INDEX_URL = self.user_dict.get("INDEX_URL", "") or ""
                    elif Config.INDEX_URL:
                        INDEX_URL = Config.INDEX_URL
                    if INDEX_URL:
                        # Use the base INDEX_URL directly instead of findpath
                        group_buttons.url_button("⚡ Index Link", INDEX_URL)
                        if mime_type.startswith(("image", "video", "audio")):
                            share_urls = f"{INDEX_URL}findpath?id={dir_id}&view=true"
                            group_buttons.url_button("🌐 View Link", share_urls)
                # Add BOT PM button
                group_buttons.url_button(
                    "View File's", f"https://t.me/{TgClient.BNAME}"
                )
                group_button = group_buttons.build_menu(2)
            else:
                msg += f"\n┊\n┊Path: <code>{rclone_path}</code>"
                # Create buttons for BOT PM when no other buttons exist
                pm_buttons = ButtonMaker()
                pm_buttons.url_button("View File's", f"https://t.me/{TgClient.BNAME}")
                pm_button = pm_buttons.build_menu(1)

                # Same buttons for group
                group_button = pm_button
                msg += f"\n┊\n╰<b>Task By</b> » {self.tag}\n\n"
            group_msg = (
                # msg + " <b><u>Action Performed :</u></b>\n"
                " <i>Cloud link(s) have been sent to User PM</i>\n\n"
            )

            if self.bot_pm and self.is_super_chat:
                await send_message(self.user_id, msg, pm_button, photo=photo)

            if hasattr(Config, "MIRROR_LOG_ID") and Config.MIRROR_LOG_ID:
                await send_message(Config.MIRROR_LOG_ID, msg, pm_button, photo=photo)

            # Send to user's configured MIRROR_DUMP_CHAT if set
            mirror_dump_chat = self.user_dict.get("MIRROR_DUMP_CHAT")
            if mirror_dump_chat:
                # Handle both simple chat ID and chat_id|topic_id format
                chat_parts = str(mirror_dump_chat).split("|")
                chat_id = chat_parts[0]
                topic_id = (
                    int(chat_parts[1])
                    if len(chat_parts) > 1 and chat_parts[1].isdigit()
                    else None
                )

                LOGGER.info(
                    f"MIRROR_DUMP_CHAT: original='{mirror_dump_chat}', chat_id='{chat_id}', topic_id={topic_id}"
                )

                try:
                    await send_message(
                        int(chat_id),
                        msg,
                        pm_button,
                        photo=photo,
                        message_thread_id=topic_id,
                    )
                except ValueError:
                    LOGGER.warning(
                        f"Invalid MIRROR_DUMP_CHAT format: {mirror_dump_chat}"
                    )

            await send_message(self.message, group_msg, group_button, photo=photo)
        # Try to send a happy/success sticker
        try:
            await send_success_sticker(self.message)
        except Exception:
            pass

        if self.seed:
            await clean_target(self.up_dir)
            async with queue_dict_lock:
                if self.mid in non_queued_up:
                    non_queued_up.remove(self.mid)
            await start_from_queued()
            return

        if self.pm_msg and (not Config.DELETE_LINKS or Config.CLEAN_LOG_MSG):
            await delete_message(self.pm_msg)

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

        # Clean up video tools selection when this is the final task in a multi-download
        if (
            hasattr(self, "multi_tag")
            and self.multi_tag
            and hasattr(self, "multi")
            and self.multi <= 1
        ):
            from ..ext_utils.video_tools_selector import multi_video_tools_selection

            if self.multi_tag in multi_video_tools_selection:
                del multi_video_tools_selection[self.multi_tag]
                LOGGER.info(
                    f"[DEBUG-VT] 🧹 Cleaned up video tools selection for completed multi-download: {self.multi_tag}"
                )

    async def on_download_error(self, error, button=None, is_limit=False):
        LOGGER.info(
            f"[CANCEL] TaskListener.on_download_error START for {self.name} - error: {error}"
        )
        # Sad/error sticker
        try:
            await send_error_sticker(self.message)
        except Exception:
            pass
        LOGGER.info(
            f"[CANCEL] TaskListener.on_download_error before task_dict_lock for {self.name}"
        )
        async with task_dict_lock:
            LOGGER.info(
                f"[CANCEL] TaskListener.on_download_error inside task_dict_lock for {self.name}"
            )
            if self.mid in task_dict:
                del task_dict[self.mid]
            count = len(task_dict)
            LOGGER.info(
                f"[CANCEL] TaskListener.on_download_error before send_message for {self.name}"
            )
            await send_message(
                self.message,
                f"{self.tag} {escape(str(error))}",
                photo="assets/BHARTIYEE LEECH.png",
            )
            LOGGER.info(
                f"[CANCEL] TaskListener.on_download_error after send_message for {self.name}"
            )
        if count == 0:
            await self.clean()
        else:
            await update_status_message(self.message.chat.id)
        if (
            self.is_super_chat
            and Config.INCOMPLETE_TASK_NOTIFIER
            and Config.DATABASE_URL
        ):
            await database.rm_complete_task(self.message.link)
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
        LOGGER.info(
            f"[CANCEL] TaskListener.on_download_error before start_from_queued for {self.name}"
        )
        await start_from_queued()
        LOGGER.info(
            f"[CANCEL] TaskListener.on_download_error after start_from_queued for {self.name}"
        )

        # Note: Video tools selection cleanup is handled in run_multi when multi_tag is discarded

        LOGGER.info(
            f"[CANCEL] TaskListener.on_download_error before sleep(3) for {self.name}"
        )
        await sleep(3)
        LOGGER.info(
            f"[CANCEL] TaskListener.on_download_error after sleep(3) for {self.name}"
        )
        LOGGER.info(
            f"[CANCEL] TaskListener.on_download_error before clean_download(self.dir) for {self.name}"
        )
        await clean_download(self.dir)
        LOGGER.info(
            f"[CANCEL] TaskListener.on_download_error after clean_download(self.dir) for {self.name}"
        )
        if self.up_dir:
            LOGGER.info(
                f"[CANCEL] TaskListener.on_download_error before clean_download(self.up_dir) for {self.name}"
            )
            await clean_download(self.up_dir)
            LOGGER.info(
                f"[CANCEL] TaskListener.on_download_error after clean_download(self.up_dir) for {self.name}"
            )
        if self.thumb and await aiopath.exists(self.thumb):
            LOGGER.info(
                f"[CANCEL] TaskListener.on_download_error before remove(self.thumb) for {self.name}"
            )
            await remove(self.thumb)
            LOGGER.info(
                f"[CANCEL] TaskListener.on_download_error after remove(self.thumb) for {self.name}"
            )
        LOGGER.info(f"[CANCEL] TaskListener.on_download_error END for {self.name}")

    async def on_upload_error(self, error):
        LOGGER.info(
            f"[CANCEL] TaskListener.on_upload_error START for {self.name} - error: {error}"
        )
        # Sad/error sticker
        try:
            await send_error_sticker(self.message)
        except Exception:
            pass
        async with task_dict_lock:
            if self.mid in task_dict:
                del task_dict[self.mid]
            count = len(task_dict)
            await send_message(
                self.message,
                f"{self.tag} {escape(str(error))}",
                photo="assets/BHARTIYEE LEECH.png",
            )
        if count == 0:
            await self.clean()
        else:
            await update_status_message(self.message.chat.id)
        if (
            self.is_super_chat
            and Config.INCOMPLETE_TASK_NOTIFIER
            and Config.DATABASE_URL
        ):
            await database.rm_complete_task(self.message.link)
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

        # Note: Video tools selection cleanup is handled in run_multi when multi_tag is discarded

        # Check if there are any active stream extractions for this task before cleaning
        try:
            from ..ext_utils.stream_extractor import active_extractions

            task_extractions = {
                sid: data
                for sid, data in active_extractions.items()
                if data.get("listener_mid") == self.mid
            }

            if task_extractions:
                extraction_paths = [data["path"] for data in task_extractions.values()]
                LOGGER.info(
                    f"Skipping cleanup for {self.name} as there are active stream extractions: {extraction_paths}"
                )
            else:
                await clean_download(self.dir)
                if self.up_dir:
                    await clean_download(self.up_dir)
                if self.thumb and await aiopath.exists(self.thumb):
                    await remove(self.thumb)
        except Exception as e:
            LOGGER.error(f"Error checking active extractions: {str(e)}")
            # Fall back to standard cleanup
            await clean_download(self.dir)
            if self.up_dir:
                await clean_download(self.up_dir)
            if self.thumb and await aiopath.exists(self.thumb):
                await remove(self.thumb)

        LOGGER.info(f"[CANCEL] TaskListener.on_upload_error END for {self.name}")

    async def extract_video_streams(self, up_path, gid):
        """
        Extract selected audio and subtitle streams from video files if enabled in user settings

        Parameters:
        up_path (str): Path to the uploaded files
        gid (str): Task ID

        Returns:
        str: Path to the extracted files directory
        """
        if not self.user_dict.get("VIDEO_STREAM_EXTRACT_ENABLED", False):
            return up_path

        LOGGER.info(f"Checking for video files to extract streams in: {up_path}")

        try:
            # Get video files in the directory
            if await aiopath.isfile(up_path) and await self.is_video_file_enhanced(
                up_path
            ):
                # Single video file
                LOGGER.info(f"Found single video file: {up_path}")
                video_files = [up_path]
                extract_dir = ospath.dirname(up_path)
            else:
                # Directory with possible video files
                extract_dir = up_path
                dir_contents = []
                if await aiopath.exists(extract_dir):
                    if await aiopath.isdir(extract_dir):
                        LOGGER.info(
                            f"Looking for video files in directory: {extract_dir}"
                        )
                        dir_contents = await listdir(extract_dir)
                    else:
                        dir_contents = [ospath.basename(extract_dir)]
                        extract_dir = ospath.dirname(extract_dir)

                LOGGER.info(f"Directory contents: {dir_contents}")

                video_files = []
                for file_ in dir_contents:
                    full_path = ospath.join(extract_dir, file_)
                    # Use enhanced detection for directory scanning (quick check to avoid slowdown)
                    if FileTypeDetector.is_video_by_extension(full_path):
                        LOGGER.info(f"Found video file: {full_path}")
                        video_files.append(full_path)

            # If no video files, return original path
            if not video_files:
                LOGGER.info(f"No video files found for stream extraction")
                return up_path

            LOGGER.info(f"Found {len(video_files)} video file(s) for stream extraction")

            # For each video file, start stream extraction process
            extractors = []
            for video_file in video_files:
                LOGGER.info(f"Creating stream extraction UI for {video_file}")
                from ..ext_utils.stream_extractor import (
                    StreamExtractor,
                    active_extractions,
                )

                # Create and show the extraction UI
                extractor = StreamExtractor(self, video_file)
                result = await extractor.create_selection_message()

                if not result:
                    LOGGER.error(
                        f"Failed to create stream extraction UI for {video_file}"
                    )
                else:
                    LOGGER.info(
                        f"Stream extraction UI created successfully for {video_file}"
                    )
                    extractors.append(extractor)

            # Wait for all extraction processes to complete or timeout after 10 minutes (600 seconds)
            if extractors:
                LOGGER.info(f"Waiting for user to interact with stream extraction UI")

                # Keep track of extraction directories
                extracted_dirs = []

                # Wait for each extractor to complete or timeout
                for extractor in extractors:
                    session_id = extractor.session_id
                    if session_id in active_extractions:
                        try:
                            # Wait up to 10 minutes for user to interact with the UI
                            extraction_timeout = 600  # 10 minutes
                            for i in range(extraction_timeout):
                                if active_extractions[session_id]["complete"].is_set():
                                    LOGGER.info(
                                        f"Stream extraction completed for {session_id}"
                                    )
                                    # Check if any files were extracted
                                    if extractor.extracted_files and (
                                        extractor.extracted_files.get("audio")
                                        or extractor.extracted_files.get("subtitle")
                                    ):
                                        # Get the extraction directory
                                        video_name = ospath.splitext(
                                            ospath.basename(extractor.video_path)
                                        )[0]
                                        extract_dir = ospath.join(
                                            ospath.dirname(extractor.video_path),
                                            f"extracted_{video_name}",
                                        )
                                        if await aiopath.exists(extract_dir):
                                            extracted_dirs.append(extract_dir)
                                    break
                                await sleep(1)
                            else:
                                # Timeout occurred
                                LOGGER.warning(
                                    f"Stream extraction timeout for {session_id} after {extraction_timeout} seconds"
                                )
                        except Exception as e:
                            LOGGER.error(
                                f"Error waiting for extraction completion: {e}"
                            )
                        finally:
                            # Clean up the active extraction entry
                            if session_id in active_extractions:
                                active_extractions[session_id][
                                    "complete"
                                ].set()  # Make sure it's marked as complete
                                del active_extractions[session_id]

                # If extraction happened and source files were deleted, use the extracted directories
                keep_source_files = self.user_dict.get("KEEP_MERGE_SOURCE_FILES", False)
                if extracted_dirs and not keep_source_files:
                    # Check if the source file still exists
                    all_sources_deleted = True
                    for video_file in video_files:
                        if await aiopath.exists(video_file):
                            all_sources_deleted = False
                            break

                    if all_sources_deleted:
                        # If all source files were deleted, only use extracted directories
                        if len(extracted_dirs) == 1:
                            LOGGER.info(
                                f"Using extracted directory as source file was deleted: {extracted_dirs[0]}"
                            )
                            return extracted_dirs[0]
                        else:
                            # Multiple extraction directories - create a parent dir
                            parent_dir = ospath.dirname(extracted_dirs[0])
                            LOGGER.info(
                                f"Using parent directory containing all extracted files: {parent_dir}"
                            )
                            return parent_dir

            # Default: return original path
            return up_path
        except Exception as e:
            LOGGER.error(f"Error in extract_video_streams: {str(e)}")
            return up_path

    async def swap_video_streams(self, up_path, gid):
        """
        Reorder audio and subtitle streams in video files if Stream Swap is enabled

        Parameters:
        up_path (str): Path to the uploaded files
        gid (str): Task ID

        Returns:
        str: Path to the modified files or original path if no changes
        """
        stream_swap_setting = self.user_dict.get("STREAM_SWAP_ENABLED", False)
        LOGGER.info(f"Stream swap setting for user: {stream_swap_setting}")
        if not stream_swap_setting:
            LOGGER.info("Stream swap is disabled, skipping")
            return up_path

        LOGGER.info(f"Checking for video files to swap streams in: {up_path}")

        try:
            # Get video files in the directory
            if await aiopath.isfile(up_path) and await self.is_video_file_enhanced(
                up_path
            ):
                # Single video file
                LOGGER.info(f"Found single video file: {up_path}")
                video_files = [up_path]
            else:
                # Directory with possible video files
                dir_contents = []
                if await aiopath.exists(up_path) and await aiopath.isdir(up_path):
                    dir_contents = await listdir(up_path)

                video_files = []
                for file in dir_contents:
                    video_path = ospath.join(up_path, file)
                    if await aiopath.isfile(
                        video_path
                    ) and FileTypeDetector.is_video_by_extension(video_path):
                        video_files.append(video_path)
                        LOGGER.info(f"Found video file in directory: {video_path}")

            # Only process if we have video files
            if not video_files:
                LOGGER.info("No video files found for stream swap")
                LOGGER.info("No video files found for stream swapping")
                return up_path

            # Process each video file
            swappers = []

            for video_file in video_files:
                try:
                    LOGGER.info(f"Creating stream swap UI for {video_file}")
                    from ..ext_utils.stream_swap import StreamSwapper, active_swaps

                    # Create and show the swap UI
                    swapper = StreamSwapper(self, video_file)
                    result = await swapper.create_selection_message()

                    if not result:
                        LOGGER.error(
                            f"Failed to create stream swap UI for {video_file}"
                        )
                    else:
                        LOGGER.info(
                            f"Stream swap UI created successfully for {video_file}"
                        )
                        swappers.append(swapper)
                except Exception as e:
                    LOGGER.error(
                        f"Error creating stream swap UI for {video_file}: {str(e)}"
                    )

            # Wait for all swap processes to complete or timeout after 10 minutes (600 seconds)
            if swappers:
                LOGGER.info(f"Waiting for user to interact with stream swap UI")

                # Keep track of any modified paths
                modified_paths = []

                # Wait for each swapper to complete or timeout
                for swapper in swappers:
                    session_id = swapper.session_id
                    if session_id in active_swaps:
                        try:
                            # Wait up to 10 minutes for user to interact with the UI
                            swap_timeout = 600  # 10 minutes
                            for i in range(swap_timeout):
                                if active_swaps[session_id]["complete"].is_set():
                                    LOGGER.info(
                                        f"Stream swap completed for {session_id}"
                                    )
                                    # If a file was successfully reordered, add it to the list
                                    if (
                                        hasattr(swapper, "reordered_file_path")
                                        and swapper.reordered_file_path
                                    ):
                                        LOGGER.info(
                                            f"Adding reordered file to modified paths: {swapper.reordered_file_path}"
                                        )
                                        modified_paths.append(
                                            swapper.reordered_file_path
                                        )
                                    break
                                await sleep(1)
                            else:
                                # Timeout occurred
                                LOGGER.warning(
                                    f"Stream swap timeout for {session_id} after {swap_timeout} seconds"
                                )
                        except Exception as e:
                            LOGGER.error(f"Error waiting for stream swap: {str(e)}")

                # If any files were modified, return the modified path or directory
                if modified_paths:
                    # If we processed a single file and have a single result, return that path
                    if len(video_files) == 1 and len(modified_paths) == 1:
                        LOGGER.info(
                            f"Returning single reordered file path: {modified_paths[0]}"
                        )
                        return modified_paths[0]
                    else:
                        # Otherwise return the directory
                        LOGGER.info(
                            f"Multiple files processed, returning directory: {up_path}"
                        )
                        return up_path

            return up_path
        except Exception as e:
            LOGGER.error(f"Error in swap_video_streams: {str(e)}")
            return up_path

    async def remove_video_streams(self, up_path: str, gid: str = "") -> str:
        """
        Process video files for stream removal (removing selected audio and subtitle tracks)

        Args:
        up_path (str): Path to the file or directory
        gid (str): GID of the download

        Returns:
        str: Path to the modified files or original path if no changes
        """
        stream_remove_setting = self.user_dict.get("STREAM_REMOVE_ENABLED", False)
        LOGGER.info(f"Stream remove setting for user: {stream_remove_setting}")
        if not stream_remove_setting:
            LOGGER.info("Stream removal is disabled, skipping")
            return up_path

        LOGGER.info(f"Checking for video files to remove streams from: {up_path}")

        try:
            # Get video files in the directory
            if await aiopath.isfile(up_path) and await self.is_video_file_enhanced(
                up_path
            ):
                # Single video file
                LOGGER.info(f"Found single video file: {up_path}")
                video_files = [up_path]
            else:
                # Directory with possible video files
                dir_contents = []
                if await aiopath.exists(up_path) and await aiopath.isdir(up_path):
                    dir_contents = await listdir(up_path)

                video_files = []
                for file in dir_contents:
                    video_path = ospath.join(up_path, file)
                    if await aiopath.isfile(
                        video_path
                    ) and FileTypeDetector.is_video_by_extension(video_path):
                        video_files.append(video_path)
                        LOGGER.info(f"Found video file in directory: {video_path}")

            # Only process if we have video files
            if not video_files:
                LOGGER.info("No video files found for stream removal")
                return up_path

            # Process each video file
            removers = []

            for video_file in video_files:
                try:
                    LOGGER.info(f"Creating stream remove UI for {video_file}")
                    from ..ext_utils.stream_remover import (
                        StreamRemover,
                        active_removals,
                    )

                    # Create and show the removal UI
                    remover = StreamRemover(self, video_file)
                    result = await remover.create_selection_message()

                    if not result:
                        LOGGER.error(
                            f"Failed to create stream removal UI for {video_file}"
                        )
                    else:
                        LOGGER.info(
                            f"Stream removal UI created successfully for {video_file}"
                        )
                        removers.append(remover)
                except Exception as e:
                    LOGGER.error(
                        f"Error creating stream removal UI for {video_file}: {str(e)}"
                    )

            # Wait for all removal UIs to complete or timeout
            if removers:
                # Create a task that waits for all removals to complete or timeout after 10 minutes
                try:
                    tasks = []
                    for remover in removers:
                        session_id = remover.session_id
                        if session_id in active_removals:
                            # Get the completion event
                            complete_event = active_removals[session_id]["complete"]
                            # Create a task that waits for the event
                            task = create_task(
                                self._wait_for_removal(complete_event, timeout=600)
                            )
                            tasks.append(task)

                    # Wait for all tasks to complete
                    if tasks:
                        LOGGER.info(
                            f"Waiting for {len(tasks)} stream removal sessions to complete or timeout..."
                        )
                        await gather(*tasks)
                        LOGGER.info(
                            "All stream removal sessions completed or timed out"
                        )
                except Exception as e:
                    LOGGER.error(f"Error waiting for stream removal sessions: {str(e)}")

            # Return the original path as the modified files will replace the original ones
            return up_path
        except Exception as e:
            LOGGER.error(f"Error in stream removal process: {str(e)}")
            return up_path

    async def _wait_for_removal(self, event, timeout=600):
        """Helper method to wait for removal event with a timeout"""
        try:
            # Wait for the event with a timeout
            await wait_for(event.wait(), timeout=timeout)
        except AsyncTimeoutError:
            LOGGER.error(f"Stream removal timed out after {timeout} seconds")
        except Exception as e:
            LOGGER.error(f"Error waiting for stream removal event: {str(e)}")

    async def encode_videos(self, path, gid):
        """
        Encode videos using ffmpeg with user-defined preset
        Supports both single resolution and multi-resolution encoding
        """
        if (
            not self.user_dict.get("VIDEO_ENCODE_ENABLED", False)
            or Config.is_media_processing_disabled()
        ):
            if Config.is_media_processing_disabled():
                LOGGER.info("Media processing disabled - skipping video encoding")
            else:
                LOGGER.info("Video encoding not enabled in user settings, skipping...")
            return path

        preset = self.user_dict.get("VIDEO_ENCODE_PRESET", "medium")
        quality = self.user_dict.get("VIDEO_ENCODE_QUALITY", "Original")
        crf = self.user_dict.get("VIDEO_ENCODE_CRF", 23)
        audio_bitrate = self.user_dict.get("VIDEO_ENCODE_AUDIO_BITRATE", "128k")
        multi_resolution = self.user_dict.get("VIDEO_ENCODE_MULTI_RESOLUTION", False)
        keep_source = self.user_dict.get("KEEP_MERGE_SOURCE_FILES", False)

        encoding_type = "Multi-resolution" if multi_resolution else "Single resolution"
        LOGGER.info(
            f"Video encoding enabled ({encoding_type}), preset: {preset}, quality: {quality}, CRF: {crf}, audio bitrate: {audio_bitrate}, keep source files: {keep_source}"
        )

        if multi_resolution:
            from ..ext_utils.ffmpeg_utils import encode_video_multi_resolution

            encode_function = encode_video_multi_resolution
        else:
            from ..ext_utils.ffmpeg_utils import encode_video

            encode_function = encode_video

        # Check if path is a file or directory
        if await aiopath.isfile(path):
            if await self.is_video_file_enhanced(path):
                # Process single video file
                LOGGER.info(f"Encoding single video: {path}")
                try:
                    # Store original filename for later restoration
                    original_path = path
                    original_name = ospath.basename(original_path)

                    # Pass listener and gid for real-time status updates
                    encoded_result = await encode_function(
                        path, self.user_id, listener=self, gid=gid
                    )

                    if multi_resolution:
                        # Multi-resolution returns a list of files
                        # With Multi-zip enabled, it returns a single zip file
                        # Without Multi-zip, it returns multiple individual files
                        multi_zip_enabled = self.user_dict.get(
                            "VIDEO_ENCODE_MULTI_ZIP", False
                        )

                        if encoded_result and len(encoded_result) >= 1:
                            if multi_zip_enabled:
                                LOGGER.info(
                                    f"Multi-resolution encoding with Multi-zip completed: {encoded_result[0]}"
                                )
                            else:
                                LOGGER.info(
                                    f"Multi-resolution encoding completed: {len(encoded_result)} files created"
                                )
                            # Return the first result (either zip file or first individual file)
                            return encoded_result[0] if encoded_result else path
                        else:
                            return encoded_result[0] if encoded_result else path
                    else:
                        # Single resolution returns a single file path
                        if encoded_result != path:
                            # Try to rename encoded file back to original filename
                            try:
                                from aiofiles.os import rename as aiorename
                                from pathlib import Path

                                encoded_path_obj = Path(encoded_result)
                                original_path_obj = Path(original_path)

                                # Check if the encoded file has quality suffixes or processing suffixes
                                stem = encoded_path_obj.stem
                                original_stem = original_path_obj.stem

                                # Check for various encoding patterns: _encoded, _processed, quality suffixes like _360p_BL, _720p_BL, etc.
                                needs_rename = (
                                    "_encoded" in stem
                                    or "_processed" in stem
                                    or "_BL" in stem  # Common suffix added by encoding
                                    or stem != original_stem  # Any change in filename
                                )

                                if needs_rename:
                                    # Create new path with original filename in same directory
                                    restored_path = (
                                        encoded_path_obj.parent
                                        / f"{original_path_obj.stem}{encoded_path_obj.suffix}"
                                    )

                                    # Remove original file first if it exists and is different from encoded result
                                    if (
                                        await aiopath.exists(original_path)
                                        and original_path != encoded_result
                                    ):
                                        await remove(original_path)

                                    # Rename encoded file to original filename
                                    await aiorename(encoded_result, str(restored_path))
                                    LOGGER.info(
                                        f"Encoded file renamed back to original filename: {original_name}"
                                    )
                                    return str(restored_path)
                                else:
                                    # No processing suffix, return as-is
                                    LOGGER.info(
                                        f"Video encoded successfully: {encoded_result}"
                                    )
                                    return encoded_result
                            except Exception as rename_err:
                                LOGGER.warning(
                                    f"Could not rename encoded file back to original name: {rename_err}"
                                )
                                LOGGER.info(
                                    f"Video encoded successfully: {encoded_result}"
                                )
                                return encoded_result
                        else:
                            return encoded_result
                except Exception as e:
                    LOGGER.error(f"Error encoding video: {str(e)}")
        else:
            # Process directory of files
            video_paths = []
            async for root, _, files in await sync_to_async(ospath.walk, path):
                for file in files:
                    file_path = ospath.join(root, file)
                    if FileTypeDetector.is_video_by_extension(file_path):
                        video_paths.append(file_path)

            # Process each video sequentially to maintain status tracking
            if video_paths:
                LOGGER.info(f"Found {len(video_paths)} videos to encode")
                all_encoded_files = []

                for i, video_path in enumerate(video_paths):
                    try:
                        LOGGER.info(
                            f"Encoding video {i + 1}/{len(video_paths)}: {video_path}"
                        )
                        # Update status message before encoding
                        if hasattr(self, "message") and hasattr(self, "mid"):
                            from ..telegram_helper.message_utils import (
                                update_status_message,
                            )

                            status_dict_key = (
                                self.message.chat.id
                                if hasattr(self.message, "chat")
                                else self.mid
                            )
                            if status_dict_key:
                                await update_status_message(status_dict_key)

                        # Pass listener and gid for real-time status updates
                        encoded_result = await encode_function(
                            video_path, self.user_id, listener=self, gid=gid
                        )

                        if multi_resolution:
                            # Multi-resolution returns a list of files
                            # With Multi-zip enabled, each video will produce a single zip file
                            # Without Multi-zip, each video will produce multiple individual files
                            if encoded_result:
                                all_encoded_files.extend(encoded_result)
                                multi_zip_enabled = self.user_dict.get(
                                    "VIDEO_ENCODE_MULTI_ZIP", False
                                )
                                if multi_zip_enabled:
                                    LOGGER.info(
                                        f"Multi-resolution encoding with Multi-zip completed for {video_path}: {encoded_result[0]}"
                                    )
                                else:
                                    LOGGER.info(
                                        f"Multi-resolution encoding completed for {video_path}: {len(encoded_result)} files created"
                                    )
                        else:
                            # Single resolution returns a single file path
                            if encoded_result != video_path:
                                all_encoded_files.append(encoded_result)
                                LOGGER.info(
                                    f"Video encoded successfully: {encoded_result}"
                                )

                                # Delete the original file if encoded file is different and 'Keep Source Files' is disabled
                                if not self.user_dict.get(
                                    "KEEP_MERGE_SOURCE_FILES", False
                                ):
                                    try:
                                        LOGGER.info(
                                            f"Deleting original video file: {video_path}"
                                        )
                                        await remove(video_path)
                                        LOGGER.info(f"Original video file deleted")
                                    except Exception as del_err:
                                        LOGGER.error(
                                            f"Error deleting original video: {str(del_err)}"
                                        )

                        # Update status again after encoding to clear out the encoding status
                        if hasattr(self, "message") and hasattr(self, "mid"):
                            from ..telegram_helper.message_utils import (
                                update_status_message,
                            )

                            status_dict_key = (
                                self.message.chat.id
                                if hasattr(self.message, "chat")
                                else self.mid
                            )
                            if status_dict_key:
                                await update_status_message(status_dict_key)
                    except Exception as e:
                        LOGGER.error(f"Error encoding video: {str(e)}")

                if multi_resolution and all_encoded_files:
                    LOGGER.info(
                        f"Multi-resolution encoding complete: {len(all_encoded_files)} total files created"
                    )

        return path

    async def convert_videos(self, path, gid):
        """
        Convert videos to different format using user-defined settings
        """
        if (
            not self.user_dict.get("VIDEO_CONVERT_ENABLED", False)
            or Config.is_media_processing_disabled()
        ):
            if Config.is_media_processing_disabled():
                LOGGER.info(
                    "Media processing disabled - skipping video format conversion"
                )
            else:
                LOGGER.info(
                    "Video format conversion not enabled in user settings, skipping..."
                )
            return path

        target_format = self.user_dict.get("VIDEO_CONVERT_FORMAT", "mp4")
        convert_codec = self.user_dict.get("VIDEO_CONVERT_CODEC", "copy")
        convert_quality = self.user_dict.get("VIDEO_CONVERT_QUALITY", "original")
        keep_source = self.user_dict.get("KEEP_MERGE_SOURCE_FILES", False)

        LOGGER.info(
            f"Video format conversion enabled, target format: {target_format}, codec: {convert_codec}, quality: {convert_quality}, keep source files: {keep_source}"
        )

        from ..ext_utils.ffmpeg_utils import convert_video

        # Check if path is a file or directory
        if await aiopath.isfile(path):
            if await self.is_video_file_enhanced(path):
                # Process single video file
                LOGGER.info(f"Converting single video: {path}")
                try:
                    # Store original filename for later restoration
                    original_path = path
                    original_name = ospath.basename(original_path)

                    # Pass listener and gid for real-time status updates
                    converted_result = await convert_video(
                        path, self.user_id, listener=self, gid=gid
                    )

                    if converted_result != path:
                        # Try to rename converted file back to original filename
                        try:
                            from aiofiles.os import rename as aiorename
                            from pathlib import Path

                            converted_path_obj = Path(converted_result)
                            original_path_obj = Path(original_path)

                            # Check if the converted file has processing suffixes or format changes
                            stem = converted_path_obj.stem
                            original_stem = original_path_obj.stem

                            # Check for various conversion patterns
                            needs_rename = (
                                "_converted" in stem
                                or "_processed" in stem
                                or stem
                                != original_stem  # Any change in filename (excluding extension)
                            )

                            if needs_rename:
                                # Create new path with original filename but keep new extension (if format changed)
                                restored_path = (
                                    converted_path_obj.parent
                                    / f"{original_path_obj.stem}{converted_path_obj.suffix}"
                                )

                                # Remove original file first if it exists and is different from converted result
                                if (
                                    await aiopath.exists(original_path)
                                    and original_path != converted_result
                                ):
                                    await remove(original_path)

                                # Rename converted file to original filename
                                await aiorename(converted_result, str(restored_path))
                                LOGGER.info(
                                    f"Converted file renamed back to original filename: {ospath.basename(restored_path)}"
                                )
                                return str(restored_path)
                            else:
                                # No processing suffix, return as-is
                                LOGGER.info(
                                    f"Video converted successfully: {converted_result}"
                                )
                                return converted_result
                        except Exception as rename_err:
                            LOGGER.warning(
                                f"Could not rename converted file back to original name: {rename_err}"
                            )
                            LOGGER.info(
                                f"Video converted successfully: {converted_result}"
                            )
                            return converted_result
                    else:
                        return converted_result
                except Exception as e:
                    LOGGER.error(f"Error converting video: {str(e)}")
        else:
            # Process directory of files
            video_paths = []
            async for root, _, files in await sync_to_async(ospath.walk, path):
                for file in files:
                    file_path = ospath.join(root, file)
                    if FileTypeDetector.is_video_by_extension(file_path):
                        video_paths.append(file_path)

            # Process each video sequentially to maintain status tracking
            if video_paths:
                LOGGER.info(f"Found {len(video_paths)} videos to convert")

                for i, video_path in enumerate(video_paths):
                    try:
                        LOGGER.info(
                            f"Converting video {i + 1}/{len(video_paths)}: {video_path}"
                        )
                        # Update status message before conversion
                        if hasattr(self, "message") and hasattr(self, "mid"):
                            from ..telegram_helper.message_utils import (
                                update_status_message,
                            )

                            status_dict_key = (
                                self.message.chat.id
                                if hasattr(self.message, "chat")
                                else self.mid
                            )
                            if status_dict_key:
                                await update_status_message(status_dict_key)

                        # Pass listener and gid for real-time status updates
                        converted_result = await convert_video(
                            video_path, self.user_id, listener=self, gid=gid
                        )

                        if converted_result != video_path:
                            LOGGER.info(
                                f"Video converted successfully: {converted_result}"
                            )

                        # Update status again after conversion to clear out the conversion status
                        if hasattr(self, "message") and hasattr(self, "mid"):
                            from ..telegram_helper.message_utils import (
                                update_status_message,
                            )

                            status_dict_key = (
                                self.message.chat.id
                                if hasattr(self.message, "chat")
                                else self.mid
                            )
                            if status_dict_key:
                                await update_status_message(status_dict_key)
                    except Exception as e:
                        LOGGER.error(f"Error converting video: {str(e)}")

        return path

    async def watermark_videos(self, path, gid):
        """
        Add watermark to videos using user-defined settings
        """
        if (
            not self.user_dict.get("VIDEO_WATERMARK_ENABLED", False)
            or Config.is_media_processing_disabled()
        ):
            if Config.is_media_processing_disabled():
                LOGGER.info("Media processing disabled - skipping video watermarking")
            else:
                LOGGER.info(
                    "Video watermarking not enabled in user settings, skipping..."
                )
            return path

        watermark_text = self.user_dict.get("VIDEO_WATERMARK_TEXT", "Default Watermark")
        watermark_position = self.user_dict.get(
            "VIDEO_WATERMARK_POSITION", "bottom-right"
        )
        watermark_opacity = self.user_dict.get("VIDEO_WATERMARK_OPACITY", 0.5)
        watermark_type = self.user_dict.get("VIDEO_WATERMARK_TYPE", "text")
        keep_source = self.user_dict.get("KEEP_MERGE_SOURCE_FILES", False)
        LOGGER.info(
            f"Video watermarking enabled, text: {watermark_text}, position: {watermark_position}, opacity: {watermark_opacity}, type: {watermark_type}, keep source files: {keep_source}"
        )

        from ..ext_utils.watermark_utils import add_watermark

        # Check if path is a file or directory
        if await aiopath.isfile(path):
            if await self.is_video_file_enhanced(path):
                # Process single video file
                LOGGER.info(f"Adding watermark to single video: {path}")
                try:
                    # Store original filename for later restoration
                    original_path = path
                    original_name = ospath.basename(original_path)

                    # Pass listener and gid for real-time status updates
                    watermarked_path = await add_watermark(
                        path, self.user_id, listener=self, gid=gid
                    )
                    if watermarked_path != path:
                        # Try to rename watermarked file back to original filename
                        try:
                            from aiofiles.os import rename as aiorename
                            from pathlib import Path

                            watermarked_path_obj = Path(watermarked_path)
                            original_path_obj = Path(original_path)

                            # Check if the watermarked file has processing suffixes
                            stem = watermarked_path_obj.stem
                            original_stem = original_path_obj.stem

                            # Check for various watermarking patterns
                            needs_rename = (
                                "_watermarked" in stem
                                or "_processed" in stem
                                or stem != original_stem  # Any change in filename
                            )

                            if needs_rename:
                                # Create new path with original filename in same directory
                                restored_path = (
                                    watermarked_path_obj.parent
                                    / f"{original_path_obj.stem}{watermarked_path_obj.suffix}"
                                )

                                # Remove original file first if it exists and is different from watermarked result
                                if (
                                    await aiopath.exists(original_path)
                                    and original_path != watermarked_path
                                ):
                                    await remove(original_path)

                                # Rename watermarked file to original filename
                                await aiorename(watermarked_path, str(restored_path))
                                LOGGER.info(
                                    f"Watermarked file renamed back to original filename: {original_name}"
                                )
                                return str(restored_path)
                            else:
                                # No processing suffix, return as-is
                                LOGGER.info(
                                    f"Video watermarked successfully: {watermarked_path}"
                                )
                                return watermarked_path
                        except Exception as rename_err:
                            LOGGER.warning(
                                f"Could not rename watermarked file back to original name: {rename_err}"
                            )
                            LOGGER.info(
                                f"Video watermarked successfully: {watermarked_path}"
                            )
                            return watermarked_path
                    else:
                        return watermarked_path
                except Exception as e:
                    LOGGER.error(f"Error watermarking video: {str(e)}")
        else:
            # Process directory of files
            video_paths = []
            async for root, _, files in await sync_to_async(ospath.walk, path):
                for file in files:
                    file_path = ospath.join(root, file)
                    if FileTypeDetector.is_video_by_extension(file_path):
                        video_paths.append(file_path)

            # Process each video sequentially to maintain status tracking
            if video_paths:
                LOGGER.info(f"Found {len(video_paths)} videos to watermark")
                for i, video_path in enumerate(video_paths):
                    try:
                        LOGGER.info(
                            f"Watermarking video {i + 1}/{len(video_paths)}: {video_path}"
                        )
                        # Update status message before watermarking
                        if hasattr(self, "message") and hasattr(self, "mid"):
                            from ..telegram_helper.message_utils import (
                                update_status_message,
                            )

                            status_dict_key = (
                                self.message.chat.id
                                if hasattr(self.message, "chat")
                                else self.mid
                            )
                            if status_dict_key:
                                await update_status_message(status_dict_key)

                        # Pass listener and gid for real-time status updates
                        watermarked_path = await add_watermark(
                            video_path, self.user_id, listener=self, gid=gid
                        )

                        # Delete the original file if watermarked file is different and 'Keep Source Files' is disabled
                        if watermarked_path != video_path and not self.user_dict.get(
                            "KEEP_MERGE_SOURCE_FILES", False
                        ):
                            try:
                                LOGGER.info(
                                    f"Deleting original video file: {video_path}"
                                )
                                await remove(video_path)
                                LOGGER.info(f"Original video file deleted")
                            except Exception as del_err:
                                LOGGER.error(
                                    f"Error deleting original video: {str(del_err)}"
                                )

                        # Update status again after watermarking to clear out the watermark status
                        if hasattr(self, "message") and hasattr(self, "mid"):
                            from ..telegram_helper.message_utils import (
                                update_status_message,
                            )

                            status_dict_key = (
                                self.message.chat.id
                                if hasattr(self.message, "chat")
                                else self.mid
                            )
                            if status_dict_key:
                                await update_status_message(status_dict_key)
                    except Exception as e:
                        LOGGER.error(f"Error watermarking video: {str(e)}")

        return path
