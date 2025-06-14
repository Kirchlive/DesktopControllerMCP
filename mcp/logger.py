"""
logger.py - Centralized logging configuration for the MCP package.

This module provides a standardized way to set up and retrieve loggers
across the entire MCP application. Import `get_logger()` in other modules
instead of configuring logging manually.
"""

import logging
import sys
from pathlib import Path

# --- Type Hinting ---
# For Path | None, Python 3.10+ allows this directly.
# No complex type aliases needed here that would benefit hugely from `type` statement,
# but function signatures are updated.

# --- Global Configuration State ---
_LOGGING_CONFIGURED: bool = False
_DEFAULT_LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
_DEFAULT_LOG_LEVEL: int = logging.INFO

def setup_logging(
    level: int | str = _DEFAULT_LOG_LEVEL, # Allow string for level name e.g. "DEBUG"
    log_file: Path | str | None = None,
    format_string: str | None = None,
    force: bool = False
) -> None:
    """
    Configures logging for the entire MCP application.

    This should ideally be called once at application startup.
    Subsequent calls with `force=False` (default) will be ignored if
    logging has already been configured.

    Args:
        level: Logging level (e.g., logging.INFO, logging.DEBUG, or "INFO", "DEBUG").
        log_file: If provided, logs will also be written to this file.
                  Can be a Path object or a string path.
        format_string: Custom log format string. Defaults to a standard format.
        force: If True, reconfigure logging even if already configured.
    """
    global _LOGGING_CONFIGURED, _DEFAULT_LOG_LEVEL, _DEFAULT_LOG_FORMAT

    if _LOGGING_CONFIGURED and not force:
        # Logging already set up, and not forcing a re-configuration.
        return

    # Determine the logging level
    actual_level: int
    if isinstance(level, str):
        numeric_level = logging.getLevelName(level.upper())
        if isinstance(numeric_level, int):
            actual_level = numeric_level
        else:
            print(f"Warning: Invalid log level string '{level}'. Defaulting to INFO.", file=sys.stderr)
            actual_level = logging.INFO
    else:
        actual_level = level

    log_format_to_use = format_string if format_string is not None else _DEFAULT_LOG_FORMAT

    # Get the root logger
    root_logger = logging.getLogger()

    # Remove any existing handlers to prevent duplicate logs if re-configuring
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        handler.close() # Close handler before removing

    # Configure the console handler (always logs to sys.stdout)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(logging.Formatter(log_format_to_use))
    root_logger.addHandler(console_handler)

    # Configure the file handler (optional)
    if log_file:
        try:
            log_file_path = Path(log_file)
            log_file_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_file_path, mode='a') # Append mode
            file_handler.setFormatter(logging.Formatter(log_format_to_use))
            root_logger.addHandler(file_handler)
        except Exception as e:
            # If file logging setup fails, log to console and continue
            print(f"Warning: Failed to set up file logging for '{log_file}': {e}", file=sys.stderr)


    # Set the determined level on the root logger
    root_logger.setLevel(actual_level)

    # Optionally, reduce noise from verbose third-party libraries
    # These levels can be adjusted as needed.
    logging.getLogger("pyautogui").setLevel(logging.WARNING)
    logging.getLogger("PIL.PngImagePlugin").setLevel(logging.WARNING) # Example for PIL sub-logger
    # Add more third-party loggers here if they are too noisy
    # logging.getLogger("urllib3").setLevel(logging.WARNING)
    # logging.getLogger("asyncio").setLevel(logging.WARNING)

    _LOGGING_CONFIGURED = True
    # Use a temporary logger for this message if called before any get_logger()
    # or rely on the fact that root_logger is now configured.
    root_logger.info(f"Logging configured. Level: {logging.getLevelName(actual_level)}. Format: '{log_format_to_use}'")
    if log_file:
        root_logger.info(f"Logging to file: {Path(log_file).resolve()}")


def get_logger(name: str) -> logging.Logger:
    """
    Retrieves a logger instance for the given module name.

    Ensures consistent logger naming and configuration across the application.
    If logging hasn't been configured by `setup_logging` yet, this function
    will trigger a default setup.

    Args:
        name: Logger name, typically `__name__` of the calling module.

    Returns:
        A configured `logging.Logger` instance.

    Example:
        >>> from mcp.logger import get_logger
        >>> logger = get_logger(__name__)
        >>> logger.info("This is an informational message.")
    """
    if not _LOGGING_CONFIGURED:
        # Auto-configure with default settings if setup_logging wasn't called explicitly.
        # This is a fallback to ensure logging always works.
        print("Note: MCP logger auto-initialized with default settings because setup_logging() was not called explicitly.", file=sys.stderr)
        setup_logging()

    return logging.getLogger(name)

# Convenience functions (optional, but can be useful for very common patterns)
# These are not strictly necessary as one can use logger.debug(), logger.error() directly.

def log_debug(logger: logging.Logger, msg: str, *args, **kwargs) -> None:
    """Logs a debug message with lazy formatting if enabled."""
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(msg, *args, **kwargs)

def log_exception(logger: logging.Logger, msg: str, exc_info: bool = True) -> None:
    """Logs an error message with exception information."""
    # This is essentially what logger.error(msg, exc_info=True) does.
    # Kept for conceptual clarity if desired, but logger.error is standard.
    logger.error(msg, exc_info=exc_info)