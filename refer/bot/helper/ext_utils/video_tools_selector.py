#!/usr/bin/env python3
"""
Video Tools Selection module for interactive video processing selection
"""

from asyncio import create_subprocess_exec, sleep
from asyncio.subprocess import PIPE
from os import path as ospath
from time import time

from ... import LOGGER, user_data
from ..telegram_helper.button_build import ButtonMaker
from ..telegram_helper.message_utils import send_message, edit_message, delete_message

# Dictionary to store video tools selection sessions
video_tools_sessions = {}

# Video processing options with their descriptions
VIDEO_TOOLS_OPTIONS = {
    "VIDEO_ENCODE": {
        "name": "Video Encode",
        "description": "Re-encode videos with different settings",
        "setting_key": "VIDEO_ENCODE_ENABLED",
    },
    "VIDEO_CONVERT": {
        "name": "Video Convert",
        "description": "Convert videos to different formats (MP4, MKV, AVI, etc.)",
        "setting_key": "VIDEO_CONVERT_ENABLED",
    },
    "VIDEO_TRIM": {
        "name": "Video Trim",
        "description": "Trim/crop video duration by start & end time",
        "setting_key": "VIDEO_TRIM_ENABLED",
    },
    "VIDEO_WATERMARK": {
        "name": "Video Watermark",
        "description": "Add text/image watermark to videos",
        "setting_key": "VIDEO_WATERMARK_ENABLED",
    },
    "VIDEO_AUDIO_MERGE": {
        "name": "Video+Audio Merge",
        "description": "Merge separate audio tracks with video",
        "setting_key": "VIDEO_AUDIO_MERGE_ENABLED",
    },
    "VIDEO_SUBTITLE_MERGE": {
        "name": "Video+Subtitle Merge",
        "description": "Merge subtitle files with video",
        "setting_key": "VIDEO_SUBTITLE_MERGE_ENABLED",
    },
    "VIDEO_HARDSUB": {
        "name": "Video Hardsub",
        "description": "Burn subtitle files into video permanently",
        "setting_key": "VIDEO_HARDSUB_ENABLED",
    },
    "VIDEO_MERGE": {
        "name": "Video Merge",
        "description": "Merge multiple video files into one",
        "setting_key": "VIDEO_MERGE_ENABLED",
    },
    "STREAM_EXTRACT": {
        "name": "Stream Extract",
        "description": "Extract audio/subtitle streams from video",
        "setting_key": "VIDEO_STREAM_EXTRACT_ENABLED",
    },
    "STREAM_SWAP": {
        "name": "Stream Swap",
        "description": "Reorder audio/subtitle tracks",
        "setting_key": "STREAM_SWAP_ENABLED",
    },
    "STREAM_REMOVE": {
        "name": "Stream Remove",
        "description": "Remove unwanted audio/subtitle tracks",
        "setting_key": "STREAM_REMOVE_ENABLED",
    },
    "INTRO_SUBTITLE": {
        "name": "Intro Subtitle",
        "description": "Generate & mux animated intro ASS subtitle",
        "setting_key": "INTRO_SUBTITLE_ENABLED",
    },
}


