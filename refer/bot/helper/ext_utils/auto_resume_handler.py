from asyncio import sleep
from logging import getLogger

from ... import LOGGER
from ...core.config_manager import Config
from ...core.tg_client import TgClient
from ..ext_utils.db_handler import database
from ..telegram_helper.message_utils import send_message
from ..telegram_helper.button_build import ButtonMaker

LOGGER = getLogger(__name__)


class AutoResumeHandler:
    """Handler for automatically resuming incomplete tasks after bot restart"""

    def __init__(self):
        self.task_recreators = {
            "mirror": self._recreate_mirror_task,
            "leech": self._recreate_leech_task,
            "qbmirror": self._recreate_qb_mirror_task,
            "qbleech": self._recreate_qb_leech_task,
            "jdmirror": self._recreate_jd_mirror_task,
            "jdleech": self._recreate_jd_leech_task,
            "nzbmirror": self._recreate_nzb_mirror_task,
            "nzbleech": self._recreate_nzb_leech_task,
            "ytdl": self._recreate_ytdl_task,
            "ytdlleech": self._recreate_ytdl_leech_task,
            "clone": self._recreate_clone_task,
        }

    async def process_incomplete_tasks(self, notifier_dict):
        """Process incomplete tasks based on auto-resume configuration"""
        if not Config.INCOMPLETE_AUTO_RESUME:
            await self._send_manual_resume_notifications(notifier_dict)
        else:
            await self._auto_resume_tasks(notifier_dict)

    async def _auto_resume_tasks(self, notifier_dict):
        """Automatically resume all incomplete tasks"""
        LOGGER.info("Auto-resuming incomplete tasks...")

        for cid, data in notifier_dict.items():
            try:
                for tag, links in data.items():
                    for link in links:
                        await self._resume_task_from_link(cid, tag, link)
                        # Small delay between task recreations to avoid overwhelming the bot
                        await sleep(1)
            except Exception as e:
                LOGGER.error(f"Error auto-resuming tasks for chat {cid}: {e}")

    async def _send_manual_resume_notifications(self, notifier_dict):
        """Send notifications with manual resume/clear buttons"""
        for cid, data in notifier_dict.items():
            try:
                msg = " <b>Incomplete Tasks Found</b>\n\n"
                msg += "The following tasks were interrupted during bot restart:\n\n"

                task_links = []
                for tag, links in data.items():
                    msg += f"<b>{tag}:</b> "
                    for index, link in enumerate(links, start=1):
                        msg += f"<a href='{link}'>{index}</a> | "
                        task_links.extend(links)
                    msg += "\n"

                buttons = ButtonMaker()
                buttons.data_button(" Resume All", f"resume_tasks {cid}")
                buttons.data_button(" Clear All", f"clear_tasks {cid}")
                reply_markup = buttons.build_menu(2)

                await TgClient.bot.send_message(
                    chat_id=cid,
                    text=msg,
                    reply_markup=reply_markup,
                    disable_web_page_preview=True,
                    disable_notification=True,
                )
            except Exception as e:
                LOGGER.error(
                    f"Error sending manual resume notification to chat {cid}: {e}"
                )

    async def _resume_task_from_link(self, cid, tag, link):
        """Resume a specific task from its message link"""
        try:
            # Extract message info from link
            if "t.me/" in link:
                # Parse Telegram message link
                parts = link.split("/")
                if len(parts) >= 2:
                    msg_id = int(parts[-1])

                    # Get the original message
                    try:
                        message = await TgClient.bot.get_messages(
                            chat_id=cid, message_ids=msg_id
                        )
                        if message and message.text:
                            await self._recreate_task_from_message(message, tag)
                    except Exception as e:
                        LOGGER.error(
                            f"Error getting message {msg_id} from chat {cid}: {e}"
                        )
        except Exception as e:
            LOGGER.error(f"Error resuming task from link {link}: {e}")

    async def _recreate_task_from_message(self, message, tag):
        """Recreate task from original message"""
        try:
            # Parse the original command
            command_text = message.text.strip()
            command_parts = command_text.split()

            if not command_parts:
                return

            # Determine task type from tag or command
            task_type = self._determine_task_type(command_parts[0], tag)

            if task_type in self.task_recreators:
                await self.task_recreators[task_type](message, command_parts)
                LOGGER.info(
                    f"Successfully recreated {task_type} task from message {message.id}"
                )
            else:
                LOGGER.warning(f"Unknown task type: {task_type}")

        except Exception as e:
            LOGGER.error(f"Error recreating task from message: {e}")

    def _determine_task_type(self, command, tag):
        """Determine task type from command and user tag"""
        # Ensure command is a string and handle potential None or non-string values
        if not isinstance(command, str):
            LOGGER.warning(
                f"Command is not a string: {command} (type: {type(command)})"
            )
            return "mirror"  # Default fallback

        command = command.lower().lstrip("/")

        # Remove bot name from command if present
        if "@" in command:
            command = command.split("@")[0]

        # Handle CMD_SUFFIX by removing it from the end of command
        # This fixes the issue with command suffixes like /mirror1, /leech2, /mirrorx, etc.
        # Ensure CMD_SUFFIX is converted to string to handle cases where it might be an integer
        cmd_suffix = str(Config.CMD_SUFFIX).lower() if Config.CMD_SUFFIX else ""
        if cmd_suffix and command.endswith(cmd_suffix):
            base_command = command[: -len(cmd_suffix)]
        else:
            base_command = command

        # Map commands to task types
        command_map = {
            "mirror": "mirror",
            "m": "mirror",
            "leech": "leech",
            "l": "leech",
            "qbmirror": "qbmirror",
            "qbm": "qbmirror",
            "qbleech": "qbleech",
            "qbl": "qbleech",
            "jdmirror": "jdmirror",
            "jdm": "jdmirror",
            "jdleech": "jdleech",
            "jdl": "jdleech",
            "nzbmirror": "nzbmirror",
            "nzbm": "nzbmirror",
            "nzbleech": "nzbleech",
            "nzbl": "nzbleech",
            "ytdl": "ytdl",
            "ytdlleech": "ytdlleech",
            "clone": "clone",
        }

        # Try with base command (without suffix) first, then fallback to original command
        return command_map.get(
            base_command, command_map.get(command, "mirror")
        )  # Default to mirror

    # Task recreation methods
    async def _recreate_mirror_task(self, message, command_parts):
        """Recreate mirror task"""
        from ...modules.mirror_leech import mirror

        await mirror(TgClient.bot, message)

    async def _recreate_leech_task(self, message, command_parts):
        """Recreate leech task"""
        from ...modules.mirror_leech import leech

        await leech(TgClient.bot, message)

    async def _recreate_qb_mirror_task(self, message, command_parts):
        """Recreate qBittorrent mirror task"""
        from ...modules.mirror_leech import qb_mirror

        await qb_mirror(TgClient.bot, message)

    async def _recreate_qb_leech_task(self, message, command_parts):
        """Recreate qBittorrent leech task"""
        from ...modules.mirror_leech import qb_leech

        await qb_leech(TgClient.bot, message)

    async def _recreate_jd_mirror_task(self, message, command_parts):
        """Recreate JDownloader mirror task"""
        from ...modules.mirror_leech import jd_mirror

        await jd_mirror(TgClient.bot, message)

    async def _recreate_jd_leech_task(self, message, command_parts):
        """Recreate JDownloader leech task"""
        from ...modules.mirror_leech import jd_leech

        await jd_leech(TgClient.bot, message)

    async def _recreate_nzb_mirror_task(self, message, command_parts):
        """Recreate NZB mirror task"""
        from ...modules.mirror_leech import nzb_mirror

        await nzb_mirror(TgClient.bot, message)

    async def _recreate_nzb_leech_task(self, message, command_parts):
        """Recreate NZB leech task"""
        from ...modules.mirror_leech import nzb_leech

        await nzb_leech(TgClient.bot, message)

    async def _recreate_ytdl_task(self, message, command_parts):
        """Recreate YouTube-dl task"""
        from ...modules.ytdlp import ytdl

        await ytdl(TgClient.bot, message)

    async def _recreate_ytdl_leech_task(self, message, command_parts):
        """Recreate YouTube-dl leech task"""
        from ...modules.ytdlp import ytdl_leech

        await ytdl_leech(TgClient.bot, message)

    async def _recreate_clone_task(self, message, command_parts):
        """Recreate clone task"""
        from ...modules.clone import clone_node

        await clone_node(TgClient.bot, message)


# Callback handlers for manual resume buttons
async def handle_resume_tasks(_, query):
    """Handle resume all tasks button"""
    data = query.data.split()
    if len(data) != 2:
        await query.answer("Invalid data", show_alert=True)
        return

    chat_id = int(data[1])
    await query.answer("Resuming all tasks...", show_alert=True)

    # Get incomplete tasks again for this specific chat
    if Config.INCOMPLETE_TASK_NOTIFIER and Config.DATABASE_URL:
        notifier_dict = await database.get_incomplete_tasks()
        if chat_id in notifier_dict:
            handler = AutoResumeHandler()
            await handler._auto_resume_tasks({chat_id: notifier_dict[chat_id]})

    # Delete the notification message
    await query.message.delete()


async def handle_clear_tasks(_, query):
    """Handle clear all tasks button"""
    data = query.data.split()
    if len(data) != 2:
        await query.answer("Invalid data", show_alert=True)
        return

    await query.answer("Tasks cleared", show_alert=True)
    # Delete the notification message
    await query.message.delete()


# Global handler instance
auto_resume_handler = AutoResumeHandler()
