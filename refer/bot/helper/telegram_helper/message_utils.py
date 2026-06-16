from asyncio import sleep, gather
from re import match as re_match
from time import time

from pyrogram.types import Message
from pyrogram.enums import ParseMode
from pyrogram.errors import (
    FloodWait,
    MessageNotModified,
    MessageEmpty,
    ReplyMarkupInvalid,
    PhotoInvalidDimensions,
    WebpageCurlFailed,
    MediaEmpty,
    MediaCaptionTooLong,
    UserIsBlocked,
    InputUserDeactivated,
    PeerIdInvalid,
)

try:
    from pyrogram.errors import FloodPremiumWait
except ImportError:
    FloodPremiumWait = FloodWait

from ... import LOGGER, intervals, status_dict, task_dict_lock
from ...core.config_manager import Config
from ...core.tg_client import TgClient
from ..ext_utils.bot_utils import SetInterval
from ..ext_utils.exceptions import TgLinkException
from ..ext_utils.user_session_manager import UserSessionManager
from ..ext_utils.status_utils import get_readable_message
from ..ext_utils.db_handler import database


# Telegram's caption limit is 1024 characters
CAPTION_LIMIT = 1024


def is_caption_too_long(text: str) -> bool:
    """Check if text exceeds Telegram's caption limit."""
    return len(text) > CAPTION_LIMIT


async def send_photo_with_long_caption(
    message_or_chat_id, photo, text, buttons=None, **kwargs
):
    """
    Send photo with text. If text is too long for caption, skip the photo
    and send only the text message.

    Args:
        message_or_chat_id: Message object or chat ID
        photo: Photo to send
        text: Text content
        buttons: Reply markup buttons
        **kwargs: Additional arguments

    Returns:
        The sent message object
    """
    try:
        # Check if caption is too long
        if is_caption_too_long(text):
            # Skip photo and send only text message when caption is too long
            if isinstance(message_or_chat_id, int):
                return await TgClient.bot.send_message(
                    chat_id=message_or_chat_id,
                    text=text,
                    disable_web_page_preview=True,
                    disable_notification=True,
                    reply_markup=buttons,
                )
            elif (
                hasattr(message_or_chat_id, "chat")
                and hasattr(message_or_chat_id.chat, "id")
                and not hasattr(message_or_chat_id, "reply")
            ):
                return await TgClient.bot.send_message(
                    chat_id=message_or_chat_id.chat.id,
                    text=text,
                    disable_web_page_preview=True,
                    disable_notification=True,
                    reply_markup=buttons,
                )
            else:
                return await message_or_chat_id.reply(
                    text=text,
                    quote=True,
                    disable_web_page_preview=True,
                    disable_notification=True,
                    reply_markup=buttons,
                )
        else:
            # Caption is within limit, send normally
            if isinstance(message_or_chat_id, int):
                return await TgClient.bot.send_photo(
                    chat_id=message_or_chat_id,
                    photo=photo,
                    caption=text,
                    reply_markup=buttons,
                    disable_notification=True,
                    **kwargs,
                )
            elif (
                hasattr(message_or_chat_id, "chat")
                and hasattr(message_or_chat_id.chat, "id")
                and not hasattr(message_or_chat_id, "reply_photo")
            ):
                return await TgClient.bot.send_photo(
                    chat_id=message_or_chat_id.chat.id,
                    photo=photo,
                    caption=text,
                    reply_markup=buttons,
                    disable_notification=True,
                    **kwargs,
                )
            else:
                return await message_or_chat_id.reply_photo(
                    photo=photo,
                    reply_to_message_id=message_or_chat_id.id,
                    caption=text,
                    quote=True,
                    reply_markup=buttons,
                    disable_notification=True,
                    **kwargs,
                )
    except Exception as e:
        LOGGER.error(f"Error in send_photo_with_long_caption: {e}")
        # Fallback to sending text without photo
        if isinstance(message_or_chat_id, int):
            return await TgClient.bot.send_message(
                chat_id=message_or_chat_id,
                text=text,
                disable_web_page_preview=True,
                disable_notification=True,
                reply_markup=buttons,
            )
        elif (
            hasattr(message_or_chat_id, "chat")
            and hasattr(message_or_chat_id.chat, "id")
            and not hasattr(message_or_chat_id, "reply")
        ):
            return await TgClient.bot.send_message(
                chat_id=message_or_chat_id.chat.id,
                text=text,
                disable_web_page_preview=True,
                disable_notification=True,
                reply_markup=buttons,
            )
        else:
            return await message_or_chat_id.reply(
                text=text,
                quote=True,
                disable_web_page_preview=True,
                disable_notification=True,
                reply_markup=buttons,
            )


