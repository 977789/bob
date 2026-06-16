"""
Utility functions for video processing with enhanced error handling and resource management.
"""

import asyncio
import os
import resource
import tempfile
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
from asyncio import create_subprocess_exec
from asyncio.subprocess import Process, PIPE

from bot import LOGGER
from bot.core.config_manager import BinConfig, Config

# Supported video and subtitle formats
SUPPORTED_VIDEO_FORMATS = {
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".wmv",
    ".flv",
    ".webm",
    ".m4v",
    ".3gp",
}
SUPPORTED_SUBTITLE_FORMATS = {
    ".srt",
    ".ass",
    ".ssa",
    ".vtt",
    ".sub",
    ".idx",
    ".sup",
    ".smi",
    ".ttml",
}
TEXT_SUBTITLE_FORMATS = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".smi", ".ttml"}
BITMAP_SUBTITLE_FORMATS = {".idx", ".sup"}

# FFmpeg codec mappings
SUBTITLE_CODEC_MAP = {
    ".srt": "subrip",
    ".ass": "ass",
    ".ssa": "ass",
    ".vtt": "webvtt",
    ".sub": "microdvd",
    ".smi": "sami",
    ".ttml": "ttml",
}


class VideoProcessError(Exception):
    """Base exception for video processing errors."""

    pass


class ValidationError(VideoProcessError):
    """Error during input validation."""

    pass


class EncodingError(VideoProcessError):
    """Error during video encoding."""

    pass


class SubtitleError(VideoProcessError):
    """Error during subtitle processing."""

    pass


def validate_video_file(file_path: str) -> bool:
    """Validate if file is a supported video format."""
    if not os.path.isfile(file_path):
        return False

    ext = Path(file_path).suffix.lower()
    return ext in SUPPORTED_VIDEO_FORMATS


def validate_subtitle_file(file_path: str) -> bool:
    """Validate if file is a supported subtitle format."""
    if not os.path.isfile(file_path):
        return False

    ext = Path(file_path).suffix.lower()
    return ext in SUPPORTED_SUBTITLE_FORMATS


def is_text_subtitle(file_path: str) -> bool:
    """Check if subtitle file is text-based (not bitmap)."""
    ext = Path(file_path).suffix.lower()
    return ext in TEXT_SUBTITLE_FORMATS


def escape_ffmpeg_path(path: str) -> str:
    """Safely escape file path for FFmpeg filters."""
    # Replace problematic characters for FFmpeg filter usage
    escaped = str(path)
    # Handle backslashes (Windows paths)
    escaped = escaped.replace("\\", "\\\\")
    # Handle colons (drive letters, timestamps)
    escaped = escaped.replace(":", "\\:")
    # Handle single quotes
    escaped = escaped.replace("'", "\\'")
    # Handle square brackets
    escaped = escaped.replace("[", "\\[").replace("]", "\\]")
    # Handle comma and semicolon
    escaped = escaped.replace(",", "\\,").replace(";", "\\;")

    return escaped


def get_subtitle_codec(file_path: str) -> Optional[str]:
    """Get appropriate FFmpeg codec for subtitle file."""
    ext = Path(file_path).suffix.lower()
    return SUBTITLE_CODEC_MAP.get(ext)


def generate_unique_filename(
    base_path: str, suffix: str = "", extension: str = ".mkv"
) -> str:
    """Generate unique filename to avoid conflicts."""
    base = Path(base_path)
    stem = base.stem
    parent = base.parent

    counter = 0
    while True:
        if counter == 0:
            filename = f"{stem}{suffix}{extension}"
        else:
            filename = f"{stem}{suffix}_{counter}{extension}"

        full_path = parent / filename
        if not full_path.exists():
            return str(full_path)
        counter += 1


@asynccontextmanager
async def temp_directory():
    """Context manager for temporary directory with guaranteed cleanup."""
    temp_dir = None
    try:
        temp_dir = tempfile.mkdtemp(prefix="video_process_")
        LOGGER.debug(f"Created temporary directory: {temp_dir}")
        yield temp_dir
    finally:
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
                LOGGER.debug(f"Cleaned up temporary directory: {temp_dir}")
            except Exception as e:
                LOGGER.error(f"Failed to clean up temp directory {temp_dir}: {e}")


@asynccontextmanager
async def temp_file(suffix="", prefix="video_process_", dir=None):
    """Context manager for temporary file with guaranteed cleanup."""
    temp_file_path = None
    try:
        fd, temp_file_path = tempfile.mkstemp(suffix=suffix, prefix=prefix, dir=dir)
        os.close(fd)  # Close the file descriptor, we just need the path
        LOGGER.debug(f"Created temporary file: {temp_file_path}")
        yield temp_file_path
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
                LOGGER.debug(f"Cleaned up temporary file: {temp_file_path}")
            except Exception as e:
                LOGGER.error(f"Failed to clean up temp file {temp_file_path}: {e}")


