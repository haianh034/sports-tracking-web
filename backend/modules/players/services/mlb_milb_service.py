"""
Official MLB + Minor League Baseball (MiLB) Schedule & Boxscore Service.
Powered by the official MLB Stats API (https://statsapi.mlb.com/api/v1/):
- Covers MLB (sportId=1) AND all Minor League levels:
  Triple-A (11), Double-A (12), High-A (13), Single-A (14), Rookie/Complex (16).
- Automatically detects when an MLB player is optioned down or on rehab assignment
  in MiLB, fetches their MiLB team schedule and game-by-game hitting/pitching stats,
  and computes realistic performance ratings.
"""

import datetime
import json
import os
import re
import unicodedata
import httpx

MLB_STATS_BASE = "https://statsapi.mlb.com/api/v1"
MLB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

MILB_SPORT_IDS = {
    11: "MiLB (Triple-A)",
    12: "MiLB (Double-A)",
    13: "MiLB (High-A)",
    14: "MiLB (Single-A)",
    16: "MiLB (Rookie)",
}
ALL_BASEBALL_SPORT_IDS = {1: "MLB", **MILB_SPORT_IDS}

_DIR = os.path.dirname(__file__)
MLB_PLAYER_CACHE_FILE = os.path.join(_DIR, "mlb_player_id_cache.json")

MLB_PLAYER_CACHE = {}        # norm_name -> {"ts": float, "person_id": int, "full_name": str, "team_id": int, "team_name": str, "sport_id": int}
MILB_SCHED_CACHE = {}        # f"{norm_name}||{deep}" -> {"ts": float, "matches": list}
MILB_MATCH_STATS_LOOKUP = {} # f"milb_{game_pk}||{norm_name}" -> dict

_HTTP_CLIENT = httpx.Client(timeout=8.0, headers=MLB_HEADERS, follow_redirects=True)


def _norm_name(name: str) -> str:
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", str(name))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _stats_key(event_id: str, player_name: str = "") -> str:
    ev = str(event_id or "").strip()
    pn = _norm_name(player_name)
    return f"{ev}||{pn}" if pn else ev


