from psutil import cpu_percent, virtual_memory, disk_usage
from time import time
from asyncio import gather, iscoroutinefunction

from pyrogram.errors import QueryIdInvalid

from .. import (
    task_dict_lock,
    status_dict,
    task_dict,
    bot_start_time,
    intervals,
    sabnzbd_client,
    DOWNLOAD_DIR,
)
from ..core.torrent_manager import TorrentManager
from ..core.jdownloader_booter import jdownloader
from ..helper.ext_utils.bot_utils import new_task
from ..helper.ext_utils.status_utils import (
    EngineStatus,
    MirrorStatus,
    get_readable_file_size,
    get_readable_time,
    speed_string_to_bytes,
)
from ..helper.telegram_helper.bot_commands import BotCommands
from ..helper.telegram_helper.message_utils import (
    send_message,
    delete_message,
    auto_delete_message,
    send_status_message,
    update_status_message,
    edit_message,
)
from ..helper.telegram_helper.button_build import ButtonMaker


@new_task
async def task_status(_, message):
    """
    Handles the /status command.
    Shows a summary of active tasks or a message if no tasks are running.
    """
    async with task_dict_lock:
        count = len(task_dict)
    if count == 0:
        currentTime = get_readable_time(time() - bot_start_time)
        free = get_readable_file_size(disk_usage(DOWNLOAD_DIR).free)
        msg = f"""〶 <b><i>No Active Bot Tasks!</i></b>
│
╰ <b>NOTE</b> → <i>Each user can get status for his tasks by adding "me" or user_id like "1234xxx" after cmd: /{BotCommands.StatusCommand[0]} me or /{BotCommands.StatusCommand[1]} me</i>

⌬ <b><u>Bot Stats</u></b>
┟ <b>CPU</b> → {cpu_percent()}% | <b>F</b> → {free} [{round(100 - disk_usage(DOWNLOAD_DIR).percent, 1)}%]
╰ <b>RAM</b> → {virtual_memory().percent}% | <b>UP</b> → {currentTime}
"""
        reply_message = await send_message(message, msg)
        await auto_delete_message(message, reply_message)
    else:
        text = message.text.split()
        if len(text) > 1:
            user_id = message.from_user.id if text[1] == "me" else int(text[1])
        else:
            user_id = 0
            sid = message.chat.id
            if obj := intervals["status"].get(sid):
                obj.cancel()
                del intervals["status"][sid]
        await send_status_message(message, user_id)
        await delete_message(message)


async def get_download_status(download):
    """
    Fetches the status and speed for a single download task.
    """
    eng = download.engine
    speed = (
        download.speed()
        if eng.startswith(("Pyro", "yt-dlp", "RClone", "Google-API"))
        else 0
    )
    return (
        (
            await download.status()
            if iscoroutinefunction(download.status)
            else download.status()
        ),
        speed,
        eng,
    )


user_refresh_info = {}


