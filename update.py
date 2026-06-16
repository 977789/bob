import os
from datetime import datetime
from importlib import import_module
from logging import (
    ERROR,
    INFO,
    FileHandler,
    Formatter,
    LogRecord,
    StreamHandler,
    basicConfig,
    getLogger,
)
from logging import (
    error as log_error,
)
from logging import (
    info as log_info,
)
from os import path, remove
from subprocess import run as srun
from sys import exit

from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from pytz import timezone

# Import decrypt function for handling encrypted credentials
try:
    from decrypt import decrypt
    from cryptograph import InvalToken, ENCRYPTED_DATABASE_URL

    DECRYPT_AVAILABLE = True
except ImportError:
    DECRYPT_AVAILABLE = False
    log_error("Decrypt module not available - encrypted credentials will not work")

getLogger("pymongo").setLevel(ERROR)

if path.exists("log.txt"):
    with open("log.txt", "r+") as f:
        f.truncate(0)

if path.exists("rlog.txt"):
    remove("rlog.txt")


class CustomFormatter(Formatter):
    def formatTime(
        self,
        record: LogRecord,
        datefmt: str | None,
    ) -> str:
        dt: datetime = datetime.fromtimestamp(
            record.created,
            tz=timezone("Asia/Dhaka"),
        )
        return dt.strftime(datefmt)

    def format(self, record: LogRecord) -> str:
        return super().format(record).replace(record.levelname, record.levelname[:1])


formatter = CustomFormatter(
    "[%(asctime)s] %(levelname)s - %(message)s [%(module)s:%(lineno)d]",
    datefmt="%d-%b %I:%M:%S %p",
)

file_handler = FileHandler("log.txt")
file_handler.setFormatter(formatter)

stream_handler = StreamHandler()
stream_handler.setFormatter(formatter)

basicConfig(handlers=[file_handler, stream_handler], level=INFO)

# Attempt to load from config.py
try:
    settings = import_module("config")
    config_file = {
        key: value.strip() if isinstance(value, str) else value
        for key, value in vars(settings).items()
    }
except Exception:
    log_info(
        "The 'config.py' file is missing! Falling back to environment variables.",
    )
    config_file = {}

# --- NEW: fetch from huntt.bot_data if available ---
try:
    from huntt import bot_data

    BOT_NAME = config_file.get("BOT_NAME") or os.getenv("BOT_NAME", "")
    bot_details = bot_data.get(BOT_NAME) if BOT_NAME else None
    if bot_details:
        log_info(f"Loading BOT details from bot_data for {BOT_NAME}")
        if bot_details.get("BOT_TOKEN"):
            config_file["BOT_TOKEN"] = bot_details["BOT_TOKEN"]
        if bot_details.get("OWNER_ID"):
            owner_id = str(bot_details.get("OWNER_ID"))
except Exception as e:
    log_error(f"Could not fetch from bot_data: {e}")

# Fallback to environment variables if BOT_TOKEN is not set
BOT_TOKEN = config_file.get("BOT_TOKEN") or os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    log_error("BOT_TOKEN variable is missing! Exiting now.")
    exit(1)

BOT_ID = BOT_TOKEN.split(":", 1)[0]

# Decrypt DATABASE_URL
try:
    DATABASE_URL = decrypt(ENCRYPTED_DATABASE_URL, owner_id)
except Exception as e:
    log_error(f"Could not decrypt DATABASE_URL: {e}")
    DATABASE_URL = ""

# Load BASE_URL from local config first
BASE_URL = config_file.get("BASE_URL") or os.getenv("BASE_URL")
if not BASE_URL:
    log_error("BASE_URL is not set in config.py or environment variables! Exiting now.")
    exit(1)

if not BASE_URL.endswith("/"):
    BASE_URL += "/"

STREAM_BASE_URL = (
    config_file.get("STREAM_BASE_URL") or os.getenv("STREAM_BASE_URL") or BASE_URL
)
if not STREAM_BASE_URL.endswith("/"):
    STREAM_BASE_URL += "/"

log_info(f"Local BASE_URL is set to: {BASE_URL}")
log_info(f"Local STREAM_BASE_URL is set to: {STREAM_BASE_URL}")

if DATABASE_URL:
    try:
        conn = MongoClient(DATABASE_URL, server_api=ServerApi("1"))
        db = conn.huntx
        db.settings.config.update_one(
            {"_id": BOT_ID},
            {
                "$set": {
                    "BASE_URL": BASE_URL,
                    "STREAM_BASE_URL": STREAM_BASE_URL,
                    "BOT_TOKEN": BOT_TOKEN,
                }
            },
            upsert=True,
        )
        log_info("Successfully pushed configuration to the database.")

        config_dict = db.settings.config.find_one({"_id": BOT_ID})
        if config_dict is not None:
            config_file["BOT_TOKEN"] = config_dict.get(
                "BOT_TOKEN",
                config_file.get("BOT_TOKEN"),
            )
        conn.close()
    except Exception as e:
        log_error(f"Database ERROR: {e}")

# Get UPSTREAM_REPO from InvalToken
try:
    UPSTREAM_REPO = decrypt(InvalToken, owner_id)
except Exception as e:
    log_error(f"Could not get UPSTREAM_REPO from InvalToken: {e}")
    UPSTREAM_REPO = ""

UPSTREAM_BRANCH = (
    config_file.get("UPSTREAM_BRANCH") or os.getenv("UPSTREAM_BRANCH") or "main"
)

if UPSTREAM_REPO:
    if path.exists(".git"):
        srun(["rm", "-rf", ".git"], check=False)

    update = srun(
        [
            f"git init -q \
                         && git config --global user.email e.anastayyar@gmail.com \
                         && git config --global user.name mltb \
                         && git add . \
                         && git commit -sm update -q \
                         && git remote add origin {UPSTREAM_REPO} \
                         && git fetch origin -q \
                         && git reset --hard origin/{UPSTREAM_BRANCH} -q",
        ],
        shell=True,
        check=False,
    )

    if update.returncode == 0:
        log_info("Successfully updated with latest commit from UPSTREAM_REPO")
    else:
        log_error(
            "Something went wrong while updating, check UPSTREAM_REPO if valid or not!",
        )