def _load_player_cache():
    global MLB_PLAYER_CACHE
    if MLB_PLAYER_CACHE:
        return
    try:
        if os.path.exists(MLB_PLAYER_CACHE_FILE):
            with open(MLB_PLAYER_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    MLB_PLAYER_CACHE = data
    except Exception:
        MLB_PLAYER_CACHE = {}


def _save_player_cache():
    try:
        with open(MLB_PLAYER_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(MLB_PLAYER_CACHE, f, ensure_ascii=False)
    except Exception:
        pass


def resolve_mlb_player(player_name: str) -> dict | None:
    """Resolve MLB/MiLB player ID and current team (including Minor League assignments)."""
    _load_player_cache()
    nk = _norm_name(player_name)
    if not nk:
        return None

    now_ts = datetime.datetime.now().timestamp()
    cached = MLB_PLAYER_CACHE.get(nk)
    # Refresh team assignment every 12 hours in case of call-up / option down to Triple-A
    if cached and (now_ts - cached.get("ts", 0)) < 12 * 3600:
        return cached if cached.get("person_id") else None

    try:
        resp = _HTTP_CLIENT.get(
            f"{MLB_STATS_BASE}/people/search",
            params={"names": player_name, "hydrate": "currentTeam"},
        )
        if resp.status_code != 200:
            return None
        people = resp.json().get("people") or []
        if not people:
            MLB_PLAYER_CACHE[nk] = {"ts": now_ts, "person_id": None}
            _save_player_cache()
            return None

        # Pick best matching active player
        chosen = None
        for p in people:
            if _norm_name(p.get("fullName", "")) == nk:
                chosen = p
                break
        if not chosen:
            for p in people:
                if p.get("active"):
                    chosen = p
                    break
        if not chosen:
            chosen = people[0]

        pid = chosen.get("id")
        ct = chosen.get("currentTeam") or {}
        tid = ct.get("id")
        tname = ct.get("name") or ""
        sid = (ct.get("sport") or {}).get("id")

        # If sportId wasn't hydrated on currentTeam, query team endpoint once
        if tid and not sid:
            try:
                tr = _HTTP_CLIENT.get(f"{MLB_STATS_BASE}/teams/{tid}")
                if tr.status_code == 200:
                    t_list = tr.json().get("teams") or []
                    if t_list:
                        sid = (t_list[0].get("sport") or {}).get("id")
                        tname = tname or t_list[0].get("name") or ""
            except Exception:
                pass

        info = {
            "ts": now_ts,
            "person_id": pid,
            "full_name": chosen.get("fullName") or player_name,
            "team_id": tid,
            "team_name": tname,
            "sport_id": sid or 1,
            "level_label": ALL_BASEBALL_SPORT_IDS.get(sid or 1, "MLB"),
            "primary_position": (chosen.get("primaryPosition") or {}).get("abbreviation", ""),
        }
        MLB_PLAYER_CACHE[nk] = info
        _save_player_cache()
        return info
    except Exception:
        return None


def _calc_hitting_rating(stat: dict, is_win: bool = False) -> tuple[float, str, list]:
    hits = int(stat.get("hits", 0) or 0)
    ab = int(stat.get("atBats", 0) or 0)
    hr = int(stat.get("homeRuns", 0) or 0)
    rbi = int(stat.get("rbi", 0) or 0)
    runs = int(stat.get("runs", 0) or 0)
    bb = int(stat.get("baseOnBalls", 0) or 0)
    sb = int(stat.get("stolenBases", 0) or 0)
    doubles = int(stat.get("doubles", 0) or 0)
    triples = int(stat.get("triples", 0) or 0)
    so = int(stat.get("strikeOuts", 0) or 0)

    rating = 6.3 + (0.4 * hits) + (0.7 * hr) + (0.25 * rbi) + (0.2 * runs) + (0.2 * bb) + (0.25 * sb) + (0.15 * doubles) + (0.3 * triples) - (0.12 * so)
    if is_win:
        rating += 0.2
    rating = round(min(9.8, max(5.2, rating)), 1)

    parts = [f"{hits}-{ab}"]
    if hr > 0:
        parts.append(f"{hr} HR")
    if rbi > 0:
        parts.append(f"{rbi} RBI")
    if runs > 0:
        parts.append(f"{runs} R")
    if bb > 0:
        parts.append(f"{bb} BB")
    if sb > 0:
        parts.append(f"{sb} SB")
    summary = ", ".join(parts)

    tags = []
    if hr >= 2:
        tags.append(f"{hr} Home Run")
    elif hr == 1:
        tags.append("Home Run")
    if hits >= 3:
        tags.append(f"{hits} Hits")
    elif hits == 2:
        tags.append("2 Hits")
    if rbi >= 2:
        tags.append(f"{rbi} RBI")
    if sb >= 1:
        tags.append(f"{sb} Cướp chốt")
    return rating, summary, tags


def _calc_pitching_rating(stat: dict, is_win: bool = False) -> tuple[float, str, list]:
    ip_str = str(stat.get("inningsPitched", "0.0") or "0.0")
    try:
        ip_parts = ip_str.split(".")
        ip_val = int(ip_parts[0]) + (int(ip_parts[1]) / 3.0 if len(ip_parts) > 1 else 0.0)
    except Exception:
        ip_val = 0.0
    er = int(stat.get("earnedRuns", 0) or 0)
    so = int(stat.get("strikeOuts", 0) or 0)
    hits_a = int(stat.get("hits", 0) or 0)
    bb = int(stat.get("baseOnBalls", 0) or 0)
    wins = int(stat.get("wins", 0) or 0)
    saves = int(stat.get("saves", 0) or 0)

    rating = 6.5 + (0.22 * ip_val) + (0.18 * so) - (0.45 * er) - (0.1 * bb)
    if wins > 0:
        rating += 0.5
    if saves > 0:
        rating += 0.5
    if ip_val >= 6.0 and er <= 2:
        rating += 0.4  # Quality start
    if is_win:
        rating += 0.15
    rating = round(min(9.8, max(5.0, rating)), 1)

    summary = f"{ip_str} IP, {hits_a} H, {er} ER, {so} K, {bb} BB"
    tags = []
    if wins > 0:
        tags.append("Pitcher thắng (W)")
    if saves > 0:
        tags.append("Cứu thua (SV)")
    if so >= 6:
        tags.append(f"{so} Strikeouts")
    if ip_val >= 6.0 and er == 0:
        tags.append("Không để mất điểm")
    return rating, summary, tags


def fetch_mlb_milb_player_schedule(
    player_name: str,
    current_team: str = "",
    include_deep_history: bool = False,
) -> list:
    """
    Fetch Minor League (MiLB: Triple-A, Double-A, High-A, Single-A, Rookie) game logs
    and upcoming schedule for a baseball player via the official MLB Stats API.
    """
    nk = _norm_name(player_name)
    if not nk:
        return []

    cache_k = f"{nk}||{bool(include_deep_history)}"
    now_ts = datetime.datetime.now().timestamp()
    if cache_k in MILB_SCHED_CACHE:
        c_entry = MILB_SCHED_CACHE[cache_k]
        if now_ts - c_entry["ts"] < 900:  # 15 minutes
            return list(c_entry["matches"])

    p_info = resolve_mlb_player(player_name)
    if not p_info or not p_info.get("person_id"):
        return []

    pid = p_info["person_id"]
    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    season = now_utc.year
    past_days_limit = 300 if include_deep_history else 14

    matches = []
    seen_pks = set()

    # 1. Fetch MiLB game logs across Triple-A, Double-A, High-A, Single-A
    # Prioritize Triple-A (11) & Double-A (12); include current sport_id if lower
    sport_ids_to_check = [11, 12]
    cur_sid = p_info.get("sport_id") or 1
    if cur_sid in MILB_SPORT_IDS and cur_sid not in sport_ids_to_check:
        sport_ids_to_check.insert(0, cur_sid)

    pos_abbr = (p_info.get("primary_position") or "").upper()
    groups = ["pitching", "hitting"] if pos_abbr == "P" else ["hitting", "pitching"]

    for sid in sport_ids_to_check:
        lvl_label = MILB_SPORT_IDS.get(sid, "MiLB")
        found_in_level = False
        for grp in groups:
            try:
                r = _HTTP_CLIENT.get(
                    f"{MLB_STATS_BASE}/people/{pid}/stats",
                    params={
                        "stats": "gameLog",
                        "group": grp,
                        "season": season,
                        "sportId": sid,
                    },
                )
                if r.status_code != 200:
                    continue
                stats_blocks = r.json().get("stats") or []
                splits = []
                for blk in stats_blocks:
                    splits.extend(blk.get("splits") or [])
                if not splits:
                    continue
                found_in_level = True

                for sp in splits:
                    g_date_str = sp.get("date") or ""
                    game_obj = sp.get("game") or {}
                    game_pk = game_obj.get("gamePk")
                    if not g_date_str or not game_pk or game_pk in seen_pks:
                        continue
                    try:
                        g_dt = datetime.datetime.strptime(g_date_str[:10], "%Y-%m-%d") + datetime.timedelta(hours=23)
                    except Exception:
                        continue

                    diff_days = (g_dt - now_utc).total_seconds() / 86400.0
                    if diff_days < -past_days_limit:
                        continue

                    seen_pks.add(game_pk)
                    is_home = bool(sp.get("isHome"))
                    is_win = bool(sp.get("isWin"))
                    my_team_name = (sp.get("team") or {}).get("name") or p_info.get("team_name") or current_team
                    opp_name = (sp.get("opponent") or {}).get("name") or "Opponent"
                    stat_dict = sp.get("stat") or {}

                    if grp == "pitching":
                        rating, summary, extra_tags = _calc_pitching_rating(stat_dict, is_win=is_win)
                    else:
                        rating, summary, extra_tags = _calc_hitting_rating(stat_dict, is_win=is_win)

                    wl_tag = "Thắng" if is_win else "Thua"
                    tags = [lvl_label, wl_tag] + [t for t in extra_tags if t not in (lvl_label, wl_tag)]
                    dt_vn = g_dt + datetime.timedelta(hours=7)
                    prefix = "vs " if is_home else "@ "
                    ev_id = f"milb_{game_pk}"
                    m_res = f"{my_team_name} ({wl_tag}) vs {opp_name} (FT)"

                    stat_payload = {
                        "has_played": True,
                        "stats_text": summary,
                        "tags": tags,
                        "rating": rating,
                        "match_result": m_res,
                    }
                    MILB_MATCH_STATS_LOOKUP[_stats_key(ev_id, player_name)] = stat_payload
                    MILB_MATCH_STATS_LOOKUP[ev_id] = stat_payload

                    matches.append({
                        "match_name": f"{prefix}{opp_name}",
                        "raw_match_name": f"{my_team_name} vs {opp_name}",
                        "match_date_utc": g_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "date_vn": dt_vn.strftime("%d/%m %H:%M"),
                        "date_full_vn": dt_vn.strftime("%d/%m/%Y %H:%M"),
                        "date_only_vn": dt_vn.strftime("%Y-%m-%d"),
                        "time_only_vn": dt_vn.strftime("%H:%M"),
                        "competition": lvl_label,
                        "event_id": ev_id,
                        "match_state": "post",
                        "match_result": m_res,
                        "status_detail": m_res,
                        "has_played": True,
                        "diff_days": diff_days,
                        "player_team": my_team_name,
                        "player_stats": summary,
                        "tags": tags,
                        "rating": rating,
                    })
            except Exception:
                continue
        if found_in_level and not include_deep_history:
            break

    # 2. If player is CURRENTLY assigned to a MiLB team, fetch upcoming 30-day schedule for that MiLB team
    if cur_sid in MILB_SPORT_IDS and p_info.get("team_id"):
        tid = p_info["team_id"]
        lvl_label = MILB_SPORT_IDS[cur_sid]
        start_s = (now_utc - datetime.timedelta(days=2)).strftime("%Y-%m-%d")
        end_s = (now_utc + datetime.timedelta(days=30)).strftime("%Y-%m-%d")
        try:
            rs = _HTTP_CLIENT.get(
                f"{MLB_STATS_BASE}/schedule",
                params={"teamId": tid, "sportId": cur_sid, "startDate": start_s, "endDate": end_s},
            )
            if rs.status_code == 200:
                for d_blk in rs.json().get("dates") or []:
                    for g in d_blk.get("games") or []:
                        gpk = g.get("gamePk")
                        if not gpk or gpk in seen_pks:
                            continue
                        g_utc_str = g.get("gameDate") or ""
                        try:
                            g_dt = datetime.datetime.strptime(g_utc_str[:19], "%Y-%m-%dT%H:%M:%S")
                        except Exception:
                            continue
                        teams_obj = g.get("teams") or {}
                        home_obj = teams_obj.get("home") or {}
                        away_obj = teams_obj.get("away") or {}
                        h_team = (home_obj.get("team") or {}).get("name") or ""
                        a_team = (away_obj.get("team") or {}).get("name") or ""
                        h_id = (home_obj.get("team") or {}).get("id")
                        is_home = (h_id == tid)
                        my_t = h_team if is_home else a_team
                        opp_t = a_team if is_home else h_team

                        abs_state = ((g.get("status") or {}).get("abstractGameState") or "Preview").lower()
                        if abs_state == "final":
                            m_state = "post"
                        elif abs_state == "live":
                            m_state = "in"
                        else:
                            m_state = "pre"

                        h_sc = home_obj.get("score")
                        a_sc = away_obj.get("score")
                        m_res = None
                        if m_state in ("post", "in") and h_sc is not None and a_sc is not None:
                            st_lbl = "LIVE" if m_state == "in" else "FT"
                            m_res = f"{h_team} {h_sc} - {a_sc} {a_team} ({st_lbl})"

                        dt_vn = g_dt + datetime.timedelta(hours=7)
                        diff_days = (g_dt - now_utc).total_seconds() / 86400.0
                        ev_id = f"milb_{gpk}"
                        seen_pks.add(gpk)

                        matches.append({
                            "match_name": f"{'vs ' if is_home else '@ '}{opp_t}",
                            "raw_match_name": f"{h_team} vs {a_team}",
                            "match_date_utc": g_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "date_vn": dt_vn.strftime("%d/%m %H:%M"),
                            "date_full_vn": dt_vn.strftime("%d/%m/%Y %H:%M"),
                            "date_only_vn": dt_vn.strftime("%Y-%m-%d"),
                            "time_only_vn": dt_vn.strftime("%H:%M"),
                            "competition": lvl_label,
                            "event_id": ev_id,
                            "match_state": m_state,
                            "match_result": m_res,
                            "status_detail": m_res or dt_vn.strftime("%d/%m • %H:%M"),
                            "has_played": (m_state == "post"),
                            "diff_days": diff_days,
                            "player_team": my_t,
                        })
        except Exception:
            pass

    matches.sort(key=lambda x: str(x.get("match_date_utc") or ""))
    MILB_SCHED_CACHE[cache_k] = {"ts": now_ts, "matches": matches}
    return list(matches)


def get_milb_match_stats(event_id: str, player_name: str = "") -> dict | None:
    if not event_id:
        return None
    if player_name:
        k = _stats_key(event_id, player_name)
        if k in MILB_MATCH_STATS_LOOKUP:
            return dict(MILB_MATCH_STATS_LOOKUP[k])
    val = MILB_MATCH_STATS_LOOKUP.get(str(event_id))
    return dict(val) if val else None
