# bot/helper/mhunt_utils/filename_processor.py
import os.path as ospath
import re
import urllib.parse

from bot import LOGGER
from bot.core.config_manager import Config
from bot.helper.ext_utils.media_utils import get_media_info
from bot.helper.ext_utils.bot_utils import sync_to_async
from bot.modules.imdb import get_poster

# Import for TMDB: extract_tmdb_info_from_filename is aliased to avoid conflict with local function
from bot.helper.ext_utils.tmdb_utils import (
    fetch_tmdb_data,
)
from aiofiles.os import rename as aiorename, path as aiopath


class SafeDict(dict):
    def __missing__(self, key):
        return ""


def extract_media_info_from_filename(
    filename: str,
) -> tuple:  # This is the original extensive one from filename_processor
    processed_filename = urllib.parse.unquote(filename)
    processed_filename = re.sub(r"www\S+", "", processed_filename)
    # Fix: Only replace multiple consecutive separators, preserve single dots and spaces
    # Old: processed_filename = re.sub(r"[\._\-]+", " ", processed_filename)
    processed_filename = re.sub(
        r"[\._\-]{2,}", " ", processed_filename
    )  # Only replace 2 or more consecutive separators
    processed_filename = re.sub(r"\[.*?\]", "", processed_filename)
    processed_filename = re.sub(r"\s+", " ", processed_filename).strip()
    processed_filename = re.sub(r"^[@/\\]\w+\s*", "", processed_filename)
    translations = {
        "Эпизод": "E",
        "エピソード": "E",
        "Saison": "Season",
        "Volumen": "Vol",
        "Часть": "Part",
    }
    for key, val in translations.items():
        processed_filename = processed_filename.replace(key, val)
    name, year, season, episode, part, volume = "", None, None, None, None, None
    series_patterns = [
        re.compile(
            r"^(?P<name>.*?)\s*[._-]?\s*(?:S|Season)\s*(?P<season>\d{1,2})\s*[._-]?\s*(?:E|Episode)\s*(?P<episode>\d{1,3})",
            re.IGNORECASE,
        ),
        re.compile(
            r"^(?P<name>.*?)\s*[._-]?\s*(?P<season>\d{1,2})\s*x\s*(?P<episode>\d{1,3})",
            re.IGNORECASE,
        ),
        # New: SxxExx or Sxx EPxx appearing anywhere (tolerant to spaces and separators)
        re.compile(
            r"^(?P<name>.*?)\s*(?:S|Season)\s*(?P<season>\d{1,2})\s*(?:E|EP|Episode)\s*(?P<episode>\d{1,3})",
            re.IGNORECASE,
        ),
        # New: Sxx ... <non-digits> ... <episode>
        re.compile(
            r"^(?P<name>.*?)\s*S(?P<season>\d{1,2})[^\d]*(?P<episode>\d{1,3})",
            re.IGNORECASE,
        ),
        # New: Match formats like "Title - 019" (episode only)
        re.compile(
            r"^(?P<name>.*?)\s*[-–—]\s*(?P<episode>\d{1,3})(?!\d)",
            re.IGNORECASE,
        ),
        # New: Match formats like "Title E019" or "Title Episode 019" (episode only)
        re.compile(
            r"^(?P<name>.*?)\s*[._-]?\s*(?:E|EP|Episode)\s*(?P<episode>\d{1,3})",
            re.IGNORECASE,
        ),
        # Bracket-wrapped episode like [019 - Something]
        re.compile(
            r"\[(?P<episode>\d{1,3})\s*-\s*.*?\]",
            re.IGNORECASE,
        ),
        # Bracket-starting with episode like [019 ...]
        re.compile(
            r"\[(?P<episode>\d{1,3})\s*",
            re.IGNORECASE,
        ),
        # Word 'episode 019'
        re.compile(
            r"episode\s+(?P<episode>\d{1,3})",
            re.IGNORECASE,
        ),
        # Decimal episodes: E1.5, EP1.25
        re.compile(
            r"(?:E|EP)\s*(?P<episode>\d\.\d{1,2})",
            re.IGNORECASE,
        ),
        # Loose decimal like 1.5 (last resort, avoid if other matches found)
        re.compile(
            r"(?<!\d)(?P<episode>\d\.\d{1,2})(?!\d)",
            re.IGNORECASE,
        ),
        # Generic number fallback (last resort)
        re.compile(r"(?<!\d)(?P<episode>\d{1,3})(?!\d)", re.IGNORECASE),
    ]
    for pattern in series_patterns:
        match = pattern.search(processed_filename)
        if match:
            if "name" in match.groupdict():
                name = match.group("name").strip()
            season = match.group("season") if "season" in match.groupdict() else season
            episode = match.group("episode")
            break
    year_match = re.search(r"\b(?P<year>(19|20)\d{2})\b", processed_filename)
    if year_match:
        year = year_match.group("year")
    if not name:
        name = ospath.splitext(processed_filename)[0]
    tags_to_remove = (
        r"\b(480p|720p|1080p|2160p|4K|UHD|WEB-DL|WEBDL|WEB DL|BluRay|BRRip|BDRip|HDTV|HDRip|DVDRip|UNCUT|"
        r"WEB|DLMUX|REMUX|ENCODED|NF|AMZN|DSNP|HMAX|HBO|HULU|Rakuten|iTunes|ZEE5|VOOT|ALTBalaji|SonyLIV|"
        r"x264|x265|h264|h265|HEVC|AAC|AC3|EAC3|DTS|TrueHD|Atmos|Opus|FLAC|MP3|Vorbis|"
        r"Hindi|English|Tamil|Telugu|Malayalam|Kannada|Multi Audio|Dual Audio|Triple Audio|Quad Audio|"
        r"ESub|ESubs|Subtitles|Subs|Hardsub|Softsub|Chapters|RARBG|TGx|PSA|Pahe|MkvCage|GalaxyRG|"
        r"Sample|Trailer|REPACK|PROPER|LIMITED|COMPLETE|EXTENDED|UNRATED|REMASTERED|CRITERION|"
        r"EP\s*\d+|EP\d+|S\d{1,2}|E\d{1,3}"
        r")\b"
    )
    if name:
        if year:
            name = re.sub(r"\b" + re.escape(year) + r"\b", "", name)
        name = re.sub(tags_to_remove, "", name, flags=re.IGNORECASE).strip()
        name = re.sub(r"\s{2,}", " ", name).strip()
        name = re.sub(r"[\s._-]+$", "", name).strip()
    if not name:
        name = "Untitled"
    return name, season, episode, year, part, volume


