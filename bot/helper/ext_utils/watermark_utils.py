from asyncio import create_subprocess_exec
from asyncio.subprocess import PIPE
import os
import re
import time
import asyncio
import shutil
from pathlib import Path

from aiofiles.os import remove
from bot import LOGGER, user_data, task_dict, task_dict_lock, status_dict
from bot.core.config_manager import Config
from bot.helper.ext_utils.bot_utils import cmd_exec
from bot.helper.telegram_helper.message_utils import update_status_message
from bot.helper.ext_utils.ffmpeg_utils import get_video_duration, get_video_info


def check_media_processing_enabled():
    """
    Check if media processing operations are enabled

    Returns:
        bool: True if enabled, False if disabled
    """
    if Config.is_media_processing_disabled():
        LOGGER.warning("Media processing operations are disabled by admin")
        return False
    return True


def apply_custom_filename(input_path, user_dict, temp_suffix="_temp"):
    """
    Apply custom filename template if set by user for all FFmpeg operations.

    Args:
        input_path (str): Path to the input file
        user_dict (dict): User settings dictionary
        temp_suffix (str): Suffix to add for temporary processing

    Returns:
        str: Output path with custom filename applied
    """
    input_path_obj = Path(input_path)
    output_dir = input_path_obj.parent

    # Check if user has set a custom filename template
    custom_filename = user_dict.get("CUSTOM_FILENAME", "")
    if custom_filename:
        # Apply custom filename template
        original_name = input_path_obj.stem
        original_ext = input_path_obj.suffix

        # Replace template variables
        custom_name = custom_filename.replace("{name}", original_name).replace(
            "{ext}", original_ext.lstrip(".")
        )

        # Ensure we have an extension
        if not custom_name.endswith(original_ext):
            custom_name += original_ext

        # Add temp suffix to avoid overwriting during processing
        final_name = f"{Path(custom_name).stem}{temp_suffix}{Path(custom_name).suffix}"
        output_filename = final_name
    else:
        # Default behavior - add processing suffix
        process_suffix = temp_suffix.replace("_temp", "_processed")
        output_filename = (
            f"{input_path_obj.stem}{process_suffix}{input_path_obj.suffix}"
        )

    return os.path.join(output_dir, output_filename)


def get_final_filename(input_path, user_dict):
    """
    Get the final filename that will be used after FFmpeg processing completes.

    Args:
        input_path (str): Path to the input file
        user_dict (dict): User settings dictionary

    Returns:
        str: Final filename with custom template applied (without temp suffix)
    """
    input_path_obj = Path(input_path)

    # Check if user has set a custom filename template
    custom_filename = user_dict.get("CUSTOM_FILENAME", "")
    if custom_filename:
        # Apply custom filename template
        original_name = input_path_obj.stem
        original_ext = input_path_obj.suffix

        # Replace template variables
        custom_name = custom_filename.replace("{name}", original_name).replace(
            "{ext}", original_ext.lstrip(".")
        )

        # Ensure we have an extension
        if not custom_name.endswith(original_ext):
            custom_name += original_ext

        return os.path.join(input_path_obj.parent, custom_name)
    else:
        # No custom filename, return original path
        return input_path


