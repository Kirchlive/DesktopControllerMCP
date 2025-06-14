"""
routes.py – FastAPI layer exposing DesktopControllerMCP-MCP (v0.1.5) core functionality.

This module defines the HTTP API endpoints for interacting with the MCP service.
It aims for:
- Minimal, clear JSON contracts.
- Async-first operations, with heavy tasks offloaded to threads.
- BackgroundTask support for fire-and-forget actions (e.g., click).
- Modularity: this router can be mounted into a parent FastAPI instance.
"""
from __future__ import annotations

import asyncio
import base64
import io
import pathlib
import time 
import sys
import functools
import uuid
from pathlib import Path  # ✅ ADDED: Missing import for Path.cwd()
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, status, Depends, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from PIL import Image  # ✅ ADDED: Missing import for Image type hints

from mcp.logger import get_logger
import mcp.capture as capture
import mcp.vision as vision
import mcp.window as window
from mcp.window import WindowNotFoundError, WindowOperationError, BBox, WindowBackendNotAvailableError
from mcp.vision import VisionError, TemplateNotFoundError, Detection

from mcp.input import backend as input_backend

logger = get_logger(__name__)

router = APIRouter(prefix="/mcp", tags=["MCP Automation Endpoints"])

@functools.lru_cache(maxsize=64)
def get_cached_template_matcher(template_full_path: pathlib.Path, threshold: float) -> vision.TemplateMatcher:
    logger.debug(f"Accessing/creating TemplateMatcher for: {template_full_path}, threshold: {threshold:.2f}")
    try:
        return vision.TemplateMatcher(template_full_path, threshold=threshold)
    except TemplateNotFoundError:
        logger.error(f"Template file not found for TemplateMatcher: {template_full_path}")
        raise
    except VisionError as ve:
        logger.error(f"VisionError creating TemplateMatcher for '{template_full_path}': {ve}", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"Unexpected error creating TemplateMatcher for '{template_full_path}': {e}", exc_info=True)
        raise VisionError(f"Failed to initialize TemplateMatcher for '{template_full_path}': {e!s}") from e

class FocusRequestData(BaseModel):
    title: str | None = Field(None, description="Substring of the window title (case-sensitive).")
    window_id: int | str | None = Field(None, description="Native window handle/ID (e.g., HWND, CGWindowID, XID).")

    @model_validator(mode='after')
    def check_at_least_one_identifier(self) -> 'FocusRequestData':
        if not self.title and self.window_id is None:
            raise ValueError("Either 'title' or 'window_id' must be provided to identify the window.")
        return self

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"title": "Notepad"},
                {"window_id": 123456},
                {"title": "My App", "window_id": "0x7b0a45"}
            ]
        }
    }

class ScreenshotResponseData(BaseModel):
    image_base64: str = Field(description="Base64 encoded string of the screenshot image.")
    width: int = Field(description="Width of the captured image in pixels.")
    height: int = Field(description="Height of the captured image in pixels.")
    format: str = Field("PNG", description="Image format (e.g., 'PNG', 'JPEG').")

class ClickTemplateData(BaseModel):
    template_path: str = Field(
        description="Relative path to the template image within the 'assets' directory (e.g., 'buttons/play.png')."
    )
    threshold: float = Field(
        0.8, ge=0.0, le=1.0,
        description="Match confidence threshold (0.0 to 1.0). Higher means stricter matching."
    )

    @field_validator('template_path')
    @classmethod
    def validate_template_path_str(cls, v_str: str) -> str:
        try:
            project_root = Path.cwd()
            assets_base_dir = (project_root / "assets").resolve()
            if not assets_base_dir.is_dir():
                logger.error(f"Critical: Assets base directory '{assets_base_dir}' does not exist or is not a directory.")
                raise ValueError(f"Server configuration error: Assets directory not found at '{assets_base_dir}'.")

            prospective_path = (assets_base_dir / v_str).resolve()

            if not prospective_path.is_relative_to(assets_base_dir):
                logger.warning(f"Path traversal attempt detected for template_path: '{v_str}' resolved to '{prospective_path}', which is outside '{assets_base_dir}'.")
                raise ValueError(f"Invalid template path: Path is outside the allowed assets directory.")

            if not prospective_path.exists() or not prospective_path.is_file():
                raise ValueError(f"Template file not found at resolved path: {prospective_path} (from input: '{v_str}')")

            allowed_suffixes = ['.png', '.jpg', '.jpeg']
            if prospective_path.suffix.lower() not in allowed_suffixes:
                raise ValueError(f"Template image must be one of {allowed_suffixes}. Found: {prospective_path.suffix}")
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error validating template_path '{v_str}': {e}", exc_info=True)
            raise ValueError(f"Internal error validating template path: {e!s}") from e
        return v_str

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"template_path": "ui_elements/submit_button.png", "threshold": 0.85},
                {"template_path": "icons/save.jpg", "threshold": 0.7}
            ]
        }
    }

