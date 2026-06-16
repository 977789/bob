from ...ext_utils.status_utils import (
    EngineStatus,
    MirrorStatus,
    get_readable_file_size,
    get_readable_time,
)


class DirectStatus:
    def __init__(self, listener, obj, gid):
        self._gid = gid
        self._obj = obj
        self.listener = listener
        self.engine = EngineStatus().STATUS_ARIA2

    def gid(self):
        return self._gid

    def progress_raw(self):
        try:
            if self.listener.size <= 0:
                return 0
            return self._obj.processed_bytes / self.listener.size * 100
        except Exception:
            return 0

    def progress(self):
        return f"{round(self.progress_raw(), 2)}%"

    def speed(self):
        return f"{get_readable_file_size(self._obj.speed)}/s"

    def name(self):
        return self.listener.name

    def size(self):
        if self.listener.size <= 0:
            # Try to get size from processed bytes if available
            if hasattr(self._obj, "processed_bytes") and self._obj.processed_bytes > 0:
                return get_readable_file_size(self._obj.processed_bytes)
            return "Unknown"
        return get_readable_file_size(self.listener.size)

    def eta(self):
        try:
            if self.listener.size <= 0 or self._obj.speed <= 0:
                return "-"
            seconds = (self.listener.size - self._obj.processed_bytes) / self._obj.speed
            return get_readable_time(seconds)
        except Exception:
            return "-"

    def status(self):
        if (
            self._obj.download_task
            and self._obj.download_task.get("status", "") == "waiting"
        ):
            return MirrorStatus.STATUS_QUEUEDL
        return MirrorStatus.STATUS_DOWNLOAD

    def processed_bytes(self):
        return get_readable_file_size(self._obj.processed_bytes)

    def task(self):
        return self._obj
