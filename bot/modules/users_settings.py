# Modified by @MirrorHunterUpdates
# Corrected and Improved by Gemini

from asyncio import sleep
from functools import partial
from html import escape
from io import BytesIO
import os
from re import sub
from PIL import Image
from time import time

from aiofiles import open as aiopen
from aiofiles.os import makedirs, remove as aioremove, path as aiopath
from pyrogram.filters import create, command
from pyrogram.handlers import MessageHandler

from bot.helper.ext_utils.status_utils import get_readable_file_size

from .. import LOGGER, auth_chats, excluded_extensions, sudo_users, user_data
from ..core.config_manager import Config
from ..core.tg_client import TgClient
from ..helper.telegram_helper.bot_commands import BotCommands
from ..helper.telegram_helper.filters import CustomFilters
from ..helper.ext_utils.media_utils import create_reply_thumbnail
from ..helper.ext_utils.bot_utils import (
    get_size_bytes,
    new_task,
    update_user_ldata,
    sync_to_async,
)
from ..helper.ext_utils.db_handler import database
from ..helper.ext_utils.media_utils import create_thumb
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.message_utils import (
    delete_message,
    edit_message,
    send_file,
    send_message,
)

handler_dict = {}


async def safe_query_answer(query, *args, **kwargs):
    """Safely handle query.answer() to prevent crashes from expired callback queries"""
    try:
        await query.answer(*args, **kwargs)
    except Exception as e:
        LOGGER.debug(f"Query answer failed (likely expired): {e}")


leech_options = [
    "LEECH_SPLIT_SIZE",
    "LEECH_DUMP_CHAT",
    "LEECH_CAPTION",
    "FILENAME_SOURCE",
    "LEECH_CAPTION_FONT",
    "SHOW_MEDIAINFO_BUTTON",
    "ENABLE_STREAM_LINK",
    "TMDB_THUMBNAIL_TYPE",
    "SAMPLE_VIDEO_ENABLED",  # Sample video feature toggle
    "SAMPLE_VIDEO_COUNT",  # Number of random sample clips to generate
    "SAMPLE_VIDEO_DURATION",  # Duration (seconds) of each sample clip
    "SAMPLE_VIDEO_SEPARATE",  # Whether to output separate sample clips instead of merged
    "leech_completion_message",
]
common_tools_options = [
    "LEECH_PREFIX",
    "LEECH_SUFFIX",
    "REMNAME",
    "NAME_SWAP",
    "AUTO_RENAME",
    "RENAME_TEMPLATE",
    "START_EPISODE",
    "START_SEASON",
    "THUMBNAIL",
    "THUMBNAIL_LAYOUT",
    "SS_GRID_ENABLED",
    "SS_GRID_COUNT",
    "SS_GRID_LAYOUT",
    "SS_GRID_PDF_MODE",
    "SS_GRID_WATERMARK",
    "SS_GRID_PDF_INDIVIDUAL_PAGES",
]
rclone_options = ["RCLONE_CONFIG", "RCLONE_PATH", "RCLONE_FLAGS"]
gdrive_options = ["TOKEN_PICKLE", "GDRIVE_ID", "INDEX_URL"]
gofile_options = ["GOFILE_TOKEN", "GOFILE_FOLDER_ID"]
ffset_options = [
    "FFMPEG_CMDS",
    "METADATA_SETTINGS",
    "ZIP_METADATA",
    # Video encoding options
    "VIDEO_ENCODE_ENABLED",
    "VIDEO_ENCODE_CODEC",
    "VIDEO_ENCODE_PRESET",
    "VIDEO_ENCODE_QUALITY",
    "VIDEO_ENCODE_CRF",
    "VIDEO_ENCODE_AUDIO_BITRATE",
    "VIDEO_ENCODE_MULTI_RESOLUTION",
    "VIDEO_ENCODE_RESOLUTION_LIST",
    "VIDEO_ENCODE_MULTI_ZIP",
    # Video conversion options
    "VIDEO_CONVERT_ENABLED",
    "VIDEO_CONVERT_FORMAT",
    "VIDEO_CONVERT_CODEC",
    "VIDEO_CONVERT_QUALITY",
    # Video watermark options
    "VIDEO_WATERMARK_ENABLED",
    "VIDEO_WATERMARK_TEXT",
    "VIDEO_WATERMARK_POSITION",
    "VIDEO_WATERMARK_OPACITY",
    "VIDEO_WATERMARK_TYPE",
    "VIDEO_WATERMARK_IMAGE_PATH",
    "VIDEO_WATERMARK_FONT_SIZE",
    "VIDEO_WATERMARK_FONT_COLOR",
    "VIDEO_WATERMARK_TEXT_BACKGROUND",
    "VIDEO_WATERMARK_DURATION_TYPE",
    "VIDEO_WATERMARK_DURATION_SECONDS",
    "VIDEO_WATERMARK_FONT_PATH",
    # Intro subtitle feature
    "INTRO_SUBTITLE_ENABLED",
    "INTRO_SUBTITLE_TEXT",
    "INTRO_SUBTITLE_STYLE",
    "INTRO_SUBTITLE_FONT_PATH",
    "INTRO_SUBTITLE_FONT_SIZE",
    "INTRO_SUBTITLE_POSITION",
    "INTRO_SUBTITLE_COLORS",
    "INTRO_SUBTITLE_CHAR_MS",
    "INTRO_SUBTITLE_DURATION",  # New duration option in milliseconds
    # Video merge and manipulation
    "VIDEO_MERGE_ENABLED",
    "VIDEO_AUDIO_MERGE_ENABLED",
    "VIDEO_SUBTITLE_MERGE_ENABLED",
    "VIDEO_STREAM_EXTRACT_ENABLED",
    "STREAM_SWAP_ENABLED",
    "STREAM_REMOVE_ENABLED",
    "KEEP_MERGE_SOURCE_FILES",
    "VIDEO_TRIM_ENABLED",
    "CUSTOM_FILENAME",
]
advanced_options = [
    "EXCLUDED_EXTENSIONS",
    "NAME_SWAP",
    "YT_DLP_OPTIONS",
    "UPLOAD_PATHS",
    "REMNAME",
    "USER_SESSION_STRING",
]
yt_options = [
    "YT_DESP",
    "YT_TAGS",
    "YT_CATEGORY_ID",
    "YT_PRIVACY_STATUS",
    "YTDLP_COOKIES",
]
vt_options = [
    # Legacy video tools options
    "VT_AUDIO_REMOVE",
    "VT_AUDIO_ORDER",
    "VT_TRIM_RANGE",
    "VT_SPEED",
    "VT_COMPRESS",
    "VT_EXTRACT",
    "VT_WATERMARK",
    "VT_WATERMARK_ENABLED",
    "VT_WATERMARK_POSITION",
    "VT_WATERMARK_OPACITY",
    "VT_WATERMARK_TYPE",
    "VT_WATERMARK_FONT_SIZE",
    "VT_WATERMARK_FONT_COLOR",
    "VT_WATERMARK_TEXT_BACKGROUND",
    "VT_WATERMARK_DURATION_TYPE",
    "VT_WATERMARK_DURATION_SECONDS",
    "VT_MERGE_VIDEOS",
    "VT_MERGE_AUDIOS",
    "VT_MERGE_SUBS",
    "VT_CONVERT_QUALITY",
    "VT_WATERMARK_IMAGE",
    "VT_SUBSYNC",
    "VT_RENAME_TO",
    "VT_HARDSUB_STYLE",
    "VT_WATERMARK_TEXT",
    "VT_WM_FONT_PATH",
    "VT_WM_FONT_BOLD",
    "VT_WATERMARK_SIZE",
    # Advanced hardsub options
    "VT_HARDSUB_FONT_PATH",
    "VT_HARDSUB_FONT_SIZE",
    "VT_HARDSUB_FONT_COLOR",
    "VT_HARDSUB_SECONDARY_COLOR",
    "VT_HARDSUB_OUTLINE_COLOR",
    "VT_HARDSUB_BACK_COLOR",
    "VT_HARDSUB_OUTLINE_WIDTH",
    "VT_HARDSUB_SHADOW_DEPTH",
    "VT_HARDSUB_ALIGNMENT",
    "VT_HARDSUB_MARGIN_L",
    "VT_HARDSUB_MARGIN_R",
    "VT_HARDSUB_MARGIN_V",
    "VT_HARDSUB_DELAY",
    "VT_HARDSUB_DURATION",
    "VT_HARDSUB_ITALIC",
    "VT_HARDSUB_UNDERLINE",
    "VT_HARDSUB_STRIKEOUT",
    "VT_HARDSUB_ENHANCE_CONTRAST",
    "VT_HARDSUB_ENHANCE_SATURATION",
    "VT_HARDSUB_ENHANCE_BRIGHTNESS",
    "VT_HARDSUB_PRESERVE_COLORS",
    # Enhanced video encoding options
    "VIDEO_ENCODE_ENABLED",
    "VIDEO_ENCODE_CODEC",
    "VIDEO_ENCODE_PRESET",
    "VIDEO_ENCODE_QUALITY",
    "VIDEO_ENCODE_CRF",
    "VIDEO_ENCODE_AUDIO_BITRATE",
    "VIDEO_ENCODE_MULTI_RESOLUTION",
    "VIDEO_ENCODE_RESOLUTION_LIST",
    "VIDEO_ENCODE_MULTI_ZIP",
    # Enhanced video conversion options
    "VIDEO_CONVERT_ENABLED",
    "VIDEO_CONVERT_FORMAT",
    "VIDEO_CONVERT_CODEC",
    "VIDEO_CONVERT_QUALITY",
    # Enhanced video merging options
    "VIDEO_MERGE_ENABLED",
    "VIDEO_AUDIO_MERGE_ENABLED",
    "VIDEO_SUBTITLE_MERGE_ENABLED",
    "VIDEO_STREAM_EXTRACT_ENABLED",
    # Enhanced video watermarking options
    "VIDEO_WATERMARK_ENABLED",
    "VIDEO_WATERMARK_TEXT",
    "VIDEO_WATERMARK_POSITION",
    "VIDEO_WATERMARK_OPACITY",
    "VIDEO_WATERMARK_TYPE",
    "VIDEO_WATERMARK_IMAGE_PATH",
    "VIDEO_WATERMARK_FONT_SIZE",
    "VIDEO_WATERMARK_FONT_COLOR",
    "VIDEO_WATERMARK_TEXT_BACKGROUND",
    "VIDEO_WATERMARK_DURATION_TYPE",
    "VIDEO_WATERMARK_DURATION_SECONDS",
    "VIDEO_WATERMARK_FONT_PATH",
    # Intro subtitle options
    "INTRO_SUBTITLE_ENABLED",
    "INTRO_SUBTITLE_TEXT",
    "INTRO_SUBTITLE_STYLE",
    "INTRO_SUBTITLE_MODE",
    "INTRO_SUBTITLE_FONT_PATH",
    "INTRO_SUBTITLE_FONT_SIZE",
    "INTRO_SUBTITLE_POSITION",
    "INTRO_SUBTITLE_COLORS",
    "INTRO_SUBTITLE_CHAR_MS",
    # Other video processing options
    "CUSTOM_FILENAME",
    "VIDEO_TRIM_ENABLED",
    "SAMPLE_VIDEO_ENABLED",
    "SAMPLE_VIDEO_COUNT",
    "SAMPLE_VIDEO_DURATION",
    "SAMPLE_VIDEO_SEPARATE",
]

