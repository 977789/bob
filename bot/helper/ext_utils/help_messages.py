from ..telegram_helper.bot_commands import BotCommands

mirror = """<b>Send link along with command line or </b>

/cmd link

<b>By replying to link/file</b>:

/cmd -n new name -e -up upload destination

<b>NOTE:</b>
1. Commands that start with <b>qb</b> are ONLY for torrents."""

yt = """<b>Send link along with command line</b>:

/cmd link
<b>By replying to link</b>:
/cmd -n new name -z password -opt x:y|x1:y1

<b>NOTE:</b>
1. Robust cookie detection is in place; the bot will check for `cookies.txt` in the root, `cookies/<user_id>/cookies.txt`, and then the `COOKIES` environment variable.
2. For advanced configurations, you can set `YT_DLP_OPTIONS` in your config file.

Check here all supported <a href='https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md'>SITES</a>
Check all yt-dlp api options from this <a href='https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/YoutubeDL.py#L212'>FILE</a> or use this <a href='https://t.me/mltb_official_channel/177'>script</a> to convert cli arguments to api options."""

clone = """Send Gdrive|Gdot|Filepress|Filebee|Appdrive|Gdflix link or rclone path along with command or by replying to the link/rc_path by command.
Use -sync to use sync method in rclone. Example: /cmd rcl/rclone_path -up rcl/rclone_path/rc -sync"""

new_name = """<b>New Name</b>: -n

/cmd link -n new name
Note: Doesn't work with torrents"""

multi_link = """<b>Multi links only by replying to first link/file</b>: -i

/cmd -i 10(number of links/files)"""

same_dir = """<b>Move file(s)/folder(s) to new folder</b>: -m

You can use this arg also to move multiple links/torrents contents to the same directory, so all links will be uploaded together as one task

/cmd link -m new folder (only one link inside new folder)
/cmd -i 10(number of links/files) -m folder name (all links contents in one folder)
/cmd -b -m folder name (reply to batch of message/file(each link on new line))

While using bulk you can also use this arg with different folder name along with the links in message or file batch
Example:
link1 -m folder1
link2 -m folder1
link3 -m folder2
link4 -m folder2
link5 -m folder3
link6
so link1 and link2 content will be uploaded from same folder which is folder1
link3 and link4 content will be uploaded from same folder also which is folder2
link5 will uploaded alone inside new folder named folder3
link6 will get uploaded normally alone
"""

thumb = """<b>Thumbnail for current task</b>: -t

/cmd link -t tg-message-link (doc or photo) or none (file without thumb)"""

split_size = """<b>Split size for current task</b>: -sp

/cmd link -sp (500mb or 2gb or 4000000000)
Note: Only mb and gb are supported or write in bytes without unit!"""

upload = """<b>Upload Destination</b>: -up

/cmd link -up rcl/gdl/gofile (rcl: to select rclone config, remote & path | gdl: To select token.pickle, gdrive id | gofile: Upload to GoFile)
You can directly add the upload path: -up remote:dir/subdir or -up Gdrive_id or -up gofile or -up gf or -up id/username (telegram) or -up id/username|topic_id (telegram)
If DEFAULT_UPLOAD is `rc` then you can pass up: `gd` to upload using gdrive tools to GDRIVE_ID or `gofile` to upload to GoFile.
If DEFAULT_UPLOAD is `gd` then you can pass up: `rc` to upload to RCLONE_PATH or `gofile` to upload to GoFile.
If DEFAULT_UPLOAD is `gofile` then you can pass up: `rc` to upload to RCLONE_PATH or `gd` to upload to GDRIVE_ID.

If you want to add path or gdrive manually from your config/token (UPLOADED FROM USETTING) add mrcc: for rclone and mtp: before the path/gdrive_id without space.
/cmd link -up mrcc:main:dump or -up mtp:gdrive_id <strong>or you can simply edit upload using owner/user token/config from usetting without adding mtp: or mrcc: before the upload path/id</strong>

To add leech destination:
-up id/@username/pm
-up b:id/@username/pm (b: means leech by bot) (id or username of the chat or write pm means private message so bot will send the files in private to you)
when you should use b:(leech by bot)? When your default settings is leech by user and you want to leech by bot for specific task.
-up u:id/@username(u: means leech by user) This incase OWNER added USER_STRING_SESSION.
-up h:id/@username(hybrid leech) h: to upload files by bot and user based on file size.
-up id/@username|topic_id(leech in specific chat and topic) add | without space and write topic id after chat id or username.

In case you want to specify whether using token.pickle or service accounts you can add tp:gdrive_id (using token.pickle) or sa:gdrive_id (using service accounts) or mtp:gdrive_id (using token.pickle uploaded from usetting).
DEFAULT_UPLOAD doesn't affect on leech cmds.
"""

