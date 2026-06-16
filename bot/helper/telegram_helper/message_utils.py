from asyncio import sleep
from time import time
from functools import wraps
from re import findall as re_findall, match as re_match
from os import path as ospath
from pyrogram.errors import (
    FloodWait,
    MessageNotModified,
    MessageEmpty,
    ReplyMarkupInvalid,
    PhotoInvalidDimensions,
    WebpageCurlFailed,
    MediaEmpty,
    MediaCaptionTooLong,
    UserBlocked,
    UserDeactivatedBan,
    UserDeactivated,
    UserIsBlocked,
    InputUserDeactivated,
    MessageIdInvalid,
    ChannelPrivate,
    ChatWriteForbidden,
    PeerIdInvalid,
    UserNotParticipant,
)
from pyrogram import Client
from pyrogram.types import InlineKeyboardMarkup

try:
    from pyrogram.errors import FloodPremiumWait
except ImportError:
    FloodPremiumWait = FloodWait

from ... import LOGGER, intervals, status_dict, task_dict_lock, cached_dict, bot_loop
from ...core.config_manager import Config
from ...core.tg_client import TgClient
from ..ext_utils.bot_utils import SetInterval
from ..ext_utils.exceptions import TgLinkException
from ..ext_utils.status_utils import get_readable_message
from .button_build import ButtonMaker
from .filters import CustomFilters

# Import user_data and database for user management
try:
    from ..ext_utils.db_handler import database
    from ..ext_utils.var_holder import user_data
except ImportError:
    database = None
    user_data = {}


async def is_admin(message, user_id=None):
    if await CustomFilters.sudo(Client, message):
        return True
    else:
        return False


class Limits:
    def __init__(self):
        self.total = 0

    def _extracted_text(self, msg: str, lmax: int):
        if match := re_findall(r'(</?\S{,4}>|<a\s?href=[\'"]\S+[\'"]|>)', msg):
            self.total = len("".join(match))
        total_limit = self.total + lmax
        space = msg[:total_limit].count(" ")
        return msg.strip()[: total_limit - space]

    def caption(self, caption: str):
        return self._extracted_text(caption, 1024)

    def text(self, text: str):
        return self._extracted_text(text, 4096)


limit = Limits()


