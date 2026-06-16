import os
import time
from .... import LOGGER
from ...ext_utils.status_utils import (
    get_readable_file_size,
    EngineStatus,
    MirrorStatus,
    get_readable_time,
)


class FFmpegStatus:
    def __init__(self, listener, obj, gid, status=""):
        self.listener = listener
        self._obj = obj
        self._gid = gid
        self._cstatus = status
        self.engine = EngineStatus().STATUS_FFMPEG

    def speed(self):
        # Return a speed value, even at the start of encoding
        if self._obj.speed_raw > 0:
            return f"{get_readable_file_size(self._obj.speed_raw)}/s"
        # Show FFmpeg speed if available, otherwise N/A
        elif hasattr(self._obj, "ffmpeg_speed") and self._obj.ffmpeg_speed > 0:
            return f"{self._obj.ffmpeg_speed:.2f}x"
        else:
            return "N/A"

    def processed_bytes(self):
        # Show actual processed bytes during encoding
        if self._obj.processed_bytes > 0:
            return get_readable_file_size(self._obj.processed_bytes)
        # If encoding has started but no bytes processed yet, show minimal value
        elif hasattr(self._obj, "encoding_started") and self._obj.encoding_started:
            return get_readable_file_size(1024)  # Show at least 1KB when started
        # If current frame > 0, we're processing
        elif hasattr(self._obj, "current_frame") and self._obj.current_frame > 0:
            return get_readable_file_size(1024)  # Show at least 1KB when processing
        else:
            return get_readable_file_size(0)

    def progress(self):
        # Always show at least some progress if encoding is active
        progress_value = self._obj.progress_raw
        if (
            progress_value <= 0
            and hasattr(self._obj, "encoding_started")
            and self._obj.encoding_started
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
        # Always return FFMPEG status for encoding tasks
        return MirrorStatus.STATUS_FFMPEG

    def eng_msg(self):
        # Return a simplified status message using direct FFmpeg's values
        if not hasattr(self._obj, "input_path"):
            return "Muxing..."

        # Build the condensed status message with FFmpeg's directly reported values
        parts = []

        # Get quality information first - this is always available
        quality = None
        if hasattr(self._obj, "quality") and self._obj.quality:
            quality = self._obj.quality if self._obj.quality != "Original" else "Orig"

        # Check if encoding has actually started producing output
        if hasattr(self._obj, "current_frame") and self._obj.current_frame > 0:
            # Frame information - directly from FFmpeg
            if hasattr(self._obj, "total_frames") and self._obj.total_frames > 0:
                parts.append(
                    f"frame {self._obj.current_frame}/{self._obj.total_frames}"
                )
            else:
                parts.append(f"frame {self._obj.current_frame}")

            # FFmpeg reported time
            if hasattr(self._obj, "encoding_time") and self._obj.encoding_time:
                parts.append(f"time {self._obj.encoding_time}")

            # FFmpeg reported speed - exactly as FFmpeg shows it
            if hasattr(self._obj, "ffmpeg_speed") and self._obj.ffmpeg_speed > 0:
                parts.append(f"speed {self._obj.ffmpeg_speed:.2f}x")

            # FFmpeg reported FPS - exactly as FFmpeg shows it
            if hasattr(self._obj, "fps") and self._obj.fps > 0:
                parts.append(f"fps {self._obj.fps:.1f}")

            # FFmpeg reported bitrate
            if hasattr(self._obj, "bitrate") and self._obj.bitrate:
                parts.append(f"{self._obj.bitrate}")

            # Add quality, CRF and audio bitrate at the end
            if quality:
                codec_info = ""
                if hasattr(self._obj, "codec") and self._obj.codec:
                    codec_info = f" ({self._obj.codec})"
                parts.append(f"{quality}{codec_info}")

            # Add CRF if available
            if hasattr(self._obj, "crf"):
                parts.append(f"CRF {self._obj.crf}")

            # Add audio bitrate if available
            if hasattr(self._obj, "audio_bitrate"):
                parts.append(f"ABR {self._obj.audio_bitrate}")
        else:
            # If encoding hasn't produced frame output yet, show initialization info
            parts = ["frame 0", f"time {self._obj.encoding_time}", "speed N/A"]

            # Add quality, CRF and audio bitrate info
            if quality:
                codec_info = ""
                if hasattr(self._obj, "codec") and self._obj.codec:
                    codec_info = f" ({self._obj.codec})"
                parts.append(f"{quality}{codec_info}")

            # Add CRF if available
            if hasattr(self._obj, "crf"):
                parts.append(f"CRF {self._obj.crf}")

            # Add audio bitrate if available
            if hasattr(self._obj, "audio_bitrate"):
                parts.append(f"ABR {self._obj.audio_bitrate}")

            # Add preparation message
            elapsed = time.time() - self._obj.start_time
            if elapsed < 3:
                parts.append("initializing...")
            elif elapsed < 10:
                parts.append("analyzing...")
            else:
                parts.append("processing...")

        # Make it a single line status that matches FFmpeg's output format
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

    def get_quality(self):
        return (
            self._obj.quality
            if hasattr(self._obj, "quality") and self._obj.quality
            else "Original"
        )

    def get_codec(self):
        return (
            self._obj.codec
            if hasattr(self._obj, "codec") and self._obj.codec
            else "x264"
        )

    def get_preset(self):
        return (
            self._obj.preset
            if hasattr(self._obj, "preset") and self._obj.preset
            else "medium"
        )

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
