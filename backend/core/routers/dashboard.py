from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
import datetime
import json
import concurrent.futures
import urllib.parse
import re

def get_starting_role_tag(player_name: str, sport_name: str) -> str:
    s_lower = (sport_name or "").lower()
    p_lower = (player_name or "").lower()
    if "bóng đá" in s_lower or "soccer" in s_lower:
        return "Đá chính"
    elif "bóng chày" in s_lower or "baseball" in s_lower:
        if any(pitcher in p_lower for pitcher in ["yamamoto", "sasaki", "imanaga", "darvish", "senga"]):
            return "Ném chính (SP)"
        return "Đội hình xuất phát (Lineup)"
    elif "bóng rổ" in s_lower or "basketball" in s_lower:
        return "Đội hình xuất phát (Starting 5)"
    elif "bóng chuyền" in s_lower or "volleyball" in s_lower:
        return "Đội hình xuất phát (Starting 6)"
    elif any(net in s_lower for net in ["quần vợt", "cầu lông", "bóng bàn", "tennis"]):
        return "Thi đấu đơn"
    return "Xuất phát"



from backend.core.db.session import get_db
from backend.core.db.models import Player, Sport, Nationality, Club, MatchPerformance, PlayerNews, NationalTeam, NationalTeamNews
from backend.core.config import EN_TO_VI_MAP
from backend.modules.players.services.espn_service import (
    fetch_player_upcoming_schedule_30d, fetch_player_career_schedule, fetch_real_schedule,
    fetch_player_match_stats, fetch_match_recap_news, fetch_espn_summary,
    MATCH_STATS_CACHE, get_player_official_injury
)
from backend.modules.players.services.sports_service import format_player_stats_and_tags, get_tournament_tag
from backend.core.services.live_score_service import get_live_scores_map
from backend.modules.national_teams.services.national_teams_service import fetch_national_team_schedule, fetch_national_team_news_feed

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="frontend/templates")

_DASHBOARD_CACHE = {}
_DASHBOARD_CACHE_TTL = 600.0  # 10 minutes (600s) for lightning fast reloads

def unpack_stats(stats_val):
    if not stats_val:
        return None, None
    if isinstance(stats_val, str) and stats_val.strip().startswith("{"):
        try:
            parsed = json.loads(stats_val)
            if isinstance(parsed, dict) and "summary" in parsed:
                return parsed.get("summary"), parsed.get("details")
        except Exception:
            pass
    return stats_val, None

def invalidate_dashboard_cache():
    _DASHBOARD_CACHE.clear()

@router.get("/", response_class=HTMLResponse)
def read_root(request: Request, db: Session = Depends(get_db)):
    all_db_players = db.query(Player).options(joinedload(Player.sport), joinedload(Player.nationality)).all()
    all_db_national_teams = db.query(NationalTeam).options(joinedload(NationalTeam.sport), joinedload(NationalTeam.nationality)).all()
    
    active_sports = {p.sport_name for p in all_db_players if p.sport_name and p.sport_name != "Không rõ"}
    active_sports.update({t.sport_name for t in all_db_national_teams if t.sport_name and t.sport_name != "Không rõ"})
    
    active_countries = {p.country_name for p in all_db_players if p.country_name and p.country_name != "Không rõ"}
    active_countries.update({t.country_name for t in all_db_national_teams if t.country_name and t.country_name != "Không rõ"})

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "sports": sorted(active_sports),
            "countries": sorted(active_countries)
        }
    )

from typing import Optional