def handle_message(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        func_name = func.__name__
        try:
            return await func(*args, **kwargs)
        except FloodWait as f:
            LOGGER.error("%s(): %s", func_name, f)
            await sleep(f.value * 1.2)
            return await wrapper(*args, **kwargs)
        except (
            UserBlocked,
            UserDeactivatedBan,
            UserDeactivated,
            UserIsBlocked,
            InputUserDeactivated,
        ):
            if Config.DATABASE_URL and database:
                user_id = args[0] if func_name == "copy_message" else args[1]
                if not user_data.get(user_id, {}).get("is_premium"):
                    await database.delete_user(user_id)
        except (
            MessageIdInvalid,
            ChannelPrivate,
            ChatWriteForbidden,
            PeerIdInvalid,
        ) as e:
            LOGGER.warning("%s(): %s", func_name, e)
            return str(e)
        except Exception as e:
            LOGGER.error("%s(): %s", func_name, e)
            if func_name == "edit_message":
                return str(e)

    return wrapper


async def sending_message(
    text: str, message, photo, reply_markup: InlineKeyboardMarkup | None = None
):
    return (
        await send_photo(text, message, photo, reply_markup)
        if Config.ENABLE_IMAGE_MODE
        else await send_message(limit.text(text), message, reply_markup)
    )


@handle_message
async def send_messagee(
    text: str, message, reply_markup: InlineKeyboardMarkup | None = None
):
    return await message.reply_text(
        limit.text(text),
        True,
        reply_markup=reply_markup,
        disable_notification=True,
        disable_web_page_preview=True,
    )


@handle_message
async def edit_custom(text: str, chat_id: int, message_id: int, reply_markup=None):
    return await TgClient.bot.edit_message_text(
        chat_id,
        message_id,
        limit.text(text),
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )


@handle_message
async def edit_messagee(
    text: str, message, reply_markup: InlineKeyboardMarkup | None = None
):
    return await message.edit_text(
        limit.text(text), reply_markup=reply_markup, disable_web_page_preview=True
    )


@handle_message
async def copy_messagee(
    chat_id: int, message, reply_markup: InlineKeyboardMarkup | None = None
):
    if not reply_markup:
        if (markup := message.reply_markup) and markup.inline_keyboard:
            reply_markup = markup
    return await message.copy(
        chat_id, disable_notification=True, reply_markup=reply_markup
    )


async def send_message(message, text, buttons=None, block=True, photo=None, **kwargs):
    try:
        # Filter out 'context' from kwargs for pyrogram calls
        final_kwargs = {k: v for k, v in kwargs.items() if k != "context"}
        final_kwargs.pop("reply_to_message_id", None)
        final_kwargs.pop("disable_web_page_preview", None)

        if photo:
            try:
                if isinstance(message, int):
                    return await TgClient.bot.send_photo(
                        chat_id=message,
                        photo=photo,
                        caption=text,
                        reply_markup=buttons,
                        disable_notification=True,
                        **final_kwargs,
                    )
                return await message.reply_photo(
                    photo=photo,
                    reply_to_message_id=message.id,
                    caption=text,
                    quote=True,
                    reply_markup=buttons,
                    disable_notification=True,
                    **final_kwargs,
                )
            except FloodWait as f:
                LOGGER.warning(str(f))
                if not block:
                    return str(f)
                await sleep(f.value * 1.2)
                return await send_message(message, text, buttons, block, photo)
            except MediaCaptionTooLong:
                # Smart caption handling: For very long captions, analyze content length
                # and skip photo if text is excessively long (over 2000 characters)
                LOGGER.info(
                    f"Caption too long, attempting smart handling. Text length: {len(text)}"
                )

                if len(text) > 2000:
                    # For very long text, skip photo and send text only
                    LOGGER.info(
                        "Text is very long (>2000 chars), skipping photo and sending text only"
                    )
                    return await send_message(message, text, buttons, block)

                # For moderately long captions, send photo without caption first
                try:
                    if isinstance(message, int):
                        photo_msg = await TgClient.bot.send_photo(
                            chat_id=message,
                            photo=photo,
                            caption="",
                            reply_markup=None,
                            disable_notification=True,
                            **final_kwargs,
                        )
                    else:
                        photo_msg = await message.reply_photo(
                            photo=photo,
                            reply_to_message_id=message.id,
                            caption="",
                            quote=True,
                            reply_markup=None,
                            disable_notification=True,
                            **final_kwargs,
                        )
                    LOGGER.info("Successfully sent photo without caption due to length")
                except Exception as e_photo:
                    LOGGER.error(
                        f"Failed to send photo without caption after caption-too-long: {e_photo}",
                        exc_info=True,
                    )
                    # Fall back to text-only send if photo still fails
                    return await send_message(message, text, buttons, block)

                # Then send the text as a separate message with buttons
                return await send_message(message, text, buttons, block)
            except (PhotoInvalidDimensions, WebpageCurlFailed, MediaEmpty) as e:
                LOGGER.error(
                    f"Photo error: {e} for chat_id/message: {message}", exc_info=True
                )
                return "PHOTO_ERROR"
            except (
                UserIsBlocked,
                UserDeactivated,
                UserDeactivatedBan,
                InputUserDeactivated,
            ) as e:
                user_id_str = (
                    str(message) if isinstance(message, int) else str(message.chat.id)
                )
                LOGGER.warning(
                    f"User blocked or deactivated error when sending photo to {user_id_str}: {e.MESSAGE}"
                )
                return "USER_BLOCKED_OR_DEACTIVATED"
            except (ChannelPrivate, ChatWriteForbidden, PeerIdInvalid) as e:
                user_id_str = (
                    str(message) if isinstance(message, int) else str(message.chat.id)
                )
                LOGGER.warning(
                    f"Channel/Chat access error when sending photo to {user_id_str}: {e}"
                )
                return f"CHANNEL_ACCESS_ERROR: {e}"
            except Exception as e:
                user_id_str = (
                    str(message) if isinstance(message, int) else str(message.chat.id)
                )
                LOGGER.error(
                    f"Error while sending photo to {user_id_str}: {e}", exc_info=True
                )
                return str(e)

        if isinstance(message, int):
            return await TgClient.bot.send_message(
                chat_id=message,
                text=limit.text(text),
                disable_web_page_preview=True,
                disable_notification=True,
                reply_markup=buttons,
                **final_kwargs,
            )
        return await message.reply(
            text=limit.text(text),
            quote=True,
            disable_web_page_preview=True,
            disable_notification=True,
            reply_markup=buttons,
            **final_kwargs,
        )
    except (
        UserIsBlocked,
        UserDeactivated,
        UserDeactivatedBan,
        InputUserDeactivated,
    ) as e:
        user_id_str = str(message) if isinstance(message, int) else str(message.chat.id)
        LOGGER.warning(
            f"User blocked or deactivated: Cannot send message to {user_id_str}. Error: {e.MESSAGE}"
        )
        return "USER_BLOCKED_OR_DEACTIVATED"
    except (ChannelPrivate, ChatWriteForbidden, PeerIdInvalid) as e:
        user_id_str = str(message) if isinstance(message, int) else str(message.chat.id)
        LOGGER.warning(
            f"Channel/Chat access error: Cannot send message to {user_id_str}. Error: {e}"
        )
        return f"CHANNEL_ACCESS_ERROR: {e}"
    except FloodWait as f:
        LOGGER.warning(str(f))
        if not block:
            return str(f)
        await sleep(f.value * 1.2)
        return await send_message(
            message, text, buttons, block=block, photo=photo, **kwargs
        )
    except ReplyMarkupInvalid as rmi:
        current_context = kwargs.get("context", "N/A")  # Keep context for logging
        buttons_details = f"Buttons object type: {type(buttons)}"
        if hasattr(buttons, "inline_keyboard"):
            buttons_details += f", InlineKeyboard: {buttons.inline_keyboard}"

        LOGGER.warning(
            f"ReplyMarkupInvalid (Context: {current_context}): {rmi}. "
            f"Message text (first 100 chars): '{text[:100]}'. "
            f"{buttons_details}. Retrying without buttons."
        )
        # Remove problematic buttons and context from kwargs for retry
        retry_kwargs = {
            k: v for k, v in kwargs.items() if k not in ["reply_markup", "context"]
        }
        return await send_message(
            message, text, None, block=block, photo=photo, **retry_kwargs
        )
    except MessageEmpty:
        LOGGER.warning(
            "MessageEmpty error. Sending with ParseMode.DISABLED might be needed if not default."
        )
        return "MESSAGE_EMPTY"
    except Exception as e:
        user_id_str = str(message) if isinstance(message, int) else str(message.chat.id)
        LOGGER.error(f"Failed to send message to {user_id_str}: {e}", exc_info=True)
        return str(e)


async def edit_message(message, text, buttons=None, block=True):
    # Validate message object before editing
    if (
        not hasattr(message, "edit")
        or not hasattr(message, "id")
        or not hasattr(message, "chat")
        or not hasattr(message.chat, "id")
    ):
        LOGGER.error(f"edit_message: Invalid message object: {message}")
        return "INVALID_MESSAGE_OBJECT"
    try:
        return await message.edit(
            text=limit.caption(text) if message.media else limit.text(text),
            disable_web_page_preview=True,
            reply_markup=buttons,
        )
    except (MessageNotModified, MessageEmpty):
        pass
    except MessageIdInvalid as e:
        LOGGER.warning(
            f"edit_message: Message ID {getattr(message, 'id', None)} is invalid in chat {getattr(getattr(message, 'chat', None), 'id', None)}: {e}"
        )
        return f"MESSAGE_ID_INVALID: {e}"
    except (ChannelPrivate, ChatWriteForbidden, PeerIdInvalid) as e:
        LOGGER.warning(
            f"edit_message: Channel/Chat access error for message {getattr(message, 'id', None)} in chat {getattr(getattr(message, 'chat', None), 'id', None)}: {e}"
        )
        return f"CHANNEL_ACCESS_ERROR: {e}"
    except ReplyMarkupInvalid as rmi:
        LOGGER.warning(str(rmi))
        return await edit_message(message, text, None)
    except FloodWait as f:
        LOGGER.warning(str(f))
        if not block:
            return str(f)
        await sleep(f.value * 1.2)
        return await edit_message(message, text, buttons)
    except Exception as e:
        LOGGER.error(
            f"edit_message: Exception for message {getattr(message, 'id', None)} in chat {getattr(getattr(message, 'chat', None), 'id', None)}: {e}",
            exc_info=True,
        )
        return str(e)


async def send_photo(
    caption: str,
    message,
    photo: str,
    reply_markup: InlineKeyboardMarkup | None = None,
):
    try:
        if not photo or not ospath.exists(photo):
            LOGGER.error(f"Thumbnail file does not exist: {photo}")
            return await message.reply(
                "<b>Thumbnail not found or could not be generated.</b>"
            )
        return await message.reply_photo(
            photo,
            True,
            limit.caption(caption),
            reply_markup=reply_markup,
            disable_notification=True,
        )
    except Exception as e:
        LOGGER.error(f"send_photo error: {e}", exc_info=True)
        return await message.reply(f"<b>Failed to send thumbnail:</b> {e}")


async def edit_reply_markup(message, buttons):
    try:
        return await message.edit_reply_markup(reply_markup=buttons)
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
        if not file or not ospath.exists(file):
            LOGGER.error(f"Attachment file does not exist: {file}")
            return await message.reply(
                "<b>Attachment not found or could not be generated.</b>"
            )
        return await message.reply_document(
            document=file,
            quote=True,
            caption=caption,
            disable_notification=True,
            reply_markup=buttons,
        )
    except FloodWait as f:
        LOGGER.warning(str(f))
        await sleep(f.value * 1.2)
        return await send_file(message, file, caption)
    except Exception as e:
        LOGGER.error(f"send_file error: {e}", exc_info=True)
        return await message.reply(f"<b>Failed to send attachment:</b> {e}")


# Remove all thread_id/message_thread_id logic for pyrogram compatibility
async def send_rss(text, chat_id, thread_id=None):
    try:
        app = TgClient.user or TgClient.bot
        # message_thread_id is not supported in pyrogram
        return await app.send_message(
            chat_id=chat_id,
            text=text,
            disable_web_page_preview=True,
            # message_thread_id=thread_id,  # Not supported in pyrogram
            disable_notification=True,
        )
    except (ChannelPrivate, ChatWriteForbidden, PeerIdInvalid) as e:
        LOGGER.warning(f"send_rss: Channel/Chat access error for chat {chat_id}: {e}")
        return f"CHANNEL_ACCESS_ERROR: {e}"
    except (FloodWait, FloodPremiumWait) as f:
        LOGGER.warning(str(f))
        await sleep(f.value * 1.2)
        return await send_rss(text, chat_id)  # thread_id removed
    except Exception as e:
        LOGGER.error(str(e), exc_info=True)
        return str(e)


@handle_message
async def send_custom(
    text: str,
    chat_id: str | int,
    reply_markup: InlineKeyboardMarkup | None = None,
    thread_id: int | None = None,
    reply_to: int | None = None,
):
    return await TgClient.bot.send_message(
        chat_id,
        limit.text(text),
        reply_markup=reply_markup,
        message_thread_id=thread_id,
        disable_web_page_preview=True,
        disable_notification=True,
        reply_to_message_id=reply_to,
    )


async def delete_message(message):
    try:
        await message.delete()
    except Exception as e:
        LOGGER.error(str(e))


async def auto_delete_message(cmd_message=None, bot_message=None, st=60):
    if not Config.DELETE_LINKS:
        return

    async def auto_delete():
        await sleep(st)
        if cmd_message is not None:
            await delete_message(cmd_message)
        if bot_message is not None:
            await delete_message(bot_message)

    bot_loop.create_task(auto_delete())


async def delete_links(message):
    # Only delete at start if explicitly enabled; default behavior is to delete after completion
    if Config.DELETE_LINKS and getattr(Config, "DELETE_LINKS_AT_START", False):
        if reply_to := message.reply_to_message:
            await delete_message(reply_to)
        await delete_message(message)


async def delete_status():
    for key, data in list(status_dict.items()):
        try:
            await delete_message(data["message"])
        except Exception as e:
            LOGGER.error(str(e))
        finally:
            # Ensure we always clean in-memory trackers, even if delete fails
            try:
                del status_dict[key]
            except Exception:
                pass
            # Also cancel any running interval for this chat/user sid
            try:
                if obj := intervals["status"].get(key):
                    obj.cancel()
                    del intervals["status"][key]
            except Exception as e:
                LOGGER.error(f"Error cancelling status interval for {key}: {e}")


async def get_tg_link_message(link):
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
        if not TgClient.user:
            raise TgLinkException("USER_SESSION_STRING required for this private link!")

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
            if not TgClient.user:
                raise e

    if not private:
        return (links, "bot") if links else (message, "bot")
    elif TgClient.user:
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
    else:
        raise TgLinkException("Private: Please report!")


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
                # Improved error handling for various telegram errors
                if (
                    message.startswith("Telegram says: [40")
                    or "MESSAGE_ID_INVALID" in message
                    or "CHANNEL_ACCESS_ERROR" in message
                    or "INVALID_MESSAGE_OBJECT" in message
                ):
                    LOGGER.warning(
                        f"Status message {sid} is no longer valid, removing from status_dict. Error: {message}"
                    )
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


async def send_custom_message(cc, chat_id, text, buttons=None):
    try:
        return await cc.send_message(
            chat_id=chat_id,
            text=text,
            disable_web_page_preview=True,
            disable_notification=True,
            reply_markup=buttons,
        )
    except (ChannelPrivate, ChatWriteForbidden, PeerIdInvalid) as e:
        LOGGER.warning(
            f"send_custom_message: Channel/Chat access error for chat {chat_id}: {e}"
        )
        return f"CHANNEL_ACCESS_ERROR: {e}"
    except FloodWait as f:
        LOGGER.warning(str(f))
        await sleep(f.value * 1.2)
        return await send_custom_message(cc, chat_id, text, buttons)
    except Exception as e:
        LOGGER.error(f"Error for chat id {chat_id}: {e}")
        return str(e)


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


async def anno_checker(message, pmsg=None):
    msg_id = message.id
    buttons = ButtonMaker()
    buttons.data_button("Verify", f"verify admin {msg_id}")
    buttons.data_button("Cancel", f"verify no {msg_id}")
    user = None
    cached_dict[msg_id] = user
    if pmsg is not None:
        await edit_message(
            pmsg,
            f"{message.sender_chat.type.name} Anon Verification",
            buttons.build_menu(1),
        )
    else:
        await send_message(
            message,
            f"{message.sender_chat.type.name} Anon Verification",
            buttons.build_menu(1),
        )
    start_time = time()
    while time() - start_time <= 10:
        await sleep(0.5)
        if cached_dict[msg_id]:
            break
    user = cached_dict[msg_id]
    del cached_dict[msg_id]
    return user


async def forcesub(message, ids, button=None):
    join_button = {}
    _msg = ""
    for channel_id in ids.split():
        if channel_id.startswith("-100"):
            channel_id = int(channel_id)
        elif channel_id.startswith("@"):
            channel_id = channel_id.replace("@", "")
        else:
            continue
        try:
            chat = await message._client.get_chat(channel_id)
        except (PeerIdInvalid, ChannelPrivate, ChatWriteForbidden) as e:
            LOGGER.warning(f"forcesub: Cannot access channel {channel_id}: {e}")
            continue
        except Exception as e:
            LOGGER.error(f"forcesub: Error getting chat {channel_id}: {e}")
            continue
        try:
            await chat.get_member(message.from_user.id)
        except UserNotParticipant:
            if username := chat.username:
                invite_link = f"https://t.me/{username}"
            else:
                invite_link = chat.invite_link
            join_button[chat.title] = invite_link
        except Exception as e:
            LOGGER.error(f"forcesub: Error checking membership for {channel_id}: {e}")
            continue
    if join_button:
        if button is None:
            button = ButtonMaker()
        _msg = "You need to join our channel to use me."
        for key, value in join_button.items():
            button.url_button(f"{key}", value)
    return _msg, button


async def send_log_message(message, link, tag):
    if not (log_chat := Config.LINKS_LOG_ID):
        return
    try:
        # Enhanced log handling to support chat_id|topic_id format
        chat_id = log_chat
        topic_id = None

        # Parse chat_id|topic_id format
        if isinstance(log_chat, str) and "|" in log_chat:
            parts = log_chat.split("|", 1)
            try:
                chat_id = int(parts[0])
                topic_id = int(parts[1]) if parts[1] else None
            except ValueError:
                LOGGER.warning(
                    f"Invalid log chat format: {log_chat}, using as single chat_id"
                )
                chat_id = log_chat

        isSuperGroup = message.chat.type in [
            message.chat.type.SUPERGROUP,
            message.chat.type.CHANNEL,
        ]
        if reply_to := message.reply_to_message:
            if not reply_to.text:
                caption = ""
                if isSuperGroup and not Config.DELETE_LINKS:
                    caption += f"<b><a href='{message.link}'>Source</a></b> | "
                caption += f"<b>Added by</b>: {tag}\n<b>User ID</b>: <code>{message.from_user.id}</code>"

                # Send with topic support
                if topic_id:
                    return await reply_to.copy(
                        chat_id, caption=caption, message_thread_id=topic_id
                    )
                return await reply_to.copy(chat_id, caption=caption)

        msg = ""
        if isSuperGroup and not Config.DELETE_LINKS:
            msg += f"\n\n<b><a href='{message.link}'>Source Link</a></b>: "
        msg += f"<code>{link}</code>\n\n<b>Added by</b>: {tag}\n"
        msg += f"<b>User ID</b>: <code>{message.from_user.id}</code>"

        # Send with topic support
        if topic_id:
            return await message._client.send_message(
                chat_id, msg, disable_web_page_preview=True, message_thread_id=topic_id
            )
        return await message._client.send_message(
            chat_id, msg, disable_web_page_preview=True
        )
    except FloodWait as r:
        LOGGER.warning(str(r))
        await sleep(r.value * 1.2)
        return await send_log_message(message, link, tag)
    except Exception as e:
        LOGGER.error(str(e))


async def is_bot_can_dm(message, button=None):
    if not Config.DM_MODE:
        return None, button
    cc = TgClient.app or TgClient.bot
    name = TgClient.APP_NAME or TgClient.NAME
    if cc == TgClient.bot and message.chat.type.name == "PRIVATE":
        return None, button
    try:
        await cc.get_users(message.from_user.id)
        await cc.send_chat_action(message.from_user.id, "typing")
    except Exception:
        if button is None:
            button = ButtonMaker()
        _msg = f"You need to <b>Start</b> @{name} in <b>DM</b>."
        button.url_button("Click To Start", f"https://t.me/{name}")
        return _msg, button
    return None, button
