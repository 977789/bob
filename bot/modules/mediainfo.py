from os import getcwd, path as ospath
from re import search
from shlex import split
from pyrogram.errors import FileReferenceExpired
import asyncio
from time import time

from aiofiles import open as aiopen
from aiofiles.os import mkdir, path as aiopath, remove as aioremove
from aiohttp import ClientSession

from .. import LOGGER
from ..core.tg_client import TgClient
from ..core.config_manager import Config
from ..helper.ext_utils.bot_utils import cmd_exec
from ..helper.ext_utils.telegraph_helper import telegraph
from telegraph.exceptions import TelegraphException
from ..helper.telegram_helper.bot_commands import BotCommands
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.message_utils import send_message, edit_message
from ..helper.telegram_helper.sticker_utils import send_mediainfo_sticker

# Global cache for telegraph links to prevent duplicate generation
_telegraph_cache = {}

# Cache cleanup settings
_cache_max_size = 1000  # Maximum number of cached links
_cache_cleanup_interval = 3600  # Cleanup every hour (in seconds)
_last_cleanup = time()


async def _cleanup_cache_if_needed():
    """Clean up cache if it's too large or too old"""
    global _last_cleanup
    current_time = time()

    # Check if cleanup is needed
    if (
        len(_telegraph_cache) > _cache_max_size
        or current_time - _last_cleanup > _cache_cleanup_interval
    ):
        # Keep only the most recent half of the cache
        if len(_telegraph_cache) > _cache_max_size // 2:
            # Convert to list and keep only recent entries
            cache_items = list(_telegraph_cache.items())
            _telegraph_cache.clear()
            # Keep the last half
            for key, value in cache_items[-(_cache_max_size // 2) :]:
                _telegraph_cache[key] = value

            LOGGER.info(f"Telegraph cache cleaned up. Size: {len(_telegraph_cache)}")

        _last_cleanup = current_time


async def gen_mediainfo(message, link=None, media=None, mmsg=None):
    temp_send = await send_message(message, "<i>Generating MediaInfo...</i>")
    try:
        # Cleanup cache if needed
        await _cleanup_cache_if_needed()

        path = "mediainfo/"
        if not await aiopath.isdir(path):
            await mkdir(path)
        file_size = 0
        if link:
            filename = search(".+/(.+)", link).group(1)
            des_path = ospath.join(path, filename)
            headers = {
                "user-agent": "Mozilla/5.0 (Linux; Android 12; 2201116PI) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Mobile Safari/537.36"
            }
            async with ClientSession() as session:
                async with session.get(link, headers=headers) as response:
                    file_size = int(response.headers.get("Content-Length", 0))
                    async with aiopen(des_path, "wb") as f:
                        async for chunk in response.content.iter_chunked(10000000):
                            await f.write(chunk)
                            break
        elif media:
            des_path = ospath.join(path, media.file_name)
            file_size = media.file_size
            if file_size <= 50000000:
                await mmsg.download(ospath.join(getcwd(), des_path))
            else:
                async for chunk in TgClient.bot.stream_media(media, limit=5):
                    async with aiopen(des_path, "ab") as f:
                        await f.write(chunk)

        stdout, _, _ = await cmd_exec(split(f'mediainfo "{des_path}"'))

        # Revert: header uses basename from des_path
        header_name = ospath.basename(des_path)
        tc = f"<h4>📌 {header_name}</h4><br><br>"
        if len(stdout) != 0:
            tc += parseinfo(stdout, file_size)

        async def _create_telegraph_with_fallback(
            title: str, content: str, file_display_name: str = ""
        ) -> str:
            try:
                return (await telegraph.create_page(title=title, content=content))[
                    "path"
                ]
            except TelegraphException as te:
                if "CONTENT_TOO_BIG" not in str(te):
                    raise
                # Split content into multiple parts and create an index page
                max_chunk = 30000
                parts = [
                    content[i : i + max_chunk]
                    for i in range(0, len(content), max_chunk)
                ]
                part_links = []
                short_name = (file_display_name or "MediaInfo").strip()[:60]
                total = len(parts)
                was_in_pre = False
                for idx, part in enumerate(parts, start=1):
                    ptitle = f"{title} - {short_name} (Part {idx}/{total})"
                    if was_in_pre:
                        part = "<pre>" + part
                    if part.count("<pre>") > part.count("</pre>"):
                        part += "</pre>"
                        was_in_pre = True
                    else:
                        was_in_pre = False
                    pid = (await telegraph.create_page(title=ptitle, content=part))[
                        "path"
                    ]
                    part_links.append(f"https://graph.org/{pid}")
                # Build index page linking to all parts
                links_html = "<br>".join(
                    [
                        f'<a href="{lnk}">Part {i + 1}/{total}</a>'
                        for i, lnk in enumerate(part_links)
                    ]
                )
                index_html = (
                    f"<h4>📌 {short_name}</h4><br><b>MediaInfo (split into {total} parts)</b><br><br>"
                    + links_html
                )
                try:
                    return (
                        await telegraph.create_page(title=title, content=index_html)
                    )["path"]
                except TelegraphException:
                    # Fallback to first part if index still too big
                    return part_links[0].split("/")[-1]

        link_id = await _create_telegraph_with_fallback(
            title="MediaInfo X", content=tc, file_display_name=ospath.basename(des_path)
        )

        # Create button with MediaInfo link
        buttons = ButtonMaker()
        buttons.url_button("📄 View MediaInfo", f"https://graph.org/{link_id}")
        button_markup = buttons.build_menu(1)

        # Create message text
        media_name = ospath.basename(des_path)
        message_text = f"<b>📊 MediaInfo Generated Successfully!</b>\n\n» <b>File:</b> <code>{media_name}</code>\n» <b>Click the button below to view detailed MediaInfo</b>"

        # Get MediaInfo image from config
        mediainfo_image = getattr(Config, "IMAGE_MEDINFO", None)
        if isinstance(mediainfo_image, str) and mediainfo_image.strip():
            # If it's a space-separated list, pick the first one
            if " " in mediainfo_image:
                mediainfo_image = mediainfo_image.split()[0]
        else:
            mediainfo_image = None

        try:
            # Delete the temp message and send new one with photo and button
            await temp_send.delete()
            sent_message = await send_message(
                message,
                message_text,
                buttons=button_markup,
                photo=mediainfo_image,
            )
            # Send sticker if configured
            await send_mediainfo_sticker(message)
            return sent_message
        except Exception as send_error:
            LOGGER.error(f"Error sending MediaInfo with photo: {send_error}")
            # Fallback to edit_message function which has proper exception handling
            await edit_message(temp_send, message_text, button_markup)
            await send_mediainfo_sticker(message)

    except Exception as e:
        LOGGER.error(e)
        await edit_message(temp_send, f"MediaInfo Stopped due to {str(e)}")
    finally:
        if await aiopath.exists(des_path):
            await aioremove(des_path)


section_dict = {
    "General": "📋",
    "Video": "🎬",
    "Audio": "🔊",
    "Text": "📝",
    "Menu": "📑",
}


def parseinfo(out, size, complete_name_override=None):
    """Enhanced MediaInfo parser with encoding function display and better formatting"""
    tc, trigger = "", False

    # Target column position for colons (MediaInfo standard alignment)
    target_colon_pos = 42

    # Enhanced section dictionary with better emojis
    section_mapping = {
        "General": "📋",
        "Video": "🎬",
        "Audio": "🔊",
        "Text": "📝",
        "Menu": "📑",
    }

    # Track encoding information for display
    encoding_info = {}

    for line in out.split("\n"):
        # Enhanced section detection
        for section, emoji in section_mapping.items():
            if line.startswith(section):
                trigger = True
                if not line.startswith("General"):
                    tc += "</pre><br>"

                # Use improved emoji and formatting
                section_name = line.replace("Text", "Subtitle")
                tc += f"<h4>{emoji} {section_name}</h4>"
                break

        # Fix spacing alignment for all MediaInfo fields
        if ":" in line and not line.strip().startswith("General"):
            colon_pos = line.find(":")
            if colon_pos > 0:
                # Extract the field name (without trailing spaces)
                field_name = line[:colon_pos].rstrip()
                # Extract the value part
                value_part = line[colon_pos + 1 :].lstrip()

                # Handle special cases for File size and Complete name override
                if field_name == "File size":
                    value_part = f"{size / (1024 * 1024):.2f} MiB"
                # Do not override Complete name here; keep exact path

                # Calculate required spacing for consistent alignment
                spaces_needed = target_colon_pos - len(field_name)
                if spaces_needed < 1:
                    spaces_needed = 1  # At least one space

                # Reconstruct the line with proper spacing
                line = field_name + " " * spaces_needed + ": " + value_part

        # Capture encoding information for summary
        if "Codec" in line and ":" in line:
            parts = line.split(":", 1)
            if len(parts) == 2:
                codec_type = parts[0].strip()
                codec_value = parts[1].strip()
                encoding_info[codec_type] = codec_value

        if trigger:
            tc += "<br><pre>"
            trigger = False
        else:
            tc += line + "\n"

    tc += "</pre><br>"

    return tc


async def mediainfo(_, message):
    rply = message.reply_to_message
    help_msg = f"""
<b>By replying to media:</b>
<code>/{BotCommands.MediaInfoCommand[0]} or /{BotCommands.MediaInfoCommand[1]} [media]</code>

<b>By reply/sending download link:</b>
<code>/{BotCommands.MediaInfoCommand[0]} or /{BotCommands.MediaInfoCommand[1]} [link]</code>
"""
    if len(message.command) > 1 or rply and rply.text:
        link = rply.text if rply else message.command[1]
        return await gen_mediainfo(message, link)
    elif rply:
        if file := next(
            (
                i
                for i in [
                    rply.document,
                    rply.video,
                    rply.audio,
                    rply.voice,
                    rply.animation,
                    rply.video_note,
                ]
                if i is not None
            ),
            None,
        ):
            return await gen_mediainfo(message, None, file, rply)
        else:
            return await send_message(message, help_msg)
    else:
        return await send_message(message, help_msg)


async def get_mediainfo_telegraph_link(
    media, mmsg=None, client=None, display_filename=None
):
    """Generate MediaInfo for a Telegram media object and return the Telegraph link only."""
    des_path = ""
    try:
        # Cleanup cache if needed
        await _cleanup_cache_if_needed()

        # Create a unique cache key based on file unique_id and size
        cache_key = f"{getattr(media, 'file_unique_id', 'unknown')}_{getattr(media, 'file_size', 0)}"

        # Check if we already have a cached link for this file
        if cache_key in _telegraph_cache:
            LOGGER.info(
                f"Using cached telegraph link for {getattr(media, 'file_name', 'unknown')}"
            )
            return _telegraph_cache[cache_key]

        LOGGER.info(
            f"Generating new telegraph link for {getattr(media, 'file_name', 'unknown')}"
        )

        # Add 3 second delay to avoid Telegraph API rate limiting
        await asyncio.sleep(3)

        file_name = getattr(media, "file_name", "N/A")
        file_id = getattr(media, "file_id", "N/A")
        mmsg_id = mmsg.id if mmsg else "N/A"
        LOGGER.debug(
            f"Generating mediainfo for file: {file_name} (ID: {file_id}), mmsg_id: {mmsg_id}"
        )
        path = "mediainfo/"

        if not await aiopath.isdir(path):
            await mkdir(path)

        # Revert: always use Telegram media.file_name for temp path
        file_name_for_path = getattr(media, "file_name", "unknown_media_file")
        des_path = ospath.join(path, file_name_for_path)

        file_size = getattr(media, "file_size", 0)
        LOGGER.debug(f"Destination path: {des_path}, File size: {file_size}")

        downloaded_size = 0
        actual_client_for_download = client if client else TgClient.bot

        # Attempt to re-fetch the message to get a fresh file reference
        if mmsg:  # mmsg is the original message object
            try:
                LOGGER.debug(
                    f"Attempting to re-fetch message {mmsg.id} from chat {mmsg.chat.id} for fresh file reference."
                )
                fresh_mmsg = await actual_client_for_download.get_messages(
                    chat_id=mmsg.chat.id, message_ids=mmsg.id
                )
                if fresh_mmsg and hasattr(fresh_mmsg, "media") and fresh_mmsg.media:
                    mmsg = fresh_mmsg  # This is the new, potentially fresh message
                    media = getattr(
                        mmsg, mmsg.media.value
                    )  # Update media object from fresh message
                    file_size = getattr(
                        media, "file_size", 0
                    )  # Update file_size from fresh media
                elif not fresh_mmsg:
                    LOGGER.warning(
                        f"Re-fetching message {mmsg.id} returned None or empty. Message might be deleted."
                    )
                    # Proceed with original mmsg/media, but it might fail
                else:  # fresh_mmsg exists but has no media
                    LOGGER.warning(f"Re-fetched message {mmsg.id} no longer has media.")
                    # Proceed with original mmsg/media or error out
                    return None  # Safer to error out if media disappeared
            except Exception as e_refetch:
                LOGGER.error(
                    f"Error re-fetching message {mmsg.id} for MediaInfo: {e_refetch}. Using original message details."
                )

        if (
            not media
        ):  # If media became None after re-fetch attempt or was None initially
            LOGGER.error("No valid media object to download for MediaInfo.")
            if await aiopath.exists(des_path):
                await aioremove(des_path)  # Clean up if temp file was created
            return None

        # Download logic
        if (
            file_size <= 50000000 and mmsg and hasattr(mmsg, "download")
        ):  # Ensure mmsg is a Message object
            LOGGER.debug("Attempting full download for MediaInfo via mmsg.download()")
            try:
                await mmsg.download(ospath.join(getcwd(), des_path))
            except (
                FileReferenceExpired
            ) as fre_download:  # Catch FREF here specifically for download
                LOGGER.warning(
                    f"File reference expired during mmsg.download() for {file_name}: {fre_download}. This might happen if re-fetch failed or was insufficient."
                )
                if await aiopath.exists(des_path):
                    await aioremove(des_path)
                return None  # Explicitly return None on FREF during download
            if await aiopath.exists(des_path):
                downloaded_size = await aiopath.getsize(des_path)
        elif (
            actual_client_for_download
        ):  # Use stream_media for larger files or if mmsg.download is not viable
            LOGGER.debug(
                f"Attempting stream_media for MediaInfo via {type(actual_client_for_download).__name__}"
            )
            limit_bytes = 5 * 1024 * 1024  # 5MB
            current_bytes = 0
            try:
                async with aiopen(des_path, "wb") as f:
                    async for chunk in actual_client_for_download.stream_media(media):
                        await f.write(chunk)
                        current_bytes += len(chunk)
                        if current_bytes >= limit_bytes:
                            break
            except (
                FileReferenceExpired
            ) as fre_stream:  # Catch FREF here specifically for stream
                LOGGER.warning(
                    f"File reference expired during stream_media() for {file_name}: {fre_stream}. This might happen if re-fetch failed or was insufficient."
                )
                if await aiopath.exists(des_path):
                    await aioremove(des_path)
                return None  # Explicitly return None on FREF during stream
            if await aiopath.exists(des_path):
                downloaded_size = await aiopath.getsize(des_path)
        else:
            LOGGER.error(
                "No client available for media download (mmsg.download or stream_media)."
            )
            if await aiopath.exists(des_path):
                await aioremove(des_path)
            return None

        LOGGER.debug(
            f"Download for MediaInfo completed. Downloaded size: {downloaded_size}"
        )

        if not await aiopath.exists(des_path) or downloaded_size == 0:
            LOGGER.error(
                f"Temporary file {des_path} not created or is empty. Cannot generate MediaInfo."
            )
            return None

        mediainfo_cmd = f'mediainfo "{des_path}"'
        LOGGER.debug(f"Executing mediainfo command: {mediainfo_cmd}")
        stdout, stderr, return_code = await cmd_exec(split(mediainfo_cmd))

        if stdout:
            LOGGER.debug(f"mediainfo stdout: {stdout.strip()}")
        if stderr:
            LOGGER.debug(f"mediainfo stderr: {stderr.strip()}")
        LOGGER.debug(f"mediainfo return code: {return_code}")

        # Use display filename if provided (preserves spaces), otherwise fall back to basename
        telegraph_title_filename = display_filename or ospath.basename(des_path)
        header_name = telegraph_title_filename
        tc = f"<h4>📌 {header_name}</h4><br><br>"
        if stdout:  # Check if stdout is not empty (it's a string from cmd_exec)
            tc += parseinfo(stdout, file_size)

        telegraph_title = "MediaInfo X"
        LOGGER.debug(
            f"Creating telegraph page with title: {telegraph_title} and content length: {len(tc)}"
        )

        async def _create_telegraph_with_fallback(
            title: str, content: str, file_display_name: str = ""
        ) -> str:
            try:
                return (await telegraph.create_page(title=title, content=content))[
                    "path"
                ]
            except TelegraphException as te:
                if "CONTENT_TOO_BIG" not in str(te):
                    raise
                max_chunk = 30000
                parts = [
                    content[i : i + max_chunk]
                    for i in range(0, len(content), max_chunk)
                ]
                part_links = []
                short_name = (file_display_name or "MediaInfo").strip()[:60]
                total = len(parts)
                was_in_pre = False
                for idx, part in enumerate(parts, start=1):
                    ptitle = f"{title} - {short_name} (Part {idx}/{total})"
                    if was_in_pre:
                        part = "<pre>" + part
                    if part.count("<pre>") > part.count("</pre>"):
                        part += "</pre>"
                        was_in_pre = True
                    else:
                        was_in_pre = False
                    pid = (await telegraph.create_page(title=ptitle, content=part))[
                        "path"
                    ]
                    part_links.append(f"https://graph.org/{pid}")
                links_html = "<br>".join(
                    [
                        f'<a href="{lnk}">Part {i + 1}/{total}</a>'
                        for i, lnk in enumerate(part_links)
                    ]
                )
                index_html = (
                    f"<h4>📌 {short_name}</h4><br><b>MediaInfo (split into {total} parts)</b><br><br>"
                    + links_html
                )
                try:
                    return (
                        await telegraph.create_page(title=title, content=index_html)
                    )["path"]
                except TelegraphException:
                    return part_links[0].split("/")[-1]

        link_id = await _create_telegraph_with_fallback(
            telegraph_title, tc, telegraph_title_filename
        )

        graph_link = f"https://graph.org/{link_id}"

        # Cache the generated link
        _telegraph_cache[cache_key] = graph_link
        LOGGER.info(
            f"Generated and cached telegraph link for {file_name}: {graph_link}"
        )

        return graph_link

    except FileReferenceExpired as fre:
        LOGGER.warning(
            f"File reference expired for {getattr(media, 'file_name', 'Unknown File')}. Cannot generate MediaInfo. Error: {fre}"
        )
        return None
    except Exception as e:
        LOGGER.error(
            f"get_mediainfo_telegraph_link error for {getattr(media, 'file_name', 'Unknown File')}: {e}",
            exc_info=True,
        )
        return None
    finally:
        if des_path and await aiopath.exists(des_path):
            try:
                await aioremove(des_path)
            except Exception as e_remove:
                LOGGER.error(
                    f"Error removing temp mediainfo file {des_path}: {e_remove}"
                )


def clear_telegraph_cache():
    """Clear the telegraph cache"""
    global _telegraph_cache
    _telegraph_cache.clear()
    LOGGER.info("Telegraph cache cleared")


def get_cache_size():
    """Get the current size of the telegraph cache"""
    return len(_telegraph_cache)


def get_cached_link(file_unique_id, file_size):
    """Get a cached telegraph link for a file"""
    cache_key = f"{file_unique_id}_{file_size}"
    return _telegraph_cache.get(cache_key)
