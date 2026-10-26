from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
import concurrent.futures

from backend.core.db.session import get_db
from backend.core.db.models import Player, Sport, Nationality, Club, MatchPerformance, PlayerNews
from backend.core.config import EN_TO_VI_MAP
from backend.modules.players.services.candidate_service import search_athlete_candidates
from backend.core.services.wiki_service import fetch_free_player_info
from backend.modules.players.services.espn_service import fetch_real_schedule, fetch_player_match_stats, fetch_player_upcoming_schedule_30d, SCHEDULE_CACHE, SCHEDULE_30D_CACHE
from backend.modules.players.services.sports_service import get_tournament_tag
from backend.modules.players.services.news_service import scan_player_news, fetch_player_news_entries

router = APIRouter(prefix="/api/players", tags=["players"])

def cleanup_orphans(db: Session):
    """
    Xóa tất cả các CLB, quốc tịch, và môn thể thao không còn bất kỳ vận động viên nào.
    Đảm bảo database không có rác hay dữ liệu chết.
    """
    try:
        db.query(Club).filter(~Club.players.any()).delete(synchronize_session=False)
        db.query(Nationality).filter(~Nationality.players.any()).delete(synchronize_session=False)
        db.query(Sport).filter(~Sport.players.any()).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()

class AddConfirmedPlayerRequest(BaseModel):
    name: str
    team: Optional[str] = "Tự do"
    sport: Optional[str] = "Môn khác"
    country: Optional[str] = "Quốc tế"
    aliases: Optional[str] = ""

class PlayerAddRequest(BaseModel):
    player_name: Optional[str] = None
    player_names: Optional[list[str]] = None

@router.get("/candidates")
def get_player_candidates(query: str = Query(...)):
    q = query.strip()
    if not q:
        return {"query": query, "has_ambiguity": False, "candidates": []}
    
    has_ambiguity, candidates = search_athlete_candidates(q)
    return {
        "query": q,
        "has_ambiguity": has_ambiguity,
        "candidates": candidates
    }

@router.post("/add-confirmed")
def add_confirmed_player(payload: AddConfirmedPlayerRequest, db: Session = Depends(get_db)):
    name = payload.name.strip()
    team_name = payload.team.strip() if payload.team else "Tự do"
    sport_name = payload.sport.strip() if payload.sport else "Môn khác"
    country_name = payload.country.strip() if payload.country else "Quốc tế"
    
    # Auto-resolve team if generic
    if team_name in ["Tự do", "Chưa rõ CLB", "LALIGA", "Theo Wikipedia", "MLB", "NBA"] or len(team_name) <= 2:
        try:
            free_info = fetch_free_player_info(name)
            if free_info.get("team_name") and free_info["team_name"] not in ["Tự do", "Chưa rõ CLB", "MLB", "NBA"]:
                team_name = free_info["team_name"]
            if country_name == "Quốc tế" and free_info.get("country_name"):
                country_name = free_info["country_name"]
            if sport_name in ["Môn khác", "Thể thao"] and free_info.get("sport_name"):
                sport_name = free_info["sport_name"]
        except Exception:
            pass

    sport = db.query(Sport).filter(Sport.name.ilike(sport_name)).first()
    if not sport:
        sport = Sport(name=sport_name)
        db.add(sport)
        db.flush()

    nationality = db.query(Nationality).filter(Nationality.name.ilike(country_name)).first()
    if not nationality:
        flag = "🌐"
        tz = "UTC"
        for info in EN_TO_VI_MAP.values():
            if isinstance(info, dict) and info.get("name") == country_name:
                flag = info.get("flag", "🌐")
                tz = info.get("tz", "UTC")
                break
        nationality = Nationality(name=country_name, flag=flag, timezone=tz)
        db.add(nationality)
        db.flush()

    club = db.query(Club).filter(Club.name.ilike(team_name), Club.sport_id == sport.id).first()
    if not club:
        club = Club(name=team_name, sport_id=sport.id, country_id=nationality.id)
        db.add(club)
        db.flush()

    player = db.query(Player).filter(Player.name.ilike(name)).first()
    if not player:
        player = Player(
            name=name,
            sport_id=sport.id,
            country_id=nationality.id,
            club_id=club.id,
            name_aliases=payload.aliases or name
        )
        db.add(player)
        db.commit()
    else:
        player.sport_id = sport.id
        player.country_id = nationality.id
        player.club_id = club.id
        if payload.aliases:
            player.name_aliases = payload.aliases
        db.commit()

    sched = fetch_real_schedule(team_name, sport_name, player_name=name)
    m_name = sched["match_name"] if sched else "Chưa có dữ liệu lịch đấu"
    m_date = sched["match_date"] if sched else None
    m_state = sched.get("match_state", "pre") if sched else "pre"
    m_res = sched.get("match_result") if sched else None
    h_played = sched.get("has_played", False) if sched else False
    ev_id = sched.get("event_id") if sched else None

    stats_info = fetch_player_match_stats(name, sport_name, team_name, event_id=ev_id, match_state=m_state)
    raw_comp = sched.get("competition") if sched else ""
    m_comp = get_tournament_tag(team_name, sport_name, m_name, raw_comp)
    if not m_comp:
        if sport_name in ["Bóng chày", "baseball"]: m_comp = "MLB"
        elif sport_name in ["Bóng rổ", "basketball"]: m_comp = "NBA"
        else: m_comp = raw_comp

    perf = db.query(MatchPerformance).filter(MatchPerformance.player_id == player.id).first()
    if not perf:
        perf = MatchPerformance(
            player_id=player.id,
            match_name=m_name,
            match_date=m_date,
            match_state=m_state,
            match_result=m_res,
            has_played=h_played,
            performance_rating=stats_info.get("rating"),
            player_stats=None,
            impression_tags=", ".join(stats_info.get("tags", [])),
            competition=m_comp
        )
        db.add(perf); db.commit()
    else:
        perf.match_name = m_name
        perf.match_date = m_date
        perf.match_state = m_state
        perf.match_result = m_res
        perf.has_played = h_played
        perf.performance_rating = stats_info.get("rating")
        perf.player_stats = None
        perf.impression_tags = ", ".join(stats_info.get("tags", []))
        perf.competition = m_comp
        db.commit()

    # Pre-warm 30d schedule cache for instantaneous dashboard response
    try:
        fetch_player_upcoming_schedule_30d(team_name, sport_name, player_name=name)
    except Exception:
        pass

    # Scan news for player
    try:
        scan_player_news(db, player.id, player.name)
    except Exception:
        pass

    try:
        from backend.core.routers.dashboard import invalidate_dashboard_cache
        invalidate_dashboard_cache()
    except Exception:
        pass

    return {
        "success": True,
        "message": f"Đã thêm thành công '{name}' ({sport_name} - {team_name} - {country_name})!",
        "player": {
            "id": player.id,
            "name": player.name,
            "team": team_name,
            "sport": sport_name,
            "country": country_name
        }
    }

