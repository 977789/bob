#!/usr/bin/env python3
"""
Stream Swap module for reordering audio and subtitle tracks in video files
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
from .media_utils import FFMpeg

# Dictionary to store stream swap sessions
swap_sessions = {}

# Dictionary to track active swap processes to prevent cleanup
active_swaps = {}


class StreamSwapper:
    def __init__(self, listener, video_path):
        """
        Initialize a stream swap session

        Parameters:
        listener: The listener object for this task
        video_path (str): Path to the video file
        """
        self.listener = listener
        self.video_path = video_path
        self.user_id = listener.message.from_user.id
        self.message = None
        self.streams_info = None
        self.audio_reorder = {}  # Map of original_index: new_index
        self.subtitle_reorder = {}  # Map of original_index: new_index
        self.session_id = f"{self.user_id}_{int(time())}"
        self.swap_complete = Event()
        self.reordered_file_path = None  # Store the path to the reordered file
        self.keep_source_files = self.listener.user_dict.get(
            "KEEP_MERGE_SOURCE_FILES", False
        )

        # Register this session as active
        active_swaps[self.session_id] = {
            "path": video_path,
            "listener_mid": listener.mid,
            "complete": self.swap_complete,
        }
        LOGGER.info(
            f"Registered active swap for session {self.session_id} - {video_path}"
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
                    # Initialize the audio reorder map with original positions
                    self.audio_reorder[len(self.streams_info["audio"]) - 1] = (
                        len(self.streams_info["audio"]) - 1
                    )
                elif codec_type == "subtitle":
                    self.streams_info["subtitle"].append(stream_data)
                    # Initialize the subtitle reorder map with original positions
                    self.subtitle_reorder[len(self.streams_info["subtitle"]) - 1] = (
                        len(self.streams_info["subtitle"]) - 1
                    )
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

    def get_stream_description(self, stream_type, stream, position):
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

        # Create a more visually distinct position indicator
        position_indicator = f"<b>[#{position + 1}]</b>"

        # Format description
        if stream_type == "audio":
            emoji = "🔊"
            channels = stream.get("channels", 0)
            bit_rate = stream.get("bit_rate", "unknown")

            desc = f"{emoji} {position_indicator} <b>{lang}</b>"

            if title:
                desc = f"{desc} - <i>{title}</i>"

            if bit_rate != "unknown":
                try:
                    bit_rate_kb = int(bit_rate) // 1000
                    desc += f" ({codec.upper()}, {channels}ch, {bit_rate_kb}kb/s)"
                except:
                    desc += f" ({codec.upper()}, {channels}ch)"
            else:
                desc += f" ({codec.upper()}, {channels}ch)"
        else:  # subtitle
            emoji = "📝"
            desc = f"{emoji} {position_indicator} <b>{lang}</b>"

            if title:
                desc = f"{desc} - <i>{title}</i>"

            desc += f" ({codec.upper()})"

        return desc

    async def move_stream_up(self, stream_type, index):
        """Move a stream up in the order (decrease its position number)"""
        try:
            index = int(index)
            if stream_type not in ["audio", "subtitle"]:
                return False

            if stream_type == "audio":
                reorder_map = self.audio_reorder
            else:
                reorder_map = self.subtitle_reorder

            # Get current position
            current_position = reorder_map[index]

            # Can't move up if already at the top
            if current_position == 0:
                return False

            # Find which stream is at the position above
            stream_above = None
            for idx, pos in reorder_map.items():
                if pos == current_position - 1:
                    stream_above = idx
                    break

            if stream_above is not None:
                # Swap positions
                reorder_map[index] = current_position - 1
                reorder_map[stream_above] = current_position

            return True
        except Exception as e:
            LOGGER.error(f"Error moving stream up: {e}")
            return False

    async def move_stream_down(self, stream_type, index):
        """Move a stream down in the order (increase its position number)"""
        try:
            index = int(index)
            if stream_type not in ["audio", "subtitle"]:
                return False

            if stream_type == "audio":
                reorder_map = self.audio_reorder
                max_position = len(self.streams_info["audio"]) - 1
            else:
                reorder_map = self.subtitle_reorder
                max_position = len(self.streams_info["subtitle"]) - 1

            # Get current position
            current_position = reorder_map[index]

            # Can't move down if already at the bottom
            if current_position == max_position:
                return False

            # Find which stream is at the position below
            stream_below = None
            for idx, pos in reorder_map.items():
                if pos == current_position + 1:
                    stream_below = idx
                    break

            if stream_below is not None:
                # Swap positions
                reorder_map[index] = current_position + 1
                reorder_map[stream_below] = current_position

            return True
        except Exception as e:
            LOGGER.error(f"Error moving stream down: {e}")
            return False

    async def create_selection_message(self):
        """Create the stream reordering interface message"""
        try:
            if not self.streams_info:
                if not await self.analyze_streams():
                    await send_message(
                        self.listener.message, "❌ Error analyzing video streams"
                    )
                    # Mark swap as complete since it failed
                    if self.session_id in active_swaps:
                        active_swaps[self.session_id]["complete"].set()
                    return False

            # Get video filename for display
            video_name = ospath.basename(self.video_path)

            # Build the selection message
            text = f"<b>Stream Swap</b>\n\n"
            text += f"<b>File:</b><b><i> {video_name}</i></b>\n\n"
            text += f"<b>Instructions:</b> Use Up/Down buttons to reorder audio or subtitle tracks, then click 'Apply'\n\n"
            text += f"<b>Note:</b> This menu will timeout after 10 minutes if no action is taken\n\n"

            # Add audio streams section with their positions
            if self.streams_info["audio"]:
                text += "🔊 <b>Audio Tracks:</b>\n"

                # Sort audio streams by their current position
                position_to_index = {
                    pos: idx for idx, pos in self.audio_reorder.items()
                }
                for position in range(len(self.streams_info["audio"])):
                    if position in position_to_index:
                        stream_idx = position_to_index[position]
                        stream = self.streams_info["audio"][stream_idx]
                        text += f"  {self.get_stream_description('audio', stream, position)}\n"

                text += "\n"
            else:
                text += "✘ <b>No audio tracks found</b>\n\n"

            # Add subtitle streams section with their positions
            if self.streams_info["subtitle"]:
                text += "📝 <b>Subtitle Tracks:</b>\n"

                # Sort subtitle streams by their current position
                position_to_index = {
                    pos: idx for idx, pos in self.subtitle_reorder.items()
                }
                for position in range(len(self.streams_info["subtitle"])):
                    if position in position_to_index:
                        stream_idx = position_to_index[position]
                        stream = self.streams_info["subtitle"][stream_idx]
                        text += f"  {self.get_stream_description('subtitle', stream, position)}\n"

                text += "\n"
            else:
                text += "✘ <b>No subtitle tracks found</b>\n\n"

            # Create buttons
            buttons = ButtonMaker()

            # Create buttons for each audio track (each with its own row)
            if self.streams_info["audio"]:
                # Sort audio streams by their current position for button display
                position_to_index = {
                    pos: idx for idx, pos in self.audio_reorder.items()
                }

                for position in range(len(self.streams_info["audio"])):
                    if position in position_to_index:
                        stream_idx = position_to_index[position]
                        stream = self.streams_info["audio"][stream_idx]

                        # Create a clear track label
                        lang = stream.get("language", "und")
                        title = stream.get("title", "")
                        track_label = f"🔊 #{position + 1}"

                        if lang != "und":
                            track_label += f" {lang}"
                        if title:
                            # Truncate title if too long
                            if len(title) > 15:
                                track_label += f" {title[:15]}..."
                            else:
                                track_label += f" {title}"

                        # Add track identifier button (non-functional, just for display)
                        buttons.data_button(
                            track_label, f"streamswap {self.session_id} noop"
                        )

                        # Add Up button (not for the first track)
                        if position > 0:
                            buttons.data_button(
                                "︿",
                                f"streamswap {self.session_id} audio_up {stream_idx}",
                            )
                        else:
                            # Add a blank button when up isn't available
                            buttons.data_button(
                                "•", f"streamswap {self.session_id} noop"
                            )

                        # Add Down button (not for the last track)
                        if position < len(self.streams_info["audio"]) - 1:
                            buttons.data_button(
                                "﹀",
                                f"streamswap {self.session_id} audio_down {stream_idx}",
                            )
                        else:
                            # Add a blank button when down isn't available
                            buttons.data_button(
                                "•", f"streamswap {self.session_id} noop"
                            )

            # Create buttons for each subtitle track (each with its own row)
            if self.streams_info["subtitle"]:
                # Sort subtitle streams by their current position for button display
                position_to_index = {
                    pos: idx for idx, pos in self.subtitle_reorder.items()
                }

                for position in range(len(self.streams_info["subtitle"])):
                    if position in position_to_index:
                        stream_idx = position_to_index[position]
                        stream = self.streams_info["subtitle"][stream_idx]

                        # Create a clear track label
                        lang = stream.get("language", "und")
                        title = stream.get("title", "")
                        track_label = f"📝 #{position + 1}"

                        if lang != "und":
                            track_label += f" {lang}"
                        if title:
                            # Truncate title if too long
                            if len(title) > 15:
                                track_label += f" {title[:15]}..."
                            else:
                                track_label += f" {title}"

                        # Add track identifier button (non-functional, just for display)
                        buttons.data_button(
                            track_label, f"streamswap {self.session_id} noop"
                        )

                        # Add Up button (not for the first track)
                        if position > 0:
                            buttons.data_button(
                                "︿",
                                f"streamswap {self.session_id} subtitle_up {stream_idx}",
                            )
                        else:
                            # Add a blank button when up isn't available
                            buttons.data_button(
                                "•", f"streamswap {self.session_id} noop"
                            )

                        # Add Down button (not for the last track)
                        if position < len(self.streams_info["subtitle"]) - 1:
                            buttons.data_button(
                                "﹀",
                                f"streamswap {self.session_id} subtitle_down {stream_idx}",
                            )
                        else:
                            # Add a blank button when down isn't available
                            buttons.data_button(
                                "•", f"streamswap {self.session_id} noop"
                            )

            # Add action buttons as a separate row
            if self.streams_info["audio"] or self.streams_info["subtitle"]:
                buttons.data_button(
                    "Apply Changes", f"streamswap {self.session_id} apply"
                )
                buttons.data_button("✘ Cancel", f"streamswap {self.session_id} cancel")
            else:
                buttons.data_button("✘ Cancel", f"streamswap {self.session_id} cancel")

            try:
                # If this is the first message, send it, otherwise edit
                if self.message is None:
                    self.message = await send_message(
                        self.listener.message,
                        text,
                        buttons.build_menu(
                            3
                        ),  # 3 columns for track name, up button, down button
                    )
                else:
                    await edit_message(
                        self.message,
                        text,
                        buttons.build_menu(
                            3
                        ),  # 3 columns for track name, up button, down button
                    )

                # Store this session
                swap_sessions[self.session_id] = self
                return True
            except Exception as e:
                LOGGER.error(f"Error sending stream swap message: {str(e)}")
                # Mark swap as complete since it failed
                if self.session_id in active_swaps:
                    active_swaps[self.session_id]["complete"].set()
                return False
        except Exception as e:
            LOGGER.error(f"Error creating stream swap message: {str(e)}")
            # Mark swap as complete since it failed
            if self.session_id in active_swaps:
                active_swaps[self.session_id]["complete"].set()
            return False

    async def cancel_swap(self):
        """Cancel the swap process"""
        if self.message:
            await edit_message(self.message, "Stream swap cancelled...")

        # Set reordered_file_path to None to indicate cancellation
        self.reordered_file_path = None

        # Remove session
        if self.session_id in swap_sessions:
            del swap_sessions[self.session_id]

        # Mark swap as complete
        if self.session_id in active_swaps:
            LOGGER.info(
                f"Setting swap complete flag in cancel_swap for {self.session_id}"
            )
            active_swaps[self.session_id]["complete"].set()

        return True

    async def apply_stream_reordering(self):
        """Apply the stream reordering changes to the video file"""
        if not self.audio_reorder and not self.subtitle_reorder:
            await edit_message(self.message, "No changes to apply")

            # Mark swap as complete
            if self.session_id in active_swaps:
                active_swaps[self.session_id]["complete"].set()
            return False

        # Check if there's anything to reorder
        audio_needs_reorder = any(idx != pos for idx, pos in self.audio_reorder.items())
        subtitle_needs_reorder = any(
            idx != pos for idx, pos in self.subtitle_reorder.items()
        )

        if not audio_needs_reorder and not subtitle_needs_reorder:
            await edit_message(self.message, "No changes in track order detected")

            # Mark swap as complete
            if self.session_id in active_swaps:
                active_swaps[self.session_id]["complete"].set()
            return False

        # Update message
        await edit_message(
            self.message,
            "🔄 Applying stream reordering...\n\nThis may take a few minutes depending on the file size.",
        )

        # Create output directory for the new file
        video_dir = ospath.dirname(self.video_path)
        video_basename = ospath.basename(self.video_path)
        video_name = ospath.splitext(video_basename)[0]
        file_extension = ospath.splitext(video_basename)[1]

        # Check for custom filename template
        user_dict = self.listener.user_dict
        custom_filename = user_dict.get("CUSTOM_FILENAME", "")
        if custom_filename:
            from bot.helper.ext_utils.watermark_utils import apply_custom_filename

            output_file = apply_custom_filename(self.video_path, user_dict, "_swapped")
        else:
            output_file = ospath.join(
                video_dir, f"{video_name}_reordered{file_extension}"
            )

        try:
            # Create FFMpeg command to reorder streams
            ffmpeg = FFMpeg(self.listener)

            # Sort audio and subtitle streams by their new positions
            audio_mapping = []
            for position in range(len(self.streams_info["audio"])):
                for idx, pos in self.audio_reorder.items():
                    if pos == position:
                        stream_index = self.streams_info["audio"][idx]["index"]
                        audio_mapping.append(stream_index)

            subtitle_mapping = []
            for position in range(len(self.streams_info["subtitle"])):
                for idx, pos in self.subtitle_reorder.items():
                    if pos == position:
                        stream_index = self.streams_info["subtitle"][idx]["index"]
                        subtitle_mapping.append(stream_index)

            # Prepare the command
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "warning",
                "-progress",
                "pipe:1",
                "-i",
                self.video_path,
            ]

            # First, build an ordered list of how streams will appear in the output
            # This is important for mapping metadata correctly
            output_stream_order = []

            # Add video streams first (maintaining original order)
            video_indices = [stream["index"] for stream in self.streams_info["video"]]
            output_stream_order.extend(video_indices)

            # Add audio streams in new order
            output_stream_order.extend(audio_mapping)

            # Add subtitle streams in new order
            output_stream_order.extend(subtitle_mapping)

            # Add other streams in original order
            other_indices = [stream["index"] for stream in self.streams_info["other"]]
            output_stream_order.extend(other_indices)

            # Map streams in the order we've determined
            for idx in output_stream_order:
                cmd.extend(["-map", f"0:{idx}"])

            # Copy all streams without re-encoding
            cmd.extend(["-c", "copy"])

            # Global metadata
            cmd.extend(["-map_metadata", "0"])

            # Create a mapping from input stream indices to output stream indices
            input_to_output_mapping = {
                in_idx: out_idx for out_idx, in_idx in enumerate(output_stream_order)
            }

            # Process all stream types for metadata preservation
            for stream_type in ["audio", "subtitle", "video"]:
                for stream in self.streams_info[stream_type]:
                    input_index = stream["index"]
                    if input_index in input_to_output_mapping:
                        output_index = input_to_output_mapping[input_index]

                        # Preserve language tags
                        if "language" in stream and stream["language"] != "und":
                            cmd.extend(
                                [
                                    f"-metadata:s:{output_index}",
                                    f"language={stream['language']}",
                                ]
                            )

                        # Preserve titles
                        if "title" in stream and stream["title"]:
                            cmd.extend(
                                [
                                    f"-metadata:s:{output_index}",
                                    f"title={stream['title']}",
                                ]
                            )

            # Finish command
            cmd.extend([output_file, "-y"])

            # Execute the command
            LOGGER.info(f"Reordering streams: {' '.join(cmd)}")
            self.listener.subproc = await create_subprocess_exec(
                *cmd, stdout=PIPE, stderr=PIPE
            )

            # Monitor progress
            await ffmpeg._ffmpeg_progress()
            stdout, stderr = await self.listener.subproc.communicate()
            code = self.listener.subproc.returncode

            if code == 0:
                LOGGER.info(f"Successfully reordered streams in {self.video_path}")

                # Update message with success
                text = f"<b>Stream Reordering Completed</b>\n\n"
                text += f"<b>Output:</b> {video_name}{file_extension}\n\n"

                # Delete source file if keep_source_files is disabled
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
                                LOGGER.info(
                                    f"Stream swapped file renamed to custom filename: {final_path}"
                                )

                        # Delete source file
                        LOGGER.info(
                            f"Deleting source video file as KEEP_MERGE_SOURCE_FILES is disabled: {self.video_path}"
                        )
                        if await aiopath.exists(self.video_path):
                            await remove(self.video_path)
                            text += "\n🗑️ <b>Source video deleted</b> as 'Keep Source Files' is disabled"
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
                                LOGGER.info(
                                    f"Stream swapped file renamed to custom filename: {final_path}"
                                )
                    except Exception as e:
                        LOGGER.error(f"Error applying custom filename: {str(e)}")

                await edit_message(self.message, text)

                # Store output file path
                self.reordered_file_path = output_file

                # Mark swap as complete
                if self.session_id in active_swaps:
                    active_swaps[self.session_id]["complete"].set()

                # Remove session
                if self.session_id in swap_sessions:
                    del swap_sessions[self.session_id]

                return output_file
            else:
                try:
                    stderr = stderr.decode().strip()
                except Exception:
                    stderr = "Unable to decode error message"

                LOGGER.error(f"Error reordering streams: {stderr}")
                await edit_message(
                    self.message,
                    f"❌ <b>Error reordering streams</b>\n\n<code>{stderr[:2000]}</code>",
                )

                # Mark swap as complete
                if self.session_id in active_swaps:
                    active_swaps[self.session_id]["complete"].set()

                # Remove session
                if self.session_id in swap_sessions:
                    del swap_sessions[self.session_id]

                return False
        except Exception as e:
            LOGGER.error(f"Error applying stream reordering: {str(e)}")
            await edit_message(
                self.message, f"❌ <b>Error reordering streams:</b> {str(e)}"
            )

            # Mark swap as complete
            if self.session_id in active_swaps:
                active_swaps[self.session_id]["complete"].set()

            # Remove session
            if self.session_id in swap_sessions:
                del swap_sessions[self.session_id]

            return False


# Callback handler for stream swap
async def handle_stream_swap_callback(client, callback_query):
    """Handle callback queries for stream swap"""
    data = callback_query.data.split()

    # Check if the format is correct
    if len(data) < 3 or data[0] != "streamswap":
        return

    session_id = data[1]
    action = data[2]

    # Handle noop action (used for display-only buttons)
    if action == "noop":
        return await callback_query.answer("This button is just for display")

    # Check if session exists
    if session_id not in swap_sessions:
        return await callback_query.answer("Session expired...")

    session = swap_sessions[session_id]

    # Handle different actions
    if action == "audio_up":
        # Move audio track up
        if len(data) < 4:
            return await callback_query.answer("Invalid request")

        index = int(data[3])
        # Get track info for better notification
        try:
            track_info = session.streams_info["audio"][index]
            current_pos = session.audio_reorder[index] + 1
            lang = track_info.get("language", "und")
            title = track_info.get("title", "")

            track_desc = f"Audio #{current_pos}"
            if lang != "und":
                track_desc += f" ({lang})"
            if title:
                track_desc += f": {title[:10]}" + ("..." if len(title) > 10 else "")
        except Exception:
            track_desc = f"Audio track #{current_pos}"

        if await session.move_stream_up("audio", index):
            new_pos = session.audio_reorder[index] + 1
            await callback_query.answer(f"Moved {track_desc} to position #{new_pos}")
            await session.create_selection_message()
        else:
            await callback_query.answer(f"{track_desc} is already at the top")

    elif action == "audio_down":
        # Move audio track down
        if len(data) < 4:
            return await callback_query.answer("Invalid request")

        index = int(data[3])
        # Get track info for better notification
        try:
            track_info = session.streams_info["audio"][index]
            current_pos = session.audio_reorder[index] + 1
            lang = track_info.get("language", "und")
            title = track_info.get("title", "")

            track_desc = f"Audio #{current_pos}"
            if lang != "und":
                track_desc += f" ({lang})"
            if title:
                track_desc += f": {title[:10]}" + ("..." if len(title) > 10 else "")
        except Exception:
            track_desc = f"Audio track #{current_pos}"

        if await session.move_stream_down("audio", index):
            new_pos = session.audio_reorder[index] + 1
            await callback_query.answer(f"Moved {track_desc} to position #{new_pos}")
            await session.create_selection_message()
        else:
            await callback_query.answer(f"{track_desc} is already at the bottom")

    elif action == "subtitle_up":
        # Move subtitle track up
        if len(data) < 4:
            return await callback_query.answer("Invalid request")

        index = int(data[3])
        # Get track info for better notification
        try:
            track_info = session.streams_info["subtitle"][index]
            current_pos = session.subtitle_reorder[index] + 1
            lang = track_info.get("language", "und")
            title = track_info.get("title", "")

            track_desc = f"Subtitle #{current_pos}"
            if lang != "und":
                track_desc += f" ({lang})"
            if title:
                track_desc += f": {title[:10]}" + ("..." if len(title) > 10 else "")
        except Exception:
            track_desc = f"Subtitle track #{current_pos}"

        if await session.move_stream_up("subtitle", index):
            new_pos = session.subtitle_reorder[index] + 1
            await callback_query.answer(f"Moved {track_desc} to position #{new_pos}")
            await session.create_selection_message()
        else:
            await callback_query.answer(f"{track_desc} is already at the top")

    elif action == "subtitle_down":
        # Move subtitle track down
        if len(data) < 4:
            return await callback_query.answer("Invalid request")

        index = int(data[3])
        # Get track info for better notification
        try:
            track_info = session.streams_info["subtitle"][index]
            current_pos = session.subtitle_reorder[index] + 1
            lang = track_info.get("language", "und")
            title = track_info.get("title", "")

            track_desc = f"Subtitle #{current_pos}"
            if lang != "und":
                track_desc += f" ({lang})"
            if title:
                track_desc += f": {title[:10]}" + ("..." if len(title) > 10 else "")
        except Exception:
            track_desc = f"Subtitle track #{current_pos}"

        if await session.move_stream_down("subtitle", index):
            new_pos = session.subtitle_reorder[index] + 1
            await callback_query.answer(f"Moved {track_desc} to position #{new_pos}")
            await session.create_selection_message()
        else:
            await callback_query.answer(f"{track_desc} is already at the bottom")

    elif action == "apply":
        # Apply changes
        await callback_query.answer("Applying changes...")
        await session.apply_stream_reordering()

    elif action == "cancel":
        # Cancel swap
        await callback_query.answer("Cancelled")
        await session.cancel_swap()


def add_swap_handler():
    """Add the stream swap callback handler to the bot"""
    try:
        from pyrogram.filters import regex
        from pyrogram.handlers import CallbackQueryHandler
        from ...core.tg_client import TgClient

        TgClient.bot.add_handler(
            CallbackQueryHandler(
                handle_stream_swap_callback, filters=regex("^streamswap")
            )
        )
        LOGGER.info("Stream swap handler registered successfully")
    except Exception as e:
        LOGGER.error(f"Error registering stream swap handler: {str(e)}")
        # Don't let this error crash the bot
