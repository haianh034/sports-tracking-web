import concurrent.futures
import datetime
import re
from sqlalchemy.orm import Session
from backend.core.db.models import Player, MatchPerformance
from backend.modules.players.services.espn_service import (
    fetch_player_career_schedule,
    fetch_player_match_stats,
    fetch_espn_summary,
)
from backend.modules.players.services.sports_service import get_tournament_tag


def standardize_match_result(cur_res: str, raw_name: str, match_name: str, team_name: str) -> str:
    if not cur_res:
        return ""
    clean_sc = re.sub(r'\(.*?\)', '', str(cur_res)).strip()
    if re.match(r'^\d+\s*-\s*\d+$', clean_sc):
        if raw_name and " vs " in raw_name:
            parts = raw_name.split(" vs ")
            return f"{parts[0].strip()} {clean_sc} {parts[1].strip()} (FT)"
        elif match_name:
            mn = match_name.strip()
            if mn.startswith("vs "):
                return f"{team_name} {clean_sc} {mn[3:].strip()} (FT)"
            elif mn.startswith("@ "):
                return f"{mn[2:].strip()} {clean_sc} {team_name} (FT)"
    return str(cur_res).strip()


def sync_player_matches_history(
    player_id: int,
    player_name: str,
    team_name: str,
    sport_name: str,
    league: str = None,
    espn_team_id: str = None,
    db: Session = None,
    force_refresh: bool = True
) -> dict:
    """
    Đồng bộ và lưu trữ toàn bộ lịch sử thi đấu trong quá khứ (mùa giải)
    và lịch thi đấu tương lai cho vận động viên thuộc mọi môn thể thao.
    """
    if not db or not player_id:
        return {"synced_count": 0, "past_count": 0, "upcoming_count": 0}

    # 1. Lấy toàn bộ lịch thi đấu (quá khứ và tương lai) của cầu thủ/đội tuyển
    all_events = fetch_player_career_schedule(
        player_name, team_name, sport_name, force_refresh=force_refresh, api_team_id=espn_team_id
    )
    if not all_events:
        return {"synced_count": 0, "past_count": 0, "upcoming_count": 0}

    # 2. Prefetch tóm tắt trận đấu (ESPN Summary) song song cho các môn hỗ trợ ESPN
    espn_sport = {"Bóng đá": "soccer", "Bóng rổ": "basketball", "Bóng chày": "baseball"}.get(sport_name)
    if espn_sport:
        league_slug = "all" if espn_sport == "soccer" else ("nba" if espn_sport == "basketball" else "mlb")
        ev_ids = [
            str(ev.get("event_id")) for ev in all_events
            if ev.get("event_id") and not str(ev.get("event_id")).startswith("non_espn_")
            and (ev.get("is_past") or ev.get("match_state") in ["post", "in"] or ev.get("diff_days", 0) < 0.1)
        ]
        if ev_ids:
            def _fetch(ev_id):
                url = f"https://site.api.espn.com/apis/site/v2/sports/{espn_sport}/{league_slug}/summary?event={ev_id}"
                fetch_espn_summary(url, ev_id)
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(16, len(ev_ids))) as ex:
                list(ex.map(_fetch, ev_ids))

    # 3. Lấy tất cả bản ghi MatchPerformance hiện có của cầu thủ trong database
    existing_perfs = db.query(MatchPerformance).filter(MatchPerformance.player_id == player_id).all()
    perf_by_ev = {str(p.event_id): p for p in existing_perfs if p.event_id}
    perf_by_date = {str(p.date_str): p for p in existing_perfs if p.date_str}
    perf_by_name = {str(p.match_name): p for p in existing_perfs if p.match_name}

    synced_count = 0
    past_count = 0
    upcoming_count = 0

    for m in all_events:
        ev_id = m.get("event_id")
        m_date_vn = m.get("date_only_vn") or ""
        m_name = m.get("match_name") or m.get("name") or "Trận đấu"
        raw_name = m.get("raw_match_name") or ""
        diff_d = m.get("diff_days", 0.0)
        is_past = m.get("is_past", False) or m.get("match_state") == "post" or diff_d < -0.05
        m_state = m.get("match_state", "post" if is_past else "pre")
        
        m_dt = None
        if m.get("match_date_utc"):
            try:
                m_dt = datetime.datetime.strptime(m["match_date_utc"][:19], "%Y-%m-%dT%H:%M:%S")
            except Exception:
                pass

        cur_res = standardize_match_result(m.get("match_result"), raw_name, m_name, team_name)
        raw_comp = m.get("competition") or ""
        m_comp = league or (get_tournament_tag(team_name, sport_name, m_name, raw_comp) or raw_comp or "")

        if is_past or m_state in ["post", "in"]:
            past_count += 1
            stats_info = fetch_player_match_stats(
                player_name, sport_name, team_name, event_id=ev_id, match_state=m_state
            )
            has_played = stats_info.get("has_played", False)
            rating = stats_info.get("rating") if has_played else None
            player_stats = stats_info.get("stats_text") if has_played else None
            tags = stats_info.get("tags", [])
        else:
            upcoming_count += 1
            has_played = False
            rating = None
            player_stats = None
            tags = [m_comp] if m_comp else []

        # Khớp với bản ghi đã có trong database
        target_perf = None
        if ev_id and str(ev_id) in perf_by_ev:
            target_perf = perf_by_ev[str(ev_id)]
        elif m_date_vn and str(m_date_vn) in perf_by_date:
            target_perf = perf_by_date[str(m_date_vn)]
        elif m_name and str(m_name) in perf_by_name:
            target_perf = perf_by_name[str(m_name)]

        if target_perf:
            target_perf.match_name = m_name
            target_perf.match_date = m_dt
            target_perf.date_str = m_date_vn or target_perf.date_str
            if ev_id:
                target_perf.event_id = str(ev_id)
            target_perf.match_state = m_state
            target_perf.match_result = cur_res or target_perf.match_result
            target_perf.has_played = has_played
            target_perf.performance_rating = rating
            target_perf.player_stats = player_stats
            target_perf.impression_tags = ", ".join(tags)
            target_perf.competition = m_comp
        else:
            new_perf = MatchPerformance(
                player_id=player_id,
                match_name=m_name,
                match_date=m_dt,
                date_str=m_date_vn,
                event_id=str(ev_id) if ev_id else None,
                match_state=m_state,
                match_result=cur_res,
                has_played=has_played,
                performance_rating=rating,
                player_stats=player_stats,
                impression_tags=", ".join(tags),
                competition=m_comp
            )
            db.add(new_perf)
            if ev_id:
                perf_by_ev[str(ev_id)] = new_perf
            if m_date_vn:
                perf_by_date[str(m_date_vn)] = new_perf
            if m_name:
                perf_by_name[str(m_name)] = new_perf

        synced_count += 1

    # Dọn dẹp bản ghi rác/trùng lặp hoàn toàn rỗng không có ngày tháng và không có event_id
    ghosts = db.query(MatchPerformance).filter(
        MatchPerformance.player_id == player_id,
        MatchPerformance.event_id.is_(None),
        MatchPerformance.date_str.is_(None),
        MatchPerformance.match_date.is_(None)
    ).all()
    for g in ghosts:
        db.delete(g)

    db.commit()
    return {
        "synced_count": synced_count,
        "past_count": past_count,
        "upcoming_count": upcoming_count
    }

