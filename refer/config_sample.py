# REQUIRED CONFIG
BOT_TOKEN = ""
OWNER_ID = 0
TELEGRAM_API = 0
TELEGRAM_HASH = ""
DATABASE_URL = ""

# OPTIONAL CONFIG
DEFAULT_LANG = "en"
TG_PROXY = {}  # {"scheme": ”socks5”, "hostname": ””, "port": 1234, "username": ”user”, "password": ”pass”}
USER_SESSION_STRING = ""
CMD_SUFFIX = ""
AUTHORIZED_CHATS = ""
SUDO_USERS = ""
STATUS_LIMIT = 10
DEFAULT_UPLOAD = "rc"
STATUS_UPDATE_INTERVAL = 15
FILELION_API = ""
STREAMWISH_API = ""
EXCLUDED_EXTENSIONS = ""
INCOMPLETE_TASK_NOTIFIER = True
INCOMPLETE_AUTO_RESUME = True
YT_DLP_OPTIONS = ""
USE_SERVICE_ACCOUNTS = False
GOFILE_API = ""
NAME_SWAP = ""
FFMPEG_CMDS = {}
UPLOAD_PATHS = {}
TMDB_API_KEY = ""  # Required for Auto Thumbnail feature
FANARTTV_API_KEY = ""  # Optional: For landscape movie/TV posters as fallback (https://fanart.tv/get-an-api-key/)
STREAM_SWAP_ENABLED = (
    False  # Enables the ability to reorder audio and subtitle tracks in video files
)

# Video Hardsub Settings
VIDEO_HARDSUB_ENABLED = (
    False  # Enable hardsub feature to burn subtitles permanently into videos
)
VIDEO_HARDSUB_STYLE = "default"  # Subtitle style: default, bold, outline, shadow, glow
VIDEO_HARDSUB_FONT_SIZE = 20  # Font size for burned subtitles (8-72)
VIDEO_HARDSUB_FONT_NAME = "Arial"  # Font family for burned subtitles

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
DISABLE_MEDIA_PROCESSING = (
    False  # Master toggle: Disables merge, stream, encode, and watermark operations
)

# Telegraph
AUTHOR_NAME = "Bzex"
AUTHOR_URL = "https://t.me/MirrorLeechGroupz"

# Task Limits
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

# Insta video downloader api
INSTADL_API = ""

# Nzb search
HYDRA_IP = ""
HYDRA_API_KEY = ""

# Media Search
IMDB_TEMPLATE = """<b>Title: </b> {title} [{year}]
<b>Also Known As:</b> {aka}
<b>Rating ⭐️:</b> <i>{rating}</i>
<b>Release Info: </b> <a href="{url_releaseinfo}">{release_date}</a>
<b>Genre: </b>{genres}
<b>IMDb URL:</b> {url}
<b>Language: </b>{languages}
<b>Country of Origin : </b> {countries}

<b>Story Line: </b><code>{plot}</code>

<a href="{url_cast}">Read More ...</a>"""

# Task Tools
FORCE_SUB_IDS = ""
MEDIA_STORE = True
DELETE_LINKS = False
CLEAN_LOG_MSG = False

# Limiters
BOT_MAX_TASKS = 0
USER_MAX_TASKS = 0
USER_TIME_INTERVAL = 0
VERIFY_TIMEOUT = 0
LOGIN_PASS = ""

# Bot Settings
BOT_PM = False
SET_COMMANDS = True
TIMEZONE = "Asia/Kolkata"

# GDrive Tools
GDRIVE_ID = ""
GD_DESP = "Uploaded with WZ Bot"
IS_TEAM_DRIVE = False
STOP_DUPLICATE = False
INDEX_URL = ""

# YT Tools
YT_DESP = "Uploaded to YouTube by Bzex bot"
YT_TAGS = ["telegram", "bot", "youtube"]  # or as a comma-separated string
YT_CATEGORY_ID = 22
YT_PRIVACY_STATUS = "unlisted"

# Rclone
RCLONE_PATH = ""
RCLONE_FLAGS = ""
RCLONE_SERVE_URL = ""
SHOW_CLOUD_LINK = True
RCLONE_SERVE_PORT = 0
RCLONE_SERVE_USER = ""
RCLONE_SERVE_PASS = ""

