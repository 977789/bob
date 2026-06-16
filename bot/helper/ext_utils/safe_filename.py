"""
Unified filename sanitization utility for consistent space preservation
Addresses the issue where spaces were inconsistently replaced with underscores
"""

import os
import re
from logging import getLogger

LOGGER = getLogger(__name__)


def safe_filename(
    filename: str, max_length: int = 200, preserve_extension: bool = True
) -> str:
    """
    Unified filename sanitization that always preserves spaces.

    This function ensures consistent behavior across all filename processing,
    addressing the issue where basename() correctly preserves spaces but other
    parts of the system might replace them with underscores.

    Args:
        filename: The filename to sanitize
        max_length: Maximum length for the filename (default 200)
        preserve_extension: Whether to preserve file extension when truncating

    Returns:
        Sanitized filename with spaces preserved
    """
    if not filename:
        return ""

    original = filename

    # Use basename approach - this is what the user said works correctly
    if os.path.sep in filename or (os.name == "nt" and "/" in filename):
        filename = os.path.basename(filename)

    # Remove only truly invalid characters that cause filesystem errors
    # Keep spaces intact as requested in the issue
    # Invalid chars: < > : " / \ | ? * and control characters
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", filename)

    # Do not alter underscores; preserve filename as-is except invalid chars

    # Remove leading/trailing dots (can cause issues on Windows)
    # but preserve spaces (this was the main issue)
    sanitized = sanitized.strip(".")

    # Handle length limitation
    if len(sanitized) > max_length:
        if preserve_extension:
            name_part, ext_part = os.path.splitext(sanitized)
            max_name_length = max(1, max_length - len(ext_part))
            sanitized = f"{name_part[:max_name_length]}{ext_part}"
        else:
            sanitized = sanitized[:max_length]

    # Final cleanup - ensure we don't have empty result
    if not sanitized.strip():
        sanitized = "file"

    # Log any changes to help debug inconsistencies
    if original != sanitized:
        LOGGER.debug(f"safe_filename: '{original}' → '{sanitized}'")
        # Special check for the space-to-underscore issue
        if " " in original and " " not in sanitized and "_" in sanitized:
            LOGGER.warning(
                f"POTENTIAL BUG: Spaces may have been replaced with underscores: '{original}' → '{sanitized}'"
            )

    return sanitized


def safe_caption_filename(caption_text: str, max_length: int = 200) -> str:
    """
    Extract and sanitize filename from caption text with space preservation.

    This addresses the specific issue where caption-derived filenames
    were getting spaces replaced with underscores inconsistently.

    Args:
        caption_text: Caption text to extract filename from
        max_length: Maximum length for the filename

    Returns:
        Sanitized filename extracted from caption
    """
    if not caption_text:
        return ""

    # Common video file extensions
    COMMON_EXTENSIONS = [
        ".mkv",
        ".mp4",
        ".avi",
        ".mov",
        ".wmv",
        ".flv",
        ".webm",
        ".m4v",
        ".3gp",
        ".mpg",
        ".mpeg",
        ".ts",
        ".m2ts",
    ]

    # Try to extract filename with extension from caption
    for ext in COMMON_EXTENSIONS:
        # Look for pattern like "filename.ext" in the caption
        escaped_ext = re.escape(ext)
        pattern = re.compile(
            r"(.+?\\" + escaped_ext + r")(?:[\s\(\[\{<_]|$)", re.IGNORECASE
        )
        match = pattern.search(caption_text)
        if match:
            extracted_filename = match.group(1).strip()
            return safe_filename(extracted_filename, max_length)

    # If no extension found, use the whole caption as filename
    return safe_filename(caption_text.strip(), max_length)


def ensure_basename_consistency(file_path: str) -> str:
    """
    Ensure filename extraction uses basename approach consistently.

    Args:
        file_path: Full file path

    Returns:
        Basename with spaces preserved
    """
    if not file_path:
        return ""

    # This is the approach the user said works correctly
    basename = os.path.basename(file_path)
    return safe_filename(basename)


# Legacy function compatibility - redirect to new safe functions
def sanitize_filename(filename: str) -> str:
    """Legacy compatibility function - redirects to safe_filename"""
    LOGGER.debug(f"Legacy sanitize_filename called with: {filename}")
    result = safe_filename(filename)
    LOGGER.debug(f"Legacy sanitize_filename result: {result}")
    return result


def sanitize_caption_filename(filename: str) -> str:
    """Legacy compatibility function - redirects to safe_caption_filename"""
    LOGGER.debug(f"Legacy sanitize_caption_filename called with: {filename}")
    result = safe_caption_filename(filename)
    LOGGER.debug(f"Legacy sanitize_caption_filename result: {result}")
    return result
