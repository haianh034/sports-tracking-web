import os
os.environ.setdefault("MALLOC_ARENA_MAX", "2")

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from contextlib import asynccontextmanager

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
    # Tự động nạp sẵn (pre-warm) cache dashboard ngầm khi khởi động để người dùng truy cập lần đầu không bị chờ
    import threading
    def _warmup_cache():
        try:
            from backend.core.db.session import SessionLocal
            from backend.core.routers.dashboard import get_dashboard_data
            db = SessionLocal()
            try:
                get_dashboard_data(db=db)
            finally:
                db.close()
        except Exception:
            pass
    threading.Thread(target=_warmup_cache, daemon=True, name="DashboardWarmup").start()
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
app.add_middleware(GZipMiddleware, minimum_size=1000)

@app.middleware("http")
async def add_no_cache_headers(request, call_next):
    response = await call_next(request)
    # Triệt để loại bỏ tình trạng trình duyệt lưu cache 304 Not Modified cho file JS/CSS tĩnh
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

if os.path.exists("frontend/static"):
    app.mount("/static", StaticFiles(directory="frontend/static"), name="static")

app.include_router(dashboard.router)
app.include_router(players.router)
app.include_router(news.router)
app.include_router(national_teams.router)

