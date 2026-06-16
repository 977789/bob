from asyncio import create_subprocess_exec
from asyncio.subprocess import PIPE
import os
import re
import time
import asyncio
from pathlib import Path
import shutil

from aiofiles.os import remove
from bot import LOGGER, user_data, task_dict, task_dict_lock, status_dict
from bot.helper.ext_utils.bot_utils import cmd_exec
from bot.helper.telegram_helper.message_utils import update_status_message
from bot.helper.mirror_leech_utils.status_utils.ffmpeg_status import FFmpegStatus
from bot.helper.ext_utils.files_utils import SevenZ
from bot.helper.mirror_leech_utils.status_utils.sevenz_status import SevenZStatus


class FFmpegEncoderHelper:
    def __init__(self, input_path, output_path):
        self.input_path = input_path
        self.output_path = output_path
        self.start_time = time.time()
        self.progress_raw = 0.01  # Start with a tiny bit of progress so it shows up
        self.speed_raw = 0
        self.eta_raw = 0
        self.processed_bytes = 0
        self.total_bytes = os.path.getsize(input_path)
        self.last_update_time = time.time()
        self.last_bytes = 0
        self.status_text = "Muxing..."
        self.duration = None
        self.last_status_update = 0
        self.current_frame = 0
        self.total_frames = 0
        self.fps = 0
        self.ffmpeg_speed = 0.1  # Start with a small speed value to display
        self.bitrate = "N/A"
        self.encoding_time = "00:00:00"
        self.short_filename = os.path.basename(input_path)
        self.quality = ""
        self.preset = ""
        self.encoding_started = False  # Flag to track if encoding has started
        self._bytes_from_total_size = (
            False  # Flag to track if we got bytes from FFmpeg total_size
        )
        self._last_time_seconds = 0  # Track last time in seconds to detect stuck time
        self._stuck_time_count = 0  # Count how many times time was stuck

    def set_quality_preset(
        self, quality, preset, codec="x264", crf=23, audio_bitrate="128k"
    ):
        """Set quality, preset, codec, crf and audio_bitrate values for status display"""
        self.quality = quality
        self.preset = preset
        self.codec = codec
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
                        f"FFmpeg encoding has started producing progress lines for {os.path.basename(self.input_path)}"
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

            # Calculate speed and ETA based on time progress (more accurate for encoding)
            now = time.time()
            time_diff = now - self.last_update_time
            if time_diff >= 2.0:  # Update less frequently to reduce fluctuations
                # Calculate processing speed based on actual progress
                if self.progress_raw > 0 and self.duration and self.duration > 0:
                    # Time-based speed calculation is more accurate for encoding
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
                if size_diff > 0:  # Only update if we've made progress
                    self.speed_raw = size_diff / time_diff
                    self.last_bytes = self.processed_bytes

                self.last_update_time = now

                # Log progress less frequently for debugging
                if now - self.last_status_update > 15:  # Only log every 15 seconds
                    self.last_status_update = now
                    LOGGER.info(
                        f"Encoding progress: {os.path.basename(self.input_path)} - {self.progress_raw:.2f}% - "
                        f"FFmpeg reports: frame={self.current_frame} fps={self.fps:.1f} time={self.encoding_time} speed={self.ffmpeg_speed:.2f}x"
                    )
        except Exception as e:
            LOGGER.error(f"Error updating FFmpeg progress: {str(e)}")

    def set_duration(self, duration):
        """Set the total duration of the video"""
        self.duration = duration


