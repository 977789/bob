from importlib import import_module
from os import getenv
import ast


class Config:
    AS_DOCUMENT = False
    AUTHORIZED_CHATS = ""
    BASE_URL = ""
    BASE_URL_PORT = 80
    BOT_IMAGE_PATH = "assets/BHARTIYEE LEECH.png"
    BOT_TOKEN = ""
    HELPER_TOKENS = ""
    BOT_MAX_TASKS = 0
    BOT_PM = True
    CMD_SUFFIX = ""
    DEFAULT_LANG = "en"
    DATABASE_URL = ""
    DEFAULT_UPLOAD = "rc"
    DELETE_LINKS = False
    DISABLE_TORRENTS = False
    DISABLE_LEECH = False
    DISABLE_BULK = False
    DISABLE_MULTI = False
    DISABLE_SEED = False
    DISABLE_FF_MODE = False
    DISABLE_MEDIA_PROCESSING = (
        False  # Master toggle for merge, stream, encode, and watermark operations
    )
    EQUAL_SPLITS = False
    EXCLUDED_EXTENSIONS = ""
    FFMPEG_CMDS = {}
    FILELION_API = ""
    GOFILE_API = ""
    MEDIA_STORE = True
    FORCE_SUB_IDS = "-1002319834974"
    GDRIVE_ID = ""
    GD_DESP = "Uploaded with BL Bot"
    AUTHOR_NAME = "Bzex"
    AUTHOR_URL = "https://t.me/MirrorLeechGroupz"
    INSTADL_API = ""
    IMDB_TEMPLATE = ""
    INCOMPLETE_TASK_NOTIFIER = True
    INCOMPLETE_AUTO_RESUME = True
    INDEX_URL = ""
    IS_TEAM_DRIVE = False
    JD_EMAIL = ""
    JD_PASS = ""
    MEGA_EMAIL = ""
    MEGA_PASSWORD = ""
    DIRECT_LIMIT = 0
    MEGA_LIMIT = 0
    TORRENT_LIMIT = 0
    GD_DL_LIMIT = 0
    RC_DL_LIMIT = 0
    CLONE_LIMIT = 0
    JD_LIMIT = 0
    NZB_LIMIT = 0
    YTDLP_LIMIT = 0
    PLAYLIST_LIMIT = 0
    LEECH_LIMIT = 0
    EXTRACT_LIMIT = 0
    ARCHIVE_LIMIT = 0
    STORAGE_LIMIT = 0
    DISK_FREE_ALERT_PCT = 10  # Show alert icon if free disk percentage <= this value
    LEECH_DUMP_CHAT = ""
    LINKS_LOG_ID = ""
    MIRROR_LOG_ID = ""
    CLEAN_LOG_MSG = False
    LEECH_PREFIX = ""
    LEECH_CAPTION = ""
    LEECH_SUFFIX = ""
    LEECH_FONT = "b"
    LEECH_SPLIT_SIZE = 2097152000
    MEDIA_GROUP = False
    HYBRID_LEECH = True
    HYPER_THREADS = 0
    HYPER_SESSION_TIMEOUT = 30 * 60  # 30 minutes default session timeout
    HYDRA_IP = ""
    HYDRA_API_KEY = ""
    NAME_SWAP = ""
    OWNER_ID = 0
    QUEUE_ALL = 0
    QUEUE_DOWNLOAD = 3
    QUEUE_UPLOAD = 3
    QUEUE_MEDIA_PROCESSING = 1  # Global queue for heavy media processing (FFmpeg, encoding, watermarking only)
    QUEUE_EXTRACT = (
        1  # Limit concurrent archive extractions (memory intensive). 0 = unlimited
    )
    EXTRACT_THREADS = (
        1  # 7z -mmt value (threads) to control memory usage during extraction
    )
    RCLONE_FLAGS = ""
    RCLONE_PATH = ""
    RCLONE_SERVE_URL = ""
    SHOW_CLOUD_LINK = True
    RCLONE_SERVE_USER = ""
    RCLONE_SERVE_PASS = ""
    RCLONE_SERVE_PORT = 8080
    RSS_CHAT = ""
    RSS_DELAY = 600
    RSS_SIZE_LIMIT = 0
    SEARCH_API_LINK = ""
    SEARCH_LIMIT = 0
    SEARCH_PLUGINS = [
        "https://raw.githubusercontent.com/qbittorrent/search-plugins/master/nova3/engines/piratebay.py",
        "https://raw.githubusercontent.com/qbittorrent/search-plugins/master/nova3/engines/limetorrents.py",
        "https://raw.githubusercontent.com/qbittorrent/search-plugins/master/nova3/engines/torlock.py",
        "https://raw.githubusercontent.com/qbittorrent/search-plugins/master/nova3/engines/torrentscsv.py",
        "https://raw.githubusercontent.com/qbittorrent/search-plugins/master/nova3/engines/eztv.py",
        "https://raw.githubusercontent.com/qbittorrent/search-plugins/master/nova3/engines/torrentproject.py",
        "https://raw.githubusercontent.com/MaurizioRicci/qBittorrent_search_engines/master/kickass_torrent.py",
        "https://raw.githubusercontent.com/MaurizioRicci/qBittorrent_search_engines/master/yts_am.py",
        "https://raw.githubusercontent.com/MadeOfMagicAndWires/qBit-plugins/master/engines/linuxtracker.py",
        "https://raw.githubusercontent.com/MadeOfMagicAndWires/qBit-plugins/master/engines/nyaasi.py",
        "https://raw.githubusercontent.com/LightDestory/qBittorrent-Search-Plugins/master/src/engines/ettv.py",
        "https://raw.githubusercontent.com/LightDestory/qBittorrent-Search-Plugins/master/src/engines/glotorrents.py",
        "https://raw.githubusercontent.com/LightDestory/qBittorrent-Search-Plugins/master/src/engines/thepiratebay.py",
        "https://raw.githubusercontent.com/v1k45/1337x-qBittorrent-search-plugin/master/leetx.py",
        "https://raw.githubusercontent.com/nindogo/qbtSearchScripts/master/magnetdl.py",
        "https://raw.githubusercontent.com/msagca/qbittorrent_plugins/main/uniondht.py",
        "https://raw.githubusercontent.com/khensolomon/leyts/master/yts.py",
    ]
    SET_COMMANDS = True
    STATUS_LIMIT = 10
    STATUS_UPDATE_INTERVAL = 15
    STOP_DUPLICATE = False
    STREAMWISH_API = ""
    SUDO_USERS = ""
    TELEGRAM_API = 0
    TELEGRAM_HASH = ""
    TG_PROXY = None
    THUMBNAIL_LAYOUT = ""
    VERIFY_TIMEOUT = 0
    LOGIN_PASS = ""
    TORRENT_TIMEOUT = 0
    DL_SPEED_LIMIT = 0  # Minimum download speed in MB/s to cancel task (0 = disabled, 1 = 1MB/s, 2 = 2MB/s, etc.)
    SPEED_LIMIT_TIMEOUT = (
        300  # Time in seconds to wait before canceling slow download (5 minutes)
    )
    AUTO_PING_INTERVAL = 5  # Auto-ping interval in MINUTES to keep bot active (0 = disabled, recommended: 5-30 minutes)
    TIMEZONE = "Asia/Kolkata"
    USER_MAX_TASKS = 0
    USER_TIME_INTERVAL = 0
    UPLOAD_PATHS = {}
    UPSTREAM_REPO = ""
    UPSTREAM_BRANCH = "master"
    UPDATE_PKGS = True
    USENET_SERVERS = []
    USER_SESSION_STRING = ""
    USER_TRANSMISSION = True
    USE_SERVICE_ACCOUNTS = False
    WEB_PINCODE = True
    YT_DLP_OPTIONS = {}
    YT_DESP = "Uploaded with Bzex bot"
    YT_TAGS = ["telegram", "bot", "youtube"]
    YT_CATEGORY_ID = 22
    YT_PRIVACY_STATUS = "unlisted"
    TMDB_API_KEY = ""
    FANARTTV_API_KEY = ""
    OPENAI_API_KEY = ""
    FORCE_PREMIUM_USER = False
    PROXY_PREFIX = ""
    PROXY_URL = ""
    REAL_DEBRID_API = ""
    DEBRID_LINK_API = ""
    # Sticker configuration: provide Telegram sticker file_ids or HTTP URLs to .webp/.webm
    # Examples: ["CAACAgUAAxkBAAIBQG...", "https://example.com/happy.webp"]
    START_STICKERS = [
        "CAACAgIAAxkBAAKtZGgWDeW6NzeQM179D9MC5hAEqM9EAAJvAQACMNSdEYAK4ffTTUU4NgQ",
    ]  # Random sticker when a task command is received
    ERROR_STICKERS = [
        "CAACAgIAAxkBAAKW0WeLJ62ixHtfg0_8EDsKziwveAnUAAInAAMkcWIaD6TdBKFK4zc2BA",
    ]  # Sad sticker on cancel/error
    SUCCESS_STICKERS = [
        "CAACAgIAAxkBAAKWwmeJVcWJ7njVPymzxH0PBCmhSQNZAAJJAgACVp29CiqXDJ0IUyEONgQ",
    ]  # Happy sticker on completed tasks

    # Auto-delete time for stickers in seconds (0 = no auto-delete)
    STICKER_AUTO_DELETE_TIME = 30

    # Anti-NSFW settings
    ANTI_NSFW = True  # Enable/disable anti-NSFW filtering
    NSFW_NOTIFY_OWNER = True  # Notify owner when NSFW content is detected

    @classmethod
    def get(cls, key):
        return getattr(cls, key) if hasattr(cls, key) else None

    @classmethod
    def set(cls, key, value):
        if hasattr(cls, key):
            setattr(cls, key, value)
        else:
            raise KeyError(f"{key} is not a valid configuration key.")

    @classmethod
    def get_all(cls):
        return {
            key: getattr(cls, key)
            for key in cls.__dict__.keys()
            if not key.startswith("__") and not callable(getattr(cls, key))
        }

    @classmethod
    def is_media_processing_disabled(cls):
        """Check if media processing operations are disabled"""
        return cls.DISABLE_MEDIA_PROCESSING

    @classmethod
    def is_merge_disabled(cls):
        """Check if merge operations are disabled"""
        return cls.DISABLE_MEDIA_PROCESSING

    @classmethod
    def is_stream_disabled(cls):
        """Check if stream operations are disabled"""
        return cls.DISABLE_MEDIA_PROCESSING

    @classmethod
    def is_encode_disabled(cls):
        """Check if encode operations are disabled"""
        return cls.DISABLE_MEDIA_PROCESSING

    @classmethod
    def is_watermark_disabled(cls):
        """Check if watermark operations are disabled"""
        return cls.DISABLE_MEDIA_PROCESSING

    @classmethod
    def get_speed_limit_bytes(cls):
        """Get download speed limit in bytes per second"""
        return cls.DL_SPEED_LIMIT * 1048576  # Convert MB/s to bytes/s

    @classmethod
    def load(cls):
        cls.load_config()
        cls.load_env()

    @classmethod
    def load_config(cls):
        try:
            settings = import_module("config")
        except ModuleNotFoundError:
            return
        for attr in dir(settings):
            if hasattr(cls, attr):
                value = getattr(settings, attr)
                if not value:
                    continue
                if isinstance(value, str):
                    value = value.strip()
                if attr == "DEFAULT_UPLOAD" and value not in ["gd", "gofile"]:
                    value = "rc"
                elif attr in [
                    "BASE_URL",
                    "RCLONE_SERVE_URL",
                    "INDEX_URL",
                    "SEARCH_API_LINK",
                ]:
                    if value:
                        value = value.strip("/")
                elif attr == "USENET_SERVERS":
                    try:
                        if not value[0].get("host"):
                            continue
                    except Exception:
                        continue
                setattr(cls, attr, value)
        for key in ["BOT_TOKEN", "OWNER_ID", "TELEGRAM_API", "TELEGRAM_HASH"]:
            value = getattr(cls, key)
            if isinstance(value, str):
                value = value.strip()
            if not value:
                raise ValueError(f"{key} variable is missing!")

    @classmethod
    def load_env(cls):
        config_vars = cls.get_all()
        for key in config_vars:
            env_value = getenv(key)
            if env_value is not None:
                converted_value = cls._convert_env_type(key, env_value)
                cls.set(key, converted_value)

    @classmethod
    def _convert_env_type(cls, key, value):
        original_value = getattr(cls, key, None)
        if original_value is None:
            return value
        # Handle list-type configs (e.g., START_STICKERS, ERROR_STICKERS, SUCCESS_STICKERS, SEARCH_PLUGINS, YT_TAGS)
        # - Empty env string should NOT override defaults
        # - JSON/py list strings are parsed
        # - Comma-separated strings are split into a list
        elif isinstance(original_value, list):
            if isinstance(value, str):
                s = value.strip()
                if s == "":
                    return original_value
                # Try to parse as a Python/JSON literal list
                try:
                    parsed = ast.literal_eval(s)
                    if isinstance(parsed, list):
                        return parsed if len(parsed) > 0 else original_value
                except Exception:
                    pass
                # Fallback: split by comma
                parts = [
                    p.strip() for p in s.replace("\n", ",").split(",") if p.strip()
                ]
                return parts if parts else original_value
            # Unknown type provided via env; keep original
            return original_value
        elif isinstance(original_value, bool):
            return value.lower() in ("true", "1", "yes")
        elif isinstance(original_value, int):
            # Special case: CMD_SUFFIX should remain a string even if numeric
            if key == "CMD_SUFFIX":
                return value
            try:
                return int(value)
            except ValueError:
                return original_value
        elif isinstance(original_value, float):
            try:
                return float(value)
            except ValueError:
                return original_value
        return value

    @classmethod
    def load_dict(cls, config_dict):
        for key, value in config_dict.items():
            if hasattr(cls, key):
                # Don't override list-type defaults with empty lists/strings (e.g., sticker pools)
                try:
                    original_value = getattr(cls, key)
                    if isinstance(original_value, list):
                        if value == [] or (
                            isinstance(value, str) and value.strip() == ""
                        ):
                            # keep existing default list
                            continue
                except Exception:
                    pass
                if key == "DEFAULT_UPLOAD" and value not in ["gd", "gofile"]:
                    value = "rc"
                elif key in [
                    "BASE_URL",
                    "RCLONE_SERVE_URL",
                    "INDEX_URL",
                    "SEARCH_API_LINK",
                ]:
                    if value:
                        value = value.strip("/")
                elif key == "USENET_SERVERS":
                    try:
                        if not value[0].get("host"):
                            value = []
                    except Exception:
                        value = []
                setattr(cls, key, value)
        for key in ["BOT_TOKEN", "OWNER_ID", "TELEGRAM_API", "TELEGRAM_HASH"]:
            value = getattr(cls, key)
            if isinstance(value, str):
                value = value.strip()
            if not value:
                raise ValueError(f"{key} variable is missing!")


class BinConfig:
    ARIA2_NAME = "speeddemon"
    QBIT_NAME = "torrentgod"
    FFMPEG_NAME = "vidwarlock"
    RCLONE_NAME = "cloudphantom"
    SABNZBD_NAME = "newsslayer"
