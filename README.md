# Mirror Hunter Bot (Private)

Key features
- Leech/Upload (Telegram, RClone, GDrive, GoFile)
- Video Tools (merge, compress, watermark, intro subtitle, remove/reorder streams, subsync)
- Name handling (prefix/suffix, REMNAME, NameSub, auto rename)
- Metadata & attachments (tags, custom text/image)
- yt-dlp downloads (per-user cookies, configurable options)

Recent improvements
- Filename processing: NameSub now applies to extracted files per-file.
- Attachments: skip for subtitle-only inputs; process after video-tools.
- yt-dlp: robust cookie detection; lower CPU/memory defaults; config overrides via YT_DLP_OPTIONS.
- Metadata: reduced logs; safer temp output handling.
- FFmpeg: standardized invocations with -nostdin; clearer stream mapping.
- VideoTools UX: All Audio/Subs/Streams preselects; Reorder has Add-All.

Configuration
- See `config_sample.py` for all available keys and defaults.
- Per-user overrides via /usetting; file-based items saved under `thumbnails/`, `cookies/`, `tokens/`, `rclone/`.

Notes
- Queue, limits, and storage thresholds are enforced via Config.
- Use per-user cookies at `cookies/<user_id>.txt`; the bot falls back to `cookies.txt` if present.