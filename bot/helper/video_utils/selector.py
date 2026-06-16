from asyncio import Event, wait_for, gather
from functools import partial
from os import path as ospath
from re import match as re_match
from time import time
from html import escape

from PIL import Image
from aiofiles.os import makedirs
from pyrogram.filters import regex, user
from pyrogram.handlers import MessageHandler, CallbackQueryHandler
from pyrogram.types import Message, CallbackQuery

from ... import videos_tools_mode, DOWNLOAD_DIR
from ...core.config_manager import Config
from ..ext_utils.bot_utils import new_task, sync_to_async
from ..ext_utils.files_utils import clean_target
from ..ext_utils.links_utils import is_media
from ..ext_utils.status_utils import get_readable_time
from ..telegram_helper.button_build import ButtonMaker
from ..telegram_helper.message_utils import (
    send_messagee as send_message,
    edit_messagee as edit_message,
    delete_message,
    send_photo,
)


class SelectMode:
    def __init__(self, listener, is_link: bool = False):
        self._isLink = is_link
        self._time = time()
        self._reply = None
        self.listener = listener
        self.is_rename = False
        self.multi_mode = False
        self.mode = ""
        self.extra_data = {}
        self.new_name = ""
        self.wm_text = ""
        self.awaiting_wm_font = False
        self.awaiting_intro_font = False
        self.awaiting_intro_colors = False
        self.event = Event()
        self.message_event = Event()

    async def _event_handler(self):
        pfunc = partial(vidtools_callback, obj=self)
        handler = self.listener.client.add_handler(
            CallbackQueryHandler(
                pfunc, filters=regex("^vidtool") & user(self.listener.user_id)
            ),
            group=-1,
        )
        try:
            await wait_for(self.event.wait(), timeout=180)
        except Exception:
            self.mode = "Task has been cancelled, time out!"
            self.listener.is_cancelled = True
            self.event.set()
        finally:
            self.listener.client.remove_handler(*handler)
            self.event.clear()

    async def message_event_handler(self, mode: str = ""):
        pfunc = partial(message_handler, obj=self, is_sub=mode == "sub_file")
        handler = self.listener.client.add_handler(
            MessageHandler(pfunc, user(self.listener.user_id)), group=-1
        )
        try:
            await wait_for(self.message_event.wait(), timeout=60)
        except Exception:
            self.message_event.set()
        finally:
            self.listener.client.remove_handler(*handler)
            self.message_event.clear()

    async def _send_message(self, text: str, buttons):
        if not self._reply:
            self._reply = await send_message(text, self.listener.message, buttons)
        else:
            await edit_message(text, self._reply, buttons)

    def _captions(self, mode: str = ""):
        # Enhanced UI implementation with bold/italic formatting
        vidmode = videos_tools_mode.get(self.mode)
        status_lines = [
            f"├ <b>📁 File</b>: <i>{self.new_name or 'Default'}</i>",
            f"├ <b>🔧 Mode</b>: <i>{vidmode or 'Selecting Tool...'}</i>",
        ]

        if self.mode == "trim" and self.extra_data:
            status_lines.append(
                f"├ <b>✂️ Trim</b>: <i>{self.extra_data.get('start_time', 'N/A')} → {self.extra_data.get('end_time', 'N/A')}</i>"
            )
        if self.mode in ("vid_sub", "watermark"):
            hardsub = self.extra_data.get("hardsub")
            status_lines.append(
                f"├ <b>🎬 Encode</b>: <i>{'✅ Yes' if hardsub else '❌ No'}</i>"
            )
        if quality := self.extra_data.get("quality"):
            status_lines.append(f"├ <b>📐 Quality</b>: <i>{quality}</i>")
        # Show codec and format for relevant modes
        if self.mode in ("convert", "compress", "watermark", "multi_res") and (
            codec := self.extra_data.get("codec")
        ):
            status_lines.append(f"├ <b>🎥 Codec</b>: <i>{codec}</i>")
        if self.mode == "convert" and (fmt := self.extra_data.get("format")):
            status_lines.append(f"├ <b>🗂️ Format</b>: <i>.{fmt.lower()}</i>")
        if self.mode == "multi_res":
            if self.extra_data.get("multi_resolution"):
                status_lines.append("├ <b>🎬 Multi-Res</b>: <i>✅ Enabled</i>")
                if res_list := self.extra_data.get("resolution_list"):
                    status_lines.append(f"├ <b>📐 Res List</b>: <i>{res_list}</i>")
            else:
                status_lines.append("├ <b>🎬 Multi-Res</b>: <i>❌ Disabled</i>")
            if self.extra_data.get("multi_zip"):
                status_lines.append("├ <b>📦 Multi-Zip</b>: <i>✅ Enabled</i>")
            else:
                status_lines.append("├ <b>📦 Multi-Zip</b>: <i>❌ Disabled</i>")
        if self.mode == "watermark" and (wm_size := self.extra_data.get("wm_size")):
            status_lines.append(f"├ <b>💧 WM Size</b>: <i>{wm_size}%</i>")
            if wm_pos := self.extra_data.get("wm_position"):
                status_lines.append(f"├ <b>📍 WM Position</b>: <i>{wm_pos}</i>")
            if wm_popup := self.extra_data.get("wm_popup"):
                status_lines.append(f"├ <b>🔁 Popup</b>: <i>every {wm_popup}s</i>")
        if self.mode == "intro_sub":
            u = getattr(self.listener, "user_dict", {}) or {}
            text_val = self.extra_data.get("text") or u.get("INTRO_SUBTITLE_TEXT")
            if text_val:
                status_lines.append(f"├ <b>📝 Text</b>: <i>{text_val}</i>")
            size_val = self.extra_data.get("font_size") or u.get(
                "INTRO_SUBTITLE_FONT_SIZE"
            )
            if size_val:
                status_lines.append(f"├ <b>🔤 Size</b>: <i>{size_val}</i>")
            pos_val = self.extra_data.get("position") or u.get(
                "INTRO_SUBTITLE_POSITION"
            )
            if pos_val:
                status_lines.append(f"├ <b>📍 Position</b>: <i>{pos_val}</i>")
            style_val = self.extra_data.get("style") or u.get("INTRO_SUBTITLE_STYLE")
            if style_val:
                status_lines.append(f"├ <b>✨ Style</b>: <i>{style_val}</i>")
            cms_val = self.extra_data.get("char_ms") or u.get("INTRO_SUBTITLE_CHAR_MS")
            if cms_val:
                status_lines.append(f"├ <b>⏱️ Char MS</b>: <i>{cms_val}</i>")
            colors_val = self.extra_data.get("colors") or u.get("INTRO_SUBTITLE_COLORS")
            if colors_val:
                status_lines.append(f"├ <b>🎨 Colors</b>: <i>{colors_val}</i>")
            if self.extra_data.get("font_path") or u.get("INTRO_SUBTITLE_FONT_PATH"):
                status_lines.append(
                    f"├ <b>🅵 Font</b>: <i>{'Custom' if (self.extra_data.get('font_path') or u.get('INTRO_SUBTITLE_FONT_PATH')) else 'Default'}</i>"
                )
            elif u.get("VT_WM_FONT_PATH"):
                status_lines.append("├ <b>🅵 Font</b>: <i>Custom (WM)</i>")

        # Enhanced status block formatting
        if status_lines:
            status_block = (
                "╭💡 <b><i>Current Configuration</i></b>\n"
                + "\n".join(status_lines)
                + "\n╰"
            )
        else:
            status_block = ""

        instruction_lines = []
        if mode == "rename":
            instruction_lines.append("Send a new filename with extension.")
        elif mode == "watermark":
            instruction_lines.append("Send an image or text for the watermark.")
        elif mode == "sub_file":
            instruction_lines.append("Send a subtitle file (.srt, .ass).")
        elif mode == "trim":
            instruction_lines.append("Send trim duration: `hh:mm:ss hh:mm:ss`")
        elif mode == "wm_size":
            instruction_lines.append(
                "Choose watermark size (in % of input image width)"
            )
        elif mode == "wm_position":
            instruction_lines.append("Choose watermark position")
        elif mode == "wm_font":
            instruction_lines.append(
                "Choose Default font or Upload a .ttf/.otf font (send as document)"
            )
        elif mode == "intro_text":
            instruction_lines.append("Send Intro Sub text.")
        elif mode == "intro_font":
            instruction_lines.append(
                "Choose Default font or Upload a .ttf/.otf font (send as document)"
            )
        elif mode == "intro_char_ms":
            instruction_lines.append(
                "Choose per-character duration in ms (typing style)"
            )
        elif mode == "intro_colors":
            instruction_lines.append(
                "Choose a color preset or select Custom to send your own list (names or #hex separated by | or space)"
            )
        elif mode == "resolution_list":
            instruction_lines.append(
                "Send comma-separated resolution list (e.g., 1080p,720p,480p)"
            )
        else:
            instruction_lines.append("Choose a tool from the main menu")
            instruction_lines.append("to begin editing your video.")

        # Enhanced instruction formatting with decorative elements
        if instruction_lines:
            if len(instruction_lines) == 1:
                instruction_block = (
                    f"\n╭ℹ️ <b><i>Instructions</i></b>\n├ {instruction_lines[0]}\n╰"
                )
            else:
                instruction_block = f"\n╭ℹ️ <b><i>Instructions</i></b>\n"
                for i, line in enumerate(instruction_lines):
                    if i == len(instruction_lines) - 1:
                        instruction_block += f"╰ {line}"
                    else:
                        instruction_block += f"├ {line}\n"
        else:
            instruction_block = ""

        # Enhanced header with decorative elements and bold formatting
        header_name = self.new_name or "Default"
        timeout_value = get_readable_time(180 - (time() - self._time))

        user_name = escape(self.listener.message.from_user.first_name)
        msg = f"""<b><i>📹 VIDEOS TOOL SETTINGS ~ {user_name}</i></b>

╭💡 <b>Name</b>: <i>{header_name}</i>
├ <b>Time Out</b>: <b>{timeout_value}</b>
╰ <i>Choose tools and customize your video processing</i>"""

        # Add status block if available
        if status_block:
            msg += f"\n\n{status_block}"

        # Add instruction block if available
        if instruction_block:
            msg += instruction_block

        return msg

    async def list_buttons(self, mode: str = ""):
        buttons, bnum, hnum = ButtonMaker(), 2, 3
        if not mode:
            vid_modes = (
                dict(list(videos_tools_mode.items())[4:])
                if self._isLink
                else videos_tools_mode
            )
            [
                buttons.data_button(
                    f"{'✅ ' if self.mode == key else ''}{value}", f"vidtool {key}"
                )
                for key, value in vid_modes.items()
            ]
            buttons.data_button(
                f"{'✅ ' if self.multi_mode else ''}Multi VT", "vidtool multi", "header"
            )
            buttons.data_button(
                f"{'✅ ' if self.new_name else ''}Rename", "vidtool rename", "header"
            )
            buttons.data_button("Cancel", "vidtool cancel", "footer")
            if self.mode:
                buttons.data_button("Done", "vidtool done", "footer")
            if self.mode == "convert":
                hnum = 2
                # Add codec selection for convert mode
                buttons.data_button(
                    f"{'✅ ' if self.extra_data.get('codec') else ''}Codec",
                    "vidtool codec",
                    "header",
                )
                # Add format selection for convert feature
                buttons.data_button(
                    f"{'✅ ' if self.extra_data.get('format') else ''}Format",
                    "vidtool format",
                    "header",
                )
            if self.mode in ("compress", "watermark") or self.extra_data.get("hardsub"):
                buttons.data_button(
                    f"{'✅ ' if self.extra_data.get('preset') else ''}Preset",
                    "vidtool preset",
                    "header",
                )
                buttons.data_button("Quality", "vidtool quality", "header")
                # Add codec selection for compress and watermark modes
                buttons.data_button(
                    f"{'✅ ' if self.extra_data.get('codec') else ''}Codec",
                    "vidtool codec",
                    "header",
                )
                # Add format selection for convert feature
                buttons.data_button(
                    f"{'✅ ' if self.extra_data.get('format') else ''}Format",
                    "vidtool format",
                    "header",
                )
            # Provide a visible toggle to enable/disable hardsub for relevant modes
            if self.mode in ("watermark", "vid_sub"):
                buttons.data_button(
                    f"{'✅ ' if self.extra_data.get('hardsub') else '❌ '}Hardsub",
                    "vidtool hardsub",
                    "header",
                )
            if self.mode == "multi_res":
                buttons.data_button(
                    f"{'✅ ' if self.extra_data.get('multi_resolution') else ''}Multi-Res",
                    "vidtool multi_resolution",
                    "header",
                )
                buttons.data_button(
                    f"{'✅ ' if self.extra_data.get('multi_zip') else ''}Multi-Zip",
                    "vidtool multi_zip",
                    "header",
                )
                buttons.data_button(
                    "Resolution List", "vidtool resolution_list", "header"
                )
                # Add codec selection for multi-resolution mode
                buttons.data_button(
                    f"{'✅ ' if self.extra_data.get('codec') else ''}Codec",
                    "vidtool codec",
                    "header",
                )
            if self.mode == "watermark":
                buttons.data_button(
                    f"{'✅ ' if self.extra_data.get('wm_popup') else ''}Popup",
                    "vidtool wm_popup",
                    "header",
                )
            if self.mode == "intro_sub":
                buttons.data_button(
                    f"{'✅ ' if self.extra_data.get('font_size') else ''}Size",
                    "vidtool intro_font_size",
                    "header",
                )
                buttons.data_button(
                    f"{'✅ ' if self.extra_data.get('position') else ''}Position",
                    "vidtool intro_position",
                    "header",
                )
                buttons.data_button(
                    f"{'✅ ' if self.extra_data.get('style') else ''}Style",
                    "vidtool intro_style",
                    "header",
                )
                buttons.data_button(
                    f"{'✅ ' if self.extra_data.get('text') else ''}Text",
                    "vidtool intro_text",
                    "header",
                )
                buttons.data_button(
                    f"{'✅ ' if self.extra_data.get('font_path') else ''}Font",
                    "vidtool intro_font",
                    "header",
                )
                buttons.data_button(
                    f"{'✅ ' if self.extra_data.get('char_ms') else ''}Char MS",
                    "vidtool intro_char_ms",
                    "header",
                )
                buttons.data_button(
                    f"{'✅ ' if self.extra_data.get('colors') else ''}Colors",
                    "vidtool intro_colors",
                    "header",
                )
        else:
            match mode:
                case "quality":
                    bnum = 3
                    buttons.data_button(
                        f"{'✅ ' if self.extra_data.get('preset') else ''}Preset",
                        "vidtool preset",
                        "header",
                    )
                    buttons.data_button(
                        f"{'✅ ' if self.extra_data.get('bitrate') else ''}Bitrate",
                        "vidtool bitrate",
                        "header",
                    )
                    buttons.data_button(
                        f"{'✅ ' if self.extra_data.get('crf') else ''}CRF",
                        "vidtool crf",
                        "header",
                    )
                    [
                        buttons.data_button(
                            f"{'✅ ' if self.extra_data.get('quality') == key else ''}{key}",
                            f"vidtool quality {key}",
                        )
                        for key in ["1080p", "720p", "540p", "480p", "360p"]
                    ]
                    buttons.data_button("<<", "vidtool back", "footer")
                    buttons.data_button("Done", "vidtool done", "footer")
                case "preset":
                    bnum = 3
                    [
                        buttons.data_button(
                            f"{'✅ ' if self.extra_data.get('preset') == preset else ''}{preset}",
                            f"vidtool preset {preset}",
                        )
                        for preset in [
                            "ultrafast",
                            "superfast",
                            "veryfast",
                            "faster",
                            "fast",
                            "medium",
                            "slow",
                            "slower",
                            "veryslow",
                        ]
                    ]
                    buttons.data_button("<<", "vidtool back", "footer")
                    buttons.data_button("Done", "vidtool done", "footer")
                case "bitrate":
                    bnum = 3
                    [
                        buttons.data_button(
                            f"{'✅ ' if self.extra_data.get('bitrate') == bitrate else ''}{bitrate}",
                            f"vidtool bitrate {bitrate}",
                        )
                        for bitrate in [
                            "96k",
                            "128k",
                            "160k",
                            "192k",
                            "224k",
                            "256k",
                            "320k",
                            "384k",
                        ]
                    ]
                    buttons.data_button("<<", "vidtool back", "footer")
                    buttons.data_button("Done", "vidtool done", "footer")
                case "crf":
                    bnum = 4
                    [
                        buttons.data_button(
                            f"{'✅ ' if self.extra_data.get('crf') == str(crf) else ''}{crf}",
                            f"vidtool crf {crf}",
                        )
                        for crf in [18, 20, 22, 23, 24, 26, 28, 30, 32, 35]
                    ]
                    buttons.data_button("<<", "vidtool back", "footer")
                    buttons.data_button("Done", "vidtool done", "footer")
                case "codec":
                    bnum = 2
                    # Get user's current codec preference
                    user_dict = getattr(self.listener, "user_dict", {}) or {}
                    current_codec = self.extra_data.get("codec") or user_dict.get(
                        "VIDEO_CONVERT_CODEC", "auto"
                    )

                    codec_options = ["copy", "x264", "x265", "auto"]
                    for codec in codec_options:
                        buttons.data_button(
                            f"{'✅ ' if current_codec == codec else ''}{codec}",
                            f"vidtool codec {codec}",
                        )
                    buttons.data_button("<<", "vidtool back", "footer")
                    buttons.data_button("Done", "vidtool done", "footer")
                case "wm_size":
                    bnum = 4
                    [
                        buttons.data_button(str(btn), f"vidtool wm_size {btn}")
                        for btn in [5, 10, 15, 20, 25, 30, 40, 50]
                    ]
                    buttons.data_button("<<", "vidtool back", "footer")
                    buttons.data_button("Done", "vidtool done", "footer")
                case "wm_position":
                    buttons.data_button("Top Left", "vidtool wm_position 5:5", "header")
                    buttons.data_button(
                        "Top Center",
                        "vidtool wm_position (main_w-overlay_w)/2:5",
                        "header",
                    )
                    buttons.data_button(
                        "Top Right",
                        "vidtool wm_position main_w-overlay_w-5:5",
                        "header",
                    )
                    buttons.data_button(
                        "Center",
                        "vidtool wm_position (main_w-overlay_w)/2:(main_h-overlay_h)/2",
                    )
                    buttons.data_button(
                        "Bottom Left",
                        "vidtool wm_position 5:main_h-overlay_h",
                        "footer",
                    )
                    buttons.data_button(
                        "Bottom Center",
                        "vidtool wm_position (main_w-overlay_w)/2:main_h-overlay_h-5",
                        "footer",
                    )
                    buttons.data_button(
                        "Bottom Right",
                        "vidtool wm_position main_w-overlay_w-5:main_h-overlay_h-5",
                        "footer",
                    )
                    buttons.data_button("<<", "vidtool back", "footer")
                    buttons.data_button("Done", "vidtool done", "footer")
                case "wm_popup":
                    bnum = 5
                    current = self.extra_data.get("wm_popup", 0)
                    if current:
                        buttons.data_button("Reset", "vidtool wm_popup 0", "header")
                    [
                        buttons.data_button(
                            f"{'✅ ' if current == key else ''}{key}",
                            f"vidtool wm_popup {key}",
                        )
                        for key in range(2, 21, 2)
                    ]
                    buttons.data_button("<<", "vidtool back", "footer")
                    buttons.data_button("Done", "vidtool done", "footer")
                case "wm_font":
                    bnum = 2
                    buttons.data_button("Default Font", "vidtool wm_font default")
                    buttons.data_button("Upload Font", "vidtool wm_font upload")
                    buttons.data_button("<<", "vidtool back", "footer")
                    buttons.data_button("Done", "vidtool done", "footer")
                case "intro_font_size":
                    bnum = 4
                    for fs in [24, 36, 48, 60, 72]:
                        buttons.data_button(
                            f"{'✅ ' if self.extra_data.get('font_size') == fs else ''}{fs}",
                            f"vidtool intro_font_size {fs}",
                        )
                    buttons.data_button("<<", "vidtool back", "footer")
                    buttons.data_button("Done", "vidtool done", "footer")
                case "intro_position":
                    for label, pos in [
                        ("Top", "top"),
                        ("Center", "center"),
                        ("Bottom", "bottom"),
                    ]:
                        buttons.data_button(
                            f"{'✅ ' if self.extra_data.get('position') == pos else ''}{label}",
                            f"vidtool intro_position {pos}",
                        )
                    buttons.data_button("<<", "vidtool back", "footer")
                    buttons.data_button("Done", "vidtool done", "footer")
                case "intro_style":
                    for label, st in [
                        ("Typing", "typing"),
                        ("Fade", "fade"),
                        ("Static", "static"),
                    ]:
                        buttons.data_button(
                            f"{'✅ ' if self.extra_data.get('style') == st else ''}{label}",
                            f"vidtool intro_style {st}",
                        )
                    buttons.data_button("<<", "vidtool back", "footer")
                    buttons.data_button("Done", "vidtool done", "footer")
                case "intro_text":
                    bnum = 1
                    buttons.data_button("<<", "vidtool back", "footer")
                    buttons.data_button("Done", "vidtool done", "footer")
                case "intro_font":
                    bnum = 2
                    buttons.data_button("Default Font", "vidtool intro_font default")
                    buttons.data_button("Upload Font", "vidtool intro_font upload")
                    buttons.data_button("<<", "vidtool back", "footer")
                    buttons.data_button("Done", "vidtool done", "footer")
                case "intro_char_ms":
                    bnum = 4
                    for cms in [100, 150, 200, 250, 300, 400, 500, 700, 1000]:
                        buttons.data_button(
                            f"{'✅ ' if self.extra_data.get('char_ms') == cms else ''}{cms}",
                            f"vidtool intro_char_ms {cms}",
                        )
                    buttons.data_button("<<", "vidtool back", "footer")
                    buttons.data_button("Done", "vidtool done", "footer")
                case "intro_colors":
                    bnum = 2
                    presets = [
                        ("Default", "default"),
                        ("Rainbow", "red|orange|yellow|green|blue|indigo|violet"),
                        ("White", "white"),
                        ("Red-Yellow-White", "red|yellow|white"),
                        ("Cyan-Magenta-White", "cyan|magenta|white"),
                        ("Custom", "custom"),
                    ]
                    for label, val in presets:
                        selected = (
                            self.extra_data.get("colors") == "" and val == "default"
                        ) or (self.extra_data.get("colors") == val)
                        buttons.data_button(
                            f"{'✅ ' if selected else ''}{label}",
                            f"vidtool intro_colors {val}",
                        )
                    buttons.data_button("<<", "vidtool back", "footer")
                    buttons.data_button("Done", "vidtool done", "footer")
                case "format":
                    bnum = 3
                    current_fmt = self.extra_data.get("format", "")
                    for fmt in ["mp4", "mkv", "webm", "mov", "avi", "flv", "m4v"]:
                        buttons.data_button(
                            f"{'✅ ' if current_fmt == fmt else ''}{fmt.upper()}",
                            f"vidtool set_format {fmt}",
                        )
                    buttons.data_button("<<", "vidtool back", "footer")
                    buttons.data_button("Done", "vidtool done", "footer")
                case _:
                    buttons.data_button("<<", "vidtool back", "footer")

        await self._send_message(
            self._captions(mode), buttons.build_menu(bnum, hnum, 3)
        )

    async def get_buttons(self):
        await gather(self.list_buttons(), self._event_handler())
        if self.listener.is_cancelled:
            await edit_message(self.mode, self._reply)
            return
        await delete_message(self._reply)
        return [self.mode, self.new_name, self.multi_mode, self.extra_data]


