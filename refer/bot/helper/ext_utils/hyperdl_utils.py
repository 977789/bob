from asyncio import (
    CancelledError,
    create_task,
    gather,
    sleep,
    wait_for,
    TimeoutError as AsyncTimeoutError,
    Event,
)
from datetime import datetime
from math import ceil, floor
from mimetypes import guess_extension
from os import path as ospath
from pathlib import Path
from re import sub
from sys import argv
from time import time

from aiofiles import open as aiopen
from aiofiles.os import makedirs, remove
from aioshutil import move
from pyrogram import StopTransmission, raw, utils
from pyrogram.errors import AuthBytesInvalid, FloodWait
from pyrogram.file_id import PHOTO_TYPES, FileId, FileType, ThumbnailSource
from pyrogram.session import Auth, Session
from pyrogram.session.internals import MsgId

from ... import LOGGER
from ...core.config_manager import Config
from ...core.tg_client import TgClient


class HyperTGDownload:
    def __init__(self):
        # Check if HyperDL is available before initialization
        if not self.is_available():
            status_info = self.get_status_info()
            LOGGER.warning(f"HyperDL not available: {status_info['reason']}")
            raise ValueError(f"HyperDL unavailable: {status_info['reason']}")

        self.clients = TgClient.helper_bots
        self.work_loads = TgClient.helper_loads
        self.message = None
        self.dump_chat = None
        self.download_dir = "downloads/"
        self.directory = None
        self.num_parts = Config.HYPER_THREADS or max(8, len(self.clients))
        self.cache_file_ref = {}
        self.cache_last_access = {}
        self.cache_max_size = 100
        self._processed_bytes = 0
        self.file_size = 0
        self.chunk_size = 1024 * 1024
        self.file_name = ""
        self._cancel_event = Event()
        self.session_pool = {}
        self.session_last_used = {}  # Track when sessions were last used
        self.session_max_idle = Config.HYPER_SESSION_TIMEOUT or (
            30 * 60
        )  # Use config or default to 30 minutes
        create_task(self._clean_cache())
        create_task(self._clean_sessions())  # Add session cleanup task

        LOGGER.info(
            f"HyperDL initialized with {len(self.clients)} helper bot(s), {self.num_parts} parts"
        )

    @staticmethod
    async def get_media_type(message):
        media_types = (
            "audio",
            "document",
            "photo",
            "sticker",
            "animation",
            "video",
            "voice",
            "video_note",
            "new_chat_photo",
        )
        for attr in media_types:
            if media := getattr(message, attr, None):
                return media
        raise ValueError("This message doesn't contain any downloadable media")

    def _update_cache(self, index, file_ref):
        self.cache_file_ref[index] = file_ref
        self.cache_last_access[index] = time()

        if len(self.cache_file_ref) > self.cache_max_size:
            oldest = sorted(self.cache_last_access.items(), key=lambda x: x[1])[0][0]
            del self.cache_file_ref[oldest]
            del self.cache_last_access[oldest]

    async def get_specific_file_ref(self, mid, client, max_retries=3):
        retries = 0
        last_error = None

        while retries < max_retries:
            try:
                media = await client.get_messages(self.dump_chat, mid)
                file_ref = FileId.decode(
                    getattr(await self.get_media_type(media), "file_id", "")
                )
                return file_ref
            except Exception as e:
                last_error = e
                retries += 1
                LOGGER.warning(f"File ref attempt {retries} failed: {e}")
                if retries < max_retries:
                    await sleep(1 * retries)

        LOGGER.error(
            f"Failed to get message {mid} from {self.dump_chat} with Client {client.me.username}"
        )
        raise ValueError(
            f"Bot needs Admin access in Chat or message may be deleted. Error: {last_error}"
        )

    async def get_file_id(self, client, index) -> FileId:
        if index not in self.cache_file_ref:
            file_ref = await self.get_specific_file_ref(self.message.id, client)
            self._update_cache(index, file_ref)
        else:
            self.cache_last_access[index] = time()
        return self.cache_file_ref[index]

    async def _clean_cache(self):
        while True:
            await sleep(15 * 60)
            current_time = time()
            expired_keys = [
                k
                for k, v in self.cache_last_access.items()
                if current_time - v > 45 * 60
            ]

            for key in expired_keys:
                if key in self.cache_file_ref:
                    del self.cache_file_ref[key]
                if key in self.cache_last_access:
                    del self.cache_last_access[key]

    async def _clean_sessions(self):
        """Clean up stale sessions to prevent hanging after inactivity"""
        while True:
            await sleep(10 * 60)  # Check every 10 minutes
            current_time = time()
            stale_sessions = []

            for session_key, last_used in self.session_last_used.items():
                if current_time - last_used > self.session_max_idle:
                    stale_sessions.append(session_key)

            for session_key in stale_sessions:
                try:
                    if session_key in self.session_pool:
                        session = self.session_pool[session_key]
                        if hasattr(session, "stop"):
                            await session.stop()
                        del self.session_pool[session_key]
                    if session_key in self.session_last_used:
                        del self.session_last_used[session_key]
                    LOGGER.info(f"Cleaned up stale session: {session_key}")
                except Exception as e:
                    LOGGER.error(f"Error cleaning session {session_key}: {e}")

    async def generate_media_session(self, client, file_id, index, max_retries=3):
        session_key = (index, file_id.dc_id)
        current_time = time()

        # Check if existing session is stale
        if (
            session_key in self.session_pool
            and session_key in self.session_last_used
            and current_time - self.session_last_used[session_key]
            > self.session_max_idle
        ):
            try:
                old_session = self.session_pool[session_key]
                if hasattr(old_session, "stop"):
                    await old_session.stop()
                del self.session_pool[session_key]
                del self.session_last_used[session_key]
                LOGGER.info(f"Removed stale session for {session_key}")
            except Exception as e:
                LOGGER.error(f"Error removing stale session: {e}")

        if session_key in self.session_pool:
            # Update last used time for existing session
            self.session_last_used[session_key] = current_time
            return self.session_pool[session_key]

        retries = 0
        while retries < max_retries:
            try:
                if file_id.dc_id != await client.storage.dc_id():
                    media_session = Session(
                        client,
                        file_id.dc_id,
                        await Auth(
                            client, file_id.dc_id, await client.storage.test_mode()
                        ).create(),
                        await client.storage.test_mode(),
                        is_media=True,
                    )
                    await media_session.start()

                    for auth_attempt in range(6):
                        try:
                            exported_auth = await client.invoke(
                                raw.functions.auth.ExportAuthorization(
                                    dc_id=file_id.dc_id
                                )
                            )

                            await media_session.invoke(
                                raw.functions.auth.ImportAuthorization(
                                    id=exported_auth.id, bytes=exported_auth.bytes
                                )
                            )
                            break
                        except AuthBytesInvalid:
                            if auth_attempt < 5:
                                await sleep(1)
                            else:
                                raise
                    else:
                        await media_session.stop()
                        raise AuthBytesInvalid(
                            "Failed to import authorization after 6 attempts"
                        )
                else:
                    media_session = Session(
                        client,
                        file_id.dc_id,
                        await client.storage.auth_key(),
                        await client.storage.test_mode(),
                        is_media=True,
                    )
                    await media_session.start()

                self.session_pool[session_key] = media_session
                self.session_last_used[session_key] = current_time
                return media_session

            except Exception as e:
                retries += 1
                LOGGER.warning(f"Session creation attempt {retries} failed: {e}")
                if retries < max_retries:
                    await sleep(retries * 2)  # Exponential backoff

        raise ValueError(f"Failed to create media session after {max_retries} attempts")

    @staticmethod
    async def get_location(file_id: FileId):
        file_type = file_id.file_type

        if file_type == FileType.CHAT_PHOTO:
            if file_id.chat_id > 0:
                peer = raw.types.InputPeerUser(
                    user_id=file_id.chat_id, access_hash=file_id.chat_access_hash
                )
            else:
                peer = (
                    raw.types.InputPeerChat(chat_id=-file_id.chat_id)
                    if file_id.chat_access_hash == 0
                    else raw.types.InputPeerChannel(
                        channel_id=utils.get_channel_id(file_id.chat_id),
                        access_hash=file_id.chat_access_hash,
                    )
                )
            return raw.types.InputPeerPhotoFileLocation(
                peer=peer,
                volume_id=file_id.volume_id,
                local_id=file_id.local_id,
                big=file_id.thumbnail_source == ThumbnailSource.CHAT_PHOTO_BIG,
            )
        elif file_type == FileType.PHOTO:
            return raw.types.InputPhotoFileLocation(
                id=file_id.media_id,
                access_hash=file_id.access_hash,
                file_reference=file_id.file_reference,
                thumb_size=file_id.thumbnail_size,
            )
        else:
            return raw.types.InputDocumentFileLocation(
                id=file_id.media_id,
                access_hash=file_id.access_hash,
                file_reference=file_id.file_reference,
                thumb_size=file_id.thumbnail_size,
            )

    async def get_file(
        self,
        offset_bytes: int,
        first_part_cut: int,
        last_part_cut: int,
        part_count: int,
        max_retries=5,
    ):
        index = min(self.work_loads, key=self.work_loads.get)
        client = self.clients[index]

        self.work_loads[index] += 1
        current_retry = 0
        session_recreated = False

        try:
            while current_retry < max_retries:
                try:
                    if self._cancel_event.is_set():
                        raise CancelledError("Download cancelled")

                    file_id = await self.get_file_id(client, index)

                    # If session was recreated, regenerate media session
                    if session_recreated:
                        session_key = (index, file_id.dc_id)
                        if session_key in self.session_pool:
                            try:
                                old_session = self.session_pool[session_key]
                                if hasattr(old_session, "stop"):
                                    await old_session.stop()
                                del self.session_pool[session_key]
                                if session_key in self.session_last_used:
                                    del self.session_last_used[session_key]
                            except Exception:
                                pass

                    media_session, location = await gather(
                        self.generate_media_session(client, file_id, index),
                        self.get_location(file_id),
                    )

                    current_part = 1
                    current_offset = offset_bytes

                    while current_part <= part_count:
                        if self._cancel_event.is_set():
                            raise CancelledError("Download cancelled")

                        try:
                            r = await wait_for(
                                media_session.invoke(
                                    raw.functions.upload.GetFile(
                                        location=location,
                                        offset=current_offset,
                                        limit=self.chunk_size,
                                    ),
                                ),
                                timeout=45,  # Increased timeout
                            )

                            if isinstance(r, raw.types.upload.File):
                                chunk = r.bytes

                                if not chunk:
                                    break

                                if part_count == 1:
                                    yield chunk[first_part_cut:last_part_cut]
                                elif current_part == 1:
                                    yield chunk[first_part_cut:]
                                elif current_part == part_count:
                                    yield chunk[:last_part_cut]
                                else:
                                    yield chunk

                                current_part += 1
                                current_offset += self.chunk_size
                                self._processed_bytes += len(chunk)

                                # Update session last used time
                                session_key = (index, file_id.dc_id)
                                self.session_last_used[session_key] = time()
                            else:
                                raise ValueError(f"Unexpected response: {r}")

                        except (FloodWait, AsyncTimeoutError, ConnectionError) as e:
                            if isinstance(e, FloodWait):
                                LOGGER.warning(f"FloodWait for {e.value} seconds")
                                await sleep(e.value + 1)
                            else:
                                await sleep(2)
                            continue
                        except Exception as e:
                            LOGGER.error(f"Chunk download error: {e}")
                            # Force session recreation on certain errors
                            if (
                                "AUTH_KEY" in str(e)
                                or "SESSION_" in str(e)
                                or "PEER_" in str(e)
                            ):
                                session_recreated = True
                            raise

                    if current_part <= part_count:
                        raise ValueError(
                            f"Incomplete download: got {current_part - 1} of {part_count} parts"
                        )
                    break

                except (
                    AsyncTimeoutError,
                    ConnectionError,
                    AttributeError,
                    AuthBytesInvalid,
                ) as e:
                    current_retry += 1
                    LOGGER.warning(f"Download retry {current_retry}/{max_retries}: {e}")
                    if current_retry >= max_retries:
                        raise

                    # Force session recreation on auth errors
                    if isinstance(e, AuthBytesInvalid) or "AUTH" in str(e):
                        session_recreated = True

                    await sleep(current_retry * 3)  # Increased backoff time

        finally:
            self.work_loads[index] -= 1

    async def progress_callback(self, progress, progress_args):
        if not progress:
            return

        while not self._cancel_event.is_set():
            try:
                if callable(progress):
                    await progress(
                        self._processed_bytes, self.file_size, *progress_args
                    )
                await sleep(1)
            except (CancelledError, StopTransmission):
                break
            except Exception:
                await sleep(1)

    async def single_part(self, start, end, part_index, max_retries=3):
        until_bytes, from_bytes = min(end, self.file_size - 1), start

        offset = from_bytes - (from_bytes % self.chunk_size)
        first_part_cut = from_bytes - offset
        last_part_cut = until_bytes % self.chunk_size + 1

        part_count = ceil(until_bytes / self.chunk_size) - floor(
            offset / self.chunk_size
        )
        part_file_path = ospath.join(
            self.directory, f"{self.file_name}.temp.{part_index:02d}"
        )

        for attempt in range(max_retries):
            try:
                async with aiopen(part_file_path, "wb") as f:
                    async for chunk in self.get_file(
                        offset, first_part_cut, last_part_cut, part_count
                    ):
                        if self._cancel_event.is_set():
                            raise CancelledError("Download cancelled")
                        await f.write(chunk)
                return part_index, part_file_path
            except (AsyncTimeoutError, ConnectionError):
                if attempt == max_retries - 1:
                    raise
                await sleep((attempt + 1) * 2)
                self._processed_bytes = 0

    async def handle_download(self, progress, progress_args):
        self._cancel_event.clear()

        await makedirs(self.directory, exist_ok=True)
        temp_file_path = (
            ospath.abspath(
                sub("\\\\", "/", ospath.join(self.directory, self.file_name))
            )
            + ".temp"
        )

        num_parts = min(self.num_parts, max(1, self.file_size // (10 * 1024 * 1024)))

        if self.file_size < 10 * 1024 * 1024:
            num_parts = 1

        part_size = self.file_size // num_parts if num_parts > 0 else self.file_size
        ranges = [
            (i * part_size, min((i + 1) * part_size - 1, self.file_size - 1))
            for i in range(num_parts)
        ]

        tasks = []
        prog_task = None

        try:
            for i, (start, end) in enumerate(ranges):
                tasks.append(create_task(self.single_part(start, end, i)))

            if progress:
                prog_task = create_task(self.progress_callback(progress, progress_args))

            results = await gather(*tasks)

            async with aiopen(temp_file_path, "wb") as temp_file:
                for _, part_file_path in sorted(results, key=lambda x: x[0]):
                    try:
                        async with aiopen(part_file_path, "rb") as part_file:
                            while True:
                                chunk = await part_file.read(8 * 1024 * 1024)
                                if not chunk:
                                    break
                                await temp_file.write(chunk)
                        await remove(part_file_path)
                    except Exception as e:
                        LOGGER.error(
                            f"Error processing part file {part_file_path}: {e}"
                        )
                        raise

            if prog_task and not prog_task.done():
                prog_task.cancel()

            file_path = ospath.splitext(temp_file_path)[0]
            await move(temp_file_path, file_path)

            return file_path

        except FloodWait as fw:
            raise fw
        except (CancelledError, StopTransmission):
            return None
        except Exception as e:
            LOGGER.error(f"HyperDL Error: {e}")
            return None
        finally:
            self._cancel_event.set()
            if prog_task and not prog_task.done():
                prog_task.cancel()

            for task in tasks:
                if not task.done():
                    task.cancel()

            # Clean up temporary part files
            for i in range(len(ranges)):
                part_path = ospath.join(
                    self.directory, f"{self.file_name}.temp.{i:02d}"
                )
                try:
                    if ospath.exists(part_path):
                        await remove(part_path)
                except Exception:
                    pass

            # Clean up sessions after download completion/failure
            try:
                await self.cleanup_all_sessions()
            except Exception as e:
                LOGGER.error(f"Error cleaning up sessions: {e}")

    @staticmethod
    async def get_extension(file_type, mime_type):
        if file_type in PHOTO_TYPES:
            return ".jpg"

        if mime_type:
            extension = guess_extension(mime_type)
            if extension:
                return extension

        if file_type == FileType.VOICE:
            return ".ogg"
        elif file_type in (FileType.VIDEO, FileType.ANIMATION, FileType.VIDEO_NOTE):
            return ".mp4"
        elif file_type == FileType.DOCUMENT:
            return ".bin"
        elif file_type == FileType.STICKER:
            return ".webp"
        elif file_type == FileType.AUDIO:
            return ".mp3"
        else:
            return ".bin"

    async def download_media(
        self,
        message,
        file_name="downloads/",
        progress=None,
        progress_args=(),
        dump_chat=None,
    ):
        try:
            if dump_chat:
                self.message = await TgClient.bot.copy_message(
                    chat_id=dump_chat,
                    from_chat_id=message.chat.id,
                    message_id=message.id,
                    disable_notification=True,
                )

            self.dump_chat = dump_chat or message.chat.id
            self.message = self.message or message
            media = await self.get_media_type(self.message)

            file_id_str = media if isinstance(media, str) else media.file_id
            file_id_obj = FileId.decode(file_id_str)

            file_type = file_id_obj.file_type
            media_file_name = getattr(media, "file_name", "")
            self.file_size = getattr(media, "file_size", 0)
            mime_type = getattr(media, "mime_type", "image/jpeg")
            date = getattr(media, "date", None)

            self.directory, self.file_name = ospath.split(file_name)
            self.file_name = self.file_name or media_file_name or ""

            if not ospath.isabs(self.file_name):
                self.directory = Path(argv[0]).parent / (
                    self.directory or self.download_dir
                )

            if not self.file_name:
                extension = await self.get_extension(file_type, mime_type)
                self.file_name = f"{FileType(file_id_obj.file_type).name.lower()}_{(date or datetime.now()).strftime('%Y-%m-%d_%H-%M-%S')}_{MsgId()}{extension}"

            return await self.handle_download(progress, progress_args)

        except Exception as e:
            LOGGER.error(f"Download media error: {e}")
            raise

    async def cleanup_all_sessions(self):
        """Clean up all active sessions"""
        for session_key, session in list(self.session_pool.items()):
            try:
                if hasattr(session, "stop"):
                    await session.stop()
                LOGGER.debug(f"Cleaned up session: {session_key}")
            except Exception as e:
                LOGGER.error(f"Error cleaning session {session_key}: {e}")

        self.session_pool.clear()
        self.session_last_used.clear()

    async def emergency_cleanup(self):
        """Emergency cleanup for when the bot gets stuck"""
        try:
            LOGGER.warning("Performing emergency cleanup of HyperDL sessions...")
            await self.cleanup_all_sessions()

            # Reset all tracking variables
            self._processed_bytes = 0
            self._cancel_event.set()

            # Clear cache
            self.cache_file_ref.clear()
            self.cache_last_access.clear()

            LOGGER.info("Emergency cleanup completed")
        except Exception as e:
            LOGGER.error(f"Error during emergency cleanup: {e}")

    @classmethod
    def is_available(cls):
        """Check if HyperDL can be used (requires helper bots)"""
        return (
            hasattr(TgClient, "helper_bots")
            and hasattr(TgClient, "helper_loads")
            and TgClient.helper_bots
            and len(TgClient.helper_bots) > 0
            and all(client is not None for client in TgClient.helper_bots.values())
        )

    @classmethod
    def get_status_info(cls):
        """Get detailed status information about HyperDL availability"""
        info = {
            "available": False,
            "reason": "Unknown",
            "helper_count": 0,
            "config_threads": Config.HYPER_THREADS,
        }

        if not hasattr(TgClient, "helper_bots"):
            info["reason"] = "TgClient.helper_bots not found"
            return info

        if not hasattr(TgClient, "helper_loads"):
            info["reason"] = "TgClient.helper_loads not found"
            return info

        if not TgClient.helper_bots:
            info["reason"] = "No helper bots configured (HELPER_TOKENS missing)"
            return info

        if len(TgClient.helper_bots) == 0:
            info["reason"] = "Helper bots list is empty"
            return info

        active_bots = sum(
            1 for client in TgClient.helper_bots.values() if client is not None
        )
        info["helper_count"] = active_bots

        if active_bots == 0:
            info["reason"] = "All helper bots are None (failed to start)"
            return info

        info["available"] = True
        info["reason"] = f"Ready with {active_bots} helper bot(s)"
        return info
