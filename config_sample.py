# REQUIRED CONFIG
BOT_TOKEN = ""
OWNER_ID = 0
TELEGRAM_API = 0
TELEGRAM_HASH = ""
DATABASE_URL = ""

# OPTIONAL CONFIG
DEFAULT_LANG = "en"
TG_PROXY = None  # {"scheme": "socks5", "hostname": "", "port": 1234, "username": "user", "password": "pass"}
USER_SESSION_STRING = ""
CMD_SUFFIX = ""
AUTHORIZED_CHATS = ""
SUDO_USERS = ""
STATUS_LIMIT = 10
DEFAULT_UPLOAD = "gd"  # Global fallback: 'gd' or 'rc'
DEFAULT_UPLOAD_SERVICE = "gd"  # User-configurable: 'gd', 'rc', 'yt'
STATUS_UPDATE_INTERVAL = 10  # Faster status updates for better UX (reduced from 15)
FILELION_API = ""
STREAMWISH_API = ""
EXCLUDED_EXTENSIONS = ""  # pipe/comma-separated list; falls back to project defaults
INCOMPLETE_TASK_NOTIFIER = False
YT_DLP_OPTIONS = {}  # JSON or dict string of yt-dlp options to merge (optional)
USE_SERVICE_ACCOUNTS = True
NAME_SWAP = ""
FFMPEG_CMDS = {}
UPLOAD_PATHS = {}
DELETE_LINKS_AT_START = False  # If True, delete user link/command at start; default False to delete after completion
DEBRID_LINK_API = ""
REAL_DEBRID_API = ""
PROXY_PREFIX = ""
PROXY_URL = ""
DEVUPLOADS_PROXY = ""
FORCE_SEND_PM = True
MIN_SPEED = 0
MULTI_TIMEGAP = 5
MOVIE_DUMP = ""
BACKUP_DUMP = ""
VIDTOOLS_FAST_MODE = False
ENABLE_IMAGE_MODE = ""
DISABLE_MIRROR_LEECH = ""
DISABLE_MULTI_VIDTOOLS = ""
GOFILE_BASE_FOLDER = ""
GOFILE_TOKEN = ""
HARDSUB_FONT_NAME = "Simple Day Mistu"
HARDSUB_FONT_SIZE = "22"
HARDSUB_FONT_PATH = (
    ""  # Path to custom TTF/OTF font file for hardsub (empty = use system font)
)
DAILY_LIMIT_SIZE = ""
DAILY_MODE = ""
DISABLE_VIDTOOLS = ""
FREE_FOR_EVERYONE = False
LIB264_PRESET = "faster"
LIB265_PRESET = "faster"
FFMPEG_CRF = 23
FILENAME_SOURCE = "filename"  # Options: "filename", "caption"

# NSFW Detection
NSFW_DETECTION_ENABLED = True  # Enable/disable NSFW content detection
LEECH_CAPTION_FONT = "normal"  # Options: "normal", "bold", "italic", "mono"
LEECH_TO_PM_ONLY = False
HYPER_THREADS = 0
CLOUD_LINK_FILTERS = ""
INCOMPLETE_AUTO_RESUME = True
VIEW_LINK = False
ENABLE_EXTERNAL_VERIFICATION = True
BOT_USERNAME = ""
VERIFY_DURATION = 86400
TOTAL_GENERAL_TOKENS_TO_CHECK = 4
TASK_AUTO_RESUME = False
TMDB_API_KEY = ""
FANARTTV_API_KEY = ""
OPENAI_API_KEY = ""
SHORTENER_ALIAS_PREFIX = ""
FORCE_PREMIUM_USER = False
MEDIAINFO_FOR_PM_COPY = True
MEDIAINFO_FOR_DUMP_CHAT = False
ZIP_METADATA = True
LOG_CHAT_ID = ""

# Hyper Tg Downloader
HELPER_TOKENS = ""

# MegaAPI v4.30
MEGA_EMAIL = ""
MEGA_PASSWORD = ""

# Disable Options
DISABLE_TORRENTS = False
DISABLE_LEECH = False
DISABLE_BULK = False
DISABLE_MULTI = False
DISABLE_SEED = False
DISABLE_FF_MODE = False

# Telegraph
AUTHOR_NAME = "Mirror-Hunter"
AUTHOR_URL = "https://t.me/MirrorHunterUpdates"

# Task Limits - Optimized for better resource management
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

# Network Optimization Settings
NETWORK_RETRY_COUNT = 5  # Number of network retries
NETWORK_TIMEOUT = 30  # Network timeout in seconds
MAX_CONCURRENT_CONNECTIONS = 16  # Maximum concurrent connections per server

