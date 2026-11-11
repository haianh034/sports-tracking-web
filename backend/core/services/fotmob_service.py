import os
import json
import urllib.request
import urllib.parse
import re
from datetime import datetime, timezone, timedelta

import unicodedata

FOTMOB_CACHE_FILE = os.path.join(os.path.dirname(__file__), "fotmob_players_cache.json")
FOTMOB_PLAYER_CACHE = {}
FOTMOB_PLAYER_DATA_CACHE = {}  # {fotmob_p_id: (ts, p_data)}
FOTMOB_MATCH_CACHE = {}

if os.path.exists(FOTMOB_CACHE_FILE):
    try:
        with open(FOTMOB_CACHE_FILE, "r", encoding="utf-8") as f:
            FOTMOB_PLAYER_CACHE = json.load(f)
    except Exception:
        FOTMOB_PLAYER_CACHE = {}

def _save_player_cache():
    try:
        with open(FOTMOB_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(FOTMOB_PLAYER_CACHE, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Referer': 'https://www.fotmob.com/',
    'Accept': 'application/json, text/plain, */*'
}

def _norm_team_text(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize('NFKD', s).encode('ASCII', 'ignore').decode('utf-8').lower()
    s = re.sub(r'^(@ |vs |vs\. )', '', s).strip()
    s = re.sub(r'\((?:w|nu|nữ|women|f|ladies)\)', '', s)
    s = re.sub(r'\b(muenchen|munchen)\b', 'munich', s)
    s = re.sub(r'\b(koeln|koln)\b', 'cologne', s)
    s = re.sub(r'\bpsg\b', 'paris saint germain', s)
    s = re.sub(r'\bman utd\b', 'manchester united', s)
    s = re.sub(r'\bman city\b', 'manchester city', s)
    s = re.sub(r'\b(fc|sc|cf|afc|ac|as|vfl|vfb|tsv|fsv|women|ladies|frauen|femeni)\b', ' ', s)
    s = re.sub(r'[^a-z0-9\s]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()

def _parse_utc_dt(raw_str: str):
    if not raw_str:
        return None
    s = str(raw_str).strip()
    clean = s.replace('Z', '').split('.')[0]
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            target = clean[:19] if len(fmt) >= 17 else (clean[:16] if len(fmt) >= 14 else clean[:10])
            return datetime.strptime(target, fmt)
        except Exception:
            continue
    return None

def get_fotmob_player(player_name: str, team_name: str = "") -> dict:
    """
    Tìm kiếm và ánh xạ cầu thủ bóng đá sang FotMob player ID.
    Hỗ trợ tên tiếng Anh, tên phiên âm châu Á (Hàn Quốc, Nhật Bản, Việt Nam).
    """
    if not player_name:
        return None
    
    clean_name = player_name.strip()
    norm_team_key = _norm_team_text(team_name or "")
    cache_key = f"{clean_name.lower()}||{norm_team_key}"
    if cache_key in FOTMOB_PLAYER_CACHE:
        return FOTMOB_PLAYER_CACHE[cache_key]

    parts = clean_name.split()
    queries = [clean_name]
    if len(parts) >= 2:
        queries.append(' '.join(parts[1:]) + ' ' + parts[0])
        queries.append(parts[-1] + ' ' + ' '.join(parts[:-1]))
    
    seen_q = set()
    best_cand = None
    t_keywords = [w for w in norm_team_key.split() if len(w) >= 3]

    for q in queries:
        if q in seen_q:
            continue
        seen_q.add(q)
        safe_q = urllib.parse.quote(q)
        url = f"https://www.fotmob.com/api/data/search/suggest?term={safe_q}"
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode())
            
            for grp in data:
                for sug in grp.get("suggestions", []):
                    if sug.get("type") == "player":
                        cand_team = _norm_team_text(sug.get("teamName") or "")
                        if t_keywords and cand_team:
                            if any(w in cand_team for w in t_keywords):
                                res = {
                                    "id": str(sug.get("id")),
                                    "name": sug.get("name"),
                                    "teamName": sug.get("teamName")
                                }
                                FOTMOB_PLAYER_CACHE[cache_key] = res
                                _save_player_cache()
                                return res
                        if not best_cand:
                            best_cand = {
                                "id": str(sug.get("id")),
                                "name": sug.get("name"),
                                "teamName": sug.get("teamName")
                            }
        except Exception:
            continue

    if best_cand:
        FOTMOB_PLAYER_CACHE[cache_key] = best_cand
        _save_player_cache()
        return best_cand

    return None

def _opponents_match(opp_norm: str, opp_keywords: list[str], m_opp_norm: str) -> bool:
    if not opp_norm or not m_opp_norm:
        return False
    if opp_norm == m_opp_norm or opp_norm in m_opp_norm or m_opp_norm in opp_norm:
        return True
    if opp_keywords and any(kw in m_opp_norm for kw in opp_keywords):
        return True
    return False

def fetch_fotmob_detailed_stats(player_name: str, team_name: str = "", opponent_name: str = "", event_date_utc: str = None) -> dict:
    """
    Truy vấn dữ liệu trận đấu và thông số chuyên sâu (Opta) từ FotMob cho cầu thủ bóng đá:
    - Điểm FotMob rating (chính thức)
    - Key Passes (Tạo cơ hội)
    - Cú sút (Shots)
    - Tỷ lệ chuyền bóng chính xác (Accurate passes %)
    - Rê bóng thành công (Dribbles %)
    - Tranh chấp thắng (Ground duels %)
    - Số lần chạm bóng (Touches)
    - Thu hồi bóng (Recoveries), tắc bóng (Tackles), v.v.
    Khớp chính xác theo ngày thi đấu (±36h) và đối thủ. Không bao giờ lấy bừa recentMatches[0].
    """
    player_info = get_fotmob_player(player_name, team_name)
    if not player_info or not player_info.get("id"):
        return None

    fotmob_p_id = str(player_info["id"])
    
    # 1. Tải playerData để lấy danh sách recentMatches (cache ngắn 10 phút trong RAM)
    now_ts = datetime.now().timestamp()
    cached_pd = FOTMOB_PLAYER_DATA_CACHE.get(fotmob_p_id)
    if cached_pd and now_ts - cached_pd[0] < 600:
        p_data = cached_pd[1]
    else:
        player_url = f"https://www.fotmob.com/api/data/playerData?id={fotmob_p_id}"
        try:
            req = urllib.request.Request(player_url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=5) as resp:
                p_data = json.loads(resp.read().decode())
            FOTMOB_PLAYER_DATA_CACHE[fotmob_p_id] = (now_ts, p_data)
        except Exception:
            return None

    recent_matches = p_data.get("recentMatches", [])
    if not recent_matches:
        return None

    target_dt = _parse_utc_dt(event_date_utc)
    opp_norm = _norm_team_text(opponent_name or "")
    opp_keywords = [w for w in opp_norm.split() if len(w) >= 3 and w not in {"the", "club", "city", "united", "real", "saint"}]
    if not opp_keywords and opp_norm:
        opp_keywords = [w for w in opp_norm.split() if len(w) >= 3]

    # Cần ít nhất ngày thi đấu hoặc tên đối thủ mới có thể đối chiếu trận thật
    if not target_dt and not opp_norm:
        return None

    target_match = None
    if target_dt:
        date_candidates = []
        for m in recent_matches:
            m_dt = _parse_utc_dt((m.get("matchDate") or {}).get("utcTime"))
            if not m_dt:
                continue
            delta_sec = abs((m_dt - target_dt).total_seconds())
            if delta_sec <= 36 * 3600:
                date_candidates.append((delta_sec, m))
        date_candidates.sort(key=lambda x: x[0])

        if date_candidates:
            if opp_norm:
                for _, m in date_candidates:
                    m_opp_norm = _norm_team_text(m.get("opponentTeamName") or "")
                    if _opponents_match(opp_norm, opp_keywords, m_opp_norm):
                        target_match = m
                        break
            else:
                # Không có tên đối thủ, chỉ nhận nếu trùng trong ±24h
                if date_candidates[0][0] <= 24 * 3600:
                    target_match = date_candidates[0][1]
    elif opp_norm:
        # Không có ngày thi đấu: chỉ nhận nếu chỉ có đúng 1 trận khớp đối thủ để tránh dính trận lượt đi/lượt về khác ngày
        opp_matches = []
        for m in recent_matches:
            m_opp_norm = _norm_team_text(m.get("opponentTeamName") or "")
            if _opponents_match(opp_norm, opp_keywords, m_opp_norm):
                opp_matches.append(m)
        if len(opp_matches) == 1:
            target_match = opp_matches[0]

    if not target_match:
        return None

    match_id = target_match.get("id")
    if not match_id:
        return None

    # 2. Tải matchDetails từ FotMob
    match_cache_key = f"{match_id}_{fotmob_p_id}"
    if match_cache_key in FOTMOB_MATCH_CACHE:
        return FOTMOB_MATCH_CACHE[match_cache_key]

    match_url = f"https://www.fotmob.com/api/data/matchDetails?matchId={match_id}"
    try:
        req = urllib.request.Request(match_url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=6) as resp:
            m_data = json.loads(resp.read().decode())
    except Exception:
        return None

    player_stats_map = m_data.get("content", {}).get("playerStats", {})
    p_stat_obj = player_stats_map.get(fotmob_p_id)
    if not p_stat_obj:
        return None

    # Bóc tách các chỉ số từ tất cả các nhóm (Top stats, Attack, Defense, Duels)
    stats_dict = {}
    for grp in p_stat_obj.get("stats", []):
        for k, v in grp.get("stats", {}).items():
            stats_dict[k] = v.get("stat", {})

    # Rating
    raw_rating = stats_dict.get("FotMob rating", {}).get("value")
    if not raw_rating and target_match.get("ratingProps", {}).get("rating"):
        try:
            raw_rating = float(target_match["ratingProps"]["rating"])
        except Exception:
            raw_rating = None
    
    fotmob_rating = round(float(raw_rating), 1) if raw_rating is not None else None

    # Key Passes / Chances created
    chances_created = stats_dict.get("Chances created", {}).get("value", 0)
    
    # Shots
    total_shots = stats_dict.get("Total shots", {}).get("value", 0)
    shots_on_target = stats_dict.get("Shots on target", {}).get("value", 0)
    
    # Passes
    acc_passes_stat = stats_dict.get("Accurate passes", {})
    acc_p_val = acc_passes_stat.get("value")
    acc_p_total = acc_passes_stat.get("total")
    acc_p_pct = round((acc_p_val / acc_p_total) * 100) if (acc_p_val is not None and acc_p_total and acc_p_total > 0) else None
    
    # Dribbles
    dribbles_stat = stats_dict.get("Successful dribbles", {})
    dribbles_val = dribbles_stat.get("value")
    dribbles_total = dribbles_stat.get("total")
    dribbles_pct = round((dribbles_val / dribbles_total) * 100) if (dribbles_val is not None and dribbles_total and dribbles_total > 0) else None

    # Duels
    g_duels_stat = stats_dict.get("Ground duels won", {})
    g_duels_val = g_duels_stat.get("value")
    g_duels_total = g_duels_stat.get("total")
    g_duels_pct = round((g_duels_val / g_duels_total) * 100) if (g_duels_val is not None and g_duels_total and g_duels_total > 0) else None

    touches = stats_dict.get("Touches", {}).get("value", 0)
    recoveries = stats_dict.get("Recoveries", {}).get("value", 0)
    minutes_played = stats_dict.get("Minutes played", {}).get("value") or target_match.get("minutesPlayed", 90)
    goals = stats_dict.get("Goals", {}).get("value") or target_match.get("goals", 0)
    assists = stats_dict.get("Assists", {}).get("value") or target_match.get("assists", 0)

    # Fun facts / Điểm nhấn nổi bật
    fun_facts = []
    for ff in p_stat_obj.get("funFacts", []):
        fb_text = ff.get("fallbackText", "")
        val = ff.get("value", "")
        if "chances" in fb_text.lower():
            fun_facts.append(f"Tạo cơ hội nhiều nhất trận ({val} lần)")
        elif "dribble" in fb_text.lower():
            fun_facts.append(f"Rê bóng nhiều nhất trận ({val} lần)")
        elif "shots" in fb_text.lower():
            fun_facts.append(f"Dứt điểm nhiều nhất trận ({val} cú sút)")
        elif "scored an own goal" in fb_text.lower() or "own goal" in fb_text.lower():
            fun_facts.append("Phản lưới")
        elif fb_text:
            fun_facts.append(fb_text.replace("%1$s", str(val)))

    # Xây dựng danh sách metrics chi tiết
    metrics = []
    if chances_created > 0:
        is_most = any("cơ hội" in ff.lower() for ff in fun_facts)
        metrics.append({
            "label": "Tạo cơ hội (Key Passes)",
            "value": f"{chances_created} lần" + (" (Cao nhất trận)" if is_most else ""),
            "highlight": chances_created >= 3
        })
    
    if total_shots > 0:
        shots_str = f"{total_shots} cú sút"
        if shots_on_target > 0:
            shots_str += f" ({shots_on_target} trúng đích)"
        metrics.append({
            "label": "Số cú sút",
            "value": shots_str,
            "highlight": total_shots >= 3
        })

    if acc_p_val is not None and acc_p_total is not None and acc_p_total > 0:
        metrics.append({
            "label": "Tỷ lệ chuyền bóng chính xác",
            "value": f"{acc_p_pct}% ({acc_p_val}/{acc_p_total})",
            "highlight": acc_p_pct >= 85
        })

    if dribbles_val is not None and dribbles_total is not None and dribbles_total > 0:
        metrics.append({
            "label": "Rê bóng thành công",
            "value": f"{dribbles_pct}% ({dribbles_val}/{dribbles_total})",
            "highlight": dribbles_pct >= 70
        })

    if g_duels_val is not None and g_duels_total is not None and g_duels_total > 0:
        metrics.append({
            "label": "Tranh chấp tầm thấp thắng",
            "value": f"{g_duels_val}/{g_duels_total} ({g_duels_pct}%)",
            "highlight": g_duels_val >= 4
        })

    if touches > 0:
        metrics.append({
            "label": "Chạm bóng",
            "value": f"{touches} lần",
            "highlight": touches >= 50
        })

    if recoveries > 0:
        metrics.append({
            "label": "Thu hồi bóng (Recoveries)",
            "value": f"{recoveries} lần",
            "highlight": False
        })

    if minutes_played:
        metrics.append({
            "label": "Thời gian thi đấu",
            "value": f"{minutes_played} phút",
            "highlight": False
        })

    # Tóm tắt hiển thị gọn gàng trên thẻ cầu thủ
    summary_parts = []
    if goals > 0:
        summary_parts.append(f"{goals} bàn")
    if assists > 0:
        summary_parts.append(f"{assists} kiến tạo")
    if chances_created > 0:
        summary_parts.append(f"{chances_created} tạo cơ hội")
    if total_shots > 0 and goals == 0:
        summary_parts.append(f"{total_shots} sút")
    if acc_p_pct is not None:
        summary_parts.append(f"{acc_p_pct}% chuyền ({acc_p_val}/{acc_p_total})")
    elif touches > 0:
        summary_parts.append(f"{touches} chạm")

    summary_text = ", ".join(summary_parts) if summary_parts else (f"{minutes_played} phút" if minutes_played else "")

    # Kiểm tra danh hiệu Cầu thủ xuất sắc nhất trận (MOTM / Player of the Match) do chính FotMob công nhận
    is_potm = False
    potm_obj = m_data.get("content", {}).get("matchFacts", {}).get("playerOfTheMatch")
    if potm_obj and str(potm_obj.get("id")) == str(fotmob_p_id):
        is_potm = True
    else:
        top_players = m_data.get("content", {}).get("matchFacts", {}).get("topPlayers", {})
        for tp_list in [top_players.get("homeTopPlayers", []), top_players.get("awayTopPlayers", [])]:
            for tp in tp_list:
                if str(tp.get("id")) == str(fotmob_p_id) and tp.get("manOfTheMatch"):
                    is_potm = True
                    break
            if is_potm:
                break
        if not is_potm:
            lineup = m_data.get("content", {}).get("lineup", {})
            for t_key in ["homeTeam", "awayTeam"]:
                t_obj = lineup.get(t_key, {})
                for player_entry in t_obj.get("starters", []) + t_obj.get("subs", []):
                    if str(player_entry.get("id")) == str(fotmob_p_id):
                        if player_entry.get("performance", {}).get("playerOfTheMatch"):
                            is_potm = True
                        break
                if is_potm:
                    break

    result = {
        "source": "FotMob",
        "fotmob_rating": fotmob_rating,
        "rating": fotmob_rating,
        "is_player_of_the_match": is_potm,
        "summary": summary_text,
        "metrics": metrics,
        "fun_facts": fun_facts,
        "match_id": match_id,
        "opponent": target_match.get("opponentTeamName"),
        "minutes_played": minutes_played,
        "goals": goals,
        "assists": assists
    }

    FOTMOB_MATCH_CACHE[match_cache_key] = result
    return result

