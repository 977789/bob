#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# (c) Modified by SilentDemonSD
# This module helps in modifying media metadata using FFmpeg

import asyncio
import logging
import os
import re
from typing import Dict, List, Optional, Union
from urllib.parse import unquote_plus

from bot import LOGGER


async def get_metadata(file_path: str) -> Dict:
    """Get metadata of a media file using FFmpeg"""
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        file_path,
    ]
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        LOGGER.error(f"Error getting metadata: {stderr.decode()}")
        return {}

    import json

    try:
        return json.loads(stdout.decode())
    except json.JSONDecodeError:
        LOGGER.error("Failed to parse metadata JSON")
        return {}


async def set_metadata(file_path: str, metadata: Dict, progress_callback=None) -> str:
    """
    Set metadata for a media file using FFmpeg
    Returns the path of the new file with metadata
    Accepts an optional progress_callback(percent: int) for progress tracking.
    """
    LOGGER.info(f"Setting metadata for {os.path.basename(file_path)}")

    # Get file extension and create output path
    file_dir = os.path.dirname(file_path)
    file_name = os.path.basename(file_path)
    file_base, file_ext = os.path.splitext(file_name)
    output_path = os.path.join(file_dir, f"{file_base}_metadata{file_ext}")

    # Get streams info to set stream-specific metadata
    streams_info = await get_metadata(file_path)

    # Build FFmpeg command
    cmd = ["ffmpeg", "-i", file_path]

    # Enhanced global metadata fields with language support
    global_fields = [
        "title",
        "artist",
        "album",
        "genre",
        "date",
        "comment",
        "copyright",
        "description",
        "album_artist",
        "composer",
        "year",
        "track",
        "disc",
        "publisher",
        "encoded_by",
        "website",
        "rating",
        "bpm",
        "mood",
        "compilation",
        "grouping",
        "subtitle",
        "orchestra",
        "conductor",
        "remixer",
        "arranger",
        "original_artist",
    ]

    # Language-specific metadata fields (ISO 639-2 language codes)
    language_fields = ["title", "description", "subtitle"]
    stream_specific = {}

    for key, value in metadata.items():
        # Handle special stream-specific metadata
        if key == "video_title":
            # Apply this title to all video streams
            stream_specific.setdefault("video", {}).setdefault("all", []).append(
                ("title", value)
            )
        elif key == "audio_title":
            # Apply this title to all audio streams
            stream_specific.setdefault("audio", {}).setdefault("all", []).append(
                ("title", value)
            )
        elif key == "subtitle_title":
            # Apply this title to all subtitle streams
            stream_specific.setdefault("subtitle", {}).setdefault("all", []).append(
                ("title", value)
            )
        elif key.startswith("audio_title:"):
            stream_index = key.split(":")[1] if ":" in key else "0"
            stream_specific.setdefault("audio", {}).setdefault(stream_index, []).append(
                ("title", value)
            )
        elif key.startswith("video_title:"):
            stream_index = key.split(":")[1] if ":" in key else "0"
            stream_specific.setdefault("video", {}).setdefault(stream_index, []).append(
                ("title", value)
            )
        elif key.startswith("subtitle_title:"):
            stream_index = key.split(":")[1] if ":" in key else "0"
            stream_specific.setdefault("subtitle", {}).setdefault(
                stream_index, []
            ).append(("title", value))
        elif ":" in key and key.split(":")[0] in language_fields:
            # Handle language-specific metadata (e.g., "title:eng=English Title")
            field, lang = key.split(":")
            if len(lang) == 3:  # ISO 639-2 language code
                cmd.extend(["-metadata", f"{field}-{lang}={value}"])
            else:
                # Treat as a global metadata
                cmd.extend(["-metadata", f"{key}={value}"])
        elif key in global_fields:
            cmd.extend(["-metadata", f"{key}={value}"])
        else:
            # Treat as a global metadata
            cmd.extend(["-metadata", f"{key}={value}"])

    # Add stream-specific metadata
    stream_index_map = {"audio": {}, "video": {}, "subtitle": {}}

    if "streams" in streams_info:
        for i, stream in enumerate(streams_info["streams"]):
            codec_type = stream.get("codec_type")
            if codec_type in ["audio", "video", "subtitle"]:
                relative_index = stream_index_map.setdefault(codec_type, {}).get(
                    "count", 0
                )
                stream_index_map[codec_type]["count"] = relative_index + 1
                stream_index_map[codec_type][str(relative_index)] = i
    # Apply stream-specific metadata
    for stream_type, indexes in stream_specific.items():
        for rel_index, metadata_list in indexes.items():
            if rel_index == "all":
                # Apply to all streams of this type
                for i in range(stream_index_map.get(stream_type, {}).get("count", 0)):
                    if str(i) in stream_index_map.get(stream_type, {}):
                        abs_index = stream_index_map[stream_type][str(i)]
                        for key, value in metadata_list:
                            cmd.extend([f"-metadata:s:{abs_index}", f"{key}={value}"])
            elif rel_index in stream_index_map.get(stream_type, {}):
                abs_index = stream_index_map[stream_type][rel_index]
                for key, value in metadata_list:
                    cmd.extend([f"-metadata:s:{abs_index}", f"{key}={value}"])
    # Map all streams and copy without re-encoding
    cmd.extend(["-map", "0", "-c", "copy", output_path])
    # Run FFmpeg process
    LOGGER.info(f"Running FFmpeg command: {' '.join(cmd)}")
    LOGGER.info(
        f"Source file has {stream_index_map.get('video', {}).get('count', 0)} video, {stream_index_map.get('audio', {}).get('count', 0)} audio, and {stream_index_map.get('subtitle', {}).get('count', 0)} subtitle streams"
    )
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    total_size = os.path.getsize(file_path)
    processed = 0
    percent = 0
    # Read stderr in real time for progress
    while True:
        line = await process.stderr.readline()
        if not line:
            break
        decoded = line.decode(errors="ignore")
        # Try to estimate progress by output file size
        if os.path.exists(output_path):
            processed = os.path.getsize(output_path)
            percent = min(100, int(processed / total_size * 100))
            if progress_callback:
                progress_callback(percent)

    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        LOGGER.error(f"Error setting metadata: {stderr.decode(errors='ignore')}")
        # Verify output file
        if os.path.exists(output_path):
            # Check if output file has correct streams
            output_metadata = await get_metadata(output_path)
            stream_counts = {"video": 0, "audio": 0, "subtitle": 0}
            if "streams" in output_metadata:
                for stream in output_metadata.get("streams", []):
                    codec_type = stream.get("codec_type")
                    if codec_type in stream_counts:
                        stream_counts[codec_type] += 1
            LOGGER.error(f"Output file stream counts: {stream_counts}")
            os.remove(output_path)
        return file_path
    LOGGER.info(f"Successfully set metadata for {file_name}")
    if progress_callback:
        progress_callback(100)
    return output_path


