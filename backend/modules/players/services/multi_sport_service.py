"""
Universal Multi-Sport Schedule & Live Service
- Table Tennis: WTT Official API + Flashscore backup
- Multi-Sport Engine: Flashscore 27+ international sports (Badminton, Volleyball, Tennis, Handball, Futsal, etc.)
- Dynamic resolution across clubs & national teams
"""

import concurrent.futures
import datetime
import hashlib
import html as html_lib
import json
import os
import re
import threading
import unicodedata
import httpx
from backend.modules.players.services.sports_service import extract_round_stage_tag

WTT_PROD_BASE = "https://wtt-website-api-prod-3-frontdoor-bddnb2haduafdze9.a01.azurefd.net/api/"
WTT_LIVE_BASE = "https://wtt-website-api-vm-frontdoor-hhaec5epbhdyfugz.a01.azurefd.net/liveeventsapi/api/"
WTT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Origin": "https://www.worldtabletennis.com",
    "Referer": "https://www.worldtabletennis.com/",
}
FS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

_DIR = os.path.dirname(__file__)
WTT_PLAYERS_CACHE_FILE = os.path.join(_DIR, "wtt_players_cache.json")
WTT_EVENTS_CACHE_FILE = os.path.join(_DIR, "wtt_events_cache.json")
FS_DAY_CACHE_FILE = os.path.join(_DIR, "flashscore_day_cache.json")

WTT_PLAYERS_CACHE = {}   # norm_player_name -> {"ittfid": str, "wtt_name": str, "ts": float}
WTT_EVENTS_CACHE = {}    # str(event_id) -> {"ts": float, "end_date": str, "cards": list}
FS_DAY_CACHE = {}        # f"{sport_slug}||{date_str}" -> {"ts": float, "date_str": str, "matches": list}
FS_DETAIL_CACHE = {}     # match_id -> {"sets": str}
WTT_MATCH_STATS_LOOKUP = {}  # event_id -> {"stats_text": str, "tags": list, "has_played": bool, "match_result": str}

_LOCK = threading.Lock()
_IN_FLIGHT_LOCKS = {}


def _get_resource_lock(key: str) -> threading.Lock:
    with _LOCK:
        lk = _IN_FLIGHT_LOCKS.get(key)
        if lk is None:
            lk = threading.Lock()
            _IN_FLIGHT_LOCKS[key] = lk
        return lk


def _load_json_cache(path: str) -> dict:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            pass
    return {}


def _save_json_cache(path: str, data: dict):
    lk = _get_resource_lock(f"save::{path}")
    if not lk.acquire(blocking=False):
        return
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass
    finally:
        lk.release()


WTT_PLAYERS_CACHE = _load_json_cache(WTT_PLAYERS_CACHE_FILE)
WTT_EVENTS_CACHE = _load_json_cache(WTT_EVENTS_CACHE_FILE)
FS_DAY_CACHE = _load_json_cache(FS_DAY_CACHE_FILE)


