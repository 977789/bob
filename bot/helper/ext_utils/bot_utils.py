from asyncio import (
    create_subprocess_exec,
    create_subprocess_shell,
    run_coroutine_threadsafe,
    sleep,
)
from asyncio.subprocess import PIPE
from base64 import urlsafe_b64decode, urlsafe_b64encode
from concurrent.futures import ThreadPoolExecutor
from functools import partial, wraps
import re
import os
from re import compile as re_compile
from httpx import AsyncClient
from datetime import datetime
from pytz import timezone

from ... import bot_loop, user_data, LOGGER
from ...core.config_manager import Config
from ..telegram_helper.button_build import ButtonMaker
from .help_messages import (
    CLONE_HELP_DICT,
    MIRROR_HELP_DICT,
    YT_HELP_DICT,
)
from .telegraph_helper import telegraph

COMMAND_USAGE = {}

# Optimized thread pool with aggressive memory management
THREAD_POOL = ThreadPoolExecutor(
    max_workers=50  # Reduced from 250 to 50 to minimize memory usage and prevent resource exhaustion
)


class SetInterval:
    def __init__(self, interval, action, *args, **kwargs):
        self.interval = interval
        self.action = action
        self.task = bot_loop.create_task(self._set_interval(*args, **kwargs))

    async def _set_interval(self, *args, **kwargs):
        while True:
            await sleep(self.interval)
            try:
                await self.action(*args, **kwargs)
            except Exception as e:
                # Never let the interval die due to an exception
                LOGGER.error(f"SetInterval action error: {e}", exc_info=True)

    def cancel(self):
        self.task.cancel()


# Removed duplicate and buggy _build_command_usage definition (redefined below)


def _build_command_usage(help_dict, command_key):
    buttons = ButtonMaker()
    cmd_list = list(help_dict.keys())[1:]
    cmd_pages = [cmd_list[i : i + 10] for i in range(0, len(cmd_list), 10)]
    temp_store = []

    for i, page in enumerate(cmd_pages):
        for name in page:
            buttons.data_button(name, f"help {command_key} {name} {i}")
        if len(cmd_pages) > 1:
            if i > 0:
                buttons.data_button("⫷", f"help pre {command_key} {i - 1}")
            if i < len(cmd_pages) - 1:
                buttons.data_button("⫸", f"help nex {command_key} {i + 1}")
        buttons.data_button("Close", "help close", "footer")
        temp_store.append(buttons.build_menu(2))
        buttons.reset()

    COMMAND_USAGE[command_key] = [help_dict["main"], *temp_store]


def create_help_buttons():
    _build_command_usage(MIRROR_HELP_DICT, "mirror")
    _build_command_usage(YT_HELP_DICT, "yt")
    _build_command_usage(CLONE_HELP_DICT, "clone")


def compare_versions(v1, v2):
    v1, v2 = (list(map(int, v.split("-")[0][1:].split("."))) for v in (v1, v2))
    return (
        "New Version Update is Available! Check Now!"
        if v1 < v2
        else (
            "More Updated! Kindly Contribute in Official"
            if v1 > v2
            else "Already up to date with latest version"
        )
    )


def bt_selection_buttons(id_):
    gid = id_[:12] if len(id_) > 25 else id_
    pin = "".join([n for n in id_ if n.isdigit()][:4])
    buttons = ButtonMaker()
    if Config.WEB_PINCODE:
        buttons.url_button("Select Files", f"{Config.BASE_URL}/app/files?gid={id_}")
        buttons.data_button("Pincode", f"sel pin {gid} {pin}")
    else:
        buttons.url_button(
            "Select Files", f"{Config.BASE_URL}/app/files?gid={id_}&pin={pin}"
        )
    buttons.data_button("Done Selecting", f"sel done {gid} {id_}")
    buttons.data_button("Cancel", f"sel cancel {gid}")
    return buttons.build_menu(2)


