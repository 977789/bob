from importlib import import_module
from os import getenv

try:
    from huntt import bot_data
except ImportError:
    bot_data = {}

IMAGES = (
    "https://telegra.ph/file/8208a66b9b32901366093.png https://telegra.ph/file/3512913400b2702ae9799.png https://telegra.ph/file/4eaebafb57d454f849950.png "
    "https://telegra.ph/file/d8adc79996a14d1edaba7.png https://telegra.ph/file/dbeadc46b14e42d215c7c.png https://telegra.ph/file/574afd675cfa2327d2ac4.png "
    "https://telegra.ph/file/85164551cdcfc0c0bbe72.png https://telegra.ph/file/0c08909cbb31ff829b83b.png https://telegra.ph/file/d7a147f27fccec607c447.png"
)


class Config:
    AS_DOCUMENT = False
    AUTHORIZED_CHATS = ""
    BASE_URL = ""
    BASE_URL_PORT = 80
    BIN_CHANNEL = ""
    BOT_TOKEN = ""
    BOT_NAME = ""
    HELPER_TOKENS = ""
    BOT_MAX_TASKS = 0
    BOT_PM = True
    CMD_SUFFIX = ""
    VIDEO_TOOLS_TIMEOUT = 120
    DEFAULT_LANG = "en"
    DATABASE_URL = ""
    DEFAULT_UPLOAD = "gd"  # Global fallback: 'gd' or 'rc'
    DEFAULT_UPLOAD_SERVICE = "gd"  # User-configurable: 'gd', 'rc', 'yt'
    DELETE_LINKS = False
    DISABLE_TORRENTS = False
    DISABLE_LEECH = False
    DISABLE_BULK = False
    DISABLE_MULTI = False
    DISABLE_SEED = False
    STREAM_MULTI_TOKENS = ""
    DISABLE_FF_MODE = False
    DEBRID_LINK_API = ""
    REAL_DEBRID_API = ""
    PROXY_PREFIX = ""
    PROXY_URL = ""
    DEVUPLOADS_PROXY = ""
    EQUAL_SPLITS = False
    EXCLUDED_EXTENSIONS = ""
    FFMPEG_CMDS = {}
    FILELION_API = ""
    MEDIA_STORE = True
    FORCE_SEND_PM = True  # Added
    FORCE_SUB_IDS = ""
    DELETE_LINKS_AT_START = False
    GDRIVE_ID = ""
    GD_DESP = "Uploaded with Hunter Bot"
    AUTHOR_NAME = "Mirror-Hunter"
    AUTHOR_URL = "https://t.me/MirrorHunterUpdates"
    INSTADL_API = ""
    IMDB_TEMPLATE = ""
    VPS_DEPLOY = False
    INCOMPLETE_TASK_NOTIFIER = False
    INDEX_URL = ""
    IS_TEAM_DRIVE = True
    JD_EMAIL = ""
    JD_PASS = ""
    MEGA_EMAIL = ""
    MEGA_PASSWORD = ""
    DIRECT_LIMIT = 0
    MIN_SPEED = 0
    MEGA_LIMIT = 0
    TORRENT_LIMIT = 0
    GD_DL_LIMIT = 0
    RC_DL_LIMIT = 0
    CLONE_LIMIT = 0
    JD_LIMIT = 0
    NZB_LIMIT = 0
    YTDLP_LIMIT = 0
    PLAYLIST_LIMIT = 0
    MULTI_TIMEGAP = 5
    LEECH_LIMIT = 0
    EXTRACT_LIMIT = 0
    ARCHIVE_LIMIT = 0
    STORAGE_LIMIT = 0
    LEECH_DUMP_CHAT = ""
    AUTO_DELETE_FROM_OWNER_LEECH_DUMP = (
        True  # Auto-delete files from owner's LEECH_DUMP_CHAT after forwarding
    )
    MIRROR_DUMP_CHAT = ""
    MOVIE_DUMP = ""
    BACKUP_DUMP = ""
    LINKS_LOG_ID = ""
    VIDTOOLS_FAST_MODE = False
    ENABLE_IMAGE_MODE = "True"
    DISABLE_MIRROR_LEECH = ""
    DISABLE_MULTI_VIDTOOLS = ""
    GOFILE_BASE_FOLDER = ""
    GOFILE_TOKEN = ""
    IMAGE_ACCESS = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_ARIA = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_AUTH = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_BOLD = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_BUZZHEAVIER = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_BYE = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_CANCEL = "https://telegra.ph/file/b9e5c05c2c818493cd2cd.jpg"
    IMAGE_CAPTION = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_COMMONS_CHECK = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_COMPLETE = "https://i.postimg.cc/3wJ2n8Vg/mhunt.jpg"
    IMAGE_CONEDIT = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_CONPRIVATE = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_CONSET = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_CONVIEW = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_COOKIES = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_DUMP = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_ERROR = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_EXTENSION = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_GD = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_GOFILE = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_HELP = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_HEROKU = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_HTML = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_IMDB = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_INFO = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_ITALIC = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_JD = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_ATTACHMENT = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_LAYOUT = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_LEECH = (
        "https://i.postimg.cc/3wJ2n8Vg/mhunt.jpg"  # Image for leech completion messages
    )
    IMAGE_LOGS = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_MDL = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_MIRROR = "https://i.postimg.cc/3wJ2n8Vg/mhunt.jpg"  # Image for mirror completion messages
    IMAGE_MEDINFO = "https://graph.org/file/62b0667c1ebb0a2f28f82.png"
    IMAGE_METADATA = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_MONO = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_NORMAL = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_OWNER = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_PAUSE = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_PRENAME = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_QBIT = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_RCLONE = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_REMNAME = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_RSS = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_SEARCH = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_STATS = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_STATUS = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_SUFNAME = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_TMDB = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_TXT = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_UNAUTH = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_UNKNOW = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_USER = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_USETIINGS = "https://telegra.ph/file/06d98362e83847d806926.jpg"
    IMAGE_VIDTOOLS = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_WEL = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_WIBU = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_YT = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    IMAGE_ZIP = "https://telegra.ph/file/5469a2d03f6b1b8b88dab.jpg"
    # Stream utils defaults
    ENABLE_STREAM_LINK = False
    STREAM_BASE_URL = ""
    STREAM_PORT = 0
    HARDSUB_FONT_NAME = "Simple Day Mistu"
    HARDSUB_FONT_SIZE = "22"
    DAILY_LIMIT_SIZE = ""
    DAILY_MODE = ""
    DISABLE_VIDTOOLS = ""
    FREE_FOR_EVERYONE = False
    LIB264_PRESET = "faster"
    LIB265_PRESET = "faster"
    FFMPEG_CRF = 23
    MIRROR_LOG_ID = ""
    CLEAN_LOG_MSG = False
    LEECH_PREFIX = ""
    LEECH_CAPTION = ""
    LEECH_SUFFIX = ""
    LEECH_FONT = ""
    FILENAME_SOURCE = "caption"
    LEECH_CAPTION_FONT = "mono"
    LEECH_SPLIT_SIZE = 2097152000
    MEDIA_GROUP = False
    HYBRID_LEECH = True
    LEECH_TO_PM_ONLY = False
    HYPER_THREADS = 0
    HYDRA_IP = ""
    HYDRA_API_KEY = ""
    NAME_SWAP = ""
    OWNER_ID = 0
    QUEUE_ALL = 0
    QUEUE_DOWNLOAD = 0
    QUEUE_UPLOAD = 0
    QUEUE_MEDIA_PROCESSING = 0
    RCLONE_FLAGS = ""
    RCLONE_PATH = ""
    RCLONE_SERVE_URL = ""
    CLOUD_LINK_FILTERS = ""
    SHOW_CLOUD_LINK = True
    RCLONE_SERVE_USER = ""
    RCLONE_SERVE_PASS = ""
    RCLONE_SERVE_PORT = 8080
    RSS_CHAT = ""
    RSS_DELAY = 600
    INCOMPLETE_AUTO_RESUME = True
    RSS_SIZE_LIMIT = 0
    SEARCH_API_LINK = ""
    SEARCH_LIMIT = 0
    SEARCH_PLUGINS = []
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
    VIEW_LINK = False
    ENABLE_EXTERNAL_VERIFICATION = True
    VERIFY_BOT = "huntverify_bot"
    DATABASE_URL_VERIFY = "mongodb+srv://huntermirror8:167400@verify.hkol8zr.mongodb.net/?retryWrites=true&w=majority&appName=verify"
    DATABASE_NAME_VERIFY = "verify"
    BOT_USERNAME = ""
    VERIFY_DURATION = 86400
    TOTAL_GENERAL_TOKENS_TO_CHECK = 4
    LOGIN_PASS = ""
    TORRENT_TIMEOUT = 0
    AUTO_CANCEL_STALLED_TASKS = True
    STALLED_TASK_TIMEOUT = 10
    MAX_CONCURRENT_TRANSMISSIONS = 15
    TIMEZONE = "UTC"
    TASK_AUTO_RESUME = False
    USER_MAX_TASKS = 0
    USER_TIME_INTERVAL = 0
    UPLOAD_PATHS = {}
    UPSTREAM_REPO = ""
    UPSTREAM_BRANCH = "main"
    UPDATE_PKGS = True
    USENET_SERVERS = []
    USER_SESSION_STRING = ""
    USER_TRANSMISSION = True
    USE_SERVICE_ACCOUNTS = True
    WEB_PINCODE = True
    YT_DLP_OPTIONS = {}
    YT_DESP = "Uploaded with Mirror-Hunter bot"
    YT_TAGS = ["telegram", "bot", "youtube"]
    YT_CATEGORY_ID = 22
    YT_PRIVACY_STATUS = "unlisted"
    TMDB_API_KEY = ""
    FANARTTV_API_KEY = ""
    OPENAI_API_KEY = ""
    SHORTENER_ALIAS_PREFIX = ""
    FORCE_PREMIUM_USER = False
    MEDIAINFO_FOR_PM_COPY = True
    MEDIAINFO_FOR_DUMP_CHAT = False
    NSFW_DETECTION_ENABLED = True
    ZIP_METADATA = True
    QUEUE_EXTRACT = 2  # Optimized concurrent archive extractions for better performance
    EXTRACT_THREADS = (
        2  # Optimized 7z threads for faster extraction while managing memory
    )
    EXTRACTION_RETRY_ATTEMPTS = 3
    EXTRACTION_TIMEOUT = 3600
    LOG_CHAT_ID = ""
    START_STICKERS = [
        "CAACAgIAAxkBAAEJwV9osXmBGVm1LZKKPXCRkJvYn35WSwACvg8AAvbk0EmejJ6Vjfwi8h4E",
    ]
    ERROR_STICKERS = [
        "CAACAgIAAxkBAAKW0WeLJ62ixHtfg0_8EDsKziwveAnUAAInAAMkcWIaD6TdBKFK4zc2BA",
    ]
    SUCCESS_STICKERS = [
        "CAACAgIAAxkBAAEJwV9osXmBGVm1LZKKPXCRkJvYn35WSwACvg8AAvbk0EmejJ6Vjfwi8h4E",
    ]
    AUTO_DELETE_STICKERS = True
    STICKER_DELETE_TIME = 60

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
    def load(cls):
        cls.load_config()
        cls.load_env()
        cls.load_bot_data()
        # Moved validation here to run AFTER all configs are loaded
        for key in ["BOT_TOKEN", "OWNER_ID", "TELEGRAM_API", "TELEGRAM_HASH"]:
            value = getattr(cls, key)
            if isinstance(value, str):
                value = value.strip()
            if not value:
                raise ValueError(f"{key} variable is missing!")

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
                if attr == "DEFAULT_UPLOAD" and value != "gd":
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
        # Validation was removed from here
        if not cls.BIN_CHANNEL:
            cls.BIN_CHANNEL = cls.LEECH_DUMP_CHAT

    @classmethod
    def load_env(cls):
        config_vars = cls.get_all()
        for key in config_vars:
            env_value = getenv(key)
            if env_value is not None:
                converted_value = cls._convert_env_type(key, env_value)
                cls.set(key, converted_value)

    @classmethod
    def load_bot_data(cls):
        """
        Load configuration from huntt bot_data if available.
        This function dynamically overrides config variables with values from bot_data,
        making the configuration more flexible and centralized.
        """
        if not bot_data:
            return

        botname = getattr(cls, "BOT_NAME")
        if not botname:
            return

        bot_details = bot_data.get(botname)
        if not bot_details:
            return

        exclude_keys = [
            "BOT_NAME",
            "SUDO_USERS",
            "AUTHORIZED_CHATS",
        ]

        for key, value in bot_details.items():
            if hasattr(cls, key) and key not in exclude_keys:
                if value is not None:
                    converted_value = cls._convert_env_type(key, str(value))
                    setattr(cls, key, converted_value)

    @classmethod
    def _convert_env_type(cls, key, value):
        import ast

        original_value = getattr(cls, key, None)
        if original_value is None:
            return value
        elif isinstance(original_value, list):
            if isinstance(value, str):
                value = value.strip()
                if not value:
                    return original_value
                if (value.startswith("[") and value.endswith("]")) or (
                    value.startswith("(") and value.endswith(")")
                ):
                    try:
                        parsed = ast.literal_eval(value)
                        if isinstance(parsed, (list, tuple)):
                            return list(parsed)
                    except Exception:
                        pass
                if "," in value:
                    return [item.strip() for item in value.split(",") if item.strip()]
                return [value]
            return original_value
        elif isinstance(original_value, bool):
            return value.lower() in ("true", "1", "yes")
        elif isinstance(original_value, int):
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
                try:
                    original_value = getattr(cls, key)
                    if isinstance(original_value, list):
                        if value == [] or (
                            isinstance(value, str) and value.strip() == ""
                        ):
                            continue
                except Exception:
                    pass
                if key == "DEFAULT_UPLOAD" and value != "gd":
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
    ARIA2_NAME = "syncd"
    QBIT_NAME = "pkgupd"
    FFMPEG_NAME = "netd"
    FFPROBE_NAME = "ffprobe"
    RCLONE_NAME = "filechk"
    SABNZBD_NAME = "procm"