class ClickOperationResponse(BaseModel):
    status: str = Field(description="Status of the click operation (e.g., 'queued', 'processing', 'completed', 'error').")
    job_id: str | None = Field(None, description="Unique ID for tracking the background job, if applicable.")
    message: str = Field(description="A descriptive message about the operation's status or result.")
    match_found: bool | None = Field(None, description="True if the template was found, False otherwise.")
    clicked_at: tuple[int, int] | None = Field(None, description="Screen coordinates (data.x, data.y) where the click occurred, if successful.")
    confidence: float | None = Field(None, description="Confidence score of the match, if found.")

# Mouse Control Request Models
class ClickRequest(BaseModel):
    """Request model for mouse click operations"""
    x: int = Field(..., description="X coordinate")
    y: int = Field(..., description="Y coordinate") 
    button: str = Field("left", description="Mouse button (left, right, middle)")

class MouseMoveRequest(BaseModel):
    """Request model for mouse move operations"""
    x: int = Field(..., description="X coordinate")
    y: int = Field(..., description="Y coordinate")

class MouseDragRequest(BaseModel):
    """Request model for mouse drag operations"""
    start_x: int = Field(..., description="Start X coordinate")
    start_y: int = Field(..., description="Start Y coordinate")
    end_x: int = Field(..., description="End X coordinate")
    end_y: int = Field(..., description="End Y coordinate")
    button: str = Field("left", description="Mouse button (left, right, middle)")
    duration: float = Field(0.5, description="Drag duration in seconds")

class MouseScrollRequest(BaseModel):
    """Request model for mouse scroll operations"""
    x: int | None = Field(None, description="X coordinate (optional)")
    y: int | None = Field(None, description="Y coordinate (optional)")
    dx: int = Field(..., description="Horizontal scroll amount")
    dy: int = Field(..., description="Vertical scroll amount")

# Keyboard Control Request Models
class TypeTextRequest(BaseModel):
    """Request model for text typing operations"""
    text: str = Field(..., description="Text to type")

class KeyPressRequest(BaseModel):
    """Request model for key press operations"""
    key: str = Field(..., description="Key to press (e.g., 'enter', 'escape', 'tab')")

class KeyboardInputRequest(BaseModel):
    """Request model for advanced keyboard operations"""
    action: str = Field(..., description="Keyboard action type (combination, special, hold, release)")
    keys: list[str] | None = Field(None, description="Keys for combination (e.g., ['ctrl', 'c'])")
    key: str | None = Field(None, description="Single key for special/hold/release")
    modifiers: list[str] | None = Field(None, description="Modifier keys (ctrl, alt, shift)")

class KeyCombinationRequest(BaseModel):
    """Request model for key combination operations"""
    keys: list[str] = Field(..., description="A list of keys to press in combination, e.g., ['ctrl', 'c']")
    modifiers: list[str] = Field([], description="Optional list of modifier keys.")

class SpecialKeyRequest(BaseModel):
    """Request model for special key operations"""
    special_key: str = Field(..., description="Special key to send")

class KeyHoldRequest(BaseModel):
    """Request model for key hold operations"""  
    key: str = Field(..., description="Key to hold down")

class KeyReleaseRequest(BaseModel):
    """Request model for key release operations"""
    key: str = Field(..., description="Key to release")

class ScreenshotRegionRequest(BaseModel):
    """Request model for region screenshot operations"""
    x: int = Field(..., description="X coordinate")
    y: int = Field(..., description="Y coordinate") 
    width: int = Field(..., description="Width of region")
    height: int = Field(..., description="Height of region")

background_click_tasks_status: dict[str, dict[str, Any]] = {}

