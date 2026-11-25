import os
import re
import json
import base64
import logging
import urllib.parse
import concurrent.futures
from fastapi import APIRouter
from pydantic import BaseModel
import httpx

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/news", tags=["news"])

class DecodeUrlsRequest(BaseModel):
    urls: list[str]

# Lưu cache URL đã giải mã xuống đĩa (disk persistence) kết hợp đồng bộ thẳng vào PostgreSQL DB
DECODED_CACHE_FILE = os.path.join(os.path.dirname(__file__), "decoded_urls_cache.json")
DECODED_URL_CACHE = {}

if os.path.exists(DECODED_CACHE_FILE):
    try:
        with open(DECODED_CACHE_FILE, "r", encoding="utf-8") as f:
            raw_cache = json.load(f)
            # Chỉ giữ các URL đã giải mã thành công (không phải news.google.com)
            DECODED_URL_CACHE = {k: v for k, v in raw_cache.items() if v and "news.google.com" not in v}
    except Exception:
        DECODED_URL_CACHE = {}

def _save_decoded_cache():
    try:
        with open(DECODED_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(DECODED_URL_CACHE, f, ensure_ascii=False)
    except Exception:
        pass

def _persist_decoded_urls_to_db(decoded_map: dict):
    """Lưu vĩnh viễn link báo gốc đã giải mã vào PostgreSQL/SQLite để không mất khi Render restart."""
    if not decoded_map:
        return
    try:
        from backend.core.db.session import SessionLocal
        from backend.core.db.models import PlayerNews, NationalTeamNews
        db = SessionLocal()
        try:
            raw_urls = list(decoded_map.keys())
            p_rows = db.query(PlayerNews).filter(PlayerNews.source_url.in_(raw_urls)).all()
            for row in p_rows:
                new_u = decoded_map.get(row.source_url)
                if new_u and "news.google.com" not in new_u:
                    row.source_url = new_u
            nt_rows = db.query(NationalTeamNews).filter(NationalTeamNews.source_url.in_(raw_urls)).all()
            for row in nt_rows:
                new_u = decoded_map.get(row.source_url)
                if new_u and "news.google.com" not in new_u:
                    row.source_url = new_u
            if p_rows or nt_rows:
                db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Persist decoded URLs to DB failed: {e}")

def _try_offline_decode(url: str) -> str | None:
    """
    Giải mã 100% offline (0ms, không gọi Google, không bao giờ bị chặn IP trên Render):
    - Bing News RSS redirect: ?url=https://...
    - Google News RSS định dạng nhúng Base64 URL trực tiếp.
    """
    if not url:
        return None
    if "bing.com/news/apiclick" in url:
        try:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            if qs.get("url") and qs["url"][0].startswith("http"):
                return qs["url"][0]
        except Exception:
            pass
    if "news.google.com" not in url:
        return url
    try:
        m = re.search(r'/(?:articles|read)/([A-Za-z0-9_\-]+)', url)
        if not m:
            return None
        b64 = m.group(1)
        pad = "=" * ((4 - len(b64) % 4) % 4)
        raw_bytes = base64.urlsafe_b64decode(b64 + pad)
        # Tìm URL http(s) nhúng trực tiếp trong payload protobuf (định dạng cũ)
        m_url = re.search(rb'https?://[^\x00-\x20\x7f-\xff"\'<>]+', raw_bytes)
        if m_url:
            cand = m_url.group(0).decode("utf-8", errors="ignore").strip()
            if cand and "news.google.com" not in cand and "google.com" not in cand:
                return cand
    except Exception:
        pass
    return None

def resolve_news_url(url: str) -> str:
    """Trả về link báo gốc nếu đã giải mã (hoặc giải mã offline ngay), ngược lại trả về link hiện tại."""
    if not url:
        return ""
    if url in DECODED_URL_CACHE:
        return DECODED_URL_CACHE[url]
    if "news.google.com" in url or "bing.com/news/apiclick" in url:
        off = _try_offline_decode(url)
        if off and "news.google.com" not in off:
            DECODED_URL_CACHE[url] = off
            return off
    return url

# Tái sử dụng HTTP client kết nối sẵn kèm Cookie vượt màn hình Consent trên server cloud (Render)
_HTTP_CLIENT = httpx.Client(
    timeout=8.0,
    follow_redirects=True,
    headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    },
    cookies={
        "CONSENT": "YES+cb.20210720-07-p0.en+FX+410",
        "SOCS": "CAESHAgBEhJnd3NfMjAyMzA4MTAtMF9SQzIaAmVuIAEaBgiAo_CmBg",
    },
)

