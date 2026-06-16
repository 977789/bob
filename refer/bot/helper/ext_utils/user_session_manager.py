from asyncio import Lock
from base64 import b64decode
from pyrogram import Client, enums
from pyrogram.errors import AuthKeyInvalid, SessionPasswordNeeded, FloodWait
from inspect import signature

from ... import LOGGER, user_data
from ...core.config_manager import Config
from ...core.tg_client import TgClient


class UserSessionManager:
    """Manages individual user sessions for private channel/group access"""

    _user_sessions = {}
    _session_lock = Lock()

    @classmethod
    def _create_client(cls, session_string, user_id):
        """Create a pyrogram client with user session"""
        kwargs = {
            "api_id": Config.TELEGRAM_API,
            "api_hash": Config.TELEGRAM_HASH,
            "session_string": session_string,
            "proxy": Config.TG_PROXY,
            "parse_mode": enums.ParseMode.HTML,
            "in_memory": True,
            "no_updates": True,
            "sleep_threshold": 60,
        }

        # Add additional parameters if supported
        for param, value in {
            "max_concurrent_transmissions": 100,
            "skip_updates": True,
        }.items():
            if param in signature(Client.__init__).parameters:
                kwargs[param] = value

        return Client(f"UserSession_{user_id}", **kwargs)

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

            def _sanitize(raw: str) -> str:
                # Trim whitespace and common wrappers from Telegram formatting
                s = (raw or "").strip()
                # Remove Telegram spoiler wrappers ||...|| if present
                if s.startswith("||") and s.endswith("||") and len(s) > 4:
                    s = s[2:-2]
                # Remove surrounding quotes/backticks
                for q in ("`", "'", '"'):
                    if s.startswith(q) and s.endswith(q) and len(s) > 2:
                        s = s[1:-1]
                # Remove triple backticks and their lines if present
                if s.startswith("```") and s.endswith("```"):
                    s = s.strip("`")
                # Drop spaces, newlines, and common invisible chars
                for ch in (
                    "\n",
                    "\r",
                    " ",
                    "\t",
                    "\u200b",
                    "\u200c",
                    "\u200d",
                    "\u2060",
                    "\ufeff",
                ):
                    s = s.replace(ch, "")
                # If text contains other words, extract the longest base64-like token
                try:
                    import re as _re

                    tokens = _re.findall(r"[A-Za-z0-9_\-\+/=]{50,}", s)
                    if tokens:
                        s = max(tokens, key=len)
                except Exception:
                    pass
                return s

            # Build candidate list: decoded once, sanitized original, decoded twice
            candidates = []

            def _try_b64_decode_to_text(s: str):
                import base64 as _b64

                def _pad(t: str) -> str:
                    missing = (-len(t)) % 4
                    return t + ("=" * missing)

                try:
                    return _b64.b64decode(_pad(s)).decode()
                except Exception:
                    try:
                        return _b64.urlsafe_b64decode(_pad(s)).decode()
                    except Exception:
                        return None

            orig = _sanitize(session_string)
            dec1 = _try_b64_decode_to_text(orig)
            dec2 = _try_b64_decode_to_text(dec1) if dec1 else None

            if dec1:
                candidates.append(_sanitize(dec1))
            # Original next
            if orig:
                candidates.append(orig)
            if dec2:
                candidates.append(_sanitize(dec2))

            last_error = None
            for candidate in candidates:
                if not candidate:
                    continue
                try:
                    # Debug-friendly minimal fingerprint (INFO for visibility)
                    fp = (
                        candidate[:3] + "…" + candidate[-3:]
                        if len(candidate) > 6
                        else "len=" + str(len(candidate))
                    )
                    LOGGER.info(
                        f"Trying user session candidate for {user_id}: {fp} (len={len(candidate)})"
                    )
                    client = cls._create_client(candidate, user_id)
                    await client.start()
                    # Store active session
                    cls._user_sessions[user_id] = client
                    user_info = client.me
                    username = user_info.username or user_info.first_name
                    LOGGER.info(f"User session started for {user_id}: {username}")
                    return client
                except AuthKeyInvalid as e:
                    last_error = e
                    LOGGER.error(
                        f"Invalid auth key for user {user_id} session (candidate failed)"
                    )
                except SessionPasswordNeeded as e:
                    last_error = e
                    LOGGER.error(
                        f"2FA enabled for user {user_id} - session cannot be used"
                    )
                    break
                except Exception as e:
                    last_error = e
                    # Try next candidate (often happens if user pasted with spoilers or whitespace)
                    continue

            # If we reach here, all candidates failed
            if isinstance(last_error, AuthKeyInvalid):
                LOGGER.error(f"Invalid auth key for user {user_id} session")
                # Remove invalid session from user data
                if user_id in user_data and "USER_SESSION_STRING" in user_data[user_id]:
                    del user_data[user_id]["USER_SESSION_STRING"]
                return None
            if isinstance(last_error, SessionPasswordNeeded):
                return None
            # Generic failure
            if last_error and "unpack requires a buffer of" in str(last_error):
                LOGGER.error(
                    f"Failed to start user session for {user_id}: {last_error}. Hint: Make sure this is a Pyrogram v2 session string copied without formatting (no spoilers/backticks), or regenerate via gen_pyro_session.py"
                )
                # This error strongly indicates a malformed or non-Pyrogram session; remove it to force re-add.
                user_dict = user_data.get(user_id, {})
                if "USER_SESSION_STRING" in user_dict:
                    del user_dict["USER_SESSION_STRING"]
                    LOGGER.info(
                        f"Cleared invalid session string for user {user_id} due to unpack error"
                    )
            else:
                LOGGER.error(
                    f"Failed to start user session for {user_id}: {last_error}"
                )
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
            chat = await client.get_chat(chat_id)
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
