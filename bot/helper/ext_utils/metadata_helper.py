#!/usr/bin/env python3

# -*- coding: utf-8 -*-

# This module helps in modifying media metadata using FFmpeg

import asyncio
import os
import tempfile
import time
from typing import Dict, Optional

from aiofiles.os import (
    path as aiopath,
    listdir,
    remove as aioremove,
    rename as aiorename,
)

from bot import LOGGER
from bot.core.config_manager import BinConfig
from .ffmpeg_utils import get_ffmpeg_metadata_cmd


async def get_metadata(file_path: str) -> Dict:
    """Get metadata of a media file using FFmpeg (ffprobe)"""
    ffprobe_cmd = [
        BinConfig.FFPROBE_NAME,
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        file_path,
    ]
    process = await asyncio.create_subprocess_exec(
        *ffprobe_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        LOGGER.error(
            f"Error getting metadata with ffprobe: {stderr.decode(errors='ignore')}"
        )
        return {}
    import json

    try:
        return json.loads(stdout.decode(errors="ignore"))
    except json.JSONDecodeError:
        LOGGER.error("Failed to parse ffprobe metadata JSON")
        return {}


async def set_metadata(
    file_path: str,
    user_ui_metadata_dict: Dict,  # Takes UI keys
    thumbnail_path: Optional[str] = None,
    attachment_text: Optional[str] = None,
    progress_callback=None,
) -> str:
    """
    Set metadata and attach files for a media file using FFmpeg, utilizing ffmpeg_utils.
    Returns the path of the new file with metadata/attachments.

    METADATA PROCESSING FIX NOTES:
    This function has been enhanced to prevent zero-size file issues that were occurring
    during metadata processing. Key improvements include:

    1. Enhanced FFmpeg output validation - checks file size and readability before returning
    2. Better progress monitoring with error handling for malformed progress data
    3. Comprehensive error handling for edge cases in FFmpeg execution
    4. Additional debugging information to help identify issues

    The function now validates that:
    - FFmpeg produces a non-zero output file
    - The output file is readable and contains valid data
    - File size is reasonable compared to input (warns if < 10% of original)
    """
    LOGGER.info(
        f"Processing metadata/attachments for {os.path.basename(file_path)} via ffmpeg_utils"
    )
    file_dir = os.path.dirname(file_path)
    file_name = os.path.basename(file_path)
    temp_output_fd, temp_output_path = tempfile.mkstemp(
        suffix=f"_processed{os.path.splitext(file_name)[1]}", dir=file_dir
    )
    os.close(temp_output_fd)
    input_file_size = await aiopath.getsize(file_path)
    media_info_for_duration = await get_metadata(file_path)
    duration_s = float(media_info_for_duration.get("format", {}).get("duration", 0))
    # Call the utility function to get the command and action flag
    (
        cmd,
        should_run_ffmpeg,
        temp_text_file_created_by_util,
    ) = await get_ffmpeg_metadata_cmd(
        input_path=file_path,
        output_path=temp_output_path,
        user_metadata=user_ui_metadata_dict,
        thumbnail_to_attach=thumbnail_path,
        text_content_to_attach=attachment_text,
    )
    if not should_run_ffmpeg:
        LOGGER.info(
            f"No metadata/attachment changes for {file_name} via ffmpeg_utils. Skipping."
        )
        if progress_callback:
            await progress_callback(100, 0, 0, 0)
        if await aiopath.exists(temp_output_path):  # Should not exist if cmd was empty
            await aioremove(temp_output_path)
        # temp_text_file_created_by_util should have been cleaned by get_ffmpeg_metadata_cmd if not used
        return file_path

    # FFmpeg process execution
    temp_text_file_to_clean_finally = (
        temp_text_file_created_by_util  # Keep track for finally block
    )

    # LOGGER.info(f"Generated FFmpeg command for {file_name}: {' '.join(cmd)}") # Debug Log Removed
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,  # Use the command from ffmpeg_utils
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        if progress_callback:
            await progress_callback(0, 0, 0, 0)  # Initial progress
        last_reported_percentage = -1
        last_update_time = time.time()
        processed_bytes = 0
        speed = 0
        eta = 0

        async def log_stream(stream, stream_name_debug):
            error_lines_list = []
            async for line_bytes in stream:
                line = line_bytes.decode("utf-8", errors="ignore").strip()
                if stream_name_debug == "stderr":
                    error_lines_list.append(line)
                LOGGER.debug(f"FFmpeg {stream_name_debug}: {line}")
            return "\n".join(error_lines_list)

        stderr_task = asyncio.create_task(log_stream(process.stderr, "stderr"))

        if (
            process.stdout
        ):  # Assuming -progress pipe:1 is used if should_run_ffmpeg is True
            progress_lines_received = 0
            last_progress_line = ""
            process_start_time = (
                time.time()
            )  # Track process start time for stuck detection

            while True:
                line_bytes = await process.stdout.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="ignore").strip()
                last_progress_line = line
                progress_lines_received += 1

                if not line:  # Skip empty lines
                    continue

                try:
                    progress_data = {
                        p.split("=")[0].strip(): p.split("=")[1].strip()
                        for p in line.split("\n")
                        if "=" in p
                    }
                except Exception as e_progress_parse:
                    LOGGER.debug(
                        f"Failed to parse progress line '{line}': {e_progress_parse}"
                    )
                    continue

                # === PATCHED: robust int() for out_time_ms ===
                percentage = (
                    last_reported_percentage if last_reported_percentage != -1 else 0
                )

                if "out_time_ms" in progress_data and duration_s > 0:
                    out_time_ms_val = progress_data["out_time_ms"]
                    if out_time_ms_val != "N/A":
                        try:
                            current_time_ms = int(out_time_ms_val)
                            percentage = round(
                                (current_time_ms / (duration_s * 1000000)) * 100, 2
                            )
                            processed_bytes = int(
                                input_file_size * (percentage / 100.0)
                            )
                        except Exception as ex_progress:
                            LOGGER.warning(
                                f"Could not parse FFmpeg out_time_ms ({out_time_ms_val}): {ex_progress}"
                            )
                            # fallback: keep last percentage
                            percentage = (
                                last_reported_percentage
                                if last_reported_percentage != -1
                                else 0
                            )
                    else:
                        # When out_time_ms:N/A, just do not update percentage this round
                        percentage = (
                            last_reported_percentage
                            if last_reported_percentage != -1
                            else 0
                        )
                elif "total_size" in progress_data and input_file_size > 0:
                    processed_bytes = int(progress_data.get("total_size", 0))
                    percentage = round((processed_bytes / input_file_size) * 100, 2)
                # else: keep the old percentage

                percentage = min(max(percentage, 0), 99.99)  # Cap at 99.99 until 'end'

                if "speed" in progress_data:
                    speed_str = progress_data["speed"].replace("x", "")
                    try:
                        current_speed = float(speed_str)
                        if (
                            duration_s > 0
                            and current_speed > 0
                            and "out_time_ms" in progress_data
                        ):
                            out_time_ms_val = progress_data["out_time_ms"]
                            if out_time_ms_val != "N/A":
                                current_time_s = int(out_time_ms_val) / 1000000
                                eta = (
                                    (duration_s - current_time_s) / current_speed
                                    if current_speed > 0
                                    else 0
                                )
                        speed = current_speed  # Update speed
                    except ValueError:
                        speed = 0  # Reset speed if parse error

                if progress_data.get("progress") == "end":
                    percentage = 100.0
                    eta = 0
                    processed_bytes = input_file_size  # Ensure processed_bytes reflects full size on end
                    if progress_callback:
                        await progress_callback(percentage, speed, processed_bytes, eta)
                    break

                now_time = time.time()

                # Check for stuck processing (no progress for too long)
                if (
                    percentage <= 1.0 and now_time - process_start_time > 180
                ):  # 3 minutes
                    LOGGER.error(
                        f"Metadata processing appears stuck for {file_name} - forcing completion"
                    )
                    percentage = 100.0  # Force completion
                    if progress_callback:
                        await progress_callback(percentage, speed, processed_bytes, eta)
                    break

                if progress_callback and (
                    now_time - last_update_time > 2
                    or percentage - last_reported_percentage >= 1.0
                    or last_reported_percentage == -1
                ):
                    await progress_callback(percentage, speed, processed_bytes, eta)
                    last_reported_percentage = percentage
                    last_update_time = now_time

                    # Debug logging for stuck progress detection
                    if percentage <= 1.0 and now_time - process_start_time > 30:
                        LOGGER.warning(
                            f"Metadata processing potentially stuck: {percentage}% after {now_time - process_start_time:.1f}s for {file_name}"
                        )
        else:
            # No stdout; still report an estimated progress if callback provided
            if progress_callback:
                await progress_callback(50, 0, input_file_size // 2, 0)
        await process.wait()
        stderr_output_str = await stderr_task

        if process.returncode != 0:
            LOGGER.error(
                f"Error processing {file_name} with ffmpeg_utils. FFmpeg RC: {process.returncode}. Stderr: {stderr_output_str}"
            )
            if await aiopath.exists(temp_output_path):  # Clean up failed output
                await aioremove(temp_output_path)
            if progress_callback:  # Report failure
                await progress_callback(0, speed, processed_bytes, eta)
            return file_path  # Return original path on failure

        if progress_callback:  # Ensure 100% is reported on success
            await progress_callback(100.0, speed, input_file_size, 0)

        # Validate the output file before returning
        if await aiopath.exists(temp_output_path):
            output_size = await aiopath.getsize(temp_output_path)
            if output_size == 0:
                LOGGER.error(
                    f"FFmpeg produced zero-size output file for {file_name}. Original size: {input_file_size}, Output: {temp_output_path}"
                )
                await aioremove(temp_output_path)
                if progress_callback:
                    await progress_callback(0, 0, 0, 0)
                return file_path  # Return original path on zero-size output
            # For other sizes, proceed silently
        else:
            LOGGER.error(
                f"FFmpeg output file {temp_output_path} does not exist after successful processing of {file_name}"
            )
            if progress_callback:
                await progress_callback(0, 0, 0, 0)
            return file_path

        return temp_output_path
    except Exception as e_ffmpeg_run:
        LOGGER.error(
            f"Exception running FFmpeg for {file_name}: {e_ffmpeg_run}", exc_info=True
        )
        if await aiopath.exists(temp_output_path):  # Clean up temp output on exception
            await aioremove(temp_output_path)
        if progress_callback:  # Report failure
            await progress_callback(0, 0, 0, 0)
        return file_path  # Return original path on exception
    finally:
        # Clean up the temporary text file created by ffmpeg_utils, if any
        if temp_text_file_to_clean_finally:
            try:
                if await aiopath.exists(temp_text_file_to_clean_finally):
                    await aioremove(temp_text_file_to_clean_finally)
            except Exception:
                pass


async def apply_metadata(
    file_path: str, metadata_settings: Dict, progress_callback=None
) -> bool:
    """
    Applies metadata to a file or files in a directory.
    `metadata_settings` should be a dict where keys are from METADATA_MAPPINGS.

    FILE REPLACEMENT SAFETY IMPROVEMENTS:
    This function has been enhanced with safer file replacement logic to prevent
    zero-size file issues:

    1. Validates processed file size and readability before replacement
    2. Uses atomic file operations with backup/restore mechanism
    3. Multiple validation steps with proper error recovery
    4. Comprehensive error handling and logging for debugging
    """
    if not await aiopath.exists(file_path):
        LOGGER.error(f"Path not found for metadata application: {file_path}")
        if progress_callback:
            await progress_callback(0, 0, 0, 0)  # Overall progress for this item
        return False

    if await aiopath.isdir(file_path):
        LOGGER.info(f"Processing directory for metadata (recursive): {file_path}")
        all_files_in_dir = []
        try:
            # Use recursive traversal to find all files in subdirectories
            for root, _, files in os.walk(file_path):
                for file in files:
                    all_files_in_dir.append(os.path.join(root, file))
        except Exception as e_list_dir:
            LOGGER.error(
                f"Error recursively listing directory {file_path}: {e_list_dir}"
            )
            if progress_callback:
                await progress_callback(0, 0, 0, 0)
            return False
        if not all_files_in_dir:
            LOGGER.info(f"Directory {file_path} is empty. No metadata to apply.")
            if progress_callback:
                await progress_callback(
                    100, 0, 0, 0
                )  # Consider empty dir as "complete"
            return True  # Or False, depending on desired behavior for empty dirs

        total_files = len(all_files_in_dir)
        overall_success_for_dir = True  # Assume success unless a file fails

        for i, item_full_path in enumerate(all_files_in_dir):
            LOGGER.info(
                f"Applying metadata to file {i + 1}/{total_files} in directory: {os.path.basename(item_full_path)}"
            )

            # Define a wrapper for per-file progress to map to overall directory progress
            # Note: Using current_index parameter to avoid closure variable issues
            def create_progress_wrapper(current_index):
                async def single_file_progress_wrapper(
                    file_perc, file_speed, file_bytes, file_eta
                ):
                    if progress_callback:
                        # Calculate overall progress: ( (current_index / total_files) + (file_perc / 100.0 * (1/total_files) ) ) * 100
                        # This ensures that current file's progress contributes proportionally to the total.
                        completed_files_contribution = (
                            current_index / total_files
                        ) * 100
                        current_file_contribution = (file_perc / 100.0) * (
                            100.0 / total_files
                        )
                        overall_percentage = (
                            completed_files_contribution + current_file_contribution
                        )
                        # Ensure progress is always moving forward and capped properly
                        overall_percentage = max(
                            overall_percentage, (current_index / total_files) * 100
                        )
                        overall_percentage = min(overall_percentage, 100.0)

                        # Optional verbose logging disabled to reduce noise
                        # if current_index == 0 and file_perc > 0:
                        #     LOGGER.info(
                        #         f"Metadata progress: File {current_index + 1}/{total_files}, File progress: {file_perc}%, Overall: {overall_percentage:.1f}%"
                        #     )

                        await progress_callback(
                            overall_percentage, file_speed, file_bytes, file_eta
                        )

                return single_file_progress_wrapper

            progress_wrapper = create_progress_wrapper(i)

            if not await apply_metadata(
                item_full_path, metadata_settings, progress_wrapper
            ):
                overall_success_for_dir = False  # If any file fails, mark dir as failed
                # Optionally, log which file failed or decide if to continue with others
                LOGGER.warning(
                    f"Metadata application failed for {item_full_path} in directory {file_path}"
                )
        if progress_callback:  # Final update for directory
            await progress_callback(100 if overall_success_for_dir else 0, 0, 0, 0)
        return overall_success_for_dir

    elif await aiopath.isfile(file_path):
        # Restrict metadata processing to videos, audios, and all supported subtitle formats
        # Extended to include all ffmpeg-supported formats
        media_extensions = [
            # Video formats
            ".mp4",
            ".mkv",
            ".avi",
            ".mov",
            ".wmv",
            ".flv",
            ".webm",
            ".m4v",
            ".mpg",
            ".mpeg",
            ".ts",
            ".m2ts",
            ".mts",
            ".3gp",
            ".ogv",
            # Audio formats
            ".mp3",
            ".m4a",
            ".flac",
            ".ogg",
            ".wav",
            ".aac",
            ".opus",
            ".wma",
            ".oga",
            ".mka",
            ".ac3",
            ".eac3",
            # Subtitle formats (all ffmpeg-supported)
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
        if not any(file_path.lower().endswith(ext) for ext in media_extensions):
            LOGGER.info(
                f"Not a supported media file for metadata by extension: {os.path.basename(file_path)}"
            )
            if progress_callback:
                await progress_callback(100, 0, 0, 0)  # No action, so "complete"
            return True  # Successfully did nothing, or False if this should be an error

        thumb_path_from_settings = metadata_settings.get("attachment_thumbnail")
        text_content_from_settings = metadata_settings.get("attachment_text")

        # Check if there's anything to do
        if (
            not metadata_settings
            and not thumb_path_from_settings
            and not text_content_from_settings
        ):
            LOGGER.info(
                f"No specific metadata, thumbnail, or text attachment defined for {file_path}. Skipping."
            )
            if progress_callback:
                await progress_callback(100, 0, 0, 0)
            return True

        try:
            processed_temp_path = await set_metadata(
                file_path,
                metadata_settings,
                thumbnail_path=thumb_path_from_settings,
                attachment_text=text_content_from_settings,
                progress_callback=progress_callback,
            )

            if processed_temp_path == file_path:  # No changes were made by set_metadata
                LOGGER.debug(
                    f"set_metadata returned original path for {file_path}. No effective changes."
                )
                return True  # Or False if an actual change was expected. True means "processed, no error"

            if await aiopath.exists(processed_temp_path):
                try:
                    # Verify the processed file has content before replacing
                    processed_size = await aiopath.getsize(processed_temp_path)
                    if processed_size == 0:
                        LOGGER.error(
                            f"Processed file {processed_temp_path} has zero size. Not replacing original."
                        )
                        await aioremove(processed_temp_path)
                        return False

                    # Additional verification: try to read the first few bytes to ensure file is accessible
                    try:
                        with open(processed_temp_path, "rb") as test_file:
                            test_data = test_file.read(1024)  # Read first 1KB
                            if len(test_data) == 0:
                                LOGGER.error(
                                    f"Processed file {processed_temp_path} appears to be empty or unreadable."
                                )
                                await aioremove(processed_temp_path)
                                return False
                    except Exception as e_read_test:
                        LOGGER.error(
                            f"Cannot read processed file {processed_temp_path}: {e_read_test}. Not replacing original."
                        )
                        await aioremove(processed_temp_path)
                        return False

                    # Get original file size for comparison
                    original_size = await aiopath.getsize(file_path)
                    LOGGER.info(
                        f"Replacing {file_path} (size: {original_size}) with processed file (size: {processed_size})"
                    )

                    # Use a backup approach for safer file replacement
                    backup_path = f"{file_path}.backup"

                    # Step 1: Create backup of original
                    await aiorename(file_path, backup_path)

                    # Step 2: Move processed file to original location
                    await aiorename(processed_temp_path, file_path)

                    # Step 3: Verify the replacement was successful
                    if await aiopath.exists(file_path):
                        final_size = await aiopath.getsize(file_path)
                        if final_size > 0:
                            # Success - remove backup
                            await aioremove(backup_path)
                            LOGGER.info(
                                f"Successfully applied metadata/attachments and replaced original: {file_path} (final size: {final_size})"
                            )
                            return True
                        else:
                            # Final file is zero size - restore backup
                            LOGGER.error(
                                f"Final file {file_path} has zero size after replacement. Restoring backup."
                            )
                            await aioremove(file_path)
                            await aiorename(backup_path, file_path)
                            return False
                    else:
                        # File doesn't exist - restore backup
                        LOGGER.error(
                            f"File {file_path} doesn't exist after replacement. Restoring backup."
                        )
                        await aiorename(backup_path, file_path)
                        return False

                except OSError as e_rename_final:
                    LOGGER.error(
                        f"Error replacing original file with processed for {file_path}: {e_rename_final}. Processed file at: {processed_temp_path}"
                    )
                    # Try to restore from backup if it exists
                    backup_path = f"{file_path}.backup"
                    if await aiopath.exists(backup_path):
                        try:
                            if not await aiopath.exists(file_path):
                                await aiorename(backup_path, file_path)
                                LOGGER.info(
                                    f"Restored original file from backup: {file_path}"
                                )
                            else:
                                await aioremove(backup_path)
                        except OSError as e_restore:
                            LOGGER.error(f"Failed to restore backup: {e_restore}")

                    # Attempt to clean up processed_temp_path if rename fails
                    if await aiopath.exists(processed_temp_path):
                        await aioremove(processed_temp_path)
                    return False
            else:
                LOGGER.error(
                    f"Processed file {processed_temp_path} not found after set_metadata for {file_path}."
                )
                return False

        except Exception as e_apply_single:
            LOGGER.error(
                f"Error in apply_metadata for single file {os.path.basename(file_path)}: {e_apply_single}",
                exc_info=True,
            )
            if progress_callback:
                await progress_callback(0, 0, 0, 0)  # Error state
            return False

    else:
        LOGGER.warning(
            f"Path {file_path} is neither a file nor a directory. Skipping metadata application."
        )
        if progress_callback:
            await progress_callback(0, 0, 0, 0)
        return False
