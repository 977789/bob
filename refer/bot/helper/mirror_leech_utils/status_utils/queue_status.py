from .... import LOGGER
from ...ext_utils.status_utils import get_readable_file_size, MirrorStatus, EngineStatus
from ...ext_utils.status_utils import MirrorStatus


class QueueStatus:
    def __init__(self, listener, gid, status):
        self.listener = listener
        self._size = self.listener.size
        self._gid = gid
        self._status = status
        self.engine = EngineStatus().STATUS_QUEUE

    def gid(self):
        return self._gid

    def name(self):
        return self.listener.name

    def size(self):
        return get_readable_file_size(self._size)

    def status(self):
        if self._status == "dl":
            return MirrorStatus.STATUS_QUEUEDL
        return MirrorStatus.STATUS_QUEUEUP

    def processed_bytes(self):
        return 0

    def progress(self):
        return "0%"

    def speed(self):
        return "0B/s"

    def eta(self):
        return "-"

    def task(self):
        return self

    async def cancel_task(self):
        LOGGER.info(f"[CANCEL] QueueStatus.cancel_task START for {self.listener.name}")
        self.listener.is_cancelled = True
        LOGGER.info(f"[CANCEL] QueueStatus: set is_cancelled for {self.listener.name}")
        if self._status == "dl":
            await self.listener.on_download_error(
                "task have been removed from queue/download"
            )
            LOGGER.info(
                f"[CANCEL] QueueStatus: on_download_error complete for {self.listener.name}"
            )
        else:
            await self.listener.on_upload_error(
                "task have been removed from queue/upload"
            )
            LOGGER.info(
                f"[CANCEL] QueueStatus: on_upload_error complete for {self.listener.name}"
            )
        LOGGER.info(f"[CANCEL] QueueStatus.cancel_task END for {self.listener.name}")


class MediaProcessingQueueStatus:
    def __init__(self, listener, gid):
        self.listener = listener
        self._size = self.listener.size
        self._gid = gid
        self.engine = EngineStatus().STATUS_QUEUE

    def gid(self):
        return self._gid

    def name(self):
        return self.listener.name

    def size(self):
        return get_readable_file_size(self._size)

    def status(self):
        return MirrorStatus.STATUS_QUEUEMEDIA

    def processed_bytes(self):
        return 0

    def progress(self):
        return "0%"

    def speed(self):
        return "0B/s"

    def eta(self):
        return "-"

    def task(self):
        return self

    async def cancel_task(self):
        LOGGER.info(
            f"[CANCEL] MediaProcessingQueueStatus.cancel_task START for {self.listener.name}"
        )
        self.listener.is_cancelled = True
        LOGGER.info(
            f"[CANCEL] MediaProcessingQueueStatus: set is_cancelled for {self.listener.name}"
        )
        await self.listener.on_upload_error(
            "Media processing task has been removed from queue"
        )
        LOGGER.info(
            f"[CANCEL] MediaProcessingQueueStatus.cancel_task END for {self.listener.name}"
        )


class ExtractionQueueStatus:
    def __init__(self, listener, gid):
        self.listener = listener
        self._size = self.listener.size
        self._gid = gid
        self.engine = EngineStatus().STATUS_QUEUE

    def gid(self):
        return self._gid

    def name(self):
        return self.listener.name

    def size(self):
        return get_readable_file_size(self._size)

    def status(self):
        return MirrorStatus.STATUS_QUEUEEXTRACT

    def processed_bytes(self):
        return 0

    def progress(self):
        return "0%"

    def speed(self):
        return "0B/s"

    def eta(self):
        return "-"

    def task(self):
        return self

    async def cancel_task(self):
        LOGGER.info(
            f"[CANCEL] ExtractionQueueStatus.cancel_task START for {self.listener.name}"
        )
        self.listener.is_cancelled = True
        LOGGER.info(
            f"[CANCEL] ExtractionQueueStatus: set is_cancelled for {self.listener.name}"
        )
        await self.listener.on_upload_error(
            "Extraction task has been removed from queue"
        )
        LOGGER.info(
            f"[CANCEL] ExtractionQueueStatus.cancel_task END for {self.listener.name}"
        )
