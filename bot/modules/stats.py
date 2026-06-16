from asyncio import gather
from re import search as research
from time import time

from aiofiles.os import path as aiopath
from psutil import (
    boot_time,
    cpu_count,
    cpu_percent,
    disk_usage,
    net_io_counters,
    swap_memory,
    virtual_memory,
)

from .. import bot_cache, bot_start_time
from ..core.config_manager import Config, BinConfig
from ..helper.ext_utils.bot_utils import cmd_exec, new_task
from ..helper.ext_utils.status_utils import (
    get_progress_bar_string,
    get_readable_file_size,
    get_readable_time,
)
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.message_utils import (
    delete_message,
    edit_message,
    send_message,
)
from ..version import get_version

commands = {
    "aria2": ([BinConfig.ARIA2_NAME, "--version"], r"aria2 version ([\d.]+)"),
    "qBittorrent": ([BinConfig.QBIT_NAME, "--version"], r"qBittorrent v([\d.]+)"),
    "SABnzbd+": (
        [BinConfig.SABNZBD_NAME, "--version"],
        rf"{BinConfig.SABNZBD_NAME}-([\d.]+)",
    ),
    "python": (["python3", "--version"], r"Python ([\d.]+)"),
    "rclone": ([BinConfig.RCLONE_NAME, "--version"], r"rclone v([\d.]+)"),
    "yt-dlp": (["yt-dlp", "--version"], r"([\d.]+)"),
    "ffmpeg": (
        [BinConfig.FFMPEG_NAME, "-version"],
        r"ffmpeg version ([\d.]+(-\w+)?).*",
    ),
    "7z": (["7z", "i"], r"7-Zip ([\d.]+)"),
    "aiohttp": (["uv", "pip", "show", "aiohttp"], r"Version: ([\d.]+)"),
    "pyrogram": (["uv", "pip", "show", "pyrogram"], r"Version: ([\d.]+)"),
    "gapi": (["uv", "pip", "show", "google-api-python-client"], r"Version: ([\d.]+)"),
    "mega": (["pip", "show", "megasdk"], r"Version: ([\d.]+)"),
}