def _strip_accents(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFD", str(s))
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _norm_tokens(s: str) -> list:
    clean = re.sub(r"[^a-z0-9\s]", " ", _strip_accents(s).lower())
    return [t for t in clean.split() if t]


def _country_codes_for(country_name: str) -> set:
    c = _strip_accents(country_name or "").lower()
    if "nhat" in c or "japan" in c:
        return {"jpn", "jp"}
    if "han" in c or "korea" in c:
        return {"kor", "kr"}
    if "trung" in c or "china" in c:
        return {"chn", "cn"}
    if "dai loan" in c or "taipei" in c or "taiwan" in c:
        return {"tpe", "tw"}
    return set()


def _format_wtt_person_name(raw_name: str) -> str:
    """Convert WTT format 'HARIMOTO Miwa' or doubles 'WANG Manyu/KUAI Man' into readable English order."""
    if not raw_name:
        return ""
    raw_str = str(raw_name).strip()
    if "/" in raw_str:
        return " / ".join(_format_wtt_person_name(part) for part in raw_str.split("/") if part.strip())
    parts = raw_str.split()
    if len(parts) >= 2 and parts[0].isupper() and not parts[-1].isupper():
        fam = parts[0].capitalize()
        given = " ".join(parts[1:])
        return f"{given} {fam}".strip()
    return " ".join(parts)


def _wtt_round_label(doc_code: str, sub_desc: str = "") -> str:
    dc = (doc_code or "").upper()
    sd = (sub_desc or "").lower()
    if "FNL-" in dc or "final -" in sd or sd.endswith("- final"):
        return "Chung kết"
    if "SFNL" in dc or "semifinal" in sd:
        return "Bán kết"
    if "QFNL" in dc or "quarterfinal" in sd:
        return "Tứ kết"
    if "8FNL" in dc or "round of 16" in sd:
        return "Vòng 1/8"
    if "R32" in dc or "round of 32" in sd:
        return "Vòng 1/16"
    if "R64" in dc or "round of 64" in sd:
        return "Vòng 1/32"
    if "RND" in dc or "group" in sd or "qual" in sd:
        return "Vòng bảng / Vòng loại"
    return ""


def _parse_wtt_scores(raw_scores: str) -> list:
    if not raw_scores:
        return []
    out = []
    for part in str(raw_scores).split(","):
        p = part.strip()
        if p.isdigit():
            out.append(int(p))
        else:
            out.append(0)
    return out


def _resolve_wtt_player_id(player_name: str) -> dict | None:
    if not player_name:
        return None
    cache_k = " ".join(_norm_tokens(player_name))
    cached = WTT_PLAYERS_CACHE.get(cache_k)
    if cached and cached.get("ittfid"):
        return cached

    tokens = _norm_tokens(player_name)
    if not tokens:
        return None
    compact_target = "".join(tokens)

    lk = _get_resource_lock(f"wtt_player::{cache_k}")
    with lk:
        cached = WTT_PLAYERS_CACHE.get(cache_k)
        if cached and cached.get("ittfid"):
            return cached

        search_terms = list(dict.fromkeys([tokens[-1], tokens[0], player_name.strip()]))
        try:
            with httpx.Client(timeout=8.0, headers=WTT_HEADERS) as client:
                for term in search_terms:
                    if len(term) < 2:
                        continue
                    resp = client.post(
                        WTT_PROD_BASE + "cms/GetPlayersListByFilters/1/25",
                        json={"searchText": term},
                    )
                    if resp.status_code != 200:
                        continue
                    rows = resp.json()
                    if not isinstance(rows, list):
                        continue
                    for row in rows:
                        fn = row.get("fullName") or ""
                        fn_tokens = _norm_tokens(fn)
                        fn_compact = "".join(fn_tokens)
                        if not fn_tokens:
                            continue
                        is_match = (
                            fn_compact == compact_target
                            or set(tokens) == set(fn_tokens)
                            or (
                                len(tokens) >= 2
                                and tokens[0] in fn_tokens
                                and "".join(tokens[1:]) in fn_compact
                            )
                            or (
                                len(tokens) >= 2
                                and tokens[-1] in fn_tokens
                                and "".join(tokens[:-1]) in fn_compact
                            )
                        )
                        if is_match and row.get("ittfid"):
                            entry = {
                                "ittfid": str(row["ittfid"]),
                                "wtt_name": fn,
                                "ts": datetime.datetime.now().timestamp(),
                            }
                            WTT_PLAYERS_CACHE[cache_k] = entry
                            _save_json_cache(WTT_PLAYERS_CACHE_FILE, WTT_PLAYERS_CACHE)
                            return entry
        except Exception:
            pass
    return None


def _fetch_wtt_player_events(ittfid: str, from_date: str, to_date: str) -> list:
    if not ittfid:
        return []
    try:
        url = f"{WTT_PROD_BASE}cms/player_upcoming_events/{ittfid}?from_date={from_date}&to_date={to_date}"
        with httpx.Client(timeout=10.0, headers=WTT_HEADERS) as client:
            r = client.get(url)
            if r.status_code == 200:
                data = r.json()
                return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


def _parse_wtt_card_compact(row: dict, event_id: str, event_name: str, category: str) -> dict | None:
    mc = row.get("match_card")
    if isinstance(mc, str):
        try:
            mc = json.loads(mc)
        except Exception:
            mc = None
    if not isinstance(mc, dict):
        return None
    comps = mc.get("competitiors") or mc.get("competitors") or []
    if len(comps) < 2:
        return None

    clean_comps = []
    for c in comps:
        p_ids = [str(c.get("competitiorId") or "")]
        p_names = [str(c.get("competitiorName") or "")]
        for pl in c.get("players") or []:
            pid = str(pl.get("playerId") or "")
            if pid and pid not in p_ids:
                p_ids.append(pid)
            pn = str(pl.get("playerName") or "")
            if pn and pn not in p_names:
                p_names.append(pn)
        clean_comps.append({
            "type": c.get("competitorType") or "",
            "id": str(c.get("competitiorId") or ""),
            "name": str(c.get("competitiorName") or ""),
            "org": str(c.get("competitiorOrg") or ""),
            "player_ids": [x for x in p_ids if x],
            "player_names": [x for x in p_names if x],
            "scores": str(c.get("scores") or ""),
        })

    return {
        "event_id": str(event_id),
        "event_name": event_name,
        "category": category,
        "doc_code": str(row.get("documentCode") or mc.get("documentCode") or ""),
        "sub_event": str(mc.get("subEventName") or row.get("subEventType") or ""),
        "sub_desc": str(mc.get("subEventDescription") or ""),
        "start_local": str(row.get("startDateLocal") or ""),
        "full_results": str(row.get("fullResults") or ""),
        "comps": clean_comps,
    }


def _get_wtt_event_cards(event_id: int, event_name: str, category: str, end_date_str: str, include_deep_history: bool = False) -> list:
    eid_str = str(event_id)
    now_ts = datetime.datetime.now().timestamp()
    today_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    is_old_finished = bool(end_date_str and end_date_str < (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=3)).strftime("%Y-%m-%d"))
    ttl = 14 * 86400 if is_old_finished else 1800

    cached = WTT_EVENTS_CACHE.get(eid_str)
    if cached and (now_ts - cached.get("ts", 0) < ttl):
        # If previously skipped 500-fallback in Phase 1 and now in Phase 2, fetch deep
        if not (include_deep_history and cached.get("needs_deep")):
            return cached.get("cards", [])

    lk = _get_resource_lock(f"wtt_event::{eid_str}")
    with lk:
        cached = WTT_EVENTS_CACHE.get(eid_str)
        if cached and (now_ts - cached.get("ts", 0) < ttl):
            if not (include_deep_history and cached.get("needs_deep")):
                return cached.get("cards", [])

        cards = []
        needs_deep = False
        try:
            with httpx.Client(timeout=12.0, headers=WTT_HEADERS) as client:
                r = client.get(f"{WTT_LIVE_BASE}cms/GetOfficialResult?EventId={eid_str}&include_match_card=true")
                if r.status_code == 200:
                    rows = r.json()
                    if isinstance(rows, list):
                        for row in rows:
                            parsed = _parse_wtt_card_compact(row, eid_str, event_name, category)
                            if parsed:
                                cards.append(parsed)
                elif r.status_code == 500:
                    if include_deep_history:
                        # Older Smash/Champions events return 500 on full payload; load singles cards in parallel
                        r_docs = client.get(f"{WTT_LIVE_BASE}cms/GetOfficialResult?EventId={eid_str}")
                        if r_docs.status_code == 200:
                            docs = [
                                d for d in (r_docs.json() or [])
                                if d.get("documentCode") and ("SINGLES" in d["documentCode"] or "DOUBLES" in d["documentCode"])
                            ]

                            def _fetch_one(d):
                                dc = d["documentCode"]
                                try:
                                    rc = client.get(f"{WTT_LIVE_BASE}cms/GetMatchCardDetails/{eid_str}/{dc}", timeout=6.0)
                                    if rc.status_code == 200:
                                        mc = rc.json()
                                        synth = {
                                            "documentCode": dc,
                                            "subEventType": d.get("subEventType"),
                                            "fullResults": d.get("fullResults"),
                                            "startDateLocal": d.get("startDateLocal"),
                                            "match_card": mc,
                                        }
                                        return _parse_wtt_card_compact(synth, eid_str, event_name, category)
                                except Exception:
                                    pass
                                return None

                            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
                                for parsed in ex.map(_fetch_one, docs):
                                    if parsed:
                                        cards.append(parsed)
                    else:
                        needs_deep = True

                # Also inspect live/upcoming schedule if event ends >= today - 1 day
                if not end_date_str or end_date_str >= (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)).strftime("%Y-%m-%d"):
                    rs = client.get(f"{WTT_LIVE_BASE}cms/GetEventSchedule/{eid_str}", timeout=8.0)
                    if rs.status_code == 200:
                        sdata = rs.json()
                        existing_dcs = {c["doc_code"] for c in cards}
                        if isinstance(sdata, list) and sdata:
                            units = sdata[0].get("Competition", {}).get("Unit", []) or []
                            for u in units:
                                dc = str(u.get("Code") or "")
                                if not dc or dc in existing_dcs:
                                    continue
                                starts = u.get("StartList", {}).get("Start", []) or []
                                if len(starts) < 2:
                                    continue
                                c_list = []
                                for st in starts:
                                    comp_obj = st.get("Competitor") or {}
                                    c_id = str(comp_obj.get("Code") or "")
                                    c_name = str((comp_obj.get("Description") or {}).get("TeamName") or "")
                                    c_org = str(comp_obj.get("Organisation") or "")
                                    if not c_id and not c_name:
                                        continue
                                    p_ids = [c_id] if c_id else []
                                    p_names = [c_name] if c_name else []
                                    for ath in comp_obj.get("Composition", {}).get("Athlete", []) or []:
                                        apid = str(ath.get("Code") or "")
                                        if apid and apid not in p_ids:
                                            p_ids.append(apid)
                                    c_list.append({
                                        "type": str(st.get("StartOrder") or ""),
                                        "id": c_id,
                                        "name": c_name,
                                        "org": c_org,
                                        "player_ids": p_ids,
                                        "player_names": p_names,
                                        "scores": "",
                                    })
                                if len(c_list) >= 2:
                                    item_desc = ""
                                    for d_obj in u.get("ItemDescription") or []:
                                        if d_obj.get("Value"):
                                            item_desc = d_obj["Value"]
                                            break
                                    cards.append({
                                        "event_id": eid_str,
                                        "event_name": event_name,
                                        "category": category,
                                        "doc_code": dc,
                                        "sub_event": str(u.get("SubEvent") or ""),
                                        "sub_desc": item_desc,
                                        "start_local": str(u.get("StartDate") or ""),
                                        "full_results": "SCHEDULED" if u.get("ScheduleStatus") == "Scheduled" else str(u.get("ScheduleStatus") or ""),
                                        "comps": c_list,
                                    })
        except Exception:
            pass

        WTT_EVENTS_CACHE[eid_str] = {
            "ts": now_ts,
            "end_date": end_date_str,
            "needs_deep": needs_deep,
            "cards": cards,
        }
        _save_json_cache(WTT_EVENTS_CACHE_FILE, WTT_EVENTS_CACHE)
        return cards


