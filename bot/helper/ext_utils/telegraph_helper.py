from asyncio import sleep
from secrets import token_hex
from telegraph.aio import Telegraph
from telegraph.exceptions import RetryAfterError

from ... import LOGGER
from ...core.config_manager import Config


class TelegraphHelper:
    def __init__(self, author_name=None, author_url=None):
        self._telegraph = Telegraph(domain="graph.org")
        self._author_name = author_name
        self._author_url = author_url
        self._account_created = False

    async def create_account(self):
        # Avoid repeated account creation attempts/log spam
        if self._account_created:
            return
        LOGGER.info("Creating Telegraph Account")
        try:
            await self._telegraph.create_account(
                short_name=token_hex(5),
                author_name=self._author_name,
                author_url=self._author_url,
            )
            self._account_created = True
        except Exception as e:
            LOGGER.error(f"Failed to create Telegraph Account: {e}")

    async def create_page(self, title, content):
        try:
            return await self._telegraph.create_page(
                title=title,
                author_name=self._author_name,
                author_url=self._author_url,
                html_content=content,
            )
        except RetryAfterError as st:
            LOGGER.warning(
                f"Telegraph Flood control exceeded. I will sleep for {st.retry_after} seconds."
            )
            await sleep(st.retry_after)
            return await self.create_page(title, content)

    async def edit_page(self, path, title, content):
        try:
            return await self._telegraph.edit_page(
                path=path,
                title=title,
                author_name=self._author_name,
                author_url=self._author_url,
                html_content=content,
            )
        except RetryAfterError as st:
            LOGGER.warning(
                f"Telegraph Flood control exceeded. I will sleep for {st.retry_after} seconds."
            )
            await sleep(st.retry_after)
            return await self.edit_page(path, title, content)

    async def edit_telegraph(self, path, telegraph_content):
        nxt_page = 1
        prev_page = 0
        num_of_path = len(path)
        for content in telegraph_content:
            if nxt_page == 1:
                content += (
                    f'<b><a href="https://telegra.ph/{path[nxt_page]}">Next</a></b>'
                )
                nxt_page += 1
            else:
                if prev_page <= num_of_path:
                    content += f'<b><a href="https://telegra.ph/{path[prev_page]}">Prev</a></b>'
                    prev_page += 1
                if nxt_page < num_of_path:
                    content += f'<b> | <a href="https://telegra.ph/{path[nxt_page]}">Next</a></b>'
                    nxt_page += 1
            await self.edit_page(
                path=path[prev_page],
                title="Mirror-Hunter Torrent Search",
                content=content,
            )
        return


telegraph = TelegraphHelper(Config.AUTHOR_NAME, Config.AUTHOR_URL)

# print(__name__) # Let's remove this print


class TelePost:
    def __init__(self, title):
        self.title = title
        self.telegraph_instance = telegraph  # Use the existing instance

    async def create_post(self, content):
        try:
            # telegraph.aio.Telegraph().create_page returns a dict with 'url'
            # The local TelegraphHelper class's create_page also returns a dict with 'path'
            page = await self.telegraph_instance.create_page(
                title=self.title, content=content
            )
            if page and "url" in page:
                return page["url"]
            elif (
                page and "path" in page
            ):  # Fallback for local helper if it returns path
                return f"https://telegra.ph/{page['path']}"  # Construct URL from path
            LOGGER.error(
                f"TelePost: create_page did not return a url or path. Page data: {page}"
            )
            return None
        except Exception as e:
            LOGGER.error(f"TelePost failed to create post: {e}")
            return None
