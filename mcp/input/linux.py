"""
linux.py – Linux low-level input backend (v0.1.5).

This backend provides input control for Linux systems, differentiating
between X11 and Wayland sessions.

For X11 sessions:
  - Prioritizes 'xdotool' command-line utility if available.
  - Falls back to 'pynput' if 'xdotool' is not found or functional.

For Wayland sessions:
  - Uses 'pynput'. Global input control under Wayland is heavily
    restricted for security reasons; functionality to control other
    applications may be limited or fail.

Features:
* ``move(point)``: Moves the mouse cursor.
* ``click(point, button)``: Simulates a mouse click.
* ``mousedown(point, button)``: Presses and holds a mouse button.
* ``mouseup(point, button)``: Releases a mouse button.
* ``drag(start_point, end_point, button, duration)``: Drags the mouse.
* ``scroll(dx, dy)``: Simulates mouse wheel scrolling.
* ``keydown(key_spec)`` / ``keyup(key_spec)`` / ``press(key_spec)``: Simulates key events.
* ``type_text(text)``: Simulates typing of Unicode text.

Key event `key_spec` types depend on the active mechanism:
  - xdotool: Expects X11 Keysym strings (e.g., "ctrl+l", "Return", "a", "Shift_L+A").
  - pynput: Expects pynput.keyboard.Key enums, pynput.keyboard.KeyCode objects,
            or single character strings.
"""
from __future__ import annotations # For type hints like Optional from older Python

import os
import subprocess
import sys
import threading
import time
from typing import Tuple, Any, Optional # For Python < 3.9 tuple, any, optional

# Assuming mcp.logger is correctly set up in the project structure
from mcp.logger import get_logger

logger = get_logger(__name__)

if not sys.platform.startswith("linux"): # pragma: no cover
    raise RuntimeError("linux.py input backend loaded on a non-Linux platform.")

# --- Global Variables for Backend State and Controllers ---
_initialized: bool = False
_initialization_lock = threading.Lock() # Ensures _initialize_backend runs once

_session_type: Optional[str] = None  # "x11", "wayland", or "unknown"
_xdotool_path: Optional[str] = None  # Path to xdotool executable if found

_mouse_controller_pynput: Optional[Any] = None # pynput.mouse.Controller instance
_keyboard_controller_pynput: Optional[Any] = None # pynput.keyboard.Controller instance
_pynput_available: bool = False

# Attempt to import pynput components
try:
    from pynput.mouse import Button as PyMouseButton, Controller as MouseController
    from pynput.keyboard import Key as PyKey, KeyCode as PyKeyCode, Controller as KeyboardController
    _pynput_available = True
except ImportError:  # pragma: no cover
    logger.warning(
        "pynput library not found. Linux input backend functionality via pynput will be unavailable. "
        "Please install pynput (e.g., `pip install pynput`)."
    )
    # Define dummy classes if pynput is not available to prevent NameErrors later
    # This allows the module to load, but pynput-dependent functions will effectively be no-ops.
    class PyMouseButton: left=None; right=None; middle=None # type: ignore[no-redef]
    class PyKey: pass # type: ignore[no-redef]
    class PyKeyCode: # type: ignore[no-redef]
        @staticmethod
        def from_char(char_val: str): return None


# --- Mappings for Button Names ---
_PYNPUT_BUTTON_MAP = {
    "left": PyMouseButton.left if _pynput_available else "left_str_dummy",
    "right": PyMouseButton.right if _pynput_available else "right_str_dummy",
    "middle": PyMouseButton.middle if _pynput_available else "middle_str_dummy",
}
_XDOTOOL_BUTTON_MAP = {"left": "1", "middle": "2", "right": "3"}


