#!/usr/bin/env python3

from pyrogram import filters
from pyrogram.types import Message

from ..ext_utils.links_utils import is_url, is_telegram_link, is_magnet
from ..telegram_helper.filters import CustomFilters
from ..telegram_helper.bot_commands import BotCommands
from ..common import user_data


class AutoProcessor:
    """Handles automatic processing of links and files based on user settings"""

    @staticmethod
    async def process_auto_message(client, message: Message):
        """Process messages for auto leech/mirror functionality"""

        # Get user info
        user = message.from_user or message.sender_chat
        if not user:
            return

        user_id = user.id
        user_dict = user_data.get(user_id, {})

        # Check if any auto features are enabled
        auto_leech = user_dict.get("AUTO_LEECH", False)
        auto_mirror = user_dict.get("AUTO_MIRROR", False)
        auto_ft = user_dict.get("AUTO_FT", False)

        if not (auto_leech or auto_mirror):
            return

        # Debug logging
        from ... import LOGGER

        LOGGER.info(
            f"Auto processing triggered for user {user_id}: auto_leech={auto_leech}, auto_mirror={auto_mirror}, auto_ft={auto_ft}"
        )

        # Check if message contains URL, magnet link, or is a media file
        message_text = message.text or message.caption or ""
        has_url = any(
            is_url(word) or is_magnet(word) or is_telegram_link(word)
            for word in message_text.split()
        )

        # Check for any kind of media file
        has_media = bool(
            message.document
            or message.photo
            or message.video
            or message.audio
            or message.voice
            or message.video_note
            or message.sticker
            or message.animation
        )

        if not (has_url or has_media):
            LOGGER.info(f"No processable content found in message for user {user_id}")
            return

        # Determine which mode to use (prioritize leech over mirror if both enabled)
        is_leech = auto_leech

        LOGGER.info(
            f"Processing {'media file' if has_media else 'URL'} for user {user_id}, mode: {'leech' if is_leech else 'mirror'}, force_tools: {auto_ft}"
        )

        # Prioritize media files over URLs in text
        # If message has media, always treat as media file regardless of text content
        if has_media:
            # For media files, use the command without URL
            if auto_ft:
                command_text = f"/{BotCommands.LeechCommand[0] if is_leech else BotCommands.MirrorCommand[0]} -ft"
            else:
                command_text = f"/{BotCommands.LeechCommand[0] if is_leech else BotCommands.MirrorCommand[0]}"
        elif has_url:
            # Extract first URL from message only if no media file present
            urls = [
                word
                for word in message_text.split()
                if is_url(word) or is_magnet(word) or is_telegram_link(word)
            ]
            if urls:
                link = urls[0]
                # Create command text
                if auto_ft:
                    command_text = f"/{BotCommands.LeechCommand[0] if is_leech else BotCommands.MirrorCommand[0]} {link} -ft"
                else:
                    command_text = f"/{BotCommands.LeechCommand[0] if is_leech else BotCommands.MirrorCommand[0]} {link}"
            else:
                command_text = f"/{BotCommands.LeechCommand[0] if is_leech else BotCommands.MirrorCommand[0]}"
        else:
            return

        LOGGER.info(f"Generated command: {command_text}")

        # Create a proper command message for processing
        import copy

        # Store original text for restoration
        original_text = message.text

        # Create a new message object that mimics a command message
        command_message = copy.copy(message)
        command_message.text = command_text

        # Ensure the command message has the necessary client references
        if not hasattr(command_message, "_client") or command_message._client is None:
            command_message._client = client
        if not hasattr(command_message, "client") or command_message.client is None:
            command_message.client = client

        # For Telegram files (media files), we need to set up reply_to properly
        if has_media:
            # The original message with the media becomes the reply_to_message
            command_message.reply_to_message = message
            # Also ensure the reply_to_message has client reference
            if hasattr(message, "_client") and message._client is None:
                message._client = client
            if hasattr(message, "client") and message.client is None:
                message.client = client
            # Clear all media from the command message itself
            command_message.document = None
            command_message.photo = None
            command_message.video = None
            command_message.audio = None
            command_message.voice = None
            command_message.video_note = None
            command_message.sticker = None
            command_message.animation = None
            LOGGER.info(f"Set up reply_to_message for media file processing")

        try:
            # Import Mirror class here to avoid circular imports
            from ...modules.mirror_leech import Mirror

            # Prioritize media files over URLs
            if has_media:
                # For media files, use Mirror with proper reply_to setup
                LOGGER.info(f"Using Mirror for media file")
                mirror_task = Mirror(client, command_message, False, is_leech)
                await mirror_task.new_event()
            elif has_url:
                # Only process URLs if no media file present
                urls = [
                    word
                    for word in message_text.split()
                    if is_url(word) or is_magnet(word) or is_telegram_link(word)
                ]
                if urls:
                    url = urls[0]
                    # Check if it's a YouTube/video URL that should use yt-dlp
                    video_domains = [
                        "youtube.",
                        "youtu.be",
                        "twitter.",
                        "instagram.",
                        "facebook.",
                        "vimeo.",
                        "dailymotion.",
                        "soundcloud.",
                        "tiktok.",
                    ]
                    is_video_url = any(
                        domain in url.lower() for domain in video_domains
                    )

                    if is_video_url:
                        # Import YtDlp class here for video URLs
                        from ...modules.ytdlp import YtDlp

                        LOGGER.info(f"Using YtDlp for video URL: {url}")
                        ytdlp_task = YtDlp(client, command_message, is_leech)
                        await ytdlp_task.new_event()
                    else:
                        # Use Mirror for regular URLs
                        LOGGER.info(f"Using Mirror for URL: {url}")
                        mirror_task = Mirror(client, command_message, False, is_leech)
                        await mirror_task.new_event()

        except Exception as e:
            # Log the error but don't fail silently
            LOGGER.error(f"Auto processing failed: {e}", exc_info=True)
        finally:
            # Restore original message text (if it was modified)
            if original_text is not None:
                message.text = original_text