def _clean_wtt_event_title(event_name: str, category: str) -> str:
    ev = re.sub(r"\s+Presented by.*$", "", str(event_name or ""), flags=re.I).strip()
    ev = re.sub(r"\s*\([^)]*\)$", "", ev).strip()
    return ev or category or "WTT Series"


def _fetch_wtt_matches_for_player(player_name: str, include_deep_history: bool = False) -> list:
    p_info = _resolve_wtt_player_id(player_name)
    if not p_info:
        return []
    ittfid = str(p_info["ittfid"])

    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    days_b = 180 if include_deep_history else 45
    from_str = (now_utc - datetime.timedelta(days=days_b)).strftime("%Y-%m-%d")
    to_str = (now_utc + datetime.timedelta(days=45)).strftime("%Y-%m-%d")

    events = _fetch_wtt_player_events(ittfid, from_str, to_str)
    if not events:
        return []

    # Ignore internal "SIM / SIMULATION" duplicate events
    real_events = [
        ev for ev in events
        if not re.match(r"^\s*SIM(?:ULATION)?\b", str(ev.get("EventName") or ""), flags=re.I)
    ]

    matches = []
    seen_ev = set()

    for ev in real_events:
        eid = ev.get("EventId")
        if not eid:
            continue
        ev_name = str(ev.get("EventName") or "")
        cat = str(ev.get("Category") or "WTT")
        end_d = str(ev.get("EndDate") or "")[:10]

        cards = _get_wtt_event_cards(eid, ev_name, cat, end_d, include_deep_history=include_deep_history)
        clean_comp = _clean_wtt_event_title(ev_name, cat)

        for card in cards:
            comps = card.get("comps") or []
            my_c = None
            opp_c = None
            for c in comps:
                if ittfid in (c.get("player_ids") or []) or ittfid == str(c.get("id")):
                    my_c = c
                else:
                    opp_c = c
            if not my_c or not opp_c:
                continue

            dc = card.get("doc_code") or ""
            dc_compact = re.sub(r"-+", "-", dc).strip("-")
            ev_key = f"wtt_{eid}_{dc_compact}"[:48]
            if ev_key in seen_ev:
                continue
            seen_ev.add(ev_key)

            raw_dt = str(card.get("start_local") or "")
            if not raw_dt:
                continue
            try:
                dt_local = datetime.datetime.strptime(raw_dt[:19], "%Y-%m-%dT%H:%M:%S")
            except Exception:
                continue

            # Approximate UTC cleanly (Flashscore/European venues ~UTC+1, Asian events ~UTC+8; exact enough for calendar alignment)
            ev_low = ev_name.lower()
            tz_offset_h = 1 if any(k in ev_low for k in ["frankfurt", "montpellier", "düsseldorf", "gdansk", "linz", "panagyurishte", "zagreb", "ljubljana", "london", "sweden", "istanbul", "vila nova"]) else 8
            dt_utc = dt_local - datetime.timedelta(hours=tz_offset_h)
            dt_vn = dt_utc + datetime.timedelta(hours=7)
            diff = (dt_utc - now_utc).total_seconds() / 86400.0

            my_scores = _parse_wtt_scores(my_c.get("scores", ""))
            opp_scores = _parse_wtt_scores(opp_c.get("scores", ""))

            pairs = []
            my_sets = 0
            opp_sets = 0
            for s1, s2 in zip(my_scores, opp_scores):
                if s1 == 0 and s2 == 0:
                    continue
                pairs.append(f"{s1}-{s2}")
                if s1 > s2:
                    my_sets += 1
                elif s2 > s1:
                    opp_sets += 1

            is_official = "OFFICIAL" in str(card.get("full_results") or "").upper()
            has_score = bool(pairs)
            m_state = "post" if (is_official or has_score or diff < -0.15) else "pre"

            opp_display = _format_wtt_person_name(opp_c.get("name") or "") or "Đối thủ"
            opp_org = opp_c.get("org") or ""
            if opp_org and f"({opp_org})" not in opp_display:
                opp_label = f"{opp_display} ({opp_org})"
            else:
                opp_label = opp_display

            sub_ev = str(card.get("sub_event") or "")
            is_doubles = "doubles" in sub_ev.lower() or "DOUBLES" in dc.upper()
            round_lbl = extract_round_stage_tag(_wtt_round_label(dc, card.get("sub_desc", "")), card.get("sub_desc", "")) or _wtt_round_label(dc, card.get("sub_desc", ""))

            tags = []
            match_res = None
            stats_text = ""

            calc_rating = None
            if m_state == "post" and has_score:
                win_str = "Thắng" if my_sets > opp_sets else ("Thua" if opp_sets > my_sets else "Hoàn thành")
                game_str = ", ".join(pairs)
                my_display = (_format_wtt_person_name(my_c.get("name") or "") or player_name) if is_doubles else player_name
                match_res = f"{my_display} {my_sets} - {opp_sets} {opp_display} (FT) • {game_str}"
                stats_text = f"{win_str} {my_sets}-{opp_sets} ({game_str})"
                tags.append(win_str)
                # Điểm số hiệu suất thi đấu thực tế theo diễn biến trận đấu bóng bàn (thang điểm 10)
                if my_sets > opp_sets:
                    if opp_sets == 0:
                        calc_rating = 9.0  # Thắng trắng áp đảo 3-0 hoặc 4-0
                    elif opp_sets == 1:
                        calc_rating = 8.4  # Thắng cách biệt 3-1 hoặc 4-1
                    else:
                        calc_rating = 7.9  # Thắng kịch tính set quyết định 3-2 hoặc 4-3
                elif opp_sets > my_sets:
                    if my_sets >= 2:
                        calc_rating = 6.6  # Thua sát nút
                    elif my_sets == 1:
                        calc_rating = 6.2
                    else:
                        calc_rating = 5.8  # Thua trắng
            elif m_state == "post":
                match_res = "Đã kết thúc (FT)"

            if round_lbl and round_lbl not in tags:
                tags.append(round_lbl)

            WTT_MATCH_STATS_LOOKUP[ev_key] = {
                "has_played": (m_state == "post" and has_score),
                "stats_text": stats_text,
                "tags": tags,
                "rating": calc_rating,
                "match_result": match_res,
            }

            matches.append({
                "match_name": f"vs {opp_label}",
                "raw_match_name": f"{player_name} vs {opp_label}",
                "match_date_utc": dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "date_vn": dt_vn.strftime("%d/%m %H:%M"),
                "date_full_vn": dt_vn.strftime("%d/%m/%Y %H:%M"),
                "date_only_vn": dt_vn.strftime("%Y-%m-%d"),
                "time_only_vn": dt_vn.strftime("%H:%M"),
                "competition": clean_comp,
                "event_id": ev_key,
                "match_state": m_state,
                "match_result": match_res,
                "status_detail": match_res or dt_vn.strftime("%d/%m • %H:%M"),
                "has_played": (m_state == "post" and has_score),
                "diff_days": diff,
                "player_team": clean_comp,
                "player_stats": stats_text,
                "tags": tags,
                "rating": calc_rating,
            })

    return matches