# JDownloader
JD_EMAIL = ""
JD_PASS = ""

# Sabnzbd
USENET_SERVERS = [
    {
        "name": "main",
        "host": "",
        "port": 563,
        "timeout": 60,
        "username": "",
        "password": "",
        "connections": 8,
        "ssl": 1,
        "ssl_verify": 2,
        "ssl_ciphers": "",
        "enable": 1,
        "required": 0,
        "optional": 0,
        "retention": 0,
        "send_group": 0,
        "priority": 0,
    }
]

# Update
UPSTREAM_REPO = ""
UPSTREAM_BRANCH = "master"
UPDATE_PKGS = True

# Leech
LEECH_SPLIT_SIZE = 0
AS_DOCUMENT = False
EQUAL_SPLITS = False
MEDIA_GROUP = False
USER_TRANSMISSION = True
HYBRID_LEECH = True
FORCE_PREMIUM_USER = (
    False  # Set to True if Telegram isn't correctly detecting premium status
)
LEECH_PREFIX = ""
LEECH_SUFFIX = ""
LEECH_FONT = "b"
LEECH_CAPTION = ""
THUMBNAIL_LAYOUT = ""

# Sequential Processing
SEQUENTIAL_PROCESSING = (
    True  # Permanently enabled sequential file processing for leech operations
)

# Log Channels
LEECH_DUMP_CHAT = ""
LINKS_LOG_ID = ""
MIRROR_LOG_ID = ""

# qBittorrent/Aria2c
TORRENT_TIMEOUT = 0

# Download Speed Limit
DL_SPEED_LIMIT = 0  # Minimum download speed in MB/s to cancel task (0 = disabled)
# Examples: 1 = 1 MB/s, 2 = 2 MB/s, 5 = 5 MB/s, etc.
SPEED_LIMIT_TIMEOUT = (
    300  # Time in seconds to wait before canceling slow download (default: 5 minutes)
)

# Auto-Ping (Keep Bot Active)
AUTO_PING_INTERVAL = 5  # Interval in MINUTES to ping bot and keep it active (0 = disabled, recommended: 5-30 minutes)

BASE_URL = ""
BASE_URL_PORT = 0
WEB_PINCODE = True

# Queueing system
QUEUE_ALL = 0
QUEUE_DOWNLOAD = 0
QUEUE_UPLOAD = 0
QUEUE_MEDIA_PROCESSING = 0  # Global queue for heavy media processing (0 = disabled, 1 = one at a time, 2+ = concurrent limit)
# Queues: FFmpeg commands, Video encoding, Video watermarking
# Excludes: Merge operations and Stream operations (run immediately)# RSS
# Extraction Queue (memory saver)
# Limit simultaneous archive extractions. 0 = unlimited (current behavior), 1 = strictly one at a time (recommended for low RAM / Heroku), N = max concurrent.
QUEUE_EXTRACT = 1
# Threads used by 7z for extraction ("-mmt"). 1 keeps RAM low. Increase for faster extraction if you have memory headroom.
EXTRACT_THREADS = 1
RSS_DELAY = 600
RSS_CHAT = ""
RSS_SIZE_LIMIT = 0

# Torrent Search
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

OPENAI_API_KEY = ""  # Optional: For AI-based filename cleaning (https://platform.openai.com/api-keys)

REAL_DEBRID_API = ""
DEBRID_LINK_API = ""
# Proxy Configuration
PROXY_PREFIX = ""  # Prefix for proxy URLs (e.g., "https://proxy.example.com/")
PROXY_URL = ""

# Stickers (optional): put Telegram sticker file_ids or direct URLs to .webp/.webm
# Examples:
# START_STICKERS = ["CAACAgUAAxkBA...", "https://example.com/starting.webp"]
# ERROR_STICKERS = ["CAACAgIAAxkBA...", "https://example.com/sad.webp"]
# SUCCESS_STICKERS = ["CAACAgQAAxkBA...", "https://example.com/happy.webp"]
START_STICKERS = []
ERROR_STICKERS = []
SUCCESS_STICKERS = []

# Auto-delete time for stickers in seconds (0 = no auto-delete, default is 30 seconds)
STICKER_AUTO_DELETE_TIME = 30
