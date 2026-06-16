import re
from asyncio import sleep
from logging import getLogger
import os
import gc  # Added for memory management
import tempfile
from os import path as ospath
from os import walk
from re import match as re_match
from time import time

import aiofiles
import aiohttp
from aiofiles.os import path as aiopath, symlink
from aiofiles.os import remove
from aioshutil import rmtree
from natsort import natsorted
from PIL import Image
from pyrogram.enums import ParseMode
from pyrogram.errors import (
    BadRequest,
    FloodWait,
    MessageNotModified,
    RPCError,
)
from pyrogram.types import InputMediaDocument, InputMediaPhoto, InputMediaVideo
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential,
)


from ....core.config_manager import Config
from ....core.tg_client import TgClient
from ....helper.mhunt_utils.filename_processor import (
    extract_media_info_from_filename,
)
from ...ext_utils.bot_utils import sync_to_async
from ...ext_utils.media_utils import (
    get_document_type,
    get_media_info,
    get_video_thumbnail,
)
from ...ext_utils.status_utils import (
    get_readable_file_size,
    get_readable_time,
)
from ...ext_utils.tmdb_utils import (
    extract_tmdb_info_from_filename as extract_tmdb_info_for_search,
)
from ....modules.mediainfo import get_mediainfo_telegraph_link
from ...telegram_helper.button_build import ButtonMaker
from ...ext_utils.tmdb_utils import fetch_tmdb_data
from ...telegram_helper.message_utils import send_custom_message

try:
    from pyrogram.errors import FloodPremiumWait
except ImportError:
    FloodPremiumWait = FloodWait

LOGGER = getLogger(__name__)


# Simplified memory cleanup - only when really needed
def _check_memory_and_cleanup():
    """Basic memory cleanup without aggressive intervention"""
    import gc

    gc.collect()
    return False


