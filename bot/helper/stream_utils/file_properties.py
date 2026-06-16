from base64 import b64encode, b64decode
from html import escape
from typing import Optional
from urllib.parse import quote_plus

from pyrogram import Client
from pyrogram.file_id import FileId

from ... import LOGGER, user_data
from ...core.config_manager import Config
from ...core.tg_client import TgClient
from ..ext_utils.exceptions import FIleNotFound
from ..ext_utils.links_utils import is_media


def get_hash_chat_id(url_path: str):
    media_hash, chat_id, message_id = b64decode(url_path).decode("utf-8").split("/")
    return media_hash, int(chat_id), int(message_id)


async def get_file_ids(
    chat_id: int, message_id: int, client: Client | None = None
) -> Optional[FileId]:
    if client is None:
        # This logic is for the bot process context
        if TgClient.stream_bots:
            client = next(iter(TgClient.stream_bots.values()))
        else:
            client = TgClient.user or TgClient.bot
        # Poll for a short time in case clients are starting up
        if client is None:
            from asyncio import sleep

            for _ in range(10):
                if TgClient.stream_bots:
                    client = next(iter(TgClient.stream_bots.values()))
                else:
                    client = TgClient.user or TgClient.bot
                if client is not None:
                    break
                await sleep(0.5)

    if client is None:
        LOGGER.error("Stream get_file_ids: No Telegram client could be found.")
        raise FIleNotFound
    message = await client.get_messages(chat_id, message_id)
    if message.empty:
        raise FIleNotFound
    file_id = file_unique_id = None
    if media := is_media(message):
        file_id, file_unique_id = FileId.decode(media.file_id), media.file_unique_id
    setattr(file_id, "file_size", getattr(media, "file_size", 0))
    setattr(file_id, "mime_type", getattr(media, "mime_type", ""))
    setattr(file_id, "file_name", getattr(media, "file_name", ""))
    setattr(file_id, "unique_id", file_unique_id)
    return file_id


def gen_link(message):
    user_id = message.from_user.id if message.from_user else None
    user_dict = user_data.get(user_id, {}) if user_id else {}
    if "ENABLE_STREAM_LINK" in user_dict:
        raw_enable_stream = user_dict["ENABLE_STREAM_LINK"]
    else:
        raw_enable_stream = Config.ENABLE_STREAM_LINK

    # Normalize to boolean
    enable_stream = str(raw_enable_stream).lower() in ("true", "1", "yes")

    LOGGER.info(
        f"gen_link: user_id={user_id}, raw_setting={raw_enable_stream}, resolved_to={enable_stream}"
    )
    if not enable_stream:
        LOGGER.info(f"Stream links disabled for user {user_id}")
        return None, None
    stream_link = dl_link = None
    if enable_stream and Config.STREAM_PORT and (base_url := Config.STREAM_BASE_URL):
        media = is_media(message)
        if not media:
            LOGGER.debug(f"No media found in message {message.id} for user {user_id}")
            return None, None
        file_unique_id = getattr(media, "file_unique_id", "")
        name, media_hash = getattr(media, "file_name", ""), file_unique_id[:6]
        name = quote_plus(escape(name or file_unique_id))
        try:
            media_hash = b64encode(
                f"{media_hash}/{message.chat.id}/{message.id}".encode()
            ).decode("utf-8")
        except Exception as e:
            LOGGER.error("Error generating link hash: %s", e)
            return stream_link, dl_link
        if getattr(media, "mime_type", "None/unknown").startswith("video"):
            stream_link = f"{base_url}watch/{media_hash}"
        dl_link = f"{base_url}dl/{name}?id={media_hash}"
        LOGGER.info(
            f"Generated links for user {user_id}: stream={stream_link}, dl={dl_link}"
        )
    else:
        LOGGER.debug(
            f"Stream link generation skipped: Missing config (ENABLE_STREAM_LINK={Config.ENABLE_STREAM_LINK}, STREAM_PORT={Config.STREAM_PORT}, STREAM_BASE_URL={base_url})"
        )
    return stream_link, dl_link
