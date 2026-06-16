from logging import getLogger
from time import sleep, time
from pyrogram.errors import (
    FloodWait,
    UserBannedInChannel,
    ChatAdminRequired,
    PeerIdInvalid,
)
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ....core.config_manager import Config
from ....core.tg_client import TgClient
from ...telegram_helper.button_build import ButtonMaker
from ...ext_utils.status_utils import get_readable_file_size, get_readable_time
from ...telegram_helper.message_utils import delete_message

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

        # Try to get the destination in multiple ways
        up_dest = None

        # First, check the normal attribute
        if hasattr(self._listener, "up_dest") and self._listener.up_dest:
            up_dest = self._listener.up_dest
            LOGGER.info(f"Using up_dest from listener: {up_dest}")

        # If not found, try to recover from _up_dest_original
        if not up_dest and hasattr(self._listener, "_up_dest_original"):
            up_dest = self._listener._up_dest_original
            LOGGER.info(f"Recovered destination from _up_dest_original: {up_dest}")

        # Debug information
        LOGGER.info(
            f"LEECH_DUMP_FORWARDING: files={len(sent_files)}, destination={up_dest}"
        )
        LOGGER.info(
            f"Listener attributes: up_dest={getattr(self._listener, 'up_dest', None)}, "
            f"_up_dest_original={getattr(self._listener, '_up_dest_original', None)}, "
            f"chat_thread_id={getattr(self._listener, 'chat_thread_id', None)}"
        )

        # If we still don't have a valid destination, check if we can get it from the message attribute
        if (
            not up_dest
            and hasattr(self._listener, "message")
            and hasattr(self._listener.message, "chat")
        ):
            up_dest = self._listener.message.chat.id
            LOGGER.info(f"Using message.chat.id as destination: {up_dest}")

        # Check if up_dest is valid
        if not up_dest:
            LOGGER.error(
                "No destination chat provided for forwarding after all recovery attempts!"
            )
            return {}, self._total_files, self._total_files

        LOGGER.info(
            f"Forwarding {self._total_files} files from LEECH_DUMP_CHAT to {up_dest}"
        )

        forwarded_msgs = {}
        corrupted = 0

        for idx, (link, name) in enumerate(sent_files.items(), 1):
            if self._listener.is_cancelled:
                return forwarded_msgs, self._total_files, corrupted

            try:
                LOGGER.info(f"Processing link: {link}")

                # Make sure we have the correct link format
                if not link or "/" not in link:
                    LOGGER.error(f"Invalid link format: {link}")
                    corrupted += 1
                    continue

                # Parse link properly depending on format
                # Format t.me/c/chat_id/msg_id or t.me/chat_handle/msg_id
                parts = link.strip("/").split("/")
                LOGGER.info(f"Link parts: {parts}")

                chat_id = None
                msg_id = None

                # Try to handle different link formats
                if len(parts) >= 3:
                    if "t.me/c/" in link:
                        # Format is t.me/c/chat_id/msg_id
                        chat_id = parts[-2]
                        msg_id = parts[-1]
                    else:
                        # Format is t.me/chat_handle/msg_id
                        chat_id = parts[-2]
                        msg_id = parts[-1]
                else:
                    # Try to find chat_id and msg_id directly from the parts
                    for part in parts:
                        if part.isdigit():
                            if msg_id is None:
                                msg_id = part
                            elif chat_id is None:
                                chat_id = msg_id
                                msg_id = part

                if not chat_id or not msg_id:
                    LOGGER.error(
                        f"Couldn't extract chat_id and msg_id from link: {link}"
                    )
                    corrupted += 1
                    continue

                if chat_id.isdigit():
                    chat_id = int(chat_id)
                # Ensure chat_id is in the correct format for supergroups/channels
                if (
                    isinstance(chat_id, int)
                    and chat_id > 0
                    and not str(chat_id).startswith("-100")
                ):
                    chat_id = int(f"-100{chat_id}")

                if msg_id.isdigit():
                    msg_id = int(msg_id)
                else:
                    LOGGER.error(f"Invalid message ID format: {msg_id}")
                    corrupted += 1
                    continue

                LOGGER.info(f"Extracted chat_id={chat_id}, msg_id={msg_id}")

                # Get the message from the dump chat
                try:
                    message = await TgClient.bot.get_messages(
                        chat_id=chat_id, message_ids=msg_id
                    )
                except Exception as e:
                    LOGGER.error(f"Failed to get message: {link}, Error: {str(e)}")
                    corrupted += 1
                    continue

                if not message:
                    LOGGER.error(f"Message not found: {link}")
                    corrupted += 1
                    continue

                # Log detailed message info
                msg_type = "Unknown"
                file_id = None
                file_name = None

                if message.document:
                    msg_type = "Document"
                    file_id = message.document.file_id
                    file_name = getattr(message.document, "file_name", "Unknown")
                    LOGGER.info(f"Document found: {file_name}, file_id={file_id}")
                elif message.video:
                    msg_type = "Video"
                    file_id = message.video.file_id
                    file_name = getattr(message.video, "file_name", "Unknown")
                    LOGGER.info(f"Video found: {file_name}, file_id={file_id}")
                elif message.audio:
                    msg_type = "Audio"
                    file_id = message.audio.file_id
                    file_name = getattr(message.audio, "file_name", "Unknown")
                    LOGGER.info(f"Audio found: {file_name}, file_id={file_id}")
                elif message.photo:
                    msg_type = "Photo"
                    if message.photo:
                        file_id = message.photo.file_id
                        LOGGER.info(f"Photo found, file_id={file_id}")

                LOGGER.info(
                    f"Found message to forward: ID={msg_id}, type={msg_type}, filename={file_name}, destination={up_dest}"
                )

                # Try alternative forwarding method if file_id is available
                if file_id and msg_type in ("Document", "Video", "Audio"):
                    try:
                        LOGGER.info(
                            f"Trying to send file directly using file_id: {file_id}"
                        )

                        if msg_type == "Document":
                            forwarded = await TgClient.bot.send_document(
                                chat_id=up_dest,
                                document=file_id,
                                caption=message.caption,
                                file_name=file_name,
                                force_document=True,
                                disable_notification=True,
                                message_thread_id=getattr(
                                    self._listener, "chat_thread_id", None
                                ),
                            )
                        elif msg_type == "Video":
                            forwarded = await TgClient.bot.send_video(
                                chat_id=up_dest,
                                video=file_id,
                                caption=message.caption,
                                file_name=file_name,
                                disable_notification=True,
                                message_thread_id=getattr(
                                    self._listener, "chat_thread_id", None
                                ),
                            )
                        elif msg_type == "Audio":
                            forwarded = await TgClient.bot.send_audio(
                                chat_id=up_dest,
                                audio=file_id,
                                caption=message.caption,
                                file_name=file_name,
                                disable_notification=True,
                                message_thread_id=getattr(
                                    self._listener, "chat_thread_id", None
                                ),
                            )

                        LOGGER.info(
                            f"Direct file send successful - new message ID: {forwarded.id}"
                        )
                    except Exception as e:
                        LOGGER.warning(
                            f"Direct file send failed: {str(e)}. Falling back to copy method."
                        )
                        # Fall back to copy method
                        try:
                            forwarded = await message.copy(
                                chat_id=up_dest,
                                disable_notification=True,
                                message_thread_id=getattr(
                                    self._listener, "chat_thread_id", None
                                ),
                            )
                            LOGGER.info(
                                f"Copy successful - new message ID: {forwarded.id}"
                            )
                        except Exception as e2:
                            LOGGER.error(f"Failed to copy message {msg_id}: {str(e2)}")
                            corrupted += 1
                            continue
                else:
                    # Use copy method for all other cases
                    try:
                        forwarded = await message.copy(
                            chat_id=up_dest,
                            disable_notification=True,
                            message_thread_id=getattr(
                                self._listener, "chat_thread_id", None
                            ),
                        )
                        LOGGER.info(f"Copy successful - new message ID: {forwarded.id}")
                    except Exception as e:
                        LOGGER.error(f"Failed to copy message {msg_id}: {str(e)}")
                        corrupted += 1
                        continue

                LOGGER.info(
                    f"Successfully forwarded message {idx}/{self._total_files} to {up_dest}"
                )

                # Add mediainfo button to forwarded message if enabled in user settings
                show_mediainfo = self._listener.user_dict.get(
                    "SHOW_MEDIAINFO_BUTTON", True
                )
                if show_mediainfo:
                    try:
                        from pyrogram.errors import FileReferenceExpired
                        from ....modules.mediainfo import get_mediainfo_telegraph_link

                        leech_dump_chat_id = int(Config.LEECH_DUMP_CHAT)
                        try:
                            original_message = await TgClient.bot.get_messages(
                                chat_id=leech_dump_chat_id, message_ids=msg_id
                            )
                        except FileReferenceExpired:
                            LOGGER.warning(
                                f"Cannot generate mediainfo: file reference expired for msg_id={msg_id}."
                            )
                            continue
                        media = None
                        if original_message.document:
                            media = original_message.document
                        elif original_message.video:
                            media = original_message.video
                        elif original_message.audio:
                            media = original_message.audio
                        if media:
                            LOGGER.info(
                                f"Generating mediainfo for file: {getattr(media, 'file_name', 'Unknown')}"
                            )
                            try:
                                telegraph_link = await get_mediainfo_telegraph_link(
                                    media, original_message
                                )
                            except FileNotFoundError:
                                LOGGER.warning(
                                    f"Cannot generate mediainfo: file not found locally for {getattr(media, 'file_name', 'Unknown')}"
                                )
                                continue
                            if telegraph_link:
                                LOGGER.info(
                                    f"Generated mediainfo link: {telegraph_link}"
                                )
                                buttons = ButtonMaker()
                                buttons.url_button("Media Info", telegraph_link)
                                await forwarded.edit_reply_markup(
                                    reply_markup=buttons.build_menu(1)
                                )
                    except Exception as e:
                        LOGGER.warning(f"Failed to add Media Info button: {e}")

                # Add the forwarded message to our dictionary
                forwarded_msgs[forwarded.link] = name

                # Update progress for the listener if needed
                self._processed_bytes += (
                    getattr(message.document, "file_size", 0) if message.document else 0
                )
                self._processed_bytes += (
                    getattr(message.video, "file_size", 0) if message.video else 0
                )
                self._processed_bytes += (
                    getattr(message.audio, "file_size", 0) if message.audio else 0
                )

                if idx % 5 == 0:
                    await sleep(1)  # Small delay to avoid flood

            except FloodWait as fw:
                LOGGER.warning(f"FloodWait: {fw.value} seconds")
                await sleep(fw.value + 5)
                idx -= 1  # Retry this message
                continue
            except (UserBannedInChannel, ChatAdminRequired, PeerIdInvalid) as e:
                LOGGER.error(f"Permission error forwarding message: {e}")
                self._error = str(e)
                corrupted += 1
                continue
            except Exception as e:
                LOGGER.error(f"Error forwarding message: {e}")
                self._error = str(e)
                corrupted += 1
                continue

        return forwarded_msgs, self._total_files, corrupted
