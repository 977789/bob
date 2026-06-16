#!/usr/bin/env python3
"""
Filename utilities for pattern removal and manipulation
"""

import os
import re
from typing import List, Optional

from ... import LOGGER


class FilenamePatternRemover:
    """
    Utility class for removing patterns from filenames
    """

    @staticmethod
    def process_filename_patterns(filename: str, patterns: str) -> str:
        """
        Process filename patterns - supports both removal and replacement

        Syntax:
        - Removal: "pattern1|pattern2|pattern3" (removes all patterns)
        - Replacement: "pattern1|replacement1 pattern2|replacement2" (replaces pattern1 with replacement1, etc.)
        - Mixed: "pattern1|replacement1 pattern2" (replace pattern1, remove pattern2)

        Args:
            filename (str): Original filename
            patterns (str): Space-separated pattern rules, each rule can be:
                          - "pattern" (remove pattern)
                          - "pattern|replacement" (replace pattern with replacement)

        Returns:
            str: Filename with patterns processed
        """
        if not patterns or not patterns.strip():
            return filename

        # Extract filename and extension
        name, ext = os.path.splitext(filename)
        original_name = name

        # Split by space to get individual pattern rules
        pattern_rules = [rule.strip() for rule in patterns.split() if rule.strip()]

        if not pattern_rules:
            return filename

        # Process each pattern rule
        for rule in pattern_rules:
            if "|" in rule:
                # Rule contains replacement: "pattern|replacement"
                parts = rule.split("|", 1)  # Split only on first |
                pattern = parts[0].strip()
                replacement = parts[1].strip() if len(parts) > 1 else ""

                if pattern:
                    try:
                        # Use regex for case-insensitive matching while escaping special chars
                        escaped_pattern = re.escape(pattern)
                        name = re.sub(
                            escaped_pattern, replacement, name, flags=re.IGNORECASE
                        )

                        LOGGER.info(
                            f"Pattern replacement: '{pattern}' -> '{replacement}' in filename"
                        )

                    except Exception as e:
                        LOGGER.error(
                            f"Error replacing pattern '{pattern}' with '{replacement}': {e}"
                        )
                        continue
            else:
                # Rule is just removal: "pattern"
                pattern = rule.strip()
                if pattern:
                    try:
                        # Use regex for case-insensitive matching while escaping special chars
                        escaped_pattern = re.escape(pattern)
                        name = re.sub(escaped_pattern, "", name, flags=re.IGNORECASE)

                        LOGGER.info(f"Pattern removal: '{pattern}' from filename")

                    except Exception as e:
                        LOGGER.error(f"Error removing pattern '{pattern}': {e}")
                        continue

        # Clean up the result
        name = re.sub(r"[.\s_\-]+", ".", name)
        name = re.sub(r"^[.\s_\-]+|[.\s_\-]+$", "", name)
        name = re.sub(r"\.+", ".", name)  # Multiple dots to single dot
        name = name.strip(" ._-")  # Remove leading/trailing separators

        # Ensure we don't end up with an empty filename
        if not name or name.isspace() or len(name) < 3:
            LOGGER.warning(
                f"Pattern processing would result in empty/short filename, keeping original: {original_name}"
            )
            name = original_name

        result = name + ext

        # Log the change if it was actually modified
        if result != filename:
            LOGGER.info(f"Filename pattern processing: '{filename}' -> '{result}'")

        return result

    @staticmethod
    def remove_patterns(filename: str, patterns: str) -> str:
        """
        Legacy method for backward compatibility - now uses process_filename_patterns
        Remove specified patterns from filename while preserving extension

        Args:
            filename (str): Original filename
            patterns (str): Pipe-separated patterns to remove (e.g., "HDRip|WEBRip|HEVC")

        Returns:
            str: Filename with patterns removed
        """
        # Convert old format to new format for backward compatibility
        if "|" in patterns and " " not in patterns:
            # Old format: "pattern1|pattern2|pattern3" -> convert to removal format
            old_patterns = [p.strip() for p in patterns.split("|") if p.strip()]
            new_patterns = " ".join(old_patterns)  # Convert to space-separated removal
            return FilenamePatternRemover.process_filename_patterns(
                filename, new_patterns
            )
        else:
            # New format or single pattern
            return FilenamePatternRemover.process_filename_patterns(filename, patterns)

    @staticmethod
    def get_user_patterns(user_dict: dict) -> str:
        """
        Get user's default removal patterns from their settings

        Args:
            user_dict (dict): User's settings dictionary

        Returns:
            str: User's default patterns or empty string
        """
        return user_dict.get("FILENAME_REMOVE_PATTERNS", "")

    @staticmethod
    def merge_patterns(command_patterns: str, user_patterns: str) -> str:
        """
        Merge command-line patterns with user's default patterns
        Supports both old (pipe-separated) and new (space-separated) formats

        Args:
            command_patterns (str): Patterns from command line
            user_patterns (str): User's default patterns

        Returns:
            str: Merged patterns string in new format (space-separated)
        """
        all_pattern_rules = []

        # Process command patterns
        if command_patterns and command_patterns.strip():
            cmd = command_patterns.strip()
            if " " in cmd:
                # New format: space-separated rules (may contain replacements)
                all_pattern_rules.extend([p.strip() for p in cmd.split() if p.strip()])
            else:
                # Single rule (could be old format removal or new format replacement)
                all_pattern_rules.append(cmd)

        # Process user patterns
        if user_patterns and user_patterns.strip():
            usr = user_patterns.strip()
            if " " in usr:
                # New format: space-separated rules (may contain replacements)
                all_pattern_rules.extend([p.strip() for p in usr.split() if p.strip()])
            else:
                # Single rule (could be old format removal or new format replacement)
                all_pattern_rules.append(usr)

        # Remove duplicates while preserving order
        seen = set()
        unique_rules = []
        for rule in all_pattern_rules:
            if rule not in seen:
                seen.add(rule)
                unique_rules.append(rule)

        return " ".join(unique_rules) if unique_rules else ""

    @staticmethod
    def validate_patterns(patterns: str) -> bool:
        """
        Validate that patterns are safe to use

        Args:
            patterns (str): Patterns to validate

        Returns:
            bool: True if patterns are valid, False otherwise
        """
        if not patterns or not patterns.strip():
            return True

        pattern_list = [p.strip() for p in patterns.split("|") if p.strip()]

        for pattern in pattern_list:
            # Check for potentially dangerous patterns
            if len(pattern) < 1:
                continue

            # Don't allow patterns that are just file extensions
            if pattern.startswith(".") and len(pattern) <= 5:
                LOGGER.warning(f"Skipping potentially dangerous pattern: {pattern}")
                return False

            # Don't allow patterns that are too generic (single character)
            if len(pattern) == 1:
                LOGGER.warning(f"Skipping too generic pattern: {pattern}")
                return False

        return True