user_download = """<b>User Download</b>: link

/cmd tp:link to download using owner token.pickle incase service account enabled.
/cmd sa:link to download using service account incase service account disabled.
/cmd tp:gdrive_id to download using token.pickle and file_id incase service account enabled.
/cmd sa:gdrive_id to download using service account and file_id incase service account disabled.
/cmd mtp:gdrive_id or mtp:link to download using user token.pickle uploaded from usetting
/cmd mrcc:remote:path to download using user rclone config uploaded from usetting
you can simply edit upload using owner/user token/config from usetting without adding mtp: or mrcc: before the path/id"""

rcf = """<b>Rclone Flags</b>: -rcf

/cmd link|path|rcl -up path|rcl -rcf --buffer-size:8M|--drive-starred-only|key|key:value
This will override all other flags except --exclude
Check here all <a href='https://rclone.org/flags/'>RcloneFlags</a>."""

bulk = """<b>Bulk Download</b>: -b

Bulk can be used only by replying to text message or text file contains links separated by new line.
Example:
link1 -n new name -up remote1:path1 -rcf |key:value|key:value
link2 -z -n new name -up remote2:path2
link3 -e -n new name -up remote2:path2
Reply to this example by this cmd -> /cmd -b(bulk)

Note: Any arg along with the cmd will be setted to all links
/cmd -b -up remote: -z -m folder name (all links contents in one zipped folder uploaded to one destination)
so you can't set different upload destinations along with link incase you have added -m along with cmd
You can set start and end of the links from the bulk like seed, with -b start:end or only end by -b :end or only start by -b start.
The default start is from zero(first link) to inf."""

rlone_dl = """<b>Rclone Download</b>:

Treat rclone paths exactly like links
/cmd main:dump/ubuntu.iso or rcl(To select config, remote and path)
Users can add their own rclone from user settings
If you want to add path manually from your config add mrcc: before the path without space
/cmd mrcc:main:dump/ubuntu.iso
You can simply edit using owner/user config from usetting without adding mrcc: before the path"""

extract_zip = """<b>Extract/Zip</b>: -e -z

/cmd link -e password (extract password protected)
/cmd link -z password (zip password protected)
/cmd link -z password -e (extract and zip password protected)
Note: When both extract and zip added with cmd it will extract first and then zip, so always extract first"""

join = """<b>Join Splitted Files</b>: -j

This option will only work before extract and zip, so mostly it will be used with -m argument (samedir)
By Reply:
/cmd -i 3 -j -m folder name
/cmd -b -j -m folder name
if u have link(folder) have splitted files:
/cmd link -j"""

tg_links = """<b>TG Links</b>:

Treat links like any direct link
Some links need user access so you must add USER_SESSION_STRING for it.
Three types of links:
Public: https://t.me/channel_name/message_id
Private: tg://openmessage?user_id=xxxxxx&message_id=xxxxx
Super: https://t.me/c/channel_id/message_id
Range: https://t.me/channel_name/first_message_id-last_message_id
Range Example: tg://openmessage?user_id=xxxxxx&message_id=555-560 or https://t.me/channel_name/100-150
Note: Range link will work only by replying cmd to it"""

sample_video = """<b>Sample Video</b>: -sv

Create sample video for one video or folder of videos.
/cmd -sv (it will take the default values which 60sec sample duration and part duration is 4sec).
You can control those values. Example: /cmd -sv 70:5(sample-duration:part-duration) or /cmd -sv :5 or /cmd -sv 70."""

screenshot = """<b>ScreenShots</b>: -ss

Create screenshots for one video or folder of videos.
/cmd -ss (it will take the default values which is 10 photos).
You can control this value. Example: /cmd -ss 6.

<b>SS Grid Features</b>: -ssg -ssgc -ssgl -ssgp -ssgw

Generate a grid of screenshots with various options:
- -ssg (Enable SS Grid feature)
- -ssgc N (Set screenshot count, e.g. -ssgc 12)
- -ssgl WxH (Set grid layout, e.g. -ssgl 3x4)
- -ssgp (Enable PDF mode to combine screenshots)
- -ssgw "text" (Add watermark to PDF)

Example: /cmd link -ssg -ssgc 12 -ssgl 3x4 -ssgp -ssgw "Downloaded by Bot"
"""
ss_grid = """<b>SS Grid Features</b>: Generate a grid of screenshots with various options

<b>Toggles and settings (via /usetting → SS Grid):</b>
• SS Grid: Enable/Disable
• Count: Number of screenshots (e.g., 12)
• Layout: Grid layout (WxH, e.g., 3x4)
• PDF Mode: Combine into a single PDF
• Watermark: Text watermark on the PDF
• Individual Pages: One image per page in PDF

<b>Command args:</b>
-ssg (enable)
-ssgc N (count)
-ssgl WxH (layout)
-ssgp (PDF mode)
-ssgw "text" (watermark)

Example: <code>/cmd link -ssg -ssgc 12 -ssgl 3x4 -ssgp -ssgw "Downloaded by Bot"</code>
"""

