"""
capture.py – Screenshot & region-handling utilities for the MCP project.

Provides synchronous and asynchronous screenshot capture with optional
cropping and saving functionality.
"""
from __future__ import annotations # Still good practice for type hints within class methods referring to the class itself

import asyncio
import pathlib
from PIL import Image # type: ignore[import-untyped] # If Pillow stubs are not perfect

from mcp.logger import get_logger

logger = get_logger(__name__)

# Type alias for bounding box using Python 3.12 'type' statement (PEP 695)
type BBox = tuple[int, int, int, int]  # (left, top, width, height)

__all__ = [
    "screenshot",
    "screenshot_async",
    "CaptureError",
    "BBox",
]

class CaptureError(Exception):
    """Raised when screenshot capture fails."""
    pass

def validate_bbox(bbox: BBox) -> None:
    """
    Validates bounding box parameters.

    Args:
        bbox: Bounding box to validate (left, top, width, height).

    Raises:
        ValueError: If bbox parameters are invalid.
    """
    left, top, width, height = bbox

    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid bbox dimensions: width={width}, height={height}. Must be positive.")

    if left < 0 or top < 0:
        # Negative coordinates might be valid in multi-monitor setups,
        # but for single window captures, they are unusual.
        logger.warning(f"Bounding box has negative top-left coordinates: left={left}, top={top}.")

def screenshot(
    bbox: BBox,
    *,
    crop: BBox | None = None,
    save_path: str | pathlib.Path | None = None,
    img_format: str | None = None, # Renamed 'format' to 'img_format' to avoid conflict with built-in
    optimize: bool = True,
    quality: int = 95,
    **kwargs,
) -> Image.Image:
    """
    Captures a screenshot of the specified bounding box.

    Args:
        bbox: Window bounding box in screen coordinates (left, top, width, height).
        crop: Optional sub-region to crop relative to the window (x, y, width, height).
        save_path: If provided, save the screenshot to this path.
        img_format: Image format (e.g., "PNG", "JPEG"). Auto-detected from save_path if None.
        optimize: Whether to optimize the saved image (default: True).
        quality: JPEG quality (1-100, default: 95).
        **kwargs: Additional arguments passed to PIL.Image.save().

    Returns:
        The captured PIL.Image.Image object.

    Raises:
        CaptureError: If screenshot capture fails.
        ValueError: If parameters are invalid.
    """
    import pyautogui # Import pyautogui here to potentially allow module to load even if pyautogui is missing for some reason.

    validate_bbox(bbox)
    logger.debug(
        f"Capturing screenshot: bbox={bbox}, crop={crop}, "
        f"save_path={save_path}, format={img_format}"
    )

    try:
        # Capture the specified region
        left, top, width, height = bbox
        # pyautogui.screenshot may return None or raise an error on failure.
        img: Image.Image | None = pyautogui.screenshot(region=(left, top, width, height))

        if img is None:
            raise CaptureError("pyautogui.screenshot() returned None. Capture failed.")

        logger.debug(f"Screenshot captured: {img.width}x{img.height}")

        # Apply crop if specified
        if crop is not None:
            validate_bbox(crop) # Also validate crop dimensions
            cx, cy, cw, ch = crop
            if cx + cw > img.width or cy + ch > img.height:
                raise ValueError(
                    f"Crop region ({cx},{cy},{cw},{ch}) exceeds "
                    f"image bounds ({img.width},{img.height})."
                )
            img = img.crop((cx, cy, cx + cw, cy + ch))
            logger.debug(f"Image cropped to: {img.width}x{img.height}")

        # Save if requested
        if save_path is not None:
            path = pathlib.Path(save_path)
            path.parent.mkdir(parents=True, exist_ok=True) # Ensure parent directory exists

            # Determine format from extension if not provided
            resolved_format = img_format
            if resolved_format is None and path.suffix:
                resolved_format = path.suffix[1:].upper()
            if not resolved_format: # Default to PNG if still no format
                resolved_format = "PNG"
                logger.debug(f"No image format specified and no extension found in save_path. Defaulting to {resolved_format}.")


            save_options = kwargs.copy()
            if optimize and resolved_format in ["PNG", "JPEG", "JPG"]:
                save_options["optimize"] = True
            if resolved_format in ["JPEG", "JPG"]:
                save_options["quality"] = quality

            img.save(path, format=resolved_format, **save_options)
            logger.info(f"Screenshot saved to: {path} (format: {resolved_format})")

        return img

    except Exception as e:
        logger.error(f"Screenshot capture failed: {e}", exc_info=True)
        if isinstance(e, (CaptureError, ValueError)):
            raise
        raise CaptureError(f"An unexpected error occurred during screenshot capture: {e}") from e

