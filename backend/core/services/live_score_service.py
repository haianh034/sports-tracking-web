import urllib.request
import json
import datetime
import concurrent.futures
import time

LIVE_SCORE_CACHE = {
    "timestamp": 0,
    "data": {}
}

CACHE_TTL = 15 # 15 giây bộ nhớ đệm để tải trang siêu tốc

SOCCER_LEAGUES = [
    "uefa.champions",
    "uefa.europa",
    "uefa.euro.conf",
    "eng.1",
    "esp.1",
    "ger.1",
    "ita.1",
    "fra.1",
    "usa.1",
    "tur.1",
    "ned.1",
    "por.1"
]

def format_period_detail(sport: str, detail: str) -> str:
    if not detail:
        return ""
    d = str(detail).strip()
    
    # Basketball
    d = d.replace("1st Quarter", "Hiệp 1").replace("2nd Quarter", "Hiệp 2")
    d = d.replace("3rd Quarter", "Hiệp 3").replace("4th Quarter", "Hiệp 4")
    d = d.replace("Halftime", "Nghỉ giữa hiệp").replace("End of Period", "Hết hiệp")
    d = d.replace("End of 4th Quarter", "Hết hiệp 4")
    d = d.replace("Final", "FT").replace("FINAL", "FT")
    
    # Baseball
    d = d.replace("Top ", "Đầu H").replace("Bot ", "Đáy H").replace("Mid ", "Giữa H")
    d = d.replace("Inning", "Hiệp")

    # Soccer
    d = d.replace("First Half", "Hiệp 1").replace("Second Half", "Hiệp 2")
    
    return d

def get_live_scores_map() -> dict:
    """
    Truy vấn bảng điểm trực tiếp thời gian thực cho tất cả các môn thể thao:
    Bóng rổ (NBA), Bóng đá (C1, EPL...), Bóng chày (MLB).
    Trả về bản đồ: { team_name_lower: match_info_dict }
    """
    now_ts = time.time()
    if now_ts - LIVE_SCORE_CACHE["timestamp"] < CACHE_TTL and LIVE_SCORE_CACHE["data"]:
        return LIVE_SCORE_CACHE["data"]

    headers = {'User-Agent': 'Mozilla/5.0'}
    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    date_str = now_utc.strftime("%Y%m%d")
    yesterday_str = (now_utc - datetime.timedelta(days=1)).strftime("%Y%m%d")

    urls_to_fetch = [
        # NBA
        ("basketball", f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={date_str}"),
        ("basketball", f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={yesterday_str}"),
        # MLB
        ("baseball", f"https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard?dates={date_str}"),
        ("baseball", f"https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard?dates={yesterday_str}"),
    ]
    # Soccer leagues (chỉ tải ngày hôm nay & hôm qua)
    for lg in SOCCER_LEAGUES:
        urls_to_fetch.append(("soccer", f"https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/scoreboard?dates={date_str}"))

    def _fetch_url(item):
        sport, u = item
        try:
            req = urllib.request.Request(u, headers=headers)
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode())
            return sport, data.get("events", [])
        except Exception:
            return sport, []

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        results = list(ex.map(_fetch_url, urls_to_fetch))

    live_map = {}
    for sport, events in results:
        for ev in events:
            comp = ev.get("competitions", [{}])[0]
            st_type = comp.get("status", {}).get("type", {})
            state = st_type.get("state", "pre") # 'in', 'post', 'pre'
            detail = st_type.get("detail", "")
            period_text = format_period_detail(sport, detail)
            
            competitors = comp.get("competitors", [])
            home = next((c for c in competitors if c.get('homeAway') == 'home'), None)
            away = next((c for c in competitors if c.get('homeAway') == 'away'), None)
            
            h_name = home.get('team', {}).get('displayName', '') if home else ''
            h_short = home.get('team', {}).get('name', '') if home else ''
            a_name = away.get('team', {}).get('displayName', '') if away else ''
            a_short = away.get('team', {}).get('name', '') if away else ''
            
            h_score = str(home.get('score', '')).strip() if home and home.get('score') is not None else ''
            a_score = str(away.get('score', '')).strip() if away and away.get('score') is not None else ''

            match_result_str = None
            if state in ['in', 'post'] and (h_score or a_score):
                if period_text:
                    match_result_str = f"{h_name} {h_score} - {a_score} {a_name} ({period_text})"
                else:
                    match_result_str = f"{h_name} {h_score} - {a_score} {a_name}"
            elif state == 'post':
                match_result_str = f"{ev.get('name', '')} (FT)"

            date_str_raw = ev.get("date")
            date_obj = None
            if date_str_raw:
                try:
                    c_date = date_str_raw.replace('Z', '').replace('.000', '')
                    if c_date.count(':') == 1: c_date += ':00'
                    date_obj = datetime.datetime.strptime(c_date[:19], "%Y-%m-%dT%H:%M:%S")
                except Exception:
                    date_obj = None

            league_name = (
                comp.get("league", {}).get("description") or
                ev.get("season", {}).get("displayName") or
                comp.get("league", {}).get("name") or
                ev.get("league", {}).get("name") or
                ("NBA" if sport == "basketball" else ("MLB" if sport == "baseball" else "Giải đấu"))
            )

            info = {
                "event_id": str(ev.get("id")),
                "match_name": ev.get("name"),
                "state": state,
                "status_detail": period_text,
                "match_result": match_result_str,
                "home_name": h_name,
                "away_name": a_name,
                "home_score": h_score,
                "away_score": a_score,
                "match_date": date_obj,
                "competition": league_name,
                "sport": sport
            }

            for t_str in [h_name, h_short, a_name, a_short]:
                if t_str:
                    clean_k = t_str.lower().strip()
                    # Ưu tiên trận đang live 'in' hơn 'post' và 'pre'
                    if clean_k not in live_map or state == 'in' or (live_map[clean_k]["state"] == 'pre' and state == 'post'):
                        live_map[clean_k] = info

    LIVE_SCORE_CACHE["timestamp"] = now_ts
    LIVE_SCORE_CACHE["data"] = live_map
    return live_map