auto_rename_help = """<b>Auto Rename</b>
When enabled, files are renamed using a template with episode/season/quality and optional metadata.

<b>Template placeholders:</b>
• {season}, {episode} (zero-padded), {season2}, {episode2} (non-padded)
• {quality}, {title}, {year}, {audio}, {original_filename}

<b>Notes:</b>
• Double braces like <code>S{{season}}E{{episode}}</code> are supported.
• Episode numbering increments in Manual mode; Auto mode extracts from filename.
• Sequential upload ordering is automatic with Auto Rename ON.
"""

remname_help = r"""<b>Remname - Remove/Replace Filename Patterns</b>

<b>Command-Line Flag:</b> <code>-remname</code>
Remove or replace patterns from filenames during download/upload.

<b>Syntax (Command-Line):</b>
Pattern rules are <b>space-separated</b>. Each rule can be:
• <code>pattern</code> - Remove pattern completely
• <code>pattern|replacement</code> - Replace pattern with replacement text

<b>Examples:</b>

<b>1. Pattern Removal (space-separated):</b>
<code>-remname "WEB-DL RARBG 1080p"</code>
Result: Removes "WEB-DL", "RARBG", and "1080p" from filename

<b>2. Pattern Replacement (pipe separates pattern|replacement):</b>
<code>-remname "(Chinese)|ENG"</code>
Result: Replaces "(Chinese)" with "ENG"

<b>3. Multiple Replacements (space separates each rule):</b>
<code>-remname "(Chinese)|ENG (Japanese)|JPN"</code>
Result: Rule 1: "(Chinese)" → "ENG", Rule 2: "(Japanese)" → "JPN"

<b>4. Mixed Operations (some replace, some remove):</b>
<code>-remname "(Chinese)|ENG RARBG Sample"</code>
Result: Replaces "(Chinese)" with "ENG", removes "RARBG" and "Sample"

<b>Real-World Example:</b>
Input: <code>Movie.(Chinese).WEB-DL.RARBG.1080p.mkv</code>
Command: <code>-remname "(Chinese)|ENG WEB-DL RARBG"</code>
Output: <code>Movie.ENG.1080p.mkv</code>

<b>Notes:</b>
• Case-insensitive matching
• Works with files and folders
• Merges with user's default patterns from /usetting
• Applied before other filename operations

<b>User Settings (via /usetting):</b>
Different syntax: Use <code>|</code> to separate patterns (legacy mode)
• Example: <code>WEB-DL|RARBG|1080p</code> (removes all three)
• Prefix with <code>regex:</code> for regex: <code>regex:www\S+|mkvCinemas</code>
• Command-line patterns are added to user settings patterns
"""

attachments_help = """<b>Attachments</b>
Settings (via /usetting → Attachments):
• Embed Default Thumb: Attach your default thumbnail if none provided
• Set Attach Text: Attach a .txt with custom content (send 'none' to clear)
• Set Attach Photo: Attach a custom photo per upload

These also work with metadata processing; attachments are embedded during metadata phase when set.

<b>Notes:</b>
• Attachments are skipped for subtitle-only inputs.
• Attachments are processed after video tools, so they will be applied to the final output.
"""

user_session_help = """<b>User Session</b>
Upload through your Telegram user account where permitted.
• Set via /usetting → Advanced → User Session
• Hybrid Leech (-hl) uses user/bot based on size when enabled
• Permissions are checked before using user session in target chats
"""

seed = """<b>Bittorrent seed</b>: -d

/cmd link -d ratio:seed_time or by replying to file/link
To specify ratio and seed time add -d ratio:time.
Example: -d 0.7:10 (ratio and time) or -d 0.7 (only ratio) or -d :10 (only time) where time in minutes"""

zip_arg = """<b>Zip</b>: -z password

/cmd link -z (zip)
/cmd link -z password (zip password protected)"""

qual = """<b>Quality Buttons</b>: -s

In case default quality added from yt-dlp options using format option and you need to select quality for specific link or links with multi links feature.
/cmd link -s"""

yt_opt = """<b>Options</b>: -opt

/cmd link -opt {"format": "bv*+mergeall[vcodec=none]", "nocheckcertificate": True, "playliststart": 10, "fragment_retries": float("inf"), "matchtitle": "S13", "writesubtitles": True, "live_from_start": True, "postprocessor_args": {"ffmpeg": ["-threads", "4"]}, "wait_for_video": (5, 100), "download_ranges": [{"start_time": 0, "end_time": 10}]}

<b>NOTE:</b> For persistent settings, you can use `YT_DLP_OPTIONS` in your config file. Command-line `-opt` will override the config settings for that specific task.

Check all yt-dlp api options from this <a href='https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/YoutubeDL.py#L184'>FILE</a> or use this <a href='https://t.me/mltb_official_channel/177'>script</a> to convert cli arguments to api options."""