@router.post(
    "/focus",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Focus a Window",
    description="Brings the specified window (identified by title or ID) to the foreground and activates it."
)
async def api_focus_window(focus_data: FocusRequestData):
    logger.info(f"API Focus request: title='{focus_data.title}', window_id={focus_data.window_id}")
    try:
        target_win = await asyncio.to_thread(
            window.get_window, title=focus_data.title, window_id=focus_data.window_id
        )
        await asyncio.to_thread(target_win.activate)
        actual_title = await asyncio.to_thread(lambda: target_win.title)
        actual_id = await asyncio.to_thread(lambda: target_win.window_id)
        logger.info(f"Window focused successfully: '{actual_title}' (ID: {actual_id})")
    except WindowNotFoundError as e:
        logger.warning(f"Window not found for focus operation: {e!s}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error_type": "window_not_found", "message": str(e)})
    except WindowOperationError as e:
        logger.error(f"Window operation error during focus: {e!s}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail={"error_type": "window_operation_failed", "message": str(e)})
    except Exception as e:
        logger.error(f"Unexpected error during focus operation: {e!s}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail={"error_type": "internal_server_error", "message": f"An unexpected server error occurred: {e!s}"})

@router.post(
    "/screenshot",
    response_model=ScreenshotResponseData,
    summary="Take Window Screenshot",
    description="Captures a screenshot of the specified window and returns it as a base64 encoded PNG."
)
async def api_take_screenshot(focus_data: FocusRequestData):
    logger.info(f"API Screenshot request: title='{focus_data.title}', window_id={focus_data.window_id}")
    try:
        target_win = await asyncio.to_thread(
            window.get_window, title=focus_data.title, window_id=focus_data.window_id
        )
        actual_title = await asyncio.to_thread(lambda: target_win.title)
        win_bbox: BBox = await asyncio.to_thread(lambda: target_win.bbox)
        img: Image = await capture.screenshot_async(win_bbox, img_format="PNG")  # ✅ FIXED: Using Image instead of Image.Image
        buffer = io.BytesIO()
        await asyncio.to_thread(img.save, buffer, format="PNG", optimize=True)
        img_base64_str: str = base64.b64encode(buffer.getvalue()).decode('utf-8')
        logger.info(f"Screenshot captured for '{actual_title}': {img.width}x{img.height}, Format: PNG")
        return ScreenshotResponseData(
            image_base64=img_base64_str,
            width=img.width,
            height=img.height,
            format="PNG"
        )
    except WindowNotFoundError as e:
        logger.warning(f"Window not found for screenshot: {e!s}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error_type": "window_not_found", "message": str(e)})
    except (capture.CaptureError, WindowOperationError) as e:
        logger.error(f"Error during screenshot capture or window operation: {e!s}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail={"error_type": "screenshot_failed", "message": str(e)})
    except Exception as e:
        logger.error(f"Unexpected error during screenshot operation: {e!s}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail={"error_type": "internal_server_error", "message": f"An unexpected server error occurred: {e!s}"})

async def _background_click_task(
    job_id: str,
    window_spec_data: FocusRequestData,
    click_spec_data: ClickTemplateData,
):
    current_task_status = background_click_tasks_status[job_id]
    current_task_status["status"] = "processing"
    current_task_status["message"] = "Click operation is now being processed."
    logger.info(f"Background Job ID {job_id}: Starting click task. Window: '{window_spec_data.title or window_spec_data.window_id}', Template: '{click_spec_data.template_path}'")

    try:
        project_root = Path.cwd()
        assets_dir = (project_root / "assets").resolve()
        absolute_template_path = (assets_dir / click_spec_data.template_path).resolve()

        target_win = await asyncio.to_thread(
            window.get_window,
            title=window_spec_data.title,
            window_id=window_spec_data.window_id
        )
        actual_win_title = await asyncio.to_thread(lambda: target_win.title)
        current_task_status["window_actual_title"] = actual_win_title
        win_bbox: BBox = await asyncio.to_thread(lambda: target_win.bbox)
        screenshot_img: Image = await capture.screenshot_async(win_bbox)  # ✅ FIXED: Using Image instead of Image.Image
        detector = get_cached_template_matcher(absolute_template_path, click_spec_data.threshold)
        detection_result: Detection | None = await asyncio.to_thread(vision.locate, screenshot_img, detector)

        if not detection_result:
            message = f"Template '{click_spec_data.template_path}' not found in window '{actual_win_title}' with threshold {click_spec_data.threshold:.2f}."
            logger.warning(f"Job ID {job_id}: {message}")
            current_task_status.update({"status": "completed", "match_found": False, "message": message})
            return

        click_x_abs = win_bbox[0] + detection_result.center[0]
        click_y_abs = win_bbox[1] + detection_result.center[1]
        click_pos_abs = (click_x_abs, click_y_abs)
        await asyncio.to_thread(input_backend.click, click_pos_abs)
        message = (f"Successfully clicked template '{click_spec_data.template_path}' in window '{actual_win_title}' "
                   f"at screen coordinates {click_pos_abs} (Confidence: {detection_result.score:.3f}).")
        logger.info(f"Job ID {job_id}: {message}")
        current_task_status.update({
            "status": "completed",
            "match_found": True,
            "message": message,
            "clicked_at": click_pos_abs,
            "confidence": round(detection_result.score, 3)
        })
    except WindowNotFoundError as e:
        msg = f"Window not found during click task: {e!s}"
        logger.warning(f"Job ID {job_id}: {msg}")
        current_task_status.update({"status": "error", "error_type": "window_not_found", "message": msg})
    except (VisionError, capture.CaptureError, WindowOperationError) as e:
        msg = f"Error during vision processing, capture, or window op: {type(e).__name__} - {e!s}"
        logger.error(f"Job ID {job_id}: {msg}", exc_info=True)
        current_task_status.update({"status": "error", "error_type": type(e).__name__.lower(), "message": msg})
    except Exception as e:
        msg = f"Unexpected error during background click task: {type(e).__name__} - {e!s}"
        logger.critical(f"Job ID {job_id}: {msg}", exc_info=True)
        current_task_status.update({"status": "error", "error_type": "internal_task_error", "message": msg})

@router.post(
    "/click",
    response_model=ClickOperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Click UI Element by Template",
    description="Locates a template image within a specified window and clicks its center. This is a background operation."
)
async def api_click_template(
    background_tasks_runner: BackgroundTasks,
    window_spec: FocusRequestData = Body(..., embed=True, title="Window Specification"),
    click_spec: ClickTemplateData = Body(..., embed=True, title="Click Template Specification"),
):
    job_id = str(uuid.uuid4())
    logger.info(
        f"API Click request queued (Job ID: {job_id}). "
        f"Window: '{window_spec.title or window_spec.window_id}', Template: '{click_spec.template_path}', Threshold: {click_spec.threshold:.2f}"
    )
    initial_job_status = {
        "status": "queued",
        "message": "Click operation has been queued for background execution.",
        "job_id": job_id,
        "template_path": click_spec.template_path,
        "window_identifier": window_spec.title or str(window_spec.window_id),
        "timestamp_queued": time.time() 
    }
    background_click_tasks_status[job_id] = initial_job_status
    background_tasks_runner.add_task(
        _background_click_task,
        job_id,
        window_spec,
        click_spec
    )
    return ClickOperationResponse(
        status="queued",
        job_id=job_id,
        message=f"Click operation for template '{click_spec.template_path}' has been queued. "
                f"Check status at /click/status/{job_id}"
    )

@router.get(
    "/click/status/{job_id}",
    response_model=dict[str, Any],
    summary="Get Click Operation Status",
    description="Retrieves the status of a backgrounded click operation by its Job ID."
)
async def api_get_click_status(job_id: str):
    logger.debug(f"API request for click job status: Job ID {job_id}")
    status_info = background_click_tasks_status.get(job_id)
    if not status_info:
        logger.warning(f"Click job ID '{job_id}' not found in status store.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_type": "job_not_found", "message": f"Click job ID '{job_id}' not found."}
        )
    return status_info

@router.get(
    "/windows",
    response_model=list[dict[str, Any]],
    summary="List Available Windows",
    description="Lists all currently available and visible windows that have a title."
)
async def api_list_windows() -> list[dict[str, Any]]:
    logger.info("API List Windows request received.")
    try:
        mcp_windows: list[window.Window] = await asyncio.to_thread(window.list_all_windows)
        
        result_list: list[dict[str, Any]] = []
        for w_obj in mcp_windows:
            try:
                w_title: str = await asyncio.to_thread(lambda: w_obj.title)
                # ✅ FIXED: Corrected lambda to call the method
                w_is_visible: bool = await asyncio.to_thread(lambda: w_obj.is_visible()) 

                if w_title and w_title != "Untitled Window" and w_is_visible:
                    w_bbox: BBox = await asyncio.to_thread(lambda: w_obj.bbox)
                    w_id: int | str | None = await asyncio.to_thread(lambda: w_obj.window_id)
                    result_list.append({
                        "title": w_title,
                        "window_id": w_id,
                        "is_visible": w_is_visible,
                        "bbox": {
                            "left": w_bbox[0], "top": w_bbox[1],
                            "width": w_bbox[2], "height": w_bbox[3]
                        },
                        "backend_used": w_obj._backend_name_used
                    })
            except WindowOperationError as e_win_op:
                logger.warning(f"Could not fully process a window during list_windows: {e_win_op!s}")
            except Exception as e_ind_win:
                logger.warning(f"Generic error processing individual window in list_windows: {e_ind_win!s}", exc_info=False)
        
        logger.info(f"Listed {len(result_list)} processable windows.")
        return result_list
    except WindowBackendNotAvailableError as e:
        logger.critical(f"Window backend not available for listing windows: {e!s}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail={"error_type":"backend_unavailable", "message": str(e)})
    except Exception as e:
        logger.error(f"Unexpected error during list_windows operation: {e!s}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail={"error_type": "internal_server_error", "message": f"Failed to enumerate windows: {e!s}"})# === PHASE 1 BACKEND APIS ===

# SYSTEM INFO APIs
@router.get(
    "/get_screen_resolution",
    response_model=dict[str, Any],
    summary="Get Screen Resolution",
    description="Get screen resolution and dimensions"
)
async def api_get_screen_resolution():
    logger.info("API Get Screen Resolution request received.")
    try:
        import pyautogui
        width, height = pyautogui.size()
        return {
            "width": width,
            "height": height,
            "message": f"Screen resolution: {width}x{height}"
        }
    except Exception as e:
        logger.error(f"Error getting screen resolution: {e!s}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_type": "system_error", "message": f"Failed to get screen resolution: {e!s}"}
        )

@router.get(
    "/get_mouse_position",
    response_model=dict[str, Any],
    summary="Get Mouse Position",
    description="Get current mouse cursor position"
)
async def api_get_mouse_position():
    logger.info("API Get Mouse Position request received.")
    try:
        import pyautogui
        x, y = pyautogui.position()
        return {
            "x": x,
            "y": y,
            "message": f"Mouse position: ({x}, {y})"
        }
    except Exception as e:
        logger.error(f"Error getting mouse position: {e!s}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_type": "system_error", "message": f"Failed to get mouse position: {e!s}"}
        )

@router.get(
    "/get_system_info",
    response_model=dict[str, Any],
    summary="Get System Information",
    description="Get system information (OS, CPU, memory, etc.)"
)
async def api_get_system_info():
    logger.info("API Get System Info request received.")
    try:
        import platform
        import psutil
        import pyautogui
        
        # Get screen count
        try:
            screen_count = len(pyautogui.getAllDisplays())
        except:
            screen_count = 1
            
        system_info = {
            "os": platform.system(),
            "os_version": platform.version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "cpu_count": psutil.cpu_count(),
            "memory_gb": round(psutil.virtual_memory().total / (1024**3), 2),
            "screen_count": screen_count,
            "python_version": platform.python_version()
        }
        
        return {
            **system_info,
            "message": f"System: {system_info['os']} {system_info['os_version']}, CPU: {system_info['cpu_count']} cores, RAM: {system_info['memory_gb']} GB"
        }
    except Exception as e:
        logger.error(f"Error getting system info: {e!s}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_type": "system_error", "message": f"Failed to get system info: {e!s}"}
        )

# MOUSE CONTROL APIs
@router.post(
    "/double_click",
    response_model=dict[str, Any],
    summary="Double Click",
    description="Double-click at specific coordinates"
)
async def api_double_click(data: ClickRequest):
    logger.info(f"API Double Click request: ({data.x}, {data.y}) with {data.button} button")
    try:
        await asyncio.to_thread(input_backend.click, (data.x, data.y), data.button)
        await asyncio.to_thread(time.sleep, 0.1)  # Short delay between clicks
        await asyncio.to_thread(input_backend.click, (data.x, data.y), data.button)
        
        return {
            "success": True,
            "x": data.x,
            "y": data.y,
            "button": data.button,
            "message": f"Double click completed at ({data.x}, {data.y}) with {data.button} button"
        }
    except Exception as e:
        logger.error(f"Error during double click: {e!s}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_type": "input_error", "message": f"Double click failed: {e!s}"}
        )

