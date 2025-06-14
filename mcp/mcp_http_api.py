#!/usr/bin/env python3
"""
HTTP Server für DesktopControllerMCP-MCP Python Backend
Stellt die DesktopControllerMCP-MCP Funktionalität über HTTP zur Verfügung
"""

import sys
import os
import asyncio
import uvicorn
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, Optional

# Füge DesktopControllerMCP zum Python Path hinzu
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Lazy imports für bessere Performance
_window_module = None
_capture_module = None
_vision_module = None

def get_window_module():
    global _window_module
    if _window_module is None:
        from mcp import window
        _window_module = window
    return _window_module

def get_capture_module():
    global _capture_module
    if _capture_module is None:
        from mcp import capture
        _capture_module = capture
    return _capture_module

def get_vision_module():
    global _vision_module
    if _vision_module is None:
        from mcp import vision
        _vision_module = vision
    return _vision_module

def get_input_module():
    """Get platform-specific input module"""
    import sys
    if sys.platform == "win32":
        from mcp.input import win as input_module
    elif sys.platform == "darwin":
        from mcp.input import mac as input_module
    else:
        from mcp.input import linux as input_module
    return input_module
# FastAPI App
app = FastAPI(
    title="DesktopControllerMCP-MCP HTTP Backend",
    description="HTTP API für DesktopControllerMCP-MCP Funktionalität",
    version="0.2.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request Models
class TestRequest(BaseModel):
    message: str = "Hello"

class WindowRequest(BaseModel):
    title: Optional[str] = None
    visible_only: bool = True

class IdScreenshotRequest(BaseModel):
    title: Optional[str] = None
    window_id: Optional[str] = None
    capture_screen: bool = False

class ClickTemplateRequest(BaseModel):
    template_path: str
    window_title: Optional[str] = None
    threshold: float = 0.8

class ClickRequest(BaseModel):
    x: int
    y: int
    button: str = "left"  # left, right, middle

class TypeTextRequest(BaseModel):
    text: str

class KeyPressRequest(BaseModel):
    key: str  # Virtual key code or key name

# Health Check
@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "DesktopControllerMCP-mcp-backend"}

# Test Endpoint
@app.post("/api/test")
async def test_connection(request: TestRequest):
    return {
        "status": "success",
        "message": f"Python backend received: {request.message}",
        "backend_version": "0.2.0"
    }
# List Windows
@app.post("/api/v1/mcp/list_windows")
async def list_windows_endpoint(request: WindowRequest):
    try:
        window_module = get_window_module()
        windows = await asyncio.to_thread(window_module.list_all_windows)
        
        result = []
        for win in windows:
            try:
                win_info = {
                    "title": await asyncio.to_thread(lambda: win.title),
                    "is_visible": await asyncio.to_thread(win.is_visible),
                    "bbox": await asyncio.to_thread(lambda: win.bbox),
                    "window_id": await asyncio.to_thread(lambda: win.window_id)
                }
                
                if not request.visible_only or win_info["is_visible"]:
                    result.append(win_info)
                    
            except Exception as e:
                print(f"Error processing window: {e}")
                continue
        
        return {"status": "success", "windows": result}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list windows: {str(e)}")