async def _stop_status_for_sid(sid: int):
    """Stop and remove periodic status updates for a chat/user id if present."""
    async with task_dict_lock:
        try:
            if status_dict.get(sid):
                del status_dict[sid]
            if obj := intervals["status"].get(sid):
                obj.cancel()
                del intervals["status"][sid]
        except Exception as e:
            LOGGER.warning(f"Failed stopping status for {sid}: {e}")


async def _cleanup_on_block(chat_id: int):
    """Cleanup when a user blocked the bot or account is deactivated."""
    try:
        await database.rm_pm_user(chat_id)
    except Exception as e:
        # Non-fatal: database might not be configured/connected
        LOGGER.debug(f"rm_pm_user({chat_id}) skipped: {e}")
    await _stop_status_for_sid(chat_id)


async def send_message(message, text, buttons=None, block=True, photo=None, **kwargs):
    # Convert exception objects to string
    if not isinstance(text, str):
        text = str(text)

    # Add promotional header and image for status, leech/mirror complete & error messages
    header_exists = text.startswith('<a href="https://t.me/bharatiyaaofficial">')

    # Check if it's a status message, leech/mirror complete or error message
    is_status_message = any(
        keyword in text
        for keyword in [
            "╭─ Tasks Status",
            "SubFolders",
            "Your video has been uploaded",
            "Your playlist",
            "File(s) have been sent",
            "Task By",
            "No Active Bot Tasks",
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬✘▬",
            "╭<b>CPU</b> »",
            "No Active",
            "Tasks!",
            "Page:",
            "Step:",
        ]
    )
    is_error_message = (
        "failed" in text.lower()
        or "error" in text.lower()
        or "cancelled" in text.lower()
    )
    is_completion_message = any(
        keyword in text
        for keyword in ["completed", "upload", "sent", "finished", "done"]
    )

    # Only add image for error and completion messages, not status messages
    if is_error_message or is_completion_message:
        # Add header only if it doesn't exist
        if not header_exists:
            header = '<a href="https://t.me/bharatiyaaofficial"><b><i>Bot Of Bzex Leech</b></i></a>\n\n'
            text = f"{header}{text}"
        # Add the BHARTIYEE LEECH image if no photo is already specified
        if photo is None:
            photo = "assets/BHARTIYEE LEECH.png"
    elif is_status_message:
        # For status messages, only add header, no image
        if not header_exists:
            header = '<a href="https://t.me/bharatiyaaofficial"><b><i>Bot Of Bzex Leech</b></i></a>\n\n'
            text = f"{header}{text}"

    try:
        if photo:
            # Use our improved caption handling helper function
            return await send_photo_with_long_caption(
                message, photo, text, buttons, **kwargs
            )
        if isinstance(message, int):
            return await TgClient.bot.send_message(
                chat_id=message,
                text=text,
                disable_web_page_preview=True,
                disable_notification=True,
                reply_markup=buttons,
                **kwargs,
            )
        # Handle fake message objects or messages without reply method
        elif (
            hasattr(message, "chat")
            and hasattr(message.chat, "id")
            and not hasattr(message, "reply")
        ):
            return await TgClient.bot.send_message(
                chat_id=message.chat.id,
                text=text,
                disable_web_page_preview=True,
                disable_notification=True,
                reply_markup=buttons,
                **kwargs,
            )
        return await message.reply(
            text=text,
            quote=True,
            disable_web_page_preview=True,
            disable_notification=True,
            reply_markup=buttons,
            **kwargs,
        )
    except (UserIsBlocked, InputUserDeactivated, PeerIdInvalid) as e:
        chat_id = (
            message
            if isinstance(message, int)
            else getattr(getattr(message, "chat", None), "id", None)
        )
        if isinstance(chat_id, int):
            await _cleanup_on_block(chat_id)
        LOGGER.warning(str(e))
        return str(e)
    except FloodWait as f:
        LOGGER.warning(str(f))
        if not block:
            return str(f)
        await sleep(f.value * 1.2)
        return await send_message(message, text, buttons)
    except ReplyMarkupInvalid as rmi:
        LOGGER.warning(str(rmi))
        return await send_message(message, text, None)
    except MessageEmpty:
        return await send_message(message, text, parse_mode=ParseMode.DISABLED)
    except Exception as e:
        LOGGER.error(str(e), exc_info=True)
        return str(e)