class WatermarkHelper:
    def __init__(self, input_path, output_path):
        self.input_path = input_path
        self.output_path = output_path
        self.start_time = time.time()
        self.progress_raw = 0.01
        self.speed_raw = 0
        self.eta_raw = 0
        self.processed_bytes = 0
        self.total_bytes = os.path.getsize(input_path)
        self.last_update_time = time.time()
        self.last_bytes = 0
        self.status_text = "Starting watermark..."
        self.duration = None
        self.last_status_update = 0
        self.current_frame = 0
        self.total_frames = 0
        self.fps = 0
        self.ffmpeg_speed = 0.1
        self.bitrate = "N/A"
        self.encoding_time = "00:00:00"
        self.short_filename = os.path.basename(input_path)
        self.watermark_text = ""
        self.watermark_position = ""
        self.watermark_opacity = 0.5
        self.watermark_type = "text"
        self.watermark_started = False
        self._bytes_from_total_size = (
            False  # Flag to track if we got bytes from FFmpeg total_size
        )
        self._last_time_seconds = 0  # Track last time in seconds to detect stuck time
        self._stuck_time_count = 0  # Count how many times time was stuck

    def set_watermark_settings(
        self,
        wm_text,
        wm_position,
        wm_opacity,
        wm_type,
        preset="medium",
        crf=23,
        audio_bitrate="128k",
    ):
        """Set watermark configuration and encoding settings"""
        self.watermark_text = wm_text
        self.watermark_position = wm_position
        self.watermark_opacity = wm_opacity
        self.watermark_type = wm_type
        self.preset = preset
        self.crf = crf
        self.audio_bitrate = audio_bitrate

    def update_progress(self, line):
        """Update progress based on FFmpeg output line"""
        try:
            if (
                "frame=" in line
                and "fps=" in line
                and "time=" in line
                and "speed=" in line
            ):
                self.ffmpeg_progress_line = line.strip()

                if not hasattr(self, "watermark_started") or not self.watermark_started:
                    self.watermark_started = True
                    LOGGER.info(
                        f"FFmpeg watermarking has started for {os.path.basename(self.input_path)}"
                    )

            # Extract time information
            time_match = re.search(r"time=(\d+:\d+:\d+\.\d+)", line)
            if time_match:
                self.encoding_time = time_match.group(1)

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
                                f"FFmpeg watermark time appears stuck at {processed_time}s - switching to frame-based progress"
                            )
                    else:
                        self._stuck_time_count = 0  # Reset counter if time progressed
                        self._last_time_seconds = processed_time

                    # Use time-based progress as primary method - but validate it makes sense
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
                                f"Watermark progress calculation exceeds 100% ({calculated_progress:.2f}%) - duration might be incorrect. Using frame-based progress."
                            )
                            # Don't update progress_raw, let frame-based calculation handle it
                        else:
                            self.progress_raw = min(100, calculated_progress)

                        if self.progress_raw < 0.1 and processed_time > 0:
                            self.progress_raw = 0.1

            # Extract fps
            fps_match = re.search(r"fps=\s*([0-9.]+)", line)
            if fps_match:
                try:
                    self.fps = float(fps_match.group(1))
                    if self.ffmpeg_speed <= 0:
                        self.ffmpeg_speed = 0.1
                except ValueError:
                    pass

            # Extract current frame
            frame_match = re.search(r"frame=\s*(\d+)", line)
            if frame_match:
                try:
                    new_frame = int(frame_match.group(1))
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
                                        f"Using frame-based watermark progress: {frame_progress:.2f}% (frame {self.current_frame}/{self.total_frames})"
                                    )

                        if self.progress_raw <= 0 and self.current_frame > 0:
                            self.progress_raw = 0.1
                except ValueError:
                    pass

            # Extract speed
            speed_match = re.search(r"speed=\s*([0-9.]+)x", line)
            if speed_match:
                try:
                    self.ffmpeg_speed = float(speed_match.group(1))
                except ValueError:
                    pass

            # Extract bitrate
            bitrate_match = re.search(r"bitrate=\s*([0-9.]+\w+/s)", line)
            if bitrate_match:
                self.bitrate = bitrate_match.group(1)

            # Check for total_size progress line (alternative progress format)
            if "=" in line:
                key, value = line.split("=", 1)
                if key == "total_size" and value != "N/A":
                    try:
                        self.processed_bytes = int(value)
                        self._bytes_from_total_size = True
                    except ValueError:
                        pass

            # Also check for size= field (another FFmpeg progress format)
            size_match = re.search(r"size=\s*(\d+)kB", line)
            if size_match:
                try:
                    size_kb = int(size_match.group(1))
                    self.processed_bytes = size_kb * 1024
                    self._bytes_from_total_size = True
                except ValueError:
                    pass

            # Calculate processed bytes by checking actual output file size
            if (
                not hasattr(self, "_bytes_from_total_size")
                or not self._bytes_from_total_size
            ):
                try:
                    if os.path.exists(self.output_path):
                        actual_output_size = os.path.getsize(self.output_path)
                        if actual_output_size > 0:
                            self.processed_bytes = actual_output_size
                        elif self.current_frame > 0:
                            # Fallback: estimate based on progress if output file doesn't exist yet
                            self.processed_bytes = max(
                                1024, int(self.total_bytes * (self.progress_raw / 100))
                            )
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

            # Calculate speed and ETA based on time progress (more accurate)
            now = time.time()
            time_diff = now - self.last_update_time
            if time_diff >= 2.0:
                # Calculate processing speed based on actual progress
                if self.progress_raw > 0 and self.duration and self.duration > 0:
                    # Time-based speed calculation is more accurate for watermarking
                    elapsed_real_time = now - self.start_time
                    if elapsed_real_time > 0:
                        time_parts = re.search(r"time=(\d+):(\d+):(\d+)\.(\d+)", line)
                        if time_parts:
                            hours, minutes, seconds, cs = map(int, time_parts.groups())
                            processed_video_time = (
                                hours * 3600 + minutes * 60 + seconds + cs / 100
                            )
                            if processed_video_time > 0:
                                # Calculate processing rate (video seconds per real second)
                                processing_rate = (
                                    processed_video_time / elapsed_real_time
                                )
                                remaining_video_time = (
                                    self.duration - processed_video_time
                                )
                                if processing_rate > 0 and remaining_video_time > 0:
                                    self.eta_raw = (
                                        remaining_video_time / processing_rate
                                    )

                # Update speed based on file size change if available
                size_diff = self.processed_bytes - self.last_bytes
                if size_diff > 0:
                    self.speed_raw = size_diff / time_diff
                    self.last_bytes = self.processed_bytes

                self.last_update_time = now

                # Log progress less frequently for debugging
                if now - self.last_status_update > 15:  # Only log every 15 seconds
                    self.last_status_update = now
                    LOGGER.info(
                        f"Watermark progress: {os.path.basename(self.input_path)} - {self.progress_raw:.2f}% - "
                        f"FFmpeg reports: frame={self.current_frame} fps={self.fps:.1f} time={self.encoding_time} speed={self.ffmpeg_speed:.2f}x"
                    )
        except Exception as e:
            LOGGER.error(f"Error updating watermark progress: {str(e)}")

    def set_duration(self, duration):
        """Set the total duration of the video"""
        self.duration = duration


