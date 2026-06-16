from contextlib import suppress
from PIL import Image
from hashlib import md5
from aiofiles.os import (
    makedirs,
    remove,
    path as aiopath,
    listdir,
)
from asyncio import (
    create_subprocess_exec,
    gather,
    wait_for,
    sleep,
)
from json import loads as jsonloads
from asyncio.subprocess import PIPE
from os import path as ospath
from re import search as re_search, findall as re_findall, split as re_split
from time import time
from aioshutil import rmtree
from ... import LOGGER, cpu_no, DOWNLOAD_DIR
from langcodes import Language
import os
import asyncio

from ...core.config_manager import BinConfig
from .bot_utils import cmd_exec, sync_to_async, decode_output
from .files_utils import get_mime_type, is_archive, is_archive_split, get_path_size
from .status_utils import get_readable_file_size
from .ffmpeg_utils import _create_memory_aware_subprocess, _ff_threads


def get_md5_hash(up_path):
    md5_hash = md5()
    with open(up_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            md5_hash.update(byte_block)
        return md5_hash.hexdigest()


def draw_transparent_image(text: str, output_path: str, font_path: str = ""):
    font_size = 500
    font_path = (
        font_path
        if font_path and ospath.exists(font_path)
        else ospath.join(os.getcwd(), "wm.ttf")
    )

    image = None
    try:
        from PIL import (
            ImageDraw,
            ImageFont,
        )

        try:
            font = ImageFont.truetype(font_path, font_size)
        except (IOError, NameError, OSError):
            from PIL import ImageFont

            font = ImageFont.load_default()
            LOGGER.warning(f"Could not load font from {font_path}, using default font")

        dummy_image = Image.new("RGBA", (1, 1))
        dummy_draw = ImageDraw.Draw(dummy_image)
        bbox = dummy_draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        padding = 150
        image_width = text_width + 2 * padding
        image_height = text_height + 2 * padding

        image = Image.new("RGBA", (image_width, image_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        text_x = text_y = padding

        shadow_offset = (10, 10)
        shadow_color = "black"
        bold_offsets = [(-1, 0), (1, 0), (0, -1), (0, 1)]
        text_color = "white"

        shadow_position = (text_x + shadow_offset[0], text_y + shadow_offset[1])
        draw.text(shadow_position, text, font=font, fill=shadow_color)

        for offset in bold_offsets:
            bold_position = (text_x + offset[0], text_y + offset[1])
            draw.text(bold_position, text, font=font, fill=text_color)

        draw.text((text_x, text_y), text, font=font, fill=text_color)

        image.save(output_path, format="PNG")
        LOGGER.info(f"Successfully created transparent image: {output_path}")

    except Exception as e:
        LOGGER.error(f"Error creating transparent image: {e}")
        raise
    finally:
        if image:
            image.close()


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
        ffresult = jsonloads(result[0])
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
                if height >= 4320:
                    qual = "8K"
                elif height >= 2160:
                    qual = "4K"
                elif height >= 1440:
                    qual = "1440p"
                elif height >= 1080:
                    qual = "1080p"
                elif height >= 720:
                    qual = "720p"
                elif height >= 540:
                    qual = "540p"
                elif height >= 480:
                    qual = "480p"
                else:
                    qual = "360p"
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


async def get_meta_video(path: str):
    try:
        stdout, stderr, rcode = await cmd_exec(
            [
                BinConfig.FFPROBE_NAME,
                "-hide_banner",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                path,
            ]
        )
        if rcode != 0:
            LOGGER.error(f"ffprobe failed for {path}: {stderr}")
            return {}, {}

        metadata = jsonloads(stdout)
        streams = metadata.get("streams", {})
        format_info = metadata.get("format", {})

        return streams, format_info
    except Exception as e:
        LOGGER.error(f"Error getting video metadata for {path}: {e}")
        return {}, {}


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


async def get_audio_thumbnail(audio_file):
    output_dir = f"{DOWNLOAD_DIR}thumbnails"
    await makedirs(output_dir, exist_ok=True)
    output = ospath.join(output_dir, f"{time()}.jpg")
    cmd = [
        BinConfig.FFMPEG_NAME,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        audio_file,
        "-an",
        "-vcodec",
        "copy",
        "-ignore_unknown",  # Ignore unknown/corrupted metadata
        "-threads",
        f"{max(1, cpu_no // 2)}",
        output,
    ]
    try:
        _, err, code = await wait_for(cmd_exec(cmd), timeout=60)
        if code != 0 or not await aiopath.exists(output):
            LOGGER.error(
                f"Error while extracting thumbnail from audio. Name: {audio_file} stderr: {err}"
            )
            return None
    except Exception:
        LOGGER.error(
            f"Error while extracting thumbnail from audio. Name: {audio_file}. Error: Timeout some issues with ffmpeg with specific arch!"
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
    LOGGER.info(f"Generating SS Grid for: {video_file}")
    LOGGER.info(
        f"SS Grid parameters - Layout: {layout}, Count: {ss_count}, PDF Mode: {pdf_mode}, Watermark: {repr(watermark)}"
    )

    if not ss_count or ss_count <= 0:
        LOGGER.warning(f"Invalid SS Grid count: {ss_count}, defaulting to 9")
        ss_count = 9

    if not layout or "x" not in layout:
        LOGGER.warning(f"Invalid SS Grid layout: {layout}, defaulting to 3x3")
        layout = "3x3"

    LOGGER.info(f"Taking {ss_count} screenshots for SS Grid...")

    dirpath = await take_ss(video_file, ss_count)
    if not dirpath:
        LOGGER.error(f"Failed to take screenshots for SS Grid: {video_file}")
        return None
    LOGGER.info(f"Successfully took screenshots for SS Grid, storing in: {dirpath}")

    output_dir = f"{DOWNLOAD_DIR}thumbnails"
    await makedirs(output_dir, exist_ok=True)

    grid_output = ospath.join(output_dir, f"grid_{time()}.jpg")
    grid_cmd = [
        BinConfig.FFMPEG_NAME,
        "-hide_banner",
        "-loglevel",
        "error",
        "-pattern_type",
        "glob",
        "-i",
        f"'{dirpath}/*.png'",
        "-vf",
        f"tile={layout}, thumbnail",
        "-q:v",
        "1",
        "-frames:v",
        "1",
        "-f",
        "mjpeg",
        "-threads",
        str(_ff_threads()),  # Use optimized thread count
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
            await rmtree(dirpath, ignore_errors=True)
            return grid_output

        try:
            from PIL import (
                Image,
            )
            from reportlab.pdfgen import canvas

            pdf_output = ospath.join(output_dir, f"screenshots_{time()}.pdf")
            screenshot_files = await listdir(dirpath)
            screenshot_files = sorted(
                [f for f in screenshot_files if f.endswith(".png")]
            )
            screenshots = [ospath.join(dirpath, file) for file in screenshot_files]

            DOWNSCALE_MAX_WIDTH = 1280
            DOWNSCALE_MAX_HEIGHT = 720

            async def create_pdf():
                def _create_pdf():
                    PAGE_WIDTH = 1920
                    PAGE_HEIGHT = 1080
                    c = canvas.Canvas(pdf_output, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
                    width, height = PAGE_WIDTH, PAGE_HEIGHT
                    img = Image.open(grid_output)
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
                        grid_output,
                        x_offset,
                        y_offset,
                        width=new_width,
                        height=new_height,
                    )
                    file_title = os.path.basename(video_file)
                    font_size = 36
                    text_x = x_offset + 30
                    text_y = y_offset + new_height - 50
                    c.setFont("Helvetica-Bold", font_size)
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
                    if pdf_individual_pages:
                        for screenshot in screenshots:
                            img = Image.open(screenshot)
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
        self.mode = None
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
        # Memory management
        self._temp_files = []

    def _set_process_limits(self):
        """Set process resource limits to prevent system overload"""
        try:
            import resource

            # Set memory limit (512MB soft, 1GB hard)
            resource.setrlimit(
                resource.RLIMIT_AS, (512 * 1024 * 1024, 1024 * 1024 * 1024)
            )
            # Set CPU time limit (30 minutes per process)
            resource.setrlimit(resource.RLIMIT_CPU, (1800, 1800))
        except (ImportError, OSError, ValueError):
            # Resource module not available or limits can't be set
            pass

        try:
            # Set process priority to low
            os.nice(5)
        except (OSError, PermissionError):
            pass

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
        """Enhanced clear with memory cleanup"""
        self._start_time = time()
        self._processed_bytes = 0
        self._processed_time = 0
        self._speed_raw = 0
        self._progress_raw = 0
        self._eta_raw = 0
        self._time_rate = 0.1
        self._last_processed_time = 0
        self._last_processed_bytes = 0

        # Clean up temporary files
        for temp_file in self._temp_files:
            try:
                if ospath.exists(temp_file):
                    os.remove(temp_file)
            except Exception:
                pass
        self._temp_files.clear()

    async def ffmpeg_cmds(self, ffmpeg_cmd_list, f_path):
        self.clear()
        self.mode = "ffmpeg_generic_cmd"

        cmd_str = " ".join(f"'{c}'" if " " in c else c for c in ffmpeg_cmd_list)
        LOGGER.info(
            f"Task {self._listener.mid}: Executing FFmpeg command: {cmd_str} (Input hint: {f_path})"
        )

        try:
            self._total_time = (await get_media_info(f_path))[0]
            if self._total_time == 0:
                LOGGER.warning(
                    f"Task {self._listener.mid}: Duration of input {f_path} is 0. Percentage progress might be inaccurate or based on output size if available."
                )
        except Exception as e:
            LOGGER.warning(
                f"Task {self._listener.mid}: Could not get media duration for {f_path}: {e}. Percentage progress may be 0 or inaccurate."
            )
            self._total_time = 0

        if self._listener.is_cancelled:
            return False

        # Create subprocess with additional environment variables for resource control
        env = os.environ.copy()
        env["OMP_NUM_THREADS"] = "1"  # Limit OpenMP threads
        env["MKL_NUM_THREADS"] = "1"  # Limit MKL threads

        self._listener.subproc = await _create_memory_aware_subprocess(
            *ffmpeg_cmd_list,
            stdout=PIPE,
            stderr=PIPE,
            env=env,
            max_retries=2,
            wait_for_resources=True,
        )

        if not self._listener.subproc:
            raise RuntimeError(
                "Failed to create FFmpeg subprocess for screenshot generation"
            )

        stderr_lines = []
        max_stderr_lines = 100  # Reduced cap for memory efficiency

        async def log_stderr():
            async for line_bytes in self._listener.subproc.stderr:
                line = line_bytes.decode("utf-8", errors="ignore").strip()
                stderr_lines.append(line)
                if len(stderr_lines) > max_stderr_lines:
                    # Drop oldest chunk to cap memory
                    del stderr_lines[: max_stderr_lines // 2]
                LOGGER.debug(f"FFmpeg stderr (Task {self._listener.mid}): {line}")

        stderr_task = asyncio.create_task(log_stderr())
        await self._listener.subproc.wait()
        await stderr_task

        code = self._listener.subproc.returncode
        stderr_output = "\n".join(stderr_lines)

        if self._listener.is_cancelled:
            LOGGER.info(f"Task {self._listener.mid}: FFmpeg command cancelled.")
            if self._listener.subproc.returncode is None:
                try:
                    self._listener.subproc.kill()
                except ProcessLookupError:
                    pass
            return False

        if code == 0:
            LOGGER.info(
                f"Task {self._listener.mid}: FFmpeg command completed successfully. Stderr (if any): {stderr_output if stderr_output else 'None'}"
            )
            return True
        elif code == -9:
            self._listener.is_cancelled = True
            LOGGER.warning(
                f"Task {self._listener.mid}: FFmpeg command was killed (SIGKILL). Stderr: {stderr_output}"
            )
            return False
        else:
            LOGGER.error(
                f"Task {self._listener.mid}: FFmpeg command failed with code {code}. Input: {f_path}. Stderr: {stderr_output}"
            )
            return False

    async def convert_video(self, video_file, ext, retry=False):
        self.clear()
        self.mode = "convert"
        self._total_time = (await get_media_info(video_file))[0]
        # Ensure _total_time is numeric for progress calculations
        if not isinstance(self._total_time, (int, float)):
            self._total_time = 0
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
                str(_ff_threads()),  # Use optimized thread count
                "-preset",
                "veryfast",  # Use fast preset to reduce CPU load
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
                str(_ff_threads()),  # Use optimized thread count
                output,
            ]
        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await _create_memory_aware_subprocess(
            *cmd, stdout=PIPE, stderr=PIPE, max_retries=2, wait_for_resources=True
        )

        if not self._listener.subproc:
            LOGGER.error("Failed to create FFmpeg subprocess for video conversion")
            return False
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
            stderr = decode_output(stderr)
            LOGGER.error(
                f"{stderr}. Something went wrong while converting video, mostly file need specific codec. Path: {video_file}"
            )
        return False

    async def convert_audio(self, audio_file, ext):
        self.clear()
        self.mode = "convert_audio"
        self._total_time = (await get_media_info(audio_file))[0]
        # Ensure _total_time is numeric for progress calculations
        if not isinstance(self._total_time, (int, float)):
            self._total_time = 0
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
            str(_ff_threads()),  # Use optimized thread count
            output,
        ]
        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await _create_memory_aware_subprocess(
            *cmd, stdout=PIPE, stderr=PIPE, max_retries=2, wait_for_resources=True
        )

        if not self._listener.subproc:
            LOGGER.error("Failed to create FFmpeg subprocess for audio conversion")
            return False
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
            stderr = decode_output(stderr)
            LOGGER.error(
                f"{stderr}. Something went wrong while converting audio, mostly file need specific codec. Path: {audio_file}"
            )
            if await aiopath.exists(output):
                await remove(output)
        return False

    async def sample_video(self, video_file, sample_duration, part_duration):
        self.clear()
        self.mode = "sample_video"

        # Ensure sample_duration and part_duration are integers to prevent type errors
        try:
            sample_duration = int(sample_duration) if sample_duration else 60
            if sample_duration <= 0:
                sample_duration = 60
        except (ValueError, TypeError):
            sample_duration = 60

        try:
            part_duration = int(part_duration) if part_duration else 4
            if part_duration <= 0:
                part_duration = 4
        except (ValueError, TypeError):
            part_duration = 4

        # Detect 4K content for optimized processing
        try:
            from .ffmpeg_utils import detect_4k_content

            is_4k, video_info = await detect_4k_content(video_file)
            pixel_count = video_info.get("pixel_count", 0)

            if is_4k:
                LOGGER.info(f"4K content detected for sampling: {video_file}")
                # Reduce sample duration for 4K to prevent memory issues
                max_4k_sample = min(sample_duration, 30)  # Max 30s for 4K
                if sample_duration > max_4k_sample:
                    LOGGER.warning(
                        f"Reducing sample duration from {sample_duration}s to {max_4k_sample}s for 4K content"
                    )
                    sample_duration = max_4k_sample

                # Shorter parts for 4K to reduce memory per segment
                if part_duration > 3:
                    part_duration = 3
                    LOGGER.info("Reducing part duration to 3s for 4K content")

        except Exception as e:
            LOGGER.debug(f"4K detection failed for sampling: {e}")
            is_4k = False

        self._total_time = sample_duration
        dir, name = video_file.rsplit("/", 1)
        output_file = f"{dir}/SAMPLE.{name}"
        segments = [(0, part_duration)]
        duration = (await get_media_info(video_file))[0]
        # Ensure duration is numeric to prevent type errors
        if not isinstance(duration, (int, float)) or duration <= 0:
            LOGGER.warning(
                f"Invalid video duration for {video_file}, skipping sample generation"
            )
            return False

        # More aggressive sample duration limits for high-resolution content
        if is_4k:
            max_allowed_sample = min(
                int(duration * 0.15), 30
            )  # 15% max for 4K, capped at 30s
        else:
            max_allowed_sample = int(duration * 0.25)  # 25% max for non-4K

        if sample_duration > max_allowed_sample:
            LOGGER.warning(
                f"Sample duration {sample_duration}s exceeds limit for {'4K' if is_4k else 'HD'} content, "
                f"reducing to {max_allowed_sample}s for memory safety"
            )
            sample_duration = max_allowed_sample

        # Skip if video is too short for meaningful sampling
        if duration < part_duration + 10:
            LOGGER.info(
                f"Video too short ({duration}s) for sample generation, skipping"
            )
            return False
        remaining_duration = duration - (part_duration * 2)
        parts = (sample_duration - (part_duration * 2)) // part_duration
        # Prevent division by zero
        if parts <= 0:
            parts = 1
        time_interval = remaining_duration // parts
        next_segment = time_interval
        for _ in range(parts):
            segments.append((next_segment, next_segment + part_duration))
            next_segment += time_interval
        segments.append((duration - part_duration, duration))

        filter_complex = ""
        for i, (start, end) in enumerate(segments):
            # Use simple trim without scaling to avoid filter syntax issues
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
        ]

        # Add 4K-specific encoding parameters
        if is_4k:
            cmd.extend(
                [
                    "-preset",
                    "ultrafast",  # Ultra-fast for 4K to minimize CPU usage
                    "-tune",
                    "zerolatency",  # Low latency for 4K
                    "-crf",
                    "32",  # Higher CRF for 4K to reduce size and memory
                    "-x264opts",
                    "ref=1:bframes=0:me=dia:subq=1:trellis=0",  # Minimal settings for 4K
                    "-max_muxing_queue_size",
                    "64",  # Smaller queue for 4K
                ]
            )
        else:
            cmd.extend(
                [
                    "-preset",
                    "veryfast",
                    "-crf",
                    "28",  # Higher CRF for smaller file size and lower memory usage
                ]
            )

        cmd.extend(
            [
                "-c:a",
                "aac",
                "-b:a",
                "96k" if is_4k else "128k",  # Lower audio bitrate for 4K to save memory
                "-movflags",
                "+faststart",
                "-pix_fmt",
                "yuv420p",
                "-shortest",
                "-threads",
                str(_ff_threads()),  # Use optimized thread count
                output_file,
            ]
        )
        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await _create_memory_aware_subprocess(
            *cmd, stdout=PIPE, stderr=PIPE, max_retries=2, wait_for_resources=True
        )

        if not self._listener.subproc:
            LOGGER.error(
                "Failed to create FFmpeg subprocess for sample video generation"
            )
            return False
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
        split_size -= 3000000
        start_time = 0
        i = 1
        while i <= parts or start_time < duration - 4:
            out_path = ospath.join(
                ospath.dirname(f_path), f"{base_name}.part{i:03}{extension}"
            )
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
                    "-threads",
                    str(_ff_threads()),  # Use optimized thread count
                    out_path,
                ]
            )

            if self._listener.is_cancelled:
                return False
            self._listener.subproc = await create_subprocess_exec(
                *cmd, stdout=PIPE, stderr=PIPE
            )
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


class FFProgress:
    def __init__(self):
        self.outfile = ""
        self._duration = 0
        self._start_time = time()
        self._eta = 0
        self._percentage = 0.0
        self._processed_bytes = 0

    @property
    def processed_bytes(self):
        return self._processed_bytes

    @property
    def percentage(self):
        return self._percentage

    @property
    def eta(self):
        return self._eta

    @property
    def speed(self):
        return (
            self._processed_bytes / (time() - self._start_time)
            if self._processed_bytes > 0
            else 0
        )

    async def update_progress_from_pipe(
        self, percentage_float, processed_bytes_val, eta_seconds, speed_multiplier_str
    ):
        # Store previous values for comparison
        prev_percentage = self._percentage
        prev_bytes = self._processed_bytes

        self._processed_bytes = processed_bytes_val
        try:
            self._percentage = round(float(percentage_float), 2)
        except ValueError:
            LOGGER.warning(
                f"FFProgress: Could not convert percentage '{percentage_float}' to float. Defaulting to 0.0."
            )
            self._percentage = 0.0
        self._eta = eta_seconds
        if hasattr(self, "_speed_multiplier_raw"):
            self._speed_multiplier_raw = speed_multiplier_str
        else:
            self._speed_multiplier_raw = speed_multiplier_str

        # Log progress updates for debugging stuck issues
        if self._percentage != prev_percentage or self._processed_bytes != prev_bytes:
            elapsed = time() - self._start_time
            if elapsed > 30 and self._percentage < 5:  # Log if slow progress after 30s
                LOGGER.info(
                    f"FFProgress update: {self._percentage}% ({self._processed_bytes} bytes) after {elapsed:.1f}s"
                )

        # Ensure minimum progress for long-running operations
        if self._percentage <= 0 and (time() - self._start_time) > 60:
            # Show minimal progress to indicate activity
            elapsed_minutes = (time() - self._start_time) / 60
            self._percentage = min(
                2.0, elapsed_minutes * 0.5
            )  # 0.5% per minute, max 2%

    @staticmethod
    async def read_lines(stream):
        data = bytearray()
        while not stream.at_eof():
            lines = re_split(rb"[\r\n]+", data)
            data[:] = lines.pop(-1)
            for line in lines:
                yield line
            data.extend(await stream.read(1024))

    async def progress(self, status: str = ""):
        start_time = time()
        # Choose the correct stream: ffmpeg -progress pipe:1 writes to stdout
        stream = (
            self.listener.subproc.stdout
            if status == "pipe"
            else self.listener.subproc.stderr
        )
        async for line in self.read_lines(stream):
            if (
                self.listener.is_cancelled
                or self.listener.subproc.returncode is not None
            ):
                return
            if status == "direct":
                self._processed_bytes = await get_path_size(self.outfile)
                if self.listener.size > 0:
                    self._percentage = round(
                        (self._processed_bytes / self.listener.size) * 100, 2
                    )
                await sleep(0.5)
                continue
            if status == "pipe":
                # Parse -progress key=value lines
                text = decode_output(line).strip()
                if not text or "=" not in text:
                    continue
                key, val = text.split("=", 1)
                key = key.strip().lower()
                val = val.strip()
                # Accumulate into a simple dict frame
                if not hasattr(self, "_pipe_frame"):
                    self._pipe_frame = {}
                self._pipe_frame[key] = val
                if key == "progress":
                    # When a progress frame ends, compute stats
                    frame = getattr(self, "_pipe_frame", {})
                    # out_time_us or out_time
                    try:
                        if "out_time_us" in frame:
                            time_sec = float(frame["out_time_us"]) / 1_000_000.0
                        elif "out_time" in frame:
                            # format hh:mm:ss.micro
                            h, m, s = frame["out_time"].split(":")
                            time_sec = (int(h) * 3600) + (int(m) * 60) + float(s)
                        else:
                            time_sec = 0.0
                    except Exception:
                        time_sec = 0.0
                    # bytes processed
                    try:
                        out_size = int(
                            frame.get("total_size") or frame.get("size") or 0
                        )
                    except Exception:
                        out_size = 0
                    self._processed_bytes = max(self._processed_bytes, out_size)
                    # duration
                    if not self._duration:
                        try:
                            self._duration = (await get_media_info(self.path))[0]
                        except Exception:
                            self._duration = 0
                    if self._duration > 0 and time_sec >= 0:
                        self._percentage = min(100.0, (time_sec / self._duration) * 100)
                    elif self.listener.size > 0 and self._processed_bytes >= 0:
                        self._percentage = (
                            self._processed_bytes / self.listener.size
                        ) * 100
                    else:
                        self._percentage = 0.0
                    # ETA via speed (e.g., 1.5x) if provided
                    try:
                        speed_mult = (
                            frame.get("speed", "1x").strip().lower().rstrip("x")
                        )
                        sm = float(speed_mult) if speed_mult else 1.0
                        if self._duration > 0 and sm > 0:
                            self._eta = (self._duration / sm) - (time() - start_time)
                        elif self.listener.size > 0 and self.speed > 0:
                            remaining = max(
                                0, self.listener.size - self._processed_bytes
                            )
                            self._eta = remaining / self.speed
                    except Exception:
                        pass
                    # Clear frame for next cycle
                    self._pipe_frame.clear()
                continue
            if progress := dict(
                re_findall(
                    r"(frame|fps|size|time|bitrate|speed)\s*\=\s*(\S+)",
                    decode_output(line),
                )
            ):
                if not self._duration:
                    self._duration = (await get_media_info(self.path))[0]
                try:
                    hh, mm, sms = progress["time"].split(":")
                except Exception:
                    continue
                time_to_second = (int(hh) * 3600) + (int(mm) * 60) + float(sms)
                self._processed_bytes = (
                    int(re_search(r"\d+", progress["size"]).group()) * 1024
                )
                if self._duration > 0:
                    self._percentage = (time_to_second / self._duration) * 100
                else:
                    # Fallback: compute progress based on output size when duration is unavailable
                    if self.listener.size > 0 and self._processed_bytes >= 0:
                        self._percentage = (
                            self._processed_bytes / self.listener.size
                        ) * 100
                    else:
                        self._percentage = 0.0
                try:
                    self._eta = (
                        self._duration / float(progress["speed"].strip("x"))
                    ) - (time() - start_time)
                except Exception:
                    # Fallback ETA using bytes and computed speed
                    try:
                        speed_multiplier = progress.get("speed", "1x").strip("x")
                        sm = float(speed_multiplier) if speed_multiplier else 1.0
                        # Estimate speed in B/s when duration missing using processed bytes delta/time
                        if sm > 0 and self.listener.size > 0:
                            remaining = max(
                                0, self.listener.size - self._processed_bytes
                            )
                            # Avoid division by zero
                            self._eta = remaining / max(1.0, self.speed)
                    except Exception:
                        pass


async def create_reply_thumbnail(message, user_id):
    thumb_dir = "thumbnails"
    thumb_path = f"{thumb_dir}/{user_id}.jpg"
    await makedirs(thumb_dir, exist_ok=True)

    if not message.photo:
        LOGGER.info(
            f"Replied message from user {message.from_user.id if message.from_user else 'N/A'} to set thumb for {user_id} does not contain a photo."
        )
        return None

    temp_photo_dir = await message.download()
    await sync_to_async(
        Image.open(temp_photo_dir).convert("RGB").save, thumb_path, "JPEG"
    )
    await remove(temp_photo_dir)
    LOGGER.info(f"Thumbnail saved for user {user_id} at {thumb_path}")
    return thumb_path
