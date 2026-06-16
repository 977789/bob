"""
Utilities for generating FFmpeg commands.
Enhanced with better error handling and resource management.
"""

import asyncio
import gc  # Added for memory management
import os
import psutil  # Added for process management
import re
import subprocess
import tempfile
import time
from json import loads
from os import path as ospath
from pathlib import Path
from asyncio import create_subprocess_exec
from asyncio.subprocess import PIPE

from bot import LOGGER, cpu_no, user_data, task_dict, task_dict_lock, status_dict

# Corrected import for Config
from bot.core.config_manager import BinConfig, Config

# from .metadata_helper import METADATA_MAPPINGS # REMOVED to break circular import
from aiofiles.os import path as aiopath, remove  # For checking existence

# Moved import to function to avoid circular import
from bot.helper.telegram_helper.message_utils import update_status_message
from bot.helper.mirror_leech_utils.status_utils.ffmpeg_status import FFMpegStatus
from pycountry import languages as _pyc_languages


def _force_gc():
    """Force garbage collection to free memory"""
    try:
        gc.collect()
        gc.collect()  # Call twice to ensure cleanup
    except Exception as e:
        LOGGER.debug(f"Error during garbage collection: {e}")


async def _create_memory_aware_subprocess(
    *args, max_retries: int = 3, wait_for_resources: bool = True, **kwargs
):
    """
    Create subprocess with memory awareness and error handling.

    Args:
        *args: Arguments for asyncio.create_subprocess_exec
        max_retries: Maximum number of retries for resource-related failures
        wait_for_resources: Whether to wait for resources before execution
        **kwargs: Keyword arguments for asyncio.create_subprocess_exec

    Returns:
        subprocess process object or None if failed
    """
    from .resource_monitor import resource_monitor

    retry_count = 0
    while retry_count < max_retries:
        try:
            # Wait for resources if requested and needed
            if wait_for_resources:
                if resource_monitor.is_memory_critical():
                    LOGGER.info(
                        "Memory critical, waiting for resources before subprocess execution"
                    )
                    if not await resource_monitor.wait_for_resources(max_wait=30):
                        LOGGER.warning("Resource wait timeout, proceeding with caution")

                # Force cleanup before subprocess
                resource_monitor.force_cleanup(aggressive=True)

                # Additional memory check with more conservative threshold
                try:
                    import psutil

                    available_memory = psutil.virtual_memory().available / (1024 * 1024)
                    if available_memory < 250:  # Less than 250MB available
                        LOGGER.warning(
                            f"Very low memory before subprocess: {available_memory:.1f}MB, "
                            "performing additional cleanup"
                        )
                        _force_gc()
                        await asyncio.sleep(1)  # Give time for cleanup
                except ImportError:
                    pass

            # Add resource limits to subprocess if not already specified
            if "preexec_fn" not in kwargs and hasattr(os, "setpriority"):

                def set_limits():
                    try:
                        # Set low priority
                        os.nice(10)
                        # Set memory limit if available (Linux only)
                        if hasattr(os, "setrlimit"):
                            import resource

                            # Limit virtual memory to 1GB (in bytes) - more conservative
                            os.setrlimit(
                                resource.RLIMIT_AS,
                                (
                                    800 * 1024 * 1024,
                                    1024 * 1024 * 1024,
                                ),  # 800MB soft, 1GB hard
                            )
                    except (OSError, AttributeError, ImportError):
                        pass

                kwargs["preexec_fn"] = set_limits

            # Create the subprocess
            process = await asyncio.create_subprocess_exec(*args, **kwargs)

            LOGGER.debug(
                f"Subprocess created successfully (PID: {process.pid if process else 'N/A'})"
            )
            return process

        except (OSError, MemoryError) as e:
            error_msg = str(e).lower()
            if any(
                x in error_msg
                for x in [
                    "resource temporarily unavailable",
                    "cannot allocate memory",
                    "out of memory",
                ]
            ):
                retry_count += 1
                LOGGER.warning(
                    f"Resource-related error on attempt {retry_count}/{max_retries}: {e}"
                )

                if retry_count < max_retries:
                    # Force aggressive cleanup and wait before retry
                    resource_monitor.force_cleanup(aggressive=True)
                    await asyncio.sleep(2 * retry_count)  # Progressive backoff
                    continue
                else:
                    LOGGER.error(
                        f"Failed to create subprocess after {max_retries} attempts: {e}"
                    )
                    return None
            else:
                # Non-resource related error, don't retry
                LOGGER.error(f"Subprocess creation failed with non-resource error: {e}")
                return None

        except Exception as e:
            LOGGER.error(f"Unexpected error creating subprocess: {e}")
            return None

    return None


