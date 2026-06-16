from aiohttp import web

from ... import LOGGER
from ...core.config_manager import Config
from .stream_routes import routes


def _web_server():
    web_app = web.Application(client_max_size=30000000)
    web_app.add_routes(routes)
    return web_app


server = web.AppRunner(_web_server())


async def start_server():
    await server.cleanup()
    if Config.ENABLE_STREAM_LINK and Config.STREAM_BASE_URL and Config.STREAM_PORT:
        LOGGER.info("Initializing web stream on port %s", Config.STREAM_PORT)
        await server.setup()
        await web.TCPSite(server, "0.0.0.0", Config.STREAM_PORT).start()
