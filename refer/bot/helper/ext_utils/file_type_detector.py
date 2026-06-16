"""
Enhanced file type detection utility for video, audio, and other media files.
Handles case-insensitive extensions, files without extensions, and uses ffprobe for robust detection.
"""

import asyncio
import json
import mimetypes
from os import path as ospath
from typing import Tuple, List, Optional, Set

from ... import LOGGER
from .bot_utils import sync_to_async, cmd_exec


class FileTypeDetector:
    """Enhanced file type detection with support for various scenarios"""

    # Comprehensive video extensions (case will be handled automatically)
    VIDEO_EXTENSIONS = {
        ".mp4",
        ".mkv",
        ".avi",
        ".webm",
        ".wmv",
        ".mov",
        ".flv",
        ".m4v",
        ".mpg",
        ".mpeg",
        ".3gp",
        ".ts",
        ".vob",
        ".asf",
        ".rm",
        ".rmvb",
        ".divx",
        ".xvid",
        ".f4v",
        ".mts",
        ".m2ts",
        ".ogv",
        ".dv",
        ".mxf",
        ".webm",
        ".y4m",
        ".yuv",
        ".264",
        ".265",
        ".h264",
        ".h265",
        ".hevc",
    }

    # Audio extensions
    AUDIO_EXTENSIONS = {
        ".mp3",
        ".aac",
        ".flac",
        ".wav",
        ".ogg",
        ".opus",
        ".m4a",
        ".wma",
        ".ac3",
        ".dts",
        ".ape",
        ".mka",
        ".amr",
        ".aiff",
        ".au",
        ".ra",
    }

    # Video MIME types
    VIDEO_MIME_TYPES = {
        "video/mp4",
        "video/x-msvideo",
        "video/quicktime",
        "video/x-ms-wmv",
        "video/webm",
        "video/x-flv",
        "video/3gpp",
        "video/mpeg",
        "video/x-matroska",
    }

    # Audio MIME types
    AUDIO_MIME_TYPES = {
        "audio/mpeg",
        "audio/aac",
        "audio/flac",
        "audio/wav",
        "audio/ogg",
        "audio/opus",
        "audio/x-m4a",
        "audio/x-ms-wma",
        "audio/ac3",
    }

    @classmethod
    def normalize_extension(cls, filepath: str) -> str:
        """Get normalized (lowercase) file extension"""
        _, ext = ospath.splitext(filepath)
        return ext.lower()

    @classmethod
    def is_video_by_extension(cls, filepath: str) -> bool:
        """Check if file is video based on extension (case-insensitive)"""
        ext = cls.normalize_extension(filepath)
        return ext in cls.VIDEO_EXTENSIONS

    @classmethod
    def is_audio_by_extension(cls, filepath: str) -> bool:
        """Check if file is audio based on extension (case-insensitive)"""
        ext = cls.normalize_extension(filepath)
        return ext in cls.AUDIO_EXTENSIONS

    @classmethod
    def get_mime_type(cls, filepath: str) -> Optional[str]:
        """Get MIME type of file"""
        try:
            mime_type, _ = mimetypes.guess_type(filepath)
            return mime_type
        except Exception:
            return None

    @classmethod
    def is_video_by_mime(cls, filepath: str) -> bool:
        """Check if file is video based on MIME type"""
        mime_type = cls.get_mime_type(filepath)
        if mime_type:
            return mime_type in cls.VIDEO_MIME_TYPES or mime_type.startswith("video/")
        return False

    @classmethod
    def is_audio_by_mime(cls, filepath: str) -> bool:
        """Check if file is audio based on MIME type"""
        mime_type = cls.get_mime_type(filepath)
        if mime_type:
            return mime_type in cls.AUDIO_MIME_TYPES or mime_type.startswith("audio/")
        return False

    @classmethod
    async def probe_file_with_ffprobe(cls, filepath: str) -> Tuple[bool, bool, dict]:
        """
        Use ffprobe to analyze file and determine if it's video/audio
        Returns: (is_video, is_audio, stream_info)
        """
        try:
            cmd = [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                "-show_format",
                filepath,
            ]

            result = await cmd_exec(cmd, shell=False)
            if result[2] != 0:  # Non-zero return code
                return False, False, {}

            probe_data = json.loads(result[0])
            streams = probe_data.get("streams", [])

            is_video = False
            is_audio = False
            stream_info = {
                "video_streams": [],
                "audio_streams": [],
                "other_streams": [],
            }

            for stream in streams:
                codec_type = stream.get("codec_type", "").lower()
                codec_name = stream.get("codec_name", "").lower()

                if codec_type == "video":
                    # Exclude image codecs that might be in video containers
                    if codec_name not in {"mjpeg", "png", "bmp", "gif"}:
                        is_video = True
                        stream_info["video_streams"].append(
                            {
                                "codec": codec_name,
                                "width": stream.get("width", 0),
                                "height": stream.get("height", 0),
                            }
                        )
                elif codec_type == "audio":
                    is_audio = True
                    stream_info["audio_streams"].append(
                        {
                            "codec": codec_name,
                            "channels": stream.get("channels", 0),
                            "sample_rate": stream.get("sample_rate", 0),
                        }
                    )
                else:
                    stream_info["other_streams"].append(
                        {"type": codec_type, "codec": codec_name}
                    )

            return is_video, is_audio, stream_info

        except Exception as e:
            LOGGER.debug(f"FFprobe analysis failed for {filepath}: {e}")
            return False, False, {}

    @classmethod
    async def detect_file_type(
        cls, filepath: str, use_ffprobe: bool = True
    ) -> Tuple[bool, bool, dict]:
        """
        Comprehensive file type detection
        Args:
            filepath: Path to the file
            use_ffprobe: Whether to use ffprobe for deep analysis (slower but more accurate)

        Returns:
            Tuple of (is_video, is_audio, detailed_info)
        """
        # Quick check by extension first
        is_video_ext = cls.is_video_by_extension(filepath)
        is_audio_ext = cls.is_audio_by_extension(filepath)

        # If extension gives clear result and we don't need deep analysis
        if not use_ffprobe and (is_video_ext or is_audio_ext):
            return is_video_ext, is_audio_ext, {"detection_method": "extension"}

        # Check MIME type
        is_video_mime = cls.is_video_by_mime(filepath)
        is_audio_mime = cls.is_audio_by_mime(filepath)

        # If we have a file without extension or conflicting information, use ffprobe
        has_extension = bool(cls.normalize_extension(filepath))
        needs_deep_check = (
            not has_extension  # No extension
            or use_ffprobe  # Forced deep check
            or (
                not is_video_ext
                and not is_audio_ext
                and (is_video_mime or is_audio_mime)
            )  # MIME suggests media but extension doesn't
        )

        if needs_deep_check:
            try:
                (
                    is_video_probe,
                    is_audio_probe,
                    stream_info,
                ) = await cls.probe_file_with_ffprobe(filepath)

                # Combine results (ffprobe has highest priority)
                final_is_video = is_video_probe or (is_video_ext and not is_audio_probe)
                final_is_audio = is_audio_probe or (is_audio_ext and not is_video_probe)

                stream_info.update(
                    {
                        "detection_method": "ffprobe",
                        "extension_match": {
                            "video": is_video_ext,
                            "audio": is_audio_ext,
                        },
                        "mime_match": {"video": is_video_mime, "audio": is_audio_mime},
                    }
                )

                return final_is_video, final_is_audio, stream_info

            except Exception as e:
                LOGGER.debug(f"Deep file analysis failed for {filepath}: {e}")

        # Fallback to extension and MIME type
        final_is_video = is_video_ext or is_video_mime
        final_is_audio = is_audio_ext or is_audio_mime

        return (
            final_is_video,
            final_is_audio,
            {
                "detection_method": "extension_mime",
                "extension_match": {"video": is_video_ext, "audio": is_audio_ext},
                "mime_match": {"video": is_video_mime, "audio": is_audio_mime},
            },
        )

    @classmethod
    async def is_video_file(cls, filepath: str, deep_check: bool = False) -> bool:
        """
        Check if file is a video file
        Args:
            filepath: Path to the file
            deep_check: Use ffprobe for accurate detection (slower)
        """
        is_video, _, _ = await cls.detect_file_type(filepath, use_ffprobe=deep_check)
        return is_video

    @classmethod
    async def is_audio_file(cls, filepath: str, deep_check: bool = False) -> bool:
        """
        Check if file is an audio file
        Args:
            filepath: Path to the file
            deep_check: Use ffprobe for accurate detection (slower)
        """
        _, is_audio, _ = await cls.detect_file_type(filepath, use_ffprobe=deep_check)
        return is_audio

    @classmethod
    def get_all_video_extensions(cls) -> Set[str]:
        """Get all supported video extensions (lowercase)"""
        return cls.VIDEO_EXTENSIONS.copy()

    @classmethod
    def get_all_audio_extensions(cls) -> Set[str]:
        """Get all supported audio extensions (lowercase)"""
        return cls.AUDIO_EXTENSIONS.copy()

    @classmethod
    def add_video_extension(cls, extension: str) -> None:
        """Add a new video extension to the detection list"""
        ext = extension.lower()
        if not ext.startswith("."):
            ext = "." + ext
        cls.VIDEO_EXTENSIONS.add(ext)

    @classmethod
    def add_audio_extension(cls, extension: str) -> None:
        """Add a new audio extension to the detection list"""
        ext = extension.lower()
        if not ext.startswith("."):
            ext = "." + ext
        cls.AUDIO_EXTENSIONS.add(ext)


# Convenience functions for backward compatibility
async def is_video_file(filepath: str, deep_check: bool = False) -> bool:
    """Check if file is a video file"""
    return await FileTypeDetector.is_video_file(filepath, deep_check)


async def is_audio_file(filepath: str, deep_check: bool = False) -> bool:
    """Check if file is an audio file"""
    return await FileTypeDetector.is_audio_file(filepath, deep_check)


async def detect_media_type(
    filepath: str, use_ffprobe: bool = True
) -> Tuple[bool, bool, dict]:
    """Detect if file is video and/or audio with detailed information"""
    return await FileTypeDetector.detect_file_type(filepath, use_ffprobe)


# Export the updated VIDEO_SUFFIXES for backward compatibility
VIDEO_SUFFIXES = tuple(FileTypeDetector.get_all_video_extensions())
AUDIO_SUFFIXES = tuple(FileTypeDetector.get_all_audio_extensions())