async def get_telegraph_list(telegraph_content):
    path = [
        (
            await telegraph.create_page(
                title="Mirror-Leech-Bot Drive Search", content=content
            )
        )["path"]
        for content in telegraph_content
    ]
    if len(path) > 1:
        await telegraph.edit_telegraph(path, telegraph_content)
    buttons = ButtonMaker()
    buttons.url_button("🔎 VIEW", f"https://telegra.ph/{path[0]}")
    return buttons.build_menu(1)


def arg_parser(items, arg_base):
    if not items:
        return

    arg_start = -1
    i = 0
    total = len(items)
    bool_arg_set = {
        "-b",
        "-e",
        "-z",
        "-s",
        "-j",
        "-d",
        "-sv",
        "-ss",
        "-f",
        "-fd",
        "-fu",
        "-sync",
        "-hl",
        "-doc",
        "-med",
        "-vt",
        "-ut",
        "-bt",
        "-yt",
        "-ssg",  # SS Grid toggle
        "-ssgp",  # SS Grid PDF mode
    }
    if Config.DISABLE_BULK and "-b" in items:
        arg_base["-b"] = False

    if Config.DISABLE_MULTI and "-i" in items:
        arg_base["-i"] = 0

    if Config.DISABLE_SEED and "-d" in items:
        arg_base["-d"] = False

    while i < total:
        part = items[i]

        if part in arg_base:
            if arg_start == -1:
                arg_start = i
            if (
                i + 1 == total
                and part in bool_arg_set
                or part
                in [
                    "-s",
                    "-j",
                    "-f",
                    "-fd",
                    "-fu",
                    "-sync",
                    "-hl",
                    "-doc",
                    "-med",
                    "-ut",
                    "-bt",
                    "-yt",
                    "-ssg",
                    "-ssgp",
                ]
            ):
                arg_base[part] = True
            else:
                sub_list = []
                for j in range(i + 1, total):
                    if items[j] in arg_base:
                        if part in bool_arg_set and not sub_list:
                            arg_base[part] = True
                            break
                        if not sub_list:
                            break
                        check = " ".join(sub_list).strip()
                        if check.startswith("[") and check.endswith("]"):
                            break
                        elif not check.startswith("["):
                            break
                    sub_list.append(items[j])
                if sub_list:
                    value = " ".join(sub_list)
                    if part == "-ff" and not value.strip().startswith("["):
                        arg_base[part].add(value)
                    else:
                        arg_base[part] = value
                    i += len(sub_list)

        i += 1

    if "link" in arg_base:
        link_items = items[:arg_start] if arg_start != -1 else items
        if link_items:
            arg_base["link"] = " ".join(link_items)


def get_size_bytes(size):
    size = size.lower()
    if "k" in size:
        size = int(float(size.split("k")[0]) * 1024)
    elif "m" in size:
        size = int(float(size.split("m")[0]) * 1048576)
    elif "g" in size:
        size = int(float(size.split("g")[0]) * 1073741824)
    elif "t" in size:
        size = int(float(size.split("t")[0]) * 1099511627776)
    else:
        size = 0
    return size


async def get_content_type(url):
    try:
        async with AsyncClient() as client:
            response = await client.get(url, allow_redirects=True, verify=False)
            return response.headers.get("Content-Type")
    except Exception:
        return None


def update_user_ldata(id_, key, value):
    user_data.setdefault(id_, {})
    user_data[id_][key] = value


def decode_output(st, typee: str = "error"):
    try:
        # Handle both bytes and string inputs
        if isinstance(st, bytes):
            return st.decode("utf-8").strip()
        elif isinstance(st, str):
            return st.strip()
        else:
            return str(st).strip()
    except Exception:
        return f"Unable to decode the {typee}!"


def encode_slink(string):
    return (urlsafe_b64encode(string.encode("ascii")).decode("ascii")).strip("=")


