from asyncio import sleep
from functools import partial
from html import escape
from io import BytesIO
from os import getcwd
from re import sub
from time import time

from aiofiles.os import makedirs, remove
from aiofiles.os import path as aiopath
from langcodes import Language
from pyrogram.filters import create
from pyrogram.handlers import MessageHandler

from bot.helper.ext_utils.status_utils import get_readable_file_size

from .. import auth_chats, excluded_extensions, sudo_users, user_data
from ..core.config_manager import Config
from ..core.tg_client import TgClient
from ..helper.ext_utils.bot_utils import (
    get_size_bytes,
    new_task,
    update_user_ldata,
)
from ..helper.ext_utils.db_handler import database
from ..helper.ext_utils.media_utils import create_thumb
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.ffmpeg_button_build import FFmpegButtonMaker
from ..helper.telegram_helper.message_utils import (
    delete_message,
    edit_message,
    send_file,
    send_message,
)

handler_dict = {}

common_tools_options = [
    "THUMBNAIL",
    "EMBED_USER_IMAGE_AS_COVER",
    "AUTO_THUMBNAIL",
    "FILENAME_PREFIX",  # Renamed from LEECH_PREFIX for universal use
    "FILENAME_SUFFIX",  # Renamed from LEECH_SUFFIX for universal use
    "FILENAME_REMOVE_PATTERNS",  # Default filename patterns to remove
    "AUTO_RENAME",
    "RENAME_TEMPLATE",
    "START_EPISODE",
    "START_SEASON",
    "THUMBNAIL_LAYOUT",
    "SS_GRID_ENABLED",  # SS Grid feature toggle
    "SS_GRID_COUNT",  # SS Grid screenshot count
    "SS_GRID_LAYOUT",  # SS Grid layout (e.g., 3x3)
    "SS_GRID_PDF_MODE",  # SS Grid PDF mode toggle
    "SS_GRID_WATERMARK",  # SS Grid PDF watermark
    "SS_GRID_PDF_INDIVIDUAL_PAGES",  # SS Grid PDF individual pages toggle
    "SAMPLE_VIDEO_ENABLED",  # Sample video feature toggle
    "SAMPLE_VIDEO_COUNT",  # Number of random sample clips to generate
    "SAMPLE_VIDEO_DURATION",  # Duration (seconds) of each sample clip
    "SAMPLE_VIDEO_SEPARATE",  # Whether to output separate sample clips instead of merged
]

leech_options = [
    "LEECH_CAPTION",
    "LEECH_SPLIT_SIZE",  # File split size for leech operations
    "EQUAL_SPLITS",  # Equal splits option for leech operations
    "SHOW_MEDIAINFO_BUTTON",  # Toggle for Media Info button - leech specific
]

dumps_options = [
    "LEECH_DUMP_CHAT",
    "MIRROR_DUMP_CHAT",
]
rclone_options = ["RCLONE_CONFIG", "RCLONE_PATH", "RCLONE_FLAGS"]
gdrive_options = ["TOKEN_PICKLE", "GDRIVE_ID", "INDEX_URL"]
gofile_options = ["GOFILE_TOKEN", "GOFILE_FOLDER_ID"]
ffset_options = [
    "FFMPEG_CMDS",
    "METADATA_SETTINGS",
    "VIDEO_MERGE_ENABLED",
    "VIDEO_AUDIO_MERGE_ENABLED",
    "VIDEO_SUBTITLE_MERGE_ENABLED",
    "VIDEO_HARDSUB_ENABLED",
    "VIDEO_HARDSUB_STYLE",
    "VIDEO_HARDSUB_FONT_SIZE",
    "VIDEO_HARDSUB_FONT_NAME",
    "VIDEO_STREAM_EXTRACT_ENABLED",
    "STREAM_SWAP_ENABLED",
    "STREAM_REMOVE_ENABLED",
    "KEEP_MERGE_SOURCE_FILES",
    "VIDEO_ENCODE_ENABLED",
    "VIDEO_ENCODE_CODEC",
    "VIDEO_ENCODE_PRESET",
    "VIDEO_ENCODE_QUALITY",
    "VIDEO_ENCODE_CRF",
    "VIDEO_ENCODE_AUDIO_BITRATE",
    "VIDEO_ENCODE_MULTI_RESOLUTION",
    "VIDEO_ENCODE_RESOLUTION_LIST",
    "VIDEO_ENCODE_MULTI_ZIP",
    "VIDEO_CONVERT_ENABLED",
    "VIDEO_CONVERT_FORMAT",
    "VIDEO_CONVERT_CODEC",
    "VIDEO_CONVERT_QUALITY",
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
    "CUSTOM_FILENAME",
    "VIDEO_TRIM_ENABLED",
]
advanced_options = [
    "EXCLUDED_EXTENSIONS",
    "NAME_SWAP",
    "YT_DLP_OPTIONS",
    "UPLOAD_PATHS",
    "USER_SESSION_STRING",
]
yt_options = [
    "YT_DESP",
    "YT_TAGS",
    "YT_CATEGORY_ID",
    "YT_PRIVACY_STATUS",
    "YTDLP_COOKIES",
]