# ==============================================================================
# FLASHSCORE.MOBI REAL SCRAPER (BADMINTON, VOLLEYBALL & TABLE TENNIS BACKUP)
# ==============================================================================

def _parse_flashscore_day_html(html_text: str, day_date: datetime.date) -> list:
    idx = html_text.find('<div id="score-data">')
    if idx == -1:
        return []
    end_idx = html_text.find('<p class="advert', idx)
    chunk = html_text[idx : end_idx if end_idx != -1 else idx + 45000]

    matches = []
    curr_comp = ""
    token_re = re.compile(
        r'<h4>(.*?)</h4>|<span>(\d\d:\d\d)</span>\s*(.*?)\s*<a\s+href="(/match/([a-zA-Z0-9]+)/[^"]*)"[^>]*class="([^"]*)"[^>]*>(.*?)</a>',
        re.S,
    )
    for m in token_re.finditer(chunk):
        if m.group(1) is not None:
            curr_comp = html_lib.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
        else:
            hhmm = m.group(2)
            teams_raw = html_lib.unescape(re.sub(r"<[^>]+>", "", m.group(3))).strip()
            href = m.group(4)
            mid = m.group(5)
            cls = (m.group(6) or "").lower()
            score_raw = html_lib.unescape(re.sub(r"<[^>]+>", "", m.group(7))).strip()
            if " - " not in teams_raw:
                continue
            parts = teams_raw.split(" - ", 1)
            side1 = parts[0].strip()
            side2 = parts[1].strip()
            matches.append({
                "comp": curr_comp,
                "time": hhmm,
                "date_cet": day_date.strftime("%Y-%m-%d"),
                "side1": side1,
                "side2": side2,
                "mid": mid,
                "href": href,
                "cls": cls,
                "score": "" if ("-" not in score_raw or re.fullmatch(r"[-\s\xa0]+", score_raw)) else score_raw,
            })
    return matches