def auto_message_filter(_, __, message: Message):
    """Custom filter for auto-processing messages"""

    # Skip if message is a command
    if message.text and message.text.startswith("/"):
        return False

    # Skip if message is from bot
    if message.from_user and message.from_user.is_bot:
        return False

    # Get user info
    user = message.from_user or message.sender_chat
    if not user:
        return False

    user_id = user.id
    user_dict = user_data.get(user_id, {})

    # Check if auto features are enabled
    auto_leech = user_dict.get("AUTO_LEECH", False)
    auto_mirror = user_dict.get("AUTO_MIRROR", False)

    if not (auto_leech or auto_mirror):
        return False

    # Check if message contains processable content
    message_text = message.text or message.caption or ""
    has_url = any(
        is_url(word) or is_magnet(word) or is_telegram_link(word)
        for word in message_text.split()
    )

    # Check for any kind of media file
    has_media = bool(
        message.document
        or message.photo
        or message.video
        or message.audio
        or message.voice
        or message.video_note
        or message.sticker
        or message.animation
    )

    result = has_url or has_media

    # Debug logging - only import if needed
    if result:
        try:
            from ... import LOGGER

            media_type = "unknown"
            if message.document:
                media_type = "document"
            elif message.photo:
                media_type = "photo"
            elif message.video:
                media_type = "video"
            elif message.audio:
                media_type = "audio"
            elif message.voice:
                media_type = "voice"
            elif message.video_note:
                media_type = "video_note"
            elif message.sticker:
                media_type = "sticker"
            elif message.animation:
                media_type = "animation"

            LOGGER.info(
                f"Auto filter triggered for user {user_id}: has_url={has_url}, has_media={has_media}, media_type={media_type}"
            )
        except Exception:
            pass  # Ignore logging errors

    return result


# Create the custom filter
auto_process_filter = filters.create(auto_message_filter)
