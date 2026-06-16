# ruff: noqa: E402

from .core.config_manager import Config

Config.load()

from datetime import datetime
from logging import Formatter

from pytz import timezone

from . import LOGGER, bot_loop
from .core.tg_client import TgClient


async def main():
    from asyncio import gather

    from .core.startup import (
        load_configurations,
        load_settings,
        save_settings,
        update_aria2_options,
        update_nzb_options,
        update_qb_options,
        update_variables,
    )

    # Initialize verification database connection
    if Config.DATABASE_URL_VERIFY:
        from .helper.ext_utils.verification_db import get_verification_db

        await get_verification_db()

    await load_settings()

    def changetz(self, timestamp):
        # Correct signature: self (Formatter) and timestamp (float)
        try:
            # Explicitly use pytz.timezone to be sure
            tz_object = timezone(Config.TIMEZONE)
            dt_obj = datetime.fromtimestamp(timestamp, tz=tz_object)
            return dt_obj.timetuple()
        except Exception:
            # Fallback to UTC if timezone conversion fails
            import time

            try:
                return time.gmtime(timestamp)
            except Exception:
                # Final fallback: use local time instead of zeroed struct_time
                return time.localtime(timestamp)

    Formatter.converter = changetz

    # Start core clients first
    await gather(
        TgClient.start_bot(),
        TgClient.start_user(),
        TgClient.start_helper_bots(),
    )

    # Initialize stream clients separately with error handling
    try:
        await TgClient.start_stream()
    except Exception as e:
        LOGGER.error(f"Failed to initialize stream clients: {e}")
        LOGGER.info("Continuing with bot initialization without stream clients...")

    await gather(load_configurations(), update_variables())

    from .core.torrent_manager import TorrentManager

    await TorrentManager.initiate()
    await gather(
        update_qb_options(),
        update_aria2_options(),
        update_nzb_options(),
    )
    from .core.jdownloader_booter import jdownloader
    from .helper.ext_utils.files_utils import clean_all
    from .helper.ext_utils.telegraph_helper import telegraph
    from .helper.mirror_leech_utils.rclone_utils.serve import rclone_serve_booter
    from .modules import (
        get_packages_version,
        initiate_search_tools,
        restart_notification,
    )

    await gather(
        save_settings(),
        jdownloader.boot(),
        clean_all(),
        initiate_search_tools(),
        get_packages_version(),
        restart_notification(),
        telegraph.create_account(),
        rclone_serve_booter(),
    )

    # --- Bot Started Notification ---
    # This section is added to send a confirmation message upon successful startup.
    from .helper.telegram_helper.message_utils import send_message

    # Send a confirmation message to the owner
    if Config.OWNER_ID:
        await send_message(Config.OWNER_ID, "<b>Bot Started Successfully!</b>")

    # Log the successful start to the console
    LOGGER.info("Bot Started!")
    # --- End of added section ---


bot_loop.run_until_complete(main())

from .core.handlers import add_handlers
from .helper.ext_utils.bot_utils import create_help_buttons, new_task
from .helper.listeners.aria2_listener import add_aria2_callbacks

add_aria2_callbacks()
create_help_buttons()
add_handlers()

# Initialize stalled task monitor
from .helper.ext_utils.stalled_task_monitor import stalled_task_monitor
from .core.config_manager import Config


async def start_stalled_task_monitor():
    if Config.AUTO_CANCEL_STALLED_TASKS:
        await stalled_task_monitor.start_monitoring()
        LOGGER.info("Stalled task monitor initialized and started")


# Start the stalled task monitor
bot_loop.run_until_complete(start_stalled_task_monitor())

from pyrogram.filters import regex
from pyrogram.handlers import CallbackQueryHandler

from .core.handlers import add_handlers
from .helper.telegram_helper.filters import CustomFilters
from .helper.telegram_helper.message_utils import (
    delete_message,
    edit_message,
    send_message,
)


@new_task
async def restart_sessions_confirm(_, query):
    data = query.data.split()
    message = query.message
    if data[1] == "confirm":
        reply_to = message.reply_to_message
        restart_message = await send_message(reply_to, "Restarting Session(s)...")
        await delete_message(message)
        await TgClient.reload()
        add_handlers()
        TgClient.bot.add_handler(
            CallbackQueryHandler(
                restart_sessions_confirm,
                filters=regex("^sessionrestart") & CustomFilters.sudo,
            )
        )
        await edit_message(restart_message, "Session(s) Restarted Successfully!")
    else:
        await delete_message(message)


TgClient.bot.add_handler(
    CallbackQueryHandler(
        restart_sessions_confirm,
        filters=regex("^sessionrestart") & CustomFilters.sudo,
    )
)

bot_loop.run_forever()
