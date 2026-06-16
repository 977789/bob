START_MSG = """
This bot can mirror from links|tgfiles|torrents|nzb|rclone-cloud to any rclone cloud, Google Drive or to telegram.
Type /{cmd} to get a list of available commands
"""
START_BUTTON1 = "Git Repo"
START_BUTTON2 = "Updates"

# --- UI Labels for Metadata Fields ---
UI_LABEL_GLOBAL_TITLE = "Global Title"
UI_LABEL_GLOBAL_ARTIST = "Global Artist"
UI_LABEL_GLOBAL_AUTHOR = "Global Author"
UI_LABEL_GLOBAL_COMMENT = "Global Comment"

UI_LABEL_VIDEO_TITLE = "Video Title"
UI_LABEL_VIDEO_ARTIST = "Video Artist"
UI_LABEL_VIDEO_AUTHOR = "Video Author"
UI_LABEL_VIDEO_COMMENT = "Video Comment"

UI_LABEL_AUDIO_TITLE = "Audio Title"
UI_LABEL_AUDIO_ARTIST = "Audio Artist"
UI_LABEL_AUDIO_AUTHOR = "Audio Author"
UI_LABEL_AUDIO_COMMENT = "Audio Comment"

UI_LABEL_SUBTITLE_TITLE = "Subtitle Title"
UI_LABEL_SUBTITLE_ARTIST = "Subtitle Artist"
UI_LABEL_SUBTITLE_AUTHOR = "Subtitle Author"
UI_LABEL_SUBTITLE_COMMENT = "Subtitle Comment"

UI_LABEL_METADATA_ALL = "Universal Metadata"  # New
UI_LABEL_WEBSITE = "Website"  # New

# --- UI Button Texts ---
UI_BUTTON_METADATA_SETTINGS = (
    "Metadata Configuration"  # Renamed from METADATA_SETTINGS_SUBMENU_BUTTON_TEXT
)

# --- UI Prompts for Metadata Input ---
UI_PROMPT_GLOBAL_TITLE = (
    "<i>🎬 Enter the Global Title. This will be mapped to the standard 'Title' tag.</i>"
)
UI_PROMPT_GLOBAL_ARTIST = "<i>🎤 Enter the Global Artist. This will be mapped to the standard 'Artist' tag.</i>"
UI_PROMPT_GLOBAL_AUTHOR = (
    "<i>✍️ Enter the Global Author. This will be mapped to the 'author' tag.</i>"
)
UI_PROMPT_GLOBAL_COMMENT = "<i>💬 Enter the Global Comment. This will be mapped to the standard 'Comment' tag.</i>"

UI_PROMPT_VIDEO_TITLE = "<i>🎬 Enter the Video Title. Applied to video streams.</i>"
UI_PROMPT_VIDEO_ARTIST = "<i>🎤 Enter the Video Artist. Applied to video streams.</i>"
UI_PROMPT_VIDEO_AUTHOR = "<i>✍️ Enter the Video Author. Applied to video streams and mapped to the 'author' tag.</i>"
UI_PROMPT_VIDEO_COMMENT = "<i>💬 Enter the Video Comment. Applied to video streams.</i>"

UI_PROMPT_AUDIO_TITLE = "<i>🎵 Enter the Audio Title. Applied to audio streams.</i>"
UI_PROMPT_AUDIO_ARTIST = "<i>🎤 Enter the Audio Artist. Applied to audio streams.</i>"
UI_PROMPT_AUDIO_AUTHOR = "<i>✍️ Enter the Audio Author. Applied to audio streams and mapped to the 'author' tag.</i>"
UI_PROMPT_AUDIO_COMMENT = "<i>💬 Enter the Audio Comment. Applied to audio streams.</i>"

UI_PROMPT_SUBTITLE_TITLE = (
    "<i>📖 Enter the Subtitle Title. Applied to subtitle streams.</i>"
)
UI_PROMPT_SUBTITLE_ARTIST = (
    "<i>🎤 Enter the Subtitle Artist. Applied to subtitle streams.</i>"
)
UI_PROMPT_SUBTITLE_AUTHOR = "<i>✍️ Enter the Subtitle Author. Applied to subtitle streams and mapped to the 'author' tag.</i>"
UI_PROMPT_SUBTITLE_COMMENT = (
    "<i>💬 Enter the Subtitle Comment. Applied to subtitle streams.</i>"
)

UI_PROMPT_METADATA_ALL = "<i>🌐 Enter a universal metadata value. This will be used for any standard field that is not specifically set. It can also populate the 'Website' tag.</i>"  # New
UI_PROMPT_WEBSITE = "<i>🔗 Enter the Website/Source URL. This will be mapped to the standard 'Website' (WWW) tag.</i>"  # New
