import pytz
from time import time
from datetime import datetime

from ...core.config_manager import Config
from ...core.tg_client import TgClient
from ..telegram_helper.button_build import ButtonMaker
from .verification_db import get_verification_db
from ... import LOGGER


VERIFY_HEADER_TEXT = "Action Required: Please Verify"
VERIFY_BODY_MSG = (
    "To continue and unlock all features, please complete a quick verification. "
    "It's fast and helps keep our community safe."
)

VERIFY_BUTTON_TEXT = "✅ Start Verification"
PREMIUM_BUTTON_TEXT = "💿 Go Premium (Skip Verification)"


def normalize_bot_identifier(bot_username):
    bot_username = bot_username.lower().replace("@", "")
    if "_bot" in bot_username:
        return bot_username
    if "_robot" in bot_username:
        return bot_username
    return bot_username.replace("_", "")


def parse_expiry(value):
    """Handle both timestamp float and date string."""
    try:
        if isinstance(value, str) and "-" in value:
            dt = datetime.strptime(value, "%Y-%m-%d")
            tz = pytz.timezone(Config.TIMEZONE)
            return dt.replace(hour=23, minute=59, second=59, tzinfo=tz).astimezone(
                pytz.UTC
            )
        elif (
            isinstance(value, (int, float)) or str(value).replace(".", "", 1).isdigit()
        ):
            return float(value)
    except Exception as e:
        LOGGER.error(f"parse_expiry: Error parsing value {value}: {e}")
    return None


async def _check_general_token_validity(user_id, token_id_str, vdb):
    LOGGER.debug(
        f"VC._check_general_token_validity: User: {user_id}, TokenID: {token_id_str}"
    )
    if vdb is None or vdb.col is None:
        LOGGER.warning(f"DB unavailable. User: {user_id}, Token: {token_id_str}")
        return False

    raw_value = await vdb.get_token_expire_date(user_id, token_id_str)
    if not raw_value:
        LOGGER.debug(f"No token field for User: {user_id}, Token: {token_id_str}")
        return False

    parsed = parse_expiry(raw_value)
    if isinstance(parsed, datetime):
        now_utc = datetime.now(pytz.UTC)
        return now_utc <= parsed
    elif isinstance(parsed, float):
        return time() <= parsed

    return False


async def _check_single_token_expiry(user_id, bot_identifier, vdb, allow_fallback=True):
    if vdb is None or vdb.col is None:
        LOGGER.warning(f"VDB unavailable for User: {user_id}")
        return False

    raw_expiry = await vdb.get_token_expire_date(user_id, bot_identifier)
    parsed = parse_expiry(raw_expiry)

    if isinstance(parsed, float):
        try:
            duration_str = await vdb.get_premium_user_time(user_id, bot_identifier)
            duration = (
                int(duration_str)
                if duration_str and str(duration_str).isdigit()
                else Config.VERIFY_DURATION
            )
            if (time() - parsed) <= duration:
                return True
        except Exception as e:
            LOGGER.error(f"Error in bot-specific expiry for User: {user_id}: {e}")
    elif isinstance(parsed, datetime):
        now_utc = datetime.now(pytz.UTC)
        if now_utc <= parsed:
            return True

    if allow_fallback:
        LOGGER.info(f"User {user_id}: fallback to general token")
        return await _check_general_token_validity(user_id, "1", vdb)
    return False


async def check_premium_status(user_id):
    """
    Check if a user has premium access that bypasses verification requirements.

    Args:
        user_id (int): Telegram user ID

    Returns:
        bool: True if user has active premium, False otherwise
    """
    vdb = await get_verification_db()
    if vdb is None or vdb.col is None:
        LOGGER.warning(f"VDB unavailable for premium check. User: {user_id}")
        return False

    try:
        is_premium = await vdb.get_premium_status(user_id)
        if not is_premium:
            LOGGER.debug(f"User {user_id} does not have premium status")
            return False

        # Check if premium has expired
        premium_expiry = await vdb.get_premium_expiry(user_id)
        if premium_expiry:
            parsed = parse_expiry(premium_expiry)
            if isinstance(parsed, datetime):
                now_utc = datetime.now(pytz.UTC)
                if now_utc > parsed:
                    LOGGER.debug(f"User {user_id} premium has expired")
                    return False
            elif isinstance(parsed, float):
                if time() > parsed:
                    LOGGER.debug(f"User {user_id} premium has expired")
                    return False

        LOGGER.info(f"User {user_id} has active premium status")
        return True
    except Exception as e:
        LOGGER.error(f"Error checking premium status for user {user_id}: {e}")
        return False