async def apply_metadata(
    file_path: str, metadata_settings: Dict, progress_callback=None
) -> str:
    """
    Apply metadata settings to a media file
    Returns the path of the file with applied metadata
    Accepts an optional progress_callback(percent: int) for progress tracking.
    """
    # Check if file exists
    if not os.path.exists(file_path):
        LOGGER.error(f"File not found: {file_path}")
        return file_path

    # Check if file is media type
    media_extensions = [".mp4", ".mkv", ".avi", ".mp3", ".m4a", ".flac", ".ogg", ".wav"]
    if not any(file_path.lower().endswith(ext) for ext in media_extensions):
        LOGGER.info(f"Not a supported media file for metadata: {file_path}")
        return file_path

    # Apply metadata and return new file path
    try:
        new_path = await set_metadata(
            file_path, metadata_settings, progress_callback=progress_callback
        )
        if (
            new_path != file_path
            and os.path.exists(new_path)
            and os.path.exists(file_path)
        ):
            os.remove(file_path)
            # Rename new file to original name
            final_path = file_path
            os.rename(new_path, final_path)
            if progress_callback:
                progress_callback(100)
            return final_path
        if progress_callback:
            progress_callback(100)
        return new_path
    except Exception as e:
        LOGGER.error(f"Error applying metadata: {e}")
        if progress_callback:
            progress_callback(0)
        return file_path