async def add_watermark(path, uid, listener=None, gid=None, output_dir=None):
    """
    Add watermark to video using user-defined settings
    :param path: Path to the video file
    :param uid: User ID
    :param listener: TaskListener instance for progress updates
    :param gid: Task ID
    :param output_dir: Output directory (optional)
    :return: Path to the watermarked video file
    """
    from bot.helper.mirror_leech_utils.status_utils.watermark_status import (
        WatermarkStatus,
    )

    user_dict = user_data.get(uid, {})
    if not user_dict.get("VIDEO_WATERMARK_ENABLED", False):
        return path

    # Get watermark settings
    watermark_text = user_dict.get("VIDEO_WATERMARK_TEXT", "Default Watermark")
    watermark_position = user_dict.get("VIDEO_WATERMARK_POSITION", "bottom-right")
    watermark_opacity = user_dict.get("VIDEO_WATERMARK_OPACITY", 0.5)
    watermark_type = user_dict.get("VIDEO_WATERMARK_TYPE", "text")
    watermark_image_path = user_dict.get("VIDEO_WATERMARK_IMAGE_PATH", "")
    watermark_font_size = user_dict.get("VIDEO_WATERMARK_FONT_SIZE", 24)
    watermark_font_color = user_dict.get("VIDEO_WATERMARK_FONT_COLOR", "white")
    watermark_text_background = user_dict.get("VIDEO_WATERMARK_TEXT_BACKGROUND", False)
    watermark_duration_type = user_dict.get("VIDEO_WATERMARK_DURATION_TYPE", "all")
    watermark_duration_seconds = user_dict.get("VIDEO_WATERMARK_DURATION_SECONDS", 10)
    watermark_font_path = user_dict.get("VIDEO_WATERMARK_FONT_PATH", "")

    # Get video encoding settings for CRF and preset
    preset = user_dict.get("VIDEO_ENCODE_PRESET", "medium")
    crf = user_dict.get("VIDEO_ENCODE_CRF", 23)
    audio_bitrate = user_dict.get("VIDEO_ENCODE_AUDIO_BITRATE", "128k")

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

    # Ensure CRF is within valid range (0-51)
    if not isinstance(crf, int) or crf < 0 or crf > 51:
        LOGGER.warning(f"Invalid CRF value: {crf}. Using default CRF 23.")
        crf = 23

    LOGGER.info(
        f"Using video encoding settings for watermark - Preset: {preset}, CRF: {crf}, Audio Bitrate: {audio_bitrate}"
    )

    input_path = Path(path)
    if output_dir is None:
        output_dir = input_path.parent

    # Apply custom filename template if set
    output_path = apply_custom_filename(str(path), user_dict, "_watermarked")

    # Initialize watermark helper for progress tracking
    watermark_helper = WatermarkHelper(str(path), output_path)
    watermark_helper.set_watermark_settings(
        watermark_text,
        watermark_position,
        watermark_opacity,
        watermark_type,
        preset,
        crf,
        audio_bitrate,
    )

    # Get video duration and info
    duration = await get_video_duration(str(path))
    if duration:
        watermark_helper.set_duration(duration)
        LOGGER.info(f"Video duration: {duration} seconds")

    video_info = await get_video_info(str(path))
    if video_info:
        if "avg_frame_rate" in video_info:
            try:
                fps_parts = video_info["avg_frame_rate"].split("/")
                if len(fps_parts) == 2 and int(fps_parts[1]) > 0:
                    avg_fps = int(fps_parts[0]) / int(fps_parts[1])
                    if duration and avg_fps > 0:
                        watermark_helper.total_frames = int(duration * avg_fps)
                        LOGGER.info(
                            f"Estimated total frames: {watermark_helper.total_frames}"
                        )
            except (ValueError, ZeroDivisionError):
                pass

    # Add to task_dict with status if listener is provided
    if listener and gid:
        LOGGER.info(f"Setting up watermark status for {listener.name}")

        # Create Watermark status
        status = WatermarkStatus(listener, watermark_helper, gid, "Watermark")

        # Update task_dict with watermark status
        async with task_dict_lock:
            task_dict[listener.mid] = status

        # Force status message updates
        for sid in list(status_dict.keys()):
            try:
                await update_status_message(sid)
                LOGGER.debug(f"Updated status message for {sid}")
            except Exception as e:
                LOGGER.error(f"Error updating status message for {sid}: {str(e)}")

    # Get stream information to preserve all streams
    stream_info = await get_stream_information(str(path))

    # Build watermark filter based on type and position
    if watermark_type == "text":
        watermark_filter = await build_text_watermark_filter(
            watermark_text,
            watermark_position,
            watermark_opacity,
            watermark_font_size,
            watermark_font_color,
            watermark_text_background,
            duration,
            watermark_duration_type,
            watermark_duration_seconds,
            watermark_font_path,
        )
        # Build ffmpeg command for text watermark using custom CRF and preset with stream preservation
        cmd = [
            "ffmpeg",
            "-i",
            str(path),
            "-vf",
            watermark_filter,
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            str(crf),
            "-map",
            "0",  # Map all streams from input
        ]
        # Add audio codec settings for all audio streams
        cmd.extend(["-c:a", "copy"])  # Copy audio streams by default
        # Add subtitle codec settings for all subtitle streams
        cmd.extend(["-c:s", "copy"])  # Copy subtitle streams
        # Add data stream settings
        cmd.extend(["-c:d", "copy"])  # Copy data streams (attachments, etc.)
        # Add other stream settings
        cmd.extend(["-c:t", "copy"])  # Copy attachment streams

        cmd.extend(["-progress", "pipe:1", "-nostats", "-y", output_path])

    else:  # image watermark
        if watermark_image_path and os.path.exists(watermark_image_path):
            LOGGER.info(f"Using image watermark: {watermark_image_path}")
            # Verify the image file is readable
            try:
                file_size = os.path.getsize(watermark_image_path)
                LOGGER.info(f"Watermark image size: {file_size} bytes")
                if file_size == 0:
                    LOGGER.error("Watermark image file is empty, falling back to text")
                    raise FileNotFoundError("Empty watermark image file")
            except Exception as e:
                LOGGER.error(f"Error checking watermark image: {str(e)}")
                watermark_filter = await build_text_watermark_filter(
                    watermark_text,
                    watermark_position,
                    watermark_opacity,
                    watermark_font_size,
                    watermark_font_color,
                    watermark_text_background,
                    duration,
                    watermark_duration_type,
                    watermark_duration_seconds,
                    watermark_font_path,
                )
                cmd = [
                    "ffmpeg",
                    "-i",
                    str(path),
                    "-vf",
                    watermark_filter,
                    "-c:v",
                    "libx264",
                    "-preset",
                    preset,
                    "-crf",
                    str(crf),
                    "-map",
                    "0",  # Map all streams from input
                    "-c:a",
                    "copy",  # Copy audio streams
                    "-c:s",
                    "copy",  # Copy subtitle streams
                    "-c:d",
                    "copy",  # Copy data streams
                    "-c:t",
                    "copy",  # Copy attachment streams
                    "-progress",
                    "pipe:1",
                    "-nostats",
                    "-y",
                    output_path,
                ]
            else:
                watermark_filter = await build_image_watermark_filter(
                    watermark_position,
                    watermark_opacity,
                    duration,
                    watermark_duration_type,
                    watermark_duration_seconds,
                )
                LOGGER.info(f"Generated image watermark filter: {watermark_filter}")
                # Build ffmpeg command for image watermark using custom CRF and preset with stream preservation
                cmd = [
                    "ffmpeg",
                    "-i",
                    str(path),
                    "-i",
                    watermark_image_path,
                    "-filter_complex",
                    watermark_filter,
                    "-map",
                    "[v]",  # Map the video output from filter_complex
                    "-map",
                    "0:a?",  # Map audio streams from first input if they exist
                    "-map",
                    "0:s?",  # Map subtitle streams from first input if they exist
                    "-map",
                    "0:d?",  # Map data streams from first input if they exist
                    "-map",
                    "0:t?",  # Map attachment streams from first input if they exist
                    "-c:v",
                    "libx264",
                    "-preset",
                    preset,
                    "-crf",
                    str(crf),
                    "-c:a",
                    "copy",  # Copy audio streams
                    "-c:s",
                    "copy",  # Copy subtitle streams
                    "-c:d",
                    "copy",  # Copy data streams
                    "-c:t",
                    "copy",  # Copy attachment streams
                    "-progress",
                    "pipe:1",
                    "-nostats",
                    "-y",
                    output_path,
                ]
        else:
            LOGGER.warning(
                f"Image watermark enabled but no valid image path found: {watermark_image_path}, falling back to text"
            )
            watermark_filter = await build_text_watermark_filter(
                watermark_text,
                watermark_position,
                watermark_opacity,
                watermark_font_size,
                watermark_font_color,
                watermark_text_background,
                duration,
                watermark_duration_type,
                watermark_duration_seconds,
                watermark_font_path,
            )
            # Build ffmpeg command for text watermark fallback using custom CRF and preset with stream preservation
            cmd = [
                "ffmpeg",
                "-i",
                str(path),
                "-vf",
                watermark_filter,
                "-c:v",
                "libx264",
                "-preset",
                preset,
                "-crf",
                str(crf),
                "-map",
                "0",  # Map all streams from input
                "-c:a",
                "copy",  # Copy audio streams
                "-c:s",
                "copy",  # Copy subtitle streams
                "-c:d",
                "copy",  # Copy data streams
                "-c:t",
                "copy",  # Copy attachment streams
                "-progress",
                "pipe:1",
                "-nostats",
                "-y",
                output_path,
            ]

    LOGGER.info(f"Starting video watermarking: {path}")
    LOGGER.info(f"Watermark type: {watermark_type}")
    LOGGER.info(
        f"Using encoding settings - Preset: {preset}, CRF: {crf} (preserving all streams)"
    )
    if watermark_type == "image":
        LOGGER.info(f"Watermark image path: {watermark_image_path}")
        LOGGER.info(
            f"Image exists: {os.path.exists(watermark_image_path) if watermark_image_path else False}"
        )
    LOGGER.debug(f"FFMPEG watermark command: {' '.join(cmd)}")

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
        """Update status messages during watermarking"""
        while not stop_status_updates:
            try:
                if hasattr(listener, "message") and hasattr(listener.message, "chat"):
                    sid = listener.message.chat.id
                    if sid in status_dict:
                        await update_status_message(sid)
                elif status_dict:
                    await update_status_message(next(iter(status_dict.keys())))
            except Exception as e:
                LOGGER.debug(f"Error in background status update: {str(e)}")

            await asyncio.sleep(8)

    # Start background status update task
    if listener and gid:
        status_update_task = asyncio.create_task(update_status_regularly())

    try:
        buffer_lines = []
        last_progress_update = time.time()
        init_time = time.time()
        force_update_time = init_time
        last_activity_time = time.time()
        timeout_seconds = 3600  # 1 hour timeout
        no_progress_timeout = 300  # 5 minutes without progress

        while True:
            try:
                # Add timeout to readline to prevent hanging
                line = await asyncio.wait_for(process.stdout.readline(), timeout=30.0)
                if not line:
                    break
                last_activity_time = time.time()
            except asyncio.TimeoutError:
                # Check if process is still running and hasn't timed out
                current_time = time.time()
                if current_time - init_time > timeout_seconds:
                    LOGGER.error(
                        f"Watermarking timed out after {timeout_seconds} seconds"
                    )
                    try:
                        process.terminate()
                        await asyncio.sleep(2)
                        if process.returncode is None:
                            process.kill()
                    except:
                        pass
                    return path
                elif current_time - last_activity_time > no_progress_timeout:
                    LOGGER.error(
                        f"No progress in watermarking for {no_progress_timeout} seconds"
                    )
                    try:
                        process.terminate()
                        await asyncio.sleep(2)
                        if process.returncode is None:
                            process.kill()
                    except:
                        pass
                    return path
                else:
                    # Just continue if still within reasonable timeouts
                    continue

            line_str = line.decode("utf-8", "ignore").strip()

            has_progress_info = False

            if "frame=" in line_str or "time=" in line_str or "speed=" in line_str:
                has_progress_info = True
                watermark_helper.update_progress(line_str)
                watermark_helper.watermark_started = True

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
                                LOGGER.debug(f"Error updating status message: {str(e)}")

            buffer_lines.append(line_str)

            now = time.time()
            if len(buffer_lines) >= 10 or now - init_time >= 5.0:
                for buffered_line in buffer_lines:
                    if "Duration:" in buffered_line:
                        LOGGER.debug(f"FFmpeg info: {buffered_line}")
                        duration_match = re.search(
                            r"Duration: (\d+):(\d+):(\d+)\.(\d+)", buffered_line
                        )
                        if duration_match and not watermark_helper.duration:
                            h, m, s, ms = map(int, duration_match.groups())
                            new_duration = h * 3600 + m * 60 + s + ms / 100
                            watermark_helper.set_duration(new_duration)
                            LOGGER.info(
                                f"Detected video duration: {new_duration} seconds"
                            )

                buffer_lines = []
                init_time = now

            if (
                now - force_update_time >= 8.0
                and not has_progress_info
                and listener
                and gid
            ):
                force_update_time = now
                if hasattr(listener, "message") and hasattr(listener.message, "chat"):
                    status_dict_key = listener.message.chat.id
                    if status_dict_key in status_dict:
                        try:
                            await update_status_message(status_dict_key)
                        except Exception as e:
                            LOGGER.debug(
                                f"Error updating forced status message: {str(e)}"
                            )

    finally:
        if listener and gid:
            stop_status_updates = True
            await asyncio.sleep(0.5)
            try:
                if "status_update_task" in locals() and not status_update_task.done():
                    status_update_task.cancel()
            except Exception as e:
                LOGGER.debug(f"Error canceling status update task: {str(e)}")

    # Process stderr for additional info
    stderr_data = await process.stderr.read()
    if stderr_data:
        stderr_lines = stderr_data.decode("utf-8", "ignore").split("\n")
        for line in stderr_lines:
            if line.strip():
                if any(
                    info in line
                    for info in ["fps=", "time=", "frame=", "speed=", "bitrate="]
                ):
                    LOGGER.debug(f"FFmpeg stderr progress: {line}")
                    watermark_helper.update_progress(line)
                elif "Duration:" in line and not watermark_helper.duration:
                    LOGGER.debug(f"FFmpeg duration info: {line}")
                    duration_match = re.search(
                        r"Duration: (\d+):(\d+):(\d+)\.(\d+)", line
                    )
                    if duration_match:
                        h, m, s, ms = map(int, duration_match.groups())
                        new_duration = h * 3600 + m * 60 + s + ms / 100

                        # Update duration if we don't have one or if the new one is significantly different
                        if not watermark_helper.duration:
                            watermark_helper.set_duration(new_duration)
                            LOGGER.info(
                                f"Detected video duration from stderr: {new_duration} seconds"
                            )
                        elif (
                            abs(watermark_helper.duration - new_duration) > 5
                        ):  # More than 5 seconds difference
                            LOGGER.info(
                                f"Updating watermark video duration from {watermark_helper.duration} to {new_duration} seconds"
                            )
                            watermark_helper.set_duration(new_duration)
                            # Reset progress to recalculate with correct duration
                            watermark_helper.progress_raw = 0.1
                elif "error" in line.lower() or "failed" in line.lower():
                    LOGGER.error(f"FFmpeg error: {line.strip()}")

    await process.wait()

    if process.returncode != 0:
        LOGGER.error(f"Error adding watermark: {stderr_data.decode('utf-8', 'ignore')}")
        return path

    LOGGER.info(f"Video watermarking completed: {output_path}")

    # Final status update
    if listener and gid:
        watermark_helper.progress_raw = 100
        watermark_helper.status_text = "Watermark complete"
        if watermark_helper.duration:
            watermark_helper.encoding_time = time.strftime(
                "%H:%M:%S", time.gmtime(watermark_helper.duration)
            )

        LOGGER.info(
            f"Watermarking complete for {os.path.basename(path)}, updating status messages"
        )

        for sid in list(status_dict.keys()):
            try:
                await update_status_message(sid)
            except Exception as e:
                LOGGER.error(f"Error with final status update for {sid}: {str(e)}")

        if hasattr(listener, "message") and hasattr(listener.message, "chat"):
            try:
                await update_status_message(listener.message.chat.id)
            except Exception as e:
                LOGGER.error(f"Error updating specific status on completion: {str(e)}")

    # Handle file replacement with custom filename
    if path != output_path:
        keep_source_files = user_dict.get("KEEP_MERGE_SOURCE_FILES", False)
        if (
            not keep_source_files
            and os.path.exists(path)
            and os.path.exists(output_path)
        ):
            try:
                # Get final filename with custom template applied
                final_path = get_final_filename(path, user_dict)
                LOGGER.info(
                    f"KEEP_MERGE_SOURCE_FILES is disabled, replacing with custom filename: {final_path}"
                )

                if os.path.getsize(output_path) > 0:
                    # Replace original file with processed version using custom filename
                    shutil.move(output_path, final_path)
                    LOGGER.info(f"File processed and renamed to: {final_path}")

                    # If final path is different from original, remove original
                    if final_path != path and os.path.exists(path):
                        await remove(path)
                        LOGGER.info(f"Original file removed: {path}")

                    return final_path
                else:
                    LOGGER.warning(f"Processed file is empty, keeping original: {path}")
                    return path
            except Exception as e:
                LOGGER.error(f"Error applying custom filename: {str(e)}")
                return path
        else:
            # If keeping source files, return processed file with custom name
            final_path = get_final_filename(path, user_dict)
            if final_path != output_path:
                try:
                    shutil.move(output_path, final_path)
                    return final_path
                except Exception as e:
                    LOGGER.error(f"Error applying custom filename: {str(e)}")
                    return output_path
            return output_path

    return path


