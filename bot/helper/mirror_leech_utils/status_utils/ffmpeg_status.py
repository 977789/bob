from time import time
from contextlib import suppress
from .... import subprocess_lock, videos_tools_mode, LOGGER
from ...ext_utils.status_utils import (
    get_readable_file_size,
    EngineStatus,
    MirrorStatus,
    get_readable_time,
)


class FFMpegStatus:
    def __init__(self, listener, obj, gid: str, status: str):
        self.listener = listener
        self._gid = gid
        self._obj = obj
        self._status = status
        self.engine = EngineStatus().STATUS_FFMPEG
        self._time = time()

    def engine(self):
        return "Alass" if self._status == "sync" else "FFmpeg"

    def elapsed(self):
        return get_readable_time(time() - self._time)

    def processed_bytes(self):
        if hasattr(self._obj, "processed_bytes"):
            return get_readable_file_size(self._obj.processed_bytes)
        return "0 B"

    def gid(self):
        return self._gid

    def progress(self):
        """
        Return the progress of the FFmpeg operation as a percentage string.
        Handles objects with 'percentage', 'progress_raw', or falls back to 0%.
        """
        val = 0.0
        if hasattr(self._obj, "percentage") and self._obj.percentage is not None:
            val = float(self._obj.percentage)
        elif hasattr(self._obj, "progress_raw") and self._obj.progress_raw is not None:
            val = float(self._obj.progress_raw)
        # Fallback for document split (system 'split') where FFmpeg progress fields may be unavailable
        elif (
            getattr(self.listener, "mode", None) == ("", "")
            or self.status() == MirrorStatus.STATUS_SPLIT
        ):
            try:
                # Estimate by summing current generated split file sizes if we have a prefix
                from os import listdir as os_listdir
                from os.path import getsize as os_getsize

                prefix = getattr(self.listener, "current_split_prefix", None)
                total = getattr(self.listener, "subsize", 0) or getattr(
                    self.listener, "size", 0
                )
                if prefix and total > 0:
                    base_dir = prefix.rsplit("/", 1)[0]
                    pref = prefix.rsplit("/", 1)[-1]
                    done = 0
                    for name in os_listdir(base_dir):
                        if name.startswith(pref):
                            try:
                                done += os_getsize(f"{base_dir}/{name}")
                            except Exception:
                                pass
                    if done > 0:
                        val = min(100.0, (done * 100.0) / float(total))
            except Exception:
                pass
        return f"{round(val, 2)}%"

    def speed(self):
        """
        Return the speed of the FFmpeg operation as a string.
        Handles objects with 'speed', 'speed_raw', or falls back to '0 B/s'.
        """
        speed_val = 0
        if hasattr(self._obj, "speed") and self._obj.speed is not None:
            speed_val = self._obj.speed
        elif hasattr(self._obj, "speed_raw") and self._obj.speed_raw is not None:
            speed_val = self._obj.speed_raw
        if speed_val:
            return f"{get_readable_file_size(speed_val)}/s"
        return "0 B/s"

    def name(self):
        if self.listener.subname:
            return f"{self.listener.name} -> {self.listener.subname}"
        return self.listener.name

    def size(self):
        return get_readable_file_size(self.listener.size)

    def timeout(self):
        return get_readable_time(180 - (time() - self._time))

    def eta(self):
        """
        Return the estimated time remaining for the operation as a string.
        Handles objects with 'eta', 'eta_raw', '_eta', or falls back to '~'.
        """
        eta_val = None
        if hasattr(self._obj, "eta") and self._obj.eta is not None:
            eta_val = self._obj.eta
        elif hasattr(self._obj, "eta_raw") and self._obj.eta_raw is not None:
            eta_val = self._obj.eta_raw
        elif hasattr(self._obj, "_eta") and self._obj._eta is not None:
            eta_val = self._obj._eta
        if eta_val is not None:
            return get_readable_time(eta_val)
        # Fallback: try to estimate from speed and processed_bytes
        try:
            speed_bps = 0
            if hasattr(self._obj, "speed") and self._obj.speed:
                speed_bps = self._obj.speed
            elif hasattr(self._obj, "speed_raw") and self._obj.speed_raw:
                speed_bps = self._obj.speed_raw
            if speed_bps > 0 and hasattr(self._obj, "processed_bytes"):
                remaining_bytes = self.listener.size - self._obj.processed_bytes
                if remaining_bytes > 0:
                    return get_readable_time(remaining_bytes / speed_bps)
        except Exception:
            pass
        return "~"

    def status(self):
        """
        Determines the status string for the current operation.
        Added a case for 'split' to correctly report splitting status.
        """
        # First, check the status string passed during initialization
        match self._status:
            case "meta":
                return MirrorStatus.STATUS_METADATA
            case "attach":
                return MirrorStatus.STATUS_ATTACHMENT
            case "sv":
                return MirrorStatus.STATUS_SAMVID
            case "cv":
                return MirrorStatus.STATUS_CONVERT
            case "wait":
                return MirrorStatus.STATUS_WAIT
            case "intro":
                return MirrorStatus.STATUS_INTRO_SUB
            case "Split":  # Changed "split" to "Split" to match initialization string
                return MirrorStatus.STATUS_SPLIT

        # If not matched, check the mode of the FFmpeg object
        if not hasattr(self._obj, "mode"):
            # Check if this is likely an encoding operation by looking at user settings
            user_dict = getattr(self.listener, "user_dict", {}) or {}
            if user_dict.get("VIDEO_ENCODE_ENABLED", False) or user_dict.get(
                "VIDEO_ENCODE_MULTI_RESOLUTION", False
            ):
                return MirrorStatus.STATUS_CONVERT
            return MirrorStatus.STATUS_EXTRACT  # Default if mode is not available

        match self._obj.mode:
            case "vid_vid" | "vid_aud" | "vid_sub":
                return MirrorStatus.STATUS_MERGE
            case "swapstream" | "reordertracks":
                return MirrorStatus.STATUS_SWAP
            case "convert" | "multi_res":
                return MirrorStatus.STATUS_CONVERT
            case "sv":
                return MirrorStatus.STATUS_SAMVID
            case "subsync":
                return MirrorStatus.STATUS_SUBSYNC
            case "compress":
                return MirrorStatus.STATUS_COMPRESS
            case "trim":
                return MirrorStatus.STATUS_TRIM
            case "watermark":
                return MirrorStatus.STATUS_WATERMARK
            case "intro_sub":
                return MirrorStatus.STATUS_INTRO_SUB
            case "rmstream":
                return MirrorStatus.STATUS_RMSTREAM
            case "speed":
                return MirrorStatus.STATUS_SPEED
            case "split":  # FIX: Added this case
                return MirrorStatus.STATUS_SPLIT
            case "extract":
                return MirrorStatus.STATUS_EXTRACT
            case _:
                # Default for encoding operations (when mode is not explicitly set)
                return MirrorStatus.STATUS_CONVERT

    def task(self):
        return self

    async def cancel_task(self):
        self.listener.is_cancelled = True

        info = f"Operation ({self._status or self._obj.mode})"
        with suppress(Exception):
            match self._status:
                case "sv":
                    info = "Creating sample video"
                case "cv":
                    info = "Convert media"
                case "meta":
                    info = "Edit metadata"
                case "attach":
                    info = "Adding attachments"
                case _:
                    info = videos_tools_mode[self._obj.mode]

        LOGGER.info("Cancelling %s: %s", info, self.name())
        async with subprocess_lock:
            if self.listener.subproc and self.listener.subproc.returncode is None:
                self.listener.subproc.kill()
        self.listener.is_cancelled = True
        await self.listener.on_upload_error(f"{info} stopped by user!")
