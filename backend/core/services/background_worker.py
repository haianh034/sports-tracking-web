import asyncio
import datetime
import logging
from backend.core.db.session import SessionLocal
from backend.core.services.batch_sync_service import execute_batched_sync

logger = logging.getLogger("background_worker")

class BackgroundSyncWorker:
    def __init__(self, interval_seconds: int = 1200): # 20 phút mặc định
        self.interval_seconds = interval_seconds
        self.is_running = False
        self.last_sync_time = None
        self.last_status = "idle"
        self._task = None

    async def start(self):
        if self.is_running:
            return
        self.is_running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("BackgroundSyncWorker đã khởi động thành công.")

    async def stop(self):
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("BackgroundSyncWorker đã dừng.")

    async def _run_loop(self):
        # Đợi 5 giây sau khi server khởi động để hệ thống ổn định trước lần quét đầu
        await asyncio.sleep(5)
        while self.is_running:
            try:
                await self.sync_once()
            except Exception as e:
                logger.error(f"Lỗi khi chạy background sync: {e}")
                self.last_status = f"error: {str(e)}"
            
            try:
                await asyncio.sleep(self.interval_seconds)
            except asyncio.CancelledError:
                break

    async def sync_once(self) -> dict:
        self.last_status = "syncing"
        loop = asyncio.get_event_loop()
        
        def _job():
            db = SessionLocal()
            try:
                return execute_batched_sync(db, update_news=True)
            finally:
                db.close()

        res = await loop.run_in_executor(None, _job)
        self.last_sync_time = datetime.datetime.now()
        self.last_status = "completed"
        return res

# Singleton instance
worker = BackgroundSyncWorker(interval_seconds=1200)

