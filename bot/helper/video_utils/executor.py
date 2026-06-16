from asyncio import create_subprocess_exec, gather, sleep
from asyncio.subprocess import PIPE
from os import path as ospath, walk
import os
from time import time
from typing import Iterable
import gc  # Added for memory management

from aiofiles import open as aiopen
from aiofiles.os import path as aiopath, makedirs, listdir, remove
from aioshutil import move
from natsort import natsorted

from ... import (
    task_dict,
    task_dict_lock,
    subprocess_lock,
    videos_tools_mode,
    LOGGER,
    DOWNLOAD_DIR,
    cpu_eater_lock,  # Added for CPU limiting
)
from ...core.config_manager import BinConfig
from .ffmpeg_utils import (
    generate_swap_streams_ffmpeg_cmd,
    generate_reorder_streams_ffmpeg_cmd,
)
from ..ext_utils.ffmpeg_utils import _create_memory_aware_subprocess

# Enhanced FFmpeg utilities
from ...helper.ext_utils.ffmpeg_utils import (
    FFmpegEncoderHelper,
    get_video_duration_enhanced,
    get_video_info_enhanced,
    get_quality_settings,
    get_encoding_presets,
    enhance_ffmpeg_command_with_presets,
    multi_resolution_encode,
    encode_video,
    _ff_threads,  # Memory optimization: thread limiting
)
from ...core.config_manager import Config
from ..ext_utils.bot_utils import sync_to_async, decode_output
from ..ext_utils.files_utils import (
    get_path_sizee as get_path_size,
    clean_target,
    ffmpeg_parse,
)
from ..ext_utils.links_utils import get_url_name
from ..ext_utils.media_utils import (
    get_meta_video,
    get_document_type,
    get_media_info,
    FFProgress,
)
from ..ext_utils.task_manager import check_running_tasks
from ..mirror_leech_utils.status_utils.ffmpeg_status import FFMpegStatus
from ..mirror_leech_utils.status_utils.queue_status import QueueStatus
from ..telegram_helper.message_utils import send_status_message, update_status_message
from .extra_selector import ExtraSelect
from .selector import SelectMode


def _normalize_audio_bitrate(raw) -> str:
    """Return a safe audio bitrate for ffmpeg.

    - "copy" => "copy" (caller must handle mapping without -b:a)
    - "original"/"orig"/"source"/"auto" => default "128k"
    - int => f"{int}k"
    - "NNNk" => unchanged
    - invalid => "128k"
    """
    try:
        if raw is None:
            return "128k"
        if isinstance(raw, (int, float)):
            ival = int(raw)
            return f"{ival}k" if ival > 0 else "128k"
        sval = str(raw).strip().lower()
        if sval == "copy":
            return "copy"
        if sval in ("orig", "original", "source", "auto"):
            return "128k"
        if sval.isdigit():
            return f"{int(sval)}k"
        if sval.endswith("k") and sval[:-1].isdigit():
            return sval
    except Exception:
        pass
    return "128k"