# Focus Window
@app.post("/api/v1/mcp/focus_window")
async def focus_window_endpoint(request: WindowRequest):
    try:
        if not request.title:
            raise HTTPException(status_code=400, detail="Window title is required")
            
        window_module = get_window_module()
        target_window = await asyncio.to_thread(window_module.get_window, title=request.title)
        await asyncio.to_thread(target_window.activate)
        
        return {
            "status": "success", 
            "message": f"Focused window: {request.title}",
            "window_title": await asyncio.to_thread(lambda: target_window.title)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to focus window: {str(e)}")
# Screenshot Window
# ID Screenshot
@app.post("/api/v1/mcp/id_screenshot")
async def id_screenshot_endpoint(request: IdScreenshotRequest):
    try:
        capture_module = get_capture_module()
        
        if request.capture_screen or (not request.title and not request.window_id):
            # Vollbild-Screenshot mit pyautogui
            import pyautogui
            screenshot = await asyncio.to_thread(pyautogui.screenshot)
            
            return {
                "status": "success",
                "message": "Full screen screenshot captured",
                "width": screenshot.width,
                "height": screenshot.height,
                "format": "PNG"
            }
            
        else:
            # Fenster-spezifischer Screenshot
            window_module = get_window_module()
            
            if request.window_id:
                # Finde Fenster nach window_id durch Iteration aller Windows
                windows = await asyncio.to_thread(window_module.list_all_windows)
                target_window = None
                
                for win in windows:
                    try:
                        win_id = await asyncio.to_thread(lambda: win.window_id)
                        if str(win_id) == str(request.window_id):
                            target_window = win
                            break
                    except Exception as e:
                        continue
                
                if not target_window:
                    raise HTTPException(status_code=404, detail=f"Window with ID '{request.window_id}' not found")
                    
            else:
                # Suche nach title
                target_window = await asyncio.to_thread(window_module.get_window, title=request.title)
            
            win_bbox = await asyncio.to_thread(lambda: target_window.bbox)
            
            # Screenshot erstellen
            import base64
            import io
            screenshot = await asyncio.to_thread(capture_module.screenshot, win_bbox, img_format="PNG")
            
            # Base64 encode
            buffer = io.BytesIO()
            await asyncio.to_thread(screenshot.save, buffer, format="PNG")
            img_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
            
            return {
                "status": "success",
                "image_base64": img_base64,
                "width": screenshot.width,
                "height": screenshot.height,
                "format": "PNG",
                "window_title": await asyncio.to_thread(lambda: target_window.title),
                "window_id": await asyncio.to_thread(lambda: getattr(target_window, 'window_id', 'unknown'))
            }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to take screenshot: {str(e)}")

# Click Template (Template Matching + Click)
@app.post("/api/v1/mcp/click_template")
async def click_template_endpoint(request: ClickTemplateRequest):
    try:
        import pathlib
        from PIL import Image
        
        window_module = get_window_module()
        capture_module = get_capture_module()
        vision_module = get_vision_module()
        input_module = get_input_module()
        
        # Get window if specified
        if request.window_title:
            target_window = await asyncio.to_thread(window_module.get_window, title=request.window_title)
            win_bbox = await asyncio.to_thread(lambda: target_window.bbox)
            # Screenshot of window
            screenshot = await asyncio.to_thread(capture_module.screenshot, win_bbox)
        else:
            # Full screen screenshot using pyautogui
            import pyautogui
            screenshot = await asyncio.to_thread(pyautogui.screenshot)
            win_bbox = None
        
        # Load template
        template_path = pathlib.Path(request.template_path)
        if not template_path.exists():
            raise HTTPException(status_code=400, detail=f"Template not found: {request.template_path}")
        
        # Create detector with template path (not PIL Image)
        detector = vision_module.TemplateMatcher(
            template_source=str(template_path),
            threshold=request.threshold
        )
        
        # Perform template matching (synchronous call)
        matches = detector.detect(screenshot)
        
        if not matches:
            return {
                "status": "error",
                "message": f"Template not found with threshold {request.threshold}",
                "matches_found": 0
            }
        
        # Click first match - use .center property correctly
        match = matches[0]
        click_x, click_y = match.center  # Returns tuple (x, y)
        
        # Adjust coordinates if window-relative
        if win_bbox and request.window_title:
            click_x += win_bbox[0]
            click_y += win_bbox[1]
        
        # Perform click
        await asyncio.to_thread(input_module.click, (click_x, click_y), "left")
        
        return {
            "status": "success",
            "message": f"Clicked template at ({click_x}, {click_y})",
            "click_position": {"x": click_x, "y": click_y},
            "confidence": match.score,  # Use .score instead of .confidence
            "matches_found": len(matches)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to click template: {str(e)}")

# Direct Click
@app.post("/api/v1/mcp/click")
async def click_endpoint(request: ClickRequest):
    try:
        input_module = get_input_module()
        await asyncio.to_thread(input_module.click, (request.x, request.y), request.button)
        
        return {
            "status": "success",
            "message": f"Clicked at ({request.x}, {request.y}) with {request.button} button"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to click: {str(e)}")

# Type Text
@app.post("/api/v1/mcp/type_text")
async def type_text_endpoint(request: TypeTextRequest):
    try:
        input_module = get_input_module()
        await asyncio.to_thread(input_module.type_text, request.text)
        
        return {
            "status": "success",
            "message": f"Typed text: {request.text}"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to type text: {str(e)}")

# Key Press
@app.post("/api/v1/mcp/key_press")
async def key_press_endpoint(request: KeyPressRequest):
    try:
        input_module = get_input_module()
        
        # Convert key name to virtual key code if needed
        if hasattr(input_module, 'press'):
            if request.key.isdigit():
                vk_code = int(request.key)
            else:
                # Simple key name to VK mapping for common keys
                key_map = {
                    'enter': 0x0D, 'return': 0x0D,
                    'escape': 0x1B, 'esc': 0x1B,
                    'space': 0x20,
                    'f2': 0x71, 'f5': 0x74,
                    'delete': 0x2E, 'del': 0x2E,
                    'backspace': 0x08,
                    'tab': 0x09,
                    'ctrl': 0x11, 'alt': 0x12, 'shift': 0x10
                }
                vk_code = key_map.get(request.key.lower())
                if vk_code is None:
                    raise ValueError(f"Unknown key: {request.key}")
            
            await asyncio.to_thread(input_module.press, vk_code)
        else:
            raise ValueError("Key press not supported on this platform")
        
        return {
            "status": "success",
            "message": f"Pressed key: {request.key}"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to press key: {str(e)}")

if __name__ == "__main__":
    print("Starting DesktopControllerMCP-MCP HTTP Backend...")
    print(f"Project root: {project_root}")
    
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8001,
        log_level="info"
    )