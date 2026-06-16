"""
Stalled Task Monitor
Monitors tasks with 0 bytes/second speed and auto-cancels them after a specified timeout.
Supports Aria2, qBittorrent, and yt-dlp tasks.
"""

import asyncio
from time import time
from typing import Dict, Set, Optional
from asyncio import iscoroutinefunction

from ... import LOGGER, task_dict, task_dict_lock, intervals
from ...core.config_manager import Config
from ...core.torrent_manager import TorrentManager
from ..ext_utils.status_utils import get_task_by_gid, MirrorStatus


class StalledTaskMonitor:
    def __init__(self):
        self.aria2_stalled_tasks: Dict[str, float] = {}  # gid -> start_time
        self.qbit_stalled_tasks: Dict[str, float] = {}  # hash -> start_time
        self.ytdlp_stalled_tasks: Dict[str, float] = {}  # mid -> start_time
        self.paused_tasks: Dict[str, float] = {}  # mid -> start_time for paused tasks
        self.monitoring = False
        self.monitor_task: Optional[asyncio.Task] = None

    async def start_monitoring(self):
        """Start the stalled task monitoring loop"""
        if self.monitoring or not Config.AUTO_CANCEL_STALLED_TASKS:
            return

        self.monitoring = True
        self.monitor_task = asyncio.create_task(self._monitor_loop())
        LOGGER.info("Stalled task monitor started")

    async def stop_monitoring(self):
        """Stop the stalled task monitoring loop"""
        if not self.monitoring:
            return

        self.monitoring = False
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
        self.monitor_task = None
        LOGGER.info("Stalled task monitor stopped")

    async def _monitor_loop(self):
        """Main monitoring loop"""
        while self.monitoring:
            try:
                await self._check_aria2_tasks()
                await self._check_qbit_tasks()
                await self._check_ytdlp_tasks()
                await self._check_paused_tasks()
                await asyncio.sleep(30)  # Check every 30 seconds
            except asyncio.CancelledError:
                break
            except Exception as e:
                LOGGER.error(f"Error in stalled task monitor: {e}")
                await asyncio.sleep(30)

    async def _check_aria2_tasks(self):
        """Check Aria2 tasks for stalled downloads"""
        if not TorrentManager.aria2:
            return

        try:
            # Get active downloads
            active_downloads = await TorrentManager.aria2.tellActive()
            waiting_downloads = await TorrentManager.aria2.tellWaiting(0, 1000)
            all_downloads = active_downloads + waiting_downloads

            current_time = time()
            timeout_seconds = Config.STALLED_TASK_TIMEOUT * 60

            for download in all_downloads:
                gid = download.get("gid", "")
                status = download.get("status", "")

                # Only monitor active downloads
                if status != "active":
                    if gid in self.aria2_stalled_tasks:
                        del self.aria2_stalled_tasks[gid]
                    continue

                # Check if download speed is 0
                download_speed = int(download.get("downloadSpeed", "0"))
                upload_speed = int(download.get("uploadSpeed", "0"))

                if download_speed == 0 and upload_speed == 0:
                    # Task is stalled (0 bytes/s)
                    if gid not in self.aria2_stalled_tasks:
                        self.aria2_stalled_tasks[gid] = current_time
                        LOGGER.info(f"Aria2 task {gid} marked as stalled (0 bytes/s)")

                    # Check if stalled for too long
                    if current_time - self.aria2_stalled_tasks[gid] >= timeout_seconds:
                        await self._cancel_aria2_task(gid, download)
                else:
                    # Task has speed, remove from stalled list
                    if gid in self.aria2_stalled_tasks:
                        del self.aria2_stalled_tasks[gid]

        except Exception as e:
            LOGGER.error(f"Error checking Aria2 stalled tasks: {e}")

    async def _check_qbit_tasks(self):
        """Check qBittorrent tasks for stalled downloads"""
        if not TorrentManager.qbittorrent:
            return

        try:
            # Get all torrents
            torrents = await TorrentManager.qbittorrent.torrents.info()

            current_time = time()
            timeout_seconds = Config.STALLED_TASK_TIMEOUT * 60

            for torrent in torrents:
                torrent_hash = torrent.hash
                state = torrent.state

                # Only monitor downloading torrents, exclude stalledDL as it's a normal qBittorrent state
                # stalledDL means the torrent is waiting for seeders, which is expected behavior
                if state not in ["downloading", "metaDL"]:
                    if torrent_hash in self.qbit_stalled_tasks:
                        del self.qbit_stalled_tasks[torrent_hash]
                    continue

                # Check if download speed is 0
                download_speed = torrent.dlspeed
                upload_speed = torrent.upspeed

                if download_speed == 0 and upload_speed == 0:
                    # Task is stalled (0 bytes/s)
                    if torrent_hash not in self.qbit_stalled_tasks:
                        self.qbit_stalled_tasks[torrent_hash] = current_time
                        LOGGER.info(
                            f"qBittorrent task {torrent.name} ({torrent_hash[:8]}) marked as stalled (0 bytes/s)"
                        )

                    # Check if stalled for too long
                    if (
                        current_time - self.qbit_stalled_tasks[torrent_hash]
                        >= timeout_seconds
                    ):
                        await self._cancel_qbit_task(torrent_hash, torrent)
                else:
                    # Task has speed, remove from stalled list
                    if torrent_hash in self.qbit_stalled_tasks:
                        del self.qbit_stalled_tasks[torrent_hash]

        except Exception as e:
            LOGGER.error(f"Error checking qBittorrent stalled tasks: {e}")

    async def _check_ytdlp_tasks(self):
        """Check yt-dlp tasks for stalled downloads"""
        try:
            current_time = time()
            timeout_seconds = Config.STALLED_TASK_TIMEOUT * 60

            # Check all tasks in task_dict for yt-dlp tasks
            async with task_dict_lock:
                for mid, task in task_dict.items():
                    # Check if it's a yt-dlp task
                    if hasattr(task, "engine") and "yt-dlp" in str(task.engine):
                        # Check if task has download speed information
                        if hasattr(task, "task") and hasattr(
                            task.task, "download_speed"
                        ):
                            download_speed = task.task.download_speed

                            # Check if download speed is 0 or very low (stalled)
                            if (
                                download_speed == 0 or download_speed < 1024
                            ):  # Less than 1 KB/s
                                # Task is stalled (0 or very low bytes/s)
                                if mid not in self.ytdlp_stalled_tasks:
                                    self.ytdlp_stalled_tasks[mid] = current_time
                                    LOGGER.info(
                                        f"yt-dlp task {task.name()} (MID: {mid}) marked as stalled (0 bytes/s)"
                                    )

                                # Check if stalled for too long
                                if (
                                    current_time - self.ytdlp_stalled_tasks[mid]
                                    >= timeout_seconds
                                ):
                                    await self._cancel_ytdlp_task(mid, task)
                            else:
                                # Task has speed, remove from stalled list
                                if mid in self.ytdlp_stalled_tasks:
                                    del self.ytdlp_stalled_tasks[mid]

        except Exception as e:
            LOGGER.error(f"Error checking yt-dlp stalled tasks: {e}")

    async def _check_paused_tasks(self):
        """Check paused tasks and cancel them if they've been paused too long"""
        try:
            current_time = time()
            timeout_seconds = Config.STALLED_TASK_TIMEOUT * 60

            # Check all tasks in task_dict for paused tasks
            async with task_dict_lock:
                for mid, task in task_dict.items():
                    # Check if it's a paused task
                    if hasattr(task, "status"):
                        # Get task status - handle both async and sync status methods
                        if iscoroutinefunction(task.status):
                            task_status = await task.status()
                        else:
                            task_status = task.status()

                        if task_status == MirrorStatus.STATUS_PAUSED:
                            # Task is paused
                            if mid not in self.paused_tasks:
                                self.paused_tasks[mid] = current_time
                                LOGGER.info(
                                    f"Task {task.name()} (MID: {mid}) marked as paused"
                                )

                            # Check if paused for too long
                            if current_time - self.paused_tasks[mid] >= timeout_seconds:
                                await self._cancel_paused_task(mid, task)
                        else:
                            # Task is not paused, remove from paused list
                            if mid in self.paused_tasks:
                                del self.paused_tasks[mid]

        except Exception as e:
            LOGGER.error(f"Error checking paused tasks: {e}")

    async def _cancel_aria2_task(self, gid: str, download: dict):
        """Cancel a stalled Aria2 task"""
        try:
            task = await get_task_by_gid(gid)
            if task:
                LOGGER.warning(
                    f"Auto-cancelling stalled Aria2 task: {aria2_name(download)} (GID: {gid}) - 0 bytes/s for {Config.STALLED_TASK_TIMEOUT} minutes"
                )
                await task.listener.on_download_error(
                    f"Task auto-cancelled: 0 bytes/s for {Config.STALLED_TASK_TIMEOUT} minutes"
                )
            else:
                # Task not found in bot, just remove from Aria2
                LOGGER.warning(
                    f"Auto-cancelling stalled Aria2 task (GID: {gid}) - 0 bytes/s for {Config.STALLED_TASK_TIMEOUT} minutes"
                )
                await TorrentManager.aria2_remove(download)

            # Remove from stalled tasks list
            if gid in self.aria2_stalled_tasks:
                del self.aria2_stalled_tasks[gid]

        except Exception as e:
            LOGGER.error(f"Error cancelling stalled Aria2 task {gid}: {e}")

    async def _cancel_qbit_task(self, torrent_hash: str, torrent):
        """Cancel a stalled qBittorrent task"""
        try:
            # Find task by hash (first 12 characters)
            task = await get_task_by_gid(torrent_hash[:12])
            if task:
                LOGGER.warning(
                    f"Auto-cancelling stalled qBittorrent task: {torrent.name} ({torrent_hash[:8]}) - 0 bytes/s for {Config.STALLED_TASK_TIMEOUT} minutes"
                )
                await task.listener.on_download_error(
                    f"Task auto-cancelled: 0 bytes/s for {Config.STALLED_TASK_TIMEOUT} minutes"
                )
            else:
                # Task not found in bot, just remove from qBittorrent
                LOGGER.warning(
                    f"Auto-cancelling stalled qBittorrent task: {torrent.name} ({torrent_hash[:8]}) - 0 bytes/s for {Config.STALLED_TASK_TIMEOUT} minutes"
                )
                await TorrentManager.qbittorrent.torrents.delete([torrent_hash], True)

            # Remove from stalled tasks list
            if torrent_hash in self.qbit_stalled_tasks:
                del self.qbit_stalled_tasks[torrent_hash]

        except Exception as e:
            LOGGER.error(
                f"Error cancelling stalled qBittorrent task {torrent_hash}: {e}"
            )

    async def _cancel_ytdlp_task(self, mid: str, task):
        """Cancel a stalled yt-dlp task"""
        try:
            LOGGER.warning(
                f"Auto-cancelling stalled yt-dlp task: {task.name()} (MID: {mid}) - 0 bytes/s for {Config.STALLED_TASK_TIMEOUT} minutes"
            )

            # Cancel the task using the listener
            if hasattr(task, "listener") and hasattr(
                task.listener, "on_download_error"
            ):
                await task.listener.on_download_error(
                    f"Task auto-cancelled: 0 bytes/s for {Config.STALLED_TASK_TIMEOUT} minutes"
                )
            else:
                # Fallback: try to cancel the task object directly
                if hasattr(task, "task") and hasattr(task.task, "_listener"):
                    await task.task._listener.on_download_error(
                        f"Task auto-cancelled: 0 bytes/s for {Config.STALLED_TASK_TIMEOUT} minutes"
                    )

            # Remove from stalled tasks list
            if mid in self.ytdlp_stalled_tasks:
                del self.ytdlp_stalled_tasks[mid]

        except Exception as e:
            LOGGER.error(f"Error cancelling stalled yt-dlp task {mid}: {e}")

    async def _cancel_paused_task(self, mid: str, task):
        """Cancel a paused task"""
        try:
            LOGGER.warning(
                f"Auto-cancelling paused task: {task.name()} (MID: {mid}) - paused for {Config.STALLED_TASK_TIMEOUT} minutes"
            )

            # Cancel the task using the listener
            if hasattr(task, "listener") and hasattr(
                task.listener, "on_download_error"
            ):
                await task.listener.on_download_error(
                    f"Task auto-cancelled: paused for {Config.STALLED_TASK_TIMEOUT} minutes"
                )
            else:
                # Fallback: try to cancel the task object directly
                if hasattr(task, "task") and hasattr(task.task, "_listener"):
                    await task.task._listener.on_download_error(
                        f"Task auto-cancelled: paused for {Config.STALLED_TASK_TIMEOUT} minutes"
                    )

            # Remove from paused tasks list
            if mid in self.paused_tasks:
                del self.paused_tasks[mid]

        except Exception as e:
            LOGGER.error(f"Error cancelling paused task {mid}: {e}")

    def reset_stalled_tasks(self):
        """Reset all stalled task tracking"""
        self.aria2_stalled_tasks.clear()
        self.qbit_stalled_tasks.clear()
        self.ytdlp_stalled_tasks.clear()
        self.paused_tasks.clear()
        LOGGER.info("Stalled task tracking reset")


# Global instance
stalled_task_monitor = StalledTaskMonitor()


def aria2_name(download_info):
    """Extract name from Aria2 download info"""
    if "bittorrent" in download_info and download_info["bittorrent"].get("info"):
        return download_info["bittorrent"]["info"]["name"]
    elif download_info.get("files"):
        if download_info["files"][0]["path"].startswith("[METADATA]"):
            return download_info["files"][0]["path"]
        file_path = download_info["files"][0]["path"]
        dir_path = download_info["dir"]
        if file_path.startswith(dir_path):
            from pathlib import Path

            parts = Path(file_path[len(dir_path) + 1 :]).parts
            if parts:
                return parts[0]
        # Fallback: extract filename from full path
        from pathlib import Path

        filename = Path(file_path).name
        if filename and filename != ".":
            return filename
        # Last resort fallback
        return f"download_{download_info.get('gid', 'unknown')}"
    else:
        # Fallback for downloads without files info
        return f"download_{download_info.get('gid', 'unknown')}"