class VideoToolsSelector:
    def __init__(self, listener, user_id):
        self.listener = listener
        self.user_id = user_id
        self.user_dict = user_data.get(user_id, {})
        self.selected_tools = set()
        self.session_id = f"vt_{user_id}_{int(time())}"
        self.message = None

    async def show_selection_menu(self):
        """Show the video tools selection interface"""
        # Create buttons for each video tool option
        buttons = ButtonMaker()

        # Check which tools are available based on user settings
        available_tools = []
        for tool_key, tool_info in VIDEO_TOOLS_OPTIONS.items():
            setting_key = tool_info["setting_key"]
            if self.user_dict.get(setting_key, False):
                available_tools.append((tool_key, tool_info))

        if not available_tools:
            text = """<b>⚠️ No Video Processing Tools Enabled</b>

You need to enable at least one video processing tool in your user settings (/usetting) before using the -ft flag.

<b>Available Tools:</b>
• Video Encoding
• Video Watermarking  
• Video+Audio Merge
• Video+Subtitle Merge
• Video Hardsub
• Video Merge
• Stream Extract
• Stream Swap
• Stream Remove

Enable the tools you want to use, then try again with -ft flag."""

            buttons.data_button("Close", f"videotools {self.session_id} cancel")
            await send_message(self.listener.message, text, buttons.build_menu(1))
            return False

        # Show available tools for selection
        text = f"""<b>🎬 Video Processing Tools Selection</b>

<b>Available Tools:</b> {len(available_tools)} enabled in your settings

Select which video processing operations you want to perform on your downloaded content:
"""

        # Add toggle buttons for each available tool
        for tool_key, tool_info in available_tools:
            is_selected = tool_key in self.selected_tools
            prefix = "✓" if is_selected else ""
            button_text = f"{prefix} {tool_info['name']}"
            buttons.data_button(
                button_text, f"videotools {self.session_id} toggle {tool_key}"
            )

        # Add control buttons
        buttons.data_button("☑All", f"videotools {self.session_id} selectall", "footer")
        buttons.data_button("☒", f"videotools {self.session_id} deselectall", "footer")
        buttons.data_button("✓Start", f"videotools {self.session_id} confirm", "footer")
        buttons.data_button("✘", f"videotools {self.session_id} cancel", "footer")

        # Store session and send message
        video_tools_sessions[self.session_id] = self
        self.message = await send_message(
            self.listener.message, text, buttons.build_menu(2)
        )
        return True

    async def update_selection_menu(self):
        """Update the selection menu with current state"""
        available_tools = []
        for tool_key, tool_info in VIDEO_TOOLS_OPTIONS.items():
            setting_key = tool_info["setting_key"]
            if self.user_dict.get(setting_key, False):
                available_tools.append((tool_key, tool_info))

        text = f"""<b>🎬 Video Processing Tools Selection</b>

<b>Available Tools:</b> {len(available_tools)} enabled in your settings
<b>Selected:</b> {len(self.selected_tools)} / {len(available_tools)}

Select which video processing operations you want to perform on your downloaded content:
"""

        buttons = ButtonMaker()

        # Add toggle buttons for each available tool
        for tool_key, tool_info in available_tools:
            is_selected = tool_key in self.selected_tools
            prefix = "✓" if is_selected else ""
            button_text = f"{prefix} {tool_info['name']}"
            buttons.data_button(
                button_text, f"videotools {self.session_id} toggle {tool_key}"
            )

        # Add control buttons
        buttons.data_button("☑All", f"videotools {self.session_id} selectall", "footer")
        buttons.data_button("☒", f"videotools {self.session_id} deselectall", "footer")
        buttons.data_button("✓Start", f"videotools {self.session_id} confirm", "footer")
        buttons.data_button("✘", f"videotools {self.session_id} cancel", "footer")

        await edit_message(self.message, text, buttons.build_menu(2))

    def toggle_tool(self, tool_key):
        """Toggle selection of a video tool"""
        if tool_key in self.selected_tools:
            self.selected_tools.remove(tool_key)
        else:
            self.selected_tools.add(tool_key)

    def select_all_tools(self):
        """Select all available tools"""
        for tool_key, tool_info in VIDEO_TOOLS_OPTIONS.items():
            setting_key = tool_info["setting_key"]
            if self.user_dict.get(setting_key, False):
                self.selected_tools.add(tool_key)

    def deselect_all_tools(self):
        """Deselect all tools"""
        self.selected_tools.clear()

    async def confirm_selection(self):
        """Confirm the selection and set video tools settings"""
        if not self.selected_tools:
            # Show warning if no tools selected
            text = """<b>⚠️ No Tools Selected</b>

You haven't selected any video processing tools. Your download will proceed without any video processing.

Do you want to continue or go back to select tools?"""

            buttons = ButtonMaker()
            buttons.data_button(
                "⬅️ Back to Selection", f"videotools {self.session_id} back"
            )
            buttons.data_button(
                "✓Start Continue Without Processing",
                f"videotools {self.session_id} proceed",
            )
            buttons.data_button("✘", f"videotools {self.session_id} cancel")

            await edit_message(self.message, text, buttons.build_menu(1))
            return False

        # Update listener's video tools settings based on selection
        self.listener.selected_video_tools = self.selected_tools

        # Store the selection for multi-downloads if this is part of a multi-download
        if hasattr(self.listener, "multi_tag") and self.listener.multi_tag:
            from ..common import multi_video_tools_selection, pending_multi_downloads

            multi_video_tools_selection[self.listener.multi_tag] = self.selected_tools
            from ... import LOGGER

            LOGGER.info(
                f"[DEBUG-VT] 💾 Stored video tools selection for multi-download {self.listener.multi_tag}: {self.selected_tools}"
            )
            LOGGER.info(
                f"[DEBUG-VT] 📊 Total stored selections: {len(multi_video_tools_selection)} - Keys: {list(multi_video_tools_selection.keys())}"
            )

            # Process queued messages if this multi-download was waiting
            if self.listener.multi_tag in pending_multi_downloads:
                pending_multi_downloads[self.listener.multi_tag][
                    "waiting_for_selection"
                ] = False
                queued_messages = pending_multi_downloads[self.listener.multi_tag][
                    "queued_messages"
                ]

                if queued_messages:
                    LOGGER.info(
                        f"[DEBUG-VT] 🚀 Processing {len(queued_messages)} queued messages for multi-download {self.listener.multi_tag}"
                    )

                    # Process each queued message
                    for msg_data in queued_messages:
                        try:
                            await msg_data["task_config"].run_multi(
                                msg_data["input_list"], msg_data["obj"]
                            )
                        except Exception as e:
                            LOGGER.error(
                                f"[DEBUG-VT] ❌ Error processing queued message: {e}"
                            )

                    # Clear the queue
                    pending_multi_downloads[self.listener.multi_tag][
                        "queued_messages"
                    ] = []
                    LOGGER.info(
                        f"[DEBUG-VT] ✅ Completed processing queued messages for multi-download {self.listener.multi_tag}"
                    )

        elif hasattr(self, "temp_key"):
            # Store with temp key for later transfer to real multi_tag
            from ..common import multi_video_tools_selection

            multi_video_tools_selection[self.temp_key] = self.selected_tools
            from ... import LOGGER

            LOGGER.info(
                f"[DEBUG-VT] 💾 Stored video tools selection with temp key {self.temp_key}: {self.selected_tools}"
            )
            LOGGER.info(
                f"[DEBUG-VT] 📊 Total stored selections: {len(multi_video_tools_selection)} - Keys: {list(multi_video_tools_selection.keys())}"
            )
        else:
            from ... import LOGGER

            LOGGER.info(
                f"[DEBUG-VT] ⚠️ Not storing selection - multi_tag: {getattr(self.listener, 'multi_tag', 'MISSING')}, temp_key: {getattr(self, 'temp_key', 'MISSING')}"
            )

        # Create summary message
        selected_names = [
            VIDEO_TOOLS_OPTIONS[tool]["name"] for tool in self.selected_tools
        ]

        text = f"""<b>✅ Video Tools Selection Confirmed</b>

<b>Selected Operations:</b> {len(self.selected_tools)}
{chr(10).join([f"• {name}" for name in selected_names])}

Your download will now proceed with the selected video processing operations."""

        await edit_message(self.message, text, None)

        # If trim selected, prompt user for times before continuing download
        if "VIDEO_TRIM" in self.selected_tools:
            try:
                from .task_manager import (
                    trim_waiters,
                )  # relative import two levels up won't work here
            except Exception:
                from ..ext_utils.task_manager import trim_waiters
            prompt = (
                "<b>✂️ Video Trim Enabled</b>\n\n"
                "Send start and end times separated by space (HH:MM:SS HH:MM:SS).\n"
                "Examples:\n<code>00:05:00 00:25:00</code> (keeps 5m-25m)\n"
                "<code>00:02:30 00:00:00</code> (keeps from 2m30s to end)\n"
                "Or send <code>skip</code> to proceed without trimming."
            )
            await sleep(1)
            msg = await send_message(self.listener.message, prompt)
            # Register waiter
            trim_waiters[self.user_id] = {
                "listener": self.listener,
                "prompt_msg_id": msg.id,
            }
        else:
            # Clean up session after short delay then continue
            await sleep(3)
            await delete_message(self.message)
            if self.session_id in video_tools_sessions:
                del video_tools_sessions[self.session_id]
            await self.listener.continue_download()

        return True

    async def cancel_selection(self):
        """Cancel the video tools selection"""
        self.listener.is_cancelled = True

        text = """<b>❌ Video Tools Selection Cancelled</b>

Download has been cancelled."""

        await edit_message(self.message, text, None)

        # Clean up session after short delay
        await sleep(2)
        await delete_message(self.message)

        # Remove session
        if self.session_id in video_tools_sessions:
            del video_tools_sessions[self.session_id]


