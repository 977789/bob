from asyncio import Event
from time import time

from ... import (
    LOGGER,
    bot_cache,
    non_queued_dl,
    non_queued_up,
    non_queued_media,  # New import for media queue tracking
    non_queued_media_processing,  # Enhanced media processing tracking
    queue_dict_lock,
    media_queue_lock,  # New import for media queue lock
    queued_dl,
    queued_up,
    queued_media,  # New import for media queue
    queued_media_processing,  # Enhanced media processing queue
    user_data,
)
from ...core.config_manager import Config
from ..mirror_leech_utils.gdrive_utils.search import GoogleDriveSearch
from ..telegram_helper.filters import CustomFilters
from ..telegram_helper.tg_utils import check_botpm, forcesub  # verify_token removed
from .bot_utils import get_telegraph_list, sync_to_async
from .files_utils import get_base_name, check_storage_threshold
from .verification_checker import perform_verification_check  # New import
from .links_utils import is_gdrive_id
from .status_utils import get_readable_time, get_readable_file_size, get_specific_tasks


async def stop_duplicate_check(listener):
    if (
        isinstance(listener.up_dest, int)
        or listener.is_leech
        or listener.select
        or not is_gdrive_id(listener.up_dest)
        or (listener.up_dest.startswith("mtp:") and listener.stop_duplicate)
        or not listener.stop_duplicate
        or listener.same_dir
    ):
        return False, None

    name = listener.name
    LOGGER.info(f"Checking File/Folder if already in Drive: {name}")

    if listener.compress:
        name = f"{name}.zip"
    elif listener.extract:
        try:
            name = get_base_name(name)
        except Exception:
            name = None

    if name is not None:
        telegraph_content, contents_no = await sync_to_async(
            GoogleDriveSearch(stop_dup=True, no_multi=listener.is_clone).drive_list,
            name,
            listener.up_dest,
            listener.user_id,
        )
        if telegraph_content:
            msg = f"File/Folder is already available in Drive.\nHere are {contents_no} list results:"
            button = await get_telegraph_list(telegraph_content)
            return msg, button

    return False, None


async def check_running_tasks(listener, state="dl"):
    all_limit = Config.QUEUE_ALL
    state_limit = Config.QUEUE_DOWNLOAD if state == "dl" else Config.QUEUE_UPLOAD
    event = None
    is_over_limit = False
    async with queue_dict_lock:
        if state == "up" and listener.mid in non_queued_dl:
            non_queued_dl.remove(listener.mid)
        if (
            (all_limit or state_limit)
            and not listener.force_run
            and not (listener.force_upload and state == "up")
            and not (listener.force_download and state == "dl")
        ):
            dl_count = len(non_queued_dl)
            up_count = len(non_queued_up)
            t_count = dl_count if state == "dl" else up_count
            is_over_limit = (
                all_limit
                and dl_count + up_count >= all_limit
                and (not state_limit or t_count >= state_limit)
            ) or (state_limit and t_count >= state_limit)
            if is_over_limit:
                event = Event()
                if state == "dl":
                    queued_dl[listener.mid] = event
                else:
                    queued_up[listener.mid] = event
        if not is_over_limit:
            if state == "up":
                non_queued_up.add(listener.mid)
            else:
                non_queued_dl.add(listener.mid)

    return is_over_limit, event


async def start_dl_from_queued(mid: int):
    queued_dl[mid].set()
    del queued_dl[mid]
    non_queued_dl.add(mid)


async def start_up_from_queued(mid: int):
    queued_up[mid].set()
    del queued_up[mid]
    non_queued_up.add(mid)


async def start_media_from_queued(mid: int):
    """Start a media processing task from queue"""
    queued_media[mid].set()
    del queued_media[mid]
    non_queued_media.add(mid)


async def check_media_queue_limit(listener):
    """Check if media processing should be queued based on QUEUE_MEDIA_PROCESSING limit"""
    if not (media_limit := Config.QUEUE_MEDIA_PROCESSING):
        return False, None  # No media queue limit, proceed immediately

    # Check if this is a media processing task (FFmpeg, encoding, watermarking)
    is_media_task = any(
        [
            getattr(listener, "is_ffmpeg", False),
            getattr(listener, "is_video_encode", False),
            getattr(listener, "is_watermark", False),
            getattr(listener, "video_mode", False),
            listener.compress,
            listener.extract,
        ]
    )

    if not is_media_task:
        return False, None  # Not a media task, proceed normally

    async with media_queue_lock:
        media_running = len(non_queued_media)
        if media_running >= media_limit:
            LOGGER.info(
                f"Media queue limit reached ({media_running}/{media_limit}), queuing task"
            )
            event = Event()
            queued_media[listener.mid] = event
            return True, event

        non_queued_media.add(listener.mid)
        return False, None