convert_media = """<b>Convert Media</b>: -ca -cv
/cmd link -ca mp3 -cv mp4 (convert all audios to mp3 and all videos to mp4)
/cmd link -ca mp3 (convert all audios to mp3)
/cmd link -cv mp4 (convert all videos to mp4)
/cmd link -ca mp3 + flac ogg (convert only flac and ogg audios to mp3)
/cmd link -cv mkv - webm flv (convert all videos to mp4 except webm and flv)"""

vt_main = """<b>Video Tools - Enhanced Edition</b>

Use <code>/vt</code> or the VT menu to configure operations without re-typing commands.

<b>How to use:</b>
1) Send a link or file, then tap the Video Tools button
2) Choose a tool (Watermark, Intro Sub, Merge, Convert, Reorder, Multi-Res, Extract, Remove, etc.)
3) Follow the guided steps; Done to apply

<b>🆕 Enhanced Features:</b>
• Multi-Resolution Encoding, Advanced Stream Tools, Enhanced FFmpeg Progress

<b>Per-task vs User Settings:</b>
• Per-task selections override User Settings for that task only
• User Settings provide defaults (e.g., fonts, colors, Intro Sub toggle)

<b>Quick command examples:</b>
• Leech 3 files into one VT session: <code>/{BotCommands.LeechCommand[1]} -i 3 -m "My Set" -vt</code>
• Mirror 2 files into one VT session: <code>/{BotCommands.MirrorCommand[1]} -i 2 -m "My Set" -vt</code>
• If you don’t want -vt prompts, preconfigure via <b>/usetting → Video Tools</b> and just run your normal command.
"""

vt_watermark = """<b>Watermark</b>

<b>From VT Menu:</b>
• Send image or enter text (text shows a preview)
• Font: Default or Upload (.ttf/.otf as document)
• Size (% of image width or font size for text)
• Position: overlay X:Y (buttons offer presets)
• Popup: optional, show watermark periodically (every N seconds)

<b>From User Settings:</b>
• Set WM Image (auto applies to tasks)
• Set WM Text (+ optional bold/font)
• Set WM Position (X:Y or presets)
• Set WM Size (default % when not set via VT)

<b>Notes:</b>
• Image + Text can be combined (text drawn when image present)
• Hardsub (burn subtitles) available via settings string or subs merge
"""

vt_intro = """<b>Intro Sub</b>

<b>From VT Menu:</b>
• Text → Font (Default/Upload) → Position → Size → Char MS → Colors → Done
• Result: Soft ASS subtitle track at start, marked as default

<b>From User Settings:</b>
• Enable Intro Sub toggle
• Set defaults: Text, Style (typing/fade/static), Position, Font Size, Colors, Char MS, Font
• Auto applies to tasks even without entering VT

<b>Notes:</b>
• Uses the intro font; falls back to WM font if unset; else system font
• Per-task font uploads override for that task only
"""

vt_merge = """<b>Merge</b>

<b>Merge Videos:</b> Combine multiple videos in order
1) Select the <b>first</b> file (reply to the first video or ensure it’s the first item)
2) Use VT menu → Merge Videos
3) Confirm the input order if prompted; Done to process

<b>Quick examples:</b>
• 2 files: Reply to the first video with <code>/vt -i 2</code> → VT menu → Merge Videos → Done
• 3 files: Reply to the first video with <code>/vt -i 3</code> → VT menu → Merge Videos → Done

<b>Merge Audios:</b> Combine audio streams
1) VT menu → Merge Audios; Done

<b>Merge Subs:</b> Attach .srt/.ass files
1) VT menu → Merge Subs; pick file(s); Done

All merge modes avoid re-encode when possible (stream copy)."""

vt_convert = """<b>Convert</b>

<b>From VT Menu:</b>
• Convert quality presets (1080p/720p/…)
• Optional CRF/Bitrate

<b>CLI Tips:</b>
• For media conversion across tasks, use Convert-Media help section (-ca/-cv)
"""

vt_reorder = """<b>Reorder Streams</b>

Change the order of video, audio, and subtitle streams in a file.

<b>From VT Menu:</b>
1) Select Reorder Streams
2) You will be presented with a list of all streams in the file.
3) Select the streams you want in the new file, in the desired order.
4) Use the "Add-All" button to quickly select all streams.
5) Done to process.

<b>Notes:</b>
• This is a lossless operation (no re-encoding).
• You can also use this to remove streams by not selecting them.
"""

VT_HELP_DICT = {
    "main": vt_main,
    "Watermark": vt_watermark,
    "Intro-Sub": vt_intro,
    "Merge": vt_merge,
    "Convert": vt_convert,
    "Reorder": vt_reorder,
}

force_start = """<b>Force Start</b>: -f -fd -fu
/cmd link -f (force download and upload)
/cmd link -fd (force download only)
/cmd link -fu (force upload directly after download finish)"""

