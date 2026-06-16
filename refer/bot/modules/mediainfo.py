from os import getcwd, path as ospath
from re import search
from shlex import split
import asyncio
from time import time

from aiofiles import open as aiopen
from aiofiles.os import mkdir, path as aiopath, remove as aioremove
from aiohttp import ClientSession

from .. import LOGGER
from ..core.tg_client import TgClient

# Global cache for telegraph links to prevent duplicate generation
_telegraph_cache = {}
from ..helper.ext_utils.bot_utils import cmd_exec
from ..helper.ext_utils.telegraph_helper import telegraph
from ..helper.telegram_helper.bot_commands import BotCommands
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.message_utils import send_message, edit_message

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
        tc = f"<h4>📌 {ospath.basename(des_path)}</h4><br><br>"
        if len(stdout) != 0:
            tc += parseinfo(stdout, file_size)

        link_id = (await telegraph.create_page(title="MediaInfo X", content=tc))["path"]

        # Create button with MediaInfo link
        buttons = ButtonMaker()
        buttons.url_button("📄 View MediaInfo", f"https://graph.org/{link_id}")
        button_markup = buttons.build_menu(1)

        # Create message text
        media_name = ospath.basename(des_path)
        message_text = f"<b>📊 MediaInfo Generated Successfully!</b>\n\n» <b>File:</b> <code>{media_name}</code>\n» <b>Click the button below to view detailed MediaInfo</b>"

        try:
            # Delete the temp message and send new one with photo and button
            await temp_send.delete()
            return await send_message(
                message,
                message_text,
                buttons=button_markup,
                photo="assets/BHARTIYEE LEECH.png",
            )
        except Exception as send_error:
            # Fallback to edit_message function which has proper exception handling
            await edit_message(temp_send, message_text, button_markup)
    except Exception as e:
        LOGGER.error(e)
        await edit_message(temp_send, f"MediaInfo Stopped due to {str(e)}")
    finally:
        if await aiopath.exists(des_path):
            await aioremove(des_path)


section_dict = {"General": "🗒", "Video": "🎞", "Audio": "🔊", "Text": "🔠", "Menu": "🗃"}


def parseinfo(out, size):
    tc, trigger = "", False
    size_line = (
        f"File size                                 : {size / (1024 * 1024):.2f} MiB"
    )
    for line in out.split("\n"):
        for section, emoji in section_dict.items():
            if line.startswith(section):
                trigger = True
                if not line.startswith("General"):
                    tc += "</pre><br>"
                tc += f"<h4>{emoji} {line.replace('Text', 'Subtitle')}</h4>"
                break
        if line.startswith("File size"):
            line = size_line
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


async def get_mediainfo_telegraph_link(media, mmsg=None):
    """Generate MediaInfo for a Telegram media object and return the Telegraph link only."""
    try:
        # Cleanup cache if needed
        await _cleanup_cache_if_needed()

        # Create a unique cache key based on file unique_id and size
        cache_key = f"{media.file_unique_id}_{media.file_size}"

        # Check if we already have a cached link for this file
        if cache_key in _telegraph_cache:
            LOGGER.info(f"Using cached telegraph link for {media.file_name}")
            return _telegraph_cache[cache_key]

        LOGGER.info(f"Generating new telegraph link for {media.file_name}")

        # Add 3 second delay to avoid Telegraph API rate limiting
        await asyncio.sleep(3)

        path = "mediainfo/"
        from aiofiles.os import mkdir, path as aiopath, remove as aioremove
        from ..helper.ext_utils.bot_utils import cmd_exec
        from ..helper.ext_utils.telegraph_helper import telegraph
        import os

        if not await aiopath.isdir(path):
            await mkdir(path)
        file_size = media.file_size if hasattr(media, "file_size") else 0
        des_path = os.path.join(path, media.file_name)
        if file_size <= 50000000:
            await mmsg.download(os.path.join(getcwd(), des_path))
        else:
            from ..core.tg_client import TgClient

            async for chunk in TgClient.bot.stream_media(media, limit=5):
                async with aiopen(des_path, "ab") as f:
                    await f.write(chunk)
        from shlex import split

        stdout, _, _ = await cmd_exec(split(f'mediainfo "{des_path}"'))
        tc = f"<h4>📌 {ospath.basename(des_path)}</h4><br><br>"
        if len(stdout) != 0:
            tc += parseinfo(stdout, file_size)
        link_id = (await telegraph.create_page(title="MediaInfo X", content=tc))["path"]
        await aioremove(des_path)

        # Cache the generated link
        telegraph_link = f"https://graph.org/{link_id}"
        _telegraph_cache[cache_key] = telegraph_link
        LOGGER.info(
            f"Generated and cached telegraph link for {media.file_name}: {telegraph_link}"
        )

        return telegraph_link
    except Exception as e:
        LOGGER.error(f"get_mediainfo_telegraph_link error: {e}")
        return None


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
