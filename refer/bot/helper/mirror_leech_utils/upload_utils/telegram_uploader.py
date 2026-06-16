from asyncio import sleep
from logging import getLogger
from os import path as ospath, walk
from time import time
import re
from re import match as re_match, sub as re_sub
import requests
from io import BytesIO
import openai

from aioshutil import rmtree
from natsort import natsorted
from PIL import Image
from pyrogram.errors import BadRequest, FloodWait, RPCError

try:
    from pyrogram.errors import FloodPremiumWait
except ImportError:
    FloodPremiumWait = FloodWait
from aiofiles.os import (
    path as aiopath,
    remove,
    rename,
)
from pyrogram.types import (
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
)
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ....core.config_manager import Config
from ....core.tg_client import TgClient
from ...ext_utils.bot_utils import sync_to_async
from ...ext_utils.files_utils import get_base_name, is_archive
from ...ext_utils.status_utils import (
    get_readable_file_size,
    get_readable_time,
    MirrorStatus,
)
from ...ext_utils.media_utils import (
    get_audio_thumbnail,
    get_document_type,
    get_media_info,
    get_multiple_frames_thumbnail,
    get_video_thumbnail,
    get_md5_hash,
)
from ...ext_utils.metadata_helper import apply_metadata
from ...ext_utils.metadata_helper import embed_cover_art
from ...telegram_helper.message_utils import delete_message
from ....modules.imdb import get_poster

LOGGER = getLogger(__name__)


# Extract media info from filename
def extract_media_info(filename):
    import urllib.parse

    filename = urllib.parse.unquote(filename)
    filename = re.sub(r"www\S+", "", filename)
    filename = re.sub(r"\.[a-zA-Z0-9]{2,4}$", "", filename)
    filename = re.sub(r"[\._\-]+", " ", filename)
    filename = re.sub(r"\[.*?\]", "", filename)
    filename = re.sub(r"\s+", " ", filename).strip()
    filename = re.sub(r"^[@/\\]\w+\s*", "", filename)
    translations = {
        "Эпизод": "E",
        "エピソード": "E",
        "Saison": "Season",
        "Volumen": "Vol",
        "Часть": "Part",
    }
    for key, val in translations.items():
        filename = filename.replace(key, val)
    pattern = re.compile(
        r"""
        (?P<name>.*?)\s*
        (?:\((?P<year>\d{4})\)|
            (?P<year_alt>\d{4})|
            S(?P<season>\d{1,2})E(?P<episode>\d{1,3})|
            S(?P<season2>\d{1,2})|
            Season\s*(?P<season3>\d{1,2})|
            Episode\s*(?P<episode2>\d{1,3})|
            Part\s*(?P<part>\d{1,2})|
            Vol\s*(?P<volume>\d{1,2})
        )
        """,
        re.VERBOSE | re.IGNORECASE,
    )
    match = pattern.search(filename)
    if match:
        name = match.group("name").strip()
        name = re.sub(
            r"\b(480p|720p|1080p|Hindi|WEB DL|x264|AAC|Zee5|BluRay|HDRip|HQ|DD\+5 1|DD\+5|5 1|192Kbps|Tamil|English|HEVC|H264|10bit|NF|AMZN|WEBRip|DVDRip|UNCUT|Dual Audio|Esubs|Atmos|DTS|TrueHD|Multi|AAC2 0|AAC5 1|AC3|ESub|Subs|Opus|FLAC|MP3|MPEG|AVC|Remux|Proper|Repack|Complete|Limited|Exclusive|Prime|Hotstar|Disney|Netflix|SonyLiv|MXPlayer|Voot|ALTBalaji|Ullu|Kooku|PrimeShots|RabbitMovies|BigMovieZoo|BoomMovies|Voovi|Besharams|MoodX|XPrime|Cineprime|PrimePlay|HuntCinema|DigiMovieplex|Wow|FlizMovies|Balloon|Stream|HD|SD|CAMRip|TS|PreDVD|PreRip|Line Audio|Cleaned|Sample|Trailer|South Movie ORG|Movie ORG)\b",
            "",
            name,
            flags=re.IGNORECASE,
        )
        name = re.sub(r"\s+", " ", name).strip()
        year = match.group("year") or match.group("year_alt")
        season = (
            match.group("season")
            or match.group("season2")
            or match.group("season3")
            or None
        )
        episode = match.group("episode") or match.group("episode2") or None
        part = match.group("part") or None
        volume = match.group("volume") or None
        return name, season, episode, year, part, volume
    return None, None, None, None, None, None


# TMDB poster fetch utility (module-level)
def fetch_tmdb_poster(title, year=None):
    """Fetch a 16:9 TMDB poster (w780 or original) for the given title/year."""
    TMDB_API_KEY = getattr(Config, "TMDB_API_KEY", "")
    if not TMDB_API_KEY:
        LOGGER.warning(
            "TMDB_API_KEY not set in config. Auto Thumbnail feature requires a valid API key."
        )
        return None
    try:
        # First, try with both title and year (year as filter, not in title)
        poster = _search_tmdb(title, year, "movie", TMDB_API_KEY)
        if poster:
            return poster
        # If not found, try with just the title (no year filter)
        poster = _search_tmdb(title, None, "movie", TMDB_API_KEY)
        if poster:
            return poster
        # If still not found, try TV show search as fallback
        poster = _search_tmdb(title, None, "tv", TMDB_API_KEY)
        if poster:
            return poster
    except Exception as e:
        LOGGER.error(f"TMDB poster fetch failed: {e}")
    return None