async def get_overview_message(key):
    """
    Generates the 'Overall Stats' message.
    FIXED: Prevents deadlocking by not holding the task_dict_lock during await calls.
    """
    tasks = {
        "Download": 0,
        "Upload": 0,
        "Seed": 0,
        "Archive": 0,
        "Extract": 0,
        "Split": 0,
        "QueueDl": 0,
        "QueueUp": 0,
        "Clone": 0,
        "CheckUp": 0,
        "Pause": 0,
        "SamVid": 0,
        "ConvertMedia": 0,
        "FFmpeg": 0,
    }
    dl_speed = 0
    up_speed = 0
    seed_speed = 0

    #
    # --- FIX START ---
    #
    # Reason: Holding a lock during `await gather` can cause a deadlock if any of the
    # `download.status()` calls are slow. Other parts of the bot that need
    # this lock will freeze.
    #
    # The fix is to get a list of tasks to check inside the lock, then release
    # the lock before awaiting the results.
    async with task_dict_lock:
        tasks_to_check = list(task_dict.values())

    status_results = await gather(
        *(get_download_status(download) for download in tasks_to_check)
    )
    #
    # --- FIX END ---
    #

    eng_status = EngineStatus()
    if any(
        eng in (eng_status.STATUS_ARIA2, eng_status.STATUS_QBIT)
        for _, __, eng in status_results
    ):
        dl_speed, seed_speed = await TorrentManager.overall_speed()

    if any(eng == eng_status.STATUS_SABNZBD for _, __, eng in status_results):
        if sabnzbd_client.LOGGED_IN:
            dl_speed += (
                int(
                    float(
                        (await sabnzbd_client.get_downloads())["queue"].get(
                            "kbpersec", "0"
                        )
                    )
                )
                * 1024
            )

    if any(eng == eng_status.STATUS_JD for _, __, eng in status_results):
        if jdownloader.is_connected:
            dl_speed += await jdownloader.device.downloadcontroller.get_speed_in_bytes()

    for status, speed, _ in status_results:
        match status:
            case MirrorStatus.STATUS_DOWNLOAD:
                tasks["Download"] += 1
                if speed:
                    dl_speed += speed_string_to_bytes(speed)
            case MirrorStatus.STATUS_UPLOAD:
                tasks["Upload"] += 1
                up_speed += speed_string_to_bytes(speed)
            case MirrorStatus.STATUS_SEED:
                tasks["Seed"] += 1
            case MirrorStatus.STATUS_ARCHIVE:
                tasks["Archive"] += 1
            case MirrorStatus.STATUS_EXTRACT:
                tasks["Extract"] += 1
            case MirrorStatus.STATUS_SPLIT:
                tasks["Split"] += 1
            case MirrorStatus.STATUS_QUEUEDL:
                tasks["QueueDl"] += 1
            case MirrorStatus.STATUS_QUEUEUP:
                tasks["QueueUp"] += 1
            case MirrorStatus.STATUS_CLONE:
                tasks["Clone"] += 1
            case MirrorStatus.STATUS_CHECK:
                tasks["CheckUp"] += 1
            case MirrorStatus.STATUS_PAUSED:
                tasks["Pause"] += 1
            case MirrorStatus.STATUS_SAMVID:
                tasks["SamVid"] += 1
            case MirrorStatus.STATUS_CONVERT:
                tasks["ConvertMedia"] += 1
            case MirrorStatus.STATUS_FFMPEG:
                tasks["FFmpeg"] += 1
            case _:
                tasks["Download"] += 1

    msg = f"""㊂ <b>Tasks Overview</b> :
        
┎ <b>Download:</b> {tasks["Download"]} | <b>Upload:</b> {tasks["Upload"]}
┠ <b>Seed:</b> {tasks["Seed"]} | <b>Archive:</b> {tasks["Archive"]}
┠ <b>Extract:</b> {tasks["Extract"]} | <b>Split:</b> {tasks["Split"]}
┠ <b>QueueDL:</b> {tasks["QueueDl"]} | <b>QueueUP:</b> {tasks["QueueUp"]}
┠ <b>Clone:</b> {tasks["Clone"]} | <b>CheckUp:</b> {tasks["CheckUp"]}
┠ <b>Paused:</b> {tasks["Pause"]} | <b>SamVideo:</b> {tasks["SamVid"]}
┞ <b>Convert:</b> {tasks["ConvertMedia"]} | <b>FFmpeg:</b> {tasks["FFmpeg"]}
│
┟ <b>Total Download Speed:</b> {get_readable_file_size(dl_speed)}/s
┠ <b>Total Upload Speed:</b> {get_readable_file_size(up_speed)}/s
╰ <b>Total Seeding Speed:</b> {get_readable_file_size(seed_speed)}/s
"""
    button = ButtonMaker()
    button.data_button("Back", f"status {key} menu")
    return msg, button.build_menu()


@new_task
async def status_pages(_, query):
    """
    Handles callbacks from the status message buttons (e.g., refresh, next page).
    """
    data = query.data.split()
    key = int(data[1])
    user_id = query.from_user.id
    message = query.message

    if data[2] == "ref":
        async with task_dict_lock:
            count = len(task_dict)
        if not count:
            try:
                await query.answer("Old status! Closing in 2s...", show_alert=True)
            except QueryIdInvalid:
                pass
            # FIX: Using 'st' as the keyword argument for the delay.
            await auto_delete_message(query.message, st=2)
            return

        if user_id not in user_refresh_info:
            user_refresh_info[user_id] = {"count": 0, "timestamp": 0}

        info = user_refresh_info[user_id]
        current_time = time()

        if info["count"] < 2:
            info["count"] += 1
            info["timestamp"] = current_time
            await update_status_message(key, force=True)
            try:
                await query.answer(text="Refreshing status...", show_alert=False)
            except QueryIdInvalid:
                pass
        else:
            elapsed_time = current_time - info["timestamp"]
            cooldown_period = 3  # seconds
            if elapsed_time < cooldown_period:
                try:
                    await query.answer(
                        text=f"Please wait {cooldown_period - elapsed_time:.1f}s to refresh.",
                        show_alert=True,
                    )
                except QueryIdInvalid:
                    pass
            else:
                info["count"] = 1
                info["timestamp"] = current_time
                await update_status_message(key, force=True)
                try:
                    await query.answer(text="Refreshing status...", show_alert=False)
                except QueryIdInvalid:
                    pass
    elif data[2] in ["nex", "pre"]:
        async with task_dict_lock:
            if key in status_dict:
                if data[2] == "nex":
                    status_dict[key]["page_no"] += status_dict[key]["page_step"]
                else:
                    status_dict[key]["page_no"] -= status_dict[key]["page_step"]
    elif data[2] == "ps":
        async with task_dict_lock:
            if key in status_dict:
                status_dict[key]["page_step"] = int(data[3])
    elif data[2] == "st":
        async with task_dict_lock:
            if key in status_dict:
                status_dict[key]["status"] = data[3]
        await update_status_message(key, force=True)
    elif data[2] == "menu":
        buttons = ButtonMaker()
        buttons.data_button("Overall Stats", f"status {key} overview_stats")
        buttons.data_button("Back to Tasks", f"status {key} ref")
        await edit_message(message, "📜 <b>Status Menu</b> 📜", buttons.build_menu(1))
    elif data[2] == "overview_stats":
        msg, buttons = await get_overview_message(key)
        await edit_message(message, msg, buttons)

    try:
        await query.answer()
    except QueryIdInvalid:
        pass
