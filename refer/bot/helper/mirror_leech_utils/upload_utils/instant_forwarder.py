from logging import getLogger
from time import time
from asyncio import sleep
from pyrogram.errors import (
    FloodWait,
    UserBannedInChannel,
    ChatAdminRequired,
    PeerIdInvalid,
)
from ....core.config_manager import Config
from ....core.tg_client import TgClient
from ...telegram_helper.button_build import ButtonMaker

LOGGER = getLogger(__name__)


class InstantForwarder:
    """
    Class to handle the instant forwarding of files from LEECH_DUMP_CHAT to user's destination
    This forwards files immediately after they're uploaded to LEECH_DUMP_CHAT
    """

    def __init__(self, listener):
        self._listener = listener
        self._processed_bytes = 0
        self._forwarded_files = (
            set()
        )  # To track files we've already forwarded to avoid duplicacy

    async def forward_file(self, msg, file_name):
        """
        Forward a single file from LEECH_DUMP_CHAT to user's destination instantly

        Args:
            msg: The message object from Telegram
            file_name: The name of the file

        Returns:
            The forwarded message object if successful, None otherwise
        """
        if (
            not self._listener
            or not hasattr(self._listener, "up_dest")
            or not self._listener.up_dest
        ):
            LOGGER.warning("No destination set for instant forwarding")
            return None

        if not msg or not hasattr(msg, "id"):
            LOGGER.error("Invalid message object for forwarding")
            return None

        # Get the destination from the listener
        up_dest = (
            getattr(self._listener, "_up_dest_original", None) or self._listener.up_dest
        )

        # Early return if up_dest is invalid or same as LEECH_DUMP_CHAT
        if not up_dest or str(up_dest) == str(Config.LEECH_DUMP_CHAT):
            LOGGER.warning(f"Invalid destination for instant forwarding: {up_dest}")
            return None

        # Check if the file has already been forwarded (to avoid duplicacy)
        if file_name in self._forwarded_files:
            LOGGER.info(f"File {file_name} already forwarded - skipping")
            return None

        # Add a unique identifier to avoid any potential duplicacy issues
        file_key = f"{msg.chat.id}_{msg.id}_{file_name}"
        if file_key in self._forwarded_files:
            LOGGER.info(
                f"File {file_name} (message ID: {msg.id}) already forwarded - skipping"
            )
            return None

        try:
            LOGGER.info(f"Instant forwarding file: {file_name} to {up_dest}")

            # Try the copy method
            forwarded = await msg.copy(
                chat_id=up_dest,
                disable_notification=True,
                message_thread_id=getattr(self._listener, "chat_thread_id", None),
            )

            # Add to the set of forwarded files with both simple name and unique key
            self._forwarded_files.add(file_name)
            self._forwarded_files.add(file_key)

            # Add mediainfo button if enabled in user settings
            await self._add_mediainfo_button(forwarded, msg)

            LOGGER.info(f"Successfully instant forwarded: {file_name}")
            return forwarded

        except FloodWait as fw:
            LOGGER.warning(f"FloodWait: {fw.value} seconds")
            await sleep(fw.value + 1)
            # Retry once after the floodwait
            try:
                forwarded = await msg.copy(
                    chat_id=up_dest,
                    disable_notification=True,
                    message_thread_id=getattr(self._listener, "chat_thread_id", None),
                )
                self._forwarded_files.add(file_name)
                self._forwarded_files.add(file_key)
                await self._add_mediainfo_button(forwarded, msg)
                LOGGER.info(
                    f"Successfully instant forwarded after floodwait: {file_name}"
                )
                return forwarded
            except Exception as e:
                LOGGER.error(f"Failed to forward file after floodwait: {str(e)}")
                return None
        except (UserBannedInChannel, ChatAdminRequired, PeerIdInvalid) as e:
            LOGGER.error(f"Permission error forwarding message: {e}")
            return None
        except Exception as e:
            LOGGER.error(f"Error forwarding message: {e}")
            return None

    async def _add_mediainfo_button(self, forwarded_msg, original_msg):
        """Add mediainfo button to the forwarded message if setting is enabled"""
        if not forwarded_msg:
            return

        show_mediainfo = self._listener.user_dict.get("SHOW_MEDIAINFO_BUTTON", True)
        if not show_mediainfo:
            return

        try:
            from ....modules.mediainfo import get_mediainfo_telegraph_link

            media = None
            if hasattr(original_msg, "document") and original_msg.document:
                media = original_msg.document
            elif hasattr(original_msg, "video") and original_msg.video:
                media = original_msg.video
            elif hasattr(original_msg, "audio") and original_msg.audio:
                media = original_msg.audio

            if not media:
                return

            telegraph_link = await get_mediainfo_telegraph_link(media, original_msg)
            if telegraph_link:
                buttons = ButtonMaker()
                buttons.url_button("Media Info", telegraph_link)
                await forwarded_msg.edit_reply_markup(
                    reply_markup=buttons.build_menu(1)
                )
        except Exception as e:
            LOGGER.warning(f"Failed to add Media Info button: {e}")

    @property
    def forwarded_files(self):
        """Get the set of files that have been forwarded"""
        return self._forwarded_files
