#!/usr/bin/env python3
"""
Stream Extractor module for extracting audio and subtitle tracks from video files
"""

from asyncio import create_subprocess_exec, gather, sleep, Event
from asyncio.subprocess import PIPE
from os import path as ospath
from aiofiles.os import makedirs, listdir, remove, path as aiopath
from time import time
import json
import re
from contextlib import suppress

from ... import LOGGER, user_data
from ..telegram_helper.button_build import ButtonMaker
from ..telegram_helper.message_utils import send_message, edit_message, send_file

# Dictionary to store stream extraction sessions
extract_sessions = {}

# Dictionary to track active extraction processes to prevent cleanup
active_extractions = {}


class StreamExtractor:
    def __init__(self, listener, video_path):
        """
        Initialize a stream extraction session

        Parameters:
        listener: The listener object for this task
        video_path (str): Path to the video file
        """
        self.listener = listener
        self.video_path = video_path
        self.user_id = listener.message.from_user.id
        self.message = None
        self.streams_info = None
        self.selected_streams = {"audio": [], "subtitle": []}
        self.extracted_files = {}
        self.session_id = f"{self.user_id}_{int(time())}"
        self.extraction_complete = Event()

        # Register this extraction as active
        active_extractions[self.session_id] = {
            "path": video_path,
            "listener_mid": listener.mid,
            "complete": self.extraction_complete,
        }
        LOGGER.info(
            f"Registered active extraction for session {self.session_id} - {video_path}"
        )

    @staticmethod
    def clean_filename(filename):
        """Clean filename to make it safe for display"""
        return re.sub(r'[\\/*?:"<>|]', "", filename)

    async def analyze_streams(self):
        """Analyze video file to identify all available streams"""
        try:
            # Run ffprobe to get stream information
            cmd = [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                "-show_format",
                self.video_path,
            ]
            process = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                LOGGER.error(f"Error analyzing video streams: {stderr.decode()}")
                return False

            # Parse ffprobe output
            info = json.loads(stdout.decode())

            self.streams_info = {
                "format": info.get("format", {}),
                "video": [],
                "audio": [],
                "subtitle": [],
                "other": [],
            }

            # Process streams by type
            for i, stream in enumerate(info.get("streams", [])):
                codec_type = stream.get("codec_type", "unknown")
                stream_data = {
                    "index": i,
                    "codec_name": stream.get("codec_name", "unknown"),
                    "language": stream.get("tags", {}).get("language", "und"),
                    "title": stream.get("tags", {}).get("title", ""),
                }

                # Add type-specific info
                if codec_type == "audio":
                    stream_data.update(
                        {
                            "channels": stream.get("channels", 2),
                            "sample_rate": stream.get("sample_rate", "48000"),
                            "bit_rate": stream.get("bit_rate", "unknown"),
                        }
                    )
                    self.streams_info["audio"].append(stream_data)
                elif codec_type == "subtitle":
                    self.streams_info["subtitle"].append(stream_data)
                elif codec_type == "video":
                    stream_data.update(
                        {
                            "width": stream.get("width", 0),
                            "height": stream.get("height", 0),
                            "fps": stream.get("r_frame_rate", "0/0"),
                        }
                    )
                    self.streams_info["video"].append(stream_data)
                else:
                    self.streams_info["other"].append(stream_data)

            return True
        except Exception as e:
            LOGGER.error(f"Error in analyze_streams: {str(e)}")
            return False

    def get_stream_description(self, stream_type, stream):
        """Generate a human-readable description of a stream"""
        lang = stream.get("language", "unknown")
        title = stream.get("title", "")
        codec = stream.get("codec_name", "unknown")

        # Try to get language name
        try:
            try:
                from langcodes import Language

                with suppress(Exception):
                    lang_display = Language.get(lang).display_name()
                    if lang_display:
                        lang = lang_display
            except ImportError:
                # If langcodes is not available, use a simple language mapping
                lang_map = {
                    "eng": "English",
                    "jpn": "Japanese",
                    "kor": "Korean",
                    "chi": "Chinese",
                    "fre": "French",
                    "ger": "German",
                    "ita": "Italian",
                    "spa": "Spanish",
                    "rus": "Russian",
                    "hin": "Hindi",
                    "por": "Portuguese",
                    "ara": "Arabic",
                }
                lang = lang_map.get(lang, lang)
        except:
            pass

        description = f"#{stream['index']}: {codec}"

        if stream_type == "audio":
            channels = stream.get("channels", 2)
            if channels > 0:
                ch_text = "mono" if channels == 1 else f"{channels}ch"
                description += f" ({ch_text})"

        if lang and lang != "und":
            description += f" - {lang}"

        if title:
            description += f" - {title}"

        return description

    async def create_selection_message(self):
        """Create the stream selection interface message"""
        try:
            if not self.streams_info:
                if not await self.analyze_streams():
                    await send_message(
                        self.listener.message, "❌ Error analyzing video streams"
                    )
                    # Mark extraction as complete since it failed
                    if self.session_id in active_extractions:
                        active_extractions[self.session_id]["complete"].set()
                    return False

            # Get video filename for display
            video_name = ospath.basename(self.video_path)

            # Build the selection message
            text = f"<b>Stream Extraction</b>\n\n"
            text += f"<b>File:</b><b><i> {video_name}</i></b>\n\n"
            text += f"<b>Instructions:</b> Select audio/subtitle tracks to extract, then click 'Extract'\n\n"
            text += f"<b>Note:</b> This menu will timeout after 10 minutes if no action is taken\n\n"

            # Add audio streams section
            if self.streams_info["audio"]:
                text += "🔊 <b>Audio Tracks:</b>\n"
                for i, stream in enumerate(self.streams_info["audio"]):
                    check = "✓" if i in self.selected_streams["audio"] else "»"
                    text += f"{check} {self.get_stream_description('audio', stream)}\n"
                text += "\n"
            else:
                text += "✘ <b>No audio tracks found</b>\n\n"

            # Add subtitle streams section
            if self.streams_info["subtitle"]:
                text += "📝 <b>Subtitle Tracks:</b>\n"
                for i, stream in enumerate(self.streams_info["subtitle"]):
                    check = "✓" if i in self.selected_streams["subtitle"] else "»"
                    text += (
                        f"{check} {self.get_stream_description('subtitle', stream)}\n"
                    )
                text += "\n"
            else:
                text += "✘ <b>No subtitle tracks found</b>\n\n"

            # Create buttons
            buttons = ButtonMaker()

            # Add audio track selection buttons
            for i in range(
                min(len(self.streams_info["audio"]), 10)
            ):  # Limit to 10 tracks for UI
                action = "remove" if i in self.selected_streams["audio"] else "add"
                stream_index = self.streams_info["audio"][i]["index"]
                buttons.data_button(
                    f"Audio #{stream_index}",
                    f"extract {self.session_id} toggle_audio {i}",
                )
        except Exception as e:
            LOGGER.error(f"Error creating stream extraction message: {str(e)}")
            # Mark extraction as complete since it failed
            if self.session_id in active_extractions:
                active_extractions[self.session_id]["complete"].set()
            return False

        # Add subtitle track selection buttons
        for i in range(
            min(len(self.streams_info["subtitle"]), 10)
        ):  # Limit to 10 tracks for UI
            action = "remove" if i in self.selected_streams["subtitle"] else "add"
            stream_index = self.streams_info["subtitle"][i]["index"]
            buttons.data_button(
                f"Sub #{stream_index}", f"extract {self.session_id} toggle_subtitle {i}"
            )

        # Add action buttons
        buttons.data_button("Extract", f"extract {self.session_id} extract")
        buttons.data_button("✘", f"extract {self.session_id} cancel")

        try:
            # If this is the first message, send it, otherwise edit
            if self.message is None:
                self.message = await send_message(
                    self.listener.message, text, buttons.build_menu(2)
                )
            else:
                await edit_message(self.message, text, buttons.build_menu(2))

            # Store this session
            extract_sessions[self.session_id] = self
            return True
        except Exception as e:
            LOGGER.error(f"Error sending stream extraction message: {str(e)}")
            # Mark extraction as complete since it failed
            if self.session_id in active_extractions:
                active_extractions[self.session_id]["complete"].set()
            return False

    def toggle_stream(self, stream_type, index):
        """Toggle selection state of a stream"""
        try:
            index = int(index)
            if stream_type not in ["audio", "subtitle"]:
                return False

            max_index = len(self.streams_info[stream_type])
            if index < 0 or index >= max_index:
                return False

            if index in self.selected_streams[stream_type]:
                self.selected_streams[stream_type].remove(index)
            else:
                self.selected_streams[stream_type].append(index)

            return True
        except Exception as e:
            LOGGER.error(f"Error toggling stream: {e}")
            return False

    async def cancel_extraction(self):
        """Cancel the extraction process"""
        if self.message:
            await edit_message(self.message, "Stream extraction cancelled...")

        # Remove session
        if self.session_id in extract_sessions:
            del extract_sessions[self.session_id]

        # Mark extraction as complete
        if self.session_id in active_extractions:
            LOGGER.info(
                f"Setting extraction complete flag in cancel_extraction for {self.session_id}"
            )
            active_extractions[self.session_id]["complete"].set()

        return True

    async def extract_selected_streams(self):
        """Extract selected audio and subtitle streams"""
        if not self.selected_streams["audio"] and not self.selected_streams["subtitle"]:
            await edit_message(self.message, "✘ No streams selected for extraction")
            return False

        # Check if we should keep source files
        self.keep_source_files = self.listener.user_dict.get(
            "KEEP_MERGE_SOURCE_FILES", False
        )

        # Get video base name and directory
        video_dir = ospath.dirname(self.video_path)
        video_basename = ospath.basename(self.video_path)
        video_name = ospath.splitext(video_basename)[0]

        # Create extraction directory
        extract_dir = ospath.join(video_dir, f"extracted_{video_name}")
        await makedirs(extract_dir, exist_ok=True)

        # Update message
        await edit_message(
            self.message,
            "🔄 Extracting selected streams...\n\nThis may take a few minutes.",
        )

        extracted_files = {"audio": {}, "subtitle": {}}
        extract_tasks = []

        # Prepare extraction commands for audio
        for audio_idx in self.selected_streams["audio"]:
            if audio_idx >= len(self.streams_info["audio"]):
                continue

            stream = self.streams_info["audio"][audio_idx]
            stream_index = stream["index"]

            # Get language and title
            lang = stream.get("language", "und")
            title = self.clean_filename(stream.get("title", f"Audio {audio_idx}"))

            # Determine output extension
            codec = stream.get("codec_name", "").lower()
            if codec in ("aac", "mp3", "opus", "flac"):
                ext = codec
            elif codec.startswith("ac3") or codec.startswith("eac3"):
                ext = "ac3"
            elif codec.startswith("dts"):
                ext = "dts"
            else:
                ext = "mka"  # Use Matroska Audio container for compatibility

            # Clean up language code
            safe_lang = lang.strip() if lang and lang != "und" else "und"

            # Create output filename with custom template support
            user_dict = self.listener.user_dict
            custom_filename = user_dict.get("CUSTOM_FILENAME", "")
            if custom_filename:
                # Apply custom filename template for audio extraction
                from pathlib import Path

                original_name = Path(self.video_path).stem
                original_ext = Path(self.video_path).suffix
                custom_base = custom_filename.replace("{name}", original_name).replace(
                    "{ext}", original_ext.lstrip(".")
                )
                # Remove extension from custom base and add audio-specific suffix
                custom_base_no_ext = Path(custom_base).stem
                output_file = ospath.join(
                    extract_dir,
                    f"{custom_base_no_ext}_audio{audio_idx}_{safe_lang}.{ext}",
                )
            else:
                # Default behavior
                output_file = ospath.join(
                    extract_dir, f"{video_name}_audio{audio_idx}_{safe_lang}.{ext}"
                )

            # Build command
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                self.video_path,
                "-map",
                f"0:{stream_index}",
            ]

            # Use appropriate codec handling based on extension
            if ext == "ac3" and codec != "ac3":
                # Force re-encoding to AC3 if output is AC3 but input is not
                cmd.extend(["-c:a", "ac3"])
            elif ext in ("aac", "mp3", "opus", "flac") and codec != ext:
                # Force re-encoding to match container if codec doesn't match
                cmd.extend(["-c:a", ext])
            else:
                # Otherwise try to copy
                cmd.extend(["-c:a", "copy"])

            # Add metadata
            cmd.extend(
                ["-metadata", f"title={title}", "-metadata", f"language={safe_lang}"]
            )

            # Add output file
            cmd.extend([output_file, "-y"])

            # Add task
            extract_tasks.append((cmd, output_file, f"audio{audio_idx}", stream))

        # Prepare extraction commands for subtitles
        for sub_idx in self.selected_streams["subtitle"]:
            if sub_idx >= len(self.streams_info["subtitle"]):
                continue

            stream = self.streams_info["subtitle"][sub_idx]
            stream_index = stream["index"]

            # Get language and title
            lang = stream.get("language", "und")
            title = self.clean_filename(stream.get("title", f"Subtitle {sub_idx}"))

            # Determine output extension
            codec = stream.get("codec_name", "").lower()
            if codec in ("subrip", "srt"):
                ext = "srt"
            elif codec in ("ass", "ssa"):
                ext = "ass"
            elif codec == "webvtt":
                ext = "vtt"
            elif codec in ("dvd_subtitle", "dvbsub", "hdmv_pgs_subtitle"):
                ext = "sup"  # For bitmap subtitles
            else:
                ext = "srt"  # Default to SRT

            # Clean up language code
            safe_lang = lang.strip() if lang and lang != "und" else "und"

            # Create output filename with custom template support
            user_dict = self.listener.user_dict
            custom_filename = user_dict.get("CUSTOM_FILENAME", "")
            if custom_filename:
                # Apply custom filename template for subtitle extraction
                from pathlib import Path

                original_name = Path(self.video_path).stem
                original_ext = Path(self.video_path).suffix
                custom_base = custom_filename.replace("{name}", original_name).replace(
                    "{ext}", original_ext.lstrip(".")
                )
                # Remove extension from custom base and add subtitle-specific suffix
                custom_base_no_ext = Path(custom_base).stem
                output_file = ospath.join(
                    extract_dir,
                    f"{custom_base_no_ext}_subtitle{sub_idx}_{safe_lang}.{ext}",
                )
            else:
                # Default behavior
                output_file = ospath.join(
                    extract_dir, f"{video_name}_subtitle{sub_idx}_{safe_lang}.{ext}"
                )

            # Build command
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                self.video_path,
                "-map",
                f"0:{stream_index}",
            ]

            # For bitmap-based subtitles, we must copy; for text-based we can convert
            if codec in ("dvd_subtitle", "dvbsub", "hdmv_pgs_subtitle"):
                cmd.extend(["-c:s", "copy"])
            else:
                # Try to convert to the desired format - specify subtitle codec properly
                if ext == "srt":
                    cmd.extend(["-c:s", "subrip"])
                elif ext == "ass":
                    cmd.extend(["-c:s", "ass"])
                elif ext == "vtt":
                    cmd.extend(["-c:s", "webvtt"])
                else:
                    # Default to copy if we don't have a specific converter
                    cmd.extend(["-c:s", "copy"])

            # Add output file
            cmd.extend([output_file, "-y"])

            # Add task
            extract_tasks.append((cmd, output_file, f"subtitle{sub_idx}", stream))

        # Execute extraction tasks
        success_count = 0
        failed_count = 0

        for cmd, output_file, stream_id, stream_info in extract_tasks:
            try:
                # Log command being executed
                cmd_str = " ".join(cmd)
                LOGGER.info(f"Extracting {stream_id}: {cmd_str}")

                # Execute FFmpeg command
                process = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
                stdout, stderr = await process.communicate()

                # Check if file exists
                file_exists = False
                try:
                    file_exists = await aiopath.exists(output_file)
                except Exception as e:
                    LOGGER.error(f"Error checking if file exists: {str(e)}")

                if process.returncode == 0 and file_exists:
                    # Extraction successful
                    stream_type = (
                        "audio" if stream_id.startswith("audio") else "subtitle"
                    )
                    idx = int(stream_id.replace("audio", "").replace("subtitle", ""))

                    # Store extraction details
                    extracted_files[stream_type][idx] = {
                        "path": output_file,
                        "filename": ospath.basename(output_file),
                        "stream_info": stream_info,
                    }
                    success_count += 1
                    LOGGER.info(f"Successfully extracted {stream_id} to {output_file}")
                else:
                    # Extraction failed - log detailed error information
                    stderr_text = stderr.decode() if stderr else "Unknown error"
                    stdout_text = stdout.decode() if stdout else ""
                    LOGGER.error(
                        f"Error extracting {stream_id} (return code: {process.returncode})"
                    )
                    LOGGER.error(f"Command: {cmd_str}")
                    LOGGER.error(f"Error message: {stderr_text}")
                    if stdout_text:
                        LOGGER.info(f"FFmpeg stdout: {stdout_text}")
                    failed_count += 1

                    # Try to recover from AC3 error by switching to MKA format if this is an audio extraction
                    if (
                        "ac3 muxer supports only codec ac3" in stderr_text
                        and stream_id.startswith("audio")
                    ):
                        try:
                            LOGGER.info(
                                f"Detected AC3 codec mismatch, attempting to retry with MKA container"
                            )
                            # Change output extension to MKA
                            mka_output = output_file.rsplit(".", 1)[0] + ".mka"
                            # Modify command to use mka and copy codec
                            mka_cmd = cmd.copy()
                            mka_cmd[-1] = mka_output  # Replace output filename

                            # Find and replace codec option if present
                            for i, param in enumerate(mka_cmd):
                                if (
                                    param in ("-c:a", "-c")
                                    and i + 1 < len(mka_cmd)
                                    and mka_cmd[i + 1] != "copy"
                                ):
                                    mka_cmd[i + 1] = "copy"  # Force copy codec for MKA

                            # Execute retry command
                            LOGGER.info(f"Retrying with MKA: {' '.join(mka_cmd)}")
                            retry_process = await create_subprocess_exec(
                                *mka_cmd, stdout=PIPE, stderr=PIPE
                            )
                            r_stdout, r_stderr = await retry_process.communicate()

                            if retry_process.returncode == 0 and await aiopath.exists(
                                mka_output
                            ):
                                stream_type = "audio"
                                idx = int(stream_id.replace("audio", ""))

                                # Register successful retry
                                extracted_files[stream_type][idx] = {
                                    "path": mka_output,
                                    "filename": ospath.basename(mka_output),
                                    "stream_info": stream_info,
                                }
                                LOGGER.info(
                                    f"Successfully extracted {stream_id} to {mka_output} after retry"
                                )
                                success_count += 1
                                failed_count -= (
                                    1  # Decrement failed count since we recovered
                                )
                        except Exception as e:
                            LOGGER.error(f"Error during retry attempt: {str(e)}")
            except Exception as e:
                LOGGER.error(f"Exception extracting {stream_id}: {str(e)}")
                failed_count += 1

        # Update extraction results
        self.extracted_files = extracted_files

        # Generate completion message
        total = len(extract_tasks)
        text = f"✓ <b>Stream Extraction Complete</b>\n\n"
        text += f" <b>Summary:</b>\n"
        text += f"» Successful: {success_count}/{total}\n"
        if failed_count > 0:
            text += f"» Failed: {failed_count}/{total}\n"
        text += "\n📂 <b>Extracted Files:</b>\n"

        # List extracted audio files
        if self.extracted_files["audio"]:
            text += "\n🔊 <b>Audio:</b>\n"
            for idx, data in self.extracted_files["audio"].items():
                text += f"» {data['filename']}\n"

        # List extracted subtitle files
        if self.extracted_files["subtitle"]:
            text += "\n📝 <b>Subtitles:</b>\n"
            for idx, data in self.extracted_files["subtitle"].items():
                text += f"» {data['filename']}\n"

        # Update message with results
        await edit_message(self.message, text)

        # Remove session
        if self.session_id in extract_sessions:
            del extract_sessions[self.session_id]

        # Mark extraction as complete
        if self.session_id in active_extractions:
            LOGGER.info(
                f"Setting extraction complete flag in extract_selected_streams for {self.session_id}"
            )
            active_extractions[self.session_id]["complete"].set()

        # Delete source file if keep_source_files is disabled and extraction was successful
        if not self.keep_source_files and success_count > 0:
            try:
                LOGGER.info(
                    f"Deleting source video file as KEEP_MERGE_SOURCE_FILES is disabled: {self.video_path}"
                )
                if await aiopath.exists(self.video_path):
                    await remove(self.video_path)
                    text += "\n\n🗑️ <b>Source video deleted</b> as 'Keep Source Files' is disabled"
                    await edit_message(self.message, text)
            except Exception as e:
                LOGGER.error(f"Error deleting source video file: {str(e)}")

        # Return extracted directory for uploading
        return extract_dir if success_count > 0 else False


