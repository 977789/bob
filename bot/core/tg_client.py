from pyrogram import Client, enums
from asyncio import Lock, gather
from inspect import signature

from .. import LOGGER
from .config_manager import Config


class TgClient:
    _lock = Lock()
    _hlock = Lock()

    bot = None
    user = None
    helper_bots = {}
    helper_loads = {}
    # stream utils
    stream_bots = {}
    stream_work_loads = {}

    BNAME = ""
    ID = 0
    IS_PREMIUM_USER = False
    MAX_SPLIT_SIZE = 2097152000

    @classmethod
    def mhtgClient(cls, *args, **kwargs):
        kwargs["api_id"] = Config.TELEGRAM_API
        kwargs["api_hash"] = Config.TELEGRAM_HASH
        kwargs["proxy"] = Config.TG_PROXY
        kwargs["parse_mode"] = enums.ParseMode.HTML
        kwargs["in_memory"] = True
        for param, value in {
            "max_concurrent_transmissions": 100,
            "skip_updates": False,
        }.items():
            if param in signature(Client.__init__).parameters:
                kwargs[param] = value
        return Client(*args, **kwargs)

    @classmethod
    async def start_hclient(cls, no, b_token):
        try:
            hbot = await cls.mhtgClient(
                f"MH-HBot{no}",
                bot_token=b_token,
                no_updates=True,
            ).start()
            LOGGER.info(f"Helper Bot [@{hbot.me.username}] Started!")
            cls.helper_bots[no], cls.helper_loads[no] = hbot, 0
        except Exception as e:
            LOGGER.error(f"Failed to start helper bot {no} from HELPER_TOKENS. {e}")
            cls.helper_bots.pop(no, None)

    @classmethod
    async def start_helper_bots(cls):
        if not Config.HELPER_TOKENS:
            return
        LOGGER.info("Generating helper client from HELPER_TOKENS")
        async with cls._hlock:
            await gather(
                *(
                    cls.start_hclient(no, b_token)
                    for no, b_token in enumerate(Config.HELPER_TOKENS.split(), start=1)
                )
            )

    @classmethod
    async def start_bot(cls):
        LOGGER.info("Generating client from BOT_TOKEN")
        cls.ID = Config.BOT_TOKEN.split(":", 1)[0]
        cls.bot = cls.mhtgClient(
            f"MH-Bot{cls.ID}",
            bot_token=Config.BOT_TOKEN,
            workdir="/usr/src/app",
        )
        await cls.bot.start()
        cls.BNAME = cls.bot.me.username
        cls.ID = Config.BOT_TOKEN.split(":", 1)[0]
        LOGGER.info(f"MH Bot : [@{cls.BNAME}] Started!")

    @classmethod
    async def start_user(cls):
        if Config.USER_SESSION_STRING:
            LOGGER.info("Generating client from USER_SESSION_STRING")
            try:
                cls.user = cls.mhtgClient(
                    "MH-User",
                    session_string=Config.USER_SESSION_STRING,
                    sleep_threshold=60,
                    no_updates=True,
                )
                await cls.user.start()
                cls.IS_PREMIUM_USER = cls.user.me.is_premium
                LOGGER.info(
                    f"Premium Status Check: User is {'' if cls.IS_PREMIUM_USER else 'NOT '} Premium"
                )

                # Always force premium status to True if user session is available
                # This ensures we always get 4GB uploads if a user session is provided
                if not cls.IS_PREMIUM_USER:
                    LOGGER.warning(
                        "Forcing Premium User status by default for all user sessions"
                    )
                    cls.IS_PREMIUM_USER = True

                if cls.IS_PREMIUM_USER:
                    cls.MAX_SPLIT_SIZE = 4194304000  # 4GB for Premium
                    LOGGER.info(f"Setting MAX_SPLIT_SIZE to 4GB: {cls.MAX_SPLIT_SIZE}")
                else:
                    LOGGER.info(
                        f"Using standard MAX_SPLIT_SIZE of 2GB: {cls.MAX_SPLIT_SIZE}"
                    )

                uname = cls.user.me.username or cls.user.me.first_name
                LOGGER.info(
                    f"MH User : [{uname}] Started! Premium: {cls.IS_PREMIUM_USER}"
                )
            except Exception as e:
                LOGGER.error(f"Failed to start client from USER_SESSION_STRING. {e}")
                cls.IS_PREMIUM_USER = False
                cls.user = None

    @classmethod
    async def stop(cls):
        from ..helper.ext_utils.user_session_manager import UserSessionManager

        async with cls._lock:
            stopped_clients = set()

            # Stop all user sessions first
            await UserSessionManager.stop_all_user_sessions()

            if cls.bot:
                await cls.bot.stop()
                stopped_clients.add(cls.bot.name)
                cls.bot = None
            if cls.user:
                await cls.user.stop()
                stopped_clients.add(cls.user.name)
                cls.user = None
            if cls.helper_bots:
                await gather(*[h_bot.stop() for h_bot in cls.helper_bots.values()])
                cls.helper_bots = {}

            # Stop stream bots if they exist and haven't been stopped already
            if cls.stream_bots:
                tasks = []
                for s_bot in cls.stream_bots.values():
                    if s_bot.name not in stopped_clients:
                        tasks.append(s_bot.stop())
                        stopped_clients.add(s_bot.name)
                if tasks:
                    await gather(*tasks)
                cls.stream_bots = {}
                cls.stream_work_loads = {}
            LOGGER.info("All Client(s) stopped")

    @classmethod
    async def reload(cls):
        async with cls._lock:
            await cls.bot.restart()
            if cls.user:
                await cls.user.restart()
            if cls.helper_bots:
                await gather(*[h_bot.restart() for h_bot in cls.helper_bots.values()])
            if cls.stream_bots:
                await gather(*[s_bot.restart() for s_bot in cls.stream_bots.values()])
            LOGGER.info("All Client(s) restarted")

    @classmethod
    async def start_stream(cls):
        """Initialize stream clients. Uses STREAM_MULTI_TOKENS if available, otherwise defaults to the main bot/user client."""
        try:
            # Initialize stream storage if not already done
            if not hasattr(cls, "stream_bots"):
                cls.stream_bots = {}
            if not hasattr(cls, "stream_work_loads"):
                cls.stream_work_loads = {}

            all_tokens = (
                Config.STREAM_MULTI_TOKENS.split()
                if hasattr(Config, "STREAM_MULTI_TOKENS") and Config.STREAM_MULTI_TOKENS
                else []
            )

            if all_tokens:
                LOGGER.info(
                    f"Found {len(all_tokens)} stream tokens. Initializing stream clients..."
                )

                async def _start_client(client_id: int, token: str):
                    try:
                        # Create client kwargs
                        client_kwargs = {
                            "api_id": Config.TELEGRAM_API,
                            "api_hash": Config.TELEGRAM_HASH,
                            "parse_mode": enums.ParseMode.HTML,
                            "in_memory": True,
                            "no_updates": True,
                        }

                        # Add proxy if configured
                        if hasattr(Config, "TG_PROXY") and Config.TG_PROXY:
                            client_kwargs["proxy"] = Config.TG_PROXY

                        client = Client(
                            f"StreamBot{client_id}",
                            bot_token=token.strip(),
                            **client_kwargs,
                        )

                        await client.start()
                        cls.stream_work_loads[client_id] = 0
                        cls.stream_bots[client_id] = client

                        username = (
                            client.me.username
                            if client.me.username
                            else f"Bot{client_id}"
                        )
                        LOGGER.info(
                            f"Stream client {client_id} [@{username}] started successfully."
                        )

                    except Exception as e:
                        LOGGER.error(
                            f"Failed to start stream client {client_id} with token {token[:10]}... Error: {e}"
                        )
                        # Remove failed client from dictionaries if it was added
                        cls.stream_bots.pop(client_id, None)
                        cls.stream_work_loads.pop(client_id, None)

                await gather(
                    *[
                        _start_client(i, token.strip())
                        for i, token in enumerate(all_tokens, 1)
                    ]
                )

                successful_clients = len(cls.stream_bots)
                if successful_clients > 0:
                    LOGGER.info(
                        f"Stream multi client mode enabled! {successful_clients}/{len(all_tokens)} clients started successfully."
                    )
                else:
                    LOGGER.warning(
                        "No stream clients could be started from STREAM_MULTI_TOKENS."
                    )

            # If no stream bots were initialized from tokens, use the main client.
            if not cls.stream_bots:
                client_to_use = TgClient.bot
                if client_to_use:
                    cls.stream_bots[0] = client_to_use
                    cls.stream_work_loads[0] = 0
                    uname = client_to_use.me.username or client_to_use.me.first_name
                    LOGGER.info(
                        f"No STREAM_MULTI_TOKENS, using main client [@{uname}] for streaming."
                    )
                else:
                    LOGGER.warning(
                        "No stream clients available and no main client to fall back on. Streaming will not work."
                    )
        except Exception as e:
            LOGGER.error(f"Error during stream clients initialization: {e}")
            # Ensure clean state on failure
            cls.stream_bots = {}
            cls.stream_work_loads = {}
