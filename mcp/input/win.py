"""
win.py – Windows low-level input backend (cursor-less SendInput) (v0.1.5).

Features:
• click(point, button): Simulates a mouse click (down + up) at absolute coordinates.
• move(point): Moves the mouse cursor to absolute coordinates. The system cursor's actual position is updated.
• mousedown(point, button): Presses and holds a mouse button at specified coordinates.
• mouseup(point, button): Releases a mouse button at specified coordinates.
• drag(start_point, end_point, button, duration): Drags the mouse from start to end with a button held down.
• scroll(dx, dy): Simulates horizontal (dx) and vertical (dy) mouse wheel scrolling.
• keydown(vk_code) / keyup(vk_code) / press(vk_code): Simulates virtual key code events.
• type_text(text): Simulates typing of Unicode text.

Coordinates are physical pixels. _normalize() converts them to the 0-65535
range required by MOUSEEVENTF_ABSOLUTE, which is documented by Microsoft
as DPI-aware.
"""
from __future__ import annotations # For type hints like Tuple from older Python versions if needed

import ctypes
import functools
import sys
import time
from ctypes import POINTER, Structure, Union, c_long, c_ulong, c_ushort, sizeof # Ensure c_ushort is imported
from typing import Tuple # For Python < 3.9, for 3.9+ tuple is fine

if sys.platform != "win32":
    raise RuntimeError("win.py input backend loaded on a non-Windows platform.")

user32 = ctypes.WinDLL("user32", use_last_error=True)

# Win32 Constants
INPUT_MOUSE    = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE        = 0x0001
MOUSEEVENTF_ABSOLUTE    = 0x8000
MOUSEEVENTF_LEFTDOWN    = 0x0002
MOUSEEVENTF_LEFTUP      = 0x0004
MOUSEEVENTF_RIGHTDOWN   = 0x0008
MOUSEEVENTF_RIGHTUP     = 0x0010
MOUSEEVENTF_MIDDLEDOWN  = 0x0020
MOUSEEVENTF_MIDDLEUP    = 0x0040
MOUSEEVENTF_WHEEL       = 0x0800  # Vertical scroll
MOUSEEVENTF_HWHEEL      = 0x1000  # Horizontal scroll
WHEEL_DELTA             = 120     # Standard value for one scroll unit (notch)

KEYEVENTF_KEYUP         = 0x0002
KEYEVENTF_UNICODE       = 0x0004  # Flag for SendInput to interpret wScan as Unicode char

# C Structs for SendInput
class MOUSEINPUT(Structure):
    _fields_ = (
        ("dx",         c_long),  # For absolute coords, normalized (0-65535)
        ("dy",         c_long),  # For absolute coords, normalized (0-65535)
        ("mouseData",  c_ulong), # For wheel events (signed value), 0 for others
        ("dwFlags",    c_ulong), # Mouse event flags (e.g., MOUSEEVENTF_MOVE)
        ("time",       c_ulong), # Timestamp (0 for system to provide)
        ("dwExtraInfo",POINTER(c_ulong)), # Extra info (usually 0)
    )

class KEYBDINPUT(Structure):
    _fields_ = (
        ("wVk",        c_ushort), # Virtual-key code
        ("wScan",      c_ushort), # Hardware scan code (or Unicode char if KEYEVENTF_UNICODE)
        ("dwFlags",    c_ulong),  # Key event flags (e.g., KEYEVENTF_KEYUP)
        ("time",       c_ulong),
        ("dwExtraInfo",POINTER(c_ulong)),
    )

class _INPUTunion(Union): # Anonymous union in C
    _fields_ = (("mi", MOUSEINPUT), ("ki", KEYBDINPUT))

class INPUT(Structure):
    _fields_ = (("type", c_ulong), ("union", _INPUTunion)) # type: INPUT_MOUSE or INPUT_KEYBOARD

# Helper Functions
def _send_input(*inputs: INPUT) -> None:
    """Sends one or more INPUT structures using SendInput."""
    num_inputs = len(inputs)
    input_array = (INPUT * num_inputs)(*inputs)
    if user32.SendInput(num_inputs, input_array, sizeof(INPUT)) != num_inputs:
        raise ctypes.WinError(ctypes.get_last_error())

