from time import time
from .... import LOGGER
from ...ext_utils.status_utils import (
    get_readable_file_size,
    get_readable_time,
    MirrorStatus,  # Added for engine name consistency if needed
)


class SplitStatus:
    def __init__(self, listener, gid: str, total_files_to_split: int = 1):
        self.listener = listener
        self._gid = gid
        self._status = MirrorStatus.STATUS_SPLIT
        self.engine = (
            "GenericSplitter"  # Could use EngineStatus if a constant is preferred
        )
        self._time = time()
        self._total_files_to_split = total_files_to_split
        self._files_processed_count = (
            0  # To track how many of the initial large files are processed
        )
        self._last_progress_update = time()
        self._last_processed_bytes = 0

    def gid(self):
        return self._gid

    def name(self):
        return self.listener.name

    def size(self):
        # This refers to the total size of the original task/file(s) being split
        return get_readable_file_size(self.listener.size)

    def status(self):
        return self._status

    def engine_name(
        self,
    ):  # Renamed from engine() to avoid conflict if listener has engine property
        return self.engine

    def progress_raw(self):
        """
        Enhanced progress calculation that properly handles FFmpeg splitting.
        """
        if self._total_files_to_split <= 0:
            return 0

        # Get progress from the current FFmpeg operation if available
        if hasattr(self.listener, "subproc") and self.listener.subproc:
            # Check if we have an FFMpeg status object in task_dict
            from .... import task_dict

            if self.listener.mid in task_dict:
                ffmpeg_status = task_dict[self.listener.mid]
                if hasattr(ffmpeg_status, "_obj") and hasattr(
                    ffmpeg_status._obj, "progress_raw"
                ):
                    current_file_progress = ffmpeg_status._obj.progress_raw
                    # Calculate overall progress based on files completed + current file progress
                    files_completed = (
                        self.listener.proceed_count - 1
                    )  # Current file not yet completed
                    total_progress = (
                        files_completed * 100 + current_file_progress
                    ) / self._total_files_to_split
                    return min(total_progress, 100)

        # Fallback to simple file-based progress
        progress = (self.listener.proceed_count / self._total_files_to_split) * 100
        return min(progress, 100)

    def progress(self):
        return f"{round(self.progress_raw(), 2)}%"

    def speed(self):
        """
        Enhanced speed calculation that gets speed from FFmpeg operations.
        """
        try:
            # Get speed from the current FFmpeg operation if available
            from .... import task_dict

            if self.listener.mid in task_dict:
                ffmpeg_status = task_dict[self.listener.mid]
                if hasattr(ffmpeg_status, "_obj") and hasattr(
                    ffmpeg_status._obj, "speed_raw"
                ):
                    speed_raw = ffmpeg_status._obj.speed_raw
                    if speed_raw and speed_raw > 0:
                        return f"{get_readable_file_size(speed_raw)}/s"

            # Fallback: calculate speed based on processed bytes if available
            if (
                hasattr(self.listener, "proceed_count")
                and self.listener.proceed_count > 0
            ):
                current_time = time()
                elapsed = current_time - self._time
                if elapsed > 0:
                    # Estimate processed bytes based on progress
                    total_size = getattr(self.listener, "size", 0)
                    progress_ratio = self.progress_raw() / 100
                    processed_bytes = total_size * progress_ratio

                    # Calculate speed
                    speed = processed_bytes / elapsed
                    if speed > 0:
                        return f"{get_readable_file_size(speed)}/s"
        except Exception as e:
            LOGGER.debug(f"Error calculating split speed: {e}")

        return "Calculating..."

    def eta(self):
        """
        Enhanced ETA calculation that gets ETA from FFmpeg operations.
        """
        try:
            # Get ETA from the current FFmpeg operation if available
            from .... import task_dict

            if self.listener.mid in task_dict:
                ffmpeg_status = task_dict[self.listener.mid]
                if hasattr(ffmpeg_status, "_obj") and hasattr(
                    ffmpeg_status._obj, "eta_raw"
                ):
                    eta_raw = ffmpeg_status._obj.eta_raw
                    if eta_raw and eta_raw != float("inf") and eta_raw > 0:
                        return get_readable_time(eta_raw)

            # Fallback: estimate ETA based on current progress and speed
            progress_ratio = self.progress_raw() / 100
            if progress_ratio > 0 and progress_ratio < 1:
                elapsed = time() - self._time
                if elapsed > 0:
                    estimated_total_time = elapsed / progress_ratio
                    remaining_time = estimated_total_time - elapsed
                    if remaining_time > 0:
                        return get_readable_time(remaining_time)
        except Exception as e:
            LOGGER.debug(f"Error calculating split ETA: {e}")

        return "~"

    def elapsed(self):
        return get_readable_time(time() - self._time)

    def task(self):
        return self

    async def cancel_task(self):
        LOGGER.info(f"Cancelling split for: {self.listener.name} (GID: {self._gid})")
        self.listener.is_cancelled = True
        # split_file utility should check listener.is_cancelled periodically.
        # No direct subproc to kill like in FFMpegStatus usually.
        # Error/cleanup will be handled by the main listener logic once split_file returns due to cancellation.
        # We can call on_upload_error here if appropriate, but proceed_split might handle it too.
        # For now, just setting the flag is the primary action for this status object.
        # The main listener's on_upload_error will likely be triggered by proceed_split returning False.
        pass