async def edit_message(message, text, buttons=None, block=True):
    # Add promotional header for status, leech/mirror complete, error messages, and user settings
    header_exists = text.startswith('<a href="https://t.me/bharatiyaaofficial">')

    # Check if it's a status message, leech/mirror complete, error message, or user settings
    is_status_message = any(
        keyword in text
        for keyword in [
            "╭─ Tasks Status",
            "SubFolders",
            "Your video has been uploaded",
            "Your playlist",
            "File(s) have been sent",
            "Task By",
            "No Active Bot Tasks",
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬✘▬",
            "╭<b>CPU</b> »",
            "No Active",
            "Tasks!",
            "Page:",
            "Step:",
        ]
    )
    is_error_message = (
        "failed" in text.lower()
        or "error" in text.lower()
        or "cancelled" in text.lower()
    )
    is_user_settings = any(
        keyword in text
        for keyword in [
            "User Settings",
            "General Settings",
            "Leech Settings",
            "Mirror Settings",
            "FF Settings",
            "Advanced Settings",
        ]
    )

    if (
        is_status_message or is_error_message or is_user_settings
    ) and not header_exists:
        header = '<a href="https://t.me/bharatiyaaofficial"><b><i>Bot Of Bzex Leech</b></i></a>\n\n'
        text = f"{header}{text}"

    try:
        return await message.edit(
            text=text,
            disable_web_page_preview=True,
            reply_markup=buttons,
        )
    except (UserIsBlocked, InputUserDeactivated, PeerIdInvalid) as e:
        chat_id = getattr(getattr(message, "chat", None), "id", None)
        if isinstance(chat_id, int):
            await _cleanup_on_block(chat_id)
        LOGGER.warning(str(e))
        return str(e)
    except (MessageNotModified, MessageEmpty):
        pass
    except ReplyMarkupInvalid as rmi:
        LOGGER.warning(str(rmi))
        return await edit_message(message, text, None)
    except MediaCaptionTooLong:
        # If editing a message with photo that has caption too long,
        # remove the photo and send as text message instead
        try:
            # Delete the current photo message
            await delete_message(message)
            # Send full text as regular message
            chat_id = getattr(getattr(message, "chat", None), "id", None)
            if chat_id:
                return await TgClient.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    disable_web_page_preview=True,
                    disable_notification=True,
                    reply_markup=buttons,
                )
            return message
        except Exception:
            # Fallback to truncation if the above fails
            return await edit_message(message, text[:1024], buttons, block)
    except FloodWait as f:
        LOGGER.warning(str(f))
        if not block:
            return str(f)
        await sleep(f.value * 1.2)
        return await edit_message(message, text, buttons)
    except Exception as e:
        LOGGER.error(str(e), exc_info=True)
        return str(e)


async def edit_reply_markup(message, buttons):
    try:
        return await message.edit_reply_markup(reply_markup=buttons)
    except (UserIsBlocked, InputUserDeactivated, PeerIdInvalid) as e:
        chat_id = getattr(getattr(message, "chat", None), "id", None)
        if isinstance(chat_id, int):
            await _cleanup_on_block(chat_id)
        LOGGER.warning(str(e))
        return str(e)
    except MessageNotModified:
        pass
    except FloodWait as f:
        LOGGER.warning(str(f))
        await sleep(f.value * 1.2)
        return await edit_reply_markup(message, buttons)
    except Exception as e:
        LOGGER.error(str(e), exc_info=True)
        return str(e)


async def send_file(message, file, caption="", buttons=None):
    try:
        return await message.reply_document(
            document=file,
            quote=True,
            caption=caption,
            disable_notification=True,
            reply_markup=buttons,
        )
    except (UserIsBlocked, InputUserDeactivated, PeerIdInvalid) as e:
        chat_id = getattr(getattr(message, "chat", None), "id", None)
        if isinstance(chat_id, int):
            await _cleanup_on_block(chat_id)
        LOGGER.warning(str(e))
        return str(e)
    except FloodWait as f:
        LOGGER.warning(str(f))
        await sleep(f.value * 1.2)
        return await send_file(message, file, caption)
    except Exception as e:
        LOGGER.error(str(e), exc_info=True)
        return str(e)