@new_task
async def message_handler(_, message: Message, obj: SelectMode, is_sub=False):
    data = mproc = None
    # Handle awaiting font uploads for watermark/intro
    if getattr(obj, "awaiting_wm_font", False) and message.document:
        font_dir = ospath.join(DOWNLOAD_DIR, "fonts")
        await makedirs(font_dir, exist_ok=True)
        save_path = ospath.join(font_dir, f"wm_{obj.listener.mid}.ttf")
        mproc = await send_message("<i>Processing, please wait...</i>", message)
        try:
            obj.extra_data["font_path"] = await message.download(save_path)
        except Exception:
            pass
        obj.awaiting_wm_font = False
        data = "wm_size"
        obj.message_event.set()
        if mproc:
            await delete_message(mproc)
        await obj.list_buttons(data)
        await delete_message(message)
        return
    if getattr(obj, "awaiting_intro_font", False) and message.document:
        font_dir = ospath.join(DOWNLOAD_DIR, "fonts")
        await makedirs(font_dir, exist_ok=True)
        save_path = ospath.join(font_dir, f"intro_{obj.listener.mid}.ttf")
        mproc = await send_message("<i>Processing, please wait...</i>", message)
        try:
            obj.extra_data["font_path"] = await message.download(save_path)
        except Exception:
            pass
        obj.awaiting_intro_font = False
        data = "intro_position"
        obj.message_event.set()
        if mproc:
            await delete_message(mproc)
        await obj.list_buttons(data)
        await delete_message(message)
        return
    if getattr(obj, "awaiting_intro_colors", False) and message.text:
        obj.extra_data["colors"] = message.text.strip()
        obj.awaiting_intro_colors = False
        data = None
        obj.message_event.set()
        if mproc:
            await delete_message(mproc)
        await obj.list_buttons(data)
        await delete_message(message)
        return
    if obj.is_rename and message.text:
        obj.new_name = message.text.strip().replace("/", "")
        obj.is_rename = False
    elif obj.mode == "multi_res" and is_sub == "resolution_list" and message.text:
        # Handle resolution list input for multi-resolution encoding
        resolution_text = message.text.strip()
        # Validate and clean resolution list (e.g., "1080p,720p,480p")
        valid_resolutions = []
        for res in resolution_text.split(","):
            res = res.strip()
            if re_match(r"^\d+p$", res):  # Validate format like "1080p"
                valid_resolutions.append(res)

        if valid_resolutions:
            obj.extra_data["resolution_list"] = ",".join(valid_resolutions)
        else:
            # Use default if invalid input
            obj.extra_data["resolution_list"] = "1080p,720p,480p"
    elif obj.mode == "watermark":
        if media := is_media(message):
            from ... import DOWNLOAD_DIR

            wm_path = ospath.join(DOWNLOAD_DIR, "thumbnails", "watermark")
            await makedirs(wm_path, exist_ok=True)
            if is_sub:
                mproc = await send_message("<i>Processing, please wait...</i>", message)
                obj.extra_data["sub_file"] = await message.download(
                    ospath.join(wm_path, media.file_name or media.file_id)
                )
            else:
                # Accept only images (photo/document with image mime, sticker, gif)
                if (
                    message.video
                    or message.audio
                    or message.voice
                    or message.video_note
                ):
                    await send_message(
                        "Only image/photo allowed for watermark!", message
                    )
                    return
                if (
                    message.document
                    and getattr(media, "mime_type", "").lower().find("image") == -1
                ):
                    await send_message("Only image document allowed!", message)
                    return
                mproc = await send_message("<i>Processing, please wait...</i>", message)
                tmp = await message.download()
                try:
                    try:
                        img = Image.open(tmp)
                        try:
                            if getattr(img, "is_animated", False):
                                img.seek(0)
                        except Exception:
                            pass
                        await sync_to_async(
                            img.convert("RGBA").save,
                            ospath.join(wm_path, f"{obj.listener.mid}.png"),
                            "PNG",
                        )
                    except Exception:
                        await send_message("Invalid image file!", message)
                        return
                finally:
                    await clean_target(tmp)
                data = "wm_size"
        elif not is_sub and message.text:
            # Create watermark image from provided text, preview it, then go to size selection
            from ... import DOWNLOAD_DIR

            obj.wm_text = message.text.strip()
            wm_path = ospath.join(DOWNLOAD_DIR, "thumbnails", "watermark")
            await makedirs(wm_path, exist_ok=True)
            fpath = ospath.join(wm_path, f"{obj.listener.mid}.png")
            try:
                from ..ext_utils.media_utils import draw_transparent_image

                await sync_to_async(draw_transparent_image, obj.wm_text, fpath)
                await send_photo(f"<code>{obj.wm_text}</code>", message, fpath)
            except Exception:
                pass
            data = "wm_font"
        else:
            # Not a valid input
            await delete_message(message)
            return
    elif obj.mode == "trim" and message.text:
        if match := re_match(
            r"(\d{2}:\d{2}:\d{2})\s(\d{2}:\d{2}:\d{2})", message.text.strip()
        ):
            obj.extra_data.update(
                {"start_time": match.group(1), "end_time": match.group(2)}
            )
        else:
            await send_message("Invalid trim duration format!", message)
            return
    obj.message_event.set()
    if mproc:
        await delete_message(mproc)
    await obj.list_buttons(data)
    await delete_message(message)