def apply_filename_patterns(
    filename: str, command_patterns: str, user_dict: dict
) -> str:
    """
    Apply filename pattern removal to a single filename

    Args:
        filename (str): Original filename
        command_patterns (str): Patterns from command line (-remname flag)
        user_dict (dict): User's settings dictionary

    Returns:
        str: Filename with patterns removed
    """
    remover = FilenamePatternRemover()

    # Get user's default patterns
    user_patterns = remover.get_user_patterns(user_dict)

    # Merge command patterns with user patterns
    merged_patterns = remover.merge_patterns(command_patterns, user_patterns)

    if not merged_patterns:
        return filename

    # Validate patterns
    if not remover.validate_patterns(merged_patterns):
        LOGGER.warning("Invalid patterns detected, skipping pattern removal")
        return filename

    # Apply pattern processing (supports both removal and replacement)
    return remover.process_filename_patterns(filename, merged_patterns)


async def apply_filename_patterns_to_path(
    path: str, command_patterns: str, user_dict: dict
) -> str:
    """
    Apply filename pattern removal to all files in a path

    Args:
        path (str): Path to file or directory
        command_patterns (str): Patterns from command line (-remname flag)
        user_dict (dict): User's settings dictionary

    Returns:
        str: Updated path (may be the same if no changes)
    """
    from aiofiles.os import rename, path as aiopath
    from ..ext_utils.bot_utils import sync_to_async
    from os import walk

    if not command_patterns and not user_dict.get("FILENAME_REMOVE_PATTERNS"):
        return path

    LOGGER.info(f"Applying filename pattern removal to: {path}")

    try:
        if await aiopath.isfile(path):
            # Single file
            old_name = os.path.basename(path)
            new_name = apply_filename_patterns(old_name, command_patterns, user_dict)

            if new_name != old_name:
                new_path = os.path.join(os.path.dirname(path), new_name)
                await rename(path, new_path)
                LOGGER.info(f"Renamed file: {old_name} -> {new_name}")
                return new_path

            return path

        elif await aiopath.isdir(path):
            # Directory - rename all files recursively
            for root, dirs, files in await sync_to_async(walk, path, topdown=False):
                for file in files:
                    old_file_path = os.path.join(root, file)
                    new_name = apply_filename_patterns(
                        file, command_patterns, user_dict
                    )

                    if new_name != file:
                        new_file_path = os.path.join(root, new_name)
                        try:
                            await rename(old_file_path, new_file_path)
                            LOGGER.info(f"Renamed file: {file} -> {new_name}")
                        except Exception as e:
                            LOGGER.error(
                                f"Error renaming {old_file_path} to {new_file_path}: {e}"
                            )

            return path

    except Exception as e:
        LOGGER.error(f"Error applying filename patterns to {path}: {e}")

    return path