def _decode_single_url(url: str) -> tuple[str, str]:
    if not url or "news.google.com" not in url:
        off = _try_offline_decode(url)
        return url, (off or url)

    # Method 0: Offline Base64 decode (0ms, không bị chặn IP trên Render)
    off = _try_offline_decode(url)
    if off and "news.google.com" not in off:
        return url, off

    # Method 1: googlenewsdecoder với 1 lần retry nhẹ nếu gặp lỗi mạng/thời gian chờ
    for attempt in range(2):
        try:
            from googlenewsdecoder import gnewsdecoder
            res = gnewsdecoder(url)
            if res.get("success") and res.get("decoded_url"):
                decoded = res["decoded_url"]
                if decoded and "news.google.com" not in decoded:
                    return url, decoded
        except Exception as e:
            logger.warning(f"gnewsdecoder attempt {attempt+1} failed for {url}: {e}")
        if attempt == 0:
            import time
            time.sleep(0.4)

    # Method 2: HTTP fallback with Consent cookies
    try:
        resp = _HTTP_CLIENT.get(url)
        final_url = str(resp.url)
        if final_url and "news.google.com" not in final_url and "consent.google.com" not in final_url:
            return url, final_url
    except Exception as e:
        logger.warning(f"HTTP fallback decode failed for {url}: {e}")

    return url, url

@router.post("/decode-urls")
def decode_news_urls(payload: DecodeUrlsRequest):
    results = []
    to_decode = []
    newly_decoded_map = {}

    for u in payload.urls:
        if not u or "news.google.com" not in u:
            off = _try_offline_decode(u)
            results.append(off or u)
        elif u in DECODED_URL_CACHE and "news.google.com" not in DECODED_URL_CACHE[u]:
            results.append(DECODED_URL_CACHE[u])
        else:
            off = _try_offline_decode(u)
            if off and "news.google.com" not in off:
                DECODED_URL_CACHE[u] = off
                newly_decoded_map[u] = off
                results.append(off)
            else:
                to_decode.append(u)

    if to_decode:
        failed_in_batch = []
        try:
            from googlenewsdecoder.decoder import GoogleDecoder
            with GoogleDecoder(timeout=8.0) as dec:
                batch_res = dec.decode_google_news_urls(to_decode, interval=0.12)
                for raw_u, res in zip(to_decode, batch_res):
                    if res.get("success") and res.get("decoded_url"):
                        real_u = res["decoded_url"]
                        if real_u and "news.google.com" not in real_u:
                            DECODED_URL_CACHE[raw_u] = real_u
                            newly_decoded_map[raw_u] = real_u
                        else:
                            failed_in_batch.append(raw_u)
                    else:
                        failed_in_batch.append(raw_u)
        except Exception as e:
            logger.error(f"GoogleDecoder batch error: {e}")
            failed_in_batch = list(to_decode)

        # Retry những link thất bại bằng _decode_single_url
        if failed_in_batch:
            for raw_u in failed_in_batch:
                try:
                    _, real_u = _decode_single_url(raw_u)
                    if real_u and real_u != raw_u and "news.google.com" not in real_u:
                        DECODED_URL_CACHE[raw_u] = real_u
                        newly_decoded_map[raw_u] = real_u
                except Exception:
                    pass

    if newly_decoded_map:
        _save_decoded_cache()
        # Lưu vĩnh viễn vào PostgreSQL để Render không bị mất cache khi restart
        _persist_decoded_urls_to_db(newly_decoded_map)

    final_list = [DECODED_URL_CACHE.get(u, u) for u in payload.urls]
    return {"success": True, "decoded_urls": final_list}