@new_task
async def vidtools_callback(_, query: CallbackQuery, obj: SelectMode):
    data = query.data.split()
    if data[1] in Config.DISABLE_VIDTOOLS and query.from_user.id != Config.OWNER_ID:
        await query.answer(f"{videos_tools_mode[data[1]]} has been disabled!", True)
        return
    await query.answer()
    if data[1] == obj.mode and len(data) == 2:
        return

    match data[1]:
        case "done":
            # Always allow completion; executor will auto-wait for subtitle if needed
            obj.event.set()
        case "back":
            # Don't clear mode completely, just go to main buttons but preserve state
            await obj.list_buttons()
        case "cancel":
            obj.mode = "Task has been cancelled!"
            obj.listener.is_cancelled = True
            obj.event.set()
        case "quality" | "crf" | "bitrate" | "preset" | "codec" as value:
            if len(data) == 3:
                obj.extra_data[value] = data[2]
            await obj.list_buttons(value)
        case "format":
            await obj.list_buttons("format")
        case "set_format":
            if len(data) == 3:
                obj.extra_data["format"] = data[2]
            await obj.list_buttons()
        case "multi_resolution" | "multi_zip":
            # Toggle multi-resolution and multi-zip options
            current_value = obj.extra_data.get(data[1], False)
            obj.extra_data[data[1]] = not current_value
            await obj.list_buttons()
        case "resolution_list":
            # Handle resolution list input
            await gather(
                obj.list_buttons("resolution_list"),
                obj.message_event_handler("resolution_list"),
            )
        case "wm_size" | "wm_position" as value:
            obj.extra_data[value] = data[2]
            await obj.list_buttons("wm_position" if value == "wm_size" else None)
        case "wm_font":
            # Choose default or upload font for text watermark
            if len(data) == 3 and data[2] == "default":
                obj.extra_data.pop("font_path", None)
                await obj.list_buttons("wm_size")
            elif len(data) == 3 and data[2] == "upload":
                obj.awaiting_wm_font = True
                await gather(obj.list_buttons("wm_font"), obj.message_event_handler())
                obj.awaiting_wm_font = False
            else:
                await obj.list_buttons("wm_font")
        case "hardsub":
            # Toggle encode (burn subtitles)
            current = obj.extra_data.get("hardsub", False)
            obj.extra_data["hardsub"] = not current
            await obj.list_buttons()
        case "intro_font_size" | "intro_position" | "intro_style" as value:
            if len(data) == 3:
                if value == "intro_font_size" and data[2].isdigit():
                    obj.extra_data["font_size"] = int(data[2])
                    # After size, go to Char MS
                    await obj.list_buttons("intro_char_ms")
                    return
                elif value == "intro_position":
                    obj.extra_data["position"] = data[2]
                    # After position, go to Size
                    await obj.list_buttons("intro_font_size")
                    return
                elif value == "intro_style":
                    obj.extra_data["style"] = data[2]
            await obj.list_buttons(value)
        case "intro_font":
            if len(data) == 3 and data[2] == "default":
                obj.extra_data.pop("font_path", None)
                await obj.list_buttons("intro_position")
            elif len(data) == 3 and data[2] == "upload":
                obj.awaiting_intro_font = True
                await gather(
                    obj.list_buttons("intro_font"), obj.message_event_handler()
                )
                obj.awaiting_intro_font = False
            else:
                await obj.list_buttons("intro_font")
        case "intro_char_ms":
            if len(data) == 3 and data[2].isdigit():
                obj.extra_data["char_ms"] = int(data[2])
                # After char ms, go to colors
                await obj.list_buttons("intro_colors")
                return
            await obj.list_buttons("intro_char_ms")
        case "intro_colors":
            if len(data) == 3:
                if data[2] == "default":
                    obj.extra_data.pop("colors", None)
                    await obj.list_buttons()
                    return
                elif data[2] == "custom":
                    obj.awaiting_intro_colors = True
                    await gather(
                        obj.list_buttons("intro_colors"),
                        obj.message_event_handler("rename"),
                    )
                    obj.awaiting_intro_colors = False
                    return
                else:
                    obj.extra_data["colors"] = data[2]
                    await obj.list_buttons()
                    return
            await obj.list_buttons("intro_colors")
        case "wm_popup":
            # Toggle/select popup frequency (every X seconds)
            if len(data) == 3 and data[2].isdigit():
                obj.extra_data["wm_popup"] = int(data[2])
            await obj.list_buttons(
                "wm_size" if not obj.extra_data.get("wm_size") else "wm_position"
            )
        case "rename":
            obj.is_rename = True
            await gather(
                obj.list_buttons("rename"), obj.message_event_handler("rename")
            )
        case "watermark":
            obj.mode = "watermark"
            await gather(
                obj.list_buttons("watermark"), obj.message_event_handler("watermark")
            )
        case "intro_sub":
            obj.mode = "intro_sub"
            # Preload defaults from user settings for better status visibility
            u = getattr(obj.listener, "user_dict", {}) or {}
            for k_src, k_dst in [
                ("INTRO_SUBTITLE_FONT_SIZE", "font_size"),
                ("INTRO_SUBTITLE_POSITION", "position"),
                ("INTRO_SUBTITLE_STYLE", "style"),
                ("INTRO_SUBTITLE_CHAR_MS", "char_ms"),
                ("INTRO_SUBTITLE_COLORS", "colors"),
            ]:
                if u.get(k_src) and k_dst not in obj.extra_data:
                    obj.extra_data[k_dst] = u.get(k_src)
            if u.get("INTRO_SUBTITLE_FONT_PATH") and not obj.extra_data.get(
                "font_path"
            ):
                obj.extra_data["font_path"] = u.get("INTRO_SUBTITLE_FONT_PATH")
            elif u.get("VT_WM_FONT_PATH") and not obj.extra_data.get("font_path"):
                obj.extra_data["font_path"] = u.get("VT_WM_FONT_PATH")
            # Ask for text first, then font, then position
            await gather(
                obj.list_buttons("intro_text"), obj.message_event_handler("rename")
            )
            if obj.new_name:
                obj.extra_data["text"] = obj.new_name
                obj.new_name = ""
            await obj.list_buttons("intro_font")
        case "trim":
            obj.mode = "trim"
            await gather(obj.list_buttons("trim"), obj.message_event_handler())
        case "multi":
            obj.multi_mode = not obj.multi_mode
            await obj.list_buttons()
        case _:
            old_mode = obj.mode
            obj.mode = data[1]
            # Only clear extra_data when switching to a different mode, not for submenus
            if old_mode != data[1]:
                obj.extra_data.clear()
            # Special handling for multi-resolution mode
            if data[1] == "multi_res":
                # Initialize with user's multi-resolution settings
                user_dict = getattr(obj.listener, "user_dict", {}) or {}
                obj.extra_data["multi_resolution"] = user_dict.get(
                    "VIDEO_ENCODE_MULTI_RESOLUTION", False
                )
                obj.extra_data["resolution_list"] = user_dict.get(
                    "VIDEO_ENCODE_RESOLUTION_LIST", "1080p,720p,480p"
                )
                obj.extra_data["multi_zip"] = user_dict.get(
                    "VIDEO_ENCODE_MULTI_ZIP", False
                )
            await obj.list_buttons()
