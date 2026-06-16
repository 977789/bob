from time import time
from ...ext_utils.status_utils import (
    MirrorStatus,
    EngineStatus,
    get_readable_file_size,
    get_readable_time,
)


class TelegramStatus:
    def __init__(self, listener, obj, gid, status, hyper=False):
        self.listener = listener
        self._obj = obj
        self._size = self.listener.size
        self._gid = gid
        self._status = status
        self.engine = EngineStatus().STATUS_TGRAM + (" (HyperDL)" if hyper else "")

    def processed_bytes(self):
        return get_readable_file_size(self._obj.processed_bytes)

    def size(self):
        return get_readable_file_size(self._size)

    def status(self):
        # Show MegaMetaData status if the uploader is in that phase
        if (
            hasattr(self._obj, "_status")
            and self._obj._status == MirrorStatus.STATUS_MEGA_METADATA
        ):
            return MirrorStatus.STATUS_MEGA_METADATA
        if self._status == "up":
            return MirrorStatus.STATUS_UPLOAD
        return MirrorStatus.STATUS_DOWNLOAD

    def name(self):
        return self.listener.name

    def progress(self):
        if (
            hasattr(self._obj, "_status")
            and self._obj._status == MirrorStatus.STATUS_MEGA_METADATA
        ):
            # Show real MegaMetaData progress if available
            if hasattr(self._obj, "metadata_progress"):
                percent = round(self._obj.metadata_progress, 2)
                if percent == 0:
                    return "Processing..."
                return f"{percent}%"
            return "Processing..."
        try:
            progress_raw = self._obj.processed_bytes / self._size * 100
        except ZeroDivisionError:
            progress_raw = 0
        return f"{round(progress_raw, 2)}%"

    def speed(self):
        # Show speed for MegaMetaData phase
        if (
            hasattr(self._obj, "_status")
            and self._obj._status == MirrorStatus.STATUS_MEGA_METADATA
        ):
            # Calculate speed as processed bytes during metadata / elapsed time
            if hasattr(self._obj, "metadata_progress") and hasattr(
                self._obj, "_start_time"
            ):
                elapsed = max(1, int(time() - self._obj._start_time))
                # Estimate processed bytes as percent of file size
                percent = getattr(self._obj, "metadata_progress", 0)
                size = getattr(self._obj, "_size", getattr(self, "_size", 0))
                processed = int(size * percent / 100)
                speed = processed / elapsed if elapsed > 0 else 0
                return f"{get_readable_file_size(speed)}/s"
            return "0B/s"
        return f"{get_readable_file_size(self._obj.speed)}/s"

    def eta(self):
        try:
            seconds = (self._size - self._obj.processed_bytes) / self._obj.speed
            return get_readable_time(seconds)
        except ZeroDivisionError:
            return "-"

    def gid(self):
        return self._gid

    def task(self):
        return self._obj