@router.post(
    "/right_click",
    response_model=dict[str, Any],
    summary="Right Click",
    description="Right-click at specific coordinates"
)
async def api_right_click(data: ClickRequest):
    logger.info(f"API Right Click request: ({data.x}, {data.y})")
    try:
        await asyncio.to_thread(input_backend.click, (data.x, data.y), "right")
        
        return {
            "success": True,
            "x": data.x,
            "y": data.y,
            "button": "right",
            "message": f"Right click completed at ({data.x}, {data.y})"
        }
    except Exception as e:
        logger.error(f"Error during right click: {e!s}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_type": "input_error", "message": f"Right click failed: {e!s}"}
        )

@router.post(
    "/mouse_move",
    response_model=dict[str, Any],
    summary="Move Mouse",
    description="Move mouse cursor to specific coordinates"
)
async def api_mouse_move(data: MouseMoveRequest):
    logger.info(f"API Mouse Move request: ({data.x}, {data.y})")
    try:
        await asyncio.to_thread(input_backend.move, (data.x, data.y))
        
        return {
            "success": True,
            "x": data.x,
            "y": data.y,
            "message": f"Mouse moved to ({data.x}, {data.y})"
        }
    except Exception as e:
        logger.error(f"Error during mouse move: {e!s}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_type": "input_error", "message": f"Mouse move failed: {e!s}"}
        )

