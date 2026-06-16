from pyrogram.enums import ChatAction
from pyrogram.errors import (
    ChannelInvalid,
    PeerIdInvalid,
    RPCError,
    UserNotParticipant,
    ChannelPrivate,
    ChatWriteForbidden,
)


from ... import LOGGER
from ...core.tg_client import TgClient
from .button_build import ButtonMaker


async def chat_info(channel_id):
    channel_id = str(channel_id).strip()
    if channel_id.startswith("-100"):
        channel_id = int(channel_id)
    elif channel_id.startswith("@"):
        channel_id = channel_id.replace("@", "")
    else:
        return None
    try:
        return await TgClient.bot.get_chat(channel_id)
    except (PeerIdInvalid, ChannelInvalid, ChannelPrivate, ChatWriteForbidden) as e:
        LOGGER.warning(f"chat_info: Cannot access channel {channel_id}: {e}")
        return None
    except Exception as e:
        LOGGER.error(f"chat_info: Unexpected error for {channel_id}: {e}")
        return None


async def forcesub(message, ids, button=None):
    join_button = {}
    _msg = ""
    for channel_id in ids.split():
        chat = await chat_info(channel_id)
        if chat is None:
            LOGGER.warning(
                f"FORCE_SUB: Could not retrieve chat info for ID {channel_id}. Skipping this channel."
            )
            continue
        try:
            await chat.get_member(message.from_user.id)
        except UserNotParticipant:
            try:
                if username := chat.username:
                    invite_link = f"https://t.me/{username}"
                else:
                    invite_link = chat.invite_link
                join_button[chat.title] = invite_link
            except Exception as invite_error:
                LOGGER.warning(
                    f"FORCE_SUB: Cannot get invite link for {channel_id}: {invite_error}"
                )
                continue
        except (ChannelPrivate, ChatWriteForbidden, PeerIdInvalid) as e:
            LOGGER.warning(f"FORCE_SUB: Access denied for channel {channel_id}: {e}")
            continue
        except RPCError as e:
            LOGGER.error(
                f"FORCE_SUB: RPC error for {channel_id}: {e.NAME}: {e.MESSAGE}"
            )
            continue
        except Exception as e:
            LOGGER.error(f"FORCE_SUB: Unexpected error for {channel_id}: {e}")
            continue
    if join_button:
        if button is None:
            button = ButtonMaker()
        _msg = "┠ Channel(s) pending to be joined, Join Now!"
        for key, value in join_button.items():
            button.url_button(f"Join {key}", value, "footer")
    return _msg, button


async def user_info(user_id):
    try:
        return await TgClient.bot.get_users(user_id)
    except Exception:
        return ""


async def check_botpm(message, button=None):
    try:
        await TgClient.bot.send_chat_action(message.from_user.id, ChatAction.TYPING)
        return None, button
    except Exception:
        if button is None:
            button = ButtonMaker()
        _msg = "┠ <i>Bot isn't Started in PM or Inbox (Private)</i>"
        button.url_button(
            "Start Bot Now", f"https://t.me/{TgClient.BNAME}?start=start", "header"
        )
        return _msg, button


# Old verify_token function removed as part of integration with new verification system.
# The new verification logic is in bot/helper/ext_utils/verification_checker.py
# and called from bot/helper/ext_utils/task_manager.py (pre_task_check)


def parse_message_link(link: str) -> tuple[int, int] | None:
    """
    Parses a Telegram message link and returns (chat_id, message_id).
    Supports formats:
    - https://t.me/c/channel_id/message_id
    - https://t.me/username/message_id
    Returns None if parsing fails.
    """
    if not link:
        return None
    parts = link.strip("/").split("/")
    if len(parts) < 2:
        return None

    message_id_str = parts[-1]
    if not message_id_str.isdigit():
        return None
    message_id = int(message_id_str)

    identifier = parts[-2]

    if identifier == "c" and len(parts) >= 3:  # t.me/c/chat_id/message_id
        chat_id_str = parts[-3]  # This was parts[-2] before, but for /c/ it's -3
        if chat_id_str.isdigit():
            # channel_id or supergroup_id from a /c/ link is usually positive, needs -100 prefix
            return int(f"-100{chat_id_str}"), message_id
    elif identifier and not identifier.isdigit():  # t.me/username/message_id
        # For username, chat_id is the username string itself for get_chat/get_messages
        return identifier, message_id

    # Fallback for direct numerical chat_id if it's not a /c/ link and not a username
    # This case is less common for typical message links shared widely
    # but could be useful if a link like t.me/CHAT_ID_NUM/MSG_ID (without /c/) is encountered.
    # However, standard links are usually /c/ or /username/.
    # For now, we'll stick to the common /c/ and /username formats.
    # If identifier.isdigit() for a non-/c/ link, it's ambiguous without more context.
    # Let's assume if it's not /c/ and not a username, it's not a parseable link for this function's scope.

    LOGGER.debug(
        f"Could not parse chat_id from link: {link} with identifier: {identifier}"
    )
    return None
