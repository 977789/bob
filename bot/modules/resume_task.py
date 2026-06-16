from asyncio import gather, sleep
from re import sub as re_sub

from pyrogram.types import CallbackQuery, Message

from bot import LOGGER
from bot.core.tg_client import TgClient
from bot.core.config_manager import Config
from bot.helper.ext_utils.bot_utils import new_task
from bot.helper.ext_utils.status_utils import action
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.telegram_helper.message_utils import send_messagee
from bot.modules.clone import Clone
from bot.modules.mirror_leech import Mirror
from bot.modules.ytdlp import YtDlp

incomplete_dict = {}


async def get_recursive_user(message: Message):
    while message.reply_to_message and not message.reply_to_message.sender_chat:
        if getattr(message.reply_to_message.from_user, "is_bot", None):
            message = await TgClient.bot.get_messages(
                message.reply_to_message.chat.id, message.reply_to_message.id
            )
        else:
            return message.reply_to_message.from_user
    return message.from_user


async def set_incomplete_task(cid, link):
    message: Message = await TgClient.bot.get_messages(cid, int(link.split("/")[-1]))
    if not message.empty:
        try:
            message.text = re_sub(
                r"-i\s\d{,4}\s?|Cancel\sMulti:\s\/cancel.+", "", message.text
            ).strip()
            text_message = message.text.split("\n")
            if len(text_message) > 1 and text_message[1].startswith("Tag: "):
                try:
                    id_ = int(text_message[1].split()[-1])
                    message.from_user = await TgClient.bot.get_users(id_)
                except Exception as e:
                    LOGGER.error(e)
            message.from_user = await get_recursive_user(message)
            if message.from_user:
                uid = message.from_user.id
                incomplete_dict.setdefault(uid, {"msgs": []})
                incomplete_dict[uid]["msgs"].append(message)
        except Exception as e:
            LOGGER.error(e, exc_info=True)


async def start_resume_task(client, tasks: list[Message]):
    user_id = ""
    for msg in tasks:
        cmd = f"{action(msg)[1:]}{Config.CMD_SUFFIX}"
        is_leech = is_qbit = is_yt = is_jd = is_clone = False

        def _check_cmd(cmds):
            if any(x == cmd for x in (cmds.split() if isinstance(cmds, str) else cmds)):
                return True
            return None

        if _check_cmd(BotCommands.LeechCommand):
            is_leech = True
        elif _check_cmd(BotCommands.QbMirrorCommand):
            is_qbit = True
        elif _check_cmd(BotCommands.QbLeechCommand):
            is_qbit = is_leech = True
        elif _check_cmd(BotCommands.YtdlCommand):
            is_yt = True
        elif _check_cmd(BotCommands.YtdlLeechCommand):
            is_leech = is_yt = True
        elif _check_cmd(BotCommands.JdMirrorCommand):
            is_jd = True
        elif _check_cmd(BotCommands.JdLeechCommand):
            is_leech = is_jd = True
        elif _check_cmd(BotCommands.CloneCommand):
            is_clone = True

        message = await send_messagee(msg.text, msg.reply_to_message or msg)
        message.from_user = msg.from_user
        if not user_id:
            user_id = message.from_user.id
        if is_yt:
            await YtDlp(client, message, is_leech=is_leech).new_event()
        elif is_clone:
            await Clone(client, message).new_event()
        else:
            await Mirror(
                client, message, is_leech=is_leech, is_qbit=is_qbit, is_jd=is_jd
            ).new_event()
        await sleep(Config.MULTI_TIMEGAP)
    incomplete_dict.pop(user_id, None)


@new_task
async def auto_resume_all_tasks():
    await sleep(8)
    for tasks in list(incomplete_dict.values()):
        await start_resume_task(TgClient.bot, tasks["msgs"])


@new_task
async def resume_task_callback(client, query: CallbackQuery):
    user_id = query.from_user.id
    if tasks := incomplete_dict.get(user_id):
        data = query.data.split()
        if data[1] == "yes":
            await gather(query.answer(), start_resume_task(client, tasks["msgs"]))
        else:
            await query.answer("Incomplete task(s) has been cleared!", True)
            del incomplete_dict[user_id]
    else:
        await query.answer("You didn't have incomplete task(s) to resume!", True)