@router.post(
    "/mouse_drag",
    response_model=dict[str, Any],
    summary="Mouse Drag",
    description="Drag from start coordinates to end coordinates"
)
async def api_mouse_drag(data: MouseDragRequest):
    logger.info(f"API Mouse Drag request: ({data.start_x}, {data.start_y}) to ({data.end_x}, {data.end_y})")
    try:
        await asyncio.to_thread(
            input_backend.drag, 
            (data.start_x, data.start_y), 
            (data.end_x, data.end_y), 
            data.button, 
            data.duration
        )
        
        return {
            "success": True,
            "start_x": data.start_x,
            "start_y": data.start_y,
            "end_x": data.end_x,
            "end_y": data.end_y,
            "button": data.button,
            "duration": data.duration,
            "message": f"Mouse drag completed from ({data.start_x}, {data.start_y}) to ({data.end_x}, {data.end_y})"
        }
    except Exception as e:
        logger.error(f"Error during mouse drag: {e!s}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_type": "input_error", "message": f"Mouse drag failed: {e!s}"}
        )

@router.post(
    "/mouse_scroll",
    response_model=dict[str, Any],
    summary="Mouse Scroll",
    description="Scroll at specific coordinates"
)
async def api_mouse_scroll(data: MouseScrollRequest):
    logger.info(f"API Mouse Scroll request: data.dx={data.dx}, data.dy={data.dy} at ({data.x}, {data.y})")
    try:
        # Move to coordinates if specified
        if data.x is not None and data.y is not None:
            await asyncio.to_thread(input_backend.move, (data.x, data.y))
            
        await asyncio.to_thread(input_backend.scroll, data.dx, data.dy)
        
        return {
            "success": True,
            "dx": data.dx,
            "dy": data.dy,
            "x": data.x,
            "y": data.y,
            "message": f"Mouse scroll completed: dx={data.dx}, dy={data.dy}"
        }
    except Exception as e:
        logger.error(f"Error during mouse scroll: {e!s}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_type": "input_error", "message": f"Mouse scroll failed: {e!s}"}
        )

