from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
import concurrent.futures
import datetime

from backend.core.db.session import get_db
from backend.core.db.models import Player, Sport, Nationality, Club, MatchPerformance, PlayerNews
from backend.core.config import EN_TO_VI_MAP, normalize_player_name
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
    league: Optional[str] = None
    espn_team_id: Optional[str] = None
    espn_league_slug: Optional[str] = None

class ChangePlayerTeamRequest(BaseModel):
    team: str
    sport: Optional[str] = None
    league: Optional[str] = None
    espn_team_id: Optional[str] = None
    espn_league_slug: Optional[str] = None

class PlayerAddRequest(BaseModel):
    player_name: Optional[str] = None
    player_names: Optional[list[str]] = None

@router.get("/team-options")
def get_team_options(query: str = Query(...), sport: Optional[str] = Query(None)):
    q = query.strip()
    if not q:
        return {"query": query, "count": 0, "teams": []}
    from backend.modules.players.services.team_service import search_team_options
    teams = search_team_options(q, sport)
    return {"query": q, "count": len(teams), "teams": teams}

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
        club = Club(name=team_name, sport_id=sport.id, country_id=nationality.id, api_team_id=payload.espn_team_id)
        db.add(club)
        db.flush()
    elif payload.espn_team_id:
        club.api_team_id = payload.espn_team_id
        db.flush()

    # Kiểm tra trùng lặp thông minh: So khớp cả tên nguyên bản lẫn tên đã chuẩn hóa loại bỏ dấu thanh/macron
    norm_new = normalize_player_name(name)
    all_players = db.query(Player).filter(Player.sport_id == sport.id).all()
    player = next((p for p in all_players if normalize_player_name(p.name) == norm_new), None)
    if not player:
        player = db.query(Player).filter(Player.name.ilike(name)).first()

    if not player:
        player = Player(
            name=name,
            sport_id=sport.id,
            country_id=nationality.id,
            club_id=club.id,
            name_aliases=payload.aliases or name,
            api_team_id=payload.espn_team_id
        )
        db.add(player)
        db.commit()
    else:
        player.sport_id = sport.id
        player.country_id = nationality.id
        player.club_id = club.id
        if payload.espn_team_id:
            player.api_team_id = payload.espn_team_id
        # Bổ sung alias mới nếu tên nhập vào có cách viết khác nhau (như Ko Itakura vs Kō Itakura)
        existing_aliases = [a.strip() for a in (player.name_aliases or "").split(",") if a.strip()]
        if name not in existing_aliases and name.lower() != player.name.lower():
            existing_aliases.append(name)
        if payload.aliases:
            for al in payload.aliases.split(","):
                al_s = al.strip()
                if al_s and al_s not in existing_aliases:
                    existing_aliases.append(al_s)
        player.name_aliases = ", ".join(existing_aliases)
        db.commit()

    if payload.espn_team_id:
        from backend.modules.players.services.espn_service import ESPN_TEAM_INFO_CACHE, SPORT_TO_ESPN, SCHEDULE_CACHE, SCHEDULE_30D_CACHE
        target_espn_sport = SPORT_TO_ESPN.get(sport_name, "soccer")
        ESPN_TEAM_INFO_CACHE[(team_name.lower().strip(), sport_name.lower().strip())] = {
            "id": str(payload.espn_team_id),
            "uid": f"s:custom~t:{payload.espn_team_id}",
            "name": team_name,
            "sport": target_espn_sport,
            "league": payload.espn_league_slug or ""
        }
        SCHEDULE_CACHE.clear()
        SCHEDULE_30D_CACHE.clear()

    recent_30d = []
    try:
        recent_30d = fetch_player_upcoming_schedule_30d(team_name, sport_name, player_name=name)
    except Exception:
        pass

    # Đồng bộ toàn bộ lịch sử thi đấu trong quá khứ (mùa giải) và lịch tương lai cho VĐV
    try:
        from backend.modules.players.services.match_sync_service import sync_player_matches_history
        sync_player_matches_history(
            player_id=player.id,
            player_name=name,
            team_name=team_name,
            sport_name=sport_name,
            league=payload.league.strip() if payload.league else None,
            espn_team_id=payload.espn_team_id,
            db=db,
            force_refresh=True
        )
    except Exception as e:
        print(f"Error syncing match history for {name}: {e}")

    try:
        from backend.core.routers.dashboard import invalidate_dashboard_cache
        invalidate_dashboard_cache()
    except Exception:
        pass

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

