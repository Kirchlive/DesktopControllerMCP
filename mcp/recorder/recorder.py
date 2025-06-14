"""
recorder.py – JSON-based macro recorder & player for CoreUI-MCP (v0.1.5).

This module uses the `pynput` library to listen for global mouse and
keyboard events during recording. Playback is performed by dispatching
these recorded events to the platform-specific input backend provided
by `mcp.input`.

Core Functionality:
- Records mouse movements, clicks, scrolls, and keyboard presses/releases.
- Saves recorded events to a JSON file with relative timestamps.
- Plays back macros from JSON files, adjusting for a specified speed factor.
- Recording can be stopped by a predefined duration or by pressing the ESC key.

Key Data Structures:
- Events are stored as a list of dictionaries, each containing:
  - "type": "move", "click", "scroll", "key"
  - "t": Timestamp (float, seconds) relative to the start of recording.
  - Other event-specific data (e.g., "x", "y", "button", "pressed", "vk", "char", "dx", "dy").

Dependencies:
- `pynput`: For listening to global input events during recording.
- `mcp.input.backend`: For dispatching events during playback.
- `mcp.logger`: For centralized logging.
"""
from __future__ import annotations # For type hints like Optional from older Python

import json
import sys
import time
import threading # For event-based stopping of recording
from pathlib import Path
from typing import Any, Dict, List, Optional # For Python < 3.9 Dict, List, Optional

# Third-party library for input listening
try:
    from pynput import keyboard, mouse # type: ignore[import-untyped]
    PYNPUT_AVAILABLE = True
except ImportError: # pragma: no cover
    PYNPUT_AVAILABLE = False
    # Define dummy classes if pynput is not available to allow module import,
    # but recording functionality will be disabled.
    class keyboard: # type: ignore[no-redef]
        class Key: # type: ignore[no-redef]
            esc = None # Dummy attribute
        class KeyCode: # type: ignore[no-redef]
            pass
        class Listener: # type: ignore[no-redef]
            def __init__(self, *args: Any, **kwargs: Any) -> None: pass
            def start(self) -> None: pass
            def stop(self) -> None: pass
            def join(self, timeout: float | None = None) -> None: pass
            def is_alive(self) -> bool: return False
    class mouse: # type: ignore[no-redef]
        class Button: # type: ignore[no-redef]
            pass
        class Listener: # type: ignore[no-redef]
            def __init__(self, *args: Any, **kwargs: Any) -> None: pass
            def start(self) -> None: pass
            def stop(self) -> None: pass
            def join(self, timeout: float | None = None) -> None: pass
            def is_alive(self) -> bool: return False


# Local MCP package imports
from mcp.logger import get_logger # Centralized logger
# The mcp.input.backend is dynamically selected based on the OS.
from mcp.input import backend as playback_input_backend

logger = get_logger(__name__)

if not PYNPUT_AVAILABLE: # pragma: no cover
    logger.critical(
        "The 'pynput' library is not installed. Macro recording functionality will be disabled. "
        "Please install it (e.g., `pip install pynput`)."
    )

