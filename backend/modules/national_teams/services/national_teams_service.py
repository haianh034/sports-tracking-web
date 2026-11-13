import urllib.request
import urllib.parse
import json
import hashlib
import xml.etree.ElementTree as ET
import datetime
import re
from sqlalchemy.orm import Session

from backend.core.db.models import Sport, Nationality, NationalTeam, NationalTeamNews

import os

# Cache for national team schedules to ensure lightning-fast UI responses
NT_SCHED_CACHE_FILE = os.path.join(os.path.dirname(__file__), "national_teams_sched_cache.json")
NATIONAL_TEAM_SCHED_CACHE = {}

if os.path.exists(NT_SCHED_CACHE_FILE):
    try:
        with open(NT_SCHED_CACHE_FILE, "r", encoding="utf-8") as f:
            _raw_nt = json.load(f)
            for k, val in _raw_nt.items():
                try:
                    NATIONAL_TEAM_SCHED_CACHE[int(k) if str(k).isdigit() else k] = (val["ts"], val["matches"])
                except Exception:
                    pass
    except Exception:
        pass

import threading

_NT_CACHE_LOCK = threading.Lock()

def _save_nt_sched_cache():
    if not _NT_CACHE_LOCK.acquire(blocking=False):
        return
    try:
        serializable = {}
        for k, v in NATIONAL_TEAM_SCHED_CACHE.items():
            serializable[str(k)] = {"ts": v[0], "matches": v[1]}
        with open(NT_SCHED_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(serializable, f, ensure_ascii=False)
    except Exception:
        pass
    finally:
        _NT_CACHE_LOCK.release()

# OFFICIAL CATALOG OF JAPAN & SOUTH KOREA NATIONAL & YOUTH TEAMS
# Used for searching and adding official teams dynamically
NATIONAL_TEAMS_CATALOG = [
    # 1. BÓNG ĐÁ (SOCCER)
    {
        "id_code": "jp_soccer_senior_m",
        "name": "ĐTQG Nam Nhật Bản",
        "short_name": "ĐTQG Nam Nhật Bản",
        "nickname": "",
        "sport": "Bóng đá",
        "country": "Nhật Bản",
        "tier": "Senior",
        "gender": "Men",
        "api_team_id": "627",
        "flag": "🇯🇵",
        "query_native": "サッカー日本代表",
        "query_en": "Samurai Blue Japan national football team",
        "description": "Đội tuyển bóng đá quốc gia nam Nhật Bản - Vòng loại World Cup 2026 & Asian Cup"
    },
    {
        "id_code": "jp_soccer_senior_w",
        "name": "ĐTQG Nữ Nhật Bản",
        "short_name": "ĐTQG Nữ Nhật Bản",
        "nickname": "",
        "sport": "Bóng đá",
        "country": "Nhật Bản",
        "tier": "Senior",
        "gender": "Women",
        "api_team_id": "2758",
        "flag": "🇯🇵",
        "query_native": "なでしこジャパン サッカー",
        "query_en": "Nadeshiko Japan women football",
        "description": "Đội tuyển bóng đá nữ quốc gia Nhật Bản - FIFA Women's World Cup & Olympics"
    },
    {
        "id_code": "jp_soccer_u23_m",
        "name": "ĐT U23 Nam Nhật Bản",
        "short_name": "ĐT U23 Nam Nhật Bản",
        "nickname": "",
        "sport": "Bóng đá",
        "country": "Nhật Bản",
        "tier": "U23",
        "gender": "Men",
        "api_team_id": "18214",
        "flag": "🇯🇵",
        "query_native": "U-23 サッカー日本代表",
        "query_en": "Japan U23 national soccer team",
        "description": "Đội tuyển U23 bóng đá nam Nhật Bản - U23 Asian Cup & Thế vận hội Olympic"
    },
    {
        "id_code": "jp_soccer_u20_m",
        "name": "ĐT U20 Nam Nhật Bản",
        "short_name": "ĐT U20 Nam Nhật Bản",
        "nickname": "",
        "sport": "Bóng đá",
        "country": "Nhật Bản",
        "tier": "U20",
        "gender": "Men",
        "api_team_id": "9252",
        "flag": "🇯🇵",
        "query_native": "U-20 サッカー日本代表",
        "query_en": "Japan U20 national football team AFC",
        "description": "Đội tuyển U20 quốc gia Nhật Bản - FIFA U-20 World Cup & U20 Asian Cup"
    },
    {
        "id_code": "jp_soccer_u20_w",
        "name": "ĐT U20 Nữ Nhật Bản",
        "short_name": "ĐT U20 Nữ Nhật Bản",
        "nickname": "Young Nadeshiko",
        "sport": "Bóng đá",
        "country": "Nhật Bản",
        "tier": "U20",
        "gender": "Women",
        "api_team_id": "10086",
        "flag": "🇯🇵",
        "query_native": "ヤングなでしこ U-20日本女子代表",
        "query_en": "Young Nadeshiko Japan U20 women",
        "description": "Đội tuyển U20 bóng đá nữ Nhật Bản - FIFA U-20 Women's World Cup"
    },
    {
        "id_code": "jp_soccer_u19_m",
        "name": "ĐT U19 Nam Nhật Bản",
        "short_name": "ĐT U19 Nam Nhật Bản",
        "nickname": "",
        "sport": "Bóng đá",
        "country": "Nhật Bản",
        "tier": "U19",
        "gender": "Men",
        "api_team_id": "9252",
        "flag": "🇯🇵",
        "query_native": "U-19 サッカー日本代表",
        "query_en": "Japan U19 national football team",
        "description": "Đội tuyển U19 quốc gia Nhật Bản"
    },
    {
        "id_code": "jp_soccer_u18_m",
        "name": "ĐT U18 Nam Nhật Bản",
        "short_name": "ĐT U18 Nam Nhật Bản",
        "nickname": "",
        "sport": "Bóng đá",
        "country": "Nhật Bản",
        "tier": "U18",
        "gender": "Men",
        "api_team_id": "8420",
        "flag": "🇯🇵",
        "query_native": "U-18 サッカー日本代表",
        "query_en": "Japan U18 national football team",
        "description": "Đội tuyển U18 quốc gia Nhật Bản"
    },
    {
        "id_code": "jp_soccer_u17_m",
        "name": "ĐT U17 Nam Nhật Bản",
        "short_name": "ĐT U17 Nam Nhật Bản",
        "nickname": "",
        "sport": "Bóng đá",
        "country": "Nhật Bản",
        "tier": "U17",
        "gender": "Men",
        "api_team_id": "8420",
        "flag": "🇯🇵",
        "query_native": "U-17 サッカー日本代表",
        "query_en": "Japan U17 national football team",
        "description": "Đội tuyển U17 bóng đá nam Nhật Bản - FIFA U-17 World Cup & U17 Asian Cup"
    },
    {
        "id_code": "jp_soccer_u17_w",
        "name": "ĐT U17 Nữ Nhật Bản",
        "short_name": "ĐT U17 Nữ Nhật Bản",
        "nickname": "",
        "sport": "Bóng đá",
        "country": "Nhật Bản",
        "tier": "U17",
        "gender": "Women",
        "api_team_id": "21570",
        "flag": "🇯🇵",
        "query_native": "U-17 日本女子代表 サッカー",
        "query_en": "Japan U17 women national football team",
        "description": "Đội tuyển U17 bóng đá nữ Nhật Bản - FIFA U-17 Women's World Cup"
    },
    {
        "id_code": "jp_soccer_u16_m",
        "name": "ĐT U16 Nam Nhật Bản",
        "short_name": "ĐT U16 Nam Nhật Bản",
        "nickname": "",
        "sport": "Bóng đá",
        "country": "Nhật Bản",
        "tier": "U16",
        "gender": "Men",
        "api_team_id": "8420",
        "flag": "🇯🇵",
        "query_native": "U-16 サッカー日本代表",
        "query_en": "Japan U16 national football team",
        "description": "Đội tuyển U16 bóng đá nam Nhật Bản - Vòng loại U17 Asian Cup"
    },
    {
        "id_code": "kr_soccer_senior_m",
        "name": "ĐTQG Nam Hàn Quốc",
        "short_name": "ĐTQG Nam Hàn Quốc",
        "nickname": "",
        "sport": "Bóng đá",
        "country": "Hàn Quốc",
        "tier": "Senior",
        "gender": "Men",
        "api_team_id": "451",
        "flag": "🇰🇷",
        "query_native": "대한민국 축구 국가대표팀",
        "query_en": "South Korea national football team",
        "description": "Đội tuyển bóng đá quốc gia Hàn Quốc - Vòng loại World Cup 2026 & Asian Cup"
    },
    {
        "id_code": "kr_soccer_senior_w",
        "name": "ĐTQG Nữ Hàn Quốc",
        "short_name": "ĐTQG Nữ Hàn Quốc",
        "nickname": "",
        "sport": "Bóng đá",
        "country": "Hàn Quốc",
        "tier": "Senior",
        "gender": "Women",
        "api_team_id": "17639",
        "flag": "🇰🇷",
        "query_native": "대한민국 여자 축구 국가대표팀",
        "query_en": "South Korea women national football team",
        "description": "Đội tuyển bóng đá nữ quốc gia Hàn Quốc - Women's Asian Cup & World Cup"
    },
    {
        "id_code": "kr_soccer_u23_m",
        "name": "ĐT U23 Nam Hàn Quốc",
        "short_name": "ĐT U23 Nam Hàn Quốc",
        "nickname": "",
        "sport": "Bóng đá",
        "country": "Hàn Quốc",
        "tier": "U23",
        "gender": "Men",
        "api_team_id": "19212",
        "flag": "🇰🇷",
        "query_native": "대한민국 U-23 축구 국가대표팀",
        "query_en": "South Korea U23 national soccer team",
        "description": "Đội tuyển U23 bóng đá nam Hàn Quốc - AFC U23 Asian Cup & Asian Games"
    },
    {
        "id_code": "kr_soccer_u20_m",
        "name": "ĐT U20 Nam Hàn Quốc",
        "short_name": "ĐT U20 Nam Hàn Quốc",
        "nickname": "",
        "sport": "Bóng đá",
        "country": "Hàn Quốc",
        "tier": "U20",
        "gender": "Men",
        "api_team_id": "2836",
        "flag": "🇰🇷",
        "query_native": "대한민국 U-20 축구 국가대표팀",
        "query_en": "South Korea U20 national football team",
        "description": "Đội tuyển U20 quốc gia Hàn Quốc - FIFA U-20 World Cup"
    },
    {
        "id_code": "kr_soccer_u20_w",
        "name": "ĐT U20 Nữ Hàn Quốc",
        "short_name": "ĐT U20 Nữ Hàn Quốc",
        "nickname": "",
        "sport": "Bóng đá",
        "country": "Hàn Quốc",
        "tier": "U20",
        "gender": "Women",
        "api_team_id": "18090",
        "flag": "🇰🇷",
        "query_native": "대한민국 U-20 여자 축구 국가대표팀",
        "query_en": "South Korea U20 women national football team",
        "description": "Đội tuyển U20 bóng đá nữ Hàn Quốc - FIFA U-20 Women's World Cup"
    },
    {
        "id_code": "kr_soccer_u19_m",
        "name": "ĐT U19 Nam Hàn Quốc",
        "short_name": "ĐT U19 Nam Hàn Quốc",
        "nickname": "",
        "sport": "Bóng đá",
        "country": "Hàn Quốc",
        "tier": "U19",
        "gender": "Men",
        "api_team_id": "2836",
        "flag": "🇰🇷",
        "query_native": "대한민국 U-19 축구 국가대표팀",
        "query_en": "South Korea U19 national football team",
        "description": "Đội tuyển U19 quốc gia Hàn Quốc"
    },
    {
        "id_code": "kr_soccer_u18_m",
        "name": "ĐT U18 Nam Hàn Quốc",
        "short_name": "ĐT U18 Nam Hàn Quốc",
        "nickname": "",
        "sport": "Bóng đá",
        "country": "Hàn Quốc",
        "tier": "U18",
        "gender": "Men",
        "api_team_id": "8414",
        "flag": "🇰🇷",
        "query_native": "대한민국 U-18 축구 국가대표팀",
        "query_en": "South Korea U18 national football team",
        "description": "Đội tuyển U18 quốc gia Hàn Quốc"
    },
    {
        "id_code": "kr_soccer_u17_m",
        "name": "ĐT U17 Nam Hàn Quốc",
        "short_name": "ĐT U17 Nam Hàn Quốc",
        "nickname": "",
        "sport": "Bóng đá",
        "country": "Hàn Quốc",
        "tier": "U17",
        "gender": "Men",
        "api_team_id": "8414",
        "flag": "🇰🇷",
        "query_native": "대한민국 U-17 축구 국가대표팀",
        "query_en": "South Korea U17 national football team",
        "description": "Đội tuyển U17 quốc gia Hàn Quốc - FIFA U-17 World Cup"
    },
    {
        "id_code": "kr_soccer_u17_w",
        "name": "ĐT U17 Nữ Hàn Quốc",
        "short_name": "ĐT U17 Nữ Hàn Quốc",
        "nickname": "",
        "sport": "Bóng đá",
        "country": "Hàn Quốc",
        "tier": "U17",
        "gender": "Women",
        "api_team_id": "22302",
        "flag": "🇰🇷",
        "query_native": "대한민국 U-17 여자 축구 국가대표팀",
        "query_en": "South Korea U17 women national football team",
        "description": "Đội tuyển U17 bóng đá nữ Hàn Quốc - FIFA U-17 Women's World Cup"
    },
    {
        "id_code": "kr_soccer_u16_m",
        "name": "ĐT U16 Nam Hàn Quốc",
        "short_name": "ĐT U16 Nam Hàn Quốc",
        "nickname": "",
        "sport": "Bóng đá",
        "country": "Hàn Quốc",
        "tier": "U16",
        "gender": "Men",
        "api_team_id": "8414",
        "flag": "🇰🇷",
        "query_native": "대한민국 U-16 축구 국가대표팀",
        "query_en": "South Korea U16 national football team",
        "description": "Đội tuyển U16 bóng đá nam Hàn Quốc - Vòng loại U17 Asian Cup"
    },

    # 2. BÓNG CHÀY (BASEBALL)
    {
        "id_code": "jp_baseball_senior_m",
        "name": "ĐTQG Nam Nhật Bản",
        "short_name": "ĐTQG Nam Nhật Bản",
        "nickname": "",
        "sport": "Bóng chày",
        "country": "Nhật Bản",
        "tier": "Senior",
        "gender": "Men",
        "api_team_id": "7",
        "flag": "🇯🇵",
        "query_native": "侍ジャパン 野球日本代表",
        "query_en": "Samurai Japan baseball national team WBSC",
        "description": "Đội tuyển bóng chày quốc gia Nhật Bản - World Baseball Classic (WBC) & WBSC Premier12"
    },
    {
        "id_code": "jp_baseball_u23_m",
        "name": "ĐT U23 Nam Nhật Bản",
        "short_name": "ĐT U23 Nam Nhật Bản",
        "nickname": "",
        "sport": "Bóng chày",
        "country": "Nhật Bản",
        "tier": "U23",
        "gender": "Men",
        "api_team_id": "samurai_japan_u23",
        "flag": "🇯🇵",
        "query_native": "U-23 侍ジャパン 野球",
        "query_en": "Japan U23 baseball team WBSC",
        "description": "Đội tuyển U23 bóng chày quốc gia Nhật Bản - WBSC U-23 Baseball World Cup"
    },
    {
        "id_code": "jp_baseball_u18_m",
        "name": "ĐT U18 Nam Nhật Bản",
        "short_name": "ĐT U18 Nam Nhật Bản",
        "nickname": "",
        "sport": "Bóng chày",
        "country": "Nhật Bản",
        "tier": "U18",
        "gender": "Men",
        "api_team_id": "samurai_japan_u18",
        "flag": "🇯🇵",
        "query_native": "U-18 侍ジャパン 高校野球日本代表",
        "query_en": "Japan U18 baseball WBSC",
        "description": "Đội tuyển U18 bóng chày quốc gia Nhật Bản - WBSC U-18 Baseball World Cup"
    },
    {
        "id_code": "kr_baseball_senior_m",
        "name": "ĐTQG Nam Hàn Quốc",
        "short_name": "ĐTQG Nam Hàn Quốc",
        "nickname": "",
        "sport": "Bóng chày",
        "country": "Hàn Quốc",
        "tier": "Senior",
        "gender": "Men",
        "api_team_id": "8",
        "flag": "🇰🇷",
        "query_native": "대한민국 야구 국가대표팀",
        "query_en": "South Korea national baseball team WBSC KBO",
        "description": "Đội tuyển bóng chày quốc gia Hàn Quốc - WBC & WBSC Premier12"
    },
    {
        "id_code": "kr_baseball_u23_m",
        "name": "ĐT U23 Nam Hàn Quốc",
        "short_name": "ĐT U23 Nam Hàn Quốc",
        "nickname": "",
        "sport": "Bóng chày",
        "country": "Hàn Quốc",
        "tier": "U23",
        "gender": "Men",
        "api_team_id": "korea_baseball_u23",
        "flag": "🇰🇷",
        "query_native": "대한민국 U-23 야구 대표팀",
        "query_en": "South Korea U23 baseball team WBSC",
        "description": "Đội tuyển U23 bóng chày quốc gia Hàn Quốc - WBSC U-23 Baseball World Cup"
    },
    {
        "id_code": "kr_baseball_u18_m",
        "name": "ĐT U18 Nam Hàn Quốc",
        "short_name": "ĐT U18 Nam Hàn Quốc",
        "nickname": "",
        "sport": "Bóng chày",
        "country": "Hàn Quốc",
        "tier": "U18",
        "gender": "Men",
        "api_team_id": "korea_baseball_u18",
        "flag": "🇰🇷",
        "query_native": "대한민국 U-18 야구 대표팀",
        "query_en": "South Korea U18 baseball team WBSC",
        "description": "Đội tuyển U18 bóng chày quốc gia Hàn Quốc - WBSC U-18 Baseball World Cup"
    },

    # 3. BÓNG RỔ (BASKETBALL)
    {
        "id_code": "jp_basketball_senior_m",
        "name": "ĐTQG Nam Nhật Bản",
        "short_name": "ĐTQG Nam Nhật Bản",
        "nickname": "",
        "sport": "Bóng rổ",
        "country": "Nhật Bản",
        "tier": "Senior",
        "gender": "Men",
        "api_team_id": "17475",
        "flag": "🇯🇵",
        "query_native": "アカツキジャパン バスケ男子日本代表",
        "query_en": "Akatsuki Japan basketball men team FIBA",
        "description": "Đội tuyển bóng rổ nam quốc gia Nhật Bản - FIBA World Cup & Asia Cup"
    },
    {
        "id_code": "jp_basketball_senior_w",
        "name": "ĐTQG Nữ Nhật Bản",
        "short_name": "ĐTQG Nữ Nhật Bản",
        "nickname": "",
        "sport": "Bóng rổ",
        "country": "Nhật Bản",
        "tier": "Senior",
        "gender": "Women",
        "api_team_id": "akatsuki_japan_women",
        "flag": "🇯🇵",
        "query_native": "アカツキジャパン バスケ女子日本代表",
        "query_en": "Japan women basketball team FIBA",
        "description": "Đội tuyển bóng rổ nữ quốc gia Nhật Bản - FIBA Women's World Cup & Olympics"
    },
    {
        "id_code": "jp_basketball_u19_m",
        "name": "ĐT U19 Nam Nhật Bản",
        "short_name": "ĐT U19 Nam Nhật Bản",
        "nickname": "",
        "sport": "Bóng rổ",
        "country": "Nhật Bản",
        "tier": "U19",
        "gender": "Men",
        "api_team_id": "akatsuki_japan_u19",
        "flag": "🇯🇵",
        "query_native": "U19 バスケ日本代表 FIBA",
        "query_en": "Japan U19 basketball FIBA",
        "description": "Đội tuyển U19 bóng rổ Nhật Bản - FIBA U19 Basketball World Cup"
    },
    {
        "id_code": "jp_basketball_u17_m",
        "name": "ĐT U17 Nam Nhật Bản",
        "short_name": "ĐT U17 Nam Nhật Bản",
        "nickname": "",
        "sport": "Bóng rổ",
        "country": "Nhật Bản",
        "tier": "U17",
        "gender": "Men",
        "api_team_id": "akatsuki_japan_u17",
        "flag": "🇯🇵",
        "query_native": "U17 バスケ男子日本代表",
        "query_en": "Japan U17 basketball FIBA",
        "description": "Đội tuyển U17 bóng rổ nam Nhật Bản - FIBA U17 Basketball World Cup"
    },
    {
        "id_code": "kr_basketball_senior_m",
        "name": "ĐTQG Nam Hàn Quốc",
        "short_name": "ĐTQG Nam Hàn Quốc",
        "nickname": "",
        "sport": "Bóng rổ",
        "country": "Hàn Quốc",
        "tier": "Senior",
        "gender": "Men",
        "api_team_id": "17480",
        "flag": "🇰🇷",
        "query_native": "대한민국 농구 국가대표팀",
        "query_en": "South Korea national basketball team FIBA",
        "description": "Đội tuyển bóng rổ quốc gia Hàn Quốc - FIBA Asia Cup"
    },
    {
        "id_code": "kr_basketball_u19_m",
        "name": "ĐT U19 Nam Hàn Quốc",
        "short_name": "ĐT U19 Nam Hàn Quốc",
        "nickname": "",
        "sport": "Bóng rổ",
        "country": "Hàn Quốc",
        "tier": "U19",
        "gender": "Men",
        "api_team_id": "korea_basketball_u19",
        "flag": "🇰🇷",
        "query_native": "대한민국 U-19 농구 대표팀",
        "query_en": "South Korea U19 basketball FIBA",
        "description": "Đội tuyển U19 bóng rổ Hàn Quốc - FIBA U19 World Cup"
    },
    {
        "id_code": "kr_basketball_u17_m",
        "name": "ĐT U17 Nam Hàn Quốc",
        "short_name": "ĐT U17 Nam Hàn Quốc",
        "nickname": "",
        "sport": "Bóng rổ",
        "country": "Hàn Quốc",
        "tier": "U17",
        "gender": "Men",
        "api_team_id": "korea_basketball_u17",
        "flag": "🇰🇷",
        "query_native": "대한민국 U-17 농구 대표팀",
        "query_en": "South Korea U17 basketball FIBA",
        "description": "Đội tuyển U17 bóng rổ nam Hàn Quốc - FIBA U17 World Cup"
    },
    {
        "id_code": "kr_basketball_senior_w",
        "name": "ĐTQG Nữ Hàn Quốc",
        "short_name": "ĐTQG Nữ Hàn Quốc",
        "nickname": "",
        "sport": "Bóng rổ",
        "country": "Hàn Quốc",
        "tier": "Senior",
        "gender": "Women",
        "api_team_id": "17485",
        "flag": "🇰🇷",
        "query_native": "대한민국 여자 농구 국가대표팀",
        "query_en": "South Korea women basketball team FIBA",
        "description": "Đội tuyển bóng rổ nữ quốc gia Hàn Quốc - FIBA Women's Asia Cup & World Cup"
    },

    # 4. BÓNG CHUYỀN (VOLLEYBALL)
    {
        "id_code": "jp_volleyball_senior_m",
        "name": "ĐTQG Nam Nhật Bản",
        "short_name": "ĐTQG Nam Nhật Bản",
        "nickname": "",
        "sport": "Bóng chuyền",
        "country": "Nhật Bản",
        "tier": "Senior",
        "gender": "Men",
        "api_team_id": "ryujin_nippon_senior",
        "flag": "🇯🇵",
        "query_native": "龍神NIPPON バレーボール男子日本代表",
        "query_en": "Ryujin Nippon Japan volleyball team VNL",
        "description": "Đội tuyển bóng chuyền nam quốc gia Nhật Bản - VNL & FIVB World Championship"
    },
    {
        "id_code": "jp_volleyball_senior_w",
        "name": "ĐTQG Nữ Nhật Bản",
        "short_name": "ĐTQG Nữ Nhật Bản",
        "nickname": "",
        "sport": "Bóng chuyền",
        "country": "Nhật Bản",
        "tier": "Senior",
        "gender": "Women",
        "api_team_id": "hinotori_nippon_senior",
        "flag": "🇯🇵",
        "query_native": "火の鳥NIPPON バレーボール女子日本代表",
        "query_en": "Hinotori Nippon Japan women volleyball VNL",
        "description": "Đội tuyển bóng chuyền nữ quốc gia Nhật Bản - VNL & FIVB World Championship"
    },
    {
        "id_code": "jp_volleyball_u21_m",
        "name": "ĐT U21 Nam Nhật Bản",
        "short_name": "ĐT U21 Nam Nhật Bản",
        "nickname": "",
        "sport": "Bóng chuyền",
        "country": "Nhật Bản",
        "tier": "U21",
        "gender": "Men",
        "api_team_id": "japan_volleyball_u21",
        "flag": "🇯🇵",
        "query_native": "男子U21 バレーボール日本代表",
        "query_en": "Japan U21 volleyball team FIVB",
        "description": "Đội tuyển U21 bóng chuyền Nhật Bản - FIVB Volleyball Men's U21 World Championship"
    },
    {
        "id_code": "kr_volleyball_senior_m",
        "name": "ĐTQG Nam Hàn Quốc",
        "short_name": "ĐTQG Nam Hàn Quốc",
        "nickname": "",
        "sport": "Bóng chuyền",
        "country": "Hàn Quốc",
        "tier": "Senior",
        "gender": "Men",
        "api_team_id": "korea_volleyball_senior",
        "flag": "🇰🇷",
        "query_native": "대한민국 남자 배구 국가대표팀",
        "query_en": "South Korea men volleyball team AVC",
        "description": "Đội tuyển bóng chuyền nam quốc gia Hàn Quốc - AVC Asian Championship"
    },
    {
        "id_code": "kr_volleyball_senior_w",
        "name": "ĐTQG Nữ Hàn Quốc",
        "short_name": "ĐTQG Nữ Hàn Quốc",
        "nickname": "",
        "sport": "Bóng chuyền",
        "country": "Hàn Quốc",
        "tier": "Senior",
        "gender": "Women",
        "api_team_id": "korea_volleyball_women",
        "flag": "🇰🇷",
        "query_native": "대한민국 여자 배구 국가대표팀",
        "query_en": "South Korea women national volleyball team VNL",
        "description": "Đội tuyển bóng chuyền nữ Hàn Quốc - VNL & Asian Games"
    },

    # 5. BÓNG BÀN (TABLE TENNIS)
    {
        "id_code": "jp_table_tennis_senior",
        "name": "ĐTQG Nam/Nữ Nhật Bản",
        "short_name": "ĐTQG Nam/Nữ Nhật Bản",
        "nickname": "",
        "sport": "Bóng bàn",
        "country": "Nhật Bản",
        "tier": "Senior",
        "gender": "Mixed",
        "api_team_id": "japan_table_tennis_senior",
        "flag": "🇯🇵",
        "query_native": "卓球日本代表 ITTF",
        "query_en": "Japan national table tennis team ITTF",
        "description": "Đội tuyển bóng bàn quốc gia Nhật Bản - ITTF World Championships"
    },
    {
        "id_code": "jp_table_tennis_youth",
        "name": "ĐT Tuyển trẻ Nhật Bản",
        "short_name": "ĐT Tuyển trẻ Nhật Bản",
        "nickname": "",
        "sport": "Bóng bàn",
        "country": "Nhật Bản",
        "tier": "Youth",
        "gender": "Mixed",
        "api_team_id": "japan_table_tennis_youth",
        "flag": "🇯🇵",
        "query_native": "卓球ジュニア日本代表",
        "query_en": "Japan youth table tennis team WTT",
        "description": "Đội tuyển bóng bàn trẻ Nhật Bản - ITTF World Youth Championships"
    },
    {
        "id_code": "kr_table_tennis_senior",
        "name": "ĐTQG Nam/Nữ Hàn Quốc",
        "short_name": "ĐTQG Nam/Nữ Hàn Quốc",
        "nickname": "",
        "sport": "Bóng bàn",
        "country": "Hàn Quốc",
        "tier": "Senior",
        "gender": "Mixed",
        "api_team_id": "korea_table_tennis_senior",
        "flag": "🇰🇷",
        "query_native": "대한민국 탁구 국가대표팀",
        "query_en": "South Korea national table tennis team ITTF",
        "description": "Đội tuyển bóng bàn quốc gia Hàn Quốc - ITTF World Championships"
    },
    {
        "id_code": "kr_table_tennis_youth",
        "name": "ĐT Tuyển trẻ Hàn Quốc",
        "short_name": "ĐT Tuyển trẻ Hàn Quốc",
        "nickname": "",
        "sport": "Bóng bàn",
        "country": "Hàn Quốc",
        "tier": "Youth",
        "gender": "Mixed",
        "api_team_id": "korea_table_tennis_youth",
        "flag": "🇰🇷",
        "query_native": "대한민국 주니어 탁구 대표팀",
        "query_en": "South Korea youth table tennis team WTT",
        "description": "Đội tuyển trẻ bóng bàn Hàn Quốc - ITTF World Youth Championships"
    },

    # 6. CẦU LÔNG (BADMINTON)
    {
        "id_code": "jp_badminton_senior",
        "name": "ĐTQG Nam/Nữ Nhật Bản",
        "short_name": "ĐTQG Nam/Nữ Nhật Bản",
        "nickname": "",
        "sport": "Cầu lông",
        "country": "Nhật Bản",
        "tier": "Senior",
        "gender": "Mixed",
        "api_team_id": "bird_japan_senior",
        "flag": "🇯🇵",
        "query_native": "バドミントン日本代表 BIRD JAPAN",
        "query_en": "Bird Japan badminton national team BWF",
        "description": "Đội tuyển cầu lông quốc gia Nhật Bản - Thomas & Uber Cup / Sudirman Cup"
    },
    {
        "id_code": "jp_badminton_youth",
        "name": "ĐT Tuyển trẻ Nhật Bản",
        "short_name": "ĐT Tuyển trẻ Nhật Bản",
        "nickname": "",
        "sport": "Cầu lông",
        "country": "Nhật Bản",
        "tier": "Youth",
        "gender": "Mixed",
        "api_team_id": "japan_badminton_youth",
        "flag": "🇯🇵",
        "query_native": "バドミントンジュニア日本代表",
        "query_en": "Japan junior badminton team BWF",
        "description": "Đội tuyển trẻ cầu lông Nhật Bản - BWF World Junior Championships"
    },
    {
        "id_code": "kr_badminton_senior",
        "name": "ĐTQG Nam/Nữ Hàn Quốc",
        "short_name": "ĐTQG Nam/Nữ Hàn Quốc",
        "nickname": "",
        "sport": "Cầu lông",
        "country": "Hàn Quốc",
        "tier": "Senior",
        "gender": "Mixed",
        "api_team_id": "korea_badminton_senior",
        "flag": "🇰🇷",
        "query_native": "대한민국 배드민턴 국가대표팀",
        "query_en": "South Korea national badminton team BWF",
        "description": "Đội tuyển cầu lông quốc gia Hàn Quốc - Thomas & Uber Cup / Sudirman Cup"
    },
    {
        "id_code": "kr_badminton_youth",
        "name": "ĐT Tuyển trẻ Hàn Quốc",
        "short_name": "ĐT Tuyển trẻ Hàn Quốc",
        "nickname": "",
        "sport": "Cầu lông",
        "country": "Hàn Quốc",
        "tier": "Youth",
        "gender": "Mixed",
        "api_team_id": "korea_badminton_youth",
        "flag": "🇰🇷",
        "query_native": "대한민국 주니어 배드민턴 대표팀",
        "query_en": "South Korea junior badminton team BWF",
        "description": "Đội tuyển trẻ cầu lông Hàn Quốc - BWF World Junior Championships"
    },

    # 7. QUẦN VỢT (TENNIS)
    {
        "id_code": "jp_tennis_senior_m",
        "name": "ĐT Davis Cup Nam Nhật Bản",
        "short_name": "ĐT Davis Cup Nam Nhật Bản",
        "nickname": "",
        "sport": "Quần vợt",
        "country": "Nhật Bản",
        "tier": "Senior",
        "gender": "Men",
        "api_team_id": "japan_davis_cup",
        "flag": "🇯🇵",
        "query_native": "テニス男子日本代表 デビスカップ",
        "query_en": "Japan Davis Cup team tennis",
        "description": "Đội tuyển quần vợt nam quốc gia Nhật Bản - Davis Cup"
    },
    {
        "id_code": "jp_tennis_senior_w",
        "name": "ĐT BJK Cup Nữ Nhật Bản",
        "short_name": "ĐT BJK Cup Nữ Nhật Bản",
        "nickname": "",
        "sport": "Quần vợt",
        "country": "Nhật Bản",
        "tier": "Senior",
        "gender": "Women",
        "api_team_id": "japan_bjk_cup",
        "flag": "🇯🇵",
        "query_native": "テニス女子日本代表 ビリージーンキングカップ",
        "query_en": "Japan Billie Jean King Cup team tennis",
        "description": "Đội tuyển quần vợt nữ quốc gia Nhật Bản - Billie Jean King Cup"
    },
    {
        "id_code": "kr_tennis_senior_m",
        "name": "ĐT Davis Cup Nam Hàn Quốc",
        "short_name": "ĐT Davis Cup Nam Hàn Quốc",
        "nickname": "",
        "sport": "Quần vợt",
        "country": "Hàn Quốc",
        "tier": "Senior",
        "gender": "Men",
        "api_team_id": "korea_davis_cup",
        "flag": "🇰🇷",
        "query_native": "대한민국 데이비스컵 대표팀",
        "query_en": "South Korea Davis Cup team tennis",
        "description": "Đội tuyển quần vợt nam quốc gia Hàn Quốc - Davis Cup"
    },
    {
        "id_code": "kr_tennis_senior_w",
        "name": "ĐT BJK Cup Nữ Hàn Quốc",
        "short_name": "ĐT BJK Cup Nữ Hàn Quốc",
        "nickname": "",
        "sport": "Quần vợt",
        "country": "Hàn Quốc",
        "tier": "Senior",
        "gender": "Women",
        "api_team_id": "korea_bjk_cup",
        "flag": "🇰🇷",
        "query_native": "대한민국 빌리진킹컵 대표팀",
        "query_en": "South Korea Billie Jean King Cup team tennis",
        "description": "Đội tuyển quần vợt nữ quốc gia Hàn Quốc - Billie Jean King Cup"
    }
]

def get_catalog_with_status(db: Session) -> list:
    """Returns the catalog with `is_added` and DB `team_id` for UI display."""
    db_teams = db.query(NationalTeam).all()
    name_map = {t.name.lower(): t.id for t in db_teams}
    
    catalog_res = []
    for item in NATIONAL_TEAMS_CATALOG:
        c_copy = dict(item)
        c_name = item["name"].lower()
        if c_name in name_map:
            c_copy["is_added"] = True
            c_copy["team_id"] = name_map[c_name]
        else:
            c_copy["is_added"] = False
            c_copy["team_id"] = None
        catalog_res.append(c_copy)
    return catalog_res


def get_matching_national_team_for_player(sport_name: str, country_name: str, gender: str = "Men") -> dict:
    """
    Tự động tìm kiếm Đội tuyển Quốc gia tương ứng cho VĐV dựa trên Môn thể thao, Quốc gia và Giới tính.
    Luôn trả về ĐTQG cao nhất (Senior) của quốc gia đó.
    """
    s_low = (sport_name or "").lower().strip()
    c_low = (country_name or "").lower().strip()
    g_low = (gender or "Men").lower().strip()
    
    for item in NATIONAL_TEAMS_CATALOG:
        if item.get("tier") != "Senior":
            continue
        if item.get("sport", "").lower() == s_low:
            item_c = item.get("country", "").lower()
            c_match = (
                (("nhật" in c_low or "japan" in c_low) and ("nhật" in item_c or "japan" in item_c)) or
                (("hàn" in c_low or "korea" in c_low) and ("hàn" in item_c or "korea" in item_c)) or
                c_low == item_c
            )
            if c_match:
                item_g = item.get("gender", "Men").lower()
                if item_g == g_low or item_g == "mixed":
                    return item
    return None

def get_matching_national_teams_for_player(sport_name: str, country_name: str, gender: str = "Men") -> list:
    """
    Tự động tìm kiếm danh sách Đội tuyển Quốc gia tương ứng cho VĐV.
    Đối với dòng thời gian của VĐV chuyên nghiệp, chỉ liên kết với ĐTQG Senior chính thức.
    """
    nt = get_matching_national_team_for_player(sport_name, country_name, gender)
    return [nt] if nt else []

def search_national_teams_catalog(query: str, db: Session) -> list:
    """Searches catalog and existing teams for user keyword."""
    all_catalog = get_catalog_with_status(db)
    if not query or not query.strip():
        return all_catalog

    q_clean = query.strip().lower()
    results = []
    for item in all_catalog:
        searchable_text = f"{item['name']} {item['short_name']} {item['nickname']} {item['sport']} {item['country']} {item['tier']} {item.get('query_native', '')}".lower()
        if q_clean in searchable_text:
            results.append(item)
    return results

def add_team_from_catalog(catalog_id: str, db: Session) -> NationalTeam:
    """Adds a team from the official catalog into the DB."""
    item = next((c for c in NATIONAL_TEAMS_CATALOG if c["id_code"] == catalog_id), None)
    if not item:
        # Check by name or id
        item = next((c for c in NATIONAL_TEAMS_CATALOG if c["name"].lower() == catalog_id.lower()), None)
    if not item:
        raise ValueError("Không tìm thấy đội tuyển trong danh mục chính thức.")

    # Check if already in DB
    existing = db.query(NationalTeam).filter(NationalTeam.name == item["name"]).first()
    if existing:
        return existing

    sport = db.query(Sport).filter(Sport.name == item["sport"]).first()
    if not sport:
        sport = Sport(name=item["sport"])
        db.add(sport)
        db.flush()

    nat = db.query(Nationality).filter(Nationality.name == item["country"]).first()
    if not nat:
        nat = Nationality(name=item["country"], flag=item["flag"])
        db.add(nat)
        db.flush()

    team = NationalTeam(
        name=item["name"],
        short_name=item["short_name"],
        nickname=item["nickname"],
        sport_id=sport.id,
        country_id=nat.id,
        tier=item["tier"],
        gender=item["gender"],
        api_team_id=item["api_team_id"],
        flag=item["flag"],
        search_query=item.get("query_native") or item.get("query_en"),
        description=item["description"]
    )
    db.add(team)
    db.commit()
    db.refresh(team)

    # Fetch initial news & schedule immediately
    fetch_national_team_news_feed(team, db, force_refresh=True)
    fetch_national_team_schedule(team)
    return team

def _extract_score_display(c):
    if not c:
        return None
    sc = c.get('score')
    if isinstance(sc, dict):
        val = sc.get('displayValue')
        if val is None:
            v = sc.get('value')
            val = str(int(v)) if v is not None else None
        return str(val) if val is not None else None
    if isinstance(sc, (int, float)):
        return str(int(sc))
    if isinstance(sc, str) and sc.strip():
        return sc.strip()
    return None

def get_national_team_tournament_tag(comp_name: str, match_name: str = "", sport_name: str = "", tier: str = "") -> str:
    """
    Standardizes tournament tag for National Teams & Youth Teams.
    Returns official tournament name (e.g. 'FIFA U-17 World Cup', 'VNL', 'WBC', 'AFC Asian Cup')
    or 'Giao hữu' if it is a friendly or unspecified international match.
    """
    c = (comp_name or "").strip()
    m = (match_name or "").strip().lower()
    c_low = c.lower()
    s_low = (sport_name or "").lower()
    
    # 1. Friendly match detection -> 'Giao hữu'
    friendly_keywords = [
        "friendly", "giao hữu", "club friendly", "international friendly", 
        "giao huu", "exhibition", "practice match", "giải giao hữu", "test match"
    ]
    if any(k in c_low or k in m for k in friendly_keywords):
        return "Giao hữu"
    
    is_soccer = ("bóng đá" in s_low or "soccer" in s_low)
    is_baseball = ("bóng chày" in s_low or "baseball" in s_low)

    # 2. Baseball Tournaments
    if any(k in c_low for k in ["asia professional baseball", "apbc", "asia professional championship"]) or (is_baseball and "asia professional" in c_low):
        return "Asia Professional Baseball Championship"
    if any(k in c_low for k in ["wbc", "world baseball classic"]):
        return "WBC"
    if any(k in c_low for k in ["premier12", "premier 12"]):
        return "WBSC Premier12"
    if any(k in c_low for k in ["u-23 baseball world cup", "u23 baseball world cup"]) or (is_baseball and "world cup" in c_low and ("u23" in c_low or "u-23" in c_low)):
        return "WBSC U-23 World Cup"
    if any(k in c_low for k in ["u-18 baseball world cup", "u18 baseball world cup", "u18 baseball"]) or (is_baseball and "world cup" in c_low and ("u18" in c_low or "u-18" in c_low)):
        return "WBSC U-18 World Cup"

    # 3. Basketball Tournaments
    if any(k in c_low for k in ["fiba u19", "fiba u-19", "u19 world cup"]) and ("bóng rổ" in s_low or "basketball" in s_low or "fiba" in c_low):
        return "FIBA U19 World Cup"
    if any(k in c_low for k in ["fiba u17", "fiba u-17", "u17 world cup"]) and ("bóng rổ" in s_low or "basketball" in s_low or "fiba" in c_low):
        return "FIBA U17 World Cup"
    if any(k in c_low for k in ["fiba world cup", "basketball world cup"]):
        return "FIBA World Cup"
    if any(k in c_low for k in ["fiba asia cup", "asia cup basketball"]):
        return "FIBA Asia Cup"

    # 4. Volleyball Tournaments
    if any(k in c_low for k in ["vnl", "volleyball nations league"]):
        return "VNL"
    if any(k in c_low for k in ["fivb world championship", "world championship"]) and ("volleyball" in s_low or "chuyền" in s_low):
        return "FIVB World Championship"
    if any(k in c_low for k in ["u21 asian", "asian championship"]) and ("volleyball" in s_low or "chuyền" in s_low):
        return "U21 Asian Championship"
    if "avc" in c_low:
        return "AVC Cup"

    # 5. FIFA World Cup & Age-group World Cups (Soccer only for generic "World Cup")
    if any(k in c_low for k in ["under-17 world cup", "u-17 world cup", "u17 world cup"]):
        return "FIFA U-17 World Cup"
    if any(k in c_low for k in ["under-20 world cup", "u-20 world cup", "u20 world cup"]):
        return "FIFA U-20 World Cup"
    if any(k in c_low for k in ["women's world cup", "fifa women", "world cup nữ"]):
        return "FIFA Women's World Cup"
    if any(k in c_low for k in ["qualifying", "qualification", "vòng loại world cup", "world cup qualifiers", "wcq"]) and is_soccer:
        return "Vòng loại World Cup"
    if "fifa world cup" in c_low or (is_soccer and "world cup" in c_low):
        return "FIFA World Cup"
    
    # 3. Olympic Games & Qualifiers
    if any(k in c_low for k in ["olympic qualifying", "vòng loại olympic"]):
        return "Vòng loại Olympic"
    if any(k in c_low for k in ["olympic", "olympics", "thế vận hội"]):
        return "Thế vận hội Olympic"

    # 4. Continental Tournaments (AFC, UEFA, etc.)
    if any(k in c_low for k in ["u23 asian cup", "u-23 asian cup", "afc u-23", "afc u23"]):
        return "AFC U23 Asian Cup"
    if any(k in c_low for k in ["u20 asian cup", "u-20 asian cup", "afc u-20", "afc u20"]):
        return "AFC U20 Asian Cup"
    if any(k in c_low for k in ["u17 asian cup", "u-17 asian cup", "afc u-17", "afc u17"]):
        return "AFC U17 Asian Cup"
    if any(k in c_low for k in ["afc asian cup", "asian cup", "cúp châu á"]):
        return "AFC Asian Cup"
    if any(k in c_low for k in ["asian games", "asiad", "á vận hội"]):
        return "ASIAD"
    if any(k in c_low for k in ["uefa nations league", "nations league"]) and "volleyball" not in s_low:
        return "UEFA Nations League"
    if any(k in c_low for k in ["euro", "uefa european"]):
        return "EURO"
    if any(k in c_low for k in ["copa america", "copa américa"]):
        return "Copa América"

    # 7. Badminton & Table Tennis
    if any(k in c_low for k in ["thomas cup", "uber cup", "thomas & uber"]):
        return "Thomas & Uber Cup"
    if any(k in c_low for k in ["sudirman cup", "sudirman"]):
        return "Sudirman Cup"
    if any(k in c_low for k in ["ittf world team", "ittf"]):
        return "ITTF World Championship"

    # 9. Clean any specific real tournament name if provided
    if c and len(c) >= 3 and not any(k in c_low for k in ["giải quốc tế", "unknown", "thể thao"]):
        clean_ret = re.sub(r'^(20\d\d[-/]\d\d|20\d\d)\s+', '', c)
        return clean_ret

    # 10. Default fallback is "Giao hữu"
    return "Giao hữu"

def extract_stage_tag(comp_name: str, match_name: str = "") -> str:
    text = f"{comp_name} {match_name}".lower()
    if any(k in text for k in ["chung kết", "final"]) and not any(k in text for k in ["bán kết", "tứ kết", "semifinal", "quarterfinal"]):
        return "Chung kết"
    if any(k in text for k in ["bán kết", "semifinal", "semi-final"]):
        return "Bán kết"
    if any(k in text for k in ["tứ kết", "quarterfinal", "quarter-final"]):
        return "Tứ kết"
    if any(k in text for k in ["vòng 16", "vòng 1/8", "round of 16"]):
        return "Vòng 1/8"
    if any(k in text for k in ["super round"]):
        return "Super Round"
    if any(k in text for k in ["tranh hạng 3", "3rd place", "bronze"]):
        return "Tranh Hạng 3"
    if any(k in text for k in ["vòng loại", "qualification", "qualifier"]):
        return "Vòng loại"
    if any(k in text for k in ["vòng bảng", "group stage", "group"]):
        return "Vòng bảng"
    return ""

def extract_national_team_result_tags(team_country: str, match_name: str, match_result: str, match_state: str, sport: str = "") -> list:
    tags = []
    if not match_result or match_state not in ["post", "in"]:
        if match_state == "in":
            tags.append("Đang thi đấu")
        return tags

    score_match = re.search(r'(\d+)\s*[-–:]\s*(\d+)', match_result)
    is_home = match_name.strip().startswith("vs")

    if score_match:
        s1 = int(score_match.group(1))
        s2 = int(score_match.group(2))
        
        res_before_dash = match_result[:score_match.start()]
        res_after_dash = match_result[score_match.end():]
        
        c_low = team_country.lower()
        jp_words = ["japan", "nhật"]
        kr_words = ["korea", "hàn"]
        check_words = jp_words if any(w in c_low for w in jp_words) else (kr_words if any(w in c_low for w in kr_words) else [c_low])
        
        if any(w in res_before_dash.lower() for w in check_words):
            our_score, opp_score = s1, s2
        elif any(w in res_after_dash.lower() for w in check_words):
            our_score, opp_score = s2, s1
        else:
            our_score = s1 if is_home else s2
            opp_score = s2 if is_home else s1

        if match_state == "in":
            tags.append("Đang thi đấu")
        else:
            diff = our_score - opp_score
            if diff > 0:
                tags.append("Thắng")
                if opp_score == 0 and any(k in sport.lower() for k in ["bóng đá", "soccer", "football"]):
                    tags.append("Giữ sạch lưới")
                if diff >= 3 and any(k in sport.lower() for k in ["bóng đá", "soccer", "football"]):
                    tags.append("Thắng đậm")
            elif diff == 0:
                tags.append("Hòa")
            else:
                tags.append("Thua")
    else:
        if match_state == "post":
            tags.append("Đã kết thúc")
            
    return tags

def extract_venue_tag(match_name: str) -> str:
    # Bỏ tag sân nhà / sân khách theo yêu cầu người dùng
    return ""

def format_national_team_match_tags(team_country: str, sport_name: str, tier: str, match: dict, recent_news_titles: list = None) -> list:
    tags = []
    comp = match.get("competition") or ""
    m_name = match.get("match_name") or ""
    res = match.get("match_result") or ""
    st = match.get("match_state", "pre")

    # 1. Tournament Tag (ALWAYS first, defaulting to 'Giao hữu' if no official tournament)
    tourn_tag = get_national_team_tournament_tag(comp, m_name, sport_name, tier)
    if tourn_tag:
        tags.append(tourn_tag)

    # 2. Stage Tag (Vòng bảng, Vòng loại, Tứ kết, Bán kết, Chung kết...)
    stage_tag = extract_stage_tag(comp, m_name)
    if not stage_tag and tourn_tag not in ["Giao hữu", ""]:
        if any(k in tourn_tag.lower() for k in ["world cup", "asian cup", "olympic", "vnl", "wbc", "championship"]):
            stage_tag = "Vòng bảng"
    if stage_tag and stage_tag not in tags:
        tags.append(stage_tag)

    # 3. Match Outcome / Result Tags (Thắng, Hòa, Thua, Giữ sạch lưới, Thắng đậm...)
    res_tags = extract_national_team_result_tags(team_country, m_name, res, st, sport=sport_name)
    for rt in res_tags:
        if rt not in tags:
            tags.append(rt)

    # 4. Pre-match status if upcoming
    if st == "pre" and not res_tags:
        diff_d = match.get("diff_days", 999.0)
        if 0 <= diff_d <= 2:
            tags.append("Sắp thi đấu")

    # 6. Highlights from news (Triệu tập đội hình, Vào bán kết, Vô địch...)
    if recent_news_titles:
        all_news_text = " ".join(recent_news_titles).lower()
        if any(k in all_news_text for k in ["triệu tập", "danh sách triệu tập", "chốt danh sách", "tập trung"]):
            if "Triệu tập đội hình" not in tags:
                tags.append("Triệu tập đội hình")
        if any(k in all_news_text for k in ["vô địch", "champion", "thắng chung kết"]):
            if "Vô địch" not in tags:
                tags.append("Vô địch 🏆")
        elif any(k in all_news_text for k in ["vé đi tiếp", "vào bán kết", "vào tứ kết", "giành vé"]):
            if "Giành vé đi tiếp" not in tags:
                tags.append("Giành vé đi tiếp")

    return tags

def fetch_national_team_schedule(team) -> list:
    """
    Fetches 100% REAL match schedule & complete match results for national & youth teams.
    Supports Soccer, Baseball (WBC), Basketball (FIBA), Volleyball, Table Tennis, Badminton.
    """
    if isinstance(team, dict):
        t_id = team.get("id") or 0
        t_sport = team.get("sport_name") or team.get("sport") or ""
        t_api_id = team.get("api_team_id") or ""
        t_country = team.get("country_name") or team.get("country") or ""
        t_short = team.get("short_name") or team.get("name") or ""
        t_tier = team.get("tier") or "Senior"
        t_gender = team.get("gender") or "Men"
    else:
        t_id = getattr(team, "id", 0)
        t_sport = getattr(team, "sport_name", "") or getattr(team, "sport", "") or ""
        t_api_id = getattr(team, "api_team_id", "") or ""
        t_country = getattr(team, "country_name", "") or getattr(team, "country", "") or ""
        t_short = getattr(team, "short_name", "") or getattr(team, "name", "") or ""
        t_tier = getattr(team, "tier", "Senior") or "Senior"
        t_gender = getattr(team, "gender", "Men") or "Men"

    t_sport = str(t_sport or "")
    t_country = str(t_country or "")
    t_short = str(t_short or "")
    t_tier = str(t_tier or "Senior")
    t_gender = str(t_gender or "Men")

    cache_key = f"{t_sport}_{t_country}_{t_tier}_{t_gender}".lower()
    now_ts = datetime.datetime.now().timestamp()
    NT_TTL = 14400  # 4 hours cache for NT schedules

    for k_cand in ([cache_key, t_id] if t_id else [cache_key]):
        if k_cand in NATIONAL_TEAM_SCHED_CACHE:
            cached_ts, cached_matches = NATIONAL_TEAM_SCHED_CACHE[k_cand]
            if now_ts - cached_ts < NT_TTL:
                # Update unified key so both Players and NTs share it
                NATIONAL_TEAM_SCHED_CACHE[cache_key] = (cached_ts, cached_matches)
                now_utc_ref = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
                refreshed_m = []
                for m in cached_matches:
                    m_c = dict(m)
                    m_utc = m_c.get("match_date_utc")
                    if m_utc:
                        try:
                            dt = datetime.datetime.fromisoformat(m_utc.replace("Z", ""))
                            diff = (dt - now_utc_ref).total_seconds() / 86400.0
                            m_c["diff_days"] = diff
                            m_c["is_past"] = (diff < -0.1) or (m_c.get("match_state") == "post")
                        except Exception:
                            pass
                    refreshed_m.append(m_c)
                return refreshed_m

    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    old_cached_matches = []
    for k_cand in ([cache_key, t_id] if t_id else [cache_key]):
        if k_cand in NATIONAL_TEAM_SCHED_CACHE:
            old_cached_matches = NATIONAL_TEAM_SCHED_CACHE[k_cand][1] or []
            break

    matches = []
    seen_keys = set()

    # 1. ESPN APIs for official national & youth teams (dynamically resolved via sport code)
    from backend.core.config import resolve_espn_sport_code
    espn_code = resolve_espn_sport_code(t_sport)
    urls = []
    if espn_code == "soccer" and t_api_id and str(t_api_id).isdigit():
        urls = [
            f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/{t_api_id}/schedule?fixture=true",
            f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/{t_api_id}/schedule",
        ]
        # Youth teams (U23, U20, U17...) often require explicit season query on ESPN
        if t_tier and t_tier.lower() != "senior":
            cur_yr = now_utc.year
            urls.extend([
                f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/{t_api_id}/schedule?season={cur_yr}",
                f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/{t_api_id}/schedule?season={cur_yr - 1}",
            ])
    elif espn_code == "baseball" and t_api_id and str(t_api_id).isdigit():
        urls = [
            f"https://site.api.espn.com/apis/site/v2/sports/baseball/world-baseball-classic/teams/{t_api_id}/schedule"
        ]
    elif espn_code == "basketball" and t_api_id and str(t_api_id).isdigit():
        urls = [
            f"https://site.api.espn.com/apis/site/v2/sports/basketball/fiba/teams/{t_api_id}/schedule"
        ]
    elif espn_code and t_api_id and str(t_api_id).isdigit():
        urls = [
            f"https://site.api.espn.com/apis/site/v2/sports/{espn_code}/all/teams/{t_api_id}/schedule"
        ]

    for u in urls:
        try:
            req = urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
            events = data.get("events", [])
            for ev in events:
                d_str = ev.get("date")
                if not d_str:
                    continue
                clean_d = d_str.replace("Z", "").replace(".000", "")
                if clean_d.count(":") == 1:
                    clean_d += ":00"
                dt = datetime.datetime.strptime(clean_d[:19], "%Y-%m-%dT%H:%M:%S")
                diff = (dt - now_utc).total_seconds() / 86400.0

                # Bao trọn các giải đấu chính thức và Olympic gần nhất (-900 ngày đến +365 ngày)
                if -900 <= diff <= 365:
                    name = ev.get("name") or ""
                    comp_obj = ev.get("competitions", [{}])[0]
                    comp_name = ev.get("league", {}).get("name") or comp_obj.get("league", {}).get("description") or "Giải quốc tế"
                    status_obj = comp_obj.get("status") or ev.get("status") or {}
                    status_type = status_obj.get("type", {})
                    is_completed = status_type.get("completed", False) or status_type.get("state") == "post"
                    is_in = status_type.get("state") == "in"
                    state = "post" if is_completed else ("in" if is_in else ("post" if diff < -0.1 else "pre"))

                    competitors = comp_obj.get("competitors", [])
                    home = next((c for c in competitors if c.get('homeAway') == 'home'), None)
                    away = next((c for c in competitors if c.get('homeAway') == 'away'), None)
                    h_name = home.get('team', {}).get('displayName', '') if home else ''
                    a_name = away.get('team', {}).get('displayName', '') if away else ''
                    h_id = str(home.get('team', {}).get('id', '')) if home else ''
                    a_id = str(away.get('team', {}).get('id', '')) if away else ''

                    # Robustly determine home/away to avoid matching self as opponent
                    is_home = False
                    if t_api_id and h_id and str(t_api_id) == str(h_id):
                        is_home = True
                    elif t_api_id and a_id and str(t_api_id) == str(a_id):
                        is_home = False
                    else:
                        t_c = t_country.lower()
                        if "nhật" in t_c or "japan" in t_c:
                            h_is_us = "japan" in h_name.lower() or "nhật" in h_name.lower()
                            a_is_us = "japan" in a_name.lower() or "nhật" in a_name.lower()
                        elif "hàn" in t_c or "korea" in t_c:
                            h_is_us = ("korea" in h_name.lower() and "north" not in h_name.lower() and "dpr" not in h_name.lower()) or "hàn" in h_name.lower()
                            a_is_us = ("korea" in a_name.lower() and "north" not in a_name.lower() and "dpr" not in a_name.lower()) or "hàn" in a_name.lower()
                        else:
                            h_is_us = t_c in h_name.lower() if t_c else False
                            a_is_us = t_c in a_name.lower() if t_c else False

                        if h_is_us and not a_is_us:
                            is_home = True
                        elif a_is_us and not h_is_us:
                            is_home = False
                        else:
                            is_home = True

                    opp_display = a_name if is_home else h_name
                    # Guard: If opp_display happens to be our own team name, flip it
                    if opp_display:
                        if ("nhật" in t_country.lower() or "japan" in t_country.lower()) and "japan" in opp_display.lower() and a_name and h_name:
                            opp_display = h_name if is_home else a_name
                            is_home = not is_home
                        elif ("hàn" in t_country.lower() or "korea" in t_country.lower()) and "korea" in opp_display.lower() and "north" not in opp_display.lower() and a_name and h_name:
                            opp_display = h_name if is_home else a_name
                            is_home = not is_home

                    opp_name = f"vs {opp_display}" if is_home else f"@ {opp_display}"
                    if not a_name or not h_name:
                        opp_name = f"vs {name}"

                    h_score = _extract_score_display(home)
                    a_score = _extract_score_display(away)

                    res_str = None
                    if state == "post":
                        if h_score is not None and a_score is not None:
                            res_str = f"{h_name} {h_score} - {a_score} {a_name} (FT)"
                        else:
                            res_str = "Đã kết thúc (FT)"
                    elif state == "in":
                        if h_score is not None and a_score is not None:
                            res_str = f"{h_name} {h_score} - {a_score} {a_name} (Đang thi đấu)"
                        else:
                            res_str = "Đang diễn ra"

                    dt_vn = dt + datetime.timedelta(hours=7)
                    m_key = (dt_vn.strftime("%Y-%m-%d"), opp_name.lower())
                    if m_key not in seen_keys:
                        seen_keys.add(m_key)
                        clean_tourn = get_national_team_tournament_tag(comp_name, opp_name, t_sport, t_tier)
                        m_item = {
                            "match_name": opp_name,
                            "raw_match_name": f"{t_short} {opp_name}",
                            "match_date_utc": dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "date_vn": dt_vn.strftime("%d/%m %H:%M"),
                            "date_full_vn": dt_vn.strftime("%d/%m/%Y %H:%M"),
                            "date_only_vn": dt_vn.strftime("%Y-%m-%d"),
                            "competition": clean_tourn,
                            "raw_competition": comp_name,
                            "match_state": state,
                            "match_result": res_str,
                            "is_past": (state == "post" or diff < -0.1),
                            "event_id": f"espn_nt_{ev.get('id', '')}",
                            "diff_days": diff
                        }
                        m_item["tags"] = format_national_team_match_tags(t_country, t_sport, t_tier, m_item)
                        matches.append(m_item)
        except Exception:
            pass

    # 2. Flashscore universal NT & Youth Team fallback/supplement (Baseball APBC/U23 WC, Soccer youth friendlies, Basketball, Volleyball, Handball, Hockey, Rugby, Cricket...)
    try:
        from backend.modules.players.services.racket_volleyball_service import fetch_flashscore_national_team_schedule
        fs_nt_matches = fetch_flashscore_national_team_schedule(
            t_sport, t_country, tier=t_tier, gender=t_gender
        )
        for fm in fs_nt_matches:
            d_vn = fm.get("date_only_vn") or ""
            opp_name = fm.get("match_name") or ""
            opp_core = re.sub(r"^(vs|@)\s+", "", opp_name, flags=re.I).strip().lower()
            is_dup = False
            try:
                d_fm = datetime.datetime.strptime(d_vn, "%Y-%m-%d").date() if d_vn else None
            except Exception:
                d_fm = None
            for k_d, k_opp in seen_keys:
                k_core = re.sub(r"^(vs|@)\s+", "", k_opp, flags=re.I).strip().lower()
                opp_same = (k_opp == opp_name.lower()) or (opp_core and k_core and (opp_core == k_core or opp_core in k_core or k_core in opp_core))
                if not opp_same:
                    continue
                if k_d == d_vn:
                    is_dup = True
                    break
                if d_fm and k_d:
                    try:
                        d_k = datetime.datetime.strptime(k_d, "%Y-%m-%d").date()
                        if abs((d_fm - d_k).days) <= 1:
                            is_dup = True
                            break
                    except Exception:
                        pass
            if is_dup:
                continue
            seen_keys.add((d_vn, opp_name.lower()))
            comp_raw = fm.get("competition") or ""
            clean_tourn = get_national_team_tournament_tag(comp_raw, opp_name, t_sport, t_tier)
            fm_utc = fm.get("match_date_utc")
            if fm_utc and isinstance(fm_utc, str) and not fm_utc.endswith("Z") and not ("+" in fm_utc or "-" in fm_utc[10:]):
                fm_utc = fm_utc + "Z"
            m_item = {
                "match_name": opp_name,
                "raw_match_name": fm.get("raw_match_name") or f"{t_short} {opp_name}",
                "match_date_utc": fm_utc,
                "date_vn": fm.get("date_vn"),
                "date_full_vn": fm.get("date_full_vn"),
                "date_only_vn": d_vn,
                "competition": clean_tourn,
                "raw_competition": comp_raw,
                "match_state": fm.get("match_state", "pre"),
                "match_result": fm.get("match_result"),
                "player_stats": fm.get("player_stats"),
                "is_past": fm.get("match_state") == "post" or (fm.get("diff_days", 0) < -0.1),
                "event_id": fm.get("event_id"),
                "diff_days": fm.get("diff_days", 0.0),
            }
            m_item["tags"] = format_national_team_match_tags(t_country, t_sport, t_tier, m_item)
            matches.append(m_item)
    except Exception:
        pass

    # 3. Retain historical past Flashscore NT matches across rolling 7-day windows
    for old_m in old_cached_matches:
        ev_s = str(old_m.get("event_id") or "")
        if ev_s.startswith("fs_") and old_m.get("match_state") == "post":
            d_vn = old_m.get("date_only_vn") or ""
            opp_name = (old_m.get("match_name") or "").lower()
            if (d_vn, opp_name) not in seen_keys:
                seen_keys.add((d_vn, opp_name))
                matches.append(old_m)

    matches.sort(key=lambda x: str(x.get("match_date_utc") or ""))
    NATIONAL_TEAM_SCHED_CACHE[cache_key] = (now_ts, matches)
    _save_nt_sched_cache()
    return matches

def fetch_national_team_news_feed(team: NationalTeam, db: Session, force_refresh: bool = False) -> list:
    """
    Fetches abundant native Japanese, Korean, and English news articles from Google News RSS.
    Uses localized ceid parameters to guarantee hundreds of native articles from Yahoo JP, Naver, etc.
    """
    existing_news = db.query(NationalTeamNews).filter(NationalTeamNews.team_id == team.id).order_by(NationalTeamNews.published_at.desc()).all()
    if not force_refresh and len(existing_news) >= 8:
        return existing_news

    # Determine native & international query targets
    cat_match = next((c for c in NATIONAL_TEAMS_CATALOG if c["name"].lower() == team.name.lower() or c["short_name"].lower() == team.short_name.lower()), None)
    
    query_configs = []
    is_japan = ("nhật" in (team.country_name or "").lower() or "japan" in (team.country_name or "").lower())
    is_korea = ("hàn" in (team.country_name or "").lower() or "korea" in (team.country_name or "").lower())
    tier_label = team.tier if team.tier and team.tier != "Senior" else ""
    sport_name = team.sport_name or ""

    if is_japan:
        if cat_match and cat_match.get("query_native"):
            native_q = cat_match["query_native"]
        elif getattr(team, "search_query", None) and any(ord(c) > 127 for c in team.search_query):
            native_q = team.search_query
        else:
            if any(k in sport_name.lower() for k in ["bóng đá", "soccer", "football"]):
                native_q = f"{tier_label} サッカー日本代表".strip()
            elif any(k in sport_name.lower() for k in ["bóng chày", "baseball"]):
                native_q = f"{tier_label} 侍ジャパン 野球".strip()
            elif any(k in sport_name.lower() for k in ["bóng rổ", "basketball"]):
                native_q = f"{tier_label} バスケ日本代表".strip()
            elif any(k in sport_name.lower() for k in ["bóng chuyền", "volleyball"]):
                native_q = f"{tier_label} バレーボール日本代表".strip()
            else:
                native_q = f"{team.name} 日本代表"
        query_configs.append({
            "query": native_q,
            "hl": "ja",
            "gl": "JP",
            "ceid": "JP:ja",
            "region": "JP"
        })
    elif is_korea:
        if cat_match and cat_match.get("query_native"):
            native_q = cat_match["query_native"]
        elif getattr(team, "search_query", None) and any(ord(c) > 127 for c in team.search_query):
            native_q = team.search_query
        else:
            if any(k in sport_name.lower() for k in ["bóng đá", "soccer", "football"]):
                native_q = f"대한민국 {tier_label} 축구 국가대표팀".strip()
            elif any(k in sport_name.lower() for k in ["bóng chày", "baseball"]):
                native_q = f"대한민국 {tier_label} 야구 대표팀".strip()
            elif any(k in sport_name.lower() for k in ["bóng rổ", "basketball"]):
                native_q = f"대한민국 {tier_label} 농구 국가대표팀".strip()
            elif any(k in sport_name.lower() for k in ["bóng chuyền", "volleyball"]):
                native_q = f"대한민국 {tier_label} 배구 국가대표팀".strip()
            else:
                native_q = f"{team.name} 대한민국 대표팀"
        query_configs.append({
            "query": native_q,
            "hl": "ko",
            "gl": "KR",
            "ceid": "KR:ko",
            "region": "KR"
        })

    # International English query fallback
    en_q = cat_match.get("query_en") if cat_match else f"{team.country_name} {tier_label} {team.sport_name} national team".strip()
    query_configs.append({
        "query": en_q,
        "hl": "en-US",
        "gl": "US",
        "ceid": "US:en",
        "region": "US"
    })

    existing_titles = {n.title for n in db.query(NationalTeamNews).filter(NationalTeamNews.team_id == team.id).all()}
    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    new_added = 0

    for cfg in query_configs:
        encoded_q = urllib.parse.quote(cfg["query"])
        url = f"https://news.google.com/rss/search?q={encoded_q}&hl={cfg['hl']}&gl={cfg['gl']}&ceid={cfg['ceid']}"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=4) as resp:
                xml_data = resp.read()
            root = ET.fromstring(xml_data)

            for item in root.findall('.//item')[:25]:
                title_elem = item.find('title')
                link_elem = item.find('link')
                pub_date_elem = item.find('pubDate')

                title = title_elem.text.strip() if title_elem is not None and title_elem.text else ''
                link = link_elem.text.strip() if link_elem is not None and link_elem.text else ''
                pub_date_str = pub_date_elem.text.strip() if pub_date_elem is not None and pub_date_elem.text else ''

                if not title or not link or title in existing_titles:
                    continue

                pub_dt = now_utc
                if pub_date_str:
                    try:
                        clean_date = pub_date_str.replace("GMT", "+0000").strip()
                        pub_dt = datetime.datetime.strptime(clean_date[:25], "%a, %d %b %Y %H:%M:%S")
                    except Exception:
                        pub_dt = now_utc

                t_lower = title.lower()
                news_type = "match"
                if any(w in t_lower for w in ["roster", "squad", "lineup", "chốt danh sách", "triệu tập", "メンバー", "招集", "명단", "발탁"]):
                    news_type = "statement"
                elif any(w in t_lower for w in ["chuyển nhượng", "bổ nhiệm", "hlv", "coach", "manager", "監督", "就任", "감독"]):
                    news_type = "transfer"
                elif any(w in t_lower for w in ["phân tích", "chiến thuật", "rating", "nhận định", "戦術", "評価", "전술", "분석"]):
                    news_type = "analysis"

                news_record = NationalTeamNews(
                    team_id=team.id,
                    title=title,
                    source_url=link,
                    news_type=news_type,
                    published_at=pub_dt,
                    region=cfg["region"]
                )
                db.add(news_record)
                existing_titles.add(title)
                new_added += 1
        except Exception:
            continue

    if new_added > 0:
        try:
            db.commit()
        except Exception:
            db.rollback()

    return db.query(NationalTeamNews).filter(NationalTeamNews.team_id == team.id).order_by(NationalTeamNews.published_at.desc()).all()

