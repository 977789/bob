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
        self, video_encode_enabled=False, watermark_enabled=False, intro_enabled=False
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
        watermark_submenu = []
        intro_submenu = []
        trim_button = None
        misc = []

        for b in default:
            txt = (b.text or "").lower()
            if "streamswap" in txt or "extract" in txt or "remove" in txt:
                stream_buttons.append(b)
            elif "encode" in txt and "ffsubmenu" in (b.callback_data or ""):
                encode_submenu.append(b)
            elif "watermark" in txt and "ffsubmenu" in (b.callback_data or ""):
                watermark_submenu.append(b)
            elif "sub intro" in txt and "ffsubmenu" in (b.callback_data or ""):
                intro_submenu.append(b)
            elif txt.startswith("✓ trim") or txt.startswith("trim"):
                trim_button = b
            else:
                misc.append(b)

        # Stream operations row (Extract, Swap, Remove)
        if stream_buttons:
            add_row(stream_buttons[:3])  # Max 3 per row

        # Individual rows for advanced features
        if trim_button:
            add_row([trim_button])

        # Encoding submenu
        if encode_submenu and video_encode_enabled:
            add_row(encode_submenu[:2])

        # Watermark submenu
        if watermark_submenu and watermark_enabled:
            add_row(watermark_submenu[:2])

        # Intro subtitle submenu
        if intro_submenu and intro_enabled:
            add_row(intro_submenu[:2])

        # Miscellaneous operations
        if misc:
            # Split misc into rows of 2-3
            for i in range(0, len(misc), 3):
                add_row(misc[i : i + 3])

        # Last body section
        if l_body:
            for b in l_body:
                add_row([b])

        # Footer (Done, Cancel)
        if footer:
            add_row(footer[:3])

        return InlineKeyboardMarkup(menu)

    def build_advanced_menu(self):
        """Build an advanced menu layout with better organization"""
        return self.build_ffmpeg_menu(
            video_encode_enabled=True, watermark_enabled=True, intro_enabled=True
        )
