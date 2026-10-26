from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os

# Khối 1: Core (Cơ sở hạ tầng, Database, Worker chung, Router Dashboard tổng hợp)
from backend.core.db.models import init_db
from backend.core.services.background_worker import worker
from backend.core.routers import dashboard

# Khối 2: Modules/Players (Vận động viên)
from backend.modules.players.routers import players, news

# Khối 3: Modules/National Teams (Đội tuyển quốc gia & Tuyển trẻ)
from backend.modules.national_teams.routers import national_teams

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    await worker.start()
    
    # Warm up dashboard cache in background on startup so first user visit loads instantly
    import threading
    def _warmup():
        try:
            from backend.core.db.session import SessionLocal
            from backend.core.routers.dashboard import get_dashboard_data
            db = SessionLocal()
            get_dashboard_data(db=db)
            db.close()
        except Exception:
            pass
    threading.Thread(target=_warmup, daemon=True).start()
    
    yield
    await worker.stop()

app = FastAPI(title="Sports Tracking Web", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if os.path.exists("frontend/static"):
    app.mount("/static", StaticFiles(directory="frontend/static"), name="static")

app.include_router(dashboard.router)
app.include_router(players.router)
app.include_router(news.router)
app.include_router(national_teams.router)

