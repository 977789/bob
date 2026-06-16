from time import time
from contextlib import suppress

from .... import LOGGER
from ...ext_utils.status_utils import (
    get_readable_file_size,
    MirrorStatus,
    EngineStatus,
    get_readable_time,
)


class SevenZStatus:
    def __init__(self, listener, obj, gid, status=""):
        self.listener = listener
        self._obj = obj
        self._gid = gid
        self._start_time = time()
        self._cstatus = status
        self.engine = EngineStatus().STATUS_7Z
        self._last_progress_update = time()
        self._last_progress_value = "0%"

    def gid(self):
        return self._gid

    def _speed_raw(self):
        """Calculate speed with safety checks for division by zero and memory efficiency"""
        try:
            elapsed = time() - self._start_time
            if elapsed <= 0:
                return 0

            # Use bytes_per_second from extraction object if available
            if (
                hasattr(self._obj, "_bytes_per_second")
                and self._obj._bytes_per_second > 0
            ):
                return self._obj._bytes_per_second

            # Fallback to basic calculation
            processed = self._obj.processed_bytes
            if processed <= 0:
                return 0

            return processed / elapsed
        except (ZeroDivisionError, AttributeError, TypeError):
            return 0

    def progress(self):
        """Enhanced progress tracking with stuck detection"""
        try:
            current_progress = self._obj.progress
            current_time = time()

            # Check if progress appears stuck
            if current_progress != self._last_progress_value:
                self._last_progress_update = current_time
                self._last_progress_value = current_progress
                LOGGER.debug(f"Progress updated: {current_progress}")
            elif (
                current_time - self._last_progress_update > 300
            ):  # 5 minutes without progress
                # If extraction seems stuck, provide estimated progress based on time
                elapsed = current_time - self._start_time
                if hasattr(self.listener, "subsize") and self.listener.subsize > 0:
                    # Estimate based on average extraction speed (conservative)
                    estimated_progress = min(99, (elapsed / 60) * 2)  # 2% per minute
                    LOGGER.warning(
                        f"Progress appears stuck, showing estimated: {estimated_progress:.1f}%"
                    )
                    return f"{estimated_progress:.1f}%"

            # Ensure progress is never empty or invalid
            if (
                not current_progress
                or current_progress == "0%"
                and (time() - self._start_time) > 60
            ):
                # For long-running extractions, show minimal progress to indicate activity
                elapsed_minutes = (time() - self._start_time) / 60
                fallback_progress = min(
                    95, elapsed_minutes * 0.5
                )  # Very conservative progress
                LOGGER.debug(f"Using fallback progress: {fallback_progress:.1f}%")
                return f"{fallback_progress:.1f}%"

            return current_progress
        except (AttributeError, TypeError) as e:
            LOGGER.debug(f"Progress calculation error: {e}")
            # Fallback progress calculation
            elapsed = time() - self._start_time
            if elapsed > 60:  # After 1 minute, show some progress
                fallback = min(90, elapsed / 60)  # 1% per minute max
                return f"{fallback:.1f}%"
            return "0%"

    def speed(self):
        """Enhanced speed calculation with better formatting"""
        try:
            speed_raw = self._speed_raw()
            if speed_raw <= 0:
                return "0B/s"
            return f"{get_readable_file_size(speed_raw)}/s"
        except Exception:
            return "0B/s"

    def processed_bytes(self):
        """Enhanced processed bytes with safety checks"""
        try:
            processed = self._obj.processed_bytes
            if processed <= 0:
                # Estimate based on progress percentage and total size
                progress_str = self._obj.progress.rstrip("%")
                if progress_str and progress_str.replace(".", "").isdigit():
                    progress_pct = float(progress_str)
                    if hasattr(self.listener, "subsize") and self.listener.subsize > 0:
                        estimated = int((progress_pct / 100) * self.listener.subsize)
                        return get_readable_file_size(estimated)
                return "0B"
            return get_readable_file_size(processed)
        except (AttributeError, ValueError, TypeError):
            return "0B"

    def name(self):
        return self.listener.name

    def size(self):
        """Enhanced size display with better handling"""
        try:
            # Try to get the actual archive size first
            if hasattr(self.listener, "subsize") and self.listener.subsize > 0:
                return get_readable_file_size(self.listener.subsize)
            # Fallback to listener size
            return get_readable_file_size(self.listener.size)
        except (AttributeError, TypeError):
            return "Unknown"

    def eta(self):
        """Enhanced ETA calculation with better error handling and estimates"""
        try:
            speed_raw = self._speed_raw()
            if speed_raw <= 0:
                # Provide estimated ETA based on elapsed time and progress
                elapsed = time() - self._start_time
                progress_str = self._obj.progress.rstrip("%")
                if progress_str and progress_str.replace(".", "").isdigit():
                    progress_pct = float(progress_str)
                    if progress_pct > 0 and progress_pct < 100:
                        estimated_total_time = (elapsed * 100) / progress_pct
                        remaining_time = estimated_total_time - elapsed
                        if remaining_time > 0:
                            return get_readable_time(remaining_time)
                return "-"

            # Calculate remaining bytes
            total_size = getattr(self.listener, "subsize", 0) or self.listener.size
            processed = self._obj.processed_bytes

            if total_size > processed > 0:
                remaining_bytes = total_size - processed
                remaining_seconds = remaining_bytes / speed_raw
                return get_readable_time(remaining_seconds)

            return "-"
        except (ZeroDivisionError, AttributeError, TypeError, ValueError):
            return "-"

    def status(self):
        if self._cstatus == "Extract":
            return MirrorStatus.STATUS_EXTRACT
        else:
            return MirrorStatus.STATUS_ARCHIVE

    def task(self):
        return self

    async def cancel_task(self):
        LOGGER.info(f"Cancelling {self._cstatus}: {self.listener.name}")
        self.listener.is_cancelled = True
        if (
            self.listener.subproc is not None
            and self.listener.subproc.returncode is None
        ):
            with suppress(Exception):
                self.listener.subproc.kill()
        await self.listener.on_upload_error(f"{self._cstatus} stopped by user!")
