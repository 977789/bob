from base64 import b64encode
from random import choice, random
from asyncio import sleep as asleep
from urllib.parse import quote

from cloudscraper import create_scraper
from urllib3 import disable_warnings

from ... import LOGGER, shortener_dict


async def short_url(longurl: str, alias: str = None, attempt: int = 0):
    if not shortener_dict:
        return longurl
    if attempt >= 4:
        return longurl
    _shortener, _shortener_api = choice(list(shortener_dict.items()))
    cget = create_scraper().request
    disable_warnings()
    try:
        if "shorte.st" in _shortener:
            if alias:
                LOGGER.debug(
                    f"Custom alias '{alias}' provided for '{_shortener}' shortener, but it's not supported by this shortener's current implementation. Proceeding without alias."
                )
            headers = {"public-api-token": _shortener_api}
            data = {"urlToShorten": quote(longurl)}
            return cget(
                "PUT", "https://api.shorte.st/v1/data/url", headers=headers, data=data
            ).json()["shortenedUrl"]
        elif "linkvertise" in _shortener:
            if alias:
                LOGGER.debug(
                    f"Custom alias '{alias}' provided for '{_shortener}' shortener, but it's not supported by this shortener's current implementation. Proceeding without alias."
                )
            url = quote(b64encode(longurl.encode("utf-8")))
            linkvertise = [
                f"https://link-to.net/{_shortener_api}/{random() * 1000}/dynamic?r={url}",
                f"https://up-to-down.net/{_shortener_api}/{random() * 1000}/dynamic?r={url}",
                f"https://direct-link.net/{_shortener_api}/{random() * 1000}/dynamic?r={url}",
                f"https://file-link.net/{_shortener_api}/{random() * 1000}/dynamic?r={url}",
            ]
            return choice(linkvertise)
        elif "bitly.com" in _shortener:
            if alias:
                LOGGER.debug(
                    f"Custom alias '{alias}' provided for '{_shortener}' shortener, but it's not supported by this shortener's current implementation. Proceeding without alias."
                )
            headers = {"Authorization": f"Bearer {_shortener_api}"}
            return cget(
                "POST",
                "https://api-ssl.bit.ly/v4/shorten",
                json={"long_url": longurl},
                headers=headers,
            ).json()["link"]
        elif "ouo.io" in _shortener:
            if alias:
                LOGGER.debug(
                    f"Custom alias '{alias}' provided for '{_shortener}' shortener, but it's not supported by this shortener's current implementation. Proceeding without alias."
                )
            return cget(
                "GET", f"http://ouo.io/api/{_shortener_api}?s={longurl}", verify=False
            ).text
        elif "cutt.ly" in _shortener:
            if alias:
                LOGGER.debug(
                    f"Custom alias '{alias}' provided for '{_shortener}' shortener, but it's not supported by this shortener's current implementation. Proceeding without alias."
                )
            return cget(
                "GET",
                f"http://cutt.ly/api/api.php?key={_shortener_api}&short={longurl}",
            ).json()["url"]["shortLink"]
        else:  # Default shortener logic that might support alias
            api_url = (
                f"https://{_shortener}/api?api={_shortener_api}&url={quote(longurl)}"
            )
            if alias:
                api_url += f"&alias={quote(alias)}"
            res = cget("GET", api_url).json()
            shorted = res.get("shortenedUrl")  # Use .get for safer access
            if not shorted:
                LOGGER.debug(
                    f"Alias '{alias}' might have failed or is not supported by {_shortener}, or first attempt failed. Trying with shrtco.de intermediary if applicable."
                )
                # Fallback to shrtco.de if the primary shortener fails or doesn't return a URL
                # The alias is typically for the primary shortener, not shrtco.de
                shrtco_res = cget(
                    "GET", f"https://api.shrtco.de/v2/shorten?url={quote(longurl)}"
                ).json()
                shrtco_link = shrtco_res.get("result", {}).get("full_short_link")
                if shrtco_link:
                    # Try the original shortener again with the shrtco_link, applying alias again
                    api_url_fallback = f"https://{_shortener}/api?api={_shortener_api}&url={quote(shrtco_link)}"
                    if alias:
                        api_url_fallback += f"&alias={quote(alias)}"  # Re-apply alias for the original shortener
                    res_fallback = cget("GET", api_url_fallback).json()
                    shorted = res_fallback.get("shortenedUrl")
            if not shorted:
                shorted = longurl
            return shorted
    except Exception as e:
        LOGGER.error(e)
        await asleep(0.8)
        attempt += 1
        return await short_url(longurl, alias, attempt)
