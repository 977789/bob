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
        # Show METADATA status if the uploader is in that phase
        if (
            hasattr(self._obj, "_status")
            and self._obj._status == MirrorStatus.STATUS_MEGA_METADATA
        ):
            return MirrorStatus.STATUS_MEGA_METADATA
        if (
            hasattr(self._obj, "_status")
            and self._obj._status == MirrorStatus.STATUS_SPLIT
        ):
            return MirrorStatus.STATUS_SPLIT
        if self._status == "up":
            return MirrorStatus.STATUS_UPLOAD
        return MirrorStatus.STATUS_DOWNLOAD

    def name(self):
        if hasattr(self._obj, "_is_splitting") and self._obj._is_splitting:
            return f"{self._obj._original_file_basename_for_status} (Part {self._obj._current_part_num}/{self._obj._total_parts})"
        return self.listener.name

    def progress(self):
        if (
            hasattr(self._obj, "_status")
            and self._obj._status == MirrorStatus.STATUS_MEGA_METADATA
        ):
            # Show real METADATA progress if available
            if hasattr(self._obj, "metadata_progress"):
                percent = round(self._obj.metadata_progress, 2)
                if percent == 0:
                    return "Processing..."
                return f"{percent}%"
            return "Processing..."
        # Always calculate progress based on processed_bytes vs total size.
        # The name() method will indicate if it's splitting a part.
        # The status() method will indicate MirrorStatus.STATUS_SPLIT.
        # This allows the progress bar to reflect the upload of the current part.
        try:
            progress_raw = self._obj.processed_bytes / self._size * 100
        except ZeroDivisionError:
            progress_raw = 0
        return f"{round(progress_raw, 2)}%"

    def speed(self):
        if (
            hasattr(self._obj, "_status")
            and self._obj._status == MirrorStatus.STATUS_SPLIT
        ):
            return "0B/s"  # Splitting is a local CPU/disk op, not network
        # Show speed for METADATA phase
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
        if (
            hasattr(self._obj, "_status")
            and self._obj._status == MirrorStatus.STATUS_SPLIT
        ):
            return "-"
        try:
            seconds = (self._size - self._obj.processed_bytes) / self._obj.speed
            return get_readable_time(seconds)
        except ZeroDivisionError:
            return "-"

    def gid(self):
        return self._gid

    def task(self):
        return self._obj