async def build_text_watermark_filter(
    text,
    position,
    opacity,
    font_size,
    font_color,
    background=False,
    video_duration=None,
    duration_type="all",
    duration_seconds=10,
    font_path="",
):
    """Build FFmpeg text watermark filter with duration control and custom fonts"""
    # Position mapping
    position_map = {
        "top-left": "x=10:y=10",
        "top-right": "x=W-tw-10:y=10",
        "bottom-left": "x=10:y=H-th-10",
        "bottom-right": "x=W-tw-10:y=H-th-10",
        "center": "x=(W-tw)/2:y=(H-th)/2",
        "top-center": "x=(W-tw)/2:y=10",
        "bottom-center": "x=(W-tw)/2:y=H-th-10",
    }

    pos = position_map.get(position, position_map["bottom-right"])

    # Calculate time range for watermark based on duration type
    time_enable = ""
    if video_duration and duration_type != "all":
        if duration_type == "start":
            # Show watermark from start for specified seconds
            time_enable = f":enable='between(t,0,{duration_seconds})'"
        elif duration_type == "end":
            # Show watermark for last specified seconds
            start_time = max(0, video_duration - duration_seconds)
            time_enable = f":enable='between(t,{start_time},{video_duration})'"
        elif duration_type == "middle":
            # Show watermark in middle for specified seconds
            middle_start = max(0, (video_duration / 2) - (duration_seconds / 2))
            middle_end = min(video_duration, middle_start + duration_seconds)
            time_enable = f":enable='between(t,{middle_start},{middle_end})'"

    # Add custom font if available
    font_param = ""
    if font_path and os.path.exists(font_path):
        # Escape the font path for FFmpeg
        escaped_font_path = font_path.replace("\\", "\\\\").replace(":", "\\:")
        font_param = f":fontfile='{escaped_font_path}'"

    # Build drawtext filter with or without background, duration control, and custom font
    if background:
        # With background box for better visibility
        filter_str = f"drawtext=text='{text}':fontsize={font_size}:fontcolor={font_color}@{opacity}:{pos}:box=1:boxcolor=black@0.3:boxborderw=2{font_param}{time_enable}"
    else:
        # Without background box for cleaner look
        filter_str = f"drawtext=text='{text}':fontsize={font_size}:fontcolor={font_color}@{opacity}:{pos}{font_param}{time_enable}"

    return filter_str