# Callback handler for stream extraction
async def handle_stream_extract_callback(client, callback_query):
    """Handle callback queries for stream extraction"""
    data = callback_query.data.split()

    # Check if the format is correct
    if len(data) < 3 or data[0] != "extract":
        return

    session_id = data[1]
    action = data[2]

    # Check if session exists
    if session_id not in extract_sessions:
        return await callback_query.answer("Session expired...")

    session = extract_sessions[session_id]

    # Handle different actions
    if action.startswith("toggle_"):
        # Toggle stream selection
        stream_type = action.split("_")[1]  # audio or subtitle
        index = int(data[3])

        if session.toggle_stream(stream_type, index):
            await callback_query.answer(f"Updated selection")
            await session.create_selection_message()
        else:
            await callback_query.answer("Invalid selection ✘")

    elif action == "extract":
        # Start extraction
        await callback_query.answer("Starting extraction...")
        extract_dir = await session.extract_selected_streams()

        # Mark extraction as complete
        if session_id in active_extractions:
            LOGGER.info(f"Setting extraction complete flag for session {session_id}")
            active_extractions[session_id]["complete"].set()

    elif action == "cancel":
        # Cancel extraction
        await callback_query.answer("Cancelled")
        await session.cancel_extraction()

        # Mark extraction as complete even if cancelled
        if session_id in active_extractions:
            LOGGER.info(
                f"Setting extraction complete flag for cancelled session {session_id}"
            )
            active_extractions[session_id]["complete"].set()


def add_extract_handler():
    """Add the stream extraction callback handler to the bot"""
    try:
        from pyrogram.filters import regex
        from pyrogram.handlers import CallbackQueryHandler
        from ...core.tg_client import TgClient

        TgClient.bot.add_handler(
            CallbackQueryHandler(
                handle_stream_extract_callback, filters=regex("^extract")
            )
        )
        LOGGER.info("Stream extraction handler registered successfully")
    except Exception as e:
        LOGGER.error(f"Error registering stream extraction handler: {str(e)}")
        # Don't let this error crash the bot