def _set_process_priority():
    """Set process priority to low to prevent system overload"""
    try:
        # Set nice value (lower priority)
        os.nice(10)  # Increase niceness (lower priority)

        # Set I/O priority if available
        try:
            # Try to set I/O priority to idle class
            subprocess.run(
                ["ionice", "-c", "3", "-p", str(os.getpid())],
                check=False,
                capture_output=True,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            # ionice not available, continue without it
            pass

        # Limit CPU affinity if possible (use only first CPU)
        try:
            current_process = psutil.Process()
            cpu_count = psutil.cpu_count()
            if cpu_count > 1:
                # Use only the first CPU core
                current_process.cpu_affinity([0])
        except (psutil.AccessDenied, AttributeError):
            # Can't set CPU affinity, continue without it
            pass

    except (OSError, PermissionError) as e:
        LOGGER.debug(f"Could not set process priority: {e}")
    except Exception as e:
        LOGGER.debug(f"Error setting process priority: {e}")


def _monitor_memory_usage():
    """Enhanced memory monitoring with global resource tracking"""
    try:
        from .resource_monitor import resource_monitor

        # Use global resource monitor for consistency
        memory_info = resource_monitor.get_memory_info()
        memory_mb = memory_info["used_mb"]
        available_mb = memory_info["available_mb"]

        # More aggressive memory cleanup for lower thresholds
        if available_mb < 150:  # Critical threshold reduced to 150MB
            LOGGER.warning(
                f"CRITICAL memory usage: {memory_mb:.1f}MB used, only {available_mb:.1f}MB available"
            )
            resource_monitor.force_cleanup(aggressive=True)
            return memory_mb

        elif available_mb < 250:  # High threshold reduced to 250MB
            LOGGER.warning(
                f"High memory usage detected: {memory_mb:.1f}MB used, {available_mb:.1f}MB available"
            )
            resource_monitor.force_cleanup()
            return memory_mb

        # Periodic cleanup
        resource_monitor.periodic_cleanup_if_needed()
        return memory_mb

    except ImportError:
        # Fallback to original psutil-based monitoring
        try:
            process = psutil.Process()
            memory_info = process.memory_info()
            memory_mb = memory_info.rss / 1024 / 1024  # RSS in MB

            # More aggressive memory cleanup for lower thresholds
            if memory_mb > 300:  # Reduced from 512MB to 300MB
                LOGGER.warning(
                    f"High memory usage detected: {memory_mb:.1f}MB, forcing cleanup"
                )
                _force_gc()
                # Force additional cleanup for very high usage
                if memory_mb > 512:
                    _force_gc()
                    time.sleep(0.1)  # Brief pause for cleanup

            return memory_mb
        except Exception as e:
            LOGGER.debug(f"Error monitoring memory: {e}")
            return 0
    except Exception as e:
        LOGGER.debug(f"Error with resource monitor: {e}")
        return 0


async def detect_4k_content(input_path: str) -> tuple[bool, dict]:
    """Detect if content is 4K resolution and get video info for memory planning"""
    try:
        # Get video information using ffprobe
        cmd = [
            BinConfig.FFPROBE_NAME if hasattr(BinConfig, "FFPROBE_NAME") else "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            input_path,
        ]

        process = await _create_memory_aware_subprocess(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            max_retries=2,
            wait_for_resources=True,
        )

        if not process:
            LOGGER.error(f"Failed to create subprocess for 4K detection: {input_path}")
            return False, {}

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            LOGGER.debug(f"ffprobe failed for {input_path}: {stderr.decode()}")
            return False, {}

        info = loads(stdout.decode())
        video_info = {}

        # Find video stream
        for stream in info.get("streams", []):
            if stream.get("codec_type") == "video":
                width = stream.get("width", 0)
                height = stream.get("height", 0)
                duration = float(stream.get("duration", 0))
                bit_rate = int(stream.get("bit_rate", 0))

                video_info = {
                    "width": width,
                    "height": height,
                    "duration": duration,
                    "bit_rate": bit_rate,
                    "is_4k": height >= 2160 or width >= 3840,
                    "is_high_res": height >= 1440 or width >= 2560,  # 1440p+
                    "pixel_count": width * height,
                }

                LOGGER.info(
                    f"Video info for {input_path}: {width}x{height}, 4K: {video_info['is_4k']}"
                )
                return video_info["is_4k"], video_info

    except Exception as e:
        LOGGER.debug(f"Error detecting 4K content: {e}")

    return False, {}


def _ff_threads(is_4k: bool = False, pixel_count: int = 0):
    """Return optimized threads value for FFmpeg operations using simplified logic.

    Uses f"{max(1, cpu_no // 2)}" as base with VPS deployment optimization.

    Args:
        is_4k: Whether the content is 4K resolution (unused - kept for compatibility)
        pixel_count: Total pixel count for memory estimation (unused - kept for compatibility)
    """
    try:
        # Get available CPU cores
        available_cores = cpu_no or os.cpu_count() or 1

        # Check if VPS deployment is enabled for better resource utilization
        is_vps_deploy = getattr(Config, "VPS_DEPLOY", False)

        if is_vps_deploy:
            # For VPS deployment with high-spec systems (like 10-core VPS)
            # Use up to 80% of available cores for better performance
            max_threads = max(1, int(available_cores * 0.8))
            LOGGER.info(
                f"VPS deployment: using {max_threads} threads (80% of {available_cores} cores)"
            )
            return max_threads
        else:
            # Use standard formula: half of available CPU cores
            threads = max(1, available_cores // 2)
            return threads

    except Exception as e:
        LOGGER.debug(f"Error in _ff_threads calculation: {e}")
        # Fallback to safe default
        return max(1, (cpu_no or os.cpu_count() or 2) // 2)


async def validate_ffmpeg_availability():
    """Check if FFmpeg is available and get version information."""
    try:
        process = await _create_memory_aware_subprocess(
            BinConfig.FFMPEG_NAME,
            "-version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            max_retries=1,
            wait_for_resources=False,  # Version check doesn't need resource waiting
        )

        if not process:
            LOGGER.error("Failed to create subprocess for FFmpeg version check")
            return False
        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            version_output = stdout.decode("utf-8", errors="ignore")
            LOGGER.debug(f"FFmpeg available: {version_output.split(chr(10))[0]}")
            return True
        else:
            LOGGER.error(
                f"FFmpeg version check failed: {stderr.decode('utf-8', errors='ignore')}"
            )
            return False

    except Exception as e:
        LOGGER.error(f"Error checking FFmpeg availability: {e}")
        return False


def build_standard_ffmpeg_cmd(
    input_files: list,
    output_file: str,
    stream_mapping: list = None,
    codec_params: dict = None,
    additional_params: list = None,
    is_4k: bool = False,
    pixel_count: int = 0,
) -> list:
    """
    Build standardized FFmpeg command with aggressive resource limits.

    Args:
        input_files: List of input file paths
        output_file: Output file path
        stream_mapping: Custom stream mapping (e.g., ['-map', '0:v', '-map', '1:a'])
        codec_params: Codec parameters (e.g., {'video': 'libx264', 'audio': 'aac'})
        additional_params: Additional FFmpeg parameters
        is_4k: Whether the content is 4K resolution
        pixel_count: Total pixel count for memory estimation

    Returns:
        Complete FFmpeg command as list with resource limitations
    """
    # Force garbage collection before building command
    _force_gc()

    # Get 4K-aware thread count
    thread_count = _ff_threads(is_4k, pixel_count)

    cmd = [
        BinConfig.FFMPEG_NAME,
        "-hide_banner",
        "-y",  # Overwrite output files
        "-loglevel",
        "error",
        "-nostdin",
        "-threads",
        str(thread_count),
        # Add additional CPU/memory limiting options
        "-thread_type",
        "slice",  # Use slice threading (more memory efficient)
        "-thread_queue_size",
        "4" if is_4k else "8",  # Even smaller queue for 4K content
    ]

    # Add 4K-specific memory optimizations
    if is_4k or pixel_count > 8000000:
        cmd.extend(
            [
                "-max_muxing_queue_size",
                "64",  # Further reduced queue for 4K to prevent memory issues
                "-avoid_negative_ts",
                "make_zero",  # Reduce processing overhead
                "-max_interleave_delta",
                "0",  # Reduce memory usage during muxing
                "-fflags",
                "+genpts",  # Generate timestamps to reduce processing
            ]
        )
    elif pixel_count > 3686400:  # High resolution
        cmd.extend(
            [
                "-max_muxing_queue_size",
                "128",  # Reduced from 256 for better memory management
                "-max_interleave_delta",
                "0",
            ]
        )

    # Add input files
    for input_file in input_files:
        cmd.extend(["-i", input_file])

    # Add stream mapping
    if stream_mapping:
        cmd.extend(stream_mapping)
    else:
        # Default: map first input completely
        cmd.extend(["-map", "0"])

    # Add codec parameters with conservative settings
    if codec_params:
        for stream_type, codec in codec_params.items():
            cmd.extend([f"-c:{stream_type[0]}", codec])

            # Add conservative encoding settings for video
            if stream_type.startswith("video") or stream_type.startswith("v"):
                if codec in ["libx264", "h264"]:
                    # Add conservative x264 settings, more aggressive for 4K
                    if is_4k:
                        cmd.extend(
                            [
                                "-preset",
                                "ultrafast",  # Ultra-fast for 4K to reduce CPU
                                "-tune",
                                "zerolatency",  # Low latency tuning
                                "-x264opts",
                                "ref=1:bframes=0:me=dia:subq=1:trellis=0:rc-lookahead=10",
                            ]
                        )
                    else:
                        cmd.extend(
                            [
                                "-preset",
                                "veryfast",  # Fast preset to reduce CPU usage
                                "-tune",
                                "film",  # General purpose tuning
                                "-x264opts",
                                "ref=1:bframes=1:me=dia:subq=2:trellis=0",
                            ]
                        )
                elif codec in ["libx265", "hevc"]:
                    # Add conservative x265 settings
                    cmd.extend(
                        [
                            "-preset",
                            "veryfast",
                            "-x265-params",
                            "ref=1:bframes=1:rd=1:me=1",  # Minimal settings
                        ]
                    )
    else:
        # Default: copy all streams (most CPU efficient)
        cmd.extend(["-c", "copy"])

    # Add memory and CPU limiting parameters
    cmd.extend(
        [
            "-max_muxing_queue_size",
            "128",  # Limit muxing queue to save memory
            "-fflags",
            "+genpts+discardcorrupt",  # Handle corrupt data gracefully
        ]
    )

    # Add additional parameters
    if additional_params:
        cmd.extend(additional_params)

    # Add output file
    cmd.append(output_file)

    # Monitor memory usage before returning
    _monitor_memory_usage()

    return cmd


async def get_ffmpeg_metadata_cmd(
    input_path: str,
    output_path: str,
    user_metadata: dict,
    thumbnail_to_attach: str = None,
    text_content_to_attach: str = None,
):
    """
    Generates a complete FFmpeg command for setting metadata and attachments with enhanced resource management.
    Returns the command list and a boolean indicating if any action is to be performed.
    Also returns path to a temporary text file if one was created for text attachment.
    """
    # Force garbage collection before starting memory-intensive operations
    _force_gc()

    # Check available memory and adjust processing accordingly
    try:
        import psutil

        available_memory = psutil.virtual_memory().available / (1024 * 1024)  # MB
        if available_memory < 100:  # Less than 100MB available
            LOGGER.warning(
                f"Low memory available: {available_memory:.1f}MB. May need to skip processing."
            )
            return False, [], ""
    except ImportError:
        pass  # psutil not available, continue normally

    # Detect 4K content for memory optimization
    is_4k, video_info = await detect_4k_content(input_path)
    pixel_count = video_info.get("pixel_count", 0)

    if is_4k:
        LOGGER.info(f"4K content detected for metadata processing: {input_path}")
        # Additional cleanup for 4K processing
        _force_gc()

    ffprobe_cmd = [
        BinConfig.FFPROBE_NAME,
        "-hide_banner",
        "-loglevel",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        input_path,
    ]
    process = await _create_memory_aware_subprocess(
        *ffprobe_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        max_retries=1,
        wait_for_resources=False,
    )

    if not process:
        LOGGER.error(f"Failed to create subprocess for stream detection: {input_path}")
        return []

    stdout, stderr_ffprobe = await process.communicate()
    # LOGGER.info(f"ffmpeg_utils: ffprobe raw JSON output:\n{stdout.decode(errors='ignore')}") # REMOVED DETAILED LOGGING
    media_streams_info = []
    if process.returncode == 0:
        try:
            media_streams_info = loads(stdout.decode(errors="ignore")).get(
                "streams", []
            )
        except Exception as e_parse:
            LOGGER.error(f"Error parsing ffprobe output for {input_path}: {e_parse}")
    else:
        LOGGER.error(
            f"ffprobe failed for {input_path}: {stderr_ffprobe.decode(errors='ignore')}"
        )

    # Build dynamic variables for metadata templates
    def _map_lang(code: str) -> str:
        c = str(code or "").strip().lower()
        if not c or c in {"unknown", "und", "none"}:
            return c
        try:
            if len(c) == 2:
                lang = _pyc_languages.get(alpha_2=c)
            elif len(c) == 3:
                lang = _pyc_languages.get(alpha_3=c)
            else:
                return c
            return lang.name if lang else c
        except Exception:
            return c

    async def _collect_langs(streams_list, codec_type: str) -> str:
        langs = []
        try:
            # Import here to avoid circular import
            from bot.helper.hunt_utils.command_gen import get_streams

            # Prefer fresh get_streams for accurate tags
            ffprobe_streams = streams_list or (await get_streams(input_path)) or []
            for s in ffprobe_streams:
                if s.get("codec_type") == codec_type:
                    tags = s.get("tags") or {}
                    lang_val = tags.get("language") or tags.get("LANGUAGE")
                    if lang_val:
                        name = _map_lang(lang_val)
                        if name and name not in langs:
                            langs.append(name)
        except Exception:
            pass
        return "/".join(langs)

    filename = ospath.basename(input_path)
    basename = ospath.splitext(filename)[0]
    extension = ospath.splitext(filename)[1].lstrip(".")
    year_match = re.search(r"(19|20)\d{2}", basename)
    year_from_name = year_match.group(0) if year_match else ""

    # Since _collect_langs is async, evaluate now
    audiolang_val = await _collect_langs(media_streams_info, "audio")
    sublang_val = await _collect_langs(media_streams_info, "subtitle")
    dynamic_vars = {
        "filename": filename,
        "basename": basename,
        "extension": extension,
        "audiolang": audiolang_val,
        "sublang": sublang_val,
        "year": year_from_name,
    }

    def _expand_dynamic_vars(value: str) -> str:
        try:
            return re.sub(
                r"\{([a-zA-Z0-9_]+)\}",
                lambda m: dynamic_vars.get(m.group(1).lower(), m.group(0)),
                str(value),
            )
        except Exception:
            return str(value)

    # Start of new stream mapping logic
    stream_maps = []
    if media_streams_info:
        for stream in media_streams_info:
            codec_type = stream.get("codec_type")
            # Basic filter for valid, non-attachment streams
            if codec_type in ["video", "audio", "subtitle"]:
                # Check for attached pictures, which can be mislabeled as video streams
                if stream.get("disposition", {}).get("attached_pic"):
                    continue
                # For video streams, ensure they have dimensions. This filters out invalid "cover art" streams.
                if codec_type == "video" and not (
                    stream.get("width") and stream.get("height")
                ):
                    continue
                stream_maps.extend(["-map", f"0:{stream['index']}"])

    # If after filtering we have no streams to map, it's an error or empty file.
    # However, to avoid breaking things, we can fall back to default mapping,
    # or better, log an error. For now, we proceed if stream_maps is not empty.
    if not stream_maps:
        LOGGER.warning(
            f"Could not determine valid streams for {input_path}. Falling back to default '-map 0'. This may fail."
        )
        # Fallback to original behavior if no valid streams were found by our logic
        stream_maps.extend(["-map", "0"])

    base_cmd = [
        BinConfig.FFMPEG_NAME,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-i",
        input_path,
    ]
    base_cmd.extend(stream_maps)  # Add the dynamically generated stream maps
    base_cmd.extend(
        [
            "-c",
            "copy",  # Copy all streams by default
            "-c:s",
            "copy",  # Explicitly copy subtitle streams
            "-threads",
            str(_ff_threads(is_4k, pixel_count)),  # Use 4K-aware threading
        ]
    )

    # Add 4K-specific optimizations to base command
    if is_4k or pixel_count > 8000000:
        base_cmd.extend(
            [
                "-max_muxing_queue_size",
                "64",  # Smaller queue for 4K metadata operations
                "-avoid_negative_ts",
                "make_zero",
            ]
        )
    elif pixel_count > 3686400:  # High resolution
        base_cmd.extend(
            [
                "-max_muxing_queue_size",
                "128",
            ]
        )

    final_cmd_parts = []

    # REMOVED: Explicit global and per-stream tag clearing
    # REMOVED: Disposition clearing

    # Define stream type to ffmpeg prefix mapping before it's used

    # 2. Apply User-Specific Metadata
    metadata_tags_applied_count = 0

    def parse_metadata_string(metadata_str):
        meta_dict = {}
        if "|" in metadata_str or "=" in metadata_str:
            for item in metadata_str.split("|"):
                if "=" in item:
                    key, value = item.split("=", 1)
                    meta_dict[key.strip()] = _expand_dynamic_vars(value.strip())
        else:
            # Simple format: a single value for default tags
            default_keys = [
                "title",
                "author",
                "artist",
                "comment",
                "album",
                "genre",
                "date",
                "website",  # Added website field for default metadata
            ]
            expanded = _expand_dynamic_vars(metadata_str)
            meta_dict = {key: expanded for key in default_keys}
        return meta_dict

    # General metadata
    if gen_meta_str := user_metadata.get("GEN_METADATA"):
        for key, value in parse_metadata_string(gen_meta_str).items():
            final_cmd_parts.extend(["-metadata", f"{key}={value}"])
            metadata_tags_applied_count += 1

    # Stream-specific metadata
    stream_meta_map = {"VID_METADATA": "v", "AUD_METADATA": "a", "SUB_METADATA": "s"}

    for meta_key, specifier in stream_meta_map.items():
        if meta_str := user_metadata.get(meta_key):
            for key, value in parse_metadata_string(meta_str).items():
                if ":" in key:
                    key, stream_index = key.split(":", 1)
                    final_cmd_parts.extend(
                        [f"-metadata:s:{specifier}:{stream_index}", f"{key}={value}"]
                    )
                else:
                    final_cmd_parts.extend(
                        [f"-metadata:s:{specifier}", f"{key}={value}"]
                    )
                metadata_tags_applied_count += 1

    # 3. Attachment Handling
    attachment_ffmpeg_idx_counter = 0
    attachments_added_this_run = False
    temp_text_file_created_path = None

    if thumbnail_to_attach and await aiopath.exists(thumbnail_to_attach):
        thumb_ext = ospath.splitext(thumbnail_to_attach)[1].lower()
        mime = ""
        if thumb_ext in [".jpg", ".jpeg"]:
            mime = "image/jpeg"
        elif thumb_ext == ".png":
            mime = "image/png"
        if mime:
            final_cmd_parts.extend(
                [
                    "-attach",
                    thumbnail_to_attach,
                    f"-metadata:s:t:{attachment_ffmpeg_idx_counter}",
                    f"mimetype={mime}",
                ]
            )
            attachment_ffmpeg_idx_counter += 1
            attachments_added_this_run = True
        else:
            LOGGER.warning(
                f"Unsupported thumbnail extension for attachment: {thumb_ext}"
            )

    if text_content_to_attach:
        try:
            file_dir_for_temp = ospath.dirname(input_path)
            temp_text_fd, temp_text_path = tempfile.mkstemp(
                suffix=".txt", text=True, dir=file_dir_for_temp
            )
            with os.fdopen(temp_text_fd, "w", encoding="utf-8") as tmp_f:
                tmp_f.write(text_content_to_attach)
            temp_text_file_created_path = temp_text_path

            final_cmd_parts.extend(
                [
                    "-attach",
                    temp_text_file_created_path,
                    f"-metadata:s:t:{attachment_ffmpeg_idx_counter}",
                    "mimetype=text/plain",
                ]
            )
            attachment_ffmpeg_idx_counter += 1
            attachments_added_this_run = True
        except Exception as e_txt_attach:
            LOGGER.error(f"Failed to create/prepare text attachment: {e_txt_attach}")
            if temp_text_file_created_path and await aiopath.exists(
                temp_text_file_created_path
            ):
                await aiopath.remove(temp_text_file_created_path)
            temp_text_file_created_path = None

    input_file_ext_lower = ospath.splitext(input_path)[1].lower()
    # Extended list of subtitle formats to handle properly (no container forcing)
    is_sub_file = input_file_ext_lower in [
        ".srt",
        ".ass",
        ".ssa",
        ".vtt",
        ".sub",
        ".idx",
        ".sup",
        ".smi",
        ".sami",
        ".ttml",
    ]
    # Do not force matroska container for subtitle-only files to avoid attachment errors
    if attachments_added_this_run and not is_sub_file:
        final_cmd_parts.extend(["-f", "matroska"])

    action_to_be_performed = (
        metadata_tags_applied_count > 0 or attachments_added_this_run
    )

    if not action_to_be_performed:
        if temp_text_file_created_path and await aiopath.exists(
            temp_text_file_created_path
        ):
            await aiopath.remove(temp_text_file_created_path)
        temp_text_file_created_path = None
        return [], False, None

    full_ffmpeg_cmd = base_cmd + final_cmd_parts
    full_ffmpeg_cmd.extend(["-progress", "pipe:1"])
    full_ffmpeg_cmd.extend([output_path, "-y"])

    return full_ffmpeg_cmd, True, temp_text_file_created_path


# Enhanced FFmpeg functionality for video tools


class FFmpegEncoderHelper:
    def __init__(self, input_path, output_path):
        self.input_path = input_path
        self.output_path = output_path
        self.start_time = time.time()
        self.progress_raw = 0.01  # Start with a tiny bit of progress so it shows up
        self.speed_raw = 0
        self.eta_raw = 0
        self.processed_bytes = 0
        self.total_bytes = (
            os.path.getsize(input_path) if os.path.exists(input_path) else 0
        )
        self.last_update_time = time.time()
        self.last_bytes = 0
        self.status_text = "Processing..."
        self.duration = None
        self.last_status_update = 0
        self.current_frame = 0
        self.total_frames = 0
        self.fps = 0
        self.ffmpeg_speed = 0.1  # Start with a small speed value to display
        self.bitrate = "N/A"
        self.encoding_time = "00:00:00"
        self.short_filename = os.path.basename(input_path) if input_path else "unknown"
        self.quality = ""
        self.preset = ""
        self.encoding_started = False  # Flag to track if encoding has started
        self._bytes_from_total_size = (
            False  # Flag to track if we got bytes from FFmpeg total_size
        )
        self._last_time_seconds = 0  # Track last time in seconds to detect stuck time
        self._stuck_time_count = 0  # Count how many times time was stuck

    def set_quality_preset(self, quality, preset, crf=23, audio_bitrate="128k"):
        """Set quality, preset, crf and audio_bitrate values for status display"""
        self.quality = quality
        self.preset = preset
        self.crf = crf
        self.audio_bitrate = audio_bitrate

    def update_progress(self, line):
        """Update progress based on FFmpeg output line, using FFmpeg's reported values directly"""
        try:
            # Store the complete FFmpeg progress line for debugging if needed
            if (
                "frame=" in line
                and "fps=" in line
                and "time=" in line
                and "speed=" in line
            ):
                self.ffmpeg_progress_line = line.strip()

                # Mark that encoding has started
                if not hasattr(self, "encoding_started") or not self.encoding_started:
                    self.encoding_started = True
                    LOGGER.info(
                        f"FFmpeg processing has started producing progress lines for {os.path.basename(self.input_path)}"
                    )

            # Extract time information - exactly as FFmpeg reports it
            time_match = re.search(r"time=(\d+:\d+:\d+\.\d+)", line)
            if time_match:
                self.encoding_time = time_match.group(1)

                # Also calculate seconds for progress percentage
                time_parts = re.search(r"time=(\d+):(\d+):(\d+)\.(\d+)", line)
                if time_parts:
                    hours, minutes, seconds, cs = map(int, time_parts.groups())
                    processed_time = hours * 3600 + minutes * 60 + seconds + cs / 100

                    # Detect if time is stuck (same value repeated while frames increase)
                    if (
                        abs(processed_time - self._last_time_seconds) < 0.1
                    ):  # Time hasn't changed significantly
                        self._stuck_time_count += 1
                        if (
                            self._stuck_time_count > 3
                        ):  # Time stuck for 3+ progress reports
                            LOGGER.warning(
                                f"FFmpeg time appears stuck at {processed_time}s - switching to frame-based progress"
                            )
                    else:
                        self._stuck_time_count = 0  # Reset counter if time progressed
                        self._last_time_seconds = processed_time

                    # Use FFmpeg's reported time directly for progress - but validate it makes sense
                    if (
                        self.duration
                        and self.duration > 0
                        and self._stuck_time_count <= 3
                    ):
                        calculated_progress = (processed_time / self.duration) * 100

                        # If calculated progress exceeds 100% but we're still processing,
                        # the duration might be wrong - use frame-based progress instead
                        if (
                            calculated_progress > 100
                            and hasattr(self, "current_frame")
                            and self.current_frame > 0
                        ):
                            LOGGER.warning(
                                f"Progress calculation exceeds 100% ({calculated_progress:.2f}%) - duration might be incorrect. Using frame-based progress."
                            )
                            # Don't update progress_raw, let frame-based calculation handle it
                        else:
                            self.progress_raw = min(100, calculated_progress)

                        # Ensure we always have some progress shown, even at the start
                        if self.progress_raw < 0.1 and processed_time > 0:
                            self.progress_raw = 0.1

            # Extract fps - direct from FFmpeg
            fps_match = re.search(r"fps=\s*([0-9.]+)", line)
            if fps_match:
                try:
                    self.fps = float(fps_match.group(1))
                    # If we have FPS but no speed, set a minimal speed to show
                    if self.ffmpeg_speed <= 0:
                        self.ffmpeg_speed = 0.1
                except ValueError:
                    pass

            # Extract current frame - direct from FFmpeg
            frame_match = re.search(r"frame=\s*(\d+)", line)
            if frame_match:
                try:
                    new_frame = int(frame_match.group(1))
                    # Only update if the new frame value is greater
                    if new_frame > self.current_frame:
                        self.current_frame = new_frame

                        # Use frame-based progress when we have total frames and either:
                        # 1. No duration available, OR
                        # 2. Time-based progress is unreliable (>100%), OR
                        # 3. Time appears to be stuck
                        if self.total_frames > 0:
                            frame_progress = (
                                self.current_frame / self.total_frames
                            ) * 100
                            if 0 <= frame_progress <= 100:
                                # Use frame-based progress if time-based is unavailable, unreliable, or stuck
                                if (
                                    not self.duration
                                    or self.progress_raw > 100
                                    or self.progress_raw <= 0
                                    or self._stuck_time_count > 3
                                ):
                                    self.progress_raw = frame_progress
                                    LOGGER.debug(
                                        f"Using frame-based progress: {frame_progress:.2f}% (frame {self.current_frame}/{self.total_frames})"
                                    )

                        # If we have frames but no progress, set a minimal progress value
                        if self.progress_raw <= 0 and self.current_frame > 0:
                            self.progress_raw = 0.1
                except ValueError:
                    pass

            # Extract speed - exactly as FFmpeg reports it
            speed_match = re.search(r"speed=\s*([0-9.]+)x", line)
            if speed_match:
                try:
                    self.ffmpeg_speed = float(speed_match.group(1))
                except ValueError:
                    pass

            # Extract bitrate - exactly as FFmpeg reports it
            bitrate_match = re.search(r"bitrate=\s*([0-9.]+\w+/s)", line)
            if bitrate_match:
                self.bitrate = bitrate_match.group(1)

            # Calculate speed and ETA based on time progress (more accurate for encoding)
            now = time.time()
            time_diff = now - self.last_update_time
            if time_diff >= 2.0:  # Update less frequently to reduce fluctuations
                # Calculate processed bytes by checking actual output file size
                try:
                    if os.path.exists(self.output_path):
                        actual_output_size = os.path.getsize(self.output_path)
                        if actual_output_size > 0:
                            self.processed_bytes = actual_output_size
                    elif self.current_frame > 0:
                        # Fallback: estimate based on progress
                        self.processed_bytes = max(
                            1024, int(self.total_bytes * (self.progress_raw / 100))
                        )
                except OSError:
                    # If file check fails, use progress-based estimation
                    if self.current_frame > 0:
                        self.processed_bytes = max(
                            1024, int(self.total_bytes * (self.progress_raw / 100))
                        )

                # Update speed based on file size change if available
                size_diff = self.processed_bytes - self.last_bytes
                if size_diff > 0:  # Only update if we've made progress
                    self.speed_raw = size_diff / time_diff
                    self.last_bytes = self.processed_bytes

                self.last_update_time = now

        except Exception as e:
            LOGGER.error(f"Error updating FFmpeg progress: {str(e)}")

    def set_duration(self, duration):
        """Set the total duration of the video"""
        self.duration = duration


async def get_video_duration_enhanced(file_path):
    """Get the duration of a video file using ffprobe"""
    cmd = [
        BinConfig.FFPROBE_NAME,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        file_path,
    ]
    try:
        process = await _create_memory_aware_subprocess(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            max_retries=1,
            wait_for_resources=False,
        )

        if not process:
            LOGGER.error(f"Failed to create subprocess for duration check: {file_path}")
            return None

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            LOGGER.error(f"Error getting video duration: {stderr.decode()}")
            return None

        return float(stdout.decode().strip())
    except (ValueError, TypeError) as e:
        LOGGER.error(f"Error parsing video duration: {str(e)}")
        return None
    except Exception as e:
        LOGGER.error(f"Unexpected error getting video duration: {str(e)}")
        return None


async def get_video_info_enhanced(file_path):
    """Get comprehensive video information using ffprobe"""
    cmd = [
        BinConfig.FFPROBE_NAME,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,avg_frame_rate,codec_name,bit_rate",
        "-of",
        "json",
        file_path,
    ]
    try:
        process = await _create_memory_aware_subprocess(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            max_retries=1,
            wait_for_resources=False,
        )

        if not process:
            LOGGER.error(f"Failed to create subprocess for video info: {file_path}")
            return {}

        stdout, stderr = await process.communicate()
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            LOGGER.error(f"Error getting video info: {stderr.decode()}")
            return {}

        result = loads(stdout.decode())
        return result.get("streams", [{}])[0] if "streams" in result else {}
    except Exception as e:
        LOGGER.error(f"Error parsing video info: {str(e)}")
        return {}


def get_quality_settings():
    """Get available quality presets for video encoding"""
    return {
        "1080p": {
            "scale": "scale=-1:1080:force_original_aspect_ratio=1:force_divisible_by=2",
            "bitrate": "2M",
            "maxrate": "2.5M",
            "bufsize": "4M",
        },
        "720p": {
            "scale": "scale=-1:720:force_original_aspect_ratio=1:force_divisible_by=2",
            "bitrate": "1.2M",
            "maxrate": "1.5M",
            "bufsize": "3M",
        },
        "480p": {
            "scale": "scale=-1:480:force_original_aspect_ratio=1:force_divisible_by=2",
            "bitrate": "600k",
            "maxrate": "800k",
            "bufsize": "1.5M",
        },
        "360p": {
            "scale": "scale=-1:360:force_original_aspect_ratio=1:force_divisible_by=2",
            "bitrate": "350k",
            "maxrate": "400k",
            "bufsize": "800k",
        },
        "Original": {},  # No resolution change
    }


def get_encoding_presets():
    """Get available FFmpeg encoding presets"""
    return [
        "ultrafast",
        "superfast",
        "veryfast",
        "faster",
        "fast",
        "medium",
        "slow",
        "slower",
        "veryslow",
    ]


async def enhance_ffmpeg_command_with_presets(
    base_cmd, user_dict, operation_type="encode"
):
    """
    Enhance FFmpeg command with user presets and quality settings.
    This replaces the basic encoding with advanced options from user settings.
    """
    if not user_dict:
        return base_cmd

    enhanced_cmd = base_cmd.copy()

    # Add encoding presets for video operations
    if operation_type == "encode" and user_dict.get("VIDEO_ENCODE_ENABLED", False):
        preset = user_dict.get("VIDEO_ENCODE_PRESET", "medium")
        crf = user_dict.get("VIDEO_ENCODE_CRF", 23)
        raw_audio_bitrate = user_dict.get("VIDEO_ENCODE_AUDIO_BITRATE", "128k")

        # Normalize audio bitrate to prevent ffmpeg errors
        def _normalize_audio_bitrate(raw):
            """Return a safe audio bitrate for ffmpeg."""
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
                return "128k"  # fallback
            except:
                return "128k"

        audio_bitrate = _normalize_audio_bitrate(raw_audio_bitrate)

        # Replace basic encoding parameters with advanced ones
        if "-c:v" in enhanced_cmd:
            cv_index = enhanced_cmd.index("-c:v")
            if cv_index + 1 < len(enhanced_cmd):
                enhanced_cmd[cv_index + 1] = "libx264"

        # Add preset after codec
        if "-preset" not in enhanced_cmd:
            cv_index = (
                enhanced_cmd.index("libx264") if "libx264" in enhanced_cmd else -1
            )
            if cv_index != -1:
                enhanced_cmd.insert(cv_index + 1, "-preset")
                enhanced_cmd.insert(cv_index + 2, preset)

        # Add CRF for quality control
        if "-crf" not in enhanced_cmd:
            enhanced_cmd.extend(["-crf", str(crf)])

        # Enhanced audio settings
        if "-b:a" not in enhanced_cmd and "-c:a" in enhanced_cmd:
            enhanced_cmd.extend(["-b:a", audio_bitrate])

    return enhanced_cmd


async def multi_resolution_encode(path, uid, listener=None, gid=None, output_dir=None):
    """
    Encode a video in multiple resolutions when multi-resolution encoding is enabled
    """
    from pathlib import Path
    from ... import user_data, task_dict, task_dict_lock, status_dict
    from ..mirror_leech_utils.status_utils.ffmpeg_status import FFMpegStatus
    from ..telegram_helper.message_utils import update_status_message
    from asyncio import create_subprocess_exec
    from asyncio.subprocess import PIPE
    import asyncio
    import os
    import shutil

    user_dict = user_data.get(uid, {})
    if not user_dict.get("VIDEO_ENCODE_MULTI_RESOLUTION", False):
        # Fallback to regular encoding
        return await encode_video(path, uid, listener, gid, output_dir)

    # Get encoding settings
    preset = user_dict.get("VIDEO_ENCODE_PRESET", "medium")
    crf = user_dict.get("VIDEO_ENCODE_CRF", 23)
    raw_audio_bitrate = user_dict.get("VIDEO_ENCODE_AUDIO_BITRATE", "128k")

    # Normalize audio bitrate to prevent ffmpeg errors
    def _normalize_audio_bitrate(raw):
        """Return a safe audio bitrate for ffmpeg."""
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
            return "128k"  # fallback
        except:
            return "128k"

    audio_bitrate = _normalize_audio_bitrate(raw_audio_bitrate)

    input_path = Path(path)
    if output_dir is None:
        output_dir = input_path.parent

    # Get original video resolution
    video_info = await get_video_info_enhanced(str(path))
    original_height = video_info.get("height", 720)

    # All possible resolutions with their FFmpeg parameters
    all_resolutions = [
        (
            "1080p",
            1080,
            [
                "-vf",
                "scale=-1:1080:force_original_aspect_ratio=decrease:force_divisible_by=2",
                "-b:v",
                "2500k",
                "-maxrate",
                "3000k",
                "-bufsize",
                "6000k",
            ],
        ),
        (
            "720p",
            720,
            [
                "-vf",
                "scale=-1:720:force_original_aspect_ratio=decrease:force_divisible_by=2",
                "-b:v",
                "1200k",
                "-maxrate",
                "1400k",
                "-bufsize",
                "2800k",
            ],
        ),
        (
            "480p",
            480,
            [
                "-vf",
                "scale=-1:480:force_original_aspect_ratio=decrease:force_divisible_by=2",
                "-b:v",
                "600k",
                "-maxrate",
                "700k",
                "-bufsize",
                "1400k",
            ],
        ),
        (
            "360p",
            360,
            [
                "-vf",
                "scale=-1:360:force_original_aspect_ratio=decrease:force_divisible_by=2",
                "-b:v",
                "350k",
                "-maxrate",
                "400k",
                "-bufsize",
                "800k",
            ],
        ),
    ]

    # Get user-selected resolutions
    resolution_list = user_dict.get("VIDEO_ENCODE_RESOLUTION_LIST", "").strip()
    if resolution_list:
        # Use user-selected resolutions
        selected_resolutions = [
            r.strip() for r in resolution_list.split(",") if r.strip()
        ]
        LOGGER.info(f"Using user-selected resolutions: {selected_resolutions}")

        # Filter available resolutions to only include user-selected ones
        user_resolutions = []
        for res_name, res_height, res_args in all_resolutions:
            if res_name in selected_resolutions and res_height <= original_height:
                user_resolutions.append((res_name, res_height, res_args))

        target_resolutions = user_resolutions
    else:
        # Use all available resolutions (original behavior)
        target_resolutions = []
        for res_name, res_height, res_args in all_resolutions:
            if res_height <= original_height:
                target_resolutions.append((res_name, res_height, res_args))

    # If no suitable resolutions found, encode to original quality
    if not target_resolutions:
        if resolution_list:
            LOGGER.info(
                f"None of the selected resolutions ({resolution_list}) are suitable for original resolution ({original_height}p), using original quality"
            )
        else:
            LOGGER.info(
                f"Video resolution ({original_height}p) is too small for multi-resolution encoding, using original quality"
            )
        single_encoded = await encode_video(path, uid, listener, gid, output_dir)
        return [single_encoded]

    LOGGER.info(
        f"Multi-resolution encoding enabled. Will create {len(target_resolutions)} versions: {[r[0] for r in target_resolutions]}"
    )

    encoded_files = []
    total_resolutions = len(target_resolutions)

    for index, (quality, height, quality_args) in enumerate(target_resolutions, 1):
        try:
            LOGGER.info(f"Encoding resolution {index}/{total_resolutions}: {quality}")

            # Create output filename for this resolution
            custom_filename = user_dict.get("CUSTOM_FILENAME", "")
            if custom_filename:
                from bot.helper.ext_utils.watermark_utils import apply_custom_filename

                output_path = apply_custom_filename(
                    str(path), user_dict, f"_{quality}_encoded"
                )
            else:
                quality_suffix = quality.replace("p", "")
                output_filename = (
                    f"{input_path.stem}_{quality_suffix}p_MH{input_path.suffix}"
                )
                output_path = os.path.join(output_dir, output_filename)

            # Verify input file exists before processing
            if not os.path.exists(str(path)):
                LOGGER.error(
                    f"Input file no longer exists for {quality} encoding: {path}"
                )
                continue

            # Initialize encoder helper for progress tracking
            encoder_helper = FFmpegEncoderHelper(str(path), output_path)
            encoder_helper.set_quality_preset(quality, preset, crf, audio_bitrate)

            # Get video duration (only if file exists)
            duration = None
            try:
                duration = await get_video_duration_enhanced(str(path))
                if duration:
                    encoder_helper.set_duration(duration)
            except Exception as e:
                LOGGER.warning(
                    f"Could not get duration for {quality} encoding (file may have been moved): {e}"
                )
                # Continue without duration - encoding can still work

            # Update status for current resolution
            if listener and gid:
                from ..mirror_leech_utils.status_utils.ffmpeg_status import FFMpegStatus

                status_text = f"Encode {quality} ({index}/{total_resolutions})"
                status = FFMpegStatus(listener, encoder_helper, gid, status_text)

                async with task_dict_lock:
                    task_dict[listener.mid] = status

                # Update status messages
                for sid in list(status_dict.keys()):
                    try:
                        await update_status_message(sid)
                    except Exception as e:
                        LOGGER.error(
                            f"Error updating status message for {sid}: {str(e)}"
                        )

            # Final check that input file still exists before encoding
            if not os.path.exists(str(path)):
                LOGGER.error(
                    f"Input file disappeared before {quality} encoding: {path}"
                )
                continue

            # Build ffmpeg command for this resolution
            cmd = [
                BinConfig.FFMPEG_NAME,
                "-i",
                str(path),
                "-c:v",
                "libx264",
                "-preset",
                preset,
                "-progress",
                "pipe:1",
                "-nostats",
            ]

            # Add quality-specific arguments
            cmd.extend(quality_args)

            # Add CRF and audio settings
            cmd.extend(["-crf", str(crf)])
            cmd.extend(["-c:a", "aac", "-b:a", audio_bitrate])
            cmd.extend(["-c:s", "copy", "-map", "0", output_path])

            LOGGER.info(f"Starting encoding for {quality}: {output_path}")

            # Execute encoding command with progress tracking
            process = await _create_memory_aware_subprocess(
                *cmd, stdout=PIPE, stderr=PIPE, max_retries=2, wait_for_resources=True
            )

            if not process:
                LOGGER.error(
                    f"Failed to create subprocess for encoding {quality}: {output_path}"
                )
                continue

            # Store subprocess reference for potential cancellation
            if listener:
                listener.subproc = process

            # Process FFmpeg output for progress updates
            while True:
                line = await process.stdout.readline()
                if not line:
                    break

                line_str = line.decode("utf-8", "ignore").strip()
                if "frame=" in line_str or "time=" in line_str or "speed=" in line_str:
                    encoder_helper.update_progress(line_str)

            # Wait for process completion
            await process.wait()

            if process.returncode != 0:
                stderr_data = await process.stderr.read()
                LOGGER.error(
                    f"Error encoding {quality}: {stderr_data.decode('utf-8', 'ignore')}"
                )
                continue

            LOGGER.info(f"Successfully encoded {quality}: {output_path}")
            encoded_files.append(output_path)

        except Exception as e:
            LOGGER.error(f"Error encoding {quality}: {str(e)}")
            continue

    # Handle Multi-zip packaging if enabled
    multi_zip_enabled = user_dict.get("VIDEO_ENCODE_MULTI_ZIP", False)
    if encoded_files and multi_zip_enabled and len(encoded_files) > 1:
        LOGGER.info("Multi-zip enabled, creating single archive with all encoded files")

        try:
            # Create zip archive with all encoded files
            import tempfile
            from ..ext_utils.files_utils import SevenZ
            from ..mirror_leech_utils.status_utils.sevenz_status import SevenZStatus

            with tempfile.TemporaryDirectory() as temp_dir:
                # Copy all encoded files to temp directory
                temp_files = []
                for encoded_file in encoded_files:
                    if os.path.exists(encoded_file):
                        filename = os.path.basename(encoded_file)
                        temp_file_path = os.path.join(temp_dir, filename)
                        shutil.move(encoded_file, temp_file_path)
                        temp_files.append(temp_file_path)

                if temp_files:
                    # Create zip filename based on original file
                    zip_filename = f"{input_path.stem}_MultiRes_Encodes.zip"
                    zip_path = os.path.join(output_dir, zip_filename)

                    # Create SevenZ instance for zipping
                    sevenz = SevenZ(listener)

                    # Update task dict for zip status
                    if listener and gid:
                        async with task_dict_lock:
                            task_dict[listener.mid] = SevenZStatus(
                                listener, sevenz, gid, "Multi-Zip"
                            )

                    # Zip all files
                    zip_result = await sevenz.zip(temp_dir, zip_path, "")

                    if zip_result and zip_result != temp_dir:
                        LOGGER.info(
                            f"Multi-zip archive created successfully: {zip_result}"
                        )
                        return [zip_result]
                    else:
                        LOGGER.error(
                            "Failed to create multi-zip archive, returning individual files"
                        )
                        # Restore files to original location if zip failed
                        restored_files = []
                        for temp_file in temp_files:
                            if os.path.exists(temp_file):
                                original_name = os.path.basename(temp_file)
                                restore_path = os.path.join(output_dir, original_name)
                                shutil.move(temp_file, restore_path)
                                restored_files.append(restore_path)
                        return restored_files if restored_files else [path]

        except Exception as e:
            LOGGER.error(f"Error creating multi-zip archive: {str(e)}")
            # Return original encoded files if zip fails
            return encoded_files if encoded_files else [path]

    return encoded_files if encoded_files else [path]


async def encode_video(path, uid, listener=None, gid=None, output_dir=None):
    """
    Encode a video using the user's encoding preset and quality settings
    :param path: Path to the video file
    :param uid: User ID
    :param listener: TaskListener instance for progress updates
    :param gid: Task ID
    :param output_dir: Output directory (optional)
    :return: Path to the encoded video file
    """
    user_dict = user_data.get(uid, {})
    if not user_dict.get("VIDEO_ENCODE_ENABLED", False):
        return path

    # Get codec setting, default to x264
    codec = user_dict.get("VIDEO_ENCODE_CODEC", "x264")

    # Get encoding preset, default to medium
    preset = user_dict.get("VIDEO_ENCODE_PRESET", "medium")

    # Get quality setting, default to Original
    quality = user_dict.get("VIDEO_ENCODE_QUALITY", "Original")

    # Get CRF value, default to 23
    crf = user_dict.get("VIDEO_ENCODE_CRF", 23)

    # Get audio bitrate, default to 128k
    audio_bitrate = user_dict.get("VIDEO_ENCODE_AUDIO_BITRATE", "128k")

    # Normalize special CRF values
    crf_copy_video = False
    if isinstance(crf, str):
        crf_l = crf.strip().lower()
        if crf_l in ("orig", "original", "source", "copy"):
            crf_copy_video = True
        else:
            try:
                crf = int(crf)
            except Exception:
                LOGGER.warning(f"Invalid CRF value: {crf}. Using default 23.")
                crf = 23
    elif isinstance(crf, (int, float)):
        try:
            crf = int(crf)
        except Exception:
            crf = 23

    # Resolve audio bitrate special values
    audio_copy = False
    if isinstance(audio_bitrate, str):
        ab_l = audio_bitrate.strip().lower()
        if ab_l == "copy":
            audio_copy = True
        elif ab_l in ("orig", "original", "source", "auto"):
            audio_bitrate = "128k"  # Default fallback
        elif ab_l.isdigit():
            audio_bitrate = f"{int(ab_l)}k"
        elif ab_l.endswith("k") and ab_l[:-1].isdigit():
            audio_bitrate = ab_l  # Already in correct format
        else:
            audio_bitrate = "128k"  # Fallback for invalid values
    elif isinstance(audio_bitrate, (int, float)):
        try:
            ival = int(audio_bitrate)
            audio_bitrate = f"{ival}k" if ival > 0 else "128k"
        except:
            audio_bitrate = "128k"
    else:
        audio_bitrate = "128k"  # Fallback for None or other types

    # Validate preset
    valid_presets = [
        "ultrafast",
        "superfast",
        "veryfast",
        "faster",
        "fast",
        "medium",
        "slow",
        "slower",
        "veryslow",
    ]
    if preset not in valid_presets:
        LOGGER.warning(
            f"Invalid encoding preset: {preset}. Using medium preset instead."
        )
        preset = "medium"

    # Validate codec
    valid_codecs = {"x264": "libx264", "x265": "libx265"}
    if codec not in valid_codecs:
        LOGGER.warning(f"Invalid encoding codec: {codec}. Using x264 codec instead.")
        codec = "x264"
    ffmpeg_codec = valid_codecs[codec]

    input_path = Path(path)
    if output_dir is None:
        output_dir = input_path.parent

    # Import custom filename utilities
    from bot.helper.ext_utils.watermark_utils import apply_custom_filename

    # Apply custom filename template if set, otherwise use quality-based naming
    custom_filename = user_dict.get("CUSTOM_FILENAME", "")
    if custom_filename:
        output_path = apply_custom_filename(str(path), user_dict, "_encoded")
    else:
        # Create output filename with quality info (original behavior)
        quality_suffix = f"_{quality.replace('p', '')}" if quality != "Original" else ""
        output_filename = f"{input_path.stem}{quality_suffix}p_BL{input_path.suffix}"
        output_path = os.path.join(output_dir, output_filename)

    # Define quality settings with proper scaling to ensure dimensions are divisible by 2
    quality_settings = {
        "1080p": [
            "-vf",
            "scale=-1:1080:force_original_aspect_ratio=decrease:force_divisible_by=2",
            "-b:v",
            "2M",
            "-maxrate",
            "2.5M",
            "-bufsize",
            "4M",
        ],
        "720p": [
            "-vf",
            "scale=-1:720:force_original_aspect_ratio=decrease:force_divisible_by=2",
            "-b:v",
            "1.2M",
            "-maxrate",
            "1.5M",
            "-bufsize",
            "3M",
        ],
        "576p": [
            "-vf",
            "scale=-1:576:force_original_aspect_ratio=decrease:force_divisible_by=2",
            "-b:v",
            "900k",
            "-maxrate",
            "1M",
            "-bufsize",
            "2M",
        ],
        "480p": [
            "-vf",
            "scale=-1:480:force_original_aspect_ratio=decrease:force_divisible_by=2",
            "-b:v",
            "600k",
            "-maxrate",
            "800k",
            "-bufsize",
            "1.5M",
        ],
        "360p": [
            "-vf",
            "scale=-1:360:force_original_aspect_ratio=decrease:force_divisible_by=2",
            "-b:v",
            "350k",
            "-maxrate",
            "400k",
            "-bufsize",
            "800k",
        ],
        "Original": [],  # No resolution change for "Original"
    }

    # Initialize encoder helper for progress tracking
    encoder_helper = FFmpegEncoderHelper(str(path), output_path)
    encoder_helper.set_quality_preset(quality, preset, crf, audio_bitrate)

    # Get video duration and info
    duration = await get_video_duration(str(path))
    if duration:
        encoder_helper.set_duration(duration)
        LOGGER.info(f"Video duration: {duration} seconds")

    video_info = await get_video_info(str(path))
    if video_info:
        # Estimate total frames if available
        if "avg_frame_rate" in video_info:
            try:
                fps_parts = video_info["avg_frame_rate"].split("/")
                if len(fps_parts) == 2 and int(fps_parts[1]) > 0:
                    avg_fps = int(fps_parts[0]) / int(fps_parts[1])
                    if duration and avg_fps > 0:
                        encoder_helper.total_frames = int(duration * avg_fps)
                        LOGGER.info(
                            f"Estimated total frames: {encoder_helper.total_frames}"
                        )
            except (ValueError, ZeroDivisionError):
                pass

    # Add to task_dict with status if listener is provided
    if listener and gid:
        LOGGER.info(f"Setting up encoding status for {listener.name}")
        status = FFMpegStatus(listener, encoder_helper, gid, "Encode")

        async with task_dict_lock:
            task_dict[listener.mid] = status

        # Force status message updates
        for sid in list(status_dict.keys()):
            try:
                await update_status_message(sid)
            except Exception as e:
                LOGGER.error(f"Error updating status message for {sid}: {str(e)}")

        # Also update specific status if available
        if hasattr(listener, "message") and hasattr(listener.message, "chat"):
            status_dict_key = listener.message.chat.id
            if status_dict_key in status_dict:
                try:
                    await update_status_message(status_dict_key)
                    LOGGER.info(f"Updated specific status for chat {status_dict_key}")
                except Exception as e:
                    LOGGER.error(f"Error updating specific status: {str(e)}")

    # Build ffmpeg command with detailed progress
    # Use -progress to pipe to stdout with more frequent updates
    cmd = ["ffmpeg", "-i", str(path), "-progress", "pipe:1", "-nostats"]

    # Video settings
    if quality in quality_settings and quality != "Original":
        # Scaling requested => must re-encode video
        cmd.extend(["-c:v", ffmpeg_codec, "-preset", preset])
        cmd.extend(quality_settings[quality])

        if not crf_copy_video:
            cmd.extend(["-crf", str(crf)])
        else:
            LOGGER.info("CRF set to copy - using original video quality")

        encoder_helper.codec = codec
        encoder_helper.quality = quality
        encoder_helper.preset = preset
        LOGGER.info(
            f"Encoding {quality} with {codec} codec, preset: {preset}, crf: {crf}"
        )
    else:
        # No scaling, but still re-encode with codec/preset if needed
        if crf_copy_video:
            cmd.extend(["-c:v", "copy"])
            encoder_helper.codec = "copy"
            LOGGER.info("Video codec set to copy - no re-encoding")
        else:
            cmd.extend(["-c:v", ffmpeg_codec, "-preset", preset, "-crf", str(crf)])
            encoder_helper.codec = codec
            encoder_helper.quality = "Original"
            encoder_helper.preset = preset
            LOGGER.info(
                f"Encoding original resolution with {codec} codec, preset: {preset}, crf: {crf}"
            )

    # Audio settings
    if audio_copy:
        cmd.extend(["-c:a", "copy"])
        LOGGER.info("Audio codec set to copy")
    else:
        cmd.extend(["-c:a", "aac", "-b:a", audio_bitrate])
        LOGGER.info(f"Audio: AAC at {audio_bitrate}")

    # Output settings
    cmd.extend(["-y", output_path])

    LOGGER.info(
        f"Starting video encoding: {input_path.name} -> {Path(output_path).name}"
    )
    LOGGER.debug(f"FFMPEG command: {' '.join(cmd)}")

    # Execute command and process output for progress updates
    try:
        process = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
        LOGGER.info("FFmpeg subprocess created successfully")
    except Exception as e:
        LOGGER.error(f"Failed to create FFmpeg subprocess: {str(e)}")
        return path

    # Store subprocess reference for potential cancellation
    if listener:
        listener.subproc = process

    # Set up background status updates
    stop_status_updates = False

    async def update_status_regularly():
        """Update status messages during encoding"""
        while not stop_status_updates:
            try:
                if (
                    listener
                    and gid
                    and hasattr(listener, "message")
                    and hasattr(listener.message, "chat")
                ):
                    status_dict_key = listener.message.chat.id
                    if status_dict_key in status_dict:
                        await update_status_message(status_dict_key)
            except Exception as e:
                LOGGER.debug(f"Error in background status update: {str(e)}")
            await asyncio.sleep(8)

    # Start background status update task
    if listener and gid:
        status_update_task = asyncio.create_task(update_status_regularly())

    try:
        buffer_lines = []
        last_progress_update = time.time()

        while True:
            line = await process.stdout.readline()
            if not line:
                break

            line_str = line.decode("utf-8", "ignore").strip()
            buffer_lines.append(line_str)

            # Keep only last 50 lines to prevent memory buildup
            if len(buffer_lines) > 50:
                buffer_lines = buffer_lines[-25:]  # Keep last 25

            # Update progress on FFmpeg progress lines
            if "frame=" in line_str or "time=" in line_str or "speed=" in line_str:
                encoder_helper.update_progress(line_str)
                encoder_helper.encoding_started = True

                # Update status periodically
                now = time.time()
                if now - last_progress_update >= 3.0 and listener and gid:
                    last_progress_update = now
                    if hasattr(listener, "message") and hasattr(
                        listener.message, "chat"
                    ):
                        status_dict_key = listener.message.chat.id
                        if status_dict_key in status_dict:
                            try:
                                await update_status_message(status_dict_key)
                            except Exception as e:
                                LOGGER.debug(f"Error updating status: {str(e)}")

    finally:
        # Stop background status updates
        if listener and gid:
            stop_status_updates = True
            await asyncio.sleep(0.5)
            try:
                if "status_update_task" in locals() and not status_update_task.done():
                    status_update_task.cancel()
            except Exception as e:
                LOGGER.debug(f"Error canceling status update task: {str(e)}")

    # Process final output
    while True:
        line = await process.stdout.readline()
        if not line:
            break
        line_str = line.decode("utf-8", "ignore").strip()
        if "frame=" in line_str or "time=" in line_str or "speed=" in line_str:
            encoder_helper.update_progress(line_str)

    # Wait for process completion
    await process.wait()

    if process.returncode != 0:
        stderr_data = await process.stderr.read()
        LOGGER.error(f"Error encoding video: {stderr_data.decode('utf-8', 'ignore')}")
        return path

    LOGGER.info(f"Successfully encoded video: {output_path}")
    return output_path


async def convert_video(path, uid, listener=None, gid=None, output_dir=None):
    """
    Convert video to different format using user's conversion settings
    :param path: Path to the video file
    :param uid: User ID
    :param listener: TaskListener instance for progress updates
    :param gid: Task ID
    :param output_dir: Output directory (optional)
    :return: Path to the converted video file
    """
    user_dict = user_data.get(uid, {})
    if not user_dict.get("VIDEO_CONVERT_ENABLED", False):
        return path

    # Get conversion settings
    target_format = user_dict.get("VIDEO_CONVERT_FORMAT", "mp4").lower()
    convert_codec = user_dict.get("VIDEO_CONVERT_CODEC", "copy").lower()
    convert_quality = user_dict.get("VIDEO_CONVERT_QUALITY", "original").lower()

    input_path = Path(path)
    current_format = input_path.suffix.lower().lstrip(".")

    # Skip conversion if already in target format and codec is copy
    if current_format == target_format and convert_codec == "copy":
        LOGGER.info(
            f"Video is already in {target_format} format and codec is 'copy', skipping conversion"
        )
        return path

    # Get source video info to check codec compatibility
    video_info = await get_video_info(str(path))
    source_video_codec = None
    source_audio_codec = None

    if video_info:
        source_video_codec = video_info.get("codec_name", "unknown").lower()
        # Get audio codec from additional stream info
        try:
            cmd_info = [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                str(path),
            ]
            process = await create_subprocess_exec(*cmd_info, stdout=PIPE, stderr=PIPE)
            stdout, _ = await process.communicate()
            if process.returncode == 0:
                import json

                probe_data = json.loads(stdout.decode())
                for stream in probe_data.get("streams", []):
                    if stream.get("codec_type") == "audio":
                        source_audio_codec = stream.get("codec_name", "unknown").lower()
                        break
        except:
            pass

    LOGGER.info(
        f"Source codecs - Video: {source_video_codec}, Audio: {source_audio_codec}"
    )

    # Check codec compatibility with target format
    def is_compatible_combination(video_codec, audio_codec, container):
        """Check if codec combination is compatible with container format"""
        compatibility_map = {
            "mp4": {
                "video": ["h264", "h265", "hevc", "mpeg4", "av1"],
                "audio": ["aac", "mp3", "ac3", "eac3"],
            },
            "mkv": {
                "video": ["h264", "h265", "hevc", "av1", "vp8", "vp9"],
                "audio": ["aac", "mp3", "opus", "vorbis", "flac", "ac3", "dts"],
            },
            "avi": {
                "video": ["h264", "xvid", "divx", "mpeg4"],
                "audio": ["mp3", "ac3", "aac"],
            },
            "mov": {
                "video": ["h264", "h265", "hevc", "prores"],
                "audio": ["aac", "mp3", "alac"],
            },
            "webm": {"video": ["vp8", "vp9", "av1"], "audio": ["vorbis", "opus"]},
            "flv": {"video": ["h264", "flv1"], "audio": ["aac", "mp3"]},
            "m4v": {"video": ["h264", "h265"], "audio": ["aac", "ac3"]},
        }

        format_info = compatibility_map.get(container.lower(), {})
        video_compatible = video_codec in format_info.get("video", [])
        audio_compatible = audio_codec in format_info.get("audio", [])

        return video_compatible and audio_compatible

    # If using copy mode, check compatibility and override if needed
    if convert_codec == "copy":
        if not is_compatible_combination(
            source_video_codec, source_audio_codec, target_format
        ):
            LOGGER.warning(
                f"Codec incompatible: {source_video_codec}/{source_audio_codec} → {target_format}"
            )
            LOGGER.info("Switching from 'copy' to 'auto' mode for codec compatibility")
            convert_codec = "auto"

    # Set output directory
    if output_dir is None:
        output_dir = input_path.parent

    # Create output filename with watermark utils import
    from bot.helper.ext_utils.watermark_utils import apply_custom_filename

    custom_filename = user_dict.get("CUSTOM_FILENAME", "")
    if custom_filename:
        output_path = apply_custom_filename(str(path), user_dict, f"_converted")
        # Ensure correct extension
        output_path = str(Path(output_path).with_suffix(f".{target_format}"))
    else:
        output_filename = f"{input_path.stem}_converted.{target_format}"
        output_path = os.path.join(output_dir, output_filename)

    # Initialize converter helper for progress tracking
    converter_helper = FFmpegEncoderHelper(str(path), output_path)

    # Get video duration and info
    duration = await get_video_duration(str(path))
    if duration:
        converter_helper.set_duration(duration)
        LOGGER.info(f"Video duration: {duration} seconds")

    video_info = await get_video_info(str(path))
    if video_info and "avg_frame_rate" in video_info:
        try:
            fps_parts = video_info["avg_frame_rate"].split("/")
            if len(fps_parts) == 2 and int(fps_parts[1]) > 0:
                avg_fps = int(fps_parts[0]) / int(fps_parts[1])
                if duration and avg_fps > 0:
                    converter_helper.total_frames = int(duration * avg_fps)
                    LOGGER.info(
                        f"Estimated total frames: {converter_helper.total_frames}"
                    )
        except (ValueError, ZeroDivisionError):
            pass

    # Add to task_dict with status if listener is provided
    if listener and gid:
        LOGGER.info(f"Setting up conversion status for {listener.name}")
        status = FFMpegStatus(listener, converter_helper, gid, "Convert")

        async with task_dict_lock:
            task_dict[listener.mid] = status

        # Force status message updates
        for sid in list(status_dict.keys()):
            try:
                await update_status_message(sid)
            except Exception as e:
                LOGGER.error(f"Error updating status message for {sid}: {str(e)}")

    # Build ffmpeg command
    cmd = ["ffmpeg", "-i", str(path), "-progress", "pipe:1", "-nostats"]

    # Determine video codec based on settings
    if convert_codec == "copy":
        cmd.extend(["-c:v", "copy"])
        converter_helper.codec = "copy"
        LOGGER.info(
            f"Converting {current_format} to {target_format} with video copy (no re-encoding)"
        )
    elif convert_codec == "auto":
        # Smart codec selection based on format with better compatibility
        format_codec_map = {
            "mp4": {"video": "libx264", "audio": "aac"},
            "mkv": {
                "video": "copy"
                if source_video_codec in ["h264", "h265", "av1"]
                else "libx264",
                "audio": "copy"
                if source_audio_codec in ["aac", "opus", "flac"]
                else "aac",
            },
            "avi": {"video": "libx264", "audio": "aac"},
            "mov": {"video": "libx264", "audio": "aac"},
            "webm": {"video": "libvpx-vp9", "audio": "libopus"},
            "flv": {"video": "libx264", "audio": "aac"},
            "m4v": {"video": "libx264", "audio": "aac"},
        }

        codec_info = format_codec_map.get(
            target_format, {"video": "libx264", "audio": "aac"}
        )
        selected_video_codec = codec_info["video"]
        selected_audio_codec = codec_info["audio"]

        # Apply video codec
        if selected_video_codec == "copy":
            cmd.extend(["-c:v", "copy"])
        else:
            cmd.extend(["-c:v", selected_video_codec])
            # Set quality based on convert_quality setting
            if convert_quality == "high":
                cmd.extend(["-crf", "18"])
            elif convert_quality == "medium":
                cmd.extend(["-crf", "23"])
            elif convert_quality == "low":
                cmd.extend(["-crf", "28"])
            else:  # original
                cmd.extend(["-crf", "23"])  # Default balanced quality

        # Apply audio codec
        if selected_audio_codec == "copy":
            cmd.extend(["-c:a", "copy"])
        else:
            cmd.extend(["-c:a", selected_audio_codec])
            if selected_audio_codec == "aac":
                cmd.extend(["-b:a", "128k"])

        converter_helper.codec = (
            selected_video_codec.replace("lib", "")
            if "lib" in selected_video_codec
            else selected_video_codec
        )
        LOGGER.info(
            f"Converting {current_format} to {target_format} with auto codecs: video={selected_video_codec}, audio={selected_audio_codec}, quality: {convert_quality}"
        )
    elif convert_codec in ["x264", "x265"]:
        # Use specified codec
        ffmpeg_codec = "libx264" if convert_codec == "x264" else "libx265"
        cmd.extend(["-c:v", ffmpeg_codec])

        # Set quality based on convert_quality setting
        if convert_quality == "high":
            cmd.extend(["-crf", "18"])
        elif convert_quality == "medium":
            cmd.extend(["-crf", "23"])
        elif convert_quality == "low":
            cmd.extend(["-crf", "28"])
        else:  # original
            cmd.extend(["-crf", "23"])  # Default balanced quality

        # Smart audio codec selection based on format
        if target_format.lower() in ["mp4", "mov", "m4v"]:
            cmd.extend(["-c:a", "aac", "-b:a", "128k"])
        elif target_format.lower() == "webm":
            cmd.extend(["-c:a", "libopus"])
        else:
            cmd.extend(["-c:a", "aac", "-b:a", "128k"])

        converter_helper.codec = convert_codec
        LOGGER.info(
            f"Converting {current_format} to {target_format} with {convert_codec} codec, quality: {convert_quality}"
        )

    # Handle all streams preservation based on target format compatibility
    if target_format.lower() == "mp4":
        # MP4: Preserve all streams with format-compatible codecs
        cmd.extend(["-c:s", "mov_text"])  # Convert subtitles to MP4 compatible format
        cmd.extend(["-map", "0"])  # Map all streams
    elif target_format.lower() == "mkv":
        # MKV: Most flexible container, preserve everything as-is
        cmd.extend(["-c:s", "copy"])  # Keep subtitle codecs
        cmd.extend(["-map", "0"])  # Map all streams
    elif target_format.lower() == "webm":
        # WebM: Preserve compatible streams, convert incompatible subtitles
        cmd.extend(["-c:s", "webvtt"])  # Convert to WebVTT for WebM compatibility
        cmd.extend(["-map", "0"])  # Map all streams
    elif target_format.lower() in ["avi", "mov", "m4v"]:
        # These formats support multiple streams but may need subtitle conversion
        if target_format.lower() == "mov":
            cmd.extend(["-c:s", "mov_text"])
        else:
            cmd.extend(["-c:s", "srt"])  # Use SRT for broader compatibility
        cmd.extend(["-map", "0"])  # Map all streams
    elif target_format.lower() == "flv":
        # FLV has limitations: single audio stream, no subtitles
        cmd.extend(["-map", "0:v", "-map", "0:a:0"])  # Only first audio stream
        LOGGER.warning(
            "FLV format limitations: preserving only first audio stream, no subtitles"
        )
    else:
        # Conservative approach for unknown formats
        cmd.extend(["-map", "0:v", "-map", "0:a"])
        LOGGER.warning(
            f"Unknown format {target_format}: preserving only video and audio streams"
        )

    # Add output path
    cmd.append(output_path)

    LOGGER.info(
        f"Starting video format conversion: {current_format.upper()} → {target_format.upper()}"
    )
    LOGGER.debug(f"FFMPEG command: {cmd}")

    # Execute command and process output for progress updates
    process = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)

    # Store subprocess reference for potential cancellation
    if listener:
        listener.subproc = process

    # Background status update task
    stop_status_updates = False

    async def update_status_regularly():
        """Update status messages during conversion"""
        while not stop_status_updates:
            try:
                if (
                    listener
                    and gid
                    and hasattr(listener, "message")
                    and hasattr(listener.message, "chat")
                ):
                    status_dict_key = listener.message.chat.id
                    if status_dict_key in status_dict:
                        await update_status_message(status_dict_key)
            except Exception as e:
                LOGGER.debug(f"Error in background status update: {str(e)}")
            await asyncio.sleep(8)

    # Start background status update task
    if listener and gid:
        status_update_task = asyncio.create_task(update_status_regularly())

    try:
        # Process FFmpeg output for progress updates
        last_progress_update = time.time()

        while True:
            line = await process.stdout.readline()
            if not line:
                break

            line_str = line.decode("utf-8", "ignore").strip()

            # Process progress information
            if "frame=" in line_str or "time=" in line_str or "speed=" in line_str:
                converter_helper.update_progress(line_str)
                converter_helper.encoding_started = True

                # Update status periodically
                now = time.time()
                if now - last_progress_update >= 3.0 and listener and gid:
                    last_progress_update = now
                    if hasattr(listener, "message") and hasattr(
                        listener.message, "chat"
                    ):
                        status_dict_key = listener.message.chat.id
                        if status_dict_key in status_dict:
                            try:
                                await update_status_message(status_dict_key)
                            except Exception as e:
                                LOGGER.debug(f"Error updating status: {str(e)}")

    finally:
        # Stop background status updates
        if listener and gid:
            stop_status_updates = True
            await asyncio.sleep(0.5)
            try:
                if "status_update_task" in locals() and not status_update_task.done():
                    status_update_task.cancel()
            except Exception as e:
                LOGGER.debug(f"Error canceling status update task: {str(e)}")

    # Wait for process completion and check result
    await process.wait()

    if process.returncode != 0:
        stderr_data = await process.stderr.read()
        error_msg = stderr_data.decode("utf-8", "ignore")
        LOGGER.error(f"Error converting video: {error_msg}")

        # Check if it's a subtitle-related error and try without subtitles
        if (
            "subrip" in error_msg.lower()
            or "subtitle" in error_msg.lower()
            or "codec not currently supported" in error_msg.lower()
            or "av1 only supported" in error_msg.lower()
            or "Could not find tag for codec" in error_msg.lower()
            or "invalid number of streams" in error_msg.lower()
        ):
            LOGGER.info(
                "Conversion failed due to codec/format incompatibility, retrying with compatible codecs..."
            )

            # Retry with forced transcoding using compatible codecs
            retry_cmd = ["ffmpeg", "-i", str(path), "-progress", "pipe:1", "-nostats"]

            # Force compatible codecs based on target format
            if target_format.lower() == "mp4":
                retry_cmd.extend(["-c:v", "libx264", "-c:a", "aac"])
                if convert_quality == "high":
                    retry_cmd.extend(["-crf", "18"])
                elif convert_quality == "medium":
                    retry_cmd.extend(["-crf", "23"])
                elif convert_quality == "low":
                    retry_cmd.extend(["-crf", "28"])
                else:
                    retry_cmd.extend(["-crf", "23"])
                retry_cmd.extend(["-b:a", "128k"])
            elif target_format.lower() == "webm":
                retry_cmd.extend(["-c:v", "libvpx-vp9", "-c:a", "libopus"])
                if convert_quality == "high":
                    retry_cmd.extend(["-crf", "18"])
                elif convert_quality == "medium":
                    retry_cmd.extend(["-crf", "23"])
                elif convert_quality == "low":
                    retry_cmd.extend(["-crf", "28"])
                else:
                    retry_cmd.extend(["-crf", "23"])
            elif target_format.lower() in ["avi", "flv", "mov", "m4v"]:
                retry_cmd.extend(["-c:v", "libx264", "-c:a", "aac"])
                if convert_quality == "high":
                    retry_cmd.extend(["-crf", "18"])
                elif convert_quality == "medium":
                    retry_cmd.extend(["-crf", "23"])
                elif convert_quality == "low":
                    retry_cmd.extend(["-crf", "28"])
                else:
                    retry_cmd.extend(["-crf", "23"])
                retry_cmd.extend(["-b:a", "128k"])
            elif target_format.lower() == "mkv":
                # MKV is flexible, use H.264 + AAC for best compatibility
                retry_cmd.extend(["-c:v", "libx264", "-c:a", "aac"])
                if convert_quality == "high":
                    retry_cmd.extend(["-crf", "18"])
                elif convert_quality == "medium":
                    retry_cmd.extend(["-crf", "23"])
                elif convert_quality == "low":
                    retry_cmd.extend(["-crf", "28"])
                else:
                    retry_cmd.extend(["-crf", "23"])
                retry_cmd.extend(["-b:a", "128k"])
            else:
                # Default fallback
                retry_cmd.extend(
                    ["-c:v", "libx264", "-c:a", "aac", "-crf", "23", "-b:a", "128k"]
                )

            # Map streams based on target format capabilities
            if target_format.lower() == "flv":
                # FLV limitations: single audio stream, no subtitles
                retry_cmd.extend(["-map", "0:v", "-map", "0:a:0"])
                LOGGER.info(
                    "FLV retry: preserving only first audio stream due to format limitations"
                )
            elif target_format.lower() in ["mp4", "m4v"]:
                # Try to preserve all streams with compatible subtitle codec
                retry_cmd.extend(["-c:s", "mov_text", "-map", "0"])
                LOGGER.info(
                    "MP4/M4V retry: preserving all streams with mov_text subtitles"
                )
            elif target_format.lower() == "webm":
                # WebM retry with WebVTT subtitles
                retry_cmd.extend(["-c:s", "webvtt", "-map", "0"])
                LOGGER.info("WebM retry: preserving all streams with webvtt subtitles")
            elif target_format.lower() in ["mkv", "avi", "mov"]:
                # These formats can handle most streams
                retry_cmd.extend(["-c:s", "srt", "-map", "0"])
                LOGGER.info(
                    f"{target_format.upper()} retry: preserving all streams with SRT subtitles"
                )
            else:
                # Conservative fallback: video and audio only
                retry_cmd.extend(["-map", "0:v", "-map", "0:a"])
                LOGGER.info(
                    "Conservative retry: preserving only video and audio streams"
                )

            retry_cmd.append(output_path)

            LOGGER.info(
                "Retrying conversion with forced compatible codecs (no subtitles)"
            )

            # Execute retry command
            retry_process = await create_subprocess_exec(
                *retry_cmd, stdout=PIPE, stderr=PIPE
            )

            if listener:
                listener.subproc = retry_process

            # Wait for retry process
            await retry_process.wait()

            if retry_process.returncode != 0:
                retry_stderr = await retry_process.stderr.read()
                LOGGER.error(
                    f"Retry conversion also failed: {retry_stderr.decode('utf-8', 'ignore')}"
                )
                return path
            else:
                LOGGER.info("Retry conversion with compatible codecs succeeded")
        else:
            return path

    LOGGER.info(f"Video format conversion completed: {output_path}")

    # Final status update
    if listener and gid:
        converter_helper.progress_raw = 100
        converter_helper.status_text = "Conversion complete"
        if converter_helper.duration:
            converter_helper.encoding_time = time.strftime(
                "%H:%M:%S", time.gmtime(converter_helper.duration)
            )

        for sid in list(status_dict.keys()):
            try:
                await update_status_message(sid)
            except Exception as e:
                LOGGER.error(f"Error with final status update: {str(e)}")

        if hasattr(listener, "message") and hasattr(listener.message, "chat"):
            try:
                await update_status_message(listener.message.chat.id)
            except Exception as e:
                LOGGER.error(f"Error updating specific status: {str(e)}")

    # Handle file replacement
    if path != output_path:
        keep_source_files = user_dict.get("KEEP_MERGE_SOURCE_FILES", False)
        if (
            not keep_source_files
            and os.path.exists(path)
            and os.path.exists(output_path)
        ):
            try:
                LOGGER.info(
                    f"KEEP_MERGE_SOURCE_FILES is disabled, removing original file: {path}"
                )
                if os.path.getsize(output_path) > 0:
                    await remove(path)
                    LOGGER.info(f"Original file removed: {path}")
                else:
                    LOGGER.warning(f"Converted file is empty, keeping original: {path}")
            except Exception as e:
                LOGGER.error(f"Error handling converted file: {str(e)}")

    return output_path