async def build_image_watermark_filter(
    position, opacity, video_duration=None, duration_type="all", duration_seconds=10
):
    """Build FFmpeg image watermark filter for two-input command with duration control"""
    # Position mapping for image overlay
    position_map = {
        "top-left": "x=10:y=10",
        "top-right": "x=W-w-10:y=10",
        "bottom-left": "x=10:y=H-h-10",
        "bottom-right": "x=W-w-10:y=H-h-10",
        "center": "x=(W-w)/2:y=(H-h)/2",
        "top-center": "x=(W-w)/2:y=10",
        "bottom-center": "x=(W-w)/2:y=H-h-10",
    }

    pos = position_map.get(position, position_map["bottom-right"])

    # Calculate time range for watermark based on duration type
    time_enable = ""
    if video_duration and duration_type != "all":
        if duration_type == "start":
            # Show watermark from start for specified seconds
            time_enable = f":enable='between(t,0,{duration_seconds})'"
        elif duration_type == "end":
            # Show watermark for last specified seconds
            start_time = max(0, video_duration - duration_seconds)
            time_enable = f":enable='between(t,{start_time},{video_duration})'"
        elif duration_type == "middle":
            # Show watermark in middle for specified seconds
            middle_start = max(0, (video_duration / 2) - (duration_seconds / 2))
            middle_end = min(video_duration, middle_start + duration_seconds)
            time_enable = f":enable='between(t,{middle_start},{middle_end})'"

    # Build overlay filter with alpha (opacity) and duration control using two inputs
    # Input 0 is the video, Input 1 is the watermark image
    if opacity < 1.0:
        # Apply opacity by modifying the alpha channel of the watermark
        # Scale the watermark to reasonable size and ensure it has an alpha channel
        filter_str = f"[1:v]scale=iw*min(200/iw\\,200/ih):ih*min(200/iw\\,200/ih),format=rgba,colorchannelmixer=aa={opacity}[wm];[0:v][wm]overlay={pos}{time_enable}[v]"
    else:
        # No opacity adjustment needed, but still scale the watermark
        filter_str = f"[1:v]scale=iw*min(200/iw\\,200/ih):ih*min(200/iw\\,200/ih)[wm];[0:v][wm]overlay={pos}{time_enable}[v]"

    return filter_str


