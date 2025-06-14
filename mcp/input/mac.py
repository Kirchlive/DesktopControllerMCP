"""
mac.py – macOS low-level input backend using Quartz CGEvent (v0.1.5).

Features:
* ``click(point, button="left")`` – Down/Up pair via ``CGEventPost``.
* ``move(point)`` – Cursor movement only (``kCGEventMouseMoved``).
* ``mousedown(point, button)`` – Press and hold a mouse button.
* ``mouseup(point, button)`` – Release a mouse button.
* ``drag(start, end, button, duration)`` – Drag mouse from start to end with button held.
* ``scroll(dx, dy)`` – Horizontal and vertical scrolling.
* ``keydown(key_code)`` / ``keyup(key_code)`` / ``press(key_code)`` – Virtual key code events.
* ``type_text(text)`` – Proper Unicode text input using ``CGEventKeyboardSetUnicodeString``.

**Accessibility Note:**
The executing program (e.g., Terminal, Python, IDE) must be granted
"Accessibility" permissions under System Settings → Privacy & Security
for synthetic CGEvent s to be accepted by the system.
"""
from __future__ import annotations # For type hints like Tuple from older Python versions

import sys
import time
from typing import Tuple # For Python < 3.9, for 3.9+ tuple is fine

if sys.platform != "darwin":
    raise RuntimeError("mac.py input backend loaded on a non-macOS platform.")

try:
    import Quartz # type: ignore[import-untyped]
except ImportError as exc:
    # This is a critical dependency for this module.
    raise RuntimeError(
        "pyobjc framework Quartz (pyobjc-framework-Quartz) is missing. "
        "Please install it: `pip install pyobjc-framework-Quartz`"
    ) from exc

# --- Mouse Event Helper Constants ---
# Mapping for CGEventCreateMouseEvent buttonNumber parameter
_CG_BUTTON_MAP = {
    "left": Quartz.kCGMouseButtonLeft,    # 0
    "right": Quartz.kCGMouseButtonRight,   # 1
    "middle": Quartz.kCGMouseButtonCenter, # 2
}

# Mapping for CGEvent type parameter for mouse button events
_CG_EVENT_TYPE_DOWN = {
    "left": Quartz.kCGEventLeftMouseDown,
    "right": Quartz.kCGEventRightMouseDown,
    "middle": Quartz.kCGEventOtherMouseDown, # 'Other' is used for middle button
}
_CG_EVENT_TYPE_UP = {
    "left": Quartz.kCGEventLeftMouseUp,
    "right": Quartz.kCGEventRightMouseUp,
    "middle": Quartz.kCGEventOtherMouseUp,
}
_CG_EVENT_TYPE_DRAGGED = {
    "left": Quartz.kCGEventLeftMouseDragged,
    "right": Quartz.kCGEventRightMouseDragged,
    "middle": Quartz.kCGEventOtherMouseDragged,
}

def _post_mouse_event(event_type: int, point: tuple[int, int], cg_button_code: int) -> None:
    """Helper to create and post a mouse event using Quartz."""
    # CGEventCreateMouseEvent(source, mouseType, mouseCursorPosition, mouseButton)
    event = Quartz.CGEventCreateMouseEvent(None, event_type, point, cg_button_code)
    if not event: # pragma: no cover (should not happen if params are valid)
        # Consider logging this error if it occurs.
        # print(f"Error: Failed to create CGEvent for type {event_type} at {point}", file=sys.stderr)
        return
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
    # CFRelease is typically handled by pyobjc's garbage collector for CGEvent objects.
    # Quartz.CFRelease(event) # Usually not needed with pyobjc

# --- Public Mouse API ---
def mousedown(point: tuple[int, int], button: str = "left") -> None:
    """Presses and holds the specified mouse button at the given screen coordinates."""
    button_key = button.lower()
    cg_button_enum_val = _CG_BUTTON_MAP.get(button_key, Quartz.kCGMouseButtonLeft)
    event_type_enum_val = _CG_EVENT_TYPE_DOWN.get(button_key, Quartz.kCGEventLeftMouseDown)
    _post_mouse_event(event_type_enum_val, point, cg_button_enum_val)

def mouseup(point: tuple[int, int], button: str = "left") -> None:
    """Releases the specified mouse button at the given screen coordinates."""
    button_key = button.lower()
    cg_button_enum_val = _CG_BUTTON_MAP.get(button_key, Quartz.kCGMouseButtonLeft)
    event_type_enum_val = _CG_EVENT_TYPE_UP.get(button_key, Quartz.kCGEventLeftMouseUp)
    _post_mouse_event(event_type_enum_val, point, cg_button_enum_val)

def move(point: tuple[int, int]) -> None:
    """Moves the mouse cursor to the specified screen coordinates without clicking."""
    # For kCGEventMouseMoved, the mouseButton parameter is not strictly relevant for the move itself,
    # but kCGMouseButtonLeft is a common default/placeholder.
    _post_mouse_event(Quartz.kCGEventMouseMoved, point, Quartz.kCGMouseButtonLeft)

def click(point: tuple[int, int], button: str = "left") -> None:
    """Performs a mouse click (press and release) at the specified screen coordinates."""
    move(point) # Ensure cursor is at the target location first
    time.sleep(0.05) # Small delay can improve reliability for some applications
    mousedown(point, button)
    time.sleep(0.05) # Delay between press and release
    mouseup(point, button)

