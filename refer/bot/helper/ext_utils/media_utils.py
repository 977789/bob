from contextlib import suppress
from PIL import Image, ImageDraw, ImageFont
from hashlib import md5
from aiofiles import open as aioopen
from aiofiles.os import remove, path as aiopath, makedirs, listdir
from asyncio import (
    create_subprocess_exec,
    gather,
    wait_for,
    sleep,
)
from asyncio.subprocess import PIPE
from os import path as ospath
from re import search as re_search, escape
from time import time
from aioshutil import rmtree, move
from .file_type_detector import FileTypeDetector, detect_media_type
from langcodes import Language
import tempfile

from ... import LOGGER, cpu_no, DOWNLOAD_DIR
from ...core.config_manager import BinConfig
from .bot_utils import cmd_exec, sync_to_async
from .files_utils import get_mime_type, is_archive, is_archive_split
from .status_utils import time_to_seconds


def get_md5_hash(up_path):
    md5_hash = md5()
    with open(up_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            md5_hash.update(byte_block)
        return md5_hash.hexdigest()


async def create_thumb(msg, _id=""):
    if not _id:
        _id = time()
        path = f"{DOWNLOAD_DIR}thumbnails"
    else:
        path = "thumbnails"
    await makedirs(path, exist_ok=True)
    photo_dir = await msg.download()
    output = ospath.join(path, f"{_id}.jpg")
    await sync_to_async(Image.open(photo_dir).convert("RGB").save, output, "JPEG")
    await remove(photo_dir)
    return output


async def get_media_info(path, extra_info=False):
    try:
        result = await cmd_exec(
            [
                "ffprobe",
                "-hide_banner",
                "-loglevel",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                path,
            ]
        )
    except Exception as e:
        LOGGER.error(f"Get Media Info: {e}. Mostly File not found! - File: {path}")
        return (0, "", "", "") if extra_info else (0, None, None)
    if result[0] and result[2] == 0:
        ffresult = eval(result[0])
        fields = ffresult.get("format")
        if fields is None:
            LOGGER.error(f"get_media_info: {result}")
            return (0, "", "", "") if extra_info else (0, None, None)
        duration = round(float(fields.get("duration", 0)))
        if extra_info:
            lang, qual, stitles = "", "", ""
            if (streams := ffresult.get("streams")) and streams[0].get(
                "codec_type"
            ) == "video":
                height = int(streams[0].get("height"))
                # Improved quality detection with better resolution mapping
                if height <= 240:
                    qual = "240p"
                elif height <= 360:
                    qual = "360p"
                elif height <= 480:
                    qual = "480p"
                elif height <= 540:
                    qual = "540p"
                elif height <= 576:
                    qual = "576p"
                elif height <= 720:
                    qual = "720p"
                elif height <= 900:
                    qual = "900p"
                elif height <= 1080:
                    qual = "1080p"
                elif height <= 1440:
                    qual = "1440p"
                elif height <= 2160:
                    qual = "2160p"
                elif height <= 4320:
                    qual = "4320p"
                else:
                    qual = f"{height}p"
                for stream in streams:
                    if stream.get("codec_type") == "audio" and (
                        lc := stream.get("tags", {}).get("language")
                    ):
                        with suppress(Exception):
                            lc = Language.get(lc).display_name()
                        if lc not in lang:
                            lang += f"{lc}, "
                    if stream.get("codec_type") == "subtitle" and (
                        st := stream.get("tags", {}).get("language")
                    ):
                        with suppress(Exception):
                            st = Language.get(st).display_name()
                        if st not in stitles:
                            stitles += f"{st}, "
            return duration, qual, lang[:-2], stitles[:-2]
        tags = fields.get("tags", {})
        artist = tags.get("artist") or tags.get("ARTIST") or tags.get("Artist")
        title = tags.get("title") or tags.get("TITLE") or tags.get("Title")
        return duration, artist, title
    return (0, "", "", "") if extra_info else (0, None, None)


async def get_document_type(path):
    """
    Enhanced document type detection with support for:
    - Case-insensitive file extensions
    - Files without extensions
    - Better video/audio format detection
    """
    is_video, is_audio, is_image = False, False, False

    # Skip archives
    if (
        is_archive(path)
        or is_archive_split(path)
        or re_search(r".+(\.|_)(rar|7z|zip|bin)(\.0*\d+)?$", path)
    ):
        return is_video, is_audio, is_image

    # Check for images first
    mime_type = await sync_to_async(get_mime_type, path)
    if mime_type and mime_type.startswith("image"):
        return False, False, True

    try:
        # Use enhanced file type detection
        is_video, is_audio, detection_info = await detect_media_type(
            path, use_ffprobe=True
        )

        # Log detection method for debugging
        detection_method = detection_info.get("detection_method", "unknown")
        if detection_method == "ffprobe":
            LOGGER.debug(
                f"File type detected via ffprobe: {path} -> video:{is_video}, audio:{is_audio}"
            )
        elif not FileTypeDetector.normalize_extension(path):
            LOGGER.info(
                f"File without extension detected: {path} -> video:{is_video}, audio:{is_audio}"
            )

        return is_video, is_audio, is_image

    except Exception as e:
        LOGGER.debug(f"Enhanced document type detection failed for {path}: {e}")

        # Fallback to original method
        try:
            result = await cmd_exec(
                [
                    "ffprobe",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-print_format",
                    "json",
                    "-show_streams",
                    path,
                ]
            )
            if result[1] and mime_type and mime_type.startswith("video"):
                is_video = True
        except Exception as e2:
            LOGGER.error(
                f"Get Document Type: {e2}. Mostly File not found! - File: {path}"
            )
            if mime_type and mime_type.startswith("audio"):
                return False, True, False
            if not mime_type or (
                not mime_type.startswith("video")
                and not mime_type.endswith("octet-stream")
            ):
                return is_video, is_audio, is_image
            if mime_type.startswith("video"):
                is_video = True
            return is_video, is_audio, is_image

        if result[0] and result[2] == 0:
            fields = eval(result[0]).get("streams")
            if fields is None:
                LOGGER.error(f"get_document_type: {result}")
                return is_video, is_audio, is_image
            is_video = False
            for stream in fields:
                if stream.get("codec_type") == "video":
                    codec_name = stream.get("codec_name", "").lower()
                    if codec_name not in {"mjpeg", "png", "bmp"}:
                        is_video = True
                elif stream.get("codec_type") == "audio":
                    is_audio = True

        return is_video, is_audio, is_image


async def get_document_type_legacy(path):
    """Original get_document_type function kept for backward compatibility"""
    is_video, is_audio, is_image = False, False, False
    if (
        is_archive(path)
        or is_archive_split(path)
        or re_search(r".+(\.|_)(rar|7z|zip|bin)(\.0*\d+)?$", path)
    ):
        return is_video, is_audio, is_image
    mime_type = await sync_to_async(get_mime_type, path)
    if mime_type.startswith("image"):
        return False, False, True
    try:
        result = await cmd_exec(
            [
                "ffprobe",
                "-hide_banner",
                "-loglevel",
                "error",
                "-print_format",
                "json",
                "-show_streams",
                path,
            ]
        )
        if result[1] and mime_type.startswith("video"):
            is_video = True
    except Exception as e:
        LOGGER.error(f"Get Document Type: {e}. Mostly File not found! - File: {path}")
        if mime_type.startswith("audio"):
            return False, True, False
        if not mime_type.startswith("video") and not mime_type.endswith("octet-stream"):
            return is_video, is_audio, is_image
        if mime_type.startswith("video"):
            is_video = True
        return is_video, is_audio, is_image
    if result[0] and result[2] == 0:
        fields = eval(result[0]).get("streams")
        if fields is None:
            LOGGER.error(f"get_document_type: {result}")
            return is_video, is_audio, is_image
        is_video = False
        for stream in fields:
            if stream.get("codec_type") == "video":
                codec_name = stream.get("codec_name", "").lower()
                if codec_name not in {"mjpeg", "png", "bmp"}:
                    is_video = True
            elif stream.get("codec_type") == "audio":
                is_audio = True
    return is_video, is_audio, is_image


async def take_ss(video_file, ss_nb) -> bool:
    duration = (await get_media_info(video_file))[0]
    if duration != 0:
        dirpath, name = video_file.rsplit("/", 1)
        name, _ = ospath.splitext(name)
        dirpath = f"{dirpath}/{name}_mltbss"
        await makedirs(dirpath, exist_ok=True)
        interval = duration // (ss_nb + 1)
        cap_time = interval
        cmds = []
        for i in range(ss_nb):
            output = f"{dirpath}/SS.{name}_{i:02}.png"
            cmd = [
                BinConfig.FFMPEG_NAME,
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{cap_time}",
                "-i",
                video_file,
                "-q:v",
                "1",
                "-frames:v",
                "1",
                "-threads",
                f"{max(1, cpu_no // 2)}",
                output,
            ]
            cap_time += interval
            cmds.append(cmd_exec(cmd))
        try:
            resutls = await wait_for(gather(*cmds), timeout=60)
            if resutls[0][2] != 0:
                LOGGER.error(
                    f"Error while creating sreenshots from video. Path: {video_file}. stderr: {resutls[0][1]}"
                )
                await rmtree(dirpath, ignore_errors=True)
                return False
        except Exception:
            LOGGER.error(
                f"Error while creating sreenshots from video. Path: {video_file}. Error: Timeout some issues with ffmpeg with specific arch!"
            )
            await rmtree(dirpath, ignore_errors=True)
            return False
        return dirpath
    else:
        LOGGER.error("take_ss: Can't get the duration of video")
        return False


async def has_embedded_artwork(audio_file):
    """
    Check if an audio file has embedded artwork/album art

    Args:
        audio_file (str): Path to the audio file

    Returns:
        bool: True if the file has embedded artwork, False otherwise
    """
    try:
        result = await cmd_exec(
            [
                "ffprobe",
                "-hide_banner",
                "-loglevel",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_type",
                "-print_format",
                "csv=p=0",
                audio_file,
            ]
        )
        # If there's a video stream (likely album art), the output will contain 'video'
        if result[0] and result[2] == 0 and "video" in result[0].strip():
            return True
    except Exception as e:
        LOGGER.debug(f"Error checking for embedded artwork in {audio_file}: {e}")
    return False


async def get_audio_thumbnail(audio_file):
    """
    Extract thumbnail/album art from audio file if available

    Args:
        audio_file (str): Path to the audio file

    Returns:
        str or None: Path to extracted thumbnail if successful, None otherwise
    """
    # First check if the audio file has embedded artwork
    if not await has_embedded_artwork(audio_file):
        LOGGER.debug(f"No embedded artwork found in audio file: {audio_file}")
        return None

    output_dir = f"{DOWNLOAD_DIR}thumbnails"
    await makedirs(output_dir, exist_ok=True)
    output = ospath.join(output_dir, f"{time()}.jpg")

    # Updated command to properly extract embedded artwork
    cmd = [
        BinConfig.FFMPEG_NAME,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        audio_file,
        "-an",  # Disable audio
        "-vcodec",
        "mjpeg",  # Use MJPEG codec for JPEG output instead of copy
        "-vframes",
        "1",  # Extract only one frame
        "-q:v",
        "2",  # High quality
        "-threads",
        f"{max(1, cpu_no // 2)}",
        output,
    ]
    try:
        _, err, code = await wait_for(cmd_exec(cmd), timeout=60)
        if code != 0 or not await aiopath.exists(output):
            LOGGER.debug(
                f"Could not extract thumbnail from audio file: {audio_file} - {err if err else 'No embedded artwork'}"
            )
            return None
    except Exception as e:
        LOGGER.debug(
            f"Timeout or error while extracting thumbnail from audio: {audio_file} - {e}"
        )
        return None
    return output


async def get_video_thumbnail(video_file, duration):
    output_dir = f"{DOWNLOAD_DIR}thumbnails"
    # Ensure thumbnails directory exists
    await makedirs(output_dir, exist_ok=True)
    await makedirs(output_dir, exist_ok=True)
    output = ospath.join(output_dir, f"{time()}.jpg")
    if duration is None:
        duration = (await get_media_info(video_file))[0]
    if duration == 0:
        duration = 3
    duration = duration // 2
    cmd = [
        BinConfig.FFMPEG_NAME,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{duration}",
        "-i",
        video_file,
        "-vf",
        "scale=640:-1",
        "-q:v",
        "5",
        "-vframes",
        "1",
        "-threads",
        "1",
        output,
    ]
    try:
        _, err, code = await wait_for(cmd_exec(cmd), timeout=60)
        if code != 0 or not await aiopath.exists(output):
            LOGGER.error(
                f"Error while extracting thumbnail from video. Name: {video_file} stderr: {err}"
            )
            return None
    except Exception:
        LOGGER.error(
            f"Error while extracting thumbnail from video. Name: {video_file}. Error: Timeout some issues with ffmpeg with specific arch!"
        )
        return None
    return output


async def get_multiple_frames_thumbnail(video_file, layout, keep_screenshots):
    ss_nb = layout.split("x")
    ss_nb = int(ss_nb[0]) * int(ss_nb[1])
    dirpath = await take_ss(video_file, ss_nb)
    if not dirpath:
        return None
    output_dir = f"{DOWNLOAD_DIR}thumbnails"
    await makedirs(output_dir, exist_ok=True)
    output = ospath.join(output_dir, f"{time()}.jpg")
    cmd = [
        BinConfig.FFMPEG_NAME,
        "-hide_banner",
        "-loglevel",
        "error",
        "-pattern_type",
        "glob",
        "-i",
        f"{escape(dirpath)}/*.png",
        "-vf",
        f"tile={layout}, thumbnail",
        "-q:v",
        "1",
        "-frames:v",
        "1",
        "-f",
        "mjpeg",
        "-threads",
        f"{max(1, cpu_no // 2)}",
        output,
    ]
    try:
        _, err, code = await wait_for(cmd_exec(cmd), timeout=60)
        if code != 0 or not await aiopath.exists(output):
            LOGGER.error(
                f"Error while combining thumbnails for video. Name: {video_file} stderr: {err}"
            )
            return None
    except Exception:
        LOGGER.error(
            f"Error while combining thumbnails from video. Name: {video_file}. Error: Timeout some issues with ffmpeg with specific arch!"
        )
        return None
    finally:
        if not keep_screenshots:
            await rmtree(dirpath, ignore_errors=True)
    return output


async def get_ss_grid_pdf(
    video_file,
    layout,
    ss_count,
    pdf_mode=False,
    watermark=None,
    pdf_individual_pages=True,
):
    """
    Create a grid of screenshots and optionally combine them into a PDF

    Args:
        video_file: Path to the video file
        layout: Grid layout (e.g., '3x3')
        ss_count: Number of screenshots to take
        pdf_mode: Whether to generate a PDF with all screenshots
        watermark: Optional watermark text for the PDF
        pdf_individual_pages: Whether to include individual screenshots as separate pages in the PDF

    Returns:
        Path to the generated image grid or PDF file, or None if failed
    """
    LOGGER.info(f"Generating SS Grid for: {video_file}")
    LOGGER.info(
        f"SS Grid parameters - Layout: {layout}, Count: {ss_count}, PDF Mode: {pdf_mode}, Watermark: {repr(watermark)}"
    )

    # Validate parameters
    if not ss_count or ss_count <= 0:
        LOGGER.warning(f"Invalid SS Grid count: {ss_count}, defaulting to 9")
        ss_count = 9

    if not layout or "x" not in layout:
        LOGGER.warning(f"Invalid SS Grid layout: {layout}, defaulting to 3x3")
        layout = "3x3"

    # First take the screenshots
    LOGGER.info(f"Taking {ss_count} screenshots for SS Grid...")

    # Validate parameters
    if not ss_count or ss_count <= 0:
        LOGGER.warning(f"Invalid SS Grid count: {ss_count}, defaulting to 9")
        ss_count = 9

    if not layout or "x" not in layout:
        LOGGER.warning(f"Invalid SS Grid layout: {layout}, defaulting to 3x3")
        layout = "3x3"
    dirpath = await take_ss(video_file, ss_count)
    if not dirpath:
        LOGGER.error(f"Failed to take screenshots for SS Grid: {video_file}")
        return None
    LOGGER.info(f"Successfully took screenshots for SS Grid, storing in: {dirpath}")

    # Create output directory
    output_dir = f"{DOWNLOAD_DIR}thumbnails"
    await makedirs(output_dir, exist_ok=True)

    # Create the grid image
    grid_output = ospath.join(output_dir, f"grid_{time()}.jpg")
    grid_cmd = [
        BinConfig.FFMPEG_NAME,
        "-hide_banner",
        "-loglevel",
        "error",
        "-pattern_type",
        "glob",
        "-i",
        f"{escape(dirpath)}/*.png",
        "-vf",
        f"tile={layout}, thumbnail",
        "-q:v",
        "1",
        "-frames:v",
        "1",
        "-f",
        "mjpeg",
        "-threads",
        f"{max(1, cpu_no // 2)}",
        grid_output,
    ]

    try:
        _, err, code = await wait_for(cmd_exec(grid_cmd), timeout=60)
        if code != 0 or not await aiopath.exists(grid_output):
            LOGGER.error(
                f"Error while creating grid image. Name: {video_file} stderr: {err}"
            )
            await rmtree(dirpath, ignore_errors=True)
            return None

        if not pdf_mode:
            # If PDF mode is not enabled, return the grid image
            await rmtree(dirpath, ignore_errors=True)
            return grid_output

        # If PDF mode is enabled, create a PDF with all screenshots
        try:
            from PIL import Image, ImageDraw, ImageFont
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas
            import tempfile

            # Create a PDF with all screenshots
            pdf_output = ospath.join(output_dir, f"screenshots_{time()}.pdf")
            # Get list of all screenshot files
            screenshot_files = await listdir(dirpath)
            screenshot_files = sorted(
                [f for f in screenshot_files if f.endswith(".png")]
            )
            screenshots = [ospath.join(dirpath, file) for file in screenshot_files]

            # Downscale factor for memory efficiency
            DOWNSCALE_MAX_WIDTH = 1280
            DOWNSCALE_MAX_HEIGHT = 720

            async def create_pdf():
                def _create_pdf():
                    # Use 16:9 aspect ratio (1920x1080 points)
                    PAGE_WIDTH = 1920
                    PAGE_HEIGHT = 1080
                    c = canvas.Canvas(pdf_output, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
                    width, height = PAGE_WIDTH, PAGE_HEIGHT
                    # Add grid image as first page
                    img = Image.open(grid_output)
                    img_width, img_height = img.size
                    ratio = min(
                        width / img_width, height / img_height
                    )  # 100% of page size
                    new_width, new_height = (
                        int(img_width * ratio),
                        int(img_height * ratio),
                    )
                    x_offset = (width - new_width) / 2
                    y_offset = (height - new_height) / 2
                    # Set black background
                    c.setFillColorRGB(0, 0, 0)
                    c.rect(0, 0, width, height, fill=1, stroke=0)
                    c.drawImage(
                        grid_output,
                        x_offset,
                        y_offset,
                        width=new_width,
                        height=new_height,
                    )
                    # Draw filename in top-left corner (on image) with small font and black outline
                    import os

                    file_title = os.path.basename(video_file)
                    font_size = 36
                    text_x = x_offset + 30
                    text_y = y_offset + new_height - 50  # 50px from top of image
                    c.setFont("Helvetica-Bold", font_size)
                    # Draw black outline (multiple offsets)
                    for dx, dy in [
                        (-2, 0),
                        (2, 0),
                        (0, -2),
                        (0, 2),
                        (-2, -2),
                        (2, 2),
                        (-2, 2),
                        (2, -2),
                    ]:
                        c.setFillColorRGB(0, 0, 0)
                        c.drawString(text_x + dx, text_y + dy, file_title)
                    # Draw main white text
                    c.setFillColorRGB(1, 1, 1)
                    c.drawString(text_x, text_y, file_title)
                    if watermark:
                        c.saveState()
                        c.setFont("Helvetica", 48)
                        c.setFillColorRGB(0.5, 0.5, 0.5, 0.3)
                        c.translate(width / 2, height / 2)
                        c.rotate(45)
                        c.drawCentredString(0, 0, watermark)
                        c.restoreState()
                    c.showPage()
                    img.close()
                    # Add individual screenshots if enabled
                    if pdf_individual_pages:
                        for screenshot in screenshots:
                            img = Image.open(screenshot)
                            # Downscale if needed
                            if (
                                img.width > DOWNSCALE_MAX_WIDTH
                                or img.height > DOWNSCALE_MAX_HEIGHT
                            ):
                                img.thumbnail(
                                    (DOWNSCALE_MAX_WIDTH, DOWNSCALE_MAX_HEIGHT),
                                    Image.LANCZOS,
                                )
                                img.save(screenshot)
                            img_width, img_height = img.size
                            ratio = min(width / img_width, height / img_height)
                            new_width, new_height = (
                                int(img_width * ratio),
                                int(img_height * ratio),
                            )
                            x_offset = (width - new_width) / 2
                            y_offset = (height - new_height) / 2
                            c.setFillColorRGB(0, 0, 0)
                            c.rect(0, 0, width, height, fill=1, stroke=0)
                            c.drawImage(
                                screenshot,
                                x_offset,
                                y_offset,
                                width=new_width,
                                height=new_height,
                            )
                            if watermark:
                                c.saveState()
                                c.setFont("Helvetica", 48)
                                c.setFillColorRGB(0.5, 0.5, 0.5, 0.3)
                                c.translate(width / 2, height / 2)
                                c.rotate(45)
                                c.drawCentredString(0, 0, watermark)
                                c.restoreState()
                            c.showPage()
                            img.close()
                    c.save()
                    return True

                return await sync_to_async(_create_pdf)

            pdf_created = await create_pdf()
            if not pdf_created:
                LOGGER.error("Failed to create PDF")
                await rmtree(dirpath, ignore_errors=True)
                if await aiopath.exists(grid_output):
                    await remove(grid_output)
                return grid_output
            # Clean up temporary files
            await rmtree(dirpath, ignore_errors=True)
            if await aiopath.exists(grid_output):
                await remove(grid_output)
            return pdf_output
        except ImportError:
            LOGGER.error(
                "Required libraries for PDF creation not available. Returning grid image instead."
            )
            await rmtree(dirpath, ignore_errors=True)
            return grid_output
        except Exception as e:
            LOGGER.error(f"Error creating PDF in SS Grid: {str(e)}")
            await rmtree(dirpath, ignore_errors=True)
            return grid_output
    except Exception as e:
        LOGGER.error(f"Error while creating SS Grid: {str(e)}")
        if await aiopath.exists(dirpath):
            await rmtree(dirpath, ignore_errors=True)
        return None


class FFMpeg:
    def __init__(self, listener):
        self._listener = listener
        self._processed_bytes = 0
        self._last_processed_bytes = 0
        self._processed_time = 0
        self._last_processed_time = 0
        self._speed_raw = 0
        self._progress_raw = 0
        self._total_time = 0
        self._eta_raw = 0
        self._time_rate = 0.1
        self._start_time = 0

    @property
    def processed_bytes(self):
        return self._processed_bytes

    @property
    def speed_raw(self):
        return self._speed_raw

    @property
    def progress_raw(self):
        return self._progress_raw

    @property
    def eta_raw(self):
        return self._eta_raw

    def clear(self):
        self._start_time = time()
        self._processed_bytes = 0
        self._processed_time = 0
        self._speed_raw = 0
        self._progress_raw = 0
        self._eta_raw = 0
        self._time_rate = 0.1
        self._last_processed_time = 0
        self._last_processed_bytes = 0

    async def _ffmpeg_progress(self):
        while not (
            self._listener.subproc.returncode is not None
            or self._listener.is_cancelled
            or self._listener.subproc.stdout.at_eof()
        ):
            try:
                line = await wait_for(self._listener.subproc.stdout.readline(), 60)
            except Exception:
                break
            line = line.decode().strip()
            if not line:
                break
            if "=" in line:
                key, value = line.split("=", 1)
                if value != "N/A":
                    if key == "total_size":
                        self._processed_bytes = int(value) + self._last_processed_bytes
                        self._speed_raw = self._processed_bytes / (
                            time() - self._start_time
                        )
                    elif key == "speed":
                        self._time_rate = max(0.1, float(value.strip("x")))
                    elif key == "out_time":
                        self._processed_time = (
                            time_to_seconds(value) + self._last_processed_time
                        )
                        try:
                            self._progress_raw = (
                                self._processed_time * 100
                            ) / self._total_time
                            self._eta_raw = (
                                self._total_time - self._processed_time
                            ) / self._time_rate
                        except ZeroDivisionError:
                            self._progress_raw = 0
                            self._eta_raw = 0
            await sleep(0.05)

    async def ffmpeg_cmds(self, ffmpeg, f_path):
        self.clear()
        self._total_time = (await get_media_info(f_path))[0]
        base_name, ext = ospath.splitext(f_path)
        dir, base_name = base_name.rsplit("/", 1)
        indices = [
            index
            for index, item in enumerate(ffmpeg)
            if item.startswith("mltb") or item == "mltb"
        ]
        outputs = []
        for index in indices:
            output_file = ffmpeg[index]
            if output_file != "mltb" and output_file.startswith("mltb"):
                bo, oext = ospath.splitext(output_file)
                if oext:
                    if ext == oext:
                        prefix = f"ffmpeg{index}." if bo == "mltb" else ""
                    else:
                        prefix = ""
                    ext = ""
                else:
                    prefix = ""
            else:
                prefix = f"ffmpeg{index}."
            output = f"{dir}/{prefix}{output_file.replace('mltb', base_name)}{ext}"
            outputs.append(output)
            ffmpeg[index] = output
        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await create_subprocess_exec(
            *ffmpeg, stdout=PIPE, stderr=PIPE
        )
        await self._ffmpeg_progress()
        _, stderr = await self._listener.subproc.communicate()
        code = self._listener.subproc.returncode
        if self._listener.is_cancelled:
            return False
        if code == 0:
            return outputs
        elif code == -9:
            self._listener.is_cancelled = True
            return False
        else:
            try:
                stderr = stderr.decode().strip()
            except Exception:
                stderr = "Unable to decode the error!"
            LOGGER.error(
                f"{stderr}. Something went wrong while running ffmpeg cmd, mostly file requires different/specific arguments. Path: {f_path}"
            )
            for op in outputs:
                if await aiopath.exists(op):
                    await remove(op)
            return False

    async def convert_video(self, video_file, ext, retry=False):
        self.clear()
        self._total_time = (await get_media_info(video_file))[0]
        base_name = ospath.splitext(video_file)[0]
        output = f"{base_name}.{ext}"
        if retry:
            cmd = [
                BinConfig.FFMPEG_NAME,
                "-hide_banner",
                "-loglevel",
                "error",
                "-progress",
                "pipe:1",
                "-i",
                video_file,
                "-map",
                "0",
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-threads",
                f"{max(1, cpu_no // 2)}",
                output,
            ]
            if ext == "mp4":
                cmd[14:14] = ["-c:s", "mov_text"]
            elif ext == "mkv":
                cmd[14:14] = ["-c:s", "ass"]
            else:
                cmd[14:14] = ["-c:s", "copy"]
        else:
            cmd = [
                BinConfig.FFMPEG_NAME,
                "-hide_banner",
                "-loglevel",
                "error",
                "-progress",
                "pipe:1",
                "-i",
                video_file,
                "-map",
                "0",
                "-c",
                "copy",
                "-threads",
                f"{max(1, cpu_no // 2)}",
                output,
            ]
        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await create_subprocess_exec(
            *cmd, stdout=PIPE, stderr=PIPE
        )
        await self._ffmpeg_progress()
        _, stderr = await self._listener.subproc.communicate()
        code = self._listener.subproc.returncode
        if self._listener.is_cancelled:
            return False
        if code == 0:
            return output
        elif code == -9:
            self._listener.is_cancelled = True
            return False
        else:
            if await aiopath.exists(output):
                await remove(output)
            if not retry:
                return await self.convert_video(video_file, ext, True)
            try:
                stderr = stderr.decode().strip()
            except Exception:
                stderr = "Unable to decode the error!"
            LOGGER.error(
                f"{stderr}. Something went wrong while converting video, mostly file need specific codec. Path: {video_file}"
            )
        return False

    async def convert_audio(self, audio_file, ext):
        self.clear()
        self._total_time = (await get_media_info(audio_file))[0]
        base_name = ospath.splitext(audio_file)[0]
        output = f"{base_name}.{ext}"
        cmd = [
            BinConfig.FFMPEG_NAME,
            "-hide_banner",
            "-loglevel",
            "error",
            "-progress",
            "pipe:1",
            "-i",
            audio_file,
            "-threads",
            f"{max(1, cpu_no // 2)}",
            output,
        ]
        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await create_subprocess_exec(
            *cmd, stdout=PIPE, stderr=PIPE
        )
        await self._ffmpeg_progress()
        _, stderr = await self._listener.subproc.communicate()
        code = self._listener.subproc.returncode
        if self._listener.is_cancelled:
            return False
        if code == 0:
            return output
        elif code == -9:
            self._listener.is_cancelled = True
            return False
        else:
            try:
                stderr = stderr.decode().strip()
            except Exception:
                stderr = "Unable to decode the error!"
            LOGGER.error(
                f"{stderr}. Something went wrong while converting audio, mostly file need specific codec. Path: {audio_file}"
            )
            if await aiopath.exists(output):
                await remove(output)
        return False

    async def sample_video(self, video_file, sample_duration, part_duration):
        self.clear()
        self._total_time = sample_duration
        dir, name = video_file.rsplit("/", 1)
        output_file = f"{dir}/SAMPLE.{name}"
        segments = [(0, part_duration)]
        duration = (await get_media_info(video_file))[0]
        remaining_duration = duration - (part_duration * 2)
        parts = (sample_duration - (part_duration * 2)) // part_duration
        time_interval = remaining_duration // parts
        next_segment = time_interval
        for _ in range(parts):
            segments.append((next_segment, next_segment + part_duration))
            next_segment += time_interval
        segments.append((duration - part_duration, duration))

        filter_complex = ""
        for i, (start, end) in enumerate(segments):
            filter_complex += (
                f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}]; "
            )
            filter_complex += (
                f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}]; "
            )

        for i in range(len(segments)):
            filter_complex += f"[v{i}][a{i}]"

        filter_complex += f"concat=n={len(segments)}:v=1:a=1[vout][aout]"

        cmd = [
            BinConfig.FFMPEG_NAME,
            "-hide_banner",
            "-loglevel",
            "error",
            "-progress",
            "pipe:1",
            "-i",
            video_file,
            "-filter_complex",
            filter_complex,
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-threads",
            f"{max(1, cpu_no // 2)}",
            output_file,
        ]

        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await create_subprocess_exec(
            *cmd, stdout=PIPE, stderr=PIPE
        )
        await self._ffmpeg_progress()
        _, stderr = await self._listener.subproc.communicate()
        code = self._listener.subproc.returncode
        if self._listener.is_cancelled:
            return False
        if code == -9:
            self._listener.is_cancelled = True
            return False
        elif code == 0:
            return output_file
        else:
            try:
                stderr = stderr.decode().strip()
            except Exception:
                stderr = "Unable to decode the error!"
            LOGGER.error(
                f"{stderr}. Something went wrong while creating sample video, mostly file is corrupted. Path: {video_file}"
            )
            if await aiopath.exists(output_file):
                await remove(output_file)
            return False

    async def split(self, f_path, file_, parts, split_size):
        self.clear()
        multi_streams = True
        self._total_time = duration = (await get_media_info(f_path))[0]
        base_name, extension = ospath.splitext(file_)

        # If no extension detected, try to determine container format from ffprobe
        if not extension:
            try:
                probe_cmd = [
                    "ffprobe",
                    "-v",
                    "quiet",
                    "-print_format",
                    "json",
                    "-show_format",
                    f_path,
                ]
                process = await create_subprocess_exec(
                    *probe_cmd, stdout=PIPE, stderr=PIPE
                )
                stdout, _ = await process.communicate()

                import json

                format_info = json.loads(stdout.decode())
                format_name = format_info.get("format", {}).get("format_name", "")

                # Map common format names to extensions
                if "matroska" in format_name.lower() or "webm" in format_name.lower():
                    extension = ".mkv"
                elif "mp4" in format_name.lower() or "mov" in format_name.lower():
                    extension = ".mp4"
                elif "avi" in format_name.lower():
                    extension = ".avi"
                elif "flv" in format_name.lower():
                    extension = ".flv"
                else:
                    # Default to mkv for video files as it's most compatible
                    extension = ".mkv"

                LOGGER.info(
                    f"No extension detected for {file_}, using {extension} based on format: {format_name}"
                )
            except Exception as e:
                LOGGER.warning(
                    f"Could not determine format for {file_}, defaulting to .mkv: {e}"
                )
                extension = ".mkv"

        LOGGER.info(
            f"Splitting file: {file_} -> {base_name}.part###${extension} (original extension: '{ospath.splitext(file_)[1] or 'none'}')"
        )

        split_size -= 3000000
        start_time = 0
        i = 1
        while i <= parts or start_time < duration - 4:
            out_path = f_path.replace(file_, f"{base_name}.part{i:03}{extension}")
            LOGGER.info(f"Creating part {i}: {out_path}")
            cmd = [
                BinConfig.FFMPEG_NAME,
                "-hide_banner",
                "-loglevel",
                "error",
                "-progress",
                "pipe:1",
                "-ss",
                str(start_time),
                "-i",
                f_path,
                "-fs",
                str(split_size),
            ]

            # Add stream mapping based on mode
            if multi_streams:
                # Map all video, audio, and subtitle streams explicitly
                # This avoids issues with problematic attachment streams (cover art, fonts, etc.)
                cmd.extend(
                    [
                        "-map",
                        "0:v?",  # Map all video streams (optional - in case file has none)
                        "-map",
                        "0:a?",  # Map all audio streams (optional - in case file has none)
                        "-map",
                        "0:s?",  # Map subtitle streams if they exist (optional)
                    ]
                )
            # If not multi_streams, FFmpeg will use default stream selection (best video + best audio)

            cmd.extend(
                [
                    "-map_chapters",
                    "-1",
                    "-async",
                    "1",
                    "-strict",
                    "-2",
                    "-c",
                    "copy",
                ]
            )

            # Add format specification when extension was auto-detected
            if not ospath.splitext(file_)[1]:  # Original file had no extension
                if extension == ".mkv":
                    cmd.extend(["-f", "matroska"])
                elif extension == ".mp4":
                    cmd.extend(["-f", "mp4"])
                elif extension == ".avi":
                    cmd.extend(["-f", "avi"])

            cmd.extend(
                [
                    "-threads",
                    f"{max(1, cpu_no // 2)}",
                    out_path,
                ]
            )

            # Store the original command length before potential modifications
            original_cmd_length = len(cmd)
            if self._listener.is_cancelled:
                return False
            self._listener.subproc = await create_subprocess_exec(
                *cmd, stdout=PIPE, stderr=PIPE
            )
            await self._ffmpeg_progress()
            _, stderr = await self._listener.subproc.communicate()
            code = self._listener.subproc.returncode
            if self._listener.is_cancelled:
                return False
            if code == -9:
                self._listener.is_cancelled = True
                return False
            elif code != 0:
                try:
                    stderr = stderr.decode().strip()
                except Exception:
                    stderr = "Unable to decode the error!"
                with suppress(Exception):
                    await remove(out_path)
                if multi_streams:
                    LOGGER.warning(
                        f"{stderr}. Retrying with default stream selection. Path: {f_path}"
                    )
                    multi_streams = False
                    continue
                else:
                    LOGGER.warning(
                        f"{stderr}. Unable to split this video, if it's size less than {self._listener.max_split_size} will be uploaded as it is. Path: {f_path}"
                    )
                return False
            out_size = await aiopath.getsize(out_path)
            if out_size > self._listener.max_split_size:
                split_size -= (out_size - self._listener.max_split_size) + 5000000
                LOGGER.warning(
                    f"Part size is {out_size}. Trying again with lower split size!. Path: {f_path}"
                )
                await remove(out_path)
                continue
            lpd = (await get_media_info(out_path))[0]
            if lpd == 0:
                LOGGER.error(
                    f"Something went wrong while splitting, mostly file is corrupted. Path: {f_path}"
                )
                break
            elif duration == lpd:
                LOGGER.warning(
                    f"This file has been splitted with default stream and audio, so you will only see one part with less size from orginal one because it doesn't have all streams and audios. This happens mostly with MKV videos. Path: {f_path}"
                )
                break
            elif lpd <= 3:
                await remove(out_path)
                break
            self._last_processed_time += lpd
            self._last_processed_bytes += out_size
            start_time += lpd - 3
            i += 1
        return True

    async def merge_video_subtitles(
        self, video_file, subtitle_files, output_file, user_dict=None
    ):
        """
        Merge a video file with one or more subtitle files

        Parameters:
        video_file (str): Path to the video file
        subtitle_files (list): List of subtitle file paths to merge
        output_file (str): Path to save the merged video

        Returns:
        bool or str: Path to merged video if successful, False otherwise
        """
        # Use custom filename if set
        if user_dict is not None:
            from bot.helper.ext_utils.watermark_utils import apply_custom_filename

            output_file = apply_custom_filename(video_file, user_dict, "_merged")

        # Store original output file for later replacement
        original_output_file = output_file

        # Ensure output is MKV format and has a different name than input to avoid FFmpeg in-place error
        if not output_file.lower().endswith(".mkv"):
            output_base = (
                output_file.rsplit(".", 1)[0] if "." in output_file else output_file
            )
            output_file = f"{output_base}.mkv"
            LOGGER.info(
                f"Changed output format to MKV to support subtitle tracks: {output_file}"
            )

        # If output file same as input, use temporary filename during merge
        if output_file == video_file:
            output_base = (
                output_file.rsplit(".", 1)[0] if "." in output_file else output_file
            )
            output_file = f"{output_base}_temp_merge.mkv"
            LOGGER.info(
                f"Using temporary filename during merge to avoid in-place editing: {output_file}"
            )

        self.clear()

        # Get video duration for progress reporting
        duration = (await get_media_info(video_file))[0]
        self._total_time = duration

        # First, check the input video to count existing streams
        try:
            # Use ffprobe to get stream information
            probe_cmd = [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                video_file,
            ]
            process = await create_subprocess_exec(*probe_cmd, stdout=PIPE, stderr=PIPE)
            stdout, _ = await process.communicate()

            try:
                import json

                video_info = json.loads(stdout.decode())
                streams = video_info.get("streams", [])

                # Count stream types
                video_streams = 0
                audio_streams = 0
                subtitle_streams = 0

                for stream in streams:
                    stream_type = stream.get("codec_type")
                    if stream_type == "video":
                        video_streams += 1
                    elif stream_type == "audio":
                        audio_streams += 1
                    elif stream_type == "subtitle":
                        subtitle_streams += 1

                LOGGER.info(
                    f"Input video has {video_streams} video, {audio_streams} audio, and {subtitle_streams} subtitle streams"
                )
                LOGGER.info(f"Will add {len(subtitle_files)} new subtitle tracks")
            except Exception as e:
                LOGGER.warning(f"Error parsing video stream info: {str(e)}")
        except Exception as e:
            LOGGER.warning(f"Error analyzing video streams: {str(e)}")

        # Base command with video input
        cmd = [
            BinConfig.FFMPEG_NAME,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-progress",
            "pipe:1",
            "-i",
            video_file,
        ]

        # Add each subtitle file as an input
        subtitle_languages = {}
        subtitle_codecs = {}
        for i, subtitle_file in enumerate(subtitle_files):
            cmd.extend(["-i", subtitle_file])
            file_name = ospath.basename(subtitle_file)
            LOGGER.info(f"Adding subtitle track: {file_name}")

            # Try to detect language from filename
            file_lower = file_name.lower()
            lang_code = "eng"  # Default language code

            # More comprehensive language detection from filename
            if (
                "english" in file_lower
                or ".en." in file_lower
                or "_en_" in file_lower
                or ".eng." in file_lower
            ):
                lang_code = "eng"
            elif (
                "spanish" in file_lower
                or ".es." in file_lower
                or "_es_" in file_lower
                or ".spa." in file_lower
            ):
                lang_code = "spa"
            elif (
                "french" in file_lower
                or ".fr." in file_lower
                or "_fr_" in file_lower
                or ".fre." in file_lower
            ):
                lang_code = "fre"
            elif (
                "german" in file_lower
                or ".de." in file_lower
                or "_de_" in file_lower
                or ".ger." in file_lower
            ):
                lang_code = "ger"
            elif (
                "italian" in file_lower
                or ".it." in file_lower
                or "_it_" in file_lower
                or ".ita." in file_lower
            ):
                lang_code = "ita"
            elif (
                "japanese" in file_lower
                or ".ja." in file_lower
                or ".jp." in file_lower
                or "_jp_" in file_lower
                or ".jpn." in file_lower
            ):
                lang_code = "jpn"
            elif (
                "korean" in file_lower
                or ".ko." in file_lower
                or "_ko_" in file_lower
                or ".kor." in file_lower
            ):
                lang_code = "kor"
            elif (
                "chinese" in file_lower
                or ".zh." in file_lower
                or "_zh_" in file_lower
                or ".chi." in file_lower
            ):
                lang_code = "chi"
            elif (
                "hindi" in file_lower
                or ".hi." in file_lower
                or "_hi_" in file_lower
                or ".hin." in file_lower
            ):
                lang_code = "hin"
            elif (
                "russian" in file_lower
                or ".ru." in file_lower
                or "_ru_" in file_lower
                or ".rus." in file_lower
            ):
                lang_code = "rus"
            elif (
                "portuguese" in file_lower
                or ".pt." in file_lower
                or "_pt_" in file_lower
                or ".por." in file_lower
            ):
                lang_code = "por"
            elif (
                "arabic" in file_lower
                or ".ar." in file_lower
                or "_ar_" in file_lower
                or ".ara." in file_lower
            ):
                lang_code = "ara"
            elif i < len(subtitle_languages):
                # Use a default code from our list if not detected
                language_codes = [
                    "eng",
                    "jpn",
                    "kor",
                    "chi",
                    "fre",
                    "ger",
                    "ita",
                    "spa",
                    "rus",
                    "hin",
                    "por",
                    "ara",
                ]
                if i < len(language_codes):
                    lang_code = language_codes[i]

            # Detect subtitle codec by extension
            ext = ospath.splitext(file_name)[1].lower()
            if ext == ".srt":
                subtitle_codecs[i] = "srt"
            elif ext in (".ass", ".ssa"):
                subtitle_codecs[i] = "ass"
            elif ext == ".vtt":
                subtitle_codecs[i] = "webvtt"
            elif ext == ".mka":
                # For MKA files, check if they contain subtitle streams
                try:
                    # Use ffprobe to examine the MKA file content
                    mka_probe_cmd = [
                        "ffprobe",
                        "-v",
                        "quiet",
                        "-print_format",
                        "json",
                        "-show_streams",
                        subtitle_file,
                    ]
                    mka_process = await create_subprocess_exec(
                        *mka_probe_cmd, stdout=PIPE, stderr=PIPE
                    )
                    mka_stdout, _ = await mka_process.communicate()

                    try:
                        import json

                        mka_info = json.loads(mka_stdout.decode())
                        mka_streams = mka_info.get("streams", [])

                        # Check if any stream is a subtitle
                        has_subtitle = False
                        for stream in mka_streams:
                            if stream.get("codec_type") == "subtitle":
                                has_subtitle = True
                                LOGGER.info(
                                    f"MKA file {file_name} contains subtitle streams, will be merged"
                                )
                                break

                        if has_subtitle:
                            subtitle_codecs[i] = (
                                "copy"  # Use copy to preserve the subtitle streams
                            )
                        else:
                            LOGGER.warning(
                                f"MKA file {file_name} doesn't contain subtitle streams, setting codec to copy anyway"
                            )
                            subtitle_codecs[i] = "copy"
                    except Exception as e:
                        LOGGER.warning(
                            f"Error parsing MKA stream info: {str(e)}, setting codec to copy"
                        )
                        subtitle_codecs[i] = "copy"
                except Exception as e:
                    LOGGER.warning(
                        f"Error analyzing MKA file {file_name}: {str(e)}, setting codec to copy"
                    )
                    subtitle_codecs[i] = "copy"
            else:
                subtitle_codecs[i] = "copy"  # fallback to copy

            # Store language info for later use in mapping
            subtitle_languages[i + 1] = lang_code
            LOGGER.info(
                f"Detected language for subtitle {i + 1}: {lang_code}, codec: {subtitle_codecs[i]}"
            )

        # Map ALL streams from original video
        cmd.extend(
            ["-map", "0"]
        )  # Map all streams (video, audio, subtitles) from original video

        # Map each subtitle from additional files
        for i in range(len(subtitle_files)):
            input_index = i + 1

            # Special handling for MKA files - map only subtitle streams
            if subtitle_files[i].endswith(".mka"):
                LOGGER.info(
                    f"Special handling for MKA file: {ospath.basename(subtitle_files[i])}"
                )
                try:
                    # Use ffprobe to identify subtitle stream indexes in the MKA file
                    mka_probe_cmd = [
                        "ffprobe",
                        "-v",
                        "quiet",
                        "-print_format",
                        "json",
                        "-show_streams",
                        subtitle_files[i],
                    ]
                    mka_process = await create_subprocess_exec(
                        *mka_probe_cmd, stdout=PIPE, stderr=PIPE
                    )
                    mka_stdout, _ = await mka_process.communicate()

                    try:
                        import json

                        mka_info = json.loads(mka_stdout.decode())
                        mka_streams = mka_info.get("streams", [])

                        # Find all subtitle streams and map them specifically
                        subtitle_indexes = []
                        for idx, stream in enumerate(mka_streams):
                            if stream.get("codec_type") == "subtitle":
                                subtitle_indexes.append(idx)
                                LOGGER.info(
                                    f"Found subtitle stream at index {idx} in MKA file"
                                )

                        if subtitle_indexes:
                            for sub_idx in subtitle_indexes:
                                cmd.extend(["-map", f"{input_index}:{sub_idx}"])
                        else:
                            # No subtitle streams found, map everything anyway as fallback
                            cmd.extend(["-map", f"{input_index}"])
                    except Exception as e:
                        LOGGER.warning(
                            f"Error parsing MKA stream info: {str(e)}, mapping all streams"
                        )
                        cmd.extend(["-map", f"{input_index}"])
                except Exception as e:
                    LOGGER.warning(
                        f"Error analyzing MKA file: {str(e)}, mapping all streams"
                    )
                    cmd.extend(["-map", f"{input_index}"])
            else:
                # Standard mapping for regular subtitle files
                cmd.extend(["-map", f"{input_index}"])

        # Calculate subtitle stream index offset
        # We need to determine how many subtitle streams are in the original video
        subtitle_stream_count = 0
        try:
            import json

            # Use the previously parsed video_info if it exists
            if "video_info" in locals():
                streams = video_info.get("streams", [])
                subtitle_stream_count = sum(
                    1 for stream in streams if stream.get("codec_type") == "subtitle"
                )
                LOGGER.info(
                    f"Found {subtitle_stream_count} subtitle streams in original video"
                )
        except Exception as e:
            LOGGER.warning(f"Error determining subtitle stream count: {str(e)}")

        # Set language for all subtitle streams being added
        for i, lang_code in subtitle_languages.items():
            # Calculate the actual stream index based on existing subtitle streams
            stream_index = subtitle_stream_count + i - 1
            # Set language for the subtitle track (use the correct stream specifier format)
            cmd.extend([f"-metadata:s:s:{stream_index}", f"language={lang_code}"])
            # Add title metadata to make it easier to identify in players
            cmd.extend(
                [f"-metadata:s:s:{stream_index}", f"title=Subtitle {i} ({lang_code})"]
            )

        # Set correct codec for each subtitle
        cmd.extend(["-c:v", "copy", "-c:a", "copy"])  # Always copy video/audio
        for i in range(len(subtitle_files)):
            codec = subtitle_codecs.get(i, "copy")
            cmd.extend([f"-c:s:{i}", codec])

        cmd.extend(
            [
                "-map_metadata",
                "0",
                "-threads",
                f"{max(1, cpu_no // 2)}",
                output_file,
                "-y",
            ]
        )

        if self._listener.is_cancelled:
            return False

        self._listener.subproc = await create_subprocess_exec(
            *cmd, stdout=PIPE, stderr=PIPE
        )

        await self._ffmpeg_progress()
        _, stderr = await self._listener.subproc.communicate()
        code = self._listener.subproc.returncode

        if self._listener.is_cancelled:
            return False

        if code == 0:
            # If we used a temporary filename, rename it back to the original
            if output_file != original_output_file:
                try:
                    if await aiopath.exists(original_output_file):
                        await remove(original_output_file)  # Remove original file first
                    await move(output_file, original_output_file)
                    LOGGER.info(
                        f"Renamed temporary file {output_file} to {original_output_file}"
                    )
                    return original_output_file
                except Exception as e:
                    LOGGER.error(f"Failed to rename temporary file: {e}")
                    return output_file
            return output_file
        elif code == -9:
            self._listener.is_cancelled = True
            return False
        else:
            try:
                stderr = stderr.decode().strip()
            except Exception:
                stderr = "Unable to decode the error!"

            LOGGER.error(f"{stderr}. Failed to merge video with subtitle tracks.")

            # Check for specific in-place editing error
            if "same as Input" in stderr and "exiting" in stderr:
                LOGGER.error(
                    "FFmpeg detected output file same as input file - this should have been handled earlier"
                )
                return False

            # If the error is related to metadata or stream specifiers, try again with a simpler command
            if (
                "Stream type specified multiple times" in stderr
                or "Invalid stream specifier" in stderr
                or "metadata" in stderr
            ):
                LOGGER.info(
                    "Retrying subtitle merge with simplified command (no metadata)"
                )

                # Reset command
                cmd = [
                    BinConfig.FFMPEG_NAME,
                    "-hide_banner",
                    "-loglevel",
                    "warning",
                    "-progress",
                    "pipe:1",
                    "-i",
                    video_file,
                ]

                # Add each subtitle file as an input
                for subtitle_file in subtitle_files:
                    cmd.extend(["-i", subtitle_file])

                # Map ALL streams from original video and all subtitles
                cmd.extend(["-map", "0"])  # Map all streams from input video
                for i in range(len(subtitle_files)):
                    input_index = i + 1
                    cmd.extend(["-map", f"{input_index}"])  # Map subtitles

                # Set correct codec for each subtitle
                cmd.extend(["-c:v", "copy", "-c:a", "copy"])
                for i in range(len(subtitle_files)):
                    codec = subtitle_codecs.get(i, "copy")
                    cmd.extend([f"-c:s:{i}", codec])

                # Copy all streams without re-encoding but skip metadata setting
                cmd.extend(
                    [
                        "-map_metadata",
                        "0",
                        "-threads",
                        f"{max(1, cpu_no // 2)}",
                        output_file,
                        "-y",
                    ]
                )

                if self._listener.is_cancelled:
                    return False

                self._listener.subproc = await create_subprocess_exec(
                    *cmd, stdout=PIPE, stderr=PIPE
                )

                await self._ffmpeg_progress()
                _, stderr = await self._listener.subproc.communicate()
                code = self._listener.subproc.returncode

                if code == 0:
                    LOGGER.info("Fallback subtitle merge method successful")
                    # If we used a temporary filename, rename it back to the original
                    if output_file != original_output_file:
                        try:
                            if await aiopath.exists(original_output_file):
                                await remove(
                                    original_output_file
                                )  # Remove original file first
                            await move(output_file, original_output_file)
                            LOGGER.info(
                                f"Renamed temporary file {output_file} to {original_output_file}"
                            )
                            return original_output_file
                        except Exception as e:
                            LOGGER.error(f"Failed to rename temporary file: {e}")
                            return output_file
                    return output_file

                try:
                    stderr = stderr.decode().strip()
                except Exception:
                    stderr = "Unable to decode the error!"

                LOGGER.error(f"Fallback subtitle merge also failed: {stderr}")

            return False

    async def hardsub_video(
        self, video_file, subtitle_files, output_file, user_dict=None
    ):
        """
        Burn subtitle files permanently into video (hardsub)

        Parameters:
        video_file (str): Path to the video file
        subtitle_files (list): List of subtitle file paths to burn into video
        output_file (str): Path to save the video with burned subtitles
        user_dict (dict): User settings dictionary

        Returns:
        bool or str: Path to hardsubbed video if successful, False otherwise
        """
        # Use custom filename if set
        if user_dict is not None:
            from bot.helper.ext_utils.watermark_utils import apply_custom_filename

            output_file = apply_custom_filename(
                video_file, user_dict, ""
            )  # Remove _hardsub suffix

        # Store original output file for later replacement
        original_output_file = output_file

        # Always use a temporary name during processing to avoid conflicts
        output_base = (
            output_file.rsplit(".", 1)[0] if "." in output_file else output_file
        )
        temp_output_file = f"{output_base}_temp_hardsub.mp4"

        LOGGER.info(
            f"Using temporary filename during hardsub processing: {temp_output_file}"
        )
        LOGGER.info(f"Final output will be: {original_output_file}")

        self.clear()

        # Get video duration for progress reporting
        duration = (await get_media_info(video_file))[0]
        self._total_time = duration

        # Get user hardsub settings
        hardsub_style = (
            user_dict.get("VIDEO_HARDSUB_STYLE", "default") if user_dict else "default"
        )
        hardsub_font_size = (
            user_dict.get("VIDEO_HARDSUB_FONT_SIZE", 20) if user_dict else 20
        )
        hardsub_font_name = (
            user_dict.get("VIDEO_HARDSUB_FONT_NAME", "Arial") if user_dict else "Arial"
        )

        # Validate font size
        try:
            hardsub_font_size = max(8, min(72, int(hardsub_font_size)))
        except (ValueError, TypeError):
            hardsub_font_size = 20

        # Base command
        cmd = [
            BinConfig.FFMPEG_NAME,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-progress",
            "pipe:1",
            "-i",
            video_file,
        ]

        # Add subtitle files as inputs
        for subtitle_file in subtitle_files:
            cmd.extend(["-i", subtitle_file])
            LOGGER.info(
                f"Adding subtitle for burning: {ospath.basename(subtitle_file)}"
            )

        # Build subtitle filter
        subtitle_filters = []

        for i, subtitle_file in enumerate(subtitle_files):
            input_index = i + 1
            file_ext = ospath.splitext(subtitle_file)[1].lower()

            if file_ext == ".ass" or file_ext == ".ssa":
                # For ASS/SSA files, use ass filter which preserves styling
                if hardsub_style == "default":
                    subtitle_filters.append(
                        f"ass='{subtitle_file.replace(':', '\\\\:').replace('\\\\', '/')}'"
                    )
                else:
                    # For non-default styles, we still use ass filter but could add force_style
                    subtitle_filters.append(
                        f"ass='{subtitle_file.replace(':', '\\\\:').replace('\\\\', '/')}'"
                    )
            else:
                # For SRT, VTT and other text-based formats, use subtitles filter
                filter_str = f"subtitles='{subtitle_file.replace(':', '\\\\:').replace('\\\\', '/')}'"

                # Apply styling based on user preferences
                if hardsub_style != "default":
                    style_options = []
                    style_options.append(f"FontSize={hardsub_font_size}")
                    # Escape font name if it contains spaces or special characters
                    escaped_font_name = hardsub_font_name.replace(" ", "\\ ").replace(
                        ":", "\\:"
                    )
                    style_options.append(f"Fontname={escaped_font_name}")

                    if hardsub_style == "bold":
                        style_options.append("Bold=1")
                    elif hardsub_style == "outline":
                        style_options.append("Outline=2")
                        style_options.append("OutlineColour=&H000000")
                    elif hardsub_style == "shadow":
                        style_options.append("Shadow=2")
                        style_options.append("BackColour=&H80000000")
                    elif hardsub_style == "glow":
                        style_options.append("Outline=3")
                        style_options.append("OutlineColour=&H00FFFFFF")

                    if style_options:
                        force_style = ",".join(style_options)
                        filter_str += f":force_style='{force_style}'"

                subtitle_filters.append(filter_str)

        # Chain subtitle filters if multiple subtitles
        if subtitle_filters:
            if len(subtitle_filters) == 1:
                video_filter = f"[0:v]{subtitle_filters[0]}[v]"
            else:
                # Chain multiple subtitle filters
                filter_chain = "[0:v]"
                for i, sub_filter in enumerate(subtitle_filters):
                    if i == len(subtitle_filters) - 1:
                        filter_chain += f"{sub_filter}[v]"
                    else:
                        filter_chain += f"{sub_filter}[v{i}];[v{i}]"
                video_filter = filter_chain

            cmd.extend(["-filter_complex", video_filter])
            cmd.extend(
                ["-map", "[v]", "-map", "0:a?"]
            )  # Map filtered video and audio if present
        else:
            cmd.extend(["-c:v", "copy", "-c:a", "copy"])  # Fallback if no filters

        # Video encoding settings for hardsub (need to re-encode for subtitle burning)
        if subtitle_filters:
            cmd.extend(
                [
                    "-c:v",
                    "libx264",
                    "-preset",
                    "medium",
                    "-crf",
                    "23",
                    "-c:a",
                    "copy",  # Keep audio as-is
                ]
            )

        cmd.extend(["-threads", f"{max(1, cpu_no // 2)}", temp_output_file, "-y"])

        if self._listener.is_cancelled:
            return False

        LOGGER.info(f"Starting hardsub with {len(subtitle_files)} subtitle file(s)")
        LOGGER.debug(f"FFmpeg hardsub command: {' '.join(cmd)}")
        self._listener.subproc = await create_subprocess_exec(
            *cmd, stdout=PIPE, stderr=PIPE
        )

        await self._ffmpeg_progress()
        _, stderr = await self._listener.subproc.communicate()
        code = self._listener.subproc.returncode

        if self._listener.is_cancelled:
            return False

        if code == 0:
            # Always rename from temporary file to final output
            try:
                # Only remove original if it's different from the final output path
                if (
                    await aiopath.exists(original_output_file)
                    and original_output_file != video_file
                ):
                    await remove(
                        original_output_file
                    )  # Remove existing output file first
                elif original_output_file == video_file:
                    # If output path is same as input, we need to safely replace the original
                    # First verify the temporary file exists and is valid
                    if not await aiopath.exists(temp_output_file):
                        LOGGER.error(
                            f"Temporary file {temp_output_file} not found, cannot replace original"
                        )
                        return False

                    # Get file sizes to verify the hardsub worked
                    original_size = await aiopath.getsize(video_file)
                    temp_size = await aiopath.getsize(temp_output_file)

                    if (
                        temp_size < original_size * 0.5
                    ):  # If new file is less than 50% of original, something went wrong
                        LOGGER.error(
                            f"Temporary file size ({temp_size}) seems too small compared to original ({original_size}), aborting replacement"
                        )
                        return False

                    # Safe replacement: remove original then rename temp
                    await remove(video_file)
                    LOGGER.info(
                        f"Removed original video: {ospath.basename(video_file)}"
                    )

                await move(temp_output_file, original_output_file)
                LOGGER.info(
                    f"Renamed temporary file {temp_output_file} to {original_output_file}"
                )
                return original_output_file
            except Exception as e:
                LOGGER.error(f"Failed to rename temporary file: {e}")
                return temp_output_file
        elif code == -9:
            self._listener.is_cancelled = True
            return False
        else:
            try:
                stderr = stderr.decode().strip()
            except Exception:
                stderr = "Unable to decode the error!"

            # Check for specific font-related errors and provide helpful messages
            if "FontName" in stderr or "Option not found" in stderr:
                LOGGER.error(
                    f"Subtitle hardsub failed with font-related error: {stderr}"
                )
                LOGGER.error(
                    "This might be due to incorrect font parameter names or unsupported font."
                )
            else:
                LOGGER.error(f"Subtitle hardsub failed: {stderr}")
            LOGGER.error(f"Failed to burn subtitles into video: {video_file}")
            return False

    async def merge_video_audio(
        self, video_file, audio_files, output_file, user_dict=None
    ):
        """
        Merge a video file with one or more audio tracks

        Parameters:
        video_file (str): Path to the video file
        audio_files (list): List of audio file paths to merge as additional tracks
        output_file (str): Path to save the merged video

        Returns:
        bool or str: Path to merged video if successful, False otherwise
        """
        # Use custom filename if set
        if user_dict is not None:
            from bot.helper.ext_utils.watermark_utils import apply_custom_filename

            output_file = apply_custom_filename(video_file, user_dict, "_merged")

        # Store original output file for later replacement
        original_output_file = output_file

        # Ensure output is MKV format and has a different name than input to avoid FFmpeg in-place error
        if not output_file.lower().endswith(".mkv"):
            output_base = (
                output_file.rsplit(".", 1)[0] if "." in output_file else output_file
            )
            output_file = f"{output_base}.mkv"
            LOGGER.info(
                f"Changed output format to MKV to support multiple audio tracks: {output_file}"
            )

        # If output file same as input, use temporary filename during merge
        if output_file == video_file:
            output_base = (
                output_file.rsplit(".", 1)[0] if "." in output_file else output_file
            )
            output_file = f"{output_base}_temp_merge.mkv"
            LOGGER.info(
                f"Using temporary filename during merge to avoid in-place editing: {output_file}"
            )

        self.clear()

        # Get video duration for progress reporting
        duration = (await get_media_info(video_file))[0]
        self._total_time = duration

        # First, check the input video to count existing streams
        try:
            # Use ffprobe to get stream information
            probe_cmd = [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                video_file,
            ]
            process = await create_subprocess_exec(*probe_cmd, stdout=PIPE, stderr=PIPE)
            stdout, _ = await process.communicate()

            try:
                import json

                video_info = json.loads(stdout.decode())
                streams = video_info.get("streams", [])

                # Count stream types
                video_streams = 0
                audio_streams = 0
                subtitle_streams = 0

                for stream in streams:
                    stream_type = stream.get("codec_type")
                    if stream_type == "video":
                        video_streams += 1
                    elif stream_type == "audio":
                        audio_streams += 1
                        # Check if audio stream has language metadata
                        if "tags" in stream and "language" in stream["tags"]:
                            LOGGER.info(
                                f"Original audio track language: {stream['tags']['language']}"
                            )
                    elif stream_type == "subtitle":
                        subtitle_streams += 1

                LOGGER.info(
                    f"Input video has {video_streams} video, {audio_streams} audio, and {subtitle_streams} subtitle streams"
                )
                LOGGER.info(f"Will add {len(audio_files)} new audio tracks")
            except Exception as e:
                LOGGER.warning(f"Error parsing video stream info: {str(e)}")
        except Exception as e:
            LOGGER.warning(f"Error analyzing video streams: {str(e)}")

        # Base command with video input
        cmd = [
            BinConfig.FFMPEG_NAME,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-progress",
            "pipe:1",
            "-i",
            video_file,
        ]

        # Add each audio file as an input and track languages
        audio_languages = {}
        for i, audio_file in enumerate(audio_files):
            cmd.extend(["-i", audio_file])
            file_name = ospath.basename(audio_file)
            LOGGER.info(f"Adding audio track: {file_name}")

            # More comprehensive language detection from filename
            file_lower = file_name.lower()
            lang_code = "eng"  # Default language code

            # Try to detect language from filename with more comprehensive patterns
            if (
                "english" in file_lower
                or ".en." in file_lower
                or "_en_" in file_lower
                or ".eng." in file_lower
            ):
                lang_code = "eng"
            elif (
                "spanish" in file_lower
                or ".es." in file_lower
                or "_es_" in file_lower
                or ".spa." in file_lower
            ):
                lang_code = "spa"
            elif (
                "french" in file_lower
                or ".fr." in file_lower
                or "_fr_" in file_lower
                or ".fre." in file_lower
            ):
                lang_code = "fre"
            elif (
                "german" in file_lower
                or ".de." in file_lower
                or "_de_" in file_lower
                or ".ger." in file_lower
            ):
                lang_code = "ger"
            elif (
                "italian" in file_lower
                or ".it." in file_lower
                or "_it_" in file_lower
                or ".ita." in file_lower
            ):
                lang_code = "ita"
            elif (
                "japanese" in file_lower
                or ".ja." in file_lower
                or ".jp." in file_lower
                or "_jp_" in file_lower
                or ".jpn." in file_lower
            ):
                lang_code = "jpn"
            elif (
                "korean" in file_lower
                or ".ko." in file_lower
                or "_ko_" in file_lower
                or ".kor." in file_lower
            ):
                lang_code = "kor"
            elif (
                "chinese" in file_lower
                or ".zh." in file_lower
                or "_zh_" in file_lower
                or ".chi." in file_lower
            ):
                lang_code = "chi"
            elif (
                "hindi" in file_lower
                or ".hi." in file_lower
                or "_hi_" in file_lower
                or ".hin." in file_lower
            ):
                lang_code = "hin"
            elif (
                "russian" in file_lower
                or ".ru." in file_lower
                or "_ru_" in file_lower
                or ".rus." in file_lower
            ):
                lang_code = "rus"
            elif (
                "portuguese" in file_lower
                or ".pt." in file_lower
                or "_pt_" in file_lower
                or ".por." in file_lower
            ):
                lang_code = "por"
            elif (
                "arabic" in file_lower
                or ".ar." in file_lower
                or "_ar_" in file_lower
                or ".ara." in file_lower
            ):
                lang_code = "ara"
            else:
                # Use a default code from our list if not detected
                language_codes = [
                    "eng",
                    "jpn",
                    "kor",
                    "chi",
                    "fre",
                    "ger",
                    "ita",
                    "spa",
                    "rus",
                    "hin",
                    "por",
                    "ara",
                ]
                if i < len(language_codes):
                    lang_code = language_codes[i]

            # Store language info for later use
            audio_languages[i + 1] = lang_code
            LOGGER.info(f"Detected language for audio track {i + 1}: {lang_code}")

        # Map ALL streams from original video
        cmd.extend(
            ["-map", "0"]
        )  # Map all streams (video, audio, subtitles) from input video

        # Map each audio stream from additional files
        for i in range(len(audio_files)):
            input_index = i + 1
            cmd.extend(
                ["-map", f"{input_index}:a?"]
            )  # All audio from each additional file

        # Calculate audio stream index offset
        # We need to determine how many audio streams are in the original video
        audio_stream_count = 0
        try:
            import json

            # Use the previously parsed video_info if it exists
            if "video_info" in locals():
                streams = video_info.get("streams", [])
                audio_stream_count = sum(
                    1 for stream in streams if stream.get("codec_type") == "audio"
                )
                LOGGER.info(
                    f"Found {audio_stream_count} audio streams in original video"
                )
        except Exception as e:
            LOGGER.warning(f"Error determining audio stream count: {str(e)}")

        # Add language metadata for all additional audio tracks
        for i, lang_code in audio_languages.items():
            # Calculate the actual stream index based on the existing audio streams
            stream_index = audio_stream_count + i - 1
            # Set language for the audio track (use the correct stream specifier format)
            cmd.extend([f"-metadata:s:a:{stream_index}", f"language={lang_code}"])
            # Add title metadata to make it easier to identify in players
            cmd.extend(
                [f"-metadata:s:a:{stream_index}", f"title=Audio {i} ({lang_code})"]
            )

        # Copy all streams without re-encoding
        cmd.extend(
            [
                "-c",
                "copy",
                "-map_metadata",
                "0",
                "-threads",
                f"{max(1, cpu_no // 2)}",
                output_file,
                "-y",
            ]
        )

        if self._listener.is_cancelled:
            return False

        self._listener.subproc = await create_subprocess_exec(
            *cmd, stdout=PIPE, stderr=PIPE
        )

        await self._ffmpeg_progress()
        _, stderr = await self._listener.subproc.communicate()
        code = self._listener.subproc.returncode

        if self._listener.is_cancelled:
            return False

        if code == 0:
            # If we used a temporary filename, rename it back to the original
            if output_file != original_output_file:
                try:
                    if await aiopath.exists(original_output_file):
                        await remove(original_output_file)  # Remove original file first
                    await move(output_file, original_output_file)
                    LOGGER.info(
                        f"Renamed temporary file {output_file} to {original_output_file}"
                    )
                    return original_output_file
                except Exception as e:
                    LOGGER.error(f"Failed to rename temporary file: {e}")
                    return output_file
            return output_file
        elif code == -9:
            self._listener.is_cancelled = True
            return False
        else:
            try:
                stderr = stderr.decode().strip()
            except Exception:
                stderr = "Unable to decode the error!"

            LOGGER.error(f"{stderr}. Failed to merge video with audio tracks.")

            # Check for specific in-place editing error
            if "same as Input" in stderr and "exiting" in stderr:
                LOGGER.error(
                    "FFmpeg detected output file same as input file - this should have been handled earlier"
                )
                return False

            # If the error is related to metadata or stream specifiers, try again with a simpler command
            if (
                "Stream type specified multiple times" in stderr
                or "Invalid stream specifier" in stderr
                or "metadata" in stderr
            ):
                LOGGER.info("Retrying merge with simplified command (no metadata)")

                # Reset command
                cmd = [
                    BinConfig.FFMPEG_NAME,
                    "-hide_banner",
                    "-loglevel",
                    "warning",
                    "-progress",
                    "pipe:1",
                    "-i",
                    video_file,
                ]

                # Add each audio file as an input
                for audio_file in audio_files:
                    cmd.extend(["-i", audio_file])

                # Map ALL streams from original video and additional audio files
                cmd.extend(["-map", "0"])  # Map all streams from input video
                for i in range(len(audio_files)):
                    input_index = i + 1
                    cmd.extend(
                        ["-map", f"{input_index}:a?"]
                    )  # All audio from each additional file

                # Copy all streams without re-encoding but skip metadata setting
                cmd.extend(
                    [
                        "-c",
                        "copy",
                        "-map_metadata",
                        "0",
                        "-threads",
                        f"{max(1, cpu_no // 2)}",
                        output_file,
                        "-y",
                    ]
                )

                if self._listener.is_cancelled:
                    return False

                self._listener.subproc = await create_subprocess_exec(
                    *cmd, stdout=PIPE, stderr=PIPE
                )

                await self._ffmpeg_progress()
                _, stderr = await self._listener.subproc.communicate()
                code = self._listener.subproc.returncode

                if code == 0:
                    LOGGER.info("Fallback merge method successful")
                    # If we used a temporary filename, rename it back to the original
                    if output_file != original_output_file:
                        try:
                            if await aiopath.exists(original_output_file):
                                await remove(
                                    original_output_file
                                )  # Remove original file first
                            await move(output_file, original_output_file)
                            LOGGER.info(
                                f"Renamed temporary file {output_file} to {original_output_file}"
                            )
                            return original_output_file
                        except Exception as e:
                            LOGGER.error(f"Failed to rename temporary file: {e}")
                            return output_file
                    return output_file

                try:
                    stderr = stderr.decode().strip()
                except Exception:
                    stderr = "Unable to decode the error!"

                LOGGER.error(f"Fallback merge also failed: {stderr}")

            return False

    async def merge_videos(self, video_files, output_file, user_dict=None):
        """
        Merge multiple video files into a single output file

        Parameters:
        video_files (list): List of video file paths to merge
        output_file (str): Path to save the merged video

        Returns:
        bool or str: Path to merged video if successful, False otherwise
        """
        # Use custom filename if set
        if user_dict is not None and video_files:
            from bot.helper.ext_utils.watermark_utils import apply_custom_filename

            output_file = apply_custom_filename(video_files[0], user_dict, "")
        # Ensure output is MKV format to support all codecs
        if not output_file.lower().endswith(".mkv"):
            output_base = (
                output_file.rsplit(".", 1)[0] if "." in output_file else output_file
            )
            output_file = f"{output_base}.mkv"
            LOGGER.info(
                f"Changed output format to MKV to support all streams: {output_file}"
            )
        self.clear()

        # Create a temporary file listing all videos to concatenate
        list_file = f"{output_file}.list"
        async with aioopen(list_file, "w") as f:
            for video_file in video_files:
                await f.write(f"file '{video_file}'\n")

        # Calculate total duration for progress reporting
        total_duration = 0
        for video_file in video_files:
            duration = (await get_media_info(video_file))[0]
            total_duration += duration

        self._total_time = total_duration

        cmd = [
            BinConfig.FFMPEG_NAME,
            "-hide_banner",
            "-loglevel",
            "error",
            "-progress",
            "pipe:1",
            "-ignore_unknown",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            list_file,
            "-map",
            "0",
            "-c",
            "copy",
            "-threads",
            f"{max(1, cpu_no // 2)}",
            output_file,
            "-y",
        ]

        if self._listener.is_cancelled:
            return False

        self._listener.subproc = await create_subprocess_exec(
            *cmd, stdout=PIPE, stderr=PIPE
        )

        await self._ffmpeg_progress()
        _, stderr = await self._listener.subproc.communicate()
        code = self._listener.subproc.returncode

        # Clean up list file
        try:
            await remove(list_file)
        except:
            pass

        if self._listener.is_cancelled:
            return False

        if code == 0:
            # Verify and fix duration metadata if needed
            merged_duration, _, _ = await get_media_info(output_file)
            if merged_duration == 0 or abs(merged_duration - total_duration) > 10:
                LOGGER.warning(
                    f"Merged video duration ({merged_duration}s) doesn't match expected ({total_duration}s). Fixing metadata..."
                )
                await self._fix_video_duration(output_file, total_duration)
            return output_file
        elif code == -9:
            self._listener.is_cancelled = True
            return False
        else:
            try:
                stderr = stderr.decode().strip()
            except Exception:
                stderr = "Unable to decode the error!"

            # Check for common errors and provide better messages
            if "codec not currently supported in container" in stderr:
                LOGGER.error(f"{stderr}")
                LOGGER.error(
                    "Container format doesn't support some codecs (likely subtitle format)"
                )

                # Try again with MKV format if it's not already MKV
                if not output_file.lower().endswith(".mkv"):
                    new_output = output_file.rsplit(".", 1)[0] + ".mkv"
                    LOGGER.info(
                        f"Attempting to merge with MKV format which supports more codecs: {new_output}"
                    )

                    # Update command to use MKV output
                    cmd[-1] = new_output  # Replace output file

                    # Run the command again
                    self._listener.subproc = await create_subprocess_exec(
                        *cmd, stdout=PIPE, stderr=PIPE
                    )

                    await self._ffmpeg_progress()
                    _, stderr = await self._listener.subproc.communicate()
                    code = self._listener.subproc.returncode

                    if code == 0:
                        LOGGER.info("Successfully merged videos with MKV container")
                        # Verify and fix duration metadata if needed for MKV retry
                        merged_duration, _, _ = await get_media_info(new_output)
                        if (
                            merged_duration == 0
                            or abs(merged_duration - total_duration) > 10
                        ):
                            LOGGER.warning(
                                f"MKV merged video duration ({merged_duration}s) doesn't match expected ({total_duration}s). Fixing metadata..."
                            )
                            await self._fix_video_duration(new_output, total_duration)
                        return new_output
                    else:
                        try:
                            stderr = stderr.decode().strip()
                        except Exception:
                            stderr = "Unable to decode the error!"
                        LOGGER.error(f"Second attempt failed: {stderr}")
            else:
                LOGGER.error(f"{stderr}. Something went wrong while merging videos.")

            if await aiopath.exists(output_file):
                try:
                    await remove(output_file)
                except:
                    pass

            return False

    async def extract_streams(self, video_file, stream_indices, output_dir=None):
        """
        Extract specific audio and subtitle streams from a video file.

        Parameters:
        video_file (str): Path to the video file
        stream_indices (dict): Dictionary with stream types as keys and list of indices to extract as values
                            Example: {'audio': [0, 2], 'subtitle': [1, 3]}
        output_dir (str): Directory to save extracted streams, defaults to same directory as video

        Returns:
        dict: Paths of extracted streams by type and index
        """
        self.clear()
        duration = (await get_media_info(video_file))[0]
        self._total_time = duration

        if not output_dir:
            output_dir = ospath.dirname(video_file)

        # Get video filename without extension to use for naming extracted files
        video_basename = ospath.basename(video_file)
        video_name = ospath.splitext(video_basename)[0]

        # Use ffprobe to get detailed stream information
        try:
            probe_cmd = [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                video_file,
            ]
            process = await create_subprocess_exec(*probe_cmd, stdout=PIPE, stderr=PIPE)
            stdout, _ = await process.communicate()

            import json

            video_info = json.loads(stdout.decode())
            streams = video_info.get("streams", [])

            # Organize streams by type
            video_streams = []
            audio_streams = []
            subtitle_streams = []

            for idx, stream in enumerate(streams):
                stream_type = stream.get("codec_type")
                if stream_type == "video":
                    video_streams.append((idx, stream))
                elif stream_type == "audio":
                    audio_streams.append((idx, stream))
                elif stream_type == "subtitle":
                    subtitle_streams.append((idx, stream))

            LOGGER.info(
                f"Found {len(video_streams)} video, {len(audio_streams)} audio, and {len(subtitle_streams)} subtitle streams"
            )
        except Exception as e:
            LOGGER.error(f"Error analyzing video streams: {str(e)}")
            return {}

        extracted_files = {"audio": {}, "subtitle": {}}
        extract_commands = []

        # Process audio streams to extract
        if "audio" in stream_indices and audio_streams:
            for track_idx in stream_indices["audio"]:
                if track_idx < 0 or track_idx >= len(audio_streams):
                    LOGGER.warning(
                        f"Audio track index {track_idx} out of range (0-{len(audio_streams) - 1})"
                    )
                    continue

                stream_index, stream = audio_streams[track_idx]

                # Get language and title if available
                lang = "und"  # unknown language by default
                title = f"Track {track_idx}"

                if "tags" in stream:
                    if "language" in stream["tags"]:
                        lang = stream["tags"]["language"]
                    if "title" in stream["tags"]:
                        title = stream["tags"]["title"]

                # Determine best extension based on codec
                codec_name = stream.get("codec_name", "").lower()
                if codec_name in ("aac", "mp3", "m4a"):
                    ext = codec_name
                elif codec_name == "opus":
                    ext = "opus"
                elif codec_name in ("flac", "alac"):
                    ext = "flac"
                elif codec_name in ("ac3", "eac3"):
                    ext = "ac3"
                elif codec_name == "dts":
                    ext = "dts"
                elif codec_name in ("pcm_s16le", "pcm_s24le"):
                    ext = "wav"
                else:
                    ext = "mka"  # Matroska Audio for everything else

                output_file = ospath.join(
                    output_dir, f"{video_name}.audio{track_idx}.{lang}.{ext}"
                )

                cmd = [
                    BinConfig.FFMPEG_NAME,
                    "-hide_banner",
                    "-loglevel",
                    "warning",
                    "-progress",
                    "pipe:1",
                    "-i",
                    video_file,
                    "-map",
                    f"0:{stream_index}",  # Map only the selected stream
                    "-c",
                    "copy",  # Copy without re-encoding
                ]

                # Add language metadata
                if lang != "und":
                    cmd.extend(["-metadata:s:a:0", f"language={lang}"])

                # Add title metadata if available
                if title:
                    cmd.extend(["-metadata:s:a:0", f"title={title}"])

                cmd.extend(
                    [
                        "-threads",
                        f"{max(1, cpu_no // 4)}",  # Use fewer CPU threads
                        output_file,
                        "-y",
                    ]
                )

                extract_commands.append((cmd, output_file, f"audio{track_idx}", stream))

        # Process subtitle streams to extract
        if "subtitle" in stream_indices and subtitle_streams:
            for track_idx in stream_indices["subtitle"]:
                if track_idx < 0 or track_idx >= len(subtitle_streams):
                    LOGGER.warning(
                        f"Subtitle track index {track_idx} out of range (0-{len(subtitle_streams) - 1})"
                    )
                    continue

                stream_index, stream = subtitle_streams[track_idx]

                # Get language and title if available
                lang = "und"  # unknown language by default
                title = f"Subtitle {track_idx}"

                if "tags" in stream:
                    if "language" in stream["tags"]:
                        lang = stream["tags"]["language"]
                    if "title" in stream["tags"]:
                        title = stream["tags"]["title"]

                # Determine best extension based on codec
                codec_name = stream.get("codec_name", "").lower()
                if codec_name in ("subrip", "srt"):
                    ext = "srt"
                elif codec_name in ("ass", "ssa"):
                    ext = "ass"
                elif codec_name == "webvtt":
                    ext = "vtt"
                elif codec_name in ("dvd_subtitle", "dvbsub", "hdmv_pgs_subtitle"):
                    ext = "sup"  # PGS/SUP format for bitmap subtitles
                else:
                    ext = "srt"  # Default to SRT for unknown formats

                output_file = ospath.join(
                    output_dir, f"{video_name}.subtitle{track_idx}.{lang}.{ext}"
                )

                cmd = [
                    BinConfig.FFMPEG_NAME,
                    "-hide_banner",
                    "-loglevel",
                    "warning",
                    "-progress",
                    "pipe:1",
                    "-i",
                    video_file,
                    "-map",
                    f"0:{stream_index}",  # Map only the selected stream
                ]

                # For bitmap-based subtitles, we can only copy them
                # For text-based subtitles, we can ensure the correct format
                if codec_name in ("dvd_subtitle", "dvbsub", "hdmv_pgs_subtitle"):
                    cmd.extend(["-c", "copy"])
                else:
                    cmd.extend(["-c", ext])  # Convert to the desired subtitle format

                # Add language metadata
                if lang != "und":
                    cmd.extend(["-metadata:s:s:0", f"language={lang}"])

                # Add title metadata if available
                if title:
                    cmd.extend(["-metadata:s:s:0", f"title={title}"])

                cmd.extend(
                    [
                        "-threads",
                        f"{max(1, cpu_no // 4)}",  # Use fewer CPU threads
                        output_file,
                        "-y",
                    ]
                )

                extract_commands.append(
                    (cmd, output_file, f"subtitle{track_idx}", stream)
                )

        # Execute each extraction command
        for cmd, output_file, stream_id, stream_info in extract_commands:
            LOGGER.info(f"Extracting {stream_id} from {video_basename}...")

            if self._listener.is_cancelled:
                return extracted_files

            self._listener.subproc = await create_subprocess_exec(
                *cmd, stdout=PIPE, stderr=PIPE
            )

            await self._ffmpeg_progress()
            _, stderr = await self._listener.subproc.communicate()
            code = self._listener.subproc.returncode

            if self._listener.is_cancelled:
                return extracted_files

            if code == 0:
                LOGGER.info(f"Successfully extracted {stream_id} to {output_file}")
                stream_type = "audio" if "audio" in stream_id else "subtitle"
                track_num = int(stream_id.replace("audio", "").replace("subtitle", ""))

                # Store extracted file information
                extracted_files[stream_type][track_num] = {
                    "path": output_file,
                    "filename": ospath.basename(output_file),
                    "stream_info": stream_info,
                }
            elif code == -9:
                self._listener.is_cancelled = True
                return extracted_files
            else:
                try:
                    stderr_text = stderr.decode().strip()
                    LOGGER.error(f"Error extracting {stream_id}: {stderr_text}")
                except:
                    LOGGER.error(f"Error extracting {stream_id}: Unknown error")

        return extracted_files

    async def get_video_streams_info(self, video_file):
        """
        Get detailed information about streams in a video file.

        Parameters:
        video_file (str): Path to the video file

        Returns:
        dict: Dictionary containing stream information categorized by type
        """
        try:
            probe_cmd = [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                "-show_format",
                video_file,
            ]
            process = await create_subprocess_exec(*probe_cmd, stdout=PIPE, stderr=PIPE)
            stdout, _ = await process.communicate()

            import json

            video_info = json.loads(stdout.decode())
            streams = video_info.get("streams", [])
            format_info = video_info.get("format", {})

            # Organize streams by type
            result = {
                "format": {
                    "filename": format_info.get("filename", ""),
                    "duration": float(format_info.get("duration", 0)),
                    "size": int(format_info.get("size", 0)),
                    "bit_rate": int(format_info.get("bit_rate", 0)),
                    "format_name": format_info.get("format_name", ""),
                },
                "video": [],
                "audio": [],
                "subtitle": [],
                "other": [],
            }

            for idx, stream in enumerate(streams):
                stream_type = stream.get("codec_type")

                # Create a simplified stream info dict
                stream_info = {
                    "index": idx,
                    "codec_name": stream.get("codec_name", "unknown"),
                    "codec_long_name": stream.get("codec_long_name", ""),
                    "language": stream.get("tags", {}).get("language", "und"),
                    "title": stream.get("tags", {}).get("title", f"Stream #{idx}"),
                    "disposition": stream.get("disposition", {}),
                }

                # Add type-specific information
                if stream_type == "video":
                    stream_info.update(
                        {
                            "width": stream.get("width", 0),
                            "height": stream.get("height", 0),
                            "display_aspect_ratio": stream.get(
                                "display_aspect_ratio", ""
                            ),
                            "fps": eval(stream.get("r_frame_rate", "0/1")),
                            "bit_depth": stream.get("bits_per_raw_sample", "8"),
                        }
                    )
                    result["video"].append(stream_info)

                elif stream_type == "audio":
                    stream_info.update(
                        {
                            "channels": stream.get("channels", 0),
                            "channel_layout": stream.get("channel_layout", ""),
                            "sample_rate": stream.get("sample_rate", ""),
                            "bit_rate": stream.get("bit_rate", "0"),
                        }
                    )
                    result["audio"].append(stream_info)

                elif stream_type == "subtitle":
                    result["subtitle"].append(stream_info)

                else:
                    result["other"].append(stream_info)

            return result

        except Exception as e:
            LOGGER.error(f"Error getting video streams info: {str(e)}")
            return {
                "format": {"duration": 0, "size": 0, "format_name": "unknown"},
                "video": [],
                "audio": [],
                "subtitle": [],
                "other": [],
            }

    async def _fix_video_duration(self, video_file, expected_duration):
        """
        Fix video duration metadata by re-muxing the file

        Parameters:
        video_file (str): Path to the video file to fix
        expected_duration (float): Expected duration in seconds

        Returns:
        bool: True if successful, False otherwise
        """
        try:
            temp_file = f"{video_file}.temp"

            # Re-mux the file to fix duration metadata
            cmd = [
                BinConfig.FFMPEG_NAME,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                video_file,
                "-c",
                "copy",
                "-map",
                "0",
                "-movflags",
                "+faststart",
                "-fflags",
                "+genpts",
                temp_file,
                "-y",
            ]

            LOGGER.info("Re-muxing video to fix duration metadata...")
            process = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
            _, stderr = await process.communicate()
            code = process.returncode

            if code == 0:
                # Replace original file with fixed version
                await remove(video_file)
                import shutil

                await sync_to_async(shutil.move, temp_file, video_file)

                # Verify the fix worked
                fixed_duration, _, _ = await get_media_info(video_file)
                LOGGER.info(
                    f"Duration metadata fixed: {fixed_duration}s (expected: {expected_duration}s)"
                )
                return True
            else:
                try:
                    stderr = stderr.decode().strip()
                except Exception:
                    stderr = "Unable to decode the error!"
                LOGGER.error(f"Failed to fix duration metadata: {stderr}")

                # Clean up temp file if it exists
                if await aiopath.exists(temp_file):
                    try:
                        await remove(temp_file)
                    except:
                        pass
                return False

        except Exception as e:
            LOGGER.error(f"Error fixing video duration: {e}")
            return False
