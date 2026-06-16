from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot.helper.telegram_helper.button_build import ButtonMaker


class FFmpgGroupType:
    CORE = 0
    MERGE = 1
    STREAM = 2
    ENCODE = 3
    WATERMARK = 4
    MISC = 5


class FFmpegButtonMaker(ButtonMaker):
    """
    Special ButtonMaker class for FFmpeg settings
    Customizes the build_menu method to create a precise layout for FFmpeg buttons
    """

    def __init__(self):
        super().__init__()
        # Additional dictionaries to store buttons by feature group
        self.grouped_buttons = {
            FFmpgGroupType.CORE: [],  # Core settings buttons
            FFmpgGroupType.MERGE: [],  # Merge operations buttons
            FFmpgGroupType.STREAM: [],  # Stream operations buttons
            FFmpgGroupType.ENCODE: [],  # Video encoding buttons
            FFmpgGroupType.WATERMARK: [],  # Watermark buttons
            FFmpgGroupType.MISC: [],  # Miscellaneous buttons
        }

    def feature_button(self, key, data, group_type, position=None):
        """Add a button that belongs to a specific feature group"""
        # Add to regular buttons collection for compatibility
        self.buttons[position if position in self.buttons else "default"].append(
            InlineKeyboardButton(text=key, callback_data=data)
        )

        # Also add to our grouped buttons
        if group_type in self.grouped_buttons:
            self.grouped_buttons[group_type].append(
                InlineKeyboardButton(text=key, callback_data=data)
            )

    def build_ffmpeg_menu(
        self,
        video_encode_enabled=False,
        video_convert_enabled=False,
        watermark_enabled=False,
        intro_enabled=False,
    ):
        """Dynamic grouped layout for FFmpeg Tools with submenu support (Layout V3)."""
        menu = []

        # Helper to add row if buttons exist
        def add_row(btns):
            row = [b for b in btns if b is not None]
            if row:
                menu.append(row)

        # Extract groups by textual cues
        header = self.buttons["header"]
        f_body = self.buttons["f_body"]
        default = self.buttons["default"]
        l_body = self.buttons["l_body"]
        footer = self.buttons["footer"]

        # Header (Meta)
        if header:
            add_row(header[:2])

        # Merge group (Video+Video, Video+Audio, Video+Subtitle)
        if f_body:
            if len(f_body) >= 1:
                # put all merge on one row if 3 exist, else split
                if len(f_body) >= 3:
                    add_row(f_body[:3])
                else:
                    for b in f_body:
                        add_row([b])

        # Categorize remaining default buttons by text
        stream_buttons = []
        encode_submenu = []
        convert_submenu = []
        watermark_submenu = []
        intro_submenu = []
        hardsub_submenu = []
        trim_button = None
        misc = []

        for b in default:
            txt = (b.text or "").lower()
            if "streamswap" in txt or "extract" in txt or "remove" in txt:
                stream_buttons.append(b)
            elif "encode" in txt and "ffsubmenu" in (b.callback_data or ""):
                encode_submenu.append(b)
            elif "convert" in txt and "ffsubmenu" in (b.callback_data or ""):
                convert_submenu.append(b)
            elif "watermark" in txt and "ffsubmenu" in (b.callback_data or ""):
                watermark_submenu.append(b)
            elif "sub intro" in txt and "ffsubmenu" in (b.callback_data or ""):
                intro_submenu.append(b)
            elif "hardsub" in txt and "ffsubmenu" in (b.callback_data or ""):
                hardsub_submenu.append(b)
            elif txt.startswith("✓ trim") or txt.startswith("trim"):
                trim_button = b
            else:
                misc.append(b)

        # Streams row(s)
        if stream_buttons:
            add_row(stream_buttons)

        # Submenu buttons row
        submenu_row = []
        if encode_submenu:
            submenu_row.extend(encode_submenu)
        if convert_submenu:
            submenu_row.extend(convert_submenu)
        if watermark_submenu:
            submenu_row.extend(watermark_submenu)
        if intro_submenu:
            submenu_row.extend(intro_submenu)
        if hardsub_submenu:
            submenu_row.extend(hardsub_submenu)

        if submenu_row:
            # Split into rows of 3
            for i in range(0, len(submenu_row), 3):
                add_row(submenu_row[i : i + 3])

        # Trim button: positioned after submenus
        if trim_button:
            add_row([trim_button])

        # Keep Source & other misc
        if l_body:
            add_row(l_body)
        if misc:
            for i in range(0, len(misc), 3):
                add_row(misc[i : i + 3])

        # Footer
        if footer:
            add_row(footer)

        return InlineKeyboardMarkup(menu)

    def build_encode_submenu(self):
        """Build submenu for encode settings."""
        menu = []

        # Helper to add row if buttons exist
        def add_row(btns):
            row = [b for b in btns if b is not None]
            if row:
                menu.append(row)

        # Get encode-related buttons
        default = self.buttons["default"]
        footer = self.buttons["footer"]

        encode_settings = []
        for b in default:
            txt = (b.text or "").lower()
            if txt in (
                "✓ preset",
                "preset",
                "✓ quality",
                "quality",
                "✓ crf",
                "crf",
                "✓ audio bitrate",
                "audio bitrate",
                "✓ video encode",
                "video encode",
            ):
                encode_settings.append(b)

        # Add encode settings in rows of 2-3
        for i in range(0, len(encode_settings), 3):
            add_row(encode_settings[i : i + 3])

        # Footer
        if footer:
            add_row(footer)

        return InlineKeyboardMarkup(menu)

    def build_convert_submenu(self):
        """Build submenu for video conversion settings."""
        menu = []

        # Helper to add row if buttons exist
        def add_row(btns):
            row = [b for b in btns if b is not None]
            if row:
                menu.append(row)

        # Get conversion-related buttons
        default = self.buttons["default"]
        footer = self.buttons["footer"]

        convert_settings = []
        for b in default:
            txt = (b.text or "").lower()
            if (
                txt.startswith("✓ format")
                or txt.startswith("format")
                or txt.startswith("✓ codec")
                or txt.startswith("codec")
                or txt.startswith("✓ quality")
                or txt.startswith("quality")
                or txt.startswith("✓ video convert")
                or txt.startswith("video convert")
                or "convert" in txt
                and ("format" in txt or "codec" in txt or "quality" in txt)
            ):
                convert_settings.append(b)

        # Add conversion settings in rows of 2-3
        for i in range(0, len(convert_settings), 3):
            add_row(convert_settings[i : i + 3])

        # Footer
        if footer:
            add_row(footer)

        return InlineKeyboardMarkup(menu)

    def build_watermark_submenu(self):
        """Build submenu for watermark settings."""
        menu = []

        # Helper to add row if buttons exist
        def add_row(btns):
            row = [b for b in btns if b is not None]
            if row:
                menu.append(row)

        # Get watermark-related buttons
        default = self.buttons["default"]
        footer = self.buttons["footer"]

        watermark_settings = []
        for b in default:
            txt = (b.text or "").lower()
            if (
                txt.startswith("✓ watermark")
                or txt.startswith("watermark")
                or txt.startswith("wm")
                or "wm " in txt
                or "wm-" in txt
                or txt.startswith("set text")
                or txt.startswith("set image")
                or "text-bg" in txt
                or "custom-font" in txt
                or "position" in txt
                or "opacity" in txt
                or "colour" in txt
                or "size" in txt
                or "duration" in txt
            ):
                watermark_settings.append(b)

        # Add watermark settings in rows of 2-3
        for i in range(0, len(watermark_settings), 3):
            add_row(watermark_settings[i : i + 3])

        # Footer
        if footer:
            add_row(footer)

        return InlineKeyboardMarkup(menu)

    def build_hardsub_submenu(self):
        """Build submenu for hardsub settings."""
        menu = []

        # Helper to add row if buttons exist
        def add_row(btns):
            row = [b for b in btns if b is not None]
            if row:
                menu.append(row)

        # Get hardsub-related buttons
        default = self.buttons["default"]
        footer = self.buttons["footer"]

        hardsub_settings = []
        for b in default:
            txt = (b.text or "").lower()
            if (
                txt.startswith("✓ hardsub")
                or txt.startswith("hardsub")
                or txt.startswith("✓ hs-")
                or txt.startswith("hs-")
            ):
                hardsub_settings.append(b)

        # Add hardsub settings in rows of 2-3
        for i in range(0, len(hardsub_settings), 3):
            add_row(hardsub_settings[i : i + 3])

        # Footer
        if footer:
            add_row(footer)

        return InlineKeyboardMarkup(menu)

    def build_intro_submenu(self):
        """Build submenu for intro subtitle settings."""
        menu = []

        # Helper to add row if buttons exist
        def add_row(btns):
            row = [b for b in btns if b is not None]
            if row:
                menu.append(row)

        # Get intro-related buttons
        default = self.buttons["default"]
        footer = self.buttons["footer"]

        intro_settings = []
        for b in default:
            txt = (b.text or "").lower()
            if (
                txt.startswith("✓ intro-sub")
                or txt.startswith("intro-sub")
                or txt.startswith("✓ is-")
                or txt.startswith("is-")
            ):
                intro_settings.append(b)

        # Add intro settings in rows of 2-3
        for i in range(0, len(intro_settings), 3):
            add_row(intro_settings[i : i + 3])

        # Footer
        if footer:
            add_row(footer)

        return InlineKeyboardMarkup(menu)