# WINDOW MANAGEMENT APIs
@router.post(
    "/get_window_info",
    response_model=dict[str, Any],
    summary="Get Window Info",
    description="Get detailed information about a window"
)
async def api_get_window_info(window_spec: FocusRequestData):
    logger.info(f"API Get Window Info request: {window_spec.title or window_spec.window_id}")
    try:
        target_win = await asyncio.to_thread(
            window.get_window,
            title=window_spec.title,
            window_id=window_spec.window_id
        )
        
        win_title = await asyncio.to_thread(lambda: target_win.title)
        win_id = await asyncio.to_thread(lambda: target_win.window_id)
        win_bbox = await asyncio.to_thread(lambda: target_win.bbox)
        is_visible = await asyncio.to_thread(lambda: target_win.is_visible())
        is_active = await asyncio.to_thread(lambda: target_win.is_active())
        is_alive = await asyncio.to_thread(lambda: target_win.is_alive())
        
        return {
            "title": win_title,
            "window_id": win_id,
            "bbox": {
                "left": win_bbox[0],
                "top": win_bbox[1], 
                "width": win_bbox[2],
                "height": win_bbox[3]
            },
            "is_visible": is_visible,
            "is_active": is_active,
            "is_alive": is_alive,
            "backend": target_win._backend_name_used,
            "message": f"Window info for '{win_title}'"
        }
    except WindowNotFoundError as e:
        logger.warning(f"Window not found for info request: {e!s}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_type": "window_not_found", "message": str(e)}
        )
    except Exception as e:
        logger.error(f"Error getting window info: {e!s}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_type": "window_error", "message": f"Get window info failed: {e!s}"}
        )

