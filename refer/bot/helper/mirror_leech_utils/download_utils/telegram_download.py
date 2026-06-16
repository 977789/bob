from asyncio import Lock, sleep
from time import time
from secrets import token_hex
from pyrogram.errors import FloodWait, PeerIdInvalid, ChannelInvalid

from bot.helper.ext_utils.hyperdl_utils import HyperTGDownload
from bot.helper.ext_utils.user_session_manager import UserSessionManager

try:
    from pyrogram.errors import FloodPremiumWait
except ImportError:
    FloodPremiumWait = FloodWait

from .... import (
    LOGGER,
    task_dict,
    task_dict_lock,
    user_data,
)
from ....core.tg_client import TgClient
from ....core.config_manager import Config
from ...ext_utils.task_manager import check_running_tasks, stop_duplicate_check
from ...mirror_leech_utils.status_utils.queue_status import QueueStatus
from ...mirror_leech_utils.status_utils.telegram_status import TelegramStatus
from ...telegram_helper.message_utils import send_status_message

global_lock = Lock()
GLOBAL_GID = dict()


class TelegramDownloadHelper:
    def __init__(self, listener):
        self._processed_bytes = 0
        self._start_time = 1
        self._listener = listener
        self._id = ""
        self.session = ""
        self._hyper_dl = len(TgClient.helper_bots) != 0 and Config.LEECH_DUMP_CHAT

    @property
    def speed(self):
        return self._processed_bytes / (time() - self._start_time)

    @property
    def processed_bytes(self):
        return self._processed_bytes

    async def _on_download_start(self, file_id, gid, from_queue):
        async with global_lock:
            GLOBAL_GID[file_id] = gid
        self._id = file_id
        async with task_dict_lock:
            task_dict[self._listener.mid] = TelegramStatus(
                self._listener, self, gid, "dl", self._hyper_dl
            )
        if not from_queue:
            await self._listener.on_download_start()
            if self._listener.multi <= 1:
                await send_status_message(self._listener.message)
            LOGGER.info(f"Download from Telegram: {self._listener.name}")
        else:
            LOGGER.info(f"Start Queued Download from Telegram: {self._listener.name}")

    async def _on_download_progress(self, current, _):
        if self._listener.is_cancelled:
            if self.session == "user":
                TgClient.user.stop_transmission()
            elif self.session == "hbots":
                for hbot in TgClient.helper_bots.values():
                    hbot.stop_transmission()
            else:
                TgClient.bot.stop_transmission()
        self._processed_bytes = current

    async def _on_download_error(self, error):
        async with global_lock:
            GLOBAL_GID.pop(self._id, None)
        await self._listener.on_download_error(error)

    async def _on_download_complete(self):
        await self._listener.on_download_complete()
        async with global_lock:
            GLOBAL_GID.pop(self._id, None)
        return

    async def _download(self, message, path):
        try:
            # Use standard download if HyperDL is disabled or failed
            if not self._hyper_dl:
                if self.session == "user_session":
                    # Use individual user session
                    user_client = await UserSessionManager.get_user_session(
                        self._listener.user_id
                    )
                    if user_client:
                        try:
                            # Get message using user session
                            user_message = await user_client.get_messages(
                                chat_id=message.chat.id, message_ids=message.id
                            )
                            download = await user_message.download(
                                file_name=path, progress=self._on_download_progress
                            )
                            LOGGER.info(
                                f"Downloaded using user session for {self._listener.user_id}"
                            )
                        except Exception as e:
                            LOGGER.warning(
                                f"User session download failed: {e}, falling back to bot session"
                            )
                            download = await message.download(
                                file_name=path, progress=self._on_download_progress
                            )
                    else:
                        LOGGER.warning("User session not available, using bot session")
                        download = await message.download(
                            file_name=path, progress=self._on_download_progress
                        )
                elif self.session == "user":
                    # Use global user (premium) client only when explicitly selected
                    try:
                        user_message = await TgClient.user.get_messages(
                            chat_id=message.chat.id, message_ids=message.id
                        )
                        download = await user_message.download(
                            file_name=path, progress=self._on_download_progress
                        )
                    except Exception:
                        download = await message.download(
                            file_name=path, progress=self._on_download_progress
                        )
                else:
                    download = await message.download(
                        file_name=path, progress=self._on_download_progress
                    )
            else:
                # HyperDL logic
                if not HyperTGDownload.is_available():
                    status_info = HyperTGDownload.get_status_info()
                    LOGGER.warning(
                        f"HyperDL not available: {status_info['reason']}, falling back to standard download"
                    )
                    self._hyper_dl = False
                else:
                    hyper_downloader = None
                    try:
                        hyper_downloader = HyperTGDownload()
                        download = await hyper_downloader.download_media(
                            message,
                            file_name=path,
                            progress=self._on_download_progress,
                            dump_chat=Config.LEECH_DUMP_CHAT,
                        )
                    except Exception as e:
                        LOGGER.warning(
                            f"HyperDL failed: {e}, falling back to standard download"
                        )
                        # Emergency cleanup in case of critical errors
                        if hyper_downloader:
                            try:
                                await hyper_downloader.emergency_cleanup()
                            except Exception:
                                pass

                        # Set flag to false to prevent retry
                        self._hyper_dl = False

            if self._listener.is_cancelled:
                return
        except (FloodWait, FloodPremiumWait) as f:
            LOGGER.warning(str(f))
            await sleep(f.value)
            await self._download(message, path)
            return
        except Exception as e:
            LOGGER.error(str(e), exc_info=True)
            await self._on_download_error(str(e))
            return
        if download is not None:
            await self._on_download_complete()
        elif not self._listener.is_cancelled:
            await self._on_download_error("Internal error occurred")
        return

    async def add_download(self, message, path, session):
        self.session = session
        if not self.session:
            # Check if user has personal session and can access this chat
            if UserSessionManager.has_user_session(self._listener.user_id):
                can_access = await UserSessionManager.can_access_chat(
                    self._listener.user_id, message.chat.id
                )
                if can_access:
                    self.session = "user_session"
                    LOGGER.info(
                        f"Using user session for {self._listener.user_id} to download from {message.chat.id}"
                    )
                    # Get message using user session
                    user_message = (
                        await UserSessionManager.get_message_with_user_session(
                            self._listener.user_id, message.chat.id, message.id
                        )
                    )
                    if user_message:
                        message = user_message
                    else:
                        LOGGER.warning(
                            f"Failed to get message using user session, falling back to bot session"
                        )
                        self.session = "bot"
                else:
                    LOGGER.info(
                        f"User session cannot access chat {message.chat.id}, using bot session"
                    )
                    self.session = "bot"
            elif self._hyper_dl:
                self.session = "hbots"
            elif self._listener.user_transmission and self._listener.is_super_chat:
                self.session = "user"
                try:
                    message = await TgClient.user.get_messages(
                        chat_id=message.chat.id, message_ids=message.id
                    )
                except (PeerIdInvalid, ChannelInvalid):
                    LOGGER.warning(
                        "User session is not in this chat!, Downloading with bot session"
                    )
                    self.session = "bot"
            else:
                self.session = "bot"
        media = getattr(message, message.media.value) if message.media else None

        if media is not None:
            async with global_lock:
                download = media.file_unique_id not in GLOBAL_GID

            if download:
                if not self._listener.name:
                    if hasattr(media, "file_name") and media.file_name:
                        if "/" in media.file_name:
                            self._listener.name = media.file_name.rsplit("/", 1)[-1]
                            path = path + self._listener.name
                        else:
                            self._listener.name = media.file_name
                    else:
                        self._listener.name = "None"
                else:
                    path = path + self._listener.name
                self._listener.size = media.file_size
                gid = token_hex(5)

                msg, button = await stop_duplicate_check(self._listener)
                if msg:
                    await self._listener.on_download_error(msg, button)
                    return

                add_to_queue, event = await check_running_tasks(self._listener)
                if add_to_queue:
                    LOGGER.info(f"Added to Queue/Download: {self._listener.name}")
                    async with task_dict_lock:
                        task_dict[self._listener.mid] = QueueStatus(
                            self._listener, gid, "dl"
                        )
                    await self._listener.on_download_start()
                    if self._listener.multi <= 1:
                        await send_status_message(self._listener.message)
                    await event.wait()
                    if self.session == "bot":
                        message = await self._listener.client.get_messages(
                            chat_id=message.chat.id, message_ids=message.id
                        )
                    elif self.session == "user_session":
                        # Re-fetch using the individual user session
                        user_message = (
                            await UserSessionManager.get_message_with_user_session(
                                self._listener.user_id, message.chat.id, message.id
                            )
                        )
                        if user_message:
                            message = user_message
                        else:
                            # Fallback to bot if user session fetch fails
                            message = await self._listener.client.get_messages(
                                chat_id=message.chat.id, message_ids=message.id
                            )
                    else:  # self.session == "user"
                        try:
                            message = await TgClient.user.get_messages(
                                chat_id=message.chat.id, message_ids=message.id
                            )
                        except (PeerIdInvalid, ChannelInvalid):
                            message = await self._listener.client.get_messages(
                                chat_id=message.chat.id, message_ids=message.id
                            )
                    if self._listener.is_cancelled:
                        async with global_lock:
                            GLOBAL_GID.pop(self._id, None)
                        return
                self._start_time = time()
                await self._on_download_start(media.file_unique_id, gid, add_to_queue)
                await self._download(message, path)
            else:
                await self._on_download_error("File already being downloaded!")
        else:
            await self._on_download_error(
                "No document in the replied message! Use SuperGroup incase you are trying to download with User session!"
            )

    async def cancel_task(self):
        self._listener.is_cancelled = True
        LOGGER.info(
            f"Cancelling download on user request: name: {self._listener.name} id: {self._id}"
        )
        await self._on_download_error("Stopped by user!")