async def apply_auto_rename_to_path(path: str, listener) -> str:
    """
    Apply Auto Rename functionality to files/directories for mirror operations.
    This replicates the Auto Rename logic from TelegramUploader for mirror uploads.

    Args:
        path (str): Path to file or directory
        listener: Task listener object with user_dict

    Returns:
        str: Updated path (may be the same if no changes)
    """
    from aiofiles.os import rename, path as aiopath
    from ..ext_utils.bot_utils import sync_to_async
    from ..ext_utils.media_utils import get_media_info
    from ...modules.imdb import get_poster
    from ..mirror_leech_utils.upload_utils.telegram_uploader import extract_media_info
    from os import walk
    import json
    import subprocess
    import re

    if not hasattr(listener, "user_dict"):
        return path

    user_dict = getattr(listener, "user_dict", {})
    auto_rename = user_dict.get("AUTO_RENAME", False)

    if not auto_rename:
        return path

    template = user_dict.get("RENAME_TEMPLATE", "S{season}E{episode}Q{quality}")
    episode = int(user_dict.get("_CURRENT_EPISODE", user_dict.get("START_EPISODE", 1)))
    season = int(user_dict.get("START_SEASON", 1))

    LOGGER.info(f"Applying Auto Rename to: {path}")

    try:
        if await aiopath.isfile(path):
            # Single file
            new_path = await _auto_rename_single_file(
                path, template, episode, season, user_dict
            )
            return new_path if new_path else path

        elif await aiopath.isdir(path):
            # Directory - rename all files recursively
            for root, dirs, files in await sync_to_async(walk, path, topdown=False):
                for file in files:
                    file_path = os.path.join(root, file)
                    try:
                        await _auto_rename_single_file(
                            file_path, template, episode, season, user_dict
                        )
                        # Update episode for next file
                        episode = user_dict.get("_CURRENT_EPISODE", episode + 1)
                    except Exception as e:
                        LOGGER.error(f"Error auto-renaming file {file_path}: {e}")

            return path

    except Exception as e:
        LOGGER.error(f"Error applying auto rename to {path}: {e}")

    return path