async def run_ffmpeg_command(
    cmd: List[str], timeout: int = 3600, use_resource_manager: bool = True
) -> Tuple[bool, str, str]:
    """
    Run FFmpeg command with proper error handling and logging.

    Returns:
        Tuple of (success, stdout, stderr)
    """
    if use_resource_manager:
        return await resource_manager.run_with_limit(cmd, timeout)

    try:
        LOGGER.debug(f"Running FFmpeg command: {' '.join(cmd)}")

        process = await create_subprocess_exec(
            *cmd,
            stdout=PIPE,
            stderr=PIPE,
            limit=1024 * 1024 * 10,  # 10MB buffer limit
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise EncodingError(f"FFmpeg command timed out after {timeout} seconds")

        stdout_str = stdout.decode("utf-8", errors="ignore")
        stderr_str = stderr.decode("utf-8", errors="ignore")

        success = process.returncode == 0

        if success:
            LOGGER.debug("FFmpeg command completed successfully")
        else:
            LOGGER.error(f"FFmpeg command failed with return code {process.returncode}")
            LOGGER.error(f"FFmpeg stderr: {stderr_str}")

        # Force garbage collection after FFmpeg operation to prevent memory accumulation
        import gc

        gc.collect()

        return success, stdout_str, stderr_str

    except Exception as e:
        LOGGER.error(f"Error running FFmpeg command: {e}")
        # Force cleanup on error too
        import gc

        gc.collect()
        return False, "", str(e)


async def probe_media_file(file_path: str) -> Optional[Dict[str, Any]]:
    """
    Probe media file using ffprobe to get stream information.

    Returns:
        Dictionary with stream information or None if probe fails
    """
    cmd = [
        BinConfig.FFPROBE_NAME,
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        file_path,
    ]

    try:
        process = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            import json

            return json.loads(stdout.decode("utf-8", errors="ignore"))
        else:
            LOGGER.error(
                f"ffprobe failed for {file_path}: {stderr.decode('utf-8', errors='ignore')}"
            )
            return None

    except Exception as e:
        LOGGER.error(f"Error probing media file {file_path}: {e}")
        return None


def validate_encoding_parameters(
    crf: Optional[int] = None,
    bitrate: Optional[int] = None,
    quality: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Validate and normalize encoding parameters.

    Returns:
        Dictionary with validated parameters
    """
    params = {}

    if crf is not None:
        if not isinstance(crf, int) or not (0 <= crf <= 51):
            raise ValidationError(f"CRF must be integer between 0-51, got: {crf}")
        params["crf"] = crf

    if bitrate is not None:
        if not isinstance(bitrate, (int, str)):
            raise ValidationError(
                f"Bitrate must be integer or string, got: {type(bitrate)}"
            )
        if isinstance(bitrate, str):
            # Parse bitrate string (e.g., "1000k", "2M")
            bitrate_str = bitrate.lower().strip()
            if bitrate_str.endswith("k"):
                params["bitrate"] = int(bitrate_str[:-1])
            elif bitrate_str.endswith("m"):
                params["bitrate"] = int(bitrate_str[:-1]) * 1000
            else:
                params["bitrate"] = int(bitrate_str)
        else:
            params["bitrate"] = bitrate

    if quality is not None:
        supported_qualities = ["360p", "480p", "540p", "720p", "1080p"]
        if quality not in supported_qualities:
            raise ValidationError(
                f"Quality must be one of {supported_qualities}, got: {quality}"
            )
        params["quality"] = quality

    return params


def standardize_stream_mapping(
    video_index: int = 0,
    audio_indices: List[int] = None,
    subtitle_indices: List[int] = None,
) -> List[str]:
    """
    Generate standardized stream mapping for FFmpeg.

    Returns:
        List of FFmpeg mapping arguments
    """
    mapping = []

    # Map video stream
    mapping.extend(["-map", f"{video_index}:v?"])

    # Map audio streams
    if audio_indices:
        for i, audio_idx in enumerate(audio_indices):
            mapping.extend(["-map", f"{audio_idx}:a?"])
    else:
        mapping.extend(["-map", f"{video_index}:a?"])

    # Map subtitle streams
    if subtitle_indices:
        for i, sub_idx in enumerate(subtitle_indices):
            mapping.extend(["-map", f"{sub_idx}:s?"])

    return mapping


async def check_ffmpeg_availability() -> bool:
    """Check if FFmpeg is available and working."""
    try:
        process = await create_subprocess_exec(
            BinConfig.FFMPEG_NAME, "-version", stdout=PIPE, stderr=PIPE
        )
        stdout, stderr = await process.communicate()
        return process.returncode == 0
    except Exception:
        return False


class ResourceManager:
    """Enhanced resource manager for video processing operations with CPU and memory optimization."""

    def __init__(self, max_concurrent: int = 2):
        # Use reasonable concurrent processes
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(self.max_concurrent)
        self.active_processes = set()

    def _set_process_limits(self):
        """Set basic process limits without being overly restrictive"""
        try:
            os.setpgrp()  # Create new process group
        except (OSError, ValueError) as e:
            LOGGER.debug(f"Could not set process group: {e}")

    async def run_with_limit(
        self, cmd: List[str], timeout: int = 3600
    ) -> Tuple[bool, str, str]:
        """Run command with enhanced resource limiting and proper cleanup."""
        async with self.semaphore:
            try:
                process = await create_subprocess_exec(
                    *cmd,
                    stdout=PIPE,
                    stderr=PIPE,
                    limit=1024 * 1024 * 10,  # Restore normal 10MB buffer
                    preexec_fn=self._set_process_limits,
                )

                self.active_processes.add(process)

                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(), timeout=timeout
                    )
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
                    return False, "", f"Command timed out after {timeout} seconds"
                finally:
                    self.active_processes.discard(process)
                    # Force cleanup after process completion
                    gc.collect()

                stdout_str = stdout.decode("utf-8", errors="ignore")
                stderr_str = stderr.decode("utf-8", errors="ignore")
                success = process.returncode == 0

                return success, stdout_str, stderr_str

            except Exception as e:
                return False, "", str(e)

    async def cleanup(self):
        """Clean up any remaining processes."""
        for process in self.active_processes.copy():
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass
        self.active_processes.clear()


async def cleanup_temp_files(*file_paths):
    """Clean up temporary files with error handling."""
    for file_path in file_paths:
        if file_path and os.path.exists(file_path):
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
                    LOGGER.debug(f"Cleaned up temporary file: {file_path}")
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
                    LOGGER.debug(f"Cleaned up temporary directory: {file_path}")
            except Exception as e:
                LOGGER.warning(f"Failed to clean up {file_path}: {e}")


async def ensure_output_cleanup(output_path: str, success: bool):
    """Clean up output file if operation failed."""
    if not success and output_path and os.path.exists(output_path):
        try:
            # Check if file is empty or corrupted
            if os.path.getsize(output_path) == 0:
                os.unlink(output_path)
                LOGGER.debug(f"Cleaned up empty output file: {output_path}")
            else:
                LOGGER.info(f"Keeping partial output file for debugging: {output_path}")
        except Exception as e:
            LOGGER.warning(f"Error during output cleanup: {e}")


def create_progress_callback(listener=None):
    """Create a progress callback function for FFmpeg operations."""

    def progress_callback(current, total=None):
        if listener and hasattr(listener, "on_progress"):
            try:
                if total:
                    percentage = (current / total) * 100
                    listener.on_progress(percentage)
                else:
                    listener.on_progress(current)
            except Exception as e:
                LOGGER.debug(f"Progress callback error: {e}")

    return progress_callback


# Subtitle color analysis functions
def analyze_subtitle_colors(subtitle_content: str, subtitle_format: str) -> List[str]:
    """
    Analyze colors present in subtitle content.

    Args:
        subtitle_content: The content of the subtitle file
        subtitle_format: Format of the subtitle (srt, ass, vtt, etc.)

    Returns:
        List of colors found in the subtitle
    """
    import re

    colors_found = []

    if subtitle_format.lower() in ["srt", "vtt", "webvtt"]:
        # SRT/VTT format: <font color="color">text</font>
        color_pattern = r'<font\s+color=["\'](.*?)["\']'
        colors_found.extend(re.findall(color_pattern, subtitle_content, re.IGNORECASE))

    elif subtitle_format.lower() in ["ass", "ssa"]:
        # ASS format: {\c&Hcolor&} or {\1c&Hcolor&}
        ass_color_pattern = r"\\[1-4]?c&H([0-9A-Fa-f]{6})&"
        hex_colors = re.findall(ass_color_pattern, subtitle_content)
        colors_found.extend([f"#{color}" for color in hex_colors])

    return colors_found


def has_existing_subtitle_colors(subtitle_file_path: str) -> bool:
    """
    Check if subtitle file has existing color information.

    Args:
        subtitle_file_path: Path to the subtitle file

    Returns:
        True if the subtitle has color information, False otherwise
    """
    try:
        if not os.path.exists(subtitle_file_path):
            return False

        # Get subtitle format from extension
        subtitle_format = os.path.splitext(subtitle_file_path)[1].lower().lstrip(".")

        # Read subtitle content
        with open(subtitle_file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # Analyze colors
        colors = analyze_subtitle_colors(content, subtitle_format)
        return len(colors) > 0

    except Exception as e:
        LOGGER.warning(
            f"Failed to analyze subtitle colors for {subtitle_file_path}: {e}"
        )
        return False


class SafePathHandler:
    """Handle file paths safely across different operating systems."""

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """Sanitize filename using unified approach that preserves spaces."""
        # Import the unified safe filename function to ensure consistency
        from bot.helper.ext_utils.safe_filename import safe_filename

        return safe_filename(filename)

    @staticmethod
    def ensure_directory_exists(file_path: str):
        """Ensure the directory for a file path exists."""
        directory = os.path.dirname(file_path)
        if directory and not os.path.exists(directory):
            try:
                os.makedirs(directory, exist_ok=True)
                LOGGER.debug(f"Created directory: {directory}")
            except Exception as e:
                LOGGER.error(f"Failed to create directory {directory}: {e}")
                raise ValidationError(f"Cannot create output directory: {e}")


# Global safe path handler
path_handler = SafePathHandler()

# Global resource manager instance
resource_manager = ResourceManager(max_concurrent=Config.QUEUE_MEDIA_PROCESSING or 2)
