#!/usr/bin/env python3

from pyrogram import filters
from pyrogram.types import Message

from bot.helper.ext_utils.links_utils import is_url, is_telegram_link, is_magnet
from bot.helper.ext_utils.nsfw_detector import NSFWDetector
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot import user_data, LOGGER
from bot.core.config_manager import Config
from bot.modules.mirror_leech import mirror as mirror_f, leech
from bot.modules.ytdlp import ytdl, ytdl_leech
import copy


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
        auto_vt = user_dict.get("AUTO_VT", False)

        if not (auto_leech or auto_mirror):
            return

        # Debug logging
        LOGGER.info(
            f"Auto processing triggered for user {user_id}: auto_leech={auto_leech}, auto_mirror={auto_mirror}, auto_vt={auto_vt}"
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

        # NSFW Content Detection for Auto Processing
        if Config.NSFW_DETECTION_ENABLED:
            try:
                # Extract URL for checking
                url_to_check = ""
                if has_url:
                    urls = [
                        word
                        for word in message_text.split()
                        if is_url(word) or is_magnet(word) or is_telegram_link(word)
                    ]
                    if urls:
                        url_to_check = urls[0]

                # Extract filename for checking
                filename_to_check = ""
                if has_media:
                    media_file = (
                        message.document
                        or message.photo
                        or message.video
                        or message.audio
                        or message.voice
                        or message.video_note
                        or message.sticker
                        or message.animation
                    )
                    if (
                        media_file
                        and hasattr(media_file, "file_name")
                        and media_file.file_name
                    ):
                        filename_to_check = media_file.file_name

                # Perform NSFW check
                is_nsfw, nsfw_reason = NSFWDetector.is_nsfw_content(
                    url_to_check, filename_to_check
                )

                if is_nsfw:
                    content_category = NSFWDetector.get_content_category(
                        url_to_check, filename_to_check
                    )
                    LOGGER.warning(
                        f"Auto-processing blocked NSFW content for user {user_id}: {nsfw_reason}"
                    )
                    # Don't send error message for auto processing, just silently skip
                    return

            except Exception as e:
                LOGGER.error(f"Error in auto-processing NSFW detection: {e}")
                # Continue processing if NSFW detection fails
                pass

        # Determine which mode to use (prioritize leech over mirror if both enabled)
        is_leech = auto_leech

        LOGGER.info(
            f"Processing {'media file' if has_media else 'URL'} for user {user_id}, mode: {'leech' if is_leech else 'mirror'}, video_tools: {auto_vt}"
        )

        cmd = BotCommands.LeechCommand[0] if is_leech else BotCommands.MirrorCommand[0]

        # Prioritize media files over URLs in text
        # If message has media, always treat as media file regardless of text content
        if has_media:
            # For media files, use the command without URL
            command_text = f"/{cmd}"
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
                command_text = f"/{cmd} {link}"
            else:
                command_text = f"/{cmd}"
        else:
            return

        if auto_vt:
            command_text += " -vt"

        LOGGER.info(f"Generated command: {command_text}")

        # Create a proper command message for processing

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
            LOGGER.info("Set up reply_to_message for media file processing")

        try:
            # Prioritize media files over URLs
            if has_media:
                # For media files, use Mirror with proper reply_to setup
                LOGGER.info("Using Mirror/Leech for media file")
                if is_leech:
                    await leech(client, command_message)
                else:
                    await mirror_f(client, command_message)
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
                        LOGGER.info(f"Using YtDlp for video URL: {url}")
                        if is_leech:
                            await ytdl_leech(client, command_message)
                        else:
                            await ytdl(client, command_message)
                    else:
                        # Use Mirror for regular URLs
                        LOGGER.info(f"Using Mirror/Leech for URL: {url}")
                        if is_leech:
                            await leech(client, command_message)
                        else:
                            await mirror_f(client, command_message)

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
