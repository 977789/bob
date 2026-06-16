from logging import getLogger
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
        self._forwarded_files = set()

    async def forward_file(self, msg, file_name):
        """
        Forward a single file from LEECH_DUMP_CHAT to user's destination instantly

        Args:
            msg: The message object from Telegram (sent by the user session)
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

        up_dest = (
            getattr(self._listener, "_up_dest_original", None) or self._listener.up_dest
        )

        if not up_dest or str(up_dest) == str(Config.LEECH_DUMP_CHAT):
            LOGGER.warning(f"Invalid destination for instant forwarding: {up_dest}")
            return None

        file_key = f"{msg.chat.id}_{msg.id}_{file_name}"
        if file_key in self._forwarded_files:
            return None

        try:
            # Get topic ID from listener if available
            topic_id = getattr(self._listener, "chat_thread_id", None)

            forwarded = await TgClient.bot.copy_message(
                chat_id=up_dest,
                from_chat_id=msg.chat.id,
                message_id=msg.id,
                disable_notification=True,
                message_thread_id=topic_id,
            )

            self._forwarded_files.add(file_key)
            await self._add_mediainfo_button(forwarded, msg, file_name)
            return forwarded

        except FloodWait as fw:
            LOGGER.warning(f"FloodWait: {fw.value} seconds")
            await sleep(fw.value + 2)
            try:
                forwarded = await TgClient.bot.copy_message(
                    chat_id=up_dest,
                    from_chat_id=msg.chat.id,
                    message_id=msg.id,
                    disable_notification=True,
                    message_thread_id=topic_id,
                )
                self._forwarded_files.add(file_key)
                await self._add_mediainfo_button(forwarded, msg, file_name)
                return forwarded
            except Exception as e:
                LOGGER.error(f"Failed to forward file after floodwait: {str(e)}")
                return None
        except (UserBannedInChannel, ChatAdminRequired, PeerIdInvalid) as e:
            LOGGER.error(f"Permission error forwarding message: {e}")
            return None
        except Exception as e:
            LOGGER.error(f"Error forwarding message: {e}", exc_info=True)
            return None

    async def _add_mediainfo_button(self, forwarded_msg, original_msg, file_name=None):
        """Add mediainfo button to the forwarded message if setting is enabled"""
        if not forwarded_msg:
            return

        show_mediainfo = self._listener.user_dict.get("SHOW_MEDIAINFO_BUTTON", True)
        if not show_mediainfo:
            return

        try:
            original_msg_for_mi = await TgClient.bot.get_messages(
                original_msg.chat.id, original_msg.id
            )
            if not original_msg_for_mi:
                LOGGER.warning(
                    f"InstantForwarder: Could not fetch original message {original_msg.id} with bot client for mediainfo."
                )
                return

            from ....modules.mediainfo import get_mediainfo_telegraph_link

            media = (
                original_msg_for_mi.document
                or original_msg_for_mi.video
                or original_msg_for_mi.audio
            )

            if not media:
                return

            telegraph_link = await get_mediainfo_telegraph_link(
                media, original_msg_for_mi, None, file_name
            )
            if telegraph_link:
                buttons = ButtonMaker()
                buttons.url_button("Media Info", telegraph_link)
                button_markup = buttons.build_menu(1)

                await forwarded_msg.edit_reply_markup(reply_markup=button_markup)
            else:
                LOGGER.warning(
                    f"InstantForwarder: Telegraph link for MediaInfo was None. Button not added for original message ID {original_msg.id}."
                )
        except Exception as e:
            LOGGER.warning(
                f"InstantForwarder: Failed to generate or add Media Info button: {e}",
                exc_info=True,
            )

    @property
    def forwarded_files(self):
        """Get the set of files that have been forwarded"""
        return self._forwarded_files
