from time import time

from .... import LOGGER
from ....core.torrent_manager import TorrentManager, aria2_name
from ...ext_utils.status_utils import (
    EngineStatus,
    MirrorStatus,
    get_readable_time,
    get_readable_file_size,
)


async def get_download(gid, old_info=None):
    try:
        if TorrentManager.aria2 is None:
            LOGGER.warning("Aria2 manager is not initialized")
            return old_info or {}
        res = await TorrentManager.aria2.tellStatus(gid)
        return res or old_info or {}
    except Exception as e:
        LOGGER.error(f"{e}: Aria2c, Error while getting torrent info")
        return old_info or {}


class Aria2Status:
    def __init__(self, listener, gid, seeding=False, queued=False):
        self._gid = gid
        self._download = {}
        self.listener = listener
        self.queued = queued
        self.start_time = 0
        self.seeding = seeding
        self.engine = EngineStatus().STATUS_ARIA2
        # self.speed_sample_count = 0 # Removed as min speed check is disabled

    async def update(self):
        self._download = await get_download(self._gid, self._download)
        if self._download.get("followedBy", []):
            self._gid = self._download["followedBy"][0]
            self._download = await get_download(self._gid)

        # Minimum speed check logic removed as per user request
        # if (
        #     not self.seeding
        #     and self._download.get("status") == "active"
        # ):
        #     if self.name() == "METADATA":
        #         pass # self.speed_sample_count += 1 # No longer needed
        #     else:
        #         current_speed = int(self._download.get("downloadSpeed", "0"))
        #         # self.speed_sample_count += 1 # No longer needed

        #         # error_msg = await check_min_speed(current_speed, self.speed_sample_count) # Call removed
        #         # if error_msg:
        #             # ... cancellation logic removed ...
        #             # return

    def progress(self):
        try:
            return f"{round(int(self._download.get('completedLength', '0')) / int(self._download.get('totalLength', '0')) * 100, 2)}%"
        except ZeroDivisionError:
            return "0%"

    def processed_bytes(self):
        return get_readable_file_size(int(self._download.get("completedLength", "0")))

    def speed(self):
        return (
            f"{get_readable_file_size(int(self._download.get('downloadSpeed', '0')))}/s"
        )

    def name(self):
        return aria2_name(self._download)

    def size(self):
        return get_readable_file_size(int(self._download.get("totalLength", "0")))

    def eta(self):
        try:
            return get_readable_time(
                (
                    int(self._download.get("totalLength", "0"))
                    - int(self._download.get("completedLength", "0"))
                )
                / int(self._download.get("downloadSpeed", "0"))
            )
        except ZeroDivisionError:
            return "-"

    async def status(self):
        await self.update()
        if self._download.get("status", "") == "waiting" or self.queued:
            if self.seeding:
                return MirrorStatus.STATUS_QUEUEUP
            else:
                return MirrorStatus.STATUS_QUEUEDL
        elif self._download.get("status", "") == "paused":
            return MirrorStatus.STATUS_PAUSED
        elif self._download.get("seeder", "") == "true" and self.seeding:
            return MirrorStatus.STATUS_SEED
        else:
            return MirrorStatus.STATUS_DOWNLOAD

    def seeders_num(self):
        return self._download.get("numSeeders", 0)

    def leechers_num(self):
        return self._download.get("connections", 0)

    def uploaded_bytes(self):
        return get_readable_file_size(int(self._download.get("uploadLength", "0")))

    def seed_speed(self):
        return (
            f"{get_readable_file_size(int(self._download.get('uploadSpeed', '0')))}/s"
        )

    def ratio(self):
        try:
            return round(
                int(self._download.get("uploadLength", "0"))
                / int(self._download.get("completedLength", "0")),
                3,
            )
        except ZeroDivisionError:
            return 0

    def seeding_time(self):
        return get_readable_time(time() - self.start_time)

    def task(self):
        return self

    def gid(self):
        return self._gid

    async def cancel_task(self):
        LOGGER.info(f"[CANCEL] Aria2Status.cancel_task START for {self.name()}")
        self.listener.is_cancelled = True
        await self.update()
        LOGGER.info(f"[CANCEL] Aria2Status: update() complete for {self.name()}")
        await TorrentManager.aria2_remove(self._download)
        LOGGER.info(f"[CANCEL] Aria2Status: aria2_remove complete for {self.name()}")
        if self._download.get("seeder", "") == "true" and self.seeding:
            LOGGER.info(f"[CANCEL] Aria2Status: Cancelling Seed for {self.name()}")
            await self.listener.on_upload_error(
                f"Seeding stopped with Ratio: {self.ratio()} and Time: {self.seeding_time()}"
            )
        else:
            if self.queued:
                LOGGER.info(
                    f"[CANCEL] Aria2Status: Cancelling QueueDl for {self.name()}"
                )
                msg = "task have been removed from queue/download"
            else:
                LOGGER.info(
                    f"[CANCEL] Aria2Status: Cancelling Download for {self.name()}"
                )
                msg = "Stopped by user!"
            await self.listener.on_download_error(msg)
        LOGGER.info(f"[CANCEL] Aria2Status.cancel_task END for {self.name()}")