# --- Initialization and Helper Functions ---
def _check_xdotool() -> Optional[str]:
    """Checks if xdotool is installed and functional, returns its path if so."""
    try:
        # 'which' command finds the executable in PATH
        proc_which = subprocess.run(["which", "xdotool"], capture_output=True, text=True, check=False)
        if proc_which.returncode == 0 and proc_which.stdout.strip():
            path_to_xdotool = proc_which.stdout.strip()
            # Verify it's somewhat functional by calling --version
            subprocess.run([path_to_xdotool, "--version"], capture_output=True, text=True, check=True, timeout=1)
            logger.info(f"xdotool executable found and verified at: {path_to_xdotool}")
            return path_to_xdotool
        logger.info("xdotool not found in PATH using 'which'.")
        return None
    except FileNotFoundError: # 'which' command itself not found
        logger.info("'which' command not found. Cannot locate xdotool this way.")
        return None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        logger.warning(f"xdotool was found but failed basic version check: {e}. Marking as unavailable.")
        return None
    except Exception as e_general: # Catch any other unexpected error
        logger.error(f"Unexpected error during xdotool check: {e_general}")
        return None


def _initialize_backend() -> None:
    """
    Initializes the Linux input backend.
    Detects session type (X11/Wayland), checks for xdotool, and initializes pynput controllers.
    This function is thread-safe and ensures initialization happens only once.
    """
    global _initialized, _session_type, _xdotool_path
    global _mouse_controller_pynput, _keyboard_controller_pynput, _pynput_available

    if _initialized:
        return

    with _initialization_lock:
        if _initialized: # Double-check after acquiring lock
            return

        logger.info("Initializing Linux input backend (v0.1.5)...")

        # 1. Determine session type (X11 or Wayland)
        _session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
        if not _session_type: # Fallback if XDG_SESSION_TYPE is not set
            if os.environ.get("WAYLAND_DISPLAY"):
                _session_type = "wayland"
            elif os.environ.get("DISPLAY"): # Common for X11
                _session_type = "x11"
            else:
                _session_type = "unknown" # Unable to determine
        logger.info(f"Detected desktop session type: '{_session_type}'")

        # 2. Check for xdotool if in an X11 session
        if _session_type == "x11":
            _xdotool_path = _check_xdotool()
            if not _xdotool_path:
                logger.warning("xdotool not found or not functional. "
                               "Will attempt to use pynput as a fallback for X11 input.")
        else:
            logger.info("Not an X11 session (or unknown), xdotool check skipped.")


        # 3. Initialize pynput controllers (if pynput was imported successfully)
        if _pynput_available:
            try:
                _mouse_controller_pynput = MouseController()
                _keyboard_controller_pynput = KeyboardController()
                logger.info("pynput mouse and keyboard controllers initialized successfully.")
            except Exception as e_pynput_init:  # pragma: no cover
                # This can happen if, e.g., no X server is running and pynput needs one.
                logger.error(f"Failed to initialize pynput controllers: {e_pynput_init}. "
                             "pynput-based input will not be available.")
                _pynput_available = False # Mark pynput as unusable
        else:
            # Warning about pynput not being imported was already logged.
            pass

        _initialized = True
        logger.info("Linux input backend initialization complete.")
        if _session_type == "wayland" and _pynput_available:
            logger.warning("WAYLAND SESSION: Global input control via pynput is highly restricted "
                           "and may not affect other applications due to security policies.")


def _run_xdotool_command(command_args: list[str]) -> bool:
    """Helper function to execute an xdotool command."""
    if not _xdotool_path: # Should be checked before calling
        logger.error("Attempted to run xdotool command, but xdotool path is not configured.")
        return False
    try:
        full_command = [_xdotool_path] + command_args
        logger.debug(f"Executing xdotool command: {' '.join(full_command)}")
        # Using short timeout as input commands should be quick.
        # capture_output=True helps in debugging if xdotool prints errors to stderr.
        result = subprocess.run(full_command, check=True, capture_output=True, text=True, timeout=2.0)
        if result.stderr: # Log stderr even on success, as it might contain warnings
            logger.debug(f"xdotool stderr (command: {' '.join(command_args)}): {result.stderr.strip()}")
        return True
    except FileNotFoundError: # Should be caught by _check_xdotool, but defense-in-depth
        logger.error(f"xdotool command failed: Executable '{_xdotool_path}' not found during execution.")
        return False
    except subprocess.CalledProcessError as e_called:
        error_output = e_called.stderr.strip() if e_called.stderr else "No stderr output."
        logger.error(f"xdotool command failed with exit code {e_called.returncode} "
                     f"(Command: {' '.join(command_args)}): {error_output}")
        return False
    except subprocess.TimeoutExpired:
        logger.error(f"xdotool command timed out: {' '.join(command_args)}")
        return False
    except Exception as e_general: # Catch any other unexpected error
        logger.error(f"Unexpected error running xdotool command {' '.join(command_args)}: {e_general}")
        return False