async def screenshot_async(
    bbox: BBox,
    **kwargs,
) -> Image.Image:
    """
    Asynchronous wrapper for screenshot capture.

    Uses asyncio.to_thread to avoid blocking the event loop.
    All parameters are identical to screenshot() and forwarded directly.

    Args:
        bbox: Window bounding box in screen coordinates.
        **kwargs: Additional arguments passed to screenshot().

    Returns:
        The captured PIL.Image.Image object.

    Raises:
        CaptureError: If screenshot capture fails.
    """
    logger.debug(f"Asynchronous screenshot requested for bbox: {bbox}")
    try:
        # Run the synchronous screenshot function in a separate thread
        return await asyncio.to_thread(screenshot, bbox, **kwargs)
    except Exception as e: # Catch any exception from the thread
        logger.error(f"Asynchronous screenshot failed: {e}", exc_info=True)
        # Re-raise as CaptureError or allow original exception type?
        # For consistency, let's wrap it if it's not already a CaptureError/ValueError.
        if isinstance(e, (CaptureError, ValueError)):
            raise
        raise CaptureError(f"Async screenshot task failed: {e}") from e

def capture_multiple_regions(
    regions: list[BBox],
    save_dir: pathlib.Path | None = None,
    img_format: str = "PNG",
) -> list[Image.Image]:
    """
    Captures screenshots of multiple regions.

    Args:
        regions: A list of BBox tuples to capture.
        save_dir: Optional directory to save screenshots.
                  Files will be named region_0.png, region_1.png, etc.
        img_format: Image format for saving (default: "PNG").

    Returns:
        A list of captured PIL.Image.Image objects.
    """
    if not regions:
        logger.info("No regions provided to capture_multiple_regions.")
        return []

    logger.info(f"Attempting to capture {len(regions)} regions.")
    captured_screenshots: list[Image.Image] = []

    for i, bbox in enumerate(regions):
        try:
            current_save_path = None
            if save_dir:
                save_dir.mkdir(parents=True, exist_ok=True)
                current_save_path = save_dir / f"region_{i}.{img_format.lower()}"

            img = screenshot(bbox, save_path=current_save_path, img_format=img_format)
            captured_screenshots.append(img)
        except Exception as e:
            # Log the error for the specific region but continue with others
            logger.error(f"Failed to capture region {i} (bbox: {bbox}): {e}", exc_info=True)

    logger.info(f"Successfully captured {len(captured_screenshots)}/{len(regions)} regions.")
    return captured_screenshots

def configure_pyautogui_performance(
    disable_fail_safe: bool = False,
    pause_duration: float = 0.0, # Default to 0.0 for potentially faster ops, was 0.1
) -> None:
    """
    Configures PyAutoGUI global performance settings.

    Args:
        disable_fail_safe: If True, disables the PyAutoGUI fail-safe mechanism
                           (moving mouse to a corner to abort). Use with caution.
        pause_duration: Duration in seconds to pause after each PyAutoGUI call.
                        Default is 0.0 (no pause).
    """
    import pyautogui # Local import
    if disable_fail_safe:
        logger.warning("Disabling PyAutoGUI fail-safe mechanism. Use with extreme caution.")
        pyautogui.FAILSAFE = False

    if pause_duration >= 0:
        pyautogui.PAUSE = pause_duration
        logger.info(f"PyAutoGUI PAUSE duration set to {pause_duration} seconds.")
    else:
        logger.warning(f"Invalid pause_duration ({pause_duration}) for PyAutoGUI. Must be non-negative.")