async def get_stats(event, key="home"):
    user_id = event.from_user.id
    btns = ButtonMaker()

    if key == "home":
        btns.data_button("Server info", f"stats {user_id} server")
        btns.data_button("User limits", f"stats {user_id} tlimits")
        btns.data_button("Repo Stats", f"stats {user_id} strepo")
        btns.data_button("✘", f"stats {user_id} close", "footer")
        msg = f"Hey, <b>{event.from_user.first_name}</b>\nCheck below buttons for details."
        return msg, btns.build_menu(2)

    if key == "server":
        bot_uptime = get_readable_time(time() - bot_start_time)
        os_uptime = get_readable_time(time() - boot_time())
        net_io = net_io_counters()
        sent = get_readable_file_size(net_io.bytes_sent)
        recv = get_readable_file_size(net_io.bytes_recv)
        total_bw = get_readable_file_size(net_io.bytes_sent + net_io.bytes_recv)
        cpu_usage = cpu_percent(interval=0.5)
        p_cores = cpu_count(logical=False)
        t_cores = cpu_count(logical=True)
        disk = disk_usage("/")
        memory = virtual_memory()
        swap = swap_memory()

        msg = f"""<b><u>Server Info:</u></b>

Bot Uptime: {bot_uptime}
OS Uptime: {os_uptime}

Sent: {sent} | Recv: {recv}
Total Bandwidth: {total_bw}

CPU ~ Physical Cores: {p_cores} | Total: {t_cores}
{get_progress_bar_string(cpu_usage)} » {cpu_usage}%

<b>DISK:</b> {get_readable_file_size(disk.total)}
Free: {get_readable_file_size(disk.free)} | Used: {get_readable_file_size(disk.used)}
{get_progress_bar_string(disk.percent)} » {disk.percent}%

<b>RAM:</b> {get_readable_file_size(memory.total)}
Free: {get_readable_file_size(memory.available)} | Used: {get_readable_file_size(memory.used)}
{get_progress_bar_string(memory.percent)} » {memory.percent}%

<b>SWAP:</b> {get_readable_file_size(swap.total)}
Free: {get_readable_file_size(swap.free)} | Used: {get_readable_file_size(swap.used)}
{get_progress_bar_string(swap.percent)} » {swap.percent}%
"""
        btns.data_button("User limits", f"stats {user_id} tlimits")
        btns.data_button("Repo Stats", f"stats {user_id} strepo")

    elif key == "tlimits":
        msg = f"""<b><u>Bot Limitations:</u></b>
Torrent: {Config.TORRENT_LIMIT or "N/A"}GB/link
Direct: {Config.DIRECT_LIMIT or "N/A"}GB/link
Leech: {Config.LEECH_LIMIT or "N/A"}GB/link
Clone: {Config.CLONE_LIMIT or "N/A"}GB/link
Gdrive: {Config.GD_DL_LIMIT or "N/A"}GB/link
Rclone: {Config.RC_DL_LIMIT or "N/A"}GB/link
Mega: {Config.MEGA_LIMIT or "N/A"}GB/link
YT-DL: {Config.YTDLP_LIMIT or "N/A"}GB/link
YT Playlist: {Config.PLAYLIST_LIMIT or "N/A"}/files
Storage Threshold: {Config.STORAGE_LIMIT or "N/A"}GB/free

Normal User Tasks: {Config.USER_MAX_TASKS or "Not Set"} Tasks/Time
Total Tasks: {Config.BOT_MAX_TASKS or "Not Set"}
Token Timeout: {get_readable_time(Config.VERIFY_DURATION) if Config.VERIFY_DURATION else "Not Set"}
"""
        btns.data_button("Server info", f"stats {user_id} server")
        btns.data_button("Repo Stats", f"stats {user_id} strepo")

    elif key == "strepo":
        last_commit, changelog = "No Data", "N/A"
        if await aiopath.exists(".git"):
            last_commit = (
                await cmd_exec(
                    "git log -1 --pretty='%cd ( %cr )' --date=format-local:'%d/%m/%Y'",
                    True,
                )
            )[0]
            changelog = (
                await cmd_exec(
                    "git log -1 --pretty=format:'<code>%s</code> <b>By</b> %an'", True
                )
            )[0]

        official_v = "N/A"
        try:
            official_v = (
                await cmd_exec(
                    f"curl -o latestversion.py https://raw.githubusercontent.com/SilentDemonSD/Mirror-Hunter/{Config.UPSTREAM_BRANCH}/bot/version.py -s && python3 latestversion.py && rm latestversion.py",
                    True,
                )
            )[0]
        except Exception:
            pass

        msg = f"""<b><u>Repo Statistics:</u></b>
<b>Bot Updated:</b> {last_commit}
<b>Current Version:</b> {get_version()}
<b>Latest Version:</b> {official_v}
<b>Last ChangeLog:</b> {changelog}
"""
        btns.data_button("Server info", f"stats {user_id} server")
        btns.data_button("User limits", f"stats {user_id} tlimits")

    btns.data_button("❮❮", f"stats {user_id} home", "footer")
    btns.data_button("✘", f"stats {user_id} close", "footer")
    return msg, btns.build_menu(2)


@new_task
async def bot_stats(_, message):
    msg, btns = await get_stats(message)
    await send_message(message, msg, btns)


@new_task
async def stats_pages(_, query):
    data = query.data.split()
    message = query.message
    user_id = query.from_user.id
    if user_id != int(data[1]):
        await query.answer("Not Yours!", show_alert=True)
    elif data[2] == "close":
        await query.answer()
        await delete_message(message)
        await delete_message(message.reply_to_message)
    else:
        await query.answer()
        msg, btns = await get_stats(query, data[2])
        await edit_message(message, msg, btns)


async def get_version_async(command, regex):
    try:
        out, err, code = await cmd_exec(command)
        if code != 0:
            return f"Error: {err}"
        match = research(regex, out)
        return match.group(1) if match else "-"
    except Exception as e:
        return f"Exception: {str(e)}"


async def get_packages_version():
    tasks = [get_version_async(command, regex) for command, regex in commands.values()]
    versions = await gather(*tasks)
    bot_cache["eng_versions"] = {}
    for tool, ver in zip(commands.keys(), versions):
        bot_cache["eng_versions"][tool] = ver
    if await aiopath.exists(".git"):
        last_commit = await cmd_exec(
            "git log -1 --date=short --pretty=format:'%cd <b>From</b> %cr'", True
        )
        last_commit = last_commit[0]
    else:
        last_commit = "No UPSTREAM_REPO"
    bot_cache["commit"] = last_commit