async def send_rss(text, chat_id, thread_id):
    try:
        app = TgClient.user or TgClient.bot
        return await app.send_message(
            chat_id=chat_id,
            text=text,
            disable_web_page_preview=True,
            message_thread_id=thread_id,
            disable_notification=True,
        )
    except (UserIsBlocked, InputUserDeactivated, PeerIdInvalid) as e:
        if isinstance(chat_id, int):
            await _cleanup_on_block(chat_id)
        LOGGER.warning(str(e))
        return str(e)
    except (FloodWait, FloodPremiumWait) as f:
        LOGGER.warning(str(f))
        await sleep(f.value * 1.2)
        return await send_rss(text)
    except Exception as e:
        LOGGER.error(str(e), exc_info=True)
        return str(e)


async def delete_message(*args):
    tasks = [msg.delete() for msg in args if isinstance(msg, Message)]
    if not tasks:
        return
    results = await gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            LOGGER.error(result)


async def delete_links(message):
    if Config.DELETE_LINKS:
        await delete_message(message, message.reply_to_message)


async def auto_delete_message(*args, stime=90):
    await sleep(stime)
    await delete_message(*args)


async def delete_status():
    async with task_dict_lock:
        for key, data in list(status_dict.items()):
            try:
                await delete_message(data["message"])
                del status_dict[key]
            except Exception as e:
                LOGGER.error(str(e))


async def get_tg_link_message(link, request_user_id: int | None = None):
    message = None
    links = []
    if link.startswith(
        (
            "https://t.me/",
            "https://telegram.me/",
            "https://telegram.dog/",
            "https://telegram.space/",
        )
    ):
        private = False
        msg = re_match(
            r"https:\/\/(t\.me|telegram\.me|telegram\.dog|telegram\.space)\/(?:c\/)?([^\/]+)(?:\/[^\/]+)?\/([0-9-]+)",
            link,
        )
    else:
        private = True
        msg = re_match(
            r"tg:\/\/(openmessage)\?user_id=([0-9]+)&message_id=([0-9-]+)", link
        )

    chat = msg[2]
    msg_id = msg[3]
    if "-" in msg_id:
        start_id, end_id = msg_id.split("-")
        msg_id = start_id = int(start_id)
        end_id = int(end_id)
        btw = end_id - start_id
        if private:
            link = link.split("&message_id=")[0]
            links.append(f"{link}&message_id={start_id}")
            for _ in range(btw):
                start_id += 1
                links.append(f"{link}&message_id={start_id}")
        else:
            link = link.rsplit("/", 1)[0]
            links.append(f"{link}/{start_id}")
            for _ in range(btw):
                start_id += 1
                links.append(f"{link}/{start_id}")
    else:
        msg_id = int(msg_id)

    if chat.isdigit():
        chat = int(chat) if private else int(f"-100{chat}")

    if not private:
        try:
            message = await TgClient.bot.get_messages(chat_id=chat, message_ids=msg_id)
            if message.empty:
                private = True
        except Exception as e:
            private = True
            # No bot access; continue to try user-based access below

    if not private:
        return (links, "bot") if links else (message, "bot")

    # Private or bot lacked access: try per-user session first (if caller provided)
    if request_user_id and UserSessionManager.has_user_session(request_user_id):
        try:
            user_message = await UserSessionManager.get_message_with_user_session(
                request_user_id, chat, msg_id
            )
            if user_message:
                return (
                    (links, "user_session") if links else (user_message, "user_session")
                )
        except Exception as e:
            # Fall through to global user or error with detailed message
            pass

    # Fall back to global user session if available
    if TgClient.user:
        try:
            user_message = await TgClient.user.get_messages(
                chat_id=chat, message_ids=msg_id
            )
        except Exception as e:
            raise TgLinkException(
                f"You don't have access to this chat!. ERROR: {e}"
            ) from e
        if not user_message.empty:
            return (links, "user") if links else (user_message, "user")

    # No valid access found
    raise TgLinkException(
        "You don't have access to this chat with the provided session."
    )


