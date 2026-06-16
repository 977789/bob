from __future__ import annotations

import json
from typing import Dict, Any

from ... import LOGGER
from ...helper.ext_utils.db_handler import database
from ...core.config_manager import Config


async def save_task_file(task_info: Dict[str, Any]) -> None:
    """
    Save task information to a file that can be used for resuming tasks on restart.

    Args:
        task_info: Dictionary containing task information
    """
    if not Config.INCOMPLETE_TASK_NOTIFIER or not Config.DATABASE_URL:
        return

    try:
        if "link" in task_info and task_info["link"]:
            # Validate task name - don't save tasks with empty or dot-only names
            task_name = task_info.get("name", "").strip()
            if not task_name or task_name in (".", ".."):
                LOGGER.warning(
                    f"Skipping task save - invalid name: '{task_name}' for link: {task_info['link']}"
                )
                return

            # Store basic task information needed for resumption
            task_data = {
                "link": task_info["link"],
                "is_leech": task_info.get("is_leech", False),
                "extract": task_info.get("extract", False),
                "compress": task_info.get("compress", False),
                "select": task_info.get("select", False),
                "seed": task_info.get("seed", False),
                "name": task_name,
                "up_dest": task_info.get("up_dest", ""),
                "message_link": task_info.get("message_link", ""),
                "tag": task_info.get("tag", ""),
                "chat_id": task_info.get("chat_id", 0),
                "user_id": task_info.get("user_id", 0),
                "ffmpeg_cmds": task_info.get("ffmpeg_cmds", None),
                "screen_shots": task_info.get("screen_shots", False),
                "thumb": task_info.get("thumb", None),
                "is_clone": task_info.get("is_clone", False),
                "is_qbit": task_info.get("is_qbit", False),
                "is_jd": task_info.get("is_jd", False),
                "is_nzb": task_info.get("is_nzb", False),
                "as_doc": task_info.get("as_doc", False),
            }

            # Save task to database for resumption
            await database.add_task_to_resume(
                json.dumps(task_data), task_info.get("message_link", "")
            )
            LOGGER.info(f"Saved task for resumption: {task_name}")
    except Exception as e:
        LOGGER.error(f"Error saving task file: {e}")


async def resume_task(task_data_str: str, chat_id: int, tag: str) -> None:
    """
    Resume a task from saved data.

    Args:
        task_data_str: JSON string with task information
        chat_id: Chat ID where to send the resumed task message
        tag: User tag for the task
    """
    try:
        task_data = json.loads(task_data_str)

        # Import here to avoid circular imports
        from ...modules.mirror_leech import (
            mirror,
            qb_mirror,
            jd_mirror,
            nzb_mirror,
            leech,
            qb_leech,
            jd_leech,
            nzb_leech,
        )

        # Get the appropriate function based on task type
        if task_data.get("is_leech", False):
            if task_data.get("is_qbit", False):
                task_func = qb_leech
            elif task_data.get("is_jd", False):
                task_func = jd_leech
            elif task_data.get("is_nzb", False):
                task_func = nzb_leech
            else:
                task_func = leech
        else:
            if task_data.get("is_qbit", False):
                task_func = qb_mirror
            elif task_data.get("is_jd", False):
                task_func = jd_mirror
            elif task_data.get("is_nzb", False):
                task_func = nzb_mirror
            else:
                task_func = mirror

        # Create command string from task data
        [task_data["link"]]

        # Add options to command
        options = []
        if task_data.get("extract", False):
            options.append("-e")
        if task_data.get("compress", False):
            options.append("-z")
        if task_data.get("select", False):
            options.append("-s")
        if task_data.get("seed", False):
            options.append("-d")
        if task_data.get("up_dest", ""):
            options.extend(["-up", task_data["up_dest"]])
        if task_data.get("name", ""):
            options.extend(["-n", task_data["name"]])
        if task_data.get("as_doc", False):
            options.append("-doc")
        if task_data.get("screen_shots", False):
            options.append("-ss")
        if task_data.get("ffmpeg_cmds", None):
            options.extend(["-cm", task_data["ffmpeg_cmds"]])
        if task_data.get("thumb", None):
            options.extend(["-th", task_data["thumb"]])

        # Force start the task
        options.append("-f")

        from pyrogram.types import Message
        from ...core.tg_client import TgClient

        # Create a message to pass to the task function
        # We need to create a dummy message as close as possible to a real Telegram message
        client = TgClient.bot

        # Create a simple dummy message to pass to the mirror/leech function
        message = Message(
            message_id=0,
            date=0,
            chat=None,
            from_user=None,
            text=f"/cmd {' '.join([task_data['link']] + options)}",
            client=client,
        )

        # Set needed attributes
        message._client = client
        message.command = ["cmd"] + [task_data["link"]] + options
        message.chat = type(
            "obj",
            (object,),
            {"id": chat_id, "type": type("obj", (object,), {"name": "SUPERGROUP"})},
        )

        # Set the user ID
        user_id = task_data.get("user_id", 0)
        if user_id:
            message.from_user = type("obj", (object,), {"id": user_id})

        # Log the resumed task
        LOGGER.info(
            f"Resuming task: {task_data.get('name', task_data['link'])} with options: {options}"
        )

        # Execute the task function to resume the task
        await task_func(client, message)

    except Exception as e:
        LOGGER.error(f"Error resuming task: {e}")
