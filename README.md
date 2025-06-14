# CoreUI-mcp (Model Context Protocol) v0.1.5

> CoreUI is a **cross-platform automation service (Windows, macOS & Linux)** that enables control of desktop applications through a combination of window management, region-based screenshots, computer vision (template matching & optional YOLOv8) and low-level input injection.

> Workflow Example: Focus on a window (`/focus`), take a screenshot of it (`/screenshot`), and click on a UI element based on a template image (`/click`) - all programmatically and without having to move the physical mouse. CoreUI-MCP provides both an HTTP API (via FastAPI) and a dedicated server for direct integration with environments such as Claude Desktop (via JSON-RPC).


## Functions

* 🖥️ **Window Management** - Find, focus and query window information on Windows, macOS & Linux (`pywinctl`).
* 📸 **Async Screencapture** - Efficient capture of entire windows or specific regions (`Base64-encoded`).
* 🖼️ **Image Recognition** - Enhanced UI recognition using caching, multi-scaling and template matching (`OpenCV`).
* 🤖 **Extended Detection** - Expandable YOLOv8 for more robust UI and element detection (requires `ultralytics`).
* 🖱️ **Cursorless Input** - Direct simulation of mouse (click, move, scroll, drag) input without blocking real cursor.
* ⌨️ **Keyboard Input** - Keyboard input (`SendInput` on Windows, `CGEvent` on macOS, `xdotool`/`pynput` on Linux).
* 📼 **Macro Recorder** - Recording of mouse and keyboard actions in JSON files and their playback.
* 🚀 **FastAPI Web-API** - Provides core functions via a modern HTTP interface (`/api/v1/mcp/...`).
* 💬 **MCP Server** - Direct integration via `stdin/stdout` using JSON-RPC for specialized use cases.
* ⚙️ **Configuration** - Customization of API behavior, logging, security settings and more via config.json.
* 📝 **Logging Feedback** - Detailed logging of all important processes for debugging and monitoring.
* 🛡️ **Error Handling** - More specific exceptions and error messages cleaner.


## 📋 Project Structure

The project is organized as follows:

- `mcp/` - Contains all source code for the `mcp` package.
  - `api/` - Handles the FastAPI web API.
    - `routes.py` - Defines API endpoints and request/response logic.
    - `__init__.py` - Makes `api` a Python sub-package.
  - `input/` - Low-level input backends for different operating systems.
    - `win.py` - Windows input backend (using `ctypes` and `SendInput`).
    - `mac.py` - macOS input backend (using `Quartz CGEvent`).
    - `linux.py` - Linux input backend (using `xdotool` or `pynput`).
    - `__init__.py` - Selects the appropriate platform-specific backend.
  - `recorder/` - Macro recording and playback functionality.
    - `recorder.py` - Implements the macro recorder and player logic.
    - `__init__.py` - Makes `recorder` a Python sub-package.
  - `capture.py` - Screenshot and region-handling utilities.
  - `logger.py` - Centralized logging configuration.
  - `main.py` - FastAPI application entry point and server startup.
  - `mcp_server.py` - JSON-RPC server for Claude Desktop and direct MCP integration.
  - `vision.py` - Element detection utilities (template matching, YOLO).
  - `window.py` - Cross-platform window management.
  - `__init__.py` - Main package initializer for `mcp`, sets version and platform specifics.
- `assets/` - Directory for template images (examples provided).
- `logs/` - Directory where log files are saved.
- `config.json` - Configuration file (created by `setup_mcp.py`).
- `pyproject.toml` - Poetry project definition, dependencies, and tool configurations.
- `README.md` - This file.
- `setup_mcp.py` - Setup script for creating directories and default configuration.
- `LICENSE` - Project license file (MIT).


## 🚀 Quick Start Guide

### 1. Prerequisites

*   Python 3.12
*   Poetry (Python package manager): [Installation](https://python-poetry.org/docs/#installation)
*   **For Linux (X11 improved input):** `xdotool` (e.g., `sudo apt install xdotool`)

### 2. Installation

```bash
# Clone the repository
git clone https://github.com/your-repo/CoreUI-mcp.git # Replace with your actual repo URL
cd CoreUI-mcp

# Install dependencies with Poetry
poetry install

# Optional: For YOLOv8 support (object detection)
poetry install --extras yolo # Or poetry install --with yolo, depending on your Poetry version
```

### 3. configuration and setup

Run the setup script to create necessary directories and a default `config.json`:

```bash
poetry run python setup_mcp.py
```

This creates:
* `config.json`: Customize this file if needed (e.g. API port, log level).
* `assets/`: Place your template images for the `click` function here.
* `Logs/`: Log files are saved here.

**Important for macOS:** Make sure that the program (Terminal, Python or the IDE from which you start it) has permissions for “Accessibility” and “Screen Recording” in System Preferences → Privacy & Security.

**Important for Linux:** Global input control (mouse/keyboard) is heavily restricted on Wayland for security reasons. While the Linux backend attempts to use pynput, its ability to control other applications on Wayland is limited. X11 sessions generally offer better compatibility for global input automation, especially if xdotool is installed.


### 4. Starten der CoreUI-MCP Dienste

CoreUI-MCP bietet zwei primäre Betriebsmodi für unterschiedliche Anwendungsfälle:

**a) Stdio Worker für Claude Desktop (Primärer Modus):**