async def update_status_message(sid, force=False):
    if intervals["stopAll"]:
        return
    async with task_dict_lock:
        if not status_dict.get(sid):
            if obj := intervals["status"].get(sid):
                obj.cancel()
                del intervals["status"][sid]
            return
        if not force and time() - status_dict[sid]["time"] < 3:
            return
        status_dict[sid]["time"] = time()
        page_no = status_dict[sid]["page_no"]
        status = status_dict[sid]["status"]
        is_user = status_dict[sid]["is_user"]
        page_step = status_dict[sid]["page_step"]
        text, buttons = await get_readable_message(
            sid, is_user, page_no, status, page_step
        )
        if text is None:
            del status_dict[sid]
            if obj := intervals["status"].get(sid):
                obj.cancel()
                del intervals["status"][sid]
            return
        if text != status_dict[sid]["message"].text:
            message = await edit_message(
                status_dict[sid]["message"], text, buttons, block=False
            )
            if isinstance(message, str):
                if message.startswith("Telegram says: [40"):
                    del status_dict[sid]
                    if obj := intervals["status"].get(sid):
                        obj.cancel()
                        del intervals["status"][sid]
                else:
                    LOGGER.error(
                        f"Status with id: {sid} haven't been updated. Error: {message}"
                    )
                return
            status_dict[sid]["message"].text = text
            status_dict[sid]["time"] = time()


async def send_status_message(msg, user_id=0):
    if intervals["stopAll"]:
        return
    sid = user_id or msg.chat.id
    is_user = bool(user_id)
    async with task_dict_lock:
        if sid in status_dict:
            page_no = status_dict[sid]["page_no"]
            status = status_dict[sid]["status"]
            page_step = status_dict[sid]["page_step"]
            text, buttons = await get_readable_message(
                sid, is_user, page_no, status, page_step
            )
            if text is None:
                del status_dict[sid]
                if obj := intervals["status"].get(sid):
                    obj.cancel()
                    del intervals["status"][sid]
                return
            old_message = status_dict[sid]["message"]
            message = await send_message(msg, text, buttons, block=False)
            if isinstance(message, str):
                LOGGER.error(
                    f"Status with id: {sid} haven't been sent. Error: {message}"
                )
                return
            await delete_message(old_message)
            message.text = text
            status_dict[sid].update({"message": message, "time": time()})
        else:
            text, buttons = await get_readable_message(sid, is_user)
            if text is None:
                return
            message = await send_message(msg, text, buttons, block=False)
            if isinstance(message, str):
                LOGGER.error(
                    f"Status with id: {sid} haven't been sent. Error: {message}"
                )
                return
            message.text = text
            status_dict[sid] = {
                "message": message,
                "time": time(),
                "page_no": 1,
                "page_step": 1,
                "status": "All",
                "is_user": is_user,
            }
        if not intervals["status"].get(sid) and not is_user:
            intervals["status"][sid] = SetInterval(
                Config.STATUS_UPDATE_INTERVAL, update_status_message, sid
            )


async def update_message_with_photo(
    message, text, buttons=None, photo=None, block=True
):
    """
    Smart message update function that handles both text and photo messages.
    If the message already has a photo, it will edit the caption.
    If it's a text message and we want to add a photo, it will delete and send new.
    """
    try:
        # Check if the current message has a photo and we want to add/keep a photo
        if hasattr(message, "photo") and message.photo and photo:
            # Edit photo caption
            try:
                return await message.edit_caption(
                    caption=text,
                    reply_markup=buttons,
                )
            except MediaCaptionTooLong:
                # Handle long caption by removing photo and sending text only
                try:
                    # Delete current photo message and send text message instead
                    await delete_message(message)
                    chat_id = getattr(getattr(message, "chat", None), "id", None)
                    if chat_id:
                        return await TgClient.bot.send_message(
                            chat_id=chat_id,
                            text=text,
                            disable_web_page_preview=True,
                            disable_notification=True,
                            reply_markup=buttons,
                        )
                except Exception:
                    # Fallback: truncate caption to fit Telegram's limit (1024 characters)
                    return await message.edit_caption(
                        caption=text[:1024],
                        reply_markup=buttons,
                    )
        elif hasattr(message, "photo") and message.photo and not photo:
            # Has photo but we don't want photo - need to delete and send text
            await delete_message(message)
            return await send_message(message.chat.id, text, buttons, block)
        elif (not hasattr(message, "photo") or not message.photo) and photo:
            # No photo but we want to add photo - need to delete and send photo
            await delete_message(message)
            return await send_message(message.chat.id, text, buttons, block, photo)
        else:
            # Both are text messages - normal edit
            return await edit_message(message, text, buttons, block)
    except Exception as e:
        LOGGER.error(f"Error in update_message_with_photo: {e}")
        # Fallback to delete and send
        await delete_message(message)
        return await send_message(message.chat.id, text, buttons, block, photo)
