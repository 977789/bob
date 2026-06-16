import os
import time
from .... import LOGGER
from ...ext_utils.status_utils import (
    get_readable_file_size,
    EngineStatus,
    MirrorStatus,
    get_readable_time,
)


class WatermarkStatus:
    def __init__(self, listener, obj, gid, status=""):
        self.listener = listener
        self._obj = obj
        self._gid = gid
        self._cstatus = status
        self.engine = EngineStatus().STATUS_WATERMARK

    def speed(self):
        # Return a speed value during watermarking
        if self._obj.speed_raw > 0:
            return f"{get_readable_file_size(self._obj.speed_raw)}/s"
        elif hasattr(self._obj, "ffmpeg_speed") and self._obj.ffmpeg_speed > 0:
            return f"{self._obj.ffmpeg_speed:.2f}x"
        else:
            return "N/A"

    def processed_bytes(self):
        # Show actual processed bytes during watermarking
        if self._obj.processed_bytes > 0:
            return get_readable_file_size(self._obj.processed_bytes)
        # If watermarking has started but no bytes processed yet, show minimal value
        elif hasattr(self._obj, "watermark_started") and self._obj.watermark_started:
            return get_readable_file_size(1024)  # Show at least 1KB when started
        # If current frame > 0, we're processing
        elif hasattr(self._obj, "current_frame") and self._obj.current_frame > 0:
            return get_readable_file_size(1024)  # Show at least 1KB when processing
        else:
            return get_readable_file_size(0)

    def progress(self):
        progress_value = self._obj.progress_raw
        if (
            progress_value <= 0
            and hasattr(self._obj, "watermark_started")
            and self._obj.watermark_started
        ):
            progress_value = 0.1
        return f"{round(progress_value, 2)}%"

    def gid(self):
        return self._gid

    def name(self):
        return self.listener.name

    def size(self):
        return get_readable_file_size(self.listener.size)

    def eta(self):
        return get_readable_time(self._obj.eta_raw) if self._obj.eta_raw else "-"

    def status(self):
        return MirrorStatus.STATUS_WATERMARK

    def eng_msg(self):
        # Return watermarking status message
        if not hasattr(self._obj, "input_path"):
            return "Starting watermark..."

        parts = []

        # Get watermark type information
        wm_type = None
        if hasattr(self._obj, "watermark_type") and self._obj.watermark_type:
            wm_type = self._obj.watermark_type.capitalize()

        # Check if watermarking has started
        if hasattr(self._obj, "current_frame") and self._obj.current_frame > 0:
            # Frame information
            if hasattr(self._obj, "total_frames") and self._obj.total_frames > 0:
                parts.append(
                    f"frame {self._obj.current_frame}/{self._obj.total_frames}"
                )
            else:
                parts.append(f"frame {self._obj.current_frame}")

            # FFmpeg reported time
            if hasattr(self._obj, "encoding_time") and self._obj.encoding_time:
                parts.append(f"time {self._obj.encoding_time}")

            # FFmpeg reported speed
            if hasattr(self._obj, "ffmpeg_speed") and self._obj.ffmpeg_speed > 0:
                parts.append(f"speed {self._obj.ffmpeg_speed:.2f}x")

            # FFmpeg reported FPS
            if hasattr(self._obj, "fps") and self._obj.fps > 0:
                parts.append(f"fps {self._obj.fps:.1f}")

            # FFmpeg reported bitrate
            if hasattr(self._obj, "bitrate") and self._obj.bitrate:
                parts.append(f"{self._obj.bitrate}")

            # Add watermark type and settings
            if wm_type:
                parts.append(f"{wm_type} WM")

            # Add encoding settings
            if hasattr(self._obj, "preset") and hasattr(self._obj, "crf"):
                parts.append(f"Preset: {self._obj.preset}")
                parts.append(f"CRF: {self._obj.crf}")

            # Add watermark position
            if hasattr(self._obj, "watermark_position"):
                pos = self._obj.watermark_position.replace("-", " ").title()
                parts.append(f"Pos: {pos}")

            # Add opacity info
            if hasattr(self._obj, "watermark_opacity"):
                opacity = int(self._obj.watermark_opacity * 100)
                parts.append(f"Op: {opacity}%")
        else:
            # If watermarking hasn't produced frame output yet
            parts = ["frame 0", f"time {self._obj.encoding_time}", "speed N/A"]

            # Add watermark info
            if wm_type:
                parts.append(f"{wm_type} WM")

            # Add preparation message
            elapsed = time.time() - self._obj.start_time
            if elapsed < 3:
                parts.append("initializing...")
            elif elapsed < 10:
                parts.append("analyzing...")
            else:
                parts.append("processing...")

        return " | ".join(parts)

    def task(self):
        return self

    # Additional information for the status message
    def get_frame_info(self):
        if hasattr(self._obj, "current_frame"):
            if hasattr(self._obj, "total_frames") and self._obj.total_frames > 0:
                return f"{self._obj.current_frame}/{self._obj.total_frames}"
            return str(self._obj.current_frame)
        return ""

    def get_fps(self):
        if hasattr(self._obj, "fps") and self._obj.fps > 0:
            return f"{self._obj.fps:.1f}"
        return ""

    def get_watermark_type(self):
        return (
            self._obj.watermark_type
            if hasattr(self._obj, "watermark_type") and self._obj.watermark_type
            else "text"
        )

    def get_watermark_position(self):
        return (
            self._obj.watermark_position
            if hasattr(self._obj, "watermark_position") and self._obj.watermark_position
            else "bottom-right"
        )

    def get_watermark_opacity(self):
        return (
            self._obj.watermark_opacity
            if hasattr(self._obj, "watermark_opacity")
            else 0.5
        )

    def get_watermark_text(self):
        return (
            self._obj.watermark_text
            if hasattr(self._obj, "watermark_text")
            else "Default Watermark"
        )

    def get_preset(self):
        return self._obj.preset if hasattr(self._obj, "preset") else "medium"

    def get_crf(self):
        return self._obj.crf if hasattr(self._obj, "crf") else 23

    def get_audio_bitrate(self):
        return (
            self._obj.audio_bitrate if hasattr(self._obj, "audio_bitrate") else "128k"
        )

    # Make methods compatible with status message generation
    def seeders_num(self):
        return ""

    def leechers_num(self):
        return ""

    def uploaded_bytes(self):
        return ""

    def seed_speed(self):
        return ""

    def ratio(self):
        return ""

    def seeding_time(self):
        return ""

    async def cancel_task(self):
        LOGGER.info(f"Cancelling {self._cstatus}: {self.listener.name}")
        self.listener.is_cancelled = True
        if (
            self.listener.subproc is not None
            and self.listener.subproc.returncode is None
        ):
            try:
                self.listener.subproc.kill()
            except Exception:
                pass
        await self.listener.on_upload_error(f"{self._cstatus} stopped by user!")