# Callback handler for video tools selection
async def handle_video_tools_callback(client, callback_query):
    """Handle callback queries for video tools selection"""
    data = callback_query.data.split()

    # Check if the format is correct
    if len(data) < 3 or data[0] != "videotools":
        return

    session_id = data[1]
    action = data[2]

    # Check if session exists
    if session_id not in video_tools_sessions:
        return await callback_query.answer("Session expired...")

    session = video_tools_sessions[session_id]

    # Handle different actions
    if action == "toggle":
        # Toggle tool selection
        if len(data) < 4:
            return await callback_query.answer("Invalid request")

        tool_key = data[3]
        session.toggle_tool(tool_key)
        await callback_query.answer(f"Toggled {VIDEO_TOOLS_OPTIONS[tool_key]['name']}")
        await session.update_selection_menu()

    elif action == "selectall":
        # Select all tools
        session.select_all_tools()
        await callback_query.answer("Selected all available tools")
        await session.update_selection_menu()

    elif action == "deselectall":
        # Deselect all tools
        session.deselect_all_tools()
        await callback_query.answer("Deselected all tools")
        await session.update_selection_menu()

    elif action == "confirm":
        # Confirm selection
        await callback_query.answer("Confirming selection...")
        await session.confirm_selection()

    elif action == "back":
        # Go back to selection from warning
        await callback_query.answer()
        await session.update_selection_menu()

    elif action == "proceed":
        # Proceed without any tools
        await callback_query.answer("Proceeding without video processing...")
        session.listener.selected_video_tools = set()

        # Store the empty selection for multi-downloads if this is part of a multi-download
        if hasattr(session.listener, "multi_tag") and session.listener.multi_tag:
            from ..common import multi_video_tools_selection, pending_multi_downloads

            multi_video_tools_selection[session.listener.multi_tag] = set()
            from ... import LOGGER

            LOGGER.info(
                f"[DEBUG-VT] 💾 Stored empty video tools selection for multi-download {session.listener.multi_tag}"
            )
            LOGGER.info(
                f"[DEBUG-VT] 📊 Total stored selections: {len(multi_video_tools_selection)} - Keys: {list(multi_video_tools_selection.keys())}"
            )

            # Process queued messages if this multi-download was waiting
            if session.listener.multi_tag in pending_multi_downloads:
                pending_multi_downloads[session.listener.multi_tag][
                    "waiting_for_selection"
                ] = False
                queued_messages = pending_multi_downloads[session.listener.multi_tag][
                    "queued_messages"
                ]

                if queued_messages:
                    LOGGER.info(
                        f"[DEBUG-VT] 🚀 Processing {len(queued_messages)} queued messages for multi-download {session.listener.multi_tag}"
                    )

                    # Process each queued message
                    for msg_data in queued_messages:
                        try:
                            await msg_data["task_config"].run_multi(
                                msg_data["input_list"], msg_data["obj"]
                            )
                        except Exception as e:
                            LOGGER.error(
                                f"[DEBUG-VT] ❌ Error processing queued message: {e}"
                            )

                    # Clear the queue
                    pending_multi_downloads[session.listener.multi_tag][
                        "queued_messages"
                    ] = []
                    LOGGER.info(
                        f"[DEBUG-VT] ✅ Completed processing queued messages for multi-download {session.listener.multi_tag}"
                    )
        else:
            from ... import LOGGER

            LOGGER.info(
                f"[DEBUG-VT] ⚠️ Not storing empty selection - multi_tag: {getattr(session.listener, 'multi_tag', 'MISSING')}"
            )

        text = """<b>Proceeding Without Video Processing</b>

Your download will proceed without any video processing operations."""

        await edit_message(session.message, text, None)

        # Clean up session
        await sleep(2)
        await delete_message(session.message)
        if session.session_id in video_tools_sessions:
            del video_tools_sessions[session.session_id]

        # Continue the download process
        await session.listener.continue_download()

    elif action == "cancel":
        # Cancel download
        await callback_query.answer("Cancelling...")
        await session.cancel_selection()


def add_video_tools_handler():
    """Add the video tools callback handler to the bot"""
    from ...core.tg_client import TgClient
    from pyrogram.handlers import CallbackQueryHandler
    from pyrogram.filters import regex

    TgClient.bot.add_handler(
        CallbackQueryHandler(handle_video_tools_callback, filters=regex("^videotools"))
    )
