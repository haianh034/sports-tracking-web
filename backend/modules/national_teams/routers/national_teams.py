from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel

from backend.core.db.session import get_db
from backend.core.db.models import NationalTeam, NationalTeamNews, Sport, Nationality
from backend.modules.national_teams.services.national_teams_service import (
    get_national_teams_dashboard_data,
    fetch_national_team_schedule,
    fetch_national_team_news_feed,
    get_catalog_with_status,
    search_national_teams_catalog,
    add_team_from_catalog,
    NATIONAL_TEAMS_CATALOG
)

router = APIRouter(prefix="/api/national-teams", tags=["national_teams"])

class AddNationalTeamRequest(BaseModel):
    name: str
    short_name: Optional[str] = None
    nickname: Optional[str] = None
    sport: str
    country: str
    tier: Optional[str] = "Senior"
    gender: Optional[str] = "Men"
    flag: Optional[str] = "🌐"
    search_query: Optional[str] = None
    description: Optional[str] = None
    api_team_id: Optional[str] = None

class AddFromCatalogRequest(BaseModel):
    id_code: str

@router.get("/catalog")
def list_catalog(db: Session = Depends(get_db)):
    """Returns official Japan & Korea national/youth teams catalog with added status."""
    return get_catalog_with_status(db)

@router.get("/search")
def search_teams(query: str = Query("", description="Từ khóa tìm kiếm"), db: Session = Depends(get_db)):
    """Searches official catalog and teams."""
    return search_national_teams_catalog(query, db)

@router.post("/add-from-catalog")
def add_team_catalog(payload: AddFromCatalogRequest, db: Session = Depends(get_db)):
    """Adds a team directly from the verified catalog."""
    try:
        team = add_team_from_catalog(payload.id_code, db)
        return {"success": True, "team_id": team.id, "name": team.name}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("")
def list_national_teams(
    country: Optional[str] = Query(None),
    sport: Optional[str] = Query(None),
    tier: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    return get_national_teams_dashboard_data(db, country=country, sport=sport, tier=tier)

@router.get("/{team_id}")
def get_national_team_detail(team_id: int, db: Session = Depends(get_db)):
    team = db.query(NationalTeam).filter(NationalTeam.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Không tìm thấy đội tuyển")

    matches = fetch_national_team_schedule(team)
    news = fetch_national_team_news_feed(team, db)

    upcoming_30d = [m for m in matches if m.get("diff_days", -1) >= 0 and m.get("diff_days", 999) <= 30 and not m.get("is_past")]

    return {
        "id": team.id,
        "name": team.name,
        "short_name": team.short_name,
        "nickname": team.nickname,
        "sport": team.sport_name,
        "country": team.country_name,
        "flag": team.flag,
        "tier": team.tier,
        "gender": team.gender,
        "description": team.description,
        "upcoming_30d": upcoming_30d,
        "all_matches": matches,
        "news": [
            {
                "title": n.title,
                "url": n.source_url,
                "news_type": n.news_type,
                "published_at": n.published_at.isoformat()
            }
            for n in news
        ]
    }

@router.post("")
def add_custom_national_team(payload: AddNationalTeamRequest, db: Session = Depends(get_db)):
    sport = db.query(Sport).filter(Sport.name.ilike(payload.sport)).first()
    if not sport:
        sport = Sport(name=payload.sport)
        db.add(sport)
        db.flush()

    nat = db.query(Nationality).filter(Nationality.name.ilike(payload.country)).first()
    if not nat:
        nat = Nationality(name=payload.country, flag=payload.flag or "🌐")
        db.add(nat)
        db.flush()

    matched_catalog = next(
        (c for c in NATIONAL_TEAMS_CATALOG if c["name"].lower() == payload.name.lower() or 
         (c["sport"].lower() == payload.sport.lower() and c["country"].lower() == payload.country.lower() and c["tier"].lower() == (payload.tier or "Senior").lower() and c.get("gender", "Men").lower() == (payload.gender or "Men").lower())),
        None
    )
    api_team_id = payload.api_team_id or (matched_catalog.get("api_team_id") if matched_catalog else None)
    flag = payload.flag or (matched_catalog.get("flag") if matched_catalog else nat.flag) or "🌐"
    search_query = payload.search_query or (matched_catalog.get("query_native") if matched_catalog else None) or f"{payload.name} sport news"
    description = payload.description or (matched_catalog.get("description") if matched_catalog else f"Đội tuyển {payload.name}")

    team = NationalTeam(
        name=payload.name,
        short_name=payload.short_name or payload.name,
        nickname=payload.nickname or (matched_catalog.get("nickname") if matched_catalog else None),
        sport_id=sport.id,
        country_id=nat.id,
        tier=payload.tier or (matched_catalog.get("tier") if matched_catalog else "Senior"),
        gender=payload.gender or (matched_catalog.get("gender") if matched_catalog else "Men"),
        flag=flag,
        search_query=search_query,
        description=description,
        api_team_id=api_team_id
    )
    db.add(team)
    db.commit()
    db.refresh(team)

    fetch_national_team_news_feed(team, db, force_refresh=True)
    fetch_national_team_schedule(team)

    try:
        from backend.core.routers.dashboard import invalidate_dashboard_cache
        invalidate_dashboard_cache()
    except Exception:
        pass

    return {"success": True, "team_id": team.id, "name": team.name}

@router.delete("/{team_id}")
def delete_national_team(team_id: int, db: Session = Depends(get_db)):
    team = db.query(NationalTeam).filter(NationalTeam.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Không tìm thấy đội tuyển")

    db.query(NationalTeamNews).filter(NationalTeamNews.team_id == team.id).delete()
    db.delete(team)
    db.commit()

    try:
        from backend.core.routers.dashboard import invalidate_dashboard_cache
        invalidate_dashboard_cache()
    except Exception:
        pass

    return {"success": True, "message": f"Đã xóa đội tuyển {team.name}"}
