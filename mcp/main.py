"""
main.py – FastAPI application entry point for CoreUI-MCP (v0.1.5).

This module provides the HTTP API server implementation using FastAPI.
It loads configuration, sets up logging, CORS, and mounts the MCP router.
"""
import json
import sys
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from mcp.logger import get_logger, setup_logging
from mcp.api.routes import router as mcp_router

# Global configuration - needed for tests
mcp_config: Dict[str, Any] = {}

def load_config(config_path: Path | None = None) -> Dict[str, Any]:
    """Loads configuration from config.json."""
    global mcp_config
    
    if config_path is None:
        config_path = Path.cwd() / "config.json"
    
    default_config = {
        "api": {
            "host": "127.0.0.1",  # Changed from 0.0.0.0 to localhost for Windows
            "port": 8080,         # Changed from 8000 to 8080 for Windows
            "cors_origins": ["*"],
            "api_prefix": "/api/v1"
        },
        "logging": {
            "level": "INFO",
            "file": "logs/mcp_api.log",
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(process)d - %(threadName)s - %(message)s"
        },
        "debug": False,
        "timeout": 300
    }
    
    if config_path.exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                user_config = json.load(f)
            
            # Merge configs - user config overrides defaults
            mcp_config = {**default_config, **user_config}
            # Ensure nested dicts are properly merged
            for key in ["api", "logging"]:
                if key in user_config:
                    mcp_config[key] = {**default_config.get(key, {}), **user_config[key]}
            
            print(f"Configuration loaded from: {config_path}")
        except (json.JSONDecodeError, Exception) as e:
            print(f"Error loading config from {config_path}: {e}. Using defaults.")
            mcp_config = default_config
    else:
        print(f"Config file not found at {config_path}. Using defaults.")
        mcp_config = default_config
    
    return mcp_config

def create_app(config: Dict[str, Any] | None = None) -> FastAPI:
    """Creates and configures the FastAPI application."""
    # Load configuration - use provided config or load from file
    if config is None:
        config = load_config()
    else:
        global mcp_config
        mcp_config = config
    
    # Setup logging
    log_config = config.get("logging", {})
    setup_logging(
        level=log_config.get("level", "INFO"),
        log_file=log_config.get("file"),
        format_string=log_config.get("format"),
        force=True
    )
    
    logger = get_logger(__name__)
    logger.info(f"Starting CoreUI-MCP FastAPI Server v0.1.5")
    
    # Create FastAPI app
    api_config = config.get("api", {})
    app = FastAPI(
        title="CoreUI-MCP Automation API",
        description="Cross-platform desktop automation via screenshots, computer vision, and input simulation",
        version="0.1.5",
        debug=config.get("debug", False),
        docs_url="/docs",
        redoc_url="/redoc",
    )
    
    # Setup CORS
    cors_origins = api_config.get("cors_origins", ["*"])
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Mount the MCP router
    api_prefix = api_config.get("api_prefix", "/api/v1")
    app.include_router(mcp_router, prefix=api_prefix)
    
    # Also mount directly for test compatibility (routes.py has prefix="/mcp")
    app.include_router(mcp_router, prefix="", tags=["MCP Direct Access"])
    
    @app.get("/", summary="API Root", description="Returns basic API information.")
    async def root():
        return {
            "name": "CoreUI-MCP Automation API",
            "version": "0.1.5",
            "status": "running",
            "docs_url": "/docs",
            "api_prefix": api_prefix
        }
    
    @app.get("/health", summary="Health Check", description="Health check endpoint.")
    async def health_check():
        return {
            "service": "CoreUI-MCP", 
            "version": "0.1.5",
            "status": "healthy"
        }
    
    # Global exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request, exc):
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "Internal server error", "detail": str(exc)}
        )
    
    logger.info("FastAPI application created and configured successfully")
    return app

def main_api_server():
    """Main entry point for the FastAPI server (called by poetry scripts)."""
    config = load_config()
    api_config = config.get("api", {})
    
    host = api_config.get("host", "127.0.0.1")  # Windows-friendly default
    port = api_config.get("port", 8080)          # Windows-friendly port
    debug = config.get("debug", False)
    
    print(f"Starting CoreUI-MCP FastAPI server on {host}:{port}")
    print(f"API Documentation: http://{host}:{port}/docs")
    print(f"API Root: http://{host}:{port}/api/v1/")
    
    # Windows-friendly uvicorn config
    uvicorn.run(
        "mcp.main:app",
        host=host,
        port=port,
        reload=debug,
        log_level="info" if not debug else "debug",
        access_log=True,
        # Windows-specific optimizations
        loop="asyncio" if sys.platform == "win32" else "auto",
        workers=1,  # Single worker for Windows compatibility
    )

# Create the app instance for uvicorn
app = create_app()

if __name__ == "__main__":
    main_api_server()