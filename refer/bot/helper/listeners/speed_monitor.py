from asyncio import sleep
from time import time

from ... import LOGGER, task_dict, intervals, jd_downloads, jd_listener_lock
from ...core.config_manager import Config
from ..ext_utils.bot_utils import new_task
from ..ext_utils.status_utils import get_readable_file_size, get_task_by_gid
from ...core.torrent_manager import TorrentManager
from ...core.jdownloader_booter import jdownloader


# Speed monitoring tracking dict
speed_monitoring = {}  # {gid: {"start_time": time, "slow_speed_start": time or None, "task_name": str}}


def init_speed_monitoring(gid, task_name="Unknown"):
    """Initialize speed monitoring for a task"""
    speed_monitoring[gid] = {
        "start_time": time(),
        "slow_speed_start": None,
        "task_name": task_name,
    }


def cleanup_speed_monitoring(gid):
    """Clean up speed monitoring data for a task"""
    if gid in speed_monitoring:
        del speed_monitoring[gid]


async def check_speed_limit(gid, current_speed_bytes):
    """
    Check if download speed is below limit and return True if task should be cancelled.

    Args:
        gid: Task identifier
        current_speed_bytes: Current download speed in bytes/s

    Returns:
        bool: True if task should be cancelled due to slow speed
    """
    if Config.DL_SPEED_LIMIT <= 0:
        return False  # Speed limit disabled

    if gid not in speed_monitoring:
        return False  # Not being monitored

    current_time = time()
    monitoring_data = speed_monitoring[gid]
    speed_limit_bytes = Config.get_speed_limit_bytes()  # Convert MB/s to bytes/s

    # Start monitoring speed after initial buffering period (15 seconds)
    if current_time - monitoring_data["start_time"] <= 15:
        return False

    task_name = monitoring_data["task_name"]

    if current_speed_bytes < speed_limit_bytes:
        if monitoring_data["slow_speed_start"] is None:
            monitoring_data["slow_speed_start"] = current_time
            LOGGER.warning(
                f"Speed limit warning: {task_name} - Speed: {current_speed_bytes} bytes/s is below limit: {Config.DL_SPEED_LIMIT} MB/s"
            )
        elif (
            current_time - monitoring_data["slow_speed_start"]
            >= Config.SPEED_LIMIT_TIMEOUT
        ):
            # Task should be cancelled due to slow speed
            speed_str = get_readable_file_size(current_speed_bytes)
            LOGGER.info(
                f"Cancelling download due to slow speed: {task_name} - Current: {speed_str}/s | Limit: {Config.DL_SPEED_LIMIT} MB/s"
            )
            cleanup_speed_monitoring(gid)
            return True
    else:
        # Reset slow speed timer if speed is above limit
        monitoring_data["slow_speed_start"] = None

    return False


@new_task
async def _speed_monitor():
    """Monitor download speeds for all active tasks"""
    while True:
        if Config.DL_SPEED_LIMIT <= 0:
            await sleep(10)
            continue

        try:
            # Check Aria2 downloads
            try:
                active_downloads = await TorrentManager.aria2.tellActive()
                for download in active_downloads:
                    gid = download.get("gid")
                    if gid and gid in speed_monitoring:
                        speed = int(download.get("downloadSpeed", "0"))
                        if await check_speed_limit(gid, speed):
                            # Cancel the task
                            if task := await get_task_by_gid(gid):
                                speed_str = get_readable_file_size(speed)
                                error_msg = f"Download cancelled due to slow speed!\nCurrent: {speed_str}/s | Limit: {Config.DL_SPEED_LIMIT} MB/s"
                                await task.listener.on_download_error(error_msg)
                            await TorrentManager.aria2.forceRemove(gid)
            except Exception as e:
                LOGGER.debug(f"Aria2 speed monitoring error: {e}")

            # Check JDownloader downloads
            try:
                if jdownloader.is_connected and jd_downloads:
                    async with jd_listener_lock:
                        for gid, d_dict in list(jd_downloads.items()):
                            if gid in speed_monitoring and d_dict["status"] == "down":
                                try:
                                    # Get current download speed from JDownloader
                                    speed = await jdownloader.device.downloadcontroller.get_speed_in_bytes()
                                    if await check_speed_limit(gid, speed):
                                        # Cancel the task
                                        if task := await get_task_by_gid(gid):
                                            speed_str = get_readable_file_size(speed)
                                            error_msg = f"Download cancelled due to slow speed!\nCurrent: {speed_str}/s | Limit: {Config.DL_SPEED_LIMIT} MB/s"
                                            await task.listener.on_download_error(
                                                error_msg
                                            )
                                        # Remove the download from JDownloader
                                        await jdownloader.device.downloads.remove_links(
                                            package_ids=d_dict["ids"]
                                        )
                                        del jd_downloads[gid]
                                except Exception as e:
                                    LOGGER.debug(
                                        f"JDownloader speed check error for {gid}: {e}"
                                    )
            except Exception as e:
                LOGGER.debug(f"JDownloader speed monitoring error: {e}")

            # Note: qBittorrent speed monitoring is handled in qbit_listener.py

        except Exception as e:
            LOGGER.error(f"Speed monitor error: {e}")

        await sleep(5)  # Check every 5 seconds


async def start_speed_monitor():
    """Start the speed monitoring system"""
    if not intervals.get("speed_monitor"):
        LOGGER.info("Starting speed monitoring system")
        intervals["speed_monitor"] = await _speed_monitor()
