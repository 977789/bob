"""
Auto-Ping Module
This module prevents the bot from going into a staling condition when not in use.
It periodically sends ping messages to keep the bot active and responsive.
"""

from asyncio import sleep
from random import choice
from time import time

from ... import LOGGER, scheduler, intervals
from ...core.config_manager import Config
from ...core.tg_client import TgClient


# Store the last ping time
last_ping_time = {"time": 0}

# Ping messages to keep it varied
PING_MESSAGES = [
    "🏓 Ping!",
    "💫 Bot is alive",
    "✨ Still here",
    "🔄 Auto-check",
    "⚡ Active status",
]


async def auto_ping_task():
    """
    Main auto-ping task that runs periodically to keep the bot active.
    This function will be called by the scheduler at regular intervals.
    """
    try:
        if not Config.AUTO_PING_INTERVAL or Config.AUTO_PING_INTERVAL <= 0:
            return

        current_time = time()

        # Check if enough time has passed since last ping
        if current_time - last_ping_time["time"] < Config.AUTO_PING_INTERVAL:
            return

        # Update last ping time
        last_ping_time["time"] = current_time

        # Simple check - just get bot info to keep connection alive
        bot_info = await TgClient.bot.get_me()

        LOGGER.info(f"Auto-Ping: Bot active check completed - @{bot_info.username}")

        # Optionally log to owner if configured
        if Config.OWNER_ID:
            try:
                # Use a simple API call instead of sending message to reduce spam
                await TgClient.bot.get_users(Config.OWNER_ID)
            except Exception:
                pass  # Ignore errors for optional logging

    except Exception as e:
        LOGGER.error(f"Error in auto_ping_task: {e}")


async def start_auto_ping():
    """
    Initialize and start the auto-ping scheduler.
    This should be called during bot startup.
    """
    try:
        if not Config.AUTO_PING_INTERVAL or Config.AUTO_PING_INTERVAL <= 0:
            LOGGER.info("Auto-Ping is disabled (AUTO_PING_INTERVAL not set or <= 0)")
            return

        # Convert minutes to seconds for the interval
        interval_seconds = Config.AUTO_PING_INTERVAL * 60

        LOGGER.info(
            f"Starting Auto-Ping scheduler with interval: {Config.AUTO_PING_INTERVAL} minutes"
        )

        # Add job to scheduler
        if not scheduler.running:
            scheduler.start()

        # Schedule the auto-ping task
        scheduler.add_job(
            auto_ping_task,
            trigger="interval",
            seconds=interval_seconds,
            id="auto_ping_job",
            name="Auto Ping Task",
            replace_existing=True,
        )

        intervals["auto_ping"] = "Running"

        LOGGER.info("Auto-Ping scheduler started successfully")

    except Exception as e:
        LOGGER.error(f"Failed to start auto-ping scheduler: {e}")


async def stop_auto_ping():
    """
    Stop the auto-ping scheduler.
    """
    try:
        if scheduler.get_job("auto_ping_job"):
            scheduler.remove_job("auto_ping_job")
            intervals["auto_ping"] = ""
            LOGGER.info("Auto-Ping scheduler stopped")
    except Exception as e:
        LOGGER.error(f"Error stopping auto-ping: {e}")


async def get_auto_ping_status():
    """
    Get the current status of the auto-ping system.
    Returns a string with status information.
    """
    if not Config.AUTO_PING_INTERVAL or Config.AUTO_PING_INTERVAL <= 0:
        return "Auto-Ping: Disabled"

    job = scheduler.get_job("auto_ping_job")
    if job:
        next_run = job.next_run_time
        return f"Auto-Ping: Active (Interval: {Config.AUTO_PING_INTERVAL} min, Next: {next_run})"
    else:
        return "Auto-Ping: Configured but not running"
