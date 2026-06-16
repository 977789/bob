#!/usr/bin/env python3
"""
Stream Remover module for removing audio and subtitle tracks from video files
"""

from asyncio import create_subprocess_exec, Event
from asyncio.subprocess import PIPE
from os import path as ospath
from aiofiles.os import makedirs, remove, path as aiopath
from time import time
import json
import re
from contextlib import suppress

from ... import LOGGER, user_data
from ..telegram_helper.button_build import ButtonMaker
from ..telegram_helper.message_utils import send_message, edit_message

# Dictionary to store stream removal sessions
remove_sessions = {}

# Dictionary to track active removal processes to prevent cleanup
active_removals = {}


class StreamRemover:
    def __init__(self, listener, video_path):
        """
        Initialize a stream removal session

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
        self.session_id = f"{self.user_id}_{int(time())}"
        self.removal_complete = Event()
        self.removed_file_path = None  # Store the path to the processed file
        self.keep_source_files = self.listener.user_dict.get(
            "KEEP_MERGE_SOURCE_FILES", False
        )

        # Register this session as active
        active_removals[self.session_id] = {
            "path": video_path,
            "listener_mid": listener.mid,
            "complete": self.removal_complete,
        }
        LOGGER.info(
            f"Registered active stream removal for session {self.session_id} - {video_path}"
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
                    "und": "Undefined",
                }
                lang = lang_map.get(lang, lang)
        except:
            pass

        description = f"#{stream['index']}: {codec}"

        if stream_type == "audio":
            emoji = "🔊"
            channels = stream.get("channels", 2)
            if channels > 0:
                ch_text = "mono" if channels == 1 else f"{channels}ch"
                description += f" ({ch_text})"

        elif stream_type == "subtitle":
            emoji = "📝"
        else:
            emoji = "📄"

        if lang and lang != "und":
            description += f" - {lang}"

        if title:
            description += f" - {title}"

        return f"{emoji} {description}"

    async def create_selection_message(self):
        """Create the stream selection interface message"""
        try:
            if not self.streams_info:
                if not await self.analyze_streams():
                    await send_message(
                        self.listener.message, "❌ Error analyzing video streams"
                    )
                    # Mark removal as complete since it failed
                    if self.session_id in active_removals:
                        active_removals[self.session_id]["complete"].set()
                    return False

            # Get video filename for display
            video_name = ospath.basename(self.video_path)

            # Build the selection message
            text = f"<b>Stream Removal</b>\n\n"
            text += f"<b>File:</b><b><i> {video_name}</i></b>\n\n"
            text += f"<b>Instructions:</b> Select audio/subtitle tracks to remove, then click 'Remove Streams'\n\n"
            text += f"<b>Note:</b> This menu will timeout after 10 minutes if no action is taken\n\n"

            # Add audio streams section
            if self.streams_info["audio"]:
                text += "🔊 <b>Audio Tracks:</b>\n"
                for i, stream in enumerate(self.streams_info["audio"]):
                    stream_index = self.streams_info["audio"][i]["index"]
                    check = (
                        "✓" if stream_index in self.selected_streams["audio"] else "»"
                    )
                    text += f"{check} {self.get_stream_description('audio', stream)}\n"
                text += "\n"
            else:
                text += "✘ <b>No audio tracks found</b>\n\n"

            # Add subtitle streams section
            if self.streams_info["subtitle"]:
                text += "📝 <b>Subtitle Tracks:</b>\n"
                for i, stream in enumerate(self.streams_info["subtitle"]):
                    stream_index = self.streams_info["subtitle"][i]["index"]
                    check = (
                        "✓"
                        if stream_index in self.selected_streams["subtitle"]
                        else "»"
                    )
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
                stream_index = self.streams_info["audio"][i]["index"]
                action = (
                    "remove"
                    if stream_index in self.selected_streams["audio"]
                    else "add"
                )
                buttons.data_button(
                    f"Audio #{stream_index}",
                    f"remove_stream {self.session_id} toggle_audio {stream_index}",
                )
        except Exception as e:
            LOGGER.error(f"Error creating stream removal message: {str(e)}")
            # Mark removal as complete since it failed
            if self.session_id in active_removals:
                active_removals[self.session_id]["complete"].set()
            return False

        # Add subtitle track selection buttons
        for i in range(
            min(len(self.streams_info["subtitle"]), 10)
        ):  # Limit to 10 tracks for UI
            stream_index = self.streams_info["subtitle"][i]["index"]
            action = (
                "remove" if stream_index in self.selected_streams["subtitle"] else "add"
            )
            buttons.data_button(
                f"Sub #{stream_index}",
                f"remove_stream {self.session_id} toggle_subtitle {stream_index}",
            )

        # Add action buttons
        buttons.data_button("Remove Streams", f"remove_stream {self.session_id} remove")
        buttons.data_button("✘", f"remove_stream {self.session_id} cancel")

        try:
            # If this is the first message, send it, otherwise edit
            if self.message is None:
                self.message = await send_message(
                    self.listener.message, text, buttons.build_menu(2)
                )
            else:
                await edit_message(self.message, text, buttons.build_menu(2))

            # Store this session
            remove_sessions[self.session_id] = self
            return True
        except Exception as e:
            LOGGER.error(f"Error sending stream removal message: {str(e)}")
            # Mark removal as complete since it failed
            if self.session_id in active_removals:
                active_removals[self.session_id]["complete"].set()
            return False

    def toggle_stream(self, stream_type, index):
        """Toggle selection state of a stream"""
        try:
            index = int(index)
            if stream_type not in ["audio", "subtitle"]:
                return False

            if stream_type == "audio":
                # Verify that we're not trying to remove the last audio track
                if (
                    len(self.streams_info["audio"]) == 1
                    and index == self.streams_info["audio"][0]["index"]
                ):
                    return False

                if index in self.selected_streams[stream_type]:
                    self.selected_streams[stream_type].remove(index)
                else:
                    self.selected_streams[stream_type].append(index)
            else:  # subtitle
                if index in self.selected_streams[stream_type]:
                    self.selected_streams[stream_type].remove(index)
                else:
                    self.selected_streams[stream_type].append(index)

            return True
        except Exception as e:
            LOGGER.error(f"Error toggling stream: {e}")
            return False

    async def cancel_removal(self):
        """Cancel the removal process"""
        if self.message:
            await edit_message(self.message, "Stream removal cancelled...")

        # Remove session
        if self.session_id in remove_sessions:
            del remove_sessions[self.session_id]

        # Mark removal as complete
        if self.session_id in active_removals:
            LOGGER.info(
                f"Setting removal complete flag in cancel_removal for {self.session_id}"
            )
            active_removals[self.session_id]["complete"].set()

        return True

    async def remove_selected_streams(self):
        """Remove selected audio and subtitle streams"""
        if not self.selected_streams["audio"] and not self.selected_streams["subtitle"]:
            await edit_message(self.message, "✘ No streams selected for removal")
            # Mark session as complete
            if self.session_id in active_removals:
                active_removals[self.session_id]["complete"].set()
            return False

        # Get video directory and filename
        video_dir = ospath.dirname(self.video_path)
        video_basename = ospath.basename(self.video_path)
        video_name, video_ext = ospath.splitext(video_basename)

        # Create output filename with custom template support
        user_dict = self.listener.user_dict
        custom_filename = user_dict.get("CUSTOM_FILENAME", "")
        if custom_filename:
            from bot.helper.ext_utils.watermark_utils import apply_custom_filename

            output_file = apply_custom_filename(self.video_path, user_dict, "_removed")
        else:
            # Default behavior
            output_file = ospath.join(video_dir, f"{video_name}_removed{video_ext}")

        # Update message
        await edit_message(
            self.message,
            "🔄 Removing selected streams...\n\nThis may take a few minutes.",
        )

        try:
            # Build ffmpeg command
            cmd = ["ffmpeg", "-hide_banner", "-i", self.video_path]

            # Create mapping for all streams we want to keep
            map_args = []

            # First, add all video streams (we keep all video streams)
            for stream in self.streams_info["video"]:
                map_args.extend(["-map", f"0:{stream['index']}"])

            # Add audio streams that are not selected for removal
            audio_indices = [stream["index"] for stream in self.streams_info["audio"]]
            for idx in audio_indices:
                if idx not in self.selected_streams["audio"]:
                    map_args.extend(["-map", f"0:{idx}"])

            # Add subtitle streams that are not selected for removal
            subtitle_indices = [
                stream["index"] for stream in self.streams_info["subtitle"]
            ]
            for idx in subtitle_indices:
                if idx not in self.selected_streams["subtitle"]:
                    map_args.extend(["-map", f"0:{idx}"])

            # Add other streams (like attachments)
            for stream in self.streams_info["other"]:
                map_args.extend(["-map", f"0:{stream['index']}"])

            # Add copy codec to ensure no re-encoding
            cmd.extend(map_args)
            cmd.extend(["-c", "copy"])

            # Add output file
            cmd.extend([output_file, "-y"])

            # Execute ffmpeg command
            LOGGER.info(f"Removing streams with command: {' '.join(cmd)}")
            process = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
            _, stderr = await process.communicate()

            # Check if output file exists
            if process.returncode == 0 and await aiopath.exists(output_file):
                self.removed_file_path = output_file

                # Update message with results
                num_audio_removed = len(self.selected_streams["audio"])
                num_subtitle_removed = len(self.selected_streams["subtitle"])

                text = f"✓ <b>Stream Removal Complete</b>\n\n"
                text += f" <b>Summary:</b>\n"
                if num_audio_removed > 0:
                    text += f"» Audio tracks removed: {num_audio_removed}\n"
                if num_subtitle_removed > 0:
                    text += f"» Subtitle tracks removed: {num_subtitle_removed}\n"

                # Handle file replacement and custom filename
                if not self.keep_source_files:
                    try:
                        # Apply final custom filename if set
                        custom_filename = user_dict.get("CUSTOM_FILENAME", "")
                        if custom_filename:
                            from bot.helper.ext_utils.watermark_utils import (
                                get_final_filename,
                            )

                            final_path = get_final_filename(self.video_path, user_dict)
                            if (
                                final_path != output_file
                                and final_path != self.video_path
                            ):
                                import shutil

                                shutil.move(output_file, final_path)
                                output_file = final_path
                                self.removed_file_path = final_path
                                LOGGER.info(
                                    f"Stream removed file renamed to custom filename: {final_path}"
                                )

                        # Delete source file
                        LOGGER.info(
                            f"Deleting source video file as KEEP_MERGE_SOURCE_FILES is disabled: {self.video_path}"
                        )
                        if await aiopath.exists(self.video_path):
                            await remove(self.video_path)
                            text += "\n\n🗑️ <b>Source video deleted</b> as 'Keep Source Files' is disabled"
                    except Exception as e:
                        LOGGER.error(f"Error handling source video file: {str(e)}")
                else:
                    # If keeping source files, still apply custom filename
                    try:
                        custom_filename = user_dict.get("CUSTOM_FILENAME", "")
                        if custom_filename:
                            from bot.helper.ext_utils.watermark_utils import (
                                get_final_filename,
                            )

                            final_path = get_final_filename(self.video_path, user_dict)
                            if final_path != output_file:
                                import shutil

                                shutil.move(output_file, final_path)
                                output_file = final_path
                                self.removed_file_path = final_path
                                LOGGER.info(
                                    f"Stream removed file renamed to custom filename: {final_path}"
                                )
                    except Exception as e:
                        LOGGER.error(f"Error applying custom filename: {str(e)}")

                # Update message with results
                await edit_message(self.message, text)

                # Remove session
                if self.session_id in remove_sessions:
                    del remove_sessions[self.session_id]

                # Mark removal as complete
                if self.session_id in active_removals:
                    active_removals[self.session_id]["complete"].set()

                return self.removed_file_path
            else:
                stderr_text = stderr.decode() if stderr else "Unknown error"
                LOGGER.error(f"Error removing streams: {stderr_text}")
                await edit_message(
                    self.message, "❌ Error removing streams. Check log for details."
                )

                # Mark removal as complete even though it failed
                if self.session_id in active_removals:
                    active_removals[self.session_id]["complete"].set()

                return False
        except Exception as e:
            LOGGER.error(f"Exception in stream removal: {str(e)}")
            await edit_message(self.message, f"❌ Error: {str(e)}")

            # Mark removal as complete since it failed
            if self.session_id in active_removals:
                active_removals[self.session_id]["complete"].set()

            return False


# Callback handler for stream removal
async def handle_stream_remove_callback(client, callback_query):
    """Handle callback queries for stream removal"""
    data = callback_query.data.split()

    # Check if the format is correct
    if len(data) < 3 or data[0] != "remove_stream":
        return

    session_id = data[1]
    action = data[2]

    # Check if session exists
    if session_id not in remove_sessions:
        return await callback_query.answer("Session expired...")

    session = remove_sessions[session_id]

    # Handle different actions
    if action.startswith("toggle_"):
        # Toggle stream selection
        stream_type = action.split("_")[1]  # audio or subtitle
        index = int(data[3])

        if session.toggle_stream(stream_type, index):
            await callback_query.answer(f"Updated selection")
            await session.create_selection_message()
        else:
            await callback_query.answer("Cannot remove last audio track ✘")

    elif action == "remove":
        # Start removal
        await callback_query.answer("Starting stream removal...")
        await session.remove_selected_streams()

    elif action == "cancel":
        # Cancel removal
        await callback_query.answer("Cancelled")
        await session.cancel_removal()


def add_stream_remove_handler():
    """Add the stream removal callback handler to the bot"""
    try:
        from pyrogram.filters import regex
        from pyrogram.handlers import CallbackQueryHandler
        from ...core.tg_client import TgClient

        TgClient.bot.add_handler(
            CallbackQueryHandler(
                handle_stream_remove_callback, filters=regex("^remove_stream")
            )
        )
        LOGGER.info("Stream removal handler registered successfully")
    except Exception as e:
        LOGGER.error(f"Error registering stream removal handler: {str(e)}")
        # Don't let this error crash the bot