gdrive = """<b>Gdrive</b>: link
If DEFAULT_UPLOAD is `rc` then you can pass up: `gd` to upload using gdrive tools to GDRIVE_ID.
If DEFAULT_UPLOAD is `gofile` then you can pass up: `gd` to upload using gdrive tools to GDRIVE_ID.
/cmd gdriveLink or gdl or gdriveId -up gdl or gdriveId or gd
/cmd tp:gdriveLink or tp:gdriveId -up tp:gdriveId or gdl or gd (to use token.pickle if service account enabled)
/cmd sa:gdriveLink or sa:gdriveId -p sa:gdriveId or gdl or gd (to use service account if service account disabled)
/cmd mtp:gdriveLink or mtp:gdriveId -up mtp:gdriveId or gdl or gd(if you have added upload gdriveId from usetting) (to use user token.pickle that uploaded by usetting)
You can simply edit using owner/user token from usetting without adding mtp: before the id"""

rclone_cl = """<b>Rclone</b>: path
If DEFAULT_UPLOAD is `gd` then you can pass up: `rc` to upload to RCLONE_PATH.
If DEFAULT_UPLOAD is `gofile` then you can pass up: `rc` to upload to RCLONE_PATH.
/cmd rcl/rclone_path -up rcl/rclone_path/rc -rcf flagkey:flagvalue|flagkey|flagkey:flagvalue
/cmd rcl or rclone_path -up rclone_path or rc or rcl
/cmd mrcc:rclone_path -up rcl or rc(if you have add rclone path from usetting) (to use user config)
You can simply edit using owner/user config from usetting without adding mrcc: before the path"""

name_swap = r"""<b>Name Substitution</b>: -ns
 Use <code>-ns "rule1|rule2|..."</code> to apply filename substitutions.
 
 <b>Rule Format:</b> <code>pattern[:replacement[:count[:flag]]]</code> (parts in <code>[]</code> are optional)
 • Use <code>|</code> to separate multiple rules.
 • Use <code>:</code> (colon) to separate parts within a single rule.
 
 <b>Behavior:</b>
 1.  <b>Simple Removals</b> (e.g., <code>term_to_remove</code> or <code>term_to_remove:</code>):
     •   Regex special characters in <code>term_to_remove</code> (like <code>.[]()*+?</code>) are <b>automatically escaped</b>. You can write them literally.
     •   Example: <code>-ns "[Old Tag]|.backup|junk file"</code> will remove the literal strings "[Old Tag]", ".backup", and "junk file".
 2.  <b>Advanced Regex / Replacements</b> (when <code>:replacement</code> or <code>:flag</code> is specified):
     •   The <code>pattern</code> is treated as a <b>raw regular expression</b>.
     •   You <b>MUST manually escape</b> any special regex characters in your <code>pattern</code> if you intend for them to be matched literally.
     •   Special characters include: <code>\ ^ $ . | ? * + ( ) [ ] { } -</code>
     •   Example: To replace a literal dot, use <code>\\.</code> in your pattern.
 
 <b>Rule Parts:</b>
 •   <code>pattern</code>: The text (for simple removal) or regex pattern to search for.
 •   <code>replacement</code> (optional): Text to replace the found pattern with. Defaults to empty (i.e., removes the pattern).
 •   <code>count</code> (optional): Maximum number of times to apply this rule. Defaults to 0 (all occurrences).
 •   <code>flag</code> (optional):
     •   <code>i</code>: Case-insensitive matching for the pattern.
     •   (Default/other chars): Case-sensitive matching.
 
 <b>Examples:</b>
 A. Remove literal "[REMOVE_ME]" and ".temp":
    <code>/cmd link -ns "[REMOVE_ME]|.temp"</code>
 
 B. Replace "apple" with "orange", case-insensitively, all occurrences:
    <code>/cmd link -ns "apple:orange:0:i"</code>
 
 C. Remove all digits from filenames:
    <code>/cmd link -ns "\\d+:"</code>
    (Here, <code>\d+</code> is a regex pattern. No replacement means removal.)
 
 D. Replace "Title - Part X" (where X is a number) with "Title Episode X":
    <code>/cmd link -ns "Part (\\d+):Episode \\1"</code>
    (Uses regex capturing group <code>(\\d+)</code> and backreference <code>\\1</code>. Must escape <code>( )</code> if literal.)
 
 <b>Note:</b> The entire substitution string after <code>-ns</code> might need to be enclosed in quotes if it contains spaces or special shell characters.
 Timeout: 60 seconds for all substitutions on a single name.
 """

metadata_dynamic_vars = r"""<b>Metadata Dynamic Variables</b>
You can use these variables in metadata values (GEN_METADATA, VID_METADATA, AUD_METADATA, SUB_METADATA):
• <code>{filename}</code> Full filename
• <code>{basename}</code> Filename without extension
• <code>{extension}</code> File extension
• <code>{audiolang}</code> Audio language(s)
• <code>{sublang}</code> Subtitle language(s)
• <code>{year}</code> Year parsed from filename

<b>Examples:</b>
• GEN_METADATA: <code>title={basename} ({year})|comment=Audio: {audiolang} | Subs: {sublang}</code>
• AUD_METADATA: <code>language={audiolang}</code>
• SUB_METADATA: <code>language={sublang}</code>
"""