# --- Event Buffer for Recording ---
class _EventBuffer:
    """
    Stores listened input events with relative timestamps.
    This class is an internal helper for the recording process.
    """
    def __init__(self) -> None:
        self._start_time_monotonic: float = time.monotonic() # High-resolution timer
        self.events: list[dict[str, Any]] = []
        self._last_event_time_monotonic: float = self._start_time_monotonic

    def _record_event(self, event_data: dict[str, Any]) -> None:
        """Adds an event to the buffer with a relative timestamp."""
        current_time_monotonic = time.monotonic()
        # Timestamp relative to the start of recording
        event_data["t"] = current_time_monotonic - self._start_time_monotonic
        # Optional: Could also record delay from the *last* event if useful for playback strategies.
        # event_data["delay_from_last"] = current_time_monotonic - self._last_event_time_monotonic
        self.events.append(event_data)
        self._last_event_time_monotonic = current_time_monotonic

    # --- pynput Mouse Event Callbacks ---
    def on_move(self, x: int, y: int) -> None: # pragma: no cover (interactive)
        """Callback for mouse move events from pynput listener."""
        self._record_event({"type": "move", "x": x, "y": y})

    def on_click(self, x: int, y: int, button: mouse.Button, pressed: bool) -> None: # pragma: no cover
        """Callback for mouse click events (button press/release)."""
        # `button.name` gives "left", "right", "middle", etc.
        self._record_event({ # KORRIGIERT von self_record_event
            "type": "click",
            "x": x, "y": y,
            "button": button.name if hasattr(button, 'name') else str(button), # Handle potential dummy
            "pressed": pressed, # True if button was pressed, False if released
        })

    def on_scroll(self, x: int, y: int, dx: int, dy: int) -> None: # pragma: no cover
        """Callback for mouse scroll events."""
        # (x, y) is the pointer position when scroll occurred.
        # dx, dy are the horizontal and vertical scroll amounts.
        self._record_event({ # KORRIGIERT von self_record_event
            "type": "scroll",
            "x": x, "y": y,
            "dx": dx, "dy": dy
        })

    # --- pynput Keyboard Event Callbacks ---
    def on_press(self, key: keyboard.Key | keyboard.KeyCode | None) -> None: # pragma: no cover
        """Callback for key press events."""
        if key is None: return # Should not happen with pynput but defensive
        try:
            vk_code, char_val = _map_pynput_key_to_vk_char(key)
            event_data: dict[str, Any] = {"type": "key", "pressed": True}
            if vk_code is not None: event_data["vk"] = vk_code
            if char_val is not None: event_data["char"] = char_val
            # Only record if we have vk_code or char_val to avoid empty key events
            if "vk" in event_data or "char" in event_data:
                self._record_event(event_data)
            else:
                logger.debug(f"Skipping press event for key '{key}' as it yielded no vk_code or char.")
        except ValueError as e: # Raised by _map_pynput_key_to_vk_char for unmappable keys
            logger.warning(f"Could not map pressed key '{key}' to vk/char: {e}. Event skipped.")

    def on_release(self, key: keyboard.Key | keyboard.KeyCode | None) -> None: # pragma: no cover
        """Callback for key release events."""
        if key is None: return
        try:
            vk_code, char_val = _map_pynput_key_to_vk_char(key)
            event_data: dict[str, Any] = {"type": "key", "pressed": False}
            if vk_code is not None: event_data["vk"] = vk_code
            # Char is less relevant for release but included for consistency if available
            if char_val is not None: event_data["char"] = char_val
            if "vk" in event_data or "char" in event_data:
                self._record_event(event_data)
            else:
                logger.debug(f"Skipping release event for key '{key}' as it yielded no vk_code or char.")
        except ValueError as e:
            logger.warning(f"Could not map released key '{key}' to vk/char: {e}. Event skipped.")

# --- Global Event for Stopping Recording ---
_stop_recording_flag = threading.Event()

def _keyboard_interrupt_listener_callback(key_pressed: Any) -> bool: # pragma: no cover (interactive)
    """
    Special pynput keyboard listener callback to detect ESC key press for stopping recording.
    Returns False to stop the listener.
    """
    if PYNPUT_AVAILABLE and hasattr(keyboard, 'Key') and key_pressed == keyboard.Key.esc:
        logger.info("ESC key pressed. Signaling recording to stop...")
        _stop_recording_flag.set()
        return False  # Instructs the pynput listener to stop
    return True # Continue listening for other keys

