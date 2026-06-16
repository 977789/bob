from asyncio import sleep
from typing import Dict, Union

from pyrogram import utils, raw, Client
from pyrogram.errors import AuthBytesInvalid
from pyrogram.file_id import FileId, FileType, ThumbnailSource
from pyrogram.session import Session, Auth

from ... import bot_loop, LOGGER
from ...core.tg_client import TgClient
from ..ext_utils.exceptions import FIleNotFound
from .file_properties import get_file_ids


class ByteStreamer:
    def __init__(self, client: Client):
        self._client = client
        self._cached_file_ids: Dict[int, FileId] = {}
        bot_loop.create_task(self._clean_cache())

    async def get_file_properties(self, chat_id: int, message_id: int) -> FileId:
        chache_id = f"{chat_id}-{message_id}"
        if chache_id not in self._cached_file_ids:
            file_id = await get_file_ids(chat_id, message_id, self._client)
            if not file_id:
                LOGGER.info("Message with ID %s not found!", message_id)
                raise FIleNotFound
            self._cached_file_ids[chache_id] = file_id
        return self._cached_file_ids[chache_id]

    async def yield_file(
        self,
        file_id: FileId,
        offset: int,
        first_part_cut: int,
        last_part_cut: int,
        part_count: int,
        chunk_size: int,
    ):
        current_part = 1
        location = await self._get_location(file_id)
        try:
            media_session = await self._generate_media_session(file_id)
            r = await media_session.invoke(
                raw.functions.upload.GetFile(
                    location=location, offset=offset, limit=chunk_size
                )
            )
            if isinstance(r, raw.types.upload.File):
                while current_part <= part_count:
                    chunk = r.bytes
                    if not chunk:
                        break
                    offset += chunk_size
                    if part_count == 1:
                        yield chunk[first_part_cut:last_part_cut]
                        break
                    if current_part == 1:
                        yield chunk[first_part_cut:]
                    if 1 < current_part <= part_count:
                        yield chunk
                    r = await media_session.invoke(
                        raw.functions.upload.GetFile(
                            location=location, offset=offset, limit=chunk_size
                        )
                    )
                    current_part += 1
        except (TimeoutError, AttributeError) as e:
            LOGGER.error(f"Timeout or AttributeError in yield_file: {e}")
        except Exception as e:
            LOGGER.error(f"Error in yield_file: {e}", exc_info=True)

    async def _generate_media_session(self, file_id: FileId) -> Session:
        media_session = self._client.media_sessions.get(file_id.dc_id, None)
        if media_session is None:
            if file_id.dc_id != await self._client.storage.dc_id():
                media_session = Session(
                    self._client,
                    file_id.dc_id,
                    await Auth(
                        self._client,
                        file_id.dc_id,
                        await self._client.storage.test_mode(),
                    ).create(),
                    await self._client.storage.test_mode(),
                    is_media=True,
                )
                await media_session.start()
                for _ in range(6):
                    exported_auth = await self._client.invoke(
                        raw.functions.auth.ExportAuthorization(dc_id=file_id.dc_id)
                    )
                    try:
                        await media_session.invoke(
                            raw.functions.auth.ImportAuthorization(
                                id=exported_auth.id, bytes=exported_auth.bytes
                            )
                        )
                        break
                    except AuthBytesInvalid:
                        if file_id.chat_id:
                            LOGGER.info(
                                "Invalid authorization bytes for DC %s", file_id.chat_id
                            )
                        continue
                else:
                    await media_session.stop()
                    raise AuthBytesInvalid
            else:
                media_session = Session(
                    self._client,
                    file_id.dc_id,
                    await self._client.storage.auth_key(),
                    await self._client.storage.test_mode(),
                    is_media=True,
                )
                await media_session.start()
            self._client.media_sessions[file_id.dc_id] = media_session
        return media_session

    @staticmethod
    async def _get_location(
        file_id: FileId,
    ) -> Union[
        raw.types.InputPhotoFileLocation,
        raw.types.InputDocumentFileLocation,
        raw.types.InputPeerPhotoFileLocation,
    ]:
        match file_id.file_type:
            case FileType.CHAT_PHOTO:
                if file_id.chat_id > 0:
                    peer = raw.types.InputPeerUser(
                        user_id=file_id.chat_id, access_hash=file_id.chat_access_hash
                    )
                elif file_id.chat_access_hash == 0:
                    peer = raw.types.InputPeerChat(chat_id=-file_id.chat_id)
                else:
                    peer = raw.types.InputPeerChannel(
                        channel_id=utils.get_channel_id(file_id.chat_id),
                        access_hash=file_id.chat_access_hash,
                    )
                return raw.types.InputPeerPhotoFileLocation(
                    peer=peer,
                    volume_id=file_id.volume_id,
                    local_id=file_id.local_id,
                    big=file_id.thumbnail_source == ThumbnailSource.CHAT_PHOTO_BIG,
                )
            case FileType.PHOTO:
                return raw.types.InputPhotoFileLocation(
                    id=file_id.media_id,
                    access_hash=file_id.access_hash,
                    file_reference=file_id.file_reference,
                    thumb_size=file_id.thumbnail_size,
                )
            case _:
                return raw.types.InputDocumentFileLocation(
                    id=file_id.media_id,
                    access_hash=file_id.access_hash,
                    file_reference=file_id.file_reference,
                    thumb_size=file_id.thumbnail_size,
                )

    async def _clean_cache(self):
        while True:
            await sleep(30 * 60)
            self._cached_file_ids.clear()
