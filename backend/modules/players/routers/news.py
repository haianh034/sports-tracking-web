import os
import json
import logging
import concurrent.futures
from fastapi import APIRouter
from pydantic import BaseModel
import httpx

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/news", tags=["news"])

class DecodeUrlsRequest(BaseModel):
    urls: list[str]

# Lưu cache URL đã giải mã xuống đĩa (disk persistence) để không phải decode lại
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

def resolve_news_url(url: str) -> str:
    """Trả về link báo gốc nếu đã giải mã, hoặc link hiện tại nếu chưa/không cần giải mã."""
    if not url:
        return ""
    return DECODED_URL_CACHE.get(url, url)

# Tái sử dụng HTTP client kết nối sẵn
_HTTP_CLIENT = httpx.Client(
    timeout=6.0,
    follow_redirects=True,
    headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
)

def _decode_single_url(url: str) -> tuple[str, str]:
    if not url or "news.google.com" not in url:
        return url, url

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

    # Method 2: HTTP fallback with persistent client
    try:
        resp = _HTTP_CLIENT.get(url)
        final_url = str(resp.url)
        if final_url and "news.google.com" not in final_url:
            return url, final_url
    except Exception as e:
        logger.warning(f"HTTP fallback decode failed for {url}: {e}")

    return url, url

@router.post("/decode-urls")
def decode_news_urls(payload: DecodeUrlsRequest):
    results = []
    to_decode = []
    
    for u in payload.urls:
        if not u or "news.google.com" not in u:
            results.append(u)
        elif u in DECODED_URL_CACHE and "news.google.com" not in DECODED_URL_CACHE[u]:
            results.append(DECODED_URL_CACHE[u])
        else:
            to_decode.append(u)

    if to_decode:
        new_added = False
        failed_in_batch = []
        try:
            from googlenewsdecoder.decoder import GoogleDecoder
            with GoogleDecoder(timeout=8.0) as dec:
                batch_res = dec.decode_google_news_urls(to_decode, interval=0.08)
                for raw_u, res in zip(to_decode, batch_res):
                    if res.get("success") and res.get("decoded_url"):
                        real_u = res["decoded_url"]
                        if real_u and "news.google.com" not in real_u:
                            DECODED_URL_CACHE[raw_u] = real_u
                            new_added = True
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
                        new_added = True
                except Exception:
                    pass

        if new_added:
            _save_decoded_cache()

        final_list = []
        for u in payload.urls:
            final_list.append(DECODED_URL_CACHE.get(u, u))
        return {"success": True, "decoded_urls": final_list}

    return {"success": True, "decoded_urls": results}