def clean_filename_for_search(filename: str) -> str:
    name_from_extract, _, _, year_from_extract, _, _ = extract_media_info_from_filename(
        filename
    )
    if name_from_extract and year_from_extract:
        if str(year_from_extract) in name_from_extract:
            result = name_from_extract
        else:
            result = f"{name_from_extract} {year_from_extract}"
    elif name_from_extract:
        result = name_from_extract
    else:
        name_part = ospath.splitext(filename)[0]
        name_part = re.sub(r"[\[\](){}⟨⟩【】『』“”‘’«»‹›❮❯❰❱❲❳❴❵]", " ", name_part)
        name_part = re.sub(r"\s+", " ", name_part).strip()
        result = name_part if name_part else "Unknown"
    return result


async def process_filename_for_upload(
    listener, current_basename: str, current_full_path: str
) -> tuple[str, str]:
    user_dict = listener.user_dict
    final_cloud_name = current_basename
    final_disk_path = current_full_path
    dirpath = ospath.dirname(current_full_path)
    is_file = await aiopath.isfile(current_full_path)

    # If this is a directory, also process all files within it (non-recursively to avoid conflicts)
    if not is_file and await aiopath.isdir(current_full_path):
        try:
            import os

            # Process files in all subdirectories but don't recursively call process_filename_for_upload on directories
            for root, dirs, files in await sync_to_async(os.walk, current_full_path):
                for file in files:
                    file_path = ospath.join(root, file)
                    if not await aiopath.exists(file_path):
                        continue

                    # Apply prefix/suffix/REMNAME/NAME_SWAP/trailing junk removal to individual files
                    try:
                        upload_prefix = user_dict.get("LEECH_PREFIX", "")
                        upload_suffix = user_dict.get("LEECH_SUFFIX", "")
                        command_prefix = getattr(listener, "name_prefix", "") or ""
                        command_suffix = getattr(listener, "name_suffix", "") or ""

                        name_part, ext_part = ospath.splitext(file)
                        original_name_part = name_part

                        # Apply prefix - command line prefix takes precedence
                        effective_prefix = command_prefix or upload_prefix
                        if effective_prefix and not name_part.startswith(
                            f"{effective_prefix} "
                        ):
                            name_part = f"{effective_prefix} {name_part}"

                        # Apply suffixes
                        if upload_suffix and not name_part.endswith(upload_suffix):
                            name_part = f"{name_part}{upload_suffix}"
                        if command_suffix and not name_part.endswith(command_suffix):
                            name_part = f"{name_part}{command_suffix}"

                        # Apply REMNAME patterns
                        remname_patterns = user_dict.get("REMNAME", "")
                        if remname_patterns:
                            try:
                                # Auto-detect if pattern is regex or needs splitting
                                # Check if the entire pattern contains regex metacharacters
                                def is_likely_regex(pattern_str):
                                    """Detect if pattern contains regex metacharacters"""
                                    return bool(
                                        re.search(
                                            r"\\[a-zA-Z]", pattern_str
                                        )  # \S, \d, \w, etc.
                                        or ".*" in pattern_str
                                        or ".+" in pattern_str
                                        or re.search(
                                            r"\[.+\]", pattern_str
                                        )  # Character classes
                                        or re.search(
                                            r"\{\d+,?\d*\}", pattern_str
                                        )  # Quantifiers
                                    )

                                # If pattern starts with "regex:", use it as-is
                                if remname_patterns.startswith("regex:"):
                                    remname_regex = re.compile(
                                        remname_patterns[6:], re.IGNORECASE
                                    )
                                # If pattern looks like a regex, use it as-is
                                elif is_likely_regex(remname_patterns):
                                    remname_regex = re.compile(
                                        remname_patterns, re.IGNORECASE
                                    )
                                else:
                                    # Split and escape individual literal patterns
                                    parts = [
                                        p.strip()
                                        for p in remname_patterns.split("|")
                                        if p.strip()
                                    ]
                                    if parts:
                                        processed_parts = [
                                            re.escape(part) for part in parts
                                        ]
                                        remname_regex = re.compile(
                                            "|".join(processed_parts), re.IGNORECASE
                                        )
                                    else:
                                        remname_regex = None

                                if remname_regex:
                                    name_part = remname_regex.sub("", name_part).strip()
                                    # Cleanup artifacts
                                    name_part = re.sub(
                                        r"\[\s*\]|\(\s*\)|\{\s*\}", "", name_part
                                    )
                                    name_part = re.sub(r"^[\s\-_\.]+", "", name_part)
                                    name_part = re.sub(r"\s-\s*\.", " - ", name_part)
                                    name_part = re.sub(r"\.{2,}", ".", name_part)
                                    name_part = re.sub(
                                        r"\s{2,}", " ", name_part
                                    ).strip()
                            except Exception as e:
                                LOGGER.error(
                                    f"[FilenameProcessor] REMNAME error for {file}: {e}"
                                )

                        # Apply NAME_SWAP rules
                        name_swap_rules = getattr(listener, "name_swap", None)
                        if name_swap_rules:
                            for swap_item in name_swap_rules:
                                if not isinstance(swap_item, (list, tuple)):
                                    continue
                                pattern, replacement, cnt_str, flag_str = (
                                    list(swap_item) + ["", "0", "NOFLAG"]
                                )[:4]

                                is_simple_removal = len(swap_item) == 1 or (
                                    len(swap_item) == 2 and swap_item[1] == ""
                                )

                                if is_simple_removal:
                                    pattern = re.escape(pattern)
                                    if flag_str in ("NOFLAG", "0", ""):
                                        flag_str = "IGNORECASE"

                                try:
                                    count_val = (
                                        int(cnt_str) if str(cnt_str).isdigit() else 0
                                    )
                                except Exception:
                                    count_val = 0

                                regex_flags = getattr(re, str(flag_str).upper(), 0)
                                try:
                                    name_part = re.sub(
                                        pattern,
                                        str(replacement or ""),
                                        name_part,
                                        count_val,
                                        flags=regex_flags,
                                    )
                                except Exception as e_swap:
                                    LOGGER.error(
                                        f"[FilenameProcessor] NameSub error for {file} pattern '{pattern}': {e_swap}"
                                    )

                        # Remove trailing junk (intro, merged, sample, remove, reorder, convert, extract)
                        trailing_pattern = r"([\s._-]*(?:intro|sample|merged|remove|reorder|convert|extract))+\s*$"
                        name_part = re.sub(
                            trailing_pattern, "", name_part, flags=re.IGNORECASE
                        ).strip()

                        # Only rename if name changed and is valid
                        if name_part and name_part != original_name_part:
                            new_file_name = f"{name_part}{ext_part}"
                            new_file_path = ospath.join(root, new_file_name)

                            if (
                                new_file_name != file
                                and await aiopath.exists(file_path)
                                and not await aiopath.exists(new_file_path)
                            ):
                                await aiorename(file_path, new_file_path)
                                LOGGER.info(
                                    f"[FilenameProcessor] Renamed file in directory: {file} -> {new_file_name}"
                                )

                    except Exception as e:
                        LOGGER.error(
                            f"[FilenameProcessor] Error processing file {file}: {e}"
                        )
        except Exception as e:
            LOGGER.error(
                f"[FilenameProcessor] Error processing directory {current_full_path}: {e}"
            )

    if not is_file:
        # Apply prefix/suffix and REMNAME to folder cloud name only (no disk rename)
        upload_prefix = user_dict.get("LEECH_PREFIX", "")
        upload_suffix = user_dict.get("LEECH_SUFFIX", "")

        # Also consider command line prefix/suffix arguments
        command_prefix = getattr(listener, "name_prefix", "") or ""
        command_suffix = getattr(listener, "name_suffix", "") or ""

        name_part_for_ps, ext_part_for_ps = ospath.splitext(final_cloud_name)

        # Apply prefix - command line prefix takes precedence over user setting
        effective_prefix = command_prefix or upload_prefix
        if effective_prefix:
            # Avoid duplicating prefix if already present
            if not name_part_for_ps.startswith(f"{effective_prefix} "):
                name_part_for_ps = f"{effective_prefix} {name_part_for_ps}"

        # Apply suffixes - both user setting and command line suffixes
        if upload_suffix and not name_part_for_ps.endswith(upload_suffix):
            name_part_for_ps = f"{name_part_for_ps}{upload_suffix}"
        if command_suffix and not name_part_for_ps.endswith(command_suffix):
            name_part_for_ps = f"{name_part_for_ps}{command_suffix}"

        new_name_after_ps = f"{name_part_for_ps}{ext_part_for_ps}"

        final_cloud_name = new_name_after_ps

        remname_patterns = user_dict.get("REMNAME", "")
        if remname_patterns:
            try:
                parts = [p.strip() for p in remname_patterns.split("|") if p.strip()]
                if parts:
                    # Process each pattern to determine if it's literal or regex
                    processed_parts = []
                    for part in parts:
                        if part.startswith("regex:"):
                            # Remove the prefix and use raw regex
                            pattern = part[6:]  # Remove 'regex:' prefix
                            processed_parts.append(pattern)
                        else:
                            # Literal string - escape regex special characters
                            processed_parts.append(re.escape(part))

                    remname_regex = re.compile("|".join(processed_parts), re.IGNORECASE)
                    name_part_for_remname, ext_part_for_remname = ospath.splitext(
                        final_cloud_name
                    )
                    processed_name_part_for_remname = remname_regex.sub(
                        "", name_part_for_remname
                    ).strip()
                    # Cleanup artifacts like empty bracket pairs left after REMNAME removal
                    processed_name_part_for_remname = re.sub(
                        r"\[\s*\]|\(\s*\)|\{\s*\}",
                        "",
                        processed_name_part_for_remname,
                    )
                    # Remove leading separators or dots left after removal
                    processed_name_part_for_remname = re.sub(
                        r"^[\s\-_\.]+",
                        "",
                        processed_name_part_for_remname,
                    )
                    # Fix ' - .Name' -> ' - Name'
                    processed_name_part_for_remname = re.sub(
                        r"\s-\s*\.",
                        " - ",
                        processed_name_part_for_remname,
                    )
                    # Collapse duplicate dots
                    processed_name_part_for_remname = re.sub(
                        r"\.{2,}", ".", processed_name_part_for_remname
                    )
                    # Normalize repeated whitespace
                    processed_name_part_for_remname = re.sub(
                        r"\s{2,}", " ", processed_name_part_for_remname
                    ).strip()
                    if processed_name_part_for_remname:
                        final_cloud_name = (
                            f"{processed_name_part_for_remname}{ext_part_for_remname}"
                        )
            except Exception as e:
                LOGGER.error(
                    f"[FilenameProcessor] Error applying REMNAME on folder name: {e}. Current name: '{final_cloud_name}'"
                )

        # Truncate overly long folder names
        if len(final_cloud_name) > 1000:
            name_part, ext_part = ospath.splitext(final_cloud_name)
            max_name_len = max(1, 1000 - len(ext_part))
            final_cloud_name = f"{name_part[:max_name_len]}{ext_part}"

        return final_cloud_name, final_disk_path

    if user_dict.get("AUTO_RENAME", False):
        # Default to 'auto' to match UI and user expectations
        auto_rename_type = user_dict.get("AUTO_RENAME_TYPE", "auto").lower()
        default_template = "{title} S{season}E{episode} {quality} [{year}]"
        template = user_dict.get(
            "RENAME_TEMPLATE",
            Config.RENAME_TEMPLATE
            if hasattr(Config, "RENAME_TEMPLATE") and Config.RENAME_TEMPLATE
            else default_template,
        )
        # Allow users who copied examples with double braces like {{episode}}
        try:
            template = re.sub(r"\{\{(\w+)\}\}", r"{\1}", str(template))
        except Exception:
            # Best-effort: keep template as-is if regex fails for some reason
            pass

        _, quality, media_lang, _ = await get_media_info(current_full_path, True)
        # Fallback to filename-based quality detection if media info is unavailable
        if not quality or not str(quality).lower().endswith("p"):
            try:
                qmatch = re.search(
                    r"\b(4320p|2160p|1440p|1080p|720p|540p|480p|360p|240p|8k|4k|\d{3,4}\s*p)\b",
                    current_basename,
                    flags=re.IGNORECASE,
                )
                if qmatch:
                    qval = qmatch.group(1).lower().replace(" ", "")
                    if qval == "4k":
                        quality = "2160p"
                    elif qval == "8k":
                        quality = "4320p"
                    else:
                        quality = qval if qval.endswith("p") else f"{qval}p"
            except Exception:
                pass
        ext_name, ext_season, ext_episode, ext_year, ext_part, ext_volume = (
            extract_media_info_from_filename(current_basename)
        )

        season_num = 1
        episode_num = 1
        if auto_rename_type == "auto":
            if ext_season and ext_season.isdigit():
                season_num = int(ext_season)
            if ext_episode and ext_episode.isdigit():
                episode_num = int(ext_episode)
        else:  # manual
            season_num = user_dict.get("START_SEASON", 1)
            episode_num = user_dict.get("_CURRENT_EPISODE", 1)

        final_title = ext_name or "Untitled"
        # ext_year is a string 'None', a year string e.g. "2023", or None (object)

        current_year_for_template = "YYYY"  # Default for template
        # Use ext_year for template if it's a valid year string
        if isinstance(ext_year, str) and ext_year.isdigit():
            current_year_for_template = ext_year

        # Check user setting for AUTO_THUMBNAIL (which implies auto metadata fetching for rename)
        auto_metadata_enabled = user_dict.get(
            "AUTO_THUMBNAIL", False
        )  # Default to False if not set
        tmdb_info_found = False

        if auto_metadata_enabled:
            if Config.TMDB_API_KEY:
                title_for_tmdb_search = ext_name
                year_for_tmdb_search = (
                    ext_year
                    if isinstance(ext_year, str) and ext_year.isdigit()
                    else None
                )

                LOGGER.info(
                    f"[FilenameProcessor] AUTO_THUMBNAIL enabled. Attempting TMDB lookup for Title: '{title_for_tmdb_search}', Year: {year_for_tmdb_search}"
                )
                try:
                    # Using fetch_tmdb_data from tmdb_utils
                    tmdb_data = await fetch_tmdb_data(
                        title=title_for_tmdb_search, year=year_for_tmdb_search
                    )
                    if tmdb_data and tmdb_data.get("title") and tmdb_data.get("year"):
                        final_title = tmdb_data["title"]
                        current_year_for_template = tmdb_data["year"]
                        tmdb_info_found = True
                        LOGGER.info(
                            f"[FilenameProcessor] TMDB Success. Title: '{final_title}', Year: '{current_year_for_template}'"
                        )
                    else:
                        LOGGER.info(
                            f"[FilenameProcessor] TMDB lookup for '{title_for_tmdb_search}' (Year: {year_for_tmdb_search}) did not yield usable data."
                        )
                except Exception as e_tmdb:
                    LOGGER.error(
                        f"[FilenameProcessor] TMDB lookup error for '{title_for_tmdb_search}': {e_tmdb}",
                        exc_info=True,
                    )
            else:
                LOGGER.info(
                    "[FilenameProcessor] TMDB_API_KEY not configured. Skipping TMDB lookup."
                )

            if not tmdb_info_found:
                LOGGER.info(
                    f"[FilenameProcessor] TMDB not used or failed. Attempting IMDB lookup for '{ext_name}' (Year: {ext_year}) as AUTO_THUMBNAIL is enabled."
                )
                search_term_for_imdb = ext_name
                if isinstance(ext_year, str) and ext_year.isdigit():
                    search_term_for_imdb = f"{ext_name} {ext_year}"

                try:
                    imdb_info_obj = await sync_to_async(
                        get_poster, search_term_for_imdb
                    )
                    if imdb_info_obj and imdb_info_obj.get("title"):
                        final_title = imdb_info_obj.get("title", final_title)
                        imdb_year_val = imdb_info_obj.get("year")
                        if imdb_year_val:
                            current_year_for_template = str(imdb_year_val)
                        LOGGER.info(
                            f"[FilenameProcessor] IMDB Success. Title: '{final_title}', Year: '{current_year_for_template}'"
                        )
                    else:
                        LOGGER.info(
                            f"[FilenameProcessor] IMDB lookup for '{search_term_for_imdb}' did not return usable data."
                        )
                except Exception as e_imdb:
                    LOGGER.warning(
                        f"[FilenameProcessor] IMDb lookup for '{search_term_for_imdb}' failed: {e_imdb}. Using filename extracted info."
                    )
        else:
            LOGGER.info(
                "[FilenameProcessor] AUTO_THUMBNAIL is disabled by user. Skipping TMDB/IMDB metadata lookup for renaming."
            )

        # Ensure final_title does not contain an extension before using in template
        final_title_base, final_title_ext = ospath.splitext(final_title.strip())
        if (
            final_title_ext
            and final_title_ext[0] == "."
            and len(final_title_ext) > 1
            and len(final_title_ext) <= 5
            and final_title_ext[1:].isalnum()
        ):
            final_title = final_title_base

        # =================== AGGRESSIVE FIX BLOCK ===================
        # 1. Force quality to have a 'p' if it's just a number
        quality_str = str(quality) if quality else "NA"
        if quality_str.isdigit():
            quality_str = f"{quality_str}p"

        # 2. Force season and episode numbers to be integers before formatting
        try:
            season_num = int(season_num)
        except (ValueError, TypeError):
            season_num = 1
        try:
            episode_num = int(episode_num)
        except (ValueError, TypeError):
            episode_num = 1
        # ==========================================================

        template_fields = {
            # Padded variants
            "season": f"{season_num:02d}",
            "episode": f"{episode_num:02d}",
            # Non-padded variants
            "season2": str(season_num),
            "episode2": str(episode_num),
            # Other fields
            "quality": quality_str,
            "title": final_title.strip(),
            "year": current_year_for_template,
            "audio": media_lang or "NA",
            "original_filename": ospath.splitext(current_basename)[0],
        }

        try:
            templated_base_name_dirty = template.format_map(SafeDict(template_fields))
            templated_base_name_cleaned = re.sub(
                r'[<>:"/\\|?*]', "", templated_base_name_dirty
            )

            # Strip any extension from the result of templating
            templated_base_name_final, templated_ext = ospath.splitext(
                templated_base_name_cleaned
            )
            if not templated_ext:  # If templated_base_name_cleaned had no extension
                templated_base_name_final = templated_base_name_cleaned

            original_extension = ospath.splitext(current_basename)[1]
            if (
                not original_extension and is_file
            ):  # Fallback for files that somehow lost original extension
                original_extension = (
                    ".mkv"  # Default to .mkv or derive if possible, though risky
                )

            new_templated_filename = f"{templated_base_name_final}{original_extension}"

            # Sanity check: if original_extension was empty and templated_base_name_final now has one, use that.
            # This case is less likely with the above stripping but as a safe guard.
            if not original_extension and ospath.splitext(templated_base_name_final)[1]:
                new_templated_filename = templated_base_name_final

            if new_templated_filename != current_basename:
                # Sanitize forbidden separators in filename
                potential_new_disk_path = ospath.join(dirpath, new_templated_filename)
                await aiorename(final_disk_path, potential_new_disk_path)
                final_disk_path = potential_new_disk_path
                final_cloud_name = new_templated_filename
        except Exception as e:
            LOGGER.error(
                f"[FilenameProcessor] Error during auto-rename: {e}. Template: '{template}'. Fields: {template_fields}"
            )

        if auto_rename_type == "manual":
            user_dict["_CURRENT_EPISODE"] = episode_num + 1

    # --- Prefix/Suffix and REMNAME logic ---
    original_cloud_name_for_ps_remname = final_cloud_name

    upload_prefix = user_dict.get("LEECH_PREFIX", "")
    upload_suffix = user_dict.get("LEECH_SUFFIX", "")

    # Also consider command line prefix/suffix arguments
    command_prefix = getattr(listener, "name_prefix", "") or ""
    command_suffix = getattr(listener, "name_suffix", "") or ""

    name_part_for_ps, ext_part_for_ps = ospath.splitext(final_cloud_name)

    # Apply prefix (with a space) to display/cloud name while preserving spaces
    # Command line prefix takes precedence over user setting
    effective_prefix = command_prefix or upload_prefix
    if effective_prefix:
        if not name_part_for_ps.startswith(f"{effective_prefix} "):
            name_part_for_ps = f"{effective_prefix} {name_part_for_ps}"

    # Apply suffix - combine user setting suffix with command line suffix
    # Both suffixes should be applied if present
    if upload_suffix:
        # Apply user setting suffix first
        if not name_part_for_ps.endswith(upload_suffix):
            name_part_for_ps = f"{name_part_for_ps}{upload_suffix}"

    if command_suffix:
        # Apply command line suffix second (so it comes after user setting suffix)
        if not name_part_for_ps.endswith(command_suffix):
            name_part_for_ps = f"{name_part_for_ps}{command_suffix}"

    # Reconstruct the filename
    new_name_after_ps = f"{name_part_for_ps}{ext_part_for_ps}"

    if new_name_after_ps != final_cloud_name:
        new_disk_path_after_ps = ospath.join(dirpath, new_name_after_ps)
        try:
            # Only rename on disk if the path actually exists and is different
            if (
                await aiopath.exists(final_disk_path)
                and final_disk_path != new_disk_path_after_ps
            ):
                await aiorename(final_disk_path, new_disk_path_after_ps)
                final_disk_path = new_disk_path_after_ps
            final_cloud_name = new_name_after_ps
            LOGGER.info(
                f"Applied prefix/suffix. Old: '{original_cloud_name_for_ps_remname}', New: '{final_cloud_name}'"
            )
        except Exception as e:
            LOGGER.error(
                f"Error renaming for prefix/suffix. Original: '{original_cloud_name_for_ps_remname}', Target: '{new_name_after_ps}'. Error: {e}"
            )
            # Keep final_cloud_name and final_disk_path as they were before this block if rename fails

    # REMNAME logic (applied after prefix/suffix)
    # Uses the potentially modified final_cloud_name from prefix/suffix step
    current_name_before_remname = final_cloud_name
    remname_patterns = user_dict.get("REMNAME", "")
    if remname_patterns:  # Apply if there are patterns
        try:
            # Auto-detect if pattern is regex or needs splitting
            # Check if the entire pattern contains regex metacharacters
            def is_likely_regex(pattern_str):
                """Detect if pattern contains regex metacharacters"""
                return bool(
                    re.search(r"\\[a-zA-Z]", pattern_str)  # \S, \d, \w, etc.
                    or ".*" in pattern_str
                    or ".+" in pattern_str
                    or re.search(r"\[.+\]", pattern_str)  # Character classes
                    or re.search(r"\{\d+,?\d*\}", pattern_str)  # Quantifiers
                )

            # If pattern starts with "regex:", use it as-is
            if remname_patterns.startswith("regex:"):
                remname_regex = re.compile(remname_patterns[6:], re.IGNORECASE)
            # If pattern looks like a regex, use it as-is
            elif is_likely_regex(remname_patterns):
                remname_regex = re.compile(remname_patterns, re.IGNORECASE)
            else:
                # Split and escape individual literal patterns
                parts = [p.strip() for p in remname_patterns.split("|") if p.strip()]
                if parts:
                    processed_parts = [re.escape(part) for part in parts]
                    remname_regex = re.compile("|".join(processed_parts), re.IGNORECASE)
                else:
                    remname_regex = None

            if remname_regex:
                # If REMNAME should operate on the name part only before extension:
                name_part_for_remname, ext_part_for_remname = ospath.splitext(
                    final_cloud_name
                )
                processed_name_part_for_remname = remname_regex.sub(
                    "", name_part_for_remname
                ).strip()

                # Cleanup artifacts like empty bracket pairs left after REMNAME removal
                processed_name_part_for_remname = re.sub(
                    r"\[\s*\]|\(\s*\)|\{\s*\}",
                    "",
                    processed_name_part_for_remname,
                )
                # Remove leading separators or dots left after removal
                processed_name_part_for_remname = re.sub(
                    r"^[\s\-_.]+",
                    "",
                    processed_name_part_for_remname,
                )
                # Fix ' - .Name' -> ' - Name'
                processed_name_part_for_remname = re.sub(
                    r"\s-\s*\.",
                    " - ",
                    processed_name_part_for_remname,
                )
                # Collapse duplicate dots
                processed_name_part_for_remname = re.sub(
                    r"\.{2,}", ".", processed_name_part_for_remname
                )
                # Normalize repeated whitespace
                processed_name_part_for_remname = re.sub(
                    r"\s{2,}", " ", processed_name_part_for_remname
                ).strip()

                # Reconstruct the name
                new_name_after_remname = (
                    f"{processed_name_part_for_remname}{ext_part_for_remname}"
                )

                # Ensure name doesn't become empty or just an extension
                if not processed_name_part_for_remname and ext_part_for_remname:
                    LOGGER.warning(
                        f"REMNAME resulted in an empty name part for '{final_cloud_name}'. Skipping REMNAME."
                    )
                elif new_name_after_remname != final_cloud_name:
                    new_disk_path_after_remname = ospath.join(
                        dirpath, new_name_after_remname
                    )
                    # Only rename on disk if the path actually exists and is different
                    if (
                        await aiopath.exists(final_disk_path)
                        and final_disk_path != new_disk_path_after_remname
                    ):
                        await aiorename(final_disk_path, new_disk_path_after_remname)
                        final_disk_path = new_disk_path_after_remname
                    final_cloud_name = new_name_after_remname
                    LOGGER.info(
                        f"Applied REMNAME. Old: '{current_name_before_remname}', New: '{final_cloud_name}'"
                    )
                # If new_name_after_remname is same as final_cloud_name, no action needed.
        except Exception as e:
            LOGGER.error(
                f"[FilenameProcessor] Error applying REMNAME regex: {e}. Current name: '{final_cloud_name}'"
            )
            # Keep final_cloud_name and final_disk_path as they were before remname if error

    # Apply Name Substitution (-ns/NAME_SWAP) rules to the base name (before extension)
    try:
        name_swap_rules = getattr(listener, "name_swap", None)
        if name_swap_rules:
            # Work on the name part only
            name_part_for_swap, ext_part_for_swap = ospath.splitext(final_cloud_name)
            original_name_part_for_swap = name_part_for_swap

            for swap_item in name_swap_rules:
                # Ensure we have a list-like with up to 4 elements
                if not isinstance(swap_item, (list, tuple)):
                    continue
                pattern, replacement, cnt_str, flag_str = (
                    list(swap_item) + ["", "0", "NOFLAG"]
                )[:4]

                # Check if this is a simple removal (should escape regex chars) or advanced regex
                is_simple_removal = (
                    len(swap_item) == 1  # Just pattern
                    or (
                        len(swap_item) == 2 and swap_item[1] == ""
                    )  # Pattern with empty replacement
                )

                # For simple removals, escape regex special characters
                if is_simple_removal:
                    pattern = re.escape(pattern)
                    # Default to case-insensitive for simple removals if no flag specified
                    # Check for default values that indicate no user-specified flag
                    if flag_str in ("NOFLAG", "0", ""):
                        flag_str = "IGNORECASE"

                # Count handling: 0 => replace all
                try:
                    count_val = int(cnt_str) if str(cnt_str).isdigit() else 0
                except Exception:
                    count_val = 0
                # Flags handling
                regex_flags = getattr(re, str(flag_str).upper(), 0)
                try:
                    name_part_for_swap = re.sub(
                        pattern,
                        str(replacement or ""),
                        name_part_for_swap,
                        count_val,
                        flags=regex_flags,
                    )
                except Exception as e_swap:
                    LOGGER.error(
                        f"[FilenameProcessor] NameSub error for pattern '{pattern}': {e_swap}"
                    )
                    # Continue with other rules

            if name_part_for_swap != original_name_part_for_swap:
                new_name_after_swap = f"{name_part_for_swap}{ext_part_for_swap}"
                new_disk_path_after_swap = ospath.join(dirpath, new_name_after_swap)
                if (
                    await aiopath.exists(final_disk_path)
                    and final_disk_path != new_disk_path_after_swap
                ):
                    await aiorename(final_disk_path, new_disk_path_after_swap)
                    final_disk_path = new_disk_path_after_swap
                final_cloud_name = new_name_after_swap
    except Exception as e_any_swap:
        LOGGER.error(f"[FilenameProcessor] Unexpected NameSub error: {e_any_swap}")

    # Clean copy indicators like " (1)", " (Copy)" etc. from the filename
    if is_file:  # Only apply to files
        name_part_for_copy_check, ext_part_for_copy_check = ospath.splitext(
            final_cloud_name
        )
        original_name_part_before_copy_clean = name_part_for_copy_check

        # List of regex patterns for common copy indicators (case-insensitive)
        # Order can matter: more specific or disruptive patterns first.
        copy_indicator_patterns = [
            r"\s*-\s*Copy$",  # " - Copy" at the end
            r"\s*\(Copy\)$",  # " (Copy)" at the end
            r"\s*\(Copie\)$",  # French " (Copie)"
            r"\s*\(Kopie\)$",  # German " (Kopie)"
            r"\s*\(\d+\)$",  # " (1)", " (23)" at the end
        ]

        for pattern in copy_indicator_patterns:
            name_part_for_copy_check = re.sub(
                pattern, "", name_part_for_copy_check, flags=re.IGNORECASE
            )

        name_part_for_copy_check = name_part_for_copy_check.strip()  # Clean up spaces

        if (
            name_part_for_copy_check != original_name_part_before_copy_clean
            and name_part_for_copy_check
        ):  # If changed and not empty
            cleaned_filename_after_copy_removal = (
                f"{name_part_for_copy_check}{ext_part_for_copy_check}"
            )
            if cleaned_filename_after_copy_removal != final_cloud_name:
                new_disk_path_after_copy_removal = ospath.join(
                    dirpath, cleaned_filename_after_copy_removal
                )
                try:
                    if (
                        final_disk_path != new_disk_path_after_copy_removal
                        and await aiopath.exists(final_disk_path)
                    ):
                        await aiorename(
                            final_disk_path, new_disk_path_after_copy_removal
                        )
                        LOGGER.info(
                            f"Cleaned copy indicator: Renamed on disk from '{final_disk_path}' to '{new_disk_path_after_copy_removal}'"
                        )
                        final_disk_path = new_disk_path_after_copy_removal
                    final_cloud_name = cleaned_filename_after_copy_removal
                except Exception as e_copy_rename:
                    LOGGER.error(
                        f"Error renaming after copy indicator removal: {e_copy_rename}. Original name '{final_cloud_name}' kept for this step."
                    )
                    # final_cloud_name remains unchanged from before this block.
                    # final_disk_path also remains as it was.
        elif (
            not name_part_for_copy_check and original_name_part_before_copy_clean
        ):  # Name became empty after cleaning
            LOGGER.warning(
                f"Filename part became empty after attempting to remove copy indicators from '{original_name_part_before_copy_clean}'. Reverting to name before this specific cleaning."
            )
            # final_cloud_name remains unchanged from before this block.

    # Remove trailing junk
    name_stem, name_ext = ospath.splitext(final_cloud_name)
    trailing_pattern = (
        r"([\s._-]*(?:intro|sample|merged|remove|reorder|convert|extract))+\s*$"
    )
    cleared = re.sub(trailing_pattern, "", name_stem, flags=re.IGNORECASE)
    if cleared != name_stem:
        new_stem = cleared.strip()
        new_name = f"{new_stem}{name_ext}"
        if new_name != final_cloud_name:
            new_disk_path = ospath.join(dirpath, new_name)
            if (
                await aiopath.exists(final_disk_path)
                and final_disk_path != new_disk_path
            ):
                if not await aiopath.exists(new_disk_path):
                    await aiorename(final_disk_path, new_disk_path)
                    final_disk_path = new_disk_path
                else:
                    LOGGER.warning(
                        f"Could not remove trailing junk from '{final_cloud_name}' because '{new_name}' already exists."
                    )
            final_cloud_name = new_name

    # Final length truncation (ensure this is the very last step for cloud name)
    if (
        len(final_cloud_name) > 1000
    ):  # Max Telegram filename length is variable, 255 is a common OS limit.
        # Telegram internal processing might have other limits for display.
        # Keeping 240 as a safe bet from original code.
        name_part, ext_part = ospath.splitext(final_cloud_name)
        max_name_len = 1000 - len(ext_part)  # Max length for the name part
        if max_name_len < 1:  # if extension is too long, this is an issue.
            max_name_len = (
                1  # Ensure name_part is not empty, though this filename will be weird.
            )

        truncated_name_part = name_part[:max_name_len]

        # If disk renaming is desired for this truncation as well:
        new_truncated_cloud_name = f"{truncated_name_part}{ext_part}"
        if new_truncated_cloud_name != final_cloud_name:
            new_truncated_disk_path = ospath.join(dirpath, new_truncated_cloud_name)
            try:
                if final_disk_path != new_truncated_disk_path and await aiopath.exists(
                    final_disk_path
                ):
                    await aiorename(final_disk_path, new_truncated_disk_path)
                    LOGGER.info(
                        f"Filename truncated for length: Renamed on disk from '{final_disk_path}' to '{new_truncated_disk_path}'"
                    )
                    final_disk_path = new_truncated_disk_path
                final_cloud_name = new_truncated_cloud_name
            except Exception as e_trunc_rename:
                LOGGER.error(
                    f"Error renaming for filename truncation: {e_trunc_rename}. Using pre-truncation name for disk if different: '{final_cloud_name}'. Cloud name will be: '{new_truncated_cloud_name}'."
                )
                final_cloud_name = new_truncated_cloud_name  # Cloud name is truncated regardless of disk rename success
        else:
            # This case means the name was already short enough or truncation resulted in same name.
            pass

    return final_cloud_name, final_disk_path