@router.post("/{player_id}/change-team")
def change_player_team(player_id: int, payload: ChangePlayerTeamRequest, db: Session = Depends(get_db)):
    player = db.query(Player).filter(Player.id == player_id).first()
    if not player:
        raise HTTPException(status_code=404, detail="Không tìm thấy vận động viên.")

    new_team_name = payload.team.strip()
    new_sport_name = payload.sport.strip() if payload.sport else player.sport_name
    new_league = payload.league.strip() if payload.league else ""

    sport = db.query(Sport).filter(Sport.name.ilike(new_sport_name)).first()
    if not sport:
        sport = Sport(name=new_sport_name)
        db.add(sport)
        db.flush()
    player.sport_id = sport.id

    club = db.query(Club).filter(Club.name.ilike(new_team_name), Club.sport_id == sport.id).first()
    if not club:
        club = Club(name=new_team_name, sport_id=sport.id, country_id=player.country_id, api_team_id=payload.espn_team_id)
        db.add(club)
        db.flush()
    elif payload.espn_team_id:
        club.api_team_id = payload.espn_team_id
        db.flush()
    player.club_id = club.id
    if payload.espn_team_id:
        player.api_team_id = payload.espn_team_id

    if payload.espn_team_id:
        from backend.modules.players.services.espn_service import ESPN_TEAM_INFO_CACHE, SPORT_TO_ESPN, SCHEDULE_CACHE, SCHEDULE_30D_CACHE
        target_espn_sport = SPORT_TO_ESPN.get(new_sport_name, "soccer")
        ESPN_TEAM_INFO_CACHE[(new_team_name.lower().strip(), new_sport_name.lower().strip())] = {
            "id": str(payload.espn_team_id),
            "uid": f"s:custom~t:{payload.espn_team_id}",
            "name": new_team_name,
            "sport": target_espn_sport,
            "league": payload.espn_league_slug or ""
        }
        SCHEDULE_CACHE.clear()
        SCHEDULE_30D_CACHE.clear()

    # Xóa lịch thi đấu tương lai chưa diễn ra của CLB cũ
    db.query(MatchPerformance).filter(
        MatchPerformance.player_id == player.id,
        MatchPerformance.match_state == "pre"
    ).delete()
    db.commit()

    # Đồng bộ toàn bộ lịch sử thi đấu của CLB mới (bao gồm cả các trận đã đấu trong mùa và lịch sắp tới)
    try:
        from backend.modules.players.services.match_sync_service import sync_player_matches_history
        sync_player_matches_history(
            player_id=player.id,
            player_name=player.name,
            team_name=new_team_name,
            sport_name=new_sport_name,
            league=new_league or None,
            espn_team_id=payload.espn_team_id,
            db=db,
            force_refresh=True
        )
    except Exception as e:
        print(f"Error syncing match history on change team for {player.name}: {e}")

    m_comp = new_league or ""

    try:
        fetch_player_upcoming_schedule_30d(new_team_name, new_sport_name, player_name=player.name, force_refresh=True)
    except Exception:
        pass

    try:
        from backend.core.routers.dashboard import invalidate_dashboard_cache
        invalidate_dashboard_cache()
    except Exception:
        pass

    return {
        "success": True,
        "message": f"Đã chuyển CLB cho '{player.name}' sang '{new_team_name}' ({m_comp or 'Đang cập nhật'})!",
        "player": {
            "id": player.id,
            "name": player.name,
            "team": new_team_name,
            "sport": new_sport_name,
            "competition": m_comp
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