def _fetch_flashscore_days(sport_slug: str, day_offsets: list) -> list:
    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    today_cet = (now_utc + datetime.timedelta(hours=1)).date()
    now_ts = datetime.datetime.now().timestamp()

    missing = []
    collected = []
    for d in day_offsets:
        day_date = today_cet + datetime.timedelta(days=d)
        d_str = day_date.strftime("%Y-%m-%d")
        ck = f"{sport_slug}||{d_str}"
        ttl = 7 * 86400 if d <= -2 else (600 if d <= 1 else 7200)
        cached = FS_DAY_CACHE.get(ck)
        if cached and (now_ts - cached.get("ts", 0) < ttl):
            for item in cached.get("matches", []):
                collected.append((d, item))
        else:
            missing.append((d, d_str, ck, day_date))

    if missing:
        lk = _get_resource_lock(f"fs_batch::{sport_slug}")
        with lk:
            still_missing = []
            for d, d_str, ck, day_date in missing:
                ttl = 7 * 86400 if d <= -2 else (600 if d <= 1 else 7200)
                cached = FS_DAY_CACHE.get(ck)
                if cached and (now_ts - cached.get("ts", 0) < ttl):
                    for item in cached.get("matches", []):
                        collected.append((d, item))
                else:
                    still_missing.append((d, d_str, ck, day_date))

            if still_missing:
                def _fetch_one(args):
                    d, d_str, ck, day_date = args
                    try:
                        fs_url = f"https://www.flashscore.mobi/{sport_slug}/?d={d}" if sport_slug else f"https://www.flashscore.mobi/?d={d}"
                        with httpx.Client(timeout=8.0, headers=FS_HEADERS) as client:
                            r = client.get(fs_url)
                            if r.status_code == 200:
                                parsed = _parse_flashscore_day_html(r.text, day_date)
                                return d, d_str, ck, parsed
                    except Exception:
                        pass
                    return d, d_str, ck, None

                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
                    for d, d_str, ck, parsed in ex.map(_fetch_one, still_missing):
                        if parsed is not None:
                            FS_DAY_CACHE[ck] = {"ts": now_ts, "date_str": d_str, "matches": parsed}
                            for item in parsed:
                                collected.append((d, item))
                _save_json_cache(FS_DAY_CACHE_FILE, FS_DAY_CACHE)

    return collected


def _fetch_fs_match_sets(href: str, mid: str) -> str:
    if mid in FS_DETAIL_CACHE:
        return FS_DETAIL_CACHE[mid].get("sets", "")
    try:
        with httpx.Client(timeout=6.0, headers=FS_HEADERS) as client:
            r = client.get(f"https://www.flashscore.mobi{href}")
            if r.status_code == 200:
                m = re.search(r'<p[^>]*class="score"[^>]*>.*?\(([\d,\s-]+)\)', r.text, re.S)
                if not m:
                    m = re.search(r"\b\d+-\d+\s*\(([\d\s,-]+)\)", re.sub(r"<[^>]+>", " ", r.text))
                sets_str = re.sub(r"\s+", "", m.group(1)).replace(",", ", ") if m else ""
                FS_DETAIL_CACHE[mid] = {"sets": sets_str}
                return sets_str
    except Exception:
        pass
    FS_DETAIL_CACHE[mid] = {"sets": ""}
    return ""


