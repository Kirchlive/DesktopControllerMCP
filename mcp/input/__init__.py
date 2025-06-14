"""
Input backends for different platforms (v0.1.5).

This module dynamically imports the appropriate platform-specific input backend
(Windows, macOS, or Linux). If an unsupported platform is detected, it falls
back to a `DummyInputBackend` that logs actions but performs no actual input.

The `backend` object exposed by this module will be an instance of the
selected platform's input functions or the dummy backend.
"""
import sys
from typing import Tuple, Any # For type hints in DummyInputBackend

# Dynamically select and import the platform-specific backend
if sys.platform == "win32":
    from . import win as backend
elif sys.platform == "darwin": # macOS
    from . import mac as backend
elif sys.platform.startswith("linux"): # Covers various Linux distributions
    from . import linux as backend
else:  # pragma: no cover (Covers unsupported platforms)
    print(
        f"WARNING: Unsupported platform '{sys.platform}' for CoreUI-MCP input backend. "
        "Input operations will be simulated by a dummy backend (logging to stderr only).",
        file=sys.stderr
    )

    class DummyInputBackend:
        """
        A dummy input backend that logs attempted actions to stderr.
        Used when CoreUI-MCP is run on an unsupported platform for input control.
        """
        def _log_action(self, action_name: str, *args: Any, **kwargs: Any) -> None:
            arg_str = ", ".join(map(str, args))
            kwarg_str = ", ".join(f"{k}={v}" for k, v in kwargs.items())
            log_msg = f"DummyInputBackend: {action_name}("
            if arg_str: log_msg += arg_str
            if kwarg_str:
                if arg_str: log_msg += ", "
                log_msg += kwarg_str
            log_msg += ")"
            print(log_msg, file=sys.stderr)

        def move(self, point: tuple[int, int], *args: Any, **kwargs: Any) -> None:
            self._log_action("move", point, *args, **kwargs)

        def click(self, point: tuple[int, int], button: str = "left", *args: Any, **kwargs: Any) -> None:
            self._log_action("click", point, button=button, *args, **kwargs)

        def mousedown(self, point: tuple[int, int], button: str = "left", *args: Any, **kwargs: Any) -> None:
            self._log_action("mousedown", point, button=button, *args, **kwargs)

        def mouseup(self, point: tuple[int, int], button: str = "left", *args: Any, **kwargs: Any) -> None:
            self._log_action("mouseup", point, button=button, *args, **kwargs)

        def drag(self, start_point: tuple[int, int], end_point: tuple[int, int], button: str = "left", duration: float = 0.5, *args: Any, **kwargs: Any) -> None:
            self._log_action("drag", start_point, end_point, button=button, duration=duration, *args, **kwargs)

        def scroll(self, dx: int, dy: int, *args: Any, **kwargs: Any) -> None:
            self._log_action("scroll", dx=dx, dy=dy, *args, **kwargs)

        def keydown(self, key_spec: Any, *args: Any, **kwargs: Any) -> None:
            self._log_action("keydown", key_spec, *args, **kwargs)

        def keyup(self, key_spec: Any, *args: Any, **kwargs: Any) -> None:
            self._log_action("keyup", key_spec, *args, **kwargs)

        def press(self, key_spec: Any, *args: Any, **kwargs: Any) -> None:
            self._log_action("press", key_spec, *args, **kwargs)

        def type_text(self, text: str, *args: Any, **kwargs: Any) -> None:
            self_log_action("type_text", text, *args, **kwargs)

    backend = DummyInputBackend()

# Make the selected 'backend' object available for import from this package.
__all__ = ["backend"]