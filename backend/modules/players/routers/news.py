import logging
import concurrent.futures
from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/news", tags=["news"])

class DecodeUrlsRequest(BaseModel):
    urls: list[str]

DECODED_URL_CACHE = {}

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
            from googlenewsdecoder import gnewsdecoder

            def _dec(url):
                try:
                    res = gnewsdecoder(url)
                    if res.get("success") and res.get("decoded_url"):
                        return url, res["decoded_url"]
                except Exception as e:
                    logger.warning(f"Error decoding Google News URL {url}: {e}")
                return url, url

            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
                dec_results = list(ex.map(_dec, to_decode))
                for raw_u, real_u in dec_results:
                    DECODED_URL_CACHE[raw_u] = real_u
        except ImportError as ie:
            logger.error(f"googlenewsdecoder module not installed: {ie}")
        except Exception as e:
            logger.error(f"Unexpected error in decode_news_urls: {e}")

        final_list = []
        for u in payload.urls:
            final_list.append(DECODED_URL_CACHE.get(u, u))
        return {"success": True, "decoded_urls": final_list}

    return {"success": True, "decoded_urls": results}