# --- Public Recorder API ---
def record(output_json_path: Path, duration_seconds: float | None = None) -> None: # pragma: no cover
    """
    Records mouse and keyboard events and saves them to a JSON file.
    Recording stops when `duration_seconds` elapses or when the ESC key is pressed.

    Args:
        output_json_path: The `pathlib.Path` object where the recorded macro (JSON) will be saved.
        duration_seconds: Optional duration in seconds for the recording. If None, records indefinitely
                          until ESC is pressed.
    """
    if not PYNPUT_AVAILABLE:
        logger.error("Cannot start recording: pynput library is not available.")
        return

    _stop_recording_flag.clear() # Reset the stop flag for a new recording session
    event_buffer = _EventBuffer()

    duration_msg = f"{duration_seconds} seconds" if duration_seconds is not None else "indefinitely (until ESC is pressed)"
    logger.info(f"Starting macro recording to: {output_json_path.resolve()}")
    logger.info(f"Recording duration: {duration_msg}. Press ESC to stop manually at any time.")

    kb_recorder_listener: keyboard.Listener | None = None
    esc_interrupt_listener: keyboard.Listener | None = None
    mouse_listener: mouse.Listener | None = None

    try:
        kb_recorder_listener = keyboard.Listener(
            on_press=event_buffer.on_press,
            on_release=event_buffer.on_release,
        )
        esc_interrupt_listener = keyboard.Listener(on_press=_keyboard_interrupt_listener_callback)
        mouse_listener = mouse.Listener(
            on_move=event_buffer.on_move,
            on_click=event_buffer.on_click,
            on_scroll=event_buffer.on_scroll
        )

        mouse_listener.start()
        kb_recorder_listener.start()
        esc_interrupt_listener.start()

        actual_recording_start_time = time.monotonic()

        if duration_seconds is not None and duration_seconds > 0:
            _stop_recording_flag.wait(timeout=duration_seconds)
        else:
            _stop_recording_flag.wait()

        actual_recording_duration = time.monotonic() - actual_recording_start_time
        logger.info(f"Recording finished after {actual_recording_duration:.2f} seconds.")

    finally: # Ensure listeners are stopped even if an error occurs during wait/start
        logger.debug("Stopping input listeners...")
        if mouse_listener and mouse_listener.is_alive(): mouse_listener.stop()
        if kb_recorder_listener and kb_recorder_listener.is_alive(): kb_recorder_listener.stop()
        if esc_interrupt_listener and esc_interrupt_listener.is_alive(): esc_interrupt_listener.stop()

        # Wait for listener threads to terminate
        if mouse_listener: mouse_listener.join(timeout=1.0)
        if kb_recorder_listener: kb_recorder_listener.join(timeout=1.0)
        if esc_interrupt_listener: esc_interrupt_listener.join(timeout=1.0)
        logger.debug("Input listeners stopped.")

    try:
        output_json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_json_path, 'w', encoding='utf-8') as f:
            json.dump(event_buffer.events, f, indent=2)
        logger.info(f"Successfully recorded {len(event_buffer.events)} events to: {output_json_path.resolve()}")
    except IOError as e_io:
        logger.error(f"Failed to write macro to {output_json_path}: {e_io}", exc_info=True)
    except Exception as e_save:
        logger.error(f"An unexpected error occurred while saving the macro: {e_save}", exc_info=True)


def play(macro_json_path: Path, speed_factor: float = 1.0) -> None: # pragma: no cover
    """
    Plays back a recorded macro from a JSON file.

    Args:
        macro_json_path: The `pathlib.Path` to the macro file (JSON) to be played.
        speed_factor: Playback speed multiplier.
                      - 1.0 = normal speed.
                      - < 1.0 = faster playback (e.g., 0.5 is 2x speed).
                      - > 1.0 = slower playback (e.g., 2.0 is 0.5x speed).
                      Must be greater than 0.
    """
    if not hasattr(playback_input_backend, 'click'):
        logger.error("Playback input backend is not available or not fully functional. Cannot play macro.")
        return

    if not (isinstance(speed_factor, (int, float)) and speed_factor > 0):
        logger.error(f"Invalid speed_factor: {speed_factor}. Must be a positive number. Defaulting to 1.0.")
        speed_factor = 1.0

    logger.info(f"Starting playback of macro: {macro_json_path.resolve()} (Speed factor: {speed_factor:.2f}x)")

    try:
        with open(macro_json_path, 'r', encoding='utf-8') as f:
            events: list[dict[str, Any]] = json.load(f)
    except FileNotFoundError:
        logger.error(f"Macro file not found: {macro_json_path}")
        return
    except json.JSONDecodeError as e_json:
        logger.error(f"Invalid JSON format in macro file '{macro_json_path}': {e_json}", exc_info=True)
        return
    except Exception as e_load:
        logger.error(f"Error loading macro file '{macro_json_path}': {e_load}", exc_info=True)
        return

    if not events:
        logger.warning(f"Macro file '{macro_json_path}' is empty. Nothing to play.")
        return

    events.sort(key=lambda ev: ev.get("t", 0.0))

    playback_start_time_monotonic = time.monotonic()
    original_first_event_timestamp = events[0].get("t", 0.0)

    for i, event_data in enumerate(events):
        original_event_relative_time = event_data.get("t", 0.0) - original_first_event_timestamp
        scheduled_playback_relative_time = original_event_relative_time / speed_factor
        current_playback_elapsed_time = time.monotonic() - playback_start_time_monotonic
        sleep_duration = scheduled_playback_relative_time - current_playback_elapsed_time
        
        if sleep_duration > 0.001:
            time.sleep(sleep_duration)

        try:
            _dispatch_event_to_backend(event_data)
        except Exception as e_dispatch:
            logger.error(f"Error dispatching event {i+1}/{len(events)}: {event_data}. Error: {e_dispatch}", exc_info=True)

        if (i + 1) % 50 == 0:
            logger.debug(f"Dispatched {i+1}/{len(events)} events from macro.")

    logger.info(f"Macro playback finished for: {macro_json_path.resolve()}")


