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
from backend.core.services.wiki_service import fetch_free_player_info, build_clean_player_aliases
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
    gender: Optional[str] = "Men"  # "Men" | "Women"

class ChangePlayerTeamRequest(BaseModel):
    team: str
    sport: Optional[str] = None
    league: Optional[str] = None
    espn_team_id: Optional[str] = None
    espn_league_slug: Optional[str] = None
    gender: Optional[str] = None  # "Men" | "Women"

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
    incoming_aliases = [a.strip() for a in (payload.aliases or "").split(",") if a.strip()]
    has_native_incoming = any(not a.isascii() for a in incoming_aliases)
    needs_wiki_team = team_name in ["Tự do", "Chưa rõ CLB", "LALIGA", "Theo Wikipedia", "MLB", "NBA"] or len(team_name) <= 2
    needs_wiki_aliases = len(incoming_aliases) <= 1 or not has_native_incoming

    free_info = {}
    if needs_wiki_team or needs_wiki_aliases or (payload.gender or "Men") == "Men":
        try:
            free_info = fetch_free_player_info(name)
        except Exception:
            free_info = {}

    if needs_wiki_team and free_info.get("found"):
        if free_info.get("team_name") and free_info["team_name"] not in ["Tự do", "Chưa rõ CLB", "MLB", "NBA"]:
            team_name = free_info["team_name"]
        if country_name == "Quốc tế" and free_info.get("country_name"):
            country_name = free_info["country_name"]
        if sport_name in ["Môn khác", "Thể thao"] and free_info.get("sport_name"):
            sport_name = free_info["sport_name"]

    wiki_aliases = [a.strip() for a in (free_info.get("aliases") or "").split(",") if a.strip()] if free_info.get("found") else []
    merged_clean_aliases = build_clean_player_aliases(name, incoming_aliases + wiki_aliases)

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

    gender = (payload.gender or "Men").strip()
    if gender == "Men" and free_info.get("found"):
        if free_info.get("gender") == "Women":
            gender = "Women"
        elif free_info.get("parent_club") and "women" in (free_info.get("parent_club") or "").lower():
            gender = "Women"
        elif free_info.get("team_name") and any(w in (free_info.get("team_name") or "").lower() for w in ["women", "frauen", "femeni", "femenino", " w ", "(nữ)"]):
            gender = "Women"

    club = db.query(Club).filter(Club.name.ilike(team_name), Club.sport_id == sport.id).first()
    if not club:
        club = Club(name=team_name, sport_id=sport.id, country_id=nationality.id, api_team_id=payload.espn_team_id, gender=gender)
        db.add(club)
        db.flush()
    elif payload.espn_team_id:
        club.api_team_id = payload.espn_team_id
        club.gender = gender
        db.flush()
    else:
        club.gender = gender
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
            name_aliases=merged_clean_aliases or name,
            api_team_id=payload.espn_team_id,
            gender=gender
        )
        db.add(player)
        db.commit()
    else:
        player.sport_id = sport.id
        player.country_id = nationality.id
        player.club_id = club.id
        if payload.espn_team_id:
            player.api_team_id = payload.espn_team_id
        player.gender = gender
        existing_aliases = [a.strip() for a in (player.name_aliases or "").split(",") if a.strip()]
        player.name_aliases = build_clean_player_aliases(player.name, existing_aliases + [name] + incoming_aliases + wiki_aliases)
        db.commit()

    if payload.espn_team_id:
        from backend.core.config import resolve_espn_sport_code
        from backend.modules.players.services.espn_service import ESPN_TEAM_INFO_CACHE, SCHEDULE_CACHE, SCHEDULE_30D_CACHE
        target_espn_sport = resolve_espn_sport_code(sport_name) or ""
        if target_espn_sport:
            ESPN_TEAM_INFO_CACHE[(team_name.lower().strip(), sport_name.lower().strip(), gender.lower())] = {
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
        from backend.core.config import resolve_espn_sport_code
        from backend.modules.players.services.espn_service import ESPN_TEAM_INFO_CACHE, SCHEDULE_CACHE, SCHEDULE_30D_CACHE
        target_espn_sport = resolve_espn_sport_code(new_sport_name) or ""
        eff_gender = (payload.gender or getattr(player, "gender", None) or ("Women" if "(nữ)" in new_team_name.lower() or "women" in new_team_name.lower() else "Men")).lower()
        if target_espn_sport:
            ESPN_TEAM_INFO_CACHE[(new_team_name.lower().strip(), new_sport_name.lower().strip(), eff_gender)] = {
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
        _, cands = search_athlete_candidates(p_name)
        if cands:
            best = next((c for c in cands if "(tuyển qg)" not in (c.get("team") or "").lower()), cands[0])
            req = AddConfirmedPlayerRequest(
                name=best.get("name") or p_name,
                team=best.get("team") or "Tự do",
                sport=best.get("sport") or "Môn khác",
                country=best.get("country") or "Quốc tế",
                aliases=best.get("aliases") or p_name,
                league=best.get("team_league") or None,
                espn_team_id=best.get("espn_team_id") or None,
                espn_league_slug=best.get("espn_league_slug") or None,
                gender=best.get("gender") or "Men",
            )
        else:
            info = fetch_free_player_info(p_name)
            team_name = info.get("team_name", "Tự do") if info.get("found") else "Tự do"
            sport_name = info.get("sport_name", "Môn khác") if info.get("found") else "Môn khác"
            country_name = info.get("country_name", "Quốc tế") if info.get("found") else "Quốc tế"
            aliases = info.get("aliases", p_name) if info.get("found") else p_name
            gender = info.get("gender", "Men") if info.get("found") else "Men"

            req = AddConfirmedPlayerRequest(
                name=p_name,
                team=team_name,
                sport=sport_name,
                country=country_name,
                aliases=aliases,
                gender=gender,
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

import concurrent.futures
from backend.core.services.batch_sync_service import execute_batched_sync
from backend.core.db.models import NationalTeam
from backend.core.db.session import SessionLocal

@router.post("/sync")
def sync_all_players(db: Session = Depends(get_db)):
    players = db.query(Player).all()
    national_teams = db.query(NationalTeam).all()
    players_count = len(players)
    nt_count = len(national_teams)
    total_count = players_count + nt_count

    if total_count == 0:
        return {"success": True, "message": "Chưa có vận động viên hoặc đội tuyển nào để cập nhật.", "count": 0}

    # Xóa toàn bộ bộ nhớ đệm lịch thi đấu
    SCHEDULE_CACHE.clear()
    SCHEDULE_30D_CACHE.clear()
    try:
        from backend.modules.national_teams.services.national_teams_service import (
            NATIONAL_TEAM_SCHED_CACHE,
            fetch_national_team_schedule,
            fetch_national_team_news_feed
        )
        NATIONAL_TEAM_SCHED_CACHE.clear()
    except Exception:
        pass

    # 1. Đồng bộ gom cụm tối ưu cho vận động viên
    if players:
        execute_batched_sync(db, update_news=True)

    # 2. Đồng bộ lịch thi đấu và quét tin tức cho các đội tuyển & đội trẻ
    if national_teams:
        def _sync_single_nt(nt_id):
            session = SessionLocal()
            try:
                nt = session.query(NationalTeam).filter(NationalTeam.id == nt_id).first()
                if nt:
                    fetch_national_team_schedule(nt)
                    fetch_national_team_news_feed(nt, session, force_refresh=True)
            except Exception as e:
                print(f"[Sync NT Error] {nt_id}: {e}")
            finally:
                session.close()

        nt_ids = [nt.id for nt in national_teams]
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            list(executor.map(_sync_single_nt, nt_ids))

    try:
        from backend.core.routers.dashboard import invalidate_dashboard_cache
        invalidate_dashboard_cache()
    except Exception:
        pass

    return {
        "success": True,
        "message": f"Đã cập nhật đồng bộ thành công {players_count} vận động viên và {nt_count} đội tuyển & đội trẻ!",
        "count": total_count,
        "players_count": players_count,
        "national_teams_count": nt_count
    }

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

