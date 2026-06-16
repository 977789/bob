"""
FFmpeg compatibility fixes for older filter options
"""

import re


def fix_ffmpeg_filter_compatibility(filter_string: str) -> str:
    """
    Fix FFmpeg filter compatibility issues by replacing deprecated or invalid options.

    Args:
        filter_string: The FFmpeg filter string to fix

    Returns:
        Fixed filter string with compatible options
    """
    if not isinstance(filter_string, str):
        return filter_string

    # Fix force_original_aspect_ratio=decrease to force_original_aspect_ratio=1
    # The 'decrease' option is not valid in newer FFmpeg versions
    fixed_filter = re.sub(
        r"force_original_aspect_ratio=decrease\b",
        "force_original_aspect_ratio=1",
        filter_string,
    )

    return fixed_filter


def test_fix():
    """Test the fix function"""
    # Test case from the error log
    problematic_filter = (
        "[0:v]trim=start=0:end=60,setpts=PTS-STARTPTS,scale=min(1920,iw):min(1080,ih):force_original_aspect_ratio=decrease[v0]; "
        "[0:a]atrim=start=0:end=60,asetpts=PTS-STARTPTS[a0]; "
        "[0:v]trim=start=1319:end=1379,setpts=PTS-STARTPTS,scale=min(1920,iw):min(1080,ih):force_original_aspect_ratio=decrease[v1]; "
        "[0:a]atrim=start=1319:end=1379,asetpts=PTS-STARTPTS[a1]; "
        "[0:v]trim=start=1379:end=1439,setpts=PTS-STARTPTS,scale=min(1920,iw):min(1080,ih):force_original_aspect_ratio=decrease[v2]; "
        "[0:a]atrim=start=1379:end=1439,asetpts=PTS-STARTPTS[a2]; "
        "[v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1[vout][aout]"
    )

    fixed_filter = fix_ffmpeg_filter_compatibility(problematic_filter)

    print("Original filter contains 'decrease':", "decrease" in problematic_filter)
    print("Fixed filter contains 'decrease':", "decrease" in fixed_filter)
    print(
        "Fixed filter contains 'force_original_aspect_ratio=1':",
        "force_original_aspect_ratio=1" in fixed_filter,
    )

    return fixed_filter


if __name__ == "__main__":
    test_fix()