class TelegramUploader:
    def __init__(self, listener, path):
        self._last_uploaded = 0
        self._processed_bytes = 0
        self._listener = listener
        self._path = path
        self._client = None
        self._start_time = time()
        self._total_files = 0
        self._thumb = self._listener.thumb or f"thumbnails/{listener.user_id}.jpg"
        self._msgs_dict = {}
        self._corrupted = 0
        self._is_corrupted = False
        self._media_dict = {"videos": {}, "documents": {}}
        self._last_msg_in_group = False
        self._up_path = ""
        self._upload_dest = None
        self._topic_id = None  # Add topic ID support
        self._dm_msg = None
        self._backup_msg = None
        self._movie_msg = None
        self._delete_msg = None
        self._lprefix = ""
        self._lsuffix = ""
        self._lcaption = ""
        self._leech_caption_font_style = "normal"
        self._media_group = False
        self._is_private = False
        self._sent_msg = None
        self._user_session = self._listener.user_transmission
        self._error = ""
        self._status = None
        self._leech_dump_initial_msg_id = None
        self._dm_initial_msg_id = None
        self._owner_dump_messages = []  # Track messages sent to owner's LEECH_DUMP_CHAT for deletion
        self._leech_dump_initial_msg = None
        self._current_display_filename = (
            None  # Store the display filename for Telegraph links
        )

    @staticmethod
    def _parse_chat_id(chat_value):
        """
        Parse chat ID from string or pipe-separated format (chat_id|topic_id).

        Args:
            chat_value: Chat ID as int, str, or "chat_id|topic_id" format

        Returns:
            tuple: (chat_id, topic_id) where topic_id may be None
        """
        if not chat_value:
            return None, None

        chat_id = chat_value
        topic_id = None

        if isinstance(chat_value, str) and "|" in chat_value:
            parts = chat_value.split("|", 1)
            try:
                chat_id = int(parts[0])
                topic_id = int(parts[1]) if parts[1] else None
            except (ValueError, IndexError):
                chat_id = parts[0] if parts else chat_value
        else:
            try:
                chat_id = (
                    int(chat_value)
                    if isinstance(chat_value, str) and chat_value.lstrip("-").isdigit()
                    else chat_value
                )
            except ValueError:
                pass

        return chat_id, topic_id

    async def _user_settings(self):
        settings_map = {
            "MEDIA_GROUP": ("_media_group", False),
            "LEECH_PREFIX": ("_lprefix", ""),
            "LEECH_SUFFIX": ("_lsuffix", ""),
            "LEECH_CAPTION": ("_lcaption", ""),
        }
        self._leech_caption_font_style = self._listener.user_dict.get(
            "LEECH_CAPTION_FONT"
        ) or getattr(Config, "LEECH_CAPTION_FONT", "normal")
        for key, (attr, default) in settings_map.items():
            setattr(
                self,
                attr,
                self._listener.user_dict.get(key) or getattr(Config, key, default),
            )
        self._upload_dest = self._listener.up_dest or self._listener.user_dict.get(
            "LEECH_DUMP_CHAT"
        )
        # Handle topic ID from listener if available
        if hasattr(self._listener, "chat_thread_id") and self._listener.chat_thread_id:
            self._topic_id = self._listener.chat_thread_id
        # Remove all logic that tries to use or store topic/thread IDs
        # All messages will go to the main chat
        if self._thumb != "none" and not await aiopath.exists(self._thumb):
            self._thumb = None
        if Config.LEECH_TO_PM_ONLY and not Config.LEECH_DUMP_CHAT:
            self._user_session = False
            if not self._upload_dest:
                self._upload_dest = self._listener.user_id

    async def _upload_progress(self, current, _):
        if self._listener.is_cancelled:
            if self._user_session:
                TgClient.user.stop_transmission()
            else:
                self._listener.client.stop_transmission()
        chunk_size = current - self._last_uploaded
        self._last_uploaded = current
        self._processed_bytes += chunk_size

    async def _msg_to_reply(self):
        if LEECH_DUMP_CHAT := Config.LEECH_DUMP_CHAT:
            try:
                msg = f"#UploadStarted: {self._listener.user.mention} #id{self._listener.user_id}"

                # Parse chat_id|topic_id format for global LEECH_DUMP_CHAT
                chat_id = LEECH_DUMP_CHAT
                topic_id = None

                if isinstance(LEECH_DUMP_CHAT, str) and "|" in LEECH_DUMP_CHAT:
                    parts = LEECH_DUMP_CHAT.split("|", 1)
                    try:
                        chat_id = int(parts[0])
                        topic_id = int(parts[1]) if parts[1] else None
                    except ValueError:
                        LOGGER.error(
                            f"Invalid global LEECH_DUMP_CHAT format: {LEECH_DUMP_CHAT}"
                        )
                        chat_id = int(LEECH_DUMP_CHAT)
                        topic_id = None
                else:
                    chat_id = int(LEECH_DUMP_CHAT)
                    topic_id = None

                chat = await TgClient.bot.get_chat(chat_id)
                # Use direct send_message call to support message_thread_id
                self._sent_msg = await self._listener.client.send_message(
                    chat_id=chat.id,
                    text=msg,
                    disable_web_page_preview=True,
                    disable_notification=True,
                    message_thread_id=topic_id,
                )
                self._is_private = self._sent_msg.chat.type.name == "PRIVATE"
                self._dm_msg = self._delete_msg = await send_custom_message(
                    TgClient.bot, self._listener.user_id, "Upload Started!!"
                )
            except Exception as e:
                await self._listener.on_upload_error(str(e))
                return False
        else:
            self._sent_msg = self._delete_msg = await send_custom_message(
                TgClient.bot, self._listener.user_id, "Upload Started!!"
            )

        if MOVIE_DUMP := Config.MOVIE_DUMP:
            msg = f"#UploadStarted: {self._listener.user.mention} #id{self._listener.user_id}"
            try:
                self._movie_msg = await send_custom_message(
                    self._listener.client, int(MOVIE_DUMP), msg
                )
            except Exception as e:
                LOGGER.error(str(e))

        if BACKUP_DUMP := Config.BACKUP_DUMP:
            msg = "#UploadStarted"
            try:
                self._backup_msg = await send_custom_message(
                    self._listener.client, int(BACKUP_DUMP), msg
                )
            except Exception as e:
                LOGGER.error(str(e))
        return True

    async def _prepare_file(self, f_path, file_):
        self._up_path = f_path
        cap_file_ = file_
        if self._lcaption:
            try:
                duration_seconds, quality, lang, subs = await get_media_info(
                    self._up_path, True
                )
                (
                    ext_title,
                    ext_season,
                    ext_episode,
                    ext_year,
                    ext_part,
                    ext_volume,
                ) = extract_media_info_from_filename(cap_file_)

                f_size = await aiopath.getsize(self._up_path)
                file_size_readable = get_readable_file_size(f_size)
                duration_readable = (
                    get_readable_time(duration_seconds) if duration_seconds else "N/A"
                )

                filename_with_style = f"<b>{cap_file_}</b>"
                if self._leech_caption_font_style == "italic":
                    filename_with_style = f"<i>{cap_file_}</i>"
                elif self._leech_caption_font_style == "mono":
                    filename_with_style = f"<code>{cap_file_}</code>"
                elif self._leech_caption_font_style == "normal":
                    filename_with_style = cap_file_

                # Original file caption (if available from source message)
                file_caption = ""
                try:
                    if hasattr(self._listener, "file_details") and isinstance(
                        self._listener.file_details, dict
                    ):
                        file_caption = (
                            self._listener.file_details.get("caption", "") or ""
                        )
                except Exception:
                    file_caption = ""

                caption_vars = {
                    "filename": filename_with_style,
                    "name": ospath.splitext(cap_file_)[0],
                    "title": ext_title or "N/A",
                    "size": file_size_readable,
                    # Aliases for broader template compatibility
                    "file_name": cap_file_,
                    "file_size": file_size_readable,
                    "file_caption": file_caption,
                    "quality": str(quality) if quality else "N/A",
                    "resolution": str(quality) if quality else "N/A",
                    "season": f"{int(ext_season):02d}"
                    if ext_season and ext_season.isdigit()
                    else ext_season or "N/A",
                    "episode": f"{int(ext_episode):02d}"
                    if ext_episode and ext_episode.isdigit()
                    else ext_episode or "N/A",
                    "year": ext_year or "N/A",
                    "part": ext_part or "N/A",
                    "volume": ext_volume or "N/A",
                    "languages": lang or "N/A",
                    "subtitles": subs or "N/A",
                    "subtitle": subs or "N/A",
                    "duration": duration_readable,
                    "audios": lang or "N/A",
                    "ott": "N/A",
                }

                if isinstance(lang, (list, tuple)) and lang:
                    caption_vars["language"] = lang[0]
                elif isinstance(lang, str):
                    caption_vars["language"] = lang
                else:
                    caption_vars["language"] = "N/A"

                cap_mono = self._lcaption.format_map(caption_vars)

            except Exception as e:
                LOGGER.error(f"Could not format LEECH_CAPTION: {e}", exc_info=True)
                cap_mono = f"<b>{cap_file_}</b>"
        else:
            cap_mono = f"<b>{cap_file_}</b>"

        if not await aiopath.exists(self._up_path):
            LOGGER.error(
                f"Critical: Path '{self._up_path}' does not exist before upload."
            )
            self._up_path = f_path

        return cap_mono

    async def _get_input_media(self, subkey, key):
        rlist = []
        for msg_wrapper in self._media_dict[key][subkey]:
            msg = msg_wrapper
            if key == "videos":
                input_media = InputMediaVideo(
                    media=msg.video.file_id, caption=msg.caption
                )
            else:
                input_media = InputMediaDocument(
                    media=msg.document.file_id, caption=msg.caption
                )
            rlist.append(input_media)
        return rlist

    async def _send_screenshots(self, dirpath, outputs):
        inputs = [
            InputMediaPhoto(ospath.join(dirpath, p), p.rsplit("/", 1)[-1])
            for p in outputs
        ]
        for i in range(0, len(inputs), 10):
            batch = inputs[i : i + 10]
            client = self._listener.client
            if self._sent_msg and self._sent_msg.chat:
                if (
                    self._user_session
                    and TgClient.user
                    and self._sent_msg.from_user
                    and self._sent_msg.from_user.is_self
                ):
                    client = TgClient.user
            if self._sent_msg:
                new_sent_msg_batch = await client.send_media_group(
                    chat_id=self._sent_msg.chat.id,
                    media=batch,
                    reply_to_message_id=self._sent_msg.id,
                    disable_notification=True,
                    message_thread_id=self._topic_id,
                )
                if new_sent_msg_batch:
                    self._sent_msg = new_sent_msg_batch[-1]
            if self._dm_msg and self._dm_msg.chat.id == self._listener.user_id:
                await TgClient.bot.send_media_group(
                    chat_id=self._listener.user_id,
                    media=batch,
                    reply_to_message_id=self._dm_msg.id,
                    disable_notification=True,
                    message_thread_id=self._topic_id,
                )

    async def _send_media_group(self, subkey, key, individual_messages_data_tuples):
        if not self._sent_msg or not self._sent_msg.chat:
            LOGGER.error("Cannot send media group: self._sent_msg context is invalid.")
            return
        client_for_group = (
            TgClient.user
            if self._user_session and TgClient.user
            else self._listener.client
        )
        media_list = []
        for chat_id, msg_id in individual_messages_data_tuples:
            try:
                original_msg = await client_for_group.get_messages(chat_id, msg_id)
                if original_msg:
                    if original_msg.video:
                        media_list.append(
                            InputMediaVideo(
                                media=original_msg.video.file_id,
                                caption=original_msg.caption,
                            )
                        )
                    elif original_msg.document:
                        media_list.append(
                            InputMediaDocument(
                                media=original_msg.document.file_id,
                                caption=original_msg.caption,
                            )
                        )
                else:
                    LOGGER.warning(
                        f"Failed to fetch message {msg_id} from chat {chat_id} for media group."
                    )
            except Exception as e_fetch:
                LOGGER.error(
                    f"Error fetching message {msg_id} for media group: {e_fetch}"
                )
        if not media_list:
            LOGGER.error(
                f"Media list for group {subkey} is empty after fetching. Cannot send."
            )
            return
        try:
            new_media_group_messages = await client_for_group.send_media_group(
                chat_id=self._sent_msg.chat.id,
                media=media_list,
                reply_to_message_id=self._sent_msg.id,
                disable_notification=True,
                message_thread_id=self._topic_id,
            )
            ids_to_delete = [item[1] for item in individual_messages_data_tuples]
            if ids_to_delete:
                await client_for_group.delete_messages(
                    chat_id=self._sent_msg.chat.id, message_ids=ids_to_delete
                )
            del self._media_dict[key][subkey]
            if new_media_group_messages:
                for msg in new_media_group_messages:
                    await self._add_buttons_to_message(msg, client_for_group)
                self._sent_msg = new_media_group_messages[-1]
                if not self._is_private:
                    for m_group in new_media_group_messages:
                        if m_group.link:
                            self._msgs_dict[m_group.link] = (
                                m_group.caption or ospath.basename(self._up_path)
                            )
        except Exception as e_group:
            LOGGER.error(
                f"Error sending/processing media group for {subkey}: {e_group}"
            )

    async def upload(self):
        await self._user_settings()
        res = await self._msg_to_reply()
        if not res:
            return
        from collections import defaultdict

        # Toggle-based ordering
        use_sequential = bool(
            self._listener.user_dict.get("AUTO_RENAME", False)
            or self._listener.user_dict.get("SEQUENTIAL_ORDER", False)
        )

        grouped_by_episode = defaultdict(list)
        for dirpath, _, files in natsorted(await sync_to_async(walk, self._path)):
            if dirpath.endswith("/yt-dlp-thumb"):
                continue
            if dirpath.endswith("_mltbss"):
                await self._send_screenshots(dirpath, files)
                await rmtree(dirpath, ignore_errors=True)
                continue
            for file_ in natsorted(files):
                f_path = ospath.join(dirpath, file_)
                # Skip filtered
                if file_.lower().endswith(tuple(self._listener.extension_filter)):
                    try:
                        await remove(f_path)
                    except Exception:
                        pass
                    continue
                if use_sequential:
                    # Extract episode and quality from filename
                    try:
                        from bot.helper.mhunt_utils.filename_processor import (
                            extract_media_info_from_filename,
                        )

                        name, s, e, y, p, v = extract_media_info_from_filename(file_)
                    except Exception:
                        s = e = None
                    # Parse quality: 480p/720p/1080p/2160p/4K
                    import re

                    q_match = re.search(r"(?<!\d)(\d{3,4})p(?!\d)|\b4k\b", file_, re.I)
                    if q_match:
                        if q_match.group(0).lower() == "4k":
                            q_int = 2160
                        else:
                            q_int = int(q_match.group(1))
                    else:
                        q_int = 0
                    # Episode key: ensure numeric; fallback 0 groups together
                    try:
                        ep_key = int(e) if (e and str(e).isdigit()) else 0
                    except Exception:
                        ep_key = 0
                    grouped_by_episode[ep_key].append((q_int, f_path, file_))
                else:
                    # Use 0 to preserve original natural dir order grouping
                    grouped_by_episode[0].append((0, f_path, file_))

        # Iterate in requested order
        episodes_iter = (
            sorted(grouped_by_episode.keys())
            if use_sequential
            else grouped_by_episode.keys()
        )
        for ep in episodes_iter:
            qualities_iter = (
                sorted(grouped_by_episode[ep], key=lambda x: x[0])
                if use_sequential
                else grouped_by_episode[ep]
            )
            for q_int, f_path, file_ in qualities_iter:
                self._error = ""
                self._up_path = f_path
                # Store the display filename for Telegraph link generation
                self._current_display_filename = file_
                if not ospath.exists(self._up_path):
                    LOGGER.error(f"{self._up_path} not exists! Continue uploading!")
                    continue
                try:
                    f_size = await aiopath.getsize(self._up_path)
                    self._total_files += 1
                    if f_size == 0:
                        LOGGER.error(
                            f"{self._up_path} size is zero, telegram don't upload zero size files"
                        )
                        self._corrupted += 1
                        continue

                    if self._listener.is_cancelled:
                        return

                    # Force user session for large files if available (like reference implementation)
                    if (
                        not self._listener.user_transmission
                        and f_size > 2097152000  # 2GB
                        and hasattr(TgClient, "user")
                        and TgClient.user is not None
                    ):
                        LOGGER.info(
                            f"File {file_} ({get_readable_file_size(f_size)}) is large, will use user session"
                        )
                        self._listener.user_transmission = True
                        return

                    sent_to_chats_for_current_file = set()
                    self._last_msg_in_group = False
                    self._last_uploaded = 0
                    # Preserve custom thumbnail from listener, fallback to user default
                    if not self._thumb or self._thumb == "none":
                        thumb_path = f"thumbnails/{self._listener.user_id}.jpg"
                        self._thumb = (
                            thumb_path if await aiopath.exists(thumb_path) else None
                        )
                    await self._upload_file(f_path, sent_to_chats_for_current_file)
                    if self._listener.is_cancelled:
                        return
                    if (
                        not self._is_corrupted
                        and (self._listener.is_super_chat or Config.LEECH_DUMP_CHAT)
                        and not self._is_private
                    ):
                        self._msgs_dict[self._sent_msg.link] = file_

                    if not self._listener.is_cancelled and self._sent_msg:
                        if self._listener.user_dict.get("LEECH_DUMP_CHAT"):
                            await self.send_to_user_dump(sent_to_chats_for_current_file)
                        if Config.LEECH_DUMP_CHAT:
                            await self.send_to_dm(sent_to_chats_for_current_file)
                        if Config.BACKUP_DUMP:
                            await self.send_to_backup_dump(
                                sent_to_chats_for_current_file
                            )
                        if Config.MOVIE_DUMP:
                            await self.send_to_movie_dump(
                                sent_to_chats_for_current_file
                            )
                        if self._listener.user_dict.get("multi_leech_dest"):
                            for chat_id_str in self._listener.user_dict[
                                "multi_leech_dest"
                            ]:
                                # Pass the original string to copy_message_to_chat to handle topic IDs
                                await self.copy_message_to_chat(
                                    chat_id_str, sent_to_chats_for_current_file
                                )

                        # Delete from owner's LEECH_DUMP_CHAT after forwarding (if enabled)
                        await self.delete_from_owner_dump(
                            sent_to_chats_for_current_file
                        )

                except Exception as err:
                    if isinstance(err, RetryError):
                        LOGGER.info(
                            f"Total Attempts: {err.last_attempt.attempt_number}"
                        )
                        err = err.last_attempt.exception()
                    LOGGER.error(f"{err}. Path: {self._up_path}")
                    self._error = str(err)
                    self._corrupted += 1
                    if self._listener.is_cancelled:
                        return
                finally:
                    if not self._listener.is_cancelled and await aiopath.exists(
                        self._up_path
                    ):
                        await remove(self._up_path)

        if not self._listener.is_cancelled:
            for key, value in list(self._media_dict.items()):
                for subkey, msgs in list(value.items()):
                    if len(msgs) > 1:
                        await self._send_media_group(subkey, key, msgs)

        if self._listener.is_cancelled:
            return
        if self._total_files == 0:
            await self._listener.on_upload_error("No files to upload!!")
            return
        if self._total_files <= self._corrupted:
            await self._listener.on_upload_error(
                f"Files Corrupted or unable to upload. {self._error or 'Check logs!'}"
            )
            return
        LOGGER.info(f"Leech Completed: {self._listener.name}")
        # Expose the last sent message and msgs map to the listener for downstream buttons/links
        try:
            if getattr(self, "_sent_msg", None):
                setattr(self._listener, "_sent_msg", self._sent_msg)
            if getattr(self, "_msgs_dict", None):
                setattr(self._listener, "_msgs_dict", self._msgs_dict)
        except Exception:
            pass
        await self._listener.on_upload_complete(
            None, self._msgs_dict, self._total_files, self._corrupted
        )

    async def _add_buttons_to_message(self, message, editing_client):
        if not message or not editing_client:
            return

        buttons = ButtonMaker()

        # Stream/Download Buttons
        raw_enable_stream = self._listener.user_dict.get(
            "ENABLE_STREAM_LINK", Config.ENABLE_STREAM_LINK
        )
        if str(raw_enable_stream).lower() in ("true", "1", "yes"):
            try:
                from ...stream_utils.file_properties import gen_link

                stream_link, dl_link = gen_link(message)
                if stream_link:
                    buttons.url_button("Stream", stream_link)
                if dl_link:
                    buttons.url_button("Download", dl_link)
            except Exception as e:
                LOGGER.error(f"StreamButton: Failed during link generation: {e}")

        # Media Info Button
        if self._listener.user_dict.get("SHOW_MEDIAINFO_BUTTON", True):
            media_obj_original = message.document or message.video or message.audio
            if media_obj_original:
                try:
                    telegraph_link = await get_mediainfo_telegraph_link(
                        media_obj_original,
                        message,
                        None,
                        self._current_display_filename,
                    )
                    if telegraph_link:
                        buttons.url_button("Media Info", telegraph_link)
                except Exception as e:
                    LOGGER.error(f"MediaInfoButton: Failed to generate link: {e}")

        if buttons.buttons:
            try:
                button_markup = buttons.build_menu(2)
                await editing_client.edit_message_reply_markup(
                    chat_id=message.chat.id,
                    message_id=message.id,
                    reply_markup=button_markup,
                )
            except MessageNotModified:
                pass
            except Exception as e:
                LOGGER.error(f"ButtonMarkup: Failed to edit message {message.id}: {e}")

    async def send_to_user_dump(self, sent_to_chats_for_current_file):
        if not self._sent_msg:
            return
        target_chat_id_str = self._listener.user_dict.get("LEECH_DUMP_CHAT")
        if not target_chat_id_str:
            return

        # Parse chat_id|topic_id format using helper
        try:
            target_chat_id, topic_id = self._parse_chat_id(target_chat_id_str)
        except (ValueError, TypeError):
            LOGGER.error(
                f"Invalid chat ID format in user LEECH_DUMP_CHAT: {target_chat_id_str}"
            )
            return

        if (target_chat_id, topic_id) in sent_to_chats_for_current_file:
            return
        bot_client = self._listener.client
        try:
            new_dump_msg = await bot_client.copy_message(
                chat_id=target_chat_id,
                from_chat_id=self._sent_msg.chat.id,
                message_id=self._sent_msg.id,
                reply_to_message_id=None,
                disable_notification=True,
                message_thread_id=topic_id,
            )
            if new_dump_msg:
                sent_to_chats_for_current_file.add((target_chat_id, topic_id))
                await self._add_buttons_to_message(new_dump_msg, bot_client)
        except Exception as e:
            LOGGER.error(f"Error in send_to_user_dump: {e}", exc_info=True)

    async def send_to_dm(self, sent_to_chats_for_current_file):
        if not self._sent_msg or not self._dm_msg:
            return
        target_chat_id = self._listener.user_id
        if (target_chat_id, None) in sent_to_chats_for_current_file:
            return
        pm_client = TgClient.bot

        if self._sent_msg.chat.id == target_chat_id:
            sent_to_chats_for_current_file.add((target_chat_id, None))
            await self._add_buttons_to_message(self._sent_msg, pm_client)
            return

        retries = 3
        retry_delay = 2
        new_dm_message = None

        for attempt in range(retries):
            try:
                new_dm_message = await pm_client.copy_message(
                    chat_id=target_chat_id,
                    from_chat_id=self._sent_msg.chat.id,
                    message_id=self._sent_msg.id,
                    reply_to_message_id=None,
                    disable_notification=True,
                )
                if new_dm_message:
                    LOGGER.info(
                        f"Send to DM: Successfully copied message {self._sent_msg.id} to chat {target_chat_id} on attempt {attempt + 1}."
                    )
                    break
            except FloodWait as fw:
                LOGGER.warning(
                    f"Send to DM: FloodWait for {fw.value}s on message {self._sent_msg.id}. Attempt {attempt + 1}/{retries}."
                )
                if attempt + 1 < retries:
                    await sleep(fw.value + 1)
                else:
                    LOGGER.error(
                        f"Send to DM: FloodWait on final attempt for message {self._sent_msg.id} to chat {target_chat_id}. Giving up."
                    )
                    new_dm_message = None
            except Exception as e:
                source_link = (
                    self._sent_msg.link
                    if hasattr(self._sent_msg, "link")
                    else f"message_id {self._sent_msg.id}"
                )
                LOGGER.error(
                    f"Error in send_to_dm copying {source_link} to {target_chat_id} (attempt {attempt + 1}/{retries}): {e}",
                    exc_info=True,
                )
                if attempt + 1 < retries:
                    await sleep(retry_delay)
                else:
                    LOGGER.error(
                        f"Send to DM: Failed after {retries} attempts for {source_link} to chat {target_chat_id}. Giving up."
                    )
                    new_dm_message = None

        if new_dm_message:
            sent_to_chats_for_current_file.add((target_chat_id, None))
            await self._add_buttons_to_message(new_dm_message, pm_client)
        else:
            source_link = (
                self._sent_msg.link
                if hasattr(self._sent_msg, "link")
                else f"message_id {self._sent_msg.id}"
            )
            LOGGER.warning(
                f"Send to DM: Failed to copy message {source_link} to chat {target_chat_id} after all retries."
            )

    async def send_to_backup_dump(self, sent_to_chats_for_current_file):
        if (
            not self._sent_msg
            or not self._backup_msg
            or not getattr(Config, "BACKUP_DUMP", None)
        ):
            return
        target_chat_id = int(Config.BACKUP_DUMP)
        if (target_chat_id, None) in sent_to_chats_for_current_file:
            return
        bot_client = self._listener.client
        try:
            new_backup_msg = await bot_client.copy_message(
                chat_id=target_chat_id,
                from_chat_id=self._sent_msg.chat.id,
                message_id=self._sent_msg.id,
                reply_to_message_id=None,
                disable_notification=True,
            )
            if new_backup_msg:
                sent_to_chats_for_current_file.add((target_chat_id, None))
                await self._add_buttons_to_message(new_backup_msg, bot_client)
        except Exception as e:
            LOGGER.error(f"Error in send_to_backup_dump: {e}", exc_info=True)

    async def send_to_movie_dump(self, sent_to_chats_for_current_file):
        if (
            not self._sent_msg
            or not self._movie_msg
            or not getattr(Config, "MOVIE_DUMP", None)
        ):
            return
        target_chat_id = int(Config.MOVIE_DUMP)
        if (target_chat_id, None) in sent_to_chats_for_current_file:
            return
        bot_client = self._listener.client
        try:
            new_movie_msg = await bot_client.copy_message(
                chat_id=target_chat_id,
                from_chat_id=self._sent_msg.chat.id,
                message_id=self._sent_msg.id,
                reply_to_message_id=None,
                disable_notification=True,
            )
            if new_movie_msg:
                sent_to_chats_for_current_file.add((target_chat_id, None))
                await self._add_buttons_to_message(new_movie_msg, bot_client)
        except Exception as e:
            LOGGER.error(f"Error in send_to_movie_dump: {e}", exc_info=True)

    async def copy_message_to_chat(self, chat_id, sent_to_chats_for_current_file=None):
        if not self._sent_msg or sent_to_chats_for_current_file is None:
            return

        # Parse chat_id|topic_id format
        dest_chat_id = chat_id
        topic_id = None

        if isinstance(chat_id, str) and "|" in chat_id:
            parts = chat_id.split("|", 1)
            try:
                dest_chat_id = int(parts[0])
                topic_id = int(parts[1]) if parts[1] else None
            except ValueError:
                LOGGER.error(f"Invalid chat ID format in multi_leech_dest: {chat_id}")
                return
        else:
            try:
                dest_chat_id = (
                    int(chat_id)
                    if isinstance(chat_id, str) and chat_id.lstrip("-").isdigit()
                    else chat_id
                )
            except ValueError:
                return

        if Config.LEECH_DUMP_CHAT:
            # Parse global LEECH_DUMP_CHAT to compare with destination
            global_chat_id = Config.LEECH_DUMP_CHAT
            if (
                isinstance(Config.LEECH_DUMP_CHAT, str)
                and "|" in Config.LEECH_DUMP_CHAT
            ):
                global_chat_id = Config.LEECH_DUMP_CHAT.split("|", 1)[0]

            if str(dest_chat_id) == str(global_chat_id).strip():
                try:
                    parsed_leech_dump_chat_id = int(global_chat_id)
                    # Check if already sent to global dump (ignoring topic differences for this check)
                    if (
                        parsed_leech_dump_chat_id,
                        None,
                    ) in sent_to_chats_for_current_file:
                        return
                except ValueError:
                    pass
        if (
            dest_chat_id,
            topic_id,
        ) in sent_to_chats_for_current_file:
            return
        bot_client = self._listener.client
        try:
            copied_msg = await bot_client.copy_message(
                chat_id=dest_chat_id,
                from_chat_id=self._sent_msg.chat.id,
                message_id=self._sent_msg.id,
                disable_notification=True,
                reply_to_message_id=None,
                message_thread_id=topic_id,
            )
            if copied_msg:
                sent_to_chats_for_current_file.add((dest_chat_id, topic_id))
                await self._add_buttons_to_message(copied_msg, bot_client)
        except Exception as e:
            LOGGER.error(
                f"Error in copy_message_to_chat (to {chat_id}): {e}", exc_info=True
            )

    async def delete_from_owner_dump(self, sent_to_chats_for_current_file):
        """
        Delete the file from owner's LEECH_DUMP_CHAT after forwarding to user destinations.
        Only deletes if:
        1. AUTO_DELETE_FROM_OWNER_LEECH_DUMP is enabled
        2. File was originally sent to owner's LEECH_DUMP_CHAT
        3. File was successfully sent to user PM
        4. If user has a personal leech dump set, file must also be sent there
        """
        if not Config.AUTO_DELETE_FROM_OWNER_LEECH_DUMP:
            return

        if not self._owner_dump_messages:
            return

        # Check if file was sent to required destinations
        # File must be sent to user PM AND (if user has dump set, it must be sent there too)

        # First check: File must be sent to user PM
        sent_to_user_pm = (
            self._listener.user_id,
            None,
        ) in sent_to_chats_for_current_file
        if not sent_to_user_pm:
            # Don't delete if file wasn't sent to user PM
            return

        # Second check: If user has a leech dump set, file must be sent there too
        user_leech_dump = self._listener.user_dict.get("LEECH_DUMP_CHAT")
        if user_leech_dump:
            try:
                user_chat_id, user_topic_id = self._parse_chat_id(user_leech_dump)
                sent_to_user_dump = (
                    user_chat_id,
                    user_topic_id,
                ) in sent_to_chats_for_current_file
                if not sent_to_user_dump:
                    # Don't delete if user has dump but file wasn't sent there
                    return
            except (ValueError, TypeError) as e:
                LOGGER.warning(f"Could not parse user leech dump chat ID: {e}")
                # If we can't parse, assume dump requirement is not met
                return

        # Delete messages from owner's LEECH_DUMP_CHAT
        for chat_id, msg_id in self._owner_dump_messages:
            try:
                await TgClient.bot.delete_messages(chat_id=chat_id, message_ids=msg_id)
                LOGGER.info(
                    f"Deleted message {msg_id} from owner's LEECH_DUMP_CHAT (chat {chat_id})"
                )
            except Exception as e:
                LOGGER.error(
                    f"Failed to delete message {msg_id} from owner's dump: {e}"
                )

        # Clear the list after deletion
        self._owner_dump_messages.clear()

    async def _upload_file(self, o_path, sent_to_chats_for_current_file):
        try:
            if self._listener.is_cancelled:
                return

            display_filename = self._current_display_filename or ospath.basename(o_path)
            cap_mono = await self._prepare_file(o_path, display_filename)
            part_suffix_regex = r"\s*\(Part \d+/\d+\)$"
            cap_mono = re.sub(part_suffix_regex, "", cap_mono)
            self._up_path = o_path

            if not await aiopath.exists(self._up_path):
                LOGGER.error(f"File to upload does not exist: {self._up_path}")
                self._corrupted += 1
                return

            await self._send_file(
                cap_mono,
                self._up_path,
                sent_to_chats_for_current_file,
                force_document=False,
                display_filename=display_filename,
            )

        except Exception as e:
            LOGGER.error(f"Error during the upload of {o_path}: {e}", exc_info=True)
            self._error = str(e)
            raise e

    @retry(
        wait=wait_exponential(multiplier=2, min=5, max=45),
        stop=stop_after_attempt(3),
        retry=retry_if_not_exception_type((FloodWait, FloodPremiumWait, RuntimeError)),
    )
    async def _send_file(
        self,
        cap_mono,
        o_path,
        sent_to_chats_for_current_file,
        force_document=False,
        flood_wait_retry_count=0,
        display_filename=None,
    ):
        if self._thumb is not None and not await aiopath.exists(self._thumb):
            self._thumb = None
        thumb = self._thumb
        self._is_corrupted = False
        downloaded_tmdb_thumb_path = None
        user_dict = self._listener.user_dict

        # Use the explicitly passed filename or basename.
        # Limit only the filename length (preserve extension); do not alter captions.
        final_filename = display_filename or ospath.basename(o_path)

        def _truncate_filename_preserve_ext(name: str, max_len: int = 60) -> str:
            try:
                if not isinstance(name, str):
                    return name
                if len(name) <= max_len:
                    return name
                base, ext = ospath.splitext(name)
                # Ensure at least 1 char remains for base
                allowed = max(1, max_len - len(ext))
                return f"{base[:allowed]}{ext}"
            except Exception:
                return name[:max_len]

        final_filename = _truncate_filename_preserve_ext(final_filename)

        is_custom_thumb_present = False
        if thumb and thumb != "none" and await aiopath.exists(thumb):
            is_custom_thumb_present = True
        client_to_use = (
            TgClient.user
            if self._user_session and TgClient.user
            else (self._listener.client or TgClient.bot)
        )
        actual_chat_id, actual_topic_id = None, None
        if Config.LEECH_TO_PM_ONLY and not Config.LEECH_DUMP_CHAT:
            actual_chat_id, actual_topic_id = self._listener.user_id, None
        elif Config.LEECH_DUMP_CHAT:
            # Parse global LEECH_DUMP_CHAT for topic ID support
            if (
                isinstance(Config.LEECH_DUMP_CHAT, str)
                and "|" in Config.LEECH_DUMP_CHAT
            ):
                parts = Config.LEECH_DUMP_CHAT.split("|", 1)
                try:
                    actual_chat_id = int(parts[0])
                    actual_topic_id = int(parts[1]) if parts[1] else None
                except ValueError:
                    LOGGER.error(
                        f"Invalid global LEECH_DUMP_CHAT format: {Config.LEECH_DUMP_CHAT}"
                    )
                    actual_chat_id = int(Config.LEECH_DUMP_CHAT)
                    actual_topic_id = None
            else:
                actual_chat_id = int(Config.LEECH_DUMP_CHAT)
                actual_topic_id = None
        elif self._upload_dest:
            actual_chat_id, actual_topic_id = self._upload_dest, self._topic_id
        elif self._listener.message and self._listener.message.chat:
            actual_chat_id, actual_topic_id = (
                self._listener.message.chat.id,
                self._listener.message.message_thread_id,
            )
        else:
            raise ValueError("Cannot determine target chat_id for upload.")
        try:
            is_video, is_audio, is_image = await get_document_type(o_path)
            key = ""

            is_part_of_split_video = False
            if re_match(r".+\.part\d{3}\..+", final_filename):
                original_ext = ospath.splitext(final_filename.split(".part")[0])[
                    -1
                ].lower()
                if original_ext in [
                    ".mkv",
                    ".mp4",
                    ".avi",
                    ".mov",
                    ".webm",
                    ".ts",
                    ".flv",
                    ".wmv",
                ]:
                    is_part_of_split_video = True

            if (
                self._listener.as_doc
                or force_document
                or (
                    (not is_video and not is_audio and not is_image)
                    and not is_part_of_split_video
                )
            ):
                key = "documents"
                if (is_video or is_part_of_split_video) and not is_custom_thumb_present:
                    if user_dict.get("AUTO_THUMBNAIL", False) and Config.TMDB_API_KEY:
                        try:
                            cleaned_title, extracted_year = (
                                extract_tmdb_info_for_search(final_filename)
                            )
                            tmdb_data = await fetch_tmdb_data(
                                title=cleaned_title,
                                year=extracted_year,
                                image_type=user_dict.get(
                                    "TMDB_THUMBNAIL_TYPE", "poster"
                                ),
                            )
                            if tmdb_data and tmdb_data.get("image_url"):
                                async with aiohttp.ClientSession() as http_session:
                                    async with http_session.get(
                                        tmdb_data["image_url"]
                                    ) as resp:
                                        if resp.status == 200:
                                            fd, downloaded_tmdb_thumb_path = (
                                                tempfile.mkstemp(
                                                    suffix=".jpg",
                                                    prefix=f"tmdb_thumb_{self._listener.mid}_",
                                                )
                                            )
                                            async with aiofiles.open(
                                                downloaded_tmdb_thumb_path, "wb"
                                            ) as f_thumb:
                                                await f_thumb.write(await resp.read())
                                            thumb = downloaded_tmdb_thumb_path
                                            is_custom_thumb_present = True
                        except Exception:
                            pass
                    if not is_custom_thumb_present:
                        thumb = await get_video_thumbnail(o_path, None)
                        if thumb:
                            is_custom_thumb_present = True
                if self._listener.is_cancelled:
                    if downloaded_tmdb_thumb_path and await aiopath.exists(
                        downloaded_tmdb_thumb_path
                    ):
                        await remove(downloaded_tmdb_thumb_path)
                    return
                new_message = await client_to_use.send_document(
                    chat_id=actual_chat_id,
                    document=o_path,
                    thumb=thumb,
                    caption=cap_mono,
                    file_name=final_filename,
                    force_document=True,
                    disable_notification=True,
                    progress=self._upload_progress,
                    parse_mode=ParseMode.HTML,
                    reply_to_message_id=None,
                    message_thread_id=actual_topic_id,
                )
            elif is_video or is_part_of_split_video:
                key = "videos"
                duration, width, height = 0, 0, 0
                try:
                    media_info_tuple = await get_media_info(o_path)
                    duration = media_info_tuple[0] if media_info_tuple else 0
                except Exception as e:
                    LOGGER.warning(
                        f"Could not get media_info (duration) for video part {o_path}: {e}"
                    )

                if not is_custom_thumb_present:
                    if user_dict.get("AUTO_THUMBNAIL", False) and Config.TMDB_API_KEY:
                        try:
                            cleaned_title, extracted_year = (
                                extract_tmdb_info_for_search(final_filename)
                            )
                            tmdb_data = await fetch_tmdb_data(
                                title=cleaned_title,
                                year=extracted_year,
                                image_type=user_dict.get(
                                    "TMDB_THUMBNAIL_TYPE", "poster"
                                ),
                            )
                            if tmdb_data and tmdb_data.get("image_url"):
                                async with aiohttp.ClientSession() as http_session:
                                    async with http_session.get(
                                        tmdb_data["image_url"]
                                    ) as resp:
                                        if resp.status == 200:
                                            fd, downloaded_tmdb_thumb_path = (
                                                tempfile.mkstemp(
                                                    suffix=".jpg",
                                                    prefix=f"tmdb_thumb_{self._listener.mid}_",
                                                )
                                            )
                                            async with aiofiles.open(
                                                downloaded_tmdb_thumb_path, "wb"
                                            ) as f_thumb:
                                                await f_thumb.write(await resp.read())
                                            thumb = downloaded_tmdb_thumb_path
                                            is_custom_thumb_present = True
                        except Exception:
                            pass
                    if not is_custom_thumb_present:
                        thumb = await get_video_thumbnail(o_path, duration)
                        if thumb:
                            is_custom_thumb_present = True
                width, height = (
                    Image.open(thumb).size
                    if thumb and await aiopath.exists(thumb)
                    else (480, 320)
                )
                if self._listener.is_cancelled:
                    if downloaded_tmdb_thumb_path and await aiopath.exists(
                        downloaded_tmdb_thumb_path
                    ):
                        await remove(downloaded_tmdb_thumb_path)
                    return
                new_message = await client_to_use.send_video(
                    chat_id=actual_chat_id,
                    video=o_path,
                    caption=cap_mono,
                    duration=duration,
                    width=width,
                    height=height,
                    thumb=thumb,
                    file_name=final_filename,
                    supports_streaming=True,
                    disable_notification=True,
                    progress=self._upload_progress,
                    parse_mode=ParseMode.HTML,
                    reply_to_message_id=None,
                    message_thread_id=actual_topic_id,
                )
            elif is_audio:
                key = "audios"
                duration, artist, title = await get_media_info(o_path)
                if self._listener.is_cancelled:
                    return
                new_message = await client_to_use.send_audio(
                    chat_id=actual_chat_id,
                    audio=o_path,
                    caption=cap_mono,
                    duration=duration,
                    performer=artist,
                    title=title,
                    thumb=thumb,
                    file_name=final_filename,
                    disable_notification=True,
                    progress=self._upload_progress,
                    parse_mode=ParseMode.HTML,
                    reply_to_message_id=None,
                    message_thread_id=actual_topic_id,
                )
            else:
                key = "photos"
                if self._listener.is_cancelled:
                    return
                new_message = await client_to_use.send_photo(
                    chat_id=actual_chat_id,
                    photo=o_path,
                    caption=cap_mono,
                    disable_notification=True,
                    progress=self._upload_progress,
                    parse_mode=ParseMode.HTML,
                    reply_to_message_id=None,
                    message_thread_id=actual_topic_id,
                )

            if new_message:
                self._sent_msg = new_message
                sent_to_chats_for_current_file.add((actual_chat_id, actual_topic_id))

                # Track if this was sent to owner's LEECH_DUMP_CHAT for potential deletion
                if Config.LEECH_DUMP_CHAT:
                    try:
                        owner_dump_chat_id, _ = self._parse_chat_id(
                            Config.LEECH_DUMP_CHAT
                        )
                        if int(actual_chat_id) == int(owner_dump_chat_id):
                            self._owner_dump_messages.append(
                                (new_message.chat.id, new_message.id)
                            )
                    except (ValueError, TypeError) as e:
                        LOGGER.warning(
                            f"Could not parse owner dump chat ID for tracking: {e}"
                        )
            else:
                raise RPCError("Upload send operation returned None.")

            if (
                not self._listener.is_cancelled
                and self._media_group
                and (self._sent_msg.video or self._sent_msg.document)
            ):
                match_group = re_match(
                    r".+(?=\.0*\d+$)|.+(?=\.part\d+\..+$)", ospath.basename(o_path)
                )
                if match_group:
                    pname = match_group.group(0)
                    current_msg_data = [self._sent_msg.chat.id, self._sent_msg.id]
                    if pname not in self._media_dict[key]:
                        self._media_dict[key][pname] = []
                    self._media_dict[key][pname].append(current_msg_data)
                    if len(self._media_dict[key][pname]) == 10:
                        await self._send_media_group(
                            pname, key, self._media_dict[key][pname]
                        )
                    else:
                        self._last_msg_in_group = True

            if thumb and await aiopath.exists(thumb):
                user_default_thumb = f"thumbnails/{self._listener.user_id}.jpg"
                if not (ospath.abspath(thumb) == ospath.abspath(user_default_thumb)):
                    await remove(thumb)

            if self._sent_msg:
                await self._add_buttons_to_message(self._sent_msg, client_to_use)
        except (FloodWait, FloodPremiumWait) as f:
            flood_wait_retry_count += 1
            LOGGER.warning(
                f"FloodWait encountered: {f}. Retry attempt {flood_wait_retry_count}/20"
            )

            if flood_wait_retry_count > 20:
                LOGGER.error(
                    f"FloodWait retry limit exceeded (20 attempts) for file: {o_path}"
                )
                raise f

            await sleep(f.value * 1.3)
            if downloaded_tmdb_thumb_path and await aiopath.exists(
                downloaded_tmdb_thumb_path
            ):
                try:
                    await remove(downloaded_tmdb_thumb_path)
                except Exception:
                    pass
            return await self._send_file(
                cap_mono,
                o_path,
                sent_to_chats_for_current_file,
                force_document,
                flood_wait_retry_count,
                display_filename,
            )
        except Exception as err:
            if downloaded_tmdb_thumb_path and await aiopath.exists(
                downloaded_tmdb_thumb_path
            ):
                try:
                    await remove(downloaded_tmdb_thumb_path)
                except Exception:
                    pass

            if isinstance(err, RuntimeError) and "can't start new thread" in str(err):
                LOGGER.error(
                    f"Thread exhaustion error for file {o_path}. This indicates system resource limits have been reached."
                )
                LOGGER.error(
                    "Possible solutions: reduce concurrent uploads, check system thread limits, or restart the application."
                )
                raise err

            err_type = "RPCError: " if isinstance(err, RPCError) else ""
            LOGGER.error(f"{err_type}{err}. Path: {o_path}", exc_info=True)
            if isinstance(err, BadRequest) and key != "documents":
                LOGGER.error(f"Retrying As Document. Path: {o_path}")
                return await self._send_file(
                    cap_mono,
                    o_path,
                    sent_to_chats_for_current_file,
                    True,
                    flood_wait_retry_count,
                    display_filename,
                )
            raise err

    @property
    def speed(self):
        try:
            return self._processed_bytes / (time() - self._start_time)
        except ZeroDivisionError:
            return 0

    @property
    def processed_bytes(self):
        return self._processed_bytes

    async def cancel_task(self):
        self._listener.is_cancelled = True
        LOGGER.info(f"Cancelling Upload: {self._listener.name}")
        await self._listener.on_upload_error("Your upload has been stopped!")
