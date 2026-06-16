from io import BytesIO
import os

from PIL import Image

from .. import LOGGER
from ..helper.ext_utils.bot_utils import new_task, update_user_ldata
from ..helper.ext_utils.db_handler import database
from ..helper.ext_utils.media_utils import create_thumb
from ..helper.telegram_helper.message_utils import send_message, delete_message
from ..helper.ext_utils.links_utils import is_url
from ..helper.ext_utils.bot_utils import sync_to_async


async def _download_url_to_path(client, url: str, dest_path: str) -> bool:
    """Download an image URL and save as JPEG to dest_path."""
    try:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, allow_redirects=True, ssl=False, timeout=20
            ) as resp:
                if resp.status != 200:
                    return False
                content_type = resp.headers.get("Content-Type", "")
                data = await resp.read()
        # Try to open image and convert to JPEG
        try:
            img = Image.open(BytesIO(data)).convert("RGB")
        except Exception as e:
            LOGGER.error(f"setthumb: Not an image or failed to decode: {e}")
            return False
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        img.save(dest_path, "JPEG")
        return True
    except Exception as e:
        LOGGER.error(f"setthumb: URL download failed: {e}")
        return False


@new_task
async def setthumb(client, message):
    user = message.from_user
    if not user:
        return
    user_id = user.id

    # Determine source: reply photo/doc, or link argument
    reply = message.reply_to_message
    args = (message.text or "").strip().split(maxsplit=1)
    url = None
    if len(args) == 2:
        url = args[1].strip()
        # Clear existing thumbnail
        if url.lower() in {"none", "clear", "remove", "off"}:
            try:
                if os.path.exists(thumb_path):
                    os.remove(thumb_path)
            except Exception:
                pass
            update_user_ldata(user_id, "THUMBNAIL", "")
            await database.update_user_doc(user_id, "THUMBNAIL", "")
            await send_message(message, "🗑️ Thumbnail removed.")
            return

    thumb_path = f"thumbnails/{user_id}.jpg"
    os.makedirs("thumbnails", exist_ok=True)

    # Case 1: reply with photo
    if reply and (
        reply.photo
        or (reply.document and (reply.document.mime_type or "").startswith("image/"))
    ):
        # Use unified helper to preserve consistent processing
        try:
            # create_thumb expects a Message with media (photo/doc)
            des_dir = await create_thumb(reply, user_id)
        except Exception:
            # Fallback to direct download to path
            des_dir = thumb_path
            await reply.download(file_name=des_dir)
        # Ensure extension .jpg (create_thumb handled)
        update_user_ldata(user_id, "THUMBNAIL", des_dir)
        await database.update_user_doc(user_id, "THUMBNAIL", des_dir)
        # Try to delete the user's media message to keep chat clean
        try:
            await client.delete_messages(chat_id=message.chat.id, message_ids=reply.id)
        except Exception as e:
            LOGGER.error(f"setthumb: failed to delete user media message: {e}")
        await send_message(message, "✅ Thumbnail saved for your account.")
        return

    # Case 2: a direct URL argument
    if url and is_url(url):
        ok = await _download_url_to_path(client, url, thumb_path)
        if not ok:
            await send_message(message, "❌ Failed to download thumbnail from link.")
            return
        update_user_ldata(user_id, "THUMBNAIL", thumb_path)
        await database.update_user_doc(user_id, "THUMBNAIL", thumb_path)
        await send_message(message, "✅ Thumbnail saved from link.")
        return

    # Case 3: user sent the photo/image in same message (rare), handle photo/doc on command msg
    if message.photo or (
        message.document and (message.document.mime_type or "").startswith("image/")
    ):
        try:
            des_dir = await create_thumb(message, user_id)
        except Exception:
            des_dir = thumb_path
            await message.download(file_name=des_dir)
        update_user_ldata(user_id, "THUMBNAIL", des_dir)
        await database.update_user_doc(user_id, "THUMBNAIL", des_dir)
        # Try to delete the user's media message (the command message itself contains the media)
        try:
            await client.delete_messages(
                chat_id=message.chat.id, message_ids=message.id
            )
        except Exception as e:
            LOGGER.error(f"setthumb: failed to delete command media message: {e}")
        await send_message(message, "✅ Thumbnail saved.")
        return

    # Case 4: reply with a video/photo preview (skip for now to keep simple)

    # Otherwise, instruct usage
    await send_message(
        message,
        "Reply with a photo/document or use /setthumb <image-link> to set your custom thumbnail.",
    )
