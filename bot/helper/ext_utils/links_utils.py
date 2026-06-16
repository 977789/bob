from re import match as re_match
from urllib.parse import unquote, urlparse, unquote_plus
from re import search as re_search
from re import sub as re_sub

from ...core.config_manager import Config


def is_magnet(url: str):
    return bool(re_match(r"magnet:\?xt=urn:(btih|btmh):[a-zA-Z0-9]*\s*", url))


def is_url(url: str):
    return bool(
        re_match(
            r"^(?!\/)(rtmps?:\/\/|mms:\/\/|rtsp:\/\/|https?:\/\/|ftp:\/\/)?([^\/:]+:[^\/@]+@)?(www\.)?(?=[^\/:\s]+\.[^\/:\s]+)([^\/:\s]+\.[^\/:\s]+)(:\d+)?(\/[^#\s]*[\s\S]*)?(\?[^#\s]*)?(#.*)?$",
            url,
        )
    )


def is_media(message):
    return (
        message.document
        or message.photo
        or message.video
        or message.audio
        or message.voice
        or message.video_note
        or message.sticker
        or message.animation
        or None
    )


def is_gdrive_link(url: str):
    return (
        "drive.google.com" in url
        or "driveusercontent.google.com" in url
        or "drive.usercontent.google.com" in url
    )


def is_telegram_link(url: str):
    return url.startswith(("https://t.me/", "tg://openmessage?user_id="))


def is_mega_link(url: str):
    return "mega.nz" in url or "mega.co.nz" in url


def get_mega_link_type(url):
    return "folder" if "folder" in url or "/#F!" in url else "file"


def is_share_link(url: str):
    return bool(
        re_match(
            r"https?:\/\/.+\.gdtot\.\S+|https?:\/\/(filepress|filebee|appdrive)\.\S+",
            url,
        )
    )


def is_rclone_path(path: str):
    return bool(
        re_match(
            r"^(mrcc:)?(?!(magnet:|mtp:|sa:|tp:))(?![- ])[a-zA-Z0-9_\. -]+(?<! ):(?!.*\/\/).*$|^rcl$",
            path,
        )
    )


def get_url_name(url: str):
    return (
        unquote_plus(unquote(urlparse(url).path.rpartition("/")[-1]))
        .replace("&quot;", '"')
        .replace("&apos;", "'")
    )


def is_gdrive_id(id_: str):
    return bool(
        re_match(
            r"^(tp:|sa:|mtp:)?(?:[a-zA-Z0-9-_]{33}|[a-zA-Z0-9_-]{19})$|^gdl$|^(tp:|mtp:)?root$",
            id_,
        )
    )


def is_gofile_upload(dest: str):
    return dest.lower() in ["gofile", "gf"]


# NEW: Extract a link from message or text for downstream modules


def get_link(message=None, text: str = "", get_source: bool = False):
    link = ""
    pattern = r"https?:\/\/(www\.)?\S+\.?[a-z]{2,6}\b(\S*)|magnet:\?xt=urn:(btih|btmh):[-a-zA-Z0-9@:%_\+.~#?&\/=]*\s*"
    try:
        content = text or (getattr(message, "text", "") or "").strip()
        if match := re_search(pattern, content):
            link = match.group()
    except Exception:
        link = ""
    if message and (reply_to := getattr(message, "reply_to_message", None)):
        media = is_media(reply_to)
        if media and get_source:
            link = f"Source is media/file: {getattr(media, 'mime_type', 'image/photo')}"
        elif not media:
            reply_text = getattr(reply_to, "text", None) or getattr(
                reply_to, "caption", None
            )
            if reply_text:
                if match := re_search(pattern, reply_text.strip()):
                    link = match.group()
                    link = link if is_magnet(link) or is_url(link) else ""
    return link


def get_rc_link(url: str) -> str:
    """Normalize duplicate slashes in URL path while preserving scheme and host."""
    try:
        from urllib.parse import urlsplit, urlunsplit

        parts = urlsplit(url)
        normalized_path = re_sub(r"/{2,}", "/", parts.path)
        return urlunsplit(
            (parts.scheme, parts.netloc, normalized_path, parts.query, parts.fragment)
        )
    except Exception:
        return url


def get_stream_link(mime_type: str, url_path: str):
    if Config.ENABLE_STREAM_LINK and Config.STREAM_BASE_URL and Config.STREAM_PORT:
        if isinstance(mime_type, str) and mime_type.startswith("video"):
            return get_rc_link(f"{Config.STREAM_BASE_URL}/stream/{url_path}?type=video")
        elif isinstance(mime_type, str) and mime_type.startswith("audio"):
            return get_rc_link(f"{Config.STREAM_BASE_URL}/stream/{url_path}?type=audio")
    return None
