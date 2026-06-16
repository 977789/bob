"""
VerifyHunter API Module for Connected Bots

This module provides a clean interface for connected bots to check premium status,
token expiry, and ban status through the verify-hunter system.
"""

import pytz
from time import time
from datetime import datetime

from .helper.ext_utils.verification_checker import (
    check_premium_status,
    check_ban_status,
    parse_expiry,
)
from .helper.ext_utils.verification_db import get_verification_db
from . import LOGGER, user_data, ban_data


class VerifyHunterAPI:
    """
    Main API class for verify-hunter integration.
    Provides simplified access to premium, ban, and token verification functions.
    """

    @staticmethod
    def check_premium(user_id):
        """
        Check if a user has premium access (synchronous version).

        Args:
            user_id (int): Telegram user ID

        Returns:
            bool: True if user has active premium, False otherwise
        """
        try:
            # First check local user_data cache
            user_info = user_data.get(user_id, {})
            is_premium = user_info.get("is_premium", False)

            if is_premium:
                # Check if premium has expired
                premium_expiry = user_info.get("premium_expiry")
                if premium_expiry:
                    if (
                        isinstance(premium_expiry, (int, float))
                        and time() > premium_expiry
                    ):
                        return False
                    elif isinstance(premium_expiry, str):
                        parsed = parse_expiry(premium_expiry)
                        if isinstance(parsed, datetime):
                            now_utc = datetime.now(pytz.UTC)
                            if now_utc > parsed:
                                return False
                        elif isinstance(parsed, float) and time() > parsed:
                            return False
                return True
            return False
        except Exception as e:
            LOGGER.error(f"Error checking premium status for user {user_id}: {e}")
            return False

    @staticmethod
    async def check_ban(user_id):
        """
        Check if a user is banned.

        Args:
            user_id (int): Telegram user ID

        Returns:
            bool: True if user is banned, False otherwise
        """
        return await check_ban_status(user_id)

    @staticmethod
    async def check_token_expiry(user_id, token_number):
        """
        Check if a specific token has expired.

        Args:
            user_id (int): Telegram user ID
            token_number (int or str): Token number/identifier

        Returns:
            bool: True if token is expired, False if still valid
        """
        try:
            vdb = await get_verification_db()
            if vdb is None or vdb.col is None:
                LOGGER.warning(
                    f"VDB unavailable for token expiry check. User: {user_id}"
                )
                return True  # Assume expired if can't check

            raw_expiry = await vdb.get_token_expire_date(user_id, str(token_number))
            if not raw_expiry:
                LOGGER.debug(
                    f"No token data for User: {user_id}, Token: {token_number}"
                )
                return True  # Assume expired if no data

            parsed = parse_expiry(raw_expiry)
            if isinstance(parsed, datetime):
                now_utc = datetime.now(pytz.UTC)
                return now_utc > parsed
            elif isinstance(parsed, float):
                return time() > parsed

            return True  # Assume expired if can't parse
        except Exception as e:
            LOGGER.error(f"Error checking token expiry for user {user_id}: {e}")
            return True  # Assume expired on error

    @staticmethod
    def get_user_data(user_id):
        """
        Get user data from the verify-hunter system.

        Args:
            user_id (int): Telegram user ID

        Returns:
            dict: User data dictionary
        """
        return user_data.get(user_id, {})

    @staticmethod
    def format_premium_status(user_id):
        """
        Get formatted premium status string for display.

        Args:
            user_id (int): Telegram user ID

        Returns:
            str: Formatted premium status message
        """
        try:
            user_info = user_data.get(user_id, {})
            is_premium = user_info.get("is_premium", False)

            if not is_premium:
                return "❌ Premium Status: Not Active"

            premium_expiry = user_info.get("premium_expiry")
            if premium_expiry:
                if isinstance(premium_expiry, (int, float)):
                    expiry_date = datetime.fromtimestamp(premium_expiry)
                    if time() > premium_expiry:
                        return "❌ Premium Status: Expired"
                    time_remaining = premium_expiry - time()
                    days = int(time_remaining // 86400)
                    hours = int((time_remaining % 86400) // 3600)
                    return (
                        f"✅ Premium Status: Active\n"
                        f"📅 Expires: {expiry_date.strftime('%Y-%m-%d %H:%M UTC')}\n"
                        f"⏰ Time Remaining: {days}d {hours}h"
                    )
                else:
                    parsed = parse_expiry(premium_expiry)
                    if isinstance(parsed, datetime):
                        now_utc = datetime.now(pytz.UTC)
                        if now_utc > parsed:
                            return "❌ Premium Status: Expired"
                        return f"✅ Premium Status: Active\n📅 Expires: {parsed.strftime('%Y-%m-%d %H:%M UTC')}"

            return "✅ Premium Status: Permanent"
        except Exception as e:
            LOGGER.error(f"Error formatting premium status for user {user_id}: {e}")
            return "❌ Premium Status: Error checking status"

    @staticmethod
    def format_ban_status(user_id):
        """
        Get formatted ban status string for display.

        Args:
            user_id (int): Telegram user ID

        Returns:
            str: Formatted ban status message
        """
        try:
            ban_info = ban_data.get(user_id, {})
            is_banned = ban_info.get("is_ban", False)

            if not is_banned:
                return "✅ Account Status: Not Banned"

            ban_reason = ban_info.get("ban_reason", "No reason provided")
            ban_expiry = ban_info.get("ban_expiry")

            if ban_expiry:
                if isinstance(ban_expiry, (int, float)):
                    if time() > ban_expiry:
                        return "✅ Account Status: Ban Expired"
                    expiry_date = datetime.fromtimestamp(ban_expiry)
                    time_remaining = ban_expiry - time()
                    days = int(time_remaining // 86400)
                    hours = int((time_remaining % 86400) // 3600)
                    return (
                        f"🚫 Account Status: Banned\n"
                        f"📄 Reason: {ban_reason}\n"
                        f"📅 Expires: {expiry_date.strftime('%Y-%m-%d %H:%M UTC')}\n"
                        f"⏰ Time Remaining: {days}d {hours}h"
                    )

            return f"🚫 Account Status: Permanently Banned\n📄 Reason: {ban_reason}"
        except Exception as e:
            LOGGER.error(f"Error formatting ban status for user {user_id}: {e}")
            return "❌ Error checking ban status"


# Convenience functions for direct import
async def check_premium(user_id):
    """
    Convenience function - check if a user has premium access.

    Args:
        user_id (int): Telegram user ID

    Returns:
        bool: True if user has active premium, False otherwise
    """
    return await check_premium_status(user_id)


async def check_ban(user_id):
    """
    Convenience function - check if a user is banned.

    Args:
        user_id (int): Telegram user ID

    Returns:
        bool: True if user is banned, False otherwise
    """
    return await check_ban_status(user_id)


def get_user_premium_info(user_id):
    """
    Get detailed premium information for a user.

    Args:
        user_id (int): Telegram user ID

    Returns:
        dict or None: Premium info dict with keys:
            - is_premium (bool): Whether user has premium
            - expiry (float): Unix timestamp of expiry (None if permanent)
            - time_remaining (int): Seconds until expiry
        Returns None if user doesn't have premium
    """
    try:
        user_info = user_data.get(user_id, {})
        is_premium = user_info.get("is_premium", False)

        if not is_premium:
            return None

        premium_expiry = user_info.get("premium_expiry")
        time_remaining = None

        if premium_expiry:
            if isinstance(premium_expiry, (int, float)):
                time_remaining = max(0, int(premium_expiry - time()))
                if time_remaining <= 0:
                    return None  # Expired
            else:
                parsed = parse_expiry(premium_expiry)
                if isinstance(parsed, datetime):
                    now_utc = datetime.now(pytz.UTC)
                    if now_utc > parsed:
                        return None  # Expired
                    time_remaining = int((parsed - now_utc).total_seconds())
                elif isinstance(parsed, float):
                    time_remaining = max(0, int(parsed - time()))
                    if time_remaining <= 0:
                        return None  # Expired

        return {
            "is_premium": True,
            "expiry": premium_expiry,
            "time_remaining": time_remaining,
        }
    except Exception as e:
        LOGGER.error(f"Error getting premium info for user {user_id}: {e}")
        return None


# Legacy function names for backward compatibility
def format_premium_status(user_id):
    """Legacy function - use VerifyHunterAPI.format_premium_status() instead."""
    return VerifyHunterAPI.format_premium_status(user_id)


def format_ban_status(user_id):
    """Legacy function - use VerifyHunterAPI.format_ban_status() instead."""
    return VerifyHunterAPI.format_ban_status(user_id)


# Additional utility functions for external bots
async def is_token_expired(user_id, token_number):
    """
    Check if a specific token has expired.

    Args:
        user_id (int): Telegram user ID
        token_number (int or str): Token number/identifier

    Returns:
        bool: True if token is expired, False if still valid
    """
    return await VerifyHunterAPI.check_token_expiry(user_id, token_number)


async def check_bot_status(user_id, token_number):
    """
    Check if a user's token has expired (alias for is_token_expired).

    Args:
        user_id (int): Telegram user ID
        token_number (int): Token number to check

    Returns:
        bool: True if token is expired/needs verification, False if still valid
    """
    return await is_token_expired(user_id, token_number)


def is_premium_user(user_id):
    """
    Check if a user has active premium access (synchronous).

    Args:
        user_id (int): Telegram user ID

    Returns:
        bool: True if user has active premium, False otherwise
    """
    return VerifyHunterAPI.check_premium(user_id)


def get_premium_info(user_id):
    """
    Get detailed premium information for a user.

    Args:
        user_id (int): Telegram user ID

    Returns:
        dict or None: Premium info dict or None if no premium
    """
    return get_user_premium_info(user_id)


def get_readable_time(seconds):
    """
    Convert seconds to a readable time format.

    Args:
        seconds (int): Number of seconds

    Returns:
        str: Human readable time string
    """
    try:
        periods = [
            ("year", 60 * 60 * 24 * 365),
            ("month", 60 * 60 * 24 * 30),
            ("day", 60 * 60 * 24),
            ("hour", 60 * 60),
            ("minute", 60),
            ("second", 1),
        ]

        strings = []
        for period_name, period_seconds in periods:
            if seconds >= period_seconds:
                period_value, seconds = divmod(seconds, period_seconds)
                has_s = "s" if period_value > 1 else ""
                strings.append(f"{period_value} {period_name}{has_s}")

        return ", ".join(strings[:2]) if strings else "0 seconds"
    except Exception:
        return f"{seconds} seconds"
