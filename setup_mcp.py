"""
setup_mcp.py - Setup and Configuration Script for DesktopControllerMCP-MCP (v0.1.5)

This script assists with the initial setup of the DesktopControllerMCP-MCP automation framework.
It performs checks, creates necessary directories, and generates a default
configuration file (`config.json`).

Key operations:
- Checks Python version (requires 3.12+ after this update).
- Verifies platform support (Windows, macOS, Linux).
- Checks for critical external dependencies like xdotool (Linux) and Node.js/npm/npx.
- Creates 'assets/', 'logs/', 'screenshots/', 'macros/', 'schemas/' directories.
- Generates a default 'config.json' with common settings, including npx execution config.
- Provides guidance on platform-specific permissions (e.g., macOS Accessibility).
"""

import sys
import os
import platform
import subprocess # For potential dependency checks or version lookups
import json
from pathlib import Path
from typing import Any # For type hinting dict values

# --- Configuration for the Setup Script ---
MIN_PYTHON_VERSION = (3, 13) # Updated requirement
PROJECT_VERSION = "0.1.5" # Consistent project version

# Define standard directory names
ASSETS_DIR_NAME = "assets"
LOGS_DIR_NAME = "logs"
SCREENSHOTS_DIR_NAME = "screenshots" # For storing captured screenshots
MACROS_DIR_NAME = "macros"           # For storing recorded macros
SCHEMAS_DIR_NAME = "schemas"         # For JSON schemas

# Default configuration structure
DEFAULT_APP_CONFIG: dict[str, Any] = {
    "api": {
        "host": "0.0.0.0",
        "port": 8000,
        "cors_origins": ["*"], # Wide open by default; restrict in production
        "api_prefix": "/api/v1" # Standard prefix for the API
    },
    "capture": {
        "default_format": "PNG",       # Default screenshot format
        "screenshot_quality": 95,    # JPEG quality (if JPEG is used)
        "optimize_images": True,     # Whether to optimize saved images (e.g., PNGs)
    },
    "vision": {
        "default_threshold": 0.8,    # Default confidence threshold for template matching
        "template_matching_method": "TM_CCOEFF_NORMED", # OpenCV method
        "enable_multiscale_template_matching": False, # Whether to use multi-scale by default
    },
    "input_simulation": { # Renamed from "input" to be more descriptive
        "click_delay_ms": 10,       # Small delay after a click action (milliseconds)
        "typing_delay_ms": 5,       # Small delay between typed characters (milliseconds)
        "pyautogui_fail_safe": True,# Enable PyAutoGUI's fail-safe corner
        "pyautogui_pause_s": 0.0,   # Global pause for PyAutoGUI actions (seconds)
    },
    "logging": {
        "level": "INFO",             # Default log level (e.g., DEBUG, INFO, WARNING, ERROR)
        "file": "logs/mcp_core.log", # Path to the main log file (relative to project root)
        "format": "%(asctime)s - %(name)s - %(levelname)s - %(process)d - %(threadName)s - %(message)s"
    },
    "security": {
        "allowed_template_dirs": [ASSETS_DIR_NAME],
        "max_screenshot_size_bytes": 10 * 1024 * 1024,  # 10MB limit for screenshot data
        "api_rate_limit": { 
            "enabled": False, 
            "requests_per_minute": 100
        },
        "npx_execution": { # Configuration for the npx_execute tool
            "use_allowlist": True, # Secure default: only allow explicitly listed packages
            "allowed_packages": [], # Empty by default; user MUST configure this for functionality
            "blocked_command_parts": [ # Comprehensive list of potentially dangerous parts
                "rm ", "del ", "format ", "sudo ", "su ", "mv ", "cp ",
                "chmod ", "chown ", "shutdown", "reboot",
                ">", "<", "|", "&", ";", "$", "..", # Shell metachars and path traversal
                "wget ", "curl ", # Network tools that could download/execute
                "git clone", "npm install", "npm uninstall", "npm update", # Prevent npx from managing packages itself
                "node ", "python ", "perl ", "ruby ", "bash ", "sh ", # Prevent direct interpreter calls
                "&&", "||", # Command chaining
                "`", # Command substitution
                "$(", # Command substitution
                "eval"
            ],
            "allow_package_versions_in_name": True, # Allows 'package@version' to be checked against 'package' in allowlist
            "execution_timeout_seconds": 300, # Default timeout for npx commands (5 minutes)
            "default_env_vars": { # Example of default environment variables for npx processes
                # "NODE_ENV": "production" # Can be useful for some npx packages
                # "MY_GLOBAL_NPM_TOKEN": "configure_this_if_needed_for_private_packages"
            }
        }
    },
    "recorder": {
        "default_macro_dir": MACROS_DIR_NAME,
        "default_recording_duration_s": 30.0
    }
}