def drag(start_point: tuple[int, int], end_point: tuple[int, int], button: str = "left", duration: float = 0.5) -> None:
    """Drags the mouse from start_point to end_point with the specified button held down."""
    button_key = button.lower()
    cg_button_enum_val = _CG_BUTTON_MAP.get(button_key, Quartz.kCGMouseButtonLeft)
    drag_event_type_enum_val = _CG_EVENT_TYPE_DRAGGED.get(button_key, Quartz.kCGEventLeftMouseDragged)

    move(start_point)
    time.sleep(0.05) # Ensure move is processed
    mousedown(start_point, button) # Use our mousedown
    time.sleep(0.05) # Ensure mousedown is processed

    if duration <= 0:
        # If no duration, directly "drag" to the end point with a single drag event
        _post_mouse_event(drag_event_type_enum_val, end_point, cg_button_enum_val)
    else:
        start_x, start_y = start_point
        end_x, end_y = end_point
        num_steps = max(2, int(duration / 0.02)) # Aim for ~50 steps per second
        time_per_step = duration / num_steps

        for i in range(num_steps + 1): # Include the end point
            ratio = i / num_steps
            current_x = int(start_x + (end_x - start_x) * ratio)
            current_y = int(start_y + (end_y - start_y) * ratio)
            _post_mouse_event(drag_event_type_enum_val, (current_x, current_y), cg_button_enum_val)
            if i < num_steps: # No sleep after the final drag event
                time.sleep(time_per_step)
    
    time.sleep(0.05) # Ensure final drag event is processed
    # Release the button at the end_point (or the last position of the drag)
    mouseup(end_point, button) # Use our mouseup

def scroll(dx: int, dy: int) -> None:
    """
    Scrolls horizontally by dx units and vertically by dy units.
    Positive dx scrolls right, negative dx scrolls left.
    Positive dy scrolls down, negative dy scrolls up (natural scroll direction).
    Units are typically lines.
    """
    # CGScrollEventUnit can be kCGScrollEventUnitPixel or kCGScrollEventUnitLine.
    # kCGScrollEventUnitLine is generally preferred for mouse-wheel like scrolling.
    # CGEventCreateScrollWheelEvent(source, units, wheelCount, wheel1, wheel2, wheel3, ...)
    # wheel1: Vertical scroll. Positive for standard/down, negative for up.
    # wheel2: Horizontal scroll. Positive for right, negative for left.
    # wheelCount determines how many wheel values are used (1 for vertical, 2 for vertical+horizontal).
    
    scroll_event = None
    if dy != 0 and dx == 0: # Only vertical scroll
        scroll_event = Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 1, int(dy))
    elif dx != 0 and dy == 0: # Only horizontal scroll
        # For horizontal-only, set wheelCount to 2, wheel1 (vertical) to 0.
        scroll_event = Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 2, 0, int(dx))
    elif dx != 0 and dy != 0: # Both directions
        scroll_event = Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 2, int(dy), int(dx))
    # If dx and dy are both 0, scroll_event remains None, and nothing happens.

    if scroll_event:
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, scroll_event)
        time.sleep(0.01) # Small delay after scroll event
    # No CFRelease needed due to pyobjc GC.

# --- Public Keyboard API ---
def keydown(key_code: int) -> None: # Expects macOS virtual key codes
    """Simulates pressing a virtual key."""
    # CGEventCreateKeyboardEvent(source, virtualKey, keyDownBool)
    event = Quartz.CGEventCreateKeyboardEvent(None, key_code, True)
    if event: Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)

def keyup(key_code: int) -> None: # Expects macOS virtual key codes
    """Simulates releasing a virtual key."""
    event = Quartz.CGEventCreateKeyboardEvent(None, key_code, False)
    if event: Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)

def press(key_code: int) -> None:
    """Simulates a full key press (keydown followed by keyup)."""
    keydown(key_code)
    time.sleep(0.01) # Small delay can help OS distinguish separate events
    keyup(key_code)

def _post_unicode_char(char_val: str) -> None:
    """Helper to post a single Unicode character as key down + key up events."""
    # CGEventKeyboardSetUnicodeString expects the number of UTF-16 code units (UniChar).
    utf16_encoded_char = char_val.encode('utf-16-le') # Little-endian for length calculation
    num_utf16_units = len(utf16_encoded_char) // 2

    # KeyDown event for the Unicode character
    # For Unicode input, virtualKey parameter is often set to 0.
    event_down = Quartz.CGEventCreateKeyboardEvent(None, 0, True)
    if not event_down: return # pragma: no cover
    Quartz.CGEventKeyboardSetUnicodeString(event_down, num_utf16_units, char_val)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event_down)

    # KeyUp event for the Unicode character
    event_up = Quartz.CGEventCreateKeyboardEvent(None, 0, False)
    if not event_up: return # pragma: no cover
    Quartz.CGEventKeyboardSetUnicodeString(event_up, num_utf16_units, char_val)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event_up)

def type_text(text: str) -> None:
    """
    Simulates typing of an arbitrary Unicode string on macOS.
    This method sends each character independently.
    """
    for char_val in text:
        _post_unicode_char(char_val)
        # Optional: A small delay between characters if typing too fast causes issues.
        # time.sleep(0.005)