# --- Public Mouse API ---
def mousedown(point: tuple[int, int], button: str = "left") -> None:
    _initialize_backend()
    btn_key = button.lower()
    x_coord, y_coord = int(point[0]), int(point[1])

    if _session_type == "x11" and _xdotool_path:
        xdotool_btn_code = _XDOTOOL_BUTTON_MAP.get(btn_key, "1") # Default to left click
        # xdotool 'mousedown' does not move the cursor, so move it first.
        if _run_xdotool_command(["mousemove", str(x_coord), str(y_coord)]):
            if not _run_xdotool_command(["mousedown", xdotool_btn_code]):
                logger.warning("xdotool mousedown command failed. Attempting pynput fallback if available.")
                if _mouse_controller_pynput: # Fallback for mousedown
                    try:
                        _mouse_controller_pynput.position = (x_coord, y_coord)
                        _mouse_controller_pynput.press(_PYNPUT_BUTTON_MAP.get(btn_key))
                    except Exception as e_fb: logger.error(f"pynput mousedown fallback failed: {e_fb}")
        else: # xdotool mousemove failed
            logger.warning("xdotool mousemove (before mousedown) failed. Pynput fallback not attempted for this sequence.")

    elif _mouse_controller_pynput:
        logger.debug(f"Using pynput for mousedown: {btn_key} at ({x_coord},{y_coord})")
        try:
            _mouse_controller_pynput.position = (x_coord, y_coord)
            _mouse_controller_pynput.press(_PYNPUT_BUTTON_MAP.get(btn_key))
        except Exception as e: logger.error(f"pynput mousedown failed: {e}")
    else:
        logger.error("No available input mechanism (xdotool or pynput) for mousedown.")


def mouseup(point: tuple[int, int], button: str = "left") -> None:
    _initialize_backend()
    btn_key = button.lower()
    x_coord, y_coord = int(point[0]), int(point[1]) # Ensure integer coords

    if _session_type == "x11" and _xdotool_path:
        xdotool_btn_code = _XDOTOOL_BUTTON_MAP.get(btn_key, "1")
        # It's good practice to ensure the mouse is at the release point, though xdotool mouseup
        # itself doesn't typically require current position if a previous mousedown set the target.
        if _run_xdotool_command(["mousemove", str(x_coord), str(y_coord)]): # Optional: ensure position
            if not _run_xdotool_command(["mouseup", xdotool_btn_code]):
                logger.warning("xdotool mouseup command failed. Attempting pynput fallback if available.")
                if _mouse_controller_pynput: # Fallback for mouseup
                    try:
                        _mouse_controller_pynput.position = (x_coord, y_coord)
                        _mouse_controller_pynput.release(_PYNPUT_BUTTON_MAP.get(btn_key))
                    except Exception as e_fb: logger.error(f"pynput mouseup fallback failed: {e_fb}")
        else:
             logger.warning("xdotool mousemove (before mouseup) failed.")


    elif _mouse_controller_pynput:
        logger.debug(f"Using pynput for mouseup: {btn_key} at ({x_coord},{y_coord})")
        try:
            _mouse_controller_pynput.position = (x_coord, y_coord) # Ensure position for release
            _mouse_controller_pynput.release(_PYNPUT_BUTTON_MAP.get(btn_key))
        except Exception as e: logger.error(f"pynput mouseup failed: {e}")
    else:
        logger.error("No available input mechanism (xdotool or pynput) for mouseup.")