def _match_fs_athlete_entrant(player_name: str, country_name: str, entrant_text: str) -> bool:
    """Strictly match Flashscore abbreviated names ('An S. Y. (Kor)', 'Okimoto Y. (Jpn)', 'Joo Cheonhui (Kor)') against player."""
    if not player_name or not entrant_text:
        return False
    # Check country mismatch if entrant includes country tag like (Chn), (Kor), (Jpn)
    expected_codes = _country_codes_for(country_name)
    cc_m = re.search(r"\(([A-Za-z]{2,3})\)", entrant_text)
    if cc_m and expected_codes:
        if cc_m.group(1).lower() not in expected_codes:
            return False

    clean_ent = re.sub(r"\([^)]*\)", "", entrant_text).strip()
    ent_tokens = _norm_tokens(clean_ent)
    p_tokens = _norm_tokens(player_name)
    if len(p_tokens) < 2 or not ent_tokens:
        return False

    # Case 1: Full surname + full given name ('joo cheonhui' vs 'joo cheon hui')
    if "".join(ent_tokens) == "".join(p_tokens) or set(p_tokens) == set(ent_tokens):
        return True

    # Case 2: Abbreviated form 'Surname I.' or 'Surname I. J.' (e.g. 'An S. Y.', 'Kim W. H.', 'Harimoto M.', 'Watanabe Y.')
    fam = ent_tokens[0]
    initials = [t for t in ent_tokens[1:] if len(t) == 1]
    full_extra = [t for t in ent_tokens[1:] if len(t) > 1]

    # Try Korean/Asian order (p_tokens[0] is family, p_tokens[1:] are given) AND Western order (p_tokens[-1] is family, p_tokens[:-1] are given)
    order_variants = [
        (p_tokens[0], p_tokens[1:]),
        (p_tokens[-1], p_tokens[:-1]),
    ]
    for p_fam, p_giv in order_variants:
        if fam != p_fam:
            continue
        p_giv_compact = "".join(p_giv)
        p_giv_initials = [g[0] for g in p_giv if g]
        # Full trailing tokens check (rare like 'Ng Ka L. A.')
        if full_extra and not all(fe in p_giv for fe in full_extra):
            continue
        if not initials:
            continue
        if len(initials) == 1:
            # Allow 1 initial when athlete has single given name ('Harimoto M.') OR Flashscore collapsed hyphenated Korean name ('Lim J.')
            if p_giv_initials and initials[0] == p_giv_initials[0]:
                # Only allow collapsed 1-initial if Flashscore actually gave 1 initial (not wrong 1st of 2!)
                if len(p_giv_initials) == 1 or entrant_text.count(".") == 1:
                    return True
        else:
            # Multi-initial (e.g. 'Kim W. H.', 'An S. Y.', 'Lee S. H.', 'Lee Y. L.') MUST match exact initial sequence!
            if initials == p_giv_initials:
                return True
            # Or 2-part non-hyphenated given name split into 2 initials? (Usually no; keep strict!)
    return False


def _match_fs_athlete_side(player_name: str, country_name: str, side_text: str) -> bool:
    for entrant in str(side_text).split("/"):
        if _match_fs_athlete_entrant(player_name, country_name, entrant.strip()):
            return True
    return False


def _match_fs_club(team_name: str, club_side: str) -> bool:
    if not team_name or not club_side:
        return False
    low_side = _strip_accents(club_side).lower().strip()
    low_t = _strip_accents(team_name).lower().strip()
    if low_t in ("tu do", "free agent", "unknown", "khong ro", "chua ro clb") or low_t.startswith("doi tuyen "):
        return False
    # Reject reserve / youth / wrong-gender squads unless explicitly in team_name
    if re.search(r"\b(2|ii|iii|u19|u20|u21|u23|w|women)\b", low_side) and not re.search(r"\b(2|ii|w|women|u19|u20|u21|u23)\b", low_t):
        return False

    aliases = [low_t]
    if "ziraat" in low_t:
        aliases.extend(["ziraat bankasi", "ziraat bankkart", "ziraat"])
    elif "suntory" in low_t:
        aliases.append("suntory sunbirds")
    else:
        core = re.sub(r"\b(fc|hc|sc|vc|bc|club|team|volleyball|handball|hockey|basketball|baseball|rugby|bankkart)\b", "", low_t).strip()
        if len(core) >= 4:
            aliases.append(core)

    for al in aliases:
        if al == low_side or (len(al) >= 5 and re.search(rf"\b{re.escape(al)}\b", low_side)):
            return True
    return False


def _match_fs_nt_side(country_name: str, tier: str, gender: str, side_text: str) -> bool:
    """Strictly match Flashscore National / Youth Team names (e.g. 'Japan', 'South Korea U23', 'Japan U17 W')."""
    if not country_name or not side_text:
        return False
    low_c = _strip_accents(country_name).lower().strip()
    low_s = _strip_accents(side_text).lower().strip()

    if "nhat" in low_c or "japan" in low_c:
        patterns = [r"\bjapan\b"]
    elif "han" in low_c or "korea" in low_c:
        if "north" in low_s or "dpr" in low_s:
            return False
        patterns = [r"\bsouth korea\b", r"\bkorea republic\b", r"\bkorea rep\.?\b"]
    elif "trung" in low_c or "china" in low_c:
        patterns = [r"\bchina\b"]
    elif "viet" in low_c:
        patterns = [r"\bvietnam\b", r"\bviet nam\b"]
    elif "my" == low_c or "usa" in low_c or "united states" in low_c:
        patterns = [r"\busa\b", r"\bunited states\b"]
    elif "dai loan" in low_c or "taipei" in low_c or "taiwan" in low_c:
        patterns = [r"\bchinese taipei\b", r"\btaiwan\b"]
    else:
        patterns = [rf"\b{re.escape(low_c)}\b"]

    matched_pat = None
    for pat in patterns:
        if re.search(pat, low_s):
            matched_pat = pat
            break
    if not matched_pat:
        return False

    # Ensure no non-national-team club words remain after removing the country name + standard suffixes
    rest = re.sub(matched_pat, " ", low_s).strip()
    rest_tokens = [t for t in re.split(r"[^a-z0-9]+", rest) if t]
    allowed_suffixes = {"u23", "u21", "u20", "u19", "u18", "u17", "u16", "u15", "w", "women", "men", "m", "f", "youth", "jr"}
    if any(t not in allowed_suffixes for t in rest_tokens):
        return False

    has_w = any(t in {"w", "women", "f"} for t in rest_tokens)
    g_low = (gender or "Men").lower()
    if g_low == "women" and not has_w:
        return False
    if g_low == "men" and has_w:
        return False

    u_tokens = [t for t in rest_tokens if re.fullmatch(r"u\d{2}", t) or t in {"youth", "jr"}]
    t_up = (tier or "Senior").upper().strip()
    if t_up == "SENIOR":
        return len(u_tokens) == 0
    if t_up == "YOUTH":
        return len(u_tokens) > 0
    if t_up in [x.upper() for x in u_tokens]:
        return True
    # Olympic/AFC U20 & U23 friendly cycles (Japan/Korea U19 <-> U20, U21 <-> U23)
    if t_up == "U23" and "u21" in u_tokens:
        return True
    if t_up == "U20" and "u19" in u_tokens:
        return True
    return False


