"""
window.py – Cross-platform window management for CoreUI-MCP (v0.1.5).

Provides a unified interface for window operations (find, focus, get bounds, etc.)
across Windows, macOS, and potentially Linux (depending on backend capabilities).
Uses PyWinCtl as the primary backend, with PyGetWindow as a fallback.
"""
from __future__ import annotations # Good for type hints like `Window` in methods

import sys
import time
from dataclasses import dataclass
from typing import Protocol, runtime_checkable # For structural subtyping

# Local package imports
from mcp.logger import get_logger

logger = get_logger(__name__)

# --- Backend Initialization ---
# Attempt to import PyWinCtl (preferred, more feature-rich and cross-platform)
_active_backend_module: Any = None
_ACTIVE_BACKEND_NAME: str = "none"

try:
    import pywinctl # type: ignore[import-untyped]
    _active_backend_module = pywinctl
    _ACTIVE_BACKEND_NAME = "pywinctl"
    logger.info("Using 'pywinctl' backend for window management.")
except ImportError:
    logger.debug("'pywinctl' not found. Attempting to use 'pygetwindow' as a fallback.")
    try:
        import pygetwindow # type: ignore[import-untyped]
        _active_backend_module = pygetwindow
        _ACTIVE_BACKEND_NAME = "pygetwindow"
        logger.warning(
            "Using 'pygetwindow' as fallback backend for window management. "
            "Functionality may be limited, especially on non-Windows platforms."
        )
    except ImportError: # pragma: no cover
        critical_msg = (
            "CRITICAL: No supported window management backend (pywinctl or pygetwindow) found. "
            "Window management capabilities will be severely limited or unavailable. "
            "Please install one: 'pip install pywinctl' (recommended) or 'pip install pygetwindow'."
        )
        logger.critical(critical_msg)
        # Not raising an error here to allow parts of MCP to load if windowing is not critical,
        # but any attempt to use window functions will fail if _active_backend_module is None.

# --- Type Alias (using Python 3.12 'type' statement - PEP 695) ---
type BBox = tuple[int, int, int, int]  # (left, top, width, height) in screen coordinates.

# --- Custom Exception Classes ---
class WindowError(RuntimeError):
    """Base class for errors related to window operations."""
    pass

class WindowNotFoundError(WindowError):
    """Raised when a window matching the query cannot be located."""
    pass

class WindowOperationError(WindowError):
    """Raised when a window operation (e.g., activate, get_bounds) fails."""
    pass

class WindowBackendNotAvailableError(WindowError):
    """Raised when no suitable windowing backend (pywinctl/pygetwindow) is loaded."""
    pass

# --- Protocol for Window Backend Objects ---
# This protocol defines the common interface expected from pywinctl/pygetwindow window objects.
# @runtime_checkable allows isinstance() checks against this protocol.
@runtime_checkable
class WindowBackendInterface(Protocol):
    """
    Protocol defining the expected interface for underlying window objects
    from backends like pywinctl or pygetwindow.
    """
    # Properties
    @property
    def title(self) -> str: ...
    @property
    def left(self) -> int: ...
    @property
    def top(self) -> int: ...
    @property
    def width(self) -> int: ...
    @property
    def height(self) -> int: ...

    # Methods (some might be properties in one backend and methods in another)
    def activate(self) -> None: ...
    def close(self) -> None: ...
    def isActive(self) -> bool: ... # Can be a property or method
    def isAlive(self) -> bool: ... # Check if the window handle/object is still valid
    def isVisible(self) -> bool: ... # Check if window is visible (not minimized/hidden)

    # Optional methods/properties for window ID (can vary greatly)
    # PyWinCtl often has a 'getHandle()' or similar. PyGetWindow has 'hWnd' on Windows.
    # The Window class will try to access these through hasattr.