def move(point: tuple[int, int]) -> None:
    _initialize_backend()
    x_coord, y_coord = int(point[0]), int(point[1])

    if _session_type == "x11" and _xdotool_path:
        if not _run_xdotool_command(["mousemove", str(x_coord), str(y_coord)]):
            logger.warning("xdotool mousemove failed. Attempting pynput fallback if available.")
            if _mouse_controller_pynput: # Fallback
                try: _mouse_controller_pynput.position = (x_coord, y_coord)
                except Exception as e_fb: logger.error(f"pynput mouse move fallback failed: {e_fb}")
    elif _mouse_controller_pynput:
        logger.debug(f"Using pynput for move to ({x_coord},{y_coord})")
        try: _mouse_controller_pynput.position = (x_coord, y_coord)
        except Exception as e: logger.error(f"pynput mouse move failed: {e}")
    else:
        logger.error("No available input mechanism (xdotool or pynput) for move.")


def click(point: tuple[int, int], button: str = "left") -> None:
    _initialize_backend()
    btn_key = button.lower()
    x_coord, y_coord = int(point[0]), int(point[1])

    if _session_type == "x11" and _xdotool_path:
        xdotool_btn_code = _XDOTOOL_BUTTON_MAP.get(btn_key, "1")
        # xdotool 'click' command sequence usually includes a mousemove to the target.
        # However, ensuring position first with a separate mousemove can be more explicit.
        # The command `xdotool mousemove x y click button_code` does this in one go.
        if not _run_xdotool_command(["mousemove", str(x_coord), str(y_coord), "click", xdotool_btn_code]):
            logger.warning("xdotool click command failed. Attempting pynput fallback if available.")
            if _mouse_controller_pynput: # Fallback
                try:
                    _mouse_controller_pynput.position = (x_coord, y_coord)
                    _mouse_controller_pynput.click(_PYNPUT_BUTTON_MAP.get(btn_key), 1) # 1 click
                except Exception as e_fb: logger.error(f"pynput click fallback failed: {e_fb}")
    elif _mouse_controller_pynput:
        logger.debug(f"Using pynput for click: {btn_key} at ({x_coord},{y_coord})")
        try:
            _mouse_controller_pynput.position = (x_coord, y_coord)
            _mouse_controller_pynput.click(_PYNPUT_BUTTON_MAP.get(btn_key), 1)
        except Exception as e: logger.error(f"pynput click failed: {e}")
    else:
        logger.error("No available input mechanism (xdotool or pynput) for click.")


def drag(start_point: tuple[int, int], end_point: tuple[int, int], button: str = "left", duration: float = 0.5) -> None:
    _initialize_backend()
    # Note: xdotool has 'mousemove_relative --sync x y' and can chain mousedown/mouseup.
    # For simplicity and consistency with other backends, we use interpolated moves.
    # This means `move` will be called repeatedly, which internally handles xdotool/pynput.

    move(start_point)
    time.sleep(0.05) # Ensure move is processed
    mousedown(start_point, button) # Uses our mousedown, which handles xdotool/pynput
    time.sleep(0.05) # Ensure mousedown is processed

    if duration <= 0:
        move(end_point) # Move directly if no duration
    else:
        start_x, start_y = start_point
        end_x, end_y = end_point
        num_steps = max(2, int(duration / 0.02)) # Aim for ~50 FPS for smooth drag
        time_per_step = duration / num_steps

        for i in range(num_steps + 1): # Include the end_point
            ratio = i / num_steps
            current_x = int(start_x + (end_x - start_x) * ratio)
            current_y = int(start_y + (end_y - start_y) * ratio)
            # `move` will use the best available backend (xdotool or pynput)
            # For xdotool, `mousemove` works even if a button is held.
            # For pynput, setting `.position` while a button is held results in a drag.
            move((current_x, current_y))
            if i < num_steps:
                time.sleep(time_per_step)
    
    time.sleep(0.05) # Ensure final move/drag is processed
    mouseup(end_point, button) # Uses our mouseup


