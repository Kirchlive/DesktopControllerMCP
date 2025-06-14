"""
MCP - Model Context Protocol
Core package initializer for DesktopControllerMCP-MCP.
"""
__version__ = "0.1.5" # Project version

import sys
import logging  # ✅ Standard logging import hinzugefügt

# Local imports - mit verbessertem Error Handling
try:
    from .logger import setup_logging, get_logger
except ImportError as e:
    # Fallback falls logger Import fehlschlägt
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    logger.warning(f"Failed to import custom logger: {e}. Using basic logging.")
    def setup_logging(level="INFO"): 
        logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO))
    def get_logger(name): 
        return logging.getLogger(name)

# Default logging setup.
# This will typically be overridden by main.py or mcp_server.py with specific configurations.
setup_logging(level="INFO")
_logger = get_logger(__name__)
_logger.info(f"Initializing MCP v{__version__} on Python {sys.version.split()[0]} ({sys.platform})")

# ✅ Windows DPI awareness - mit verbessertem Error Handling
if sys.platform == "win32":
    try:
        import ctypes
        # Constants for DPI awareness levels
        PROCESS_DPI_UNAWARE = 0
        PROCESS_SYSTEM_DPI_AWARE = 1
        PROCESS_PER_MONITOR_DPI_AWARE = 2

        awareness = ctypes.c_int()
        # Get current DPI awareness for the process
        result_get = ctypes.windll.shcore.GetProcessDpiAwareness(0, ctypes.byref(awareness))

        if result_get != 0:
            _logger.warning(f"Failed to get current DPI awareness. Error code: {result_get}")
        else:
            _logger.info(f"Current process DPI awareness value: {awareness.value}")
            # Set awareness to Per-Monitor DPI Aware if currently unaware
            if awareness.value == PROCESS_DPI_UNAWARE:
                ret_set = ctypes.windll.shcore.SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE)
                if ret_set == 0:  # S_OK
                    _logger.info("Process DPI awareness successfully set to PROCESS_PER_MONITOR_DPI_AWARE.")
                elif ret_set == ctypes.HRESULT(0x80070005).value:  # E_ACCESSDENIED
                    _logger.info("Failed to set DPI awareness: E_ACCESSDENIED. It might already be set by a manifest.")
                else:
                    _logger.warning(f"Failed to set DPI awareness. SetProcessDpiAwareness returned: {ret_set}")
            else:
                _logger.info("Process DPI awareness is already set (not UNAWARE). Skipping SetProcessDpiAwareness.")

    except ImportError:
        _logger.warning("ctypes library not available. Cannot manage DPI awareness settings.")
    except AttributeError:
        _logger.warning("shcore.SetProcessDpiAwareness or GetProcessDpiAwareness not found. "
                       "This might indicate an older Windows version.")
    except Exception as e:
        _logger.error(f"An unexpected error occurred during DPI awareness setup: {e}", exc_info=True)