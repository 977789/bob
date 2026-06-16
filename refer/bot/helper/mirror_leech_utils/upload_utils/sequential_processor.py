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


class SequentialProcessor:
    """
    Sequential file processor that handles:
    1. Upload to LEECH_DUMP_CHAT (primary storage/org destination)
    2. Copy to User PM By Bot session From LEECH_DUMP_CHAT
    3. Copy to up_dest (if specified) By Bot session from LEECH_DUMP_CHAT
    4. Bot will add a mediainfo button by editing message and telegraph link generated via using /mediainfo
    5. Wait 3 seconds between files
    6. Repeat for next file
    """

    def __init__(self, listener):
        self._listener = listener
        self._start_time = time()
        self._processed_files = []
        self._total_files = 0
        self._msgs_dict = {}
        self._corrupted = 0
        self._error = ""
        self._bot_pm_enabled = False  # Will be set by telegram uploader

    async def process_files_sequentially(self, files_dict, total_size):
        """
        Process files sequentially with the new workflow:
        1. Upload to LEECH_DUMP_CHAT (already done)
        2. Copy to User PM from LEECH_DUMP_CHAT
        3. Copy to up_dest (if specified) from LEECH_DUMP_CHAT
        4. Add mediainfo button with telegraph link
        5. Wait 3 seconds between files
        """
        if not files_dict:
            LOGGER.warning("No files to process sequentially")
            return {}, 0, 0

        if not Config.LEECH_DUMP_CHAT:
            LOGGER.error("LEECH_DUMP_CHAT not configured for sequential processing")
            return {}, 0, 0

        # Sequential processing is always enabled
        self._total_files = len(files_dict)
        processed_files = {}

        # Get destinations
        user_pm_dest = self._get_user_pm_destination()
        up_dest = getattr(self._listener, "up_dest", None)

        # Check if BOT_PM is enabled to avoid duplication
        # BOT_PM can be set in user_dict, passed from uploader, or through listener
        bot_pm_from_user = self._listener.user_dict.get("BOT_PM", False)
        bot_pm_from_uploader = getattr(self, "_bot_pm_enabled", False)
        bot_pm_from_listener = getattr(self._listener, "_bot_pm", False)
        bot_pm_enabled = (
            bot_pm_from_user or bot_pm_from_uploader or bot_pm_from_listener
        )

        # Skip if up_dest is same as LEECH_DUMP_CHAT
        if up_dest and str(up_dest) == str(Config.LEECH_DUMP_CHAT):
            up_dest = None

        # If BOT_PM is enabled, don't copy to User PM again as it's already done by telegram uploader
        if bot_pm_enabled:
            user_pm_dest = None
            LOGGER.info("BOT_PM is enabled, skipping User PM copy to avoid duplication")

        LOGGER.info(f"Starting sequential processing of {self._total_files} files")
        LOGGER.info(
            f"BOT_PM: {bot_pm_enabled} (user: {bot_pm_from_user}, uploader: {bot_pm_from_uploader}, listener: {bot_pm_from_listener})"
        )
        LOGGER.info(f"Destinations - User PM: {user_pm_dest}, Up Dest: {up_dest}")

        for idx, (file_link, file_name) in enumerate(files_dict.items(), 1):
            try:
                LOGGER.info(f"Processing file {idx}/{self._total_files}: {file_name}")

                # Step 1: Files should already be in LEECH_DUMP_CHAT from upload
                # Get the message from LEECH_DUMP_CHAT
                dump_msg = await self._get_message_from_link(file_link)
                if not dump_msg:
                    LOGGER.error(
                        f"Could not get message from LEECH_DUMP_CHAT for {file_name}"
                    )
                    continue

                # Step 2: Copy to User PM if available
                user_pm_msg = None
                if user_pm_dest:
                    user_pm_msg = await self._copy_to_destination(
                        dump_msg, user_pm_dest, file_name, "User PM"
                    )

                # Step 3: Copy to up_dest if specified and different from User PM
                up_dest_msg = None
                if up_dest and up_dest != user_pm_dest:
                    up_dest_msg = await self._copy_to_destination(
                        dump_msg, up_dest, file_name, "Up Dest"
                    )

                # Step 4: Add mediainfo button to all copies
                await self._add_mediainfo_buttons(
                    dump_msg, user_pm_msg, up_dest_msg, file_name
                )

                # Store the processed file info
                # Priority: User PM message > up_dest message > dump message
                # But if BOT_PM is enabled, prefer up_dest message as user PM is handled separately
                if bot_pm_enabled:
                    final_msg = up_dest_msg or dump_msg
                else:
                    final_msg = user_pm_msg or up_dest_msg or dump_msg

                if final_msg:
                    processed_files[self._get_message_link(final_msg)] = file_name
                    self._processed_files.append(file_name)

                LOGGER.info(
                    f"Successfully processed file {idx}/{self._total_files}: {file_name}"
                )

                # Step 5: Wait 3 seconds between files (except for the last file)
                if idx < self._total_files:
                    await sleep(3)

            except Exception as e:
                LOGGER.error(f"Error processing file {file_name}: {str(e)}")
                self._corrupted += 1
                continue

        self._msgs_dict = processed_files
        LOGGER.info(
            f"Sequential processing completed. Processed: {len(processed_files)}, Corrupted: {self._corrupted}"
        )

        return processed_files, self._total_files, self._corrupted

    def _get_user_pm_destination(self):
        """Get user PM destination from listener"""
        if hasattr(self._listener, "message") and hasattr(
            self._listener.message, "from_user"
        ):
            return self._listener.message.from_user.id
        return None

    async def _get_message_from_link(self, file_link):
        """Get message object from Telegram link"""
        try:
            # Extract chat_id and message_id from the link
            # Format: https://t.me/c/chat_id/message_id
            parts = file_link.split("/")
            if len(parts) >= 2:
                chat_id = -int("100" + parts[-2])  # Convert to supergroup format
                message_id = int(parts[-1])
                return await TgClient.bot.get_messages(chat_id, message_id)
        except Exception as e:
            LOGGER.error(f"Error getting message from link {file_link}: {e}")
        return None

    async def _copy_to_destination(self, source_msg, destination, file_name, dest_type):
        """Copy message to destination"""
        try:
            LOGGER.info(f"Copying {file_name} to {dest_type}: {destination}")

            copied_msg = await source_msg.copy(
                chat_id=destination,
                disable_notification=True,
                message_thread_id=getattr(self._listener, "chat_thread_id", None),
            )

            LOGGER.info(f"Successfully copied {file_name} to {dest_type}")
            return copied_msg

        except FloodWait as e:
            LOGGER.warning(f"FloodWait {e.value} seconds while copying to {dest_type}")
            await sleep(e.value)
            return await self._copy_to_destination(
                source_msg, destination, file_name, dest_type
            )
        except UserBannedInChannel:
            LOGGER.error(f"Bot is banned in destination {dest_type}: {destination}")
            return None
        except ChatAdminRequired:
            LOGGER.error(
                f"Bot needs admin rights in destination {dest_type}: {destination}"
            )
            return None
        except PeerIdInvalid:
            LOGGER.error(f"Invalid destination {dest_type}: {destination}")
            return None
        except Exception as e:
            LOGGER.error(f"Error copying to {dest_type} {destination}: {str(e)}")
            return None

    async def _add_mediainfo_buttons(
        self, dump_msg, user_pm_msg, up_dest_msg, file_name
    ):
        """Add mediainfo buttons to all message copies (using global cache to avoid telegraph rate limiting)"""
        try:
            # Check if mediainfo button should be shown
            show_mediainfo = self._listener.user_dict.get("SHOW_MEDIAINFO_BUTTON", True)
            if not show_mediainfo:
                return

            # Generate mediainfo telegraph link (now cached at module level)
            telegraph_link = await self._generate_mediainfo_link(dump_msg)
            if not telegraph_link:
                return

            # Create the button
            buttons = ButtonMaker()
            buttons.url_button("Media Info", telegraph_link)
            reply_markup = buttons.build_menu(1)

            # Add button to all message copies
            messages_to_edit = []
            if dump_msg:
                messages_to_edit.append(("LEECH_DUMP_CHAT", dump_msg))
            if user_pm_msg:
                messages_to_edit.append(("User PM", user_pm_msg))
            if up_dest_msg:
                messages_to_edit.append(("Up Dest", up_dest_msg))

            for dest_name, msg in messages_to_edit:
                try:
                    await msg.edit_reply_markup(reply_markup=reply_markup)
                    LOGGER.info(f"Added mediainfo button to {file_name} in {dest_name}")
                    # Small delay to avoid rate limiting when editing multiple messages
                    await sleep(0.5)
                except FloodWait as e:
                    LOGGER.warning(
                        f"FloodWait {e.value}s when adding mediainfo button to {file_name} in {dest_name}"
                    )
                    await sleep(e.value)
                    try:
                        await msg.edit_reply_markup(reply_markup=reply_markup)
                        LOGGER.info(
                            f"Retry successful: Added mediainfo button to {file_name} in {dest_name}"
                        )
                    except Exception as retry_err:
                        LOGGER.error(
                            f"Retry failed for mediainfo button to {file_name} in {dest_name}: {retry_err}"
                        )
                except Exception as e:
                    LOGGER.warning(
                        f"Failed to add mediainfo button to {file_name} in {dest_name}: {e}"
                    )

        except Exception as e:
            LOGGER.error(f"Error adding mediainfo buttons for {file_name}: {e}")

    async def _generate_mediainfo_link(self, msg):
        """Generate mediainfo telegraph link for a message"""
        try:
            from ....modules.mediainfo import get_mediainfo_telegraph_link

            media = None
            if hasattr(msg, "document") and msg.document:
                media = msg.document
            elif hasattr(msg, "video") and msg.video:
                media = msg.video
            elif hasattr(msg, "audio") and msg.audio:
                media = msg.audio

            if not media:
                return None

            return await get_mediainfo_telegraph_link(media, msg)

        except FloodWait as e:
            LOGGER.warning(
                f"FloodWait {e.value}s when generating mediainfo telegraph link"
            )
            await sleep(e.value)
            # Don't retry immediately, let the caller handle it
            return None
        except Exception as e:
            LOGGER.error(f"Error generating mediainfo link: {e}")
            return None

    def _get_message_link(self, msg):
        """Get Telegram message link"""
        try:
            if hasattr(msg, "link"):
                return msg.link
            elif hasattr(msg, "chat") and hasattr(msg, "id"):
                chat_id = str(msg.chat.id).replace("-100", "")
                return f"https://t.me/c/{chat_id}/{msg.id}"
        except Exception as e:
            LOGGER.error(f"Error getting message link: {e}")
        return None

    @property
    def processed_files(self):
        """Get list of processed files"""
        return self._processed_files

    @property
    def total_files(self):
        """Get total number of files"""
        return self._total_files

    @property
    def corrupted(self):
        """Get number of corrupted files"""
        return self._corrupted

    @property
    def msgs_dict(self):
        """Get messages dictionary"""
        return self._msgs_dict