class MCPSetupHelper:
    """
    A helper class to manage the setup process for DesktopControllerMCP-MCP.
    """
    def __init__(self, project_root_dir: Path):
        self.project_root: Path = project_root_dir
        self.config_file_path: Path = self.project_root / "config.json"
        self.assets_dir: Path = self.project_root / ASSETS_DIR_NAME
        self.logs_dir: Path = self.project_root / LOGS_DIR_NAME
        self.screenshots_dir: Path = self.project_root / SCREENSHOTS_DIR_NAME
        self.macros_dir: Path = self.project_root / MACROS_DIR_NAME
        self.schemas_dir: Path = self.project_root / SCHEMAS_DIR_NAME

    def _print_header(self, title: str) -> None:
        print(f"\n--- {title} ---")

    def check_python_version(self) -> bool:
        self._print_header(f"Python Version Check (Minimum Required: {MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]})")
        current_version_str = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        print(f"Current Python version: {current_version_str} (from {sys.executable})")
        if sys.version_info < MIN_PYTHON_VERSION:
            min_req_str = f"{MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]}"
            print(f"[ERROR] Python {min_req_str}+ is required. Please upgrade.")
            return False
        print(f"[OK] Python version {current_version_str} meets the requirement.")
        return True

    def check_platform_support(self) -> None:
        self._print_header("Platform Support Check")
        current_os = platform.system()
        print(f"Operating System: {current_os} ({platform.platform()})")
        supported_platforms = ["Windows", "Darwin", "Linux"]
        if current_os not in supported_platforms:
            print(f"[WARNING] OS '{current_os}' is not officially listed as fully supported.")
            print(f"   DesktopControllerMCP-MCP targets: {', '.join(supported_platforms)}. Some features might not work as expected.")
        else:
            print(f"[OK] Platform '{current_os}' is within targeted systems.")
        if current_os == "Darwin":
            print("\n   macOS Specifics:\n   - Ensure 'Accessibility' & 'Screen Recording' permissions for Terminal/Python/IDE.")
        elif current_os == "Linux":
            print("\n   Linux Specifics:\n   - 'xdotool' recommended for X11 input (`sudo apt install xdotool`).\n   - Wayland input control is restricted.")
        elif current_os == "Windows":
            try:
                import ctypes as win_ctypes
                is_admin = (os.getuid() == 0) if hasattr(os, 'getuid') else (win_ctypes.windll.shell32.IsUserAnAdmin() != 0)
                print(f"   INFO: Running {'with' if is_admin else 'without'} administrator privileges.")
            except Exception: print("   INFO: Could not determine administrator status.")

    def check_external_dependencies(self) -> None:
        self._print_header("External Dependency Checks")
        all_good = True
        if platform.system() == "Linux":
            try:
                result = subprocess.run(["which", "xdotool"], capture_output=True, text=True, check=False)
                if result.returncode == 0 and result.stdout.strip(): print(f"[OK] 'xdotool' found: {result.stdout.strip()}")
                else: print("[WARN] 'xdotool' not found (Recommended for X11 input).")
            except Exception as e: print(f"[WARN] Error checking 'xdotool': {e}")

        node_found, npm_found, npx_found = False, False, False
        try:
            res_node = subprocess.run(["node", "--version"], capture_output=True, text=True, check=False)
            if res_node.returncode == 0 and res_node.stdout.strip(): node_found = True; print(f"[OK] Node.js found: {res_node.stdout.strip()}")
            else: print("[WARN] Node.js not found (Needed for `npm`, `npx`)."); all_good = False
        except Exception as e: print(f"[WARN] Error checking Node.js: {e}"); all_good = False
        
        if node_found:
            try:
                res_npm = subprocess.run(["npm", "--version"], capture_output=True, text=True, check=False)
                if res_npm.returncode == 0 and res_npm.stdout.strip(): npm_found = True; print(f"[OK] npm found: {res_npm.stdout.strip()}")
                else: print("[WARN] npm not found (Needed for Node.js dev tools).")
            except Exception as e: print(f"[WARN] Error checking npm: {e}")
            try:
                res_npx = subprocess.run(["npx", "--version"], capture_output=True, text=True, check=False)
                if res_npx.returncode == 0 and res_npx.stdout.strip(): npx_found = True; print(f"[OK] npx found (npm: {res_npx.stdout.strip()})")
                else: print("[ERROR] npx not found. **CRITICAL for 'npx_execute' tool.**"); all_good = False
            except Exception as e: print(f"[WARN] Error checking npx: {e}"); all_good = False
        
        if node_found and npm_found and npx_found: print("   (Node.js/npm/npx used for 'npx_execute' tool & dev utilities like Prettier).")
        elif not node_found: print("   Install Node.js (includes npm, npx) from https://nodejs.org/ for 'npx_execute' tool & dev utilities.")
        else: print("   Node.js found, but npm/npx might be missing/misconfigured. Ensure complete Node.js installation.")

        if not all_good: print("[WARNING]  Some external dependencies are missing or unverified. Review messages above.")
        else: print("External dependency checks passed or provided relevant information.")

    def setup_project_directories(self) -> None:
        self._print_header("Directory Setup")
        for dir_path in [self.assets_dir, self.logs_dir, self.screenshots_dir, self.macros_dir, self.schemas_dir]:
            try:
                dir_path.mkdir(parents=True, exist_ok=True)
                print(f"[OK] Ensured directory exists: {dir_path.relative_to(self.project_root)}")
            except OSError as e_os: print(f"[ERROR] ERROR: Failed to create directory {dir_path}: {e_os}", file=sys.stderr)

    def create_default_config_file(self, overwrite_existing: bool = False) -> None:
        self._print_header("Configuration File Setup")
        if self.config_file_path.exists() and not overwrite_existing:
            print(f"[OK] Config file '{self.config_file_path.name}' already exists. No changes made.")
            return
        try:
            with open(self.config_file_path, 'w', encoding='utf-8') as f:
                json.dump(DEFAULT_APP_CONFIG, f, indent=2)
            action = "Overwritten" if overwrite_existing and self.config_file_path.exists() else "Created"
            print(f"[OK] {action} default config file: {self.config_file_path.name}")
            print(f"   Review & customize '{self.config_file_path.name}', especially 'security.npx_execution'.")
        except Exception as e: print(f"[ERROR] ERROR writing config file {self.config_file_path}: {e}", file=sys.stderr)

    def create_example_assets(self) -> None:
        self._print_header("Example Asset Creation")
        if not self.assets_dir.exists(): print("[WARN] Assets dir does not exist. Skipping example asset."); return
        example_path = self.assets_dir / "example_play_button.png"
        if example_path.exists(): print(f"[OK] Example asset '{example_path.name}' already exists."); return
        try:
            from PIL import Image, ImageDraw
            img = Image.new('RGB', (64,64), color='lightgray'); draw = ImageDraw.Draw(img)
            draw.polygon([(19,16),(19,48),(51,32)], fill='green', outline='darkgreen')
            img.save(example_path, "PNG")
            print(f"[OK] Created example asset: {example_path.name}")
        except ImportError: print(f"[WARN] Pillow (PIL) not found. Cannot create example asset. Place images in '{ASSETS_DIR_NAME}/'.")
        except Exception as e: print(f"[WARNING]  Warning: Could not create example asset '{example_path.name}': {e}")

    def print_next_steps_guidance(self) -> None:
        self._print_header("Setup Complete!")
        print(f"DesktopControllerMCP-MCP v{PROJECT_VERSION} basic setup is finished.")
        print("\nNext Steps:")
        print("1. Review 'config.json', especially `security.npx_execution` settings:")
        print("   - Configure `use_allowlist`, `allowed_packages` for the 'npx_execute' tool.")
        print("   - Adjust `execution_timeout_seconds` and `default_env_vars` as needed.")
        print("2. Place template images into 'assets/' directory.")
        print("3. Install Python dependencies: `poetry install`")
        if (self.project_root / "package.json").exists():
            print("4. Install Node.js dev dependencies (for Prettier, etc.): `npm install`")
            print("   (Enables `npm run format` for non-Python files.)")
        else:
            print("4. (Optional) For Node.js dev tools (like Prettier), create 'package.json' & run `npm install`.")
        print("\n   Node.js/npm/npx are REQUIRED for the 'npx_execute' tool in MCP Server.")
        print("   Ensure they are installed and in PATH for this tool to function.")
        print("\nStarting Services:")
        print(f"   FastAPI: `poetry run python -m mcp.main` (API docs: http://{DEFAULT_APP_CONFIG['api']['host']}:{DEFAULT_APP_CONFIG['api']['port']}/docs)")
        print("   MCP Server (with 'npx_execute' tool): `poetry run python -m mcp.mcp_server`")
        print(f"   Macro Recorder: `poetry run mcp-recorder record {MACROS_DIR_NAME}/my_macro.json --duration 30`")
        print(f"   Macro Player: `poetry run mcp-recorder play {MACROS_DIR_NAME}/my_macro.json`")
        print("\nRefer to README.md for detailed usage instructions.")

    def run_full_setup(self) -> None:
        print(f"===== DesktopControllerMCP-MCP v{PROJECT_VERSION} Setup Script =====")
        if not self.check_python_version(): sys.exit(1)
        self.check_platform_support()
        self.check_external_dependencies()
        self.setup_project_directories()
        self.create_default_config_file()
        self.create_example_assets()
        self.print_next_steps_guidance()
        print("\n============================================")
        print("Setup finished. Refer to documentation or open an issue for problems.")

if __name__ == "__main__":
    setup_handler = MCPSetupHelper(Path(__file__).resolve().parent)
    setup_handler.run_full_setup()