def scroll(dx: int, dy: int) -> None:
    _initialize_backend()
    if dx == 0 and dy == 0:
        return # Nothing to scroll

    if _session_type == "x11" and _xdotool_path:
        logger.debug(f"Scrolling dx={dx}, dy={dy} using xdotool.")
        # xdotool uses button clicks for scrolling: 4=up, 5=down, 6=left, 7=right.
        # Convert dx/dy units into a sequence of these button clicks.
        commands_to_run: list[list[str]] = []
        if dy < 0: # Scroll Up (dy is negative)
            for _ in range(abs(dy)): commands_to_run.append(["click", "4"])
        elif dy > 0: # Scroll Down (dy is positive)
            for _ in range(abs(dy)): commands_to_run.append(["click", "5"])
        
        if dx < 0: # Scroll Left (dx is negative)
            for _ in range(abs(dx)): commands_to_run.append(["click", "6"])
        elif dx > 0: # Scroll Right (dx is positive)
            for _ in range(abs(dx)): commands_to_run.append(["click", "7"])
        
        all_succeeded = True
        for cmd_args in commands_to_run:
            if not _run_xdotool_command(cmd_args):
                all_succeeded = False # Mark failure but try all scroll steps
            time.sleep(0.01) # Small delay between individual scroll "clicks"

        if not all_succeeded and _mouse_controller_pynput:
             logger.warning("One or more xdotool scroll commands failed. Attempting pynput fallback.")
             try: _mouse_controller_pynput.scroll(dx, dy)
             except Exception as e_fb: logger.error(f"pynput scroll fallback also failed: {e_fb}")
        elif not all_succeeded:
             logger.error("xdotool scroll failed and pynput fallback not available/failed.")

    elif _mouse_controller_pynput:
        logger.debug(f"Scrolling dx={dx}, dy={dy} using pynput.")
        try:
            _mouse_controller_pynput.scroll(dx, dy) # pynput handles dx, dy directly
        except Exception as e:  # pragma: no cover (pynput errors can be varied)
            logger.error(f"pynput scroll(dx={dx}, dy={dy}) failed: {e}")
    else:
        logger.error("No available input mechanism (xdotool or pynput) for scroll.")


# --- Public Keyboard API ---
def _handle_key_event(key_spec: Any, action: str) -> None: # action: "down", "up", or "press"
    """Internal helper to dispatch key events to xdotool or pynput."""
    _initialize_backend()

    if _session_type == "x11" and _xdotool_path:
        if not isinstance(key_spec, str):
            logger.error(f"xdotool key action ('{action}') expects a string Keysym "
                         f"(e.g., 'Control_L', 'a', 'Return'), but got type {type(key_spec)}: '{key_spec}'. Action aborted.")
            return
        logger.debug(f"Performing key {action} for Keysym '{key_spec}' using xdotool.")
        # Determine xdotool command based on action
        xdotool_cmd = "key" # For 'press' (down+up)
        if action == "down": xdotool_cmd = "keydown"
        elif action == "up": xdotool_cmd = "keyup"
        _run_xdotool_command([xdotool_cmd, key_spec])
    elif _keyboard_controller_pynput:
        logger.debug(f"Performing key {action} for key_spec '{key_spec}' using pynput.")
        try:
            if action == "down": _keyboard_controller_pynput.press(key_spec)
            elif action == "up": _keyboard_controller_pynput.release(key_spec)
            elif action == "press":
                _keyboard_controller_pynput.press(key_spec)
                time.sleep(0.01) # Small delay for distinct events
                _keyboard_controller_pynput.release(key_spec)
        except Exception as e:  # pragma: no cover (pynput can raise various errors)
            logger.error(f"pynput key {action} for key_spec '{key_spec}' failed: {e}")
    else:
        logger.error(f"No available input mechanism (xdotool or pynput) for key {action}.")


def keydown(key_spec: Any) -> None:
    """Simulates pressing a key (key down event)."""
    _handle_key_event(key_spec, "down")

def keyup(key_spec: Any) -> None:
    """Simulates releasing a key (key up event)."""
    _handle_key_event(key_spec, "up")

def press(key_spec: Any) -> None:
    """Simulates a full key press (key down followed by key up)."""
    _handle_key_event(key_spec, "press")

def type_text(text: str) -> None:
    """Simulates typing of an arbitrary Unicode string."""
    _initialize_backend()
    if not isinstance(text, str):
        logger.error(f"type_text expects a string argument, but got {type(text)}. Action aborted.")
        return

    if _session_type == "x11" and _xdotool_path:
        logger.debug(f"Typing text (first 20 chars: '{text[:20]}...') using xdotool.")
        # '--clearmodifiers' helps ensure stray modifiers don't affect typing.
        # '--delay' can be added if typing is too fast for some applications.
        _run_xdotool_command(["type", "--clearmodifiers", text])
    elif _keyboard_controller_pynput:
        logger.debug(f"Typing text (first 20 chars: '{text[:20]}...') using pynput.")
        try:
            _keyboard_controller_pynput.type(text)
        except Exception as e:  # pragma: no cover
            logger.error(f"pynput type_text failed: {e}")
    else:
        logger.error("No available input mechanism (xdotool or pynput) for type_text.")