@router.post(
    "/close_window",
    response_model=dict[str, Any],
    summary="Close Window",
    description="Close a specific window"
)
async def api_close_window(window_spec: FocusRequestData):
    logger.info(f"API Close Window request: {window_spec.title or window_spec.window_id}")
    try:
        target_win = await asyncio.to_thread(
            window.get_window,
            title=window_spec.title,
            window_id=window_spec.window_id
        )
        
        win_title = await asyncio.to_thread(lambda: target_win.title)
        await asyncio.to_thread(target_win.close)
        
        return {
            "success": True,
            "window_title": win_title,
            "message": f"Window '{win_title}' closed successfully"
        }
    except WindowNotFoundError as e:
        logger.warning(f"Window not found for close request: {e!s}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_type": "window_not_found", "message": str(e)}
        )
    except Exception as e:
        logger.error(f"Error closing window: {e!s}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_type": "window_error", "message": f"Close window failed: {e!s}"}
        )

@router.post(
    "/minimize_window",
    response_model=dict[str, Any],
    summary="Minimize Window",
    description="Minimize a specific window"
)
async def api_minimize_window(window_spec: FocusRequestData):
    logger.info(f"API Minimize Window request: {window_spec.title or window_spec.window_id}")
    try:
        target_win = await asyncio.to_thread(
            window.get_window,
            title=window_spec.title,
            window_id=window_spec.window_id
        )
        
        win_title = await asyncio.to_thread(lambda: target_win.title)
        
        # pywinctl und pygetwindow haben unterschiedliche minimize Methoden
        try:
            if hasattr(target_win._window_impl, 'minimize'):
                await asyncio.to_thread(target_win._window_impl.minimize)
            else:
                # Fallback for backends without minimize
                logger.warning(f"Window backend does not support minimize for '{win_title}'")
                return {
                    "success": False,
                    "window_title": win_title,
                    "message": f"Minimize not supported for window '{win_title}' with backend {target_win._backend_name_used}"
                }
        except Exception as e_min:
            logger.warning(f"Minimize operation failed for '{win_title}': {e_min!s}")
            return {
                "success": False,
                "window_title": win_title,
                "message": f"Minimize failed for window '{win_title}': {e_min!s}"
            }
        
        return {
            "success": True,
            "window_title": win_title,
            "message": f"Window '{win_title}' minimized successfully"
        }
    except WindowNotFoundError as e:
        logger.warning(f"Window not found for minimize request: {e!s}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_type": "window_not_found", "message": str(e)}
        )
    except Exception as e:
        logger.error(f"Error minimizing window: {e!s}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_type": "window_error", "message": f"Minimize window failed: {e!s}"}
        )

@router.post(
    "/maximize_window", 
    response_model=dict[str, Any],
    summary="Maximize Window",
    description="Maximize a specific window"
)
async def api_maximize_window(window_spec: FocusRequestData):
    logger.info(f"API Maximize Window request: {window_spec.title or window_spec.window_id}")
    try:
        target_win = await asyncio.to_thread(
            window.get_window,
            title=window_spec.title,
            window_id=window_spec.window_id
        )
        
        win_title = await asyncio.to_thread(lambda: target_win.title)
        
        # pywinctl und pygetwindow haben unterschiedliche maximize Methoden
        try:
            if hasattr(target_win._window_impl, 'maximize'):
                await asyncio.to_thread(target_win._window_impl.maximize)
            else:
                # Fallback for backends without maximize
                logger.warning(f"Window backend does not support maximize for '{win_title}'")
                return {
                    "success": False,
                    "window_title": win_title,
                    "message": f"Maximize not supported for window '{win_title}' with backend {target_win._backend_name_used}"
                }
        except Exception as e_max:
            logger.warning(f"Maximize operation failed for '{win_title}': {e_max!s}")
            return {
                "success": False,
                "window_title": win_title,
                "message": f"Maximize failed for window '{win_title}': {e_max!s}"
            }
        
        return {
            "success": True,
            "window_title": win_title,
            "message": f"Window '{win_title}' maximized successfully"
        }
    except WindowNotFoundError as e:
        logger.warning(f"Window not found for maximize request: {e!s}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_type": "window_not_found", "message": str(e)}
        )
    except Exception as e:
        logger.error(f"Error maximizing window: {e!s}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_type": "window_error", "message": f"Maximize window failed: {e!s}"}
        )