def _normalize(x: int, y: int) -> tuple[int, int]:
    """Converts screen pixel coordinates to normalized absolute coordinates (0-65535)."""
    # SM_CXVIRTUALSCREEN (78) and SM_CYVIRTUALSCREEN (79) for multi-monitor setups
    # Fallback to SM_CXSCREEN (0) and SM_CYSCREEN (1) for single monitor
    screen_width = user32.GetSystemMetrics(78) or user32.GetSystemMetrics(0)
    screen_height = user32.GetSystemMetrics(79) or user32.GetSystemMetrics(1)

    # Avoid division by zero if screen metrics are unusual (e.g., 1 or 0)
    norm_x = int(x * 65535 / (screen_width - 1)) if screen_width > 1 else 0
    norm_y = int(y * 65535 / (screen_height - 1)) if screen_height > 1 else 0
    return norm_x, norm_y

def _mouse_event(flags: int, x: int = 0, y: int = 0, mouse_data: int = 0) -> None:
    """Helper to create and send a mouse event with absolute coordinates."""
    # For MOUSEEVENTF_ABSOLUTE, dx and dy contain normalized absolute coordinates.
    # If not MOUSEEVENTF_ABSOLUTE, dx and dy are relative_motion. We always use ABSOLUTE.
    normalized_x, normalized_y = _normalize(x, y)
    # mouseData is ulong in struct, but for wheel events it's treated as signed by the system.
    # ctypes handles the conversion of Python int to ulong appropriately.
    mi = MOUSEINPUT(normalized_x, normalized_y, mouse_data, MOUSEEVENTF_ABSOLUTE | flags, 0, None)
    _send_input(INPUT(type=INPUT_MOUSE, union=_INPUTunion(mi=mi)))

# Public Mouse API
def mousedown(point: tuple[int, int], button: str = "left") -> None:
    """Presses and holds a mouse button at the specified point."""
    button_flags_map = {
        "left": MOUSEEVENTF_LEFTDOWN,
        "right": MOUSEEVENTF_RIGHTDOWN,
        "middle": MOUSEEVENTF_MIDDLEDOWN,
    }
    event_flag = button_flags_map.get(button.lower(), MOUSEEVENTF_LEFTDOWN)
    _mouse_event(event_flag, point[0], point[1])

def mouseup(point: tuple[int, int], button: str = "left") -> None:
    """Releases a mouse button at the specified point."""
    button_flags_map = {
        "left": MOUSEEVENTF_LEFTUP,
        "right": MOUSEEVENTF_RIGHTUP,
        "middle": MOUSEEVENTF_MIDDLEUP,
    }
    event_flag = button_flags_map.get(button.lower(), MOUSEEVENTF_LEFTUP)
    _mouse_event(event_flag, point[0], point[1])

@functools.singledispatch # Allows overloading `click` for different first arg types if needed
def click(point: Any, button: str = "left") -> None: # `Any` for singledispatch base
    """Generic click dispatcher. Use specific registration for `tuple`."""
    raise NotImplementedError(f"click not implemented for type {type(point)}")

@click.register(tuple) # type: ignore[no-redef]
def _click_tuple(point: tuple[int, int], button: str = "left") -> None:
    """Performs a mouse click (down + up) at the specified screen coordinates."""
    move(point) # Ensure cursor is at the target point
    time.sleep(0.01) # Small delay can improve reliability in some apps
    mousedown(point, button)
    time.sleep(0.01) # Delay between press and release
    mouseup(point, button)

def move(point: tuple[int, int]) -> None:
    """Moves the mouse cursor to the specified screen coordinates."""
    _mouse_event(MOUSEEVENTF_MOVE, point[0], point[1])

def drag(start_point: tuple[int, int], end_point: tuple[int, int], button: str = "left", duration: float = 0.5) -> None:
    """Drags the mouse from start_point to end_point with a button held down."""
    move(start_point)
    time.sleep(0.05) # Ensure move is processed before mousedown
    mousedown(start_point, button)
    time.sleep(0.05) # Ensure mousedown is processed

    if duration <= 0:
        move(end_point) # Instantaneous move if no duration
    else:
        start_x, start_y = start_point
        end_x, end_y = end_point
        num_steps = max(2, int(duration / 0.02)) # Aim for ~50 steps per second
        time_per_step = duration / num_steps

        for i in range(num_steps + 1): # Include the end point
            ratio = i / num_steps
            current_x = int(start_x + (end_x - start_x) * ratio)
            current_y = int(start_y + (end_y - start_y) * ratio)
            move((current_x, current_y))
            if i < num_steps: # No sleep after the final move
                time.sleep(time_per_step)
    
    time.sleep(0.05) # Ensure final move/drag is processed
    mouseup(end_point, button) # Release button at the destination