sequential_help = r"""<b>Sequential Ordering</b>
When Auto Rename is ON, files are uploaded episode-first then quality-next by default.
If Auto Rename is OFF, enable <b>Sequential</b> from Leech settings to group as:
S01E01 480p → 720p → 1080p, then S01E02 480p → 720p → 1080p, etc.
Supported qualities include 480p/720p/1080p/2160p (4K)."""

transmission = """<b>Tg transmission</b>: -hl -ut -bt
/cmd link -hl (leech by user and bot session with respect to size) (Hybrid Leech)
/cmd link -bt (leech by bot session)
/cmd link -ut (leech by user)"""

thumbnail_layout = """Thumbnail Layout: -tl
/cmd link -tl 3x3 (widthxheight) 3 photos in row and 3 photos in column"""

leech_as = """<b>Leech as</b>: -doc -med
/cmd link -doc (Leech as document)
/cmd link -med (Leech as media)"""

ffmpeg_cmds = """<b>FFmpeg Commands</b>: -ff
list of lists of ffmpeg commands. You can set multiple ffmpeg commands for all files before upload. Don't write ffmpeg at beginning, start directly with the arguments.
Notes:
1. Add <code>-del</code> to the list(s) which you want from the bot to delete the original files after command run complete!
3. To execute one of pre-added lists in bot like: ({"subtitle": ["-i mltb.mkv -c copy -c:s srt mltb.mkv"]}), you must use -ff subtitle (list key)
Examples: ["-i mltb.mkv -c copy -c:s srt mltb.mkv", "-i mltb.video -c copy -c:s srt mltb", "-i mltb.m4a -c:a libmp3lame -q:a 2 mltb.mp3", "-i mltb.audio -c:a libmp3lame -q:a 2 mltb.mp3", "-i mltb -map 0:a -c copy mltb.mka -map 0:s -c copy mltb.srt"]
Here I will explain how to use mltb.* which is reference to files you want to work on.
1. First cmd: the input is mltb.mkv so this cmd will work only on mkv videos and the output is mltb.mkv also so all outputs is mkv. -del will delete the original media after complete run of the cmd.
2. Second cmd: the input is mltb.video so this cmd will work on all videos and the output is only mltb so the extenstion is same as input files.
3. Third cmd: the input in mltb.m4a so this cmd will work only on m4a audios and the output is mltb.mp3 so the output extension is mp3.
4. Fourth cmd: the input is mltb.audio so this cmd will work on all audios and the output is mltb.mp3 so the output extension is mp3."""

YT_HELP_DICT = {
    "main": yt,
    "New-Name": f"{new_name}\nNote: Don't add file extension",
    "Zip": zip_arg,
    "Quality": qual,
    "Options": yt_opt,
    "Multi-Link": multi_link,
    "Same-Directory": same_dir,
    "Thumb": thumb,
    "Split-Size": split_size,
    "Upload-Destination": upload,
    "Rclone-Flags": rcf,
    "Bulk": bulk,
    "Sample-Video": sample_video,
    "Screenshot": screenshot,
    "SS-Grid": ss_grid,
    "Convert-Media": convert_media,
    "Force-Start": force_start,
    "Name-Swap": name_swap,
    "Metadata-Vars": metadata_dynamic_vars,
    "Sequential": sequential_help,
    "TG-Transmission": transmission,
    "Thumb-Layout": thumbnail_layout,
    "Leech-Type": leech_as,
    "FFmpeg-Cmds": ffmpeg_cmds,
    "Auto-Rename": auto_rename_help,
    "Remname": remname_help,
    "Attachments": attachments_help,
    "User-Session": user_session_help,
}

gofile_help = """<b>GoFile</b>: Upload files to GoFile
If DEFAULT_UPLOAD is `rc` or `gd` then you can pass up: `gofile` or `gf` to upload to GoFile.
/cmd link -up gofile or -up gf
Requires user's personal token or global GOFILE_TOKEN as fallback.

<b>Personal GoFile Settings (via /usetting):</b>
• <b>GoFile Token</b>: Set your personal GoFile API token.
  - Path: /usetting → GoFile Tools → GoFile Token
• <b>GoFile Folder ID</b>: Specify a folder ID to upload files to a specific GoFile folder. Leave empty to upload to the root folder.
  - Path: /usetting → GoFile Tools → GoFile Folder ID
• <b>Default Upload Service</b>: Set GoFile as your default upload destination.
  - Path: /usetting → Default Upload Service → GoFile

<b>Token Priority:</b> User's GoFile Token (from /usetting) > Global GOFILE_TOKEN (bot config)
<b>Folder Priority:</b> User's GoFile Folder ID (from /usetting) > Root Folder (if not set)"""