async def encode_video_multi_resolution(
    path, uid, listener=None, gid=None, output_dir=None
):
    """
    Encode a video in multiple resolutions when multi-resolution encoding is enabled
    :param path: Path to the video file
    :param uid: User ID
    :param listener: TaskListener instance for progress updates
    :param gid: Task ID
    :param output_dir: Output directory (optional)
    :return: List of paths to the encoded video files
    """
    user_dict = user_data.get(uid, {})
    if not user_dict.get("VIDEO_ENCODE_ENABLED", False):
        return [path]

    if not user_dict.get("VIDEO_ENCODE_MULTI_RESOLUTION", False):
        # Fall back to single resolution encoding
        single_encoded = await encode_video(path, uid, listener, gid, output_dir)
        return [single_encoded]

    # Get encoding settings
    codec = user_dict.get("VIDEO_ENCODE_CODEC", "x264")
    preset = user_dict.get("VIDEO_ENCODE_PRESET", "medium")
    crf = user_dict.get("VIDEO_ENCODE_CRF", 23)
    audio_bitrate = user_dict.get("VIDEO_ENCODE_AUDIO_BITRATE", "128k")

    # Normalize CRF and audio bitrate special values
    crf_copy_video = False
    if isinstance(crf, str):
        crf_l = crf.strip().lower()
        if crf_l in ("orig", "original", "source", "copy"):
            # In multi-resolution mode we can't copy video while scaling. We'll ignore and fall back.
            LOGGER.warning(
                "Requested original CRF (video copy) in multi-resolution mode; falling back to re-encode with CRF 23."
            )
            crf = 23
        else:
            try:
                crf = int(crf)
            except Exception:
                LOGGER.warning(f"Invalid CRF value: {crf}. Using default 23.")
                crf = 23

    # Resolve original audio bitrate or copy if requested
    audio_copy = False
    if isinstance(audio_bitrate, str):
        ab_l = audio_bitrate.strip().lower()
        if ab_l in ("copy",):
            audio_copy = True
        elif ab_l in ("orig", "original", "source"):
            try:
                kbps = await get_original_audio_bitrate_kbps(str(path))
                if kbps:
                    audio_bitrate = f"{kbps}k"
                else:
                    audio_bitrate = "128k"
            except Exception:
                audio_bitrate = "128k"

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

    # Get original video resolution to determine which resolutions to create
    video_info = await get_video_info(str(path))
    original_height = 720  # Default fallback

    if video_info and "height" in video_info:
        original_height = int(video_info["height"])
        LOGGER.info(
            f"Original video resolution: {video_info.get('width', 'unknown')}x{original_height}"
        )

    # Define all available resolutions in descending order
    # Using force_original_aspect_ratio=decrease:force_divisible_by=2 to ensure dimensions are even
    all_resolutions = [
        (
            "1080p",
            1080,
            [
                "-vf",
                "scale=-1:1080:force_original_aspect_ratio=decrease:force_divisible_by=2",
                "-b:v",
                "2M",
                "-maxrate",
                "2.5M",
                "-bufsize",
                "4M",
            ],
        ),
        (
            "720p",
            720,
            [
                "-vf",
                "scale=-1:720:force_original_aspect_ratio=decrease:force_divisible_by=2",
                "-b:v",
                "1.2M",
                "-maxrate",
                "1.5M",
                "-bufsize",
                "3M",
            ],
        ),
        (
            "576p",
            576,
            [
                "-vf",
                "scale=-1:576:force_original_aspect_ratio=decrease:force_divisible_by=2",
                "-b:v",
                "900k",
                "-maxrate",
                "1M",
                "-bufsize",
                "2M",
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
                "800k",
                "-bufsize",
                "1.5M",
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
                    f"{input_path.stem}_{quality_suffix}p_BL{input_path.suffix}"
                )
                output_path = os.path.join(output_dir, output_filename)

            # Initialize encoder helper for progress tracking
            encoder_helper = FFmpegEncoderHelper(str(path), output_path)
            encoder_helper.set_quality_preset(
                quality, preset, codec, crf, audio_bitrate
            )

            # Get video duration
            duration = await get_video_duration(str(path))
            if duration:
                encoder_helper.set_duration(duration)

            # Update status for current resolution
            if listener and gid:
                status_text = f"Encode {quality} ({index}/{total_resolutions})"
                status = FFmpegStatus(listener, encoder_helper, gid, status_text)

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

            # Build ffmpeg command for this resolution
            cmd = [
                "ffmpeg",
                "-i",
                str(path),
                "-c:v",
                ffmpeg_codec,
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
            if audio_copy:
                cmd.extend(["-c:a", "copy"])
            else:
                cmd.extend(["-c:a", "aac", "-b:a", audio_bitrate])
            cmd.extend(["-c:s", "copy", "-map", "0", output_path])

            LOGGER.info(
                f"Starting encoding for {quality} with codec: {codec}: {output_path}"
            )
            LOGGER.debug(f"FFMPEG command: {cmd}")

            # Execute encoding command
            process = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)

            # Store subprocess reference for potential cancellation
            if listener:
                listener.subproc = process

            # Background task for status updates
            stop_status_updates = False

            async def update_status_regularly():
                while not stop_status_updates:
                    await asyncio.sleep(2.0)
                    if listener and gid and not stop_status_updates:
                        try:
                            if hasattr(listener, "message") and hasattr(
                                listener.message, "chat"
                            ):
                                status_dict_key = listener.message.chat.id
                                if status_dict_key in status_dict:
                                    await update_status_message(status_dict_key)
                        except Exception as e:
                            LOGGER.debug(f"Error in background status update: {str(e)}")

            # Start background status update task
            if listener and gid:
                status_update_task = asyncio.create_task(update_status_regularly())

            try:
                # Process FFmpeg output for progress updates
                while True:
                    line = await process.stdout.readline()
                    if not line:
                        break

                    line_str = line.decode("utf-8", "ignore").strip()

                    if (
                        "frame=" in line_str
                        or "time=" in line_str
                        or "speed=" in line_str
                    ):
                        encoder_helper.update_progress(line_str)

            finally:
                # Stop background status updates
                if listener and gid:
                    stop_status_updates = True
                    await asyncio.sleep(0.5)
                    try:
                        if (
                            "status_update_task" in locals()
                            and not status_update_task.done()
                        ):
                            status_update_task.cancel()
                    except Exception as e:
                        LOGGER.debug(f"Error canceling status update task: {str(e)}")

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

    # Final status update
    if listener and gid:
        try:
            # Reset status to complete
            encoder_helper.progress_raw = 100
            encoder_helper.status_text = (
                f"Multi-resolution encoding complete ({len(encoded_files)} files)"
            )

            for sid in list(status_dict.keys()):
                try:
                    await update_status_message(sid)
                except Exception as e:
                    LOGGER.error(f"Error with final status update for {sid}: {str(e)}")

            if hasattr(listener, "message") and hasattr(listener.message, "chat"):
                await update_status_message(listener.message.chat.id)

        except Exception as e:
            LOGGER.error(f"Error updating final status: {str(e)}")

    # Handle Multi-zip packaging if enabled
    multi_zip_enabled = user_dict.get("VIDEO_ENCODE_MULTI_ZIP", False)
    if encoded_files and multi_zip_enabled and len(encoded_files) > 1:
        LOGGER.info("Multi-zip enabled, creating single archive with all encoded files")

        # Update status to show zipping progress
        if listener and gid:
            try:
                encoder_helper.progress_raw = 0
                encoder_helper.status_text = "Creating Multi-Zip archive..."

                for sid in list(status_dict.keys()):
                    try:
                        await update_status_message(sid)
                    except Exception as e:
                        LOGGER.error(f"Error updating zip status for {sid}: {str(e)}")
            except Exception as e:
                LOGGER.error(f"Error updating zip status: {str(e)}")

        try:
            # Create zip archive with all encoded files
            # Create a temporary directory for the files
            import tempfile

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
                    input_path = Path(path)
                    zip_filename = f"{input_path.stem}_MultiRes_Encodes.zip"
                    zip_path = os.path.join(
                        output_dir or input_path.parent, zip_filename
                    )

                    # Create SevenZ instance for zipping
                    sevenz = SevenZ(listener)

                    # Update task dict for zip status
                    if listener and gid:
                        async with task_dict_lock:
                            task_dict[listener.mid] = SevenZStatus(
                                listener, sevenz, gid, "Multi-Zip"
                            )

                    # Zip all files
                    zip_result = await sevenz.zip(temp_dir, zip_path, "")  # No password

                    if zip_result and zip_result != temp_dir:
                        LOGGER.info(
                            f"Multi-zip archive created successfully: {zip_result}"
                        )

                        # Handle original source file deletion if needed
                        if not user_dict.get("KEEP_MERGE_SOURCE_FILES", False):
                            try:
                                if os.path.exists(path):
                                    await remove(path)
                                    LOGGER.info(f"Original source file removed: {path}")
                            except Exception as e:
                                LOGGER.error(
                                    f"Error removing original source file: {str(e)}"
                                )

                        # Return the zip file path
                        return [zip_result]
                    else:
                        LOGGER.error(
                            "Failed to create multi-zip archive, returning individual files"
                        )
                        # Move files back to original location if zip failed
                        restored_files = []
                        for temp_file in temp_files:
                            if os.path.exists(temp_file):
                                original_name = os.path.basename(temp_file)
                                restore_path = os.path.join(
                                    output_dir or input_path.parent, original_name
                                )
                                shutil.move(temp_file, restore_path)
                                restored_files.append(restore_path)
                        return restored_files if restored_files else [path]
                else:
                    LOGGER.warning(
                        "No encoded files found for multi-zip, returning original"
                    )
                    return [path]

        except Exception as e:
            LOGGER.error(f"Error creating multi-zip archive: {str(e)}")
            # Return original encoded files if zip fails
            return encoded_files if encoded_files else [path]

    # Handle original file deletion if needed
    if encoded_files and not user_dict.get("KEEP_MERGE_SOURCE_FILES", False):
        try:
            if os.path.exists(path):
                await remove(path)
                LOGGER.info(f"Original file removed: {path}")
        except Exception as e:
            LOGGER.error(f"Error removing original file: {str(e)}")

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
        elif ab_l in ("orig", "original", "source"):
            try:
                kbps = await get_original_audio_bitrate_kbps(str(path))
                if kbps:
                    audio_bitrate = f"{kbps}k"
                else:
                    audio_bitrate = "128k"
            except Exception:
                audio_bitrate = "128k"

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
    from bot.helper.ext_utils.watermark_utils import (
        apply_custom_filename,
        get_final_filename,
    )

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
        # Store the original status if it exists
        original_status = None
        async with task_dict_lock:
            if listener.mid in task_dict:
                original_status = task_dict[listener.mid]

        # Create FFmpeg status
        status = FFmpegStatus(listener, encoder_helper, gid, "Encode")

        # Update task_dict with encoding status
        async with task_dict_lock:
            task_dict[listener.mid] = status

        # Force status message updates across all active status messages
        for sid in list(status_dict.keys()):
            try:
                await update_status_message(sid)
                LOGGER.debug(f"Updated status message for {sid}")
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
        # If user asked for original/copy CRF but scaling is requested, fall back to a safe numeric CRF
        used_crf = 23 if crf_copy_video else crf
        if crf_copy_video:
            LOGGER.warning(
                "CRF 'original' requested but scaling is applied; falling back to CRF 23."
            )
            try:
                encoder_helper.crf = used_crf
            except Exception:
                pass
        LOGGER.info(
            f"Encoding video to {quality} with codec: {codec}, preset: {preset}, CRF: {used_crf}, audio: {('copy' if audio_copy else audio_bitrate)}"
        )
        cmd.extend(["-crf", str(used_crf)])
    else:
        # No scaling. If CRF says original/copy, copy video. Else re-encode with CRF
        if crf_copy_video:
            cmd.extend(["-c:v", "copy"])
            LOGGER.info(
                f"Keeping original video stream (copy). Audio: {('copy' if audio_copy else audio_bitrate)}"
            )
        else:
            cmd.extend(["-c:v", ffmpeg_codec, "-preset", preset, "-crf", str(crf)])
            LOGGER.info(
                f"Re-encoding video (no scaling) with codec: {codec}, preset {preset}, CRF: {crf}. Audio: {('copy' if audio_copy else audio_bitrate)}"
            )

    # Audio settings
    if audio_copy:
        cmd.extend(["-c:a", "copy"])
    else:
        cmd.extend(["-c:a", "aac", "-b:a", audio_bitrate])

    # Add subtitle settings and output path
    cmd.extend(["-c:s", "copy", "-map", "0", output_path])

    LOGGER.info(f"Starting video encoding: {path}")
    LOGGER.debug(f"FFMPEG command: {cmd}")

    # Execute command and process output for progress updates
    process = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)

    # Store subprocess reference for potential cancellation
    if listener:
        listener.subproc = process

    # Process output for progress updates
    last_status_update = 0
    # Set up a background task to update status messages at reasonable intervals
    stop_status_updates = False

    async def update_status_regularly():
        """Update status messages occasionally during encoding to avoid excessive refreshing"""
        while not stop_status_updates:
            try:
                # Only update one status message at a time to reduce load
                sid = None

                # First try to get the listener's specific chat ID
                if hasattr(listener, "message") and hasattr(listener.message, "chat"):
                    sid = listener.message.chat.id
                    if sid in status_dict:
                        await update_status_message(sid)

                # If specific chat update failed, try one general update
                if not sid or sid not in status_dict:
                    # Get any status dict key
                    if status_dict:
                        await update_status_message(next(iter(status_dict.keys())))

            except Exception as e:
                LOGGER.debug(f"Error in background status update: {str(e)}")

            # Sleep for a longer interval to reduce refreshing
            await asyncio.sleep(12)  # Update every 12 seconds

    # Start background status update task
    if listener and gid:
        status_update_task = asyncio.create_task(update_status_regularly())

    try:
        # Buffer to collect ffmpeg output lines for smoother progress updates
        buffer_lines = []
        last_progress_update = time.time()

        # Make sure we show initial status before we start processing
        if (
            listener
            and gid
            and hasattr(listener, "message")
            and hasattr(listener.message, "chat")
        ):
            status_dict_key = listener.message.chat.id
            if status_dict_key in status_dict:
                try:
                    await update_status_message(status_dict_key)
                except Exception as e:
                    LOGGER.debug(f"Error updating initial status message: {str(e)}")

        # Set a timer to periodically update status even without progress
        init_time = time.time()
        force_update_time = init_time

        while True:
            line = await process.stdout.readline()
            if not line:
                break

            line_str = line.decode("utf-8", "ignore").strip()

            # Process any line with progress info
            has_progress_info = False

            if "frame=" in line_str or "time=" in line_str or "speed=" in line_str:
                # This is a progress info from FFmpeg - update immediately
                has_progress_info = True
                encoder_helper.update_progress(line_str)
                encoder_helper.encoding_started = True

                # Trigger a status update every 3 seconds when we have progress
                now = time.time()
                if now - last_progress_update >= 3.0 and listener and gid:
                    last_progress_update = now
                    # Update the status message in the background
                    if hasattr(listener, "message") and hasattr(
                        listener.message, "chat"
                    ):
                        status_dict_key = listener.message.chat.id
                        if status_dict_key in status_dict:
                            try:
                                await update_status_message(status_dict_key)
                            except Exception as e:
                                LOGGER.debug(f"Error updating status message: {str(e)}")

            # Always collect in buffer for analysis
            buffer_lines.append(line_str)

            # Process buffer periodically or when it gets large
            now = time.time()
            if len(buffer_lines) >= 10 or now - init_time >= 5.0:
                for buffered_line in buffer_lines:
                    # Check for any useful info in non-progress lines
                    if "Duration:" in buffered_line:
                        LOGGER.debug(f"FFmpeg info: {buffered_line}")
                        duration_match = re.search(
                            r"Duration: (\d+):(\d+):(\d+)\.(\d+)", buffered_line
                        )
                        if duration_match and not encoder_helper.duration:
                            h, m, s, ms = map(int, duration_match.groups())
                            new_duration = h * 3600 + m * 60 + s + ms / 100
                            encoder_helper.set_duration(new_duration)
                            LOGGER.info(
                                f"Detected video duration: {new_duration} seconds"
                            )

                # Clear buffer after processing
                buffer_lines = []
                init_time = now

            # Force status updates periodically even without progress
            if (
                now - force_update_time >= 8.0
                and not has_progress_info
                and listener
                and gid
            ):
                force_update_time = now
                # Update status to show we're still alive
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
        # Make sure to stop the background task
        if listener and gid:
            stop_status_updates = True
            await asyncio.sleep(0.5)  # Give task time to stop cleanly
            try:
                if "status_update_task" in locals() and not status_update_task.done():
                    status_update_task.cancel()
            except Exception as e:
                LOGGER.debug(f"Error canceling status update task: {str(e)}")

    # Process stderr for additional info and progress updates
    stderr_data = await process.stderr.read()
    if stderr_data:
        stderr_lines = stderr_data.decode("utf-8", "ignore").split("\n")
        for line in stderr_lines:
            if line.strip():
                # Look for useful information in stderr
                if any(
                    info in line
                    for info in ["fps=", "time=", "frame=", "speed=", "bitrate="]
                ):
                    # This looks like progress information - update progress tracking
                    LOGGER.debug(f"FFmpeg stderr progress: {line}")
                    encoder_helper.update_progress(line)

                # Look for duration info if we don't have it yet or if current duration seems wrong
                elif "Duration:" in line:
                    LOGGER.debug(f"FFmpeg duration info: {line}")
                    duration_match = re.search(
                        r"Duration: (\d+):(\d+):(\d+)\.(\d+)", line
                    )
                    if duration_match:
                        h, m, s, ms = map(int, duration_match.groups())
                        new_duration = h * 3600 + m * 60 + s + ms / 100

                        # Update duration if we don't have one or if the new one is significantly different
                        if not encoder_helper.duration:
                            encoder_helper.set_duration(new_duration)
                            LOGGER.info(
                                f"Detected video duration from stderr: {new_duration} seconds"
                            )
                        elif (
                            abs(encoder_helper.duration - new_duration) > 5
                        ):  # More than 5 seconds difference
                            LOGGER.info(
                                f"Updating video duration from {encoder_helper.duration} to {new_duration} seconds (detected from stderr)"
                            )
                            encoder_helper.set_duration(new_duration)
                            # Reset progress to recalculate with correct duration
                            encoder_helper.progress_raw = 0.1
                elif "error" in line.lower() or "failed" in line.lower():
                    # Log errors
                    LOGGER.error(f"FFmpeg error: {line.strip()}")

    # Wait for process to complete
    await process.wait()

    if process.returncode != 0:
        LOGGER.error(f"Error encoding video: {stderr_data.decode('utf-8', 'ignore')}")
        return path

    LOGGER.info(f"Video encoding completed: {output_path}")

    # Update task_dict and status message after encoding is complete
    if listener and gid:
        # Set final values to indicate completion
        encoder_helper.progress_raw = 100
        encoder_helper.status_text = "Encoding complete"
        if encoder_helper.duration:
            encoder_helper.encoding_time = time.strftime(
                "%H:%M:%S", time.gmtime(encoder_helper.duration)
            )

        # Final status update to show completion
        LOGGER.info(
            f"Encoding complete for {os.path.basename(path)}, updating status messages"
        )

        # Update all status messages to reflect completion
        for sid in list(status_dict.keys()):
            try:
                await update_status_message(sid)
            except Exception as e:
                LOGGER.error(f"Error with final status update for {sid}: {str(e)}")

        # Ensure our specific chat is updated
        if hasattr(listener, "message") and hasattr(listener.message, "chat"):
            try:
                await update_status_message(listener.message.chat.id)
            except Exception as e:
                LOGGER.error(f"Error updating specific status on completion: {str(e)}")

    # Handle file replacement with custom filename
    if path != output_path:
        # Only delete the original if KEEP_MERGE_SOURCE_FILES is disabled
        keep_source_files = user_dict.get("KEEP_MERGE_SOURCE_FILES", False)
        if (
            not keep_source_files
            and os.path.exists(path)
            and os.path.exists(output_path)
        ):
            try:
                # Check if user has custom filename template
                custom_filename = user_dict.get("CUSTOM_FILENAME", "")
                if custom_filename:
                    # Get final filename with custom template applied
                    from bot.helper.ext_utils.watermark_utils import get_final_filename

                    final_path = get_final_filename(path, user_dict)
                    LOGGER.info(
                        f"KEEP_MERGE_SOURCE_FILES is disabled, applying custom filename: {final_path}"
                    )

                    # First verify that the encoded file is valid and has data
                    if os.path.getsize(output_path) > 0:
                        # Move encoded file to final custom filename
                        import shutil

                        shutil.move(output_path, final_path)
                        LOGGER.info(f"File encoded and renamed to: {final_path}")

                        # Remove original file if different from final path
                        if final_path != path and os.path.exists(path):
                            await remove(path)
                            LOGGER.info(f"Original file removed: {path}")

                        return final_path
                    else:
                        LOGGER.warning(
                            f"Encoded file is empty, keeping original: {path}"
                        )
                        return path
                else:
                    # Original behavior for non-custom filenames
                    LOGGER.info(
                        f"KEEP_MERGE_SOURCE_FILES is disabled, removing original file: {path}"
                    )
                    # First verify that the encoded file is valid and has data
                    if os.path.getsize(output_path) > 0:
                        await remove(path)
                        LOGGER.info(f"Original file removed: {path}")
                    else:
                        LOGGER.warning(
                            f"Encoded file is empty, keeping original: {path}"
                        )
            except Exception as e:
                LOGGER.error(f"Error handling encoded file: {str(e)}")
        else:
            # If keeping source files, apply custom filename if set
            custom_filename = user_dict.get("CUSTOM_FILENAME", "")
            if custom_filename and os.path.exists(output_path):
                try:
                    from bot.helper.ext_utils.watermark_utils import get_final_filename

                    final_path = get_final_filename(path, user_dict)
                    if final_path != output_path:
                        import shutil

                        shutil.move(output_path, final_path)
                        LOGGER.info(f"Encoded file renamed to: {final_path}")
                        return final_path
                except Exception as e:
                    LOGGER.error(f"Error applying custom filename: {str(e)}")

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

    # Get detailed stream information for better logging
    try:
        probe_cmd = [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_streams",
            str(path),
        ]
        probe_result = await create_subprocess_exec(
            *probe_cmd, stdout=PIPE, stderr=PIPE
        )
        stdout, stderr = await probe_result.communicate()

        if probe_result.returncode == 0:
            import json

            probe_data = json.loads(stdout.decode("utf-8"))
            streams = probe_data.get("streams", [])

            video_streams = []
            audio_streams = []
            subtitle_streams = []

            for i, stream in enumerate(streams):
                codec_name = stream.get("codec_name", "unknown")
                stream_type = stream.get("codec_type", "unknown")

                if stream_type == "video":
                    resolution = (
                        f"{stream.get('width', '?')}x{stream.get('height', '?')}"
                    )
                    video_streams.append(f"{codec_name}({resolution})")
                elif stream_type == "audio":
                    lang = stream.get("tags", {}).get(
                        "language", stream.get("tags", {}).get("title", "unknown")
                    )
                    channels = stream.get("channels", "?")
                    audio_streams.append(f"{codec_name}({lang},{channels}ch)")
                elif stream_type == "subtitle":
                    lang = stream.get("tags", {}).get(
                        "language", stream.get("tags", {}).get("title", "unknown")
                    )
                    subtitle_streams.append(f"{codec_name}({lang})")

            if video_streams:
                LOGGER.info(f"Video streams: {', '.join(video_streams)}")
            if audio_streams:
                LOGGER.info(
                    f"Audio streams: {', '.join(audio_streams)} (total: {len(audio_streams)})"
                )
            if subtitle_streams:
                LOGGER.info(
                    f"Subtitle streams: {', '.join(subtitle_streams)} (total: {len(subtitle_streams)})"
                )

    except Exception as e:
        LOGGER.debug(f"Detailed stream detection failed: {e}")

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

    # Create output filename
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
        status = FFmpegStatus(listener, converter_helper, gid, "Convert")

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


async def get_media_info(path):
    """
    Get media information using ffprobe
    :param path: Path to the media file
    :return: Dictionary with media information
    """
    try:
        cmd = [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            path,
        ]
        res, stdout, stderr = await cmd_exec(cmd)

        if res != 0:
            LOGGER.error(f"Error getting media info: {stderr}")
            return None

        return stdout
    except Exception as e:
        LOGGER.error(f"Error getting media info: {e}")
        return None


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


async def get_original_audio_bitrate_kbps(file_path: str) -> int | None:
    """Return the source audio bitrate in kbps for the first audio stream using ffprobe.

    Falls back to None if not found. Rounds to common bitrates to avoid odd values.
    """
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=bit_rate,codec_name",
            "-of",
            "json",
            file_path,
        ]
        process = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            return None
        import json

        data = json.loads(stdout.decode() or "{}")
        streams = data.get("streams", [])
        if not streams:
            return None
        br = streams[0].get("bit_rate")
        if not br:
            return None
        try:
            kbps = int(int(br) / 1000)
        except Exception:
            return None
        # Round to nearest typical value
        common = [64, 96, 112, 128, 160, 192, 224, 256, 320, 384, 448]
        nearest = min(common, key=lambda x: abs(x - kbps))
        # Avoid rounding down too far
        if kbps >= nearest + 12 and nearest < 448:
            # choose next higher if we under-shot significantly
            idx = common.index(nearest)
            nearest = common[min(idx + 1, len(common) - 1)]
        return nearest
    except Exception:
        return None