@router.post("/add")
def add_player(payload: Optional[PlayerAddRequest] = None, name: Optional[str] = Query(None), db: Session = Depends(get_db)):
    names_to_process = []
    if payload:
        if payload.player_names:
            names_to_process.extend([n.strip() for n in payload.player_names if n.strip()])
        if payload.player_name:
            names_to_process.append(payload.player_name.strip())
    if name:
        names_to_process.append(name.strip())

    names_to_process = list(dict.fromkeys([n for n in names_to_process if n]))
    if not names_to_process:
        raise HTTPException(status_code=400, detail="Vui lòng cung cấp ít nhất một tên vận động viên.")

    results = []
    for p_name in names_to_process:
        info = fetch_free_player_info(p_name)
        team_name = info.get("team_name", "Tự do") if info.get("found") else "Tự do"
        sport_name = info.get("sport_name", "Môn khác") if info.get("found") else "Môn khác"
        country_name = info.get("country_name", "Quốc tế") if info.get("found") else "Quốc tế"
        aliases = info.get("aliases", p_name) if info.get("found") else p_name
        
        req = AddConfirmedPlayerRequest(
            name=p_name,
            team=team_name,
            sport=sport_name,
            country=country_name,
            aliases=aliases
        )
        res = add_confirmed_player(req, db)
        results.append(res["player"])

    return {"success": True, "players": results}

@router.delete("/{player_id}")
def delete_player(player_id: int, db: Session = Depends(get_db)):
    player = db.query(Player).filter(Player.id == player_id).first()
    if not player:
        raise HTTPException(status_code=404, detail="Không tìm thấy cầu thủ cần xóa.")
    player_name = player.name
    db.query(MatchPerformance).filter(MatchPerformance.player_id == player_id).delete()
    db.query(PlayerNews).filter(PlayerNews.player_id == player_id).delete()
    db.delete(player)
    db.commit()

    # Dọn dẹp tự động các CLB, Quốc tịch, Môn thể thao không còn cầu thủ nào tham gia
    cleanup_orphans(db)

    try:
        from backend.core.routers.dashboard import invalidate_dashboard_cache
        invalidate_dashboard_cache()
    except Exception:
        pass

    return {"success": True, "message": f"Đã xóa thành công cầu thủ '{player_name}' khỏi hệ thống."}

from backend.core.services.batch_sync_service import execute_batched_sync

@router.post("/sync")
def sync_all_players(db: Session = Depends(get_db)):
    players = db.query(Player).all()
    count = len(players)
    if count == 0:
        return {"success": True, "message": "Chưa có cầu thủ nào để cập nhật.", "count": 0}

    SCHEDULE_CACHE.clear()
    SCHEDULE_30D_CACHE.clear()

    # Sử dụng tiến trình kiến trúc gom cụm (Team-Level Batching & Bulk Scoreboards)
    res = execute_batched_sync(db, update_news=True)
    return {"success": True, "message": f"Đã cập nhật đồng bộ tối ưu cho {count} cầu thủ!", "count": count}

@router.get("/check-nationality")
def check_player_nationality(name: str):
    info = fetch_free_player_info(name)
    return {
        "name": name,
        "country": info.get("country_name", "Quốc tế"),
        "flag": info.get("country_flag", "🌐"),
        "team": info.get("team_name", "Tự do"),
        "sport": info.get("sport_name", "Môn khác")
    }

