from contextlib import suppress
from re import IGNORECASE, findall, search
import logging  # Added logging

from imdb import Cinemagoer, IMDbDataAccessError  # Added IMDbDataAccessError
from pycountry import countries as conn
from pyrogram.errors import MediaEmpty, PhotoInvalidDimensions, WebpageMediaEmpty

from ..core.tg_client import TgClient
from ..core.config_manager import Config
from ..helper.ext_utils.status_utils import get_readable_time
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.message_utils import (
    send_message,
    edit_message,
    delete_message,
)

imdb = Cinemagoer()

IMDB_GENRE_EMOJI = {
    "Action": "🚀",
    "Adult": "🔞",
    "Adventure": "🌋",
    "Animation": "🎠",
    "Biography": "📜",
    "Comedy": "🪗",
    "Crime": "🔪",
    "Documentary": "🎞",
    "Drama": "🎭",
    "Family": "👨‍👩‍👧‍👦",
    "Fantasy": "🫧",
    "Film Noir": "🎯",
    "Game Show": "🎮",
    "History": "🏛",
    "Horror": "🧟",
    "Musical": "🎻",
    "Music": "🎸",
    "Mystery": "🧳",
    "News": "📰",
    "Reality-TV": "🖥",
    "Romance": "🥰",
    "Sci-Fi": "🌠",
    "Short": "📝",
    "Sport": "⛳",
    "Talk-Show": "👨‍🍳",
    "Thriller": "🗡",
    "War": "⚔",
    "Western": "🪩",
}
LIST_ITEMS = 4

# Initialize logger for this module
LOGGER = logging.getLogger(__name__)


async def imdb_search(_, message):
    if " " in message.text:
        k = await send_message(message, "<i>Searching IMDB ...</i>")
        title = message.text.split(" ", 1)[1]
        user_id = message.from_user.id
        buttons = ButtonMaker()
        if result := search(r"imdb\.com/title/tt(\d+)", title, IGNORECASE):
            movieid = result.group(1)
            try:
                movie = imdb.get_movie(movieid)
                if movie:
                    buttons.data_button(
                        f"🎬 {movie.get('title')} ({movie.get('year')})",
                        f"imdb {user_id} movie {movieid}",
                    )
                else:
                    return await edit_message(
                        k, "<i>No Results Found (direct ID search failed)</i>"
                    )
            except IMDbDataAccessError as e:
                LOGGER.warning(
                    f"IMDbDataAccessError during imdb_search (get_movie by ID {movieid}): {e}"
                )
                return await edit_message(
                    k, "<i>IMDb service error. Please try again later.</i>"
                )
            except Exception as e:
                LOGGER.error(
                    f"Unexpected error during imdb_search (get_movie by ID {movieid}): {e}",
                    exc_info=True,
                )
                return await edit_message(k, "<i>An unexpected error occurred.</i>")
        else:
            movies = get_poster(
                title, bulk=True
            )  # This now handles IMDbDataAccessError
            if not movies:  # movies will be None if search_movie failed or no results
                return await edit_message(
                    k,
                    "<i>No Results Found or IMDb service error. Try Again or Use <b>Title ID</b></i>",
                    k,
                )
            for movie_obj in (
                movies
            ):  # Renamed to avoid conflict with 'movie' from outer scope if any
                buttons.data_button(
                    f"🎬 {movie_obj.get('title')} ({movie_obj.get('year')})",  # Assuming movie_obj is a movie object from imdbpy
                    f"imdb {user_id} movie {movie_obj.movieID}",
                )
        buttons.data_button("🚫 Close 🚫", f"imdb {user_id} close")
        await edit_message(
            k, "<b><i>Search Results found on IMDb.com</i></b>", buttons.build_menu(1)
        )
    else:
        await send_message(
            message,
            "<i>Send Movie / TV Series Name along with /imdb Command or send IMDB URL</i>",
        )


