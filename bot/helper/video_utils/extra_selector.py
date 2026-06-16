from ast import literal_eval
from asyncio import Event, wait_for, gather
from functools import partial
from time import time

from pyrogram.filters import regex, user
from pyrogram.handlers import CallbackQueryHandler
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup
from pyrogram.errors import QueryIdInvalid

from bot import videos_tools_mode
from ..ext_utils.bot_utils import new_task
from ..ext_utils.status_utils import get_readable_file_size, get_readable_time
from ..telegram_helper.button_build import ButtonMaker
from ..telegram_helper.message_utils import (
    send_messagee as send_message,
    edit_messagee as edit_message,
    delete_message,
)


class ExtraSelect:
    def __init__(self):
        self.first_selected_stream = None
        self.first_selected_stream_original_text = None  # Stores original display text of the first selected stream for restoration
        self.time = time()
        self.reply = None
        self.event = Event()
        self.extension: list[str] = []
        self.status = ""

    async def _event_handler(self):
        pfunc = partial(vidtools_extselector_callback, obj=self)
        handler = self.listener.client.add_handler(
            CallbackQueryHandler(
                pfunc, filters=regex("^extra") & user(self.listener.user_id)
            ),
            group=-1,
        )
        try:
            await wait_for(self.event.wait(), timeout=180)
        except Exception:
            self.event.set()
        finally:
            self.listener.client.remove_handler(*handler)
            self.event.clear()

    async def update_message(self, text: str, buttons: InlineKeyboardMarkup):
        if not self.reply:
            self.reply = await send_message(text, self.listener.message, buttons)
        else:
            await edit_message(text, self.reply, buttons)

    def streams_select(self, streams: dict | None = None):
        buttons = ButtonMaker()
        mode = self.mode
        ddict = self.data

        if mode == "reordertracks":
            ddict = self.data
            if not ddict:  # First time setup for this mode
                ddict.setdefault("all_streams_for_reorder", {})
                ddict.setdefault("current_reorder_selection", [])
                ddict.setdefault("available_to_add", [])

                temp_available_to_add = []
                for stream in streams:
                    index_map, codec_name, codec_type, lang = (
                        stream.get("index"),
                        stream.get("codec_name"),
                        stream.get("codec_type"),
                        stream.get("tags", {}).get("language"),
                    )
                    if not lang:
                        lang = str(index_map)
                    # For now, let's focus on reordering audio streams, similar to refer example
                    if codec_type not in ["audio"]:
                        continue

                    ddict["all_streams_for_reorder"][index_map] = {
                        "info": f"{codec_type.title()} ~ {lang.upper()} ({codec_name})",
                        "type": codec_type,
                        "map": index_map,  # Original index
                        "lang": lang,
                    }
                    temp_available_to_add.append(index_map)
                # Sort available streams by their original index for consistent display
                ddict["available_to_add"] = sorted(temp_available_to_add)
                self.data = ddict

            text = f"<b>TRACK REORDER SETTINGS ~ {self.listener.tag}</b>\n"
            text += f"<code>{self.listener.name}</code>\n"
            text += (
                f"File Size: <b>{get_readable_file_size(self.listener.size)}</b>\n\n"
            )

            text += "<b>Current Reordered Selection (Output Order):</b>\n"
            if not ddict.get("current_reorder_selection"):
                text += (
                    "<i>None selected yet. Add streams from 'Available Streams'.</i>\n"
                )
            else:
                for i, original_idx in enumerate(ddict["current_reorder_selection"]):
                    stream_info = (
                        ddict["all_streams_for_reorder"]
                        .get(original_idx, {})
                        .get("info", f"Unknown Stream {original_idx}")
                    )
                    text += f"{i + 1}. {stream_info}\n"
            text += "\n"

            # Buttons for modifying current selection (removing items)
            if ddict.get("current_reorder_selection"):
                text += "<b>Modify Selection:</b>\n"
                for i, original_idx in enumerate(ddict["current_reorder_selection"]):
                    stream_info = (
                        ddict["all_streams_for_reorder"]
                        .get(original_idx, {})
                        .get("info", f"Stream {original_idx}")
                    )
                    buttons.data_button(
                        f"❌ {i + 1}. {stream_info}",
                        f"extra reordertracks remove_at_pos {i}",
                    )
                buttons.data_button(
                    "Clear Entire Selection",
                    "extra reordertracks clear_selection",
                    "line",
                )

            text += "\n<b>Available Streams to Add (Audio):</b>\n"
            if not ddict.get("available_to_add"):
                text += "<i>All available audio streams have been added to the selection.</i>\n"
            else:
                for original_idx in ddict["available_to_add"]:
                    stream_info = (
                        ddict["all_streams_for_reorder"]
                        .get(original_idx, {})
                        .get("info", f"Unknown Stream {original_idx}")
                    )
                    buttons.data_button(
                        f"➕ {stream_info}", f"extra reordertracks add {original_idx}"
                    )
                # Add All available at once
                buttons.data_button(
                    "Add All Available", "extra reordertracks add_all", "line"
                )

            buttons.data_button(
                "Confirm Reorder", "extra reordertracks continue", "footer"
            )
            buttons.data_button("Cancel", "extra cancel", "footer")

            text += (
                f"\n\n<i>Time Out: {get_readable_time(180 - (time() - self.time))}</i>"
            )
            return text, buttons.build_menu(
                1
            )  # Adjust columns as needed, 1 might be good for lists

        else:  # Original logic for other modes
            if (
                not self.data
                or "stream" not in self.data
                or not self.data.get("stream")
            ):
                ddict = {}
                ddict.setdefault("stream", {})
                ddict["sdata"] = []
                self.data = ddict
                for stream in streams:
                    index_map, codec_name, codec_type, lang = (
                        stream.get("index"),
                        stream.get("codec_name"),
                        stream.get("codec_type"),
                        stream.get("tags", {}).get("language"),
                    )
                    if not lang:
                        lang = str(index_map)
                    if codec_type not in ["video", "audio", "subtitle"]:
                        continue
                    if codec_type == "audio":
                        ddict["is_audio"] = True
                    elif codec_type == "subtitle":
                        ddict["is_sub"] = True
                    ddict["stream"][index_map] = {
                        "info": f"{codec_type.title()} ~ {lang.upper()}",
                        "name": codec_name,
                        "map": index_map,
                        "type": codec_type,
                        "lang": lang,
                    }
            else:
                ddict = self.data
            text = ""
            for key, value in ddict["stream"].items():
                if mode == "extract":
                    buttons.data_button(value["info"], f"extra {mode} {key}")
                    audio_extension, sub_extension, video_extension = self.extension
                    text = f"<b>STREAM EXTRACT SETTINGS ~ {self.listener.tag}</b>\n"
                    text += f"<code>{self.listener.name}</code>\n"
                    text += f"File Size: <b>{get_readable_file_size(self.listener.size)}</b>\n"
                    text += f"Video Format: <b>{video_extension.upper()}</b>\n"
                    text += f"Audio Format: <b>{audio_extension.upper()}</b>\n"
                    text += f"Subtitle Format: <b>{sub_extension.upper()}</b>\n"
                    text += f"Fast Mode: <b>{'✅ Enable' if ddict.get('fast_mode') else 'Disable'}</b>\n\n"
                    text += "Select available stream below to unpack!"
                else:  # rmstream
                    if value["type"] != "video":
                        buttons.data_button(value["info"], f"extra {mode} {key}")
                    text = f"<b>STREAM REMOVE SETTINGS ~ {self.listener.tag}</b>\n"
                    text += f"<code>{self.listener.name}</code>\n"
                    text += f"File Size: <b>{get_readable_file_size(self.listener.size)}</b>\n"
                    if sdata := ddict.get("sdata"):
                        text += "\nStream will removed:\n"
                        for i, index_val in enumerate(sdata, start=1):
                            text += (
                                f"{i}. {ddict['stream'][index_val]['info']}\n".replace(
                                    "✅ ", ""
                                )
                            )
                    text += "\nSelect available stream below!"
            # Group action buttons placed after per-stream buttons
            if mode == "extract":
                for ext in self.extension:
                    buttons.data_button(
                        ext.upper(), f"extra {mode} extension {ext}", "header"
                    )
                buttons.data_button(
                    "✅ Fast Mode" if ddict.get("fast_mode") else "Fast Mode",
                    f"extra {mode} fast {ddict.get('fast_mode', False)}",
                    "header",
                )
                buttons.data_button("Extract All", f"extra {mode} video audio subtitle")
            else:  # rmstream
                if ddict.get("is_sub"):
                    buttons.data_button("All Subs", f"extra {mode} subtitle")
                if ddict.get("is_audio"):
                    buttons.data_button("All Audio", f"extra {mode} audio")
                if ddict.get("is_audio") or ddict.get("is_sub"):
                    buttons.data_button("All Streams", f"extra {mode} all")
                buttons.data_button("Reset", f"extra {mode} reset", "header")
                buttons.data_button("Reverse", f"extra {mode} reverse", "header")
                buttons.data_button("Continue", f"extra {mode} continue", "footer")
            buttons.data_button("Cancel", "extra cancel", "footer")
            text += (
                f"\n\n<i>Time Out: {get_readable_time(180 - (time() - self.time))}</i>"
            )
            return text, buttons.build_menu(2, 3)

    async def compress_select(self, streams: dict):
        self.data = {}
        buttons = ButtonMaker()
        for stream in streams:
            index_map, codec_type, lang = (
                stream.get("index"),
                stream.get("codec_type"),
                stream.get("tags", {}).get("language"),
            )
            if codec_type == "video" and index_map == 0:
                self.data["video"] = index_map
            if codec_type == "video" and "video" not in self.data:
                self.data["video"] = index_map
            if codec_type == "audio":
                buttons.data_button(
                    f"Audio ~ {(lang or str(index_map)).upper()}",
                    f"extra compress {index_map}",
                )
        buttons.data_button("Continue", "extra compress 0")
        buttons.data_button("Cancel", "extra cancel")
        await self.update_message(
            f"{self.listener.tag}, Select available audio or press <b>Continue (all audio)</b>.\n<code>{self.listener.name}</code>",
            buttons.build_menu(2),
        )

    async def remove_stream_select(self, streams: dict):
        self.data = {}
        await self.update_message(*self.streams_select(streams))

    async def convert_select(self, streams: dict):
        buttons = ButtonMaker()

        # Initialize convert data structure if not exists
        if not hasattr(self, "data") or not isinstance(self.data, dict):
            self.data = {}

        # Get current video resolution for display
        hvid = "Unknown"
        if streams:
            for stream in streams:
                if stream.get("codec_type") == "video" and stream.get("height"):
                    hvid = f"{stream['height']}p"
                    break

        # Get user settings for defaults
        user_dict = getattr(self.listener, "user_dict", {}) or {}

        # Initialize convert settings with user defaults if not set
        if "convert_settings" not in self.data:
            self.data["convert_settings"] = {
                "codec": user_dict.get("VIDEO_CONVERT_CODEC", "copy"),
                "quality": user_dict.get("VIDEO_CONVERT_QUALITY", "original"),
                "format": user_dict.get("VIDEO_CONVERT_FORMAT", "mp4"),
                "preset": user_dict.get("VIDEO_ENCODE_PRESET", "medium"),
                "crf": user_dict.get("VIDEO_ENCODE_CRF", "23"),
                "bitrate": user_dict.get("VIDEO_ENCODE_BITRATE", "auto"),
                # Force multi-resolution off for simple convert flow after download
                "multi_resolution": False,
                "resolution_list": user_dict.get(
                    "VIDEO_ENCODE_RESOLUTION_LIST", "1080p,720p,480p"
                ),
                "multi_zip": user_dict.get("VIDEO_ENCODE_MULTI_ZIP", False),
            }

        convert_settings = self.data["convert_settings"]

        # If user pre-selected a format in the selector, adopt it here
        try:
            if (
                isinstance(self.listener.video_mode, (list, tuple))
                and len(self.listener.video_mode) >= 4
                and isinstance(self.listener.video_mode[3], dict)
            ):
                pre_fmt = self.listener.video_mode[3].get("format")
                if pre_fmt:
                    convert_settings["format"] = pre_fmt
        except Exception:
            pass

        # Default to a simple resolution menu after download
        submenu = self.data.get("convert_submenu", "resolution")

        if submenu == "main":
            # Main convert menu with advanced options
            buttons.data_button(
                f"{'✓ ' if convert_settings.get('codec') != 'copy' else ''}Codec: {convert_settings.get('codec', 'copy')}",
                "extra convert codec",
            )
            buttons.data_button(
                f"{'✓ ' if convert_settings.get('quality') != 'original' else ''}Quality: {convert_settings.get('quality', 'original')}",
                "extra convert quality",
            )
            buttons.data_button(
                f"{'✓ ' if convert_settings.get('preset') != 'medium' else ''}Preset: {convert_settings.get('preset', 'medium')}",
                "extra convert preset",
            )
            buttons.data_button(
                f"{'✓ ' if convert_settings.get('crf') != '23' else ''}CRF: {convert_settings.get('crf', '23')}",
                "extra convert crf",
            )
            buttons.data_button(
                f"{'✓ ' if convert_settings.get('bitrate') != 'auto' else ''}Bitrate: {convert_settings.get('bitrate', 'auto')}",
                "extra convert bitrate",
            )
            buttons.data_button("Resolution Selection", "extra convert resolution")
            if convert_settings.get("multi_resolution"):
                buttons.data_button(
                    f"✓ Multi-Res: {convert_settings.get('resolution_list', '1080p,720p,480p')}",
                    "extra convert multires",
                )
            else:
                buttons.data_button("Multi-Resolution", "extra convert multires")

            buttons.data_button("Back", "extra convert back", "footer")
            buttons.data_button("Apply Convert", "extra convert apply", "footer")
            buttons.data_button("Cancel", "extra cancel", "footer")

            # Enhanced status text with current settings
            settings_info = []
            if convert_settings.get("codec") != "copy":
                settings_info.append(f"Codec: <b>{convert_settings.get('codec')}</b>")
            if convert_settings.get("quality") != "original":
                settings_info.append(
                    f"Quality: <b>{convert_settings.get('quality')}</b>"
                )
            if convert_settings.get("preset") != "medium":
                settings_info.append(f"Preset: <b>{convert_settings.get('preset')}</b>")
            if convert_settings.get("crf") != "23":
                settings_info.append(f"CRF: <b>{convert_settings.get('crf')}</b>")
            if convert_settings.get("bitrate") != "auto":
                settings_info.append(
                    f"Bitrate: <b>{convert_settings.get('bitrate')}</b>"
                )
            if convert_settings.get("multi_resolution"):
                settings_info.append(
                    f"Multi-Res: <b>{convert_settings.get('resolution_list')}</b>"
                )

            status_text = "\n".join(f"├ {setting}" for setting in settings_info)
            if status_text:
                status_text = f"\n\n╭ <b>Current Settings</b>\n{status_text}\n╰"

            text = (
                f"<b>ENHANCED CONVERT SETTINGS ~ {self.listener.tag}</b>\n"
                f"<code>{self.listener.name}</code>\n\n"
                f"Current Resolution: <b>{hvid}</b>"
                f"{status_text}\n\n"
                f"<i>Configure advanced conversion options below:</i>"
            )

        elif submenu == "codec":
            # Codec selection submenu
            codec_options = ["copy", "auto", "x264", "x265"]
            for codec in codec_options:
                buttons.data_button(
                    f"{'✓ ' if convert_settings.get('codec') == codec else ''}{codec}",
                    f"extra convert codec_set {codec}",
                )
            buttons.data_button("Back to Main", "extra convert main", "footer")
            text = (
                f"<b>SELECT CODEC ~ {self.listener.tag}</b>\n"
                f"<code>{self.listener.name}</code>\n\n"
                f"<b>copy</b> - Keep original codec (fastest)\n"
                f"<b>auto</b> - Smart codec selection\n"
                f"<b>x264</b> - H.264 encoding (compatible)\n"
                f"<b>x265</b> - H.265 encoding (smaller files)\n\n"
                f"Current: <b>{convert_settings.get('codec', 'copy')}</b>"
            )

        elif submenu == "quality":
            # Quality selection submenu
            quality_options = ["original", "high", "medium", "low"]
            for quality in quality_options:
                buttons.data_button(
                    f"{'✓ ' if convert_settings.get('quality') == quality else ''}{quality.capitalize()}",
                    f"extra convert quality_set {quality}",
                )
            buttons.data_button("Back to Main", "extra convert main", "footer")
            text = (
                f"<b>SELECT QUALITY ~ {self.listener.tag}</b>\n"
                f"<code>{self.listener.name}</code>\n\n"
                f"Current: <b>{convert_settings.get('quality', 'original').capitalize()}</b>"
            )

        elif submenu == "preset":
            # Preset selection submenu
            presets = [
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
            for preset in presets:
                buttons.data_button(
                    f"{'✓ ' if convert_settings.get('preset') == preset else ''}{preset}",
                    f"extra convert preset_set {preset}",
                )
            buttons.data_button("Back to Main", "extra convert main", "footer")
            text = (
                f"<b>SELECT PRESET ~ {self.listener.tag}</b>\n"
                f"<code>{self.listener.name}</code>\n\n"
                f"Current: <b>{convert_settings.get('preset', 'medium')}</b>"
            )

        elif submenu == "crf":
            # CRF selection submenu
            crf_options = ["18", "20", "22", "23", "24", "26", "28", "30"]
            for crf in crf_options:
                buttons.data_button(
                    f"{'✓ ' if convert_settings.get('crf') == crf else ''}CRF {crf}",
                    f"extra convert crf_set {crf}",
                )
            buttons.data_button("Back to Main", "extra convert main", "footer")
            text = (
                f"<b>SELECT CRF ~ {self.listener.tag}</b>\n"
                f"<code>{self.listener.name}</code>\n\n"
                f"Lower values = higher quality, larger files\n"
                f"Higher values = lower quality, smaller files\n\n"
                f"Current: <b>{convert_settings.get('crf', '23')}</b>"
            )

        elif submenu == "bitrate":
            # Bitrate selection submenu
            bitrate_options = ["auto", "500k", "1M", "2M", "4M", "8M", "16M"]
            for bitrate in bitrate_options:
                buttons.data_button(
                    f"{'✓ ' if convert_settings.get('bitrate') == bitrate else ''}{bitrate}",
                    f"extra convert bitrate_set {bitrate}",
                )
            buttons.data_button("Back to Main", "extra convert main", "footer")
            text = (
                f"<b>SELECT BITRATE ~ {self.listener.tag}</b>\n"
                f"<code>{self.listener.name}</code>\n\n"
                f"Current: <b>{convert_settings.get('bitrate', 'auto')}</b>"
            )

        elif submenu == "resolution":
            # Basic resolution selection (original functionality)
            resolution = {
                "1080p": "Convert 1080p",
                "720p": "Convert 720p",
                "540p": "Convert 540p",
                "480p": "Convert 480p",
                "360p": "Convert 360p",
            }
            [
                buttons.data_button(typee, f"extra convert resolution_set {key}")
                for key, typee in resolution.items()
                if key != hvid
            ]
            # Show currently selected container/format for clarity
            buttons.data_button(
                f"Format: .{convert_settings.get('format', 'mp4').lower()}",
                "extra convert main",
                "header",
            )
            buttons.data_button("Back to Main", "extra convert main", "footer")
            text = (
                f"<b>SELECT RESOLUTION ~ {self.listener.tag}</b>\n"
                f"<code>{self.listener.name}</code>\n\n"
                f"Current resolution is <b>{hvid}</b>"
            )

        elif submenu == "multires":
            # Multi-resolution options
            buttons.data_button(
                f"{'✓' if convert_settings.get('multi_resolution') else '×'} Enable Multi-Resolution",
                "extra convert multires_toggle",
            )
            if convert_settings.get("multi_resolution"):
                buttons.data_button(
                    f"Resolution List: {convert_settings.get('resolution_list', '1080p,720p,480p')}",
                    "extra convert reslist",
                )
                buttons.data_button(
                    f"{'✓' if convert_settings.get('multi_zip') else '×'} Multi-ZIP Output",
                    "extra convert multizip_toggle",
                )
            buttons.data_button("Back to Main", "extra convert main", "footer")
            text = (
                f"<b>MULTI-RESOLUTION SETTINGS ~ {self.listener.tag}</b>\n"
                f"<code>{self.listener.name}</code>\n\n"
                f"Multi-Resolution: <b>{'Enabled' if convert_settings.get('multi_resolution') else 'Disabled'}</b>"
            )

        else:
            # Fallback to main menu
            self.data["convert_submenu"] = "main"
            return await self.convert_select(streams)

        await self.update_message(text, buttons.build_menu(2))

    async def subsync_select(self):
        buttons = ButtonMaker()
        text = ""
        index = 1
        if not self.status:
            for position, file in self.data["list"].items():
                # Accept common subtitle extensions consistently
                if file.endswith((".srt", ".ass", ".ssa", ".vtt", ".sub")):
                    ref_file = self.data["final"].get(position, {}).get("ref", "")
                    text += f"{index}. {file} {'✅ ' if ref_file else ''}\n"
                    but_txt = f"✅ {index}" if ref_file else index
                    buttons.data_button(but_txt, f"extra subsync {position}")
                    index += 1
            buttons.data_button("Cancel", "extra cancel", "footer")
            if self.data["final"]:
                buttons.data_button("Continue", "extra subsync continue", "footer")
        else:
            file: dict = self.data["list"][self.status]
            text = f"Current: <b>{file}</b>\n"
            text += (
                f"References: <b>{ref}</b>\n"
                if (ref := self.data["final"].get(self.status, {}).get("ref"))
                else ""
            )
            text += "\nSelect Available References Below!\n"
            self.data["final"][self.status] = {"file": file}
            for position, file in self.data["list"].items():
                if position != self.status and file not in self.data["final"].values():
                    text += f"{index}. {file}\n"
                    buttons.data_button(index, f"extra subsync select {position}")
                    index += 1
        await self.update_message(text, buttons.build_menu(5))

    async def extract_select(self, streams: dict):
        audio_ext, subtitle_ext = None, None
        for stream in streams:
            codec_name, codec_type = stream.get("codec_name"), stream.get("codec_type")
            if codec_type == "audio" and not audio_ext:
                if codec_name in ["aac", "ac3", "eac3", "m4a", "mka", "wav"]:
                    audio_ext = codec_name
                else:
                    audio_ext = "aac"
            elif codec_type == "subtitle" and not subtitle_ext:
                subtitle_ext = "srt" if codec_name == "subrip" else "ass"
        audio_ext = audio_ext or "aac"
        subtitle_ext = subtitle_ext or "srt"
        self.extension = [audio_ext, subtitle_ext, "mkv"]
        await self.update_message(*self.streams_select(streams))

    async def _reorder_tracks_select(self, streams: dict):
        self.data = {}  # Initialize data for this mode
        # We will populate self.data within streams_select if it's the first call for this mode
        await self.update_message(*self.streams_select(streams))

    async def multi_res_select(self, streams: dict):
        """Multi-resolution encoding doesn't need stream selection, just proceed"""
        # Multi-resolution mode is configuration-based, not stream-selection based
        # The settings are handled in the selector.py file
        self.data = {"proceed": True}  # Just set some data to indicate we're ready
        self.listener.data_from_video_tool_selection = True
        self.event.set()

    async def extra_buttons(self, *args):
        func = {
            "extract": self.extract_select,
            "subsync": self.subsync_select,
            "rmstream": self.remove_stream_select,
            "convert": self.convert_select,
            "compress": self.compress_select,
            "reordertracks": self._reorder_tracks_select,
            "multi_res": self.multi_res_select,
        }
        await func[self.mode](*args)
        await self._event_handler()
        await delete_message(self.reply)
        if self.listener.is_cancelled:
            await self.listener.on_upload_error(
                f"{videos_tools_mode[self.mode]} stopped by user!"
            )


@new_task
async def vidtools_extselector_callback(_, query: CallbackQuery, obj: ExtraSelect):
    data = query.data.split()

    # Helper function to safely answer callback queries
    async def safe_answer(text=None, show_alert=False):
        try:
            await query.answer(text, show_alert=show_alert)
        except QueryIdInvalid:
            # Callback query has expired, continue processing but don't answer
            pass
        except Exception as e:
            # Log other errors but don't crash
            from .... import LOGGER

            LOGGER.warning(f"Error answering callback query: {e}")

    match data[1]:
        case "cancel":
            await safe_answer()
            obj.listener.is_cancelled = True
            obj.data = None  # Clear data on cancel
            if (
                obj.first_selected_stream is not None
                and obj.first_selected_stream in obj.data.get("stream", {})
            ):  # Safely access stream
                obj.data["stream"][obj.first_selected_stream]["info"] = obj.data[
                    "stream"
                ][obj.first_selected_stream]["original_info"]
            obj.first_selected_stream = None
            obj.first_selected_stream_original_text = None
            obj.event.set()
        case "reordertracks":
            ddict = obj.data
            await safe_answer()  # Acknowledge the callback immediately

            match data[2]:
                case "add":
                    stream_original_idx = int(data[3])
                    if stream_original_idx in ddict.get("available_to_add", []):
                        ddict["available_to_add"].remove(stream_original_idx)
                        ddict.setdefault("current_reorder_selection", []).append(
                            stream_original_idx
                        )
                    else:
                        await safe_answer(
                            "Stream already added or invalid.", show_alert=True
                        )
                        return  # Avoid unnecessary UI update if error
                case "add_all":
                    # Move all available_to_add into current_reorder_selection preserving order
                    avail = ddict.get("available_to_add", [])
                    if avail:
                        ddict.setdefault("current_reorder_selection", []).extend(avail)
                        ddict["available_to_add"] = []
                    else:
                        await safe_answer(
                            "No available streams to add.", show_alert=True
                        )
                        return
                case "remove_at_pos":
                    position_in_selection = int(data[3])
                    current_selection = ddict.get("current_reorder_selection", [])
                    if 0 <= position_in_selection < len(current_selection):
                        removed_original_idx = current_selection.pop(
                            position_in_selection
                        )
                        # Add back to available_to_add and re-sort for consistent display
                        ddict.setdefault("available_to_add", []).append(
                            removed_original_idx
                        )
                        ddict["available_to_add"].sort()
                    else:
                        await safe_answer(
                            "Invalid position to remove.", show_alert=True
                        )
                        return
                case "clear_selection":
                    current_selection = ddict.get("current_reorder_selection", [])
                    available_to_add = ddict.setdefault("available_to_add", [])
                    available_to_add.extend(current_selection)
                    available_to_add.sort()
                    current_selection.clear()
                case "continue":
                    if ddict.get("current_reorder_selection"):
                        obj.data["reordered_streams"] = list(
                            ddict["current_reorder_selection"]
                        )  # Store a copy
                        obj.listener.data_from_video_tool_selection = True
                        obj.event.set()
                        return  # Don't update message after setting event
                    else:
                        await safe_answer(
                            "No streams selected or reordered to confirm!",
                            show_alert=True,
                        )
                        return

            # Update the message after action, unless event was set
            await obj.update_message(*obj.streams_select())
            return  # Explicit return after handling reordertracks

        case "subsync":
            if data[2].isdigit():
                obj.status = int(data[2])
            elif data[2] == "select":
                obj.data["final"][obj.status]["ref"] = obj.data["list"][int(data[3])]
                obj.status = ""
            elif data[2] == "continue":
                obj.listener.data_from_video_tool_selection = True
                obj.event.set()
                return
            await gather(safe_answer(), obj.subsync_select())
        case "compress":
            await safe_answer()
            obj.data["audio"] = int(data[2])
            obj.listener.data_from_video_tool_selection = True
            obj.event.set()
        case "convert":
            await safe_answer()

            # Handle different convert actions
            if len(data) < 3:
                return

            action = data[2]

            if action == "main":
                # Go back to main convert menu
                if not hasattr(obj, "data") or not isinstance(obj.data, dict):
                    obj.data = {}
                obj.data["convert_submenu"] = "main"
                await obj.convert_select(
                    {}
                )  # Empty streams, we'll get them from metadata
                return

            elif action == "back":
                # Go back to convert mode selection (out of convert settings)
                obj.data = {}
                obj.event.set()
                return

            elif action == "apply":
                # Apply convert settings and proceed
                obj.listener.data_from_video_tool_selection = True
                obj.event.set()
                return

            elif action in [
                "codec",
                "quality",
                "preset",
                "crf",
                "bitrate",
                "resolution",
                "multires",
            ]:
                # Navigate to submenu
                if not hasattr(obj, "data") or not isinstance(obj.data, dict):
                    obj.data = {}
                obj.data["convert_submenu"] = action
                await obj.convert_select(
                    {}
                )  # Empty streams, we'll get them from metadata
                return

            elif action.endswith("_set") and len(data) >= 4:
                # Set a specific value
                setting_type = action.replace("_set", "")
                value = data[3]

                # Initialize convert settings if needed
                if not hasattr(obj, "data") or not isinstance(obj.data, dict):
                    obj.data = {}
                if "convert_settings" not in obj.data:
                    obj.data["convert_settings"] = {}

                obj.data["convert_settings"][setting_type] = value

                # If user chose a resolution, apply immediately and proceed
                if setting_type == "resolution":
                    obj.data["convert_settings"]["target_resolution"] = value
                    # Backward-compatible path: set data to raw resolution for executor
                    obj.data = value
                    obj.listener.data_from_video_tool_selection = True
                    obj.event.set()
                    return

                # Otherwise, go back to main menu after setting
                obj.data["convert_submenu"] = "main"
                await obj.convert_select({})
                return

            elif action == "multires_toggle":
                # Toggle multi-resolution
                if not hasattr(obj, "data") or not isinstance(obj.data, dict):
                    obj.data = {}
                if "convert_settings" not in obj.data:
                    obj.data["convert_settings"] = {}

                current = obj.data["convert_settings"].get("multi_resolution", False)
                obj.data["convert_settings"]["multi_resolution"] = not current

                # Stay in multires submenu
                obj.data["convert_submenu"] = "multires"
                await obj.convert_select({})
                return

            elif action == "multizip_toggle":
                # Toggle multi-zip
                if not hasattr(obj, "data") or not isinstance(obj.data, dict):
                    obj.data = {}
                if "convert_settings" not in obj.data:
                    obj.data["convert_settings"] = {}

                current = obj.data["convert_settings"].get("multi_zip", False)
                obj.data["convert_settings"]["multi_zip"] = not current

                # Stay in multires submenu
                obj.data["convert_submenu"] = "multires"
                await obj.convert_select({})
                return

            elif action == "reslist":
                # For now, show current resolution list (future: allow editing)
                # This could be enhanced to allow custom input later
                if not hasattr(obj, "data") or not isinstance(obj.data, dict):
                    obj.data = {}
                if "convert_settings" not in obj.data:
                    obj.data["convert_settings"] = {}

                # Stay in multires submenu for now
                obj.data["convert_submenu"] = "multires"
                await obj.convert_select({})
                return

            # Legacy support for direct resolution selection (backward compatibility)
            elif action in ["1080p", "720p", "540p", "480p", "360p"]:
                # Store resolution and apply
                if not hasattr(obj, "data") or not isinstance(obj.data, dict):
                    obj.data = {}
                if "convert_settings" not in obj.data:
                    obj.data["convert_settings"] = {}

                obj.data["convert_settings"]["target_resolution"] = action
                obj.data = action  # For backward compatibility with executor
                obj.listener.data_from_video_tool_selection = True
                obj.event.set()
                return
        case "rmstream":
            ddict: dict = obj.data
            match data[2]:
                case "reset":
                    if sdata := ddict["sdata"]:
                        await safe_answer()
                        for map_index in sdata:
                            info = ddict["stream"][map_index]["info"]
                            ddict["stream"][map_index]["info"] = info.replace("✅ ", "")
                        sdata.clear()
                        await obj.update_message(*obj.streams_select())
                    else:
                        await safe_answer("No any selected stream to reset!", True)
                case "continue":
                    if ddict["sdata"]:
                        await safe_answer()
                        obj.listener.data_from_video_tool_selection = True
                        obj.event.set()
                    else:
                        await safe_answer("Please select at least one stream!", True)
                case "audio" | "subtitle" | "all" as value:
                    # Preselect requested group and allow user to deselect before continuing
                    await safe_answer()
                    target_types = []
                    if value == "audio":
                        target_types = ["audio"]
                    elif value == "subtitle":
                        target_types = ["subtitle"]
                    else:
                        target_types = ["audio", "subtitle"]

                    # Initialize sdata if missing
                    ddict.setdefault("sdata", [])
                    for map_index, stream_info in ddict.get("stream", {}).items():
                        if (
                            stream_info.get("type") in target_types
                            and map_index not in ddict["sdata"]
                            and map_index != 0
                        ):
                            ddict["sdata"].append(map_index)
                            info = stream_info.get("info", "")
                            if not info.startswith("✅ "):
                                stream_info["info"] = f"✅ {info}"
                    # Update message to let user deselect, do not proceed yet
                    await obj.update_message(*obj.streams_select())
                case "reverse":
                    if ddict["sdata"]:
                        await safe_answer()
                        new_sdata = [
                            x
                            for x in ddict["stream"]
                            if x not in ddict["sdata"] and x != 0
                        ]
                        for key, value_obj in ddict["stream"].items():
                            info = value_obj["info"]
                            ddict["stream"][key]["info"] = (
                                f"✅ {info}"
                                if key in new_sdata
                                else info.replace("✅ ", "")
                            )
                        ddict["sdata"] = new_sdata
                        await obj.update_message(*obj.streams_select())
                    else:
                        await safe_answer("No any selected stream to revers!", True)
                case value:
                    await safe_answer()
                    map_index = int(value)
                    info = ddict["stream"][map_index]["info"]
                    if map_index in ddict["sdata"]:
                        ddict["sdata"].remove(map_index)
                        ddict["stream"][map_index]["info"] = info.replace("✅ ", "")
                    else:
                        ddict["sdata"].append(map_index)
                        ddict["stream"][map_index]["info"] = f"✅ {info}"
                    await obj.update_message(*obj.streams_select())
        case "extract":
            value = data[2]
            await safe_answer()
            if value in ("extension", "fast"):
                ext_dict = {
                    "ass": [1, "srt"],
                    "srt": [1, "ass"],
                    "aac": [0, "ogg"],
                    "ogg": [0, "mp3"],
                    "mp3": [0, "ac3"],
                    "ac3": [0, "eac3"],
                    "eac3": [0, "m4a"],
                    "m4a": [0, "mka"],
                    "mka": [0, "wav"],
                    "wav": [0, "aac"],
                    "mp4": [2, "mkv"],
                    "mkv": [2, "mp4"],
                }
                if data[3] in ext_dict:
                    index, ext = ext_dict[data[3]]
                    obj.extension[index] = ext
                if value == "fast":
                    obj.data["fast_mode"] = not literal_eval(data[3])
                await obj.update_message(*obj.streams_select())
            else:
                obj.data.update(
                    {
                        "key": int(value) if value.isdigit() else data[2:],
                        "extension": obj.extension,
                    }
                )
                obj.listener.data_from_video_tool_selection = True
                obj.event.set()
