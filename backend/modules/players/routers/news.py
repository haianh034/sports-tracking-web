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
            DECODED_URL_CACHE = json.load(f)
    except Exception:
        DECODED_URL_CACHE = {}

def _save_decoded_cache():
    try:
        with open(DECODED_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(DECODED_URL_CACHE, f, ensure_ascii=False)
    except Exception:
        pass

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

    # Method 1: googlenewsdecoder
    try:
        from googlenewsdecoder import gnewsdecoder
        res = gnewsdecoder(url)
        if res.get("success") and res.get("decoded_url"):
            decoded = res["decoded_url"]
            if decoded and "news.google.com" not in decoded:
                return url, decoded
    except Exception as e:
        logger.warning(f"gnewsdecoder failed for {url}: {e}")

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
        elif u in DECODED_URL_CACHE:
            results.append(DECODED_URL_CACHE[u])
        else:
            to_decode.append(u)

    if to_decode:
        try:
            # Dùng 5 worker để tránh gây quá tải CPU trên Render
            workers_count = min(5, len(to_decode))
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers_count) as ex:
                dec_results = list(ex.map(_decode_single_url, to_decode))
                new_added = False
                for raw_u, real_u in dec_results:
                    if raw_u != real_u:
                        DECODED_URL_CACHE[raw_u] = real_u
                        new_added = True
                    else:
                        DECODED_URL_CACHE[raw_u] = real_u
                if new_added:
                    _save_decoded_cache()
        except Exception as e:
            logger.error(f"Unexpected error in decode_news_urls thread pool: {e}")

        final_list = []
        for u in payload.urls:
            final_list.append(DECODED_URL_CACHE.get(u, u))
        return {"success": True, "decoded_urls": final_list}

    return {"success": True, "decoded_urls": results}