# --- Internal Helper Functions ---

def _dispatch_event_to_backend(event_data: dict[str, Any]) -> None:
    """
    Dispatches a single recorded event to the appropriate function
    in the `playback_input_backend`.
    """
    event_type = event_data.get("type")

    if event_type == "move":
        if hasattr(playback_input_backend, "move"):
            playback_input_backend.move((event_data["x"], event_data["y"]))
        else: logger.warning("Playback backend does not support 'move' event. Skipping.")

    elif event_type == "click":
        if event_data.get("pressed"): 
            if hasattr(playback_input_backend, "mousedown"): # Prefer mousedown/mouseup if available
                playback_input_backend.mousedown(
                    (event_data["x"], event_data["y"]),
                    button=event_data.get("button", "left")
                )
            elif hasattr(playback_input_backend, "click"): # Fallback to full click
                 logger.debug("Using backend.click for mousedown event from recording.")
                 playback_input_backend.click(
                    (event_data["x"], event_data["y"]),
                    button=event_data.get("button", "left")
                )
            else: logger.warning("Playback backend does not support 'mousedown' or 'click' event. Skipping press.")
        else: # This is a mouseup event from recording
            if hasattr(playback_input_backend, "mouseup"):
                 playback_input_backend.mouseup(
                    (event_data["x"], event_data["y"]),
                    button=event_data.get("button", "left")
                )
            # If only 'click' is available, it's already handled by the 'pressed'==True case
            elif not hasattr(playback_input_backend, "mousedown"): # And no mousedown means click was likely used
                 logger.debug("Skipping mouseup from recording as backend.click (used for mousedown) handles both.")
            else: logger.warning("Playback backend does not support 'mouseup' event. Skipping release.")


    elif event_type == "scroll":
        if hasattr(playback_input_backend, "scroll"):
            playback_input_backend.scroll(event_data.get("dx", 0), event_data.get("dy", 0))
        else: logger.warning("Playback backend does not support 'scroll' event. Skipping.")

    elif event_type == "key":
        key_to_send: Any = None
        if "vk" in event_data and event_data["vk"] is not None:
            key_to_send = event_data["vk"]
        elif "char" in event_data and event_data["char"] is not None:
            key_to_send = event_data["char"]

        if key_to_send is None:
            logger.warning(f"Skipping key event with no usable 'vk' or 'char': {event_data}")
            return

        if event_data.get("pressed"):
            if hasattr(playback_input_backend, "keydown"):
                playback_input_backend.keydown(key_to_send)
            else: logger.warning("Playback backend does not support 'keydown'. Skipping.")
        else: 
            if hasattr(playback_input_backend, "keyup"):
                playback_input_backend.keyup(key_to_send)
            else: logger.warning("Playback backend does not support 'keyup'. Skipping.")
    else:
        logger.warning(f"Unknown event type encountered during playback: '{event_type}'. Event: {event_data}. Skipping.")