MIRROR_HELP_DICT = {
    "main": mirror,
    "New-Name": new_name,
    "DL-Auth": "<b>Direct link authorization</b>: -au -ap\n\n/cmd link -au username -ap password",
    "Headers": "<b>Direct link custom headers</b>: -h\n\n/cmd link -h key: value key1: value1",
    "Extract/Zip": extract_zip,
    "Select-Files": "<b>Bittorrent/JDownloader/Sabnzbd File Selection</b>: -s\n\n/cmd link -s or by replying to file/link",
    "Torrent-Seed": seed,
    "Multi-Link": multi_link,
    "Same-Directory": same_dir,
    "Thumb": thumb,
    "Split-Size": split_size,
    "Upload-Destination": upload,
    "Rclone-Flags": rcf,
    "Bulk": bulk,
    "Join": join,
    "Rclone-DL": rlone_dl,
    "Tg-Links": tg_links,
    "Sample-Video": sample_video,
    "Screenshot": screenshot,
    "SS-Grid": ss_grid,
    "Convert-Media": convert_media,
    "Force-Start": force_start,
    "User-Download": user_download,
    "Name-Swap": name_swap,
    "Metadata-Vars": metadata_dynamic_vars,
    "Sequential": sequential_help,
    "TG-Transmission": transmission,
    "Thumb-Layout": thumbnail_layout,
    "Leech-Type": leech_as,
    "FFmpeg-Cmds": ffmpeg_cmds,
    "GoFile": gofile_help,
    "Auto-Rename": auto_rename_help,
    "Remname": remname_help,
    "Attachments": attachments_help,
    "User-Session": user_session_help,
}

CLONE_HELP_DICT = {
    "main": clone,
    "Multi-Link": multi_link,
    "Bulk": bulk,
    "Gdrive": gdrive,
    "Rclone": rclone_cl,
    "GoFile": gofile_help,
}

RSS_HELP_MESSAGE = """
Use this format to add feed url:
Title1 link (required)
Title2 link -c cmd -inf xx -exf xx
Title3 link -c cmd -d ratio:time -z password

-c command -up mrcc:remote:path/subdir -rcf --buffer-size:8M|key|key:value
-inf For included words filter.
-exf For excluded words filter.
-stv true or false (sensitive filter)

Example: Title https://www.rss-url.com -inf 1080 or 720 or 144p|mkv or mp4|hevc -exf flv or web|xxx
This filter will parse links that its titles contain `(1080 or 720 or 144p) and (mkv or mp4) and hevc` and doesn't contain (flv or web) and xxx words. You can add whatever you want.

Another example: -inf  1080  or 720p|.web. or .webrip.|hvec or x264. This will parse titles that contain ( 1080  or 720p) and (.web. or .webrip.) and (hvec or x264). I have added space before and after 1080 to avoid wrong matching. If this `10805695` number in title it will match 1080 if added 1080 without spaces after it.

Filter Notes:
1. | means and.
2. Add `or` between similar keys, you can add it between qualities or between extensions, so don't add filter like this f: 1080|mp4 or 720|web because this will parse 1080 and (mp4 or 720) and web ... not (1080 and mp4) or (720 and web).
3. You can add `or` and `|` as much as you want.
4. Take a look at the title if it has a static special character after or before the qualities or extensions or whatever and use them in the filter to avoid wrong match.
Timeout: 60 sec.
"""

PASSWORD_ERROR_MESSAGE = """
<b>This link requires a password!</b>
- Insert <b>::</b> after the link and write the password after the sign.

<b>Example:</b> link::my password
"""


