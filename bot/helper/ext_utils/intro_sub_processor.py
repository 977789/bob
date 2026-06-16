#!/usr/bin/env python3

# -*- coding: utf-8 -*-

# This module handles intro subtitle processing as a separate post-processing step

from typing import Optional
from aiofiles.os import path as aiopath

from bot import LOGGER


async def apply_intro_sub_processing(
    listener, input_path: str, user_id: int
) -> Optional[str]:
    """
    Apply intro subtitle processing to video files as a post-processing step.
    This function acts as a wrapper around the existing VideoToolsExecutor._intro_sub method.

    Args:
        listener: Task listener instance
        input_path: Path to the video file or directory
        user_id: User ID for settings

    Returns:
        Path to processed file(s) or None if failed
    """
    try:
        LOGGER.info(f"Starting intro_sub post-processing for: {input_path}")

        # Check if input exists
        if not await aiopath.exists(input_path):
            LOGGER.error(f"Input path does not exist: {input_path}")
            return None

        # Import VideoToolsExecutor here to avoid circular imports
        from ..video_utils.executor import VideoToolsExecutor

        # Create a temporary video mode for intro_sub processing
        original_video_mode = getattr(listener, "video_mode", None)
        listener.video_mode = (
            "intro_sub",
            listener.name or "intro_processed",
            False,
            {},
        )

        try:
            # Create executor for intro_sub processing
            # Use a dummy gid for post-processing
            intro_executor = VideoToolsExecutor(
                listener, input_path, f"intro_post_{user_id}", metadata=False
            )

            # Execute intro_sub processing
            processed_path = await intro_executor._intro_sub()

            if processed_path and await aiopath.exists(processed_path):
                LOGGER.info(
                    f"intro_sub post-processing completed successfully: {processed_path}"
                )
                return processed_path
            else:
                LOGGER.warning(
                    f"intro_sub post-processing did not produce valid output"
                )
                return input_path

        finally:
            # Restore original video mode
            listener.video_mode = original_video_mode

    except Exception as e:
        LOGGER.error(f"Error in intro_sub post-processing: {e}")
        return None