def decode_slink(b64_str):
    try:
        # Clean the base64 string and add proper padding
        cleaned_b64 = b64_str.strip("=")
        # Calculate proper padding
        padding_needed = (4 - len(cleaned_b64) % 4) % 4
        padded_b64 = cleaned_b64 + "=" * padding_needed

        # Validate the length is correct
        if len(padded_b64) % 4 != 0:
            raise ValueError("Invalid base64 string length")

        return urlsafe_b64decode(padded_b64.encode("ascii")).decode("ascii")
    except Exception as e:
        # Only log as debug for common invalid inputs like "start", "help", etc.
        # to reduce noise in logs
        if b64_str.lower() in ["start", "help", "cancel", "close"]:
            LOGGER.debug(f"Invalid base64 input '{b64_str}': {e}")
        else:
            LOGGER.error(f"Failed to decode slink '{b64_str}': {e}")
        # Return a safe fallback or raise a more descriptive error
        raise ValueError(f"Invalid or corrupted base64 string: {b64_str}")


async def cmd_exec(cmd, shell=False):
    if shell:
        proc = await create_subprocess_shell(cmd, stdout=PIPE, stderr=PIPE)
    else:
        proc = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
    stdout, stderr = await proc.communicate()
    stdout = decode_output(stdout, "response")
    stderr = decode_output(stderr, "error")
    return stdout, stderr, proc.returncode


def clean_video_name(file_path, compress=False):
    base_name = os.path.basename(file_path)
    final_name = os.path.splitext(base_name)[0]
    if compress:
        final_name = re.sub(
            r"[-._]?(360|480|540|720|1080)(p)?", "", final_name, flags=re.IGNORECASE
        )
    return final_name