help_string = f"""
NOTE: Try each command without any argument to see more detalis.
/{BotCommands.MirrorCommand[0]} or /{BotCommands.MirrorCommand[1]}: Start mirroring to cloud.
/{BotCommands.QbMirrorCommand[0]} or /{BotCommands.QbMirrorCommand[1]}: Start Mirroring to cloud using qBittorrent.
/{BotCommands.JdMirrorCommand[0]} or /{BotCommands.JdMirrorCommand[1]}: Start Mirroring to cloud using JDownloader.
/{BotCommands.NzbMirrorCommand[0]} or /{BotCommands.NzbMirrorCommand[1]}: Start Mirroring to cloud using Sabnzbd.
/{BotCommands.YtdlCommand[0]} or /{BotCommands.YtdlCommand[1]}: Mirror yt-dlp supported link.
/{BotCommands.LeechCommand[0]} or /{BotCommands.LeechCommand[1]}: Start leeching to Telegram.
/{BotCommands.QbLeechCommand[0]} or /{BotCommands.QbLeechCommand[1]}: Start leeching using qBittorrent.
/{BotCommands.JdLeechCommand[0]} or /{BotCommands.JdLeechCommand[1]}: Start leeching using JDownloader.
/{BotCommands.NzbLeechCommand[0]} or /{BotCommands.NzbLeechCommand[1]}: Start leeching using Sabnzbd.
/{BotCommands.YtdlLeechCommand[0]} or /{BotCommands.YtdlLeechCommand[1]}: Leech yt-dlp supported link.
/{BotCommands.CloneCommand} [drive_url]: Copy file/folder to Google Drive.
/{BotCommands.CountCommand} [drive_url]: Count file/folder of Google Drive.
/{BotCommands.DeleteCommand} [drive_url]: Delete file/folder from Google Drive (Only Owner & Sudo).
/{BotCommands.UserSetCommand[0]} or /{BotCommands.UserSetCommand[1]} [query]: Users settings.
/{BotCommands.BotSetCommand[0]} or /{BotCommands.BotSetCommand[1]} [query]: Bot settings.
/{BotCommands.SelectCommand}: Select files from torrents or nzb by gid or reply.
/{BotCommands.CancelTaskCommand[0]} or /{BotCommands.CancelTaskCommand[1]} [gid]: Cancel task by gid or reply.
/{BotCommands.ForceStartCommand[0]} or /{BotCommands.ForceStartCommand[1]} [gid]: Force start task by gid or reply.
/{BotCommands.CancelAllCommand} [query]: Cancel all [status] tasks.
/{BotCommands.ListCommand} [query]: Search in Google Drive(s).
/{BotCommands.SearchCommand} [query]: Search for torrents with API.
/{BotCommands.MediaInfoCommand[0]} or /{BotCommands.MediaInfoCommand[1]} [query]: Get media info.
/{BotCommands.StatusCommand}: Shows a status of all the downloads.
/{BotCommands.StatsCommand}: Show stats of the machine where the bot is hosted in.
/{BotCommands.PingCommand}: Check how long it takes to Ping the Bot (Only Owner & Sudo).
/{BotCommands.AuthorizeCommand}: Authorize a chat or a user to use the bot (Only Owner & Sudo).
/{BotCommands.UnAuthorizeCommand}: Unauthorize a chat or a user to use the bot (Only Owner & Sudo).
/{BotCommands.UsersCommand}: show users settings (Only Owner & Sudo).
/{BotCommands.AddSudoCommand}: Add sudo user (Only Owner).
/{BotCommands.RmSudoCommand}: Remove sudo users (Only Owner).
/{BotCommands.RestartCommand}: Restart and update the bot (Only Owner & Sudo).
/{BotCommands.UthumbCommand}: Directly Sets User Thumbnail.
/{BotCommands.RmthumbCommand}: Directly Removes User Thumbnail.
/{BotCommands.LogCommand}: Get a log file of the bot. Handy for getting crash reports (Only Owner & Sudo).
/{BotCommands.ShellCommand}: Run shell commands (Only Owner).
/{BotCommands.AExecCommand}: Exec async functions (Only Owner).
/{BotCommands.ExecCommand}: Exec sync functions (Only Owner).
/{BotCommands.ClearLocalsCommand}: Clear {BotCommands.AExecCommand} or {BotCommands.ExecCommand} locals (Only Owner).
/{BotCommands.RssCommand}: RSS Menu.
"""

BOT_COMMANDS = {
    "Mirror": "[link/file] Mirror to Upload Destination",
    "QbMirror": "[magnet/torrent] Mirror to Upload Destination using qbit",
    "Ytdl": "[link] Mirror YouTube, m3u8, Social Media and yt-dlp supported urls",
    "Leech": "[link/file] Leech files to Upload to Telegram",
    "QbLeech": "[magnet/torrent] Leech files to Upload to Telegram using qbit",
    "YtdlLeech": "[link] Leech YouTube, m3u8, Social Media and yt-dlp supported urls",
    "Clone": "[link] Clone files/folders to GDrive",
    "UserSet": "User personal settings",
    "ForceStart": "[gid/reply] Force start from queued task",
    "Count": "[link] Count no. of files/folders in GDrive",
    "List": "[query] Search any Text which is available in GDrive",
    "Search": "[query] Search torrents via Qbit Plugins",
    "MediaInfo": "[reply/link] Get MediaInfo of the Target Media",
    "SpeedTest": "Check Bot Speed using Speedtest.com",
    "Select": "[gid/reply] Select files for NZB, Aria2, Qbit Tasks",
    "Ping": "Ping Bot to test Response Speed",
    "Status": "[id/me] Tasks Status of Bot",
    "Stats": "Bot, OS, Repo & System full Statistics",
    "Rss": "User RSS Management Settings",
    "IMDB": "[query] or ttxxxxxx Get IMDB info",
    "CancelAll": "Cancel all Tasks on the Bot",
    "Help": "Detailed help usage of the Hunter Bot",
    "BotSet": "[SUDO] Bot Management Settings",
    "Log": "[SUDO] Get Bot Logs for Internal Working",
    "Restart": "[SUDO] Reboot bot",
    "RestartSessions": "[SUDO] Reboot User Sessions",
    "Uthumb": "Directly Sets User Thumbnail",
    "Rmthumb": "Directly Removes User Thumbnail",
}