# User-friendly descriptions for settings
user_settings_text = {
    "THUMBNAIL": (
        "Photo or Document",
        "Sets a custom thumbnail for files uploaded to Telegram.",
        """<i>🖼️ Upload a photo to set it as your custom thumbnail.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "RCLONE_CONFIG": (
        "rclone.conf File",
        "Configures your Rclone (remote cloud storage) destination.",
        """<i>📁 Upload your <code>rclone.conf</code> file to set up your Rclone destination.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "TOKEN_PICKLE": (
        "token.pickle File",
        "Configures your Google Drive upload destination.",
        """<i>📁 Upload your <code>token.pickle</code> file to set up your Google Drive destination.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "LEECH_SPLIT_SIZE": (
        "Size (e.g., 2.5GB, 1000MB)",
        "Sets the file split size for Telegram uploads.",
        f"""<i>💾 Specify the leech split size. Examples: 40000000 (bytes), 2.5GB, 1000MB. Premium User: {TgClient.IS_PREMIUM_USER}.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "LEECH_DUMP_CHAT": (
        "Chat ID, Username, or 'pm'",
        "Sets the destination chat for leeched files.",
        """<i>📍 Specify the leech destination using:</i><br>
<i>• <code>b:id/@username/pm</code> (Bot uploads to chat ID, username, or your PM)</i><br>
<i>• <code>u:id/@username</code> (User account uploads, requires USER_SESSION_STRING)</i><br>
<i>• <code>h:id/@username</code> (Hybrid mode, bot/user upload based on file size)</i><br>
<i>• <code>id/@username|topic_id</code> (Leech to a specific chat topic)</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "MIRROR_DUMP_CHAT": (
        "Integer",
        "Chat ID where mirror completions will be forwarded. This allows you to automatically send mirror links to a specific chat.",
        "<i>Send chat ID (with -100 prefix for supergroups) to set mirror dump destination.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "LEECH_PREFIX": (
        "Text (HTML supported)",
        "Adds a prefix to filenames (e.g., a channel name).",
        """<i>🔖 Enter the prefix for filenames (e.g., <code>@mychannel</code>). HTML tags are supported.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "LEECH_SUFFIX": (
        "Text (HTML supported)",
        "Adds a suffix to filenames (e.g., a quality tag).",
        """<i>🔖 Enter the suffix for filenames (e.g., <code>-4K</code>). HTML tags are supported.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "LEECH_CAPTION": (
        "Text with Template Support",
        "Sets a custom caption for uploaded files.",
        """<i>📝 Create a custom leech caption. You can use these formatting templates:</i><br>
<i>• <code>{{filename}}</code>: Full file name</i><br>
<i>• <code>{{name}}</code>: File name without extension</i><br>
<i>• <code>{{size}}</code>: File size (e.g., 2.45GB)</i><br>
<i>• <code>{{file_caption}}</code>: Original file caption</i><br>
<i>• <code>{{resolution}}</code>, <code>{{quality}}</code>, <code>{{year}}</code></i><br>
<i>• <code>{{season}}</code> (S01), <code>{{episode}}</code> (E03)</i><br>
<i>• <code>{{languages}}</code>, <code>{{subtitles}}</code>, <code>{{audios}}</code></i><br>
<i>• <code>{{duration}}</code> (HH:MM:SS), <code>{{ott}}</code> (e.g., Netflix)</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "FILENAME_SOURCE": (
        "Options: 'filename' or 'caption'",
        "Chooses whether to name the file from its original filename or from the message caption.",
        """<i>📝 Choose the source for the filename: 'filename' (original name) or 'caption' (Telegram message caption).</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "LEECH_CAPTION_FONT": (
        "Options: normal, bold, italic, mono",
        "Sets the font style for the filename in the caption.",
        """<i>💅 Choose a font for the filename in the caption: 'normal', 'bold', 'italic', or 'mono'. This only applies if your caption uses '{{filename}}'.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "THUMBNAIL_LAYOUT": (
        "Dimensions (e.g., 3x3)",
        "Sets the layout for thumbnail grids.",
        """<i>🖼️ Specify the thumbnail grid layout (e.g., <code>3x3</code>, <code>2x4</code>).</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "RCLONE_PATH": (
        "Rclone Path",
        "Sets the default Rclone upload path.",
        """<i>📁 Specify the Rclone destination path (e.g., <code>drive:folder/subfolder</code>). Use <code>mrcc:</code> for a custom config file.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "RCLONE_FLAGS": (
        "Rclone Flags",
        "Set custom flags for Rclone uploads to control its behavior.",
        """<i>⚙️ Provide Rclone flags separated by <code>|</code> (e.g., <code>--buffer-size:8M|--drive-starred-only</code>). For a full list, see the <a href='https://rclone.org/flags/'>official Rclone documentation</a>.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "GDRIVE_ID": (
        "Folder ID or URL",
        "Sets the Google Drive folder for uploads.",
        """<i>📁 Enter the Google Drive Folder ID or URL (e.g., <code>1Abc...xyz</code> or <code>mtp:F435...</code> for a custom token).</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "INDEX_URL": (
        "URL",
        "Sets the index link URL to be added to Google Drive uploads.",
        """<i>🔗 Enter the index link URL for your Google Drive files.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "GOFILE_TOKEN": (
        "API Token",
        "Sets your GoFile API token for uploads.",
        """<i>🔑 Enter your GoFile API token. You can get one from your <a href='https://gofile.io/myProfile'>GoFile Profile</a> page.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "GOFILE_FOLDER_ID": (
        "Folder ID",
        "Sets the GoFile Folder ID for uploads (optional).",
        """<i>📁 Enter the GoFile Folder ID. If you leave this empty, files will be uploaded to the main (root) folder.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "UPLOAD_PATHS": (
        "Python Dictionary Format",
        "Configures multiple shortcut paths for different upload services.",
        """<i>📂 Provide upload path shortcuts in a dictionary format (e.g., <code>{'gd': 'gdrive_id', 'rc': 'remote:folder'}</code>).</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "EXCLUDED_EXTENSIONS": (
        "Space-Separated List",
        "Sets file extensions to exclude from any processing.",
        """<i>🚫 Enter extensions to exclude, separated by spaces (e.g., <code>txt pdf doc</code>). Do not include the dot.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "NAME_SWAP": (
        "Text or Pattern",
        "Configures filename swapping patterns.",
        """<i>🔄 Enter a name swapping pattern or text.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "YT_DLP_OPTIONS": (
        "Python Dictionary Format",
        "Define custom options for yt-dlp to control download behavior.",
        """<i>📥 Provide your yt-dlp options in a dictionary format (e.g., <code>{'format': 'bv*+mergeall[vcodec=none]', 'nocheckcertificate': True}</code>). Refer to the <a href='https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/YoutubeDL.py#L184'>yt-dlp documentation</a> for all available options.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "FFMPEG_CMDS": (
        "Python Dictionary Format",
        "Sets custom FFmpeg commands for file processing.",
        """<i>🎥 Enter FFmpeg commands in a dictionary format (e.g., <code>{'subtitle': ['-i mltb.mkv -c copy -c:s srt mltb.mkv']}</code>).</i><br>
<i><b>Notes:</b></i><br>
<i>• Add <code>-del</code> to delete the original file after processing.</i><br>
<i>• Use <code>mltb.*</code> as a placeholder for the filename (e.g., <code>mltb.mkv</code> for MKV files).</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "GEN_METADATA": (
        "Metadata Text",
        "Sets the general metadata for all streams.",
        """<i>Enter metadata using one of the supported formats below.</i><br>
<i><b><u>Supported Formats:</u></b></i><br>
<i>• <b>Simplified:</b> <code>My Video Title</code> (applies to all default tags)</i><br>
<i>• <b>Simple Pipe:</b> <code>title|artist|album...</code> (e.g., <code>My Video|Artist|Album</code>)</i><br>
<i>• <b>Key-Value Pipe:</b> <code>key=value|key=value</code> (e.g., <code>title=My Title|artist=The Artist</code>)</i><br>
<i>• <b>Key-Value Comma:</b> <code>key=\"value\", key=\"value\"</code> (e.g., <code>title=\"My Title\", artist=\"The Artist\"</code>)</i><br>
<i>• <b>Stream-Specific:</b> <code>key:stream_index=value</code> (e.g., <code>title:0=My Title</code> for stream 0)</i><br><br>
<i><b><u>Dynamic Variables (usable in values):</u></b></i><br>
<i>• <code>{filename}</code> Full filename</i><br>
<i>• <code>{basename}</code> Filename without extension</i><br>
<i>• <code>{extension}</code> File extension</i><br>
<i>• <code>{audiolang}</code> Audio language(s)</i><br>
<i>• <code>{sublang}</code> Subtitle language(s)</i><br>
<i>• <code>{year}</code> Year parsed from filename</i><br>
<i>Example: <code>title={basename} ({year})|comment=Audio: {audiolang} | Subs: {sublang}</code></i><br><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "VID_METADATA": (
        "Metadata Text",
        "Sets metadata specifically for video streams.",
        """<i>Enter metadata using one of the supported formats below.</i><br>
<i><b><u>Supported Formats:</u></b></i><br>
<i>• <b>Simplified:</b> <code>My Video Title</code> (applies to all default tags)</i><br>
<i>• <b>Simple Pipe:</b> <code>title|artist|album...</code> (e.g., <code>My Video|Artist|Album</code>)</i><br>
<i>• <b>Key-Value Pipe:</b> <code>key=value|key=value</code> (e.g., <code>title=My Title|artist=The Artist</code>)</i><br>
<i>• <b>Key-Value Comma:</b> <code>key=\"value\", key=\"value\"</code> (e.g., <code>title=\"My Title\", artist=\"The Artist\"</code>)</i><br>
<i>• <b>Stream-Specific:</b> <code>key:stream_index=value</code> (e.g., <code>title:0=My Title</code> for stream 0)</i><br><br>
<i><b><u>Dynamic Variables (usable in values):</u></b></i><br>
<i>• <code>{filename}</code>, <code>{basename}</code>, <code>{extension}</code>, <code>{year}</code></i><br>
<i>Example: <code>title={basename} ({year})</code></i><br><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "AUD_METADATA": (
        "Metadata Text",
        "Sets metadata specifically for audio streams.",
        """<i>Enter metadata using one of the supported formats below.</i><br>
<i><b><u>Supported Formats:</u></b></i><br>
<i>• <b>Simplified:</b> <code>My Video Title</code> (applies to all default tags)</i><br>
<i>• <b>Simple Pipe:</b> <code>title|artist|album...</code> (e.g., <code>My Video|Artist|Album</code>)</i><br>
<i>• <b>Key-Value Pipe:</b> <code>key=value|key=value</code> (e.g., <code>title=My Title|artist=The Artist</code>)</i><br>
<i>• <b>Key-Value Comma:</b> <code>key=\"value\", key=\"value\"</code> (e.g., <code>title=\"My Title\", artist=\"The Artist\"</code>)</i><br>
<i>• <b>Stream-Specific:</b> <code>key:stream_index=value</code> (e.g., <code>title:0=My Title</code> for stream 0)</i><br><br>
<i><b><u>Dynamic Variables (usable in values):</u></b></i><br>
<i>• <code>{audiolang}</code>, <code>{filename}</code>, <code>{basename}</code>, <code>{extension}</code></i><br>
<i>Example: <code>language={audiolang}</code></i><br><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "SUB_METADATA": (
        "Metadata Text",
        "Sets metadata specifically for subtitle streams.",
        """<i>Enter metadata using one of the supported formats below.</i><br>
<i><b><u>Supported Formats:</u></b></i><br>
<i>• <b>Simplified:</b> <code>My Video Title</code> (applies to all default tags)</i><br>
<i>• <b>Simple Pipe:</b> <code>title|artist|album...</code> (e.g., <code>My Video|Artist|Album</code>)</i><br>
<i>• <b>Key-Value Pipe:</b> <code>key=value|key=value</code> (e.g., <code>title=My Title|artist=The Artist</code>)</i><br>
<i>• <b>Key-Value Comma:</b> <code>key=\"value\", key=\"value\"</code> (e.g., <code>title=\"My Title\", artist=\"The Artist\"</code>)</i><br>
<i>• <b>Stream-Specific:</b> <code>key:stream_index=value</code> (e.g., <code>title:0=My Title</code> for stream 0)</i><br><br>
<i><b><u>Dynamic Variables (usable in values):</u></b></i><br>
<i>• <code>{sublang}</code>, <code>{filename}</code>, <code>{basename}</code>, <code>{extension}</code></i><br>
<i>Example: <code>language={sublang}</code></i><br><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "METADATA_CMDS": (
        "Metadata Commands",
        "Sets metadata commands for files.",
        """<i>🎬 Enter metadata commands (e.g., <code>title='Join @MirrorHunterUpdates'</code>). See <a href='https://t.me/MirrorHunterUpdates/'>Documentation</a>.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "YT_DESP": (
        "Text",
        "Sets a custom description for your YouTube uploads.",
        """<i>📜 Enter the custom description for your YouTube uploads.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "YT_TAGS": (
        "Comma-Separated Text",
        "Sets custom tags (keywords) for your YouTube uploads.",
        """<i>🏷️ Enter YouTube tags separated by commas (e.g., <code>tag1,tag2,tag3</code>).</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "YT_CATEGORY_ID": (
        "Number",
        "Sets the category ID for YouTube uploads (e.g., 22 for 'People & Blogs').",
        """<i>🔢 Enter the YouTube category ID (e.g., <code>22</code>).</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "YT_PRIVACY_STATUS": (
        "Text: 'public', 'private', or 'unlisted'",
        "Sets the privacy status for your YouTube uploads.",
        """<i>🔒 Enter the YouTube privacy status: <code>public</code>, <code>private</code>, or <code>unlisted</code>.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "AUTO_RENAME": (
        "Toggle ON/OFF",
        "Enables or disables automatic file renaming based on a template.",
        "<i>✅ Toggle to enable or disable Auto Rename. Configure the template in the 'Auto Rename' submenu.</i>",
    ),
    "RENAME_TEMPLATE": (
        "Template String",
        "Sets the template for renaming files.",
        """<i>📝 Enter the rename template (e.g., <code>S{{season}}E{{episode}} - {{quality}}</code> or <code>{{title}} ({{year}}) [{{rating}}]</code>). This is used for both Auto and Manual rename modes.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "START_EPISODE": (
        "Number",
        "Sets the starting episode number for batch renaming in 'Manual' mode.",
        """<i>🔢 Enter the starting episode number (e.g., <code>1</code>). This only applies if Auto Rename is set to 'Manual' mode.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "START_SEASON": (
        "Number",
        "Sets the starting season number for batch renaming in 'Manual' mode.",
        """<i>🔢 Enter the starting season number (e.g., <code>1</code>). This only applies if Auto Rename is set to 'Manual' mode.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "AUTO_THUMBNAIL": (
        "Boolean",
        "Enables or disables automatic thumbnail fetching from TMDB/IMDB.",
        """<i>🖼️ Enter <code>true</code> or <code>false</code> to enable or disable automatic thumbnail generation from online databases.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "TMDB_THUMBNAIL_TYPE": (
        "Options: 'poster' or 'backdrop'",
        "Sets the image type (poster or backdrop) to fetch for auto thumbnails.",
        "<i>🖼️ Choose the TMDB image type: 'poster' (vertical) or 'backdrop' (horizontal). The default is 'poster'. This is used if AUTO_THUMBNAIL is enabled.</i>",
    ),
    "YTDLP_COOKIES": (
        "cookies.txt File",
        "Sets a custom cookies file for yt-dlp to access private content.",
        """<i>📁 Upload your <code>cookies.txt</code> file for yt-dlp. This is needed for sites that require a login.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "SHOW_MEDIAINFO_BUTTON": (
        "Boolean",
        "Shows or hides the 'Media Info' button on uploaded files.",
        """<i>✅ Enter <code>true</code> or <code>false</code> to show or hide the Media Info button.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "ENABLE_STREAM_LINK": (
        "Boolean",
        "Shows or hides the 'Stream' and 'Download' buttons on uploaded files.",
        """<i>✅ Enter <code>true</code> or <code>false</code> to show or hide the Stream and Download buttons.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "SS_GRID_ENABLED": (
        "Boolean",
        "Enables or disables the screenshot grid generation feature.",
        """<i>🖼️ Enter <code>true</code> or <code>false</code> to enable or disable the screenshot grid feature.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "SS_GRID_COUNT": (
        "Number",
        "Sets the number of screenshots to capture for the grid.",
        """<i>🔢 Enter the number of screenshots for the grid (a value between 1-20 is recommended).</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "SS_GRID_LAYOUT": (
        "Dimensions (e.g., 3x3)",
        "Sets the layout (rows and columns) for the screenshot grid.",
        """<i>🖼️ Enter the grid layout (e.g., <code>3x3</code>, <code>2x4</code>).</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "SS_GRID_PDF_MODE": (
        "Boolean",
        "Compiles the screenshot grid into a single PDF file.",
        """<i>📄 Enter <code>true</code> or <code>false</code> to enable or disable compiling screenshots into a PDF.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "SS_GRID_WATERMARK": (
        "Text",
        "Adds a watermark text to the screenshot grid PDF.",
        """<i>🔖 Enter the watermark text for the screenshot grid PDF. Enter <code>None</code> to disable it.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "SS_GRID_PDF_INDIVIDUAL_PAGES": (
        "Boolean",
        "If PDF mode is on, this creates a separate page for each screenshot.",
        """<i>📄 Enter <code>true</code> or <code>false</code> to put each screenshot on an individual page in the PDF.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "DEFAULT_UPLOAD_SERVICE": (
        "Submenu",
        "Sets the default service (GDrive, Rclone, etc.) for uploads.",
        "<i>🚀 Choose your preferred default upload service when no specific uploader is chosen in a command.</i>",
    ),
    "EMBED_DEFAULT_USER_THUMBNAIL": (
        "Toggle ON/OFF",
        "Automatically attach your default thumbnail to uploads if no other thumbnail is specified.",
        "<i>🖼️ Toggle to automatically embed your default user thumbnail.</i>",
    ),
    "USER_ATTACHMENT_TEXT": (
        "Text",
        "Set custom text to attach as a .txt file with your uploads.",
        """<i>📝 Enter the text you want to attach as a file. Send 'none' or use the Clear button to remove it.</i>""",
    ),
    "USER_ATTACHMENT_PHOTO": (
        "Photo Upload",
        "Set a custom photo to attach with your uploads.",
        """<i>🖼️ Send the photo you want to use as a custom attachment, or reply to an existing photo message.</i>""",
    ),
    "ZIP_METADATA": (
        "Toggle ON/OFF",
        "If enabled, metadata will be applied to files before zipping.",
        "<i>⚙️ Toggle to enable or disable applying metadata to files during zip operations.</i>",
    ),
    "REMNAME": (
        "Text or Pattern (use | to separate)",
        "Sets text patterns to remove from filenames.",
        """<i>🚫 Enter text or patterns to remove from filenames. Separate multiple items with a pipe <code>|</code> (e.g., <code>[TGx] | .XYZ</code>).</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "leech_completion_message": (
        "Toggle ON/OFF",
        "Enables or disables the 'leech completed' notification message.",
        "<i>✅ Toggle to enable or disable the leech completed message.</i>",
    ),
    "LEECH_DUMP_CHAT": (
        "Chat ID, Username, or 'pm'",
        "Sets the destination chat for leeched files.",
        """<i>📍 Specify the leech destination using:</i><br>
<i>• <code>b:id/@username/pm</code> (Bot uploads to chat ID, username, or your PM)</i><br>
<i>• <code>u:id/@username</code> (User account uploads, requires USER_SESSION_STRING)</i><br>
<i>• <code>h:id/@username</code> (Hybrid mode, bot/user upload based on file size)</i><br>
<i>• <code>id/@username|topic_id</code> (Leech to a specific chat topic)</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "USER_SESSION_STRING": (
        "Pyrogram Session String",
        "Allows the bot to download from private chats/channels you are in.",
        """<i>Send your Pyrogram (v2) session string. This lets the bot access content from your private chats. You can generate one using the /gensession command.</i>""",
    ),
    "VT_AUDIO_REMOVE": (
        "Comma-separated audio indexes (e.g., 0,2)",
        "Audio Removal removes specified audio streams by their audio index (not global stream index).",
        """<b>㊂ Audio Remove Settings :</b>
╭ <b>L/M Filename Audio Remove</b> : <i>{status}</i>
├ <b>Description</b> : Audio Removal removes specified audio streams.

Example:
Default audio: audio : 0, audio : 1, audio : 2
Specified audio: 0,2

<i>Send audio indexes to remove (e.g., <code>0,2</code>).</i>
╰<b>Time Left :</b> <code>60 sec</code>""",
    ),
    "VT_AUDIO_ORDER": (
        "Comma-separated new order (e.g., 2,1,3,0)",
        "Audio Swapping reorders audio streams by their audio index (not global stream index).",
        """<b>㊂ Audio Change Settings :</b>
╭ <b>L/M Filename Audio Change</b> : <i>{status}</i>
├ <b>Description</b> : Audio Swapping modifies the order/arrangement of audio streams.

Example:
Default: audio : 0, audio : 1, audio : 2, audio : 3
New Arrangement: 2,1,3,0

<i>Send new audio order (e.g., <code>2,1,3,0</code>).</i>
╰<b>Time Left :</b> <code>60 sec</code>""",
    ),
    "VT_TRIM_RANGE": (
        "Time range (e.g., 00:00:10-00:01:30)",
        "Trims video between start and end timestamps.",
        """<b>㊂ Trim Settings</b>
╭ <b>Description</b> : Cut a segment from the video using start-end times.
├ <b>Format</b> : <code>HH:MM:SS-HH:MM:SS</code>
╰ <b>Example</b> : <code>00:00:10-00:01:30</code>
""",
    ),
    "VT_SPEED": (
        "Speed config (e.g., up,2.0 or down,0.5)",
        "Changes playback speed for video and audio.",
        """<b>㊂ Speed Settings</b>
╭ <b>Description</b> : Speed up or slow down.
├ <b>Format</b> : <code>up,2.0</code> or <code>down,0.5</code>
╰ <b>Example</b> : <code>up,1.25</code>
""",
    ),
    "VT_COMPRESS": (
        "Compress config (e.g., quality=720p,crf=23,bitrate=1000,bitdepth=yuv420p10le)",
        "Compresses/re-encodes the video with optional scaling and audio settings.",
        """<b>㊂ Compress Settings</b>
╭ <b>Description</b> : Set quality scale and encoder options.
├ <b>Keys</b> : <code>quality</code>, <code>crf</code>, <code>bitrate</code>, <code>bitdepth</code>
├ <b>Example</b> : <code>quality=720p,crf=23,bitrate=1200,bitdepth=yuv420p10le</code>
╰ <b>Note</b> : Omit keys you don't need.
""",
    ),
    "VT_EXTRACT": (
        "Extract config (e.g., video,audio,subtitle|aac,srt,mkv)",
        "Extract streams to separate files with chosen extensions.",
        """<b>㊂ Extract Settings</b>
╭ <b>Description</b> : Choose stream types to extract and output extensions.
├ <b>Format</b> : <code>types|exts</code> where types is comma list of video,audio,subtitle and exts is <code>aac,srt,mkv</code>
╰ <b>Example</b> : <code>audio,subtitle|aac,srt,mkv</code>
""",
    ),
    "VT_WATERMARK": (
        "Watermark config (e.g., size=20,position=10:10,popup=0,hardsub=false)",
        "Adds watermark; optionally burn subtitles (hardsub).",
        """<b>㊂ Watermark Settings</b>
╭ <b>Description</b> : Configure watermark overlay and hardsub.
├ <b>Keys</b> : <code>size</code>, <code>position</code>, <code>popup</code>, <code>hardsub</code>
├ <b>Example</b> : <code>size=20,position=10:10,popup=0,hardsub=false</code>
╰ <b>Note</b> : For hardsub font settings, keep default or adjust later.
""",
    ),
    "VT_WATERMARK_TEXT": (
        "Watermark Text",
        "Sets the text to overlay when using watermark tool (if no image is set).",
        """<i>🖋️ Send the watermark text to render on video (e.g., <code>@yourchannel</code>).</i><br>
<i>Tip: Use with 'Set WM Position' and optional WM image. If an image is uploaded, text will be added alongside the image.</i>""",
    ),
    "VT_WM_FONT_PATH": (
        "Font (TTF/OTF) Document",
        "Optional font for text watermark (drawtext).",
        """<i>📁 Upload a .ttf or .otf file to be used by the watermark text renderer.</i>""",
    ),
    "VT_WM_FONT_BOLD": (
        "Boolean",
        "Bold style for watermark text (if supported by font).",
        """<i>🔤 Send true/false to toggle bold style for drawtext watermark text.</i>""",
    ),
    "VT_MERGE_VIDEOS": (
        "Merge Videos",
        "Enable or disable merging of video streams.",
        """<i>🎥 Enable or disable merging of video streams. This is useful for combining multiple video files into a single file.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "VT_MERGE_AUDIOS": (
        "Merge Audios",
        "Enable or disable merging of audio streams.",
        """<i>🎧 Enable or disable merging of audio streams. This is useful for combining multiple audio files into a single file.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "VT_MERGE_SUBS": (
        "Merge Subtitles",
        "Enable or disable merging of subtitle streams.",
        """<i>🎞️ Enable or disable merging of subtitle streams. This is useful for combining multiple subtitle files into a single file.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "VT_CONVERT_QUALITY": (
        "Convert Quality",
        "Convert video quality to a specified format.",
        """<i>🎞️ Enter the desired quality or extended options.</i><br>
<b>Examples:</b><br>
- <code>720p</code><br>
- <code>1080p,crf=22</code><br>
- <code>540p,bitrate=1200</code> (kbps)<br>
- <code>480p,crf=24,bitrate=800,bitdepth=yuv420p10le</code><br>
<b>Keys:</b> <code>crf</code> (0-51), <code>bitrate</code> (in kbps), <code>bitdepth</code> (e.g., yuv420p10le)<br>
<i>Tip: Works like -vt Convert. Omit keys you don't need.</i>""",
    ),
    "VT_WATERMARK_IMAGE": (
        "Watermark Image",
        "Set a watermark image for the video.",
        """<i>🖼️ Upload an image to set as the watermark. This image will be added to the video at the specified position.</i><br>
<b>Supported:</b> PNG, JPG, JPEG, BMP, GIF, WEBP. If one method fails, try uploading as a <b>Document</b> instead of Photo (or vice versa).<br>
<i>Animated images will use the first frame.</i>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "VT_SUBSYNC": (
        "Boolean",
        "Enable automatic subtitle sync across files in a folder (no manual selection).",
        """<i>🔁 Send true/false to enable or disable automatic subtitle synchronization.</i><br>
<i>When enabled, the bot will run subtitle auto-sync where applicable.</i>""",
    ),
    "VT_RENAME_TO": (
        "String",
        "Rename the final output file to the specified name (extension preserved).",
        """<i>✏️ Send the new base filename (without extension). The original extension will be preserved.</i><br>
<i>Example:</i> <code>My Show S01E01</code>""",
    ),
    "VT_HARDSUB_STYLE": (
        "String",
        "Set hardsub subtitle style. Options: default, bold, outline, shadow, glow.",
        """<i>🎞️ Enter hardsub style: <code>default</code>, <code>bold</code>, <code>outline</code>, <code>shadow</code>, or <code>glow</code>.</i><br>
<i>This controls how burned-in subtitles appear on the video. Default uses original subtitle formatting.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "VT_HARDSUB_FONT_PATH": (
        "File",
        "Custom font file for hardsub subtitles (TTF/OTF).",
        """<i>🔤 Upload a TTF or OTF font file to use for hardsub subtitles.</i><br>
<i>This will override the default font. Leave empty to use system default font.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "VT_HARDSUB_FONT_SIZE": (
        "Integer",
        "Font size for hardsub subtitles (default: 22).",
        """<i>📏 Enter a number for subtitle font size (e.g., 18, 24, 32).</i><br>
<i>Larger values make subtitles more prominent but may cover more of the video.</i>""",
    ),
    "VT_HARDSUB_FONT_COLOR": (
        "Color Code",
        "Primary color for hardsub subtitles (ASS color format).",
        """<i>🎨 Enter color in ASS format: &HBBGGRR (e.g., &H00FFFFFF for white, &H000000FF for red, &H0000FFFF for yellow).</i><br>
<i>Format: &H + Blue + Green + Red in hexadecimal. Common colors:</i><br>
<i>• White: &H00FFFFFF • Red: &H000000FF • Yellow: &H0000FFFF • Green: &H0000FF00 • Blue: &H00FF0000 • Black: &H00000000</i>""",
    ),
    "VT_HARDSUB_SECONDARY_COLOR": (
        "Color Code",
        "Secondary color for hardsub subtitles (used for karaoke effects).",
        """<i>🎨 Enter secondary color in ASS format: &HBBGGRR (e.g., &H0000FF00 for green).</i><br>
<i>Used for karaoke effects and special highlighting.</i>""",
    ),
    "VT_HARDSUB_OUTLINE_COLOR": (
        "Color Code",
        "Outline color for hardsub subtitles (text border).",
        """<i>🎨 Enter outline color in ASS format: &HBBGGRR (e.g., &H00000000 for black).</i><br>
<i>Creates a border around the text for better readability.</i>""",
    ),
    "VT_HARDSUB_BACK_COLOR": (
        "Color Code",
        "Background color for hardsub subtitles (text background).",
        """<i>🎨 Enter background color in ASS format: &HBBGGRR (e.g., &H80000000 for semi-transparent black).</i><br>
<i>Creates a background box behind the text.</i>""",
    ),
    "VT_HARDSUB_OUTLINE_WIDTH": (
        "Integer",
        "Outline width for hardsub subtitles (default: 2).",
        """<i>📏 Enter outline width (0-10, default: 2).</i><br>
<i>Higher values create thicker borders around text.</i>""",
    ),
    "VT_HARDSUB_SHADOW_DEPTH": (
        "Integer",
        "Shadow depth for hardsub subtitles (default: 2).",
        """<i>📏 Enter shadow depth (0-10, default: 2).</i><br>
<i>Creates a shadow effect behind the text for better visibility.</i>""",
    ),
    "VT_HARDSUB_ALIGNMENT": (
        "Integer",
        "Text alignment for hardsub subtitles (1-9, default: 2).",
        """<i>📍 Enter alignment number (1-9):</i><br>
<i>1=Left-Top, 2=Center-Top, 3=Right-Top</i><br>
<i>4=Left-Middle, 5=Center-Middle, 6=Right-Middle</i><br>
<i>7=Left-Bottom, 8=Center-Bottom, 9=Right-Bottom</i>""",
    ),
    "VT_HARDSUB_MARGIN_L": (
        "Integer",
        "Left margin for hardsub subtitles (default: 10).",
        """<i>📏 Enter left margin in pixels (default: 10).</i><br>
<i>Controls distance from left edge of video.</i>""",
    ),
    "VT_HARDSUB_MARGIN_R": (
        "Integer",
        "Right margin for hardsub subtitles (default: 10).",
        """<i>📏 Enter right margin in pixels (default: 10).</i><br>
<i>Controls distance from right edge of video.</i>""",
    ),
    "VT_HARDSUB_MARGIN_V": (
        "Integer",
        "Vertical margin for hardsub subtitles - distance from video edge (default: 10).",
        """<i>📏 Enter vertical margin in pixels (default: 10).</i><br>
<i>Controls distance from top/bottom edge of video. Higher values move subtitles further from the edge.</i><br>
<i>For bottom subtitles: larger values move subtitles up. For top subtitles: larger values move subtitles down.</i>""",
    ),
    "VT_HARDSUB_DELAY": (
        "Integer",
        "Delay in milliseconds for hardsub subtitles (default: 0).",
        """<i>⏱️ Enter delay in milliseconds (default: 0).</i><br>
<i>Positive values delay subtitles, negative values start them earlier.</i>""",
    ),
    "VT_HARDSUB_DURATION": (
        "Integer",
        "Duration in milliseconds for hardsub subtitles (default: 0 = auto).",
        """<i>⏱️ Enter duration in milliseconds (default: 0 = auto).</i><br>
<i>0 means use original subtitle timing, other values override duration.</i>""",
    ),
    "VT_HARDSUB_ITALIC": (
        "Boolean",
        "Enable italic text for hardsub subtitles (default: false).",
        """<i>📝 Enter <code>true</code> or <code>false</code> for italic text.</i><br>
<i>Adds italic styling to subtitles.</i>""",
    ),
    "VT_HARDSUB_UNDERLINE": (
        "Boolean",
        "Enable underline for hardsub subtitles (default: false).",
        """<i>📝 Enter <code>true</code> or <code>false</code> for underlined text.</i><br>
<i>Adds underline styling to subtitles.</i>""",
    ),
    "VT_HARDSUB_STRIKEOUT": (
        "Boolean",
        "Enable strikethrough for hardsub subtitles (default: false).",
        """<i>📝 Enter <code>true</code> or <code>false</code> for strikethrough text.</i><br>
<i>Adds strikethrough styling to subtitles.</i>""",
    ),
    "VT_HARDSUB_ENHANCE_CONTRAST": (
        "Boolean",
        "Enable contrast enhancement for hardsub subtitles (default: true).",
        """<i>✨ Enter <code>true</code> or <code>false</code> for contrast enhancement.</i><br>
<i>Improves subtitle visibility by enhancing contrast.</i>""",
    ),
    "VT_HARDSUB_ENHANCE_SATURATION": (
        "Boolean",
        "Enable saturation enhancement for hardsub subtitles (default: false).",
        """<i>✨ Enter <code>true</code> or <code>false</code> for saturation enhancement.</i><br>
<i>Makes colors more vibrant in the video.</i>""",
    ),
    "VT_HARDSUB_ENHANCE_BRIGHTNESS": (
        "Boolean",
        "Enable brightness enhancement for hardsub subtitles (default: false).",
        """<i>✨ Enter <code>true</code> or <code>false</code> for brightness enhancement.</i><br>
<i>Slightly increases video brightness for better subtitle visibility.</i>""",
    ),
    "VT_HARDSUB_PRESERVE_COLORS": (
        "Boolean",
        "Preserve existing colors in subtitle files when applying hardsub (default: true).",
        """<i>🎨 Enter <code>true</code> or <code>false</code> to preserve subtitle colors.</i><br>
<i>When true, existing colors in subtitle files are preserved and hardsub color is only applied to uncolored text.</i><br>
<i>When false, hardsub color overrides all text colors in the subtitle file.</i>""",
    ),
    "INTRO_SUBTITLE_ENABLED": (
        "Boolean",
        "Enable or disable intro subtitle injection (soft mux of styled ASS track at start).",
        """<i>Send true/false to enable or disable intro subtitle soft mux feature.</i><br>""",
    ),
    "INTRO_SUBTITLE_TEXT": (
        "String",
        "The text content for the intro subtitle (will be converted to ASS with optional animation).",
        """<i>Send the text to display in intro subtitle (plain text, no HTML).</i>""",
    ),
    "INTRO_SUBTITLE_STYLE": (
        "typing|fade|static|auto",
        "Animation style: typing (per-character reveal), fade (fade in/out), static (plain), auto (adaptive).",
        """<i>Send style: typing / fade / static / auto.</i><br><i>Format is automatically selected: ASS for customized styles, SRT for plain.</i>""",
    ),
    "INTRO_SUBTITLE_MODE": (
        "existing|new",
        "Whether to modify an existing embedded subtitle or always add a new one (default: new).",
        """<i>Send <b>existing</b> to modify current embedded subtitle when available, or <b>new</b> (default) to always create a new intro subtitle track.</i><br><b>Note:</b> Format is auto-detected based on customization. ASS is used for styled subtitles (typing, fade, custom colors, positioning), SRT for plain ones. In 'existing' mode, files without embedded subtitles are skipped.</i>""",
    ),
    "INTRO_SUBTITLE_FONT_PATH": (
        "Path",
        "Font file path (TTF/OTF) to embed in container (MKV attachments).",
        """<i>Send path to .ttf/.otf font file or upload via this setting.</i>""",
    ),
    "INTRO_SUBTITLE_FONT_SIZE": (
        "Integer",
        "Font size for intro subtitle (default 48).",
        """<i>Send font size integer (e.g., 48).</i>""",
    ),
    "INTRO_SUBTITLE_POSITION": (
        "bottom|center|top",
        "Vertical position of the intro subtitle.",
        """<i>Send position: bottom / center / top.</i>""",
    ),
    "INTRO_SUBTITLE_COLORS": (
        "List",
        "Pipe or space separated colors for cycling (typing mode). Supports color names or hex codes.",
        """<i>Send colors separated by | or space. You can use color names (e.g., red|blue|green) or hex codes (#FF0000|#00FF00|#0000FF).</i>""",
    ),
    "INTRO_SUBTITLE_CHAR_MS": (
        "Integer",
        "Per-character duration in ms for typing style (default 300).",
        """<i>Send integer ms per character (e.g., 300).</i>""",
    ),
    "INTRO_SUBTITLE_DURATION": (
        "Integer",
        "Fixed duration in milliseconds for intro subtitle display (overrides character-based timing).",
        """<i>Send duration in milliseconds (e.g., 3000 for 3 seconds). If set, this overrides character-based timing.</i>""",
    ),
    "VT_WATERMARK_SIZE": (
        "Integer (percent)",
        "Default size percentage for watermark (image scale or text font size).",
        """<i>Enter default watermark size (e.g., 20). This is used when not specified in -vt.</i>""",
    ),
    # Enhanced VT_WATERMARK settings to match VIDEO_WATERMARK functionality
    "VT_WATERMARK_ENABLED": (
        "Boolean",
        "Enable or disable video watermark for video tools processing.",
        """<i>Send true/false to enable or disable video watermark feature in video tools.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "VT_WATERMARK_POSITION": (
        "String",
        "Position of watermark on video (top-left, top-right, bottom-left, bottom-right, center).",
        """<i>Send position for watermark placement:</i><br>
<b>Options:</b> top-left, top-right, bottom-left, bottom-right, center<br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "VT_WATERMARK_OPACITY": (
        "Float",
        "Opacity/transparency of the watermark (0.0 to 1.0).",
        """<i>Send opacity value (e.g., 0.5, 0.8). Lower values = more transparent.</i><br>
<i>Range: 0.0 (fully transparent) to 1.0 (fully opaque)</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "VT_WATERMARK_TYPE": (
        "String",
        "Type of watermark: text or image.",
        """<i>Send 'text' for text-based watermark or 'image' for image-based watermark.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "VT_WATERMARK_FONT_SIZE": (
        "Integer",
        "Font size for text watermark.",
        """<i>Send font size in pixels (e.g., 24, 32, 48).</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "VT_WATERMARK_FONT_COLOR": (
        "String",
        "Font color for text watermark (hex color or color name).",
        """<i>Send color for text watermark (e.g., white, #FFFFFF, red, #FF0000).</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "VT_WATERMARK_TEXT_BACKGROUND": (
        "String",
        "Background color/style for text watermark.",
        """<i>Send background style for text watermark (e.g., none, black, #000000@0.5).</i><br>
<i>Use @opacity for transparency (e.g., black@0.5)</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "VT_WATERMARK_DURATION_TYPE": (
        "String",
        "Duration type for watermark display (full, seconds, percentage).",
        """<i>Send duration type:</i><br>
<b>full</b> - Show throughout entire video<br>
<b>seconds</b> - Show for specific number of seconds<br>
<b>percentage</b> - Show for percentage of video duration<br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "VT_WATERMARK_DURATION_SECONDS": (
        "Integer",
        "Duration in seconds for watermark display (when duration_type is 'seconds').",
        """<i>Send number of seconds to display watermark (e.g., 30, 60, 120).</i><br>
<i>Only applies when duration type is set to 'seconds'</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    # Enhanced video tools settings from reference
    "VIDEO_ENCODE_ENABLED": (
        "Boolean",
        "Enable or disable video encoding for your uploads. This will re-encode videos with specified preset.",
        """<i>🎬 Send true/false to enable or disable video encoding.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "VIDEO_ENCODE_PRESET": (
        "String",
        "Set the encoding preset for videos. Available options: ultrafast, superfast, veryfast, faster, fast, medium, slow, slower, veryslow.",
        """<i>⚡ Send your preferred encoding preset (e.g., medium). The slower the preset, the better the quality and smaller the file size, but it will take longer to encode.</i><br>
<b>Available:</b> ultrafast, superfast, veryfast, faster, fast, medium, slow, slower, veryslow<br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "VIDEO_ENCODE_QUALITY": (
        "String",
        "Set the target video quality/resolution for encoding. Select from predefined quality settings: 1080p, 720p, 480p, 360p, or Original.",
        """<i>📺 Send your preferred quality setting (e.g., 720p). Use 'Original' to keep the original resolution.</i><br>
<b>Available:</b> 1080p, 720p, 480p, 360p, Original<br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "VIDEO_ENCODE_CRF": (
        "Integer",
        "Set the Constant Rate Factor (CRF) for encoding. Lower values mean better quality but larger files (18-28 recommended).",
        """<i>Send CRF value (e.g., 23). Range: 0-51. Lower = better quality, larger files.</i>""",
    ),
    "VIDEO_ENCODE_AUDIO_BITRATE": (
        "String",
        "Set the audio bitrate for encoded videos (e.g., 128k, 192k, 256k).",
        """<i>Send audio bitrate (e.g., 128k). Higher values mean better audio quality.</i>""",
    ),
    "VIDEO_ENCODE_MULTI_RESOLUTION": (
        "Boolean",
        "Enable multi-resolution encoding to create multiple quality versions of videos.",
        """<i>Send true/false to enable or disable multi-resolution encoding.</i>""",
    ),
    "VIDEO_ENCODE_RESOLUTION_LIST": (
        "String",
        "Comma-separated list of resolutions for multi-resolution encoding (e.g., 1080p,720p,480p).",
        """<i>Send comma-separated resolutions (e.g., 1080p,720p,480p). Leave empty for all available resolutions.</i>""",
    ),
    "VIDEO_ENCODE_MULTI_ZIP": (
        "Boolean",
        "Package multiple encoded resolutions into a single ZIP file.",
        """<i>Send true/false to enable or disable multi-resolution ZIP packaging.</i>""",
    ),
    "VIDEO_WATERMARK_ENABLED": (
        "Boolean",
        "Enable or disable video watermarking for uploads.",
        """<i>🖋️ Send true/false to enable or disable video watermarking.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "VIDEO_WATERMARK_TEXT": (
        "String",
        "Text to use for video watermarking.",
        """<i>Send the text you want to use as watermark.</i>""",
    ),
    "VIDEO_WATERMARK_POSITION": (
        "String",
        "Position of the watermark on video (topleft, topright, bottomleft, bottomright, center).",
        """<i>Send watermark position (e.g., bottomright).</i>""",
    ),
    "VIDEO_WATERMARK_OPACITY": (
        "Float",
        "Opacity of the video watermark (0.1 to 1.0).",
        """<i>Send opacity value (e.g., 0.7). 1.0 = fully opaque, 0.1 = very transparent.</i>""",
    ),
    "VIDEO_WATERMARK_TYPE": (
        "String",
        "Type of watermark: text or image.",
        """<i>Send 'text' or 'image' to specify watermark type.</i>""",
    ),
    "VIDEO_WATERMARK_IMAGE_PATH": (
        "File",
        "Image file to use as video watermark.",
        """<i>Send an image file to use as watermark.</i>""",
    ),
    "VIDEO_WATERMARK_FONT_SIZE": (
        "Integer",
        "Font size for text watermarks.",
        """<i>Send font size (e.g., 24).</i>""",
    ),
    "VIDEO_WATERMARK_FONT_COLOR": (
        "String",
        "Font color for text watermarks (color name or hex code).",
        """<i>Send color name (e.g., white) or hex code (e.g., #FFFFFF).</i>""",
    ),
    "VIDEO_WATERMARK_TEXT_BACKGROUND": (
        "Boolean",
        "Add background to text watermarks for better visibility.",
        """<i>Send true/false to enable or disable text background.</i>""",
    ),
    "VIDEO_WATERMARK_DURATION_TYPE": (
        "String",
        "Duration type for watermark display: full, seconds, or percentage.",
        """<i>Send 'full', 'seconds', or 'percentage' to specify duration type.</i>""",
    ),
    "VIDEO_WATERMARK_DURATION_SECONDS": (
        "Integer",
        "Duration in seconds for watermark display (when duration_type is 'seconds').",
        """<i>Send duration in seconds (e.g., 30).</i>""",
    ),
    "VIDEO_WATERMARK_FONT_PATH": (
        "File",
        "Custom font file for text watermarks.",
        """<i>Send a TTF or OTF font file to use for text watermarks.</i>""",
    ),
    "INTRO_SUBTITLE_TEXT": (
        "String",
        "Text to display in intro subtitles.",
        """<i>Send the text for intro subtitles.</i>""",
    ),
    "INTRO_SUBTITLE_STYLE": (
        "String",
        "Style for intro subtitles: typing, fade, or instant.",
        """<i>Send 'typing', 'fade', or 'instant' for subtitle style.</i>""",
    ),
    "CUSTOM_FILENAME": (
        "String",
        "Template for custom filename generation with variables like {title}, {quality}, etc.",
        """<i>Send filename template (e.g., {title} - {quality}). Available variables: {title}, {quality}, {codec}, {year}, etc.</i>""",
    ),
    "VIDEO_TRIM_ENABLED": (
        "Boolean",
        "Enable automatic video trimming based on user settings.",
        """<i>Send true/false to enable or disable video trimming.</i>""",
    ),
    # Missing video processing settings
    "VIDEO_MERGE_ENABLED": (
        "Boolean",
        "Enable or disable video merging functionality for combining multiple video files.",
        """<i>🔗 Send true/false to enable or disable video merging feature.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "VIDEO_AUDIO_MERGE_ENABLED": (
        "Boolean",
        "Enable or disable video+audio merging functionality for combining video with separate audio tracks.",
        """<i>🎵 Send true/false to enable or disable video+audio merging feature.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "VIDEO_SUBTITLE_MERGE_ENABLED": (
        "Boolean",
        "Enable or disable video+subtitle merging functionality for adding subtitles to videos.",
        """<i>📝 Send true/false to enable or disable video+subtitle merging feature.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "VIDEO_HARDSUB_ENABLED": (
        "Boolean",
        "Enable or disable video hardsub functionality for burning subtitles permanently into videos.",
        """<i>🔥 Send true/false to enable or disable video hardsub feature.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "VIDEO_HARDSUB_FONT_NAME": (
        "String",
        "Font name for hardsub subtitles (e.g., Arial, Helvetica, DejaVu Sans).",
        """<i>🔤 Send the font name for hardsub subtitles (e.g., Arial).</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "VIDEO_HARDSUB_FONT_SIZE": (
        "Integer",
        "Font size for hardsub subtitles (default: 22).",
        """<i>📏 Send font size for hardsub subtitles (e.g., 22).</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "VIDEO_HARDSUB_FONT_COLOUR": (
        "String",
        "Primary color for hardsub subtitles in ASS color format (e.g., FFFFFF for white).",
        """<i>🎨 Send color in ASS format (e.g., FFFFFF for white, 00FF00 for green).</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "VIDEO_HARDSUB_STYLE": (
        "String",
        "Set the subtitle style for hardsub. Options: default, bold, outline, shadow, glow. Default style uses the original subtitle formatting.",
        """<i>💪 Send subtitle style: <code>default</code>, <code>bold</code>, <code>outline</code>, <code>shadow</code>, or <code>glow</code>.</i><br>
<i>• <b>default</b>: Original subtitle formatting</i><br>
<i>• <b>bold</b>: Bold text</i><br>
<i>• <b>outline</b>: Bold with black outline</i><br>
<i>• <b>shadow</b>: Bold with shadow effect</i><br>
<i>• <b>glow</b>: Bold with white glow effect</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "VIDEO_STREAM_EXTRACT_ENABLED": (
        "Boolean",
        "Enable or disable stream extraction functionality for extracting audio/subtitle streams from videos.",
        """<i>📤 Send true/false to enable or disable stream extraction feature.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "INTRO_SUBTITLE_ENABLED": (
        "Boolean",
        "Enable or disable intro subtitle generation for videos.",
        """<i>🎯 Send true/false to enable or disable intro subtitle feature.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "INTRO_SUBTITLE_MODE": (
        "String",
        "Mode for intro subtitle generation: new, append, or replace.",
        """<i>⚙️ Send 'new', 'append', or 'replace' to specify subtitle mode.</i><br>
<b>Available:</b> new, append, replace<br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "INTRO_SUBTITLE_FONT_PATH": (
        "File",
        "Custom font file for intro subtitles.",
        """<i>🔤 Send a TTF or OTF font file to use for intro subtitles.</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "INTRO_SUBTITLE_FONT_SIZE": (
        "Integer",
        "Font size for intro subtitles.",
        """<i>📏 Send font size (e.g., 24).</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "INTRO_SUBTITLE_POSITION": (
        "String",
        "Position of intro subtitles: top, center, or bottom.",
        """<i>📍 Send 'top', 'center', or 'bottom' for subtitle position.</i><br>
<b>Available:</b> top, center, bottom<br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "INTRO_SUBTITLE_COLORS": (
        "String",
        "Color scheme for intro subtitles (pipe-separated for multiple colors).",
        """<i>🎨 Send colors separated by | (e.g., red|blue|green) or single color name/hex code.</i><br>
<b>Examples:</b> red|blue|green, white, #FFFFFF<br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "INTRO_SUBTITLE_CHAR_MS": (
        "Integer",
        "Character display duration in milliseconds for typing animation.",
        """<i>⏱️ Send duration in milliseconds (e.g., 300).</i><br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    "INTRO_SUBTITLE_DURATION": (
        "Integer",
        "Fixed total duration in milliseconds for intro subtitle display.",
        """<i>⏰ Send total duration in milliseconds (e.g., 3000 for 3 seconds).</i><br>
<b>Note:</b> This overrides character-based timing when set.<br>
<i>Please provide the required input within 60 seconds.</i>""",
    ),
    # Sample video settings
    "SAMPLE_VIDEO_ENABLED": (
        "Boolean",
        "Enable or disable automatic sample video generation for leeched videos.",
        "<i>Send true/false to enable or disable sample video generation. When enabled, the bot will create sample clip(s) from each video.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "SAMPLE_VIDEO_COUNT": (
        "Integer (1-10)",
        "Number of random sample clips to generate per video.",
        "<i>Send a number between 1 and 10 for how many sample clips to generate.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "SAMPLE_VIDEO_DURATION": (
        "Integer (seconds)",
        "Duration in seconds of each random sample clip.",
        "<i>Send duration in seconds for each sample clip (recommended: 30-120).</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "SAMPLE_VIDEO_SEPARATE": (
        "Boolean",
        "Generate separate sample clip files instead of merging into one.",
        "<i>Send true/false to enable separate clips instead of merged.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    # Video encoding settings
    "VIDEO_ENCODE_ENABLED": (
        "Boolean",
        "Enable or disable video encoding for your uploads.",
        "<i>Send true/false to enable or disable video encoding.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_ENCODE_PRESET": (
        "String",
        "Set encoding preset: ultrafast, superfast, veryfast, faster, fast, medium, slow, slower, veryslow.",
        "<i>Send preset (e.g., medium). Slower presets = better quality but take longer.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_ENCODE_QUALITY": (
        "String",
        "Set target video quality/resolution: 1080p, 720p, 480p, 360p, or custom.",
        "<i>Send quality (e.g., 1080p, 720p, 480p, 360p, custom).</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_ENCODE_CRF": (
        "Integer",
        "Constant Rate Factor for encoding. Range: 0-51, lower = better quality but larger size.",
        "<i>Send CRF value (e.g., 23). Lower = better quality. Recommended: 18-28.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_ENCODE_AUDIO_BITRATE": (
        "String",
        "Audio bitrate for encoding: 128k, 192k, 256k, 320k.",
        "<i>Send audio bitrate (e.g., 128k, 192k, 256k, 320k).</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_ENCODE_CODEC": (
        "String",
        "Video codec for encoding: x264 (H.264) or x265 (H.265/HEVC).",
        "<i>Send 'x264' for faster encoding or 'x265' for better compression.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    # Video conversion settings
    "VIDEO_CONVERT_ENABLED": (
        "Boolean",
        "Enable or disable video format conversion.",
        "<i>Send true/false to enable or disable video format conversion.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_CONVERT_FORMAT": (
        "String",
        "Target format for conversion: mp4, mkv, avi, mov, webm, flv, m4v.",
        "<i>Send target format (e.g., mp4, mkv, webm).</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_CONVERT_CODEC": (
        "String",
        "Codec for conversion: copy, auto, x264, x265.",
        "<i>Send 'copy' to keep original codec, 'auto' for smart selection, or specific codec.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_CONVERT_QUALITY": (
        "String",
        "Quality for conversion: original, high, medium, low.",
        "<i>Send quality level (e.g., high, medium, low). 'original' maintains source quality.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    # Video watermark settings
    "VIDEO_WATERMARK_ENABLED": (
        "Boolean",
        "Enable or disable video watermarking.",
        "<i>Send true/false to enable or disable video watermarking.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_WATERMARK_TEXT": (
        "String",
        "Text to use as watermark on videos.",
        "<i>Send watermark text (e.g., 'My Channel', '@username').</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_WATERMARK_POSITION": (
        "String",
        "Position: top-left, top-right, top-center, bottom-left, bottom-right, bottom-center, center.",
        "<i>Send position (e.g., bottom-right, top-left, center).</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_WATERMARK_OPACITY": (
        "Float",
        "Watermark opacity/transparency. Range: 0.1-1.0.",
        "<i>Send opacity (e.g., 0.5, 0.8). Lower = more transparent.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_WATERMARK_TYPE": (
        "String",
        "Watermark type: text or image.",
        "<i>Send 'text' for text watermark or 'image' for image watermark.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_WATERMARK_IMAGE_PATH": (
        "Photo or Doc",
        "Image file to use as watermark. PNG with transparency recommended.",
        "<i>Send image file for watermark. PNG format recommended.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    # Video merge and manipulation settings
    "VIDEO_MERGE_ENABLED": (
        "Boolean",
        "Enable video merge feature for combining multiple videos.",
        "<i>Send true/false to enable or disable video merge.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_AUDIO_MERGE_ENABLED": (
        "Boolean",
        "Enable video+audio merge feature.",
        "<i>Send true/false to enable or disable video+audio merge.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_SUBTITLE_MERGE_ENABLED": (
        "Boolean",
        "Enable video+subtitle merge feature.",
        "<i>Send true/false to enable or disable video+subtitle merge.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_STREAM_EXTRACT_ENABLED": (
        "Boolean",
        "Enable stream extract feature for extracting audio/subtitles.",
        "<i>Send true/false to enable or disable stream extract.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_TRIM_ENABLED": (
        "Boolean",
        "Enable video trim feature to cut portions of video.",
        "<i>Send true/false to enable or disable video trim.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "CUSTOM_FILENAME": (
        "String",
        "Custom filename template. Use {name} for original name, {ext} for extension.",
        "<i>Send filename template (e.g., 'MyVideo_{name}', '{name}_HD').</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
}


@TgClient.bot.on_message(command(BotCommands.UthumbCommand) & CustomFilters.authorized)
async def set_user_thumbnail_cmd(client, message):
    user_id = message.from_user.id
    if not message.reply_to_message:
        await send_message(
            message, "Please reply to an image to set it as your thumbnail."
        )
        return

    replied_message = message.reply_to_message
    if not replied_message.photo:
        await send_message(message, "Replied message is not a photo.")
        return

    processing_msg = await send_message(message, "🖼️ Processing your thumbnail...")
    thumbnail_path = await create_reply_thumbnail(replied_message, user_id)

    if thumbnail_path:
        update_user_ldata(user_id, "THUMBNAIL", thumbnail_path)
        # Save binary content to both THUMBNAIL and THUMBNAIL_CONTENT for consistency
        await database.update_user_doc(user_id, "THUMBNAIL", thumbnail_path)
        await database.update_user_doc(user_id, "THUMBNAIL_CONTENT", thumbnail_path)
        await edit_message(
            processing_msg, "✅ Custom thumbnail has been set successfully!"
        )
    else:
        await edit_message(processing_msg, "❌ Failed to set thumbnail.")


async def get_user_settings(from_user, stype="main"):
    user_id = from_user.id
    user_name = from_user.mention(style="html")
    buttons = ButtonMaker()
    user_dict = user_data.get(user_id, {})
    rclone_conf = f"rclone/{user_id}.conf"
    token_pickle = f"tokens/{user_id}.pickle"

    if stype == "main":
        # Determine other settings status for buttons - use cleaner status indicators
        name_swap_status = "✅" if user_dict.get("NAME_SWAP") else "❌"
        remname_status = "✅" if user_dict.get("REMNAME") else "❌"
        upload_paths_status = "✅" if user_dict.get("UPLOAD_PATHS") else "❌"
        excluded_ext_status = "✅" if user_dict.get("EXCLUDED_EXTENSIONS") else "❌"

        buttons.data_button(
            "Default Upload Service",
            f"userset {user_id} upload_service_menu",
            position="header",
        )

        buttons.data_button("Gdrive Tools", f"userset {user_id} gdrive")
        buttons.data_button("Rclone Tools", f"userset {user_id} rclone")
        buttons.data_button("GoFile Tools", f"userset {user_id} gofile")
        buttons.data_button("Leech Tools", f"userset {user_id} leech")
        buttons.data_button("Common Tools", f"userset {user_id} common_tools")
        buttons.data_button("Dump Settings", f"userset {user_id} dumps")
        buttons.data_button("YT-DLP Tools", f"userset {user_id} yttools")
        buttons.data_button("Metadata", f"userset {user_id} ffset")
        buttons.data_button(
            f"Upload Paths {upload_paths_status}",
            f"userset {user_id} menu UPLOAD_PATHS",
        )
        buttons.data_button(
            f"Excluded Ext {excluded_ext_status}",
            f"userset {user_id} menu EXCLUDED_EXTENSIONS",
        )
        buttons.data_button("Use 'MY' token/config", f"userset {user_id} general")
        buttons.data_button("Advanced Settings", f"userset {user_id} advanced")
        buttons.data_button("Auto Leech/Mirror", f"userset {user_id} auto_process")
        buttons.data_button("Attachment", f"userset {user_id} attachments_menu")
        buttons.data_button("Video Tools", f"userset {user_id} vtset")
        buttons.data_button("Zip Mode", f"userset {user_id} zipmode")

        # FIX: "Reset All" button on its own full-width row above the "Close" button.
        buttons.data_button(
            "Reset All ♻️", f"userset {user_id} reset_all_prompt", position="l_body"
        )
        buttons.data_button("✘", f"userset {user_id} close", position="footer")

        text = "<b>⌬ USER SETTINGS</b>\n\n"

        text += f"<b>Settings For</b>: <b>{user_name}</b>\n"
        settings_list = []

        is_as_doc = user_dict.get("AS_DOCUMENT", Config.AS_DOCUMENT)
        ltype = "DOCUMENT" if is_as_doc else "MEDIA"
        settings_list.append(f"Leech Type: <b>{ltype}</b>")

        leech_split_size = get_readable_file_size(
            user_dict.get("LEECH_SPLIT_SIZE", Config.LEECH_SPLIT_SIZE)
        )
        settings_list.append(f"Leech Split Size: <b>{leech_split_size}</b>")

        equal_splits = (
            "Enabled"
            if user_dict.get("EQUAL_SPLITS", Config.EQUAL_SPLITS)
            else "Disabled"
        )
        settings_list.append(f"Leech Equal Splits: <b>{equal_splits}</b>")

        upload_client = (
            "user session"
            if user_dict.get("USER_TRANSMISSION", Config.USER_TRANSMISSION)
            else "bot session"
        )
        settings_list.append(f"Leech Upload Client: <b>{upload_client}</b>")

        mixed_upload = (
            "Enabled"
            if user_dict.get("HYBRID_LEECH", Config.HYBRID_LEECH)
            else "Disabled"
        )
        settings_list.append(f"Leech Mixed Upload: <b>{mixed_upload}</b>")

        leech_dump = (
            "✅ Set"
            if (user_dict.get("LEECH_DUMP_CHAT") or Config.LEECH_DUMP_CHAT)
            else "Not Set"
        )
        settings_list.append(f"Leech User Dump: <b>{leech_dump}</b>")

        mirror_dump = (
            "✅ Set"
            if (user_dict.get("MIRROR_DUMP_CHAT") or Config.MIRROR_DUMP_CHAT)
            else "Not Set"
        )
        settings_list.append(f"Mirror Dump Chat: <b>{mirror_dump}</b>")

        leech_prefix = (
            "✅ Set"
            if (user_dict.get("LEECH_PREFIX") or Config.LEECH_PREFIX)
            else "Not Set"
        )
        settings_list.append(f"Leech Prefix: <b>{leech_prefix}</b>")

        leech_suffix = (
            "✅ Set"
            if (user_dict.get("LEECH_SUFFIX") or Config.LEECH_SUFFIX)
            else "Not Set"
        )
        settings_list.append(f"Leech Suffix: <b>{leech_suffix}</b>")

        leech_caption_status = "✅ Set" if user_dict.get("LEECH_CAPTION") else "Not Set"
        settings_list.append(f"Leech Custom Caption: <b>{leech_caption_status}</b>")

        user_session = "✅ Set" if user_dict.get("USER_STRING_SESSION") else "Not Set"
        settings_list.append(f"User Session: <b>{user_session}</b>")

        mediainfo = (
            "Enabled" if user_dict.get("SHOW_MEDIAINFO_BUTTON", True) else "Disabled"
        )
        settings_list.append(f"MediaInfo: <b>{mediainfo}</b>")

        filename_source = user_dict.get("FILENAME_SOURCE", Config.FILENAME_SOURCE)
        settings_list.append(f"Get Name From: <b>{filename_source.title()}</b>")

        leech_caption_font = user_dict.get(
            "LEECH_CAPTION_FONT", Config.LEECH_CAPTION_FONT
        )
        settings_list.append(f"Caption Font: <b>{leech_caption_font.title()}</b>")

        thumb_path = f"thumbnails/{user_id}.jpg"
        thumb_status = "✅ Set" if await aiopath.exists(thumb_path) else "Not Set"
        settings_list.append(f"Thumbnail: <b>{thumb_status}</b>")

        thumb_layout = user_dict.get("THUMBNAIL_LAYOUT", "1x1")
        settings_list.append(f"Thumbnail Layout: <b>{thumb_layout}</b>")

        metadata = "✅ Set" if user_dict.get("METADATA_SETTINGS") else "Not Set"
        settings_list.append(f"Metadata: <b>{metadata}</b>")

        auto_rename = "Enabled" if user_dict.get("AUTO_RENAME") else "Disabled"
        settings_list.append(f"Auto Rename: <b>{auto_rename}</b>")

        gdrive_token = "Exists" if await aiopath.exists(token_pickle) else "Not Exists"
        settings_list.append(f"Gdrive Token: <b>{gdrive_token}</b>")

        gdrive_id = (
            "✅ Set" if (user_dict.get("GDRIVE_ID") or Config.GDRIVE_ID) else "Not Set"
        )
        settings_list.append(f"Gdrive ID: <b>{gdrive_id}</b>")

        index_link = (
            "✅ Set" if (user_dict.get("INDEX_URL") or Config.INDEX_URL) else "Not Set"
        )
        settings_list.append(f"Index Link: <b>{index_link}</b>")

        stop_duplicate = (
            "Enabled"
            if user_dict.get("STOP_DUPLICATE", Config.STOP_DUPLICATE)
            else "Disabled"
        )
        settings_list.append(f"Stop Duplicate: <b>{stop_duplicate}</b>")
        settings_list.append("Default Package: <b>Gdrive API</b>")

        upload_using = (
            "MY token/config" if user_dict.get("USER_TOKENS") else "OWNER token/config"
        )
        settings_list.append(f"Upload Using: <b>{upload_using}</b>")

        upload_paths = "✅ Set" if user_dict.get("UPLOAD_PATHS") else "Not Set"
        settings_list.append(f"Upload Paths: <b>{upload_paths}</b>")

        name_sub_status = "✅ Set" if user_dict.get("NAME_SWAP") else "Not Set"
        settings_list.append(f"Name Substitute: <b>{name_sub_status}</b>")

        remname_status = "✅ Set" if user_dict.get("REMNAME") else "Not Set"
        settings_list.append(f"Remname: <b>{remname_status}</b>")

        rclone_config = "✅ Set" if await aiopath.exists(rclone_conf) else "Not Set"
        settings_list.append(f"Rclone Config: <b>{rclone_config}</b>")

        rclone_path = (
            "✅ Set"
            if (user_dict.get("RCLONE_PATH") or Config.RCLONE_PATH)
            else "Not Set"
        )
        settings_list.append(f"Rclone Path: <b>{rclone_path}</b>")

        gofile_token = "Set" if user_dict.get("GOFILE_TOKEN") else "Not Set"
        settings_list.append(f"GoFile Token: <b>{gofile_token}</b>")

        gofile_folder = "✅ Set" if user_dict.get("GOFILE_FOLDER_ID") else "Not Set"
        settings_list.append(f"GoFile Folder: <b>{gofile_folder}</b>")

        yt_cookie = (
            "Exists"
            if await aiopath.exists(f"cookies/{user_id}/cookies.txt")
            else "Not Exists"
        )
        settings_list.append(f"YT-DLP Cookies: <b>{yt_cookie}</b>")

        yt_dlp_opts = "Custom" if user_dict.get("YT_DLP_OPTIONS") else "Default"
        settings_list.append(f"YT-DLP Options: <b>{yt_dlp_opts}</b>")

        excluded_ext = (
            "✅ Set"
            if user_dict.get("EXCLUDED_EXTENSIONS", excluded_extensions)
            != excluded_extensions
            else "Not Set"
        )
        settings_list.append(f"Excluded Extensions: <b>{excluded_ext}</b>")

        default_upload_service = user_dict.get(
            "DEFAULT_UPLOAD_SERVICE", Config.DEFAULT_UPLOAD_SERVICE
        )
        settings_list.append(f"Default Upload: <b>{default_upload_service.upper()}</b>")

        zip_mode = user_dict.get("ZIP_MODE", "folders")
        settings_list.append(f"Zip Mode: <b>{zip_mode.title()}</b>")

        if settings_list:
            text += f"╭ {settings_list[0]}\n"
            for item in settings_list[1:-1]:
                text += f"├ {item}\n"
            if len(settings_list) > 1:
                text += f"╰ {settings_list[-1]}\n"

        btns = buttons.build_menu(2)
        return text, btns

    elif stype == "thumbnail":
        thumb_path = f"thumbnails/{user_id}.jpg"
        thumbmsg = "Exists" if await aiopath.exists(thumb_path) else "Not Exists"
        auto_thumb_status = user_dict.get("AUTO_THUMBNAIL", False)

        buttons.data_button("Set Thumbnail", f"userset {user_id} file THUMBNAIL")
        buttons.data_button("Remove Thumbnail", f"userset {user_id} rm_thumb")
        buttons.data_button(
            f"Auto Thumbnail: {'✅ ON' if auto_thumb_status else '❌ OFF'}",
            f"userset {user_id} tog_thumb AUTO_THUMBNAIL",
        )

        current_tmdb_type = user_dict.get("TMDB_THUMBNAIL_TYPE", "poster")
        next_tmdb_type = "backdrop" if current_tmdb_type == "poster" else "poster"
        buttons.data_button(
            f"TMDB Type: {current_tmdb_type.title()} (Tap to switch to {next_tmdb_type.title()})",
            f"userset {user_id} set_tmdb_type {next_tmdb_type}",
        )

        buttons.data_button(
            "Thumbnail Layout", f"userset {user_id} menu THUMBNAIL_LAYOUT"
        )

        buttons.data_button("❮❮", f"userset {user_id} back main", position="footer")
        buttons.data_button("✘", f"userset {user_id} close", position="footer")

        text = f"<u>Thumbnail Settings for {user_name}</u>\n\n"
        thumb_settings = [
            f"Custom Thumbnail: <b>{thumbmsg}</b>",
            f"Auto Thumbnail (TMDB/IMDB): <b>{'Enabled' if auto_thumb_status else 'Disabled'}</b>",
            f"TMDB Thumbnail Type: <b>{current_tmdb_type.title()}</b> (Used if Auto Thumbnail is ON)",
            f"Thumbnail Layout: <b>{user_dict.get('THUMBNAIL_LAYOUT', '1x1')}</b>",
        ]

        if thumb_settings:
            text += f"╭ {thumb_settings[0]}\n"
            for item in thumb_settings[1:-1]:
                text += f"├ {item}\n"
            if len(thumb_settings) > 1:
                text += f"╰ {thumb_settings[-1]}\n"

        btns = buttons.build_menu(2)
        return text, btns

    elif stype == "leech":
        buttons = ButtonMaker()

        # Helper to add a tick when a setting is set
        def _tick(label: str, is_set: bool) -> str:
            return ("✅ " + label) if is_set else label

        buttons.data_button("Split Size", f"userset {user_id} menu LEECH_SPLIT_SIZE")
        split_size = user_dict.get("LEECH_SPLIT_SIZE", Config.LEECH_SPLIT_SIZE)
        # Leech destination button removed - now handled in dumps section
        # buttons.data_button("Destination", f"userset {user_id} menu leech_dest")
        # leech_dest = user_dict.get("leech_dest", Config.LEECH_DUMP_CHAT or "None")
        buttons.data_button(
            _tick("Custom Caption", bool(user_dict.get("LEECH_CAPTION"))),
            f"userset {user_id} menu LEECH_CAPTION",
        )
        lcap = user_dict.get("LEECH_CAPTION", Config.LEECH_CAPTION or "Not Set")
        lprefix = user_dict.get("LEECH_PREFIX", Config.LEECH_PREFIX or "Not Set")
        lsuffix = user_dict.get("LEECH_SUFFIX", Config.LEECH_SUFFIX or "Not Set")

        current_filename_source = user_dict.get(
            "FILENAME_SOURCE", Config.FILENAME_SOURCE
        )
        if current_filename_source == "filename":
            buttons.data_button(
                _tick("Name from: Caption", current_filename_source == "caption"),
                f"userset {user_id} set_fs caption",
            )
        else:
            buttons.data_button(
                _tick("Name from: Filename", current_filename_source == "filename"),
                f"userset {user_id} set_fs filename",
            )

        buttons.data_button(
            _tick(
                "Caption Font",
                bool(user_dict.get("LEECH_CAPTION_FONT", Config.LEECH_CAPTION_FONT)),
            ),
            f"userset {user_id} caption_font_menu",
        )

        is_as_doc = user_dict.get("AS_DOCUMENT", Config.AS_DOCUMENT)
        ltype = "DOCUMENT" if is_as_doc else "MEDIA"
        if is_as_doc:
            buttons.data_button("Send as Media", f"userset {user_id} tog AS_DOCUMENT f")
        else:
            buttons.data_button(
                "Send as Document", f"userset {user_id} tog AS_DOCUMENT t"
            )

        equal_splits = "Enabled"
        if user_dict.get("EQUAL_SPLITS", Config.EQUAL_SPLITS):
            buttons.data_button(
                "Disable Equal Splits", f"userset {user_id} tog EQUAL_SPLITS f"
            )
        else:
            equal_splits = "Disabled"
            buttons.data_button(
                "Enable Equal Splits", f"userset {user_id} tog EQUAL_SPLITS t"
            )

        media_group = "Enabled"
        if user_dict.get("MEDIA_GROUP", Config.MEDIA_GROUP):
            buttons.data_button(
                "Disable Media Group", f"userset {user_id} tog MEDIA_GROUP f"
            )
        else:
            media_group = "Disabled"
            buttons.data_button(
                "Enable Media Group", f"userset {user_id} tog MEDIA_GROUP t"
            )

        leech_completion = "Enabled"
        if user_dict.get("leech_completion_message", True):
            buttons.data_button(
                "Disable Completion Msg",
                f"userset {user_id} tog leech_completion_message f",
            )
        else:
            leech_completion = "Disabled"
            buttons.data_button(
                "Enable Completion Msg",
                f"userset {user_id} tog leech_completion_message t",
            )

        mediainfo_msg = "Shown"
        if user_dict.get("SHOW_MEDIAINFO_BUTTON", True):
            buttons.data_button(
                "Disable Media Info", f"userset {user_id} tog SHOW_MEDIAINFO_BUTTON f"
            )
        else:
            mediainfo_msg = "Hidden"
            buttons.data_button(
                "Enable Media Info", f"userset {user_id} tog SHOW_MEDIAINFO_BUTTON t"
            )

        stream_link_msg = "Shown"
        if user_dict.get("ENABLE_STREAM_LINK", Config.ENABLE_STREAM_LINK):
            buttons.data_button(
                "Disable Stream Link", f"userset {user_id} tog ENABLE_STREAM_LINK f"
            )
        else:
            stream_link_msg = "Hidden"
            buttons.data_button(
                "Enable Stream Link", f"userset {user_id} tog ENABLE_STREAM_LINK t"
            )

        # New: Sequential Ordering Toggle
        sequential = user_dict.get("SEQUENTIAL_ORDER", False)
        if sequential:
            buttons.data_button(
                "Disable Sequential", f"userset {user_id} tog SEQUENTIAL_ORDER f"
            )
        else:
            buttons.data_button(
                "Enable Sequential", f"userset {user_id} tog SEQUENTIAL_ORDER t"
            )

        # Move Thumbnail management under Leech settings with a tickmark
        try:
            thumb_exists = await aiopath.exists(f"thumbnails/{user_id}.jpg")
        except Exception:
            thumb_exists = False
        buttons.data_button(
            _tick("Thumbnail", thumb_exists), f"userset {user_id} menu THUMBNAIL"
        )

        text = f"<u>Leech Settings for {user_name}</u>\n\n"
        leech_settings = [
            f"Leech Type: <b>{ltype}</b>",
            f"Split Size: <b>{get_readable_file_size(split_size)}</b>",
            f"Equal Splits: <b>{equal_splits}</b>",
            f"Media Group: <b>{media_group}</b>",
            f"Sequential: <b>{'Enabled' if sequential else 'Disabled'}</b>",
            # f"Prefix: <code>{escape(lprefix)}</code>",
            #    f"Suffix: <code>{escape(lsuffix)}</code>",
            f"Custom Caption: <code>{escape(lcap)}</code>",
            f"Filename Source: <b>{user_dict.get('FILENAME_SOURCE', Config.FILENAME_SOURCE).title()}</b>",
            f"Caption Font: <b>{user_dict.get('LEECH_CAPTION_FONT', Config.LEECH_CAPTION_FONT).title()}</b>",
            # Destination removed from leech tools - now in dumps section
            # f"Destination: <code>{leech_dest}</code>",
            f"Completion Message: <b>{leech_completion}</b>",
            f"Screenshot Settings: <b>{'Enabled' if user_dict.get('SS_GRID_ENABLED') else 'Disabled'}</b>",
            f"Auto Rename: <b>{'Enabled' if user_dict.get('AUTO_RENAME') else 'Disabled'}</b>",
            f"Media Info Button: <b>{mediainfo_msg}</b>",
            f"Stream Link Button: <b>{stream_link_msg}</b>",
            f"Thumbnail: <b>{'✅ Set' if thumb_exists else '❌ Not Set'}</b>",
        ]

        if leech_settings:
            text += f"╭ {leech_settings[0]}\n"
            for item in leech_settings[1:-1]:
                text += f"├ {item}\n"
            if len(leech_settings) > 1:
                text += f"╰ {leech_settings[-1]}\n"

        buttons.data_button("❮❮", f"userset {user_id} back main", position="footer")
        buttons.data_button("✘", f"userset {user_id} close", position="footer")
        btns = buttons.build_menu(2)
        return text, btns

    elif stype == "dumps":
        buttons.data_button(
            "Leech Destination", f"userset {user_id} menu LEECH_DUMP_CHAT"
        )
        if user_dict.get("LEECH_DUMP_CHAT", False):
            leech_dest = user_dict["LEECH_DUMP_CHAT"]
        elif "LEECH_DUMP_CHAT" not in user_dict and Config.LEECH_DUMP_CHAT:
            leech_dest = Config.LEECH_DUMP_CHAT
        else:
            leech_dest = "None"

        buttons.data_button(
            "Mirror Destination", f"userset {user_id} menu MIRROR_DUMP_CHAT"
        )
        if user_dict.get("MIRROR_DUMP_CHAT", False):
            mirror_dest = user_dict["MIRROR_DUMP_CHAT"]
        elif (
            "MIRROR_DUMP_CHAT" not in user_dict
            and hasattr(Config, "MIRROR_DUMP_CHAT")
            and Config.MIRROR_DUMP_CHAT
        ):
            mirror_dest = Config.MIRROR_DUMP_CHAT
        else:
            mirror_dest = "None"

        buttons.data_button("Back", f"userset {user_id} back", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(1)

        text = f"""〄 <b>DUMPS Settings :</b>
╭ <b>Name</b> » {user_name}
├ 
├ <b>Leech Destination</b> » <code>{leech_dest}</code>
├ <b>Mirror Destination</b> » <code>{mirror_dest}</code>
├ 
├ <i>Configure separate destinations for Leech and Mirror operations</i>
├ <i>• Leech Destination: Where leeched files are sent</i>
╰ <i>• Mirror Destination: Where mirror links are posted</i>"""

        return text, btns

    elif stype == "general":
        buttons.data_button("❮❮", f"userset {user_id} back main", position="footer")
        buttons.data_button("✘", f"userset {user_id} close", position="footer")

        user_tokens = user_dict.get("USER_TOKENS", False)
        token_mode = "User" if user_tokens else "Owner"
        toggle_token_mode = "Owner" if user_tokens else "User"
        buttons.data_button(
            f"Switch to {toggle_token_mode} Token",
            f"userset {user_id} tog USER_TOKENS {'f' if user_tokens else 't'}",
        )

        btns = buttons.build_menu(1)
        text = (
            f"<u>Token Settings for {user_name}</u>\n\n"
            f"╭ Token Mode: <b>{token_mode}</b>"
        )
        return text, btns

    elif stype == "advanced":
        buttons.data_button(
            "Excluded Extensions", f"userset {user_id} menu EXCLUDED_EXTENSIONS"
        )
        buttons.data_button("Name Swap", f"userset {user_id} menu NAME_SWAP")
        buttons.data_button("YT-DLP Options", f"userset {user_id} menu YT_DLP_OPTIONS")
        buttons.data_button("Upload Paths", f"userset {user_id} menu UPLOAD_PATHS")
        buttons.data_button("Remname", f"userset {user_id} menu REMNAME")
        buttons.data_button(
            "User Session", f"userset {user_id} menu USER_SESSION_STRING"
        )
        buttons.data_button("❮❮", f"userset {user_id} back main", position="footer")
        buttons.data_button("✘", f"userset {user_id} close", position="footer")

        ex_ex = user_dict.get("EXCLUDED_EXTENSIONS", "Not Set")
        if isinstance(ex_ex, list):
            ex_ex = " ".join(ex_ex)

        text = f"<u>Advanced Settings for {user_name}</u>\n\n"
        advanced_settings = [
            f"Excluded Extensions: <b><code>{ex_ex}</code></b>",
            f"Name Swap: <b><code>{user_dict.get('NAME_SWAP', 'Not Set')}</code></b>",
            f"YT-DLP Options: <b><code>{user_dict.get('YT_DLP_OPTIONS', 'Not Set')}</code></b>",
            f"Upload Paths: <b><code>{user_dict.get('UPLOAD_PATHS', 'Not Set')}</code></b>",
            f"Remname: <b><code>{user_dict.get('REMNAME', 'Not Set')}</code></b>",
            f"User Session: <b>{'Set' if user_dict.get('USER_SESSION_STRING') else 'Not Set'}</b>",
        ]

        if advanced_settings:
            text += f"╭ {advanced_settings[0]}\n"
            for item in advanced_settings[1:-1]:
                text += f"├ {item}\n"
            if len(advanced_settings) > 1:
                text += f"╰ {advanced_settings[-1]}\n"

        btns = buttons.build_menu(2)
        return text, btns

    elif stype == "rclone":
        buttons.data_button("Rclone Config", f"userset {user_id} file RCLONE_CONFIG")
        buttons.data_button("Rclone Path", f"userset {user_id} menu RCLONE_PATH")
        buttons.data_button("Rclone Flags", f"userset {user_id} menu RCLONE_FLAGS")
        buttons.data_button("❮❮", f"userset {user_id} back main", position="footer")
        buttons.data_button("✘", f"userset {user_id} close", position="footer")

        rccmsg = "Set" if await aiopath.exists(rclone_conf) else "Not Set"
        rccpath = user_dict.get("RCLONE_PATH", Config.RCLONE_PATH or "None")
        rcflags = user_dict.get("RCLONE_FLAGS", Config.RCLONE_FLAGS or "None")
        btns = buttons.build_menu(1)

        text = f"<u>Rclone Settings for {user_name}</u>\n\n"
        rclone_settings = [
            f"Rclone Config: <b>{rccmsg}</b>",
            f"Rclone Flags: <code>{rcflags}</code>",
            f"Rclone Path: <code>{rccpath}</code>",
        ]

        if rclone_settings:
            text += f"╭ {rclone_settings[0]}\n"
            for item in rclone_settings[1:-1]:
                text += f"├ {item}\n"
            if len(rclone_settings) > 1:
                text += f"╰ {rclone_settings[-1]}\n"

        return text, btns

    elif stype == "gdrive":
        buttons.data_button("Token Pickle", f"userset {user_id} file TOKEN_PICKLE")
        buttons.data_button("Drive ID", f"userset {user_id} menu GDRIVE_ID")
        buttons.data_button("Index URL", f"userset {user_id} menu INDEX_URL")

        sd_msg = "Enabled"
        if user_dict.get("STOP_DUPLICATE", Config.STOP_DUPLICATE):
            buttons.data_button(
                "Disable Stop Duplicate", f"userset {user_id} tog STOP_DUPLICATE f"
            )
        else:
            sd_msg = "Disabled"
            buttons.data_button(
                "Enable Stop Duplicate",
                f"userset {user_id} tog STOP_DUPLICATE t",
                "l_body",
            )

        buttons.data_button("❮❮", f"userset {user_id} back main", position="footer")
        buttons.data_button("✘", f"userset {user_id} close", position="footer")

        tokenmsg = "Set" if await aiopath.exists(token_pickle) else "Not Set"
        gdrive_id = user_dict.get("GDRIVE_ID", Config.GDRIVE_ID or "None")
        index = user_dict.get("INDEX_URL", Config.INDEX_URL or "None")
        btns = buttons.build_menu(2)

        text = f"<u>Google Drive Settings for {user_name}</u>\n\n"
        gdrive_settings = [
            f"Token Pickle: <b>{tokenmsg}</b>",
            f"Drive ID: <code>{gdrive_id}</code>",
            f"Index URL: <code>{index}</code>",
            f"Stop Duplicate: <b>{sd_msg}</b>",
        ]
        if gdrive_settings:
            text += f"╭ {gdrive_settings[0]}\n"
            for item in gdrive_settings[1:-1]:
                text += f"├ {item}\n"
            if len(gdrive_settings) > 1:
                text += f"╰ {gdrive_settings[-1]}\n"

        return text, btns

    elif stype == "gofile":
        buttons.data_button("GoFile Token", f"userset {user_id} menu GOFILE_TOKEN")
        buttons.data_button(
            "GoFile Folder ID", f"userset {user_id} menu GOFILE_FOLDER_ID"
        )
        buttons.data_button("❮❮", f"userset {user_id} back main", position="footer")
        buttons.data_button("✘", f"userset {user_id} close", position="footer")

        gofile_token_status = "Set" if user_dict.get("GOFILE_TOKEN") else "Not Set"
        gofile_folder_id = user_dict.get("GOFILE_FOLDER_ID") or "Root Folder"

        btns = buttons.build_menu(1)

        text = f"<u>GoFile Settings for {user_name}</u>\n\n"
        gofile_settings = [
            f"GoFile Token: <b>{gofile_token_status}</b>",
            f"GoFile Folder ID: <code>{gofile_folder_id}</code>",
        ]

        if gofile_settings:
            text += f"╭ {gofile_settings[0]}\n"
            if len(gofile_settings) > 1:
                text += f"╰ {gofile_settings[-1]}\n"

        return text, btns

    elif stype == "ffset":
        buttons.data_button("General Metadata", f"userset {user_id} menu GEN_METADATA")
        buttons.data_button("Video Metadata", f"userset {user_id} menu VID_METADATA")
        buttons.data_button("Audio Metadata", f"userset {user_id} menu AUD_METADATA")
        buttons.data_button("Subtitle Metadata", f"userset {user_id} menu SUB_METADATA")

        # Note: Encode and Convert functionality moved to Video Tools section to avoid duplication
        # Users should use Video Tools → Watermark for video processing features

        buttons.data_button("❮❮", f"userset {user_id} back main", position="footer")
        buttons.data_button("✘", f"userset {user_id} close", position="footer")

        text = f"<u>FFmpeg Settings for {user_name}</u>\n\n"

        metadata_values = user_dict.get("METADATA_SETTINGS", {})
        gen_meta = metadata_values.get("GEN_METADATA", "Not Set")
        vid_meta = metadata_values.get("VID_METADATA", "Not Set")
        aud_meta = metadata_values.get("AUD_METADATA", "Not Set")
        sub_meta = metadata_values.get("SUB_METADATA", "Not Set")

        # Add watermark status (temporarily disabled - moved to video tools section)
        # wm_status = "✓ Enabled" if watermark_enabled else "✗ Disabled"

        text += f"<b>📋 Metadata Settings:</b>\n"
        text += f"╭ General: <b><code>{escape(str(gen_meta))}</code></b>\n"
        text += f"├ Video: <b><code>{escape(str(vid_meta))}</code></b>\n"
        text += f"├ Audio: <b><code>{escape(str(aud_meta))}</code></b>\n"
        text += f"╰ Subtitle: <b><code>{escape(str(sub_meta))}</code></b>\n\n"

        # Watermark settings moved to video tools section
        # text += f"<b>🎭 Watermark Settings:</b>\n"
        # text += f"╰ Status: <b>{wm_status}</b>"

        btns = buttons.build_menu(2)
        return text, btns

    elif stype == "yttools":
        buttons.data_button("Description", f"userset {user_id} menu YT_DESP")
        yt_desp_val = user_dict.get("YT_DESP", "Not Set")
        buttons.data_button("Tags", f"userset {user_id} menu YT_TAGS")
        yt_tags_val = user_dict.get("YT_TAGS", "Not Set")
        buttons.data_button("Category ID", f"userset {user_id} menu YT_CATEGORY_ID")
        yt_cat_id_val = user_dict.get("YT_CATEGORY_ID", "Not Set")
        buttons.data_button(
            "Privacy Status", f"userset {user_id} menu YT_PRIVACY_STATUS"
        )
        yt_privacy_val = user_dict.get("YT_PRIVACY_STATUS", "Not Set")
        cookies_path = f"cookies/{user_id}/cookies.txt"
        cookies_msg = "Set" if await aiopath.exists(cookies_path) else "Not Set"
        buttons.data_button("Cookies", f"userset {user_id} file YTDLP_COOKIES")

        text = f"<u>YouTube Settings for {user_name}</u>\n\n"
        yt_settings = [
            f"Description: <b><code>{escape(str(yt_desp_val))}</code></b>",
            f"Tags: <b><code>{escape(str(yt_tags_val))}</code></b>",
            f"Category ID: <b><code>{escape(str(yt_cat_id_val))}</code></b>",
            f"Privacy Status: <b><code>{escape(str(yt_privacy_val))}</code></b>",
            f"Cookies: <b>{cookies_msg}</b>",
        ]
        if yt_settings:
            text += f"╭ {yt_settings[0]}\n"
            for item in yt_settings[1:-1]:
                text += f"├ {item}\n"
            if len(yt_settings) > 1:
                text += f"╰ {yt_settings[-1]}\n"

        buttons.data_button("❮❮", f"userset {user_id} back main", position="footer")
        buttons.data_button("✘", f"userset {user_id} close", position="footer")
        btns = buttons.build_menu(2)
        return text, btns

    elif stype == "autorename":
        auto_rename = user_dict.get("AUTO_RENAME", False)
        auto_rename_type = user_dict.get("AUTO_RENAME_TYPE", "auto")
        buttons = ButtonMaker()
        buttons.data_button(
            f"Auto Rename: {'✅ ON' if auto_rename else '❌ OFF'}",
            f"userset {user_id} tog AUTO_RENAME {'f' if auto_rename else 't'}",
        )
        buttons.data_button("Set Template", f"userset {user_id} menu RENAME_TEMPLATE")

        if auto_rename_type == "manual":
            buttons.data_button(
                "Mode: Manual (Tap to switch to Auto)",
                f"userset {user_id} set_rename_type auto",
            )
            buttons.data_button(
                "Set Episode Count", f"userset {user_id} menu START_EPISODE"
            )
            buttons.data_button(
                "Set Season Count", f"userset {user_id} menu START_SEASON"
            )
        else:
            buttons.data_button(
                "Mode: Auto (Tap to switch to Manual)",
                f"userset {user_id} set_rename_type manual",
            )

        buttons.data_button(
            "❮❮", f"userset {user_id} back common_tools", position="footer"
        )
        buttons.data_button("✘", f"userset {user_id} close", position="footer")
        text = "<u>Auto Rename Settings</u>\n\n"
        rename_settings = [
            f"Status: <b>{'Enabled' if auto_rename else 'Disabled'}</b>",
            f"Mode: <b>{auto_rename_type.title()}</b>",
        ]

        text += f"╭ {rename_settings[0]}\n"
        text += f"╰ {rename_settings[1]}\n"

        btns = buttons.build_menu(2)
        return text, btns

    elif stype == "ssgrid":
        ss_enabled = user_dict.get("SS_GRID_ENABLED", False)
        pdf_mode = user_dict.get("SS_GRID_PDF_MODE", False)
        individual_pages = user_dict.get("SS_GRID_PDF_INDIVIDUAL_PAGES", False)
        buttons = ButtonMaker()

        buttons.data_button(
            f"Screenshot Grid: {'✅ ON' if ss_enabled else '❌ OFF'}",
            f"userset {user_id} tog SS_GRID_ENABLED {'f' if ss_enabled else 't'}",
        )
        buttons.data_button(
            f"PDF Mode: {'✅ ON' if pdf_mode else '❌ OFF'}",
            f"userset {user_id} tog SS_GRID_PDF_MODE {'f' if pdf_mode else 't'}",
        )
        buttons.data_button(
            f"Individual Pages: {'✅ ON' if individual_pages else '❌ OFF'}",
            f"userset {user_id} tog SS_GRID_PDF_INDIVIDUAL_PAGES {'f' if individual_pages else 't'}",
        )

        buttons.data_button("Set Count", f"userset {user_id} menu SS_GRID_COUNT")
        buttons.data_button("Set Layout", f"userset {user_id} menu SS_GRID_LAYOUT")
        buttons.data_button(
            "Set Watermark", f"userset {user_id} menu SS_GRID_WATERMARK"
        )

        buttons.data_button(
            "❮❮", f"userset {user_id} back common_tools", position="footer"
        )
        buttons.data_button("✘", f"userset {user_id} close", position="footer")
        text = "<u>Screenshot Grid Settings</u>\n\n"
        ss_settings = [
            f"Status: <b>{'Enabled' if ss_enabled else 'Disabled'}</b>",
            f"PDF Mode: <b>{'Enabled' if pdf_mode else 'Disabled'}</b>",
            f"Individual PDF Pages: <b>{'Enabled' if individual_pages else 'Disabled'}</b>",
            f"Count: <b>{user_dict.get('SS_GRID_COUNT', 'Not Set')}</b>",
            f"Layout: <b>{user_dict.get('SS_GRID_LAYOUT', 'Not Set')}</b>",
            f"Watermark: <b><code>{user_dict.get('SS_GRID_WATERMARK', 'Not Set')}</code></b>",
        ]

        if ss_settings:
            text += f"╭ {ss_settings[0]}\n"
            for item in ss_settings[1:-1]:
                text += f"├ {item}\n"
            if len(ss_settings) > 1:
                text += f"╰ {ss_settings[-1]}\n"

        btns = buttons.build_menu(2)
        return text, btns

    elif stype == "common_tools":
        buttons = ButtonMaker()

        # Get status for all common tools
        name_swap_status = "✅" if user_dict.get("NAME_SWAP") else "❌"
        remname_status = "✅" if user_dict.get("REMNAME") else "❌"
        auto_rename = user_dict.get("AUTO_RENAME", False)
        ss_enabled = user_dict.get("SS_GRID_ENABLED", False)
        thumb_path = f"thumbnails/{user_id}.jpg"
        thumb_exists = await aiopath.exists(thumb_path)

        # Prefix & Suffix
        buttons.data_button("Prefix", f"userset {user_id} menu LEECH_PREFIX")
        buttons.data_button("Suffix", f"userset {user_id} menu LEECH_SUFFIX")

        # Name operations
        buttons.data_button(
            f"Name Substitute {name_swap_status}", f"userset {user_id} menu NAME_SWAP"
        )
        buttons.data_button(
            f"Remname {remname_status}", f"userset {user_id} menu REMNAME"
        )

        # Auto rename
        buttons.data_button("Auto Rename", f"userset {user_id} autorename")

        # Thumbnail
        buttons.data_button("Thumbnail", f"userset {user_id} thumbnail")

        # Screenshot grid
        buttons.data_button("Screenshot Grid", f"userset {user_id} ssgrid")

        buttons.data_button("❮❮", f"userset {user_id} back main", position="footer")
        buttons.data_button("✘", f"userset {user_id} close", position="footer")

        text = f"<u>Common Tools for {user_name}</u>\n\n"
        common_settings = [
            f"Prefix: <b>{user_dict.get('LEECH_PREFIX', Config.LEECH_PREFIX or 'Not Set')}</b>",
            f"Suffix: <b>{user_dict.get('LEECH_SUFFIX', Config.LEECH_SUFFIX or 'Not Set')}</b>",
            f"Name Substitute: <b>{'Set' if user_dict.get('NAME_SWAP') else 'Not Set'}</b>",
            f"Remname: <b>{'Set' if user_dict.get('REMNAME') else 'Not Set'}</b>",
            f"Auto Rename: <b>{'Enabled' if auto_rename else 'Disabled'}</b>",
            f"Thumbnail: <b>{'Set' if thumb_exists else 'Not Set'}</b>",
            f"Screenshot Grid: <b>{'Enabled' if ss_enabled else 'Disabled'}</b>",
        ]

        if common_settings:
            text += f"╭ {common_settings[0]}\n"
            for item in common_settings[1:-1]:
                text += f"├ {item}\n"
            if len(common_settings) > 1:
                text += f"╰ {common_settings[-1]}\n"

        btns = buttons.build_menu(2)
        return text, btns

    elif stype == "vt_samplevideo":
        # Video Tools Sample Video Settings (same as samplevideo but with different back navigation)
        sv_enabled = user_dict.get("SAMPLE_VIDEO_ENABLED", False)
        sv_count = user_dict.get("SAMPLE_VIDEO_COUNT", 1)
        sv_duration = user_dict.get("SAMPLE_VIDEO_DURATION", 60)
        sv_separate = user_dict.get("SAMPLE_VIDEO_SEPARATE", False)

        buttons = ButtonMaker()

        buttons.data_button(
            f"Sample Video: {'✅ ON' if sv_enabled else '❌ OFF'}",
            f"userset {user_id} vt_tog SAMPLE_VIDEO_ENABLED {'f' if sv_enabled else 't'}",
        )
        buttons.data_button(
            f"Separate Clips: {'✅ ON' if sv_separate else '❌ OFF'}",
            f"userset {user_id} vt_tog SAMPLE_VIDEO_SEPARATE {'f' if sv_separate else 't'}",
        )

        buttons.data_button("Set Count", f"userset {user_id} menu SAMPLE_VIDEO_COUNT")
        buttons.data_button(
            "Set Duration", f"userset {user_id} menu SAMPLE_VIDEO_DURATION"
        )

        buttons.data_button("❮❮", f"userset {user_id} back vtset", position="footer")
        buttons.data_button("✘", f"userset {user_id} close", position="footer")

        text = "<u>Sample Video Settings</u>\n\n"
        sv_settings = [
            f"Status: <b>{'Enabled' if sv_enabled else 'Disabled'}</b>",
            f"Clip Count: <b>{sv_count}</b>",
            f"Clip Duration: <b>{sv_duration} sec</b>",
            f"Output Mode: <b>{'Separate Files' if sv_separate else 'Single Merged File'}</b>",
        ]

        if sv_settings:
            text += f"╭ {sv_settings[0]}\n"
            for item in sv_settings[1:-1]:
                text += f"├ {item}\n"
            if len(sv_settings) > 1:
                text += f"╰ {sv_settings[-1]}\n"

        text += "\n<i>💡 The bot will generate random clip(s) from video(s) after download. Total clip duration should not exceed 25% of original video length.</i>"

        btns = buttons.build_menu(2)
        return text, btns

    elif stype == "vt_encoding":
        # Video Encoding Settings submenu
        buttons = ButtonMaker()

        # Get encoding settings
        video_encode_enabled = user_dict.get("VIDEO_ENCODE_ENABLED", False)
        video_encode_codec = user_dict.get("VIDEO_ENCODE_CODEC", "x264")
        video_encode_preset = user_dict.get("VIDEO_ENCODE_PRESET", "medium")
        video_encode_quality = user_dict.get("VIDEO_ENCODE_QUALITY", "Original")
        video_encode_crf = user_dict.get("VIDEO_ENCODE_CRF", 23)
        video_encode_audio_bitrate = user_dict.get("VIDEO_ENCODE_AUDIO_BITRATE", "128k")
        multi_res_enabled = user_dict.get("VIDEO_ENCODE_MULTI_RESOLUTION", False)
        resolution_list = user_dict.get("VIDEO_ENCODE_RESOLUTION_LIST", "")
        multi_zip_enabled = user_dict.get("VIDEO_ENCODE_MULTI_ZIP", False)

        # Main toggle
        buttons.data_button(
            f"{'Disable' if video_encode_enabled else 'Enable'} Encoding",
            f"userset {user_id} tog VIDEO_ENCODE_ENABLED {'f' if video_encode_enabled else 't'}",
        )

        # Show encoding options only when enabled
        if video_encode_enabled:
            buttons.data_button(
                "Set Codec", f"userset {user_id} menu VIDEO_ENCODE_CODEC"
            )
            buttons.data_button(
                "Set Preset", f"userset {user_id} menu VIDEO_ENCODE_PRESET"
            )
            buttons.data_button(
                "Set Quality", f"userset {user_id} menu VIDEO_ENCODE_QUALITY"
            )
            buttons.data_button("Set CRF", f"userset {user_id} menu VIDEO_ENCODE_CRF")
            buttons.data_button(
                "Audio Bitrate", f"userset {user_id} menu VIDEO_ENCODE_AUDIO_BITRATE"
            )

            # Multi-resolution options
            buttons.data_button(
                f"{'Disable' if multi_res_enabled else 'Enable'} Multi-Res",
                f"userset {user_id} tog VIDEO_ENCODE_MULTI_RESOLUTION {'f' if multi_res_enabled else 't'}",
            )

            if multi_res_enabled:
                buttons.data_button(
                    "Set Resolutions",
                    f"userset {user_id} menu VIDEO_ENCODE_RESOLUTION_LIST",
                )
                buttons.data_button(
                    f"{'Disable' if multi_zip_enabled else 'Enable'} Multi-Zip",
                    f"userset {user_id} tog VIDEO_ENCODE_MULTI_ZIP {'f' if multi_zip_enabled else 't'}",
                )

        buttons.data_button("❮❮", f"userset {user_id} back vtset", position="footer")
        buttons.data_button("✘", f"userset {user_id} close", position="footer")

        text = "🎬 <u>Video Encoding Settings</u>\n\n"
        encoding_settings = [
            f"Status: <b>{'Enabled' if video_encode_enabled else 'Disabled'}</b>",
        ]

        if video_encode_enabled:
            encoding_settings.extend(
                [
                    f"Codec: <b>{video_encode_codec}</b>",
                    f"Preset: <b>{video_encode_preset}</b>",
                    f"Quality: <b>{video_encode_quality}</b>",
                    f"CRF: <b>{video_encode_crf}</b>",
                    f"Audio Bitrate: <b>{video_encode_audio_bitrate}</b>",
                    f"Multi-Resolution: <b>{'Enabled' if multi_res_enabled else 'Disabled'}</b>",
                ]
            )

            if multi_res_enabled:
                res_display = resolution_list if resolution_list else "All Available"
                encoding_settings.extend(
                    [
                        f"Resolutions: <b>{res_display}</b>",
                        f"Multi-Zip: <b>{'Enabled' if multi_zip_enabled else 'Disabled'}</b>",
                    ]
                )

        # Format the settings display
        text += "╭ " + encoding_settings[0] + "\n"
        if len(encoding_settings) > 1:
            for setting in encoding_settings[1:-1]:
                text += f"├ {setting}\n"
            if len(encoding_settings) > 1:
                text += f"╰ {encoding_settings[-1]}\n"

        if video_encode_enabled:
            text += "\n<i>💡 Video encoding will re-encode videos with specified preset for better compression and quality control.</i>"

        btns = buttons.build_menu(2)
        return text, btns

    elif stype == "vt_hardsub":
        # Video Hardsub Settings submenu
        buttons = ButtonMaker()

        # Get hardsub settings
        hardsub_enabled = user_dict.get("VIDEO_HARDSUB_ENABLED", False)
        hardsub_font_name = user_dict.get("VIDEO_HARDSUB_FONT_NAME", "Arial")
        hardsub_font_size = user_dict.get("VIDEO_HARDSUB_FONT_SIZE", 22)
        hardsub_font_colour = user_dict.get("VIDEO_HARDSUB_FONT_COLOUR", "FFFFFF")
        hardsub_style = user_dict.get("VIDEO_HARDSUB_STYLE", "default")

        # Main toggle
        buttons.data_button(
            f"{'Disable' if hardsub_enabled else 'Enable'} Hardsub",
            f"userset {user_id} tog VIDEO_HARDSUB_ENABLED {'f' if hardsub_enabled else 't'}",
        )

        # Show hardsub options only when enabled
        if hardsub_enabled:
            buttons.data_button(
                "Set Font Name", f"userset {user_id} menu VIDEO_HARDSUB_FONT_NAME"
            )
            buttons.data_button(
                "Upload Custom Font", f"userset {user_id} file VT_HARDSUB_FONT_PATH"
            )
            buttons.data_button(
                "Set Font Size", f"userset {user_id} menu VIDEO_HARDSUB_FONT_SIZE"
            )
            buttons.data_button(
                "Set Font Color", f"userset {user_id} menu VIDEO_HARDSUB_FONT_COLOUR"
            )
            buttons.data_button(
                "Set Style", f"userset {user_id} menu VIDEO_HARDSUB_STYLE"
            )
            # Add margin settings
            buttons.data_button(
                "Set Left Margin", f"userset {user_id} menu VT_HARDSUB_MARGIN_L"
            )
            buttons.data_button(
                "Set Right Margin", f"userset {user_id} menu VT_HARDSUB_MARGIN_R"
            )
            buttons.data_button(
                "Set Vertical Margin", f"userset {user_id} menu VT_HARDSUB_MARGIN_V"
            )

        buttons.data_button("❮❮", f"userset {user_id} back vtset", position="footer")
        buttons.data_button("✘", f"userset {user_id} close", position="footer")

        text = "<u>Video Hardsub Settings</u>\n\n"
        hardsub_settings = [
            f"Status: <b>{'Enabled' if hardsub_enabled else 'Disabled'}</b>",
        ]

        if hardsub_enabled:
            custom_font_path = user_dict.get("VT_HARDSUB_FONT_PATH", "")

            if custom_font_path:
                custom_font_status = "Single Font File"
            else:
                custom_font_status = "System Font"

            # Get margin settings
            margin_l = user_dict.get("VT_HARDSUB_MARGIN_L", 10)
            margin_r = user_dict.get("VT_HARDSUB_MARGIN_R", 10)
            margin_v = user_dict.get("VT_HARDSUB_MARGIN_V", 10)
            hardsub_settings.extend(
                [
                    f"Font Name: <b>{hardsub_font_name}</b>",
                    f"Font Type: <b>{custom_font_status}</b>",
                    f"Font Size: <b>{hardsub_font_size}</b>",
                    f"Font Color: <b>#{hardsub_font_colour}</b>",
                    f"Style: <b>{hardsub_style.title() if hardsub_style else 'default'}</b>",
                    f"Margins (L/R/V): <b>{margin_l}/{margin_r}/{margin_v}</b>",
                ]
            )

        # Format the settings display
        if hardsub_settings:
            text += f"╭ {hardsub_settings[0]}\n"
            for item in hardsub_settings[1:-1]:
                text += f"├ {item}\n"
            if len(hardsub_settings) > 1:
                text += f"╰ {hardsub_settings[-1]}\n"

        if hardsub_enabled:
            text += "\n<i>🔥 Hardsub will permanently burn subtitles into the video. This cannot be undone but ensures subtitles are always visible.</i>"
            text += "\n\n<b>📋 Supported Styles:</b>"
            text += "\n• <code>default</code> - Original subtitle formatting"
            text += "\n• <code>bold</code> - Bold text"
            text += "\n• <code>outline</code> - Bold with black outline"
            text += "\n• <code>shadow</code> - Bold with shadow effect"
            text += "\n• <code>glow</code> - Bold with white glow effect"

        btns = buttons.build_menu(2)
        return text, btns

    elif stype == "auto_process":
        buttons = ButtonMaker()
        user_dict = user_data.get(user_id, {})
        auto_leech = user_dict.get("AUTO_LEECH", False)
        auto_mirror = user_dict.get("AUTO_MIRROR", False)
        auto_vt = user_dict.get("AUTO_VT", False)

        buttons.data_button(
            "Disable Auto Leech" if auto_leech else "Enable Auto Leech",
            f"userset {user_id} tog AUTO_LEECH {'f' if auto_leech else 't'}",
        )
        buttons.data_button(
            "Disable Auto Mirror" if auto_mirror else "Enable Auto Mirror",
            f"userset {user_id} tog AUTO_MIRROR {'f' if auto_mirror else 't'}",
        )
        buttons.data_button(
            "Disable Auto -vt" if auto_vt else "Enable Auto -vt",
            f"userset {user_id} tog AUTO_VT {'f' if auto_vt else 't'}",
        )
        buttons.data_button("❮❮", f"userset {user_id} back general", position="footer")
        buttons.data_button("✘", f"userset {user_id} close", position="footer")
        btns = buttons.build_menu(2)
        text = f"""<u>Auto Leech/Mirror Settings for {user_name}</u>

╭<b>Auto Leech:</b> <b>{"Enabled" if auto_leech else "Disabled"}</b>
├<b>Auto Mirror:</b> <b>{"Enabled" if auto_mirror else "Disabled"}</b>
╰<b>Auto -vt:</b> <b>{"Enabled" if auto_vt else "Disabled"}</b>

<i>When enabled, the bot will automatically process any links or files you send:
• Auto Leech: Automatically leeches links/files
• Auto Mirror: Automatically mirrors links/files
• Auto -vt: Asks for video tools selection like normal commands</i>"""
        return text, btns

    elif stype == "attachments_menu":
        buttons = ButtonMaker()
        text = f"<u>Attachment Settings for {user_name}</u>\n\n"
        attachment_settings = []

        embed_default_thumb = user_dict.get("EMBED_DEFAULT_USER_THUMBNAIL", False)
        buttons.data_button(
            f"Embed Default Thumb: {'✅ ON' if embed_default_thumb else '❌ OFF'}",
            f"userset {user_id} tog EMBED_DEFAULT_USER_THUMBNAIL {'f' if embed_default_thumb else 't'}",
        )
        attachment_settings.append(
            f"Embed Thumb: <b>{'Enabled' if embed_default_thumb else 'Disabled'}</b>"
        )

        raw_text_val = user_dict.get("USER_ATTACHMENT_TEXT")
        user_attach_text_val = (
            raw_text_val if isinstance(raw_text_val, str) else "Not Set"
        )
        buttons.data_button(
            "Set Attach Text", f"userset {user_id} menu USER_ATTACHMENT_TEXT"
        )
        attachment_settings.append(
            f"Custom Attach Text: <b><code>{escape(user_attach_text_val if isinstance(user_attach_text_val, str) and len(user_attach_text_val) < 20 else (user_attach_text_val[:20] + '...') if isinstance(user_attach_text_val, str) else user_attach_text_val)}</code></b>"
        )

        user_attach_photo_val = user_dict.get("USER_ATTACHMENT_PHOTO")
        custom_photo_status = (
            "Set"
            if user_attach_photo_val and await aiopath.exists(user_attach_photo_val)
            else "Not Set"
        )

        if custom_photo_status == "Set":
            buttons.data_button(
                "Change Attach Photo", f"userset {user_id} file USER_ATTACHMENT_PHOTO"
            )
            buttons.data_button(
                "Remove Attach Photo",
                f"userset {user_id} remove_file USER_ATTACHMENT_PHOTO",
            )
        else:
            buttons.data_button(
                "Set Attach Photo", f"userset {user_id} file USER_ATTACHMENT_PHOTO"
            )

        photo_text = f"Custom Attach Photo: <b>{custom_photo_status}</b>"
        if custom_photo_status == "Set":
            photo_text += (
                f" (<code>{escape(os.path.basename(user_attach_photo_val))}</code>)"
            )
        attachment_settings.append(photo_text)

        if attachment_settings:
            text += f"╭ {attachment_settings[0]}\n"
            for item in attachment_settings[1:-1]:
                text += f"├ {item}\n"
            if len(attachment_settings) > 1:
                text += f"╰ {attachment_settings[-1]}\n"

        buttons.data_button(
            "❮❮", f"userset {user_id} back_photo main", position="footer"
        )
        buttons.data_button("✘", f"userset {user_id} close", position="footer")
        btns = buttons.build_menu(1)
        return text, btns

    elif stype == "vtset":
        buttons = ButtonMaker()
        # Status summary
        ar_val = user_dict.get("VT_AUDIO_REMOVE")
        ao_val = user_dict.get("VT_AUDIO_ORDER")
        ar_status = ar_val if ar_val else "Not Exists"
        ao_status = ao_val if ao_val else "Not Exists"
        buttons.data_button("Audio Remove", f"userset {user_id} menu VT_AUDIO_REMOVE")
        buttons.data_button("Audio Change", f"userset {user_id} menu VT_AUDIO_ORDER")
        # Additional tools
        tr_status = user_dict.get("VT_TRIM_RANGE", "Not Set")
        sp_status = user_dict.get("VT_SPEED", "Not Set")
        cp_status = user_dict.get("VT_COMPRESS", "Not Set")
        ex_status = user_dict.get("VT_EXTRACT", "Not Set")
        # Watermark variables removed - functionality only via -vt command
        cv_status = user_dict.get("VT_CONVERT_QUALITY", "Not Set")
        buttons.data_button("Trim", f"userset {user_id} menu VT_TRIM_RANGE")
        buttons.data_button("Speed", f"userset {user_id} menu VT_SPEED")
        buttons.data_button("Compress", f"userset {user_id} menu VT_COMPRESS")
        buttons.data_button("Extract", f"userset {user_id} menu VT_EXTRACT")
        # Watermark functionality is only available via -vt command, not through UI
        buttons.data_button("Convert", f"userset {user_id} menu VT_CONVERT_QUALITY")
        # Hardsub controls
        hardsub_enabled = user_dict.get("VIDEO_HARDSUB_ENABLED", False)
        buttons.data_button(
            ("Disable " if hardsub_enabled else "Enable ") + "Hardsub",
            f"userset {user_id} tog VIDEO_HARDSUB_ENABLED {'f' if hardsub_enabled else 't'}",
        )
        buttons.data_button("Hardsub Settings", f"userset {user_id} vt_hardsub")
        # Intro Sub controls
        intro_enabled = user_dict.get("INTRO_SUBTITLE_ENABLED", False)
        buttons.data_button(
            ("Disable " if intro_enabled else "Enable ") + "Intro Sub",
            f"userset {user_id} tog INTRO_SUBTITLE_ENABLED {'f' if intro_enabled else 't'}",
        )
        buttons.data_button("Intro Sub Settings", f"userset {user_id} intro_menu")
        # Subsync toggle and Rename
        subsync_enabled = bool(user_dict.get("VT_SUBSYNC", False))
        buttons.data_button(
            ("Disable " if subsync_enabled else "Enable ") + "Subsync",
            f"userset {user_id} tog VT_SUBSYNC {'f' if subsync_enabled else 't'}",
        )
        buttons.data_button("Rename To", f"userset {user_id} menu VT_RENAME_TO")
        # Merge toggles
        mv = bool(user_dict.get("VT_MERGE_VIDEOS", False))
        ma = bool(user_dict.get("VT_MERGE_AUDIOS", False))
        ms = bool(user_dict.get("VT_MERGE_SUBS", False))
        buttons.data_button(
            ("Disable " if mv else "Enable ") + "Merge Videos",
            f"userset {user_id} tog VT_MERGE_VIDEOS {'f' if mv else 't'}",
        )
        buttons.data_button(
            ("Disable " if ma else "Enable ") + "Merge Audios",
            f"userset {user_id} tog VT_MERGE_AUDIOS {'f' if ma else 't'}",
        )
        buttons.data_button(
            ("Disable " if ms else "Enable ") + "Merge Subtitles",
            f"userset {user_id} tog VT_MERGE_SUBS {'f' if ms else 't'}",
        )
        # Sample Video settings
        buttons.data_button(
            "Sample Video Settings", f"userset {user_id} vt_samplevideo"
        )
        # Video Encoding settings
        video_encode_enabled = user_dict.get("VIDEO_ENCODE_ENABLED", False)
        buttons.data_button("Encoding Settings", f"userset {user_id} vt_encoding")
        buttons.data_button("❮❮", f"userset {user_id} back main", position="footer")
        buttons.data_button("✘", f"userset {user_id} close", position="footer")
        btns = buttons.build_menu(2)
        text = "㊂ Video Tools Settings"
        text += f"\n╭ <b>L/M Filename Audio Remove</b> : {escape(str(ar_status))}"
        text += f"\n├ <b>L/M Filename Audio Change</b> : {escape(str(ao_status))}"
        text += f"\n├ <b>Trim</b>: {escape(str(tr_status))}"
        text += f"\n├ <b>Speed</b>: {escape(str(sp_status))}"
        text += f"\n├ <b>Compress</b>: {escape(str(cp_status))}"
        text += f"\n├ <b>Extract</b>: {escape(str(ex_status))}"
        # Watermark info removed - functionality only via -vt command
        text += f"\n├ <b>Convert</b>: {escape(str(cv_status))}"
        # Hardsub status
        hardsub_enabled = user_dict.get("VIDEO_HARDSUB_ENABLED", False)
        hardsub_font = user_dict.get("VIDEO_HARDSUB_FONT_NAME", "Not Set")
        text += f"\n├ <b>Hardsub</b>: {'Enabled' if hardsub_enabled else 'Disabled'} ({hardsub_font})"
        text += f"\n├ <b>Subsync</b>: {'Enabled' if subsync_enabled else 'Disabled'}"
        text += f"\n├ <b>Intro Sub</b>: {'Enabled' if user_dict.get('INTRO_SUBTITLE_ENABLED', False) else 'Disabled'}"
        text += f"\n├ <b>Intro Text</b>: {escape(str(user_dict.get('INTRO_SUBTITLE_TEXT', 'Not Set')))}"
        text += f"\n├ <b>Intro Style</b>: {escape(str(user_dict.get('INTRO_SUBTITLE_STYLE', 'typing')))}"
        text += f"\n├ <b>Intro Mode</b>: {escape(str(user_dict.get('INTRO_SUBTITLE_MODE', 'existing')))}"
        text += f"\n├ <b>Intro Position</b>: {escape(str(user_dict.get('INTRO_SUBTITLE_POSITION', 'bottom')))}"
        text += f"\n├ <b>Intro Font Size</b>: {escape(str(user_dict.get('INTRO_SUBTITLE_FONT_SIZE', 48)))}"
        text += f"\n├ <b>Intro Colors</b>: {escape(str(user_dict.get('INTRO_SUBTITLE_COLORS', 'Default')))}"
        text += f"\n├ <b>Intro Char MS</b>: {escape(str(user_dict.get('INTRO_SUBTITLE_CHAR_MS', 300)))}"
        text += f"\n├ <b>Rename To</b>: {escape(str(user_dict.get('VT_RENAME_TO', 'Not Set')))}"
        text += f"\n├ <b>Merge Videos</b>: {'Enabled' if mv else 'Disabled'}"
        text += f"\n├ <b>Merge Audios</b>: {'Enabled' if ma else 'Disabled'}"
        text += f"\n├ <b>Merge Subtitles</b>: {'Enabled' if ms else 'Disabled'}"
        # Sample Video status
        sv_enabled = user_dict.get("SAMPLE_VIDEO_ENABLED", False)
        sv_count = user_dict.get("SAMPLE_VIDEO_COUNT", 3)
        sv_duration = user_dict.get("SAMPLE_VIDEO_DURATION", 60)
        text += f"\n├ <b>Sample Video</b>: {'Enabled' if sv_enabled else 'Disabled'} ({sv_count}x{sv_duration}s)"
        # Video Encoding status
        video_encode_enabled = user_dict.get("VIDEO_ENCODE_ENABLED", False)
        video_encode_preset = user_dict.get("VIDEO_ENCODE_PRESET", "medium")
        text += f"\n╰ <b>Video Encoding</b>: {'Enabled' if video_encode_enabled else 'Disabled'} ({video_encode_preset})"
        return text, btns

    elif stype == "zipmode":
        # Zip Mode submenu
        current_mode = (user_dict.get("ZIP_MODE", "folders") or "folders").lower()

        def label(mode_key, label):
            return ("✅ " if current_mode == mode_key else "") + label

        buttons.data_button(
            label("folders", "Folders (Default)"),
            f"userset {user_id} set ZIP_MODE folders",
        )
        buttons.data_button(
            label("cloud_part", "Cloud Part"),
            f"userset {user_id} set ZIP_MODE cloud_part",
        )
        buttons.data_button(
            label("each_files", "Each Files"),
            f"userset {user_id} set ZIP_MODE each_files",
        )
        buttons.data_button(
            label("part_mode", "Part Mode"), f"userset {user_id} set ZIP_MODE part_mode"
        )
        buttons.data_button(
            label("auto_mode", "Auto Mode"), f"userset {user_id} set ZIP_MODE auto_mode"
        )
        buttons.data_button("❮❮", f"userset {user_id} back main", position="footer")
        buttons.data_button("✘", f"userset {user_id} close", position="footer")
        cur = user_dict.get("ZIP_MODE", "folders").title()
        text = (
            f"<u>ZIP MODE SETTINGS</u>\n\n"
            "⁍ Folders/Default: Zip file/folder\n"
            "⁍ Cloud Part: Zip file/folder as part 3.91GB (Mirror Cmds)\n"
            "⁍ Each Files: Zip each file in folder/subfolder\n"
            "⁍ Part Mode: Zip each file in folder/subfolder as part if > 3.91GB (Mirror Cmds)\n"
            "⁍ Auto Mode: Zip only files > 3.91GB in folder/subfolder\n\n"
            f"Current Mode: <b>{cur}</b>\n\n"
            "Note: Seeding supported only in Default (Folders) mode."
        )
        btns = buttons.build_menu(2)
        return text, btns

    return "Invalid Settings page.", None


@new_task
async def send_user_settings(_, message):
    from_user = message.from_user
    user_id = from_user.id
    handler_dict[user_id] = False
    msg, button = await get_user_settings(from_user)

    thumb_path = f"thumbnails/{user_id}.jpg"
    photo_to_send = thumb_path
    if not await aiopath.exists(thumb_path):
        photo_to_send = getattr(Config, "IMAGE_USETIINGS", None)

    if photo_to_send:
        res = await send_message(
            message, msg, button, photo=photo_to_send, reply_to_message_id=message.id
        )
        if isinstance(res, str):
            LOGGER.error(f"Failed to send user settings with photo: {res}")
            await send_message(message, msg, button)
    else:
        await send_message(message, msg, button)


@new_task
async def add_file(_, message, ftype, rfunc):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    des_dir = None
    if ftype == "THUMBNAIL":
        des_dir = await create_thumb(message, user_id)
    elif ftype == "USER_ATTACHMENT_PHOTO":
        attach_dir = os.path.join(os.getcwd(), "attachments")
        await makedirs(attach_dir, exist_ok=True)
        des_dir = os.path.join(attach_dir, f"{user_id}_custom_attach.jpg")
        if message.photo:
            await message.download(file_name=des_dir)
            try:
                with Image.open(des_dir) as img:
                    img.verify()
                LOGGER.info(f"USER_ATTACHMENT_PHOTO saved and verified: {des_dir}")
                LOGGER.info(
                    "Reminder: For USER_ATTACHMENT_PHOTO to persist, map 'attachments/' to a persistent volume."
                )
            except Exception as e:
                LOGGER.error(
                    f"Uploaded USER_ATTACHMENT_PHOTO {des_dir} is not a valid image or PIL error: {e}"
                )
                if await aiopath.exists(des_dir):
                    await aioremove(des_dir)
                des_dir = None
                if not handler_dict.get(user_id, True):
                    await send_message(
                        message, "Invalid image file for attachment. Please try again."
                    )
        else:
            des_dir = None
            if not handler_dict.get(user_id, True):
                await send_message(message, "No photo found for USER_ATTACHMENT_PHOTO.")

    elif ftype == "RCLONE_CONFIG":
        des_dir = f"{os.getcwd()}/rclone/{user_id}.conf"
        await makedirs(f"{os.getcwd()}/rclone/", exist_ok=True)
        await message.download(file_name=des_dir)
    elif ftype == "TOKEN_PICKLE":
        des_dir = f"{os.getcwd()}/tokens/{user_id}.pickle"
        await makedirs(f"{os.getcwd()}/tokens/", exist_ok=True)
        await message.download(file_name=des_dir)
    elif ftype == "YTDLP_COOKIES":
        des_dir = f"{os.getcwd()}/cookies/{user_id}/cookies.txt"
        await makedirs(f"{os.getcwd()}/cookies/{user_id}", exist_ok=True)
        await message.download(file_name=des_dir)
    elif ftype == "VT_WATERMARK_IMAGE":
        wm_dir = os.path.join(os.getcwd(), "thumbnails", "watermark")
        await makedirs(wm_dir, exist_ok=True)
        des_dir = os.path.join(wm_dir, f"{user_id}.png")
        # Accept photo, document, animation, or sticker upload
        if message.photo or message.document or message.animation or message.sticker:
            temp_path = des_dir + ".tmp"
            await message.download(file_name=temp_path)
            try:
                # Open and convert to PNG (use first frame if animated)
                with Image.open(temp_path) as img:
                    try:
                        if getattr(img, "is_animated", False):
                            img.seek(0)
                    except Exception:
                        pass
                    img.convert("RGBA").save(des_dir, format="PNG")
                LOGGER.info(f"VT_WATERMARK_IMAGE saved and verified: {des_dir}")
            except Exception as e:
                LOGGER.error(
                    f"Uploaded VT_WATERMARK_IMAGE is not a valid image or PIL error: {e}"
                )
                if await aiopath.exists(temp_path):
                    await aioremove(temp_path)
                des_dir = None
                if not handler_dict.get(user_id, True):
                    await send_message(
                        message,
                        "Invalid image file for watermark. Please try again (try sending as Document).",
                    )
            finally:
                if await aiopath.exists(temp_path):
                    await aioremove(temp_path)
        else:
            des_dir = None
            if not handler_dict.get(user_id, True):
                await send_message(message, "No image found for VT_WATERMARK_IMAGE.")
    elif ftype == "VIDEO_WATERMARK_IMAGE_PATH":
        wm_dir = os.path.join(os.getcwd(), "thumbnails", "video_watermark")
        await makedirs(wm_dir, exist_ok=True)
        des_dir = os.path.join(wm_dir, f"{user_id}.png")
        # Accept photo, document, animation, or sticker upload
        if message.photo or message.document or message.animation or message.sticker:
            temp_path = des_dir + ".tmp"
            await message.download(file_name=temp_path)
            try:
                # Open and convert to PNG with transparency support (use first frame if animated)
                with Image.open(temp_path) as img:
                    try:
                        if getattr(img, "is_animated", False):
                            img.seek(0)
                    except Exception:
                        pass
                    img.convert("RGBA").save(des_dir, format="PNG")
                LOGGER.info(f"VIDEO_WATERMARK_IMAGE_PATH saved and verified: {des_dir}")
            except Exception as e:
                LOGGER.error(
                    f"Uploaded VIDEO_WATERMARK_IMAGE_PATH is not a valid image or PIL error: {e}"
                )
                if await aiopath.exists(temp_path):
                    await aioremove(temp_path)
                des_dir = None
                if not handler_dict.get(user_id, True):
                    await send_message(
                        message,
                        "Invalid image file for video watermark. Please try uploading as Document instead.",
                    )
            finally:
                if await aiopath.exists(temp_path):
                    await aioremove(temp_path)
        else:
            des_dir = None
            if not handler_dict.get(user_id, True):
                await send_message(
                    message, "No image found for VIDEO_WATERMARK_IMAGE_PATH."
                )
    elif ftype in [
        "INTRO_SUBTITLE_FONT_PATH",
        "VT_WM_FONT_PATH",
        "VT_HARDSUB_FONT_PATH",
    ]:
        # Handle font file uploads (TTF/OTF)
        font_dir = os.path.join(os.getcwd(), "fonts")
        await makedirs(font_dir, exist_ok=True)

        if ftype == "INTRO_SUBTITLE_FONT_PATH":
            des_dir = os.path.join(font_dir, f"{user_id}.ttf")
        elif ftype == "VT_WM_FONT_PATH":
            des_dir = os.path.join(font_dir, f"wm_{user_id}.ttf")
        elif ftype == "VT_HARDSUB_FONT_PATH":
            des_dir = os.path.join(font_dir, f"hardsub_{user_id}.ttf")

        if message.document:
            # Validate font file
            if message.document.file_name and (
                message.document.file_name.lower().endswith((".ttf", ".otf"))
            ):
                await message.download(file_name=des_dir)
                LOGGER.info(f"{ftype} font file saved: {des_dir}")
            else:
                des_dir = None
                if not handler_dict.get(user_id, True):
                    await send_message(
                        message, "Please upload a valid TTF or OTF font file."
                    )
        else:
            des_dir = None
            if not handler_dict.get(user_id, True):
                await send_message(message, f"No document found for {ftype}.")
    else:
        des_dir = None

    await delete_message(message)

    if des_dir:
        update_user_ldata(user_id, ftype, des_dir)
        if ftype == "USER_ATTACHMENT_PHOTO":
            try:
                async with aiopen(des_dir, "rb") as photo_file:
                    photo_binary_content = await photo_file.read()
                update_user_ldata(
                    user_id, "USER_ATTACHMENT_PHOTO_CONTENT", photo_binary_content
                )
                LOGGER.info(
                    f"Stored binary content for USER_ATTACHMENT_PHOTO for user {user_id}"
                )
            except Exception as e:
                LOGGER.error(
                    f"Failed to read binary for USER_ATTACHMENT_PHOTO {des_dir}: {e}"
                )
                update_user_ldata(user_id, "USER_ATTACHMENT_PHOTO", None)
        # Persist user private files to DB for restoration after restart
        if (
            ftype in ("THUMBNAIL", "RCLONE_CONFIG", "TOKEN_PICKLE", "YTDLP_COOKIES")
            and des_dir
        ):
            try:
                # Update path in user_data and save binary to database
                update_user_ldata(user_id, ftype, des_dir)
                # Store binary content using update_user_doc like reference implementation
                await database.update_user_doc(user_id, f"{ftype}_CONTENT", des_dir)
                LOGGER.info(f"Stored {ftype} content for user {user_id} into DB")
            except Exception as e:
                LOGGER.error(f"Failed to store {ftype} content for {user_id}: {e}")
        await database.update_user_data(user_id)
    elif ftype == "USER_ATTACHMENT_PHOTO" and not des_dir:
        update_user_ldata(user_id, "USER_ATTACHMENT_PHOTO", None)
        update_user_ldata(user_id, "USER_ATTACHMENT_PHOTO_CONTENT", None)
        await database.update_user_data(user_id)

    if rfunc:
        await rfunc()


@new_task
async def add_one(_, message, option, rfunc):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    user_dict = user_data.get(user_id, {})
    value = message.text
    if value.startswith("{") and value.endswith("}"):
        try:
            value = eval(value)
            if user_dict.get(option):
                user_dict[option].update(value)
            else:
                update_user_ldata(user_id, option, value)
        except Exception as e:
            await send_message(message, str(e))
            return
    else:
        await send_message(message, "It must be a dictionary!")
        return
    await delete_message(message)
    await rfunc()
    await database.update_user_data(user_id)


@new_task
async def remove_one(_, message, option, rfunc):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    user_dict = user_data.get(user_id, {})
    names = message.text.split("/")
    if user_dict.get(option):
        for name in names:
            if name in user_dict[option]:
                del user_dict[option][name]
    await delete_message(message)
    await rfunc()
    await database.update_user_data(user_id)


@new_task
async def set_option(_, message, option, rfunc):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    value = message.text
    if option in ["GEN_METADATA", "VID_METADATA", "AUD_METADATA", "SUB_METADATA"]:
        user_metadata = user_data.setdefault(user_id, {}).setdefault(
            "METADATA_SETTINGS", {}
        )
        user_metadata[option] = value

        await delete_message(message)
        await rfunc()
        await database.update_user_data(user_id)
        return

    if option == "LEECH_SPLIT_SIZE":
        value = get_size_bytes(value)
        if value:
            value = min(int(value), TgClient.MAX_SPLIT_SIZE)
    elif option == "EXCLUDED_EXTENSIONS":
        value = ["aria2", "!qB", "ass"] + [
            x.lstrip(".").strip().lower() for x in value.split()
        ]
    elif option == "YT_TAGS":
        if isinstance(value, str):
            value = [tag.strip() for tag in value.split(",") if tag.strip()]
    elif option == "YT_CATEGORY_ID" and value.isdigit():
        value = int(value)
    elif option == "YT_PRIVACY_STATUS" and value.lower() not in [
        "public",
        "private",
        "unlisted",
    ]:
        await send_message(
            message, "YouTube privacy status must be public, private, or unlisted."
        )
        return
    elif option in ["UPLOAD_PATHS", "FFMPEG_CMDS", "YT_DLP_OPTIONS"]:
        if value.startswith("{") and value.endswith("}"):
            try:
                value = eval(sub(r"\s+", " ", value))
            except Exception as e:
                await send_message(message, str(e))
                return
        else:
            await send_message(message, "It must be a dictionary!")
            return
    elif option == "USER_SESSION_STRING":
        if not value or len(value) < 50:
            await send_message(
                message,
                "❌ Invalid session string! Please provide a valid Telegram session string.",
            )
            return
        from base64 import b64encode

        value = b64encode(value.encode()).decode()
    elif option == "VIDEO_ENCODE_CODEC":
        # Validate codec selection
        allowed_codecs = {"x264", "x265"}
        value_lower = value.lower().strip()
        if value_lower not in allowed_codecs:
            await send_message(
                message, f"Invalid codec '{value}'. Please choose 'x264' or 'x265'."
            )
            return
        value = value_lower
    elif option == "VIDEO_CONVERT_CODEC":
        # Validate codec selection for conversion
        allowed_codecs = {"copy", "auto", "x264", "x265"}
        value_lower = value.lower().strip()
        if value_lower not in allowed_codecs:
            await send_message(
                message,
                f"Invalid codec '{value}'. Please choose 'copy', 'auto', 'x264', or 'x265'.",
            )
            return
        value = value_lower
    elif option == "VIDEO_HARDSUB_STYLE":
        # Validate hardsub style selection
        allowed_styles = {
            "default",
            "bold",
            "outline",
            "shadow",
            "glow",
        }  # All supported styles
        value_lower = value.lower().strip()
        if value_lower not in allowed_styles:
            await send_message(
                message,
                f"Invalid hardsub style '{value}'. Please choose from: {', '.join(sorted(allowed_styles))}.",
            )
            return
        value = value_lower
    elif option == "VT_HARDSUB_STYLE":
        # Validate VT hardsub style selection
        allowed_styles = {
            "default",
            "bold",
            "outline",
            "shadow",
            "glow",
        }  # All supported styles
        value_lower = value.lower().strip()
        if value_lower not in allowed_styles:
            await send_message(
                message,
                f"Invalid hardsub style '{value}'. Please choose from: {', '.join(sorted(allowed_styles))}.",
            )
            return
        value = value_lower

    update_user_ldata(user_id, option, value)

    # If setting watermark text, also generate a PNG preview and store path for user
    if option == "VT_WATERMARK_TEXT" and value:
        try:
            wm_dir = os.path.join(os.getcwd(), "thumbnails", "watermark")
            await makedirs(wm_dir, exist_ok=True)
            out_path = os.path.join(wm_dir, f"{user_id}.png")
            from ..helper.ext_utils.media_utils import draw_transparent_image
        except Exception:
            from bot.helper.ext_utils.media_utils import draw_transparent_image

            wm_dir = os.path.join(os.getcwd(), "thumbnails", "watermark")
            await makedirs(wm_dir, exist_ok=True)
            out_path = os.path.join(wm_dir, f"{user_id}.png")
        try:
            await sync_to_async(draw_transparent_image, value.strip(), out_path)
            update_user_ldata(user_id, "VT_WATERMARK_IMAGE", out_path)
        except Exception:
            pass

    await delete_message(message)
    await rfunc()
    await database.update_user_data(user_id)


async def get_menu(query, option):
    user_id = query.from_user.id
    message = query.message
    handler_dict[user_id] = False
    user_dict = user_data.get(user_id, {})
    buttons = ButtonMaker()
    file_options = [
        "THUMBNAIL",
        "RCLONE_CONFIG",
        "TOKEN_PICKLE",
        "YTDLP_COOKIES",
        "VT_WATERMARK_IMAGE",
        "INTRO_SUBTITLE_FONT_PATH",
        "VT_WM_FONT_PATH",
        "VT_HARDSUB_FONT_PATH",
    ]
    dict_options = ["YT_DLP_OPTIONS", "FFMPEG_CMDS", "UPLOAD_PATHS"]
    file_dict = {
        "THUMBNAIL": f"thumbnails/{user_id}.jpg",
        "RCLONE_CONFIG": f"rclone/{user_id}.conf",
        "TOKEN_PICKLE": f"tokens/{user_id}.pickle",
        "YTDLP_COOKIES": f"cookies/{user_id}/cookies.txt",
        "VT_WATERMARK_IMAGE": f"thumbnails/watermark/{user_id}.png",
        "INTRO_SUBTITLE_FONT_PATH": f"fonts/{user_id}.ttf",
        "VT_WM_FONT_PATH": f"fonts/wm_{user_id}.ttf",
        "VT_HARDSUB_FONT_PATH": f"fonts/hardsub_{user_id}.ttf",
    }

    key = "file" if option in file_options else "set"
    if option in ["GEN_METADATA", "VID_METADATA", "AUD_METADATA", "SUB_METADATA"]:
        current_val = user_dict.get("METADATA_SETTINGS", {}).get(option)
    else:
        current_val = user_dict.get(option)

    if key == "file":
        if await aiopath.exists(file_dict.get(option, "")):
            buttons.data_button("Change", f"userset {user_id} {key} {option}")
        else:
            buttons.data_button("Set", f"userset {user_id} {key} {option}")
    else:
        buttons.data_button(
            "Change" if current_val else "Set", f"userset {user_id} {key} {option}"
        )

    if current_val:
        if option in dict_options:
            buttons.data_button(
                "Add Option", f"userset {user_id} addone {option}", "header"
            )
            buttons.data_button(
                "Remove Option", f"userset {user_id} rmone {option}", "header"
            )
        if key == "set":
            buttons.data_button("Reset", f"userset {user_id} reset {option}")

    if key == "file" and await aiopath.exists(file_dict.get(option, "")):
        buttons.data_button("Remove", f"userset {user_id} remove {option}")

    back_stype = "main"
    if option in leech_options:
        back_stype = "leech"
    elif option in common_tools_options:
        back_stype = "common_tools"
    elif option in rclone_options:
        back_stype = "rclone"
    elif option in gdrive_options:
        back_stype = "gdrive"
    elif option in gofile_options:
        back_stype = "gofile"
    elif option in yt_options:
        back_stype = "yttools"
    elif option in ffset_options or option in [
        "GEN_METADATA",
        "VID_METADATA",
        "AUD_METADATA",
        "SUB_METADATA",
    ]:
        back_stype = "ffset"
    elif option in vt_options:
        back_stype = "vtset"

    buttons.data_button("❮❮", f"userset {user_id} back {back_stype}", position="footer")
    buttons.data_button("✘", f"userset {user_id} close", position="footer")

    val = current_val
    if option in file_dict and (val or await aiopath.exists(file_dict.get(option, ""))):
        val = "Set"
    elif option == "LEECH_SPLIT_SIZE" and val:
        val = get_readable_file_size(val)

    text = f"<u>Option Settings: {option}</u>\n\n"
    option_settings = [
        f"Value: <b>{escape(str(val)) if val else 'Not Set'}</b>",
        f"Input Type: <b>{user_settings_text[option][0]}</b>",
        f"Description: <b>{user_settings_text[option][1]}</b>",
    ]

    if option_settings:
        text += f"╭ {option_settings[0]}\n"
        for item in option_settings[1:-1]:
            text += f"├ {item}\n"
        if len(option_settings) > 1:
            text += f"╰ {option_settings[-1]}\n"

    # FIX: Removed the prompt from the menu screen. It will now only appear after clicking Set/Change.
    await edit_message(message, text, buttons.build_menu(2))


async def get_caption_font_menu(query):
    user_id = query.from_user.id
    message = query.message
    handler_dict[user_id] = False
    user_dict = user_data.get(user_id, {})
    buttons = ButtonMaker()
    current_font = user_dict.get("LEECH_CAPTION_FONT", Config.LEECH_CAPTION_FONT)

    font_options = ["normal", "bold", "italic", "mono"]
    for font in font_options:
        prefix = "✅ " if current_font == font else ""
        buttons.data_button(
            f"{prefix}{font.title()}", f"userset {user_id} set_font {font}"
        )

    buttons.data_button("❮❮", f"userset {user_id} back leech", position="footer")
    buttons.data_button("✘", f"userset {user_id} close", position="footer")

    text = (
        f"<u>Caption Font Settings for {query.from_user.mention(style='html')}</u>\n\n"
        f"Select a font style for the filename in the caption. This applies if you use "
        f"<code>{{filename}}</code> in your custom caption or if no custom caption is set.\n\n"
        f"╭ Current Font: <b>{current_font.title()}</b>"
    )
    await edit_message(message, text, buttons.build_menu(2))


async def get_upload_service_menu(query):
    user_id = query.from_user.id
    message = query.message
    handler_dict[user_id] = False
    user_dict = user_data.get(user_id, {})
    buttons = ButtonMaker()
    current_service = user_dict.get(
        "DEFAULT_UPLOAD_SERVICE", Config.DEFAULT_UPLOAD_SERVICE
    )
    service_options = {
        "gd": "GDrive",
        "rc": "Rclone",
        "yt": "YouTube",
        "gofile": "GoFile",
    }

    for service_key, service_name in service_options.items():
        prefix = "✅ " if current_service == service_key else ""
        buttons.data_button(
            f"{prefix}{service_name}", f"userset {user_id} set_dus {service_key}"
        )

    buttons.data_button("❮❮", f"userset {user_id} back main", position="footer")
    buttons.data_button("✘", f"userset {user_id} close", position="footer")

    text = (
        f"<u>Default Upload Service for {query.from_user.mention(style='html')}</u>\n\n"
        f"Choose your preferred default upload destination when no specific uploader is selected in the command.\n\n"
        f"╭ Current Default: <b>{service_options.get(current_service, current_service).upper()}</b>"
    )
    await edit_message(message, text, buttons.build_menu(1))


async def event_handler(client, query, pfunc, rfunc, photo=False, document=False):
    user_id = query.from_user.id
    handler_dict[user_id] = True
    start_time = time()

    async def event_filter(_, __, event):
        user = event.from_user or event.sender_chat
        if user.id != user_id or event.chat.id != query.message.chat.id:
            return False
        if photo and document:
            return bool(
                event.photo or event.document or event.animation or event.sticker
            )
        elif photo:
            return bool(event.photo)
        elif document:
            return bool(event.document)
        else:
            return bool(event.text)

    handler = client.add_handler(
        MessageHandler(pfunc, filters=create(event_filter)), group=-1
    )

    while handler_dict.get(user_id):
        await sleep(0.5)
        if time() - start_time > 60:
            handler_dict[user_id] = False
            if rfunc:
                await rfunc()
    client.remove_handler(*handler)


@new_task
async def edit_user_settings(client, query):
    from_user = query.from_user
    user_id = from_user.id
    message = query.message
    data = query.data.split()
    user_dict = user_data.get(user_id, {})
    reply_to = message.reply_to_message

    if user_id != int(data[1]):
        return await query.answer("Not Yours!", show_alert=True)

    try:
        await query.answer()
    except Exception:
        pass

    action = data[2]

    if action in [
        "main",
        "leech",
        "common_tools",
        "thumbnail",
        "general",
        "rclone",
        "gdrive",
        "gofile",
        "ffset",
        "advanced",
        "yttools",
        "autorename",
        "ssgrid",
        "vt_samplevideo",
        "vt_encoding",
        "vt_hardsub",
        "auto_process",
        "vtset",
        "zipmode",
        "dumps",
    ]:
        msg, button = await get_user_settings(from_user, action)
        await edit_message(message, msg, button)

    elif action == "samplevideo":
        # Redirect legacy samplevideo to vt_samplevideo
        msg, button = await get_user_settings(from_user, "vt_samplevideo")
        await edit_message(message, msg, button)

    elif action == "set_rename_type":
        rename_type = data[3]
        if rename_type in ["auto", "manual"]:
            update_user_ldata(user_id, "AUTO_RENAME_TYPE", rename_type)
            await database.update_user_data(user_id)
        msg, button = await get_user_settings(from_user, "autorename")
        await edit_message(message, msg, button)

    elif action == "attachments_menu":
        msg, button = await get_user_settings(from_user, "attachments_menu")
        photo_to_send = user_dict.get("USER_ATTACHMENT_PHOTO")
        if not photo_to_send or not await aiopath.exists(photo_to_send):
            thumb_path = f"thumbnails/{user_id}.jpg"
            if await aiopath.exists(thumb_path):
                photo_to_send = thumb_path
            else:
                photo_to_send = getattr(Config, "IMAGE_USETIINGS", None)

        await delete_message(message)
        if photo_to_send:
            res = await send_message(
                reply_to or message,
                msg,
                button,
                photo=photo_to_send,
                reply_to_message_id=reply_to.id if reply_to else None,
            )
            if isinstance(res, str):
                LOGGER.error(f"Failed to send user settings with photo: {res}")
                await send_message(reply_to or message, msg, button)
        else:
            await send_message(reply_to or message, msg, button)

    elif action == "back_photo":
        stype = data[3]
        msg, button = await get_user_settings(from_user, stype)
        photo_to_send = f"thumbnails/{user_id}.jpg"
        if not await aiopath.exists(photo_to_send):
            photo_to_send = getattr(Config, "IMAGE_USETIINGS", None)

        await delete_message(message)
        if photo_to_send:
            res = await send_message(
                reply_to or message,
                msg,
                button,
                photo=photo_to_send,
                reply_to_message_id=reply_to.id if reply_to else None,
            )
            if isinstance(res, str):
                LOGGER.error(f"Failed to send user settings with photo: {res}")
                await send_message(reply_to or message, msg, button)
        else:
            await send_message(reply_to or message, msg, button)

    elif action == "back":
        stype = data[3] if len(data) > 3 else "main"
        msg, button = await get_user_settings(from_user, stype)
        await edit_message(message, msg, button)

    elif action == "ffsubmenu":
        await safe_query_answer(query)
        submenu_type = data[3]  # encode, convert, watermark, or intro

        if submenu_type == "encode":
            # Show encode settings submenu
            buttons = ButtonMaker()
            video_encode_enabled = user_dict.get("VIDEO_ENCODE_ENABLED", False)

            # Video encode toggle
            buttons.data_button(
                f"{'✓ ' if video_encode_enabled else ''}Video Encode",
                f"userset {user_id} tog VIDEO_ENCODE_ENABLED {'f' if video_encode_enabled else 't'} encode",
            )

            if video_encode_enabled:
                # Encode settings only show when encoding is enabled
                default_codec = "x264"
                current_codec = user_dict.get("VIDEO_ENCODE_CODEC", default_codec)
                has_custom_codec = current_codec != default_codec
                buttons.data_button(
                    f"{'✓ ' if has_custom_codec else ''}Codec",
                    f"userset {user_id} codec {user_id}",
                )

                default_preset = "medium"
                current_preset = user_dict.get("VIDEO_ENCODE_PRESET", default_preset)
                has_custom_preset = current_preset != default_preset
                buttons.data_button(
                    f"{'✓ ' if has_custom_preset else ''}Preset",
                    f"userset {user_id} preset {user_id}",
                )

                default_quality = "Original"
                current_quality = user_dict.get("VIDEO_ENCODE_QUALITY", default_quality)
                has_custom_quality = current_quality != default_quality
                buttons.data_button(
                    f"{'✓ ' if has_custom_quality else ''}Quality",
                    f"userset {user_id} quality {user_id}",
                )

                default_crf = 23
                current_crf = user_dict.get("VIDEO_ENCODE_CRF", default_crf)
                has_custom_crf = current_crf != default_crf
                buttons.data_button(
                    f"{'✓ ' if has_custom_crf else ''}CRF",
                    f"userset {user_id} crf {user_id}",
                )

                default_bitrate = "128k"
                current_bitrate = user_dict.get(
                    "VIDEO_ENCODE_AUDIO_BITRATE", default_bitrate
                )
                has_custom_bitrate = current_bitrate != default_bitrate
                buttons.data_button(
                    f"{'✓ ' if has_custom_bitrate else ''}Audio Bitrate",
                    f"userset {user_id} menu VIDEO_ENCODE_AUDIO_BITRATE",
                )

                # Multi-resolution settings
                multi_res_enabled = user_dict.get(
                    "VIDEO_ENCODE_MULTI_RESOLUTION", False
                )
                buttons.data_button(
                    f"{'✓ ' if multi_res_enabled else ''}Multi-Res",
                    f"userset {user_id} tog VIDEO_ENCODE_MULTI_RESOLUTION {'f' if multi_res_enabled else 't'} encode",
                )

                if multi_res_enabled:
                    has_custom_resolutions = bool(
                        user_dict.get("VIDEO_ENCODE_RESOLUTION_LIST", "")
                    )
                    buttons.data_button(
                        f"{'✓ ' if has_custom_resolutions else ''}Resolutions",
                        f"userset {user_id} menu VIDEO_ENCODE_RESOLUTION_LIST",
                    )

                    multi_zip_enabled = user_dict.get("VIDEO_ENCODE_MULTI_ZIP", False)
                    buttons.data_button(
                        f"{'✓ ' if multi_zip_enabled else ''}Multi-Zip",
                        f"userset {user_id} tog VIDEO_ENCODE_MULTI_ZIP {'f' if multi_zip_enabled else 't'} encode",
                    )

            buttons.data_button("Back", f"userset {user_id} back ffset", "footer")
            buttons.data_button("Close", f"userset {user_id} close", "footer")
            btns = buttons.build_menu(2)

            encode_status = "Enabled" if video_encode_enabled else "Disabled"
            codec = user_dict.get("VIDEO_ENCODE_CODEC", "x264")
            preset = user_dict.get("VIDEO_ENCODE_PRESET", "medium")
            quality = user_dict.get("VIDEO_ENCODE_QUALITY", "Original")
            crf = user_dict.get("VIDEO_ENCODE_CRF", 23)
            bitrate = user_dict.get("VIDEO_ENCODE_AUDIO_BITRATE", "128k")

            # Multi-resolution settings for display
            multi_res_enabled = user_dict.get("VIDEO_ENCODE_MULTI_RESOLUTION", False)
            multi_res_status = "Enabled" if multi_res_enabled else "Disabled"

            resolution_list = user_dict.get("VIDEO_ENCODE_RESOLUTION_LIST", "")
            if resolution_list:
                resolutions_display = resolution_list
            else:
                resolutions_display = "All Available"

            multi_zip_enabled = user_dict.get("VIDEO_ENCODE_MULTI_ZIP", False)
            multi_zip_status = "Enabled" if multi_zip_enabled else "Disabled"

            text = f"""📹 <b>Encode Settings</b>
╭<b>Video Encode</b> » <b>{encode_status}</b>
┊<b>Codec</b> » <b>{codec}</b>
┊<b>Preset</b> » <b>{preset}</b>
┊<b>Quality</b> » <b>{quality}</b>
┊<b>CRF</b> » <b>{crf}</b>
┊<b>Audio Bitrate</b> » <b>{bitrate}</b>
┊<b>Multi-Res</b> » <b>{multi_res_status}</b>
┊<b>Resolutions</b> » <b>{resolutions_display}</b>
╰<b>Multi-Zip</b> » <b>{multi_zip_status}</b>"""
            await edit_message(message, text, btns)

        elif submenu_type == "convert":
            # Show convert settings submenu
            buttons = ButtonMaker()
            video_convert_enabled = user_dict.get("VIDEO_CONVERT_ENABLED", False)

            # Video convert toggle
            buttons.data_button(
                f"{'✓ ' if video_convert_enabled else ''}Video Convert",
                f"userset {user_id} tog VIDEO_CONVERT_ENABLED {'f' if video_convert_enabled else 't'} convert",
            )

            if video_convert_enabled:
                # Convert settings only show when conversion is enabled
                default_format = "mp4"
                current_format = user_dict.get("VIDEO_CONVERT_FORMAT", default_format)
                has_custom_format = current_format != default_format
                buttons.data_button(
                    f"{'✓ ' if has_custom_format else ''}Format",
                    f"userset {user_id} convertformat {user_id}",
                )

                default_codec = "copy"
                current_codec = user_dict.get("VIDEO_CONVERT_CODEC", default_codec)
                has_custom_codec = current_codec != default_codec
                buttons.data_button(
                    f"{'✓ ' if has_custom_codec else ''}Codec",
                    f"userset {user_id} convertcodec {user_id}",
                )

                default_quality = "original"
                current_quality = user_dict.get(
                    "VIDEO_CONVERT_QUALITY", default_quality
                )
                has_custom_quality = current_quality != default_quality
                buttons.data_button(
                    f"{'✓ ' if has_custom_quality else ''}Quality",
                    f"userset {user_id} convertquality {user_id}",
                )

            buttons.data_button("Back", f"userset {user_id} back ffset", "footer")
            buttons.data_button("Close", f"userset {user_id} close", "footer")
            btns = buttons.build_menu(2)

            convert_status = "Enabled" if video_convert_enabled else "Disabled"
            format_display = user_dict.get("VIDEO_CONVERT_FORMAT", "mp4")
            codec_display = user_dict.get("VIDEO_CONVERT_CODEC", "copy")
            quality_display = user_dict.get("VIDEO_CONVERT_QUALITY", "original")

            text = f"""🔄 <b>Convert Settings</b>
╭<b>Video Convert</b> » <b>{convert_status}</b>
┊<b>Format</b> » <b>{format_display.upper()}</b>
┊<b>Codec</b> » <b>{codec_display}</b>
╰<b>Quality</b> » <b>{quality_display}</b>"""
            await edit_message(message, text, btns)

        elif submenu_type == "watermark":
            # Show watermark settings submenu
            from bot.helper.telegram_helper.ffmpeg_button_build import FFmpegButtonMaker

            buttons = FFmpegButtonMaker()
            watermark_enabled = user_dict.get("VIDEO_WATERMARK_ENABLED", False)

            # Watermark toggle
            buttons.data_button(
                f"{'✓ ' if watermark_enabled else ''}Watermark",
                f"userset {user_id} tog VIDEO_WATERMARK_ENABLED {'f' if watermark_enabled else 't'} watermark",
            )

            if watermark_enabled:
                # Watermark settings only show when enabled
                default_wm_text = "Default Watermark"
                current_wm_text = user_dict.get("VIDEO_WATERMARK_TEXT", default_wm_text)
                has_custom_wm_text = current_wm_text != default_wm_text
                buttons.data_button(
                    f"{'✓ ' if has_custom_wm_text else ''}Set Text",
                    f"userset {user_id} menu VIDEO_WATERMARK_TEXT",
                )

                default_wm_type = "text"
                current_wm_type = user_dict.get("VIDEO_WATERMARK_TYPE", default_wm_type)
                has_custom_wm_type = current_wm_type != default_wm_type
                buttons.data_button(
                    f"{'✓ ' if has_custom_wm_type else ''}WM-Type",
                    f"userset {user_id} wmtype {user_id}",
                )

                has_wm_image = bool(user_dict.get("VIDEO_WATERMARK_IMAGE_PATH", ""))
                buttons.data_button(
                    f"{'✓ ' if has_wm_image else ''}Set Image",
                    f"userset {user_id} file VIDEO_WATERMARK_IMAGE_PATH",
                )

                default_position = "bottom-right"
                current_position = user_dict.get(
                    "VIDEO_WATERMARK_POSITION", default_position
                )
                has_custom_position = current_position != default_position
                buttons.data_button(
                    f"{'✓ ' if has_custom_position else ''}Position",
                    f"userset {user_id} wmposition {user_id}",
                )

                default_opacity = 0.5
                current_opacity = user_dict.get(
                    "VIDEO_WATERMARK_OPACITY", default_opacity
                )
                has_custom_opacity = current_opacity != default_opacity
                buttons.data_button(
                    f"{'✓ ' if has_custom_opacity else ''}Opacity",
                    f"userset {user_id} wmopacity {user_id}",
                )

                text_bg_enabled = user_dict.get(
                    "VIDEO_WATERMARK_TEXT_BACKGROUND", False
                )
                buttons.data_button(
                    f"{'✓ ' if text_bg_enabled else ''}Text-BG",
                    f"userset {user_id} tog VIDEO_WATERMARK_TEXT_BACKGROUND {'f' if text_bg_enabled else 't'}",
                )

                has_custom_font = bool(user_dict.get("VIDEO_WATERMARK_FONT_PATH", ""))
                buttons.data_button(
                    f"{'✓ ' if has_custom_font else ''}Custom-Font",
                    f"userset {user_id} file VIDEO_WATERMARK_FONT_PATH",
                )

                default_font_size = 24
                current_font_size = user_dict.get(
                    "VIDEO_WATERMARK_FONT_SIZE", default_font_size
                )
                has_custom_font_size = current_font_size != default_font_size
                buttons.data_button(
                    f"{'✓ ' if has_custom_font_size else ''}Size",
                    f"userset {user_id} menu VIDEO_WATERMARK_FONT_SIZE",
                )

                default_font_color = "white"
                current_font_color = user_dict.get(
                    "VIDEO_WATERMARK_FONT_COLOR", default_font_color
                )
                has_custom_font_color = current_font_color != default_font_color
                buttons.data_button(
                    f"{'✓ ' if has_custom_font_color else ''}Colour",
                    f"userset {user_id} menu VIDEO_WATERMARK_FONT_COLOR",
                )

                default_duration_type = "all"
                current_duration_type = user_dict.get(
                    "VIDEO_WATERMARK_DURATION_TYPE", default_duration_type
                )
                has_custom_duration_type = (
                    current_duration_type != default_duration_type
                )
                buttons.data_button(
                    f"{'✓ ' if has_custom_duration_type else ''}WM-Duration",
                    f"userset {user_id} wmduration {user_id}",
                )

            # Back button
            buttons.data_button("Back", f"userset {user_id} ffset", "footer")
            buttons.data_button("Close", f"userset {user_id} close", "footer")

            btns = buttons.build_menu(2)

            # Build status text
            wm_status = "✓ Enabled" if watermark_enabled else "✗ Disabled"
            text = f"""🎭 <b>Watermark Settings</b>

╭ <b>Status:</b> {wm_status}"""

            if watermark_enabled:
                wm_text = user_dict.get("VIDEO_WATERMARK_TEXT", "Default Watermark")
                wm_type = user_dict.get("VIDEO_WATERMARK_TYPE", "text")
                wm_position = user_dict.get("VIDEO_WATERMARK_POSITION", "bottom-right")
                wm_opacity = user_dict.get("VIDEO_WATERMARK_OPACITY", 0.5)
                wm_font_size = user_dict.get("VIDEO_WATERMARK_FONT_SIZE", 24)
                wm_font_color = user_dict.get("VIDEO_WATERMARK_FONT_COLOR", "white")
                text_bg = (
                    "Enabled"
                    if user_dict.get("VIDEO_WATERMARK_TEXT_BACKGROUND", False)
                    else "Disabled"
                )
                has_image = (
                    "Set"
                    if user_dict.get("VIDEO_WATERMARK_IMAGE_PATH", "")
                    else "Not Set"
                )
                has_font = (
                    "Set"
                    if user_dict.get("VIDEO_WATERMARK_FONT_PATH", "")
                    else "Default"
                )

                text += f"""
┊ <b>Text:</b> {escape(wm_text[:30] + "..." if len(wm_text) > 30 else wm_text)}
┊ <b>Type:</b> {wm_type}
┊ <b>Image:</b> {has_image}
┊ <b>Position:</b> {wm_position}
┊ <b>Opacity:</b> {int(wm_opacity * 100)}%
┊ <b>Font Size:</b> {wm_font_size}
┊ <b>Font Color:</b> {wm_font_color}
┊ <b>Text Background:</b> {text_bg}
╰ <b>Custom Font:</b> {has_font}"""

            await edit_message(message, text, btns)
        else:
            # Fallback for other submenus that aren't implemented yet
            await send_message(
                reply_to or message, f"Submenu '{submenu_type}' not implemented yet."
            )

    elif action == "vtsubmenu":
        await safe_query_answer(query)
        submenu_type = data[3]  # watermark or other future submenus

        if submenu_type == "watermark":
            # Show VT watermark settings submenu (using VIDEO_WATERMARK settings for functionality)
            buttons = ButtonMaker()
            watermark_enabled = user_dict.get("VIDEO_WATERMARK_ENABLED", False)

            # Main watermark enable/disable toggle (use VIDEO_WATERMARK_ENABLED for actual functionality)
            buttons.data_button(
                f"{'✓ ' if watermark_enabled else ''}Enable Watermark",
                f"userset {user_id} tog VIDEO_WATERMARK_ENABLED {'f' if watermark_enabled else 't'} vt_watermark",
            )

            if watermark_enabled:
                # Watermark settings only show when enabled (use VIDEO_WATERMARK settings)

                # Text watermark settings
                default_wm_text = "Default Watermark"
                current_wm_text = user_dict.get("VIDEO_WATERMARK_TEXT", default_wm_text)
                has_custom_wm_text = current_wm_text != default_wm_text
                buttons.data_button(
                    f"{'✓ ' if has_custom_wm_text else ''}Set Text",
                    f"userset {user_id} menu VIDEO_WATERMARK_TEXT",
                )

                # Watermark type selection (text/image)
                default_wm_type = "text"
                current_wm_type = user_dict.get("VIDEO_WATERMARK_TYPE", default_wm_type)
                has_custom_wm_type = current_wm_type != default_wm_type
                buttons.data_button(
                    f"{'✓ ' if has_custom_wm_type else ''}WM-Type",
                    f"userset {user_id} wmtype {user_id}",
                )

                # Image watermark
                has_wm_image = bool(user_dict.get("VIDEO_WATERMARK_IMAGE_PATH", ""))
                buttons.data_button(
                    f"{'✓ ' if has_wm_image else ''}Set Image",
                    f"userset {user_id} file VIDEO_WATERMARK_IMAGE_PATH",
                )

                # Position settings
                default_position = "bottom-right"
                current_position = user_dict.get(
                    "VIDEO_WATERMARK_POSITION", default_position
                )
                has_custom_position = current_position != default_position
                buttons.data_button(
                    f"{'✓ ' if has_custom_position else ''}Position",
                    f"userset {user_id} wmposition {user_id}",
                )

                # Opacity settings
                default_opacity = 0.5
                current_opacity = user_dict.get(
                    "VIDEO_WATERMARK_OPACITY", default_opacity
                )
                has_custom_opacity = current_opacity != default_opacity
                buttons.data_button(
                    f"{'✓ ' if has_custom_opacity else ''}Opacity",
                    f"userset {user_id} wmopacity {user_id}",
                )

                # Font settings
                default_font_size = 24
                current_font_size = user_dict.get(
                    "VIDEO_WATERMARK_FONT_SIZE", default_font_size
                )
                has_custom_font_size = current_font_size != default_font_size
                buttons.data_button(
                    f"{'✓ ' if has_custom_font_size else ''}Font Size",
                    f"userset {user_id} menu VIDEO_WATERMARK_FONT_SIZE",
                )

                # Font color
                default_font_color = "white"
                current_font_color = user_dict.get(
                    "VIDEO_WATERMARK_FONT_COLOR", default_font_color
                )
                has_custom_font_color = current_font_color != default_font_color
                buttons.data_button(
                    f"{'✓ ' if has_custom_font_color else ''}Font Color",
                    f"userset {user_id} menu VIDEO_WATERMARK_FONT_COLOR",
                )

                # Text background
                has_text_bg = bool(user_dict.get("VIDEO_WATERMARK_TEXT_BACKGROUND", ""))
                buttons.data_button(
                    f"{'✓ ' if has_text_bg else ''}Text Background",
                    f"userset {user_id} tog VIDEO_WATERMARK_TEXT_BACKGROUND {'f' if has_text_bg else 't'}",
                )

                # Duration settings
                default_duration_type = "full"
                current_duration_type = user_dict.get(
                    "VIDEO_WATERMARK_DURATION_TYPE", default_duration_type
                )
                has_custom_duration_type = (
                    current_duration_type != default_duration_type
                )
                buttons.data_button(
                    f"{'✓ ' if has_custom_duration_type else ''}Duration Type",
                    f"userset {user_id} menu VIDEO_WATERMARK_DURATION_TYPE",
                )

                if current_duration_type == "seconds":
                    default_duration_seconds = 60
                    current_duration_seconds = user_dict.get(
                        "VIDEO_WATERMARK_DURATION_SECONDS", default_duration_seconds
                    )
                    has_custom_seconds = (
                        current_duration_seconds != default_duration_seconds
                    )
                    buttons.data_button(
                        f"{'✓ ' if has_custom_seconds else ''}WM-Seconds",
                        f"userset {user_id} menu VIDEO_WATERMARK_DURATION_SECONDS",
                    )

            buttons.data_button("Back", f"userset {user_id} back vtset", "footer")
            buttons.data_button("Close", f"userset {user_id} close", "footer")
            btns = buttons.build_menu(2)

            watermark_status = "Enabled" if watermark_enabled else "Disabled"
            wm_text = user_dict.get("VIDEO_WATERMARK_TEXT", "Default Watermark")
            wm_type = user_dict.get("VIDEO_WATERMARK_TYPE", "text")
            wm_position = user_dict.get("VIDEO_WATERMARK_POSITION", "bottom-right")
            wm_opacity = user_dict.get("VIDEO_WATERMARK_OPACITY", 0.5)

            text = f"""🌊 <b>VT Watermark Settings</b>
╭<b>Watermark</b> » <b>{watermark_status}</b>
├<b>Text</b> » <code>{escape(str(wm_text))}</code>
├<b>Type</b> » <b>{wm_type.title()}</b>
├<b>Position</b> » <b>{wm_position}</b>
╰<b>Opacity</b> » <b>{wm_opacity}</b>

<i>💡 Enhanced watermark settings for Video Tools section. Configure text/image watermarks with position, opacity, and timing options.</i>"""

            await edit_message(message, text, btns)
        else:
            # Fallback for other vtsubmenus that aren't implemented yet
            await send_message(
                reply_to or message, f"VT Submenu '{submenu_type}' not implemented yet."
            )

    elif action == "upload_service_menu":
        await get_upload_service_menu(query)
    elif action == "set_dus":
        service = data[3]
        if service in ["gd", "rc", "yt", "gofile"]:
            update_user_ldata(user_id, "DEFAULT_UPLOAD_SERVICE", service)
            await database.update_user_data(user_id)
        await get_upload_service_menu(query)
    elif action == "caption_font_menu":
        await get_caption_font_menu(query)
    elif action == "set_font":
        font = data[3]
        if font in ["normal", "bold", "italic", "mono"]:
            update_user_ldata(user_id, "LEECH_CAPTION_FONT", font)
            await database.update_user_data(user_id)
        await get_caption_font_menu(query)
    elif action == "set_fs":
        source = data[3]
        if source in ["filename", "caption"]:
            update_user_ldata(user_id, "FILENAME_SOURCE", source)
            await database.update_user_data(user_id)
        msg, button = await get_user_settings(from_user, "leech")
        await edit_message(message, msg, button)

    elif action == "wmtype":
        await safe_query_answer(query)
        # Show watermark type selection submenu
        buttons = ButtonMaker()
        wm_type = user_dict.get("VIDEO_WATERMARK_TYPE", "text")

        type_options = [("text", "Text"), ("image", "Image")]

        for option, display_name in type_options:
            # Mark the current selected type with a checkmark
            button_text = f"✓ {display_name}" if wm_type == option else display_name
            buttons.data_button(button_text, f"userset {user_id} setwmtype {option}")

        buttons.data_button("Back", f"userset {user_id} ffsubmenu watermark", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(1)

        text = f"""〄 <b>Watermark Type :</b>
╭<b>Current Type</b> » <b>{wm_type}</b>
┊
┊<b>Text:</b> Use text overlay as watermark
╰<b>Image:</b> Use uploaded image as watermark
"""
        await edit_message(message, text, btns)

    elif action == "setwmtype":
        await safe_query_answer(query)
        option = data[3]
        if option in ["text", "image"]:
            update_user_ldata(user_id, "VIDEO_WATERMARK_TYPE", option)
            await database.update_user_data(user_id)
        # Go back to watermark submenu
        msg, button = await get_user_settings(from_user, "ffsubmenu")
        data[3] = "watermark"  # Set submenu type
        action = "ffsubmenu"
        # Re-call the ffsubmenu handler
        submenu_type = "watermark"
        from bot.helper.telegram_helper.ffmpeg_button_build import FFmpegButtonMaker

        buttons = FFmpegButtonMaker()
        watermark_enabled = user_dict.get("VIDEO_WATERMARK_ENABLED", False)
        # ... (repeat watermark submenu code here or call it as a function)
        # For now, redirect back to ffsubmenu watermark
        await edit_user_settings(client, query)
        return

    # Codec handler for encoding
    elif action == "codec":
        await query.answer()
        # Show codec selection submenu
        buttons = ButtonMaker()
        codec = user_dict.get("VIDEO_ENCODE_CODEC", "x264")
        # Available codec options
        codec_options = ["x264", "x265"]
        for option in codec_options:
            button_text = f"✓ {option}" if codec == option else option
            buttons.data_button(button_text, f"userset {user_id} setcodec {option}")
        buttons.data_button("Back", f"userset {user_id} ffsubmenu encode", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(2)
        text = f"""〄 <b>Video Encoding Codec :</b>
╭<b>Current Codec</b> » <b>{codec}</b>
┊
┊<b>x264 (H.264/AVC):</b>
┊• Faster encoding
┊• Better compatibility
┊• Larger file sizes
┊
┊<b>x265 (H.265/HEVC):</b>
┊• Better compression (~30-50% smaller files)
┊• Slower encoding (2-3x longer)
╰• Modern codec with excellent quality"""
        await edit_message(message, text, btns)

    elif action == "setcodec":
        await query.answer()
        option = data[3]
        # Validate against allowed codecs for safety
        allowed = {"x264", "x265"}
        if option not in allowed:
            await query.edit_message_text("Invalid codec!")
            await sleep(1)
        else:
            update_user_ldata(user_id, "VIDEO_ENCODE_CODEC", option)
            await database.update_user_data(user_id)
        # Go back to encode submenu
        data[2] = "ffsubmenu"
        data[3] = "encode"
        await edit_user_settings(client, query)
        return

    # Convert format handler
    elif action == "convertformat":
        await query.answer()
        # Show format selection submenu
        buttons = ButtonMaker()
        format_option = user_dict.get("VIDEO_CONVERT_FORMAT", "mp4")
        # Available format options
        format_options = ["mp4", "mkv", "avi", "mov", "webm", "flv", "m4v"]
        for option in format_options:
            button_text = (
                f"✓ {option.upper()}" if format_option == option else option.upper()
            )
            buttons.data_button(button_text, f"userset {user_id} setformat {option}")
        buttons.data_button("Back", f"userset {user_id} ffsubmenu convert", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(3)
        text = f"""🔄 <b>Video Convert Format :</b>
╭<b>Current Format</b> » <b>{format_option.upper()}</b>
┊
┊<b>Format Options:</b>
┊<b>MP4</b> » Most compatible, good quality
┊<b>MKV</b> » Best for multiple streams
┊<b>AVI</b> » Legacy format, wide support
┊<b>MOV</b> » Apple/QuickTime format
┊<b>WEBM</b> » Web-optimized, good compression
┊<b>FLV</b> » Flash video format
╰<b>M4V</b> » iTunes-compatible format"""
        await edit_message(message, text, btns)

    elif action == "setformat":
        await query.answer()
        option = data[3]
        # Validate against allowed formats for safety
        allowed = {"mp4", "mkv", "avi", "mov", "webm", "flv", "m4v"}
        if option not in allowed:
            await query.edit_message_text("Invalid format!")
            await sleep(1)
        else:
            update_user_ldata(user_id, "VIDEO_CONVERT_FORMAT", option)
            await database.update_user_data(user_id)
        # Go back to convert submenu
        data[2] = "ffsubmenu"
        data[3] = "convert"
        await edit_user_settings(client, query)
        return

    # Convert codec handler
    elif action == "convertcodec":
        await query.answer()
        # Show the Convert Codec submenu
        buttons = ButtonMaker()
        codec_option = user_dict.get("VIDEO_CONVERT_CODEC", "copy")
        # Available codec options for conversion
        codec_options = ["copy", "x264", "x265", "auto"]
        for option in codec_options:
            button_text = f"✓ {option}" if codec_option == option else option
            buttons.data_button(
                button_text, f"userset {user_id} setconvertcodec {option}"
            )
        buttons.data_button("Back", f"userset {user_id} ffsubmenu convert", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(2)
        text = f"""🎬 <b>Video Convert Codec :</b>
╭<b>Current Codec</b> » <b>{codec_option}</b>
┊
┊<b>Available Options:</b>
┊<b>copy</b> » Keep original codec (fastest, no quality loss)
┊<b>x264</b> » Re-encode with H.264 (compatibility)
┊<b>x265</b> » Re-encode with H.265 (compression)
╰<b>auto</b> » Smart selection based on format"""
        await edit_message(message, text, btns)

    elif action == "setconvertcodec":
        await query.answer()
        option = data[3]
        # Validate against allowed codecs for safety
        allowed = {"copy", "x264", "x265", "auto"}
        if option not in allowed:
            await query.edit_message_text("Invalid codec!")
            await sleep(1)
        else:
            update_user_ldata(user_id, "VIDEO_CONVERT_CODEC", option)
            await database.update_user_data(user_id)
        # Go back to convert submenu
        data[2] = "ffsubmenu"
        data[3] = "convert"
        await edit_user_settings(client, query)
        return

    # Convert quality handler
    elif action == "convertquality":
        await query.answer()
        # Show quality selection submenu
        buttons = ButtonMaker()
        quality_option = user_dict.get("VIDEO_CONVERT_QUALITY", "original")
        # Available quality options
        quality_options = ["original", "high", "medium", "low"]
        for option in quality_options:
            button_text = f"✓ {option}" if quality_option == option else option
            buttons.data_button(
                button_text, f"userset {user_id} setconvertquality {option}"
            )
        buttons.data_button("Back", f"userset {user_id} ffsubmenu convert", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(2)
        text = f"""⭐ <b>Video Convert Quality :</b>
╭<b>Current Quality</b> » <b>{quality_option}</b>
┊
┊<b>Quality Options:</b>
┊<b>original</b> » Keep original quality (no scaling)
┊<b>high</b> » High quality output (recommended)
┊<b>medium</b> » Balanced quality and size
╰<b>low</b> » Lower quality, smaller file size"""
        await edit_message(message, text, btns)

    elif action == "setconvertquality":
        await safe_query_answer(query)
        option = data[3]
        # Validate against allowed quality options for safety
        allowed = {"original", "high", "medium", "low"}
        if option not in allowed:
            await query.edit_message_text("Invalid quality!")
            await sleep(1)
        else:
            update_user_ldata(user_id, "VIDEO_CONVERT_QUALITY", option)
            await database.update_user_data(user_id)
        # Go back to convert submenu
        data[2] = "ffsubmenu"
        data[3] = "convert"
        await edit_user_settings(client, query)
        return

    elif action == "wmposition":
        await query.answer()
        # Show watermark position selection submenu
        buttons = ButtonMaker()
        position = user_dict.get("VIDEO_WATERMARK_POSITION", "bottom-right")

        position_options = [
            ("top-left", "Top Left"),
            ("top-right", "Top Right"),
            ("bottom-left", "Bottom Left"),
            ("bottom-right", "Bottom Right"),
            ("center", "Center"),
        ]

        for option, display_name in position_options:
            button_text = f"✓ {display_name}" if position == option else display_name
            buttons.data_button(button_text, f"userset {user_id} setwmpos {option}")

        buttons.data_button("Back", f"userset {user_id} ffsubmenu watermark", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(2)

        text = f"""〄 <b>Watermark Position :</b>
╭<b>Current Position</b> » <b>{position}</b>
┊
┊Choose where to place the watermark:
┊• <b>Top Left/Right</b> - Upper corners
┊• <b>Bottom Left/Right</b> - Lower corners
╰• <b>Center</b> - Center of video
"""
        await edit_message(message, text, btns)

    elif action == "setwmpos":
        await query.answer()
        option = data[3]
        position_map = {
            "top-left": "top-left",
            "top-right": "top-right",
            "bottom-left": "bottom-left",
            "bottom-right": "bottom-right",
            "center": "center",
        }
        if option in position_map:
            update_user_ldata(user_id, "VIDEO_WATERMARK_POSITION", position_map[option])
            await database.update_user_data(user_id)
        # Go back to watermark submenu by triggering ffsubmenu watermark
        data[2] = "ffsubmenu"
        data[3] = "watermark"
        await edit_user_settings(client, query)
        return

    elif action == "wmopacity":
        await query.answer()
        # Show opacity selection submenu
        buttons = ButtonMaker()
        opacity = user_dict.get("VIDEO_WATERMARK_OPACITY", 0.5)

        opacity_options = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]

        for option in opacity_options:
            try:
                button_text = (
                    f"✓ {int(option * 100)}%"
                    if abs(opacity - option) < 0.01
                    else f"{int(option * 100)}%"
                )
            except (ValueError, TypeError):
                button_text = f"{int(option * 100)}%"
            buttons.data_button(button_text, f"userset {user_id} setwmopacity {option}")

        buttons.data_button("Back", f"userset {user_id} ffsubmenu watermark", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(4)

        # Safely calculate opacity percentage
        try:
            opacity_percent = int(opacity * 100) if opacity else 50
        except (ValueError, TypeError):
            opacity_percent = 50

        text = f"""〄 <b>Watermark Opacity :</b>
╭<b>Current Opacity</b> » <b>{opacity_percent}%</b>
┊
┊<b>Opacity levels:</b>
┊• <b>10-30%</b> - Very subtle
┊• <b>40-60%</b> - Balanced visibility
╰• <b>70-100%</b> - Highly visible
"""
        await edit_message(message, text, btns)

    elif action == "setwmopacity":
        await query.answer()
        try:
            option = float(data[3])
            if 0.0 <= option <= 1.0:
                update_user_ldata(user_id, "VIDEO_WATERMARK_OPACITY", option)
                await database.update_user_data(user_id)
        except (ValueError, IndexError):
            pass
        # Go back to watermark submenu
        data[2] = "ffsubmenu"
        data[3] = "watermark"
        await edit_user_settings(client, query)
        return

    # VT Watermark handlers removed - VT watermark submenu now uses working VIDEO_WATERMARK handlers

    elif action == "menu":
        await get_menu(query, data[3])
    elif action == "tog_thumb":
        key = data[3]
        user_dict[key] = not user_dict.get(key, False)
        await database.update_user_data(user_id)
        msg, button = await get_user_settings(from_user, "thumbnail")
        await edit_message(message, msg, button)
    elif action == "set_tmdb_type":
        tmdb_type = data[3]
        if tmdb_type in ["poster", "backdrop"]:
            update_user_ldata(user_id, "TMDB_THUMBNAIL_TYPE", tmdb_type)
            await database.update_user_data(user_id)
        msg, button = await get_user_settings(from_user, "thumbnail")
        await edit_message(message, msg, button)
    elif action == "tog":
        key = data[3]
        new_value = data[4] == "t"
        update_user_ldata(user_id, key, new_value)

        # When enabling watermark for the first time, set default text if none exists
        if key == "VIDEO_WATERMARK_ENABLED" and new_value:
            if not user_dict.get("VIDEO_WATERMARK_TEXT"):
                update_user_ldata(user_id, "VIDEO_WATERMARK_TEXT", "Mirror Hunter Bot")

        await database.update_user_data(user_id)

        # Enforce mutual exclusivity in attachment settings
        if key == "EMBED_DEFAULT_USER_THUMBNAIL" and (data[4] == "t"):
            # When embedding default thumb, clear custom attachment text and photo
            update_user_ldata(user_id, "USER_ATTACHMENT_TEXT", None)
            update_user_ldata(user_id, "USER_ATTACHMENT_PHOTO", None)
            update_user_ldata(user_id, "USER_ATTACHMENT_PHOTO_CONTENT", None)
            # Only clear from memory, not database - user didn't explicitly remove the files
            await database.update_user_data(user_id)

        if key in [
            "SS_GRID_ENABLED",
            "SS_GRID_PDF_MODE",
            "SS_GRID_PDF_INDIVIDUAL_PAGES",
        ]:
            back_stype = "ssgrid"
        elif key in [
            "SAMPLE_VIDEO_ENABLED",
            "SAMPLE_VIDEO_SEPARATE",
        ]:
            back_stype = "vt_samplevideo"
        elif key == "STOP_DUPLICATE":
            back_stype = "gdrive"
        elif key == "USER_TOKENS":
            back_stype = "general"
        elif key in ["AUTO_LEECH", "AUTO_MIRROR", "AUTO_VT"]:
            back_stype = "auto_process"
        elif key == "EMBED_DEFAULT_USER_THUMBNAIL":
            back_stype = "attachments_menu"
        elif key == "ZIP_METADATA":
            back_stype = "ffset"
        elif key in [
            "VT_MERGE_VIDEOS",
            "VT_MERGE_AUDIOS",
            "VT_MERGE_SUBS",
        ]:
            back_stype = "vtset"
        elif key in [
            "VT_HARDSUB_STYLE",
            "VIDEO_WATERMARK_ENABLED",  # Updated to use working VIDEO_WATERMARK system
            "INTRO_SUBTITLE_ENABLED",
            "VT_WM_FONT_BOLD",
        ]:
            back_stype = "vtset"
        elif key in [
            "VIDEO_ENCODE_ENABLED",
            "VIDEO_ENCODE_MULTI_RESOLUTION",
            "VIDEO_ENCODE_MULTI_ZIP",
        ]:
            back_stype = "vt_encoding"
        elif key in [
            "VIDEO_ENCODE_PRESET",
            "VIDEO_ENCODE_QUALITY",
            "VIDEO_ENCODE_CRF",
            "VIDEO_ENCODE_AUDIO_BITRATE",
            "VIDEO_ENCODE_RESOLUTION_LIST",
        ]:
            back_stype = "vt_encoding"
        else:
            back_stype = "leech"

        # Check for special navigation parameter (5th element)
        if len(data) > 5 and data[5] == "vt_watermark":
            # Special case: navigate back to VT watermark submenu
            data_copy = data.copy()
            data_copy[2] = "vtsubmenu"
            data_copy[3] = "watermark"
            modified_query = type(
                "obj",
                (object,),
                {
                    "from_user": query.from_user,
                    "message": query.message,
                    "data": " ".join(data_copy[:4]),
                    "answer": lambda *args, **kwargs: None,  # Add missing answer method
                },
            )()
            await edit_user_settings(client, modified_query)
            return

        msg, button = await get_user_settings(from_user, back_stype)
        await edit_message(message, msg, button)

    elif action == "vt_tog":
        # Video Tools toggle - goes back to vt_samplevideo instead of samplevideo
        key = data[3]
        update_user_ldata(user_id, key, data[4] == "t")
        await database.update_user_data(user_id)
        msg, button = await get_user_settings(from_user, "vt_samplevideo")
        await edit_message(message, msg, button)

    elif action == "wmpos_menu":
        # Build position selection buttons using short tokens to avoid long callback_data
        pos_buttons = ButtonMaker()
        positions = [
            ("Top-Left", "tl"),
            ("Top-Right", "tr"),
            ("Bottom-Left", "bl"),
            ("Bottom-Right", "br"),
            ("Center", "c"),
        ]
        for label, token in positions:
            pos_buttons.data_button(label, f"userset {user_id} wmpos_set {token}")
        pos_buttons.data_button("❮❮", f"userset {user_id} vtset", position="footer")
        await edit_message(
            message, "Select Watermark Position:", pos_buttons.build_menu(2)
        )

    elif action == "wmpos_set":
        # Map short tokens to actual ffmpeg overlay expressions
        token = data[3] if len(data) > 3 else "tl"
        mapping = {
            "tl": "10:10",
            "tr": "main_w-overlay_w-10:10",
            "bl": "10:main_h-overlay_h-10",
            "br": "main_w-overlay_w-10:main_h-overlay_h-10",
            "c": "(main_w-overlay_w)/2:(main_h-overlay_h)/2",
        }
        pos_val = mapping.get(token, "10:10")
        update_user_ldata(user_id, "VT_WATERMARK_POSITION", pos_val)
        await database.update_user_data(user_id)
        msg, button = await get_user_settings(from_user, "vtset")
        await edit_message(message, msg, button)

    elif action == "file":
        option = data[3]
        back_menu, back_option = "menu", option
        if option == "THUMBNAIL":
            back_menu, back_option = "thumbnail", ""
        elif option == "USER_ATTACHMENT_PHOTO":
            back_menu, back_option = "attachments_menu", ""

        async def rfunc_on_timeout():
            handler_dict[user_id] = False
            await edit_user_settings(client, query)

        async def rfunc_on_success():
            handler_dict[user_id] = False
            await delete_message(message)
            if option == "THUMBNAIL":
                msg, btn = await get_user_settings(from_user, "thumbnail")
                photo_to_send = user_dict.get("THUMBNAIL") or getattr(
                    Config, "IMAGE_USETIINGS", None
                )
            elif option == "USER_ATTACHMENT_PHOTO":
                msg, btn = await get_user_settings(from_user, "attachments_menu")
                photo_to_send = user_dict.get("USER_ATTACHMENT_PHOTO") or getattr(
                    Config, "IMAGE_USETIINGS", None
                )
            else:
                await get_menu(query, option)
                return

            if photo_to_send and await aiopath.exists(photo_to_send):
                res = await send_message(
                    reply_to or message,
                    msg,
                    btn,
                    photo=photo_to_send,
                    reply_to_message_id=reply_to.id if reply_to else None,
                )
                if isinstance(res, str):
                    LOGGER.error(f"Failed to send user settings with photo: {res}")
                    await send_message(reply_to or message, msg, btn)
            else:
                await send_message(reply_to or message, msg, btn)

        pfunc = partial(add_file, ftype=option, rfunc=rfunc_on_success)
        prompt_buttons = ButtonMaker()
        prompt_buttons.data_button(
            "❮❮", f"userset {user_id} {back_menu} {back_option}", position="footer"
        )
        prompt_buttons.data_button("✘", f"userset {user_id} close", position="footer")
        prompt_text = user_settings_text[option][2]
        base_text = message.caption.html if message.caption else ""
        await edit_message(
            message, base_text + "\n\n" + prompt_text, prompt_buttons.build_menu(2)
        )
        is_photo = option in ["THUMBNAIL", "USER_ATTACHMENT_PHOTO"]
        if option == "VT_WATERMARK_IMAGE":
            await event_handler(
                client,
                query,
                pfunc,
                rfunc_on_timeout,
                photo=True,
                document=True,
            )
            # After upload (or timeout), refresh VT settings page
            msg, btn = await get_user_settings(from_user, "vtset")
            await edit_message(message, msg, btn)
        else:
            await event_handler(
                client,
                query,
                pfunc,
                rfunc_on_timeout,
                photo=is_photo,
                document=not is_photo,
            )

        # If we just set USER_ATTACHMENT_PHOTO, clear USER_ATTACHMENT_TEXT and disable embed default
        if option == "USER_ATTACHMENT_PHOTO" and user_dict.get("USER_ATTACHMENT_PHOTO"):
            update_user_ldata(user_id, "USER_ATTACHMENT_TEXT", None)
            update_user_ldata(user_id, "EMBED_DEFAULT_USER_THUMBNAIL", False)
            await database.update_user_data(user_id)

    elif action == "remove_file":
        option = data[3]
        if option == "USER_ATTACHMENT_PHOTO":
            removed_path = user_dict.get("USER_ATTACHMENT_PHOTO")
            update_user_ldata(user_id, "USER_ATTACHMENT_PHOTO", None)
            update_user_ldata(user_id, "USER_ATTACHMENT_PHOTO_CONTENT", None)
            if removed_path and await aiopath.exists(removed_path):
                await aioremove(removed_path)
            # Clear from database properly
            await database.update_user_doc(user_id, "USER_ATTACHMENT_PHOTO")
            await database.update_user_doc(user_id, "USER_ATTACHMENT_PHOTO_CONTENT")
            await query.answer("Custom Attachment Photo removed!", show_alert=True)
            await database.update_user_data(user_id)
        elif option == "VT_WATERMARK_IMAGE":
            removed_path = user_dict.pop("VT_WATERMARK_IMAGE", None)
            if removed_path and await aiopath.exists(removed_path):
                await aioremove(removed_path)
                await query.answer("Watermark image removed!", show_alert=True)
            # Clear from database properly
            await database.update_user_doc(user_id, "VT_WATERMARK_IMAGE")
            await database.update_user_data(user_id)

            class MockQuery:
                def __init__(self, original_query):
                    self.from_user = original_query.from_user
                    self.message = original_query.message
                    self.data = f"userset {user_id} back_photo main"

                async def answer(self, *args, **kwargs):
                    pass

            await edit_user_settings(client, MockQuery(query))

    elif action in ["set", "addone", "rmone"]:
        option = data[3]
        metadata_field_keys = [
            "metadata_all",
            "website",
            "global_title",
            "global_author",
            "global_artist",
            "video_title",
            "video_artist",
            "video_author",
            "audio_title",
            "audio_artist",
            "audio_author",
            "subtitle_title",
            "subtitle_artist",
            "subtitle_author",
            "global_comment",
            "video_comment",
            "audio_comment",
            "subtitle_comment",
        ]

        if option in metadata_field_keys:
            back_stype = "metadata_menu"
        elif option in gofile_options:
            back_stype = "gofile"
        else:
            back_stype = "menu"
        # Persist direct set options like ZIP_MODE values coming from buttons
        if action == "set" and option == "ZIP_MODE" and len(data) >= 5:
            mode_val = data[4]
            update_user_ldata(user_id, "ZIP_MODE", mode_val)
            await database.update_user_data(user_id)
            await get_menu(query, option)
            return

        async def rfunc_restore():
            if option in metadata_field_keys:
                await get_metadata_menu(query, option)
            elif option in gofile_options:
                msg, button = await get_user_settings(from_user, "gofile")
                await edit_message(message, msg, button)
            elif option == "VT_WATERMARK_TEXT":
                # After setting watermark text, show position chooser
                pos_buttons = ButtonMaker()
                positions = [
                    ("Top-Left", "tl"),
                    ("Top-Right", "tr"),
                    ("Bottom-Left", "bl"),
                    ("Bottom-Right", "br"),
                    ("Center", "c"),
                ]
                for label, token in positions:
                    pos_buttons.data_button(
                        label, f"userset {user_id} wmpos_set {token}"
                    )
                pos_buttons.data_button(
                    "❮❮", f"userset {user_id} vtset", position="footer"
                )
                await edit_message(
                    message, "Select Watermark Position:", pos_buttons.build_menu(2)
                )
            else:
                await get_menu(query, option)

        pfunc_map = {"set": set_option, "addone": add_one, "rmone": remove_one}
        pfunc = partial(pfunc_map[action], option=option, rfunc=rfunc_restore)

        prompt_buttons = ButtonMaker()
        if back_stype == "gofile":
            prompt_buttons.data_button(
                "❮❮", f"userset {user_id} gofile", position="footer"
            )
        else:
            prompt_buttons.data_button(
                "❮❮", f"userset {user_id} {back_stype} {option}", position="footer"
            )
        prompt_buttons.data_button("✘", f"userset {user_id} close", position="footer")

        prompt_text = user_settings_text.get(option, ["", "", "Provide input"])[2]
        base_text = message.caption.html if message.caption else message.text.html
        await edit_message(
            message, base_text + "\n\n" + prompt_text, prompt_buttons.build_menu(2)
        )
        await event_handler(client, query, pfunc, rfunc_restore)

        # If user has set USER_ATTACHMENT_TEXT, clear photo and disable embed default
        if option == "USER_ATTACHMENT_TEXT" and user_dict.get("USER_ATTACHMENT_TEXT"):
            update_user_ldata(user_id, "USER_ATTACHMENT_PHOTO", None)
            update_user_ldata(user_id, "USER_ATTACHMENT_PHOTO_CONTENT", None)
            update_user_ldata(user_id, "EMBED_DEFAULT_USER_THUMBNAIL", False)
            # Only clear from memory, not database - user didn't explicitly remove the files
            await database.update_user_data(user_id)

    elif action == "rm_thumb":
        thumb_path = f"thumbnails/{user_id}.jpg"
        if await aiopath.exists(thumb_path):
            await aioremove(thumb_path)
        update_user_ldata(user_id, "THUMBNAIL", None)
        update_user_ldata(user_id, "THUMBNAIL_CONTENT", None)
        await database.update_user_doc(user_id, "THUMBNAIL")
        await database.update_user_doc(user_id, "THUMBNAIL_CONTENT")
        await database.update_user_data(user_id)
        await delete_message(message)
        msg, button = await get_user_settings(from_user, "thumbnail")
        photo_to_send = getattr(Config, "IMAGE_USETIINGS", None)
        if photo_to_send:
            res = await send_message(
                reply_to or message,
                msg,
                button,
                photo=photo_to_send,
                reply_to_message_id=reply_to.id if reply_to else None,
            )
            if isinstance(res, str):
                LOGGER.error(f"Failed to send user settings with photo: {res}")
                await send_message(reply_to or message, msg, button)
        else:
            await send_message(reply_to or message, msg, button)

    elif action == "remove":
        option = data[3]
        file_dict = {
            "RCLONE_CONFIG": f"rclone/{user_id}.conf",
            "TOKEN_PICKLE": f"tokens/{user_id}.pickle",
            "YTDLP_COOKIES": f"cookies/{user_id}/cookies.txt",
            "INTRO_SUBTITLE_FONT_PATH": f"fonts/{user_id}.ttf",
            "VT_WM_FONT_PATH": f"fonts/wm_{user_id}.ttf",
            "VT_HARDSUB_FONT_PATH": f"fonts/hardsub_{user_id}.ttf",
        }
        file_path = file_dict.get(option)
        if file_path and await aiopath.exists(file_path):
            await aioremove(file_path)

        # Special cleanup for font files
        if option == "VT_HARDSUB_FONT_PATH":
            # For single font file removal, log the action
            LOGGER.info(f"Removed single font file for user {user_id}")

        user_dict.pop(option, None)
        # Clear from database properly for file-based options
        if option in (
            "RCLONE_CONFIG",
            "TOKEN_PICKLE",
            "YTDLP_COOKIES",
            "INTRO_SUBTITLE_FONT_PATH",
            "VT_WM_FONT_PATH",
            "VT_HARDSUB_FONT_PATH",
        ):
            await database.update_user_doc(user_id, option)
            # Also clear the _CONTENT field for file types that have binary content
            if option in ("RCLONE_CONFIG", "TOKEN_PICKLE", "YTDLP_COOKIES"):
                await database.update_user_doc(user_id, f"{option}_CONTENT")
        await database.update_user_data(user_id)
        await get_menu(query, option)

    elif action == "reset":
        option_to_reset = data[3]

        metadata_options = [
            "GEN_METADATA",
            "VID_METADATA",
            "AUD_METADATA",
            "SUB_METADATA",
        ]

        if option_to_reset == "USER_SESSION_STRING":
            from bot.helper.ext_utils.user_session_manager import UserSessionManager

            await UserSessionManager.remove_user_session(user_id)
            user_dict.pop(option_to_reset, None)
        elif option_to_reset in metadata_options:
            if user_dict.get("METADATA_SETTINGS"):
                del user_dict["METADATA_SETTINGS"]
        else:
            update_user_ldata(user_id, option_to_reset, None)

        await database.update_user_data(user_id)

        if option_to_reset in gofile_options:
            msg, button = await get_user_settings(from_user, "gofile")
            await edit_message(message, msg, button)
        else:
            await get_menu(query, option_to_reset)

    elif action == "reset_all_prompt":
        buttons = ButtonMaker()
        buttons.data_button("✅ Yes, Reset All", f"userset {user_id} reset_all_confirm")
        buttons.data_button("❌ No, Cancel", f"userset {user_id} back main")
        text = (
            "⚠️ <b><u>CONFIRMATION</u></b> ⚠️\n\n"
            "Are you sure you want to reset <b>ALL</b> your settings?\n\n"
            "This will delete:\n"
            "• Your custom thumbnail\n"
            "• Rclone, GDrive, and Cookies files\n"
            "• All other personalized settings\n\n"
            "<b>This action cannot be undone.</b>"
        )
        await edit_message(message, text, buttons.build_menu(1))

    elif action == "reset_all_confirm":
        await query.answer("Resetting all your settings...", show_alert=False)
        user_dict_to_delete = user_data.get(user_id, {})
        user_attach_photo = user_dict_to_delete.get("USER_ATTACHMENT_PHOTO")

        paths_to_remove = [
            f"thumbnails/{user_id}.jpg",
            f"rclone/{user_id}.conf",
            f"tokens/{user_id}.pickle",
            f"cookies/{user_id}/cookies.txt",
            f"fonts/hardsub_{user_id}.ttf",
            f"fonts/wm_{user_id}.ttf",
            f"fonts/{user_id}.ttf",
        ]
        if user_attach_photo and isinstance(user_attach_photo, str):
            paths_to_remove.append(user_attach_photo)

        for path in paths_to_remove:
            if await aiopath.exists(path):
                await aioremove(path)

        # Clear all file-based data from database
        file_keys_to_clear = [
            "THUMBNAIL",
            "THUMBNAIL_CONTENT",
            "RCLONE_CONFIG",
            "RCLONE_CONFIG_CONTENT",
            "TOKEN_PICKLE",
            "TOKEN_PICKLE_CONTENT",
            "YTDLP_COOKIES",
            "YTDLP_COOKIES_CONTENT",
            "USER_ATTACHMENT_PHOTO",
            "USER_ATTACHMENT_PHOTO_CONTENT",
            "VT_WATERMARK_IMAGE",
            "INTRO_SUBTITLE_FONT_PATH",
            "VT_WM_FONT_PATH",
            "VT_HARDSUB_FONT_PATH",
        ]
        for key in file_keys_to_clear:
            await database.update_user_doc(user_id, key)

        if user_id in user_data:
            user_data[user_id].clear()
            await database.update_user_data(user_id)
            user_data.pop(user_id, None)

        await query.answer("All settings have been reset to default!", show_alert=True)
        msg, button = await get_user_settings(from_user, "main")
        await edit_message(message, msg, button)

    elif action == "close":
        await delete_message(message)
        if reply_to:
            await delete_message(reply_to)

    elif action == "intro_menu":
        # Intro Subtitle submenu
        intro_buttons = ButtonMaker()
        intro_enabled = user_dict.get("INTRO_SUBTITLE_ENABLED", False)
        intro_buttons.data_button(
            ("Disable " if intro_enabled else "Enable ") + "Intro Sub",
            f"userset {user_id} tog INTRO_SUBTITLE_ENABLED {'f' if intro_enabled else 't'}",
        )
        # Settings shortcuts
        intro_buttons.data_button(
            "Set Text", f"userset {user_id} menu INTRO_SUBTITLE_TEXT"
        )
        intro_buttons.data_button(
            "Set Style", f"userset {user_id} menu INTRO_SUBTITLE_STYLE"
        )
        intro_buttons.data_button(
            "Set Mode", f"userset {user_id} menu INTRO_SUBTITLE_MODE"
        )
        intro_buttons.data_button(
            "Set Position", f"userset {user_id} menu INTRO_SUBTITLE_POSITION"
        )
        intro_buttons.data_button(
            "Set Font Size", f"userset {user_id} menu INTRO_SUBTITLE_FONT_SIZE"
        )
        intro_buttons.data_button(
            "Set Colors", f"userset {user_id} menu INTRO_SUBTITLE_COLORS"
        )
        intro_buttons.data_button(
            "Upload Font", f"userset {user_id} file INTRO_SUBTITLE_FONT_PATH"
        )
        intro_buttons.data_button(
            "Set Char MS", f"userset {user_id} menu INTRO_SUBTITLE_CHAR_MS"
        )
        intro_buttons.data_button("❮❮", f"userset {user_id} vtset", position="footer")
        intro_text = (
            f"<u>Intro Subtitle Settings</u>\n\n"
            f"Status: <b>{'Enabled' if intro_enabled else 'Disabled'}</b>\n"
            f"Text: <code>{escape(str(user_dict.get('INTRO_SUBTITLE_TEXT', 'Not Set')))}</code>\n"
            f"Style: <b>{escape(str(user_dict.get('INTRO_SUBTITLE_STYLE', 'typing')))}</b>\n"
            f"Mode: <b>{escape(str(user_dict.get('INTRO_SUBTITLE_MODE', 'new')))}</b>\n"
            f"Position: <b>{escape(str(user_dict.get('INTRO_SUBTITLE_POSITION', 'bottom')))}</b>\n"
            f"Font Size: <b>{escape(str(user_dict.get('INTRO_SUBTITLE_FONT_SIZE', 48)))}</b>\n"
            f"Colors: <code>{escape(str(user_dict.get('INTRO_SUBTITLE_COLORS', 'Default')))}</code>\n"
            f"Char MS: <b>{escape(str(user_dict.get('INTRO_SUBTITLE_CHAR_MS', 300)))}</b>\n"
            f"Font: <code>{escape(str(user_dict.get('INTRO_SUBTITLE_FONT_PATH', 'System Default')))}</code>\n"
            f"<i>Note: Some styles (e.g., typing) work only with ASS/SSA. If the embedded subtitle is another type or already styled, your style may not apply. Use Mode = <b>new</b> to add a separate styled intro track.</i>\n"
        )
        await edit_message(message, intro_text, intro_buttons.build_menu(2))


@new_task
async def get_users_settings(_, message):
    msg = ""
    if auth_chats:
        msg += f"<b>Auth Chats:</b> {auth_chats}\n"
    if sudo_users:
        msg += f"<b>Sudo Users:</b> {sudo_users}\n\n"
    if user_data:
        for u, d in user_data.items():
            kmsg = f"\n<b>{u}:</b>\n"
            if vmsg := "".join(
                f"  <code>{k}: {v or None}</code>\n" for k, v in d.items()
            ):
                msg += kmsg + vmsg
        if len(msg.encode()) > 4000:
            with BytesIO(msg.encode()) as ofile:
                ofile.name = "users_settings.txt"
                await send_file(message, ofile)
        else:
            await send_message(message, msg or "No user data found!")
    else:
        await send_message(message, "No user data found!")


@TgClient.bot.on_message(command(BotCommands.RmthumbCommand) & CustomFilters.authorized)
async def remove_user_thumbnail_cmd(_, message):
    user_id = message.from_user.id
    thumb_path = f"thumbnails/{user_id}.jpg"

    if user_data.get(user_id, {}).get("THUMBNAIL") or await aiopath.exists(thumb_path):
        if await aiopath.exists(thumb_path):
            await aioremove(thumb_path)
        update_user_ldata(user_id, "THUMBNAIL", None)
        update_user_ldata(user_id, "THUMBNAIL_CONTENT", None)
        # Clear from database properly
        await database.update_user_doc(user_id, "THUMBNAIL")
        await database.update_user_doc(user_id, "THUMBNAIL_CONTENT")
        await database.update_user_data(user_id)
        await send_message(message, "✅ Custom thumbnail removed successfully.")
    else:
        await send_message(message, "ℹ️ You do not have a custom thumbnail set.")


async def get_metadata_menu(query, option):
    return await get_menu(query, option)