def _search_tmdb(title, year, media_type, api_key):
    """Helper function to search TMDB for both movies and TV shows"""
    search_url = f"https://api.themoviedb.org/3/search/{media_type}"
    poster_base = "https://image.tmdb.org/t/p/"
    params = {"api_key": api_key, "query": title}

    if year and media_type == "movie":
        params["year"] = year

    resp = requests.get(search_url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    if data["results"]:
        item = data["results"][0]

        # Try to get backdrop first (landscape, any aspect ratio)
        if item.get("backdrop_path"):
            for size in ["w780", "original"]:
                try:
                    poster_url = poster_base + size + item["backdrop_path"]
                    img_resp = requests.get(poster_url, timeout=10)
                    img_resp.raise_for_status()
                    return BytesIO(img_resp.content)
                except Exception:
                    continue

        # Fall back to poster if no backdrop
        if item.get("poster_path"):
            try:
                poster_url = poster_base + "original" + item["poster_path"]
                img_resp = requests.get(poster_url, timeout=10)
                img_resp.raise_for_status()
                return BytesIO(img_resp.content)
            except Exception:
                pass

    return None


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
        self._lprefix = ""
        self._lsuffix = ""
        self._lcaption = ""
        self._lfont = ""
        self._bot_pm = False
        self._media_group = False
        self._is_private = False
        self._sent_msg = None
        self._log_msg = None
        self._instant_forwarder = (
            None  # Will be initialized in _user_settings if needed
        )
        self._user_session = self._listener.user_transmission
        self._error = ""
        self._status = None  # Track current status for progress/status bar
        self._metadata_progress = 0  # Track metadata progress (0-100)
        # Track original base message so we can safely re-fetch even if self._sent_msg becomes None
        self._base_chat_id = None
        self._base_msg_id = None

    async def _upload_progress(self, current, _):
        if self._listener.is_cancelled:
            if self._user_session and TgClient.user:
                TgClient.user.stop_transmission()
            elif hasattr(self._listener, "client"):
                self._listener.client.stop_transmission()
        chunk_size = current - self._last_uploaded
        self._last_uploaded = current
        self._processed_bytes += chunk_size

    async def _user_settings(self):
        settings_map = {
            "MEDIA_GROUP": ("_media_group", False),
            "BOT_PM": ("_bot_pm", False),
            "FILENAME_PREFIX": ("_lprefix", ""),  # New universal prefix
            "FILENAME_SUFFIX": ("_lsuffix", ""),  # New universal suffix
            "LEECH_CAPTION": ("_lcaption", ""),
            "LEECH_FONT": ("_lfont", ""),
        }

        for key, (attr, default) in settings_map.items():
            value = self._listener.user_dict.get(key) or getattr(Config, key, default)

            # Backward compatibility: fall back to LEECH_PREFIX/SUFFIX if FILENAME_PREFIX/SUFFIX not set
            if key == "FILENAME_PREFIX" and not value:
                value = self._listener.user_dict.get("LEECH_PREFIX") or getattr(
                    Config, "LEECH_PREFIX", default
                )
            elif key == "FILENAME_SUFFIX" and not value:
                value = self._listener.user_dict.get("LEECH_SUFFIX") or getattr(
                    Config, "LEECH_SUFFIX", default
                )

            setattr(self, attr, value)
        if self._thumb != "none" and not await aiopath.exists(self._thumb):
            self._thumb = None
            # Always use LEECH_DUMP_CHAT for all files if it's configured
        self.use_leech_dump = bool(Config.LEECH_DUMP_CHAT)
        # Sequential processing is always enabled
        self.use_sequential_processing = True

        # Initialize the sequential processor if using LEECH_DUMP_CHAT
        if self.use_leech_dump and Config.LEECH_DUMP_CHAT:
            from ..upload_utils.sequential_processor import SequentialProcessor

            self._sequential_processor = SequentialProcessor(self._listener)
        else:
            self._sequential_processor = None

    async def _msg_to_reply(
        self,
    ):  # If LEECH_DUMP_CHAT is set, always send files there first
        if self.use_leech_dump and Config.LEECH_DUMP_CHAT:
            up_dest = Config.LEECH_DUMP_CHAT
            # Store original destination to use later when forwarding files
            if hasattr(self._listener, "up_dest") and self._listener.up_dest:
                self._original_up_dest = (
                    self._listener.up_dest
                )  # Temporarily change the listener's destination to LEECH_DUMP_CHAT
                self._listener._up_dest_original = self._listener.up_dest
                # Actually update the destination to LEECH_DUMP_CHAT
                self._listener.up_dest = up_dest
                LOGGER.info(
                    f"Original destination saved: {self._original_up_dest}, set current to: {up_dest}"
                )
            else:
                # If the listener doesn't have an up_dest, use the chat where command was sent
                if hasattr(self._listener, "message") and hasattr(
                    self._listener.message, "chat"
                ):
                    self._original_up_dest = self._listener.message.chat.id
                    LOGGER.info(
                        f"Using command chat as original destination: {self._original_up_dest}"
                    )
                else:
                    self._original_up_dest = None
                    LOGGER.info("No original destination found in listener")

            msg_link = (
                self._listener.message.link if self._listener.is_super_chat else ""
            )
            msg = f"""» <b><u>Leech Started :</u></b>
┊
┊<b>User :</b> {self._listener.user.mention} ( #ID{self._listener.user_id} ){f"\n┊<b>Message Link :</b> <a href='{msg_link}'>Click Here</a>" if msg_link else ""}
╰<b>Source :</b> <a href='{self._listener.source_url}'>Click Here</a>"""
            try:
                self._log_msg = await TgClient.bot.send_message(
                    chat_id=up_dest,
                    text=msg,
                    disable_web_page_preview=True,
                    message_thread_id=getattr(self._listener, "chat_thread_id", None),
                    disable_notification=True,
                )
                self._sent_msg = self._log_msg
                # Store base ids for future safe retrieval
                self._base_chat_id = self._sent_msg.chat.id
                self._base_msg_id = self._sent_msg.id
                if self._user_session:
                    try:
                        self._sent_msg = await TgClient.user.get_messages(
                            chat_id=self._sent_msg.chat.id,
                            message_ids=self._sent_msg.id,
                        )
                        # When using LEECH_DUMP_CHAT, _is_private should be based on original destination, not dump chat
                        if hasattr(self, "_original_up_dest"):
                            original_dest = self._original_up_dest
                            if isinstance(original_dest, (int, str)) and original_dest:
                                # For user IDs (private chats), they are typically positive integers < 1000000000
                                # For supergroups/channels, they start with -100
                                if (
                                    isinstance(original_dest, int)
                                    and original_dest > 0
                                    and original_dest < 1000000000
                                ):
                                    self._is_private = True
                                elif (
                                    isinstance(original_dest, str)
                                    and original_dest.strip()
                                    and not original_dest.startswith("-")
                                    and not original_dest.startswith("@")
                                ):
                                    self._is_private = True
                                else:
                                    self._is_private = False
                            else:
                                self._is_private = False
                            LOGGER.info(
                                f"Set _is_private={self._is_private} based on original destination: {original_dest}"
                            )
                        else:
                            # If no original destination, assume not private
                            self._is_private = False
                        LOGGER.info(
                            f"Retrieved message via user session in LEECH_DUMP_CHAT"
                        )
                    except Exception as e:
                        LOGGER.error(
                            f"Failed to retrieve message via user session in LEECH_DUMP_CHAT: {e}"
                        )
                        # Fall back to setting _is_private based on original destination
                        if hasattr(self, "_original_up_dest"):
                            original_dest = self._original_up_dest
                            if isinstance(original_dest, (int, str)) and original_dest:
                                if (
                                    isinstance(original_dest, int)
                                    and original_dest > 0
                                    and original_dest < 1000000000
                                ):
                                    self._is_private = True
                                elif (
                                    isinstance(original_dest, str)
                                    and original_dest.strip()
                                    and not original_dest.startswith("-")
                                    and not original_dest.startswith("@")
                                ):
                                    self._is_private = True
                                else:
                                    self._is_private = False
                            else:
                                self._is_private = False
                        else:
                            self._is_private = False
                else:
                    # For bot session in LEECH_DUMP_CHAT, also use original destination logic
                    if hasattr(self, "_original_up_dest"):
                        original_dest = self._original_up_dest
                        if isinstance(original_dest, (int, str)) and original_dest:
                            if (
                                isinstance(original_dest, int)
                                and original_dest > 0
                                and original_dest < 1000000000
                            ):
                                self._is_private = True
                            elif (
                                isinstance(original_dest, str)
                                and original_dest.strip()
                                and not original_dest.startswith("-")
                                and not original_dest.startswith("@")
                            ):
                                self._is_private = True
                            else:
                                self._is_private = False
                        else:
                            self._is_private = False
                    else:
                        self._is_private = False
            except Exception as e:
                await self._listener.on_upload_error(str(e))
                return False
        elif self._listener.up_dest:
            msg_link = (
                self._listener.message.link if self._listener.is_super_chat else ""
            )
            msg = f"""» <b><u>Leech Started :</u></b>
┊
┊<b>User :</b> {self._listener.user.mention} ( #ID{self._listener.user_id} ){f"\n┊<b>Message Link :</b> <a href='{msg_link}'>Click Here</a>" if msg_link else ""}
╰<b>Source :</b> <a href='{self._listener.source_url}'>Click Here</a>"""
            try:
                self._log_msg = await TgClient.bot.send_message(
                    chat_id=self._listener.up_dest,
                    text=msg,
                    disable_web_page_preview=True,
                    message_thread_id=self._listener.chat_thread_id,
                    disable_notification=True,
                )
                self._sent_msg = self._log_msg
                self._base_chat_id = self._sent_msg.chat.id
                self._base_msg_id = self._sent_msg.id
                if self._user_session:
                    try:
                        self._sent_msg = await TgClient.user.get_messages(
                            chat_id=self._sent_msg.chat.id,
                            message_ids=self._sent_msg.id,
                        )
                        # Ensure _is_private is set for user session messages
                        self._is_private = self._sent_msg.chat.type.name == "PRIVATE"
                        LOGGER.info(
                            f"Retrieved message via user session for listener up_dest"
                        )
                    except Exception as e:
                        LOGGER.error(
                            f"Failed to retrieve message via user session for listener up_dest: {e}"
                        )
                        # Fall back to setting _is_private from original message
                        self._is_private = self._sent_msg.chat.type.name == "PRIVATE"
                else:
                    self._is_private = self._sent_msg.chat.type.name == "PRIVATE"
            except Exception as e:
                await self._listener.on_upload_error(str(e))
                return False

        elif self._user_session:
            self._sent_msg = await TgClient.user.get_messages(
                chat_id=self._listener.message.chat.id, message_ids=self._listener.mid
            )
            if self._sent_msg is None:
                self._sent_msg = await TgClient.user.send_message(
                    chat_id=self._listener.message.chat.id,
                    text="Deleted Cmd Message! Don't delete the cmd message again!",
                    disable_web_page_preview=True,
                    disable_notification=True,
                )
            self._base_chat_id = self._sent_msg.chat.id
            self._base_msg_id = self._sent_msg.id
        else:
            self._sent_msg = self._listener.message
            if self._sent_msg is not None:
                self._base_chat_id = self._sent_msg.chat.id
                self._base_msg_id = self._sent_msg.id
        return True

    async def _ensure_base_message(self):
        """Ensure we have a valid base message reference; reconstruct if possible."""
        if self._sent_msg is not None:
            if self._base_chat_id is None:
                try:
                    self._base_chat_id = self._sent_msg.chat.id
                    self._base_msg_id = self._sent_msg.id
                except AttributeError:
                    # Will attempt reconstruction below
                    self._sent_msg = None
        if self._sent_msg is None:
            # Try log message first
            candidate = getattr(self, "_log_msg", None) or getattr(
                self._listener, "message", None
            )
            if candidate is not None:
                self._sent_msg = candidate
                try:
                    self._base_chat_id = self._sent_msg.chat.id
                    self._base_msg_id = self._sent_msg.id
                except AttributeError:
                    LOGGER.error(
                        "Candidate message lacks chat/id attributes; cannot set base ids"
                    )
                    return False
            else:
                LOGGER.error(
                    "Unable to reconstruct base message; _sent_msg remains None"
                )
                return False
        return True

    async def _refresh_sent_msg(self, prefer_user_session: bool):
        """Attempt to refresh self._sent_msg using stored base ids.

        Falls back gracefully if user session retrieval fails.
        """
        if not await self._ensure_base_message():
            return False
        chat_id = self._base_chat_id
        msg_id = self._base_msg_id
        if chat_id is None or msg_id is None:
            LOGGER.error("Base chat/message id missing; cannot refresh sent message")
            return False
        if prefer_user_session and TgClient.user:
            try:
                self._sent_msg = await TgClient.user.get_messages(
                    chat_id=chat_id, message_ids=msg_id
                )
                return True
            except Exception as e:
                LOGGER.error(
                    f"User session get_messages failed: {e}; falling back to bot client if available"
                )
        # Fallback to listener client (bot)
        try:
            if hasattr(self._listener, "client") and self._listener.client:
                self._sent_msg = await self._listener.client.get_messages(
                    chat_id=chat_id, message_ids=msg_id
                )
                return True
        except Exception as e:
            LOGGER.error(f"Bot client get_messages fallback failed: {e}")
        return False

    async def _prepare_file(self, pre_file_, dirpath):
        cap_file_ = file_ = pre_file_

        # --- FILENAME PATTERN REMOVAL ---
        # Apply pattern removal first, before any other renaming logic
        if (
            hasattr(self._listener, "remname_patterns")
            and self._listener.remname_patterns
        ):
            from ...ext_utils.filename_utils import apply_filename_patterns

            user_dict = getattr(self._listener, "user_dict", {})
            file_ = apply_filename_patterns(
                file_, self._listener.remname_patterns, user_dict
            )
            cap_file_ = file_  # Update caption file name too

            # If filename changed, update the actual file path
            if file_ != pre_file_:
                old_path = ospath.join(dirpath, pre_file_)
                new_path = ospath.join(dirpath, file_)
                if await aiopath.exists(old_path):
                    await rename(old_path, new_path)
                    self._up_path = new_path
        # --- END FILENAME PATTERN REMOVAL ---

        # --- AUTO RENAME LOGIC ---
        import re  # Import re module for both auto-rename logic and clean_filename_for_title function

        user_dict = getattr(self._listener, "user_dict", {})
        auto_rename = user_dict.get("AUTO_RENAME", False)
        template = user_dict.get("RENAME_TEMPLATE", "S{season}E{episode}Q{quality}")
        episode = int(
            user_dict.get("_CURRENT_EPISODE", user_dict.get("START_EPISODE", 1))
        )
        season = int(user_dict.get("START_SEASON", 1))
        imdb_data = {}
        if auto_rename:
            up_path = ospath.join(dirpath, pre_file_)
            _, quality, *_ = await get_media_info(up_path, True)
            quality = str(quality).replace("p", "") if quality else ""

            # Clean filename to get probable title
            def clean_filename_for_title(filename):
                # Use extract_media_info to get the best title and year
                name, season, episode, year, part, volume = extract_media_info(filename)
                # If we have both name and year, return 'Name Year'
                if name and year:
                    result = f"{name} {year}"
                elif name:
                    result = name
                else:
                    # fallback to old logic if extract_media_info fails
                    name = ospath.splitext(filename)[0]
                    name = re.sub(r"[\[\](){}⟨⟩【】『』“”‘’«»‹›❮❯❰❱❲❳❴❵]", " ", name)
                    name = re.sub(r"\s+", " ", name).strip()
                    result = name if name else "Unknown"
                LOGGER.info(f"Final cleaned title for lookups: '{result}'")
                return result

            probable_title = clean_filename_for_title(pre_file_)
            # Fetch IMDB info
            imdb_info = None
            if probable_title:
                imdb_info = get_poster(probable_title)
            if imdb_info:
                imdb_data = {
                    "title": imdb_info.get("title", ""),
                    "year": imdb_info.get("year", ""),
                    "rating": imdb_info.get("rating", "").replace(" / 10", ""),
                    "genre": imdb_info.get("genres", ""),
                }
            else:
                imdb_data = {
                    "title": probable_title,
                    "year": "",
                    "rating": "",
                    "genre": "",
                }
            # Get audio language(s)
            _, _, lang, _ = await get_media_info(up_path, True)
            audio_count = 0
            audio = lang or ""
            try:
                import json, subprocess

                ffprobe_cmd = [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "a",
                    "-show_entries",
                    "stream=index",
                    "-of",
                    "json",
                    up_path,
                ]
                ffprobe_out = subprocess.run(
                    ffprobe_cmd, capture_output=True, text=True
                )
                if ffprobe_out.returncode == 0:
                    audio_json = json.loads(ffprobe_out.stdout)
                    audio_count = len(audio_json.get("streams", []))
                if audio_count >= 2:
                    audio = "MultiAuD"
            except Exception:
                pass
            # Merge all fields for template - episode will be updated later
            template_fields = dict(
                season=season,
                episode2=episode,  # integer, for E1, E2, ...
                episode=f"{episode:02d}",  # zero-padded, for E01, E02, ...
                quality=quality,
                audio=audio,
                **imdb_data,
            )

            # Check if this is a multi-resolution file (contains pattern like _720p_BL, _480p_BL, etc.)
            is_multi_resolution_file = bool(re.search(r"_\d+p_BL\.", pre_file_))

            # Handle episode numbering for multi-resolution files
            if is_multi_resolution_file:
                # Check if we've already processed a file from this batch
                base_filename = re.sub(
                    r"_\d+p_BL\.", ".", pre_file_
                )  # Remove quality suffix
                batch_key = f"multi_res_batch_{base_filename}"

                # For multi-resolution batch, use the same episode number for all files
                if not user_dict.get(batch_key, False):
                    # First file in batch - increment and store the episode number
                    user_dict["_CURRENT_EPISODE"] = episode + 1
                    user_dict[batch_key] = (
                        episode  # Store the episode number to use for this batch
                    )
                    current_episode = episode  # Use original episode for this batch
                    LOGGER.info(
                        f"Multi-resolution batch detected. Episode {episode} will be used for all files in batch: {base_filename}"
                    )
                else:
                    # Subsequent files in batch - use the same episode number as the first file
                    current_episode = user_dict[batch_key]
                    LOGGER.info(
                        f"Multi-resolution file from same batch, using episode {current_episode}: {pre_file_}"
                    )

                # Clean up old batch keys to prevent memory buildup (keep only recent 50 keys)
                batch_keys = [
                    k for k in user_dict.keys() if k.startswith("multi_res_batch_")
                ]
                if len(batch_keys) > 50:
                    # Remove oldest batch keys (simple cleanup)
                    for key in sorted(batch_keys)[:-50]:
                        user_dict.pop(key, None)

                # Update template fields with correct episode
                template_fields["episode2"] = current_episode
                template_fields["episode"] = f"{current_episode:02d}"
            else:
                # Regular single file - increment episode counter normally
                user_dict["_CURRENT_EPISODE"] = episode + 1
                LOGGER.info(
                    f"Single file processed. Using episode {episode}, next will be {episode + 1}: {pre_file_}"
                )

            new_name = template.format(**template_fields)
            ext = ospath.splitext(file_)[1]
            file_ = f"{new_name}{ext}"

            new_path = ospath.join(dirpath, file_)
            if up_path != new_path and await aiopath.exists(up_path):
                await rename(up_path, new_path)
                self._up_path = new_path
            cap_file_ = file_
        # --- END AUTO RENAME LOGIC ---

        if self._lprefix:
            cap_file_ = self._lprefix.replace(r"\s", " ") + file_
            self._lprefix = re_sub(r"<.*?>", "", self._lprefix).replace(r"\s", " ")
            if not file_.startswith(self._lprefix):
                file_ = f"{self._lprefix}{file_}"

        if self._lsuffix:
            name, ext = ospath.splitext(cap_file_)
            cap_file_ = name + self._lsuffix.replace(r"\s", " ") + ext
            self._lsuffix = re_sub(r"<.*?>", "", self._lsuffix).replace(r"\s", " ")

        cap_mono = (
            f"<{Config.LEECH_FONT}>{cap_file_}</{Config.LEECH_FONT}>"
            if Config.LEECH_FONT
            else cap_file_
        )
        if self._lcaption:
            self._lcaption = re_sub(
                r"(\\\||\\\{|\\\}|\\s)",
                lambda m: {r"\|": "%%", r"\{": "&%&", r"\}": "$%$", r"\s": " "}[
                    m.group(0)
                ],
                self._lcaption,
            )

            parts = self._lcaption.split("|")
            parts[0] = re_sub(
                r"\{([^}]+)\}", lambda m: f"{{{m.group(1).lower()}}}", parts[0]
            )
            up_path = ospath.join(dirpath, pre_file_)
            dur, qual, lang, subs = await get_media_info(up_path, True)
            file_size = get_readable_file_size(await aiopath.getsize(up_path))
            duration = get_readable_time(dur)
            # Try to extract resolution from qual or filename
            resolution = str(qual) if qual else ""
            # Try to extract year from filename
            year_match = re.search(r"(19|20)\\d{2}", pre_file_)
            year = year_match.group(0) if year_match else ""
            # Try to extract ott/platform from filename (NF, AMZN, etc.)
            ott_match = re.search(
                r"(NF|AMZN|DSNP|HMAX|ZEE5|JIO|SONY|APLTV|HULU|YOUTUBE|APPLE)",
                pre_file_,
                re.I,
            )
            ott = ott_match.group(0).upper() if ott_match else ""
            # Audio info: if multiple audio tracks, set to 'MultiAuD', else show language(s)
            audio_count = 0
            audio = lang or ""
            try:
                import json, subprocess

                ffprobe_cmd = [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "a",
                    "-show_entries",
                    "stream=index",
                    "-of",
                    "json",
                    up_path,
                ]
                ffprobe_out = subprocess.run(
                    ffprobe_cmd, capture_output=True, text=True
                )
                if ffprobe_out.returncode == 0:
                    audio_json = json.loads(ffprobe_out.stdout)
                    audio_count = len(audio_json.get("streams", []))
                if audio_count >= 2:
                    audio = "MultiAuD"
            except Exception:
                pass
            # Name (file name without extension)
            name = ospath.splitext(pre_file_)[0]
            # File name with extension
            file_name = pre_file_
            # Season/Episode from user_dict if available
            season = user_dict.get("START_SEASON", 1)
            episode = user_dict.get("START_EPISODE", 1)
            # Quality from qual or filename
            quality = qual or ""
            # BL (default format)
            BL = file_name
            # Custom file caption (if any)
            file_caption = (
                self._listener.file_details.get("caption", "")
                if hasattr(self._listener, "file_details")
                else ""
            )
            # Subtitles (from get_media_info)
            subtitles = subs or ""
            # Compose the format dict (support both lower and upper case keys)
            caption_vars = {
                "BL": BL,
                "bl": BL,
                "file_name": file_name,
                "file_size": file_size,
                "file_caption": file_caption,
                "languages": lang,
                "subtitles": subtitles,
                "duration": duration,
                "ott": ott,
                "resolution": resolution,
                "name": name,
                "year": year,
                "quality": quality,
                "season": season,
                "episode": episode,
                "audio": audio,
            }
            cap_mono = parts[0].format(**caption_vars)

            for part in parts[1:]:
                args = part.split(":")
                cap_mono = cap_mono.replace(
                    args[0],
                    args[1] if len(args) > 1 else "",
                    int(args[2]) if len(args) == 3 else -1,
                )
            cap_mono = re_sub(
                r"%%|&%&|\$%\$",
                lambda m: {"%%": "|", "&%&": "{", "$%$": "}"}[m.group()],
                cap_mono,
            )

        if len(file_) > 255:
            if is_archive(file_):
                name = get_base_name(file_)
                ext = file_.split(name, 1)[1]
            elif match := re_match(r".+(?=\..+\.0*\d+$)|.+(?=\.part\d+\..+$)", file_):
                name = match.group(0)
                ext = file_.split(name, 1)[1]
            elif len(fsplit := ospath.splitext(file_)) > 1:
                name = fsplit[0]
                ext = fsplit[1]
            else:
                name = file_
                ext = ""
            if self._lsuffix:
                ext = f"{self._lsuffix}{ext}"
            name = name[: 255 - len(ext)]
            file_ = f"{name}{ext}"
        elif self._lsuffix:
            name, ext = ospath.splitext(file_)
            file_ = f"{name}{self._lsuffix}{ext}"  # If file name changed but not due to auto_rename, update path
        if pre_file_ != file_ and not auto_rename:
            new_path = ospath.join(dirpath, file_)
            if await aiopath.exists(self._up_path):
                await rename(self._up_path, new_path)
                self._up_path = new_path

        # Helper function for cleaning filename for TMDB/IMDB/Fanart.tv search
        def clean_filename_for_title(filename):
            # Use extract_media_info to get the best title and year
            name, season, episode, year, part, volume = extract_media_info(filename)
            # If we have both name and year, return 'Name Year'
            if name and year:
                result = f"{name} {year}"
            elif name:
                result = name
            else:
                # fallback to old logic if extract_media_info fails
                name = ospath.splitext(filename)[0]
                name = re.sub(r"[\[\](){}⟨⟩【】『』“”‘’«»‹›❮❯❰❱❲❳❴❵]", " ", name)
                name = re.sub(r"\s+", " ", name).strip()
                result = name if name else "Unknown"
            LOGGER.info(f"Final cleaned title for lookups: '{result}'")
            return result

        # --- AUTO THUMBNAIL (TMDB) LOGIC ---
        if user_dict.get("AUTO_THUMBNAIL", False) and (
            not self._thumb or not await aiopath.exists(self._thumb)
        ):
            probable_title = clean_filename_for_title(pre_file_)
            year_match = re.search(
                r"(19|20)\\d{2}", pre_file_
            )  # Fixed regex pattern (removed extra backslash)
            year = year_match.group(0) if year_match else None
            LOGGER.info(f"Fetching TMDB poster for: {probable_title} ({year})")
            tmdb_thumb = fetch_tmdb_poster(probable_title, year)
            if tmdb_thumb:
                # Ensure thumbnails directory exists using absolute path
                import os
                from os import getcwd

                thumbnails_dir = os.path.join(getcwd(), "thumbnails")
                os.makedirs(thumbnails_dir, exist_ok=True)
                thumb_filename = f"tmdb_{self._listener.user_id}_{int(time())}.jpg"
                thumb_path = os.path.join(thumbnails_dir, thumb_filename)

                try:
                    # Try to optimize the image if PIL is available
                    from PIL import Image
                    from io import BytesIO

                    image_data = BytesIO(tmdb_thumb.read())
                    tmdb_thumb.seek(0)  # Reset file pointer in case of fallback

                    img = Image.open(image_data)

                    # Use higher resolution for better quality
                    max_width = 1280  # Increased from 800 for better quality

                    # Calculate optimal dimensions for 16:9 aspect ratio
                    target_ratio = 16 / 9
                    current_ratio = img.width / img.height

                    # TMDB backdrops are usually already 16:9, but ensure correct ratio
                    if abs(current_ratio - target_ratio) > 0.1:  # Not close to 16:9
                        LOGGER.info(f"Adjusting TMDB image to 16:9 aspect ratio")
                        new_width = max_width
                        new_height = int(new_width / target_ratio)
                        img = img.resize((new_width, new_height), Image.LANCZOS)
                    elif img.width > max_width:  # Already 16:9 but too large
                        ratio = max_width / float(img.width)
                        height = int(float(img.height) * ratio)
                        img = img.resize((max_width, height), Image.LANCZOS)

                    # Save with high quality settings
                    img.save(thumb_path, "JPEG", quality=95, optimize=True)

                except ImportError:
                    # If PIL not available, save directly
                    LOGGER.info("PIL not available, saving image without optimization")
                    with open(thumb_path, "wb") as f:
                        f.write(tmdb_thumb.read())
                except Exception as e:
                    # If image processing fails, save directly
                    LOGGER.error(f"Error processing image: {e}, saving raw image")
                    with open(thumb_path, "wb") as f:
                        f.write(tmdb_thumb.read())

                self._thumb = thumb_path
                LOGGER.info(f"TMDB poster set as thumbnail: {thumb_path}")
            else:  # Try IMDB as fallback with different search strategies
                LOGGER.info(
                    f"No TMDB poster found for: {probable_title}, trying IMDB..."
                )

                # Function to try getting IMDB widescreen image
                def get_imdb_widescreen_image(imdb_id):
                    try:
                        # Try to get an alternative widescreen backdrop image
                        backdrop_url = (
                            f"https://www.imdb.com/title/{imdb_id}/mediaindex"
                        )
                        headers = {
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
                        }

                        # Try to fetch the media gallery page
                        gallery_resp = requests.get(
                            backdrop_url, headers=headers, timeout=15
                        )
                        if gallery_resp.status_code == 200:
                            # Look for landscape/widescreen images
                            import re

                            # Pattern to match landscape image links
                            img_pattern = (
                                r'https://m\.media-amazon\.com/images/M/[^"]+\.jpg'
                            )
                            all_images = re.findall(img_pattern, gallery_resp.text)

                            # Filter for likely widescreen/landscape images
                            widescreen_images = []
                            for img_url in all_images:
                                # Most widescreen images have specific patterns in their URLs
                                if any(
                                    marker in img_url.lower()
                                    for marker in [
                                        "scene",
                                        "landscape",
                                        "still",
                                        "wide",
                                    ]
                                ):
                                    widescreen_images.append(img_url)

                            # Return the first widescreen image or any image if no specific widescreen found
                            if widescreen_images:
                                LOGGER.info(
                                    f"Found IMDB widescreen image: {widescreen_images[0]}"
                                )
                                return widescreen_images[0]
                            elif all_images:
                                # Just return the first image if we can't identify a widescreen one
                                return all_images[0]
                    except Exception as e:
                        LOGGER.error(f"Error fetching IMDB widescreen image: {e}")
                    return None

                # Strategy 1: Try with year if available
                if year:
                    imdb_data = get_poster(f"{probable_title} {year}")
                else:
                    imdb_data = None

                # Strategy 2: Try without year if first attempt failed
                if not imdb_data or not imdb_data.get("poster"):
                    imdb_data = get_poster(probable_title)

                # Strategy 3: Try with first part of title (for complex titles)
                if not imdb_data or not imdb_data.get("poster"):
                    first_part = " ".join(probable_title.split()[:2])
                    if first_part and first_part != probable_title:
                        imdb_data = get_poster(
                            first_part + (f" {year}" if year else "")
                        )

                # Get widescreen image if available
                poster_url = None
                if imdb_data and imdb_data.get("imdb_id"):
                    widescreen_url = get_imdb_widescreen_image(imdb_data["imdb_id"])
                    if widescreen_url:
                        # Check if the image is actually landscape and close to 16:9
                        try:
                            img_resp = requests.get(widescreen_url, timeout=10)
                            img_resp.raise_for_status()
                            from PIL import Image
                            from io import BytesIO

                            img = Image.open(BytesIO(img_resp.content))
                            width, height = img.size
                            aspect_ratio = width / height
                            # Only use if width > height (landscape), remove 16:9 aspect ratio check
                            if width > height:
                                poster_url = widescreen_url
                                LOGGER.info(
                                    f"Using IMDB landscape image: {widescreen_url}"
                                )
                            else:
                                LOGGER.info(
                                    f"IMDB image found but not landscape, skipping IMDB thumbnail."
                                )
                        except Exception as e:
                            LOGGER.error(f"Error validating IMDB widescreen image: {e}")
                # Do NOT use regular poster if no valid landscape found
                if poster_url:
                    try:
                        LOGGER.info(
                            f"Found IMDB match: {imdb_data.get('title')} ({imdb_data.get('year')})"
                        )
                        LOGGER.info(f"Found IMDB poster: {poster_url}")
                        # Validate the URL format
                        if not poster_url.startswith("http"):
                            LOGGER.error(f"Invalid poster URL format: {poster_url}")
                            raise ValueError("Invalid poster URL format")
                        img_resp = requests.get(poster_url, timeout=10)
                        img_resp.raise_for_status()
                        content_type = img_resp.headers.get("Content-Type", "")
                        if not content_type.startswith("image/"):
                            LOGGER.error(
                                f"Content is not an image. Content-Type: {content_type}"
                            )
                            raise ValueError(f"Content is not an image: {content_type}")
                        import os
                        from os import getcwd

                        thumbnails_dir = os.path.join(getcwd(), "thumbnails")
                        os.makedirs(thumbnails_dir, exist_ok=True)
                        thumb_filename = (
                            f"imdb_{self._listener.user_id}_{int(time())}.jpg"
                        )
                        thumb_path = os.path.join(thumbnails_dir, thumb_filename)
                        with open(thumb_path, "wb") as f:
                            f.write(img_resp.content)
                        self._thumb = thumb_path
                        LOGGER.info(f"IMDB poster set as thumbnail: {thumb_path}")
                    except Exception as e:
                        LOGGER.error(f"Error fetching IMDB poster: {e}")
                        LOGGER.warning(
                            f"No suitable poster found for: {probable_title}"
                        )
                else:
                    LOGGER.warning(
                        f"No TMDB or IMDB 16:9 poster found for: {probable_title}"
                    )
        elif user_dict.get("AUTO_THUMBNAIL", False):
            LOGGER.info("Custom thumbnail already exists, skipping poster fetch")

        # --- FANART.TV FALLBACK LOGIC ---
        if not self._thumb and user_dict.get("AUTO_THUMBNAIL", False):
            LOGGER.info(
                f"No TMDB or IMDB 16:9 poster found for: {probable_title}, trying Fanart.tv fallback..."
            )

            def fetch_fanart_landscape(title, year=None, tmdb_id=None):
                """Fetch a landscape image from Fanart.tv using TMDB ID or title/year. 16:9 not required, just landscape."""
                import requests
                from io import BytesIO

                api_key = getattr(Config, "FANARTTV_API_KEY", "")
                if not api_key:
                    LOGGER.warning(
                        "FANARTTV_API_KEY not set in config. Skipping Fanart.tv fallback."
                    )
                    return None
                # If TMDB ID is not provided, try to get it from TMDB API
                if not tmdb_id and getattr(Config, "TMDB_API_KEY", ""):
                    try:
                        tmdb_url = f"https://api.themoviedb.org/3/search/movie"
                        params = {"api_key": Config.TMDB_API_KEY, "query": title}
                        if year:
                            params["year"] = year
                        resp = requests.get(tmdb_url, params=params, timeout=10)
                        resp.raise_for_status()
                        data = resp.json()
                        if data["results"]:
                            tmdb_id = data["results"][0]["id"]
                    except Exception as e:
                        LOGGER.warning(f"Could not get TMDB ID for Fanart.tv: {e}")
                if not tmdb_id:
                    LOGGER.warning("No TMDB ID found for Fanart.tv fallback.")
                    return None
                # Now query Fanart.tv for landscape images
                try:
                    url = f"https://webservice.fanart.tv/v3/movies/{tmdb_id}?api_key={api_key}"
                    resp = requests.get(url, timeout=10)
                    resp.raise_for_status()
                    data = resp.json()
                    # Fanart.tv returns 'moviebackground' and 'hdmovieclearart' for landscape
                    images = []
                    if "moviebackground" in data:
                        images.extend(data["moviebackground"])
                    if "hdmovieclearart" in data:
                        images.extend(data["hdmovieclearart"])
                    # Pick the first available landscape image (width > height)
                    for img in images:
                        img_url = img.get("url")
                        if img_url:
                            try:
                                img_resp = requests.get(img_url, timeout=10)
                                img_resp.raise_for_status()
                                from PIL import Image

                                img_obj = Image.open(BytesIO(img_resp.content))
                                width, height = img_obj.size
                                if width > height:
                                    return BytesIO(img_resp.content)
                            except Exception as e:
                                LOGGER.warning(
                                    f"Fanart.tv image validation failed: {e}"
                                )
                    LOGGER.warning("No valid landscape image found on Fanart.tv.")
                except Exception as e:
                    LOGGER.warning(f"Fanart.tv API error: {e}")
                return None

            # Try to get TMDB ID if available from previous search
            tmdb_id = None
            if getattr(Config, "TMDB_API_KEY", ""):
                try:
                    tmdb_url = f"https://api.themoviedb.org/3/search/movie"
                    params = {"api_key": Config.TMDB_API_KEY, "query": probable_title}
                    if year:
                        params["year"] = year
                    resp = requests.get(tmdb_url, params=params, timeout=10)
                    resp.raise_for_status()
                    data = resp.json()
                    if data["results"]:
                        tmdb_id = data["results"][0]["id"]
                except Exception:
                    pass
            fanart_thumb = fetch_fanart_landscape(probable_title, year, tmdb_id)
            if fanart_thumb:
                import os
                from os import getcwd

                thumbnails_dir = os.path.join(getcwd(), "thumbnails")
                os.makedirs(thumbnails_dir, exist_ok=True)
                thumb_filename = f"fanart_{self._listener.user_id}_{int(time())}.jpg"
                thumb_path = os.path.join(thumbnails_dir, thumb_filename)
                try:
                    from PIL import Image

                    img = Image.open(fanart_thumb)
                    max_width = 1280
                    if img.width > max_width:
                        ratio = max_width / float(img.width)
                        height = int(float(img.height) * ratio)
                        img = img.resize((max_width, height), Image.LANCZOS)
                    img.save(thumb_path, "JPEG", quality=95, optimize=True)
                except Exception as e:
                    LOGGER.error(
                        f"Error processing Fanart.tv image: {e}, saving raw image"
                    )
                    with open(thumb_path, "wb") as f:
                        f.write(fanart_thumb.read())
                self._thumb = thumb_path
                LOGGER.info(f"Fanart.tv poster set as thumbnail: {thumb_path}")
            else:
                LOGGER.warning(
                    f"No suitable Fanart.tv landscape image found for: {probable_title}"
                )

        # --- END FANART.TV FALLBACK ---
        return cap_mono

    def _get_input_media(self, subkey, key):
        rlist = []
        for msg in self._media_dict[key][subkey]:
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
            if Config.BOT_PM:
                await TgClient.bot.send_media_group(
                    chat_id=self._listener.user_id,
                    media=batch,
                    disable_notification=True,
                )
            self._sent_msg = (
                await self._sent_msg.reply_media_group(
                    media=batch,
                    quote=True,
                    disable_notification=True,
                )
            )[-1]

    async def _send_media_group(self, subkey, key, msgs):
        for index, msg in enumerate(msgs):
            if self._listener.hybrid_leech or not self._user_session:
                msgs[index] = await self._listener.client.get_messages(
                    chat_id=msg[0], message_ids=msg[1]
                )
            else:
                msgs[index] = await TgClient.user.get_messages(
                    chat_id=msg[0], message_ids=msg[1]
                )
        msgs_list = await msgs[0].reply_to_message.reply_media_group(
            media=self._get_input_media(subkey, key),
            quote=True,
            disable_notification=True,
        )
        for msg in msgs:
            if msg.link in self._msgs_dict:
                del self._msgs_dict[msg.link]
            await delete_message(msg)
        del self._media_dict[key][subkey]
        if self._listener.is_super_chat or self._listener.up_dest:
            for m in msgs_list:
                self._msgs_dict[m.link] = m.caption
        self._sent_msg = msgs_list[-1]

    async def _copy_media(self):
        try:
            if self._bot_pm:
                await TgClient.bot.copy_message(
                    chat_id=self._listener.user_id,
                    from_chat_id=self._sent_msg.chat.id,
                    message_id=self._sent_msg.id,
                    reply_to_message_id=(
                        self._listener.pm_msg.id if self._listener.pm_msg else None
                    ),
                )
        except Exception as err:
            if not self._listener.is_cancelled:
                LOGGER.error(f"Failed To Send in BotPM:\n{str(err)}")

    async def upload(self):
        await self._user_settings()
        LOGGER.info(
            f"Uploader settings: use_leech_dump={getattr(self, 'use_leech_dump', False)}, LEECH_DUMP_CHAT={Config.LEECH_DUMP_CHAT}"
        )
        res = await self._msg_to_reply()
        if not res:
            return
        is_log_del = False

        # --- PREPROCESS: Apply metadata to all video/audio files in advance and update status ---
        if self._listener.user_dict and self._listener.user_dict.get(
            "METADATA_SETTINGS"
        ):
            metadata_settings = self._listener.user_dict["METADATA_SETTINGS"]
            # Gather all video/audio files first
            all_files = []
            for dirpath, _, files in natsorted(await sync_to_async(walk, self._path)):
                if dirpath.strip().endswith(
                    "/yt-dlp-thumb"
                ) or dirpath.strip().endswith("_mltbss"):
                    continue
                for file_ in natsorted(files):
                    up_path = ospath.join(dirpath, file_)
                    if not await aiopath.exists(up_path):
                        continue
                    is_video, is_audio, _ = await get_document_type(up_path)
                    if is_video or is_audio:
                        all_files.append(up_path)
            total = len(all_files)
            for idx, up_path in enumerate(all_files, 1):
                self._status = MirrorStatus.STATUS_MEGA_METADATA
                # Show progress as 'Metadata X/Y' in status
                self._metadata_progress = int(idx / total * 100) if total else 100
                if hasattr(self._listener, "update_status_message"):
                    await self._listener.update_status_message(force=True)
                await apply_metadata(up_path, metadata_settings)
            self._metadata_progress = 100
            self._status = MirrorStatus.STATUS_UPLOAD
            if hasattr(self._listener, "update_status_message"):
                await self._listener.update_status_message(force=True)
        # --- END PREPROCESS ---
        for dirpath, _, files in natsorted(await sync_to_async(walk, self._path)):
            if dirpath.strip().endswith("/yt-dlp-thumb"):
                continue
            if dirpath.strip().endswith("_mltbss"):
                await self._send_screenshots(dirpath, files)
                await rmtree(dirpath, ignore_errors=True)
                continue
            for file_ in natsorted(files):
                self._error = ""
                self._up_path = f_path = ospath.join(dirpath, file_)
                if not await aiopath.exists(self._up_path):
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

                    # Debug file size and session info
                    LOGGER.info(
                        f"File: {file_}, Size: {f_size} bytes ({f_size / (1024**3):.2f} GB)"
                    )
                    LOGGER.info(
                        f"TgClient.IS_PREMIUM_USER: {TgClient.IS_PREMIUM_USER}, TgClient.MAX_SPLIT_SIZE: {TgClient.MAX_SPLIT_SIZE}"
                    )
                    LOGGER.info(
                        f"User session available: {TgClient.user is not None}, Hybrid leech: {self._listener.hybrid_leech}, User transmission: {getattr(self._listener, 'user_transmission', None)}"
                    )

                    # --- REMOVED: per-file metadata application ---
                    # self._status = MirrorStatus.STATUS_MEGA_METADATA
                    # self._up_path = await self._process_media_metadata(self._up_path)
                    # self._status = MirrorStatus.STATUS_UPLOAD
                    try:
                        cap_mono = await self._prepare_file(file_, dirpath)
                    except FileNotFoundError as e:
                        LOGGER.error(f"File not found during rename: {str(e)}")
                        self._corrupted += 1
                        continue
                    # If user asked to embed user image as cover art, and we have a thumbnail path, embed into media file
                    try:
                        user_dict = getattr(self._listener, "user_dict", {})
                        if user_dict.get("EMBED_USER_IMAGE_AS_COVER", False):
                            # Use self._thumb if exists, else user's saved thumbnail
                            cover_img = None
                            if (
                                self._thumb
                                and await aiopath.exists(self._thumb)
                                and self._thumb != "none"
                            ):
                                cover_img = self._thumb
                            else:
                                # default user thumbnail path
                                default_thumb = (
                                    f"thumbnails/{self._listener.user_id}.jpg"
                                )
                                if await aiopath.exists(default_thumb):
                                    cover_img = default_thumb
                            if cover_img:
                                # Only embed for audio/video files
                                is_video, is_audio, _ = await get_document_type(
                                    self._up_path
                                )
                                if is_video or is_audio:
                                    LOGGER.info(
                                        f"Embedding cover art for {file_} using {cover_img}"
                                    )
                                    self._up_path = await embed_cover_art(
                                        self._up_path, cover_img
                                    )
                    except Exception as e:
                        LOGGER.warning(f"Cover art embed skipped: {e}")
                    if self._last_msg_in_group:
                        group_lists = [
                            x for v in self._media_dict.values() for x in v.keys()
                        ]
                        match = re_match(r".+(?=\.0*\d+$)|.+(?=\.part\d+\..+$)", f_path)
                        if not match or match and match.group(0) not in group_lists:
                            for key, value in list(self._media_dict.items()):
                                for subkey, msgs in list(value.items()):
                                    if len(msgs) > 1:
                                        await self._send_media_group(subkey, key, msgs)
                    if self._listener.hybrid_leech and self._listener.user_transmission:
                        # For hybrid leech, use user session for files > 2GB
                        self._user_session = f_size > 2097152000
                        if self._user_session:
                            try:
                                # Safely refresh message using helper (may reconstruct if None)
                                if not await self._refresh_sent_msg(
                                    prefer_user_session=True
                                ):
                                    raise RuntimeError(
                                        "Failed to refresh base message for user session upload"
                                    )
                                # When using LEECH_DUMP_CHAT, _is_private should be based on original destination, not dump chat
                                if (
                                    self.use_leech_dump
                                    and Config.LEECH_DUMP_CHAT
                                    and hasattr(self, "_original_up_dest")
                                ):
                                    # Check if original destination is a private chat
                                    original_dest = self._original_up_dest
                                    if (
                                        isinstance(original_dest, (int, str))
                                        and original_dest
                                    ):
                                        # For user IDs (private chats), they are typically positive integers < 1000000000
                                        # For supergroups/channels, they start with -100
                                        if (
                                            isinstance(original_dest, int)
                                            and original_dest > 0
                                            and original_dest < 1000000000
                                        ):
                                            self._is_private = True
                                        elif (
                                            isinstance(original_dest, str)
                                            and original_dest.strip()
                                            and not original_dest.startswith("-")
                                            and not original_dest.startswith("@")
                                        ):
                                            self._is_private = True
                                        else:
                                            self._is_private = False
                                    else:
                                        self._is_private = False
                                    LOGGER.info(
                                        f"Set _is_private={self._is_private} based on original destination: {original_dest}"
                                    )
                                else:
                                    # Normal behavior when not using LEECH_DUMP_CHAT
                                    self._is_private = (
                                        self._sent_msg.chat.type.name == "PRIVATE"
                                    )
                                LOGGER.info(
                                    f"Retrieved message via user session for large file: {file_} (size: {f_size})"
                                )
                            except Exception as e:
                                LOGGER.error(
                                    f"Failed to retrieve message via user session for file {file_}: {e}"
                                )
                                # Fall back to using bot session
                                await self._refresh_sent_msg(prefer_user_session=False)
                                # Apply same logic for fallback
                                if (
                                    self.use_leech_dump
                                    and Config.LEECH_DUMP_CHAT
                                    and hasattr(self, "_original_up_dest")
                                ):
                                    original_dest = self._original_up_dest
                                    if (
                                        isinstance(original_dest, (int, str))
                                        and original_dest
                                    ):
                                        if (
                                            isinstance(original_dest, int)
                                            and original_dest > 0
                                            and original_dest < 1000000000
                                        ):
                                            self._is_private = True
                                        elif (
                                            isinstance(original_dest, str)
                                            and original_dest.strip()
                                            and not original_dest.startswith("-")
                                            and not original_dest.startswith("@")
                                        ):
                                            self._is_private = True
                                        else:
                                            self._is_private = False
                                    else:
                                        self._is_private = False
                                else:
                                    self._is_private = (
                                        self._sent_msg.chat.type.name == "PRIVATE"
                                    )
                                self._user_session = False
                        else:
                            await self._refresh_sent_msg(prefer_user_session=False)
                    elif TgClient.user and TgClient.IS_PREMIUM_USER:
                        # If we have a premium user session available, use it for large files
                        self._user_session = f_size > 2097152000
                        if self._user_session:
                            try:
                                if not await self._refresh_sent_msg(
                                    prefer_user_session=True
                                ):
                                    raise RuntimeError(
                                        "Failed to refresh base message for premium user session upload"
                                    )
                                # When using LEECH_DUMP_CHAT, _is_private should be based on original destination, not dump chat
                                if (
                                    self.use_leech_dump
                                    and Config.LEECH_DUMP_CHAT
                                    and hasattr(self, "_original_up_dest")
                                ):
                                    original_dest = self._original_up_dest
                                    if (
                                        isinstance(original_dest, (int, str))
                                        and original_dest
                                    ):
                                        if (
                                            isinstance(original_dest, int)
                                            and original_dest > 0
                                            and original_dest < 1000000000
                                        ):
                                            self._is_private = True
                                        elif (
                                            isinstance(original_dest, str)
                                            and original_dest.strip()
                                            and not original_dest.startswith("-")
                                            and not original_dest.startswith("@")
                                        ):
                                            self._is_private = True
                                        else:
                                            self._is_private = False
                                    else:
                                        self._is_private = False
                                else:
                                    self._is_private = (
                                        self._sent_msg.chat.type.name == "PRIVATE"
                                    )
                                LOGGER.info(
                                    f"Using premium user session for large file: {file_} (size: {f_size})"
                                )
                            except Exception as e:
                                LOGGER.error(
                                    f"Failed to retrieve message via premium user session for file {file_}: {e}"
                                )
                                self._user_session = False
                    self._last_msg_in_group = False
                    self._last_uploaded = 0
                    await self._upload_file(cap_mono, file_, f_path)
                    # Add Media Info button if enabled in user settings
                    # Skip if using LEECH_DUMP_CHAT as sequential processor will handle it
                    show_mediainfo = self._listener.user_dict.get(
                        "SHOW_MEDIAINFO_BUTTON", True
                    )
                    if show_mediainfo and self._sent_msg and not self.use_leech_dump:
                        try:
                            from ....modules.mediainfo import (
                                get_mediainfo_telegraph_link,
                            )
                            from ...telegram_helper.button_build import ButtonMaker

                            telegraph_link = None
                            media = None
                            if self._sent_msg.document:
                                media = self._sent_msg.document
                            elif self._sent_msg.video:
                                media = self._sent_msg.video
                            elif self._sent_msg.audio:
                                media = self._sent_msg.audio
                            if media:
                                telegraph_link = await get_mediainfo_telegraph_link(
                                    media, self._sent_msg
                                )
                            if telegraph_link:
                                buttons = ButtonMaker()
                                buttons.url_button("Media Info", telegraph_link)
                                await self._sent_msg.edit_reply_markup(
                                    buttons.build_menu(1)
                                )
                        except Exception as e:
                            LOGGER.warning(f"Failed to add Media Info button: {e}")
                    if self._log_msg and not is_log_del and Config.CLEAN_LOG_MSG:
                        await delete_message(self._log_msg)
                        is_log_del = True
                    if self._listener.is_cancelled:
                        return
                    if (
                        not self._is_corrupted
                        and (self._listener.is_super_chat or self._listener.up_dest)
                        and not self._is_private
                    ):
                        try:
                            # Ensure the message has a valid link before adding to dict
                            if hasattr(self._sent_msg, "link") and self._sent_msg.link:
                                self._msgs_dict[self._sent_msg.link] = file_
                                LOGGER.info(
                                    f"Added file {file_} to msgs_dict with link: {self._sent_msg.link}"
                                )
                            else:
                                LOGGER.warning(
                                    f"Message for file {file_} does not have a valid link attribute"
                                )
                        except Exception as e:
                            LOGGER.error(f"Error adding file {file_} to msgs_dict: {e}")
                        # Note: Sequential processing will handle file forwarding after all uploads are complete
                    await sleep(1)
                except Exception as err:
                    if isinstance(err, RetryError):
                        LOGGER.info(
                            f"Total Attempts: {err.last_attempt.attempt_number}"
                        )
                        err = err.last_attempt.exception()
                    LOGGER.error(f"{err}. Path: {self._up_path}", exc_info=True)
                    self._error = str(err)
                    self._corrupted += 1
                    if self._listener.is_cancelled:
                        return
                if not self._listener.is_cancelled and await aiopath.exists(
                    self._up_path
                ):
                    await remove(self._up_path)
        # Handle remaining media groups
        for key, value in list(self._media_dict.items()):
            for subkey, msgs in list(value.items()):
                if len(msgs) > 1:
                    try:
                        await self._send_media_group(subkey, key, msgs)
                    except Exception as e:
                        LOGGER.info(
                            f"While sending media group at the end of task. Error: {e}"
                        )
        if self._listener.is_cancelled:
            return
        if self._total_files == 0:
            await self._listener.on_upload_error(
                "No files to upload. In case you have filled EXCLUDED_EXTENSIONS, then check if all files have those extensions or not."
            )
            return
        if self._total_files <= self._corrupted:
            await self._listener.on_upload_error(
                f"Files Corrupted or unable to upload. {self._error or 'Check logs!'}"
            )
            return

        LOGGER.info(f"Leech Completed: {self._listener.name}")

        # If using LEECH_DUMP, process files sequentially (always enabled)
        if self.use_leech_dump and Config.LEECH_DUMP_CHAT and self._msgs_dict:
            original_dest = getattr(self, "_original_up_dest", None)
            LOGGER.info(
                f"DEBUG LEECH_DUMP: use_leech_dump={self.use_leech_dump}, sequential=Always Enabled, original_dest={original_dest}, files_count={len(self._msgs_dict)}, dump_chat={Config.LEECH_DUMP_CHAT}"
            )

            if original_dest and self._sequential_processor:
                try:
                    # Temporarily set the listener's up_dest to the original destination
                    original_listener_up_dest = self._listener.up_dest
                    self._listener.up_dest = original_dest
                    # Force set chat_thread_id if needed
                    if not hasattr(self._listener, "chat_thread_id"):
                        self._listener.chat_thread_id = None

                    # Pass BOT_PM setting to sequential processor to avoid duplication
                    self._sequential_processor._bot_pm_enabled = self._bot_pm

                    # Use sequential processing (always enabled)
                    LOGGER.info(
                        f"Starting sequential processing of {len(self._msgs_dict)} files"
                    )
                    (
                        processed_msgs,
                        total_files,
                        corrupted,
                    ) = await self._sequential_processor.process_files_sequentially(
                        self._msgs_dict, self._processed_bytes
                    )
                    LOGGER.info(
                        f"Sequential processing completed: processed {len(processed_msgs)} files, corrupted {corrupted}"
                    )

                    # Update the messages dict with processed messages
                    if processed_msgs:
                        self._msgs_dict = processed_msgs
                        if corrupted > 0:
                            self._corrupted += corrupted
                        LOGGER.info(
                            f"Successfully processed {len(processed_msgs)} files"
                        )

                    # Restore the original destination
                    self._listener.up_dest = original_listener_up_dest

                except Exception as e:
                    LOGGER.error(f"Failed to process files sequentially: {str(e)}")
                    # Restore the original destination in case of error
                    self._listener.up_dest = original_listener_up_dest
            else:
                LOGGER.warning(
                    "Sequential processing skipped - no original destination or processor not initialized"
                )

        await self._listener.on_upload_complete(
            None, self._msgs_dict, self._total_files, self._corrupted
        )
        return

    @retry(
        wait=wait_exponential(multiplier=2, min=4, max=8),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(Exception),
    )
    async def _upload_file(self, cap_mono, file, o_path, force_document=False):
        if (
            self._thumb is not None
            and not await aiopath.exists(self._thumb)
            and self._thumb != "none"
        ):
            self._thumb = None
        thumb = self._thumb
        self._is_corrupted = False

        # Debug session information
        f_size = await aiopath.getsize(self._up_path)
        LOGGER.info(f"Upload attempt for: {file}")
        LOGGER.info(f"File size: {f_size} bytes ({f_size / (1024**2):.2f} MB)")
        LOGGER.info(f"Using user session: {self._user_session}")
        LOGGER.info(f"TgClient.user available: {TgClient.user is not None}")
        LOGGER.info(f"TgClient.IS_PREMIUM_USER: {TgClient.IS_PREMIUM_USER}")

        # Force user session for large files if premium user is available
        if (
            not self._user_session
            and f_size > 2097152000
            and TgClient.user
            and TgClient.IS_PREMIUM_USER
        ):
            LOGGER.warning(
                f"File size {f_size} bytes exceeds 2GB limit but user session not set. Forcing user session for premium user."
            )
            self._user_session = True
            # Also need to get the message via user client
            try:
                if await self._refresh_sent_msg(prefer_user_session=True):
                    LOGGER.info(
                        "Successfully refreshed message via user client for large file upload"
                    )
                else:
                    raise RuntimeError(
                        "_refresh_sent_msg returned False while forcing user session"
                    )
            except Exception as e:
                LOGGER.error(f"Failed to retrieve message via user client: {e}")
                self._user_session = False

        try:
            is_video, is_audio, is_image = await get_document_type(self._up_path)

            if not is_image and thumb is None:
                file_name = ospath.splitext(file)[0]
                thumb_path = f"{self._path}/yt-dlp-thumb/{file_name}.jpg"
                if await aiopath.isfile(thumb_path):
                    thumb = thumb_path
                elif is_audio and not is_video:
                    thumb = await get_audio_thumbnail(self._up_path)

            if (
                self._listener.as_doc
                or force_document
                or (not is_video and not is_audio and not is_image)
            ):
                key = "documents"
                if is_video and thumb is None:
                    thumb = await get_video_thumbnail(self._up_path, None)

                if self._listener.is_cancelled:
                    return
                if thumb == "none":
                    thumb = None

                # Use user client for large files if user session is available
                if self._user_session and TgClient.user:
                    self._sent_msg = await TgClient.user.send_document(
                        chat_id=self._sent_msg.chat.id,
                        document=self._up_path,
                        reply_to_message_id=self._sent_msg.id,
                        thumb=thumb,
                        caption=cap_mono,
                        force_document=True,
                        disable_notification=True,
                        progress=self._upload_progress,
                    )
                else:
                    self._sent_msg = await self._sent_msg.reply_document(
                        document=self._up_path,
                        quote=True,
                        thumb=thumb,
                        caption=cap_mono,
                        force_document=True,
                        disable_notification=True,
                        progress=self._upload_progress,
                    )
            elif is_video:
                key = "videos"
                duration = (await get_media_info(self._up_path))[0]
                if thumb is None and self._listener.thumbnail_layout:
                    thumb = await get_multiple_frames_thumbnail(
                        self._path,
                        self._listener.thumbnail_layout,
                        self._listener.screen_shots,
                    )
                if thumb is None:
                    thumb = await get_video_thumbnail(self._up_path, duration)
                if thumb is not None and thumb != "none":
                    with Image.open(thumb) as img:
                        width, height = img.size
                else:
                    width = 480
                    height = 320
                if self._listener.is_cancelled:
                    return
                if thumb == "none":
                    thumb = None

                # Use user client for large files if user session is available
                if self._user_session and TgClient.user:
                    self._sent_msg = await TgClient.user.send_video(
                        chat_id=self._sent_msg.chat.id,
                        video=self._up_path,
                        reply_to_message_id=self._sent_msg.id,
                        caption=cap_mono,
                        duration=duration,
                        width=width,
                        height=height,
                        thumb=thumb,
                        supports_streaming=True,
                        disable_notification=True,
                        progress=self._upload_progress,
                    )
                else:
                    self._sent_msg = await self._sent_msg.reply_video(
                        video=self._up_path,
                        quote=True,
                        caption=cap_mono,
                        duration=duration,
                        width=width,
                        height=height,
                        thumb=thumb,
                        supports_streaming=True,
                        disable_notification=True,
                        progress=self._upload_progress,
                    )
            elif is_audio:
                key = "audios"
                duration, artist, title = await get_media_info(self._up_path)
                if self._listener.is_cancelled:
                    return
                if thumb == "none":
                    thumb = None

                # Use user client for large files if user session is available
                if self._user_session and TgClient.user:
                    self._sent_msg = await TgClient.user.send_audio(
                        chat_id=self._sent_msg.chat.id,
                        audio=self._up_path,
                        reply_to_message_id=self._sent_msg.id,
                        caption=cap_mono,
                        duration=duration,
                        performer=artist,
                        title=title,
                        thumb=thumb,
                        disable_notification=True,
                        progress=self._upload_progress,
                    )
                else:
                    self._sent_msg = await self._sent_msg.reply_audio(
                        audio=self._up_path,
                        quote=True,
                        caption=cap_mono,
                        duration=duration,
                        performer=artist,
                        title=title,
                        thumb=thumb,
                        disable_notification=True,
                        progress=self._upload_progress,
                    )
            else:
                key = "photos"
                if self._listener.is_cancelled:
                    return
                # Use user client for large files if user session is available
                if self._user_session and TgClient.user:
                    self._sent_msg = await TgClient.user.send_photo(
                        chat_id=self._sent_msg.chat.id,
                        photo=self._up_path,
                        reply_to_message_id=self._sent_msg.id,
                        caption=cap_mono,
                        disable_notification=True,
                        progress=self._upload_progress,
                    )
                else:
                    self._sent_msg = await self._sent_msg.reply_photo(
                        photo=self._up_path,
                        quote=True,
                        caption=cap_mono,
                        disable_notification=True,
                        progress=self._upload_progress,
                    )

            if (
                not self._listener.is_cancelled
                and self._media_group
                and (self._sent_msg.video or self._sent_msg.document)
            ):
                key = "documents" if self._sent_msg.document else "videos"
                if match := re_match(r".+(?=\.0*\d+$)|.+(?=\.part\d+\..+$)", o_path):
                    pname = match.group(0)
                    if pname in self._media_dict[key].keys():
                        self._media_dict[key][pname].append(
                            [self._sent_msg.chat.id, self._sent_msg.id]
                        )
                    else:
                        self._media_dict[key][pname] = [
                            [self._sent_msg.chat.id, self._sent_msg.id]
                        ]
                    msgs = self._media_dict[key][pname]
                    if len(msgs) == 10:
                        await self._send_media_group(pname, key, msgs)
                    else:
                        self._last_msg_in_group = True

            if self._sent_msg:
                await self._copy_media()

            if (
                self._thumb is None
                and thumb is not None
                and await aiopath.exists(thumb)
            ):
                await remove(thumb)
        except (FloodWait, FloodPremiumWait) as f:
            LOGGER.warning(str(f))
            await sleep(f.value * 1.3)
            if (
                self._thumb is None
                and thumb is not None
                and await aiopath.exists(thumb)
            ):
                await remove(thumb)
            return await self._upload_file(cap_mono, file, o_path)
        except Exception as err:
            if (
                self._thumb is None
                and thumb is not None
                and await aiopath.exists(thumb)
            ):
                await remove(thumb)
            err_type = "RPCError: " if isinstance(err, RPCError) else ""
            LOGGER.error(f"{err_type}{err}. Path: {self._up_path}", exc_info=True)
            if isinstance(err, BadRequest) and key != "documents":
                LOGGER.error(f"Retrying As Document. Path: {self._up_path}")
                return await self._upload_file(cap_mono, file, o_path, True)
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
        await self._listener.on_upload_error("your upload has been stopped!")

    async def _process_media_metadata(self, file_path):
        """Process media file with metadata settings if available"""
        if self._listener.user_dict and self._listener.user_dict.get(
            "METADATA_SETTINGS"
        ):
            LOGGER.info(f"Applying metadata to {ospath.basename(file_path)}")
            metadata_settings = self._listener.user_dict["METADATA_SETTINGS"]
            try:
                # Simulate progress tracking for metadata (replace with real tracking if possible)
                self._metadata_progress = 0
                processed_path = await apply_metadata(
                    file_path,
                    metadata_settings,
                    progress_callback=self._set_metadata_progress,
                )
                self._metadata_progress = 100
                if processed_path != file_path:
                    LOGGER.info(
                        f"Metadata successfully applied to {ospath.basename(file_path)}"
                    )
                return processed_path
            except Exception as e:
                LOGGER.error(f"Error applying metadata: {e}")
                self._metadata_progress = 0
                return file_path
        return file_path

    def _set_metadata_progress(self, percent):
        self._metadata_progress = percent

    @property
    def metadata_progress(self):
        return self._metadata_progress

    def status(self):
        # Return MegaMetaData status if set, otherwise Upload
        if self._status == MirrorStatus.STATUS_MEGA_METADATA:
            return MirrorStatus.STATUS_MEGA_METADATA
        return MirrorStatus.STATUS_UPLOAD