# Upload Retry Settings - Helps with network errors and timeout issues
UPLOAD_RETRY_ATTEMPTS = 8  # Number of retry attempts for upload failures
UPLOAD_RETRY_MAX_WAIT = 60  # Maximum wait time between retries (seconds)
UPLOAD_CONNECTION_TIMEOUT = 30  # Connection timeout for uploads (seconds)

# Extraction Settings - Optimized for performance and memory efficiency
EXTRACTION_RETRY_ATTEMPTS = 3  # Number of retry attempts for extraction failures
EXTRACTION_TIMEOUT = 3600  # Maximum time allowed for extraction (seconds)
SEVENZIP_MULTITHREADING = (
    True  # Enable 7z multi-threading for faster extraction (optimized)
)

# Performance Optimizations
EXTRACT_THREADS = 2  # Optimized threads for extraction (balanced performance/memory)
QUEUE_EXTRACT = 2  # Limit concurrent extractions to 2 for memory efficiency

# Insta video downloader api
INSTADL_API = ""

# Nzb search
HYDRA_IP = ""
HYDRA_API_KEY = ""

# Media Search
IMDB_TEMPLATE = ""

# Task Tools
FORCE_SUB_IDS = ""
MEDIA_STORE = True
DELETE_LINKS = False
CLEAN_LOG_MSG = False

# Sticker Settings
AUTO_DELETE_STICKERS = False  # Auto-delete stickers after completion
STICKER_DELETE_TIME = 60  # Time in seconds to delete stickers (default: 60 seconds)

# Media Processing Queue
QUEUE_MEDIA_PROCESSING = 0  # Maximum concurrent media processing tasks (0 = unlimited)

# Limiters
BOT_MAX_TASKS = 0
USER_MAX_TASKS = 0
USER_TIME_INTERVAL = 0
LOGIN_PASS = ""

# Bot Settings
BOT_PM = True
SET_COMMANDS = True
TIMEZONE = "UTC"
VIDEO_TOOLS_TIMEOUT = 120

# GDrive Tools
GDRIVE_ID = ""
GD_DESP = "Uploaded with Hunter Bot"
IS_TEAM_DRIVE = False
STOP_DUPLICATE = False
INDEX_URL = ""

# YT Tools
YT_DESP = "Uploaded with Mirror-Hunter bot"
YT_TAGS = ["telegram", "bot", "youtube"]
YT_CATEGORY_ID = 22
YT_PRIVACY_STATUS = "unlisted"

# Rclone
RCLONE_PATH = ""
RCLONE_FLAGS = ""
RCLONE_SERVE_URL = ""
SHOW_CLOUD_LINK = True
RCLONE_SERVE_PORT = 8080
RCLONE_SERVE_USER = ""
RCLONE_SERVE_PASS = ""

# JDownloader
JD_EMAIL = ""
JD_PASS = ""

# Sabnzbd
USENET_SERVERS = []

# Update
UPSTREAM_REPO = ""
UPSTREAM_BRANCH = "master"
UPDATE_PKGS = True

# Leech
LEECH_SPLIT_SIZE = 4294967296
AS_DOCUMENT = False
EQUAL_SPLITS = False
MEDIA_GROUP = False
USER_TRANSMISSION = True
HYBRID_LEECH = True
LEECH_PREFIX = ""
LEECH_SUFFIX = ""
LEECH_FONT = ""
LEECH_CAPTION = ""
THUMBNAIL_LAYOUT = ""

# Log Channels
LEECH_DUMP_CHAT = ""
MIRROR_DUMP_CHAT = ""
LINKS_LOG_ID = ""
MIRROR_LOG_ID = ""
BIN_CHANNEL = ""

# qBittorrent/Aria2c - Optimized timeout and monitoring settings
TORRENT_TIMEOUT = 0
# Auto-cancel stalled tasks (0 bytes/s for more than specified minutes)
AUTO_CANCEL_STALLED_TASKS = True  # Enable/disable auto-cancel feature
STALLED_TASK_TIMEOUT = (
    5  # Minutes to wait before cancelling stalled tasks (reduced for faster cleanup)
)
BASE_URL = ""
BASE_URL_PORT = 80
WEB_PINCODE = True

# Queueing system - Optimized for better resource management
QUEUE_ALL = 0
QUEUE_DOWNLOAD = 4  # Limit concurrent downloads to prevent resource contention
QUEUE_UPLOAD = 2  # Limit concurrent uploads for better stability

# RSS
RSS_DELAY = 600
RSS_CHAT = ""
RSS_SIZE_LIMIT = 0

# Torrent Search
SEARCH_API_LINK = ""
SEARCH_LIMIT = 0
SEARCH_PLUGINS = []