def _clean_fs_comp(raw_comp: str, sport_slug: str) -> str:
    if not raw_comp:
        return "BWF World Tour" if sport_slug == "badminton" else "Giải đấu"
    c = raw_comp
    c = re.sub(r"^(?:BWF\s+WORLD\s+TOUR\s*-\s*(?:MEN|WOMEN|MIXED)(?:\s+DOUBLES)?\s*:\s*)", "", c, flags=re.I)
    c = re.sub(r"^(?:OTHERS\s*-\s*(?:MEN|WOMEN|MIXED)(?:\s+DOUBLES)?\s*:\s*)", "", c, flags=re.I)
    c = re.sub(r"^[A-Z][A-Z\s\.\-/]{1,22}:\s*", "", c)
    c = re.sub(r"\s*\([^)]*\)$", "", c).strip()
    return c or raw_comp


def _fetch_flashscore_matches(
    player_name: str,
    team_name: str,
    sport_slug: str,
    country_name: str = None,
    is_team_mode: bool = False,
    nt_match_cfg: dict = None,
) -> list:
    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    day_rows = _fetch_flashscore_days(sport_slug, list(range(-7, 8)))

    matched_raw = []
    seen_mid = set()
    for d_off, row in day_rows:
        if row["mid"] in seen_mid:
            continue
        if nt_match_cfg:
            is_s1 = _match_fs_nt_side(nt_match_cfg["country"], nt_match_cfg["tier"], nt_match_cfg["gender"], row["side1"])
            is_s2 = _match_fs_nt_side(nt_match_cfg["country"], nt_match_cfg["tier"], nt_match_cfg["gender"], row["side2"])
        elif is_team_mode:
            is_s1 = _match_fs_club(team_name, row["side1"])
            is_s2 = _match_fs_club(team_name, row["side2"])
        else:
            is_s1 = _match_fs_athlete_side(player_name, country_name, row["side1"])
            is_s2 = _match_fs_athlete_side(player_name, country_name, row["side2"])
        if not (is_s1 or is_s2):
            continue
        seen_mid.add(row["mid"])
        matched_raw.append((d_off, row, is_s1))

    # Fetch set details in parallel for finished matches (capped & cached)
    fin_items = [r for _, r, _ in matched_raw if "fin" in r["cls"] or r["score"]]
    if fin_items:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, len(fin_items))) as ex:
            list(ex.map(lambda item: _fetch_fs_match_sets(item["href"], item["mid"]), fin_items))

    results = []
    for _, row, is_s1 in matched_raw:
        try:
            dt_cet = datetime.datetime.strptime(f"{row['date_cet']} {row['time']}", "%Y-%m-%d %H:%M")
        except Exception:
            continue
        dt_utc = dt_cet - datetime.timedelta(hours=1)
        dt_vn = dt_utc + datetime.timedelta(hours=7)
        diff = (dt_utc - now_utc).total_seconds() / 86400.0

        opp_side = row["side2"] if is_s1 else row["side1"]
        our_side = row["side1"] if is_s1 else row["side2"]
        cls = row["cls"]
        is_post = ("fin" in cls) or (bool(row["score"]) and "live" not in cls and diff < -0.08)
        is_live = "live" in cls
        m_state = "post" if is_post else ("in" if is_live else ("post" if diff < -0.15 else "pre"))

        sets_str = FS_DETAIL_CACHE.get(row["mid"], {}).get("sets", "")
        sc = row["score"]
        match_res = None
        stats_text = ""
        tags = []

        is_walkover = bool(re.search(r'\b(wo|w/o|walkover|ret|retired)\b', f"{sc} {cls}", re.I))
        calc_rating = None
        if m_state in ("post", "in") and sc:
            set_part = f" • {sets_str}" if sets_str else ""
            state_lbl = "LIVE" if m_state == "in" else "FT"
            match_res = f"{row['side1']} {sc} {row['side2']} ({state_lbl}){set_part}"
            if is_walkover:
                tags.append("Bỏ cuộc / Walkover (WO)")
            else:
                m_sc = re.match(r"(\d+)\s*-\s*(\d+)", sc)
                if m_sc:
                    a, b = int(m_sc.group(1)), int(m_sc.group(2))
                    our_s, opp_s = (a, b) if is_s1 else (b, a)
                    wl = "Thắng" if our_s > opp_s else ("Thua" if opp_s > our_s else "Hòa")
                    if m_state == "post":
                        tags.append(wl)
                        # Điểm số đánh giá hiệu suất thực tế cho Cầu lông, Bóng bàn, Quần vợt, Bóng chuyền
                        if our_s > opp_s:
                            if opp_s == 0:
                                calc_rating = 8.8  # Thắng áp đảo không để thua set nào (2-0, 3-0)
                            elif opp_s == 1 and our_s >= 3:
                                calc_rating = 8.4  # Thắng 3-1
                            else:
                                calc_rating = 8.0  # Thắng set quyết định (2-1, 3-2)
                        elif opp_s > our_s:
                            if our_s >= 1:
                                calc_rating = 6.6  # Thua nhưng giành được set thắng
                            else:
                                calc_rating = 6.0  # Thua trắng
                    stats_text = f"{wl} {our_s}-{opp_s}" + (f" ({sets_str})" if sets_str else "")
        elif m_state == "post":
            match_res = "Đã kết thúc (FT)"

        comp_clean = _clean_fs_comp(row["comp"], sport_slug)
        fs_round_tag = extract_round_stage_tag(row["comp"], comp_clean, date_vn_str=dt_vn.strftime("%Y-%m-%d"))
        if fs_round_tag and fs_round_tag not in tags:
            tags.append(fs_round_tag)

        ev_id = f"fs_{sport_slug}_{row['mid']}"
        has_p = (m_state == "post" and bool(sc) and not is_walkover)
        WTT_MATCH_STATS_LOOKUP[ev_id] = {
            "has_played": has_p,
            "stats_text": stats_text,
            "tags": tags,
            "rating": calc_rating,
            "match_result": match_res,
        }

        prefix = "vs " if is_s1 or not is_team_mode else "@ "
        results.append({
            "match_name": f"{prefix}{opp_side}",
            "raw_match_name": f"{row['side1']} vs {row['side2']}",
            "match_date_utc": dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "date_vn": dt_vn.strftime("%d/%m %H:%M"),
            "date_full_vn": dt_vn.strftime("%d/%m/%Y %H:%M"),
            "date_only_vn": dt_vn.strftime("%Y-%m-%d"),
            "time_only_vn": dt_vn.strftime("%H:%M"),
            "competition": comp_clean,
            "round_tag": fs_round_tag,
            "event_id": ev_id,
            "match_state": m_state,
            "match_result": match_res,
            "status_detail": match_res or dt_vn.strftime("%d/%m • %H:%M"),
            "has_played": has_p,
            "diff_days": diff,
            "player_team": our_side if not is_team_mode else "",
            "player_stats": stats_text,
            "tags": tags,
            "rating": calc_rating,
        })

    results.sort(key=lambda x: str(x.get("match_date_utc") or ""))
    return results


