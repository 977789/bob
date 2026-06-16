# ruff: noqa: E402

from uvloop import install

install()

from subprocess import run as srun
from os import getcwd
from asyncio import Lock, new_event_loop, set_event_loop
from logging import (
    ERROR,
    INFO,
    WARNING,
    FileHandler,
    StreamHandler,
    basicConfig,
    getLogger,
)
from os import cpu_count, environ
from time import time

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pyrogram import utils as pyroutils

from .core.config_manager import BinConfig
from sabnzbdapi import SabnzbdClient

getLogger("requests").setLevel(WARNING)
getLogger("urllib3").setLevel(WARNING)
getLogger("pyrogram").setLevel(ERROR)
getLogger("aiohttp").setLevel(ERROR)
getLogger("apscheduler").setLevel(ERROR)
getLogger("httpx").setLevel(WARNING)
getLogger("pymongo").setLevel(WARNING)
getLogger("aiohttp").setLevel(WARNING)

pyroutils.MIN_CHAT_ID = -999999999999
pyroutils.MIN_CHANNEL_ID = -100999999999999
bot_start_time = time()

bot_loop = new_event_loop()
set_event_loop(bot_loop)

basicConfig(
    format="[%(asctime)s] [%(levelname)s] - %(message)s",  #  [%(filename)s:%(lineno)d]
    datefmt="%d-%b-%Y %I:%M:%S %p",
    handlers=[FileHandler("log.txt"), StreamHandler()],
    level=INFO,
)

LOGGER = getLogger(__name__)
cpu_no = cpu_count()

videos_tools_mode = {
    "vid_vid": "Video + Video",
    "vid_aud": "Video + Audio",
    "vid_sub": "Video + Subtitle",
    "subsync": "SubSync",
    "compress": "Compress",
    "convert": "Convert",
    "watermark": "Watermark",
    "extract": "Extract",
    "trim": "Trim",
    "speed": "Speed",
    "rmstream": "Remove Stream",
    "reordertracks": "Swap Stream",
    "intro_sub": "Intro Sub",
    "multi_res": "Encode",
}

bot_cache = {}
DOWNLOAD_DIR = "/usr/src/app/downloads/"
intervals = {"status": {}, "qb": "", "jd": "", "nzb": "", "stopAll": False}
qb_torrents = {}
jd_downloads = {}
nzb_jobs = {}
user_data = {}
ban_data = {}
cached_dict = {}
# Dictionary to track when users last clicked the refresh button (user_id: timestamp)
refresh_cooldown = {}
aria2_options = {}
qbit_options = {}
nzb_options = {}
queued_dl = {}
queued_up = {}
queued_media = {}  # New queue for media processing tasks
queued_media_processing = {}  # Queue for media processing tasks (ffmpeg, encoding, etc.)
status_dict = {}
task_dict = {}
rss_dict = {}
shortener_dict = {}
var_list = [
    "BOT_TOKEN",
    "TELEGRAM_API",
    "TELEGRAM_HASH",
    "OWNER_ID",
    "DATABASE_URL",
    "BASE_URL",
    "UPSTREAM_REPO",
    "UPSTREAM_BRANCH",
    "UPDATE_PKGS",
    "SHORTENER_ALIAS_PREFIX",
]
auth_chats = {}
excluded_extensions = ["aria2", "!qB", "ass"]
drives_names = []
drives_ids = []
index_urls = []
sudo_users = []
non_queued_dl = set()
non_queued_up = set()
non_queued_media = set()  # New set for tracking non-queued media tasks
non_queued_media_processing = set()  # Set of media processing tasks currently running
multi_tags = set()
task_dict_lock = Lock()
queue_dict_lock = Lock()
media_queue_lock = Lock()  # New lock for media queue operations
qb_listener_lock = Lock()
nzb_listener_lock = Lock()
jd_listener_lock = Lock()
cpu_eater_lock = Lock()
subprocess_lock = Lock()
same_directory_lock = Lock()

sabnzbd_client = SabnzbdClient(
    host="http://localhost",
    api_key="admin",
    port="8070",
)
srun([BinConfig.QBIT_NAME, "-d", f"--profile={getcwd()}"], check=False)


def env(key: str, default: str | int | float = ""):
    value = environ.get(key, default)
    if isinstance(value, str):
        if value.lstrip("-").isdigit():
            return int(value)
        if value.lower() in ("true", "false"):
            return value.lower() == "true"
        if value.startswith("[") and value.endswith("]"):
            return eval(value)
    return value


ARIA_NAME = env("ARIA_NAME", "baja")
QBIT_NAME = env("QBIT_NAME", "bajq")
FFMPEG_NAME = env("FFMPEG_NAME", "bajf")
SEVENZ_NAME = env("SEVENZ_NAME", "7z")
SPLIT_NAME = env("SPLIT_NAME", "split")
CLOUDFLARE_NAME = env("CLOUDFLARE_NAME", "cloudflared")
JAVA_NAME = env("JAVA_NAME", "java")

scheduler = AsyncIOScheduler(event_loop=bot_loop)