async def embed_cover_art(file_path: str, image_path: str) -> str:
    """Embed an image as cover art so players like VLC show it as a thumbnail.

    Behavior:
    - Works for common audio (mp3, m4a, flac, ogg, wav) and video (mp4, mkv, mov, avi) containers.
    - Adds the image as an attached picture stream without re-encoding existing streams.
    - Preserves ALL streams (video, audio, subtitle), chapters, metadata, and dispositions.
    - Replaces the original file on success and returns the final path (same as input path).
    - On failure, returns the original path unchanged.
    """
    try:
        if not os.path.exists(file_path) or not os.path.exists(image_path):
            return file_path

        # Only attempt on common media containers
        supported_exts = {
            ".mp3",
            ".m4a",
            ".flac",
            ".ogg",
            ".wav",
            ".mp4",
            ".mkv",
            ".mov",
            ".avi",
        }
        _, ext = os.path.splitext(file_path)
        ext = ext.lower()
        if ext not in supported_exts:
            return file_path

        # Get metadata to understand the stream structure
        meta = await get_metadata(file_path)
        if not meta or "streams" not in meta:
            return file_path

        video_count = 0
        audio_count = 0
        subtitle_count = 0
        attachment_count = 0
        data_streams = 0

        for s in meta["streams"]:
            codec_type = s.get("codec_type", "")
            if codec_type == "video":
                video_count += 1
            elif codec_type == "audio":
                audio_count += 1
            elif codec_type == "subtitle":
                subtitle_count += 1
            elif codec_type == "attachment":
                attachment_count += 1
            elif codec_type == "data":
                data_streams += 1

        LOGGER.info(
            f"Source streams: {video_count} video, {audio_count} audio, {subtitle_count} subtitle, {attachment_count} attachments, {data_streams} data"
        )

        # Build output temp path
        file_dir = os.path.dirname(file_path)
        file_name = os.path.basename(file_path)
        file_base, file_ext = os.path.splitext(file_name)
        output_path = os.path.join(file_dir, f"{file_base}_cover{file_ext}")

        # Container-specific embedding
        if ext == ".mkv":
            # Matroska supports attachments; use -attach and set mimetype/filename
            import mimetypes

            mime = mimetypes.guess_type(image_path)[0] or "image/jpeg"
            filename = os.path.basename(image_path)
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                file_path,
                "-attach",
                image_path,
                "-metadata:s:t",
                f"mimetype={mime}",
                "-metadata:s:t",
                f"filename={filename}",
                "-map",
                "0",  # Map all streams from original
                "-c",
                "copy",  # Copy without re-encoding
                "-map_metadata",
                "0",  # Copy global metadata
                "-map_chapters",
                "0",  # Preserve chapters
                output_path,
            ]
        else:
            # Generic approach: add image as attached_pic stream while preserving everything
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                file_path,
                "-i",
                image_path,
                "-map",
                "0",  # Map all streams from first input (original file)
                "-map",
                "1:0",  # Map image from second input
                "-c",
                "copy",  # Copy all streams without re-encoding
                "-map_metadata",
                "0",  # Copy global metadata from original
                "-map_chapters",
                "0",  # Preserve chapters if any
            ]

            # Copy all stream-level metadata and dispositions from original streams
            for i, stream in enumerate(meta.get("streams", [])):
                cmd.extend([f"-map_metadata:s:{i}", f"0:s:{i}"])
                # Preserve disposition flags
                disposition = stream.get("disposition", {})
                for key, value in disposition.items():
                    if value:
                        cmd.extend([f"-disposition:s:{i}", key])

            # Set the newly added image stream as attached picture
            cover_stream_index = len(
                meta.get("streams", [])
            )  # Index of the new cover image stream
            cmd.extend(
                [
                    f"-disposition:s:{cover_stream_index}",
                    "attached_pic",
                    f"-metadata:s:{cover_stream_index}",
                    "title=Cover",
                    f"-metadata:s:{cover_stream_index}",
                    "comment=Cover (front)",
                ]
            )

            # For MP3, ensure ID3v2.3 so cover art is recognized widely
            if ext == ".mp3":
                cmd.extend(["-id3v2_version", "3"])

            cmd.append(output_path)

        LOGGER.info(f"Embedding cover art into {file_name}")
        LOGGER.debug(f"FFmpeg command: {' '.join(cmd)}")

        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()

        if process.returncode != 0 or not os.path.exists(output_path):
            LOGGER.error(
                f"Failed to embed cover art for {file_name}: {stderr.decode(errors='ignore')}"
            )
            # Cleanup if partially created
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except Exception:
                    pass
            return file_path

        # Verify that all streams are preserved in output
        output_meta = await get_metadata(output_path)
        if output_meta and "streams" in output_meta:
            out_video = out_audio = out_subtitle = out_attachment = out_data = 0
            for s in output_meta["streams"]:
                codec_type = s.get("codec_type", "")
                if codec_type == "video":
                    out_video += 1
                elif codec_type == "audio":
                    out_audio += 1
                elif codec_type == "subtitle":
                    out_subtitle += 1
                elif codec_type == "attachment":
                    out_attachment += 1
                elif codec_type == "data":
                    out_data += 1

            LOGGER.info(
                f"Output streams: {out_video} video, {out_audio} audio, {out_subtitle} subtitle, {out_attachment} attachments, {out_data} data"
            )

            # Check if we lost any streams (allowing for +1 video for cover art in non-mkv containers)
            expected_video = video_count + (
                0 if ext == ".mkv" else 1
            )  # +1 for attached_pic in non-mkv
            if (
                out_video < expected_video
                or out_audio < audio_count
                or out_subtitle < subtitle_count
                or out_data < data_streams
            ):
                LOGGER.warning(
                    f"Stream count mismatch! Expected: {expected_video}v {audio_count}a {subtitle_count}s {data_streams}d, Got: {out_video}v {out_audio}a {out_subtitle}s {out_data}d"
                )

        # Replace original file atomically
        try:
            os.remove(file_path)
            os.rename(output_path, file_path)
        except Exception as e:
            LOGGER.error(
                f"Failed to replace original with covered file for {file_name}: {e}"
            )
            # If rename failed, keep the original
            try:
                if os.path.exists(output_path):
                    os.remove(output_path)
            except Exception:
                pass
            return file_path

        return file_path
    except Exception as e:
        LOGGER.error(f"Unexpected error embedding cover art: {e}")
        return file_path