user_settings_text = {
    "THUMBNAIL": (
        "Photo or Doc",
        "Custom Thumbnail is used as the thumbnail for the files you upload to telegram in media or document mode.",
        "<i>Send a photo to save it as custom thumbnail.</i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "EMBED_USER_IMAGE_AS_COVER": (
        "Boolean",
        "Embed your saved thumbnail image into audio/video files as cover art so local players like VLC show it as the poster. Works for both Mirror and Leech operations.",
        "<i>Send true/false to enable or disable embedding your user image as cover art into files.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "RCLONE_CONFIG": (
        "",
        "",
        "<i>Send your <code>rclone.conf</code> file to use as your Upload Dest to RClone.</i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "TOKEN_PICKLE": (
        "",
        "",
        "<i>Send your <code>token.pickle</code> to use as your Upload Dest to GDrive</i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "LEECH_SPLIT_SIZE": (
        "",
        "",
        f"Send Leech split size in bytes or use gb or mb. Example: 40000000 or 2.5gb or 1000mb. PREMIUM_USER: {TgClient.IS_PREMIUM_USER}.</i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "LEECH_DUMP_CHAT": (
        "",
        "",
        """Send leech destination ID/USERNAME/PM. 
* b:id/@username/pm (b: means leech by bot) (id or username of the chat or write pm means private message so bot will send the files in private to you)
* id/@username|topic_id(leech in specific chat and topic) add | without space and write topic id after chat id or username.
╰<b>Time Left :</b> <code>60 sec</code>""",
    ),
    "MIRROR_DUMP_CHAT": (
        "",
        "",
        """Send mirror destination ID/USERNAME/PM where mirror links will be posted.
* id/@username/pm (id or username of the chat or write pm means private message)
* id/@username|topic_id (mirror in specific chat and topic) add | without space and write topic id after chat id or username.
╰<b>Time Left :</b> <code>60 sec</code>""",
    ),
    "FILENAME_PREFIX": (
        "",
        "",
        "Send Filename Prefix (applies to both mirror and leech). You can add HTML tags. Example: <code>@mychannel</code>.</i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "FILENAME_SUFFIX": (
        "",
        "",
        "Send Filename Suffix (applies to both mirror and leech). You can add HTML tags. Example: <code>@mychannel</code>.</i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "FILENAME_REMOVE_PATTERNS": (
        "",
        "",
        """Send filename patterns to remove or replace. Supports both removal and replacement operations.

<b>🔄 Replacement Syntax (NEW):</b>
<code>pattern1|replacement1 pattern2|replacement2</code>

<b>🗑️ Removal Syntax:</b>
<code>pattern1 pattern2 pattern3</code> - Remove patterns
<code>pattern1|pattern2|pattern3</code> - Old format (still works)

<b>📝 Examples:</b>
<code>(Yao.Shen.Ji)|rizz (Yao.Shen)|iss</code> - Replace Chinese with English
<code>(Chinese)|ENG (Subbed)|DUB</code> - Replace language tags
<code>HDRip WEBRip x264</code> - Remove quality tags
<code>[RARBG]| Sample|</code> - Replace with empty (same as removal)

<b>🔀 Mixed Operations:</b>
<code>(Chinese)|ENG RARBG Sample</code> - Replace (Chinese) with ENG, remove RARBG and Sample

<b>ℹ️ Rules:</b>
• Use spaces to separate different pattern rules
• Use | within a rule for replacement: pattern|replacement
• Case-insensitive matching
• File extensions are preserved
• Applied automatically to all downloads</i> \n╰<b>Time Left :</b> <code>60 sec</code>""",
    ),
    "LEECH_CAPTION": (
        "",
        "",
        """Send Leech Caption. You can add HTML tags.<br>
Format Templates:<br>
<code>{BL}</code> : Default BL Format, Like Same File Name<br>
<code>{file_name}</code> : Default File Name That Will Be On File Name<br>
<code>{file_size}</code> : File Size Of The Media. Like: 2.45GB<br>
<code>{file_caption}</code> : Custom File Caption On Media<br>
<code>{languages}</code> : All Languages In Media<br>
<code>{subtitles}</code> : All Subtitles In Media. Like- English<br>
<code>{duration}</code> : The Duration Of File In HH:MM:SS Format<br>
<code>{ott}</code> : For OTT, Like- NF, AMZN etc<br>
<code>{resolution}</code> : Video Resolution. Like-- 480p, 720p<br>
<code>{name}</code> : The File Name Only, Like: Premi Babu<br>
<code>{year}</code> : Year On The Media Name<br>
<code>{quality}</code> : Quality Of The File. Like:- WEB-DL, WEBRip, BluRay etc.<br>
<code>{season}</code> : Season Of The File, Like- S01<br>
<code>{episode}</code> : Episode Of The File, Like- E03<br>
<code>{audio}</code> : Audio Type Of The Media. Shows language(s) if single audio, or <b>MultiAuD</b> if 2 or more audio tracks.<br>
╰<b>Time Left :</b> <code>60 sec</code>""",
    ),
    "THUMBNAIL_LAYOUT": (
        "",
        "",
        "Send thumbnail layout (widthxheight, 2x2, 3x3, 2x4, 4x4, ...). Example: 3x3.</i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "RCLONE_PATH": (
        "",
        "",
        "Send Rclone Path. If you want to use your rclone config edit using owner/user config from usetting or add mrcc: before rclone path. Example mrcc:remote:folder. </i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "RCLONE_FLAGS": (
        "",
        "",
        "key:value|key|key|key:value . Check here all <a href='https://rclone.org/flags/'>RcloneFlags</a>\nEx: --buffer-size:8M|--drive-starred-only",
    ),
    "GDRIVE_ID": (
        "",
        "",
        "Send Gdrive ID. If you want to use your token.pickle edit using owner/user token from usetting or add mtp: before the id. Example: mtp:F435RGGRDXXXXXX . </i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "INDEX_URL": (
        "",
        "",
        "Send Index URL for your gdrive option. </i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "GOFILE_TOKEN": (
        "",
        "",
        "Send your GoFile API Token. Get it from <a href='https://gofile.io/myProfile'>GoFile Profile</a>. </i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "GOFILE_FOLDER_ID": (
        "",
        "",
        "Send GoFile Folder ID where you want to upload files (Optional). Leave empty to upload to root folder. </i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "UPLOAD_PATHS": (
        "",
        "",
        "Send Dict of keys that have path values. Example: {'path 1': 'remote:rclonefolder', 'path 2': 'gdrive1 id', 'path 3': 'tg chat id', 'path 4': 'mrcc:remote:', 'path 5': b:@username} . </i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "USER_SESSION_STRING": (
        "",
        "",
        """<i>Send your Telegram User Session String to download files from private channels/groups.</i>

<b>⚠️ Important:</b>
• Use this to download files from private channels/groups you have access to
• Files will be downloaded using your session and uploaded via premium user session
• Your session string will be encrypted and stored securely
• Never share your session string with anyone
• You can generate session string using <a href='https://colab.research.google.com/drive/15rA8DjTFqBi6gwzwctcZWlWnsIqiV-jC?usp=sharing'>BL-SS-GEN</a>

<b>Format:</b> Send your session string as plain text.

╰<b>Time Left :</b> <code>60 sec</code>""",
    ),
    "EXCLUDED_EXTENSIONS": (
        "",
        "",
        "Send exluded extenions seperated by space without dot at beginning. </i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "NAME_SWAP": (
        "",
        "",
        """<i>Send your Name Swap. You can add pattern instead of normal text according to the format.</i>
<b>Full Documentation Guide</b> <a href="https://t.me/WZML_X/77">Click Here</a>
╰<b>Time Left :</b> <code>60 sec</code>
""",
    ),
    "YT_DLP_OPTIONS": (
        "",
        "",
        """Format: {key: value, key: value, key: value}.
Example: {"format": "bv*+mergeall[vcodec=none]", "nocheckcertificate": True, "playliststart": 10, "fragment_retries": float("inf"), "matchtitle": "S13", "writesubtitles": True, "live_from_start": True, "postprocessor_args": {"ffmpeg": ["-threads", "4"]}, "wait_for_video": (5, 100), "download_ranges": [{"start_time": 0, "end_time": 10}]}
Check all yt-dlp api options from this <a href='https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/YoutubeDL.py#L184'>FILE</a> or use this <a href='https://t.me/mltb_official_channel/177'>script</a> to convert cli arguments to api options.

<i>Send dict of YT-DLP Options according to format.</i> \n╰<b>Time Left :</b> <code>60 sec</code>""",
    ),
    "FFMPEG_CMDS": (
        "",
        "",
        """Dict of list values of ffmpeg commands. You can set multiple ffmpeg commands for all files before upload. Don't write ffmpeg at beginning, start directly with the arguments.
Examples: {"subtitle": ["-i mltb.mkv -c copy -c:s srt mltb.mkv", "-i mltb.video -c copy -c:s srt mltb"], "convert": ["-i mltb.m4a -c:a libmp3lame -q:a 2 mltb.mp3", "-i mltb.audio -c:a libmp3lame -q:a 2 mltb.mp3"], extract: ["-i mltb -map 0:a -c copy mltb.mka -map 0:s -c copy mltb.srt"]}
Notes:
- Add `-del` to the list which you want from the bot to delete the original files after command run complete!
- To execute one of those lists in bot for example, you must use -ff subtitle (list key) or -ff convert (list key)
Here I will explain how to use mltb.* which is reference to files you want to work on.
1. First cmd: the input is mltb.mkv so this cmd will work only on mkv videos and the output is mltb.mkv also so all outputs is mkv. -del will delete the original media after complete run of the cmd.
2. Second cmd: the input is mltb.video so this cmd will work on all videos and the output is only mltb so the extenstion is same as input files.
3. Third cmd: the input in mltb.m4a so this cmd will work only on m4a audios and the output is mltb.mp3 so the output extension is mp3.
4. Fourth cmd: the input is mltb.audio so this cmd will work on all audios and the output is mltb.mp3 so the output extension is mp3.

<i>Send dict of FFMPEG_CMDS Options according to format.</i> \n╰<b>Time Left :</b> <code>60 sec</code>
""",
    ),
    "METADATA_SETTINGS": (
        "",
        "",
        """Dict of metadata settings to apply to audio/video files. This will change metadata like title, artist, album, etc.

<b>Supported formats:</b>
1. <b>Simple format:</b> title|artist|album|genre|date|comment
   Example: <code>My Video Title|Bzex-X|Summer Collection</code>

2. <b>Pipe-separated key=value format:</b> key=value|key2=value2|key3=value3
   Example: <code>title=My Video Title|artist=Bzex-X|album=Summer Collection|genre=Documentary|date=2025|comment=Downloaded with Bzex-X</code>

3. <b>Comma-separated format:</b> title="My Title", artist="Artist Name"
   Example: <code>title="My Video Title", artist="Bzex-X", comment="Downloaded by Bzex-X"</code>

<b>Stream-specific fields:</b>
• <code>video_title</code> - Title for ALL video streams
• <code>audio_title</code> - Title for ALL audio streams 
• <code>subtitle_title</code> - Title for ALL subtitle streams

<b>Or for specific streams:</b>
• <code>audio_title:0</code> - Title for first audio stream
• <code>audio_title:1</code> - Title for second audio stream
• <code>video_title:0</code> - Title for first video stream
• <code>subtitle_title:0</code> - Title for first subtitle
• <code>subtitle_title:1</code> - Title for second subtitle

<b>Shorthand format (most convenient):</b>
• <code>videotitle-audiotitle-subtitle-author-artist</code>
  - 1st: all video stream titles
  - 2nd: all audio stream titles
  - 3rd: all subtitle stream titles
  - 4th: author (global metadata)
  - 5th: artist (global metadata)
  
  Example: <code>MyVideoTitle-MyAudioTitle-MySubtitleTitle-John Doe-MyBand</code>

<b>Single word/phrase:</b>
• <code>MyUniversalTitle</code>
  - Sets the same value as the global title, author, artist, and as the title for all video, audio, and subtitle streams.
  - Example: <code>MyUniversalTitle</code>

<i>Send metadata settings according to your preferred format. The bot will process and apply them to your media files.</i> \n╰<b>Time Left :</b> <code>60 sec</code>
""",
    ),
    "METADATA_CMDS": (
        "",
        "",
        """<i>Send your Meta data. You can according to the format title="Join @MirrorLeechGroupz".</i>
╰<b>Time Left :</b> <code>60 sec</code>
""",
    ),
    "YT_DESP": (
        "String",
        "Custom description for YouTube uploads. Default is used if not set.",
        "<i>Send your custom YouTube description.</i> \nTime Left : <code>60 sec</code>",
    ),
    "YT_TAGS": (
        "Comma-separated strings",
        "Custom tags for YouTube uploads (e.g., tag1,tag2,tag3). Default is used if not set.",
        "<i>Send your custom YouTube tags as a comma-separated list.</i> \nTime Left : <code>60 sec</code>",
    ),
    "YT_CATEGORY_ID": (
        "Number",
        "Custom category ID for YouTube uploads. Default is used if not set.",
        "<i>Send your custom YouTube category ID (e.g., 22).</i> \nTime Left : <code>60 sec</code>",
    ),
    "YT_PRIVACY_STATUS": (
        "public, private, or unlisted",
        "Custom privacy status for YouTube uploads. Default is used if not set.",
        "<i>Send your custom YouTube privacy status (public, private, or unlisted).</i> \nTime Left : <code>60 sec</code>",
    ),
    "AUTO_RENAME": (
        "Boolean",
        "Enable or disable auto renaming of files using a template.",
        "<i>Send true/false to enable or disable auto renaming.</i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "RENAME_TEMPLATE": (
        "Template String",
        " <b>IMDB INTEGRATED</b> \n Template for renaming files. Use {season}, {episode}, {quality}, {title}, {year}, {rating}, {genre}, {audio}.",
        "<i>Send your rename template. Example: S{season}E{episode}Q{quality} or {title}{year}{rating}{genre}{audio}</i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "START_EPISODE": (
        "Number",
        "Set the starting episode number.",
        "<i>Send the starting episode number (e.g., 1 or 5).</i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "START_SEASON": (
        "Number",
        "Set the starting season number.",
        "<i>Send the starting season number (e.g., 1 or 2).</i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "AUTO_THUMBNAIL": (
        "Boolean",
        "Enable or disable automatic thumbnail extraction from TMDB/IMDB for your uploads. If enabled and no custom thumbnail is set, the bot will fetch a poster from TMDB (16:9 backdrop preferred) or IMDB based on the file name/title.",
        "<i>Send true/false to enable or disable auto thumbnail feature. When enabled, the bot will use TMDB (preferred) or IMDB posters as your thumbnail if no custom thumbnail is set.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "OPENAI_API_KEY": (
        "String",
        "OpenAI API key for AI-based filename cleaning. Get yours at https://platform.openai.com/api-keys",
        "<i>Send your OpenAI API key for AI filename cleaning. This is optional, but enables the best possible filename-to-title extraction for thumbnails and metadata.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "YTDLP_COOKIES": (
        "Text file",
        "Custom cookies.txt for yt-dlp. If not set, the bot will use the default cookies.txt.",
        "<i>Send your cookies.txt file for yt-dlp.</i> \nTime Left : <code>60 sec</code>",
    ),
    "VIDEO_ENCODE_ENABLED": (
        "Boolean",
        "Enable or disable video encoding for your uploads. This will re-encode videos with specified preset.",
        "<i>Send true/false to enable or disable video encoding.</i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_ENCODE_CODEC": (
        "String",
        "Set the video codec for encoding. Choose between x264 (faster, larger files) or x265 (slower, smaller files with better compression).",
        "<i>Send 'x264' for H.264/AVC encoding or 'x265' for H.265/HEVC encoding. x265 provides better compression but takes longer to encode.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_ENCODE_PRESET": (
        "String",
        "Set the encoding preset for videos. Available options: ultrafast, superfast, veryfast, faster, fast, medium, slow, slower, veryslow.",
        "<i>Send your preferred encoding preset (e.g., medium). The slower the preset, the better the quality and smaller the file size, but it will take longer to encode.</i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_ENCODE_QUALITY": (
        "String",
        "Set the target video quality/resolution for encoding. Select from predefined quality settings: 1080p, 720p, 480p, 360p, or custom.",
        "<i>Send your desired video quality (e.g., 1080p, 720p, 480p, 360p, or custom). Each quality setting has optimized encoding parameters.</i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_ENCODE_CRF": (
        "Integer or 'original'",
        "Set the Constant Rate Factor (CRF) for video encoding. Range: 0-51. You can also send 'original' to keep the original video stream (copy) when no scaling is applied.",
        "<i>Send a CRF value (e.g., 23). Lower = better quality (bigger size). Recommended: 18-28. Or send 'original' to copy the source video when quality is 'Original' (no scaling).</i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_ENCODE_AUDIO_BITRATE": (
        "String ('128k'|'192k'|...'original'|'copy')",
        "Set the audio mode/bitrate. Use standard bitrates (e.g., 128k). Or 'original' to match the source bitrate. Or 'copy' to copy the original audio stream without re-encoding.",
        "<i>Send 128k/192k/256k/320k etc. Or send 'original' to auto-detect the source bitrate. Or send 'copy' to keep the original audio as-is.</i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_ENCODE_MULTI_RESOLUTION": (
        "Boolean",
        "Enable multi-resolution encoding. When enabled, videos will be encoded in multiple resolutions (1080p, 720p, 480p, 360p) based on the original video quality.",
        "<i>Send true/false to enable or disable multi-resolution encoding. This creates multiple files with different quality levels from the same source video.</i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_ENCODE_RESOLUTION_LIST": (
        "String",
        "Select specific resolutions for multi-resolution encoding. Format: comma-separated list (e.g., '1080p,720p,480p'). Available: 1080p, 720p, 576p, 480p, 360p.",
        "<i>Send comma-separated resolution list (e.g., '1080p,720p,480p' or '720p,360p'). Only these resolutions will be created during multi-resolution encoding.</i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_ENCODE_MULTI_ZIP": (
        "Boolean",
        "Enable multi-zip packaging for multi-resolution encodes. When enabled, all multi-resolution encodes will be packaged into a single zip file instead of separate files.",
        "<i>Send true/false to enable or disable multi-zip packaging. This creates a single zip file containing all encoded resolutions instead of individual files.</i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_CONVERT_ENABLED": (
        "Boolean",
        "Enable or disable video format conversion. When enabled, videos will be converted to your specified format (e.g., MKV to MP4, AVI to MP4).",
        "<i>Send true/false to enable or disable video format conversion. This allows converting between different video container formats.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_CONVERT_FORMAT": (
        "String",
        "Set the target video format for conversion. Available formats: mp4, mkv, avi, mov, webm, flv, m4v.",
        "<i>Send your desired output format (e.g., 'mp4', 'mkv', 'avi'). The video will be converted to this container format.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_CONVERT_CODEC": (
        "String",
        "Set the video codec to use during format conversion. Options: copy (fastest), x264, x265, or auto (smart selection).",
        "<i>Send 'copy' to keep original codec (fastest), 'x264' or 'x265' to re-encode, or 'auto' for smart codec selection based on format.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_CONVERT_QUALITY": (
        "String",
        "Set the video quality for format conversion when re-encoding. Options: original, high, medium, low.",
        "<i>Send 'original' to maintain quality, 'high' for best quality, 'medium' for balanced, or 'low' for smaller files.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_WATERMARK_ENABLED": (
        "Boolean",
        "Enable or disable video watermarking for your uploads. This will add a watermark to videos using your specified settings.",
        "<i>Send true/false to enable or disable video watermarking.</i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_WATERMARK_TEXT": (
        "String",
        "Set the text to be used as watermark on videos. This text will be overlaid on the video.",
        "<i>Send your desired watermark text (e.g., 'My Channel', '@username'). This will be displayed on your videos.</i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_WATERMARK_POSITION": (
        "String",
        "Set the position of the watermark on the video. Available positions: top-left, top-right, top-center, bottom-left, bottom-right, bottom-center, center.",
        "<i>Send your preferred watermark position (e.g., bottom-right, top-left, center). This determines where the watermark appears on the video.</i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_WATERMARK_OPACITY": (
        "Float",
        "Set the opacity/transparency of the watermark. Range: 0.1-1.0, where 0.1 is very transparent and 1.0 is fully opaque.",
        "<i>Send an opacity value (e.g., 0.5, 0.8). Lower values make the watermark more transparent. Recommended: 0.3-0.8.</i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_WATERMARK_TYPE": (
        "String",
        "Set the type of watermark to use. Options: text or image. Text watermarks use your specified text, image watermarks use an uploaded image file.",
        "<i>Send 'text' for text watermark or 'image' for image watermark. Make sure to set the image path if using image watermark.</i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_WATERMARK_IMAGE_PATH": (
        "Photo or Doc",
        "Upload an image file to use as watermark. Only used when watermark type is set to 'image'. Supported formats: PNG, JPG, JPEG, BMP, GIF. PNG with transparency recommended for best results.",
        "<i>Send an image file to use as your watermark. PNG format with transparency is recommended for best results.</i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_WATERMARK_FONT_SIZE": (
        "Integer",
        "Set the font size for text watermarks. Range: 12-72. Larger sizes are more visible but take up more space.",
        "<i>Send a font size value (e.g., 24, 36). Larger values make the text bigger. Recommended: 18-36.</i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_WATERMARK_FONT_COLOR": (
        "String",
        "Set the color of the text watermark. You can use color names (white, black, red, blue) or hex codes (#FFFFFF, #000000).",
        "<i>Send a color name or hex code (e.g., 'white', 'yellow', '#FF0000'). Common options: white, black, yellow, red, blue.</i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_WATERMARK_TEXT_BACKGROUND": (
        "Boolean",
        "Enable or disable background box for text watermarks. Background box improves text visibility but may affect video aesthetics.",
        "<i>Send true/false to enable or disable the background box behind text watermarks.</i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_WATERMARK_DURATION_TYPE": (
        "String",
        "Set when the watermark appears in the video. Options: 'all' (entire video), 'start' (beginning), 'middle' (center), 'end' (ending).",
        "<i>Send 'all', 'start', 'middle', or 'end' to control when the watermark appears during video playback.</i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_WATERMARK_DURATION_SECONDS": (
        "Integer",
        "Set how many seconds the watermark appears (for start/middle/end types). Range: 5-60 seconds. Ignored if type is 'all'.",
        "<i>Send the number of seconds (e.g., 10, 15, 30). This controls how long the watermark shows for start/middle/end positions.</i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_WATERMARK_FONT_PATH": (
        "Font or Doc",
        "Upload a custom font file (.ttf or .otf) to use for text watermarks. Provides unique typography for your watermark text.",
        "<i>Send a font file (.ttf or .otf format) to use as your custom watermark font. Font will be applied to all text watermarks.</i> \n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "INTRO_SUBTITLE_ENABLED": (
        "Boolean",
        "Enable or disable intro subtitle injection (soft mux of styled ASS track at start).",
        "<i>Send true/false to enable or disable intro subtitle soft mux feature.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "INTRO_SUBTITLE_TEXT": (
        "String",
        "The text content for the intro subtitle (will be converted to ASS with optional animation).",
        "<i>Send the text to display in intro subtitle (plain text, no HTML).</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "INTRO_SUBTITLE_STYLE": (
        "typing|fade|static",
        "Animation style: typing (per-character reveal), fade (fade in/out once), static (single cue).",
        "<i>Send style: typing / fade / static.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "INTRO_SUBTITLE_FONT_PATH": (
        "Path",
        "Font file path (TTF/OTF) to embed in container (MKV attachments).",
        "<i>Send path to .ttf/.otf font file or leave blank for default.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "INTRO_SUBTITLE_FONT_SIZE": (
        "Integer",
        "Font size for intro subtitle (default 48).",
        "<i>Send font size integer (e.g., 48).</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "INTRO_SUBTITLE_POSITION": (
        "bottom|center|top",
        "Vertical position of the intro subtitle. Center adds \n\n to push baseline if needed.",
        "<i>Send position: bottom / center / top.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "INTRO_SUBTITLE_COLORS": (
        "List",
        "Pipe or space separated colors for cycling (typing mode). Supports color names or hex codes.",
        "<i>Send colors separated by | or space. You can use color names like: red, blue, green, yellow, white, black, orange, purple, pink, cyan, magenta, lime, gold, silver, brown, gray/grey, violet, indigo, navy, teal, olive, maroon, aqua, fuchsia, coral, salmon, crimson, darkred, darkblue, darkgreen, lightblue, lightgreen, lightgray/lightgrey.\n\nOr use hex codes like: #FF0000 #00FF00 #0000FF\n\nExamples:\n• red|blue|green\n• #FF0000|#00FF00|#0000FF\n• red blue yellow\n• orange purple pink</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "INTRO_SUBTITLE_CHAR_MS": (
        "Integer",
        "Per-character duration in ms for typing style (default 300).",
        "<i>Send integer ms per character (e.g., 300).</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "SHOW_MEDIAINFO_BUTTON": (
        "Boolean",
        "Show or hide the 'Media Info' button under every uploaded file.",
        "<i>Send true/false to enable or disable the Media Info button under uploaded files.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "SS_GRID_ENABLED": (
        "Boolean",
        "Enable or disable the SS Grid feature which shows screenshots in a grid layout",
        "<i>Send true/false to enable or disable the SS Grid feature.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "SS_GRID_COUNT": (
        "",
        "",
        "<i>Send the number of screenshots to take for the SS Grid (1-20 recommended).</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "SS_GRID_LAYOUT": (
        "",
        "",
        "<i>Send the layout for the SS Grid in format widthxheight (e.g., 3x3, 4x4, 2x3).</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "SS_GRID_PDF_MODE": (
        "Boolean",
        "Enable or disable PDF mode for SS Grid to combine all screenshots into a PDF",
        "<i>Send true/false to enable or disable PDF mode for SS Grid.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "SS_GRID_WATERMARK": (
        "",
        "",
        "<i>Send the text to use as watermark on the SS Grid PDF. Send 'None' to disable watermark.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "SS_GRID_PDF_INDIVIDUAL_PAGES": (
        "Boolean",
        "Enable or disable individual screenshot pages in the PDF.",
        "<i>Send true/false to enable or disable individual screenshot pages in the PDF for SS Grid.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "SAMPLE_VIDEO_ENABLED": (
        "Boolean",
        "Enable or disable automatic random sample video generation for leeched videos.",
        "<i>Send true/false to enable or disable automatic sample video generation. When enabled, the bot will create random sample clip(s) from each video.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "SAMPLE_VIDEO_COUNT": (
        "Integer (1-10)",
        "Number of random sample clips to generate per video when sample video feature is enabled.",
        "<i>Send a number between 1 and 10 indicating how many random sample clips you want per video.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "SAMPLE_VIDEO_DURATION": (
        "Integer (seconds)",
        "Duration in seconds of each random sample clip (e.g., 30, 60, 90). Must be less than total video duration.",
        "<i>Send the duration in seconds for each sample clip (recommended: 30-120).</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "SAMPLE_VIDEO_SEPARATE": (
        "Boolean",
        "Generate separate sample clip files instead of merging into one sample video.",
        "<i>Send true/false to enable separate sample clips. When enabled, each random segment will be its own SAMPLE_*. file instead of being concatenated.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_MERGE_ENABLED": (
        "Boolean",
        "Enable or disable the Video Merge feature which allows merging multiple video files into one.",
        "<i>Send true/false to enable or disable the Video Merge feature.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_AUDIO_MERGE_ENABLED": (
        "Boolean",
        "Enable or disable the Video+Audio Merge feature which allows merging video files with separate audio tracks.",
        "<i>Send true/false to enable or disable the Video+Audio Merge feature.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_SUBTITLE_MERGE_ENABLED": (
        "Boolean",
        "Enable or disable the Video+Subtitle Merge feature which allows merging video files with separate subtitle files.",
        "<i>Send true/false to enable or disable the Video+Subtitle Merge feature.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_HARDSUB_ENABLED": (
        "Boolean",
        "Enable or disable the Video Hardsub feature which permanently burns subtitle files into video.",
        "<i>Send true/false to enable or disable the Video Hardsub feature. This creates a video with subtitles permanently embedded.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_HARDSUB_STYLE": (
        "String",
        "Set the subtitle style for hardsub. Options: default, bold, outline, shadow, glow. Default style uses the original subtitle formatting.",
        "<i>Send subtitle style (default, bold, outline, shadow, glow). This affects how burned-in subtitles look on the video.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_HARDSUB_FONT_SIZE": (
        "Integer (8-72)",
        "Set the font size for burned-in subtitles. Range: 8-72 pixels. Default is 20.",
        "<i>Send a number between 8 and 72 for subtitle font size. Larger numbers make subtitles bigger.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_HARDSUB_FONT_NAME": (
        "String",
        "Set the font family for burned-in subtitles. Common fonts: Arial, Times, Helvetica, Verdana, or system font path.",
        "<i>Send font name (e.g., Arial, Times, Helvetica) or path to custom font file for burned-in subtitles.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_STREAM_EXTRACT_ENABLED": (
        "Boolean",
        "Enable or disable the Stream Extract feature which allows extracting audio tracks and subtitles from video files.",
        "<i>Send true/false to enable or disable the Stream Extract feature.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIDEO_TRIM_ENABLED": (
        "Boolean",
        "Enable or disable the Video Trim feature to cut a portion of the video between start & end times.",
        "<i>Send true/false to enable or disable the Video Trim feature. When enabled you can select it via -ft and will be prompted for times.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "STREAM_REMOVE_ENABLED": (
        "Boolean",
        "Enable or disable the Stream Remove feature which allows removing selected audio tracks and subtitles from video files.",
        "<i>Send true/false to enable or disable the Stream Remove feature.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "STREAM_SWAP_ENABLED": (
        "Boolean",
        "Enable or disable the Stream Swap feature which allows reordering audio and subtitle tracks in video files.",
        "<i>Send true/false to enable or disable the Stream Swap feature.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "KEEP_MERGE_SOURCE_FILES": (
        "Boolean",
        "Keep and upload the original source files when merging videos.",
        "<i>Send true/false to enable or disable uploading source files when using the Video Merge feature.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "CUSTOM_FILENAME": (
        "String",
        "Set a custom filename template for all processed files. Use {name} for original filename without extension, {ext} for original extension.",
        "<i>Send your custom filename template (e.g., 'MyVideo_{name}', 'Channel_{name}_HD', '{name}_Watermarked'). Use {name} for original name and {ext} for extension.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "LEECH_DUMP_CHAT": (
        "Integer",
        "Chat ID where leech completions will be forwarded. This allows you to automatically send completed downloads to a specific chat.",
        "<i>Send chat ID (with -100 prefix for supergroups) to set leech dump destination.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
    "MIRROR_DUMP_CHAT": (
        "Integer",
        "Chat ID where mirror completions will be forwarded. This allows you to automatically send mirror links to a specific chat.",
        "<i>Send chat ID (with -100 prefix for supergroups) to set mirror dump destination.</i>\n╰<b>Time Left :</b> <code>60 sec</code>",
    ),
}


async def get_user_settings(from_user, stype="main"):
    user_id = from_user.id
    user_name = from_user.mention(style="html")
    buttons = ButtonMaker()
    rclone_conf = f"rclone/{user_id}.conf"
    token_pickle = f"tokens/{user_id}.pickle"
    user_dict = user_data.get(user_id, {})

    if stype == "main":
        buttons.data_button(
            "General Settings", f"userset {user_id} general", position="header"
        )
        buttons.data_button("Common Tools", f"userset {user_id} common_tools")
        buttons.data_button("DUMPS", f"userset {user_id} dumps")
        buttons.data_button("Mirror Settings", f"userset {user_id} mirror")
        buttons.data_button("Leech Settings", f"userset {user_id} leech")
        buttons.data_button("FFMPEG Tools", f"userset {user_id} ffset")
        buttons.data_button(
            "Advanced Settings", f"userset {user_id} advanced", position="l_body"
        )
        buttons.data_button("Auto Leech/Mirror", f"userset {user_id} auto_process")

        if user_dict and any(
            key in user_dict
            for key in list(user_settings_text.keys())
            + [
                "USER_TOKENS",
                "AS_DOCUMENT",
                "EQUAL_SPLITS",
                "MEDIA_GROUP",
                "STOP_DUPLICATE",
                "DEFAULT_UPLOAD",
            ]
        ):
            buttons.data_button(
                "Reset All", f"userset {user_id} confirm_reset_all", position="footer"
            )
        buttons.data_button("Close", f"userset {user_id} close", position="footer")

        text = f"""〄 <b>User Settings :</b>

╭<b>Name</b> » {user_name}
┊<b>UserID</b> » #ID{user_id}
┊<b>Username</b> » @{from_user.username}
┊<b>Telegram DC</b> » {from_user.dc_id}
╰<b>Telegram Lang</b> » {Language.get(lc).display_name() if (lc := from_user.language_code) else "N/A"}"""

        btns = buttons.build_menu(2)

    elif stype == "general":
        if user_dict.get("DEFAULT_UPLOAD", ""):
            default_upload = user_dict["DEFAULT_UPLOAD"]
        elif "DEFAULT_UPLOAD" not in user_dict:
            default_upload = Config.DEFAULT_UPLOAD

        if default_upload == "gd":
            du = "GDRIVE API"
            dur1 = "RCLONE"
            dur2 = "GOFILE"
        elif default_upload == "gofile":
            du = "GOFILE"
            dur1 = "GDRIVE API"
            dur2 = "RCLONE"
        else:
            du = "RCLONE"
            dur1 = "GDRIVE API"
            dur2 = "GOFILE"

        buttons.data_button(
            f"Swap to {dur1} Mode",
            f"userset {user_id} {default_upload}_gd general"
            if default_upload != "gd"
            else f"userset {user_id} {default_upload}_rc general",
        )
        buttons.data_button(
            f"Swap to {dur2} Mode",
            f"userset {user_id} {default_upload}_gofile general"
            if default_upload != "gofile"
            else f"userset {user_id} {default_upload}_rc general",
        )

        user_tokens = user_dict.get("USER_TOKENS", False)
        tr = "USER" if user_tokens else "OWNER"
        trr = "OWNER" if user_tokens else "USER"
        buttons.data_button(
            f"Swap to {trr} token/config",
            f"userset {user_id} tog USER_TOKENS {'f' if user_tokens else 't'}",
        )

        # Auto Leech/Mirror button moved to main menu
        buttons.data_button("Back", f"userset {user_id} back", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(1)

        text = f"""〄 <b>General Settings :</b>
╭<b>Name</b> » {user_name}
┊
┊<b>Default Upload Package</b> » <b>{du}</b>
╰<b>Default Usage Mode</b> » <b>{tr}'s</b> token/config
"""

    elif stype == "common_tools":
        thumbpath = f"thumbnails/{user_id}.jpg"
        buttons.data_button("Thumbnail", f"userset {user_id} menu THUMBNAIL")
        thumbmsg = "Exists" if await aiopath.exists(thumbpath) else "Not Exists"

        # Embed user image as cover toggle
        embed_cover = user_dict.get("EMBED_USER_IMAGE_AS_COVER", False)
        buttons.data_button(
            "✓ Thumb as Cover" if embed_cover else "Thumb as Cover",
            f"userset {user_id} tog EMBED_USER_IMAGE_AS_COVER {'f' if embed_cover else 't'}",
        )

        # Auto Thumbnail toggle button
        buttons.data_button(
            "✓ Auto Thumbnail"
            if user_dict.get("AUTO_THUMBNAIL", False)
            else "Auto Thumbnail",
            f"userset {user_id} tog AUTO_THUMBNAIL {'f' if user_dict.get('AUTO_THUMBNAIL', False) else 't'}",
        )

        # Universal Prefix/Suffix (applies to both mirror and leech)
        buttons.data_button("Prefix", f"userset {user_id} menu FILENAME_PREFIX")
        if user_dict.get("FILENAME_PREFIX", False):
            fprefix = user_dict["FILENAME_PREFIX"]
        elif user_dict.get("LEECH_PREFIX", False):  # Migration support
            fprefix = user_dict["LEECH_PREFIX"]
        else:
            fprefix = "Not Set"

        buttons.data_button("Suffix", f"userset {user_id} menu FILENAME_SUFFIX")
        if user_dict.get("FILENAME_SUFFIX", False):
            fsuffix = user_dict["FILENAME_SUFFIX"]
        elif user_dict.get("LEECH_SUFFIX", False):  # Migration support
            fsuffix = user_dict["LEECH_SUFFIX"]
        else:
            fsuffix = "Not Set"

        # Remove patterns
        buttons.data_button(
            "Rem-Name", f"userset {user_id} menu FILENAME_REMOVE_PATTERNS"
        )
        if user_dict.get("FILENAME_REMOVE_PATTERNS", False):
            remove_patterns = user_dict["FILENAME_REMOVE_PATTERNS"]
        else:
            remove_patterns = "None"

        # Auto Rename submenu
        buttons.data_button("Auto Rename", f"userset {user_id} autorename")

        # Thumbnail Layout
        buttons.data_button(
            "Thumbnail Layout", f"userset {user_id} menu THUMBNAIL_LAYOUT"
        )
        if user_dict.get("THUMBNAIL_LAYOUT", False):
            thumb_layout = user_dict["THUMBNAIL_LAYOUT"]
        elif "THUMBNAIL_LAYOUT" not in user_dict and Config.THUMBNAIL_LAYOUT:
            thumb_layout = Config.THUMBNAIL_LAYOUT
        else:
            thumb_layout = "None"

        # SS Grid Settings
        buttons.data_button("SS Grid Settings", f"userset {user_id} ssgrid")

        # Sample Video Settings
        buttons.data_button("Sample Video", f"userset {user_id} samplevideo")

        buttons.data_button("Back", f"userset {user_id} back", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(2)

        # Get display values
        auto_thumb_msg = (
            "Enabled" if user_dict.get("AUTO_THUMBNAIL", False) else "Disabled"
        )
        ss_grid_msg = (
            "Enabled" if user_dict.get("SS_GRID_ENABLED", False) else "Disabled"
        )
        sample_video_msg = (
            "Enabled" if user_dict.get("SAMPLE_VIDEO_ENABLED", False) else "Disabled"
        )

        text = f"""〄 <b>Common Tools Settings :</b>
╭<b>Name</b> » {user_name}
┊
┊Custom Thumbnail » <b>{thumbmsg}</b>
┊Thumb as Cover » <b>{"Enabled" if embed_cover else "Disabled"}</b>
┊Auto Thumbnail (TMDB/IMDB) » <b>{auto_thumb_msg}</b>
┊Thumbnail Layout » <b>{thumb_layout}</b>
┊Prefix » <code>{escape(fprefix)}</code>
┊Suffix » <code>{escape(fsuffix)}</code>
┊Rem-name» <code>{escape(remove_patterns)}</code>
┊Auto Rename » <b>{"Enabled" if user_dict.get("AUTO_RENAME", False) else "Disabled"}</b>
┊SS Grid » <b>{ss_grid_msg}</b>
╰Sample Video » <b>{sample_video_msg}</b>

<i>These settings apply to both Mirror and Leech operations</i>"""

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
            "MIRROR_DUMP_CHAT" not in user_dict and Config.MIRROR_DUMP_CHAT
            if hasattr(Config, "MIRROR_DUMP_CHAT")
            else None
        ):
            mirror_dest = Config.MIRROR_DUMP_CHAT
        else:
            mirror_dest = "None"

        buttons.data_button("Back", f"userset {user_id} back", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(1)

        text = f"""〄 <b>DUMPS Settings :</b>
╭<b>Name</b> » {user_name}
┊
┊<b>Leech Destination</b> » <code>{leech_dest}</code>
┊<b>Mirror Destination</b> » <code>{mirror_dest}</code>
┊
┊<i>Configure separate destinations for Leech and Mirror operations</i>
┊<i>• Leech Destination: Where leeched files are sent</i>
╰<i>• Mirror Destination: Where mirror links are posted</i>"""

    elif stype == "leech":
        # Updated leech settings with destination moved to DUMPS section
        buttons.data_button("Leech Caption", f"userset {user_id} menu LEECH_CAPTION")
        if user_dict.get("LEECH_CAPTION", False):
            lcap = user_dict["LEECH_CAPTION"]
        elif "LEECH_CAPTION" not in user_dict and Config.LEECH_CAPTION:
            lcap = Config.LEECH_CAPTION
        else:
            lcap = "Not Exists"

        # Leech-specific toggles
        if (
            user_dict.get("AS_DOCUMENT", False)
            or "AS_DOCUMENT" not in user_dict
            and Config.AS_DOCUMENT
        ):
            ltype = "DOCUMENT"
            buttons.data_button("Send As Media", f"userset {user_id} tog AS_DOCUMENT f")
        else:
            ltype = "MEDIA"
            buttons.data_button(
                "Send As Document", f"userset {user_id} tog AS_DOCUMENT t"
            )

        if (
            user_dict.get("MEDIA_GROUP", False)
            or "MEDIA_GROUP" not in user_dict
            and Config.MEDIA_GROUP
        ):
            buttons.data_button(
                "Disable Media Group", f"userset {user_id} tog MEDIA_GROUP f"
            )
            media_group = "Enabled"
        else:
            buttons.data_button(
                "Enable Media Group", f"userset {user_id} tog MEDIA_GROUP t"
            )
            media_group = "Disabled"

        # Add Media Info Button toggle
        if user_dict.get("SHOW_MEDIAINFO_BUTTON", True):
            buttons.data_button(
                "Hide Media Info Button",
                f"userset {user_id} tog SHOW_MEDIAINFO_BUTTON f",
            )
            mediainfo_msg = "Shown"
        else:
            buttons.data_button(
                "Show Media Info Button",
                f"userset {user_id} tog SHOW_MEDIAINFO_BUTTON t",
            )
            mediainfo_msg = "Hidden"

        # File split size for leech operations
        buttons.data_button(
            "File Split Size", f"userset {user_id} menu LEECH_SPLIT_SIZE"
        )
        if user_dict.get("LEECH_SPLIT_SIZE", False):
            split_size = user_dict["LEECH_SPLIT_SIZE"]
        else:
            split_size = Config.LEECH_SPLIT_SIZE

        # Equal splits toggle for leech operations
        if (
            user_dict.get("EQUAL_SPLITS", False)
            or "EQUAL_SPLITS" not in user_dict
            and Config.EQUAL_SPLITS
        ):
            buttons.data_button(
                "✓ Equal Splits", f"userset {user_id} tog EQUAL_SPLITS f"
            )
            equal_splits = "Enabled"
        else:
            buttons.data_button("Equal Splits", f"userset {user_id} tog EQUAL_SPLITS t")
            equal_splits = "Disabled"

        buttons.data_button("Back", f"userset {user_id} back", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(2)

        text = f"""〄 <b>Leech Settings :</b>
╭<b>Name</b> » {user_name}
┊
┊Leech Type » <b>{ltype}</b>
┊Media Group » <b>{media_group}</b>
┊Leech Caption » <code>{escape(lcap)}</code>
┊Media Info Button » <b>{mediainfo_msg}</b>
┊File Split Size » <b>{get_readable_file_size(split_size)}</b>
┊Equal Splits » <b>{equal_splits}</b>
┊
╰Sequential Processing » <b>Always Enabled</b>  """

    elif stype == "rclone":
        buttons.data_button("Rclone Config", f"userset {user_id} menu RCLONE_CONFIG")
        buttons.data_button(
            "Default Rclone Path", f"userset {user_id} menu RCLONE_PATH"
        )
        buttons.data_button("Rclone Flags", f"userset {user_id} menu RCLONE_FLAGS")

        buttons.data_button("Back", f"userset {user_id} back mirror", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")

        rccmsg = "Exists" if await aiopath.exists(rclone_conf) else "Not Exists"
        if user_dict.get("RCLONE_PATH", False):
            rccpath = user_dict["RCLONE_PATH"]
        elif Config.RCLONE_PATH:
            rccpath = Config.RCLONE_PATH
        else:
            rccpath = "None"
        btns = buttons.build_menu(1)

        if user_dict.get("RCLONE_FLAGS", False):
            rcflags = user_dict["RCLONE_FLAGS"]
        elif "RCLONE_FLAGS" not in user_dict and Config.RCLONE_FLAGS:
            rcflags = Config.RCLONE_FLAGS
        else:
            rcflags = "None"

        text = f"""〄 <b>RClone Settings :</b>
╭<b>Name</b> » {user_name}
┊
┊<b>Rclone Config</b> » <b>{rccmsg}</b>
┊<b>Rclone Flags</b> » <code>{rcflags}</code>
╰<b>Rclone Path</b> » <code>{rccpath}</code>"""

    elif stype == "gdrive":
        buttons.data_button("token.pickle", f"userset {user_id} menu TOKEN_PICKLE")
        buttons.data_button("Default Gdrive ID", f"userset {user_id} menu GDRIVE_ID")
        buttons.data_button("Index URL", f"userset {user_id} menu INDEX_URL")
        if (
            user_dict.get("STOP_DUPLICATE", False)
            or "STOP_DUPLICATE" not in user_dict
            and Config.STOP_DUPLICATE
        ):
            buttons.data_button(
                "Disable Stop Duplicate", f"userset {user_id} tog STOP_DUPLICATE f"
            )
            sd_msg = "Enabled"
        else:
            buttons.data_button(
                "Enable Stop Duplicate",
                f"userset {user_id} tog STOP_DUPLICATE t",
                "l_body",
            )
            sd_msg = "Disabled"
        buttons.data_button("Back", f"userset {user_id} back mirror", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")

        tokenmsg = "Exists" if await aiopath.exists(token_pickle) else "Not Exists"
        if user_dict.get("GDRIVE_ID", False):
            gdrive_id = user_dict["GDRIVE_ID"]
        elif GDID := Config.GDRIVE_ID:
            gdrive_id = GDID
        else:
            gdrive_id = "None"
        index = user_dict["INDEX_URL"] if user_dict.get("INDEX_URL", False) else "None"
        btns = buttons.build_menu(2)

        text = f"""〄 <b>GDrive Tools Settings :</b>
╭<b>Name</b> » {user_name}
┊
┊<b>Gdrive Token</b> » <b>{tokenmsg}</b>
┊<b>Gdrive ID</b> » <code>{gdrive_id}</code>
┊<b>Index URL</b> » <code>{index}</code>
╰<b>Stop Duplicate</b> » <b>{sd_msg}</b>"""
    elif stype == "gofile":
        buttons.data_button("GoFile Token", f"userset {user_id} menu GOFILE_TOKEN")
        buttons.data_button(
            "GoFile Folder ID", f"userset {user_id} menu GOFILE_FOLDER_ID"
        )
        buttons.data_button("Back", f"userset {user_id} back mirror", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")

        gofile_token_status = (
            "Exists" if user_dict.get("GOFILE_TOKEN") else "Not Exists"
        )
        if user_dict.get("GOFILE_FOLDER_ID", False):
            gofile_folder = user_dict["GOFILE_FOLDER_ID"]
        else:
            gofile_folder = "Root Folder"

        btns = buttons.build_menu(2)

        text = f"""〄 <b>GoFile Tools Settings :</b>
╭<b>Name</b> » {user_name}
┊
┊<b>GoFile Token</b> » <b>{gofile_token_status}</b>
╰<b>GoFile Folder</b> » <code>{gofile_folder}</code>"""
    elif stype == "mirror":
        buttons.data_button("RClone Tools", f"userset {user_id} rclone")
        rccmsg = "Exists" if await aiopath.exists(rclone_conf) else "Not Exists"
        if user_dict.get("RCLONE_PATH", False):
            rccpath = user_dict["RCLONE_PATH"]
        elif RP := Config.RCLONE_PATH:
            rccpath = RP
        else:
            rccpath = "None"

        buttons.data_button("GDrive Tools", f"userset {user_id} gdrive")
        tokenmsg = "Exists" if await aiopath.exists(token_pickle) else "Not Exists"
        if user_dict.get("GDRIVE_ID", False):
            gdrive_id = user_dict["GDRIVE_ID"]
        elif GI := Config.GDRIVE_ID:
            gdrive_id = GI
        else:
            gdrive_id = "None"

        buttons.data_button("GoFile Tools", f"userset {user_id} gofile")
        gofile_token_status = (
            "Exists" if user_dict.get("GOFILE_TOKEN") else "Not Exists"
        )
        if user_dict.get("GOFILE_FOLDER_ID", False):
            gofile_folder = user_dict["GOFILE_FOLDER_ID"]
        else:
            gofile_folder = "Root Folder"

        index = user_dict["INDEX_URL"] if user_dict.get("INDEX_URL", False) else "None"
        if (
            user_dict.get("STOP_DUPLICATE", False)
            or "STOP_DUPLICATE" not in user_dict
            and Config.STOP_DUPLICATE
        ):
            sd_msg = "Enabled"
        else:
            sd_msg = "Disabled"

        buttons.data_button("YT Tools", f"userset {user_id} yttools")
        buttons.data_button("Back", f"userset {user_id} back", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(1)

        text = f"""〄 <b>Mirror Settings :</b>
╭<b>Name</b> » {user_name}
┊
┊<b>Rclone Config</b> » <b>{rccmsg}</b>
┊<b>Rclone Path</b> » <code>{rccpath}</code>
┊<b>Gdrive Token</b> » <b>{tokenmsg}</b>
┊<b>Gdrive ID</b> » <code>{gdrive_id}</code>
┊<b>Index Link</b> » <code>{index}</code>
┊<b>GoFile Token</b> » <b>{gofile_token_status}</b>
┊<b>GoFile Folder</b> » <code>{gofile_folder}</code>
╰<b>Stop Duplicate</b> » <b>{sd_msg}</b>
"""

    elif stype == "ffset":
        # Get status of key features to determine which buttons to show
        video_encode_enabled = user_dict.get("VIDEO_ENCODE_ENABLED", True)
        watermark_enabled = user_dict.get("VIDEO_WATERMARK_ENABLED", True)
        intro_enabled = user_dict.get("INTRO_SUBTITLE_ENABLED", True)

        # Use our special FFmpeg button maker
        buttons = FFmpegButtonMaker()

        # First row (2 buttons)
        has_ffmpeg_cmds = bool(user_dict.get("FFMPEG_CMDS", False))
        buttons.data_button(
            f"{'✓ ' if has_ffmpeg_cmds else ''}FFMPEG CMD",
            f"userset {user_id} menu FFMPEG_CMDS",
            "header",
        )

        has_metadata = bool(user_dict.get("METADATA_SETTINGS", False))
        buttons.data_button(
            f"{'✓ ' if has_metadata else ''}MegaMetaData",
            f"userset {user_id} menu METADATA_SETTINGS",
            "header",
        )

        # Second row (Merge operations)
        video_merge_enabled = user_dict.get("VIDEO_MERGE_ENABLED", True)
        buttons.data_button(
            f"{'✓ ' if video_merge_enabled else ''}Vid+Vid",
            f"userset {user_id} tog VIDEO_MERGE_ENABLED {'f' if video_merge_enabled else 't'}",
            "f_body",
        )

        video_audio_merge_enabled = user_dict.get("VIDEO_AUDIO_MERGE_ENABLED", True)
        buttons.data_button(
            f"{'✓ ' if video_audio_merge_enabled else ''}Vid+Aud",
            f"userset {user_id} tog VIDEO_AUDIO_MERGE_ENABLED {'f' if video_audio_merge_enabled else 't'}",
            "f_body",
        )

        video_subtitle_merge_enabled = user_dict.get(
            "VIDEO_SUBTITLE_MERGE_ENABLED", True
        )
        buttons.data_button(
            f"{'✓ ' if video_subtitle_merge_enabled else ''}Vid+Sub",
            f"userset {user_id} tog VIDEO_SUBTITLE_MERGE_ENABLED {'f' if video_subtitle_merge_enabled else 't'}",
            "f_body",
        )

        video_hardsub_enabled = user_dict.get("VIDEO_HARDSUB_ENABLED", True)
        buttons.data_button(
            f"{'✓ ' if video_hardsub_enabled else ''}Hardsub",
            f"userset {user_id} tog VIDEO_HARDSUB_ENABLED {'f' if video_hardsub_enabled else 't'}",
            "f_body",
        )

        # Stream operations row
        stream_swap_enabled = user_dict.get("STREAM_SWAP_ENABLED", True)
        buttons.data_button(
            f"{'✓ ' if stream_swap_enabled else ''}StreamSwap",
            f"userset {user_id} tog STREAM_SWAP_ENABLED {'f' if stream_swap_enabled else 't'}",
        )

        stream_extract_enabled = user_dict.get("VIDEO_STREAM_EXTRACT_ENABLED", True)
        buttons.data_button(
            f"{'✓ ' if stream_extract_enabled else ''}Extract",
            f"userset {user_id} tog VIDEO_STREAM_EXTRACT_ENABLED {'f' if stream_extract_enabled else 't'}",
        )

        stream_remove_enabled = user_dict.get("STREAM_REMOVE_ENABLED", True)
        buttons.data_button(
            f"{'✓ ' if stream_remove_enabled else ''}Remove",
            f"userset {user_id} tog STREAM_REMOVE_ENABLED {'f' if stream_remove_enabled else 't'}",
        )

        # Submenu buttons row
        # Encode submenu button
        encode_status_icon = "✓ " if video_encode_enabled else ""
        buttons.data_button(
            f"{encode_status_icon}Encode", f"userset {user_id} ffsubmenu encode"
        )

        # Convert submenu button
        convert_enabled = user_dict.get("VIDEO_CONVERT_ENABLED", False)
        convert_status_icon = "✓ " if convert_enabled else ""
        buttons.data_button(
            f"{convert_status_icon}Convert", f"userset {user_id} ffsubmenu convert"
        )

        # Watermark submenu button
        watermark_status_icon = "✓ " if watermark_enabled else ""
        buttons.data_button(
            f"{watermark_status_icon}Watermark",
            f"userset {user_id} ffsubmenu watermark",
        )

        # Intro Sub submenu button
        intro_status_icon = "✓ " if intro_enabled else ""
        buttons.data_button(
            f"{intro_status_icon}Sub Intro", f"userset {user_id} ffsubmenu intro"
        )

        # Hardsub submenu button
        hardsub_enabled = user_dict.get("VIDEO_HARDSUB_ENABLED", True)
        hardsub_status_icon = "✓ " if hardsub_enabled else ""
        buttons.data_button(
            f"{hardsub_status_icon}Hardsub", f"userset {user_id} ffsubmenu hardsub"
        )

        # Trim button
        video_trim_enabled = user_dict.get("VIDEO_TRIM_ENABLED", True)
        buttons.data_button(
            f"{'✓ ' if video_trim_enabled else ''}Trim",
            f"userset {user_id} tog VIDEO_TRIM_ENABLED {'f' if video_trim_enabled else 't'}",
        )

        # Keep Source row
        keep_source_enabled = user_dict.get("KEEP_MERGE_SOURCE_FILES", False)
        buttons.data_button(
            f"{'✓ ' if keep_source_enabled else ''}Keep Source",
            f"userset {user_id} tog KEEP_MERGE_SOURCE_FILES {'f' if keep_source_enabled else 't'}",
            "l_body",
        )

        # Custom Filename
        has_custom_filename = bool(user_dict.get("CUSTOM_FILENAME", ""))
        buttons.data_button(
            f"{'✓ ' if has_custom_filename else ''}Rename",
            f"userset {user_id} menu CUSTOM_FILENAME",
        )

        # Footer navigation
        buttons.data_button("Back", f"userset {user_id} back", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")

        # Build the main FFmpeg menu
        btns = buttons.build_ffmpeg_menu(
            video_encode_enabled=video_encode_enabled,
            watermark_enabled=watermark_enabled,
            intro_enabled=intro_enabled,
        )

        # Get display values for status
        if user_dict.get("FFMPEG_CMDS", False):
            ffc = user_dict["FFMPEG_CMDS"]
        elif "FFMPEG_CMDS" not in user_dict and Config.FFMPEG_CMDS:
            ffc = Config.FFMPEG_CMDS
        else:
            ffc = "<b>Not Exists</b>"

        if user_dict.get("METADATA_SETTINGS", False):
            meta = user_dict["METADATA_SETTINGS"]
        else:
            meta = "<b>Not Exists</b>"

        # Get status values for display
        video_encode = "Enabled" if video_encode_enabled else "Disabled"
        video_convert = (
            "Enabled" if user_dict.get("VIDEO_CONVERT_ENABLED", False) else "Disabled"
        )
        video_watermark = "Enabled" if watermark_enabled else "Disabled"
        intro_subtitle = "Enabled" if intro_enabled else "Disabled"
        video_trim_status = (
            "Enabled" if user_dict.get("VIDEO_TRIM_ENABLED", True) else "Disabled"
        )
        keep_source = (
            "Enabled" if user_dict.get("KEEP_MERGE_SOURCE_FILES", False) else "Disabled"
        )

        # Get merge status values
        video_merge = (
            "Enabled" if user_dict.get("VIDEO_MERGE_ENABLED", True) else "Disabled"
        )
        video_audio_merge = (
            "Enabled"
            if user_dict.get("VIDEO_AUDIO_MERGE_ENABLED", True)
            else "Disabled"
        )
        video_subtitle_merge = (
            "Enabled"
            if user_dict.get("VIDEO_SUBTITLE_MERGE_ENABLED", True)
            else "Disabled"
        )
        video_hardsub = (
            "Enabled" if user_dict.get("VIDEO_HARDSUB_ENABLED", True) else "Disabled"
        )

        # Get stream status values
        stream_extract = (
            "Enabled"
            if user_dict.get("VIDEO_STREAM_EXTRACT_ENABLED", True)
            else "Disabled"
        )
        stream_swap = (
            "Enabled" if user_dict.get("STREAM_SWAP_ENABLED", True) else "Disabled"
        )
        stream_remove = (
            "Enabled" if user_dict.get("STREAM_REMOVE_ENABLED", True) else "Disabled"
        )

        # Get custom filename
        custom_filename = user_dict.get("CUSTOM_FILENAME", "")
        custom_filename_display = custom_filename if custom_filename else "Not Set"

        if isinstance(ffc, dict):
            ffc = "\n" + "\n".join(
                [
                    f"{no}. <b>{key}</b>: <code>{value[0]}</code>"
                    for no, (key, value) in enumerate(ffc.items(), start=1)
                ]
            )

        if isinstance(meta, dict):
            meta = "\n" + "\n".join(
                [
                    f"{no}. <b>{key}</b>: <code>{value}</code>"
                    for no, (key, value) in enumerate(meta.items(), start=1)
                ]
            )

        text = f"""〄 <b>FF Settings :</b>
╭<b>Name</b> » {user_name}
┊
┊<b>CORE</b>
┊<b>FFmpeg</b> » {ffc} | <b>Metadata</b> » {meta}
┊
┊<b>MERGE</b> 
┊<b>Video</b> » <b>{video_merge}</b> | <b>V+A</b> » <b>{video_audio_merge}</b> \n┊ <b>V+S</b> » <b>{video_subtitle_merge}</b> | <b>Hardsub</b> » <b>{video_hardsub}</b>
┊
┊<b>STREAM</b> 
┊<b>Extract</b> » <b>{stream_extract}</b> | <b>Swap</b> » <b>{stream_swap}</b> \n┊ <b>Remove</b> » <b>{stream_remove}</b>
┊
┊<b>ENCODE</b>  » <b>{video_encode}</b>
┊<b>CONVERT</b> » <b>{video_convert}</b>
┊<b>WATERMARK</b> » <b>{video_watermark}</b> | <b>Intro Sub</b> » <b>{intro_subtitle}</b>
┊<b>Trim</b> » <b>{video_trim_status}</b>
┊
┊<b>Custom Filename</b> » <b>{custom_filename_display}</b>
╰<b>Keep Source</b> » <b>{keep_source}</b>"""

    elif stype == "advanced":
        buttons.data_button(
            "Excluded Extensions", f"userset {user_id} menu EXCLUDED_EXTENSIONS"
        )
        if user_dict.get("EXCLUDED_EXTENSIONS", False):
            ex_ex = user_dict["EXCLUDED_EXTENSIONS"]
        elif "EXCLUDED_EXTENSIONS" not in user_dict:
            ex_ex = excluded_extensions
        else:
            ex_ex = "None"

        if ex_ex != "None":
            ex_ex = ", ".join(ex_ex)

        ns_msg = (
            f"<code>{swap}</code>"
            if (swap := user_dict.get("NAME_SWAP", False))
            else "<b>Not Exists</b>"
        )
        buttons.data_button("Name Swap", f"userset {user_id} menu NAME_SWAP")

        buttons.data_button("YT-DLP Options", f"userset {user_id} menu YT_DLP_OPTIONS")
        if user_dict.get("YT_DLP_OPTIONS", False):
            ytopt = user_dict["YT_DLP_OPTIONS"]
        elif "YT_DLP_OPTIONS" not in user_dict and Config.YT_DLP_OPTIONS:
            ytopt = Config.YT_DLP_OPTIONS
        else:
            ytopt = "None"

        upload_paths = user_dict.get("UPLOAD_PATHS", {})
        if not upload_paths and "UPLOAD_PATHS" not in user_dict and Config.UPLOAD_PATHS:
            upload_paths = Config.UPLOAD_PATHS
        else:
            upload_paths = "None"
        buttons.data_button("Upload Paths", f"userset {user_id} menu UPLOAD_PATHS")

        user_session = user_dict.get("USER_SESSION_STRING", "")
        if user_session:
            session_display = "✅ Set"
        else:
            session_display = "❌ Not Set"
        buttons.data_button(
            "User Session", f"userset {user_id} menu USER_SESSION_STRING"
        )

        buttons.data_button("Back", f"userset {user_id} back", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(1)

        text = f"""〄 <b>Advanced Settings :</b>
╭<b>Name</b> » {user_name}
┊
┊<b>Name Swaps</b> » {ns_msg}
┊<b>Excluded Extensions</b> » <code>{ex_ex}</code>
┊<b>Upload Paths</b> » <b>{upload_paths}</b>
┊<b>YT-DLP Options</b> » <code>{ytopt}</code>
╰<b>User Session</b> » <b>{session_display}</b>"""
    elif stype == "yttools":
        buttons.data_button("YT Description", f"userset {user_id} menu YT_DESP")
        yt_desp_val = user_dict.get(
            "YT_DESP", Config.YT_DESP if hasattr(Config, "YT_DESP") else "Not Set"
        )

        buttons.data_button("YT Tags", f"userset {user_id} menu YT_TAGS")
        yt_tags_val = user_dict.get(
            "YT_TAGS",
            Config.YT_TAGS if hasattr(Config, "YT_TAGS") else "Not Set (Uses Default)",
        )
        if isinstance(yt_tags_val, list):
            yt_tags_val = ",".join(yt_tags_val)

        buttons.data_button("YT Category ID", f"userset {user_id} menu YT_CATEGORY_ID")
        yt_cat_id_val = user_dict.get(
            "YT_CATEGORY_ID",
            Config.YT_CATEGORY_ID
            if hasattr(Config, "YT_CATEGORY_ID")
            else "Not Set (Uses Default)",
        )

        buttons.data_button(
            "YT Privacy Status", f"userset {user_id} menu YT_PRIVACY_STATUS"
        )
        yt_privacy_val = user_dict.get(
            "YT_PRIVACY_STATUS",
            Config.YT_PRIVACY_STATUS
            if hasattr(Config, "YT_PRIVACY_STATUS")
            else "Not Set (Uses Default)",
        )

        # Add custom cookies button
        cookies_path = f"cookies/{user_id}.txt"
        cookies_msg = "Exists" if await aiopath.exists(cookies_path) else "Not Exists"
        buttons.data_button("YTDLP Cookies", f"userset {user_id} menu YTDLP_COOKIES")
        text = f"""〄 <b>YouTube Tools Settings:</b>
╭<b>Name</b> » {user_name}
┊
┊<b>YT Description</b> » <code>{escape(str(yt_desp_val))}</code>
┊<b>YT Tags</b> » <code>{escape(str(yt_tags_val))}</code>
┊<b>YT Category ID</b> » <code>{escape(str(yt_cat_id_val))}</code>
┊<b>YT Privacy Status</b> » <code>{escape(str(yt_privacy_val))}</code>
╰<b>YTDLP Cookies</b> » <b>{cookies_msg}</b>"""
        buttons.data_button("Back", f"userset {user_id} back mirror", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(2)

        return text, btns

    return text, btns


async def update_user_settings(query, stype="main"):
    handler_dict[query.from_user.id] = False

    # Handle submenu redirections
    if stype in ["ssgrid", "samplevideo", "autorename", "dumps"]:
        # These should redirect to their respective handlers in edit_user_settings
        from_user = query.from_user
        user_id = from_user.id
        message = query.message
        user_dict = user_data.get(user_id, {})

        if stype == "dumps":
            # Redirect to DUMPS submenu
            buttons = ButtonMaker()

            # Leech Destination
            if user_dict.get("LEECH_DUMP_CHAT", False):
                leech_dest = user_dict["LEECH_DUMP_CHAT"]
            elif "LEECH_DUMP_CHAT" not in user_dict and Config.LEECH_DUMP_CHAT:
                leech_dest = Config.LEECH_DUMP_CHAT
            else:
                leech_dest = "None"

            # Mirror Destination
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

            buttons.data_button(
                "Leech Destination", f"userset {user_id} menu LEECH_DUMP_CHAT"
            )
            buttons.data_button(
                "Mirror Destination", f"userset {user_id} menu MIRROR_DUMP_CHAT"
            )
            buttons.data_button("Back", f"userset {user_id} back", "footer")
            buttons.data_button("Close", f"userset {user_id} close", "footer")
            btns = buttons.build_menu(1)

            text = f"""〄 <b>DUMPS Settings :</b>
╭<b>Name</b> » {from_user.mention(style="html")}
┊
┊<b>Leech Destination</b> » <code>{leech_dest}</code>
┊<b>Mirror Destination</b> » <code>{mirror_dest}</code>
┊
┊<i>Configure separate destinations for Leech and Mirror operations</i>
┊<i>• Leech Destination: Where leeched files are sent</i>
╰<i>• Mirror Destination: Where mirror links are posted</i>"""
            await edit_message(message, text, btns)
            return
        elif stype == "ssgrid":
            # Redirect to SS Grid submenu
            buttons = ButtonMaker()
            ss_grid_enabled = user_dict.get("SS_GRID_ENABLED", False)
            ss_grid_count = user_dict.get("SS_GRID_COUNT", 9)
            ss_grid_layout = user_dict.get("SS_GRID_LAYOUT", "3x3")
            ss_grid_pdf_mode = user_dict.get("SS_GRID_PDF_MODE", False)
            ss_grid_watermark = user_dict.get("SS_GRID_WATERMARK", "")
            ss_grid_pdf_individual = user_dict.get("SS_GRID_PDF_INDIVIDUAL_PAGES", True)

            buttons.data_button(
                "Enable" if not ss_grid_enabled else "Disable",
                f"userset {user_id} tog SS_GRID_ENABLED {'t' if not ss_grid_enabled else 'f'}",
            )
            buttons.data_button(
                "Set Screenshot Count", f"userset {user_id} menu SS_GRID_COUNT"
            )
            buttons.data_button(
                "Set Grid Layout", f"userset {user_id} menu SS_GRID_LAYOUT"
            )
            buttons.data_button(
                "Enable PDF Mode" if not ss_grid_pdf_mode else "Disable PDF Mode",
                f"userset {user_id} tog SS_GRID_PDF_MODE {'t' if not ss_grid_pdf_mode else 'f'}",
            )
            buttons.data_button(
                "Disable Individual Pages"
                if ss_grid_pdf_individual
                else "Enable Individual Pages",
                f"userset {user_id} tog SS_GRID_PDF_INDIVIDUAL_PAGES {'f' if ss_grid_pdf_individual else 't'}",
            )
            buttons.data_button(
                "Set PDF Watermark", f"userset {user_id} menu SS_GRID_WATERMARK"
            )
            buttons.data_button(
                "Back", f"userset {user_id} back common_tools", "footer"
            )
            buttons.data_button("Close", f"userset {user_id} close", "footer")
            btns = buttons.build_menu(2)

            text = f"""〄 <b>SS Grid Settings :</b>
╭<b>Status</b> » <b>{"Enabled" if ss_grid_enabled else "Disabled"}</b>
┊<b>Screenshot Count</b> » <b>{ss_grid_count}</b>
┊<b>Grid Layout</b> » <b>{ss_grid_layout}</b>
┊<b>PDF Mode</b> » <b>{"Enabled" if ss_grid_pdf_mode else "Disabled"}</b>
┊<b>PDF Individual Pages</b> » <b>{"Enabled" if ss_grid_pdf_individual else "Disabled"}</b>
╰<b>PDF Watermark</b> » <code>{ss_grid_watermark or "Not Set"}</code>"""
            await edit_message(message, text, btns)
            return

        elif stype == "samplevideo":
            # Redirect to Sample Video submenu
            buttons = ButtonMaker()
            sv_enabled = user_dict.get("SAMPLE_VIDEO_ENABLED", False)
            sv_count = user_dict.get("SAMPLE_VIDEO_COUNT", 1)
            sv_dur = user_dict.get("SAMPLE_VIDEO_DURATION", 60)
            sv_sep = user_dict.get("SAMPLE_VIDEO_SEPARATE", False)

            buttons.data_button(
                "Enable" if not sv_enabled else "Disable",
                f"userset {user_id} tog SAMPLE_VIDEO_ENABLED {'t' if not sv_enabled else 'f'}",
            )
            buttons.data_button(
                "Set Clip Count", f"userset {user_id} menu SAMPLE_VIDEO_COUNT"
            )
            buttons.data_button(
                "Set Clip Duration", f"userset {user_id} menu SAMPLE_VIDEO_DURATION"
            )
            buttons.data_button(
                "Separate Clips" if not sv_sep else "Merge Clips",
                f"userset {user_id} tog SAMPLE_VIDEO_SEPARATE {'t' if not sv_sep else 'f'}",
            )
            buttons.data_button(
                "Back", f"userset {user_id} back common_tools", "footer"
            )
            buttons.data_button("Close", f"userset {user_id} close", "footer")
            btns = buttons.build_menu(2)

            text = f"""〄 <b>Sample Video Settings :</b>
╭<b>Status</b> » <b>{"Enabled" if sv_enabled else "Disabled"}</b>
┊<b>Clip Count</b> » <b>{sv_count}</b>
┊<b>Clip Duration</b> » <b>{sv_dur} sec</b>
╰<b>Output Mode</b> » <b>{"Separate Files" if sv_sep else "Single Merged File"}</b>

<i>The bot will generate random clip(s) from video(s) after download and include them with upload. Clip count * duration should not exceed 25% of original video length.</i>"""
            await edit_message(message, text, btns)
            return

        elif stype == "autorename":
            # Redirect to Auto Rename submenu
            buttons = ButtonMaker()
            auto_rename = user_dict.get("AUTO_RENAME", False)
            template = user_dict.get("RENAME_TEMPLATE", "S{season}E{episode}Q{quality}")
            start_ep = user_dict.get("START_EPISODE", 1)
            start_season = user_dict.get("START_SEASON", 1)

            buttons.data_button(
                "Enable" if not auto_rename else "Disable",
                f"userset {user_id} tog AUTO_RENAME {'t' if not auto_rename else 'f'}",
            )
            buttons.data_button(
                "Set Template", f"userset {user_id} menu RENAME_TEMPLATE"
            )
            buttons.data_button(
                "Set Start Episode", f"userset {user_id} menu START_EPISODE"
            )
            buttons.data_button(
                "Set Start Season", f"userset {user_id} menu START_SEASON"
            )
            buttons.data_button(
                "Back", f"userset {user_id} back common_tools", "footer"
            )
            buttons.data_button("Close", f"userset {user_id} close", "footer")
            btns = buttons.build_menu(2)

            text = f"""〄 <b>Auto Rename Settings :</b>\n╭<b>Status</b> » <b>{"Enabled" if auto_rename else "Disabled"}</b>\n┊<b>Template</b> » <code>{template}</code>\n┊<b>Start Episode</b> » <b>{start_ep}</b>\n┊<b>Current Episode</b> » <b>{user_dict.get("_CURRENT_EPISODE", start_ep)}</b>\n╰<b>Start Season</b> » <b>{start_season}</b>"""
            await edit_message(message, text, btns)
            return

    msg, button = await get_user_settings(query.from_user, stype)
    # Use smart update function to handle photo messages properly
    from ..helper.telegram_helper.message_utils import update_message_with_photo

    await update_message_with_photo(query.message, msg, button)


@new_task
async def send_user_settings(_, message):
    from_user = message.from_user
    handler_dict[from_user.id] = False
    msg, button = await get_user_settings(from_user)
    # Send user settings message without photo
    await send_message(message, msg, button)


@new_task
async def add_file(_, message, ftype, rfunc):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    if ftype == "THUMBNAIL":
        des_dir = await create_thumb(message, user_id)
    elif ftype == "RCLONE_CONFIG":
        rpath = f"{getcwd()}/rclone/"
        await makedirs(rpath, exist_ok=True)
        des_dir = f"{rpath}{user_id}.conf"
        await message.download(file_name=des_dir)
    elif ftype == "TOKEN_PICKLE":
        tpath = f"{getcwd()}/tokens/"
        await makedirs(tpath, exist_ok=True)
        des_dir = f"{tpath}{user_id}.pickle"
        await message.download(file_name=des_dir)
    elif ftype == "YTDLP_COOKIES":
        cpath = f"{getcwd()}/cookies/"
        await makedirs(cpath, exist_ok=True)
        des_dir = f"{cpath}{user_id}.txt"
        await message.download(file_name=des_dir)
    elif ftype == "VIDEO_WATERMARK_IMAGE_PATH":
        wpath = f"{getcwd()}/watermarks/"
        await makedirs(wpath, exist_ok=True)

        # Handle both photo and document messages
        if message.photo:
            # For photos, get the highest resolution version
            file_ext = "jpg"
            des_dir = f"{wpath}{user_id}_watermark.{file_ext}"
            await message.download(file_name=des_dir)
        elif message.document:
            # For documents, check if it's an image
            mime_type = message.document.mime_type or ""
            if not mime_type.startswith("image/"):
                await send_message(
                    message, "❌ Please upload an image file (PNG, JPG, JPEG, BMP, GIF)"
                )
                await rfunc()
                return

            file_name = message.document.file_name or "watermark"
            file_ext = file_name.split(".")[-1].lower() if "." in file_name else "png"

            # Validate image format
            valid_formats = ["png", "jpg", "jpeg", "bmp", "gif", "webp"]
            if file_ext not in valid_formats:
                await send_message(
                    message,
                    f"❌ Unsupported format '{file_ext}'. Please use: {', '.join(valid_formats).upper()}",
                )
                await rfunc()
                return

            des_dir = f"{wpath}{user_id}_watermark.{file_ext}"
            await message.download(file_name=des_dir)
        else:
            await send_message(message, "❌ Please send an image file")
            await rfunc()
            return
    elif ftype == "VIDEO_WATERMARK_FONT_PATH":
        fpath = f"{getcwd()}/fonts/"
        await makedirs(fpath, exist_ok=True)

        # Handle font file uploads
        if message.document:
            file_name = message.document.file_name or "font"
            file_ext = file_name.split(".")[-1].lower() if "." in file_name else ""

            # Validate font format
            valid_formats = ["ttf", "otf"]
            if file_ext not in valid_formats:
                await send_message(
                    message,
                    f"❌ Unsupported font format '{file_ext}'. Please use: {', '.join(valid_formats).upper()}",
                )
                await rfunc()
                return

            # Check file size (fonts should be reasonable size)
            if message.document.file_size > 10 * 1024 * 1024:  # 10MB limit
                await send_message(
                    message, "❌ Font file too large. Maximum size: 10MB"
                )
                await rfunc()
                return

            des_dir = f"{fpath}{user_id}_font.{file_ext}"
            await message.download(file_name=des_dir)
        else:
            await send_message(message, "❌ Please send a font file (.ttf or .otf)")
            await rfunc()
            return
    await delete_message(message)
    update_user_ldata(user_id, ftype, des_dir)
    await rfunc()
    await database.update_user_doc(user_id, ftype, des_dir)


@new_task
async def add_one(_, message, option, rfunc):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    user_dict = user_data.get(user_id, {})
    value = message.text
    if value.startswith("{") and value.endswith("}"):
        try:
            value = eval(value)
            if user_dict[option]:
                user_dict[option].update(value)
            else:
                update_user_ldata(user_id, option, value)
        except Exception as e:
            await send_message(message, str(e))
            return
    else:
        await send_message(message, "It must be Dict!")
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
    if option == "LEECH_SPLIT_SIZE":
        if not value.isdigit():
            value = get_size_bytes(value)
        value = min(int(value), TgClient.MAX_SPLIT_SIZE)
    # elif option == "LEECH_DUMP_CHAT": # TODO: Add
    elif option == "EXCLUDED_EXTENSIONS":
        fx = value.split()
        value = ["aria2", "!qB"]
        for x in fx:
            x = x.lstrip(".")
            value.append(x.strip().lower())
    elif option == "YT_TAGS":
        if isinstance(value, str):
            value = [tag.strip() for tag in value.split(",") if tag.strip()]
        elif not isinstance(value, list):
            await send_message(message, "YT Tags must be a comma-separated string.")
            return
    elif option == "YT_CATEGORY_ID":
        if isinstance(value, str) and value.isdigit():
            value = int(value)
        elif not isinstance(value, int):
            await send_message(message, "YT Category ID must be a whole number.")
            return
    elif option == "YT_PRIVACY_STATUS":
        allowed_statuses = ["public", "private", "unlisted"]
        if not isinstance(value, str) or value.lower() not in allowed_statuses:
            await send_message(
                message,
                f"YT Privacy Status must be one of: {', '.join(allowed_statuses)}.",
            )
            return
    elif option == "METADATA_SETTINGS":
        try:
            # Parse the input - support multiple formats:
            # 1. Simple format: title|artist|album|genre|date|comment
            # 2. Key-value format with pipes: key=value|key2=value2|key3=value3
            # 3. Key-value format with commas: title="My Title", artist="Artist Name"
            metadata = {}

            if "|" in value and "=" in value:
                # New pipe-separated key=value format: key=value|key2=value2|key3=value3
                pairs = value.split("|")
                for pair in pairs:
                    if "=" in pair:
                        key, val = pair.split("=", 1)
                        metadata[key.strip()] = val.strip().strip('"')
            elif "|" in value and "=" not in value:
                # Simple format with pipe separator
                fields = ["title", "artist", "album", "genre", "date", "comment"]
                values = value.split("|")
                for i, val in enumerate(values):
                    if i < len(fields) and val.strip():
                        metadata[fields[i]] = val.strip()
            elif "-" in value and "=" not in value:
                # Support 'videotitle-audiotitle-subtitle' shorthand
                parts = value.split("-")
                if len(parts) > 0 and parts[0].strip():
                    metadata["video_title"] = parts[0].strip()
                if len(parts) > 1 and parts[1].strip():
                    metadata["audio_title"] = parts[1].strip()
                if len(parts) > 2 and parts[2].strip():
                    metadata["subtitle_title"] = parts[2].strip()
                if len(parts) > 3 and parts[3].strip():
                    metadata["author"] = parts[3].strip()
                if len(parts) > 4 and parts[4].strip():
                    metadata["artist"] = parts[4].strip()
            elif value and all(sep not in value for sep in ["|", "-", "="]):
                # Single word/phrase: set as global title, author, artist, and all stream titles
                v = value.strip()
                if v:
                    metadata["title"] = v
                    metadata["author"] = v
                    metadata["artist"] = v
                    metadata["video_title"] = v
                    metadata["audio_title"] = v
                    metadata["subtitle_title"] = v
            else:
                # Traditional key=value format with commas
                for item in value.split(","):
                    if "=" in item:
                        key, val = item.split("=", 1)
                        metadata[key.strip()] = val.strip().strip('"')

            if not metadata:
                await send_message(
                    message, "No valid metadata found. Please check your input format."
                )
                return

            value = metadata
        except Exception as e:
            await send_message(
                message,
                f'Invalid metadata format. Please use one of the supported formats:\n1. Simple: title|artist|album|genre|date|comment\n2. Pipe-separated key=value: title=My Title|artist=My Artist|genre=Rock\n3. Comma-separated: title="My Title", artist="Artist Name"',
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
            await send_message(message, "It must be dict!")
            return
    elif option == "USER_SESSION_STRING":
        # Sanitize common formatting artifacts before validation
        sval = (value or "").strip()
        # Remove Telegram spoilers ||...||
        if sval.startswith("||") and sval.endswith("||") and len(sval) > 4:
            sval = sval[2:-2]
        # Remove surrounding quotes/backticks and triple backticks blocks
        if sval.startswith("```") and sval.endswith("```"):
            sval = sval.strip("`")
        for q in ("`", "'", '"'):
            if sval.startswith(q) and sval.endswith(q) and len(sval) > 2:
                sval = sval[1:-1]
        # Strip whitespace, tabs, invisible chars, newlines
        for ch in (
            "\n",
            "\r",
            " ",
            "\t",
            "\u200b",
            "\u200c",
            "\u200d",
            "\u2060",
            "\ufeff",
        ):
            sval = sval.replace(ch, "")
        # If text includes other words, extract the longest base64-like token
        try:
            import re as _re

            tokens = _re.findall(r"[A-Za-z0-9_\-\+/=]{50,}", sval)
            if tokens:
                sval = max(tokens, key=len)
        except Exception:
            pass

        if not sval or len(sval) < 50:
            await send_message(
                message,
                "❌ Invalid session string! Please provide a valid Telegram session string.",
            )
            return

        # More flexible validation for different session string formats
        # Check if it looks like a valid session string (contains base64-like characters)
        import re

        if not re.match(r"^[A-Za-z0-9+/=_-]+$", sval):
            await send_message(
                message,
                "❌ Invalid session string format! Please provide a valid Telegram session string.",
            )
            return

        # Try to validate the session by attempting to decode it as base64
        try:
            import base64

            # Test if it's valid base64 (session strings are usually base64 encoded)
            base64.b64decode(sval + "==")  # Add padding if needed
        except Exception:
            # If base64 decode fails, it might still be valid for pyrogram
            pass

        # Validate the session by attempting to start a temporary client
        from pyrogram import Client as _TmpClient, enums as _tmp_enums

        ok = False
        try:
            tmp = _TmpClient(
                name=f"_validate_{user_id}",
                api_id=Config.TELEGRAM_API,
                api_hash=Config.TELEGRAM_HASH,
                session_string=sval,
                in_memory=True,
                no_updates=True,
                parse_mode=_tmp_enums.ParseMode.HTML,
            )
            await tmp.start()
            await tmp.get_me()
            await tmp.stop()
            ok = True
        except Exception as e:
            await send_message(
                message,
                f"❌ Invalid session: {e}\nPlease generate a PyroFork/Pyrogram v2 session with the same API ID/HASH and paste it as plain text (no spoilers/backticks).",
            )
            ok = False
        if not ok:
            return
        # Encrypt the validated session string before storing
        from base64 import b64encode

        value = b64encode(sval.encode()).decode()
        await send_message(
            message,
            "✅ User session validated and saved. You can now access your private chats.",
        )
    elif option == "SAMPLE_VIDEO_COUNT":
        if not value.isdigit():
            await send_message(message, "Enter a number between 1 and 10.")
            return
        iv = int(value)
        if iv < 1 or iv > 10:
            await send_message(message, "Clip count must be 1-10.")
            return
        value = iv
    elif option == "SAMPLE_VIDEO_DURATION":
        if not value.isdigit():
            await send_message(message, "Enter duration in seconds (5-600).")
            return
        iv = int(value)
        if iv < 5 or iv > 600:
            await send_message(message, "Duration must be between 5 and 600 seconds.")
            return
        value = iv
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
    elif option == "VIDEO_ENCODE_PRESET":
        # Validate encoding preset
        allowed_presets = {
            "ultrafast",
            "superfast",
            "veryfast",
            "faster",
            "fast",
            "medium",
            "slow",
            "slower",
            "veryslow",
        }
        value_lower = value.lower().strip()
        if value_lower not in allowed_presets:
            await send_message(
                message,
                f"Invalid preset '{value}'. Please choose one of: {', '.join(sorted(allowed_presets))}.",
            )
            return
        value = value_lower
    elif option == "VIDEO_CONVERT_FORMAT":
        # Validate video convert format
        allowed_formats = {"mp4", "mkv", "avi", "mov", "webm", "flv", "m4v"}
        value_lower = value.lower().strip()
        if value_lower not in allowed_formats:
            await send_message(
                message,
                f"Invalid format '{value}'. Please choose one of: {', '.join(sorted(allowed_formats))}.",
            )
            return
        value = value_lower
    elif option == "VIDEO_CONVERT_CODEC":
        # Validate video convert codec
        allowed_codecs = {"copy", "x264", "x265", "auto"}
        value_lower = value.lower().strip()
        if value_lower not in allowed_codecs:
            await send_message(
                message,
                f"Invalid codec '{value}'. Please choose one of: {', '.join(sorted(allowed_codecs))}.",
            )
            return
        value = value_lower
    elif option == "VIDEO_CONVERT_QUALITY":
        # Validate video convert quality
        allowed_qualities = {"original", "high", "medium", "low"}
        value_lower = value.lower().strip()
        if value_lower not in allowed_qualities:
            await send_message(
                message,
                f"Invalid quality '{value}'. Please choose one of: {', '.join(sorted(allowed_qualities))}.",
            )
            return
        value = value_lower
    update_user_ldata(user_id, option, value)
    # If START_EPISODE or START_SEASON is set, also reset _CURRENT_EPISODE or _CURRENT_SEASON
    user_dict = user_data.get(user_id, {})
    if option == "START_EPISODE":
        user_dict["_CURRENT_EPISODE"] = int(value)
        update_user_ldata(user_id, "_CURRENT_EPISODE", int(value))
    elif option == "START_SEASON":
        user_dict["_CURRENT_SEASON"] = int(value)
        update_user_ldata(user_id, "_CURRENT_SEASON", int(value))
    await delete_message(message)
    await rfunc()
    await database.update_user_data(user_id)


async def get_menu(option, message, user_id):
    handler_dict[user_id] = False
    user_dict = user_data.get(user_id, {})

    file_dict = {
        "THUMBNAIL": f"thumbnails/{user_id}.jpg",
        "RCLONE_CONFIG": f"rclone/{user_id}.conf",
        "TOKEN_PICKLE": f"tokens/{user_id}.pickle",
        "YTDLP_COOKIES": f"cookies/{user_id}.txt",
    }

    buttons = ButtonMaker()
    if option in ["THUMBNAIL", "RCLONE_CONFIG", "TOKEN_PICKLE", "YTDLP_COOKIES"]:
        key = "file"
    else:
        key = "set"
    buttons.data_button(
        "Change" if user_dict.get(option, False) else "Set",
        f"userset {user_id} {key} {option}",
    )
    if user_dict.get(option, False):
        if option == "THUMBNAIL":
            buttons.data_button(
                "View Thumb", f"userset {user_id} view THUMBNAIL", "header"
            )
        elif option in ["YT_DLP_OPTIONS", "FFMPEG_CMDS", "UPLOAD_PATHS"]:
            buttons.data_button(
                "Add One", f"userset {user_id} addone {option}", "header"
            )
            buttons.data_button(
                "Remove One", f"userset {user_id} rmone {option}", "header"
            )
        elif option == "USER_SESSION_STRING":
            buttons.data_button(
                "🗑 Remove Session", f"userset {user_id} reset {option}", "header"
            )

        if key != "file":  # TODO: option default val check
            buttons.data_button("Reset", f"userset {user_id} reset {option}")
        elif await aiopath.exists(file_dict[option]):
            buttons.data_button("Remove", f"userset {user_id} remove {option}")
    if option in common_tools_options:
        back_to = "common_tools"
    elif option in leech_options:
        # Check if this option belongs to a submenu
        if option in [
            "SS_GRID_ENABLED",
            "SS_GRID_COUNT",
            "SS_GRID_LAYOUT",
            "SS_GRID_PDF_MODE",
            "SS_GRID_WATERMARK",
            "SS_GRID_PDF_INDIVIDUAL_PAGES",
        ]:
            back_to = "ssgrid"
        elif option in [
            "SAMPLE_VIDEO_ENABLED",
            "SAMPLE_VIDEO_COUNT",
            "SAMPLE_VIDEO_DURATION",
            "SAMPLE_VIDEO_SEPARATE",
        ]:
            back_to = "samplevideo"
        elif option in [
            "AUTO_RENAME",
            "RENAME_TEMPLATE",
            "START_EPISODE",
            "START_SEASON",
        ]:
            back_to = "autorename"
        else:
            back_to = "leech"
    elif option in dumps_options:
        back_to = "dumps"
    elif option in rclone_options:
        back_to = "rclone"
    elif option in gdrive_options:
        back_to = "gdrive"
    elif option in gofile_options:
        back_to = "gofile"
    elif option in yt_options:
        back_to = "yttools"
    elif option in ffset_options:
        back_to = "ffset"
    elif option in advanced_options:
        back_to = "advanced"
    else:
        back_to = "back"
    buttons.data_button("Back", f"userset {user_id} {back_to}", "footer")
    buttons.data_button("Close", f"userset {user_id} close", "footer")
    val = user_dict.get(option)
    if option in file_dict and await aiopath.exists(file_dict[option]):
        val = "<b>Exists</b>"
    elif option == "LEECH_SPLIT_SIZE":
        val = get_readable_file_size(val)
    text = f"""〄 <b><u>Menu Settings :</u></b>

╭<b>Option</b> » {option}
┊
┊<b>Option's Value</b> » {val if val else "<b>Not Exists</b>"}
┊
┊<b>Default Input Type</b> » {user_settings_text[option][0]}
╰<b>Description</b> » {user_settings_text[option][1]}
"""
    await edit_message(message, text, buttons.build_menu(2))


async def event_handler(client, query, pfunc, rfunc, photo=False, document=False):
    user_id = query.from_user.id
    handler_dict[user_id] = True
    start_time = update_time = time()

    async def event_filter(_, __, event):
        if photo:
            mtype = event.photo or event.document
        elif document:
            mtype = event.document
        else:
            mtype = event.text
        user = event.from_user or event.sender_chat
        return bool(
            user.id == user_id and event.chat.id == query.message.chat.id and mtype
        )

    handler = client.add_handler(
        MessageHandler(pfunc, filters=create(event_filter)), group=-1
    )

    while handler_dict[user_id]:
        await sleep(0.5)
        if time() - start_time > 60:
            handler_dict[user_id] = False
            await rfunc()
        elif time() - update_time > 8 and handler_dict[user_id]:
            update_time = time()
            try:
                msg = await client.get_messages(query.message.chat.id, query.message.id)
                if msg and msg.text:
                    text = msg.text.split("\n")
                    text[-1] = (
                        f"╰<b>Time Left :</b> <code>{round(60 - (time() - start_time), 2)} sec</code>"
                    )
                    await edit_message(msg, "\n".join(text), msg.reply_markup)
            except Exception:
                # If message is deleted or not accessible, stop the handler
                handler_dict[user_id] = False
    client.remove_handler(*handler)


@new_task
async def edit_user_settings(client, query):
    from_user = query.from_user
    user_id = from_user.id
    name = from_user.mention
    message = query.message
    data = query.data.split()

    handler_dict[user_id] = False
    thumb_path = f"thumbnails/{user_id}.jpg"
    rclone_conf = f"rclone/{user_id}.conf"
    token_pickle = f"tokens/{user_id}.pickle"
    user_dict = user_data.get(user_id, {})
    if user_id != int(data[1]):
        return await query.answer("Not Yours!", show_alert=True)
    elif data[2] == "setevent":
        await query.answer()
    elif data[2] in [
        "general",
        "common_tools",
        "dumps",
        "mirror",
        "leech",
        "ffset",
        "advanced",
        "gdrive",
        "gofile",
        "rclone",
        "yttools",
    ]:
        await query.answer()
        await update_user_settings(query, data[2])
    elif data[2] == "autorename":
        await query.answer()
        # Show the Auto Rename submenu
        buttons = ButtonMaker()
        auto_rename = user_dict.get("AUTO_RENAME", False)
        template = user_dict.get("RENAME_TEMPLATE", "S{season}E{episode}Q{quality}")
        start_ep = user_dict.get("START_EPISODE", 1)
        start_season = user_dict.get("START_SEASON", 1)
        buttons.data_button(
            "Enable" if not auto_rename else "Disable",
            f"userset {user_id} tog AUTO_RENAME {'t' if not auto_rename else 'f'}",
        )
        buttons.data_button("Set Template", f"userset {user_id} menu RENAME_TEMPLATE")
        buttons.data_button(
            "Set Start Episode", f"userset {user_id} menu START_EPISODE"
        )
        buttons.data_button("Set Start Season", f"userset {user_id} menu START_SEASON")
        buttons.data_button("Back", f"userset {user_id} back leech", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(2)
        text = f"""〄 <b>Auto Rename Settings :</b>\n╭<b>Status</b> » <b>{"Enabled" if auto_rename else "Disabled"}</b>\n┊<b>Template</b> » <code>{template}</code>\n┊<b>Start Episode</b> » <b>{start_ep}</b>\n┊<b>Current Episode</b> » <b>{user_dict.get("_CURRENT_EPISODE", start_ep)}</b>\n╰<b>Start Season</b> » <b>{start_season}</b>"""
        await edit_message(message, text, btns)
    elif data[2] == "ssgrid":
        await query.answer()
        # Show the SS Grid submenu
        buttons = ButtonMaker()
        ss_grid_enabled = user_dict.get("SS_GRID_ENABLED", False)
        ss_grid_count = user_dict.get("SS_GRID_COUNT", 9)
        ss_grid_layout = user_dict.get("SS_GRID_LAYOUT", "3x3")
        ss_grid_pdf_mode = user_dict.get("SS_GRID_PDF_MODE", False)
        ss_grid_watermark = user_dict.get("SS_GRID_WATERMARK", "")
        ss_grid_pdf_individual = user_dict.get("SS_GRID_PDF_INDIVIDUAL_PAGES", True)

        buttons.data_button(
            "Enable" if not ss_grid_enabled else "Disable",
            f"userset {user_id} tog SS_GRID_ENABLED {'t' if not ss_grid_enabled else 'f'}",
        )
        buttons.data_button(
            "Set Screenshot Count", f"userset {user_id} menu SS_GRID_COUNT"
        )
        buttons.data_button("Set Grid Layout", f"userset {user_id} menu SS_GRID_LAYOUT")
        buttons.data_button(
            "Enable PDF Mode" if not ss_grid_pdf_mode else "Disable PDF Mode",
            f"userset {user_id} tog SS_GRID_PDF_MODE {'t' if not ss_grid_pdf_mode else 'f'}",
        )
        buttons.data_button(
            "Disable Individual Pages"
            if ss_grid_pdf_individual
            else "Enable Individual Pages",
            f"userset {user_id} tog SS_GRID_PDF_INDIVIDUAL_PAGES {'f' if ss_grid_pdf_individual else 't'}",
        )
        buttons.data_button(
            "Set PDF Watermark", f"userset {user_id} menu SS_GRID_WATERMARK"
        )
        buttons.data_button("Back", f"userset {user_id} back common_tools", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(2)

        text = f"""〄 <b>SS Grid Settings :</b>
╭<b>Status</b> » <b>{"Enabled" if ss_grid_enabled else "Disabled"}</b>
┊<b>Screenshot Count</b> » <b>{ss_grid_count}</b>
┊<b>Grid Layout</b> » <b>{ss_grid_layout}</b>
┊<b>PDF Mode</b> » <b>{"Enabled" if ss_grid_pdf_mode else "Disabled"}</b>
┊<b>PDF Individual Pages</b> » <b>{"Enabled" if ss_grid_pdf_individual else "Disabled"}</b>
╰<b>PDF Watermark</b> » <code>{ss_grid_watermark or "Not Set"}</code>"""
        await edit_message(message, text, btns)
    elif data[2] == "samplevideo":
        await query.answer()
        buttons = ButtonMaker()
        sv_enabled = user_dict.get("SAMPLE_VIDEO_ENABLED", False)
        sv_count = user_dict.get("SAMPLE_VIDEO_COUNT", 1)
        sv_dur = user_dict.get("SAMPLE_VIDEO_DURATION", 60)
        sv_sep = user_dict.get("SAMPLE_VIDEO_SEPARATE", False)
        buttons.data_button(
            "Enable" if not sv_enabled else "Disable",
            f"userset {user_id} tog SAMPLE_VIDEO_ENABLED {'t' if not sv_enabled else 'f'}",
        )
        buttons.data_button(
            "Set Clip Count", f"userset {user_id} menu SAMPLE_VIDEO_COUNT"
        )
        buttons.data_button(
            "Set Clip Duration", f"userset {user_id} menu SAMPLE_VIDEO_DURATION"
        )
        buttons.data_button(
            "Separate Clips" if not sv_sep else "Merge Clips",
            f"userset {user_id} tog SAMPLE_VIDEO_SEPARATE {'t' if not sv_sep else 'f'}",
        )
        buttons.data_button("Back", f"userset {user_id} back common_tools", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(2)
        text = f"""〄 <b>Sample Video Settings :</b>
╭<b>Status</b> » <b>{"Enabled" if sv_enabled else "Disabled"}</b>
┊<b>Clip Count</b> » <b>{sv_count}</b>
┊<b>Clip Duration</b> » <b>{sv_dur} sec</b>
╰<b>Output Mode</b> » <b>{"Separate Files" if sv_sep else "Single Merged File"}</b>

<i>The bot will generate random clip(s) from video(s) after download and include them with upload. Clip count * duration should not exceed 25% of original video length.</i>"""
        await edit_message(message, text, btns)
    elif data[2] == "auto_process":
        await query.answer()
        # Show the Auto Leech/Mirror submenu
        buttons = ButtonMaker()
        auto_leech = user_dict.get("AUTO_LEECH", False)
        auto_mirror = user_dict.get("AUTO_MIRROR", False)
        auto_ft = user_dict.get("AUTO_FT", False)

        buttons.data_button(
            "Disable Auto Leech" if auto_leech else "Enable Auto Leech",
            f"userset {user_id} tog AUTO_LEECH {'f' if auto_leech else 't'}",
        )
        buttons.data_button(
            "Disable Auto Mirror" if auto_mirror else "Enable Auto Mirror",
            f"userset {user_id} tog AUTO_MIRROR {'f' if auto_mirror else 't'}",
        )
        buttons.data_button(
            "Disable Auto -ft" if auto_ft else "Enable Auto -ft",
            f"userset {user_id} tog AUTO_FT {'f' if auto_ft else 't'}",
        )
        buttons.data_button("Back", f"userset {user_id} back", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(2)

        text = f"""〄 <b>Auto Leech/Mirror Settings :</b>
╭<b>Auto Leech</b> » <b>{"Enabled" if auto_leech else "Disabled"}</b>
┊<b>Auto Mirror</b> » <b>{"Enabled" if auto_mirror else "Disabled"}</b>
╰<b>Auto -ft</b> » <b>{"Enabled" if auto_ft else "Disabled"}</b>

<i>When enabled, the bot will automatically process any links or files you send:
• Auto Leech: Automatically leeches links/files
• Auto Mirror: Automatically mirrors links/files  
• Auto -ft: Asks for video tools selection like normal commands</i>"""
        await edit_message(message, text, btns)
    elif data[2] == "ffsubmenu":
        await query.answer()
        submenu_type = data[3]  # encode, watermark, or intro

        if submenu_type == "encode":
            # Show encode settings submenu
            buttons = FFmpegButtonMaker()
            video_encode_enabled = user_dict.get("VIDEO_ENCODE_ENABLED", False)

            # Video encode toggle
            buttons.data_button(
                f"{'✓ ' if video_encode_enabled else ''}Video Encode",
                f"userset {user_id} tog VIDEO_ENCODE_ENABLED {'f' if video_encode_enabled else 't'} encode",
            )

            if video_encode_enabled:
                # Encode settings only show when encoding is enabled
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
                    f"userset {user_id} vidquality {user_id}",
                )

                default_crf = 23
                current_crf = user_dict.get("VIDEO_ENCODE_CRF", default_crf)
                has_custom_crf = current_crf != default_crf
                buttons.data_button(
                    f"{'✓ ' if has_custom_crf else ''}CRF",
                    f"userset {user_id} videocrf {user_id}",
                )

                default_bitrate = "128k"
                current_bitrate = user_dict.get(
                    "VIDEO_ENCODE_AUDIO_BITRATE", default_bitrate
                )
                has_custom_bitrate = current_bitrate != default_bitrate
                buttons.data_button(
                    f"{'✓ ' if has_custom_bitrate else ''}Audio Bitrate",
                    f"userset {user_id} audiobitrate {user_id}",
                )

                # Codec selection
                default_codec = "x264"
                current_codec = user_dict.get("VIDEO_ENCODE_CODEC", default_codec)
                has_custom_codec = current_codec != default_codec
                buttons.data_button(
                    f"{'✓ ' if has_custom_codec else ''}Codec",
                    f"userset {user_id} codec {user_id}",
                )

                # Multi-resolution encoding options
                multi_res_enabled = user_dict.get(
                    "VIDEO_ENCODE_MULTI_RESOLUTION", False
                )
                buttons.data_button(
                    f"{'✓ ' if multi_res_enabled else ''}Multi-Res",
                    f"userset {user_id} tog VIDEO_ENCODE_MULTI_RESOLUTION {'f' if multi_res_enabled else 't'} encode",
                )

                if multi_res_enabled:
                    # Resolution selection button only shows when multi-res is enabled
                    resolution_list = user_dict.get("VIDEO_ENCODE_RESOLUTION_LIST", "")
                    has_custom_resolutions = bool(resolution_list.strip())
                    buttons.data_button(
                        f"{'✓ ' if has_custom_resolutions else ''}Resolutions",
                        f"userset {user_id} resolutions {user_id}",
                    )

                    # Multi-zip option only shows when multi-res is enabled
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
            if resolution_list.strip():
                resolutions_display = resolution_list
            else:
                resolutions_display = "Auto (All Suitable)"

            # Multi-zip setting for display
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
            buttons = FFmpegButtonMaker()
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

                default_seconds = 10
                current_seconds = user_dict.get(
                    "VIDEO_WATERMARK_DURATION_SECONDS", default_seconds
                )
                has_custom_seconds = current_seconds != default_seconds
                buttons.data_button(
                    f"{'✓ ' if has_custom_seconds else ''}WM-Seconds",
                    f"userset {user_id} menu VIDEO_WATERMARK_DURATION_SECONDS",
                )

            buttons.data_button("Back", f"userset {user_id} back ffset", "footer")
            buttons.data_button("Close", f"userset {user_id} close", "footer")
            btns = buttons.build_menu(2)

            watermark_status = "Enabled" if watermark_enabled else "Disabled"
            wm_text = user_dict.get("VIDEO_WATERMARK_TEXT", "Default Watermark")
            wm_type = user_dict.get("VIDEO_WATERMARK_TYPE", "text")
            wm_position = user_dict.get("VIDEO_WATERMARK_POSITION", "bottom-right")
            wm_opacity = user_dict.get("VIDEO_WATERMARK_OPACITY", 0.5)

            text = f"""🌊 <b>Watermark Settings</b>
╭<b>Watermark</b> » <b>{watermark_status}</b>
┊<b>Text</b> » <code>{wm_text}</code>
┊<b>Type</b> » <b>{wm_type}</b>
┊<b>Position</b> » <b>{wm_position}</b>
╰<b>Opacity</b> » <b>{wm_opacity}</b>"""
            await edit_message(message, text, btns)

        elif submenu_type == "intro":
            # Show intro subtitle settings submenu
            buttons = FFmpegButtonMaker()
            intro_enabled = user_dict.get("INTRO_SUBTITLE_ENABLED", False)

            # Intro Sub toggle
            buttons.data_button(
                f"{'✓ ' if intro_enabled else ''}Intro-Sub",
                f"userset {user_id} tog INTRO_SUBTITLE_ENABLED {'f' if intro_enabled else 't'} intro",
            )

            if intro_enabled:
                # Intro settings only show when enabled
                has_intro_text = bool(user_dict.get("INTRO_SUBTITLE_TEXT"))
                buttons.data_button(
                    f"{'✓ ' if has_intro_text else ''}IS-Text",
                    f"userset {user_id} menu INTRO_SUBTITLE_TEXT",
                )

                style = user_dict.get("INTRO_SUBTITLE_STYLE", "typing")
                style_custom = style != "typing"
                buttons.data_button(
                    f"{'✓ ' if style_custom else ''}IS-Style",
                    f"userset {user_id} menu INTRO_SUBTITLE_STYLE",
                )

                pos = user_dict.get("INTRO_SUBTITLE_POSITION", "bottom")
                pos_custom = pos != "bottom"
                buttons.data_button(
                    f"{'✓ ' if pos_custom else ''}IS-Pos",
                    f"userset {user_id} menu INTRO_SUBTITLE_POSITION",
                )

                has_intro_font = bool(user_dict.get("INTRO_SUBTITLE_FONT_PATH"))
                buttons.data_button(
                    f"{'✓ ' if has_intro_font else ''}IS-Font",
                    f"userset {user_id} file INTRO_SUBTITLE_FONT_PATH",
                )

                font_size_def = 48
                font_size_cur = user_dict.get("INTRO_SUBTITLE_FONT_SIZE", font_size_def)
                font_size_custom = font_size_cur != font_size_def
                buttons.data_button(
                    f"{'✓ ' if font_size_custom else ''}IS-Size",
                    f"userset {user_id} menu INTRO_SUBTITLE_FONT_SIZE",
                )

                has_colors = bool(user_dict.get("INTRO_SUBTITLE_COLORS"))
                buttons.data_button(
                    f"{'✓ ' if has_colors else ''}IS-Colours",
                    f"userset {user_id} menu INTRO_SUBTITLE_COLORS",
                )

                char_ms_def = 300
                char_ms_cur = user_dict.get("INTRO_SUBTITLE_CHAR_MS", char_ms_def)
                char_ms_custom = char_ms_cur != char_ms_def
                buttons.data_button(
                    f"{'✓ ' if char_ms_custom else ''}IS-ms",
                    f"userset {user_id} menu INTRO_SUBTITLE_CHAR_MS",
                )

            buttons.data_button("Back", f"userset {user_id} back ffset", "footer")
            buttons.data_button("Close", f"userset {user_id} close", "footer")
            btns = buttons.build_menu(2)

            intro_status = "Enabled" if intro_enabled else "Disabled"
            intro_text = user_dict.get("INTRO_SUBTITLE_TEXT", "Not Set")
            intro_style = user_dict.get("INTRO_SUBTITLE_STYLE", "typing")
            intro_pos = user_dict.get("INTRO_SUBTITLE_POSITION", "bottom")

            text = f"""📝 <b>Intro Subtitle Settings</b>
╭<b>Intro Sub</b> » <b>{intro_status}</b>
┊<b>Text</b> » <code>{intro_text}</code>
┊<b>Style</b> » <b>{intro_style}</b>
╰<b>Position</b> » <b>{intro_pos}</b>"""
            await edit_message(message, text, btns)

        elif submenu_type == "hardsub":
            # Show hardsub settings submenu
            buttons = FFmpegButtonMaker()
            hardsub_enabled = user_dict.get("VIDEO_HARDSUB_ENABLED", False)

            # Hardsub toggle
            buttons.data_button(
                f"{'✓ ' if hardsub_enabled else ''}Hardsub",
                f"userset {user_id} tog VIDEO_HARDSUB_ENABLED {'f' if hardsub_enabled else 't'} hardsub",
            )

            if hardsub_enabled:
                # Hardsub settings only show when enabled
                style = user_dict.get("VIDEO_HARDSUB_STYLE", "default")
                style_custom = style != "default"
                buttons.data_button(
                    f"{'✓ ' if style_custom else ''}HS-Style",
                    f"userset {user_id} menu VIDEO_HARDSUB_STYLE",
                )

                font_size_def = 20
                font_size_cur = user_dict.get("VIDEO_HARDSUB_FONT_SIZE", font_size_def)
                font_size_custom = font_size_cur != font_size_def
                buttons.data_button(
                    f"{'✓ ' if font_size_custom else ''}HS-Size",
                    f"userset {user_id} menu VIDEO_HARDSUB_FONT_SIZE",
                )

                font_name = user_dict.get("VIDEO_HARDSUB_FONT_NAME", "Arial")
                font_name_custom = font_name != "Arial"
                buttons.data_button(
                    f"{'✓ ' if font_name_custom else ''}HS-Font",
                    f"userset {user_id} menu VIDEO_HARDSUB_FONT_NAME",
                )

            buttons.data_button("Back", f"userset {user_id} back ffset", "footer")
            buttons.data_button("Close", f"userset {user_id} close", "footer")
            btns = buttons.build_menu(2)

            hardsub_status = "Enabled" if hardsub_enabled else "Disabled"
            hardsub_style = user_dict.get("VIDEO_HARDSUB_STYLE", "default")
            hardsub_font_size = user_dict.get("VIDEO_HARDSUB_FONT_SIZE", 20)
            hardsub_font_name = user_dict.get("VIDEO_HARDSUB_FONT_NAME", "Arial")

            text = f"""🔥 <b>Hardsub Settings</b>
╭<b>Hardsub</b> » <b>{hardsub_status}</b>
┊<b>Style</b> » <b>{hardsub_style}</b>
┊<b>Font Size</b> » <b>{hardsub_font_size}px</b>
╰<b>Font Name</b> » <b>{hardsub_font_name}</b>"""
            await edit_message(message, text, btns)

    elif data[2] == "vidquality":
        await query.answer()
        # Show the Video Quality submenu
        buttons = ButtonMaker()
        quality = user_dict.get("VIDEO_ENCODE_QUALITY", "Original")

        quality_options = ["1080p", "720p", "576p", "480p", "360p", "Original"]

        # Add each option as individual button
        for option in quality_options:
            # Mark the current selected quality with a checkmark
            button_text = f"✓ {option}" if quality == option else option
            buttons.data_button(button_text, f"userset {user_id} setquality {option}")

        buttons.data_button("Back", f"userset {user_id} ffsubmenu encode", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(2)

        text = f"""〄 <b>Video Encoding Quality :</b>
╭<b>Current Quality</b> » <b>{quality}</b>
┊
┊<b>1080p</b> » Full HD, high quality (bitrate ~2000-2500k)
┊<b>720p</b> » HD, balanced quality (bitrate ~1000-1500k)
┊<b>576p</b> » PAL DVD quality (bitrate ~800-1000k)
┊<b>480p</b> » DVD quality, medium size (bitrate ~500-800k)
┊<b>360p</b> » Low resolution, small size (bitrate ~300-400k)
╰<b>Original</b> » Keep original resolution, only apply preset
"""
        await edit_message(message, text, btns)
    elif data[2] == "setquality":
        await query.answer()
        # Update the user setting with selected quality
        quality = data[3]
        update_user_ldata(user_id, "VIDEO_ENCODE_QUALITY", quality)
        await database.update_user_data(user_id)
        await query.edit_message_text("Video encoding quality updated!")
        await sleep(1)  # Short pause to show the message

        # Re-display the quality menu with updated selection
        buttons = ButtonMaker()
        quality_options = ["1080p", "720p", "576p", "480p", "360p", "Original"]

        # Add each option as individual button
        for option in quality_options:
            # Mark the current selected quality with a checkmark
            button_text = f"✓ {option}" if quality == option else option
            buttons.data_button(button_text, f"userset {user_id} setquality {option}")

        buttons.data_button("Back", f"userset {user_id} ffsubmenu encode", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(2)

        text = f"""〄 <b>Video Encoding Quality :</b>
╭<b>Current Quality</b> » <b>{quality}</b>
┊
┊<b>1080p</b> » Full HD, high quality (bitrate ~2000-2500k)
┊<b>720p</b> » HD, balanced quality (bitrate ~1000-1500k)
┊<b>576p</b> » PAL DVD quality (bitrate ~800-1000k)
┊<b>480p</b> » DVD quality, medium size (bitrate ~500-800k)
┊<b>360p</b> » Low resolution, small size (bitrate ~300-400k)
╰<b>Original</b> » Keep original resolution, only apply preset
"""
        await edit_message(message, text, btns)
    elif data[2] == "videocrf":
        await query.answer()
        # Show the CRF submenu
        buttons = ButtonMaker()
        crf = user_dict.get("VIDEO_ENCODE_CRF", 23)

        # Common CRF values, lower = better quality but larger file
        crf_options = [18, 20, 23, 25, 28, 30]

        # Add each option as individual button
        for option in crf_options:
            # Mark the current selected crf with a checkmark
            button_text = f"✓ {option}" if crf == option else f"{option}"
            buttons.data_button(button_text, f"userset {user_id} setcrf {option}")
        # Add 'Original' option (keeps source video when no scaling)
        orig_selected = isinstance(crf, str) and str(crf).lower() == "original"
        buttons.data_button(
            f"✓ Original" if orig_selected else "Original",
            f"userset {user_id} setcrf original",
        )

        buttons.data_button("Back", f"userset {user_id} ffsubmenu encode", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(3)

        text = f"""〄 <b>Video Encoding CRF :</b>
╭<b>Current CRF</b> » <b>{crf}</b>
┊
┊<b>What is CRF?</b>
┊CRF (Constant Rate Factor) controls quality.
┊Lower values = higher quality but larger files.
┊Higher values = smaller files but lower quality.
┊
┊<b>18</b> » Very high quality (visually lossless)
┊<b>20</b> » High quality
┊<b>23</b> » Default, good quality
┊<b>25</b> » Standard quality, smaller size
┊<b>28</b> » Lower quality, small size
┊<b>30</b> » Low quality, very small size
╰<b>Original</b> » Keep source video (copy) when quality is 'Original' (no scaling)
"""
        await edit_message(message, text, btns)
    elif data[2] == "codec":
        await query.answer()
        # Show the Codec submenu
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
╰• Modern codec with excellent quality
"""
        await edit_message(message, text, btns)
    elif data[2] == "setcodec":
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
            await query.edit_message_text("Video encoding codec updated!")
            await sleep(1)
        # Re-render submenu
        buttons = ButtonMaker()
        codec = user_dict.get("VIDEO_ENCODE_CODEC", option)
        codec_options = ["x264", "x265"]
        for c in codec_options:
            button_text = f"✓ {c}" if codec == c else c
            buttons.data_button(button_text, f"userset {user_id} setcodec {c}")
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
╰• Modern codec with excellent quality
"""
        await edit_message(message, text, btns)
    elif data[2] == "preset":
        await query.answer()
        # Show the Preset submenu
        buttons = ButtonMaker()
        preset = user_dict.get("VIDEO_ENCODE_PRESET", "medium")
        # x264/x265 common presets
        preset_options = [
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
        for option in preset_options:
            button_text = f"✓ {option}" if preset == option else option
            buttons.data_button(button_text, f"userset {user_id} setpreset {option}")
        buttons.data_button("Back", f"userset {user_id} ffsubmenu encode", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(2)
        text = f"""〄 <b>Video Encoding Preset :</b>
╭<b>Current Preset</b> » <b>{preset}</b>
┊
┊Presets trade off speed vs. compression efficiency.
┊Slower = better quality/smaller size, but longer encode times.
╰Faster = larger size, but much quicker encodes.
"""
        await edit_message(message, text, btns)
    elif data[2] == "setpreset":
        await query.answer()
        option = data[3]
        # Validate against allowed presets for safety
        allowed = {
            "ultrafast",
            "superfast",
            "veryfast",
            "faster",
            "fast",
            "medium",
            "slow",
            "slower",
            "veryslow",
        }
        if option not in allowed:
            await query.edit_message_text("Invalid preset!")
            await sleep(1)
        else:
            update_user_ldata(user_id, "VIDEO_ENCODE_PRESET", option)
            await database.update_user_data(user_id)
            await query.edit_message_text("Video encoding preset updated!")
            await sleep(1)
        # Re-render submenu
        buttons = ButtonMaker()
        preset = user_dict.get("VIDEO_ENCODE_PRESET", option)
        preset_options = [
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
        for p in preset_options:
            button_text = f"✓ {p}" if preset == p else p
            buttons.data_button(button_text, f"userset {user_id} setpreset {p}")
        buttons.data_button("Back", f"userset {user_id} ffsubmenu encode", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(2)
        text = f"""〄 <b>Video Encoding Preset :</b>
╭<b>Current Preset</b> » <b>{preset}</b>
┊
┊Presets trade off speed vs. compression efficiency.
┊Slower = better quality/smaller size, but longer encode times.
╰Faster = larger size, but much quicker encodes.
"""
        await edit_message(message, text, btns)
    elif data[2] == "setcrf":
        await query.answer()
        # Update the user setting with selected CRF
        raw_val = data[3]
        crf = raw_val
        try:
            if isinstance(raw_val, str) and raw_val.lower() == "original":
                update_user_ldata(user_id, "VIDEO_ENCODE_CRF", "original")
                await database.update_user_data(user_id)
                await query.edit_message_text("Video encoding CRF updated!")
                crf = "original"
            else:
                iv = int(raw_val)
                # Validate CRF range (0-51 for x264/x265)
                if 0 <= iv <= 51:
                    update_user_ldata(user_id, "VIDEO_ENCODE_CRF", iv)
                    await database.update_user_data(user_id)
                    await query.edit_message_text("Video encoding CRF updated!")
                    crf = iv
                else:
                    await query.edit_message_text(
                        "Invalid CRF value! Must be between 0-51."
                    )
        except ValueError:
            await query.edit_message_text(
                "Invalid CRF value! Must be an integer or 'original'."
            )

        await sleep(1)  # Short pause to show the message

        # Re-display the CRF menu with updated selection
        buttons = ButtonMaker()
        crf_options = [18, 20, 23, 25, 28, 30]

        # Add each option as individual button
        for option in crf_options:
            # Mark the current selected CRF with a checkmark
            button_text = f"✓ {option}" if crf == option else f"{option}"
            buttons.data_button(button_text, f"userset {user_id} setcrf {option}")
        # Add 'Original' option (keeps source video when no scaling)
        orig_selected = isinstance(crf, str) and str(crf).lower() == "original"
        buttons.data_button(
            f"✓ Original" if orig_selected else "Original",
            f"userset {user_id} setcrf original",
        )

        buttons.data_button("Back", f"userset {user_id} ffsubmenu encode", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(3)

        text = f"""〄 <b>Video Encoding CRF :</b>
╭<b>Current CRF</b> » <b>{crf}</b>
┊
┊<b>What is CRF?</b>
┊CRF (Constant Rate Factor) controls quality.
┊Lower values = higher quality but larger files.
┊Higher values = smaller files but lower quality.
┊
┊<b>18</b> » Very high quality (visually lossless)
┊<b>20</b> » High quality
┊<b>23</b> » Default, good quality
┊<b>25</b> » Standard quality, smaller size
┊<b>28</b> » Lower quality, small size
┊<b>30</b> » Low quality, very small size
╰<b>Original</b> » Keep source video (copy) when quality is 'Original' (no scaling)
"""
        await edit_message(message, text, btns)
    elif data[2] == "audiobitrate":
        await query.answer()
        # Show the Audio Bitrate submenu
        buttons = ButtonMaker()
        bitrate = user_dict.get("VIDEO_ENCODE_AUDIO_BITRATE", "128k")

        # Common audio bitrate values
        bitrate_options = ["64k", "96k", "128k", "192k", "256k", "320k"]

        # Add each option as individual button
        for option in bitrate_options:
            # Mark the current selected bitrate with a checkmark
            button_text = f"✓ {option}" if bitrate == option else option
            buttons.data_button(button_text, f"userset {user_id} setbitrate {option}")
        # Add special options: Original (auto-detect) and Copy (stream-copy)
        buttons.data_button(
            f"✓ Original" if str(bitrate).lower() == "original" else "Original",
            f"userset {user_id} setbitrate original",
        )
        buttons.data_button(
            f"✓ Copy" if str(bitrate).lower() == "copy" else "Copy",
            f"userset {user_id} setbitrate copy",
        )

        buttons.data_button("Back", f"userset {user_id} ffsubmenu encode", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(3)

        text = f"""〄 <b>Audio Bitrate for Encoding :</b>
╭<b>Current Bitrate</b> » <b>{bitrate}</b>
┊
┊<b>What is Audio Bitrate?</b>
┊Audio bitrate determines sound quality.
┊Higher values = better audio but larger files.
┊
┊<b>64k</b> » Low quality, smallest size
┊<b>96k</b> » Basic quality, very small size 
┊<b>128k</b> » Standard quality (default)
┊<b>192k</b> » Good quality, balanced size
┊<b>256k</b> » Very good quality
┊<b>320k</b> » Excellent quality, largest size
╰<b>Original</b> » Match source bitrate | <b>Copy</b> » Keep original audio stream
"""
        await edit_message(message, text, btns)

    elif data[2] == "setbitrate":
        await query.answer()
        # Update the user setting with selected bitrate
        bitrate = data[3]
        update_user_ldata(user_id, "VIDEO_ENCODE_AUDIO_BITRATE", bitrate)
        await database.update_user_data(user_id)
        await query.edit_message_text("Audio bitrate updated!")
        await sleep(1)  # Short pause to show the message

        # Re-display the bitrate menu with updated selection
        buttons = ButtonMaker()
        bitrate_options = ["64k", "96k", "128k", "192k", "256k", "320k"]

        # Add each option as individual button
        for option in bitrate_options:
            # Mark the current selected bitrate with a checkmark
            button_text = f"✓ {option}" if bitrate == option else option
            buttons.data_button(button_text, f"userset {user_id} setbitrate {option}")
        # Add special options: Original (auto-detect) and Copy (stream-copy)
        buttons.data_button(
            f"✓ Original" if str(bitrate).lower() == "original" else "Original",
            f"userset {user_id} setbitrate original",
        )
        buttons.data_button(
            f"✓ Copy" if str(bitrate).lower() == "copy" else "Copy",
            f"userset {user_id} setbitrate copy",
        )

        buttons.data_button("Back", f"userset {user_id} ffsubmenu encode", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(3)

        text = f"""〄 <b>Audio Bitrate for Encoding :</b>
╭<b>Current Bitrate</b> » <b>{bitrate}</b>
┊
┊<b>What is Audio Bitrate?</b>
┊Audio bitrate determines sound quality.
┊Higher values = better audio but larger files.
┊
┊<b>64k</b> » Low quality, smallest size
┊<b>96k</b> » Basic quality, very small size 
┊<b>128k</b> » Standard quality (default)
┊<b>192k</b> » Good quality, balanced size
┊<b>256k</b> » Very good quality
┊<b>320k</b> » Excellent quality, largest size
╰<b>Original</b> » Match source bitrate | <b>Copy</b> » Keep original audio stream
"""
        await edit_message(message, text, btns)
    elif data[2] == "resolutions":
        await query.answer()
        # Show the Resolution Selection submenu
        buttons = ButtonMaker()
        current_resolutions = user_dict.get("VIDEO_ENCODE_RESOLUTION_LIST", "")

        # Parse current selections
        selected_resolutions = set()
        if current_resolutions.strip():
            selected_resolutions = set(
                [r.strip() for r in current_resolutions.split(",") if r.strip()]
            )

        # Available resolution options
        resolution_options = ["1080p", "720p", "576p", "480p", "360p"]

        # Add toggle buttons for each resolution
        for resolution in resolution_options:
            is_selected = resolution in selected_resolutions
            button_text = f"✓ {resolution}" if is_selected else resolution
            buttons.data_button(
                button_text, f"userset {user_id} toggleres {resolution}"
            )

        # Control buttons
        buttons.data_button("Select All", f"userset {user_id} resall select", "footer")
        buttons.data_button("Clear All", f"userset {user_id} resall clear", "footer")
        buttons.data_button("Back", f"userset {user_id} ffsubmenu encode", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(3)

        # Display current selections
        if selected_resolutions:
            current_display = ", ".join(
                sorted(
                    selected_resolutions,
                    key=lambda x: int(x.replace("p", "")),
                    reverse=True,
                )
            )
        else:
            current_display = "All Available (Auto)"

        text = f"""🎯 <b>Multi-Resolution Selection :</b>
╭<b>Current Selection</b> » <b>{current_display}</b>
┊
┊<b>Available Resolutions:</b>
┊Select which resolutions to create during multi-resolution encoding.
┊Only resolutions equal to or lower than the original will be created.
┊
┊<b>1080p</b> » Full HD (1920x1080)
┊<b>720p</b> » HD (1280x720)
┊<b>576p</b> » PAL Standard (720x576)
┊<b>480p</b> » SD (854x480)
┊<b>360p</b> » Low Quality (640x360)
┊
╰<b>Tip:</b> If none selected, all suitable resolutions will be created automatically.
"""
        await edit_message(message, text, btns)
    elif data[2] == "toggleres":
        await query.answer()
        # Toggle resolution selection
        resolution = data[3]
        current_resolutions = user_dict.get("VIDEO_ENCODE_RESOLUTION_LIST", "")

        # Parse current selections
        selected_resolutions = set()
        if current_resolutions.strip():
            selected_resolutions = set(
                [r.strip() for r in current_resolutions.split(",") if r.strip()]
            )

        # Toggle the resolution
        if resolution in selected_resolutions:
            selected_resolutions.remove(resolution)
        else:
            selected_resolutions.add(resolution)

        # Update the setting
        new_resolution_list = ",".join(
            sorted(
                selected_resolutions,
                key=lambda x: int(x.replace("p", "")),
                reverse=True,
            )
        )
        update_user_ldata(user_id, "VIDEO_ENCODE_RESOLUTION_LIST", new_resolution_list)
        await database.update_user_data(user_id)

        # Re-display the resolution menu with updated selection
        buttons = ButtonMaker()
        resolution_options = ["1080p", "720p", "576p", "480p", "360p"]

        # Add toggle buttons for each resolution
        for res in resolution_options:
            is_selected = res in selected_resolutions
            button_text = f"✓ {res}" if is_selected else res
            buttons.data_button(button_text, f"userset {user_id} toggleres {res}")

        # Control buttons
        buttons.data_button("Select All", f"userset {user_id} resall select", "footer")
        buttons.data_button("Clear All", f"userset {user_id} resall clear", "footer")
        buttons.data_button("Back", f"userset {user_id} ffsubmenu encode", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(3)

        # Display current selections
        if selected_resolutions:
            current_display = ", ".join(
                sorted(
                    selected_resolutions,
                    key=lambda x: int(x.replace("p", "")),
                    reverse=True,
                )
            )
        else:
            current_display = "All Available (Auto)"

        text = f"""🎯 <b>Multi-Resolution Selection :</b>
╭<b>Current Selection</b> » <b>{current_display}</b>
┊
┊<b>Available Resolutions:</b>
┊Select which resolutions to create during multi-resolution encoding.
┊Only resolutions equal to or lower than the original will be created.
┊
┊<b>1080p</b> » Full HD (1920x1080)
┊<b>720p</b> » HD (1280x720)
┊<b>576p</b> » PAL Standard (720x576)
┊<b>480p</b> » SD (854x480)
┊<b>360p</b> » Low Quality (640x360)
┊
╰<b>Tip:</b> If none selected, all suitable resolutions will be created automatically.
"""
        await edit_message(message, text, btns)
    elif data[2] == "resall":
        await query.answer()
        # Handle select all / clear all
        action = data[3]  # "select" or "clear"

        if action == "select":
            # Select all resolutions
            selected_resolutions = {"1080p", "720p", "576p", "480p", "360p"}
            new_resolution_list = ",".join(
                sorted(
                    selected_resolutions,
                    key=lambda x: int(x.replace("p", "")),
                    reverse=True,
                )
            )
            update_user_ldata(
                user_id, "VIDEO_ENCODE_RESOLUTION_LIST", new_resolution_list
            )
        else:  # "clear"
            # Clear all selections
            update_user_ldata(user_id, "VIDEO_ENCODE_RESOLUTION_LIST", "")
            selected_resolutions = set()

        await database.update_user_data(user_id)

        # Re-display the resolution menu with updated selection
        buttons = ButtonMaker()
        resolution_options = ["1080p", "720p", "576p", "480p", "360p"]

        # Add toggle buttons for each resolution
        for res in resolution_options:
            is_selected = res in selected_resolutions
            button_text = f"✓ {res}" if is_selected else res
            buttons.data_button(button_text, f"userset {user_id} toggleres {res}")

        # Control buttons
        buttons.data_button("Select All", f"userset {user_id} resall select", "footer")
        buttons.data_button("Clear All", f"userset {user_id} resall clear", "footer")
        buttons.data_button("Back", f"userset {user_id} ffsubmenu encode", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(3)

        # Display current selections
        if selected_resolutions:
            current_display = ", ".join(
                sorted(
                    selected_resolutions,
                    key=lambda x: int(x.replace("p", "")),
                    reverse=True,
                )
            )
        else:
            current_display = "All Available (Auto)"

        text = f"""🎯 <b>Multi-Resolution Selection :</b>
╭<b>Current Selection</b> » <b>{current_display}</b>
┊
┊<b>Available Resolutions:</b>
┊Select which resolutions to create during multi-resolution encoding.
┊Only resolutions equal to or lower than the original will be created.
┊
┊<b>1080p</b> » Full HD (1920x1080)
┊<b>720p</b> » HD (1280x720)
┊<b>576p</b> » PAL Standard (720x576)
┊<b>480p</b> » SD (854x480)
┊<b>360p</b> » Low Quality (640x360)
┊
╰<b>Tip:</b> If none selected, all suitable resolutions will be created automatically.
"""
        await edit_message(message, text, btns)
    elif data[2] == "convertformat":
        await query.answer()
        # Show the Convert Format submenu
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
┊<b>Available Formats:</b>
┊<b>MP4</b> » Universal compatibility, good for sharing
┊<b>MKV</b> » Feature-rich, supports multiple streams
┊<b>AVI</b> » Classic format, wide compatibility
┊<b>MOV</b> » Apple/QuickTime format
┊<b>WEBM</b> » Web-optimized, good compression
┊<b>FLV</b> » Flash video format
╰<b>M4V</b> » iTunes-compatible format
"""
        await edit_message(message, text, btns)
    elif data[2] == "setformat":
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
            await query.edit_message_text("Video convert format updated!")
            await sleep(1)
        # Re-render submenu
        buttons = ButtonMaker()
        format_option = user_dict.get("VIDEO_CONVERT_FORMAT", option)
        format_options = ["mp4", "mkv", "avi", "mov", "webm", "flv", "m4v"]
        for f in format_options:
            button_text = f"✓ {f.upper()}" if format_option == f else f.upper()
            buttons.data_button(button_text, f"userset {user_id} setformat {f}")
        buttons.data_button("Back", f"userset {user_id} ffsubmenu convert", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(3)
        text = f"""🔄 <b>Video Convert Format :</b>
╭<b>Current Format</b> » <b>{format_option.upper()}</b>
┊
┊<b>Available Formats:</b>
┊<b>MP4</b> » Universal compatibility, good for sharing
┊<b>MKV</b> » Feature-rich, supports multiple streams
┊<b>AVI</b> » Classic format, wide compatibility
┊<b>MOV</b> » Apple/QuickTime format
┊<b>WEBM</b> » Web-optimized, good compression
┊<b>FLV</b> » Flash video format
╰<b>M4V</b> » iTunes-compatible format
"""
        await edit_message(message, text, btns)
    elif data[2] == "convertcodec":
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
╰<b>auto</b> » Smart selection based on format
"""
        await edit_message(message, text, btns)
    elif data[2] == "setconvertcodec":
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
            await query.edit_message_text("Video convert codec updated!")
            await sleep(1)
        # Re-render submenu
        buttons = ButtonMaker()
        codec_option = user_dict.get("VIDEO_CONVERT_CODEC", option)
        codec_options = ["copy", "x264", "x265", "auto"]
        for c in codec_options:
            button_text = f"✓ {c}" if codec_option == c else c
            buttons.data_button(button_text, f"userset {user_id} setconvertcodec {c}")
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
╰<b>auto</b> » Smart selection based on format
"""
        await edit_message(message, text, btns)
    elif data[2] == "convertquality":
        await query.answer()
        # Show the Convert Quality submenu
        buttons = ButtonMaker()
        quality_option = user_dict.get("VIDEO_CONVERT_QUALITY", "original")
        # Available quality options for conversion
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
┊<b>Available Options:</b>
┊<b>original</b> » Keep original quality (when re-encoding)
┊<b>high</b> » High quality (CRF 18, larger files)
┊<b>medium</b> » Medium quality (CRF 23, balanced)
╰<b>low</b> » Low quality (CRF 28, smaller files)
"""
        await edit_message(message, text, btns)
    elif data[2] == "setconvertquality":
        await query.answer()
        option = data[3]
        # Validate against allowed qualities for safety
        allowed = {"original", "high", "medium", "low"}
        if option not in allowed:
            await query.edit_message_text("Invalid quality!")
            await sleep(1)
        else:
            update_user_ldata(user_id, "VIDEO_CONVERT_QUALITY", option)
            await database.update_user_data(user_id)
            await query.edit_message_text("Video convert quality updated!")
            await sleep(1)
        # Re-render submenu
        buttons = ButtonMaker()
        quality_option = user_dict.get("VIDEO_CONVERT_QUALITY", option)
        quality_options = ["original", "high", "medium", "low"]
        for q in quality_options:
            button_text = f"✓ {q}" if quality_option == q else q
            buttons.data_button(button_text, f"userset {user_id} setconvertquality {q}")
        buttons.data_button("Back", f"userset {user_id} ffsubmenu convert", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(2)
        text = f"""⭐ <b>Video Convert Quality :</b>
╭<b>Current Quality</b> » <b>{quality_option}</b>
┊
┊<b>Available Options:</b>
┊<b>original</b> » Keep original quality (when re-encoding)
┊<b>high</b> » High quality (CRF 18, larger files)
┊<b>medium</b> » Medium quality (CRF 23, balanced)
╰<b>low</b> » Low quality (CRF 28, smaller files)
"""
        await edit_message(message, text, btns)
    elif data[2] == "wmposition":
        await query.answer()
        # Show the Watermark Position submenu
        buttons = ButtonMaker()
        position = user_dict.get("VIDEO_WATERMARK_POSITION", "bottom-right")

        # Watermark position options
        position_options = [
            ("top-left", "Top Left"),
            ("top-center", "Top Center"),
            ("top-right", "Top Right"),
            ("center", "Center"),
            ("bottom-left", "Bottom Left"),
            ("bottom-center", "Bottom Center"),
            ("bottom-right", "Bottom Right"),
        ]

        # Add each option as individual button
        for option, display_name in position_options:
            # Mark the current selected position with a checkmark
            button_text = f"✓ {display_name}" if position == option else display_name
            buttons.data_button(button_text, f"userset {user_id} setwmpos {option}")

        buttons.data_button("Back", f"userset {user_id} ffsubmenu watermark", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(2)

        text = f"""〄 <b>Watermark Position :</b>
╭<b>Current Position</b> » <b>{position}</b>
┊
┊<b>Position Options:</b>
┊Choose where the watermark appears on video.
┊
┊<b>Top positions</b> » Watermark at top of video
┊<b>Center</b> » Watermark in middle of video
╰<b>Bottom positions</b> » Watermark at bottom of video
"""
        await edit_message(message, text, btns)
    elif data[2] == "setwmpos":
        await query.answer()
        # Update the user setting with selected position
        position = data[3]
        update_user_ldata(user_id, "VIDEO_WATERMARK_POSITION", position)
        await database.update_user_data(user_id)
        await query.edit_message_text("Watermark position updated!")
        await sleep(1)

        # Re-display the position menu with updated selection
        buttons = ButtonMaker()
        position_options = [
            ("top-left", "Top Left"),
            ("top-center", "Top Center"),
            ("top-right", "Top Right"),
            ("center", "Center"),
            ("bottom-left", "Bottom Left"),
            ("bottom-center", "Bottom Center"),
            ("bottom-right", "Bottom Right"),
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
┊<b>Position Options:</b>
┊Choose where the watermark appears on video.
┊
┊<b>Top positions</b> » Watermark at top of video
┊<b>Center</b> » Watermark in middle of video
╰<b>Bottom positions</b> » Watermark at bottom of video
"""
        await edit_message(message, text, btns)
    elif data[2] == "wmtype":
        await query.answer()
        # Show the Watermark Type submenu
        buttons = ButtonMaker()
        wm_type = user_dict.get("VIDEO_WATERMARK_TYPE", "text")

        # Watermark type options
        type_options = [("text", "Text Watermark"), ("image", "Image Watermark")]

        # Add each option as individual button
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
┊<b>Text Watermark:</b>
┊Uses your custom text as watermark.
┊Configurable font size, color, opacity.
┊
┊<b>Image Watermark:</b>
┊Uses an image file as watermark.
╰Requires setting image path separately.
"""
        await edit_message(message, text, btns)
    elif data[2] == "setwmtype":
        await query.answer()
        # Update the user setting with selected type
        wm_type = data[3]
        update_user_ldata(user_id, "VIDEO_WATERMARK_TYPE", wm_type)
        await database.update_user_data(user_id)
        await query.edit_message_text("Watermark type updated!")
        await sleep(1)

        # Re-display the type menu with updated selection
        buttons = ButtonMaker()
        type_options = [("text", "Text Watermark"), ("image", "Image Watermark")]

        for option, display_name in type_options:
            button_text = f"✓ {display_name}" if wm_type == option else display_name
            buttons.data_button(button_text, f"userset {user_id} setwmtype {option}")

        buttons.data_button("Back", f"userset {user_id} ffsubmenu watermark", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(1)

        text = f"""〄 <b>Watermark Type :</b>
╭<b>Current Type</b> » <b>{wm_type}</b>
┊
┊<b>Text Watermark:</b>
┊Uses your custom text as watermark.
┊Configurable font size, color, opacity.
┊
┊<b>Image Watermark:</b>
┊Uses an image file as watermark.
╰Requires setting image path separately.
"""
        await edit_message(message, text, btns)
    elif data[2] == "wmopacity":
        await query.answer()
        # Show the Watermark Opacity submenu
        buttons = ButtonMaker()
        opacity = user_dict.get("VIDEO_WATERMARK_OPACITY", 0.5)

        # Ensure opacity is a valid float
        try:
            if not isinstance(opacity, (int, float)):
                opacity = (
                    float(opacity)
                    if isinstance(opacity, str)
                    and opacity.replace(".", "", 1).isdigit()
                    else 0.5
                )
            if opacity < 0 or opacity > 1:
                opacity = 0.5
        except (ValueError, TypeError):
            opacity = 0.5

        # Opacity options
        opacity_options = [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]

        # Add each option as individual button
        for option in opacity_options:
            # Mark the current selected opacity with a checkmark
            try:
                button_text = (
                    f"✓ {int(option * 100)}%"
                    if opacity == option
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
            opacity_percent = int(opacity * 100)
        except (ValueError, TypeError):
            opacity_percent = 50

        text = f"""〄 <b>Watermark Opacity :</b>
╭<b>Current Opacity</b> » <b>{opacity_percent}%</b>
┊
┊<b>What is Opacity?</b>
┊Controls watermark transparency.
┊Lower values = more transparent
┊Higher values = more visible
┊
┊<b>20%-40%</b> » Subtle, barely visible
┊<b>50%-70%</b> » Balanced visibility
╰<b>80%-90%</b> » Very visible, prominent
"""
        await edit_message(message, text, btns)
    elif data[2] == "setwmopacity":
        await query.answer()
        # Update the user setting with selected opacity
        try:
            opacity = float(data[3])
            # Validate opacity is within acceptable range
            if 0 <= opacity <= 1:
                update_user_ldata(user_id, "VIDEO_WATERMARK_OPACITY", opacity)
                await database.update_user_data(user_id)
                await query.edit_message_text("Watermark opacity updated!")
                await sleep(1)
            else:
                await query.edit_message_text(
                    "Invalid opacity value! Must be between 0 and 1."
                )
                await sleep(1.5)
        except (ValueError, IndexError, TypeError):
            await query.edit_message_text("Error: Invalid opacity value format.")
            await sleep(1.5)

        # Re-display the opacity menu with updated selection
        buttons = ButtonMaker()
        opacity_options = [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]

        # Get current opacity setting, with robust error handling
        try:
            opacity = user_dict.get("VIDEO_WATERMARK_OPACITY", 0.5)
            if not isinstance(opacity, (int, float)):
                opacity = (
                    float(opacity)
                    if isinstance(opacity, str)
                    and opacity.replace(".", "", 1).isdigit()
                    else 0.5
                )
            if opacity < 0 or opacity > 1:
                opacity = 0.5
        except (ValueError, TypeError):
            opacity = 0.5

        for option in opacity_options:
            try:
                button_text = (
                    f"✓ {int(option * 100)}%"
                    if opacity == option
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
            opacity_percent = int(opacity * 100)
        except (ValueError, TypeError):
            opacity_percent = 50

        text = f"""〄 <b>Watermark Opacity :</b>
╭<b>Current Opacity</b> » <b>{opacity_percent}%</b>
┊
┊<b>What is Opacity?</b>
┊Controls watermark transparency.
┊Lower values = more transparent
┊Higher values = more visible
┊
┊<b>20%-40%</b> » Subtle, barely visible
┊<b>50%-70%</b> » Balanced visibility
╰<b>80%-90%</b> » Very visible, prominent
"""
        await edit_message(message, text, btns)
    elif data[2] == "wmduration":
        await query.answer()
        # Show the Watermark Duration submenu
        buttons = ButtonMaker()
        duration_type = user_dict.get("VIDEO_WATERMARK_DURATION_TYPE", "all")

        # Duration type options
        duration_options = [
            ("all", "All Video", "Watermark appears throughout entire video"),
            ("start", "Start Only", "Watermark appears at video beginning"),
            ("middle", "Middle Only", "Watermark appears in video center"),
            ("end", "End Only", "Watermark appears at video ending"),
        ]

        # Add each option as individual button
        for option, display_name, description in duration_options:
            # Mark the current selected duration with a checkmark
            button_text = (
                f"✓ {display_name}" if duration_type == option else display_name
            )
            buttons.data_button(
                button_text, f"userset {user_id} setwmduration {option}"
            )

        buttons.data_button("Back", f"userset {user_id} ffsubmenu watermark", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(2)

        seconds = user_dict.get("VIDEO_WATERMARK_DURATION_SECONDS", 10)
        text = f"""〄 <b>Watermark Duration :</b>
╭<b>Current Type</b> » <b>{duration_type}</b>
┊<b>Duration</b> » <b>{seconds} seconds</b>
┊
┊<b>Duration Types:</b>
┊<b>All Video</b> » Throughout entire video
┊<b>Start Only</b> » First {seconds} seconds
┊<b>Middle Only</b> » {seconds} seconds from center  
┊<b>End Only</b> » Last {seconds} seconds
┊
╰<i>Use 'WM Seconds' to change duration time.</i>
"""
        await edit_message(message, text, btns)
    elif data[2] == "setwmduration":
        await query.answer()
        # Update the user setting with selected duration type
        duration_type = data[3]
        update_user_ldata(user_id, "VIDEO_WATERMARK_DURATION_TYPE", duration_type)
        await database.update_user_data(user_id)
        await query.edit_message_text("Watermark duration type updated!")
        await sleep(1)

        # Re-display the duration menu with updated selection
        buttons = ButtonMaker()
        duration_options = [
            ("all", "All Video", "Watermark appears throughout entire video"),
            ("start", "Start Only", "Watermark appears at video beginning"),
            ("middle", "Middle Only", "Watermark appears in video center"),
            ("end", "End Only", "Watermark appears at video ending"),
        ]

        for option, display_name, description in duration_options:
            button_text = (
                f"✓ {display_name}" if duration_type == option else display_name
            )
            buttons.data_button(
                button_text, f"userset {user_id} setwmduration {option}"
            )

        buttons.data_button("Back", f"userset {user_id} ffsubmenu watermark", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(2)

        seconds = user_dict.get("VIDEO_WATERMARK_DURATION_SECONDS", 10)
        text = f"""〄 <b>Watermark Duration :</b>
╭<b>Current Type</b> » <b>{duration_type}</b>
┊<b>Duration</b> » <b>{seconds} seconds</b>
┊
┊<b>Duration Types:</b>
┊<b>All Video</b> » Throughout entire video
┊<b>Start Only</b> » First {seconds} seconds
┊<b>Middle Only</b> » {seconds} seconds from center  
┊<b>End Only</b> » Last {seconds} seconds
┊
╰<i>Use 'WM Seconds' to change duration time.</i>
"""
        await edit_message(message, text, btns)
    elif data[2] == "menu":
        await query.answer()
        await get_menu(data[3], message, user_id)
    elif data[2] == "tog":
        await query.answer()
        # Ignore USER_TRANSMISSION and HYBRID_LEECH toggles as they are removed
        if data[3] in ["USER_TRANSMISSION", "HYBRID_LEECH"]:
            await query.answer("This feature has been disabled.", show_alert=True)
            return

        update_user_ldata(user_id, data[3], data[4] == "t")
        if data[3] == "STOP_DUPLICATE":
            back_to = "gdrive"
        elif data[3] == "USER_TOKENS":
            back_to = "general"
        elif data[3] in ["AUTO_LEECH", "AUTO_MIRROR", "AUTO_FT"]:
            # For auto processing toggles, go back to auto_process menu
            # Update the user data and database first
            await database.update_user_data(user_id)

            # Get updated values from user_dict
            user_dict = user_data.get(user_id, {})
            auto_leech = user_dict.get("AUTO_LEECH", False)
            auto_mirror = user_dict.get("AUTO_MIRROR", False)
            auto_ft = user_dict.get("AUTO_FT", False)

            # Re-display the auto process menu with updated values
            buttons = ButtonMaker()
            buttons.data_button(
                "Disable Auto Leech" if auto_leech else "Enable Auto Leech",
                f"userset {user_id} tog AUTO_LEECH {'f' if auto_leech else 't'}",
            )
            buttons.data_button(
                "Disable Auto Mirror" if auto_mirror else "Enable Auto Mirror",
                f"userset {user_id} tog AUTO_MIRROR {'f' if auto_mirror else 't'}",
            )
            buttons.data_button(
                "Disable Auto -ft" if auto_ft else "Enable Auto -ft",
                f"userset {user_id} tog AUTO_FT {'f' if auto_ft else 't'}",
            )
            buttons.data_button("Back", f"userset {user_id} back", "footer")
            buttons.data_button("Close", f"userset {user_id} close", "footer")
            btns = buttons.build_menu(2)

            text = f"""〄 <b>Auto Leech/Mirror Settings :</b>
╭<b>Auto Leech</b> » <b>{"Enabled" if auto_leech else "Disabled"}</b>
┊<b>Auto Mirror</b> » <b>{"Enabled" if auto_mirror else "Disabled"}</b>
╰<b>Auto -ft</b> » <b>{"Enabled" if auto_ft else "Disabled"}</b>

<i>When enabled, the bot will automatically process any links or files you send:
• Auto Leech: Automatically leeches links/files
• Auto Mirror: Automatically mirrors links/files  
• Auto -ft: Asks for video tools selection like normal commands</i>"""
            await edit_message(message, text, btns)
            return
        elif data[3] in ffset_options:
            # Check if there's a submenu context parameter
            if len(data) >= 6 and data[5] in [
                "encode",
                "watermark",
                "intro",
                "hardsub",
                "convert",
            ]:
                # User toggled from a submenu, update database and refresh the submenu
                await database.update_user_data(user_id)

                # Get the updated user_dict after database save
                user_dict = user_data.get(user_id, {})
                submenu_type = data[5]
                message = query.message

                # Directly handle the submenu refresh
                if submenu_type == "encode":
                    # Show encode settings submenu with updated state
                    buttons = FFmpegButtonMaker()
                    video_encode_enabled = user_dict.get("VIDEO_ENCODE_ENABLED", False)

                    # Video encode toggle
                    buttons.data_button(
                        f"{'✓ ' if video_encode_enabled else ''}Video Encode",
                        f"userset {user_id} tog VIDEO_ENCODE_ENABLED {'f' if video_encode_enabled else 't'} encode",
                    )

                    if video_encode_enabled:
                        # Encode settings only show when encoding is enabled
                        default_preset = "medium"
                        current_preset = user_dict.get(
                            "VIDEO_ENCODE_PRESET", default_preset
                        )
                        has_custom_preset = current_preset != default_preset
                        buttons.data_button(
                            f"{'✓ ' if has_custom_preset else ''}Preset",
                            f"userset {user_id} menu VIDEO_ENCODE_PRESET",
                        )

                        default_quality = "Original"
                        current_quality = user_dict.get(
                            "VIDEO_ENCODE_QUALITY", default_quality
                        )
                        has_custom_quality = current_quality != default_quality
                        buttons.data_button(
                            f"{'✓ ' if has_custom_quality else ''}Quality",
                            f"userset {user_id} vidquality {user_id}",
                        )

                        default_crf = 23
                        current_crf = user_dict.get("VIDEO_ENCODE_CRF", default_crf)
                        has_custom_crf = current_crf != default_crf
                        buttons.data_button(
                            f"{'✓ ' if has_custom_crf else ''}CRF",
                            f"userset {user_id} videocrf {user_id}",
                        )

                        default_bitrate = "128k"
                        current_bitrate = user_dict.get(
                            "VIDEO_ENCODE_AUDIO_BITRATE", default_bitrate
                        )
                        has_custom_bitrate = current_bitrate != default_bitrate
                        buttons.data_button(
                            f"{'✓ ' if has_custom_bitrate else ''}Audio Bitrate",
                            f"userset {user_id} audiobitrate {user_id}",
                        )

                        # Codec selection
                        default_codec = "x264"
                        current_codec = user_dict.get(
                            "VIDEO_ENCODE_CODEC", default_codec
                        )
                        has_custom_codec = current_codec != default_codec
                        buttons.data_button(
                            f"{'✓ ' if has_custom_codec else ''}Codec",
                            f"userset {user_id} codec {user_id}",
                        )

                        # Multi-resolution encoding options
                        multi_res_enabled = user_dict.get(
                            "VIDEO_ENCODE_MULTI_RESOLUTION", False
                        )
                        buttons.data_button(
                            f"{'✓ ' if multi_res_enabled else ''}Multi-Res",
                            f"userset {user_id} tog VIDEO_ENCODE_MULTI_RESOLUTION {'f' if multi_res_enabled else 't'} encode",
                        )

                        if multi_res_enabled:
                            # Resolution selection button only shows when multi-res is enabled
                            resolution_list = user_dict.get(
                                "VIDEO_ENCODE_RESOLUTION_LIST", ""
                            )
                            has_custom_resolutions = bool(resolution_list.strip())
                            buttons.data_button(
                                f"{'✓ ' if has_custom_resolutions else ''}Resolutions",
                                f"userset {user_id} resolutions {user_id}",
                            )

                            # Multi-zip option only shows when multi-res is enabled
                            multi_zip_enabled = user_dict.get(
                                "VIDEO_ENCODE_MULTI_ZIP", False
                            )
                            buttons.data_button(
                                f"{'✓ ' if multi_zip_enabled else ''}Multi-Zip",
                                f"userset {user_id} tog VIDEO_ENCODE_MULTI_ZIP {'f' if multi_zip_enabled else 't'} encode",
                            )

                    buttons.data_button(
                        "Back", f"userset {user_id} back ffset", "footer"
                    )
                    buttons.data_button("Close", f"userset {user_id} close", "footer")
                    btns = buttons.build_menu(2)

                    encode_status = "Enabled" if video_encode_enabled else "Disabled"
                    preset = user_dict.get("VIDEO_ENCODE_PRESET", "medium")
                    quality = user_dict.get("VIDEO_ENCODE_QUALITY", "Original")
                    crf = user_dict.get("VIDEO_ENCODE_CRF", 23)
                    bitrate = user_dict.get("VIDEO_ENCODE_AUDIO_BITRATE", "128k")
                    codec = user_dict.get("VIDEO_ENCODE_CODEC", "x264")

                    # Multi-resolution settings for display
                    multi_res_enabled = user_dict.get(
                        "VIDEO_ENCODE_MULTI_RESOLUTION", False
                    )
                    multi_res_status = "Enabled" if multi_res_enabled else "Disabled"

                    resolution_list = user_dict.get("VIDEO_ENCODE_RESOLUTION_LIST", "")
                    if resolution_list.strip():
                        resolutions_display = resolution_list
                    else:
                        resolutions_display = "Auto (All Suitable)"

                    # Multi-zip setting for display
                    multi_zip_enabled = user_dict.get("VIDEO_ENCODE_MULTI_ZIP", False)
                    multi_zip_status = "Enabled" if multi_zip_enabled else "Disabled"

                    text = f"""📹 <b>Encode Settings</b>
╭<b>Video Encode</b> » <b>{encode_status}</b>
┊<b>Preset</b> » <b>{preset}</b>
┊<b>Quality</b> » <b>{quality}</b>
┊<b>CRF</b> » <b>{crf}</b>
┊<b>Audio Bitrate</b> » <b>{bitrate}</b>
┊<b>Codec</b> » <b>{codec}</b>
┊<b>Multi-Res</b> » <b>{multi_res_status}</b>
┊<b>Resolutions</b> » <b>{resolutions_display}</b>
╰<b>Multi-Zip</b> » <b>{multi_zip_status}</b>"""
                    await edit_message(message, text, btns)
                    return

                elif submenu_type == "watermark":
                    # Show watermark settings submenu with updated state
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
                        current_wm_text = user_dict.get(
                            "VIDEO_WATERMARK_TEXT", default_wm_text
                        )
                        has_custom_wm_text = current_wm_text != default_wm_text
                        buttons.data_button(
                            f"{'✓ ' if has_custom_wm_text else ''}Set Text",
                            f"userset {user_id} menu VIDEO_WATERMARK_TEXT",
                        )

                        default_wm_type = "text"
                        current_wm_type = user_dict.get(
                            "VIDEO_WATERMARK_TYPE", default_wm_type
                        )
                        has_custom_wm_type = current_wm_type != default_wm_type
                        buttons.data_button(
                            f"{'✓ ' if has_custom_wm_type else ''}WM-Type",
                            f"userset {user_id} wmtype {user_id}",
                        )

                        has_wm_image = bool(
                            user_dict.get("VIDEO_WATERMARK_IMAGE_PATH", "")
                        )
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

                        has_custom_font = bool(
                            user_dict.get("VIDEO_WATERMARK_FONT_PATH", "")
                        )
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

                        default_seconds = 10
                        current_seconds = user_dict.get(
                            "VIDEO_WATERMARK_DURATION_SECONDS", default_seconds
                        )
                        has_custom_seconds = current_seconds != default_seconds
                        buttons.data_button(
                            f"{'✓ ' if has_custom_seconds else ''}WM-Seconds",
                            f"userset {user_id} menu VIDEO_WATERMARK_DURATION_SECONDS",
                        )

                    buttons.data_button(
                        "Back", f"userset {user_id} back ffset", "footer"
                    )
                    buttons.data_button("Close", f"userset {user_id} close", "footer")
                    btns = buttons.build_menu(2)

                    watermark_status = "Enabled" if watermark_enabled else "Disabled"
                    wm_text = user_dict.get("VIDEO_WATERMARK_TEXT", "Default Watermark")
                    wm_type = user_dict.get("VIDEO_WATERMARK_TYPE", "text")
                    wm_position = user_dict.get(
                        "VIDEO_WATERMARK_POSITION", "bottom-right"
                    )
                    wm_opacity = user_dict.get("VIDEO_WATERMARK_OPACITY", 0.5)

                    text = f"""🌊 <b>Watermark Settings</b>
╭<b>Watermark</b> » <b>{watermark_status}</b>
┊<b>Text</b> » <code>{wm_text}</code>
┊<b>Type</b> » <b>{wm_type}</b>
┊<b>Position</b> » <b>{wm_position}</b>
╰<b>Opacity</b> » <b>{wm_opacity}</b>"""
                    await edit_message(message, text, btns)

                elif submenu_type == "intro":
                    # Show intro subtitle settings submenu with updated state
                    buttons = FFmpegButtonMaker()
                    intro_enabled = user_dict.get("INTRO_SUBTITLE_ENABLED", False)

                    # Intro Sub toggle
                    buttons.data_button(
                        f"{'✓ ' if intro_enabled else ''}Intro-Sub",
                        f"userset {user_id} tog INTRO_SUBTITLE_ENABLED {'f' if intro_enabled else 't'} intro",
                    )

                    if intro_enabled:
                        # Intro settings only show when enabled
                        has_intro_text = bool(user_dict.get("INTRO_SUBTITLE_TEXT"))
                        buttons.data_button(
                            f"{'✓ ' if has_intro_text else ''}IS-Text",
                            f"userset {user_id} menu INTRO_SUBTITLE_TEXT",
                        )

                        style = user_dict.get("INTRO_SUBTITLE_STYLE", "typing")
                        style_custom = style != "typing"
                        buttons.data_button(
                            f"{'✓ ' if style_custom else ''}IS-Style",
                            f"userset {user_id} menu INTRO_SUBTITLE_STYLE",
                        )

                        pos = user_dict.get("INTRO_SUBTITLE_POSITION", "bottom")
                        pos_custom = pos != "bottom"
                        buttons.data_button(
                            f"{'✓ ' if pos_custom else ''}IS-Pos",
                            f"userset {user_id} menu INTRO_SUBTITLE_POSITION",
                        )

                        has_intro_font = bool(user_dict.get("INTRO_SUBTITLE_FONT_PATH"))
                        buttons.data_button(
                            f"{'✓ ' if has_intro_font else ''}IS-Font",
                            f"userset {user_id} file INTRO_SUBTITLE_FONT_PATH",
                        )

                        font_size_def = 48
                        font_size_cur = user_dict.get(
                            "INTRO_SUBTITLE_FONT_SIZE", font_size_def
                        )
                        font_size_custom = font_size_cur != font_size_def
                        buttons.data_button(
                            f"{'✓ ' if font_size_custom else ''}IS-Size",
                            f"userset {user_id} menu INTRO_SUBTITLE_FONT_SIZE",
                        )

                        has_colors = bool(user_dict.get("INTRO_SUBTITLE_COLORS"))
                        buttons.data_button(
                            f"{'✓ ' if has_colors else ''}IS-Colours",
                            f"userset {user_id} menu INTRO_SUBTITLE_COLORS",
                        )

                        char_ms_def = 300
                        char_ms_cur = user_dict.get(
                            "INTRO_SUBTITLE_CHAR_MS", char_ms_def
                        )
                        char_ms_custom = char_ms_cur != char_ms_def
                        buttons.data_button(
                            f"{'✓ ' if char_ms_custom else ''}IS-ms",
                            f"userset {user_id} menu INTRO_SUBTITLE_CHAR_MS",
                        )

                    buttons.data_button(
                        "Back", f"userset {user_id} back ffset", "footer"
                    )
                    buttons.data_button("Close", f"userset {user_id} close", "footer")
                    btns = buttons.build_menu(2)

                    intro_status = "Enabled" if intro_enabled else "Disabled"
                    intro_text = user_dict.get("INTRO_SUBTITLE_TEXT", "Not Set")
                    intro_style = user_dict.get("INTRO_SUBTITLE_STYLE", "typing")
                    intro_pos = user_dict.get("INTRO_SUBTITLE_POSITION", "bottom")

                    text = f"""📝 <b>Intro Subtitle Settings</b>
╭<b>Intro Sub</b> » <b>{intro_status}</b>
┊<b>Text</b> » <code>{intro_text}</code>
┊<b>Style</b> » <b>{intro_style}</b>
╰<b>Position</b> » <b>{intro_pos}</b>"""
                    await edit_message(message, text, btns)
                    return

                elif submenu_type == "hardsub":
                    # Show hardsub settings submenu with updated state
                    buttons = FFmpegButtonMaker()
                    hardsub_enabled = user_dict.get("VIDEO_HARDSUB_ENABLED", False)

                    # Hardsub toggle
                    buttons.data_button(
                        f"{'✓ ' if hardsub_enabled else ''}Hardsub",
                        f"userset {user_id} tog VIDEO_HARDSUB_ENABLED {'f' if hardsub_enabled else 't'} hardsub",
                    )

                    if hardsub_enabled:
                        # Hardsub settings only show when enabled
                        style = user_dict.get("VIDEO_HARDSUB_STYLE", "default")
                        style_custom = style != "default"
                        buttons.data_button(
                            f"{'✓ ' if style_custom else ''}HS-Style",
                            f"userset {user_id} menu VIDEO_HARDSUB_STYLE",
                        )

                        font_size_def = 20
                        font_size_cur = user_dict.get(
                            "VIDEO_HARDSUB_FONT_SIZE", font_size_def
                        )
                        font_size_custom = font_size_cur != font_size_def
                        buttons.data_button(
                            f"{'✓ ' if font_size_custom else ''}HS-Size",
                            f"userset {user_id} menu VIDEO_HARDSUB_FONT_SIZE",
                        )

                        font_name = user_dict.get("VIDEO_HARDSUB_FONT_NAME", "Arial")
                        font_name_custom = font_name != "Arial"
                        buttons.data_button(
                            f"{'✓ ' if font_name_custom else ''}HS-Font",
                            f"userset {user_id} menu VIDEO_HARDSUB_FONT_NAME",
                        )

                    buttons.data_button(
                        "Back", f"userset {user_id} back ffset", "footer"
                    )
                    buttons.data_button("Close", f"userset {user_id} close", "footer")
                    btns = buttons.build_menu(2)

                    hardsub_status = "Enabled" if hardsub_enabled else "Disabled"
                    hardsub_style = user_dict.get("VIDEO_HARDSUB_STYLE", "default")
                    hardsub_font_size = user_dict.get("VIDEO_HARDSUB_FONT_SIZE", 20)
                    hardsub_font_name = user_dict.get(
                        "VIDEO_HARDSUB_FONT_NAME", "Arial"
                    )

                    text = f"""🔥 <b>Hardsub Settings</b>
╭<b>Hardsub</b> » <b>{hardsub_status}</b>
┊<b>Style</b> » <b>{hardsub_style}</b>
┊<b>Font Size</b> » <b>{hardsub_font_size}px</b>
╰<b>Font Name</b> » <b>{hardsub_font_name}</b>"""
                    await edit_message(message, text, btns)
                    return

                elif submenu_type == "convert":
                    # Show convert settings submenu with updated state
                    buttons = FFmpegButtonMaker()
                    video_convert_enabled = user_dict.get(
                        "VIDEO_CONVERT_ENABLED", False
                    )

                    # Video convert toggle
                    buttons.data_button(
                        f"{'✓ ' if video_convert_enabled else ''}Video Convert",
                        f"userset {user_id} tog VIDEO_CONVERT_ENABLED {'f' if video_convert_enabled else 't'} convert",
                    )

                    if video_convert_enabled:
                        # Convert settings only show when conversion is enabled
                        default_format = "mp4"
                        current_format = user_dict.get(
                            "VIDEO_CONVERT_FORMAT", default_format
                        )
                        has_custom_format = current_format != default_format
                        buttons.data_button(
                            f"{'✓ ' if has_custom_format else ''}Format",
                            f"userset {user_id} convertformat {user_id}",
                        )

                        default_codec = "copy"
                        current_codec = user_dict.get(
                            "VIDEO_CONVERT_CODEC", default_codec
                        )
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

                    buttons.data_button(
                        "Back", f"userset {user_id} back ffset", "footer"
                    )
                    buttons.data_button("Close", f"userset {user_id} close", "footer")
                    btns = buttons.build_menu(2)

                    convert_status = "Enabled" if video_convert_enabled else "Disabled"
                    convert_format = user_dict.get("VIDEO_CONVERT_FORMAT", "mp4")
                    convert_codec = user_dict.get("VIDEO_CONVERT_CODEC", "copy")
                    convert_quality = user_dict.get("VIDEO_CONVERT_QUALITY", "original")

                    text = f"""🔄 <b>Video Convert Settings</b>
╭<b>Convert</b> » <b>{convert_status}</b>
┊<b>Format</b> » <b>{convert_format.upper()}</b>
┊<b>Codec</b> » <b>{convert_codec}</b>
╰<b>Quality</b> » <b>{convert_quality}</b>"""
                    await edit_message(message, text, btns)

                return
            else:
                back_to = "ffset"
                await update_user_settings(query, stype=back_to)
                await database.update_user_data(user_id)
                return
        elif data[3] in [
            "SS_GRID_ENABLED",
            "SS_GRID_PDF_MODE",
            "SS_GRID_PDF_INDIVIDUAL_PAGES",
        ]:
            # For SS Grid toggles, update database and refresh the ssgrid submenu
            await database.update_user_data(user_id)

            # Get updated values from user_dict
            user_dict = user_data.get(user_id, {})
            ss_grid_enabled = user_dict.get("SS_GRID_ENABLED", False)
            ss_grid_count = user_dict.get("SS_GRID_COUNT", 9)
            ss_grid_layout = user_dict.get("SS_GRID_LAYOUT", "3x3")
            ss_grid_pdf_mode = user_dict.get("SS_GRID_PDF_MODE", False)
            ss_grid_watermark = user_dict.get("SS_GRID_WATERMARK", "")
            ss_grid_pdf_individual = user_dict.get("SS_GRID_PDF_INDIVIDUAL_PAGES", True)

            # Re-display the SS Grid menu with updated values
            buttons = ButtonMaker()
            buttons.data_button(
                "Enable" if not ss_grid_enabled else "Disable",
                f"userset {user_id} tog SS_GRID_ENABLED {'t' if not ss_grid_enabled else 'f'}",
            )
            buttons.data_button(
                "Set Screenshot Count", f"userset {user_id} menu SS_GRID_COUNT"
            )
            buttons.data_button(
                "Set Grid Layout", f"userset {user_id} menu SS_GRID_LAYOUT"
            )
            buttons.data_button(
                "Enable PDF Mode" if not ss_grid_pdf_mode else "Disable PDF Mode",
                f"userset {user_id} tog SS_GRID_PDF_MODE {'t' if not ss_grid_pdf_mode else 'f'}",
            )
            buttons.data_button(
                "Disable Individual Pages"
                if ss_grid_pdf_individual
                else "Enable Individual Pages",
                f"userset {user_id} tog SS_GRID_PDF_INDIVIDUAL_PAGES {'f' if ss_grid_pdf_individual else 't'}",
            )
            buttons.data_button(
                "Set PDF Watermark", f"userset {user_id} menu SS_GRID_WATERMARK"
            )
            buttons.data_button(
                "Back", f"userset {user_id} back common_tools", "footer"
            )
            buttons.data_button("Close", f"userset {user_id} close", "footer")
            btns = buttons.build_menu(2)

            text = f"""〄 <b>SS Grid Settings :</b>
╭<b>Status</b> » <b>{"Enabled" if ss_grid_enabled else "Disabled"}</b>
┊<b>Screenshot Count</b> » <b>{ss_grid_count}</b>
┊<b>Grid Layout</b> » <b>{ss_grid_layout}</b>
┊<b>PDF Mode</b> » <b>{"Enabled" if ss_grid_pdf_mode else "Disabled"}</b>
┊<b>PDF Individual Pages</b> » <b>{"Enabled" if ss_grid_pdf_individual else "Disabled"}</b>
╰<b>PDF Watermark</b> » <code>{ss_grid_watermark or "Not Set"}</code>"""
            await edit_message(message, text, btns)
            return
        elif data[3] in ["SAMPLE_VIDEO_ENABLED", "SAMPLE_VIDEO_SEPARATE"]:
            # For Sample Video toggles, update database and refresh the samplevideo submenu
            await database.update_user_data(user_id)

            # Get updated values from user_dict
            user_dict = user_data.get(user_id, {})
            sv_enabled = user_dict.get("SAMPLE_VIDEO_ENABLED", False)
            sv_count = user_dict.get("SAMPLE_VIDEO_COUNT", 1)
            sv_dur = user_dict.get("SAMPLE_VIDEO_DURATION", 60)
            sv_sep = user_dict.get("SAMPLE_VIDEO_SEPARATE", False)

            # Re-display the Sample Video menu with updated values
            buttons = ButtonMaker()
            buttons.data_button(
                "Enable" if not sv_enabled else "Disable",
                f"userset {user_id} tog SAMPLE_VIDEO_ENABLED {'t' if not sv_enabled else 'f'}",
            )
            buttons.data_button(
                "Set Clip Count", f"userset {user_id} menu SAMPLE_VIDEO_COUNT"
            )
            buttons.data_button(
                "Set Clip Duration", f"userset {user_id} menu SAMPLE_VIDEO_DURATION"
            )
            buttons.data_button(
                "Separate Clips" if not sv_sep else "Merge Clips",
                f"userset {user_id} tog SAMPLE_VIDEO_SEPARATE {'t' if not sv_sep else 'f'}",
            )
            buttons.data_button(
                "Back", f"userset {user_id} back common_tools", "footer"
            )
            buttons.data_button("Close", f"userset {user_id} close", "footer")
            btns = buttons.build_menu(2)
            text = f"""〄 <b>Sample Video Settings :</b>
╭<b>Status</b> » <b>{"Enabled" if sv_enabled else "Disabled"}</b>
┊<b>Clip Count</b> » <b>{sv_count}</b>
┊<b>Clip Duration</b> » <b>{sv_dur} sec</b>
╰<b>Output Mode</b> » <b>{"Separate Files" if sv_sep else "Single Merged File"}</b>

<i>The bot will generate random clip(s) from video(s) after download and include them with upload. Clip count * duration should not exceed 25% of original video length.</i>"""
            await edit_message(message, text, btns)
            return
        elif data[3] == "AUTO_RENAME":
            # For Auto Rename toggle, update database and refresh the autorename submenu
            await database.update_user_data(user_id)

            # Get updated values from user_dict
            user_dict = user_data.get(user_id, {})
            auto_rename = user_dict.get("AUTO_RENAME", False)
            template = user_dict.get("RENAME_TEMPLATE", "S{season}E{episode}Q{quality}")
            start_ep = user_dict.get("START_EPISODE", 1)
            start_season = user_dict.get("START_SEASON", 1)

            # Re-display the Auto Rename menu with updated values
            buttons = ButtonMaker()
            buttons.data_button(
                "Enable" if not auto_rename else "Disable",
                f"userset {user_id} tog AUTO_RENAME {'t' if not auto_rename else 'f'}",
            )
            buttons.data_button(
                "Set Template", f"userset {user_id} menu RENAME_TEMPLATE"
            )
            buttons.data_button(
                "Set Start Episode", f"userset {user_id} menu START_EPISODE"
            )
            buttons.data_button(
                "Set Start Season", f"userset {user_id} menu START_SEASON"
            )
            buttons.data_button(
                "Back", f"userset {user_id} back common_tools", "footer"
            )
            buttons.data_button("Close", f"userset {user_id} close", "footer")
            btns = buttons.build_menu(2)
            text = f"""〄 <b>Auto Rename Settings :</b>\n╭<b>Status</b> » <b>{"Enabled" if auto_rename else "Disabled"}</b>\n┊<b>Template</b> » <code>{template}</code>\n┊<b>Start Episode</b> » <b>{start_ep}</b>\n┊<b>Current Episode</b> » <b>{user_dict.get("_CURRENT_EPISODE", start_ep)}</b>\n╰<b>Start Season</b> » <b>{start_season}</b>"""
            await edit_message(message, text, btns)
            return
        elif data[3] in ["AUTO_THUMBNAIL", "EMBED_USER_IMAGE_AS_COVER"]:
            # For Auto Thumbnail and Thumb as Cover toggles, redirect back to common_tools
            back_to = "common_tools"
        else:
            back_to = "leech"

        await database.update_user_data(user_id)
        await update_user_settings(query, stype=back_to)

    elif data[2] == "file":
        await query.answer()
        buttons = ButtonMaker()
        text = user_settings_text[data[3]][2]
        buttons.data_button("Stop", f"userset {user_id} menu {data[3]} stop")
        buttons.data_button("Back", f"userset {user_id} menu {data[3]}", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")

        # Handle case where message.text might be None
        current_text = message.text.html if message.text else ""
        await edit_message(message, current_text + "\n\n" + text, buttons.build_menu(1))
        rfunc = partial(get_menu, data[3], message, user_id)
        pfunc = partial(add_file, ftype=data[3], rfunc=rfunc)
        await event_handler(
            client,
            query,
            pfunc,
            rfunc,
            photo=data[3] in ["THUMBNAIL", "VIDEO_WATERMARK_IMAGE_PATH"],
            document=data[3]
            in [
                "RCLONE_CONFIG",
                "TOKEN_PICKLE",
                "YTDLP_COOKIES",
                "VIDEO_WATERMARK_IMAGE_PATH",
                "VIDEO_WATERMARK_FONT_PATH",
            ],
        )
    elif data[2] in ["set", "addone", "rmone"]:
        await query.answer()
        buttons = ButtonMaker()
        if data[2] == "set":
            text = user_settings_text[data[3]][2]
            func = set_option
        elif data[2] == "addone":
            text = f"Add one or more string key and value to {data[3]}. Example: {{'key 1': 62625261, 'key 2': 'value 2'}}. Timeout: 60 sec"
            func = add_one
        elif data[2] == "rmone":
            text = f"Remove one or more key from {data[3]}. Example: key 1/key2/key 3. Timeout: 60 sec"
            func = remove_one
        buttons.data_button("Stop", f"userset {user_id} menu {data[3]} stop")
        buttons.data_button("Back", f"userset {user_id} menu {data[3]}", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")

        # Handle case where message.text might be None
        current_text = message.text.html if message.text else ""
        await edit_message(message, current_text + "\n\n" + text, buttons.build_menu(1))
        rfunc = partial(get_menu, data[3], message, user_id)
        pfunc = partial(func, option=data[3], rfunc=rfunc)
        await event_handler(client, query, pfunc, rfunc)
    elif data[2] == "remove":
        await query.answer("Removed!", show_alert=True)
        if data[3] in ["THUMBNAIL", "RCLONE_CONFIG", "TOKEN_PICKLE"]:
            if data[3] == "THUMBNAIL":
                fpath = thumb_path
            elif data[3] == "RCLONE_CONFIG":
                fpath = rclone_conf
            else:
                fpath = token_pickle
            if await aiopath.exists(fpath):
                await remove(fpath)
            del user_dict[data[3]]
            await database.update_user_doc(user_id, data[3])
        else:
            update_user_ldata(user_id, data[3], "")
            await database.update_user_data(user_id)
        await get_menu(data[3], message, user_id)
    elif data[2] == "reset" and data[3] == "USER_SESSION_STRING":
        from ..helper.ext_utils.user_session_manager import UserSessionManager

        await query.answer("User session removed!", show_alert=True)
        await UserSessionManager.remove_user_session(user_id)
        update_user_ldata(user_id, "USER_SESSION_STRING", "")
        await database.update_user_data(user_id)
        await get_menu(data[3], message, user_id)
    elif data[2] == "reset_episode":
        await query.answer("Episode counter reset!", show_alert=True)
        user_dict["_CURRENT_EPISODE"] = user_dict.get("START_EPISODE", 1)
        await database.update_user_data(user_id)
        # Refresh the autorename submenu
        buttons = ButtonMaker()
        auto_rename = user_dict.get("AUTO_RENAME", False)
        template = user_dict.get("RENAME_TEMPLATE", "S{season}E{episode}Q{quality}")
        start_ep = user_dict.get("START_EPISODE", 1)
        start_season = user_dict.get("START_SEASON", 1)
        buttons.data_button(
            "Enable" if not auto_rename else "Disable",
            f"userset {user_id} tog AUTO_RENAME {'t' if not auto_rename else 'f'}",
        )
        buttons.data_button("Set Template", f"userset {user_id} menu RENAME_TEMPLATE")
        buttons.data_button(
            "Set Start Episode", f"userset {user_id} menu START_EPISODE"
        )
        buttons.data_button("Set Start Season", f"userset {user_id} menu START_SEASON")
        buttons.data_button("Back", f"userset {user_id} back leech", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(2)
        text = f"""〄 <b>Auto Rename Settings :</b>\n╭<b>Status</b> » <b>{"Enabled" if auto_rename else "Disabled"}</b>\n┊<b>Template</b> » <code>{template}</code>\n┊<b>Start Episode</b> » <b>{start_ep}</b>\n┊<b>Current Episode</b> » <b>{user_dict.get("_CURRENT_EPISODE", start_ep)}</b>\n╰<b>Start Season</b> » <b>{start_season}</b>"""
        await edit_message(message, text, btns)
    elif data[2] == "reset":
        await query.answer("Reset Done!", show_alert=True)
        user_dict.pop(data[3], None)
        await database.update_user_data(user_id)
        await get_menu(data[3], message, user_id)
    elif data[2] == "confirm_reset_all":
        await query.answer()
        buttons = ButtonMaker()
        buttons.data_button("Yes", f"userset {user_id} do_reset_all yes")
        buttons.data_button("No", f"userset {user_id} do_reset_all no")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        text = "<i>Are you sure you want to reset all your user settings?</i>"
        await edit_message(query.message, text, buttons.build_menu(2))
    elif data[2] == "do_reset_all":
        if data[3] == "yes":
            await query.answer("Reset Done!", show_alert=True)
            user_dict = user_data.get(user_id, {})
            for k in list(user_dict.keys()):
                if k not in ("SUDO", "AUTH", "VERIFY_TOKEN", "VERIFY_TIME"):
                    del user_dict[k]
            for fpath in [thumb_path, rclone_conf, token_pickle]:
                if await aiopath.exists(fpath):
                    await remove(fpath)
            await update_user_settings(query)
            await database.update_user_data(user_id)
        else:
            await query.answer("Reset Cancelled.", show_alert=True)
            await update_user_settings(query)
    elif data[2] == "view":
        await query.answer()
        await send_file(message, thumb_path, name)
    elif data[2] in ["gd", "rc", "gofile"] or "_" in data[2]:
        await query.answer()
        context = "general"  # default context

        if "_" in data[2]:
            # Handle new format like "rc_gd", "rc_gofile", "gd_rc", etc.
            current_mode, target_mode = data[2].split("_")
            du = target_mode
            # Check if context is provided
            if len(data) > 3:
                context = data[3]
        else:
            # Handle legacy format for backwards compatibility
            du = "rc" if data[2] == "gd" else "gd"
            # Check if context is provided
            if len(data) > 3:
                context = data[3]

        update_user_ldata(user_id, "DEFAULT_UPLOAD", du)
        await update_user_settings(query, stype=context)
        await database.update_user_data(user_id)
    elif data[2] == "back":
        await query.answer()
        stype = data[3] if len(data) == 4 else "main"
        await update_user_settings(query, stype)
    else:
        await query.answer()
        await delete_message(message, message.reply_to_message)


@new_task
async def get_users_settings(_, message):
    msg = ""
    if auth_chats:
        msg += f"AUTHORIZED_CHATS: {auth_chats}\n"
    if sudo_users:
        msg += f"SUDO_USERS: {sudo_users}\n\n"
    if user_data:
        for u, d in user_data.items():
            kmsg = f"\n<b>{u}:</b>\n"
            if vmsg := "".join(
                f"{k}: <code>{v or None}</code>\n" for k, v in d.items()
            ):
                msg += kmsg + vmsg
        if not msg:
            await send_message(message, "No users data!")
            return
        msg_ecd = msg.encode()
        if len(msg_ecd) > 4000:
            with BytesIO(msg_ecd) as ofile:
                ofile.name = "users_settings.txt"
                await send_file(message, ofile)
        else:
            await send_message(message, msg)
    else:
        await send_message(message, "No users data!")