def get_racket_or_volleyball_match_stats(event_id: str) -> dict | None:
    if not event_id:
        return None
    return WTT_MATCH_STATS_LOOKUP.get(str(event_id))


def fetch_flashscore_national_team_schedule(
    sport_name: str,
    country_name: str,
    tier: str = "Senior",
    gender: str = "Men",
) -> list:
    """Dynamically fetch national & youth team schedules from Flashscore for any supported team sport."""
    from backend.core.config import resolve_flashscore_sport_slug
    fs_slug = resolve_flashscore_sport_slug(sport_name)
    if fs_slug is None:
        return []
    return _fetch_flashscore_matches(
        player_name="",
        team_name="",
        sport_slug=fs_slug,
        country_name=country_name,
        is_team_mode=True,
        nt_match_cfg={"country": country_name, "tier": tier or "Senior", "gender": gender or "Men"},
    )


def fetch_racket_or_volleyball_schedule(
    player_name: str,
    team_name: str,
    sport_name: str,
    country_name: str = None,
    gender: str = "Men",
    include_deep_history: bool = False,
) -> list:
    """
    Universal multi-sport schedule fetcher:
    - Table Tennis: WTT Official Public API + Flashscore fallback/supplement
    - Any other sport supported by Flashscore (27 sports dynamically resolved): clubs & individual athletes
    """
    from backend.core.config import resolve_flashscore_sport_slug
    fs_slug = resolve_flashscore_sport_slug(sport_name)
    s_low = _strip_accents(sport_name or "").lower()

    if fs_slug == "table-tennis" or any(k in s_low for k in ["bong ban", "table tennis", "ping pong"]):
        wtt_matches = _fetch_wtt_matches_for_player(player_name, include_deep_history=include_deep_history)
        fs_matches = _fetch_flashscore_matches(player_name, team_name, "table-tennis", country_name=country_name, is_team_mode=False)

        merged = list(wtt_matches)
        wtt_signatures = set()
        for wm in wtt_matches:
            d_vn = wm.get("date_only_vn") or ""
            opp_toks = set(_norm_tokens(wm.get("match_name") or ""))
            wtt_signatures.add((d_vn, frozenset(t for t in opp_toks if len(t) >= 3)))

        for fm in fs_matches:
            fd_vn = fm.get("date_only_vn") or ""
            f_toks = [t for t in _norm_tokens(fm.get("match_name") or "") if len(t) >= 3]
            is_dup = False
            for wd, wset in wtt_signatures:
                try:
                    d_diff = abs((datetime.datetime.strptime(fd_vn, "%Y-%m-%d") - datetime.datetime.strptime(wd, "%Y-%m-%d")).days)
                except Exception:
                    d_diff = 9
                if d_diff <= 1 and any(ft in wset for ft in f_toks):
                    is_dup = True
                    break
            if not is_dup:
                merged.append(fm)

        merged.sort(key=lambda x: str(x.get("match_date_utc") or ""))
        return merged

    if fs_slug is None:
        return []

    individual_fs_slugs = {"badminton", "tennis", "table-tennis", "boxing", "mma", "snooker", "darts"}
    if fs_slug in individual_fs_slugs:
        return _fetch_flashscore_matches(player_name, team_name, fs_slug, country_name=country_name, is_team_mode=False)

    # Team / hybrid sports (volleyball, hockey, handball, basketball, baseball, soccer, rugby, cricket, futsal, water-polo, etc.)
    t_low = _strip_accents(team_name or "").lower().strip()
    has_club = bool(t_low and t_low not in ("tu do", "free agent", "unknown", "khong ro", "chua ro clb") and not t_low.startswith("doi tuyen "))
    if has_club:
        res_club = _fetch_flashscore_matches(player_name, team_name, fs_slug, country_name=country_name, is_team_mode=True)
        if res_club:
            return res_club
    return _fetch_flashscore_matches(player_name, team_name, fs_slug, country_name=country_name, is_team_mode=False)


# Multi-sport aliases
fetch_multi_sport_schedule = fetch_racket_or_volleyball_schedule
get_multi_sport_match_stats = get_racket_or_volleyball_match_stats