# SCREENSHOT APIs
@router.post(
    "/screenshot_region",
    response_model=dict[str, Any], 
    summary="Screenshot Region",
    description="Take screenshot of a specific screen region"
)
async def api_screenshot_region(data: ScreenshotRegionRequest):
    logger.info(f"API Screenshot Region request: ({data.x}, {data.y}) {data.width}x{data.height}")
    try:
        # Create bbox for region
        region_bbox: BBox = (data.x, data.y, data.width, data.height)
        
        # Take screenshot of region
        img: Image = await capture.screenshot_async(region_bbox, img_format="PNG")
        
        # Convert to base64
        buffer = io.BytesIO()
        await asyncio.to_thread(img.save, buffer, format="PNG", optimize=True)
        img_base64_str: str = base64.b64encode(buffer.getvalue()).decode('utf-8')
        
        return {
            "image_base64": img_base64_str,
            "width": data.width,
            "height": data.height,
            "format": "PNG",
            "region": {"x": data.x, "y": data.y, "width": data.width, "height": data.height},
            "message": f"Screenshot region captured: ({data.x}, {data.y}) {data.width}x{data.height}"
        }
    except Exception as e:
        logger.error(f"Error taking region screenshot: {e!s}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_type": "capture_error", "message": f"Screenshot region failed: {e!s}"}
        )

# KEYBOARD CONTROL APIs
@router.post(
    "/key_combination",
    response_model=dict[str, Any],
    summary="Key Combination",
    description="Press key combination (e.g., Ctrl+C)"
)
async def api_key_combination(data: KeyCombinationRequest):
    logger.info(f"API Key Combination request: {'+'.join(data.modifiers + data.keys)}")
    try:
        # Press modifiers first
        for modifier in data.modifiers:
            await asyncio.to_thread(input_backend.keydown, modifier)
            
        # Press main keys
        for key in data.keys:
            await asyncio.to_thread(input_backend.press, key)
            
        # Release modifiers
        for modifier in reversed(data.modifiers):
            await asyncio.to_thread(input_backend.keyup, modifier)
        
        return {
            "success": True,
            "keys": data.keys,
            "modifiers": data.modifiers,
            "combination": '+'.join(data.modifiers + data.keys),
            "message": f"Key combination '{'+'.join(data.modifiers + data.keys)}' pressed"
        }
    except Exception as e:
        logger.error(f"Error pressing key combination: {e!s}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_type": "input_error", "message": f"Key combination failed: {e!s}"}
        )

@router.post(
    "/send_special_key",
    response_model=dict[str, Any],
    summary="Send Special Key",
    description="Send special keys like Enter, Escape, Tab, etc."
)
async def api_send_special_key(data: SpecialKeyRequest):
    logger.info(f"API Send Special Key request: {data.special_key}")
    try:
        # Map common special key names
        key_mapping = {
            "enter": "enter",
            "return": "enter", 
            "escape": "esc",
            "tab": "tab",
            "space": "space",
            "delete": "delete",
            "backspace": "backspace",
            "home": "home",
            "end": "end",
            "pageup": "pageup",
            "pagedown": "pagedown",
            "arrowup": "up",
            "arrowdown": "down", 
            "arrowleft": "left",
            "arrowright": "right"
        }
        
        # Get the correct key name
        key_to_press = key_mapping.get(data.special_key.lower(), data.special_key)
        
        await asyncio.to_thread(input_backend.press, key_to_press)
        
        return {
            "success": True,
            "special_key": data.special_key,
            "key_pressed": key_to_press,
            "message": f"Special key '{data.special_key}' sent"
        }
    except Exception as e:
        logger.error(f"Error sending special key: {e!s}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_type": "input_error", "message": f"Send special key failed: {e!s}"}
        )

@router.post(
    "/key_hold",
    response_model=dict[str, Any],
    summary="Key Hold",
    description="Hold a key down (keydown without keyup)"
)
async def api_key_hold(data: KeyHoldRequest):
    logger.info(f"API Key Hold request: {data.key}")
    try:
        await asyncio.to_thread(input_backend.keydown, data.key)
        
        return {
            "success": True,
            "key": data.key,
            "message": f"Key '{data.key}' held down"
        }
    except Exception as e:
        logger.error(f"Error holding key: {e!s}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_type": "input_error", "message": f"Key hold failed: {e!s}"}
        )

@router.post(
    "/key_release",
    response_model=dict[str, Any],
    summary="Key Release", 
    description="Release a held key (keyup)"
)
async def api_key_release(data: KeyReleaseRequest):
    logger.info(f"API Key Release request: {data.key}")
    try:
        await asyncio.to_thread(input_backend.keyup, data.key)
        
        return {
            "success": True,
            "key": data.key,
            "message": f"Key '{data.key}' released"
        }
    except Exception as e:
        logger.error(f"Error releasing key: {e!s}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_type": "input_error", "message": f"Key release failed: {e!s}"}
        )