@router.get("/api/dashboard")
def get_dashboard_data(
    sport: Optional[str] = None,
    country: Optional[str] = None,
    sport_id: Optional[int] = None,
    country_id: Optional[int] = None,
    entity_type: Optional[str] = Query(None, description="'all', 'player', or 'national_team'"),
    db: Session = Depends(get_db)
):
    all_db_players = db.query(Player).options(
        joinedload(Player.sport),
        joinedload(Player.nationality),
        joinedload(Player.club)
    ).all()

    all_db_national_teams = db.query(NationalTeam).options(
        joinedload(NationalTeam.sport),
        joinedload(NationalTeam.nationality)
    ).all()

    def matches_dropdown_filters(item):
        s_name = item.sport_name
        c_name = item.country_name
        if sport and isinstance(sport, str) and sport.strip() and s_name.lower() != sport.strip().lower():
            return False
        if country and isinstance(country, str) and country.strip() and c_name.lower() != country.strip().lower():
            return False
        if sport_id and isinstance(sport_id, int) and item.sport_id != sport_id:
            return False
        if country_id and isinstance(country_id, int) and item.country_id != country_id:
            return False
        return True

    clean_sport = sport if isinstance(sport, str) else None
    clean_country = country if isinstance(country, str) else None
    clean_sport_id = sport_id if isinstance(sport_id, int) else None
    clean_country_id = country_id if isinstance(country_id, int) else None
    clean_entity_type = entity_type if isinstance(entity_type, str) else None

    cache_key = (
        (clean_sport or "").strip().lower(),
        (clean_country or "").strip().lower(),
        clean_sport_id,
        clean_country_id,
        (clean_entity_type or "").strip().lower()
    )
    now_ts = datetime.datetime.now().timestamp()
    if cache_key in _DASHBOARD_CACHE:
        c_ts, c_data = _DASHBOARD_CACHE[cache_key]
        if now_ts - c_ts < _DASHBOARD_CACHE_TTL:
            return c_data

    total_filtered_players = sum(1 for p in all_db_players if matches_dropdown_filters(p))
    total_filtered_national_teams = sum(1 for t in all_db_national_teams if matches_dropdown_filters(t))

    players = all_db_players if clean_entity_type != "national_team" else []
    national_teams = all_db_national_teams if clean_entity_type != "player" else []
    
    # 1. Determine active sports and countries dynamically based on active entity scope
    active_sports_set = set()
    active_countries_set = set()
    if clean_entity_type == "player":
        active_sports_set = {p.sport_name for p in all_db_players if p.sport_name and p.sport_name != "Không rõ"}
        active_countries_set = {p.country_name for p in all_db_players if p.country_name and p.country_name != "Không rõ"}
    elif clean_entity_type == "national_team":
        active_sports_set = {t.sport_name for t in all_db_national_teams if t.sport_name and t.sport_name != "Không rõ"}
        active_countries_set = {t.country_name for t in all_db_national_teams if t.country_name and t.country_name != "Không rõ"}
    else:
        active_sports_set = {p.sport_name for p in all_db_players if p.sport_name and p.sport_name != "Không rõ"}
        active_sports_set.update({t.sport_name for t in all_db_national_teams if t.sport_name and t.sport_name != "Không rõ"})
        active_countries_set = {p.country_name for p in all_db_players if p.country_name and p.country_name != "Không rõ"}
        active_countries_set.update({t.country_name for t in all_db_national_teams if t.country_name and t.country_name != "Không rõ"})

    sports_list = [{"name": s} for s in sorted(active_sports_set)]
    countries_list = [{"name": c} for c in sorted(active_countries_set)]

    active_players = []
    upcoming_players = []
    no_match_players = []
    schedule_players = []
    
    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    ict_now = now_utc + datetime.timedelta(hours=7)
    today_ict = ict_now.date()
    today_str_vn = today_ict.strftime("%Y-%m-%d")
    
    player_data_tuples = []
    for p in players:
        sport_name = p.sport_name
        country_name = p.country_name
        team_name = p.team_name

        if sport and isinstance(sport, str) and sport.strip() and sport_name.lower() != sport.strip().lower():
            continue
        if country and isinstance(country, str) and country.strip() and country_name.lower() != country.strip().lower():
            continue
        if sport_id and isinstance(sport_id, int) and p.sport_id != sport_id:
            continue
        if country_id and isinstance(country_id, int) and p.country_id != country_id:
            continue
        
        player_data_tuples.append((p, team_name, sport_name, country_name))

    # Load existing historical match performances from database to avoid repeated external API calls
    all_db_perfs = db.query(MatchPerformance).all()
    perf_by_player_event = {}
    perf_by_player_date = {}
    for perf in all_db_perfs:
        if perf.event_id:
            perf_by_player_event[(perf.player_id, str(perf.event_id))] = perf
        if perf.date_str:
            perf_by_player_date[(perf.player_id, str(perf.date_str))] = perf

    # Fetch player career schedules in parallel (supporting club transfer history)
    def _fetch_player_career(item):
        p, t_name, s_name, _ = item
        return p.id, fetch_player_career_schedule(p.name, t_name, s_name)

    sched_map = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for pid, s_list in ex.map(_fetch_player_career, player_data_tuples):
            sched_map[pid] = s_list

    # Prefetch recent past ESPN event summaries in parallel ONLY if not already locked in DB
    unique_past_events = set()
    for p, team_name, sport_name, _ in player_data_tuples:
        espn_sport = {"Bóng đá": "soccer", "Bóng rổ": "basketball", "Bóng chày": "baseball"}.get(sport_name)
        if espn_sport:
            for m in sched_map.get(p.id, []):
                diff_d = m.get("diff_days", 999.0)
                ev_id = m.get("event_id")
                m_date_vn = m.get("date_only_vn") or ""
                # Skip prefetch if already stored in DB
                has_in_db = False
                if ev_id and (p.id, str(ev_id)) in perf_by_player_event:
                    has_in_db = True
                elif m_date_vn and (p.id, str(m_date_vn)) in perf_by_player_date:
                    has_in_db = True

                if not has_in_db and ev_id and -300 <= diff_d < -0.05 and not str(ev_id).startswith("non_espn_"):
                    cache_k = f"{p.name}_{ev_id}_post"
                    if cache_k not in MATCH_STATS_CACHE:
                        unique_past_events.add((espn_sport, str(ev_id)))

    def _prefetch_summary(item):
        espn_sport, ev_id = item
        league = "all" if espn_sport == "soccer" else ("nba" if espn_sport == "basketball" else "mlb")
        url = f"https://site.api.espn.com/apis/site/v2/sports/{espn_sport}/{league}/summary?event={ev_id}"
        fetch_espn_summary(url, ev_id)

    if unique_past_events:
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
            list(ex.map(_prefetch_summary, unique_past_events))

    # Khung 48 giờ chuẩn: Từ 00:00:00 ngày hôm trước đến 23:59:59 ngày hôm nay (tính theo giờ Việt Nam UTC+7)
    yesterday_ict = today_ict - datetime.timedelta(days=1)
    today_win_start_utc = datetime.datetime.combine(yesterday_ict, datetime.time.min) - datetime.timedelta(hours=7)
    today_win_end_utc = datetime.datetime.combine(today_ict, datetime.time.max) - datetime.timedelta(hours=7)
    live_scores = get_live_scores_map()

    # Batch load latest match performance and player news to eliminate per-player DB roundtrips
    today_perf_by_player = {}
    for perf in all_db_perfs:
        if perf.player_id not in today_perf_by_player:
            today_perf_by_player[perf.player_id] = perf

    all_db_player_news = db.query(PlayerNews).order_by(PlayerNews.published_at.desc()).all()
    news_by_player = {}
    for n in all_db_player_news:
        news_by_player.setdefault(n.player_id, []).append(n)

    for p, team_name, sport_name, country_name in player_data_tuples:
        match_today = today_perf_by_player.get(p.id)
        all_player_news = list(news_by_player.get(p.id, []))
        news_today = [n for n in all_player_news if today_win_start_utc <= n.published_at <= today_win_end_utc]
        
        tz_offset = "UTC"
        country_flag = "🌐"
        for info in EN_TO_VI_MAP.values():
            if isinstance(info, dict) and info.get("name") == country_name:
                tz_offset = info.get("tz", "UTC")
                country_flag = info.get("flag", "🌐")
                break

        match_date_utc = (match_today.match_date.strftime("%Y-%m-%dT%H:%M:%SZ") if (match_today and match_today.match_date) else None)
        
        in_today_activity = False
        is_within_month = False
        next_match_text = "Chưa có dữ liệu lịch đấu"
        
        diff_days = 999
        if match_today and match_today.match_date:
            match_ict = match_today.match_date + datetime.timedelta(hours=7)
            match_date_ict = match_ict.date()
            diff_days = (match_date_ict - today_ict).days
            
            # STRICT TODAY: Only matches taking place on TODAY (diff_days == 0) or live matches (match_state == 'in')
            # Matches on tomorrow (diff_days == 1 or 23/10) belong to Upcoming Matches.
            # Matches on yesterday (diff_days == -1 or 21/10) belong to Past Matches / No Match.
            if diff_days == 0:
                in_today_activity = True
                is_within_month = True
                next_match_text = match_today.match_name
            elif diff_days > 0 and diff_days <= 30:
                in_today_activity = False
                is_within_month = True
                next_match_text = match_today.match_name
            else:
                in_today_activity = False
                is_within_month = False
                next_match_text = "Không có trận trong 1 tháng sắp tới"
        else:
            in_today_activity = False
            is_within_month = False
            next_match_text = "Không có trận trong 1 tháng sắp tới"
        
        match_state = getattr(match_today, 'match_state', 'pre') or 'pre'
        match_result = getattr(match_today, 'match_result', None)
        raw_stats = getattr(match_today, 'player_stats', None)
        rating = match_today.performance_rating if match_today else None
        
        raw_tags = (match_today.impression_tags or "").split(",") if match_today and match_today.impression_tags else []
        comp_name = getattr(match_today, 'competition', None) or ""

        p_news_titles = [n.title for n in news_today]
        if not p_news_titles:
            p_news_titles = [n.title for n in all_player_news[:15]]

        # Kiểm tra kết quả trực tiếp thời gian thực cho trận đấu đang live/vừa kết thúc hôm nay
        clean_team_key = (team_name or "").lower().strip()
        live_info = live_scores.get(clean_team_key)
        if not live_info:
            for k in live_scores:
                if k in clean_team_key or clean_team_key in k:
                    live_info = live_scores[k]
                    break

        if live_info:
            live_state = live_info.get("state", "pre")
            # Only count as today if the live match is actually happening now ('in') or today
            if live_state == "in" or (live_state == "post" and diff_days == 0):
                match_state = live_state
                in_today_activity = True
                is_within_month = True
                if live_info.get("match_result"):
                    match_result = live_info["match_result"]
                if live_info.get("competition"):
                    comp_name = live_info["competition"]
                
                # Cập nhật thông số thi đấu trực tiếp cho cầu thủ
                ev_id = live_info.get("event_id")
                stats_info = fetch_player_match_stats(p.name, sport_name, team_name, event_id=ev_id, match_state=match_state, news_titles=p_news_titles)
                if stats_info.get("tags"):
                    raw_tags = stats_info.get("tags", [])
                if stats_info.get("has_played"):
                    rating = stats_info.get("rating")
                    raw_stats = stats_info.get("stats_text")
                
                if match_today:
                    match_today.match_state = match_state
                    match_today.match_result = match_result
                    match_today.competition = comp_name
                    if stats_info.get("tags"):
                        match_today.impression_tags = ", ".join(raw_tags)
                    if stats_info.get("has_played"):
                        match_today.performance_rating = rating
                        match_today.player_stats = raw_stats
                        match_today.has_played = True

        if not comp_name and sport_name == "Bóng đá":
            for m in sched_map.get(p.id, []):
                if m.get("competition"):
                    comp_name = m.get("competition")
                    break
            if not comp_name and team_name:
                clean_comp = get_tournament_tag(team_name, sport_name, "", "")
                if clean_comp:
                    comp_name = clean_comp
            if comp_name and match_today:
                match_today.competition = comp_name

        is_player_no_match = (not in_today_activity and not is_within_month)
        raw_stats_summary, _ = unpack_stats(raw_stats)
        _, tags = format_player_stats_and_tags(
            p.name, sport_name, team_name,
            match_today.match_name if match_today else "",
            match_state, raw_stats_summary, raw_tags,
            competition_name=comp_name,
            news_titles=p_news_titles,
            is_no_match=is_player_no_match
        )

        all_matches_raw = sched_map.get(p.id, [])
        all_matches = []
        upcoming_matches_30d = []
        today_str_vn = today_ict.strftime("%Y-%m-%d")

        for m_raw in all_matches_raw:
            m = dict(m_raw)
            m_date_vn = m.get("date_only_vn") or ""
            diff_d = m.get("diff_days", 999.0)
            is_m_past = m.get("is_past") or (m.get("match_state") == "post") or (diff_d < -0.1)

            # Standardize tournament tag across past & present
            raw_c = m.get("competition") or ""
            clean_comp = get_tournament_tag(p.team_name, sport_name, m.get("match_name", ""), raw_c)
            if not clean_comp:
                if sport_name in ["Bóng chày", "baseball"]: clean_comp = "MLB"
                elif sport_name in ["Bóng rổ", "basketball"]: clean_comp = "NBA"
                else: clean_comp = raw_c
            m["competition"] = clean_comp

            # 1. Match-specific Rating & Stats & Tags
            is_matching_today_perf = False
            if match_today and in_today_activity:
                m_ev_id = str(m.get("event_id") or "")
                perf_ev_id = str(getattr(match_today, "event_id", "") or "")
                perf_date_vn = (match_today.match_date + datetime.timedelta(hours=7)).strftime("%Y-%m-%d") if match_today.match_date else ""
                if (m_ev_id and perf_ev_id and m_ev_id == perf_ev_id) or (m_date_vn and m_date_vn == perf_date_vn and m_date_vn == today_str_vn):
                    is_matching_today_perf = True

            if is_matching_today_perf and match_today:
                h_played = (match_today.has_played if match_today else False)
                db_tags = [t.strip() for t in (match_today.impression_tags or "").split(",") if t.strip()]
                is_no_play = not h_played or any(no_play_kw in t for t in (db_tags or tags) for no_play_kw in ["Không đăng ký", "Không thi đấu", "Dự bị (Không vào sân)", "Chấn thương"])
                
                m["rating"] = None if is_no_play else rating
                m["player_stats"] = None if is_no_play else raw_stats
                # Include competition tag + impression tags directly from match_today
                m_tags = [clean_comp] if clean_comp else []
                for t in (db_tags or tags):
                    if t and t not in m_tags:
                        t_low = t.lower()
                        if "cứu thua" in t_low and "xuất sắc" not in t_low:
                            continue
                        m_tags.append(t)
                m["tags"] = m_tags
                m["has_played"] = False if is_no_play else h_played
            elif is_m_past:
                ev_id = m.get("event_id")
                match_team = m.get("player_team") or team_name
                db_perf = None
                if ev_id:
                    db_perf = perf_by_player_event.get((p.id, str(ev_id)))
                if not db_perf and m_date_vn:
                    db_perf = perf_by_player_date.get((p.id, str(m_date_vn)))

                if db_perf and (db_perf.player_stats or db_perf.impression_tags or db_perf.has_played is not None):
                    m["has_played"] = db_perf.has_played or False
                    m["rating"] = db_perf.performance_rating if m["has_played"] else None
                    m["player_stats"] = db_perf.player_stats if m["has_played"] else None
                    m_tags = [clean_comp] if clean_comp else []
                    db_tags = [t.strip() for t in (db_perf.impression_tags or "").split(",") if t.strip()]
                    for t in db_tags:
                        if t and t not in m_tags:
                            t_low = t.lower()
                            if "cứu thua" in t_low and "xuất sắc" not in t_low:
                                continue
                            m_tags.append(t)
                    m["tags"] = m_tags
                else:
                    real_stats = None
                    if ev_id and diff_d >= -300:
                        try:
                            real_stats = fetch_player_match_stats(
                                p.name, sport_name, match_team, event_id=ev_id, match_state="post", news_titles=p_news_titles
                            )
                        except Exception:
                            real_stats = None
                    
                    if real_stats:
                        has_p = real_stats.get("has_played", False)
                        p_rating = real_stats.get("rating") if has_p else None
                        p_stats = real_stats.get("stats_text") if has_p else None
                        raw_tags_list = real_stats.get("tags", [])

                        m["has_played"] = has_p
                        m["rating"] = p_rating
                        m["player_stats"] = p_stats
                        m_tags = [clean_comp] if clean_comp else []
                        for t in raw_tags_list:
                            if t and t not in m_tags:
                                t_low = t.lower()
                                if "cứu thua" in t_low and "xuất sắc" not in t_low:
                                    continue
                                m_tags.append(t)
                        m["tags"] = m_tags

                        # Lock into Database permanently
                        try:
                            m_dt = None
                            if m.get("match_date_utc"):
                                try:
                                    m_dt = datetime.datetime.strptime(m["match_date_utc"][:19], "%Y-%m-%dT%H:%M:%S")
                                except Exception:
                                    pass
                            new_perf = MatchPerformance(
                                player_id=p.id,
                                match_name=m.get("match_name"),
                                match_date=m_dt,
                                has_played=has_p,
                                performance_rating=p_rating,
                                impression_tags=",".join(raw_tags_list),
                                match_state="post",
                                match_result=m.get("match_result"),
                                player_stats=p_stats,
                                competition=clean_comp,
                                event_id=str(ev_id) if ev_id else None,
                                date_str=m_date_vn
                            )
                            db.add(new_perf)
                            if ev_id:
                                perf_by_player_event[(p.id, str(ev_id))] = new_perf
                            if m_date_vn:
                                perf_by_player_date[(p.id, str(m_date_vn))] = new_perf
                        except Exception:
                            pass
                    else:
                        m["rating"] = None
                        m["player_stats"] = None
                        m["tags"] = [clean_comp] if clean_comp else []
                        m["has_played"] = False
            else:
                m["rating"] = None
                m["player_stats"] = None
                m_tags = [clean_comp] if clean_comp else []
                off_inj = get_player_official_injury(p.name, sport_name)
                if off_inj:
                    m_tags.append(off_inj["formatted_tag"])
                m["tags"] = m_tags
                m["has_played"] = False

            # 2. Match News Window: [D - 1 day 00:00:00 to D 23:59:59]
            if m_date_vn:
                try:
                    d_dt = datetime.datetime.strptime(m_date_vn, "%Y-%m-%d").date()
                    d_prev = d_dt - datetime.timedelta(days=1)
                    win_start = datetime.datetime.combine(d_prev, datetime.time.min) - datetime.timedelta(hours=7)
                    win_end = datetime.datetime.combine(d_dt, datetime.time.max) - datetime.timedelta(hours=7)
                    m_news = [
                        {
                            "title": n.title,
                            "url": n.source_url,
                            "news_type": n.news_type,
                            "region": getattr(n, "region", "US") or "US"
                        }
                        for n in all_player_news
                        if win_start <= n.published_at <= win_end
                    ]
                except Exception:
                    m_news = []
            else:
                m_news = []
            
            # Logic báo theo yêu cầu:
            # 1. Trận đấu diễn ra quá 30 ngày (diff_d < -30): chuyển về đúng 1 báo tóm tắt trận đấu
            if diff_d < -30:
                ev_id = m.get("event_id")
                if ev_id and not str(ev_id).startswith("non_espn_"):
                    ev_link = f"https://www.espn.com/match?gameId={ev_id}"
                else:
                    clean_q = urllib.parse.quote(f"{p.name} {team_name} {m.get('match_name', '')} {clean_comp}".strip())
                    ev_link = f"https://www.google.com/search?q={clean_q}"
                res_part = f" - {m.get('match_result')}" if m.get("match_result") else ""
                comp_part = f" [{clean_comp}]" if clean_comp else ""
                m_news = [{
                    "title": f"Điểm tin trận đấu: {p.name} ({team_name}) {m.get('match_name', '')}{res_part}{comp_part}",
                    "url": ev_link,
                    "news_type": "Thi đấu",
                    "region": "Quốc tế"
                }]
            # 2. Trận đấu trong khoảng 30 ngày trở lại đây (-30 <= diff_d <= 0):
            # Lưu lại báo theo khung 48h (ngày thi đấu và ngày hôm trước). Nếu DB chưa có thì lấy từ recap & lưu vào DB
            elif is_m_past and -30 <= diff_d <= 0:
                if len(m_news) == 0:
                    ev_id = m.get("event_id")
                    recap_items = fetch_match_recap_news(
                        str(ev_id or ""), sport_name, team_name, p.name, m.get("match_name", ""),
                        m_date_vn, match_result=m.get("match_result"), comp_name=clean_comp
                    )
                    for r_item in recap_items:
                        try:
                            new_n = PlayerNews(
                                player_id=p.id,
                                title=r_item["title"],
                                source_url=r_item["url"],
                                news_type=r_item.get("news_type", "Thi đấu"),
                                region=r_item.get("region", "US"),
                                published_at=win_end
                            )
                            db.add(new_n)
                            all_player_news.append(new_n)
                            m_news.append(r_item)
                        except Exception:
                            m_news.append(r_item)
            
            m_s, m_d = unpack_stats(m.get("player_stats"))
            m["player_stats"] = m_s
            m["detailed_stats"] = m_d
            m["news"] = m_news
            m["news_count"] = len(m_news)
            all_matches.append(m)

            if 0 <= diff_d <= 30 and not is_m_past and m.get("match_state") != "post":
                upcoming_matches_30d.append(m)

        all_upcoming_matches = [
            m for m in all_matches 
            if m.get("diff_days", -1) >= 0 and not m.get("is_past") and m.get("match_state") != "post"
        ]

        # If player did not play in today's match, rating MUST be None
        if match_today and not getattr(match_today, 'has_played', True):
            rating = None
            raw_stats = None
        if any(no_play_kw in t for t in tags for no_play_kw in ["Không đăng ký", "Không thi đấu", "Dự bị (Không vào sân)", "Chấn thương"]):
            rating = None
            raw_stats = None

        # Build accurate match representation depending on player category:
        # 1. TODAY'S ACTIVITIES: Focused on Today's match
        # 2. UPCOMING MATCHES: Focused on strictly next future match (upcoming_matches_30d[0])
        # 3. NO MATCH: Focused on season off / no matches
        if in_today_activity:
            curr_match_name = match_today.match_name if match_today else (upcoming_matches_30d[0]["match_name"] if upcoming_matches_30d else "Đang thi đấu hôm nay")
            curr_match_date_utc = match_date_utc
            curr_match_state = match_state
            curr_match_result = match_result
            curr_rating = rating
            c_summary, c_details = unpack_stats(raw_stats)
            curr_stats = c_summary
            curr_detailed_stats = c_details
            curr_tags = tags
            next_match_text = curr_match_name
            next_match_date_str = match_today.match_date.strftime("%d/%m/%Y") if (match_today and match_today.match_date) else "Hôm nay"
            is_within_month = True
        elif len(upcoming_matches_30d) > 0:
            first_up = upcoming_matches_30d[0]
            curr_match_name = first_up["match_name"]
            curr_match_date_utc = first_up["match_date_utc"]
            curr_match_state = "pre"
            curr_match_result = None
            curr_rating = None
            curr_stats = None
            curr_detailed_stats = None
            
            clean_comp = get_tournament_tag(team_name, sport_name, curr_match_name, first_up.get("competition", ""))
            curr_tags = [clean_comp] if clean_comp else []
            next_match_text = first_up['match_name']
            next_match_date_str = first_up.get("date_vn") or "Sắp diễn ra"
            is_within_month = True
        else:
            curr_match_name = "Không có trận trong 1 tháng sắp tới (Nghỉ mùa)"
            curr_match_date_utc = None
            curr_match_state = "pre"
            curr_match_result = None
            curr_rating = None
            curr_stats = None
            curr_detailed_stats = None
            curr_tags = ["Nghỉ mùa"]
            next_match_text = "Không có trận trong 1 tháng sắp tới (Nghỉ mùa)"
            next_match_date_str = "N/A"
            is_within_month = False

        # Unified official injury handling for all players across all sports
        off_inj = get_player_official_injury(p.name, sport_name)
        if not off_inj and any("chấn thương" in t.lower() or "đau nhẹ" in t.lower() for t in (curr_tags or tags)):
            inj_tag = next((t for t in (curr_tags or tags) if "chấn thương" in t.lower() or "đau nhẹ" in t.lower()), "Chấn thương")
            off_inj = {
                "has_injury": True,
                "tag_label": inj_tag,
                "tooltip": "Chấn thương: Đang trong quá trình điều trị / hồi phục thể lực | Trạng thái: Nghỉ thi đấu",
                "formatted_tag": f"{inj_tag}::Chấn thương: Đang trong quá trình điều trị / hồi phục thể lực | Trạng thái: Nghỉ thi đấu",
                "status": "Out",
                "severity": "Chấn thương (Nghỉ thi đấu)",
                "injury_desc": "Đang trong quá trình điều trị / hồi phục thể lực",
                "injury_type": "Chấn thương thể lực",
                "injury_detail": "Nghỉ thi đấu",
                "side": "",
                "return_date": "Đang cập nhật",
                "is_severe": True
            }

        if off_inj:
            curr_tags = [t for t in curr_tags if "chấn thương" not in t.lower() and t != off_inj["tag_label"]]
            curr_tags.append(off_inj["formatted_tag"])
            injury_data = off_inj
        else:
            injury_data = {
                "has_injury": False,
                "status": "Fit",
                "severity": "Thể lực tốt",
                "tag_label": "Sẵn sàng",
                "tooltip": "Thể lực đảm bảo, sẵn sàng ra sân thi đấu",
                "return_date": "Hiện tại",
                "injury_desc": "Không có ghi nhận chấn thương"
            }

        player_news_list = news_today if news_today else all_player_news[:10]

        player_item = {
            "id": p.id,
            "entity_type": "player",
            "tier_badge": None,
            "name": p.name,
            "api_player_id": p.api_player_id,
            "api_team_id": p.api_team_id,
            "name_aliases": p.name_aliases,
            "sport": sport_name,
            "country": country_name,
            "country_timezone": tz_offset,
            "country_flag": country_flag,
            "team": team_name,
            "next_match": next_match_text,
            "match_state": curr_match_state,
            "match_result": curr_match_result,
            "player_stats": curr_stats,
            "detailed_stats": curr_detailed_stats,
            "rating": curr_rating,
            "tags": curr_tags,
            "injury": injury_data,
            "is_within_month": is_within_month,
            "match_date_utc": curr_match_date_utc,
            "next_match_date": next_match_date_str,
            "all_matches": all_matches,
            "details": {
                "match": curr_match_name,
                "match_date_utc": curr_match_date_utc,
                "match_state": curr_match_state,
                "match_result": curr_match_result,
                "player_stats": curr_stats,
                "detailed_stats": curr_detailed_stats,
                "injury": injury_data,
                "upcoming_matches_30d": upcoming_matches_30d,
                "all_upcoming_matches": all_upcoming_matches,
                "all_matches": all_matches,
                "news": [
                    {
                        "title": n.title,
                        "url": n.source_url,
                        "news_type": n.news_type,
                        "region": getattr(n, "region", "US") or "US"
                    }
                    for n in player_news_list
                ]
            }
        }
        
        if in_today_activity:
            active_players.append(dict(player_item))
        elif len(upcoming_matches_30d) > 0:
            upcoming_players.append(dict(player_item))
        else:
            no_match_item = dict(player_item)
            no_match_players.append(no_match_item)

        sched_item = dict(player_item)
        sched_item["tags"] = []
        sched_item["upcoming_3_matches"] = upcoming_matches_30d[:3]
        sched_item["earliest_match_utc"] = upcoming_matches_30d[0]["match_date_utc"] if upcoming_matches_30d else None
        schedule_players.append(sched_item)

    try:
        db.commit()
    except Exception:
        pass

    # 2. Process National & Youth Teams (Unified integration into same timeline and tabs)
    filtered_nts = []
    for nt in national_teams:
        s_name = nt.sport_name
        c_name = nt.country_name
        if sport and isinstance(sport, str) and sport.strip() and s_name.lower() != sport.strip().lower():
            continue
        if country and isinstance(country, str) and country.strip() and c_name.lower() != country.strip().lower():
            continue
        if sport_id and isinstance(sport_id, int) and nt.sport_id != sport_id:
            continue
        if country_id and isinstance(country_id, int) and nt.country_id != country_id:
            continue
        filtered_nts.append({
            "id": nt.id,
            "name": nt.name,
            "short_name": nt.short_name,
            "nickname": nt.nickname,
            "sport_id": nt.sport_id,
            "country_id": nt.country_id,
            "sport_name": s_name,
            "country_name": c_name,
            "flag": nt.flag,
            "tier": nt.tier,
            "gender": nt.gender,
            "description": nt.description,
            "api_team_id": nt.api_team_id
        })

    def _fetch_nt_sched(t):
        return t["id"], fetch_national_team_schedule(t)

    nt_sched_map = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for tid, s_list in ex.map(_fetch_nt_sched, filtered_nts):
            nt_sched_map[tid] = s_list

    # Batch load national team news from DB
    all_nt_news = db.query(NationalTeamNews).all()
    nt_news_by_team = {}
    for n in all_nt_news:
        nt_news_by_team.setdefault(n.team_id, []).append(n)

    for nt in filtered_nts:
        nt_id = nt["id"]
        nt_matches = nt_sched_map.get(nt_id, [])
        nt_news = nt_news_by_team.get(nt_id, [])

        nt_upcoming_30d = []
        nt_upcoming_all = []
        nt_match_today = None

        for m in nt_matches:
            diff_d = m.get("diff_days", 999.0)
            is_m_past = m.get("is_past") or (diff_d < -0.1)
            m_date_vn = m.get("date_only_vn") or ""

            # News window for match (48h)
            if m_date_vn:
                try:
                    d_dt = datetime.datetime.strptime(m_date_vn, "%Y-%m-%d").date()
                    d_prev = d_dt - datetime.timedelta(days=1)
                    w_start = datetime.datetime.combine(d_prev, datetime.time.min) - datetime.timedelta(hours=7)
                    w_end = datetime.datetime.combine(d_dt, datetime.time.max) - datetime.timedelta(hours=7)
                    m_news = [
                        {"title": n.title, "url": n.source_url, "news_type": n.news_type, "region": getattr(n, "region", "US") or "US"}
                        for n in nt_news if w_start <= n.published_at <= w_end
                    ]
                except Exception:
                    m_news = []
            else:
                m_news = []

            if not m_news and nt_news:
                m_news = [{"title": n.title, "url": n.source_url, "news_type": n.news_type, "region": getattr(n, "region", "US") or "US"} for n in nt_news[:5]]

            m["news"] = m_news
            m["news_count"] = len(m_news)

            if m_date_vn == today_str_vn:
                nt_match_today = m

            if not is_m_past and diff_d >= 0:
                nt_upcoming_all.append(m)
                if diff_d <= 30:
                    nt_upcoming_30d.append(m)

        tier_clean = nt.get("tier") or "Senior"
        if tier_clean == "Senior":
            tier_badge = "ĐTQG"
        elif tier_clean in ["U23", "U21", "U20", "U19", "U18", "U17"]:
            tier_badge = tier_clean
        else:
            tier_badge = "Tuyển trẻ"

        if nt_match_today:
            curr_match_name = nt_match_today.get("match_name")
            curr_match_date_utc = nt_match_today.get("match_date_utc")
            curr_match_state = nt_match_today.get("match_state", "pre")
            curr_match_result = nt_match_today.get("match_result")
            next_match_text = nt_match_today.get("match_name")
            next_match_date_str = nt_match_today.get("date_vn") or "Hôm nay"
            in_today = True
        elif nt_upcoming_all:
            first_up = nt_upcoming_all[0]
            curr_match_name = first_up.get("match_name")
            curr_match_date_utc = first_up.get("match_date_utc")
            curr_match_state = "pre"
            curr_match_result = None
            next_match_text = first_up.get("match_name")
            next_match_date_str = first_up.get("date_vn") or "Sắp diễn ra"
            in_today = False
        else:
            curr_match_name = "Chưa có lịch sắp tới"
            curr_match_date_utc = None
            curr_match_state = "pre"
            curr_match_result = None
            next_match_text = "Chưa có lịch sắp tới"
            next_match_date_str = "N/A"
            in_today = False

        tz_offset = "UTC+9"

        nt_item = {
            "id": f"nt_{nt_id}",
            "db_id": nt_id,
            "entity_type": "national_team",
            "name": nt["name"],
            "short_name": nt.get("short_name") or nt["name"],
            "api_player_id": None,
            "api_team_id": nt.get("api_team_id"),
            "name_aliases": "",
            "sport": nt["sport_name"],
            "country": nt["country_name"],
            "country_timezone": tz_offset,
            "country_flag": nt.get("flag") or "🌐",
            "team": nt["sport_name"],
            "tier": nt.get("tier"),
            "tier_badge": None,
            "next_match": next_match_text,
            "match_state": curr_match_state,
            "match_result": curr_match_result,
            "player_stats": None,
            "rating": None,
            "tags": [],
            "injury": {"has_injury": False, "status": "Fit", "severity": "Sẵn sàng", "tag_label": "Sẵn sàng", "tooltip": "Đội hình đầy đủ", "return_date": "Hiện tại", "injury_desc": ""},
            "is_within_month": len(nt_upcoming_30d) > 0,
            "match_date_utc": curr_match_date_utc,
            "next_match_date": next_match_date_str,
            "all_matches": nt_matches,
            "details": {
                "match": curr_match_name,
                "match_date_utc": curr_match_date_utc,
                "match_state": curr_match_state,
                "match_result": curr_match_result,
                "player_stats": None,
                "injury": {"has_injury": False},
                "upcoming_matches_30d": nt_upcoming_30d,
                "all_upcoming_matches": nt_upcoming_all,
                "all_matches": nt_matches,
                "news": [
                    {"title": n.title, "url": n.source_url, "news_type": n.news_type, "region": getattr(n, "region", "US") or "US"}
                    for n in nt_news[:15]
                ]
            }
        }

        if in_today:
            active_players.append(dict(nt_item))
        elif len(nt_upcoming_30d) > 0:
            upcoming_players.append(dict(nt_item))
        else:
            no_match_players.append(dict(nt_item))

        sched_nt = dict(nt_item)
        sched_nt["upcoming_3_matches"] = nt_upcoming_30d[:3]
        sched_nt["earliest_match_utc"] = nt_upcoming_30d[0]["match_date_utc"] if nt_upcoming_30d else None
        schedule_players.append(sched_nt)
            
    # Sắp xếp: Ưu tiên số lượng báo chí được nhắc tới trước, sau đó đến lịch thi đấu
    def sort_active_today_players(p):
        news_count = len(p.get("details", {}).get("news", []))
        rating_val = p.get("rating")
        has_rating = 1 if (isinstance(rating_val, (int, float)) and rating_val > 0) else 0
        rating_score = float(rating_val) if has_rating else 0.0
        m_state = p.get("match_state", "pre")
        state_priority = 3 if has_rating else (2 if m_state in ["post", "in"] else 1)
        return (news_count, state_priority, rating_score)

    def sort_by_news_and_time(p):
        news_count = len(p.get("details", {}).get("news", []))
        time_score = 9999999999.0
        dt_raw = p.get("match_date_utc") or p.get("details", {}).get("match_date_utc")
        if dt_raw:
            try:
                clean_dt_str = dt_raw.replace("Z", "")
                mdt = datetime.datetime.fromisoformat(clean_dt_str)
                time_score = mdt.timestamp()
            except Exception:
                pass
        return (-news_count, time_score)

    active_players.sort(key=sort_active_today_players, reverse=True)
    upcoming_players.sort(key=sort_by_news_and_time)
    no_match_players.sort(key=lambda p: len(p.get("details", {}).get("news", [])), reverse=True)

    def sort_schedule_key(p):
        news_count = len(p.get("details", {}).get("news", []))
        earliest_utc = p.get("earliest_match_utc")
        time_val = 9999999999.0
        if earliest_utc:
            try:
                time_val = datetime.datetime.fromisoformat(earliest_utc.replace("Z", "")).timestamp()
            except Exception:
                pass
        return (-news_count, time_val)

    schedule_players.sort(key=sort_schedule_key)

    calendar_counts = {}
    for p_item in (active_players + upcoming_players + no_match_players):
        p_matches = p_item.get("all_matches") or p_item.get("details", {}).get("all_matches", [])
        seen_dates_for_player = set()
        for m in p_matches:
            d_key = m.get("date_only_vn")
            if not d_key and m.get("match_date_utc"):
                try:
                    dt_utc = datetime.datetime.fromisoformat(m["match_date_utc"].replace("Z", ""))
                    d_key = (dt_utc + datetime.timedelta(hours=7)).strftime("%Y-%m-%d")
                except Exception:
                    pass
            if d_key and d_key not in seen_dates_for_player:
                seen_dates_for_player.add(d_key)
                calendar_counts[d_key] = calendar_counts.get(d_key, 0) + 1

    # Bổ sung đủ ngày từ đầu mùa (25/02/2026), ngày không có ai thi đấu thì ghi 0
    start_date = datetime.date(2026, 2, 25)
    end_date = (today_ict if isinstance(today_ict, datetime.date) else today_ict.date()) + datetime.timedelta(days=35)
    for k in list(calendar_counts.keys()):
        try:
            kd = datetime.datetime.strptime(k, "%Y-%m-%d").date()
            if kd > end_date:
                end_date = kd
        except Exception:
            pass

    curr_d = start_date
    while curr_d <= end_date:
        k_str = curr_d.strftime("%Y-%m-%d")
        if k_str not in calendar_counts:
            calendar_counts[k_str] = 0
        curr_d += datetime.timedelta(days=1)

    result_data = {
        "today_date_vn": today_str_vn,
        "server_time_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "active_players": active_players,
        "upcoming_players": upcoming_players,
        "inactive_players": upcoming_players,
        "no_match_players": no_match_players,
        "schedule_players": schedule_players,
        "calendar_counts": calendar_counts,
        "sports_list": sports_list,
        "countries_list": countries_list,
        "total_players": total_filtered_players,
        "total_national_teams": total_filtered_national_teams,
        "total_all": total_filtered_players + total_filtered_national_teams
    }
    _DASHBOARD_CACHE[cache_key] = (now_ts, result_data)
    return result_data