class VideoToolsExecutor(FFProgress, ExtraSelect):
    # Class-level constants for supported/unsupported file formats
    SUPPORTED_VIDEO_EXTS = {
        ".mp4",
        ".mkv",
        ".avi",
        ".mov",
        ".wmv",
        ".flv",
        ".webm",
        ".m4v",
        ".3gp",
        ".mpg",
        ".mpeg",
        ".ts",
        ".vob",
        ".ogv",
        ".mts",
        ".m2ts",
    }
    SUPPORTED_AUDIO_EXTS = {
        ".mp3",
        ".aac",
        ".flac",
        ".wav",
        ".ogg",
        ".m4a",
        ".wma",
        ".opus",
        ".alac",
        ".ape",
    }

    # Explicitly unsupported formats that should never be processed by FFmpeg
    UNSUPPORTED_EXTS = {
        ".img",
        ".iso",
        ".bin",
        ".dmg",
        ".vhd",
        ".vmdk",  # Disk images
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".bmp",
        ".tiff",
        ".svg",
        ".webp",  # Images
        ".zip",
        ".rar",
        ".7z",
        ".tar",
        ".gz",
        ".bz2",  # Archives
        ".exe",
        ".dll",
        ".so",
        ".dylib",  # Executables
        ".pdf",
        ".doc",
        ".docx",
        ".txt",
        ".rtf",
    }  # Documents

    def __init__(
        self,
        listener,
        path: str,
        gid: str,
        unwanted_files: list | None = None,
        metadata: Iterable | bool = False,
    ):
        if unwanted_files is None:
            unwanted_files = []
        self.data = None
        self.listener = listener
        self.path = path
        self.mode = None
        self._multi_mode = False
        self._is_dir = None
        self._unwanted_files = unwanted_files
        self._metadata = metadata
        self._org_path = path
        self._gid = gid
        self._start_time = time()
        self._files = []
        self._quality = {
            "1080p": "1920",
            "720p": "1280",
            "540p": "960",
            "480p": "854",
            "360p": "640",
        }
        FFProgress.__init__(self)
        ExtraSelect.__init__(self)

    def _is_supported_media_format(
        self, filepath: str, video_only: bool = False
    ) -> bool | None:
        """
        Check if file has a supported media format for FFmpeg processing.

        Args:
            filepath: Path to the file to check
            video_only: If True, only check for video formats; if False, check video and audio

        Returns:
            True: File has supported format
            False: File has explicitly unsupported format
            None: Unknown extension (should use get_document_type for detection)
        """
        ext = ospath.splitext(filepath)[1].lower()

        # Explicitly reject unsupported formats first
        if ext in self.UNSUPPORTED_EXTS:
            LOGGER.debug(f"Skipping unsupported format for FFmpeg: {filepath}")
            return False

        # Accept supported formats
        if ext in self.SUPPORTED_VIDEO_EXTS:
            return True
        if not video_only and ext in self.SUPPORTED_AUDIO_EXTS:
            return True

        # For unknown extensions, let get_document_type decide
        return None

    async def _get_font_path(self, **kwargs):
        """Get the appropriate font path from single font file upload."""
        user_dict = getattr(self.listener, "user_dict", {}) or {}
        font_path = None

        LOGGER.info(
            f"Font path selection for user {getattr(self.listener, 'user_id', 'unknown')}"
        )
        LOGGER.info(
            f"Available font option - VT_HARDSUB_FONT_PATH: {user_dict.get('VT_HARDSUB_FONT_PATH')}"
        )

        # 1. Check explicit font path from kwargs first (highest priority)
        if kwargs.get("font_path"):
            font_path = kwargs.get("font_path")
            if await aiopath.exists(font_path):
                LOGGER.info(f"Using kwargs font path (priority 1): {font_path}")
                return font_path
            else:
                LOGGER.warning(f"Kwargs font path not found: {font_path}")

        # 2. Check single font file from user settings (priority 2)
        single_font_path = user_dict.get("VT_HARDSUB_FONT_PATH")
        if single_font_path and await aiopath.exists(single_font_path):
            LOGGER.info(f"Using single font file (priority 2): {single_font_path}")
            return single_font_path
        elif single_font_path:
            LOGGER.warning(f"Single font file not found: {single_font_path}")
            # Clear stale single font reference if file no longer exists
            LOGGER.info(
                f"Clearing stale single font reference for user {self.listener.user_id}"
            )
            user_dict.pop("VT_HARDSUB_FONT_PATH", None)

        # 3. Fall back to system default font path from config
        config_font_path = getattr(Config, "HARDSUB_FONT_PATH", "")
        if config_font_path and await aiopath.exists(config_font_path):
            LOGGER.info(f"Using config font path: {config_font_path}")
            return config_font_path
        elif config_font_path:
            LOGGER.warning(f"Config font path not found: {config_font_path}")

        # 4. No custom font found, return None to use system font
        LOGGER.info("No custom font found, will use system font name")
        return None

    async def _queue(self, update: bool = False):
        if not self._metadata:
            return
        add_to_queue, event = await check_running_tasks(self.listener)
        if add_to_queue:
            LOGGER.info("Added to Queue/Download: %s", self.listener.name)
            async with task_dict_lock:
                task_dict[self.listener.mid] = QueueStatus(
                    self.listener, self._gid, "dl"
                )
            await self.listener.on_download_start()
            if update:
                await send_status_message(self.listener.message)
            await event.wait()
            if self.listener.is_cancelled:
                return
        if add_to_queue:
            LOGGER.info("Start Queued Video Tools: %s", self.listener.name)
        else:
            await self.listener.on_download_start()

    async def _run_multi_mode(self):
        await self._send_status()
        self.reply = None
        self.data = None
        self._org_path = self.path
        self._start_time = self.time = time()
        self._files.clear()

        # Check for auto-watermark before showing selector UI
        user_dict = getattr(self.listener, "user_dict", {}) or {}
        auto_watermark_enabled = user_dict.get(
            "VIDEO_WATERMARK_ENABLED", False
        ) or user_dict.get("VT_WATERMARK_ENABLED", False)

        # If watermark is enabled in settings, auto-enable watermark mode
        if auto_watermark_enabled:
            # Check if there's watermark content available (text or image)
            has_wm_text = bool(
                user_dict.get("VIDEO_WATERMARK_TEXT")
                or user_dict.get("VT_WATERMARK_TEXT")
            )
            has_wm_image = bool(
                user_dict.get("VIDEO_WATERMARK_IMAGE_PATH")
                or user_dict.get("VT_WATERMARK_IMAGE")
            )

            # If watermark is enabled but no content is set, provide default text
            if not has_wm_text and not has_wm_image:
                if not user_dict.get("VIDEO_WATERMARK_TEXT"):
                    user_dict["VIDEO_WATERMARK_TEXT"] = "Mirror Hunter Bot"
                    has_wm_text = True

            if has_wm_text or has_wm_image:
                # Auto-set watermark mode with default settings
                kwargs = {}
                kwargs["wm_size"] = (
                    user_dict.get("VIDEO_WATERMARK_FONT_SIZE")
                    or user_dict.get("VT_WATERMARK_SIZE")
                    or 20
                )
                kwargs["wm_position"] = (
                    user_dict.get("VIDEO_WATERMARK_POSITION")
                    or user_dict.get("VT_WATERMARK_POSITION")
                    or "main_w-overlay_w-5:main_h-overlay_h-5"
                )
                self.listener.video_mode = ["watermark", None, False, kwargs]
                LOGGER.info(
                    f"Auto-enabled watermark mode from user settings for {self.path}"
                )
                return await self.execute()

        # Otherwise, show the selector UI as normal
        self.listener.video_mode = await SelectMode(self.listener).get_buttons()
        if not self.listener.video_mode:
            return self.path
        return await self.execute()

    async def execute(self):
        self._is_dir = await aiopath.isdir(self.path)

        # Handle case where video_mode might be None (when not using -vt)
        if not self.listener.video_mode:
            self.mode, self.listener.name, self._multi_mode, kwargs = (
                None,
                None,
                False,
                {},
            )
        else:
            self.mode, self.listener.name, self._multi_mode, kwargs = (
                self.listener.video_mode
            )

        # Enhanced automatic processing: Apply watermark when enabled even without -vt
        user_dict = getattr(self.listener, "user_dict", {}) or {}
        auto_watermark_enabled = user_dict.get(
            "VIDEO_WATERMARK_ENABLED", False
        ) or user_dict.get("VT_WATERMARK_ENABLED", False)

        # If no mode is selected but watermark is enabled, automatically enable watermark mode
        if not self.mode and auto_watermark_enabled:
            # Check if there's watermark content available (text or image)
            has_wm_text = bool(
                user_dict.get("VIDEO_WATERMARK_TEXT")
                or user_dict.get("VT_WATERMARK_TEXT")
            )
            has_wm_image = bool(
                user_dict.get("VIDEO_WATERMARK_IMAGE_PATH")
                or user_dict.get("VT_WATERMARK_IMAGE")
            )

            # If watermark is enabled but no content is set, provide default text
            if not has_wm_text and not has_wm_image:
                # Set default watermark text when enabled but no content specified
                if not user_dict.get("VIDEO_WATERMARK_TEXT"):
                    user_dict["VIDEO_WATERMARK_TEXT"] = "Mirror Hunter Bot"
                    has_wm_text = True

            if has_wm_text or has_wm_image:
                self.mode = "watermark"
                if not kwargs:
                    kwargs = {}
                # Use settings from user preferences for auto watermark
                if not kwargs.get("wm_size"):
                    kwargs["wm_size"] = (
                        user_dict.get("VIDEO_WATERMARK_FONT_SIZE")
                        or user_dict.get("VT_WATERMARK_SIZE")
                        or 20
                    )
                if not kwargs.get("wm_position"):
                    kwargs["wm_position"] = (
                        user_dict.get("VIDEO_WATERMARK_POSITION")
                        or user_dict.get("VT_WATERMARK_POSITION")
                        or "main_w-overlay_w-5:main_h-overlay_h-5"
                    )
                LOGGER.info(
                    f"Auto-enabled watermark mode for {self.path} (watermark settings enabled)"
                )

        # If still no mode, return original path (no processing needed)
        if not self.mode:
            return self._org_path

        # Prefill convert quality when provided by listener (auto mode)
        if self.mode == "convert" and hasattr(self.listener, "video_convert_prefill"):
            self.data = getattr(self.listener, "video_convert_prefill")
        if not self._metadata and self.mode in Config.DISABLE_MULTI_VIDTOOLS:
            if path := await self._get_video():
                self.path = path
            else:
                return self._org_path
        if self._metadata:
            if not self.listener.name:
                self.listener.name = get_url_name(self.path)
            if not self.listener.name.upper().endswith(("MP4", "MKV")):
                self.listener.name += ".mkv"
            try:
                self.listener.size = int(self._metadata[1]["size"])
            except Exception:
                self.listener.is_cancelled = True
                await self.listener.on_download_error("Invalid data, check the link!")
                return

        try:
            match self.mode:
                case "vid_vid":
                    self.path = await self._merge_vids()
                case "vid_aud":
                    self.path = await self._merge_audios()
                case "vid_sub":
                    self.path = await self._merge_subtitles(**kwargs)
                case "hardsub":
                    self.path = await self._process_hardsub(**kwargs)
                case "trim":
                    self.path = await self._vid_trimmer(**kwargs)
                case "speed":
                    self.path = await self._vid_speed(**kwargs)
                case "watermark":
                    self.path = await self._vid_marker(**kwargs)
                case "compress":
                    self.path = await self._vid_compress(**kwargs)
                case "subsync":
                    self.path = await self._subsync(**kwargs)
                case "rmstream":
                    self.path = await self._rm_stream()
                case "extract":
                    self.path = await self._vid_extract()
                case "swapstream":  # Aliased to reordertracks by selector.py
                    self.path = await self._reorder_tracks()
                case "reordertracks":  # New mode for direct reordering
                    self.path = await self._reorder_tracks()
                case "intro_sub":
                    self.path = await self._intro_sub(**kwargs)
                case "multi_res":
                    self.path = await self._multi_res_encode(**kwargs)
                case _:
                    self.path = await self._vid_convert(**kwargs)
        except Exception as e:
            LOGGER.error(e, exc_info=True)
            self.path = self._org_path

        if self._multi_mode:
            return await self._run_multi_mode()

        return self.path

    async def _send_status(self, status: str = "wait"):
        async with task_dict_lock:
            task_dict[self.listener.mid] = FFMpegStatus(
                self.listener, self, self._gid, status
            )
        if self._metadata and status == "wait":
            await send_status_message(self.listener.message)

    async def _get_files(self):
        """Get video/audio files for processing, filtering out unsupported formats."""
        file_list = []

        if self._metadata:
            file_list.append(self.path)
        elif await aiopath.isfile(self.path):
            # Check format support first
            format_check = self._is_supported_media_format(self.path, video_only=False)
            if format_check is False:
                # Explicitly unsupported, skip
                LOGGER.info(f"Skipping file with unsupported format: {self.path}")
                return file_list
            # If format_check is True or None, proceed with document type check
            if (await get_document_type(self.path))[0]:
                file_list.append(self.path)
        else:
            for dirpath, _, files in await sync_to_async(walk, self.path):
                for file in natsorted(files):
                    fpath = ospath.join(dirpath, file)
                    fname_upper = file.upper()
                    # Robustly skip SAMPLE files (e.g., SAMPLE.mkv, sample.mp4, or a file just named SAMPLE)
                    if (
                        fpath in self._unwanted_files
                        or fname_upper.startswith("SAMPLE.")
                        or fname_upper == "SAMPLE"
                    ):
                        continue
                    # Check format support first
                    format_check = self._is_supported_media_format(
                        fpath, video_only=False
                    )
                    if format_check is False:
                        # Explicitly unsupported, skip
                        continue
                    # If format_check is True or None, proceed with document type check
                    if (await get_document_type(fpath))[0]:
                        file_list.append(fpath)
        return file_list

    async def _get_video(self):
        """Get a single video file for processing, filtering out unsupported formats."""
        if not self._is_dir:
            # Use video_only=True since audio files are not considered videos
            format_check = self._is_supported_media_format(self.path, video_only=True)
            if format_check is False:
                LOGGER.info(f"Skipping file with unsupported video format: {self.path}")
                return None
            if (await get_document_type(self.path))[0]:
                return self.path
        for dirpath, _, files in await sync_to_async(walk, self.path):
            for file in natsorted(files):
                fpath = ospath.join(dirpath, file)
                fname_upper = file.upper()
                # Robustly skip SAMPLE files
                if (
                    fpath in self._unwanted_files
                    or fname_upper.startswith("SAMPLE.")
                    or fname_upper == "SAMPLE"
                ):
                    continue
                # Check format support (video only)
                format_check = self._is_supported_media_format(fpath, video_only=True)
                if format_check is False:
                    continue
                if (await get_document_type(fpath))[0]:
                    return fpath

    async def _final_path(self, outfile: str = ""):
        if self._metadata:
            self._org_path = outfile or self.outfile
        else:
            # If a new outfile was produced by the operation, prefer it
            if outfile and await aiopath.exists(outfile):
                self._org_path = outfile
            elif self.outfile and await aiopath.exists(self.outfile):
                self._org_path = self.outfile
            scan_dir = (
                self._org_path if self._is_dir else ospath.split(self._org_path)[0]
            )
            for dirpath, _, files in await sync_to_async(walk, scan_dir):
                for file in files:
                    if file.endswith(tuple(self.listener.excluded_extensions)):
                        await clean_target(ospath.join(dirpath, file))

            all_files = []
            for dirpath, _, files in await sync_to_async(walk, scan_dir):
                all_files.extend((dirpath, file) for file in files)
            if len(all_files) == 1:
                self._org_path = ospath.join(*all_files[0])

        return self._org_path

    async def _name_base_dir(self, path: str, info: str = "", multi: bool = False):
        base_dir, file_name = ospath.split(path)
        if not self.listener.name or multi:
            if info:
                if await aiopath.isfile(path):
                    file_name = file_name.rsplit(".", 1)[0]
                file_name += f"_{info}.mkv"
            self.listener.name = file_name
        if not self.listener.name.upper().endswith(("MP4", "MKV")):
            self.listener.name += ".mkv"
        return base_dir if await aiopath.isfile(path) else path

    async def _run_cmd(self, cmd: list[str], status: str = "prog"):
        await self._send_status(status)
        if status == "sync":
            self.listener.subproc = await _create_memory_aware_subprocess(
                *cmd, max_retries=2, wait_for_resources=True
            )
            if not self.listener.subproc:
                raise RuntimeError("Failed to create subprocess for sync command")
            code = await self.listener.subproc.wait()
        else:
            async with subprocess_lock:
                self.listener.subproc = await _create_memory_aware_subprocess(
                    *cmd,
                    stdout=PIPE,
                    stderr=PIPE,
                    max_retries=2,
                    wait_for_resources=True,
                )
            if not self.listener.subproc:
                raise RuntimeError("Failed to create subprocess for FFmpeg command")
            # If ffmpeg is invoked with -progress pipe:1, progress is emitted on stdout
            progress_mode = "pipe" if "-progress" in cmd else status
            _, code = await gather(
                self.progress(progress_mode), self.listener.subproc.wait()
            )
        if self.listener.is_cancelled:
            return
        if code == 0:
            if not self.listener.seed:
                await gather(*[clean_target(file) for file in self._files])
            self._files.clear()
            return True
        if code != -9:
            # Do not delete outfile on failure if size is non-zero; keep logs
            try:
                if await aiopath.exists(self.outfile):
                    from ..ext_utils.files_utils import get_path_sizee as _gps

                    if (await _gps(self.outfile)) == 0:
                        await clean_target(self.outfile)
            except Exception:
                pass
            err_stderr = decode_output(await self.listener.subproc.stderr.read())
            err_stdout = decode_output(await self.listener.subproc.stdout.read())
            error = (
                "Failed to sync the subtitle!"
                if status == "sync"
                else (err_stderr or err_stdout or "Unknown ffmpeg error")
            )
            LOGGER.error(
                "%s. Failed to %s: %s\nCommand: %s",
                error,
                videos_tools_mode[self.mode],
                self.outfile,
                cmd,
            )
            self._files.clear()

    async def _vid_extract(self):
        if file_list := await self._get_files():
            if self._metadata:
                base_dir = ospath.join(
                    self.listener.dir, self.listener.name.split(".", 1)[0]
                )
                await makedirs(base_dir, exist_ok=True)
                streams = self._metadata[0]
            else:
                main_video = file_list[0]
                base_dir = self.listener.dir
                await makedirs(base_dir, exist_ok=True)
                await self._name_base_dir(main_video, "Extract", len(file_list) > 1)
                (streams, _), self.listener.size = await gather(
                    get_meta_video(main_video),
                    get_path_size(main_video),
                )
            await gather(self._send_status(), self.extra_buttons(streams))
        else:
            return self._org_path

        await self._queue()
        if self.listener.is_cancelled:
            return

        if not self.data or "key" not in self.data:
            LOGGER.warning(
                "Aborting video stream extraction: No stream selection data found (e.g., timeout or cancelled before selection)."
            )
            return self._org_path

        if "extension" not in self.data:
            LOGGER.warning(
                "Stream extraction extension data not found. Attempting to use defaults."
            )
            default_extensions = [
                "aac",
                "srt",
                "mkv",
            ]
            if (
                hasattr(self, "extension")
                and isinstance(self.extension, list)
                and len(self.extension) == 3
                and all(isinstance(ext, str) for ext in self.extension)
            ):
                LOGGER.info(f"Using extensions from self.extension: {self.extension}")
                self.data["extension"] = self.extension
            else:
                LOGGER.warning(
                    f"self.extension not suitable or not found. Using hardcoded defaults: {default_extensions}"
                )
                self.data["extension"] = default_extensions

        # Store original path before modifying _org_path
        original_file_path = self._org_path

        if await aiopath.isfile(self._org_path) or self._metadata:
            base_name = (
                self.listener.name if self._metadata else ospath.basename(self.path)
            )
            self._org_path = ospath.join(
                base_dir, f"{base_name.rsplit('.', 1)[0]} (EXTRACT)"
            )
            await makedirs(self._org_path, exist_ok=True)
            base_dir = self._org_path

        task_files = []
        for file in file_list:
            self.path = file
            if not self._metadata:
                self.listener.size = await get_path_size(self.path)
            base_name = (
                self.listener.name if self._metadata else ospath.basename(self.path)
            )
            base_name = base_name.rsplit(".", 1)[0]
            extension = dict(
                zip(["audio", "subtitle", "video"], self.data["extension"])
            )

            def _build_command(stream_data: dict, extension_str: str):
                cmd = [
                    BinConfig.FFMPEG_NAME,
                    "-hide_banner",
                    "-y",
                    "-i",
                    self.path,
                    "-map",
                    f"0:{stream_data['map']}",
                ]

                stream_type = stream_data["type"]
                codec_option_set = False

                if stream_type == "subtitle":
                    target_ext = extension_str.lower()
                    if target_ext == "srt":
                        cmd.extend(("-c:s", "srt"))
                        codec_option_set = True
                    elif target_ext == "ass":
                        cmd.extend(("-c:s", "ass"))
                        codec_option_set = True
                    elif target_ext == "vtt":
                        cmd.extend(("-c:s", "webvtt"))
                        codec_option_set = True
                elif stream_type == "audio":
                    target_ext = extension_str.lower()
                    if target_ext == "aac":
                        cmd.extend(("-c:a", "aac"))
                        codec_option_set = True
                    elif target_ext == "mp3":
                        cmd.extend(("-c:a", "libmp3lame"))
                        codec_option_set = True
                    elif target_ext == "ogg":
                        cmd.extend(("-c:a", "libvorbis"))
                        codec_option_set = True
                elif stream_type == "video":
                    cmd.extend(("-c:v", "copy"))
                    codec_option_set = True

                if not codec_option_set and self.data.get("fast_mode"):
                    cmd.extend(("-c", "copy"))

                cmd.append(self.outfile)
                return cmd

            keys = self.data["key"]
            if isinstance(keys, int):
                stream_data = self.data["stream"][keys]
                self.listener.name = f"{base_name}_{stream_data['lang'].upper()}.{extension[stream_data['type']]}"
                self.outfile = ospath.join(base_dir, self.listener.name)
                cmd = _build_command(stream_data, extension[stream_data["type"]])
                if await self._run_cmd(cmd):
                    task_files.append(file)
                else:
                    LOGGER.error(
                        f"Failed to extract stream {stream_data['map']} ({stream_data['type']}:{stream_data['lang']}) from file {file}"
                    )
                if self.listener.is_cancelled:
                    return
            else:
                ext_all = []
                for stream_data in self.data["stream"].values():
                    for key in keys:
                        if key == stream_data["type"]:
                            self.listener.name = f"{base_name}_{stream_data['lang'].upper()}.{extension[key]}"
                            self.outfile = ospath.join(base_dir, self.listener.name)
                            cmd = _build_command(stream_data, extension[key])
                            if await self._run_cmd(cmd):
                                ext_all.append(file)
                            if self.listener.is_cancelled:
                                return
                if any(ext_all):
                    task_files.append(file)
                else:
                    LOGGER.error(
                        f"Failed to extract any of the requested streams from file {file}"
                    )

        # Check if extraction was successful before cleaning source files
        extraction_successful = False
        if await aiopath.exists(self._org_path):
            # Check if the extraction directory has any content
            try:
                contents = await listdir(self._org_path)
                if contents:
                    extraction_successful = True
                    # Only clean source files if extraction was successful
                    await gather(*[clean_target(file) for file in task_files])
                else:
                    LOGGER.warning(
                        f"Extraction directory {self._org_path} is empty. Keeping original files."
                    )
            except Exception as e:
                LOGGER.error(f"Error checking extraction directory contents: {e}")

        if extraction_successful:
            return await self._final_path(self._org_path)
        else:
            # If extraction failed or directory is empty, return original path
            LOGGER.warning(
                "Extraction failed or produced no output. Returning original path."
            )
            return original_file_path

    async def _vid_convert(self, **kwargs):
        file_list = await self._get_files()
        multi = len(file_list) > 1
        if not file_list:
            return self._org_path

        # Check if user has enabled enhanced video encoding
        user_dict = getattr(self.listener, "user_dict", {}) or {}
        enhanced_encoding = user_dict.get("VIDEO_ENCODE_ENABLED", False)

        # Get codec override from video tools selector if available
        selector_codec = None
        if (
            isinstance(self.listener.video_mode, list)
            and len(self.listener.video_mode) >= 4
        ):
            ed = self.listener.video_mode[3] or {}
            selector_codec = ed.get("codec")

        # Extract enhanced convert settings from video tools selector
        enhanced_convert_settings = {}
        has_enhanced_settings = False

        if (
            hasattr(self, "data")
            and isinstance(self.data, dict)
            and "convert_settings" in self.data
        ):
            convert_settings = self.data["convert_settings"]
            enhanced_convert_settings = {
                "codec": convert_settings.get("codec", "copy"),
                "quality": convert_settings.get("quality", "original"),
                "preset": convert_settings.get("preset", "medium"),
                "crf": convert_settings.get("crf", "23"),
                "bitrate": convert_settings.get("bitrate", "auto"),
                "multi_resolution": convert_settings.get("multi_resolution", False),
                "resolution_list": convert_settings.get(
                    "resolution_list", "1080p,720p,480p"
                ),
                "multi_zip": convert_settings.get("multi_zip", False),
                "target_resolution": convert_settings.get("target_resolution"),
            }

            # Check if any enhanced settings differ from defaults
            has_enhanced_settings = any(
                v != default
                for v, default in [
                    (enhanced_convert_settings["codec"], "copy"),
                    (enhanced_convert_settings["quality"], "original"),
                    (enhanced_convert_settings["preset"], "medium"),
                    (enhanced_convert_settings["crf"], "23"),
                    (enhanced_convert_settings["bitrate"], "auto"),
                    (enhanced_convert_settings["multi_resolution"], False),
                ]
            )

            if has_enhanced_settings:
                enhanced_encoding = True
                LOGGER.info(
                    f"Enhanced convert settings detected: {enhanced_convert_settings}"
                )

                # For backward compatibility: if we have a target_resolution, also set legacy data format
                if enhanced_convert_settings.get("target_resolution"):
                    # Keep both formats for maximum compatibility
                    legacy_data = enhanced_convert_settings["target_resolution"]
                    LOGGER.info(f"Setting legacy data format: {legacy_data}")

        # Handle legacy string data format (backward compatibility)
        elif hasattr(self, "data") and isinstance(self.data, str):
            # This is the old format, keep as is
            LOGGER.info(f"Legacy convert data format detected: {self.data}")

        if self._metadata:
            base_dir = self.listener.dir
            await makedirs(base_dir, exist_ok=True)
            streams = self._metadata[0]
        else:
            main_video = file_list[0]
            base_dir = self.listener.dir
            await makedirs(base_dir, exist_ok=True)
            await self._name_base_dir(main_video, "Convert", len(file_list) > 1)
            (streams, _), self.listener.size = await gather(
                get_meta_video(main_video),
                get_path_size(main_video),
            )
            # Ensure output filename differs from input when auto mode prefilled name didn't change
            try:
                orig_base = ospath.basename(main_video)
                if self.listener.name == orig_base:
                    name_no_ext = orig_base.rsplit(".", 1)[0]
                    # Use enhanced settings for filename suffix if available
                    if enhanced_convert_settings.get("target_resolution"):
                        qual = enhanced_convert_settings["target_resolution"]
                    else:
                        qual = (
                            str(self.data)
                            if self.data and not isinstance(self.data, dict)
                            else ""
                        )
                    suffix = f"_CONVERT_{qual}" if qual else "_CONVERT"
                    self.listener.name = f"{name_no_ext}{suffix}.mkv"
            except Exception:
                pass
        auto_mode = kwargs.get("auto", False)
        if not (auto_mode and self.data):
            await gather(self._send_status(), self.extra_buttons(streams))
            await self._queue()
            if self.listener.is_cancelled:
                return
            if not self.data:
                return self._org_path
        self.outfile = self._org_path
        crf, bitrate, bitdepth, preset, audio_bitrate = (
            kwargs.get("crf") or getattr(Config, "FFMPEG_CRF", 23),
            kwargs.get("bitrate"),
            kwargs.get("bitdepth"),
            kwargs.get("preset") or "medium",
            _normalize_audio_bitrate(kwargs.get("audio_bitrate") or "128k"),
        )

        # Disable post-download advanced convert; keep simple convert flow
        if False and enhanced_encoding:
            enhanced_kwargs = kwargs.copy()
            if enhanced_convert_settings:
                if enhanced_convert_settings.get("codec") != "copy":
                    enhanced_kwargs["codec"] = enhanced_convert_settings["codec"]
                if enhanced_convert_settings.get("quality") != "original":
                    enhanced_kwargs["quality"] = enhanced_convert_settings["quality"]
                if enhanced_convert_settings.get("preset") != "medium":
                    enhanced_kwargs["preset"] = enhanced_convert_settings["preset"]
                if enhanced_convert_settings.get("crf") != "23":
                    enhanced_kwargs["crf"] = enhanced_convert_settings["crf"]
                if enhanced_convert_settings.get("bitrate") != "auto":
                    enhanced_kwargs["bitrate"] = enhanced_convert_settings["bitrate"]
                if enhanced_convert_settings.get("multi_resolution"):
                    enhanced_kwargs["multi_resolution"] = True
                    enhanced_kwargs["resolution_list"] = enhanced_convert_settings.get(
                        "resolution_list", "1080p,720p,480p"
                    )
                    enhanced_kwargs["multi_zip"] = enhanced_convert_settings.get(
                        "multi_zip", False
                    )
                    self.mode = "multi_res"
                    return await self._multi_res_encode(**enhanced_kwargs)

        # Set mode for regular conversion to ensure proper status display
        self.mode = "convert"

        any_successful = False
        for file in file_list:
            self.path = file
            # Extract quality key from self.data (handle both dict and string cases)
            if isinstance(self.data, dict):
                raw_quality = self.data.get("convert_settings", {}).get(
                    "quality", "original"
                )
                # Ensure quality is a string (handle nested dicts or other types)
                quality_key = (
                    str(raw_quality)
                    if raw_quality and not isinstance(raw_quality, dict)
                    else "original"
                )
                data_str = (
                    quality_key if quality_key != "original" else "1080p"
                )  # Default fallback
            else:
                quality_key = str(self.data) if self.data else "original"
                data_str = quality_key if quality_key != "original" else "1080p"

            if not self._metadata:
                _, self.listener.size = await gather(
                    self._name_base_dir(self.path, f"Convert-{data_str}", multi),
                    get_path_size(self.path),
                )
            self.outfile = ospath.join(base_dir, self.listener.name)
            self._files.append(self.path)

            # Enforce output extension based on selected target format
            target_fmt = (
                self.data.get("convert_settings", {}).get("format")
                if isinstance(self.data, dict)
                else None
            )
            # Fallback to selector extra_data if available via listener (selector stores in video_mode kwargs)
            if (
                not target_fmt
                and isinstance(self.listener.video_mode, (list, tuple))
                and len(self.listener.video_mode) >= 4
            ):
                vm_kwargs = self.listener.video_mode[3] or {}
                target_fmt = vm_kwargs.get("format")
            if target_fmt:
                try:
                    base_no_ext = self.listener.name.rsplit(".", 1)[0]
                    self.listener.name = f"{base_no_ext}.{target_fmt.lower()}"
                    self.outfile = ospath.join(base_dir, self.listener.name)
                except Exception:
                    pass

            # Determine if scaling is needed; only add -vf when scaling is requested
            apply_scaling = quality_key in self._quality
            if apply_scaling:
                scale_filter = f"scale={self._quality[quality_key]}:-2"

            cmd = [
                BinConfig.FFMPEG_NAME,
                "-hide_banner",
                "-y",
                "-threads",
                str(_ff_threads()),  # Memory optimization: limit threads
                "-i",
                self.path,
            ]
            if apply_scaling:
                cmd.extend(["-vf", scale_filter])

            # Add video codec and preset - use selector override or user settings
            user_codec = selector_codec or user_dict.get("VIDEO_CONVERT_CODEC", "copy")
            if user_codec == "copy":
                # If scaling is applied, we cannot copy the video stream; fall back to libx264
                if apply_scaling:
                    cmd.extend(("-c:v", "libx264"))
                    if preset:
                        cmd.extend(("-preset", preset))
                    if crf:
                        cmd.extend(("-crf", str(crf)))
                else:
                    cmd.extend(("-c:v", "copy"))
            elif user_codec == "x264":
                cmd.extend(("-c:v", "libx264"))
                # Only add preset and crf when encoding (not copying)
                if preset:
                    cmd.extend(("-preset", preset))
                if crf:
                    cmd.extend(("-crf", str(crf)))
            elif user_codec == "x265":
                cmd.extend(("-c:v", "libx265"))
                # Only add preset and crf when encoding (not copying)
                if preset:
                    cmd.extend(("-preset", preset))
                if crf:
                    cmd.extend(("-crf", str(crf)))
            elif user_codec == "auto":
                # Auto selection based on output format and quality
                cmd.extend(("-c:v", "libx264"))  # Default to x264 for compatibility
                # Only add preset and crf when encoding (not copying)
                if preset:
                    cmd.extend(("-preset", preset))
                if crf:
                    cmd.extend(("-crf", str(crf)))
            else:
                # Fallback to x264 for unknown codecs
                cmd.extend(("-c:v", "libx264"))
                # Only add preset and crf when encoding (not copying)
                if preset:
                    cmd.extend(("-preset", preset))
                if crf:
                    cmd.extend(("-crf", str(crf)))
            if bitdepth:
                cmd.extend(("-pix_fmt", bitdepth))
            if bitrate:
                bitrate = f"{bitrate}k"
                cmd.extend(
                    (
                        "-b:v",
                        bitrate,
                        "-minrate",
                        bitrate,
                        "-maxrate",
                        bitrate,
                        "-bufsize",
                        bitrate,
                    )
                )
            audio_codec_params = []
            if audio_bitrate and audio_bitrate != "copy":
                # Re-encode audio with specified bitrate
                audio_codec_params.extend(["-c:a", "aac", "-b:a", audio_bitrate])
            else:
                # Copy audio without re-encoding
                audio_codec_params.extend(["-c:a", "copy"])

            cmd.extend(audio_codec_params)
            # Apply container-specific subtitle handling based on selected format
            target_fmt = (
                self.data.get("convert_settings", {}).get("format")
                if isinstance(self.data, dict)
                else None
            ) or (
                self.extra_data.get("format") if hasattr(self, "extra_data") else None
            )
            # Fallback to outfile extension if format not explicitly set
            if not target_fmt:
                try:
                    _, ext = ospath.splitext(self.outfile)
                    target_fmt = (ext or "").lstrip(".")
                except Exception:
                    target_fmt = ""
            target_fmt = (target_fmt or "").lower()
            if target_fmt == "mp4":
                # MP4: map all, H.264 + yuv420p, AAC audio, mov_text subs, faststart
                cmd.extend(
                    [
                        "-map",
                        "0",
                        "-c:s",
                        "mov_text",
                        "-movflags",
                        "+faststart",
                        "-pix_fmt",
                        "yuv420p",
                    ]
                )
                # Enforce AAC audio for compatibility
                safe_ab = _normalize_audio_bitrate(audio_bitrate or "128k")
                if safe_ab == "copy":
                    cmd.extend(["-c:a", "copy"])  # unlikely for MP4, but safe
                else:
                    cmd.extend(["-c:a", "aac", "-b:a", safe_ab])  # last wins
            elif target_fmt == "mkv":
                # MKV: map all and copy subs; any codec is fine
                cmd.extend(["-map", "0", "-c:s", "copy"])
            elif target_fmt == "webm":
                # WEBM: map all, VP9 video, Opus audio, WebVTT subs
                cmd.extend(["-map", "0", "-c:s", "webvtt"])
                # Force VP9 for video
                cmd.extend(["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", str(crf or 33)])
                # Force Opus for audio
                cmd.extend(["-c:a", "libopus", "-b:a", "96k"])
            elif target_fmt in ("avi", "m4v"):
                # AVI/M4V have different needs; split handling
                if target_fmt == "avi":
                    # AVI: prefer MPEG-4 Part 2 (Xvid), MP3 audio, no subs
                    cmd.extend(
                        [
                            "-map",
                            "0:v",
                            "-map",
                            "0:a:0",
                            "-sn",
                            "-c:v",
                            "mpeg4",
                            "-vtag",
                            "XVID",
                            "-qscale:v",
                            "5",
                            "-c:a",
                            "libmp3lame",
                            "-b:a",
                            "128k",
                            "-pix_fmt",
                            "yuv420p",
                        ]
                    )
                else:
                    # M4V: treat like MP4
                    cmd.extend(
                        [
                            "-map",
                            "0",
                            "-c:s",
                            "mov_text",
                            "-movflags",
                            "+faststart",
                            "-pix_fmt",
                            "yuv420p",
                        ]
                    )
                    safe_ab = _normalize_audio_bitrate(audio_bitrate or "128k")
                    if safe_ab == "copy":
                        cmd.extend(["-c:a", "copy"])  # unlikely for M4V, but safe
                    else:
                        cmd.extend(["-c:a", "aac", "-b:a", safe_ab])  # ensure AAC
            elif target_fmt == "mov":
                # MOV: map all, mov_text subs, AAC audio, yuv420p, faststart
                cmd.extend(
                    [
                        "-map",
                        "0",
                        "-c:s",
                        "mov_text",
                        "-movflags",
                        "+faststart",
                        "-pix_fmt",
                        "yuv420p",
                    ]
                )
                cmd.extend(
                    ["-c:a", "aac", "-b:a", audio_bitrate or "128k"]
                )  # ensure AAC
            elif target_fmt == "flv":
                # FLV: H.264 + yuv420p, AAC audio, first audio stream only, no subs
                cmd.extend(
                    [
                        "-map",
                        "0:v",
                        "-map",
                        "0:a:0",
                        "-sn",
                        "-c:v",
                        "libx264",
                        "-pix_fmt",
                        "yuv420p",
                    ]
                )
                safe_ab = _normalize_audio_bitrate(audio_bitrate or "128k")
                if safe_ab == "copy":
                    cmd.extend(["-c:a", "copy"])  # MOV compatibility
                else:
                    cmd.extend(["-c:a", "aac", "-b:a", safe_ab])
                safe_ab = _normalize_audio_bitrate(audio_bitrate or "128k")
                if safe_ab == "copy":
                    cmd.extend(
                        ["-c:a", "copy"]
                    )  # FLV generally expects AAC; copy as fallback
                else:
                    cmd.extend(["-c:a", "aac", "-b:a", safe_ab])
            else:
                # Default: map all, copy subs
                cmd.extend(["-map", "0", "-c:s", "copy"])  # Default

            cmd.append(self.outfile)
            if await self._run_cmd(cmd):
                any_successful = True
            if self.listener.is_cancelled:
                return

        if multi:
            return base_dir if any_successful else self._org_path
        elif any_successful:
            return self.outfile
        return self._org_path

    async def _enhanced_vid_convert(
        self,
        file_list,
        base_dir,
        multi,
        crf,
        bitrate,
        bitdepth,
        user_dict,
        audio_bitrate=None,
        **kwargs,
    ):
        """Enhanced video conversion using advanced FFmpeg capabilities"""
        # Get selector overrides from kwargs (from video tools selector)
        selector_preset = kwargs.get("preset")
        selector_crf = kwargs.get("crf")
        selector_audio_bitrate = kwargs.get("audio_bitrate")
        selector_quality = kwargs.get("quality")
        selector_codec = kwargs.get("codec")  # Get codec from selector

        # Get user encoding settings with selector overrides taking priority
        preset = selector_preset or user_dict.get("VIDEO_ENCODE_PRESET", "medium")
        quality = selector_quality or user_dict.get("VIDEO_ENCODE_QUALITY", "Original")

        # Get codec setting with selector override taking priority
        user_codec = selector_codec or user_dict.get("VIDEO_ENCODE_CODEC", "x264")

        # Ensure CRF is a valid numeric value
        raw_crf = selector_crf or user_dict.get("VIDEO_ENCODE_CRF", crf)
        try:
            user_crf = int(raw_crf) if raw_crf != "Original" else crf
        except (ValueError, TypeError):
            user_crf = crf  # Use default if invalid
        final_audio_bitrate = (
            selector_audio_bitrate
            or audio_bitrate
            or user_dict.get("VIDEO_ENCODE_AUDIO_BITRATE", "128k")
        )
        multi_resolution = user_dict.get("VIDEO_ENCODE_MULTI_RESOLUTION", False)
        resolution_list = user_dict.get(
            "VIDEO_ENCODE_RESOLUTION_LIST", "1080p,720p,480p"
        )
        multi_zip = user_dict.get("VIDEO_ENCODE_MULTI_ZIP", False)

        # Set mode for proper status display - this fixes the "Extracting" status issue
        if multi_resolution:
            self.mode = "multi_res"
        else:
            self.mode = "convert"

        LOGGER.info(
            f"Enhanced video encoding - preset={preset}, quality={quality}, crf={user_crf}, audio_bitrate={final_audio_bitrate}, multi_res={multi_resolution}"
        )

        quality_settings = get_quality_settings()

        for file in file_list:
            self.path = file
            if not self._metadata:
                _, self.listener.size = await gather(
                    self._name_base_dir(
                        self.path, f"Enhanced-Convert-{quality}", multi
                    ),
                    get_path_size(self.path),
                )

            # Create FFmpeg encoder helper for progress tracking
            self.outfile = ospath.join(base_dir, self.listener.name)

            # Handle multi-resolution encoding
            if multi_resolution:
                await self._process_multi_resolution_encoding(
                    file,
                    base_dir,
                    preset,
                    user_crf,
                    final_audio_bitrate,
                    resolution_list,
                    multi_zip,
                    quality_settings,
                    user_dict,
                )
            else:
                # Standard single resolution encoding
                encoder_helper = FFmpegEncoderHelper(self.path, self.outfile)
                encoder_helper.set_quality_preset(
                    quality, preset, user_crf, final_audio_bitrate
                )

                # Standard encoding process...
                await self._run_standard_encoding(
                    encoder_helper, quality, quality_settings
                )

            if self.listener.is_cancelled:
                return

        return await self._final_path()

    async def _process_multi_resolution_encoding(
        self,
        file_path,
        base_dir,
        preset,
        crf,
        audio_bitrate,
        resolution_list,
        multi_zip,
        quality_settings,
        user_dict=None,
    ):
        """Process multi-resolution encoding with optional ZIP packaging"""
        if user_dict is None:
            user_dict = getattr(self.listener, "user_dict", {}) or {}

        resolutions = [res.strip() for res in resolution_list.split(",") if res.strip()]
        encoded_files = []

        # Get user codec setting for encoding
        user_codec = user_dict.get("VIDEO_ENCODE_CODEC", "x264")

        LOGGER.info(
            f"Starting multi-resolution encoding for resolutions: {resolutions}"
        )

        for resolution in resolutions:
            if self.listener.is_cancelled:
                return

            # Create resolution-specific output file
            base_name = ospath.splitext(self.listener.name)[0]
            ext = ospath.splitext(self.listener.name)[1] or ".mp4"
            res_output = ospath.join(base_dir, f"{base_name}_{resolution}{ext}")

            # Create encoder helper for this resolution
            encoder_helper = FFmpegEncoderHelper(file_path, res_output)
            encoder_helper.set_quality_preset(resolution, preset, crf, audio_bitrate)

            # Build FFmpeg command for this resolution
            # Determine video codec based on user settings
            if user_codec == "x265":
                video_codec = "libx265"
            elif user_codec == "x264":
                video_codec = "libx264"
            else:
                video_codec = "libx264"  # Default fallback

            cmd = [
                BinConfig.FFMPEG_NAME,
                "-hide_banner",
                "-loglevel",
                "error",
                "-progress",
                "pipe:1",
                "-y",
                "-threads",
                str(_ff_threads()),  # Memory optimization: limit threads
                "-i",
                file_path,
                "-c:v",
                video_codec,
                "-preset",
                preset,
                "-crf",
                str(crf),
                "-c:a",
                "aac",
                "-b:a",
                audio_bitrate,
            ]

            # Add resolution-specific scaling
            if resolution in quality_settings:
                settings = quality_settings[resolution]
                if "scale" in settings:
                    cmd.extend(["-vf", settings["scale"]])
                if "bitrate" in settings:
                    cmd.extend(["-b:v", settings["bitrate"]])

            cmd.extend(["-c:s", "copy", "-map", "0", res_output])

            LOGGER.info(f"Encoding {resolution} resolution...")
            await self._run_enhanced_cmd(cmd, encoder_helper)

            if ospath.exists(res_output):
                encoded_files.append(res_output)
                LOGGER.info(f"Successfully encoded {resolution}: {res_output}")

        # Handle ZIP packaging for multi-resolution files
        if multi_zip and len(encoded_files) > 1:
            await self._create_multi_resolution_zip(encoded_files, base_dir)

        # Update the output path to the first encoded file or ZIP
        if encoded_files:
            self.outfile = encoded_files[0]
            if multi_zip and len(encoded_files) > 1:
                zip_name = f"{ospath.splitext(self.listener.name)[0]}_multi_res.zip"
                self.outfile = ospath.join(base_dir, zip_name)

    async def _create_multi_resolution_zip(self, encoded_files, base_dir):
        """Create ZIP package for multi-resolution encoded files"""
        zip_name = f"{ospath.splitext(self.listener.name)[0]}_multi_res.zip"
        zip_path = ospath.join(base_dir, zip_name)

        LOGGER.info(f"Creating multi-resolution ZIP: {zip_path}")

        cmd = ["7z", "a", "-tzip", "-mx=1", zip_path] + encoded_files

        try:
            async with subprocess_lock:
                proc = await _create_memory_aware_subprocess(
                    *cmd,
                    stdout=PIPE,
                    stderr=PIPE,
                    max_retries=2,
                    wait_for_resources=False,  # 7z compression doesn't need resource waiting
                )

                if not proc:
                    LOGGER.error("Failed to create subprocess for ZIP creation")
                    return None

                _, stderr = await proc.communicate()

                if proc.returncode != 0:
                    error_msg = stderr.decode("utf-8", "ignore")
                    LOGGER.error(f"ZIP creation failed: {error_msg}")
                    raise Exception(f"ZIP creation failed: {error_msg}")

                LOGGER.info(f"Multi-resolution ZIP created successfully: {zip_path}")

                # Clean up individual files after zipping
                for file_path in encoded_files:
                    try:
                        await remove(file_path)
                        LOGGER.info(f"Cleaned up individual file: {file_path}")
                    except Exception as e:
                        LOGGER.warning(f"Failed to clean up {file_path}: {e}")

        except Exception as e:
            LOGGER.error(f"Error creating multi-resolution ZIP: {e}")
            raise

    async def _run_standard_encoding(self, encoder_helper, quality, quality_settings):
        """Run standard single-resolution encoding"""
        # Get video info for duration and frame estimation
        try:
            duration = await get_video_duration_enhanced(self.path)
            if duration:
                encoder_helper.set_duration(duration)

            video_info = await get_video_info_enhanced(self.path)
            if video_info and "avg_frame_rate" in video_info:
                fps_parts = video_info["avg_frame_rate"].split("/")
                if len(fps_parts) == 2 and int(fps_parts[1]) > 0:
                    avg_fps = int(fps_parts[0]) / int(fps_parts[1])
                    if duration and avg_fps > 0:
                        encoder_helper.total_frames = int(duration * avg_fps)
        except Exception as e:
            LOGGER.warning(f"Could not get video info for enhanced encoding: {e}")

        self._files.append(self.path)

        # Build enhanced FFmpeg command with user codec settings
        # Determine video codec based on user settings
        if user_codec == "x265":
            video_codec = "libx265"
        elif user_codec == "x264":
            video_codec = "libx264"
        else:
            video_codec = "libx264"  # Default fallback

        cmd = [
            BinConfig.FFMPEG_NAME,
            "-hide_banner",
            "-loglevel",
            "error",
            "-progress",
            "pipe:1",
            "-y",
            "-threads",
            str(_ff_threads()),  # Memory optimization: limit threads
            "-i",
            self.path,
            "-c:v",
            video_codec,
            "-preset",
            encoder_helper.preset,
            "-crf",
            str(encoder_helper.crf),
            "-c:a",
            "aac",
            "-b:a",
            encoder_helper.audio_bitrate,
        ]

        # Add quality-specific video filters
        if quality in quality_settings and quality != "Original":
            settings = quality_settings[quality]
            if "scale" in settings:
                cmd.extend(["-vf", settings["scale"]])
            if "bitrate" in settings:
                cmd.extend(["-b:v", settings["bitrate"]])
            if "maxrate" in settings:
                cmd.extend(["-maxrate", settings["maxrate"]])
            if "bufsize" in settings:
                cmd.extend(["-bufsize", settings["bufsize"]])

                # Add subtitle and output mapping
                cmd.extend(["-c:s", "copy", "-map", "0", self.outfile])

        # Run enhanced command with progress tracking
        await self._run_enhanced_cmd(cmd, encoder_helper)

        return await self._final_path()

    async def _run_enhanced_cmd(self, cmd, encoder_helper):
        """Run FFmpeg command with enhanced progress tracking"""
        try:
            async with subprocess_lock:
                self.listener.subproc = await _create_memory_aware_subprocess(
                    *cmd,
                    stdout=PIPE,
                    stderr=PIPE,
                    max_retries=2,
                    wait_for_resources=True,
                )

            if not self.listener.subproc:
                LOGGER.error("Failed to create subprocess for enhanced FFmpeg command")
                return False

            # Process output for progress updates
            while True:
                line = await self.listener.subproc.stdout.readline()
                if not line:
                    break

                line_str = line.decode("utf-8", "ignore").strip()
                if line_str and any(
                    key in line_str for key in ["frame=", "time=", "speed=", "fps="]
                ):
                    encoder_helper.update_progress(line_str)

            # Wait for process completion
            await self.listener.subproc.wait()

            if self.listener.subproc.returncode != 0:
                stderr_data = await self.listener.subproc.stderr.read()
                error_msg = stderr_data.decode("utf-8", "ignore")
                LOGGER.error(f"Enhanced FFmpeg encoding failed: {error_msg}")
                raise Exception(f"Encoding failed: {error_msg}")

            LOGGER.info(f"Enhanced video encoding completed: {self.outfile}")

        except Exception as e:
            LOGGER.error(f"Error in enhanced video encoding: {e}")
            raise

    async def _rm_stream(self):
        file_list = await self._get_files()
        multi = len(file_list) > 1
        if not file_list:
            return self._org_path

        # Auto-apply from user settings: VT_AUDIO_REMOVE (e.g., "0,2")
        auto_remove = (self.listener.user_dict or {}).get("VT_AUDIO_REMOVE")
        if auto_remove:
            try:
                # Build data structure to mimic selector outcome
                # We need global stream indexes for audio tracks; map audio N to actual index later
                # Fetch streams for first file
                main_video = file_list[0]
                streams, _ = await get_meta_video(main_video)
                audio_indices_global = [
                    s.get("index") for s in streams if s.get("codec_type") == "audio"
                ]
                # Parse user-provided audio positions
                remove_positions = [
                    int(x.strip())
                    for x in str(auto_remove).split(",")
                    if x.strip().isdigit()
                ]
                # Compute sdata as global stream indexes to REMOVE
                sdata = []
                for pos in remove_positions:
                    if 0 <= pos < len(audio_indices_global):
                        sdata.append(audio_indices_global[pos])
                if sdata:
                    self.data = {
                        "stream": {s.get("index"): s for s in streams},
                        "sdata": sdata,
                    }
                    # Proceed directly to building commands below
            except Exception:
                pass

        if self._metadata:
            base_dir = self.listener.dir
            await makedirs(base_dir, exist_ok=True)
            streams = self._metadata[0]
        else:
            main_video = file_list[0]
            base_dir = self.listener.dir
            await makedirs(base_dir, exist_ok=True)
            await self._name_base_dir(main_video, "Remove", multi)
            (streams, _), self.listener.size = await gather(
                get_meta_video(main_video),
                get_path_size(main_video),
            )
            # Ensure output filename differs from input
            try:
                orig_base = ospath.basename(main_video)
                if self.listener.name == orig_base:
                    name_no_ext = orig_base.rsplit(".", 1)[0]
                    self.listener.name = f"{name_no_ext}_REMOVE.mkv"
            except Exception:
                pass
        if not getattr(self, "data", None):
            await gather(self._send_status(), self.extra_buttons(streams))
            await self._queue()
            if self.listener.is_cancelled:
                return
            if not self.data:
                return self._org_path

        self.outfile = self._org_path
        any_successful = False
        for file in file_list:
            self.path = file
            if not self._metadata:
                _, self.listener.size = await gather(
                    self._name_base_dir(self.path, "Remove", multi),
                    get_path_size(self.path),
                )
            key = self.data.get("key", "")
            self.outfile = ospath.join(base_dir, self.listener.name)
            self._files.append(self.path)
            cmd = [BinConfig.FFMPEG_NAME, "-hide_banner", "-y", "-i", self.path]
            # Check if we're removing audio streams and need to set default on first remaining audio
            # This is necessary when removing specific streams (not using key shortcuts like "audio" or "subtitle")
            # to ensure a default audio track is always available for playback
            need_audio_default = False
            first_remaining_audio_idx = None
            if key != "audio" and key != "subtitle":
                # When removing specific streams (neither all audio nor all subtitles)
                # check if any audio streams were removed
                removed_audio_streams = [
                    idx
                    for idx in self.data["sdata"]
                    if self.data["stream"].get(idx, {}).get("type") == "audio"
                ]
                if removed_audio_streams:
                    # Find first remaining audio stream to set as default
                    for idx in self.data["stream"]:
                        if (
                            idx not in self.data["sdata"]
                            and self.data["stream"].get(idx, {}).get("type") == "audio"
                        ):
                            first_remaining_audio_idx = idx
                            need_audio_default = True
                            break

            if key == "audio":
                cmd.extend(("-map", "0:v:?", "-map", "0:s:?"))
            elif key == "subtitle":
                cmd.extend(("-map", "0:v:?", "-map", "0:a:?"))
                # Set first audio as default when subtitles are removed
                cmd.extend(("-disposition:a:0", "default"))
            else:
                for x in self.data["stream"]:
                    if x not in self.data["sdata"]:
                        cmd.extend(("-map", f"0:{x}?"))

            # Set default disposition on first remaining audio if audio was removed
            if need_audio_default and first_remaining_audio_idx is not None:
                # Calculate output audio stream index (count audio streams before this one in output)
                output_audio_idx = 0
                for idx in sorted(self.data["stream"].keys()):
                    if (
                        idx not in self.data["sdata"]
                        and self.data["stream"].get(idx, {}).get("type") == "audio"
                    ):
                        if idx == first_remaining_audio_idx:
                            break
                        output_audio_idx += 1
                cmd.extend(
                    ("-disposition:a", "0")
                )  # Clear all audio dispositions first
                cmd.extend((f"-disposition:a:{output_audio_idx}", "default"))

            cmd.extend(("-c", "copy", self.outfile))
            ok = await self._run_cmd(cmd)
            if not ok:
                # Fallback remux: regenerate timestamps and normalize container if copy mapping fails
                remux_cmd = [
                    BinConfig.FFMPEG_NAME,
                    "-hide_banner",
                    "-y",
                    "-fflags",
                    "+genpts",
                    "-i",
                    self.path,
                ]
                if key == "audio":
                    remux_cmd.extend(("-map", "0:v:?", "-map", "0:s:?"))
                elif key == "subtitle":
                    remux_cmd.extend(("-map", "0:v:?", "-map", "0:a:?"))
                    # Set first audio as default when subtitles are removed
                    remux_cmd.extend(("-disposition:a:0", "default"))
                else:
                    for x in self.data["stream"]:
                        if x not in self.data["sdata"]:
                            remux_cmd.extend(("-map", f"0:{x}?"))

                # Set default disposition on first remaining audio if audio was removed
                if need_audio_default and first_remaining_audio_idx is not None:
                    output_audio_idx = 0
                    for idx in sorted(self.data["stream"].keys()):
                        if (
                            idx not in self.data["sdata"]
                            and self.data["stream"].get(idx, {}).get("type") == "audio"
                        ):
                            if idx == first_remaining_audio_idx:
                                break
                            output_audio_idx += 1
                    remux_cmd.extend(
                        ("-disposition:a", "0")
                    )  # Clear all audio dispositions first
                    remux_cmd.extend((f"-disposition:a:{output_audio_idx}", "default"))

                remux_cmd.extend(("-c", "copy", self.outfile))
                ok = await self._run_cmd(remux_cmd)
            if ok:
                any_successful = True
            if self.listener.is_cancelled:
                return

        if multi:
            return base_dir if any_successful else self._org_path
        elif any_successful:
            return self.outfile
        return self._org_path

    async def _vid_trimmer(self, start_time: str, end_time: str):
        await self._queue(True)
        if self.listener.is_cancelled:
            return
        self.outfile = self._org_path
        for file in (file_list := await self._get_files()):
            self.path = file
            if self._metadata:
                base_dir = self.listener.dir
                await makedirs(base_dir, exist_ok=True)
            else:
                base_dir = self.listener.dir
                await makedirs(base_dir, exist_ok=True)
                await self._name_base_dir(self.path, "Trim", len(file_list) > 1)
                self.listener.size = await get_path_size(self.path)
            self.outfile = ospath.join(base_dir, self.listener.name)
            self._files.append(self.path)
            cmd = [
                BinConfig.FFMPEG_NAME,
                "-hide_banner",
                "-y",
                "-i",
                self.path,
                "-ss",
                start_time,
                "-to",
                end_time,
                "-map",
                "0",
                "-c",
                "copy",
                self.outfile,
            ]
            await self._run_cmd(cmd)
            if self.listener.is_cancelled:
                return

        return await self._final_path()

    async def _vid_speed(self, speed_number: int, speed_type: str):
        await self._queue()
        if self.listener.is_cancelled:
            return
        self.outfile = self._org_path
        for file in (file_list := await self._get_files()):
            self.path = file
            if self._metadata:
                base_dir = self.listener.dir
                await makedirs(base_dir, exist_ok=True)
            else:
                base_dir = self.listener.dir
                await makedirs(base_dir, exist_ok=True)
                await self._name_base_dir(self.path, "Speed", len(file_list) > 1)
                self.listener.size = await get_path_size(self.path)
            self.outfile = ospath.join(base_dir, self.listener.name)
            self._files.append(self.path)

            video_speed, audio_speed = (
                (1 / speed_number, speed_number)
                if speed_type == "up"
                else (1 / speed_number, 1 / speed_number)
            )

            cmd = [
                BinConfig.FFMPEG_NAME,
                "-hide_banner",
                "-y",
                "-i",
                self.path,
                "-filter_complex",
                f"[0:v]setpts={video_speed}*PTS[v];[0:a]atempo={audio_speed}[a]",
                "-map",
                "[v]",
                "-map",
                "[a]",
                "-map",
                "0:s:?",
                "-c:s",
                "copy",
                self.outfile,
            ]
            await self._run_cmd(cmd)
            if self.listener.is_cancelled:
                return

        return await self._final_path()

    async def _subsync(self, sync_type: str = "sync_manual"):
        if not self._is_dir:
            return self._org_path
        self.listener.size = await get_path_size(self.path)
        list_files = natsorted(await listdir(self.path))
        if len(list_files) <= 1:
            return self._org_path
        sub_files, ref_files = [], []
        if sync_type == "sync_manual":
            index = 1
            self.data = {"list": {}, "final": {}}
            for file in list_files:
                # Consider videos as refs and common subtitle files as subs
                if (await get_document_type(ospath.join(self.path, file)))[
                    0
                ] or file.lower().endswith((".srt", ".ass", ".ssa", ".vtt", ".sub")):
                    self.data["list"].update({index: file})
                    index += 1
            if not self.data["list"]:
                return self._org_path
            await gather(self._send_status(), self.extra_buttons())

            if self.listener.is_cancelled:
                return
            if not self.data or not self.data["final"]:
                return self._org_path
            for key in self.data["final"].values():
                sub_files.append(ospath.join(self.path, key["file"]))
                ref_files.append(ospath.join(self.path, key["ref"]))
        else:
            for file in list_files:
                file_ = ospath.join(self.path, file)
                is_video, is_audio, _ = await get_document_type(file_)
                if is_video or is_audio:
                    ref_files.append(file_)
                elif file_.lower().endswith((".srt", ".ass", ".ssa", ".vtt", ".sub")):
                    sub_files.append(file_)

            if not sub_files:
                return self._org_path

            if not ref_files and len(sub_files) > 1:
                ref_files = list(filter(lambda x: (x, sub_files.remove(x)), sub_files))

            if not ref_files or not sub_files:
                return self._org_path

        for sub_file, ref_file in zip(sub_files, ref_files):
            self._files.extend((sub_file, ref_file))
            self.listener.size = await get_path_size(ref_file)
            self.listener.name = ospath.basename(sub_file)
            name, ext = ospath.splitext(sub_file)
            cmd = [
                "alass",
                "--allow-negative-timestamps",
                ref_file,
                sub_file,
                f"{name}_SYNC{ext}",
            ]
            await self._run_cmd(cmd, "sync")
            if self.listener.is_cancelled:
                return

        return await self._final_path(self._org_path)

    async def _vid_compress(self, **kwargs):
        # Get user settings for codec preferences
        user_dict = getattr(self.listener, "user_dict", {}) or {}

        # Get codec override from video tools selector if available
        selector_codec = None
        if (
            isinstance(self.listener.video_mode, list)
            and len(self.listener.video_mode) >= 4
        ):
            ed = self.listener.video_mode[3] or {}
            selector_codec = ed.get("codec")

        file_list = await self._get_files()
        multi = len(file_list) > 1
        if not file_list:
            return self._org_path

        if self._metadata:
            base_dir = self.listener.dir
            await makedirs(base_dir, exist_ok=True)
            streams = self._metadata[0]
        else:
            main_video = file_list[0]
            base_dir = self.listener.dir
            await makedirs(base_dir, exist_ok=True)
            await self._name_base_dir(main_video, "Compress", multi)
            (streams, _), self.listener.size = await gather(
                get_meta_video(main_video),
                get_path_size(main_video),
            )
        await gather(self._send_status(), self.extra_buttons(streams))
        await self._queue()
        if self.listener.is_cancelled:
            return
        if not isinstance(self.data, dict):
            return self._org_path

        # CPU limiting and memory management for video compression
        async with cpu_eater_lock:
            try:
                return await self._run_compress_with_cpu_limit(
                    file_list, multi, kwargs, user_dict, selector_codec
                )
            finally:
                gc.collect()  # Force garbage collection after compression

    async def _run_compress_with_cpu_limit(
        self, file_list, multi, kwargs, user_dict=None, selector_codec=None
    ):
        """Run compression with enhanced resource monitoring and CPU limiting"""
        from ..ext_utils.resource_monitor import (
            resource_monitor,
            should_skip_resource_intensive_task,
        )

        # Check if we should skip compression due to resource constraints
        if should_skip_resource_intensive_task("video_compression"):
            LOGGER.warning("Skipping video compression due to resource constraints")
            return self._org_path

        # Log resource status before compression
        resource_monitor.log_resource_status("before_video_compression")

        # Wait for resources if needed
        if not await resource_monitor.wait_for_resources(max_wait=60):
            LOGGER.warning(
                "Could not acquire sufficient resources for video compression"
            )
            # Continue but with more conservative settings

        base_dir = self.listener.dir if self._metadata else ospath.dirname(file_list[0])

        self.outfile = self._org_path
        quality, crf, bitrate, bitdepth, preset, audio_bitrate = (
            kwargs.get("quality"),
            kwargs.get("crf") or getattr(Config, "FFMPEG_CRF", 23),
            kwargs.get("bitrate"),
            kwargs.get("bitdepth"),
            kwargs.get("preset") or "medium",
            kwargs.get("audio_bitrate") or "192k",
        )

        # Adjust settings based on resource availability
        if resource_monitor.is_memory_high():
            LOGGER.info("High memory detected, using conservative compression settings")
            if preset in ["slow", "slower", "veryslow"]:
                preset = "fast"  # Use faster preset to reduce memory usage
            if (
                int(str(crf).split(".")[0]) < 28
            ):  # Ensure higher CRF for lower memory usage
                crf = 28
        for file in file_list:
            self.path = file
            if not self._metadata:
                _, self.listener.size = await gather(
                    self._name_base_dir(self.path, "Compress", multi),
                    get_path_size(self.path),
                )
            self.outfile = ospath.join(base_dir, self.listener.name)
            self._files.append(self.path)
            # Build compression command with user codec preferences
            user_codec = selector_codec or (
                user_dict.get("VIDEO_CONVERT_CODEC", "auto") if user_dict else "auto"
            )

            # Determine codec based on user settings
            if user_codec == "x264":
                video_codec = "libx264"
                default_preset = Config.LIB264_PRESET
                default_pixfmt = "yuv420p"
            elif user_codec == "copy":
                # For compression, we can't use copy, so fall back to x265 for better compression
                video_codec = "libx265"
                default_preset = Config.LIB265_PRESET
                default_pixfmt = "yuv420p10le"
            else:  # x265, auto, or unknown - default to x265 for compression
                video_codec = "libx265"
                default_preset = Config.LIB265_PRESET
                default_pixfmt = "yuv420p10le"

            cmd = [
                BinConfig.FFMPEG_NAME,
                "-hide_banner",
                "-y",
                "-i",
                self.path,
                "-preset",
                preset or default_preset,
                "-c:v",
                video_codec,
            ]

            # Add profile for x265
            if video_codec == "libx265":
                cmd.extend(["-profile:v", "main10"])

            cmd.extend(
                [
                    "-map",
                    f"0:{self.data['video']}",
                ]
            )
            if crf:
                cmd.extend(("-crf", str(crf)))
            if bitdepth:
                cmd.extend(("-pix_fmt", bitdepth))
            else:
                cmd.extend(("-pix_fmt", default_pixfmt))
            if bitrate:
                bitrate = f"{bitrate}k"
                cmd.extend(
                    (
                        "-b:v",
                        bitrate,
                        "-minrate",
                        bitrate,
                        "-maxrate",
                        bitrate,
                        "-bufsize",
                        bitrate,
                    )
                )
            cmd.extend(
                (
                    "-vf",
                    f"scale={self._quality[quality]}:-2,eq=contrast=1.07"
                    if quality
                    else "eq=contrast=1.07",
                )
            )
            cmd.extend(
                (
                    "-map",
                    f"0:{self.data['audio']}" if self.data.get("audio") else "0:a:?",
                )
            )
            cmd.extend(
                (
                    "-c:a",
                    "aac",
                    "-b:a",
                    audio_bitrate,
                    "-map",
                    "0:s:?",
                    "-c:s",
                    "copy",
                    self.outfile,
                )
            )
            await self._run_cmd(cmd)
            if self.listener.is_cancelled:
                return

            # Garbage collection after each file to free memory
            gc.collect()

        return await self._final_path()

    async def _vid_marker(self, **kwargs):
        await self._queue(True)
        if self.listener.is_cancelled:
            return

        # Get user settings for codec preferences
        user_dict = getattr(self.listener, "user_dict", {}) or {}

        # Get codec override from video tools selector if available
        selector_codec = None
        if (
            isinstance(self.listener.video_mode, list)
            and len(self.listener.video_mode) >= 4
        ):
            ed = self.listener.video_mode[3] or {}
            selector_codec = ed.get("codec")

        # Merge selections from -vt (selector) into kwargs
        try:
            if (
                isinstance(self.listener.video_mode, list)
                and len(self.listener.video_mode) >= 4
            ):
                ed = self.listener.video_mode[3] or {}
                if ed.get("wm_size") is not None:
                    try:
                        kwargs["wm_size"] = int(ed.get("wm_size"))
                    except Exception:
                        kwargs["wm_size"] = ed.get("wm_size")
                if ed.get("wm_position"):
                    kwargs["wm_position"] = ed.get("wm_position")
                if ed.get("wm_popup") is not None:
                    try:
                        kwargs["wm_popup"] = int(ed.get("wm_popup"))
                    except Exception:
                        kwargs["wm_popup"] = ed.get("wm_popup")
                if ed.get("hardsub") is not None:
                    kwargs["hardsub"] = ed.get("hardsub")
                if ed.get("sub_file"):
                    kwargs["sub_file"] = ed.get("sub_file")
                if ed.get("font_path"):
                    kwargs["font_path"] = ed.get("font_path")
                # Enhanced encoding settings from video tools selector
                if ed.get("preset"):
                    kwargs["preset"] = ed.get("preset")
                if ed.get("crf"):
                    try:
                        kwargs["crf"] = int(ed.get("crf"))
                    except Exception:
                        kwargs["crf"] = ed.get("crf")
                if ed.get("bitrate"):
                    # For video tools, bitrate from selector is audio bitrate
                    kwargs["audio_bitrate"] = ed.get("bitrate")
                if ed.get("quality"):
                    kwargs["quality"] = ed.get("quality")
                # Add codec extraction from selector
                if ed.get("codec"):
                    kwargs["codec"] = ed.get("codec")
        except Exception:
            pass
        # Resolve watermark image path with robust fallbacks
        user_dict = getattr(self.listener, "user_dict", {}) or {}

        # Try new VIDEO_WATERMARK_* settings first, then fallback to VT_*
        user_wm_img = user_dict.get("VIDEO_WATERMARK_IMAGE_PATH") or user_dict.get(
            "VT_WATERMARK_IMAGE"
        )
        candidates = []
        if user_wm_img:
            candidates.append(user_wm_img)
        from ... import DOWNLOAD_DIR

        candidates.append(
            ospath.join(
                DOWNLOAD_DIR, "thumbnails", "watermark", f"{self.listener.mid}.png"
            )
        )
        # Also check common CWD-based paths
        try:
            cwd_base = ospath.abspath(ospath.curdir)
        except Exception:
            cwd_base = "/usr/src/app"
        # By user_id (settings) and by mid (selector)
        uid = getattr(self.listener, "user_id", None)
        if uid:
            candidates.append(
                ospath.join(cwd_base, "thumbnails", "watermark", f"{uid}.png")
            )
        candidates.append(
            ospath.join(cwd_base, "thumbnails", "watermark", f"{self.listener.mid}.png")
        )
        wm_path = None
        for cand in candidates:
            if cand and await aiopath.exists(cand):
                wm_path = cand
                break
        wm_size, wm_position, wm_popup = (
            kwargs.get("wm_size"),
            kwargs.get("wm_position"),
            kwargs.get("wm_popup") or "",
        )
        # Default position if not provided; prefer new settings, then legacy
        if not wm_position:
            wm_position = (
                user_dict.get("VIDEO_WATERMARK_POSITION")
                or user_dict.get("VT_WATERMARK_POSITION")
                or "10:10"
            )

        # Convert descriptive position names to FFmpeg coordinate expressions
        position_map = {
            "top-left": "5:5",
            "top-right": "main_w-overlay_w-5:5",
            "bottom-left": "5:main_h-overlay_h-5",
            "bottom-right": "main_w-overlay_w-5:main_h-overlay_h-5",
            "center": "(main_w-overlay_w)/2:(main_h-overlay_h)/2",
        }

        # If position is a descriptive name, convert it to coordinates
        if wm_position in position_map:
            wm_position = position_map[wm_position]
        # Default wm_size: prefer new settings, then legacy, else 20
        if wm_size is None:
            wm_size = (
                user_dict.get("VIDEO_WATERMARK_FONT_SIZE")
                or user_dict.get("VT_WATERMARK_SIZE")
                or 20
            )
        hardsub, sub_file = kwargs.get("hardsub") or "", kwargs.get("sub_file", "")
        crf, bitrate, bitdepth = (
            kwargs.get("crf") or getattr(Config, "FFMPEG_CRF", 23),
            kwargs.get("bitrate"),
            kwargs.get("bitdepth"),
        )
        quality = (
            f",scale={self._quality[kwargs['quality']]}:-2"
            if kwargs.get("quality")
            else ""
        )
        for file in (file_list := await self._get_files()):
            self.path = file
            self._files.append(self.path)
            if self._metadata:
                base_dir, file_size = self.listener.dir, self.listener.size
                await gather(
                    makedirs(base_dir, exist_ok=True), self._send_status("wait")
                )
            else:
                base_dir = self.listener.dir
                await makedirs(base_dir, exist_ok=True)
                await self._name_base_dir(self.path, "Marker", len(file_list) > 1)
                file_size = await get_path_size(self.path)
            # Only use image watermark when a valid image exists
            use_wm_image = bool(wm_path) and await aiopath.exists(wm_path)
            self.listener.size = file_size + (
                await get_path_size(wm_path) if use_wm_image else 0
            )
            # Ensure output does not overwrite input path when we actually watermark
            name_no_ext, ext = ospath.splitext(self.listener.name)
            safe_out = f"{name_no_ext}_WM{ext or '.mkv'}"
            self.outfile = ospath.join(base_dir, safe_out)
            self._files.append(self.path)
            if wm_popup:
                duration = (await get_media_info(self.path))[0]
                # Ensure duration is numeric to prevent issues in FFmpeg command generation
                if not isinstance(duration, (int, float)) or duration <= 0:
                    duration = 1  # Use 1 as fallback to prevent division by zero
                wm_popup = rf":enable=lt(mod(t\,{duration}/{wm_popup})\,20)"

            # Retrieve WM text early for checks - prefer new settings, then legacy
            vt_text = user_dict.get("VIDEO_WATERMARK_TEXT") or user_dict.get(
                "VT_WATERMARK_TEXT"
            )
            # Force no-op when neither image nor text watermark is available
            if not use_wm_image and not vt_text:
                # Nothing to watermark; pass-through original
                self.outfile = self.path
                continue
            if hardsub and await aiopath.exists(sub_file):
                # Import the color detection function
                from ..ext_utils.video_process_utils import (
                    has_existing_subtitle_colors,
                    escape_ffmpeg_path,
                )

                # Enhanced font configuration with font path support
                user_dict = getattr(self.listener, "user_dict", {}) or {}
                font_path = await self._get_font_path(**kwargs)

                # Determine font name and directory to use
                fonts_dir = None
                if font_path and await aiopath.exists(font_path):
                    # Use custom font file - extract directory and filename
                    fonts_dir = ospath.dirname(font_path)
                    # Use just the filename without extension as the font name
                    # libass will find the font in the fontsdir
                    font_name = ospath.splitext(ospath.basename(font_path))[0]
                    LOGGER.info(
                        f"Hardsub vid_marker using custom font file: {font_path}"
                    )
                    LOGGER.info(f"Font directory: {fonts_dir}, Font name: {font_name}")
                else:
                    # Use system font name
                    font_name = kwargs.get("font_name", "").replace(
                        "_", " "
                    ) or user_dict.get(
                        "VIDEO_HARDSUB_FONT_NAME", Config.HARDSUB_FONT_NAME
                    )
                    LOGGER.info(
                        f"Hardsub vid_marker using system font name: {font_name}"
                    )
                    if font_path:
                        LOGGER.warning(
                            f"Custom font file not found, falling back to system font: {font_path}"
                        )
                font_size_value = kwargs.get("font_size") or (
                    self.listener.user_dict or {}
                ).get("VIDEO_HARDSUB_FONT_SIZE", Config.HARDSUB_FONT_SIZE)
                font_size = f",FontSize={font_size_value}" if font_size_value else ""

                # Check if subtitle has existing colors
                has_existing_colors = has_existing_subtitle_colors(sub_file)
                LOGGER.info(f"Subtitle has existing colors: {has_existing_colors}")

                # Check user preference for preserving existing colors
                preserve_colors = (self.listener.user_dict or {}).get(
                    "VT_HARDSUB_PRESERVE_COLORS",
                    True,  # Default to preserving colors
                )
                LOGGER.info(f"User preserve colors setting: {preserve_colors}")

                # Apply color logic based on user preference and existing colors
                font_colour = ""
                apply_hardsub_color = True
                if preserve_colors and has_existing_colors:
                    # Don't override existing colors when preservation is enabled
                    apply_hardsub_color = False
                    LOGGER.info(
                        "Preserving existing subtitle colors, not applying hardsub color"
                    )
                elif not preserve_colors:
                    # Always apply hardsub color when preservation is disabled
                    apply_hardsub_color = True
                    LOGGER.info("Force applying hardsub color (preservation disabled)")
                elif not has_existing_colors:
                    # Apply hardsub color when subtitle has no existing colors
                    apply_hardsub_color = True
                    LOGGER.info(
                        "Applying hardsub color to subtitle without existing colors"
                    )

                if apply_hardsub_color and (
                    kwargs.get("font_colour")
                    or (self.listener.user_dict or {}).get("VIDEO_HARDSUB_FONT_COLOUR")
                ):
                    hardsub_color = kwargs.get("font_colour") or (
                        self.listener.user_dict or {}
                    ).get("VIDEO_HARDSUB_FONT_COLOUR")
                    font_colour = f",PrimaryColour=&H{hardsub_color}"

                # Get hardsub style from user settings or kwargs
                hardsub_style = kwargs.get("hardsub_style") or (
                    (self.listener.user_dict or {}).get(
                        "VIDEO_HARDSUB_STYLE", "default"
                    )
                )

                # Build proper force_style following refer implementation
                force_style_parts = [f"FontName={font_name}"]
                if font_size_value:
                    force_style_parts.append(f"FontSize={font_size_value}")

                # Add color only if applying hardsub color
                if apply_hardsub_color and hardsub_color:
                    force_style_parts.append(f"PrimaryColour=&H{hardsub_color}")

                # Add style-specific options
                if hardsub_style == "bold":
                    force_style_parts.append("Bold=1")
                elif hardsub_style == "outline":
                    force_style_parts.extend(
                        ["Bold=1", "Outline=2", "OutlineColour=&H00000000"]
                    )
                elif hardsub_style == "shadow":
                    force_style_parts.extend(
                        ["Bold=1", "Shadow=2", "BackColour=&H80000000"]
                    )
                elif hardsub_style == "glow":
                    force_style_parts.extend(
                        ["Bold=1", "Outline=3", "OutlineColour=&H00FFFFFF"]
                    )
                else:  # default style
                    # Add basic shadow for readability unless style is explicitly default
                    force_style_parts.append("Shadow=1.5")

                force_style = ",".join(force_style_parts)
                LOGGER.info(f"Hardsub vid_marker force_style applied: {force_style}")

                # Add fontsdir parameter if custom font is used
                if fonts_dir:
                    fonts_dir_escaped = escape_ffmpeg_path(fonts_dir)
                    hardsub = f",subtitles='{sub_file}':fontsdir='{fonts_dir_escaped}':force_style='{force_style}',eq=contrast=1.07"
                else:
                    hardsub = f",subtitles='{sub_file}':force_style='{force_style}',eq=contrast=1.07"

            # Build filter for image/text watermark
            # Only apply text filter when there is no image watermark available
            text_filter = ""
            if vt_text and not use_wm_image:
                # Escape characters for drawtext
                esc_text = (
                    vt_text.replace("\\", "\\\\")
                    .replace(":", r"\:")
                    .replace("'", r"\\'")
                )
                # Resolve a usable font path for drawtext
                font_candidates = []
                if kwargs.get("font_path"):
                    font_candidates.append(kwargs["font_path"])
                cfg_font = getattr(Config, "HARDSUB_FONT_PATH", "")
                if cfg_font:
                    font_candidates.append(cfg_font)
                # User-specified WM font path in settings - prefer new, then legacy
                try:
                    if user_dict:
                        wm_font = user_dict.get(
                            "VIDEO_WATERMARK_FONT_PATH"
                        ) or user_dict.get("VT_WM_FONT_PATH")
                        if wm_font:
                            font_candidates.insert(0, wm_font)
                except Exception:
                    pass
                font_candidates.extend(
                    [
                        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                        "/usr/local/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                        ospath.join(ospath.abspath(ospath.curdir), "wm.ttf"),
                    ]
                )
                fontfile = None
                for cand in font_candidates:
                    if cand and await aiopath.exists(cand):
                        fontfile = cand
                        break
                if not fontfile:
                    fontfile = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
                # Compute fontsize from wm_size (percentage -> heuristic baseline)
                try:
                    fsz = int(wm_size) if wm_size else 24
                except Exception:
                    fsz = 24
                pos = wm_position or "10:10"
                # Support overlay-style expressions in position. Expect "X:Y" string as used by overlay filter
                if ":" in pos:
                    x_expr, y_expr = pos.split(":", 1)
                else:
                    x_expr, y_expr = "10", "10"
                bold_flag = False
                try:
                    bold_flag = bool(
                        (self.listener.user_dict or {}).get("VT_WM_FONT_BOLD", False)
                    )
                except Exception:
                    pass
                draw_opts = [
                    f"fontfile='{fontfile}'",
                    f"text='{esc_text}'",
                    f"fontsize={fsz}",
                    "fontcolor=white",
                    "bordercolor=black",
                    "borderw=2",
                    f"x={x_expr}",
                    f"y={y_expr}",
                ]
                if bold_flag:
                    draw_opts.append(
                        r"fontcolor_expr=if(gte(mod(n\,2)\,1)\,white\,white)"
                    )
                text_filter = ",drawtext=" + ":".join(draw_opts)

            # Filter graph assembly
            if use_wm_image:
                # Build overlay filter first
                overlay_filter = f"[1:v]scale=iw*{wm_size}/100:-1[wm];[0:v][wm]overlay={wm_position}{wm_popup}"
                # Apply quality, hardsub, and text filters to the result
                if quality or hardsub or text_filter:
                    post_filters = []
                    if quality:
                        post_filters.append(quality.lstrip(","))
                    if hardsub and isinstance(hardsub, str):
                        post_filters.append(hardsub.lstrip(","))
                    if text_filter:
                        post_filters.append(text_filter.lstrip(","))
                    filter_graph = f"{overlay_filter}[v1];[v1]{','.join(post_filters)}"
                else:
                    filter_graph = overlay_filter
                cmd = [
                    BinConfig.FFMPEG_NAME,
                    "-hide_banner",
                    "-y",
                    "-i",
                    self.path,
                    "-i",
                    wm_path,
                    "-filter_complex",
                    filter_graph,
                ]
            else:
                # No image; apply text (if any) and quality/hardsub directly on [0:v]
                # Build a clean chain without leading commas after [0:v]
                base_filter = quality.lstrip(",") if quality else "null"
                parts = [base_filter]
                if hardsub and isinstance(hardsub, str):
                    parts.append(hardsub.lstrip(","))
                if text_filter:
                    parts.append(text_filter.lstrip(","))
                filter_graph = f"[0:v]{','.join(parts)}"
                cmd = [
                    BinConfig.FFMPEG_NAME,
                    "-hide_banner",
                    "-y",
                    "-i",
                    self.path,
                    "-filter_complex",
                    filter_graph,
                ]
            # Use user codec preferences when watermark encoding is enabled
            user_codec = selector_codec or user_dict.get("VIDEO_CONVERT_CODEC", "auto")

            # Determine codec based on user settings and fast mode
            if Config.VIDTOOLS_FAST_MODE:
                if user_codec == "x265":
                    cmd.extend(("-c:v", "libx265", "-preset", Config.LIB265_PRESET))
                elif user_codec == "x264":
                    cmd.extend(("-c:v", "libx264", "-preset", Config.LIB264_PRESET))
                elif user_codec == "copy":
                    # For watermark with copy, we need to re-encode, so use default x264
                    cmd.extend(("-c:v", "libx264", "-preset", Config.LIB264_PRESET))
                else:  # auto or unknown
                    cmd.extend(("-c:v", "libx264", "-preset", Config.LIB264_PRESET))
                if bitdepth:
                    cmd.extend(("-pix_fmt", bitdepth))
            else:
                if user_codec == "x264":
                    cmd.extend(
                        (
                            "-c:v",
                            "libx264",
                            "-preset",
                            Config.LIB264_PRESET,
                        )
                    )
                    if bitdepth:
                        cmd.extend(("-pix_fmt", bitdepth))
                    else:
                        cmd.extend(("-pix_fmt", "yuv420p"))
                elif user_codec == "copy":
                    # For watermark with copy, we need to re-encode, so use default x265
                    cmd.extend(
                        (
                            "-c:v",
                            "libx265",
                            "-preset",
                            Config.LIB265_PRESET,
                            "-profile:v",
                            "main10",
                        )
                    )
                    if bitdepth:
                        cmd.extend(("-pix_fmt", bitdepth))
                    else:
                        cmd.extend(("-pix_fmt", "yuv420p10le"))
                else:  # x265, auto, or unknown - default to x265 in non-fast mode
                    cmd.extend(
                        (
                            "-c:v",
                            "libx265",
                            "-preset",
                            Config.LIB265_PRESET,
                            "-profile:v",
                            "main10",
                        )
                    )
                    if bitdepth:
                        cmd.extend(("-pix_fmt", bitdepth))
                    else:
                        cmd.extend(("-pix_fmt", "yuv420p10le"))
            if crf:
                cmd.extend(("-crf", str(crf)))
            if bitrate:
                bitrate = f"{bitrate}k"
                cmd.extend(
                    (
                        "-b:v",
                        bitrate,
                        "-minrate",
                        bitrate,
                        "-maxrate",
                        bitrate,
                        "-bufsize",
                        bitrate,
                    )
                )
            if hardsub:
                cmd.extend(("-map", "-0:s:?"))
            else:
                cmd.extend(("-map", "0:s:?", "-c:s", "copy"))
            cmd.extend(("-map", "0:a:?", "-c:a", "copy", self.outfile))
            ok = await self._run_cmd(cmd)
            # Fallback: retry with libx264 if first attempt fails (e.g., missing x265/drawtext issues)
            if not ok:
                fallback_cmd = [
                    BinConfig.FFMPEG_NAME,
                    "-hide_banner",
                    "-y",
                    "-i",
                    self.path,
                ]
                if use_wm_image:
                    fallback_cmd.extend(
                        ["-i", wm_path, "-filter_complex", filter_graph]
                    )
                else:
                    fallback_cmd.extend(["-filter_complex", filter_graph])
                fallback_cmd.extend(
                    (
                        "-c:v",
                        "libx264",
                        "-preset",
                        Config.LIB264_PRESET,
                        "-pix_fmt",
                        "yuv420p",
                    )
                )
                if crf:
                    fallback_cmd.extend(("-crf", str(crf)))
                if bitrate:
                    br = f"{bitrate}k" if isinstance(bitrate, int) else str(bitrate)
                    fallback_cmd.extend(
                        ("-b:v", br, "-minrate", br, "-maxrate", br, "-bufsize", br)
                    )
                if hardsub:
                    fallback_cmd.extend(("-map", "-0:s:?"))
                else:
                    fallback_cmd.extend(("-map", "0:s:?", "-c:s", "copy"))
                fallback_cmd.extend(
                    (
                        "-map",
                        "0:a:?",
                        "-c:a",
                        "copy",
                        self.outfile,
                    )
                )
                await self._run_cmd(fallback_cmd)
            if self.listener.is_cancelled:
                return

        return await self._final_path(self.outfile)

    async def _merge_vids(self):
        self.listener.size = 0
        list_files = []
        for dirpath, _, files in await sync_to_async(walk, self.path):
            for file in natsorted(files):
                fname_upper = file.upper()
                if fname_upper.startswith("SAMPLE.") or fname_upper == "SAMPLE":
                    continue
                fpath = ospath.join(dirpath, file)
                if (await get_document_type(fpath))[0]:
                    duration_for_merge = (await get_media_info(fpath))[0]
                    if duration_for_merge and duration_for_merge > 0:
                        self.listener.size += await get_path_size(fpath)
                        list_files.append(f"file '{ffmpeg_parse(fpath)}'")
                        self._files.append(fpath)
                    else:
                        LOGGER.warning(
                            f"Skipping invalid/unreadable video file for merge: {fpath}"
                        )

        self.outfile = self._org_path
        if len(list_files) > 1:
            await self._name_base_dir(self.path)
            await update_status_message(self.listener.message.chat.id)
            input_file = ospath.join(self.path, "input.txt")
            async with aiopen(input_file, "w") as f:
                await f.write("\n".join(list_files))

            # Use basename to avoid nested path issues
            filename = (
                ospath.basename(self.listener.name)
                if self.listener.name
                else "merged_video.mkv"
            )
            self.outfile = ospath.join(self.path, filename)
            cmd = [
                BinConfig.FFMPEG_NAME,
                "-hide_banner",
                "-ignore_unknown",
                "-y",
                "-fflags",
                "+genpts",
                "-avoid_negative_ts",
                "make_zero",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                input_file,
                "-map",
                "0",
                "-c",
                "copy",
                self.outfile,
            ]
            ok = await self._run_cmd(cmd, "direct")
            if not ok:
                fallback_cmd = [
                    BinConfig.FFMPEG_NAME,
                    "-hide_banner",
                    "-y",
                    "-fflags",
                    "+genpts",
                    "-avoid_negative_ts",
                    "make_zero",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    input_file,
                    "-map",
                    "0:v:0?",
                    "-map",
                    "0:a:?",
                    "-map",
                    "0:s:?",
                    "-vsync",
                    "vfr",
                    "-shortest",
                    "-c:v",
                    "libx264",
                    "-preset",
                    Config.LIB264_PRESET,
                    "-crf",
                    str(getattr(Config, "FFMPEG_CRF", 23)),
                    "-c:a",
                    "aac",
                    "-ar",
                    "48000",
                    "-b:a",
                    "192k",
                    "-c:s",
                    "copy",
                    self.outfile,
                ]
                await self._run_cmd(fallback_cmd)
            await clean_target(input_file)
            if self.listener.is_cancelled:
                return
        else:
            return self._org_path

        return await self._final_path()

    async def _merge_audios(self):
        if self.listener.is_cancelled:
            return self._org_path
        if not self.path or not await aiopath.isdir(self.path):
            LOGGER.error(f"_merge_audios: Path '{self.path}' is not a valid directory.")
            return self._org_path

        self.listener.size = 0
        main_video = None
        audio_files = []

        # Scan directory
        for dirpath, _, files in await sync_to_async(walk, self.path):
            for file in natsorted(files):
                if file == f"SAMPLE.{file}":
                    continue
                fpath = ospath.join(dirpath, file)
                is_video, is_audio, _ = await get_document_type(fpath)
                if is_video and not main_video:
                    main_video = fpath
                elif is_audio:
                    self.listener.size += await get_path_size(fpath)
                    audio_files.append(fpath)

        if not main_video:
            LOGGER.info("Not detected main video!")
            return self._org_path

        # Only one video + collected audios
        self._files = [main_video] + audio_files
        self.outfile = self._org_path

        if len(self._files) > 1:
            _, size = await gather(
                self._name_base_dir(self.path), get_path_size(main_video)
            )
            self.listener.size += size
            await update_status_message(self.listener.message.chat.id)

            cmd = [BinConfig.FFMPEG_NAME, "-hide_banner", "-y"]

            # Add inputs
            for f in self._files:
                cmd.extend(("-i", f))

            # Map everything from main video
            cmd.extend(("-map", "0"))

            # Map external audios
            for j in range(1, len(self._files)):
                cmd.extend(("-map", f"{j}:a"))

            # Make the first added external audio default
            if len(audio_files) > 0:
                cmd.extend(["-disposition:a:1", "default"])

            # Final output - use basename to avoid nested path issues
            filename = (
                ospath.basename(self.listener.name)
                if self.listener.name
                else "merged_video.mkv"
            )
            self.outfile = ospath.join(self.path, filename)
            cmd.extend(["-c", "copy", self.outfile])

            cmd_success = await self._run_cmd(cmd, "direct")

            if self.listener.is_cancelled:
                if await aiopath.exists(self.outfile):
                    await clean_target(self.outfile)
                return self._org_path

            self.path = self.outfile if cmd_success else self._org_path
            if self.listener.is_cancelled:
                return self._org_path
        else:
            return self._org_path

        return await self._final_path(self.path)

    async def _reorder_tracks(self):
        file_list = await self._get_files()
        multi = len(file_list) > 1
        if not file_list:
            LOGGER.error("ReorderTracks: No files found to process.")
            return self._org_path

        # Auto-apply from user settings: VT_AUDIO_ORDER (e.g., "2,1,3,0")
        auto_order = (self.listener.user_dict or {}).get("VT_AUDIO_ORDER")
        prefilled_order = None
        if auto_order:
            try:
                # Parse user-provided order (positions in audio track list)
                order_positions = [
                    int(x.strip())
                    for x in str(auto_order).split(",")
                    if x.strip().isdigit()
                ]
                # Will map later once we have streams
                prefilled_order = order_positions
            except Exception:
                prefilled_order = None

        # Initial setup for streams and base_dir based on metadata or first file
        if self._metadata:
            base_dir = self.listener.dir  # Output directory
            await makedirs(base_dir, exist_ok=True)
            streams = self._metadata[0]  # ffprobe streams from metadata
        else:
            main_video = file_list[0]
            await self._name_base_dir(main_video, "Reorder", multi)
            base_dir = ospath.dirname(
                ospath.join(self.listener.dir, self.listener.name)
            )
            if not await aiopath.isdir(base_dir):
                await makedirs(base_dir, exist_ok=True)
            # Ensure output filename differs from input
            try:
                orig_base = ospath.basename(main_video)
                if self.listener.name == orig_base:
                    name_no_ext = orig_base.rsplit(".", 1)[0]
                    self.listener.name = f"{name_no_ext}_REORDER.mkv"
            except Exception:
                pass

            meta_video_result, main_video_size = await gather(
                get_meta_video(main_video),
                get_path_size(main_video),
            )
            streams = meta_video_result[0]
            self.listener.size = main_video_size

        # If we have prefilled_order, convert to global stream indexes and skip UI
        if prefilled_order is not None:
            audio_indices_global = [
                s.get("index") for s in streams if s.get("codec_type") == "audio"
            ]
            user_defined_stream_order = []
            for pos in prefilled_order:
                if 0 <= pos < len(audio_indices_global):
                    user_defined_stream_order.append(audio_indices_global[pos])
            if user_defined_stream_order:
                self.data = {"reordered_streams": user_defined_stream_order}
            else:
                self.data = None

        if not getattr(self, "data", None):
            # Call UI selector only if no auto setting applied
            await self._send_status()
            await self.extra_buttons(streams)

            if self.listener.is_cancelled:
                LOGGER.info(
                    "ReorderTracks: Task cancelled by user during selection / ExtraSelect."
                )
                return self._org_path

            await self._queue()
            if self.listener.is_cancelled:
                LOGGER.info(
                    "ReorderTracks: Task cancelled by user after selection / during queue."
                )
                return self._org_path

            if not self.data or "reordered_streams" not in self.data:
                if (
                    self.data
                    and "reordered_streams" in self.data
                    and not self.data["reordered_streams"]
                ):
                    LOGGER.info(
                        "ReorderTracks: User confirmed with an empty reorder selection. No changes needed."
                    )
                    return self._org_path
                LOGGER.error(
                    f"ReorderTracks: 'reordered_streams' data not found or invalid after selection, and not cancelled. Data: {self.data}"
                )
                return self._org_path

        user_defined_stream_order = self.data["reordered_streams"]
        if not user_defined_stream_order:
            LOGGER.info(
                "ReorderTracks: User confirmed with an empty reorder selection. No changes needed."
            )
            return self._org_path

        processed_at_least_one_successfully = False
        last_successful_outfile = None

        for file_idx, file_path_item in enumerate(file_list):
            self.path = file_path_item
            current_streams_for_file = streams
            if not self._metadata:
                current_file_size = await get_path_size(self.path)
                await self._name_base_dir(self.path, "Reorder", multi)
                self.listener.size = current_file_size
            self.outfile = ospath.join(base_dir, self.listener.name)
            self._files.append(self.path)
            if multi and not self._metadata and file_idx > 0:
                current_streams_meta_result = await get_meta_video(self.path)
                current_streams_for_file = current_streams_meta_result[0]

            cmd = generate_reorder_streams_ffmpeg_cmd(
                all_streams_info=current_streams_for_file,
                user_defined_order=user_defined_stream_order,
                ffmpeg_path=BinConfig.FFMPEG_NAME,
                input_path=self.path,
                output_path=self.outfile,
            )

            LOGGER.info(
                f"ReorderTracks: Executing FFmpeg command for {self.path}: {' '.join(cmd)}"
            )
            cmd_success = await self._run_cmd(cmd)

            if self.listener.is_cancelled:
                LOGGER.info("ReorderTracks: Task cancelled during FFmpeg execution.")
                return self._org_path

            if cmd_success:
                processed_at_least_one_successfully = True
                last_successful_outfile = self.outfile
                if not multi:
                    self.path = self.outfile
            else:
                LOGGER.error(
                    f"ReorderTracks: FFmpeg command failed for file {self.path}."
                )

        if not processed_at_least_one_successfully:
            return self._org_path
        if multi:
            return await self._final_path(base_dir)
        return await self._final_path(last_successful_outfile)

    async def _swap_streams(self):
        file_list = await self._get_files()
        multi = len(file_list) > 1
        if not file_list:
            LOGGER.error("SwapStreams: No files found to process.")
            return self._org_path

        if self._metadata:
            base_dir = self.listener.dir
            await makedirs(base_dir, exist_ok=True)
            streams = self._metadata[0]
        else:
            main_video = file_list[0]
            await self._name_base_dir(main_video, "Swap", multi)
            base_dir = ospath.dirname(
                ospath.join(
                    self.listener.dir if self._metadata else ospath.dirname(main_video),
                    self.listener.name,
                )
            )
            if not await aiopath.isdir(base_dir):
                await makedirs(base_dir, exist_ok=True)

            meta_video_result, main_video_size = await gather(
                get_meta_video(main_video),
                get_path_size(main_video),
            )
            streams = meta_video_result[0]
            self.listener.size = main_video_size

        self.listener = self.listener
        await gather(self._send_status(), self.extra_buttons(streams))

        await self._queue()
        if self.listener.is_cancelled:
            LOGGER.info("SwapStreams: Task cancelled by user.")
            return self._org_path

        if not self.data or "swap_pairs" not in self.data:
            LOGGER.error(
                f"SwapStreams: No swap_pairs data found after selection. Data: {self.data}"
            )
            return self._org_path

        swap_pairs_from_data = self.data["swap_pairs"]
        if not swap_pairs_from_data:
            LOGGER.error("SwapStreams: swap_pairs list is empty.")
            return self._org_path

        valid_pairs = []
        for index1, index2 in swap_pairs_from_data:
            stream1 = next((s for s in streams if s["index"] == index1), None)
            stream2 = next((s for s in streams if s["index"] == index2), None)

            if not stream1 or not stream2:
                LOGGER.error(
                    f"SwapStreams: Invalid stream indices for swapping: {index1}, {index2}. One or both not found in video metadata."
                )
                continue

            stream_type = stream1["codec_type"]
            if stream_type != stream2["codec_type"]:
                LOGGER.error(
                    f"SwapStreams: Cannot swap streams of different types: {stream1['codec_type']} (idx {index1}) with {stream2['codec_type']} (idx {index2})."
                )
                continue

            if stream_type not in ["audio", "subtitle"]:
                LOGGER.error(
                    f"SwapStreams: Can only swap audio or subtitle streams, got: {stream_type} for pair ({index1}, {index2})."
                )
                continue
            valid_pairs.append((index1, index2, stream_type))

        if not valid_pairs:
            LOGGER.error(
                "SwapStreams: No valid swap pairs to process after validation."
            )
            return self._org_path

        for file_idx, file_path_item in enumerate(file_list):
            self.path = file_path_item
            if not self._metadata:
                current_file_size = await get_path_size(self.path)
                await self._name_base_dir(self.path, "Swap" if multi else "Swap", multi)
                self.listener.size = current_file_size

            current_output_base_dir = (
                self.listener.dir if self._metadata else ospath.dirname(self.path)
            )
            if not await aiopath.isdir(current_output_base_dir):
                await makedirs(current_output_base_dir, exist_ok=True)

            final_output_name_for_current_file = self.listener.name
            self.outfile = ospath.join(
                current_output_base_dir, final_output_name_for_current_file
            )

            self._files.append(self.path)

            current_streams = streams
            if multi and not self._metadata and file_idx > 0:
                current_streams_meta = await get_meta_video(self.path)
                current_streams = current_streams_meta[0]
            else:
                # For single file, or the first file in multi-mode, use 'streams'
                # which was fetched before the loop (or from self._metadata)
                current_streams = streams

            # We use swap_pairs_from_data which are the direct pairs from the UI.
            # generate_swap_streams_ffmpeg_cmd will handle the logic based on current_streams.
            # valid_pairs was primarily for early exit and logging if types didn't match etc.
            # but the core mapping should use the original selection against the current file's streams.
            cmd = generate_swap_streams_ffmpeg_cmd(
                all_streams_info=current_streams,
                swap_pairs=swap_pairs_from_data,
                ffmpeg_path=BinConfig.FFMPEG_NAME,
                input_path=self.path,
                output_path=self.outfile,
            )

            LOGGER.info(f"SwapStreams: Executing FFmpeg command: {' '.join(cmd)}")
            cmd_success = await self._run_cmd(cmd)

            if self.listener.is_cancelled:
                LOGGER.info("SwapStreams: Task cancelled during FFmpeg execution.")
                return self._org_path

            if not cmd_success:
                LOGGER.error(
                    f"SwapStreams: FFmpeg command failed for file {self.path}."
                )
            else:
                if not multi:
                    self.path = self.outfile
                else:
                    pass

        if multi:
            self.path = await self._final_path(
                ospath.dirname(self.outfile)
                if "self.outfile" in locals() and self.outfile
                else self._org_path
            )
        elif "cmd_success" in locals() and cmd_success:
            self.path = await self._final_path(self.outfile)
        else:
            self.path = await self._final_path(self._org_path)

        return self.path

    async def _merge_subtitles(self, **kwargs):
        from ..ext_utils.video_process_utils import (
            validate_video_file,
            validate_subtitle_file,
            escape_ffmpeg_path,
            get_subtitle_codec,
            generate_unique_filename,
            validate_encoding_parameters,
            SubtitleError,
            ValidationError,
            temp_directory,
        )

        self.listener.size = 0
        # Track the largest video to avoid picking a SAMPLE as main
        main_video = None
        best_size = -1
        subtitle_files = []

        # Improved file detection with validation
        for dirpath, _, files in await sync_to_async(walk, self.path):
            for file in natsorted(files):
                fname_upper = file.upper()
                if fname_upper.startswith("SAMPLE.") or fname_upper == "SAMPLE":
                    continue
                fpath = ospath.join(dirpath, file)

                try:
                    # Use our validation functions
                    if validate_video_file(fpath):
                        cur_size = await get_path_size(fpath)
                        if cur_size > best_size:
                            best_size = cur_size
                            main_video = fpath
                    elif validate_subtitle_file(fpath):
                        self.listener.size += await get_path_size(fpath)
                        subtitle_files.append(fpath)
                except Exception as e:
                    LOGGER.warning(f"Error processing file {fpath}: {e}")
                    continue

        # If hardsub is requested but no subtitle found yet, wait briefly for a subtitle to arrive (auto-flow)
        if kwargs.get("hardsub") and not subtitle_files:
            await self._send_status("wait")
            for _ in range(12):  # wait up to ~12s
                await sleep(1)
                for dirpath, _, files in await sync_to_async(walk, self.path):
                    for file in natsorted(files):
                        fpath = ospath.join(dirpath, file)
                        try:
                            if (
                                validate_subtitle_file(fpath)
                                and fpath not in subtitle_files
                            ):
                                subtitle_files.append(fpath)
                                break
                        except Exception:
                            pass
                if subtitle_files:
                    break

        if not main_video:
            LOGGER.error("No valid main video file detected!")
            return self._org_path

        if not subtitle_files:
            LOGGER.warning("No valid subtitle files found!")
            return self._org_path

        # Combine video and subtitle files
        self._files = [main_video] + subtitle_files
        self.outfile = self._org_path

        try:
            # Validate encoding parameters
            validated_params = validate_encoding_parameters(
                crf=kwargs.get("crf"),
                bitrate=kwargs.get("bitrate"),
                quality=kwargs.get("quality"),
            )

            _, size = await gather(
                self._name_base_dir(self.path), get_path_size(main_video)
            )
            self.listener.size += size

            # Generate unique output filename to avoid conflicts
            # Use basename to avoid nested path issues
            filename = (
                ospath.basename(self.listener.name)
                if self.listener.name
                else "merged_video.mkv"
            )
            base_output_path = ospath.join(self.listener.dir, filename)
            self.outfile = generate_unique_filename(base_output_path, suffix="_merged")

            # Validate and truncate path if too long to prevent ffmpeg errors
            self.outfile = self.outfile

            # Build FFmpeg command with improved logic
            if kwargs.get("hardsub"):
                success = await self._process_hardsub_merge(
                    subtitle_files[0], **kwargs, **validated_params
                )
            else:
                success = await self._process_softsub_merge(
                    subtitle_files, **kwargs, **validated_params
                )

            if not success:
                # Fallback strategy with different parameters
                LOGGER.warning("Primary encoding failed, attempting fallback...")
                fallback_params = {**kwargs, "crf": 23, "quality": None}
                if kwargs.get("hardsub"):
                    success = await self._process_hardsub_merge(
                        subtitle_files[0], **fallback_params
                    )
                else:
                    success = await self._process_softsub_merge(
                        subtitle_files, **fallback_params
                    )

                if not success:
                    raise SubtitleError("Both primary and fallback encoding failed")

            if self.listener.is_cancelled:
                return

        except (ValidationError, SubtitleError) as e:
            LOGGER.error(f"Subtitle merge failed: {e}")
            return self._org_path
        except Exception as e:
            LOGGER.error(f"Unexpected error during subtitle merge: {e}")
            return self._org_path

        return await self._final_path()

    async def _process_hardsub_merge(self, subtitle_file: str, **kwargs) -> bool:
        """Process hardsub (burned-in) subtitle merge with advanced styling options."""
        from ..ext_utils.video_process_utils import (
            escape_ffmpeg_path,
            has_existing_subtitle_colors,
        )

        try:
            cmd = [BinConfig.FFMPEG_NAME, "-hide_banner", "-y"]
            self.path, status = self._files[0], "prog"
            cmd.extend(("-i", self.path, "-vf"))

            # Enhanced font configuration with font path support and advanced styling options
            user_dict = getattr(self.listener, "user_dict", {}) or {}
            font_path = await self._get_font_path(**kwargs)

            # Determine font name and directory to use
            fonts_dir = None
            if font_path and await aiopath.exists(font_path):
                # Use custom font file - extract directory and filename
                fonts_dir = ospath.dirname(font_path)
                # Use just the filename without extension as the font name
                # libass will find the font in the fontsdir
                font_name = ospath.splitext(ospath.basename(font_path))[0]
                LOGGER.info(f"Hardsub using custom font file: {font_path}")
                LOGGER.info(f"Font directory: {fonts_dir}, Font name: {font_name}")
            else:
                # Use system font name
                font_name = kwargs.get("font_name", "").replace(
                    "_", " "
                ) or user_dict.get("VIDEO_HARDSUB_FONT_NAME", Config.HARDSUB_FONT_NAME)
                LOGGER.info(f"Hardsub using system font name: {font_name}")
                if font_path:
                    LOGGER.warning(
                        f"Custom font file not found, falling back to system font: {font_path}"
                    )
            font_size_value = kwargs.get("font_size") or (
                getattr(self.listener, "user_dict", {}) or {}
            ).get("VIDEO_HARDSUB_FONT_SIZE", Config.HARDSUB_FONT_SIZE)
            font_size = f",FontSize={font_size_value}" if font_size_value else ""

            # Advanced color options with user settings support
            user_hardsub_color = (getattr(self.listener, "user_dict", {}) or {}).get(
                "VIDEO_HARDSUB_FONT_COLOUR"
            )
            primary_color = kwargs.get("font_colour") or (
                f"&H{user_hardsub_color}" if user_hardsub_color else "&H00FFFFFF"
            )  # Default white
            secondary_color = kwargs.get(
                "secondary_colour", "&H00000000"
            )  # Default black
            outline_color = kwargs.get("outline_colour", "&H00000000")  # Default black
            back_color = kwargs.get(
                "back_colour", "&H80000000"
            )  # Default semi-transparent black

            font_colour = f",PrimaryColour={primary_color}"
            secondary_colour = f",SecondaryColour={secondary_color}"
            outline_colour = f",OutlineColour={outline_color}"
            back_colour = f",BackColour={back_color}"

            # Get hardsub style from user settings or kwargs
            hardsub_style = kwargs.get("hardsub_style") or (
                (getattr(self.listener, "user_dict", {}) or {}).get(
                    "VIDEO_HARDSUB_STYLE", "default"
                )
            )

            # Apply style-based formatting
            style_options = ""
            if hardsub_style == "bold":
                style_options = ",Bold=1"
            elif hardsub_style == "outline":
                style_options = ",Bold=1,Outline=3,OutlineColour=&H00000000"
            elif hardsub_style == "shadow":
                style_options = ",Bold=1,Shadow=3"
            elif hardsub_style == "glow":
                style_options = ",Bold=1,Outline=2,Shadow=2,OutlineColour=&H00FFFFFF"
            # default style uses original subtitle formatting (no extra options)
            italic_style = ",Italic=1" if kwargs.get("italic_style", False) else ""
            underline_style = (
                ",Underline=1" if kwargs.get("underline_style", False) else ""
            )
            strikeout_style = (
                ",StrikeOut=1" if kwargs.get("strikeout_style", False) else ""
            )

            # Outline and shadow settings
            outline_width = kwargs.get("outline_width", 2)
            shadow_depth = kwargs.get("shadow_depth", 2)
            outline_style = f",Outline={outline_width}"
            shadow_style = f",Shadow={shadow_depth}"

            # Positioning options - read from user settings if not provided in kwargs
            user_dict = getattr(self.listener, "user_dict", {}) or {}
            margin_l = kwargs.get("margin_l") or user_dict.get(
                "VT_HARDSUB_MARGIN_L", 10
            )
            margin_r = kwargs.get("margin_r") or user_dict.get(
                "VT_HARDSUB_MARGIN_R", 10
            )
            margin_v = kwargs.get("margin_v") or user_dict.get(
                "VT_HARDSUB_MARGIN_V", 10
            )
            alignment = kwargs.get("alignment") or user_dict.get(
                "VT_HARDSUB_ALIGNMENT", 2
            )  # Default bottom center

            LOGGER.info(
                f"Hardsub margins - L: {margin_l}, R: {margin_r}, V: {margin_v}, Alignment: {alignment}"
            )

            margin_l_style = f",MarginL={margin_l}"
            margin_r_style = f",MarginR={margin_r}"
            margin_v_style = f",MarginV={margin_v}"
            alignment_style = f",Alignment={alignment}"

            # Timing options
            delay = kwargs.get("subtitle_delay", 0)
            duration = kwargs.get("subtitle_duration", 0)
            timing_style = ""
            if delay != 0:
                timing_style += f",Delay={delay}"
            if duration != 0:
                timing_style += f",Duration={duration}"

            # Quality scaling
            quality = (
                f",scale={self._quality[kwargs['quality']]}:-2"
                if kwargs.get("quality")
                else ""
            )

            # Get validated parameters
            crf = kwargs.get("crf", getattr(Config, "FFMPEG_CRF", 23))
            bitrate = kwargs.get("bitrate")
            bitdepth = kwargs.get("bitdepth")

            # Decide fast hardsub defaults unless user explicitly set heavy options
            fast_mode = not any(
                (
                    kwargs.get("codec"),
                    kwargs.get("bitrate"),
                    kwargs.get("quality"),
                )
            )

            # Improved path escaping for subtitle filter
            sub_path_escaped = escape_ffmpeg_path(subtitle_file)

            # Check if subtitle has existing color information
            has_existing_colors = has_existing_subtitle_colors(subtitle_file)
            LOGGER.info(f"Subtitle has existing colors: {has_existing_colors}")

            # Check user preference for preserving existing colors
            preserve_colors = (getattr(self.listener, "user_dict", {}) or {}).get(
                "VT_HARDSUB_PRESERVE_COLORS",
                True,  # Default to preserving colors
            )
            LOGGER.info(f"User preserve colors setting: {preserve_colors}")

            # Build advanced subtitle filter with comprehensive styling
            # Apply color logic based on user preference and existing colors
            force_style_parts = [
                f"FontName={font_name}",
                f"FontSize={font_size_value}",
            ]

            # Add color styling based on user preference and existing colors
            apply_hardsub_color = True
            if preserve_colors and has_existing_colors:
                # Don't override existing colors when preservation is enabled
                apply_hardsub_color = False
                LOGGER.info(
                    "Preserving existing subtitle colors, not applying hardsub color"
                )
            elif not preserve_colors:
                # Always apply hardsub color when preservation is disabled
                apply_hardsub_color = True
                LOGGER.info("Force applying hardsub color (preservation disabled)")
            elif not has_existing_colors:
                # Apply hardsub color when subtitle has no existing colors
                apply_hardsub_color = True
                LOGGER.info(
                    "Applying hardsub color to subtitle without existing colors"
                )

            if apply_hardsub_color:
                # Apply hardsub color only if subtitle doesn't have its own colors
                force_style_parts.extend(
                    [
                        f"PrimaryColour={primary_color}",
                        f"SecondaryColour={secondary_color}",
                    ]
                )

            # Add other styling that doesn't interfere with colors
            force_style_parts.extend(
                [
                    f"OutlineColour={outline_color}",
                    f"BackColour={back_color}",
                    f"Outline={outline_width}",
                    f"Shadow={shadow_depth}",
                    f"MarginL={margin_l}",
                    f"MarginR={margin_r}",
                    f"MarginV={margin_v}",
                    f"Alignment={alignment}",
                ]
            )

            # Add style-based formatting
            if hardsub_style == "bold":
                force_style_parts.append("Bold=1")
            elif hardsub_style == "outline":
                force_style_parts.extend(
                    ["Bold=1", "Outline=3", "OutlineColour=&H00000000"]
                )
            elif hardsub_style == "shadow":
                force_style_parts.extend(["Bold=1", "Shadow=3"])
            elif hardsub_style == "glow":
                force_style_parts.extend(
                    ["Bold=1", "Outline=2", "Shadow=2", "OutlineColour=&H00FFFFFF"]
                )
            # default style uses original subtitle formatting (no bold added)
            if italic_style:
                force_style_parts.append("Italic=1")
            if underline_style:
                force_style_parts.append("Underline=1")
            if strikeout_style:
                force_style_parts.append("StrikeOut=1")

            # Add timing options if specified
            if timing_style:
                force_style_parts.append(timing_style.lstrip(","))

            # Build the complete subtitle filter
            force_style = ",".join(force_style_parts)
            LOGGER.info(f"Hardsub force_style applied: {force_style}")

            # Add fontsdir parameter if custom font is used
            if fonts_dir:
                from ..ext_utils.video_process_utils import escape_ffmpeg_path

                fonts_dir_escaped = escape_ffmpeg_path(fonts_dir)
                subtitle_filter = f"subtitles='{sub_path_escaped}':fontsdir='{fonts_dir_escaped}':force_style='{force_style}'"
            else:
                subtitle_filter = (
                    f"subtitles='{sub_path_escaped}':force_style='{force_style}'"
                )

            # Add quality scaling if specified
            if quality:
                subtitle_filter += quality

            # Add additional effects in non-fast mode
            if not fast_mode:
                # Add contrast enhancement and other effects
                effects = []
                if kwargs.get("enhance_contrast", True):
                    effects.append("eq=contrast=1.07")
                if kwargs.get("enhance_saturation", False):
                    effects.append("eq=saturation=1.1")
                if kwargs.get("enhance_brightness", False):
                    effects.append("eq=brightness=0.05")

                if effects:
                    subtitle_filter += "," + ",".join(effects)

            cmd.append(subtitle_filter)

            # Encoding settings with user codec preferences
            user_codec = (getattr(self.listener, "user_dict", {}) or {}).get(
                "VIDEO_CONVERT_CODEC", "auto"
            )

            if fast_mode or Config.VIDTOOLS_FAST_MODE:
                # In fast mode, prefer user codec but fall back to x264 for compatibility
                if user_codec == "x265":
                    # Even if user prefers x265, x264 is significantly faster for burn-in
                    cmd.extend(("-preset", "veryfast", "-c:v", "libx264"))
                elif user_codec == "x264":
                    cmd.extend(("-preset", "veryfast", "-c:v", "libx264"))
                elif user_codec == "copy":
                    # Need re-encode for hardsub
                    cmd.extend(("-preset", "veryfast", "-c:v", "libx264"))
                else:  # auto or unknown
                    cmd.extend(("-preset", "veryfast", "-c:v", "libx264"))
                # Standardized stream mapping with tolerant audio mapping
                cmd.extend(("-map", "0:v:0", "-map", "0:a:?", "-c:a", "copy"))
                if bitdepth:
                    cmd.extend(("-pix_fmt", bitdepth))
                else:
                    cmd.extend(("-pix_fmt", "yuv420p"))
            else:
                # In non-fast mode, prefer x265 unless user specifically wants x264
                if user_codec == "x264":
                    cmd.extend(("-preset", Config.LIB264_PRESET, "-c:v", "libx264"))
                    # For x264, use tolerant audio mapping
                    cmd.extend(("-map", "0:v:0", "-map", "0:a:?", "-c:a", "copy"))
                    if bitdepth:
                        cmd.extend(("-pix_fmt", bitdepth))
                    else:
                        cmd.extend(("-pix_fmt", "yuv420p"))
                elif user_codec == "copy":
                    # For intro subtitle, we need to re-encode, so use x265
                    cmd.extend(
                        (
                            "-preset",
                            Config.LIB265_PRESET,
                            "-c:v",
                            "libx265",
                            "-profile:v",
                            "main10",
                            "-x265-params",
                            "no-info=1",
                            "-bsf:v",
                            "filter_units=remove_types=6",
                        )
                    )
                    # For x265, use tolerant audio mapping and re-encode audio
                    cmd.extend(
                        (
                            "-map",
                            "0:v:0",
                            "-map",
                            "0:a:?",
                            "-c:a",
                            "aac",
                            "-b:a",
                            "192k",
                        )
                    )
                    if bitdepth:
                        cmd.extend(("-pix_fmt", bitdepth))
                    else:
                        cmd.extend(("-pix_fmt", "yuv420p10le"))
                else:  # x265, auto, or unknown - default to x265 in non-fast mode
                    cmd.extend(
                        (
                            "-preset",
                            Config.LIB265_PRESET,
                            "-c:v",
                            "libx265",
                            "-profile:v",
                            "main10",
                            "-x265-params",
                            "no-info=1",
                            "-bsf:v",
                            "filter_units=remove_types=6",
                        )
                    )
                    # For x265, use tolerant audio mapping and re-encode audio
                    cmd.extend(
                        (
                            "-map",
                            "0:v:0",
                            "-map",
                            "0:a:?",
                            "-c:a",
                            "aac",
                            "-b:a",
                            "192k",
                        )
                    )
                    if bitdepth:
                        cmd.extend(("-pix_fmt", bitdepth))
                    else:
                        cmd.extend(("-pix_fmt", "yuv420p10le"))

            # Quality settings
            if crf:
                cmd.extend(("-crf", str(crf)))
            if bitrate:
                bitrate_str = (
                    f"{bitrate}k" if isinstance(bitrate, int) else str(bitrate)
                )
                cmd.extend(
                    (
                        "-b:v",
                        bitrate_str,
                        "-minrate",
                        bitrate_str,
                        "-maxrate",
                        bitrate_str,
                        "-bufsize",
                        bitrate_str,
                    )
                )

            # Exclude internal subtitles to avoid conflicts
            cmd.extend(("-map", "-0:s:?", self.outfile))

            return await self._run_cmd(cmd, status)

        except Exception as e:
            LOGGER.error(f"Error processing hardsub merge: {e}")
            return False

    async def _process_hardsub(self, **kwargs):
        """Process hardsub (burned-in) subtitle with style support based on user settings."""
        await self._queue()
        if self.listener.is_cancelled:
            return self.path

        # Find subtitle file - look for common subtitle files in the same directory
        import glob

        if self._is_dir:
            # For directories, find video and subtitle files
            video_files = []
            subtitle_files = []

            for ext in ["*.mp4", "*.mkv", "*.avi", "*.mov", "*.webm", "*.m4v"]:
                video_files.extend(glob.glob(ospath.join(self.path, ext)))
                video_files.extend(glob.glob(ospath.join(self.path, ext.upper())))

            for ext in ["*.srt", "*.ass", "*.ssa", "*.vtt", "*.sub"]:
                subtitle_files.extend(glob.glob(ospath.join(self.path, ext)))
                subtitle_files.extend(glob.glob(ospath.join(self.path, ext.upper())))

            if not video_files:
                LOGGER.error("No video files found for hardsub processing")
                return self.path

            if not subtitle_files:
                LOGGER.error("No subtitle files found for hardsub processing")
                return self.path

            # Process each video file with matching subtitle
            for video_file in video_files:
                # Find matching subtitle file
                video_name = ospath.splitext(ospath.basename(video_file))[0]
                matching_subtitle = None

                for sub_file in subtitle_files:
                    sub_name = ospath.splitext(ospath.basename(sub_file))[0]
                    if sub_name == video_name or sub_name.startswith(video_name):
                        matching_subtitle = sub_file
                        break

                if matching_subtitle:
                    success = await self._apply_hardsub_to_file(
                        video_file, matching_subtitle, **kwargs
                    )
                    if not success:
                        LOGGER.error(f"Failed to apply hardsub to {video_file}")
        else:
            # For single file, look for subtitle with same name
            video_path = self.path
            video_name = ospath.splitext(video_path)[0]
            subtitle_path = None

            # Try different subtitle extensions
            for ext in [".srt", ".ass", ".ssa", ".vtt", ".sub"]:
                potential_sub = video_name + ext
                if await aiopath.exists(potential_sub):
                    subtitle_path = potential_sub
                    break

            if subtitle_path:
                success = await self._apply_hardsub_to_file(
                    video_path, subtitle_path, **kwargs
                )
                if not success:
                    LOGGER.error(f"Failed to apply hardsub to {video_path}")
            else:
                LOGGER.warning(f"No subtitle file found for {video_path}")

        return self.path

    async def _apply_hardsub_to_file(
        self, video_file: str, subtitle_file: str, **kwargs
    ) -> bool:
        """Apply hardsub to a single video file with specified subtitle file."""
        from ..ext_utils.video_process_utils import escape_ffmpeg_path

        try:
            # Get font path using the same logic as hardsub merge
            font_path = await self._get_font_path(**kwargs)

            # Get hardsub style settings
            hardsub_style = kwargs.get("hardsub_style", "default")
            font_size = kwargs.get("font_size", 22)
            font_colour = kwargs.get("font_colour", "FFFFFF")

            # Determine font name and directory to use
            fonts_dir = None
            if font_path and await aiopath.exists(font_path):
                # Use custom font file - extract directory and filename
                fonts_dir = ospath.dirname(font_path)
                # Use just the filename without extension as the font name
                # libass will find the font in the fontsdir
                font_name = ospath.splitext(ospath.basename(font_path))[0]
                LOGGER.info(f"Apply hardsub using custom font file: {font_path}")
                LOGGER.info(f"Font directory: {fonts_dir}, Font name: {font_name}")
            else:
                # Use system font name
                user_dict = getattr(self.listener, "user_dict", {}) or {}
                font_name = kwargs.get("font_name") or user_dict.get(
                    "VIDEO_HARDSUB_FONT_NAME", "Arial"
                )
                LOGGER.info(f"Apply hardsub using system font name: {font_name}")

            # Prepare output file path
            output_ext = ospath.splitext(video_file)[1]
            output_file = video_file.replace(output_ext, f"_hardsub{output_ext}")

            cmd = [BinConfig.FFMPEG_NAME, "-hide_banner", "-y"]
            cmd.extend(("-i", video_file, "-vf"))

            # Escape subtitle path for ffmpeg
            sub_path_escaped = escape_ffmpeg_path(subtitle_file)

            # Build subtitle filter based on style
            file_ext = ospath.splitext(subtitle_file)[1].lower()

            if file_ext in [".ass", ".ssa"]:
                # For ASS/SSA files, use ass filter to preserve existing styling unless overridden
                if hardsub_style == "default":
                    # Add fontsdir if custom font is used
                    if fonts_dir:
                        fonts_dir_escaped = escape_ffmpeg_path(fonts_dir)
                        subtitle_filter = (
                            f"ass='{sub_path_escaped}':fontsdir='{fonts_dir_escaped}'"
                        )
                    else:
                        subtitle_filter = f"ass='{sub_path_escaped}'"
                else:
                    # Add fontsdir if custom font is used
                    if fonts_dir:
                        fonts_dir_escaped = escape_ffmpeg_path(fonts_dir)
                        subtitle_filter = (
                            f"ass='{sub_path_escaped}':fontsdir='{fonts_dir_escaped}'"
                        )
                    else:
                        subtitle_filter = f"ass='{sub_path_escaped}'"
            else:
                # For SRT, VTT and other text-based formats, use subtitles filter with style control
                # Add fontsdir parameter if custom font is used
                if fonts_dir:
                    fonts_dir_escaped = escape_ffmpeg_path(fonts_dir)
                    subtitle_filter = (
                        f"subtitles='{sub_path_escaped}':fontsdir='{fonts_dir_escaped}'"
                    )
                else:
                    subtitle_filter = f"subtitles='{sub_path_escaped}'"

                # Apply styling based on user preferences (like refer implementation)
                if hardsub_style != "default":
                    style_options = []
                    style_options.append(f"FontSize={font_size}")
                    # Use font name directly without path
                    style_options.append(f"FontName={font_name}")

                    if hardsub_style == "bold":
                        style_options.append("Bold=1")
                    elif hardsub_style == "outline":
                        style_options.append("Bold=1")
                        style_options.append("Outline=2")
                        style_options.append("OutlineColour=&H00000000")
                    elif hardsub_style == "shadow":
                        style_options.append("Bold=1")
                        style_options.append("Shadow=2")
                        style_options.append("BackColour=&H80000000")
                    elif hardsub_style == "glow":
                        style_options.append("Bold=1")
                        style_options.append("Outline=3")
                        style_options.append("OutlineColour=&H00FFFFFF")

                    if style_options:
                        force_style = ",".join(style_options)
                        subtitle_filter += f":force_style='{force_style}'"

            cmd.append(subtitle_filter)

            # Use fast encoding settings for hardsub
            cmd.extend(("-preset", "fast", "-c:v", "libx264"))
            cmd.extend(("-map", "0:v:0", "-map", "0:a:?", "-c:a", "copy"))
            cmd.extend(("-pix_fmt", "yuv420p"))
            cmd.append(output_file)

            # Run the command
            process = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                # Replace original file with hardsub version
                await remove(video_file)
                await move(output_file, video_file)
                LOGGER.info(
                    f"Successfully applied hardsub to {video_file} with style: {hardsub_style}"
                )
                return True
            else:
                LOGGER.error(f"FFmpeg hardsub error: {stderr.decode()}")
                # Clean up failed output file
                if await aiopath.exists(output_file):
                    await remove(output_file)
                return False

        except Exception as e:
            LOGGER.error(f"Error applying hardsub to {video_file}: {e}")
            return False

    async def _process_softsub_merge(self, subtitle_files: list, **kwargs) -> bool:
        """Process soft subtitle merge with improved stream mapping."""
        from ..ext_utils.video_process_utils import get_subtitle_codec

        try:
            cmd = [BinConfig.FFMPEG_NAME, "-hide_banner", "-y"]

            # Add all input files
            for file_path in self._files:
                cmd.extend(("-i", file_path))

            # Standardized stream mapping with proper tolerant syntax
            # Map video and audio from main file (input 0)
            cmd.extend(("-map", "0:v:?", "-map", "0:a:?"))

            # Map each external subtitle file (inputs 1..N)
            subtitle_stream_index = 0
            for i, sub_file in enumerate(subtitle_files, 1):
                cmd.extend(("-map", f"{i}:s:?"))

                # Set appropriate codec for subtitle format
                codec = get_subtitle_codec(sub_file)
                if codec:
                    cmd.extend((f"-c:s:{subtitle_stream_index}", codec))
                subtitle_stream_index += 1

            # Map internal subtitles from main video as well (if any)
            cmd.extend(("-map", "0:s:?"))

            # Copy streams without re-encoding, including subtitles
            cmd.extend(("-c:v", "copy", "-c:a", "copy", "-c:s", "copy"))

            # Set default subtitle disposition
            if subtitle_files:
                cmd.extend(
                    (
                        "-disposition:s",
                        "0",  # Clear all subtitle dispositions first
                        "-disposition:s:0",
                        "default+forced",  # Set first external sub as default
                        "-metadata:s:s:0",
                        "language=eng",
                    )
                )

            cmd.append(self.outfile)
            return await self._run_cmd(cmd, "direct")

        except Exception as e:
            LOGGER.error(f"Error processing softsub merge: {e}")
            return False

    async def _intro_sub(self, **kwargs):
        from pathlib import Path
        from aiofiles.os import path as aiopath

        from ..ext_utils.intro_subtitle_utils import (
            check_embedded_subtitles,
            extract_subtitle,
            insert_intro_into_subtitle,
            build_intro_replace_cmd,
            generate_intro_ass,  # fade only
            build_intro_mux_cmd,
            convert_subtitle_to_srt,
            generate_intro_srt,  # typing + static
        )
        from ..ext_utils.files_utils import clean_target

        await self._queue(True)
        if self.listener.is_cancelled:
            return

        # Get user settings for codec preferences
        user_dict = getattr(self.listener, "user_dict", {}) or {}

        file_list = await self._get_files()
        if not file_list:
            LOGGER.warning("Intro Subtitle: No video files found to process.")
            return self._org_path

        await self._send_status("intro")

        last_output = None
        overrides = {}

        # --- Collect overrides ---
        if (
            isinstance(self.listener.video_mode, list)
            and len(self.listener.video_mode) >= 4
        ):
            ed = self.listener.video_mode[3] or {}
            if ed.get("font_size"):
                overrides["font_size"] = int(ed["font_size"])
            if ed.get("position"):
                overrides["position"] = ed["position"]
            if ed.get("style"):
                overrides["style"] = ed["style"]
            if ed.get("text"):
                overrides["text"] = ed["text"]
            if ed.get("char_ms"):
                overrides["char_ms"] = int(ed["char_ms"])
            if ed.get("colors"):
                overrides["colors"] = ed["colors"]

        for file in file_list:
            self.path = file
            self.listener.size = await get_path_size(self.path)
            tmp_dir = Path(self.path).parent

            has_subs, sub_stream_info, all_streams = await check_embedded_subtitles(
                self.path
            )

            try:
                from ..ext_utils.intro_subtitle_utils import (
                    _get_user_settings as _isu_get_settings,
                )

                settings_tmp = _isu_get_settings(self.listener.user_id, overrides)

                # --- Strict mode validation: only "new" (default) and "existing" ---
                user_mode = (
                    getattr(self.listener, "user_dict", {}).get(
                        "INTRO_SUBTITLE_MODE", "new"
                    )
                    or "new"
                ).lower()

                # Ensure only valid modes are used
                if user_mode not in ["new", "existing"]:
                    LOGGER.warning(
                        f"Invalid intro subtitle mode '{user_mode}', defaulting to 'new'"
                    )
                    mode_pref = "new"
                else:
                    mode_pref = user_mode

                # Force new mode behavior (ignore existing subtitles)
                if mode_pref == "new":
                    has_subs = False
                    LOGGER.info(
                        "Intro subtitle mode: 'new' - will always create new subtitle (ignoring embedded subs)"
                    )
                else:
                    LOGGER.info(
                        "Intro subtitle mode: 'existing' - will modify embedded subtitle if available"
                    )

            except Exception:
                mode_pref = "new"
                LOGGER.info(
                    "Exception in subtitle mode detection, defaulting to 'new' mode"
                )

            cmd, out_path = None, None
            temp_sub_files = []

            try:
                if has_subs and sub_stream_info and all_streams:
                    # --- Modify existing subtitle ---
                    LOGGER.info(f"Modifying existing subtitle for: {self.path}")

                    extracted_sub_path, sub_format = await extract_subtitle(
                        self.path, sub_stream_info, tmp_dir
                    )

                    if extracted_sub_path:
                        temp_sub_files.append(extracted_sub_path)

                    if not extracted_sub_path:
                        LOGGER.error(
                            "Subtitle extraction failed. Falling back to adding new subtitle."
                        )
                        has_subs = False

                    else:
                        if sub_format in ("ass", "ssa"):
                            sub_format = "ass"

                        if sub_format not in ("ass", "ssa", "srt"):
                            try:
                                srt_path = await convert_subtitle_to_srt(
                                    extracted_sub_path
                                )
                                if srt_path:
                                    temp_sub_files.append(srt_path)
                                    extracted_sub_path = srt_path
                                    sub_format = "srt"
                            except Exception:
                                pass

                        modified_sub_path = await insert_intro_into_subtitle(
                            extracted_sub_path,
                            sub_format,
                            self.listener.user_id,
                            overrides,
                        )

                        if modified_sub_path:
                            temp_sub_files.append(modified_sub_path)

                        if not modified_sub_path:
                            LOGGER.error(
                                "Failed to insert intro into subtitle. Aborting for this file."
                            )
                            last_output = self.path
                            continue

                        cmd, out_path = build_intro_replace_cmd(
                            self.path, modified_sub_path, sub_stream_info, all_streams
                        )

                if not has_subs:
                    if mode_pref == "existing":
                        LOGGER.info(
                            f"Intro subtitle mode 'existing': No embedded subtitle found in {self.path}. Skipping intro subtitle injection."
                        )
                        last_output = self.path
                        continue

                    # --- Add new subtitle (default path) ---
                    LOGGER.info(
                        f"No valid embedded subtitle found. Creating and adding a new one for: {self.path}"
                    )

                    from ..ext_utils.intro_subtitle_utils import (
                        _is_customized_subtitle,
                    )

                    # Auto-detect format based on customization
                    # Use ASS for customized subtitles (styling, effects, positioning, etc.)
                    # Use SRT for plain subtitles (no customization)
                    is_customized = _is_customized_subtitle(
                        self.listener.user_id, overrides
                    )

                    if is_customized:
                        sub_path = await generate_intro_ass(
                            self.listener.user_id,
                            self.path,
                            overrides=overrides,
                        )
                        sub_type = "ass"
                        LOGGER.info(
                            "Using ASS format for customized intro subtitle (styling/effects applied)"
                        )
                    else:
                        sub_path = await generate_intro_srt(
                            self.listener.user_id,
                            self.path,
                            overrides=overrides,
                        )
                        sub_type = "srt"
                        LOGGER.info(
                            "Using SRT format for plain intro subtitle (no customization)"
                        )

                    if not sub_path:
                        LOGGER.error(
                            f"Failed to generate intro subtitle file (type: {sub_type}). Aborting for this file."
                        )
                        last_output = self.path
                        continue

                    temp_sub_files.append(sub_path)

                    from pathlib import Path as _Path

                    p = _Path(self.path)
                    out_path = str(p.with_name(f"{p.stem}_intro.mkv"))

                    try:
                        existing_sub_count = len(
                            [
                                s
                                for s in (all_streams or [])
                                if s.get("codec_type") == "subtitle"
                            ]
                        )
                    except Exception:
                        existing_sub_count = 0

                    new_sub_index = existing_sub_count
                    title = "Intro"

                    cmd = [
                        BinConfig.FFMPEG_NAME,
                        "-hide_banner",
                        "-y",
                        "-loglevel",
                        "error",
                        "-i",
                        self.path,
                        "-i",
                        str(sub_path),
                        "-map",
                        "0",
                        "-map",
                        "1",
                        "-c",
                        "copy",
                        "-disposition:s",
                        "0",
                        f"-disposition:s:{new_sub_index}",
                        "default+forced",
                        f"-metadata:s:s:{new_sub_index}",
                        "language=eng",
                        f"-metadata:s:s:{new_sub_index}",
                        f"title={title}",
                        "-progress",
                        "pipe:1",
                        out_path,
                    ]

                # --- Run ffmpeg ---
                if cmd and out_path:
                    self.outfile = out_path
                    await self._send_status("intro")
                    ok = await self._run_cmd(cmd)

                    if ok and await aiopath.exists(out_path):
                        last_output = out_path
                        if self.path != out_path and await aiopath.exists(self.path):
                            await clean_target(self.path)
                    else:
                        LOGGER.error(
                            f"FFmpeg operation failed for {self.path}. Original file kept."
                        )
                        last_output = self.path

                else:
                    LOGGER.error(
                        f"Could not generate FFmpeg command for {self.path}. Original file kept."
                    )
                    last_output = self.path

            except Exception as e:
                LOGGER.error(
                    f"An unexpected error occurred during intro_sub for {self.path}: {e}",
                    exc_info=True,
                )
                last_output = self.path

            finally:
                for temp_file in temp_sub_files:
                    if temp_file and await aiopath.exists(temp_file):
                        await clean_target(str(temp_file))

            if self.listener.is_cancelled:
                return

        return await self._final_path(last_output or self._org_path)

    async def _multi_res_encode(self, **kwargs):
        """Handle multi-resolution encoding of videos"""
        user_dict = self.listener.user_dict

        # Check if multi-resolution encoding is enabled
        if not user_dict.get("VIDEO_ENCODE_MULTI_RESOLUTION", False):
            LOGGER.info(
                "Multi-resolution encoding not enabled, falling back to regular convert"
            )
            return await self._vid_convert(**kwargs)

        # Set mode for multi-resolution encoding to ensure proper status display
        self.mode = "multi_res"

        LOGGER.info(f"Starting multi-resolution encoding for: {self.path}")

        try:
            # Use the enhanced multi-resolution encoding function
            encoded_files = await multi_resolution_encode(
                self.path,
                self.listener.user_id,
                self.listener,
                self._gid,
                ospath.dirname(self.path),
            )

            if encoded_files and len(encoded_files) > 0:
                # If we got multiple files or a ZIP, return the first/main file
                self.outfile = encoded_files[0]
                LOGGER.info(
                    f"Multi-resolution encoding completed: {len(encoded_files)} files"
                )
                return encoded_files[0]
            else:
                LOGGER.warning(
                    "Multi-resolution encoding returned no files, keeping original"
                )
                return self.path

        except Exception as e:
            LOGGER.error(f"Error in multi-resolution encoding: {e}")
            # Fallback to regular conversion on error
            return await self._vid_convert(**kwargs)