def get_national_teams_dashboard_data(db: Session, country: str = None, sport: str = None, tier: str = None) -> dict:
    """Prepares structured data for national teams."""
    query = db.query(NationalTeam)
    if country and country != "Tất cả":
        query = query.filter(NationalTeam.country_name.ilike(f"%{country}%"))
    if sport and sport != "Tất cả":
        query = query.filter(NationalTeam.sport_name.ilike(f"%{sport}%"))
    if tier and tier != "Tất cả":
        query = query.filter(NationalTeam.tier.ilike(f"%{tier}%"))

    teams = query.all()
    result_teams = []

    for t in teams:
        matches = fetch_national_team_schedule(t)
        all_news = fetch_national_team_news_feed(t, db)

        upcoming_30d = []
        upcoming_all = []
        next_match = None

        for m in matches:
            diff_d = m.get("diff_days", 999.0)
            is_past = m.get("is_past") or (diff_d < -0.1)

            if not is_past and diff_d >= 0:
                upcoming_all.append(m)
                if diff_d <= 30:
                    upcoming_30d.append(m)

        if upcoming_all:
            next_match = upcoming_all[0]

        # Clean simplified tier label (ĐTQG, U23, U20, U19, U17, Tuyển trẻ - no JP/KR prefix)
        tier_clean = t.tier or "Senior"
        if tier_clean == "Senior":
            tier_badge = "ĐTQG"
        elif tier_clean in ["U23", "U21", "U20", "U19", "U18", "U17"]:
            tier_badge = tier_clean
        else:
            tier_badge = "Tuyển trẻ"

        nt_tags = (next_match.get("tags") if next_match else None) or ["Chờ lịch thi đấu", "Nghỉ đợt tập trung"]

        team_item = {
            "id": t.id,
            "entity_type": "national_team",
            "name": t.name,
            "short_name": t.short_name,
            "nickname": t.nickname,
            "sport": t.sport_name,
            "country": t.country_name,
            "flag": t.flag or "🌐",
            "tier": t.tier,
            "tier_badge": tier_badge,
            "gender": t.gender,
            "description": t.description,
            "tags": nt_tags,
            "next_match": next_match.get("match_name") if next_match else "Chưa có lịch sắp tới",
            "next_match_date": next_match.get("date_vn") if next_match else "N/A",
            "next_match_competition": next_match.get("competition") if next_match else "",
            "upcoming_30d_count": len(upcoming_30d),
            "upcoming_30d_matches": upcoming_30d,
            "all_matches": matches,
            "news_count": len(all_news),
            "recent_news": [
                {"title": n.title, "url": n.source_url, "news_type": n.news_type, "published_at": n.published_at.isoformat()}
                for n in all_news[:15]
            ]
        }
        result_teams.append(team_item)

    # Sort: News count descending first, then upcoming match
    def sort_nt_key(item):
        news_cnt = item["news_count"]
        has_upcoming = 1 if item["upcoming_30d_count"] > 0 else 0
        return (-news_cnt, -has_upcoming)

    result_teams.sort(key=sort_nt_key)

    return {
        "total_teams": len(result_teams),
        "teams": result_teams,
        "available_sports": sorted(list({t["sport"] for t in result_teams})),
        "available_countries": sorted(list({t["country"] for t in result_teams})),
        "available_tiers": ["Senior", "U23", "U20", "U19", "U18", "U21", "Youth"]
    }