async def _auto_rename_single_file(
    file_path: str, template: str, episode: int, season: int, user_dict: dict
):
    """
    Apply Auto Rename to a single file

    Returns:
        str: New file path if renamed, original path if not renamed
    """
    from aiofiles.os import rename
    from ..ext_utils.media_utils import get_media_info
    from ...modules.imdb import get_poster
    from ..mirror_leech_utils.upload_utils.telegram_uploader import extract_media_info
    import json
    import subprocess
    import re

    old_filename = os.path.basename(file_path)
    directory = os.path.dirname(file_path)

    try:
        # Get media quality
        _, quality, lang, _ = await get_media_info(file_path, True)
        quality = str(quality).replace("p", "") if quality else ""

        # Clean filename to get probable title
        def clean_filename_for_title(filename):
            # Use extract_media_info to get the best title and year
            name, season, episode, year, part, volume = extract_media_info(filename)
            # If we have both name and year, return 'Name Year'
            if name and year:
                result = f"{name} {year}"
            elif name:
                result = name
            else:
                # fallback to old logic if extract_media_info fails
                name = os.path.splitext(filename)[0]
                name = re.sub(r'[\[\](){}⟨⟩【】『』""' "«»‹›❮❯❰❱❲❳❴❵]", " ", name)
                name = re.sub(r"\s+", " ", name).strip()
                result = name if name else "Unknown"
            LOGGER.info(f"Final cleaned title for lookups: '{result}'")
            return result

        probable_title = clean_filename_for_title(old_filename)

        # Fetch IMDB info
        imdb_info = None
        imdb_data = {}
        if probable_title:
            imdb_info = get_poster(probable_title)
        if imdb_info:
            imdb_data = {
                "title": imdb_info.get("title", ""),
                "year": imdb_info.get("year", ""),
                "rating": imdb_info.get("rating", "").replace(" / 10", ""),
                "genre": imdb_info.get("genres", ""),
            }
        else:
            imdb_data = {"title": probable_title, "year": "", "rating": "", "genre": ""}

        # Get audio language(s)
        audio_count = 0
        audio = lang or ""
        try:
            ffprobe_cmd = [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=index",
                "-of",
                "json",
                file_path,
            ]
            ffprobe_out = subprocess.run(
                ffprobe_cmd, capture_output=True, text=True, timeout=30
            )
            if ffprobe_out.returncode == 0:
                audio_json = json.loads(ffprobe_out.stdout)
                audio_count = len(audio_json.get("streams", []))
            if audio_count >= 2:
                audio = "MultiAuD"
        except Exception:
            pass

        # Merge all fields for template - episode will be updated later
        template_fields = dict(
            season=season,
            episode2=episode,  # integer, for E1, E2, ...
            episode=f"{episode:02d}",  # zero-padded, for E01, E02, ...
            quality=quality,
            audio=audio,
            **imdb_data,
        )

        # Check if this is a multi-resolution file (contains pattern like _720p_BL, _480p_BL, etc.)
        is_multi_resolution_file = bool(re.search(r"_\d+p_BL\.", old_filename))

        # Handle episode numbering for multi-resolution files
        if is_multi_resolution_file:
            # Check if we've already processed a file from this batch
            base_filename = re.sub(
                r"_\d+p_BL\.", ".", old_filename
            )  # Remove quality suffix
            batch_key = f"multi_res_batch_{base_filename}"

            # For multi-resolution batch, use the same episode number for all files
            if not user_dict.get(batch_key, False):
                # First file in batch - increment and store the episode number
                user_dict["_CURRENT_EPISODE"] = episode + 1
                user_dict[batch_key] = (
                    episode  # Store the episode number to use for this batch
                )
                current_episode = episode  # Use original episode for this batch
                LOGGER.info(
                    f"Multi-resolution batch detected. Episode {episode} will be used for all files in batch: {base_filename}"
                )
            else:
                # Subsequent files in batch - use the same episode number as the first file
                current_episode = user_dict[batch_key]
                LOGGER.info(
                    f"Multi-resolution file from same batch, using episode {current_episode}: {old_filename}"
                )

            # Clean up old batch keys to prevent memory buildup (keep only recent 50 keys)
            batch_keys = [
                k for k in user_dict.keys() if k.startswith("multi_res_batch_")
            ]
            if len(batch_keys) > 50:
                # Remove oldest batch keys (simple cleanup)
                for key in sorted(batch_keys)[:-50]:
                    user_dict.pop(key, None)

            # Update template fields with correct episode
            template_fields["episode2"] = current_episode
            template_fields["episode"] = f"{current_episode:02d}"
        else:
            # Regular single file - increment episode counter normally
            user_dict["_CURRENT_EPISODE"] = episode + 1
            LOGGER.info(
                f"Single file processed. Using episode {episode}, next will be {episode + 1}: {old_filename}"
            )

        new_name = template.format(**template_fields)
        ext = os.path.splitext(old_filename)[1]
        new_filename = f"{new_name}{ext}"
        new_file_path = os.path.join(directory, new_filename)

        # Rename the file if name changed
        if file_path != new_file_path and os.path.exists(file_path):
            await rename(file_path, new_file_path)
            LOGGER.info(f"Auto renamed file: '{old_filename}' -> '{new_filename}'")
            return new_file_path
        else:
            return file_path

    except Exception as e:
        LOGGER.error(f"Error in auto rename for {old_filename}: {e}")
        return file_path
