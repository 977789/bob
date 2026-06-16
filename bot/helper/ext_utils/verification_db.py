import motor.motor_asyncio

from ...core.config_manager import Config  # Corrected import path
from ... import LOGGER  # Corrected import path

# Global instance, initialized on first use or explicitly
_verification_db_instance = None


class VerificationDb:
    def __init__(self, uri, database_name):
        try:
            self._client = motor.motor_asyncio.AsyncIOMotorClient(uri)
            self.db = self._client[database_name]
            # Collection names based on analysis of verify-bot and bot-verifysupport
            # 'user_data' collection seems to be where 'date<token_name>' and 'verify' fields are stored.
            # 'bot-verifysupport/token_db.py' used 'access_token' for this.
            # 'verify-bot/add_verify.py' updates user_data and calls database.update_user_data(target_id)
            # Let's assume the collection is named 'users' as it's common, or 'user_data'
            # The original token_db.py used 'access_token'. Let's stick to that for now and adjust if needed.
            # From verify-bot's db_handler, it seems it might be db.users[TgClient.ID]
            # For simplicity and to align with the source `token_db.py`, using `access_token`
            # but this might need adjustment if `verify-bot` uses a different collection for these specific fields.
            # The `user_data` in `verify-bot` seems to be an in-memory cache that is then saved via `db_handler.py`
            # which uses `self.db.users[TgClient.ID].replace_one({'_id': user_id}, data, upsert=True)`
            # So, the collection is indeed 'users' and it's keyed by bot ID.
            # However, the token_db.py from bot-verifysupport uses a single collection 'access_token'
            # and doesn't key by bot_id in the collection name itself.
            # Using 'user_data' collection as specified by user.
            self.col = self.db.user_data  # Changed from users to user_data
            # self.col2 = self.db.short_url # This was for short_url specific settings in bot-verifysupport, may not be needed by main bot directly
            LOGGER.info("VerificationDb: Connected.")
        except Exception as e:
            LOGGER.error(f"VerificationDb: Error connecting to database: {e}")
            self._client = None
            self.db = None
            self.col = None

    async def get_token_expire_date(self, user_id, token_identifier):
        """
        Fetches the token expiration date/timestamp.
        token_identifier can be a specific bot_username (e.g., "MyMainBot") or a general token_id (e.g., 1, 2, 3).
        In verify-bot, these are stored as 'date<bot_username>' or 'date<token_id>'.
        """
        if self.col is None:
            LOGGER.debug(
                f"VDB.get_token_expire_date: Collection is None. User: {user_id}, Identifier: {token_identifier}"
            )
            return None
        user_doc = await self.col.find_one({"_id": int(user_id)})
        LOGGER.debug(f"VDB.get_token_expire_date: UserDoc for {user_id}: {user_doc}")
        if user_doc:
            value = user_doc.get(f"date{token_identifier}")
            LOGGER.debug(
                f"VDB.get_token_expire_date: User: {user_id}, Identifier: {token_identifier}, Field: date{token_identifier}, Value: {value}"
            )
            return value
        LOGGER.debug(
            f"VDB.get_token_expire_date: No UserDoc or field for User: {user_id}, Identifier: {token_identifier}"
        )
        return None

    async def get_premium_user_time(self, user_id, token_identifier):
        """
        Fetches the premium time for a user for a specific token/bot.
        Stored as 'prm_time<bot_username>' or 'prm_time<token_id>'.
        """
        if self.col is None:
            LOGGER.debug(
                f"VDB.get_premium_user_time: Collection is None. User: {user_id}, Identifier: {token_identifier}"
            )
            return None
        user_doc = await self.col.find_one({"_id": int(user_id)})
        LOGGER.debug(f"VDB.get_premium_user_time: UserDoc for {user_id}: {user_doc}")
        if user_doc:
            value = user_doc.get(f"prm_time{token_identifier}")
            LOGGER.debug(
                f"VDB.get_premium_user_time: User: {user_id}, Identifier: {token_identifier}, Field: prm_time{token_identifier}, Value: {value}"
            )
            return value
        LOGGER.debug(
            f"VDB.get_premium_user_time: No UserDoc or field for User: {user_id}, Identifier: {token_identifier}"
        )
        return None

    async def get_verify_status(self, user_id):
        """
        Gets how the user should be verified (e.g., "all", "single").
        Stored as 'verify' field in the user's document.
        """
        if self.col is None:
            LOGGER.debug(
                f"VDB.get_verify_status: Collection is None. User: {user_id}. Returning 'all'."
            )
            return "all"  # Default to 'all' if DB error or not found
        user_doc = await self.col.find_one({"_id": int(user_id)})
        LOGGER.debug(f"VDB.get_verify_status: UserDoc for {user_id}: {user_doc}")
        if user_doc:
            value = user_doc.get("verify", "all")
            LOGGER.debug(
                f"VDB.get_verify_status: User: {user_id}, Field: verify, Value: {value}"
            )
            return value
        LOGGER.debug(
            f"VDB.get_verify_status: No UserDoc for {user_id}. Returning 'all'."
        )
        return "all"

    async def get_premium_status(self, user_id):
        """
        Check if a user has premium status.
        Stored as 'is_premium' field in the user's document.
        """
        if self.col is None:
            LOGGER.debug(
                f"VDB.get_premium_status: Collection is None. User: {user_id}. Returning False."
            )
            return False
        user_doc = await self.col.find_one({"_id": int(user_id)})
        LOGGER.debug(f"VDB.get_premium_status: UserDoc for {user_id}: {user_doc}")
        if user_doc:
            value = user_doc.get("is_premium", False)
            LOGGER.debug(
                f"VDB.get_premium_status: User: {user_id}, Field: is_premium, Value: {value}"
            )
            return value
        LOGGER.debug(
            f"VDB.get_premium_status: No UserDoc for {user_id}. Returning False."
        )
        return False

    async def get_premium_expiry(self, user_id):
        """
        Get premium expiry timestamp for a user.
        Stored as 'premium_expiry' field in the user's document.
        """
        if self.col is None:
            LOGGER.debug(
                f"VDB.get_premium_expiry: Collection is None. User: {user_id}. Returning None."
            )
            return None
        user_doc = await self.col.find_one({"_id": int(user_id)})
        LOGGER.debug(f"VDB.get_premium_expiry: UserDoc for {user_id}: {user_doc}")
        if user_doc:
            value = user_doc.get("premium_expiry")
            LOGGER.debug(
                f"VDB.get_premium_expiry: User: {user_id}, Field: premium_expiry, Value: {value}"
            )
            return value
        LOGGER.debug(
            f"VDB.get_premium_expiry: No UserDoc for {user_id}. Returning None."
        )
        return None

    async def get_ban_status(self, user_id):
        """
        Check if a user is banned.
        Stored as 'is_ban' field in the user's document.
        """
        if self.col is None:
            LOGGER.debug(
                f"VDB.get_ban_status: Collection is None. User: {user_id}. Returning False."
            )
            return False
        user_doc = await self.col.find_one({"_id": int(user_id)})
        LOGGER.debug(f"VDB.get_ban_status: UserDoc for {user_id}: {user_doc}")
        if user_doc:
            value = user_doc.get("is_ban", False)
            LOGGER.debug(
                f"VDB.get_ban_status: User: {user_id}, Field: is_ban, Value: {value}"
            )
            return value
        LOGGER.debug(f"VDB.get_ban_status: No UserDoc for {user_id}. Returning False.")
        return False

    # Methods like get_total, get_token_time from the original token_db.py might be specific
    # to bot-verifysupport's own token/shortener system and not directly needed by the main bot
    # for checking verification status set by verify-bot.
    # The main bot primarily needs to read 'date<identifier>', 'prm_time<identifier>', and 'verify' fields.

    # It's unlikely the main bot will SET verification data, only read it.
    # Functions like update_premium_user_time, set_verify were for bot-verifysupport itself.


async def get_verification_db():
    global _verification_db_instance
    if Config.DATABASE_URL_VERIFY and not _verification_db_instance:
        _verification_db_instance = VerificationDb(
            Config.DATABASE_URL_VERIFY, Config.DATABASE_NAME_VERIFY
        )
    if (
        _verification_db_instance and _verification_db_instance.col is None
    ):  # Attempt to reconnect if connection failed previously
        _verification_db_instance = VerificationDb(
            Config.DATABASE_URL_VERIFY, Config.DATABASE_NAME_VERIFY
        )
    return _verification_db_instance


# Example of how it might be initialized during startup in main bot's __main__.py or startup.py
# async def on_startup():
#     await get_verification_db() # Initialize/check connection
#     # ... other startup tasks