def scroll(dx: int, dy: int) -> None:
    """
    Scrolls horizontally by dx units and vertically by dy units.
    Positive dx scrolls right, negative dx scrolls left.
    Positive dy scrolls down (towards user), negative dy scrolls up (away from user).
    """
    if dy != 0:
        # For MOUSEEVENTF_WHEEL:
        # Positive mouseData value indicates the wheel was rotated forward (away from the user - scroll UP).
        # Negative mouseData value indicates the wheel was rotated backward (towards the user - scroll DOWN).
        # So, if dy is intuitive (positive=down, negative=up), mouse_data needs inversion for dy.
        _mouse_event(MOUSEEVENTF_WHEEL, mouse_data=int(dy * -WHEEL_DELTA))
        time.sleep(0.01) # Small delay between scroll events if both are triggered
    if dx != 0:
        # For MOUSEEVENTF_HWHEEL:
        # Positive mouseData scrolls RIGHT. Negative mouseData scrolls LEFT.
        # dx maps directly.
        _mouse_event(MOUSEEVENTF_HWHEEL, mouse_data=int(dx * WHEEL_DELTA))
        time.sleep(0.01)

# Public Keyboard API
def keydown(vk_code: int) -> None:
    """Simulates pressing a virtual key."""
    # For keydown, wScan can be 0. dwFlags = 0 for default behavior.
    _send_input(INPUT(type=INPUT_KEYBOARD, union=_INPUTunion(ki=KEYBDINPUT(wVk=vk_code, wScan=0, dwFlags=0, time=0, dwExtraInfo=None))))

def keyup(vk_code: int) -> None:
    """Simulates releasing a virtual key."""
    _send_input(INPUT(type=INPUT_KEYBOARD, union=_INPUTunion(ki=KEYBDINPUT(wVk=vk_code, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=None))))

def press(vk_code: int) -> None:
    """Simulates a full key press (keydown followed by keyup)."""
    keydown(vk_code)
    time.sleep(0.01) # Optional small delay between keydown and keyup
    keyup(vk_code)

def _send_unicode(char_code: int, is_key_up: bool = False) -> None:
    """Helper to send a Unicode character event."""
    # For Unicode input, wVk is 0. wScan is the Unicode character.
    # KEYEVENTF_UNICODE flag must be set.
    flags = KEYEVENTF_UNICODE
    if is_key_up:
        flags |= KEYEVENTF_KEYUP
    ki = KEYBDINPUT(wVk=0, wScan=char_code, dwFlags=flags, time=0, dwExtraInfo=None)
    _send_input(INPUT(type=INPUT_KEYBOARD, union=_INPUTunion(ki=ki)))

def type_text(text: str) -> None:
    """
    Simulates typing of an arbitrary Unicode string.
    For characters outside the Basic Multilingual Plane (BMP) (> 0xFFFF),
    it sends the necessary surrogate pair.
    """
    for char_val in text:
        char_code_point = ord(char_val)

        if char_code_point <= 0xFFFF: # Character is in BMP
            _send_unicode(char_code_point, is_key_up=False) # KeyDown
            _send_unicode(char_code_point, is_key_up=True)  # KeyUp
        else: # Character is outside BMP, needs surrogate pair
            # Formula for surrogate pairs:
            # H = (C - 0x10000) / 0x400 + 0xD800
            # L = (C - 0x10000) % 0x400 + 0xDC00
            # where C is the code point.
            adjusted_code = char_code_point - 0x10000
            high_surrogate = (adjusted_code // 0x400) + 0xD800
            low_surrogate = (adjusted_code % 0x400) + 0xDC00

            _send_unicode(high_surrogate, is_key_up=False)
            _send_unicode(high_surrogate, is_key_up=True)
            _send_unicode(low_surrogate, is_key_up=False)
            _send_unicode(low_surrogate, is_key_up=True)
        time.sleep(0.005) # Tiny delay between characters if needed