# --- Test Block (for direct execution of this file) ---
if __name__ == "__main__":  # pragma: no cover
    # This test block helps in verifying the functionality directly.
    # It's crucial to run this in the target Linux environment.
    print(f"--- Linux Input Backend Test (v0.1.5) ---")
    _initialize_backend() # Explicitly initialize for test run
    print(f"Test Environment Configuration:")
    print(f"  Session Type: {_session_type or 'Not Determined'}")
    print(f"  xdotool Path: {_xdotool_path or 'Not Found / Not Used'}")
    print(f"  pynput Available: {_pynput_available}")
    print(f"  pynput Mouse Controller: {'Initialized' if _mouse_controller_pynput else 'Not Initialized'}")
    print(f"  pynput Keyboard Controller: {'Initialized' if _keyboard_controller_pynput else 'Not Initialized'}")
    print("-----------------------------------------------------")

    if not ((_session_type == "x11" and _xdotool_path) or _pynput_available):
        print("CRITICAL: No functional input mechanism (neither xdotool for X11 nor pynput) "
              "could be initialized. Cannot run tests effectively.")
        sys.exit(1)

    print("IMPORTANT: You have 5 seconds to switch focus to a text editor or a drawing application "
          "to observe the input simulation effects.")
    time.sleep(5)

    # Test Sequence
    try:
        target_pos1 = (200, 250)
        logger.info(f"\nTEST: Moving mouse to {target_pos1}")
        move(target_pos1)
        time.sleep(0.5)

        logger.info(f"TEST: Left click at {target_pos1}")
        click(target_pos1, "left")
        time.sleep(0.5)

        test_string_1 = "Hello from CoreUI-MCP on Linux! "
        logger.info(f"TEST: Typing: '{test_string_1}'")
        type_text(test_string_1)
        time.sleep(0.5)

        # Key press test (Enter key)
        if _session_type == "x11" and _xdotool_path:
            logger.info("TEST: Pressing Enter key (using xdotool with 'Return' Keysym)")
            press("Return")
        elif _pynput_available and PyKey: # Check if PyKey was successfully imported
            logger.info("TEST: Pressing Enter key (using pynput with PyKey.enter)")
            press(PyKey.enter)
        else:
            logger.warning("Skipping Enter key press test (no suitable mechanism).")
        time.sleep(0.5)

        logger.info("TEST: Scrolling down by 2 units, then right by 1 unit.")
        scroll(dx=0, dy=2) # Scroll down
        time.sleep(0.2)
        scroll(dx=1, dy=0) # Scroll right
        time.sleep(1)

        logger.info("TEST: Scrolling up by 3 units.")
        scroll(dx=0, dy=-3) # Scroll up
        time.sleep(1)

        drag_start_pt = (300, 300)
        drag_end_pt = (500, 400)
        drag_duration_s = 1.0
        logger.info(f"TEST: Dragging with left button from {drag_start_pt} to {drag_end_pt} over {drag_duration_s}s.")
        type_text(f"\nPreparing to drag from {drag_start_pt} to {drag_end_pt}...\n") # For visual cue in editor
        time.sleep(0.5)
        drag(drag_start_pt, drag_end_pt, "left", drag_duration_s)
        time.sleep(1)

        logger.info("\n--- Linux input simulation tests finished. ---")
        print("\n--- Linux input simulation tests finished. ---")
        print("Please check your target application (text editor/drawing app) for the results.")
        if _session_type == "wayland":
            print("NOTE: If on Wayland, global input effects on other applications might be limited or absent.")

    except Exception as e_test:
        logger.critical(f"An error occurred during the test run: {e_test}", exc_info=True)
        print(f"An error occurred during the test run: {e_test}")