# --- Window Class ---
@dataclass(repr=False) # Custom __repr__ is provided
class Window:
    """
    A cross-platform wrapper for a desktop window, providing common operations.
    Instances should be created via factory functions like `get_window()` or `list_all_windows()`.
    """
    _window_impl: WindowBackendInterface # The actual backend window object (pywinctl/pygetwindow)
    _backend_name_used: str # Name of the backend ('pywinctl' or 'pygetwindow')

    def __post_init__(self):
        """Validates the window object after initialization."""
        if not self.is_alive():
            # Try to get title for error message, even if not alive, but handle failure
            title_for_error = "unknown or closed window"
            try:
                # Accessing self.title here would call the property, which itself calls is_alive
                # So, access the underlying implementation directly but safely
                if hasattr(self._window_impl, 'title') and self._window_impl.title:
                    title_for_error = f"'{self._window_impl.title}'"
            except Exception: # pragma: no cover
                pass # Keep default "unknown or closed window"
            raise WindowNotFoundError(
                f"Window handle for {title_for_error} is not valid or the window is closed. "
                "Cannot create Window object."
            )
        logger.debug(
            f"Window object created: title='{self.title}', "
            f"id={self.window_id}, backend='{self._backend_name_used}'"
        )

    @property
    def title(self) -> str:
        """Gets the window title. Returns 'Untitled Window' or 'Unknown Title' on error/empty."""
        if not self.is_alive(): return "Window Not Alive"
        try:
            # Backend's title property might return None or empty string
            win_title = self._window_impl.title
            return win_title.strip() if win_title and win_title.strip() else "Untitled Window"
        except Exception as e: # pragma: no cover (should be caught by is_alive generally)
            logger.warning(f"Failed to get window title (ID: {self.window_id}, Backend: {self._backend_name_used}): {e}")
            return "Unknown Title"

    @property
    def window_id(self) -> int | str | None:
        """
        Gets a native window handle/ID. Type and availability vary by platform and backend.
        Returns None if not retrievable.
        - Windows: Typically an integer HWND.
        - macOS: Can be an integer CGWindowID (from pywinctl) or more complex object.
        - Linux: Can be an integer XID (from pywinctl).
        """
        if not self.is_alive(): return None
        try:
            if self._backend_name_used == "pywinctl":
                # PyWinCtl's getHandle() is preferred if available
                if hasattr(self._window_impl, 'getHandle') and callable(self._window_impl.getHandle):
                    return self._window_impl.getHandle() # type: ignore
                # Fallbacks for common internal attributes in PyWinCtl
                elif hasattr(self._window_impl, '_hWnd'): # Windows
                    return self._window_impl._hWnd # type: ignore
                elif hasattr(self._window_impl, '_winID'): # macOS/Linux
                    return self._window_impl._winID # type: ignore
            elif self._backend_name_used == "pygetwindow":
                if sys.platform == "win32" and hasattr(self._window_impl, 'hWnd'): # Windows HWND
                    return self._window_impl.hWnd # type: ignore
                # PyGetWindow on macOS/Linux doesn't provide a simple integer ID easily.
                # It might wrap an object that can be stringified.
                # For now, return None or a string representation if possible.
                if hasattr(self._window_impl, 'id'): return self._window_impl.id # type: ignore
                return str(self._window_impl) # Fallback to string representation

            # Generic fallbacks (less reliable)
            for attr_name in ['id', '_id', 'handle', '_handle']:
                if hasattr(self._window_impl, attr_name):
                    return getattr(self._window_impl, attr_name)
            return None # No common ID attribute found
        except Exception as e: # pragma: no cover
            logger.warning(f"Failed to get window ID for title '{self.title}': {e}")
            return None

    @property
    def bbox(self) -> BBox:
        """
        Returns the window's bounding box (left, top, width, height) in screen coordinates.

        Raises:
            WindowOperationError: If bounds cannot be retrieved or are invalid.
        """
        if not self.is_alive():
            raise WindowOperationError(f"Cannot get bounds for non-alive window '{self.title}'.")
        try:
            # Ensure all components are integers and dimensions are positive
            left = int(self._window_impl.left)
            top = int(self._window_impl.top)
            width = int(self._window_impl.width)
            height = int(self._window_impl.height)

            if width <= 0 or height <= 0:
                raise WindowOperationError(
                    f"Window '{self.title}' (ID: {self.window_id}) has invalid dimensions: W={width}, H={height}. "
                    "Window might be minimized or in a strange state."
                )
            return (left, top, width, height)
        except AttributeError as e_attr: # Backend object missing a required geometry attribute
            logger.error(f"Backend '{self._backend_name_used}' is missing a geometry attribute for '{self.title}': {e_attr}")
            raise WindowOperationError(f"Cannot get window bounds for '{self.title}': Missing attribute in backend.") from e_attr
        except Exception as e: # Catch any other errors
            logger.error(f"Failed to get window bounds for '{self.title}': {e}", exc_info=True)
            raise WindowOperationError(f"Cannot get window bounds for '{self.title}': {e!s}") from e

    def activate(self, retries: int = 2, delay_s: float = 0.1) -> None:
        """
        Brings the window to the foreground and activates it.

        Args:
            retries: Number of attempts to activate and verify.
            delay_s: Delay in seconds between retries and after activation attempts.

        Raises:
            WindowOperationError: If activation fails after all retries.
        """
        if not self.is_alive():
            raise WindowOperationError(f"Cannot activate non-alive window: '{self.title}'.")

        logger.debug(f"Attempting to activate window '{self.title}' (ID: {self.window_id}). Retries: {retries}, Delay: {delay_s}s.")
        last_error: Exception | None = None

        for attempt in range(retries + 1):
            try:
                self._window_impl.activate() # Core activation call
                time.sleep(delay_s / 2) # Brief pause for OS to process

                if self.is_active(): # Verify activation
                    logger.info(f"Window '{self.title}' activated successfully (Attempt {attempt + 1}).")
                    return
                else: # pragma: no cover
                    logger.debug(f"Activation attempt {attempt + 1} for '{self.title}': isActive check returned False.")
                    # Some backends/OS might not reflect isActive immediately.
                    # If activate() itself doesn't raise, and no isActive, we might assume success.
                    if not (hasattr(self._window_impl, 'isActive') or hasattr(self._window_impl, 'is_active')):
                        logger.info(f"Window '{self.title}' activate() called (Attempt {attempt + 1}). No isActive check available, assuming success.")
                        return

            except Exception as e: # Catch errors from _window_impl.activate() or self.is_active()
                last_error = e
                logger.warning(f"Activation attempt {attempt + 1}/{retries+1} for '{self.title}' failed: {e!s}")

            if attempt < retries:
                logger.debug(f"Waiting {delay_s}s before next activation attempt for '{self.title}'.")
                time.sleep(delay_s)

        # If loop finishes without successful activation
        error_msg = f"Failed to activate window '{self.title}' after {retries + 1} attempts."
        if last_error:
            logger.error(f"{error_msg} Last error: {last_error!s}", exc_info=isinstance(last_error, Exception))
            raise WindowOperationError(error_msg) from last_error
        else: # pragma: no cover (should typically have last_error if all attempts fail)
            logger.error(error_msg + " No specific error reported by backend.")
            raise WindowOperationError(error_msg)

    def bring_to_front(self) -> None:
        """Alias for `activate()`."""
        self.activate()

    def is_alive(self) -> bool:
        """Checks if the window handle is still valid and the window likely exists."""
        if not hasattr(self._window_impl, 'isAlive'):
            # Fallback: If no direct isAlive, try accessing a basic property.
            # This is less reliable as it might raise other errors or give false positives.
            try:
                _ = self._window_impl.title # Accessing title might fail if not alive
                return True # If no error, assume it's somewhat alive
            except Exception:
                return False

        try:
            # FIX: isAlive is a property in pywinctl, not a method
            # Check if it's callable first, otherwise treat as property
            if callable(self._window_impl.isAlive):
                return bool(self._window_impl.isAlive())
            else:
                return bool(self._window_impl.isAlive)
        except Exception as e: # pragma: no cover (defensive against backend errors)
            logger.debug(f"Error checking is_alive for '{getattr(self._window_impl, 'title', 'unknown')}': {e!s}. Assuming not alive.")
            return False

    def is_active(self) -> bool:
        """Checks if the window is currently the active, foreground window."""
        if not self.is_alive(): return False
        try:
            if hasattr(self._window_impl, 'isActive'): # Common attribute/method name
                # It can be a property (pywinctl) or a method (pygetwindow)
                is_active_val = self._window_impl.isActive
                return is_active_val() if callable(is_active_val) else bool(is_active_val)
            elif hasattr(self._window_impl, 'is_active'): # Alternative common name
                 is_active_val = self._window_impl.is_active # type: ignore
                 return is_active_val() if callable(is_active_val) else bool(is_active_val)

            logger.debug(f"'isActive' check not directly available for '{self.title}' via backend '{self._backend_name_used}'.")
            return False # Cannot determine, assume not active
        except Exception as e: # pragma: no cover
            logger.warning(f"Could not determine 'isActive' status for '{self.title}': {e!s}. Assuming not active.")
            return False

    def is_visible(self) -> bool:
        """Checks if the window is currently visible (e.g., not minimized or hidden)."""
        if not self.is_alive(): return False
        try:
            if hasattr(self._window_impl, 'isVisible'): # pygetwindow method, pywinctl property
                is_visible_val = self._window_impl.isVisible
                return is_visible_val() if callable(is_visible_val) else bool(is_visible_val)
            elif hasattr(self._window_impl, 'visible'): # Common property name (pywinctl)
                return bool(self._window_impl.visible) # type: ignore

            # Fallback: if visibility cannot be determined, and it's alive, assume it *might* be visible.
            # This is a weak assumption.
            logger.debug(f"Visibility check not directly available for '{self.title}' via backend '{self._backend_name_used}'. Assuming visible if alive.")
            return True
        except Exception as e: # pragma: no cover
            logger.warning(f"Could not determine visibility for '{self.title}': {e!s}. Assuming not visible.")
            return False

    def close(self) -> None:
        """Attempts to close the window gracefully."""
        if not self.is_alive():
            logger.warning(f"Window '{self.title}' is already closed or not alive. Close operation skipped.")
            return

        logger.info(f"Attempting to close window '{self.title}' (ID: {self.window_id})")
        if hasattr(self._window_impl, 'close') and callable(self._window_impl.close):
            try:
                self._window_impl.close()
                # Wait briefly and check if it's actually closed
                time.sleep(0.2)
                if not self.is_alive():
                    logger.info(f"Window '{self.title}' closed successfully.")
                else: # pragma: no cover
                    logger.warning(f"Window '{self.title}' might not have closed after command (still alive).")
            except Exception as e:
                logger.error(f"Failed to close window '{self.title}': {e!s}", exc_info=True)
                raise WindowOperationError(f"Cannot close window '{self.title}': {e!s}") from e
        else:
            logger.error(f"Window close operation not supported by backend '{self._backend_name_used}' for window '{self.title}'.")
            raise NotImplementedError(
                f"Window close operation is not supported by the current backend ('{self._backend_name_used}')."
            )

    def __repr__(self) -> str:
        title_str = "ErrorGettingTitle"
        bbox_str = "N/A"
        alive_str = "Error"
        try: title_str = self.title # Use property to get processed title
        except: pass
        try: alive_str = str(self.is_alive())
        except: pass
        try:
            if self.is_alive(): # Only get bbox if alive to prevent errors
                bbox_val = self.bbox
                bbox_str = f"({bbox_val[0]},{bbox_val[1]} {bbox_val[2]}x{bbox_val[3]})"
        except: bbox_str = "ErrorGettingBBox"


        return (
            f"Window(title='{title_str}', id={self.window_id}, "
            f"bbox={bbox_str}, backend='{self._backend_name_used}', alive={alive_str})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Window):
            return NotImplemented
        # Equality based on the underlying implementation object and backend name.
        # This assumes backend window objects are comparable or have stable IDs.
        return (self._window_impl == other._window_impl and
                self._backend_name_used == other._backend_name_used)

    def __hash__(self) -> int:
        # Hashing based on the underlying implementation object.
        # This requires the backend window objects to be hashable.
        return hash((self._backend_name_used, self._window_impl))


# --- Factory Functions ---
def _ensure_backend_available() -> None:
    """Checks if a windowing backend is loaded, raises error if not."""
    if _active_backend_module is None:
        raise WindowBackendNotAvailableError(
            "No window management backend (pywinctl or pygetwindow) is loaded. "
            "Please install one of these libraries."
        )

def _find_window_impl(title: str | None = None, window_id: int | str | None = None) -> WindowBackendInterface:
    """
    Internal helper to find a single window using the active backend.
    Prioritizes visible and active windows if multiple matches occur for a title.
    """
    _ensure_backend_available()
    if not title and window_id is None: # Should be caught by public functions
        raise ValueError("Either title or window_id must be provided to _find_window_impl.")

    found_windows_backend: list[Any] = [] # List of raw backend window objects

    if _ACTIVE_BACKEND_NAME == "pywinctl":
        if title:
            # PyWinCtl's getWindowsWithTitle can return multiple matches
            found_windows_backend = _active_backend_module.getWindowsWithTitle(title) # type: ignore
        elif window_id is not None:
            # PyWinCtl's getWindowByHandle might be platform specific.
            # Iterate all windows and match ID is a more generic fallback.
            all_wins = _active_backend_module.getAllWindows() # type: ignore
            for w_impl in all_wins:
                try:
                    current_win_id = None
                    if hasattr(w_impl, 'getHandle') and callable(w_impl.getHandle): current_win_id = w_impl.getHandle()
                    elif hasattr(w_impl, '_hWnd') and w_impl._hWnd == window_id: current_win_id = w_impl._hWnd # Windows
                    elif hasattr(w_impl, '_winID') and w_impl._winID == window_id: current_win_id = w_impl._winID # macOS/Linux

                    if current_win_id == window_id:
                        found_windows_backend.append(w_impl)
                        break # Found by ID, usually unique
                except Exception:  # pragma: no cover
                    continue # Skip windows we can't get a comparable ID for
    elif _ACTIVE_BACKEND_NAME == "pygetwindow":
        if title:
            found_windows_backend = _active_backend_module.getWindowsWithTitle(title) # type: ignore
        elif window_id is not None: # pragma: no cover (pygetwindow has limited find-by-ID)
            logger.warning(f"Finding by raw window_id ({window_id}) with 'pygetwindow' backend is less reliable.")
            if sys.platform == "win32" and isinstance(window_id, int):
                # Try to find by HWND if on Windows
                try:
                    win_by_hwnd = _active_backend_module.Win32Window(window_id) # type: ignore
                    if win_by_hwnd and hasattr(win_by_hwnd, 'title'): # Check if it's a valid window object
                         found_windows_backend.append(win_by_hwnd)
                except Exception: # pygetwindow raises if HWND not found or invalid
                    pass # Will be caught by "No window found" later
            else: # No standard way for pygetwindow on other platforms by ID
                logger.debug(f"Direct find by window_id ({window_id}) with pygetwindow on {sys.platform} is not supported. Iterating all windows.")
                # Fallback: Iterate all and try to match (less efficient)
                all_wins_pgw = _active_backend_module.getAllWindows() # type: ignore
                for w_pgw_impl in all_wins_pgw:
                    # This is very speculative as pygetwindow doesn't expose a consistent ID easily
                    if hasattr(w_pgw_impl, 'id') and w_pgw_impl.id == window_id:
                        found_windows_backend.append(w_pgw_impl)
                        break
                    # Could try str(w_pgw_impl) if window_id is a string, but highly unreliable

    if not found_windows_backend:
        criteria = f"title containing '{title}'" if title else f"ID '{window_id}'"
        raise WindowNotFoundError(f"No window found matching {criteria} using backend '{_ACTIVE_BACKEND_NAME}'.")

    # Filter for "alive" windows first (using a temporary Window wrapper for its is_alive)
    # This is a bit circular, but necessary if the backend objects themselves don't robustly report aliveness before wrapping.
    alive_backend_windows: list[WindowBackendInterface] = []
    for w_impl_raw in found_windows_backend:
        try:
            # Check if the raw object itself has an isAlive method/property
            if hasattr(w_impl_raw, 'isAlive'):
                is_alive_val = w_impl_raw.isAlive
                if callable(is_alive_val):
                    if is_alive_val(): alive_backend_windows.append(w_impl_raw)
                elif bool(is_alive_val):
                    alive_backend_windows.append(w_impl_raw)
            else: # If no direct isAlive, assume it's alive for now if backend returned it
                alive_backend_windows.append(w_impl_raw)
        except Exception: # pragma: no cover
            logger.debug(f"Error checking raw aliveness for potential window '{getattr(w_impl_raw, 'title', 'unknown')}', skipping.")
            continue

    if not alive_backend_windows:
        criteria = f"title containing '{title}'" if title else f"ID '{window_id}'"
        raise WindowNotFoundError(f"No *alive* window found matching {criteria}. (Original matches might be closed).")

    # Prefer visible and then active windows from the alive ones
    best_match: WindowBackendInterface | None = None
    # Score: 2 for active&visible, 1 for visible, 0 for others
    current_best_score = -1

    for w_impl_alive in alive_backend_windows:
        is_vis = False
        is_act = False
        try:
            if hasattr(w_impl_alive, 'isVisible'): # Method or property
                val = w_impl_alive.isVisible
                is_vis = val() if callable(val) else bool(val)
            elif hasattr(w_impl_alive, 'visible'): # Property
                is_vis = bool(w_impl_alive.visible) # type: ignore
            else: # Assume visible if no check available but alive
                is_vis = True

            if is_vis and hasattr(w_impl_alive, 'isActive'): # Method or property
                val = w_impl_alive.isActive
                is_act = val() if callable(val) else bool(val)
            elif is_vis and hasattr(w_impl_alive, 'is_active'): # Alternative
                val = w_impl_alive.is_active # type: ignore
                is_act = val() if callable(val) else bool(val)


            score = (2 if is_act and is_vis else 1 if is_vis else 0)

            if score > current_best_score:
                current_best_score = score
                best_match = w_impl_alive
                if score == 2: break # Active and visible is the best we can get

        except Exception: # pragma: no cover
            logger.debug(f"Error checking visibility/activity for '{getattr(w_impl_alive, 'title', 'unknown')}', skipping in preference logic.")
            continue

    if best_match:
        logger.debug(f"Selected best match: '{getattr(best_match, 'title', 'N/A')}' with score {current_best_score}")
        return best_match # type: ignore
    else: # Should not happen if alive_backend_windows is not empty
        logger.debug("No best match found after filtering, returning first alive (should be one).")
        return alive_backend_windows[0] # type: ignore


def get_window(*, title: str | None = None, window_id: int | str | None = None) -> Window:
    """
    Gets a `Window` handle by its title (substring match) or native window ID.
    If multiple windows match a title, it prioritizes active and visible ones.

    Args:
        title: Substring of the window title to search for. Case-sensitive.
        window_id: Native window handle/ID (e.g., HWND on Windows, CGWindowID on macOS, XID on Linux).
                   Type can be int or str depending on platform/backend.

    Returns:
        A `Window` object representing the found window.

    Raises:
        ValueError: If neither 'title' nor 'window_id' is provided.
        TypeError: If 'title' is not a string or 'window_id' is not int/str (basic check).
        WindowNotFoundError: If no matching window is found.
        WindowBackendNotAvailableError: If no windowing backend is loaded.
        WindowOperationError: For other unexpected errors during the process.
    """
    if title is None and window_id is None:
        raise ValueError("Either 'title' or 'window_id' must be provided to get_window.")
    if title is not None and not isinstance(title, str):
         raise TypeError(f"'title' must be a string if provided, got {type(title)}.")
    if window_id is not None and not isinstance(window_id, (int, str)): # Allow str for some platform IDs
         raise TypeError(f"'window_id' must be an int or string if provided, got {type(window_id)}.")

    _ensure_backend_available() # Checks if _active_backend_module is loaded
    logger.debug(f"Attempting to get window: title='{title}', window_id={window_id}, backend='{_ACTIVE_BACKEND_NAME}'")

    try:
        # _find_window_impl returns the raw backend window object
        backend_window_obj = _find_window_impl(title=title, window_id=window_id)
        # Wrap it in our Window class
        return Window(_window_impl=backend_window_obj, _backend_name_used=_ACTIVE_BACKEND_NAME)
    except (WindowNotFoundError, WindowBackendNotAvailableError, ValueError, TypeError):
        raise # Re-raise specific known errors
    except Exception as e: # Catch any other unexpected error from backend or internal logic
        criteria = f"title='{title}'" if title else f"window_id={window_id}"
        logger.error(f"Unexpected error getting window ({criteria}): {e!s}", exc_info=True)
        raise WindowOperationError(f"Failed to get window ({criteria}): An unexpected error occurred - {e!s}") from e


def list_all_windows() -> list[Window]:
    """
    Lists all currently available windows wrapped in CoreUI-MCP's `Window` objects.
    Filters out windows that are not "alive" or cause errors during basic property access.

    Returns:
        A list of `Window` objects.

    Raises:
        WindowBackendNotAvailableError: If no windowing backend is loaded.
        WindowOperationError: For other unexpected errors during enumeration.
    """
    _ensure_backend_available()
    logger.debug(f"Listing all windows using backend '{_ACTIVE_BACKEND_NAME}'...")

    try:
        # _active_backend_module.getAllWindows() is common to pywinctl and pygetwindow
        raw_backend_windows = _active_backend_module.getAllWindows() # type: ignore
    except Exception as e: # pragma: no cover (if the backend's getAllWindows itself fails)
        logger.error(f"Backend '{_ACTIVE_BACKEND_NAME}' failed during getAllWindows(): {e!s}", exc_info=True)
        raise WindowOperationError(f"Cannot list windows using '{_ACTIVE_BACKEND_NAME}': {e!s}") from e

    mcp_windows: list[Window] = []
    if raw_backend_windows:
        for w_impl_raw in raw_backend_windows:
            try:
                # Attempt to wrap each backend window object.
                # The Window constructor itself calls is_alive and will raise WindowNotFoundError
                # if the window is not considered valid/alive.
                mcp_windows.append(Window(_window_impl=w_impl_raw, _backend_name_used=_ACTIVE_BACKEND_NAME))
            except WindowNotFoundError: # pragma: no cover (Window is not alive, skip it)
                title_for_log = "unknown"
                try: title_for_log = f"'{getattr(w_impl_raw, 'title', 'N/A')}'"
                except: pass
                logger.debug(f"Skipping non-alive or invalid window object {title_for_log} during list_all_windows.")
            except Exception as e_wrap: # pragma: no cover (Other error during wrapping a specific window)
                title_for_log = "unknown"
                try: title_for_log = f"'{getattr(w_impl_raw, 'title', 'N/A')}'"
                except: pass
                logger.warning(f"Could not wrap window object {title_for_log} due to error: {e_wrap!s}")

    logger.info(f"Found {len(mcp_windows)} valid and accessible windows.")
    return mcp_windows

def screenshot_window(window_id: int | str | None = None, title: str | None = None) -> bytes:
    """
    Takes a screenshot of a specific window or the entire screen.

    Args:
        window_id: Optional native window handle/ID to screenshot.
        title: Optional window title substring to match (used if window_id is not provided).

    Returns:
        A bytes object containing the screenshot image in PNG format.

    Raises:
        WindowNotFoundError: If no window matches the given criteria.
        WindowBackendNotAvailableError: If no windowing backend is loaded.
        WindowOperationError: For other unexpected errors during screenshot.
    """
    import PIL.ImageGrab  # Python's cross-platform screenshot library
    import io
    import PIL.Image

    logger.debug(f"Screenshot request: window_id={window_id}, title={title}")

    if window_id is None and title is None:
        # Entire screen screenshot
        logger.info("Taking screenshot of entire screen.")
        screenshot = PIL.ImageGrab.grab()
        # Save to memory
        img_byte_arr = io.BytesIO()
        screenshot.save(img_byte_arr, format='PNG')
        return img_byte_arr.getvalue()

    # Find specific window
    try:
        window = get_window(window_id=window_id, title=title)
        bbox = window.bbox  # This will raise error if window is not alive

        logger.info(f"Taking screenshot of window: {window.title}")
        screenshot = PIL.ImageGrab.grab(bbox=bbox)
        
        # Save to memory
        img_byte_arr = io.BytesIO()
        screenshot.save(img_byte_arr, format='PNG')
        return img_byte_arr.getvalue()

    except Exception as e:
        logger.error(f"Screenshot failed: {e!s}", exc_info=True)
        raise WindowOperationError(f"Screenshot failed: {e!s}") from e