def _map_pynput_key_to_vk_char(pynput_key_obj: keyboard.Key | keyboard.KeyCode | None) -> tuple[int | None, str | None]:
    """
    Maps a pynput key object to a virtual key (vk) code and/or a character.
    This mapping can be platform-dependent and is a simplification.
    Pynput's `vk` attribute is often available on Windows. On other platforms,
    it might be less reliable or represent different key code systems.

    Returns:
        A tuple (vk_code, character_value). Either can be None.

    Raises:
        ValueError: If the key object cannot be meaningfully mapped.
    """
    vk_code: int | None = None
    char_val: str | None = None

    if not PYNPUT_AVAILABLE: # Should not be called if pynput not available, but defensive
        raise ValueError("pynput is not available to map keys.")

    if isinstance(pynput_key_obj, keyboard.KeyCode):
        if hasattr(pynput_key_obj, 'vk') and pynput_key_obj.vk is not None:
            vk_code = int(pynput_key_obj.vk)
        if hasattr(pynput_key_obj, 'char') and pynput_key_obj.char is not None:
            char_val = str(pynput_key_obj.char)
    elif isinstance(pynput_key_obj, keyboard.Key):
        if hasattr(pynput_key_obj, 'value') and hasattr(pynput_key_obj.value, 'vk') and pynput_key_obj.value.vk is not None:
            vk_code = int(pynput_key_obj.value.vk)
    else:
        raise ValueError(f"Unrecognized pynput key type: {type(pynput_key_obj)}")

    if vk_code is None and char_val is None:
        key_name_attr = getattr(pynput_key_obj, 'name', 'N/A')
        raise ValueError(f"Cannot map pynput key '{pynput_key_obj}' (name: {key_name_attr}) to a usable vk_code or character.")

    return vk_code, char_val


# --- Command-Line Interface (CLI) ---
def main_recorder_cli(): # pragma: no cover
    """CLI entry point for the MCP macro recorder and player."""
    import argparse

    if not PYNPUT_AVAILABLE and ('record' in sys.argv or '--help' not in sys.argv):
        err_msg = "CRITICAL: pynput library is not installed. Macro recording is not possible."
        logger.critical(err_msg)
        print(err_msg, file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description="CoreUI-MCP Macro Recorder & Player (v0.1.5). "
                    "Records mouse/keyboard actions to JSON or plays them back."
    )
    subparsers = parser.add_subparsers(dest="command", required=True, title="Available Commands",
                                       help="Use 'record' to create a new macro, or 'play' to run an existing one.")

    record_parser = subparsers.add_parser("record", help="Record a new macro to a JSON file.")
    record_parser.add_argument(
        "output_path",
        type=Path,
        help="Path to the JSON file where the recorded macro will be saved."
    )
    record_parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Optional: Maximum duration of the recording in seconds. "
             "If not provided, recording continues until ESC is pressed."
    )

    play_parser = subparsers.add_parser("play", help="Play an existing macro from a JSON file.")
    play_parser.add_argument(
        "macro_path",
        type=Path,
        help="Path to the JSON macro file to be played."
    )
    play_parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Playback speed factor (e.g., 0.5 for 2x speed, 1.0 for normal, 2.0 for 0.5x speed). Default: 1.0."
    )

    args = parser.parse_args()

    if not logger.handlers:
        from mcp.logger import setup_logging # Local import if needed for direct script run
        setup_logging(level="INFO", log_file=Path("logs") / "mcp_recorder_cli.log", force=False)

    if args.command == "record":
        if not PYNPUT_AVAILABLE:
            logger.critical("Cannot execute 'record' command: pynput is not installed.")
            print("Error: pynput library is required for recording. Please install it.", file=sys.stderr)
            sys.exit(1)
        record(args.output_path, args.duration)
    elif args.command == "play":
        play(args.macro_path, args.speed)

if __name__ == "__main__": # pragma: no cover
    main_recorder_cli()