from asyncio import Lock
from base64 import b64decode
from pyrogram import Client, enums
from pyrogram.errors import AuthKeyInvalid, SessionPasswordNeeded

from bot import LOGGER, user_data
from bot.core.config_manager import Config


class UserSessionManager:
    """Manages individual user sessions for private channel/group access"""

    _user_sessions = {}
    _session_lock = Lock()

    @classmethod
    def _create_client(cls, session_string, user_id):
        """Create a pyrogram client with user session"""
        return Client(
            f"UserSession_{user_id}",
            api_id=Config.TELEGRAM_API,
            api_hash=Config.TELEGRAM_HASH,
            session_string=session_string,
            proxy=Config.TG_PROXY,
            parse_mode=enums.ParseMode.HTML,
            in_memory=True,
            no_updates=True,
            sleep_threshold=60,
        )

    @classmethod
    async def get_user_session(cls, user_id):
        """Get or create user session client"""
        async with cls._session_lock:
            # Check if session already exists and is active
            if user_id in cls._user_sessions:
                client = cls._user_sessions[user_id]
                if client and not client.is_connected:
                    try:
                        await client.connect()
                        return client
                    except Exception as e:
                        LOGGER.error(f"Failed to reconnect user session {user_id}: {e}")
                        # Remove invalid session
                        cls._user_sessions.pop(user_id, None)
                elif client and client.is_connected:
                    return client

            # Get user session string from user data
            user_dict = user_data.get(user_id, {})
            session_string = user_dict.get("USER_SESSION_STRING")

            if not session_string:
                return None

            try:
                # Decrypt session string (reverse of base64 encoding)
                decoded_session = b64decode(session_string.encode()).decode()

                # Create and start client
                client = cls._create_client(decoded_session, user_id)
                await client.start()

                # Store active session
                cls._user_sessions[user_id] = client

                user_info = client.me
                username = user_info.username or user_info.first_name
                LOGGER.info(f"User session started for {user_id}: {username}")

                return client

            except AuthKeyInvalid:
                LOGGER.error(f"Invalid auth key for user {user_id} session")
                # Remove invalid session from user data
                if user_id in user_data and "USER_SESSION_STRING" in user_data[user_id]:
                    del user_data[user_id]["USER_SESSION_STRING"]
                return None
            except SessionPasswordNeeded:
                LOGGER.error(f"2FA enabled for user {user_id} - session cannot be used")
                return None
            except Exception as e:
                LOGGER.error(f"Failed to start user session for {user_id}: {e}")
                # Don't remove session on generic errors as it might be temporary
                return None

    @classmethod
    async def stop_user_session(cls, user_id):
        """Stop and remove user session"""
        async with cls._session_lock:
            if user_id in cls._user_sessions:
                client = cls._user_sessions.pop(user_id)
                if client:
                    try:
                        await client.stop()
                        LOGGER.info(f"User session stopped for {user_id}")
                    except Exception as e:
                        LOGGER.error(f"Error stopping user session {user_id}: {e}")

    @classmethod
    async def stop_all_user_sessions(cls):
        """Stop all user sessions"""
        async with cls._session_lock:
            for user_id in list(cls._user_sessions.keys()):
                await cls.stop_user_session(user_id)

    @classmethod
    async def validate_user_session(cls, user_id):
        """Validate if user has a working session"""
        try:
            client = await cls.get_user_session(user_id)
            if client:
                # Try to get user info to validate session
                await client.get_me()
                return True
        except Exception as e:
            LOGGER.error(f"User session validation failed for {user_id}: {e}")
        return False

    @classmethod
    async def can_access_chat(cls, user_id, chat_id):
        """Check if user session can access a specific chat"""
        try:
            client = await cls.get_user_session(user_id)
            if not client:
                return False

            # Try to get chat info
            await client.get_chat(chat_id)
            return True
        except Exception as e:
            LOGGER.debug(f"User {user_id} cannot access chat {chat_id}: {e}")
            return False

    @classmethod
    async def get_message_with_user_session(cls, user_id, chat_id, message_id):
        """Get message using user session"""
        try:
            client = await cls.get_user_session(user_id)
            if not client:
                return None

            message = await client.get_messages(chat_id, message_id)
            return message
        except Exception as e:
            LOGGER.error(
                f"Failed to get message {message_id} from {chat_id} using user session {user_id}: {e}"
            )
            return None

    @classmethod
    def has_user_session(cls, user_id):
        """Check if user has a session string configured"""
        user_dict = user_data.get(user_id, {})
        return bool(user_dict.get("USER_SESSION_STRING"))

    @classmethod
    async def remove_user_session(cls, user_id):
        """Remove user session and clean up"""
        # Stop active session
        await cls.stop_user_session(user_id)

        # Remove from user data
        user_dict = user_data.get(user_id, {})
        if "USER_SESSION_STRING" in user_dict:
            del user_dict["USER_SESSION_STRING"]
            LOGGER.info(f"User session removed for {user_id}")