async def get_video_duration(file_path):
    """Get the duration of a video file using ffprobe"""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        file_path,
    ]
    process = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        LOGGER.error(f"Error getting video duration: {stderr.decode()}")
        return None

    try:
        return float(stdout.decode().strip())
    except (ValueError, TypeError) as e:
        LOGGER.error(f"Error parsing video duration: {str(e)}")
        return None


async def get_video_info(file_path):
    """Get comprehensive video information using ffprobe"""
    cmd = [
        "ffprobe",
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
    process = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        LOGGER.error(f"Error getting video info: {stderr.decode()}")
        return {}

    try:
        import json

        result = json.loads(stdout.decode())
        return result.get("streams", [{}])[0] if "streams" in result else {}
    except Exception as e:
        LOGGER.error(f"Error parsing video info: {str(e)}")
        return {}


async def get_stream_information(file_path):
    """Get detailed stream information using ffprobe"""
    cmd = ["ffprobe", "-v", "error", "-show_streams", "-of", "json", file_path]
    process = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        LOGGER.error(f"Error getting stream information: {stderr.decode()}")
        return {}

    try:
        import json

        result = json.loads(stdout.decode())
        return result.get("streams", [])
    except Exception as e:
        LOGGER.error(f"Error parsing stream information: {str(e)}")
        return []