async def start_from_queued():
    if all_limit := Config.QUEUE_ALL:
        dl_limit = Config.QUEUE_DOWNLOAD
        up_limit = Config.QUEUE_UPLOAD
        async with queue_dict_lock:
            dl = len(non_queued_dl)
            up = len(non_queued_up)
            all_ = dl + up
            if all_ < all_limit:
                f_tasks = all_limit - all_
                if queued_up and (not up_limit or up < up_limit):
                    for index, mid in enumerate(list(queued_up.keys()), start=1):
                        await start_up_from_queued(mid)
                        f_tasks -= 1
                        if f_tasks == 0 or (up_limit and index >= up_limit - up):
                            break
                if queued_dl and (not dl_limit or dl < dl_limit) and f_tasks != 0:
                    for index, mid in enumerate(list(queued_dl.keys()), start=1):
                        await start_dl_from_queued(mid)
                        if (dl_limit and index >= dl_limit - dl) or index == f_tasks:
                            break
        return

    if up_limit := Config.QUEUE_UPLOAD:
        async with queue_dict_lock:
            up = len(non_queued_up)
            if queued_up and up < up_limit:
                f_tasks = up_limit - up
                for index, mid in enumerate(list(queued_up.keys()), start=1):
                    await start_up_from_queued(mid)
                    if index == f_tasks:
                        break
    else:
        async with queue_dict_lock:
            if queued_up:
                for mid in list(queued_up.keys()):
                    await start_up_from_queued(mid)

    if dl_limit := Config.QUEUE_DOWNLOAD:
        async with queue_dict_lock:
            dl = len(non_queued_dl)
            if queued_dl and dl < dl_limit:
                f_tasks = dl_limit - dl
                for index, mid in enumerate(list(queued_dl.keys()), start=1):
                    await start_dl_from_queued(mid)
                    if index == f_tasks:
                        break
    else:
        async with queue_dict_lock:
            if queued_dl:
                for mid in list(queued_dl.keys()):
                    await start_dl_from_queued(mid)

    # Media queue processing
    if media_limit := Config.QUEUE_MEDIA_PROCESSING:
        async with media_queue_lock:
            media_running = len(non_queued_media)
            if queued_media and media_running < media_limit:
                f_tasks = media_limit - media_running
                for index, mid in enumerate(list(queued_media.keys()), start=1):
                    await start_media_from_queued(mid)
                    if index == f_tasks:
                        break
    else:
        async with media_queue_lock:
            if queued_media:
                for mid in list(queued_media.keys()):
                    await start_media_from_queued(mid)


async def limit_checker(listener, yt_playlist=0):
    LOGGER.info("Checking Size Limit...")
    if await CustomFilters.sudo("", listener.message):
        LOGGER.info("SUDO User. Skipping Size Limit...")
        return

    size = listener.size
    if not size:
        return  # No size to check

    # --- Playlist Limit Check (special case) ---
    if bool(yt_playlist):
        playlist_limit = getattr(Config, "PLAYLIST_LIMIT", 0)
        if playlist_limit and yt_playlist >= playlist_limit:
            return f"YouTube Playlist limit is {playlist_limit}."

    # --- Size-based Limit Checks ---
    applicable_limits = []

    # Leech, Archive, Extract limits
    if listener.is_leech:
        if limit := getattr(Config, "LEECH_LIMIT", 0):
            applicable_limits.append((limit, "Leech"))
        # For leech tasks that also extract, apply both limits
        if listener.extract:
            if limit := getattr(Config, "EXTRACT_LIMIT", 0):
                applicable_limits.append((limit, "Extract"))
    else:
        # Archive and Extract limits only apply to non-leech tasks
        if listener.compress:
            if limit := getattr(Config, "ARCHIVE_LIMIT", 0):
                applicable_limits.append((limit, "Archive"))
        if listener.extract:
            if limit := getattr(Config, "EXTRACT_LIMIT", 0):
                applicable_limits.append((limit, "Extract"))

    # Download-specific limits
    dl_limit_map = {
        "TORRENT_LIMIT": "Torrent",
        "MEGA_LIMIT": "Mega",
        "GD_DL_LIMIT": "GDriveDL",
        "CLONE_LIMIT": "Clone",
        "JD_LIMIT": "JDownloader",
        "NZB_LIMIT": "SABnzbd",
        "RC_DL_LIMIT": "RCloneDL",
        "YTDLP_LIMIT": "YT-DLP",
    }

    dl_conditions = {
        "TORRENT_LIMIT": listener.is_torrent or listener.is_qbit,
        "MEGA_LIMIT": listener.is_mega,
        "GD_DL_LIMIT": listener.is_gdrive,
        "CLONE_LIMIT": listener.is_clone,
        "JD_LIMIT": listener.is_jd,
        "NZB_LIMIT": listener.is_nzb,
        "RC_DL_LIMIT": listener.is_rclone,
        "YTDLP_LIMIT": listener.is_ytdlp,
    }

    is_dl_type_matched = False
    for limit_attr, condition in dl_conditions.items():
        if condition:
            is_dl_type_matched = True
            if limit := getattr(Config, limit_attr, 0):
                applicable_limits.append((limit, dl_limit_map[limit_attr]))

    # Fallback to Direct limit if no other download type matched
    if not is_dl_type_matched:
        if limit := getattr(Config, "DIRECT_LIMIT", 0):
            applicable_limits.append((limit, "Direct"))

    # Now, find the most restrictive limit among all applicable ones
    if applicable_limits:
        min_limit_gb, limit_name = min(applicable_limits, key=lambda x: x[0])

        byte_limit = min_limit_gb * 1024**3
        if size >= byte_limit:
            LOGGER.info(
                f"{limit_name} Limit Breached for {listener.name} | Size: {get_readable_file_size(size)}"
            )
            return f"File size exceeds the allowed limit. ({limit_name} limit is {get_readable_file_size(byte_limit)}.)"

    # --- Storage Threshold Check ---
    if Config.STORAGE_LIMIT and not listener.is_clone:
        limit = Config.STORAGE_LIMIT * 1024**3
        if not await check_storage_threshold(
            size, limit, any([listener.compress, listener.extract])
        ):
            return f"Storage threshold limit is {get_readable_file_size(limit)}."

    return None  # No limit breached


