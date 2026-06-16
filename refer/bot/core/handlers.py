# ruff: noqa: F403, F405

from pyrogram.filters import command, regex
from pyrogram.handlers import CallbackQueryHandler, EditedMessageHandler, MessageHandler
from pyrogram.types import BotCommand

from ..core.config_manager import Config
from ..helper.ext_utils.help_messages import BOT_COMMANDS
from ..helper.telegram_helper.bot_commands import BotCommands
from ..helper.telegram_helper.filters import CustomFilters
from ..helper.ext_utils.stream_extractor import add_extract_handler
from ..helper.ext_utils.stream_swap import add_swap_handler
from ..helper.ext_utils.stream_remover import add_stream_remove_handler
from ..helper.ext_utils.video_tools_selector import add_video_tools_handler
from ..helper.ext_utils.auto_resume_handler import (
    handle_resume_tasks,
    handle_clear_tasks,
)
from ..helper.ext_utils.auto_processor import AutoProcessor, auto_process_filter
from ..modules import *
from ..modules.mirror_leech import handle_thumbnail_upload
from .tg_client import TgClient
from pyrogram import filters
from ..helper.ext_utils.task_manager import thumbnail_waiters
from ..helper.ext_utils.task_manager import trim_waiters
from ..modules.setthumb import setthumb


