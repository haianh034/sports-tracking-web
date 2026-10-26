import urllib.request
import urllib.parse
import json
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

def _save_nt_sched_cache():
    try:
        serializable = {}
        for k, v in NATIONAL_TEAM_SCHED_CACHE.items():
            serializable[str(k)] = {"ts": v[0], "matches": v[1]}
        with open(NT_SCHED_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(serializable, f, ensure_ascii=False)
    except Exception:
        pass

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
        "api_team_id": "samurai_japan_senior",
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
        "id_code": "kr_baseball_senior_m",
        "name": "ĐTQG Nam Hàn Quốc",
        "short_name": "ĐTQG Nam Hàn Quốc",
        "nickname": "",
        "sport": "Bóng chày",
        "country": "Hàn Quốc",
        "tier": "Senior",
        "gender": "Men",
        "api_team_id": "korea_baseball_senior",
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
        "api_team_id": "akatsuki_japan_senior",
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
        "id_code": "kr_basketball_senior_m",
        "name": "ĐTQG Nam Hàn Quốc",
        "short_name": "ĐTQG Nam Hàn Quốc",
        "nickname": "",
        "sport": "Bóng rổ",
        "country": "Hàn Quốc",
        "tier": "Senior",
        "gender": "Men",
        "api_team_id": "korea_basketball_senior",
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

def fetch_national_team_schedule(team) -> list:
    """
    Fetches 100% REAL match schedule for national & youth teams using official ESPN endpoints.
    Strictly NO fake or fabricated fixtures: if no match is scheduled on official APIs,
    an empty list is returned.
    """
    t_id = getattr(team, "id", None) or (team.get("id") if isinstance(team, dict) else 0)
    t_sport = getattr(team, "sport_name", None) or (team.get("sport_name") if isinstance(team, dict) else "")
    t_api_id = getattr(team, "api_team_id", None) or (team.get("api_team_id") if isinstance(team, dict) else "")
    t_country = getattr(team, "country_name", None) or (team.get("country_name") if isinstance(team, dict) else "")
    t_short = getattr(team, "short_name", None) or (team.get("short_name") if isinstance(team, dict) else "")

    cache_key = t_id
    now_ts = datetime.datetime.now().timestamp()
    if cache_key in NATIONAL_TEAM_SCHED_CACHE:
        cached_ts, cached_matches = NATIONAL_TEAM_SCHED_CACHE[cache_key]
        if now_ts - cached_ts < 1800:  # 15 minutes cache
            return cached_matches

    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    matches = []

    # 1. ESPN Soccer API for official national & youth football teams
    if t_sport == "Bóng đá" and t_api_id and str(t_api_id).isdigit():
        urls = [
            f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/{t_api_id}/schedule?fixture=true",
            f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/{t_api_id}/schedule"
        ]
        seen_keys = set()
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

                    if -365 <= diff <= 365:
                        name = ev.get("name") or ""
                        comp_obj = ev.get("competitions", [{}])[0]
                        comp_name = ev.get("league", {}).get("name") or comp_obj.get("league", {}).get("description") or "Giải quốc tế"
                        status_type = ev.get("status", {}).get("type", {})
                        state = "post" if status_type.get("completed") else ("in" if status_type.get("state") == "in" else "pre")
                        
                        competitors = comp_obj.get("competitors", [])
                        home = next((c for c in competitors if c.get('homeAway') == 'home'), None)
                        away = next((c for c in competitors if c.get('homeAway') == 'away'), None)
                        h_name = home.get('team', {}).get('displayName', '') if home else ''
                        a_name = away.get('team', {}).get('displayName', '') if away else ''

                        is_home = (t_country.lower() in h_name.lower() or "japan" in h_name.lower() or "korea" in h_name.lower())
                        opp_name = f"vs {a_name}" if is_home else f"@ {h_name}"
                        if not a_name or not h_name:
                            opp_name = f"vs {name}"

                        res_str = None
                        if state == "post":
                            h_score = home.get('score', '') if home else ''
                            a_score = away.get('score', '') if away else ''
                            if h_score and a_score:
                                res_str = f"{h_score} - {a_score}"
                            else:
                                res_str = "Đã kết thúc"

                        dt_vn = dt + datetime.timedelta(hours=7)
                        m_key = (dt_vn.strftime("%Y-%m-%d"), opp_name.lower())
                        if m_key not in seen_keys:
                            seen_keys.add(m_key)
                            matches.append({
                                "match_name": opp_name,
                                "raw_match_name": f"{t_short} {opp_name}",
                                "match_date_utc": dt.isoformat(),
                                "date_vn": dt_vn.strftime("%d/%m %H:%M"),
                                "date_full_vn": dt_vn.strftime("%d/%m/%Y %H:%M"),
                                "date_only_vn": dt_vn.strftime("%Y-%m-%d"),
                                "competition": comp_name,
                                "match_state": state,
                                "match_result": res_str,
                                "is_past": (state == "post" or diff < -0.1),
                                "event_id": f"espn_nt_{ev.get('id', '')}",
                                "diff_days": diff
                            })
            except Exception:
                pass

    # Strictly truthful: if no match on official API, matches remains [] (empty list)
    matches.sort(key=lambda x: x["match_date_utc"])
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
    is_japan = (team.country_name == "Nhật Bản")
    is_korea = (team.country_name == "Hàn Quốc")

    if is_japan:
        native_q = cat_match.get("query_native") if cat_match else f"{team.nickname or team.name}"
        query_configs.append({
            "query": native_q,
            "hl": "ja",
            "gl": "JP",
            "ceid": "JP:ja",
            "region": "JP"
        })
    elif is_korea:
        native_q = cat_match.get("query_native") if cat_match else f"{team.nickname or team.name}"
        query_configs.append({
            "query": native_q,
            "hl": "ko",
            "gl": "KR",
            "ceid": "KR:ko",
            "region": "KR"
        })

    # International English query fallback
    en_q = cat_match.get("query_en") if cat_match else f"{team.name} {team.sport_name}"
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
