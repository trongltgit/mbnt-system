from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from pathlib import Path
import os
import logging

from config import APP_NAME, APP_VERSION, DEBUG
from database import init_db, SessionLocal
from models import User, UserRole
from auth import hash_password
import models as models_module

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description="Internal Foreign Currency Trading System for VCB",
    debug=DEBUG
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
static_path = Path(__file__).parent / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

# Import routers
from routers import auth, admin, transaction, upload, message, report

# Include routers
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(transaction.router)
app.include_router(upload.router)
app.include_router(message.router)
app.include_router(report.router)

@app.on_event("startup")
def startup_event():
    """Initialize database on startup"""
    logger.info("Initializing database...")
    init_db()
    
    # Create default admin if doesn't exist
    db = SessionLocal()
    try:
        admin_user = db.query(User).filter(User.username == "admin").first()
        if not admin_user:
            logger.info("Creating default admin user...")
            admin_user = User(
                username="admin",
                email="admin@vcb.vn",
                full_name="Administrator",
                hashed_password=hash_password("Vcb@1234"),
                role=UserRole.ADMIN.value,
                department="IT",
                is_active=True
            )
            db.add(admin_user)
            db.commit()
            logger.info("Default admin user created. Username: admin, Password: Vcb@1234")
    finally:
        db.close()

@app.get("/", response_class=HTMLResponse)
def root():
    """Root endpoint - serve index.html"""
    index_path = Path(__file__).parent / "static" / "index.html"
    if index_path.exists():
        with open(index_path, "r") as f:
            return f.read()
    return """
    <html>
        <head>
            <title>MBNT System</title>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    margin: 0;
                }
                .container {
                    text-align: center;
                    background: white;
                    padding: 40px;
                    border-radius: 10px;
                    box-shadow: 0 10px 40px rgba(0,0,0,0.1);
                }
                h1 { color: #333; margin: 0; }
                p { color: #666; margin: 10px 0; }
                .links {
                    margin-top: 30px;
                }
                a {
                    display: inline-block;
                    margin: 10px;
                    padding: 10px 20px;
                    background-color: #667eea;
                    color: white;
                    text-decoration: none;
                    border-radius: 5px;
                    transition: background-color 0.3s;
                }
                a:hover {
                    background-color: #764ba2;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>MBNT System</h1>
                <p>GIAO DỊCH MUA BÁN NGOẠI TỆ NỘI BỘ</p>
                <p>Internal Foreign Currency Trading System for VCB</p>
                <div class="links">
                    <a href="/login">Login</a>
                    <a href="/docs">API Documentation</a>
                </div>
            </div>
        </body>
    </html>
    """

@app.get("/health")
def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "app_name": APP_NAME,
        "version": APP_VERSION
    }

@app.get("/api/info")
def api_info():
    """API information"""
    return {
        "app_name": APP_NAME,
        "version": APP_VERSION,
        "description": "Internal Foreign Currency Trading System for VCB",
        "endpoints": {
            "auth": "/api/auth",
            "admin": "/api/admin",
            "transactions": "/api/transactions",
            "upload": "/api/upload",
            "messages": "/api/messages",
            "reports": "/api/reports"
        }
    }

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return {
        "detail": exc.detail,
        "status_code": exc.status_code
    }

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return {
        "detail": "Validation error",
        "errors": exc.errors()
    }

# WebSocket support for real-time notifications (optional enhancement)
from fastapi import WebSocket
from typing import Dict, Set
import json

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, Set[WebSocket]] = {}
    
    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = set()
        self.active_connections[user_id].add(websocket)
    
    def disconnect(self, user_id: int, websocket: WebSocket):
        if user_id in self.active_connections:
            self.active_connections[user_id].discard(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
    
    async def broadcast(self, user_id: int, message: dict):
        if user_id in self.active_connections:
            for connection in self.active_connections[user_id]:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.error(f"Error sending WebSocket message: {e}")

ws_manager = ConnectionManager()

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    """WebSocket endpoint for real-time notifications"""
    await ws_manager.connect(user_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Echo or process messages if needed
            await websocket.send_text(f"Message received: {data}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        ws_manager.disconnect(user_id, websocket)

# Environment-specific configuration
if __name__ == "__main__":
    import uvicorn
    
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=DEBUG,
        log_level="info"
    )