def add_handlers():
    TgClient.bot.add_handler(
        MessageHandler(
            authorize,
            filters=command(BotCommands.AuthorizeCommand, case_sensitive=True)
            & CustomFilters.sudo,
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            unauthorize,
            filters=command(BotCommands.UnAuthorizeCommand, case_sensitive=True)
            & CustomFilters.sudo,
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            add_sudo,
            filters=command(BotCommands.AddSudoCommand, case_sensitive=True)
            & CustomFilters.sudo,
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            remove_sudo,
            filters=command(BotCommands.RmSudoCommand, case_sensitive=True)
            & CustomFilters.sudo,
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            send_bot_settings,
            filters=command(BotCommands.BotSetCommand, case_sensitive=True)
            & (CustomFilters.owner | CustomFilters.sudo),
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            broadcast,
            filters=command(BotCommands.BroadcastCommand, case_sensitive=True)
            & CustomFilters.sudo,
        )
    )
    TgClient.bot.add_handler(
        CallbackQueryHandler(
            edit_bot_settings, filters=regex("^botset") & CustomFilters.sudo
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            cancel,
            filters=regex(rf"^/{BotCommands.CancelTaskCommand[1]}?(?:_\w+).*$")
            & CustomFilters.authorized,
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            cancel_all_buttons,
            filters=command(BotCommands.CancelAllCommand, case_sensitive=True)
            & CustomFilters.authorized,
        )
    )
    TgClient.bot.add_handler(
        CallbackQueryHandler(cancel_all_update, filters=regex("^canall"))
    )
    TgClient.bot.add_handler(
        CallbackQueryHandler(cancel_multi, filters=regex("^stopm"))
    )
    TgClient.bot.add_handler(
        MessageHandler(
            clone_node,
            filters=command(BotCommands.CloneCommand, case_sensitive=True)
            & CustomFilters.authorized,
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            aioexecute,
            filters=command(BotCommands.AExecCommand, case_sensitive=True)
            & CustomFilters.sudo,
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            execute,
            filters=command(BotCommands.ExecCommand, case_sensitive=True)
            & CustomFilters.sudo,
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            clear,
            filters=command(BotCommands.ClearLocalsCommand, case_sensitive=True)
            & CustomFilters.sudo,
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            select,
            filters=command(BotCommands.SelectCommand, case_sensitive=True)
            & CustomFilters.authorized,
        )
    )
    TgClient.bot.add_handler(
        CallbackQueryHandler(confirm_selection, filters=regex("^sel"))
    )
    TgClient.bot.add_handler(
        MessageHandler(
            remove_from_queue,
            filters=command(BotCommands.ForceStartCommand, case_sensitive=True)
            & CustomFilters.authorized,
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            count_node,
            filters=command(BotCommands.CountCommand, case_sensitive=True)
            & CustomFilters.authorized,
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            delete_file,
            filters=command(BotCommands.DeleteCommand, case_sensitive=True)
            & CustomFilters.authorized,
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            gdrive_search,
            filters=command(BotCommands.ListCommand, case_sensitive=True)
            & CustomFilters.authorized,
        )
    )
    TgClient.bot.add_handler(
        CallbackQueryHandler(select_type, filters=regex("^list_types"))
    )
    TgClient.bot.add_handler(CallbackQueryHandler(arg_usage, filters=regex("^help")))
    TgClient.bot.add_handler(
        MessageHandler(
            mirror,
            filters=command(BotCommands.MirrorCommand, case_sensitive=True)
            & CustomFilters.authorized,
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            qb_mirror,
            filters=command(BotCommands.QbMirrorCommand, case_sensitive=True)
            & CustomFilters.authorized,
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            jd_mirror,
            filters=command(BotCommands.JdMirrorCommand, case_sensitive=True)
            & CustomFilters.authorized,
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            nzb_mirror,
            filters=command(BotCommands.NzbMirrorCommand, case_sensitive=True)
            & CustomFilters.authorized,
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            leech,
            filters=command(BotCommands.LeechCommand, case_sensitive=True)
            & CustomFilters.authorized,
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            qb_leech,
            filters=command(BotCommands.QbLeechCommand, case_sensitive=True)
            & CustomFilters.authorized,
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            jd_leech,
            filters=command(BotCommands.JdLeechCommand, case_sensitive=True)
            & CustomFilters.authorized,
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            nzb_leech,
            filters=command(BotCommands.NzbLeechCommand, case_sensitive=True)
            & CustomFilters.authorized,
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            get_rss_menu,
            filters=command(BotCommands.RssCommand, case_sensitive=True)
            & CustomFilters.authorized,
        )
    )
    TgClient.bot.add_handler(CallbackQueryHandler(rss_listener, filters=regex("^rss")))
    TgClient.bot.add_handler(
        MessageHandler(
            run_shell,
            filters=command(BotCommands.ShellCommand, case_sensitive=True)
            & CustomFilters.sudo,
        )
    )
    TgClient.bot.add_handler(
        EditedMessageHandler(
            run_shell,
            filters=command(BotCommands.ShellCommand, case_sensitive=True)
            & CustomFilters.owner,
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            start, filters=command(BotCommands.StartCommand, case_sensitive=True)
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            login, filters=command(BotCommands.LoginCommand, case_sensitive=True)
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            log,
            filters=command(BotCommands.LogCommand, case_sensitive=True)
            & CustomFilters.sudo,
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            restart_bot,
            filters=command(BotCommands.RestartCommand, case_sensitive=True)
            & CustomFilters.sudo,
        )
    )
    TgClient.bot.add_handler(
        CallbackQueryHandler(
            confirm_restart_wait, filters=regex("^botrestart_wait") & CustomFilters.sudo
        )
    )
    TgClient.bot.add_handler(
        CallbackQueryHandler(
            confirm_restart, filters=regex("^botrestart(?!_wait)") & CustomFilters.sudo
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            restart_sessions,
            filters=command(BotCommands.RestartSessionsCommand, case_sensitive=True)
            & CustomFilters.sudo,
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            imdb_search,
            filters=command(BotCommands.IMDBCommand, case_sensitive=True)
            & CustomFilters.authorized,
        )
    )
    TgClient.bot.add_handler(
        CallbackQueryHandler(imdb_callback, filters=regex("^imdb"))
    )
    TgClient.bot.add_handler(
        MessageHandler(
            ping,
            filters=command(BotCommands.PingCommand, case_sensitive=True)
            & CustomFilters.authorized,
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            bot_help,
            filters=command(BotCommands.HelpCommand, case_sensitive=True)
            & CustomFilters.authorized,
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            mediainfo,
            filters=command(BotCommands.MediaInfoCommand, case_sensitive=True)
            & CustomFilters.authorized,
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            speedtest,
            filters=command(BotCommands.SpeedTestCommand, case_sensitive=True)
            & CustomFilters.authorized,
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            bot_stats,
            filters=command(BotCommands.StatsCommand, case_sensitive=True)
            & CustomFilters.authorized,
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            task_status,
            filters=command(BotCommands.StatusCommand, case_sensitive=True)
            & CustomFilters.authorized,
        )
    )
    TgClient.bot.add_handler(
        CallbackQueryHandler(status_pages, filters=regex("^status"))
    )
    TgClient.bot.add_handler(CallbackQueryHandler(stats_pages, filters=regex("^stats")))
    TgClient.bot.add_handler(CallbackQueryHandler(log_cb, filters=regex("^log")))
    TgClient.bot.add_handler(CallbackQueryHandler(start_cb, filters=regex("^start")))
    TgClient.bot.add_handler(
        MessageHandler(
            torrent_search,
            filters=command(BotCommands.SearchCommand, case_sensitive=True)
            & CustomFilters.authorized,
        )
    )
    TgClient.bot.add_handler(
        CallbackQueryHandler(torrent_search_update, filters=regex("^torser"))
    )
    TgClient.bot.add_handler(
        MessageHandler(
            get_users_settings,
            filters=command(BotCommands.UsersCommand, case_sensitive=True)
            & CustomFilters.sudo,
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            send_user_settings,
            filters=command(BotCommands.UserSetCommand, case_sensitive=True)
            & CustomFilters.authorized_uset,
        )
    )
    TgClient.bot.add_handler(
        CallbackQueryHandler(edit_user_settings, filters=regex("^userset"))
    )
    TgClient.bot.add_handler(
        MessageHandler(
            ytdl,
            filters=command(BotCommands.YtdlCommand, case_sensitive=True)
            & CustomFilters.authorized,
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            ytdl_leech,
            filters=command(BotCommands.YtdlLeechCommand, case_sensitive=True)
            & CustomFilters.authorized,
        )
    )
    TgClient.bot.add_handler(
        MessageHandler(
            hydra_search,
            filters=command(BotCommands.NzbSearchCommand, case_sensitive=True)
            & CustomFilters.authorized,
        )
    )
    # Set custom thumbnail command
    TgClient.bot.add_handler(
        MessageHandler(
            setthumb,
            filters=command(BotCommands.SetThumbCommand, case_sensitive=True)
            & CustomFilters.authorized,
        )
    )
    if Config.SET_COMMANDS:
        global BOT_COMMANDS

        def insert_at(d, k, v, i):
            return dict(list(d.items())[:i] + [(k, v)] + list(d.items())[i:])

        if Config.JD_EMAIL and Config.JD_PASS:
            BOT_COMMANDS = insert_at(
                BOT_COMMANDS,
                "JdMirror",
                "[link/file] Mirror to Upload Destination using JDownloader",
                2,
            )
            BOT_COMMANDS = insert_at(
                BOT_COMMANDS,
                "JdLeech",
                "[link/file] Leech files to Upload to Telegram using JDownloader",
                6,
            )

        if len(Config.USENET_SERVERS) != 0:
            BOT_COMMANDS = insert_at(
                BOT_COMMANDS,
                "NzbMirror",
                "[nzb] Mirror to Upload Destination using Sabnzbd",
                2,
            )
            BOT_COMMANDS = insert_at(
                BOT_COMMANDS,
                "NzbLeech",
                "[nzb] Leech files to Upload to Telegram using Sabnzbd",
                6,
            )

        if Config.LOGIN_PASS:
            BOT_COMMANDS = insert_at(
                BOT_COMMANDS, "Login", "[password] Login to Bot", 14
            )

        TgClient.bot.set_bot_commands(
            [
                BotCommand(
                    cmds[0] if isinstance(cmds, list) else cmds,
                    description,
                )
                for cmd, description in BOT_COMMANDS.items()
                for cmds in [getattr(BotCommands, f"{cmd}Command", None)]
                if cmds is not None
            ]
        )
        # Add stream extraction, swap, and removal handlers
    add_extract_handler()
    add_swap_handler()
    add_stream_remove_handler()

    # Add video tools selector handler
    add_video_tools_handler()

    # Add auto-resume handlers
    TgClient.bot.add_handler(
        CallbackQueryHandler(handle_resume_tasks, filters=regex("^resume_tasks"))
    )
    TgClient.bot.add_handler(
        CallbackQueryHandler(handle_clear_tasks, filters=regex("^clear_tasks"))
    )

    # Custom filter: only allow if user is in thumbnail_waiters
    async def waiting_for_thumbnail_filter(_, __, update):
        user_id = update.from_user.id if update.from_user else None
        return user_id in thumbnail_waiters

    waiting_for_thumbnail = filters.create(waiting_for_thumbnail_filter)

    # Filter for trim time input
    async def waiting_for_trim_filter(_, __, update):
        user_id = update.from_user.id if update.from_user else None
        return user_id in trim_waiters and bool(update.text)

    waiting_for_trim = filters.create(waiting_for_trim_filter)

    # Flatten the commands list - some values are strings, some are lists
    all_commands = []
    for cmd in BotCommands.commands.values():
        if isinstance(cmd, list):
            all_commands.extend(cmd)
        else:
            all_commands.append(cmd)

    # Handler for auto processing of links and files
    TgClient.bot.add_handler(
        MessageHandler(
            AutoProcessor.process_auto_message,
            filters=CustomFilters.authorized & auto_process_filter,
        )
    )

    # Handler for thumbnail uploads when requested with -t flag without URL
    TgClient.bot.add_handler(
        MessageHandler(
            handle_thumbnail_upload,
            filters=CustomFilters.authorized & waiting_for_thumbnail & filters.photo,
        )
    )

    # Handler for trim time input
    async def handle_trim_input(client, message):
        user_id = message.from_user.id
        if user_id not in trim_waiters:
            return
        data = trim_waiters.pop(user_id)
        listener = data.get("listener")
        prompt_id = data.get("prompt_msg_id")
        text = message.text.strip()
        from ..helper.telegram_helper.message_utils import send_message, delete_message

        if text.lower() == "skip":
            listener.selected_video_tools.discard("VIDEO_TRIM")
            await send_message(message, "Skipping trim.")
            await listener.continue_download()
            return
        parts = text.split()
        if len(parts) != 2:
            await send_message(
                message, "Send two times: START END (HH:MM:SS HH:MM:SS) or skip"
            )
            trim_waiters[user_id] = {"listener": listener, "prompt_msg_id": prompt_id}
            return
        start_time, end_time = parts
        import re

        pat = r"^\d{2}:\d{2}:\d{2}$"
        if not re.match(pat, start_time) or not re.match(pat, end_time):
            await send_message(message, "Invalid format. Use HH:MM:SS HH:MM:SS")
            trim_waiters[user_id] = {"listener": listener, "prompt_msg_id": prompt_id}
            return
        listener.trim_times = (start_time, end_time)
        await send_message(message, f"Trim set: {start_time} -> {end_time or 'END'}")
        await listener.continue_download()

    TgClient.bot.add_handler(
        MessageHandler(
            handle_trim_input, filters=CustomFilters.authorized & waiting_for_trim
        )
    )