_NT_SQUAD_CONTEXT_CACHE = {}


def fetch_national_team_squad_context(
    country: str,
    sport: str,
    tier: str = "Senior",
    comp_name: str = "",
    gender: str = "Male",
    opponent_name: str = "",
) -> dict:
    """Fetch recent official/news squad-announcement headlines & decoded roster text (4h TTL)."""
    g_norm = "Women" if str(gender or "").lower() in ("women", "female", "nữ", "f") else "Male"
    cache_key = (
        (country or "").strip().lower(),
        (sport or "").strip().lower(),
        (tier or "Senior").strip().lower(),
        g_norm.lower(),
        (comp_name or "").strip().lower()[:60],
    )
    now_ts = datetime.datetime.now().timestamp()
    cached = _NT_SQUAD_CONTEXT_CACHE.get(cache_key)
    if cached and (now_ts - cached["ts"] < 14400):
        return cached["data"]

    c_low = (country or "").lower()
    s_low = (sport or "").lower()
    is_jp = any(k in c_low for k in ["japan", "nhật"])
    is_kr = any(k in c_low for k in ["korea", "hàn"])
    is_women = (g_norm == "Women")

    queries = []
    if is_jp:
        if "bóng chày" in s_low or "baseball" in s_low:
            queries.append(("ja", "侍ジャパン メンバー OR ロースター OR 招集"))
            queries.append(("en", '"Samurai Japan" OR "Japan national baseball" roster OR squad OR APBC'))
        elif "bóng đá" in s_low or "soccer" in s_low or "football" in s_low:
            if is_women:
                queries.append(("ja", "site:jfa.jp なでしこジャパン メンバー"))
                queries.append(("ja", "なでしこジャパン 招集 OR メンバー"))
            elif tier in {"U23", "U21", "U20", "U19", "U18", "U17", "Youth"}:
                queries.append(("ja", "site:jfa.jp U-21日本代表 メンバー・スケジュール"))
                queries.append(("ja", f"site:jfa.jp U-{tier[1:] if tier.startswith('U') else tier}日本代表 メンバー・スケジュール"))
                queries.append(("ja", "site:jfa.jp U-23日本代表 メンバー・スケジュール"))
            else:
                queries.append(("ja", "site:jfa.jp SAMURAI BLUE メンバー・スケジュール"))
                queries.append(("ja", "サッカー日本代表 メンバー 背番号 OR 招集"))
        else:
            queries.append(("en", f'"{country}" {"women " if is_women else ""}{sport} national team squad OR roster'))
    elif is_kr:
        if "bóng chày" in s_low or "baseball" in s_low:
            queries.append(("ko", "야구 대표팀 명단 OR 엔特리"))
            queries.append(("en", '"South Korea" baseball national team roster OR squad OR APBC'))
        elif "bóng đá" in s_low or "soccer" in s_low or "football" in s_low:
            if is_women:
                queries.append(("ko", "여자축구 국가대표팀 명단 OR 소집"))
            elif tier in {"U23", "U21", "U20", "U19", "U18", "U17", "Youth"}:
                queries.append(("ko", f"U-{tier[1:] if tier.startswith('U') else tier} 축구대표팀 명단 OR 소집"))
                queries.append(("ko", "site:kfa.or.kr 대표팀 명단"))
            else:
                queries.append(("ko", "축구 국가대표팀 소집 명단 발표"))
                queries.append(("en", '"South Korea" national football team squad OR called up'))
        else:
            queries.append(("en", f'"{country}" {"women " if is_women else ""}{sport} national team squad OR roster'))
    else:
        queries.append(("en", f'"{country}" {"women " if is_women else ""}{sport} national team squad OR roster'))

    titles = []
    articles_meta = []
    seen = set()
    for lang, q in queries[:2]:
        try:
            hl = "ja" if lang == "ja" else ("ko" if lang == "ko" else "en-US")
            gl = "JP" if lang == "ja" else ("KR" if lang == "ko" else "US")
            ceid = f"{gl}:{lang}"
            url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}&hl={hl}&gl={gl}&ceid={ceid}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                xml_data = resp.read()
            root = ET.fromstring(xml_data)
            for item in root.findall("./channel/item")[:15]:
                t_el = item.find("title")
                l_el = item.find("link")
                if t_el is not None and t_el.text:
                    t_clean = t_el.text.strip()
                    if t_clean.lower() not in seen:
                        seen.add(t_clean.lower())
                        titles.append(t_clean)
                        articles_meta.append((t_clean, l_el.text.strip() if (l_el is not None and l_el.text) else ""))
        except Exception:
            continue

    # Decode and fetch top 2 official/squad-list articles to extract full player roster text
    def _score_squad_article(t_str: str) -> int:
        tl = t_str.lower()
        sc = 0
        req_tier = (tier or "Senior").lower()
        if req_tier == "senior":
            if any(k in tl for k in ["u-23", "u-21", "u-20", "u-19", "u-18", "u-17", "u23", "u21", "u20", "u19", "u17"]):
                return -99
        else:
            tier_num = re.sub(r'[^0-9]', '', str(tier))
            if any(k in tl for k in ["samurai blue", "a代表"]) and not any(k in tl for k in ["u-21", "u-23", "u-20", "u21", "u23", "u20"]):
                return -99
            if tier_num and f"u-{tier_num}" in tl:
                sc += 10
            elif any(k in tl for k in ["u-21", "u-23", "u-20"]):
                sc += 6

        if "jfa" in tl or "kfa" in tl: sc += 5
        if any(k in tl for k in ["メンバー・スケジュール", "招集メンバー", "소집 명단 발표", "명단 발표", "背番号", "official squad", "final roster"]): sc += 5
        elif any(k in tl for k in ["メンバー", "명단", "엔트리", "squad", "roster"]): sc += 2
        if any(k in tl for k in ["配信が決定", "放送", "テレビ", "チケット", "ticket", "broadcast"]): sc -= 6
        return sc

    ranked_articles = sorted(articles_meta, key=lambda x: -_score_squad_article(x[0]))
    squad_texts = []
    squad_nospace_parts = []
    squad_source_titles = []
    has_official_squad_roster = False

    try:
        import httpx
        from googlenewsdecoder import gnewsdecoder
        for art_title, art_link in ranked_articles:
            if _score_squad_article(art_title) < 2 or not art_link:
                continue
            try:
                dec = gnewsdecoder(art_link)
                target_url = dec.get("decoded_url") if isinstance(dec, dict) else None
                if not target_url:
                    continue
                resp = httpx.get(target_url, timeout=6, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
                if resp.status_code != 200 or not resp.text:
                    continue
                raw_html = resp.text
                # Strip HTML comments first so archived/commented-out old squads never pollute current roster
                clean = re.sub(r"<!--.*?-->", " ", raw_html, flags=re.S)
                clean = re.sub(r"<(?:script|style|nav|footer|header|aside)[^>]*>.*?</(?:script|style|nav|footer|header|aside)>", " ", clean, flags=re.S | re.I)
                clean = re.sub(r"<div[^>]*(?:sidebar|recommend|ranking|related|widget|banner)[^>]*>.*?</div>", " ", clean, flags=re.S | re.I)
                clean = re.sub(r"<[^>]+>", " ", clean)
                clean_space = re.sub(r"\s+", " ", clean).strip().lower()
                clean_nospace = re.sub(r"\s+", "", clean).lower()
                if len(clean_nospace) >= 400 and any(
                    mk in clean_nospace for mk in ["gk", "df", "mf", "fw", "監督", "명단", "골키퍼", "수비수", "미드필더", "공격수", "pitcher", "catcher", "roster", "squad"]
                ):
                    squad_texts.append(clean_space)
                    squad_nospace_parts.append(clean_nospace)
                    squad_source_titles.append(art_title)
                    has_official_squad_roster = True
                    if len(squad_texts) >= 2:
                        break
            except Exception:
                continue
    except Exception:
        pass

    combined_low = " ".join([comp_name or ""] + titles).lower()
    is_dom_u24 = any(k in combined_low for k in [
        "asia professional baseball", "apbc", "u-24", "u24", "u-23", "u23",
        "eaff", "e-1", "domestic", "jリーグ組", "kbo", "npb",
    ])
    res = {
        "titles": titles,
        "is_domestic_or_u24_tournament": is_dom_u24,
        "squad_articles_text": "\n".join(squad_texts),
        "squad_articles_nospace": "\n".join(squad_nospace_parts),
        "squad_source_title": squad_source_titles[0] if squad_source_titles else "",
        "has_official_squad_roster": has_official_squad_roster,
    }
    _NT_SQUAD_CONTEXT_CACHE[cache_key] = {"ts": now_ts, "data": res}
    return res


def evaluate_national_team_callup(
    player_name: str,
    team_name: str,
    sport_name: str,
    country_name: str,
    gender: str = "Male",
    nt_match: dict = None,
    player_news_titles: list = None,
    official_injury: dict = None,
    recent_club_injury: bool = False,
    player_aliases: str = None,
) -> tuple:
    """
    Determine whether an athlete is called up, omitted/not called up, or injured for a National Team match.
    Returns (status, tag_label, reason_detail) where status in:
      'called_up' | 'not_called_up' | 'injured_withdrawal' | 'unknown'
    """
    nt_match = nt_match or {}
    tags_low = " ".join(str(t).lower() for t in (nt_match.get("tags") or []))
    if nt_match.get("has_played") and not nt_match.get("no_lineup_data"):
        return ("called_up", "Được triệu tập", "Thi đấu chính thức cho ĐTQG")
    if any(k in tags_low for k in ["đá chính", "vào sân", "dự bị", "xuất phát"]):
        return ("called_up", "Được triệu tập", "Có tên trong danh sách thi đấu ĐTQG")
    if "không lên tuyển" in tags_low:
        return ("not_called_up", "Không lên tuyển", "Không có tên trong danh sách ĐTQG")
    if "vắng mặt đtqg (chấn thương)" in tags_low:
        return ("injured_withdrawal", "Vắng mặt ĐTQG (Chấn thương)", "Rút lui khỏi ĐTQG do chấn thương")

    comp_name = str(nt_match.get("competition") or nt_match.get("raw_match_name") or "")
    comp_low = comp_name.lower()
    nt_tier = str(nt_match.get("nt_tier") or nt_match.get("tier") or "Senior")

    # 1. Deterministic tournament eligibility (Youth or Domestic/U24 tournaments)
    is_youth_match = (
        nt_tier in {"U23", "U21", "U20", "U19", "U18", "U17", "Youth"}
        or any(u in comp_low for u in ["u23", "u-23", "u21", "u20", "u-20", "u19", "u17"])
    )

    try:
        from backend.modules.players.services.sports_service import resolve_team_league
        club_league = resolve_team_league(team_name, sport_name)
    except Exception:
        club_league = ""

    # Baseball: MLB players (Ohtani, Yamamoto, Suzuki, Imanaga, Yoshida, etc.) do NOT play in APBC, Premier12, U-23, or off-season friendlies
    if "bóng chày" in sport_name.lower() or "baseball" in sport_name.lower():
        is_wbc_or_olympic = any(k in comp_low for k in ["wbc", "world baseball classic", "olympic", "thế vận hội"])
        if club_league == "MLB" and not is_wbc_or_olympic:
            return (
                "not_called_up",
                "Không lên tuyển",
                "Cầu thủ thuộc 40-man roster MLB không tham gia các giải giao hữu / APBC / U-23 ngoài WBC",
            )

    is_eaff = any(k in comp_low for k in ["eaff", "e-1 championship"])
    if is_eaff and club_league in {"Premier League", "La Liga", "Bundesliga", "Serie A", "Ligue 1", "Eredivisie", "Championship", "MLS", "WSL"}:
        return (
            "not_called_up",
            "Không lên tuyển",
            "Giải EAFF E-1 chỉ triệu tập cầu thủ thi đấu trong nước",
        )

    # 2. Build all name variants (Latin + CJK/Hangul aliases from DB)
    raw_variants = [player_name or ""]
    if player_aliases:
        raw_variants.extend([a.strip() for a in str(player_aliases).split(",") if a.strip()])
    name_variants_low = []
    cjk_variants_nospace = []
    for v in raw_variants:
        vl = v.strip().lower()
        if len(vl) >= 2 and vl not in name_variants_low:
            name_variants_low.append(vl)
        if re.search(r"[\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7af]", v):
            vn = re.sub(r"\s+", "", v).lower()
            if len(vn) >= 2 and vn not in cjk_variants_nospace:
                cjk_variants_nospace.append(vn)

    p_tokens = [tok.lower() for tok in re.split(r"\s+", (player_name or "").strip()) if len(tok) >= 3]
    last_tok = p_tokens[-1] if p_tokens else ""
    first_tok = p_tokens[0] if p_tokens else ""

    p_titles = [str(t) for t in (player_news_titles or []) if t]
    has_recent_inj_news = False
    for title in p_titles[:15]:
        tl = title.lower()
        if any(k in tl for k in ["injury", "injured", "hamstring", "ankle", "knee", "負傷", "怪我", "戦線復帰", "負傷離脱", "부상", "chấn thương"]):
            has_recent_inj_news = True

    # 3. Check official/decoded squad roster text FIRST (highest accuracy, eliminates speculative article titles!)
    squad_ctx = fetch_national_team_squad_context(
        country_name,
        sport_name,
        tier=nt_tier,
        comp_name=comp_name,
        gender=gender,
        opponent_name=str(nt_match.get("match_name") or ""),
    )

    sq_text = squad_ctx.get("squad_articles_text") or ""
    sq_nospace = squad_ctx.get("squad_articles_nospace") or ""
    if squad_ctx.get("has_official_squad_roster"):
        in_roster = False
        withdrawn_in_roster = False
        for cv in cjk_variants_nospace:
            idx = sq_nospace.find(cv)
            if idx >= 0:
                tail = sq_nospace[idx:idx + len(cv) + 35]
                if any(wk in tail for wk in ["離脱", "不参加", "辞退", "부상제외", "소집해제"]):
                    withdrawn_in_roster = True
                else:
                    in_roster = True
                break
        if not in_roster and not withdrawn_in_roster:
            for nv in name_variants_low:
                if nv in sq_text:
                    in_roster = True
                    break
        if in_roster:
            return ("called_up", "Được triệu tập", squad_ctx.get("squad_source_title") or f"Có tên trong danh sách triệu tập {nt_tier}")
        if withdrawn_in_roster or (official_injury or recent_club_injury or has_recent_inj_news):
            return ("injured_withdrawal", "Vắng mặt ĐTQG (Chấn thương)", "Không có tên / rút lui khỏi danh sách triệu tập ĐTQG do chấn thương")
        if is_youth_match:
            return ("not_called_up", "Không lên tuyển", f"Không có tên trong danh sách đội tuyển trẻ ({nt_tier}) đợt này")
        return ("not_called_up", "Không lên tuyển", "Không có tên trong danh sách triệu tập ĐTQG đợt này")

    # 4. Fallback when no official squad roster page was parsed: check player injuries & news headlines
    if official_injury or recent_club_injury:
        return ("injured_withdrawal", "Vắng mặt ĐTQG (Chấn thương)", "Đang chấn thương tại CLB nên vắng mặt đợt tập trung ĐTQG")

    for title in p_titles[:15]:
        tl = title.lower()
        if any(k in tl for k in ["withdraw", "withdrew", "pulled out", "ruled out", "辞退", "負傷離脱", "부상 낙마", "소집 해制", "소집 해제", "rút lui", "lỡ hẹn"]):
            if any(k in tl for k in ["japan", "korea", "samurai", "national", "đtqg", "tuyển", "대표", "代表", "world cup", "friendly"]):
                return ("injured_withdrawal", "Vắng mặt ĐTQG (Chấn thương)", title)
        if any(k in tl for k in ["left out", "omitted", "snubbed", "not called", "選外", "招集外", "不選出", "제외", "명단 제외", "không được triệu tập"]):
            return ("not_called_up", "Không lên tuyển", title)
    for title in p_titles[:15]:
        tl = title.lower()
        if any(k in tl for k in ["called up", "named in", "squad", "roster", "招集", "代表選出", "メンバー入り", "발탁", "명단 포함", "triệu tập", "lên tuyển"]):
            if any(k in tl for k in ["japan", "korea", "samurai", "national", "đtqg", "tuyển", "대표", "代表", "friendly", "qualifier"]):
                return ("called_up", "Được triệu tập", title)

    sq_titles = squad_ctx.get("titles") or []
    for st in sq_titles:
        stl = st.lower()
        st_ns = re.sub(r"\s+", "", stl)
        if _mentions_player(stl, st_ns):
            if any(k in stl for k in ["withdraw", "辞退", "負傷", "부상", "omitted", "選外", "제외"]):
                return ("not_called_up", "Không lên tuyển", st)
            if any(k in stl for k in ["roster", "squad", "called", "招集", "メンバー", "代表", "명단", "발탁"]):
                return ("called_up", "Được triệu tập", st)

    if is_youth_match:
        return ("not_called_up", "Không lên tuyển", f"Không có tên trong danh sách đội tuyển trẻ ({nt_tier})")

    if squad_ctx.get("is_domestic_or_u24_tournament") and club_league in {"MLB", "Premier League", "La Liga", "Bundesliga", "Serie A", "Ligue 1", "NBA"}:
        return ("not_called_up", "Không lên tuyển", "Giải đấu sử dụng đội hình nội địa / U24")

    return ("unknown", "", "")