async def user_interval_check(user_id):
    bot_cache.setdefault("time_interval", {})
    if (time_interval := bot_cache["time_interval"].get(user_id, False)) and (
        time() - time_interval
    ) < (UTI := Config.USER_TIME_INTERVAL):
        return UTI - (time() - time_interval)
    bot_cache["time_interval"][user_id] = time()
    return None


async def pre_task_check(message, is_video_merge_task: bool = False):
    """
    Performs pre-task checks for a user.
    Returns a modernized message if any checks fail.
    """
    LOGGER.info("Running Pre-Task Checks...")

    if await CustomFilters.sudo("", message):
        return None, None

    user_id = (message.from_user or message.sender_chat).id
    if Config.RSS_CHAT and user_id == int(Config.RSS_CHAT):
        return None, None

    error_reasons = []
    button = None

    # Force Subscription Check
    if message.chat.type != message.chat.type.BOT and (
        fsub_ids := Config.FORCE_SUB_IDS
    ):
        fsub_msg, button = await forcesub(message, fsub_ids, button)
        if fsub_msg:
            error_reasons.append(fsub_msg)

    # Bot PM Check
    user_dict = user_data.get(user_id, {})
    if Config.BOT_PM or user_dict.get("BOT_PM"):
        botpm_msg, button = await check_botpm(message, button)
        if botpm_msg:
            error_reasons.append(botpm_msg)

    # User Time Interval Check
    if (uti := Config.USER_TIME_INTERVAL) and (
        ut := await user_interval_check(user_id)
    ):
        error_reasons.append(
            f"⏱️ <b>Cooldown Active</b>: Please wait <code>{get_readable_time(ut)}</code> before your next request. (Interval: <code>{get_readable_time(uti)}</code>)"
        )

    # Bot Max Tasks Check
    if (bmax_tasks := Config.BOT_MAX_TASKS) and len(
        await get_specific_tasks("All", False)
    ) >= int(bmax_tasks):
        error_reasons.append(
            f"🤖 <b>Bot is Busy</b>: The bot is currently handling the maximum number of tasks (<code>{bmax_tasks}</code>). Please try again in a moment."
        )

    # User Max Tasks Check (Enhanced Logic)
    if maxtask := Config.USER_MAX_TASKS:
        all_user_tasks = await get_specific_tasks("All", user_id)
        running_normal_tasks = sum(
            1
            for task in all_user_tasks
            if not getattr(task.listener, "is_user_limit_exempt", False)
        )

        if not is_video_merge_task and running_normal_tasks >= int(maxtask):
            error_reasons.append(
                f"👤 <b>Task Limit Reached</b>: You're already running the maximum of <code>{maxtask}</code> task(s). Please wait for one to complete."
            )

    # Token Verification Check (New System)
    if Config.VERIFY_BOT:  # Only run if a VERIFY_BOT is configured
        verification_msg, button = await perform_verification_check(user_id, button)
        if verification_msg:
            error_reasons.append(verification_msg)
    # End Token Verification Check

    # If any errors were found, format and return the modern message
    if error_reasons:
        username = message.from_user.mention
        final_msg = f"Hey {username}, your request has been denied. 🚦\n\n"
        final_msg += "<b>Reason(s):</b>\n"
        for reason in error_reasons:
            final_msg += f"• {reason}\n"

        if button is not None:
            button = button.build_menu(2)
        return final_msg, button

    return None, None


async def check_min_speed(total_speed, count):
    if MIN_SPEED := Config.MIN_SPEED:
        # Add a grace period: only check speed if we have at least 3 speed samples
        if count < 3:
            return None  # Not enough data yet, don't cancel

        avg_speed_threshold = MIN_SPEED * 1024  # Convert KB/s to B/s

        # Ensure count is not zero to avoid ZeroDivisionError, though count < 3 check should prevent it.
        if count == 0:
            task_avg_speed = (
                0  # Or handle as an anomaly, though count < 3 should prevent this.
            )
        else:
            task_avg_speed = total_speed / count

        if task_avg_speed < avg_speed_threshold:
            return f"Minimum download speed required is greater than {get_readable_file_size(avg_speed_threshold)}/s. Your task's average download speed is {get_readable_file_size(task_avg_speed)}/s."
