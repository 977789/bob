import re
from logging import getLogger
from time import time
from asyncio import sleep
from pyrogram.enums import ChatType
from pyrogram.errors import (
    FloodWait,
    UserBannedInChannel,
    ChatAdminRequired,
    PeerIdInvalid,
)

from ....core.tg_client import TgClient
from ....modules.mediainfo import get_mediainfo_telegraph_link
from ...telegram_helper.button_build import ButtonMaker

LOGGER = getLogger(__name__)


class LeechForwarder:
    """
    Class to handle the forwarding of files from LEECH_DUMP_CHAT to user's destination
    """

    def __init__(self, listener):
        self._listener = listener
        self._start_time = time()
        self._processed_bytes = 0
        self._total_files = 0
        self._msgs_dict = {}
        self._corrupted = 0
        self._error = ""

    async def forward_leech_files(self, sent_files, size):
        """
        Forward files from LEECH_DUMP_CHAT to user's destination

        Args:
            sent_files: Dictionary of file links and their names sent to LEECH_DUMP_CHAT
            size: Total size of files

        Returns:
            Dictionary of forwarded file links and their names
        """
        if not sent_files:
            LOGGER.warning("No files to forward from LEECH_DUMP_CHAT")
            return {}, 0, 0

        self._total_files = len(sent_files)

        up_dest = getattr(self._listener, "_up_dest_original", None)

        if not up_dest:
            LOGGER.error("Could not determine the original destination for forwarding!")
            return {}, self._total_files, self._total_files

        forwarded_msgs = {}
        corrupted = 0

        for idx, (link, name) in enumerate(sent_files.items(), 1):
            if self._listener.is_cancelled:
                return forwarded_msgs, self._total_files, corrupted

            try:
                chat_id = None
                msg_id = None

                private_match = re.match(r"https?://t\.me/c/(\d+)/(\d+)", link)
                public_match = re.match(r"https?://t\.me/([^/]+)/(\d+)", link)

                if private_match:
                    chat_id_str = private_match.group(1)
                    chat_id = int(f"-100{chat_id_str}")
                    msg_id = int(private_match.group(2))
                elif public_match:
                    chat_id = public_match.group(1)  # Could be username
                    msg_id = int(public_match.group(2))
                else:
                    LOGGER.error(
                        f"Could not parse message link: {link}. Format not recognized."
                    )
                    corrupted += 1
                    continue

                message = await TgClient.bot.get_messages(
                    chat_id=chat_id, message_ids=msg_id
                )
                if not message:
                    LOGGER.error(
                        f"Failed to get message from link: {link} using bot client."
                    )
                    corrupted += 1
                    continue

                # Get topic ID from listener if available
                topic_id = getattr(self._listener, "chat_thread_id", None)

                forwarded = await TgClient.bot.copy_message(
                    chat_id=up_dest,
                    from_chat_id=message.chat.id,
                    message_id=message.id,
                    disable_notification=True,
                    message_thread_id=topic_id,
                )

                if not forwarded:
                    LOGGER.error(f"Message copy returned None for link: {link}")
                    corrupted += 1
                    continue

                link_to_store = ""
                if forwarded.chat.type == ChatType.PRIVATE:
                    link_to_store = (
                        f"https://t.me/pm/{forwarded.chat.id}/{forwarded.id}"
                    )
                else:
                    link_to_store = forwarded.link

                forwarded_msgs[link_to_store] = name

                show_mediainfo = self._listener.user_dict.get(
                    "SHOW_MEDIAINFO_BUTTON", True
                )
                if show_mediainfo:
                    media_content = message.document or message.video or message.audio
                    if media_content:
                        try:
                            telegraph_link = await get_mediainfo_telegraph_link(
                                media_content, message, None, name
                            )
                            if telegraph_link:
                                buttons = ButtonMaker()
                                buttons.url_button("Media Info", telegraph_link)
                                await forwarded.edit_reply_markup(
                                    reply_markup=buttons.build_menu(1)
                                )
                        except Exception as e:
                            LOGGER.warning(
                                f"Failed to add MediaInfo button for {name}: {e}"
                            )

                if idx % 5 == 0:
                    await sleep(1)

            except FloodWait as fw:
                LOGGER.warning(f"FloodWait: Waiting {fw.value + 5}s for link: {link}")
                await sleep(fw.value + 5)
                idx -= 1
                continue
            except (UserBannedInChannel, ChatAdminRequired, PeerIdInvalid) as e:
                LOGGER.error(
                    f"Permission error forwarding message: {e}. The bot may not be in the dump channel."
                )
                self._error = str(e)
                corrupted += (self._total_files - idx) + 1
                break
            except Exception as e:
                LOGGER.error(
                    f"An unexpected error occurred while forwarding link {link}: {e}",
                    exc_info=True,
                )
                self._error = str(e)
                corrupted += 1
                continue

        return forwarded_msgs, self._total_files, corrupted