async def check_ban_status(user_id):
    """
    Check if a user is banned.

    Args:
        user_id (int): Telegram user ID

    Returns:
        bool: True if user is banned, False otherwise
    """
    vdb = await get_verification_db()
    if vdb is None or vdb.col is None:
        LOGGER.warning(f"VDB unavailable for ban check. User: {user_id}")
        return False

    try:
        is_banned = await vdb.get_ban_status(user_id)
        LOGGER.debug(f"User {user_id} ban status: {is_banned}")
        return is_banned
    except Exception as e:
        LOGGER.error(f"Error checking ban status for user {user_id}: {e}")
        return False


async def perform_verification_check(user_id, existing_button=None):
    if not Config.ENABLE_EXTERNAL_VERIFICATION:
        LOGGER.info("Verification disabled via config.")
        return None, existing_button

    vdb = await get_verification_db()
    if vdb is None or vdb.col is None:
        LOGGER.warning("Verification DB unavailable. Allowing user.")
        return None, existing_button

    # Check if user is banned first
    if await check_ban_status(user_id):
        LOGGER.warning(f"User {user_id} is banned")
        return "🚫 You are banned from using this bot.", existing_button

    # Check if user has premium status - premium users bypass all verification
    if await check_premium_status(user_id):
        LOGGER.info(f"User {user_id} has premium access - bypassing verification")
        return None, existing_button

    raw_identifier = (
        Config.BOT_USERNAME or TgClient.BNAME or str(TgClient.ID) or "defaultbot"
    )
    bot_identifier = normalize_bot_identifier(raw_identifier)

    # Check for single-token verification
    is_verified = await _check_single_token_expiry(
        user_id, bot_identifier, vdb, allow_fallback=False
    )
    if is_verified:
        LOGGER.info(f"User {user_id} passed verification.")
        return None, existing_button

    verify_type = await vdb.get_verify_status(user_id)
    LOGGER.warning(
        f"User {user_id} - Verification triggered. DB Verify Type: {verify_type}, Bot ID: {bot_identifier}"
    )

    button = existing_button or ButtonMaker()
    needs_prompt = False

    if verify_type == "single":
        needs_prompt = True
        payload = f"verify_{bot_identifier}" if Config.BOT_USERNAME else "verify"
        button.url_button(
            VERIFY_BUTTON_TEXT, f"https://t.me/{Config.VERIFY_BOT}?start={payload}"
        )

    elif verify_type == "all":
        all_valid = True
        for i in range(1, Config.TOTAL_GENERAL_TOKENS_TO_CHECK + 1):
            token_ok = await _check_general_token_validity(user_id, str(i), vdb)
            LOGGER.debug(f"Token {i} validity for user {user_id}: {token_ok}")
            if not token_ok:
                LOGGER.info(f"User {user_id} failed general token check: token {i}")
                all_valid = False
                break
        if all_valid:
            LOGGER.info(f"User {user_id} passed all-token check.")
            return None, existing_button
        needs_prompt = True
        button.url_button(
            VERIFY_BUTTON_TEXT, f"https://t.me/{Config.VERIFY_BOT}?start=verify"
        )

    else:
        LOGGER.warning(f"Unknown verify_type '{verify_type}' for user {user_id}")
        needs_prompt = True
        button.url_button(
            VERIFY_BUTTON_TEXT, f"https://t.me/{Config.VERIFY_BOT}?start=verify"
        )

    if needs_prompt and Config.VERIFY_BOT:
        button.url_button(
            PREMIUM_BUTTON_TEXT, f"https://t.me/{Config.VERIFY_BOT}?start=premium"
        )
        msg = f"✨ <b>{VERIFY_HEADER_TEXT}</b>\n\n{VERIFY_BODY_MSG}"
        LOGGER.info(f"Prompting user {user_id} for verification.")
        return msg, button

    return None, existing_button