def new_task(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        task = bot_loop.create_task(func(*args, **kwargs))
        return task

    return wrapper


async def sync_to_async(func, *args, wait=True, **kwargs):
    pfunc = partial(func, *args, **kwargs)
    future = bot_loop.run_in_executor(THREAD_POOL, pfunc)
    return await future if wait else future


def async_to_sync(func, *args, wait=True, **kwargs):
    future = run_coroutine_threadsafe(func(*args, **kwargs), bot_loop)
    return future.result() if wait else future


def loop_thread(func):
    @wraps(func)
    def wrapper(*args, wait=False, **kwargs):
        future = run_coroutine_threadsafe(func(*args, **kwargs), bot_loop)
        return future.result() if wait else future

    return wrapper


def get_date_time(message_date_timestamp):  # Changed to accept timestamp directly
    time_zone = Config.TIMEZONE  # Corrected: Assuming Config.TIMEZONE is available
    date_time = datetime.fromtimestamp(message_date_timestamp, tz=timezone(time_zone))
    return date_time.strftime("%d/%m/%y"), date_time.strftime("%I:%M:%S %p")


def presuf_remname_name(listener, file_name: str):
    prename = listener.name_prefix or listener.user_dict.get("prename", "")
    sufname = listener.name_suffix or listener.user_dict.get("sufname", "")
    remname = listener.user_dict.get("REMNAME", "")  # Changed "remname" to "REMNAME"
    file_prefix = Config.FILENAME_PREFIX
    if not any([prename, sufname, remname, file_prefix]):
        return file_name
    listener.seed = False  # Assuming 'seed' attribute might be used elsewhere or by other parts of pre/suf logic
    if prename and prename not in file_name:
        file_name = f"{prename} {file_name}".strip()
    if (
        sufname and sufname not in file_name and "." in file_name[-12:]
    ):  # Check if '.' in last 12 chars to guess extension
        fname, ext = file_name.rsplit(".", 1)
        file_name = f"{fname} {sufname}.{ext}"
    if file_prefix and file_prefix not in file_name:  # Global prefix
        file_name = f"{file_prefix} {file_name}".strip()
    if remname:
        parts = [p.strip() for p in remname.split("|") if p.strip()]
        if parts:
            # Process each pattern to determine if it's literal or regex
            processed_parts = []
            for part in parts:
                if part.startswith("regex:"):
                    # Remove the prefix and use raw regex
                    pattern = part[6:]  # Remove 'regex:' prefix
                    processed_parts.append(pattern)
                else:
                    # Literal string - escape regex special characters
                    processed_parts.append(re.escape(part))

            remname_regex_str = "|".join(processed_parts)
            try:
                remname_regex = re_compile(remname_regex_str, re.IGNORECASE)
                LOGGER.debug(
                    f"Applying remname regex '{remname_regex_str}' to filename: {file_name}"
                )
                file_name = remname_regex.sub("", file_name)
                LOGGER.debug(f"After remname applied: {file_name}")
            except Exception as e:
                LOGGER.error(
                    f"Invalid regex created from remname '{remname}' (Effective regex string: '{remname_regex_str}'). Error: {e}"
                )
    # Apply Name Substitution (-ns/NAME_SWAP)
    try:
        name_swap_rules = getattr(listener, "name_swap", None)
        if name_swap_rules:
            name_part, ext_part = os.path.splitext(file_name)
            original_name_part = name_part
            for swap_item in name_swap_rules:
                if not isinstance(swap_item, (list, tuple)):
                    continue
                pattern, replacement, cnt_str, flag_str = (
                    list(swap_item) + ["", "0", "NOFLAG"]
                )[:4]

                # Check if this is a simple removal (should escape regex chars) or advanced regex
                is_simple_removal = (
                    len(swap_item) == 1  # Just pattern
                    or (
                        len(swap_item) == 2 and swap_item[1] == ""
                    )  # Pattern with empty replacement
                )

                # For simple removals, escape regex special characters
                if is_simple_removal:
                    pattern = re.escape(pattern)
                    # Default to case-insensitive for simple removals if no flag specified
                    # Check for default values that indicate no user-specified flag
                    if flag_str in ("NOFLAG", "0", ""):
                        flag_str = "IGNORECASE"

                # Count handling: 0 => replace all
                try:
                    count_val = int(cnt_str) if str(cnt_str).isdigit() else 0
                except Exception:
                    count_val = 0
                # Flags handling
                regex_flags = getattr(re, str(flag_str).upper(), 0)
                try:
                    name_part = re.sub(
                        pattern,
                        str(replacement or ""),
                        name_part,
                        count_val,
                        flags=regex_flags,
                    )
                except Exception as e_swap:
                    LOGGER.error(f"NameSub error for pattern '{pattern}': {e_swap}")
                    # Continue with other rules

            if name_part != original_name_part:
                file_name = f"{name_part}{ext_part}"
    except Exception as e_any_swap:
        LOGGER.error(f"Unexpected NameSub error: {e_any_swap}")
    # Common cleanup for multiple spaces and leading/trailing slashes or unwanted chars
    file_name = file_name.replace("  ", " ").replace("/", "").strip()
    return file_name


def is_valid_cookies_file(cookie_file_path):
    """
    Validates if a cookie file exists and is in valid Netscape format.

    Args:
        cookie_file_path (str): Path to the cookie file

    Returns:
        bool: True if valid, False if invalid/corrupted/empty/doesn't exist
    """
    try:
        if not cookie_file_path or not os.path.exists(cookie_file_path):
            return False

        # Check if file is empty
        if os.path.getsize(cookie_file_path) == 0:
            return False

        with open(cookie_file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read().strip()

        # Check if file is empty after stripping whitespace
        if not content:
            return False

        lines = content.split("\n")
        valid_lines = 0

        for line in lines:
            line = line.strip()

            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue

            # Netscape format should have at least 6 tab-separated fields:
            # domain, domain_specified, path, secure, expires, name, value
            # Some variants may have 7 fields
            parts = line.split("\t")
            if len(parts) >= 6:
                # Basic validation that required fields are present
                domain, domain_specified, path, secure, expires, name = parts[:6]
                if domain and path and name:
                    valid_lines += 1

        # Consider file valid if it has at least one valid cookie line
        return valid_lines > 0

    except Exception as e:
        LOGGER.warning(f"Cookie file validation error for {cookie_file_path}: {e}")
        return False
