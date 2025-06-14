# <img src="https://raw.githubusercontent.com/Core-UI/DesktopControllerMCP/main/assets/DesktopControllerMCP-logo.png" width="32" height="32"> DesktopControllerMCP

**Cross-Platform Desktop Automation Service for AI Agents**

![Python 3.13](https://img.shields.io/badge/Python-3.13-blue.svg)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)
![Status](https://img.shields.io/badge/Status-Stable-green.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

<img src="https://raw.githubusercontent.com/Core-UI/DesktopControllerMCP/main/assets/DesktopControllerMCP-workflow.png" alt="DesktopControllerMCP Workflow Example">

*DesktopControllerMCP enables AI agents like Claude Desktop to control graphical user interfaces through a combination of computer vision and synthetic input.*

## 🚀 Key Features

- ✅ **Python 3.13 Ready:** Fully compatible and tested with the latest version of Python.
- 🖥️ **Cross-Platform:** A unified API for Windows, macOS, and Linux.
- 🤖 **AI Agent Integration:** Optimized for Claude Desktop with a high-performance Node.js wrapper to prevent timeouts.
- 👁️ **Computer Vision:** Robust UI element detection via template matching (`OpenCV`) with optional `YOLOv8` support.
- 🖱️⌨️ **Synthetic Input:** Precise, platform-native control of mouse and keyboard without interfering with the physical cursor.
- 듀얼 **Dual Operation Modes:**
    - **Stdio Worker:** For lightning-fast, direct integration with tools like Claude Desktop.
    - **HTTP API Server:** A flexible FastAPI interface for general-purpose automation tasks.
- 📼 **Macro Recorder:** Record and play back user actions to easily automate repetitive tasks.

## 🎯 What is DesktopControllerMCP?

DesktopControllerMCP acts as a bridge between Large Language Models (LLMs) and your desktop's graphical user interface. It allows an AI agent to "see" the screen and "interact" with it as if it were a human user.

**Workflow Loop:**
1.  **Focus:** The agent asks DesktopControllerMCP to focus the "Editor" window.
2.  **Screenshot:** The agent requests a screenshot of that window.
3.  **Analyze:** The agent analyzes the image and finds the coordinates of the "Save" button.
4.  **Input:** The agent instructs DesktopControllerMCP to click on those coordinates.

All of this happens programmatically, quickly, and reliably across all major operating systems.

## ⚡ Quick Start

### 1. Prerequisites
- **Python 3.13**
- **Poetry** (Python Package Manager)
- **Node.js >= 18** (for the Claude Desktop wrapper)
- **(Optional for Linux)** `xdotool` for enhanced input control (`sudo apt install xdotool`)

### 2. Installation
```bash
# 1. Clone the repository
git clone https://github.com/your-repo/DesktopControllerMCP.git # Replace with your repo URL
cd DesktopControllerMCP

# 2. Run the setup script (creates config.json and directories)
python setup_mcp.py

# 3. Install Python dependencies
poetry install

# 4. Install Node.js dependencies
cd mcp-server
npm install
cd ..
```

### 3. Usage

You can use DesktopControllerMCP in two ways:

#### Option 1: For Claude Desktop (Primary Mode)
You don't need to start anything manually! Simply configure your Claude Desktop to use the `mcp-server`. The Node.js wrapper will start the Python worker automatically.

**Example `claude_desktop_config.json`:**
```json
{
  "mcpServers": {
    "DesktopControllerMCP": {
      "command": "node",
      "args": ["C:/path/to/DesktopControllerMCP/mcp-server/index.js"]
    }
  }
}
```

#### Option 2: As a Standalone HTTP API Server
This mode is ideal for custom scripts or integration with other tools.

```bash
# Starts the FastAPI server on http://127.0.0.1:8000
poetry run DesktopControllerMCP-http-api
```
The interactive API documentation (Swagger UI) is available at `http://127.0.0.1:8000/docs`.

## 🛠️ Technical Architecture

DesktopControllerMCP uses a hybrid architecture to ensure maximum performance and flexibility.

| Component | Technology | Role |
| :--- | :--- | :--- |
| **MCP Wrapper** | Node.js | Receives requests from Claude Desktop (MCP/JSON-RPC). Extremely fast startup. |
| **Stdio Worker** | Python | Executes the core automation logic. Communicates with the Node.js wrapper at high speed via Stdio. |
| **HTTP API Server** | Python (FastAPI) | Optionally exposes the automation logic via a universal REST API. |
| **Core Logic** | Python | Cross-platform modules for windowing, input, vision, etc. |

<img src="https://raw.githubusercontent.com/Core-UI/DesktopControllerMCP/main/assets/DesktopControllerMCP-architecture.png" alt="DesktopControllerMCP Architecture">

## 🔧 Configuration

The main configuration is handled via the `config.json` file in the root directory. Here, you can customize:
- API port and host
- Logging level and format
- Default values for computer vision and input simulation
- Security policies for the `npx_execute` tool

## 🔀 Detailed Feature Overview

A complete list of planned and partially implemented tools can be found in the **[TOOL_UPDATE_README.md](TOOL_UPDATE_README.md)**.

**Currently implemented core functions:**
- **Window Management:** `list_windows`, `focus_window`, `get_window_info`, `minimize_window`, etc.
- **Mouse Control:** `click`, `double_click`, `right_click`, `mouse_move`, `mouse_drag`, `mouse_scroll`.
- **Keyboard Control:** `type_text`, `key_press`, `key_combination`.
- **Screen Capture:** `screenshot_window`, `screenshot_region`.
- **Vision:** `click_template`.

## 🐛 Troubleshooting & Known Issues

- **macOS Permissions:** The application that starts DesktopControllerMCP (e.g., Terminal, VS Code) requires "Accessibility" and "Screen Recording" permissions in System Settings.
- **Linux Wayland:** Global input control is highly restricted under Wayland. For the best compatibility, an X11 session is recommended.
- **Incorrect Window Detection:** Ensure `pywinctl` is installed correctly. The `isAlive` check has already been fixed for newer versions.

## 🤝 Contributing

Contributions are welcome! The project is cleanly structured and ready for expansion. Potential next steps include:
- Implementing more tools from the `TOOL_UPDATE_README.md` roadmap.
- Improving Wayland support for the Linux input backend.
- Integrating other computer vision models (e.g., OCR).
- Building out an automated test suite with `pytest`.

## 📄 License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