Dieser Modus ist für die direkte Integration mit Claude Desktop über den mitgelieferten NPX-Wrapper vorgesehen. Sie müssen diesen Server **nicht manuell starten**. Der Node.js-Server unter `mcp-server/` startet diesen Worker-Prozess automatisch.

Für Debugging-Zwecke können Sie den Worker manuell starten mit:
```bash
# Startet den Worker, der auf Eingaben via stdin wartet
poetry run coreui-mcp-stdio-worker
```

**b) Eigenständiger HTTP-API-Server (Für Entwicklung und allgemeine Automatisierung):**

Dieser Modus startet einen FastAPI-Server, der die Automatisierungsfunktionen über eine REST-API bereitstellt. Er ist ideal, wenn Sie CoreUI-MCP programmatisch von anderen Skripten oder Anwendungen aus steuern möchten.

```bash
# Startet den HTTP-Server auf http://127.0.0.1:8000
poetry run coreui-mcp-http-api
```

Die API-Dokumentation (Swagger UI) finden Sie dann unter `http://127.0.0.1:8000/docs`.

### 5. use macro recorder

**Record:**
```bash
poetry run mcp-recorder record assets/my_macro.json --duration 30
# Records for 30 seconds or until ESC is pressed. (Assumes mcp-recorder script is not set up in pyproject yet)
# If mcp-recorder script is set up in pyproject.toml:
# poetry run mcp-recorder record assets/my_macro.json --duration 30
```

**Play:**
```bash
poetry run mcp-recorder play assets/my_macro.json --speed 1.0
# If mcp-recorder script is set up in pyproject.toml:
# poetry run mcp-recorder play assets/my_macro.json --speed 1.0
```


## FastAPI API overview (`/api/v1/mcp`)

| Endpoint      | Method | Body (JSON) | Result |
|---------------|--------|----------------------------------------------|------------------------------------------------------------------------------|
| `/focus`      |  POST  | `{title?: string, window_id? : int}`         | `204 No Content` (success) / `404 Not Found` / `500 Internal Server Error`   |
| `/screenshot` |  POST  | `{title?: string, window_id?: int}`          | `200 OK` with `{image_base64, width, height, format}`     / `404` / `500`    |
| `/click`      | POST   | Window Spec: `{title?: string, window_id?: int | str}` <br> Click Spec: `{template_path: string, threshold?: float}` | `202 Accepted` with `{status: "queued", job_id, message}` / `404` / `500`    |
| `/click/status/{job_id}` | GET |          -                           | `200 OK` with job status details / `404 Not Found`                           |
| `/windows`    |  GET   |                  -                           | `200 OK` with list of window objects / `500 Internal Server Error`           |

*Detailed schemas and examples can be found in the Swagger UI (`/docs`). Note: The /click endpoint takes two JSON objects in the request body if using tools like Swagger UI; for programmatic requests, these are typically combined or sent appropriately by the client library.

## MCP Server (Claude Desktop) Tools

The `mcp_server.py` implements the following tools, which can be called via JSON-RPC:

* `list_windows`: Lists all available and visible windows.
* `focus_window`: Focuses a window based on its title.
* `screenshot_window`: Creates a screenshot of a window based on its title.
* `click_template`: Searches for a template image in a window and clicks on it.


## Security notes

* **API access**: By default, the FastAPI server listens on 0.0.0.0, making it accessible on the network. Restrict access via firewalls or reverse proxies and consider implementing authentication (e.g., API keys, OAuth2) if you expose CoreUI-MCP in an untrusted environment.
* **Template paths**: The `template_path` validation in `ClickRequest` is designed to prevent path traversal attacks by restricting paths to configured `assets` directories. Check the configuration in `config.json` (e.g., `security.allowed_template_dirs` if implemented, currently hardcoded to "assets" in `routes.py`).
* **Execute with caution**: CoreUI-mcp can simulate any input on the desktop. Run it with the lowest possible privileges and only in trusted automation scenarios.
* **Linux Input Permissions**: For the Linux backend, `xdotool` might require appropriate X11 permissions. `pynput` might require the process to be run with certain privileges or specific libraries to be installed for full functionality, especially concerning global event listening/posting. Operations requiring `/dev/uinput` (not directly used by current `linux.py` but by tools like `ydotool`) would need root or special group permissions.


## Tests

Run all PyTest tests with coverage:

```bash
poetry run pytest --cov=mcp
# Or if 'src' is specifically the source directory in pytest.ini:
# poetry run pytest --cov=src```

## 🛠️ Extend CoreUI-MCP

*   **Advanced Input Scenarios**: Expose `drag`, `scroll`, direct `keydown`/`keyup`, and `type_text` through the FastAPI and MCP Server interfaces by defining appropriate request schemas and handlers.
*   **Enhance Linux Input Backend**:
    *   Implement more robust Wayland workarounds or specific compositor integrations (very complex).
    *   Add an abstraction layer for key codes/keysyms if a platform-agnostic key input API is desired.
*   **Other Vision Models**: Integrate other object recognition or OCR models in `vision.py`.
*   **Advanced Configuration**: Make more parameters controllable via `config.json`.
*   **Web UI**: Develop a simple web interface for interacting with the FastAPI service.
```


## License

MIT – see the `LICENSE` file.
