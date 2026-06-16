import random
import ast
from typing import Sequence, Optional, Union

from ...core.tg_client import TgClient
from ...core.config_manager import Config
from ... import LOGGER


async def _send_sticker_target(chat_or_message: Union[int, object], sticker: str):
    """
    Internal: send a sticker by file_id or URL, handling both message and chat_id.
    """
    try:
        if isinstance(chat_or_message, int):
            return await TgClient.bot.send_sticker(
                chat_id=chat_or_message, sticker=sticker, disable_notification=True
            )
        # message-like object
        if hasattr(chat_or_message, "reply_sticker"):
            return await chat_or_message.reply_sticker(
                sticker=sticker, quote=True, disable_notification=True
            )
        # fallback to chat id
        chat_id = getattr(getattr(chat_or_message, "chat", None), "id", None)
        if chat_id is None:
            LOGGER.warning(
                "sticker_utils: could not resolve chat id; skipping sticker send"
            )
            return None
        return await TgClient.bot.send_sticker(
            chat_id=chat_id, sticker=sticker, disable_notification=True
        )
    except Exception as e:
        # Don't break the flow due to sticker issues
        LOGGER.warning(f"sticker_utils: failed to send sticker: {e}")
        return None


def _normalize_pool(pool: Optional[Union[Sequence[str], str]]) -> Sequence[str]:
    """Normalize various pool formats into a list of sticker strings.
    Accepts:
    - list/tuple of strings
    - a single string (file_id)
    - a JSON-like list string: "[\"id1\", \"id2\"]"
    - a comma-separated string: "id1,id2"
    - a whitespace-separated string: "id1 id2"
    """
    if not pool:
        return []
    # If already a list/tuple of strings
    if isinstance(pool, (list, tuple)):
        return [s for s in pool if isinstance(s, str) and s.strip()]
    if isinstance(pool, str):
        s = pool.strip()
        if not s:
            return []
        # Try JSON/py literal list first
        if (s.startswith("[") and s.endswith("]")) or (
            s.startswith("(") and s.endswith(")")
        ):
            try:
                parsed = ast.literal_eval(s)
                if isinstance(parsed, (list, tuple)):
                    return [str(x).strip() for x in parsed if str(x).strip()]
            except Exception:
                pass
        # Try comma-separated
        if "," in s:
            return [part.strip() for part in s.split(",") if part.strip()]
        # Try whitespace-separated (but don't split a lone file_id)
        parts = s.split()
        if len(parts) > 1:
            return [p for p in parts if p]
        # Single token -> single file_id
        return [s]
    # Unknown type -> nothing
    return []


async def send_random_sticker(
    chat_or_message: Union[int, object], pool: Optional[Union[Sequence[str], str]]
):
    """
    Send a random sticker from the provided pool (list/tuple of file_ids or URLs).
    If pool is empty or None, does nothing.
    """
    pool_list = _normalize_pool(pool)
    if not pool_list:
        return None
    try:
        sticker = random.choice(list(pool_list))
    except Exception:
        return None
    return await _send_sticker_target(chat_or_message, sticker)


async def send_start_sticker(chat_or_message: Union[int, object]):
    """Send a random start sticker if configured"""
    stickers = getattr(Config, "START_STICKERS", [])
    sticker_message = await send_random_sticker(chat_or_message, stickers)
    if sticker_message:
        await auto_delete_sticker(sticker_message)
    return sticker_message


async def send_error_sticker(chat_or_message: Union[int, object]):
    """Send a random error sticker if configured"""
    stickers = getattr(Config, "ERROR_STICKERS", [])
    sticker_message = await send_random_sticker(chat_or_message, stickers)
    if sticker_message:
        await auto_delete_sticker(sticker_message)
    return sticker_message


async def send_success_sticker(chat_or_message: Union[int, object]):
    """Send a random success sticker if configured"""
    stickers = getattr(Config, "SUCCESS_STICKERS", [])
    sticker_message = await send_random_sticker(chat_or_message, stickers)
    if sticker_message:
        await auto_delete_sticker(sticker_message)
    return sticker_message


async def send_mediainfo_sticker(chat_or_message: Union[int, object]):
    """Send a sticker for MediaInfo operations"""
    # Use start stickers for MediaInfo since it's a neutral operation
    return await send_start_sticker(chat_or_message)


async def auto_delete_sticker(sticker_message, delete_time=None):
    """Auto-delete sticker after specified time if AUTO_DELETE_STICKERS is enabled"""
    if not sticker_message or not getattr(Config, "AUTO_DELETE_STICKERS", False):
        return

    from asyncio import sleep, create_task

    delete_time = delete_time or getattr(Config, "STICKER_DELETE_TIME", 60)

    async def delete_after_time():
        try:
            await sleep(delete_time)
            await sticker_message.delete()
            LOGGER.info(f"Auto-deleted sticker after {delete_time} seconds")
        except Exception as e:
            LOGGER.warning(f"Failed to auto-delete sticker: {e}")

    create_task(delete_after_time())