def get_poster(query, bulk=False, id=False, file=None):
    movie_object = None  # Initialize movie_object to None
    if not id:
        query = (query.strip()).lower()
        title = query
        year = findall(r"[1-2]\d{3}$", query, IGNORECASE)
        if year:
            year = list_to_str(year[:1])
            title = (query.replace(year, "")).strip()
        elif file is not None:
            year = findall(r"[1-2]\d{3}", file, IGNORECASE)
            if year:
                year = list_to_str(year[:1])
        else:
            year = None

        try:
            movie_results = imdb.search_movie(title.lower(), results=10)
        except IMDbDataAccessError as e:
            LOGGER.warning(
                f"IMDbDataAccessError during search_movie for '{title}': {e}"
            )
            return None
        except Exception as e:
            LOGGER.error(
                f"Unexpected error during search_movie for '{title}': {e}",
                exc_info=True,
            )
            return None

        if not movie_results:
            return None
        if year:
            filtered = (
                list(filter(lambda k: str(k.get("year")) == str(year), movie_results))
                or movie_results
            )
        else:
            filtered = movie_results

        # Further filter for kind 'movie' or 'tv series'
        kind_filtered_results = [
            m for m in filtered if m.get("kind") in ["movie", "tv series"]
        ]

        if (
            not kind_filtered_results
        ):  # If no movies or tv series, fallback to any kind from filtered
            kind_filtered_results = filtered

        if not kind_filtered_results:  # If still no results (e.g. original movie_results was empty after filtering)
            return None

        if bulk:
            # For bulk, we want to return a list of movie objects, not just IDs.
            # We need to fetch each movie. This could be slow and error-prone.
            # Consider if bulk should return raw search results or full movie objects.
            # For now, returning raw search results (which are already movie objects from search_movie)
            return kind_filtered_results

        movieid = kind_filtered_results[0].movieID
    else:  # if id is True
        movieid = query  # query is the movieID

    try:
        movie_object = imdb.get_movie(movieid)
    except IMDbDataAccessError as e:
        LOGGER.warning(f"IMDbDataAccessError during get_movie for ID '{movieid}': {e}")
        # Return a dictionary with minimal default values if critical info is needed downstream
        # or None if downstream can handle it. For now, returning None.
        return None
    except Exception as e:
        LOGGER.error(
            f"Unexpected error during get_movie for ID '{movieid}': {e}", exc_info=True
        )
        return None

    if not movie_object:  # If get_movie returned None (e.g. due to error or invalid ID)
        return None

    # Proceed with movie_object if successfully fetched
    if movie_object.get("original air date"):
        date = movie_object["original air date"]
    elif movie_object.get("year"):
        date = movie_object.get("year")
    else:
        date = "N/A"
    plot = movie_object.get("plot")
    plot = plot[0] if plot and len(plot) > 0 else movie_object.get("plot outline")
    if plot and len(plot) > 300:
        plot = f"{plot[:300]}..."

    # Safely access rating, default to "N/A" if not present or not a string/number
    rating_value = movie_object.get("rating")
    rating_str = f"{rating_value} / 10" if rating_value else "N/A"

    return {
        "title": movie_object.get(
            "title", "N/A"
        ),  # Provide default for essential fields
        "trailer": movie_object.get("videos"),
        "votes": movie_object.get("votes"),
        "aka": list_to_str(movie_object.get("akas")),
        "seasons": movie_object.get("number of seasons"),
        "box_office": movie_object.get("box office"),
        "localized_title": movie_object.get("localized title"),
        "kind": movie_object.get("kind"),
        "imdb_id": f"tt{movie_object.get('imdbID')}"
        if movie_object.get("imdbID")
        else "N/A",
        "cast": list_to_str(movie_object.get("cast")),
        "runtime": list_to_str(
            [
                get_readable_time(int(run) * 60)
                for run in movie_object.get("runtimes", [])
                if run.isdigit()
            ]  # Ensure run is digit
        )
        or "N/A",  # Handle empty or non-digit runtimes
        "countries": list_to_hash(movie_object.get("countries"), True),
        "certificates": list_to_str(movie_object.get("certificates")),
        "languages": list_to_hash(movie_object.get("languages")),
        "director": list_to_str(movie_object.get("director")),
        "writer": list_to_str(movie_object.get("writer")),
        "producer": list_to_str(movie_object.get("producer")),
        "composer": list_to_str(movie_object.get("composer")),
        "cinematographer": list_to_str(movie_object.get("cinematographer")),
        "music_team": list_to_str(movie_object.get("music department")),
        "distributors": list_to_str(movie_object.get("distributors")),
        "release_date": date,
        "year": movie_object.get("year", "N/A"),  # Provide default
        "genres": list_to_hash(movie_object.get("genres"), emoji=True),
        "poster": movie_object.get("full-size cover url"),
        "plot": plot,
        "rating": rating_str,
        "url": f"https://www.imdb.com/title/tt{movieid}" if movieid else "N/A",
        "url_cast": f"https://www.imdb.com/title/tt{movieid}/fullcredits#cast"
        if movieid
        else "N/A",
        "url_releaseinfo": f"https://www.imdb.com/title/tt{movieid}/releaseinfo"
        if movieid
        else "N/A",
    }


