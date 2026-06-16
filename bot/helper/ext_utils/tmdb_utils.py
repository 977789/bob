import re
import aiohttp
from bot.core.config_manager import Config
from bot import LOGGER


def extract_tmdb_info_from_filename(name: str) -> tuple[str, str | None]:
    """
    Cleans a filename and extracts a potential title and year for TMDB search.
    Adapted from refer/bot/helper/ext_utils/tmdb_thumbnail.py.
    """
    original_name = name  # Store original name for later reference if needed
    year = None
    # Remove common release group tags, URLs, etc.
    name = re.sub(r"www\S+", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\[.*?\]", "", name)  # Remove content in square brackets
    name = re.sub(
        r"\(.*?\)", "", name
    )  # Remove content in parentheses (optional, could remove year)

    # Try to extract year first - common patterns like (2023), [2023], or just 2023
    year_match = re.search(r"\b((?:19|20)\d{2})\b", name)
    if year_match:
        year = year_match.group(1)
        # Remove the found year from the name to clean it up for title search
        name = name.replace(year_match.group(0), "", 1).strip()

    # Replace multiple consecutive dots, underscores, hyphens with spaces (preserve single ones)
    # Old aggressive: name = re.sub(r"[.\-_]+", " ", name)
    name = re.sub(
        r"[.\-_]{2,}", " ", name
    )  # Only replace 2 or more consecutive separators

    # Remove known series patterns like S01E01, Season 1 Episode 1, etc.
    series_patterns = [
        r"[Ss]\d{1,2}[Ee]\d{1,3}",  # S01E01
        r"[Ss]eason\s*\d{1,2}",  # Season 1 / Season 01
        r"[Ee]pisode\s*\d{1,3}",  # Episode 1 / Episode 001
        r"\b\d{1,2}x\d{1,3}\b",  # 1x01, 12x01
    ]
    for pattern in series_patterns:
        name = re.sub(pattern, "", name, flags=re.IGNORECASE)

    # Remove common quality tags and other noise
    noise_patterns = [
        r"\b(480p|720p|1080p|2160p|4k|UHD)\b",
        r"\b(WEB-DL|WEBDL|WEB DL|WEB-RIP|WEBRIP|WEB)\b",
        r"\b(BluRay|Blu-Ray|BRRip|BDRip|HDDVD|DVD)\b",
        r"\b(HDTV|HDRip|DVDRip|TVRip)\b",
        r"\b(x264|x265|h264|h265|HEVC|XviD|DivX)\b",
        r"\b(AAC|AC3|EAC3|DTS|TrueHD|Atmos|MP3|FLAC|Opus)\b",
        r"\b(Dual[- ]Audio|Multi[- ]Audio|Hindi|English|Tamil|Telugu|JAP|ENG|SUB|SUBS|ESub|Subbed)\b",  # Language & Subtitle
        r"\b(UNCUT|REMASTERED|EXTENDED|PROPER|REPACK|LIMITED|COMPLETE|SPECIAL EDITION)\b",  # Edition tags
        r"\b(RARBG|PSA|MkvCage|GalaxyRG|TGx|Pahe|YTS.MX|ETRG|EVO|HDChina|JoyBell)\b",  # Release groups
        r"\b(BDRip|HDTVRip|DVDRip)\b",  # More rip types
        r"\b(Part\s*\d{1,2})\b",  # Part numbers
        r"\[.*?\]",  # Content in square brackets (already there but ensure it's comprehensive)
        r"\(.*?\)",  # Content in parentheses (already there, careful with years)
        r"\b(mkv|mp4|avi|mov|flv|wmv|webm)\b",  # Common video extensions as whole words
        r"\.\w{2,4}$",  # Remove file extension like .mkv, .mp4 (dot prefixed)
    ]
    for pattern in noise_patterns:
        name = re.sub(pattern, "", name, flags=re.IGNORECASE)

    # After removing season/episode patterns and noise, the remaining part should be the title.
    # Clean up multiple spaces and leading/trailing spaces that might result from substitutions.
    name = re.sub(r"\s+", " ", name).strip()

    # If year was removed by parenthesis cleaning, re-check if it was part of original name
    if not year:
        year_match_final = re.search(
            r"\b((?:19|20)\d{2})\b", original_name
        )  # Search in original_name
        if year_match_final:
            year = year_match_final.group(1)

    # One last pass to remove any stray multiple separators if name is not empty
    if name:
        # Fix: Only replace multiple consecutive separators, preserve single ones
        # Old aggressive: name = re.sub(r"[._-]+", " ", name).strip()
        name = re.sub(
            r"[._-]{2,}", " ", name
        ).strip()  # Only replace 2 or more consecutive separators

    # If the name is just S or E or similar noise after cleaning, consider it untitled
    if not name or name.lower() in ["s", "e", "ep"]:
        return "Untitled", year

    return name, year


async def fetch_tmdb_data(
    title: str,
    year: str = None,
    session: aiohttp.ClientSession = None,
    image_type: str = "poster",
) -> dict | None:
    """
    Fetches movie/TV show data from TMDB using aiohttp.

    Args:
        title: The title to search for.
        year: Optional year to refine the search.
        session: Optional aiohttp.ClientSession. A new one is created if not provided.
        image_type: Type of image to fetch ('poster' or 'backdrop'). Defaults to 'poster'.

    Returns:
        A dictionary with TMDB data:
        {'title': str, 'year': str, 'image_url': str | None, 'id': int, 'type': 'movie'/'tv', 'image_type_fetched': str}
        or None if not found or an error occurs.
    """
    if not Config.TMDB_API_KEY:
        LOGGER.error("TMDB_API_KEY is not configured.")
        return None

    cleaned_title, extracted_year_from_title = extract_tmdb_info_from_filename(title)
    search_year = year or extracted_year_from_title  # Prioritize explicitly passed year

    api_url = "https://api.themoviedb.org/3/search/multi"
    params = {
        "api_key": Config.TMDB_API_KEY,
        "query": cleaned_title,
        "language": "en-US",  # Request English results for consistency
        "include_adult": "false",
    }
    # TMDB API for /search/multi doesn't directly take 'year' as a top-level param for movies in the same way it does for /discover.
    # It takes 'primary_release_year' for movies or 'first_air_date_year' for TV shows in their respective search endpoints.
    # For /search/multi, we filter by year from the results.
    # If a year is provided, we can add it to the query for better textual matching, though TMDB's behavior varies.
    # if search_year:
    #    params["query"] = f"{cleaned_title} {search_year}" # Appending year to query sometimes helps

    internal_session = False
    if session is None:
        session = aiohttp.ClientSession()
        internal_session = True

    try:
        async with session.get(
            api_url, params=params, ssl=False
        ) as resp:  # ssl=False as in refer/
            if resp.status != 200:
                LOGGER.error(
                    f"TMDB API error: Status {resp.status} for title '{cleaned_title}'"
                )
                return None

            data = await resp.json()
            results = data.get("results", [])

            if not results:
                LOGGER.info(
                    f"TMDB: No results found for '{cleaned_title}' (Year: {search_year or 'Any'})"
                )
                return None

            best_match = None

            # Filter and sort results:
            # 1. Prioritize exact year match (if year is provided)
            # 2. Prioritize movies over TV shows if multiple types match, or vice-versa based on typical content if discernible
            # 3. Popularity can be a secondary sorting factor

            potential_matches = []
            for res in results:
                res_title = None
                res_year_str = None
                res_id = res.get("id")
                media_type = res.get("media_type")

                if (
                    media_type not in ["movie", "tv"] or not res_id
                ):  # Ensure it's a movie or TV and has an ID
                    continue

                res_title_original = (
                    res.get("title") if media_type == "movie" else res.get("name")
                )

                # Determine path key based on requested image_type
                path_key = (
                    "backdrop_path" if image_type == "backdrop" else "poster_path"
                )
                res_image_path = res.get(path_key)
                actual_image_type_fetched = (
                    image_type  # Assume we get what we asked for initially
                )

                # If primary image type is not found, try to fallback to the other type
                if not res_image_path:
                    fallback_path_key = (
                        "poster_path" if image_type == "backdrop" else "backdrop_path"
                    )
                    res_image_path = res.get(fallback_path_key)
                    if res_image_path:  # Only update if fallback was successful
                        actual_image_type_fetched = fallback_path_key.split("_")[0]
                    # If both are None, res_image_path will remain None

                res_year_str = None
                if media_type == "movie":
                    # res_title = res.get("title") # Already got as res_title_original
                    if res.get("release_date") and len(res["release_date"]) >= 4:
                        res_year_str = res["release_date"][:4]
                elif media_type == "tv":
                    res_title = res.get("name")
                    if res.get("first_air_date") and len(res["first_air_date"]) >= 4:
                        res_year_str = res["first_air_date"][:4]
                else:  # Skip persons, etc.
                    continue

                if not res_title or not res_id:  # Basic check for usable data
                    continue

                match_score = 0
                # Score based on year match
                if search_year and res_year_str == search_year:
                    match_score += 10  # Strong preference for year match

                # Score based on title similarity (simple check, can be improved)
                # For now, we assume TMDB's relevance sorting is decent for the query.
                # A more advanced similarity check (e.g., Levenshtein distance) could be added.

                # Store potential match with its score
                potential_matches.append(
                    {
                        "data": res,
                        "title": res_title_original,  # Use the fetched title
                        "year": res_year_str,
                        "id": res_id,
                        "image_path": res_image_path,  # Store the fetched image path (poster or backdrop)
                        "type": media_type,
                        "image_type_fetched": actual_image_type_fetched,  # Store which type was actually found
                        "score": match_score,
                        "popularity": res.get(
                            "popularity", 0
                        ),  # Already used in previous version, ensure it's here
                    }
                )

            if not potential_matches:
                LOGGER.info(
                    f"TMDB: No suitable movie/TV results after filtering for '{cleaned_title}' (Year: {search_year})"
                )
                return None

            potential_matches.sort(
                key=lambda x: (x["score"], x["popularity"]), reverse=True
            )
            best_match = potential_matches[0]

            final_image_url = None
            if best_match.get("image_path"):
                # Use w780 for backdrops, w500 for posters for better quality/aspect ratio
                image_size = (
                    "w780" if best_match["image_type_fetched"] == "backdrop" else "w500"
                )
                final_image_url = (
                    f"https://image.tmdb.org/t/p/{image_size}{best_match['image_path']}"
                )

            LOGGER.info(
                f"TMDB: Best match for '{cleaned_title}' (Year: {search_year}): {best_match['title']} ({best_match['year'] or 'N/A'}), Type: {best_match['type']}, Image: {best_match['image_type_fetched']}"
            )
            return {
                "title": best_match["title"],
                "year": best_match["year"],
                "image_url": final_image_url,
                "id": best_match["id"],
                "type": best_match["type"],
                "image_type_fetched": best_match["image_type_fetched"],
            }

    except aiohttp.ClientError as e:
        LOGGER.error(f"TMDB network error for title '{cleaned_title}': {e}")
        return None
    except Exception as e:
        LOGGER.error(
            f"Error processing TMDB data for title '{cleaned_title}': {e}",
            exc_info=True,
        )
        return None
    finally:
        if internal_session and session:
            await session.close()


# Example usage:
async def main_test():
    # Ensure Config.TMDB_API_KEY is set for testing, e.g., from environment variable
    import os

    if not Config.TMDB_API_KEY:
        Config.TMDB_API_KEY = os.environ.get(
            "TMDB_API_KEY_ENV_VAR"
        )  # Replace with your env var name

    if not Config.TMDB_API_KEY:
        print("Please set TMDB_API_KEY_ENV_VAR environment variable for testing.")
        return

    test_cases = [
        ("The Matrix", "1999"),
        ("Pulp Fiction"),
        ("Breaking Bad", "2008"),
        ("NonExistentXYZ123", "2025"),
        ("Fight Club 1999"),  # Year in title
        ("The.Dark.Knight.2008.1080p.BluRay"),
        ("Friends S01E01"),
    ]

    async with aiohttp.ClientSession() as http_session:
        for case in test_cases:
            title_to_test = case[0]
            year_to_test = case[1] if len(case) > 1 else None

            # Test filename cleaning
            cleaned_name, auto_extracted_year = extract_tmdb_info_from_filename(
                title_to_test
            )
            print(f"\nOriginal: '{title_to_test}'")
            print(
                f"Cleaned Name for Search: '{cleaned_name}', Auto-extracted Year: {auto_extracted_year}"
            )

            # Test TMDB data fetching (using the explicitly passed year if available, else auto_extracted_year)
            effective_year_for_search = year_to_test or auto_extracted_year
            print(
                f"Fetching TMDB data for: '{cleaned_name}', Explicit Year: {effective_year_for_search if effective_year_for_search else 'Any'}"
            )

            data = await fetch_tmdb_data(
                cleaned_name, effective_year_for_search, session=http_session
            )  # Pass cleaned name
            if data:
                print(f"  TMDB Title: {data['title']}")
                print(f"  TMDB Year: {data['year']}")
                print(f"  TMDB Type: {data['type']}")
                print(f"  TMDB ID: {data['id']}")
                print(f"  Poster URL: {data['poster_url']}")
            else:
                print("  No TMDB data found or error.")


if __name__ == "__main__":
    # asyncio.run(main_test()) # This is how you would run it
    pass