def list_to_str(k):
    if not k:
        return ""
    elif len(k) == 1:
        return str(k[0])
    elif LIST_ITEMS:
        k = k[: int(LIST_ITEMS)]
        return " ".join(f"{elem}," for elem in k)[:-1] + " ..."
    else:
        return " ".join(f"{elem}," for elem in k)[:-1]


def list_to_hash(k, flagg=False, emoji=False):
    listing = ""
    if not k:
        return ""
    elif len(k) == 1:
        if not flagg:
            if emoji:
                return str(
                    IMDB_GENRE_EMOJI.get(k[0], "")
                    + " #"
                    + k[0].replace(" ", "_").replace("-", "_")
                )
            return str("#" + k[0].replace(" ", "_").replace("-", "_"))
        try:
            conflag = (conn.get(name=k[0])).flag
            return str(f"{conflag} #" + k[0].replace(" ", "_").replace("-", "_"))
        except AttributeError:
            return str("#" + k[0].replace(" ", "_").replace("-", "_"))
    elif LIST_ITEMS:
        k = k[: int(LIST_ITEMS)]
        for elem in k:
            ele = elem.replace(" ", "_").replace("-", "_")
            if flagg:
                with suppress(AttributeError):
                    conflag = (conn.get(name=elem)).flag
                    listing += f"{conflag} "
            if emoji:
                listing += f"{IMDB_GENRE_EMOJI.get(elem, '')} "
            listing += f"#{ele}, "
        return f"{listing[:-2]}"
    else:
        for elem in k:
            ele = elem.replace(" ", "_").replace("-", "_")
            if flagg:
                conflag = (conn.get(name=elem)).flag
                listing += f"{conflag} "
            listing += f"#{ele}, "
        return listing[:-2]


async def imdb_callback(_, query):
    message = query.message
    user_id = query.from_user.id
    data = query.data.split()
    if user_id != int(data[1]):
        await query.answer("Not Yours!", show_alert=True)
    elif data[2] == "movie":
        await query.answer()
        imdb = get_poster(query=data[3], id=True)
        buttons = ButtonMaker()
        if imdb["trailer"]:
            if isinstance(imdb["trailer"], list):
                buttons.url_button("▶️ IMDb Trailer ", imdb["trailer"][-1])
                imdb["trailer"] = list_to_str(imdb["trailer"])
            else:
                buttons.url_button("▶️ IMDb Trailer ", imdb["trailer"])
        buttons.data_button("🚫 Close 🚫", f"imdb {user_id} close")
        buttons = buttons.build_menu(1)
        template = ""
        # if int(data[1]) in user_data and user_data[int(data[1])].get('imdb_temp'):
        #    template = user_data[int(data[1])].get('imdb_temp')
        # if not template:
        template = Config.IMDB_TEMPLATE
        if imdb and template != "":
            cap = template.format(**imdb, **locals())
        else:
            cap = "No Results"
        if imdb.get("poster"):
            try:
                await TgClient.bot.send_photo(
                    chat_id=query.message.reply_to_message.chat.id,
                    caption=cap,
                    photo=imdb["poster"],
                    reply_to_message_id=query.message.reply_to_message.id,
                    reply_markup=buttons,
                )
            except (MediaEmpty, PhotoInvalidDimensions, WebpageMediaEmpty):
                poster = imdb.get("poster").replace(".jpg", "._V1_UX360.jpg")
                await send_message(message.reply_to_message, cap, buttons, photo=poster)
        else:
            await send_message(
                message.reply_to_message,
                cap,
                buttons,
                "https://telegra.ph/file/5af8d90a479b0d11df298.jpg",
            )
        await delete_message(message)
    else:
        await query.answer()
        await delete_message(message)
        await delete_message(message.reply_to_message)
