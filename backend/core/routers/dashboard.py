from fastapi import APIRouter, Depends, Query, Request, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import text
from dataclasses import dataclass
import os
import datetime
import json
import concurrent.futures
import urllib.parse
import re
import time
import logging
import threading

logger = logging.getLogger("uvicorn.error")

_DASHBOARD_BUILD_LOCK = threading.Lock()
_HYDRATION_LOCK = threading.Lock()
_IS_HYDRATING = False

@dataclass(slots=True)
class FastNewsItem:
    title: str
    source_url: str
    news_type: str
    region: str
    published_at: datetime.datetime
    published_at_iso: str

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
    MATCH_STATS_CACHE, get_player_official_injury, is_player_retired
)
from backend.modules.players.services.sports_service import (
    format_player_stats_and_tags,
    get_tournament_tag,
    extract_round_stage_tag,
    extract_match_outcome_tag,
    resolve_team_league,
)
from backend.modules.national_teams.services.national_teams_service import evaluate_national_team_callup
from backend.core.services.live_score_service import get_live_scores_map
from backend.modules.national_teams.services.national_teams_service import (
    fetch_national_team_schedule, fetch_national_team_news_feed,
    format_national_team_match_tags, get_national_team_tournament_tag
)

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="frontend/templates")

_DASHBOARD_CACHE = {}
_DASHBOARD_CACHE_TTL = 900.0  # 15 minutes (900s) for lightning fast reloads
_DASHBOARD_SNAPSHOT_FILE = os.path.join(os.path.dirname(__file__), "dashboard_snapshot_cache.json")
_SNAPSHOT_LOCK = threading.Lock()
_SNAPSHOT_CHECKED_ON_BOOT = False

def _save_dashboard_snapshot(result_data: dict):
    if not result_data:
        return
    def _write_task(payload_copy):
        if not _SNAPSHOT_LOCK.acquire(blocking=False):
            return
        try:
            wrapper = {
                "saved_ts": datetime.datetime.now().timestamp(),
                "today_date_vn": payload_copy.get("today_date_vn"),
                "data": payload_copy
            }
            tmp_file = _DASHBOARD_SNAPSHOT_FILE + ".tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(wrapper, f, ensure_ascii=False)
            os.replace(tmp_file, _DASHBOARD_SNAPSHOT_FILE)
        except Exception as e:
            logger.warning(f"[Snapshot] Lỗi ghi snapshot dashboard: {e}")
        finally:
            _SNAPSHOT_LOCK.release()
    threading.Thread(target=_write_task, args=(result_data,), daemon=True).start()

def _load_dashboard_snapshot_if_available() -> bool:
    """
    Nạp snapshot dashboard từ đĩa nếu có trong cùng ngày VN (tối đa 12h).
    Giúp mở app / reload / restart server hiển thị tức thì trong < 50ms (Stale-While-Revalidate).
    """
    global _SNAPSHOT_CHECKED_ON_BOOT
    if _SNAPSHOT_CHECKED_ON_BOOT:
        return False
    _SNAPSHOT_CHECKED_ON_BOOT = True

    if not os.path.exists(_DASHBOARD_SNAPSHOT_FILE):
        return False

    try:
        now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        today_str_vn = (now_utc + datetime.timedelta(hours=7)).strftime("%Y-%m-%d")
        now_ts = datetime.datetime.now().timestamp()

        with open(_DASHBOARD_SNAPSHOT_FILE, "r", encoding="utf-8") as f:
            wrapper = json.load(f)

        saved_ts = wrapper.get("saved_ts", 0)
        saved_date = wrapper.get("today_date_vn")
        snap_data = wrapper.get("data")

        if not snap_data or not saved_ts:
            return False

        # Chỉ dùng lại snapshot của cùng ngày Việt Nam (hoặc < 12 tiếng)
        if saved_date != today_str_vn or (now_ts - saved_ts) > 43200:
            return False

        is_stale = (now_ts - saved_ts) > _DASHBOARD_CACHE_TTL
        all_full_key = ("", "", None, None, "all", True)
        all_partial_key = ("", "", None, None, "all", False)
        empty_full_key = ("", "", None, None, "", True)
        empty_partial_key = ("", "", None, None, "", False)

        if not is_stale and snap_data.get("is_full_load"):
            _DASHBOARD_CACHE[all_full_key] = (saved_ts, snap_data)
            _DASHBOARD_CACHE[empty_full_key] = (saved_ts, snap_data)
            _DASHBOARD_CACHE[all_partial_key] = (saved_ts, snap_data)
            _DASHBOARD_CACHE[empty_partial_key] = (saved_ts, snap_data)
        else:
            # Stale hoặc chưa full: đặt vào partial cache để trả về ngay tức thì (<50ms),
            # đồng thời gắn is_full_load=False để kích hoạt background hydration làm mới ngầm!
            stale_copy = dict(snap_data)
            stale_copy["is_full_load"] = False
            _DASHBOARD_CACHE[all_partial_key] = (now_ts, stale_copy)
            _DASHBOARD_CACHE[empty_partial_key] = (now_ts, stale_copy)

        logger.info(f"==> [Snapshot] Nạp tức thì dashboard từ ổ đĩa (tuổi: {int(now_ts - saved_ts)}s, stale={is_stale})")
        return True
    except Exception as e:
        logger.warning(f"[Snapshot] Lỗi đọc snapshot dashboard: {e}")
        return False

def _filter_cached_dashboard(base_data: dict, entity_type: str = None) -> dict:
    if not entity_type or entity_type == "all":
        return base_data

    target_type = "player" if entity_type == "player" else "national_team"
    
    # Lọc danh sách vận động viên / đội tuyển theo đúng entity_type
    filtered_active = [p for p in base_data.get("active_players", []) if p.get("entity_type") == target_type]
    filtered_upcoming = [p for p in base_data.get("upcoming_players", []) if p.get("entity_type") == target_type]
    filtered_no_match = [p for p in base_data.get("no_match_players", []) if p.get("entity_type") == target_type]
    filtered_schedule = [p for p in base_data.get("schedule_players", []) if p.get("entity_type") == target_type]

    # Tính toán lại môn và quốc tịch active
    active_sports_set = {p.get("sport") for p in filtered_schedule if p.get("sport") and p.get("sport") != "Không rõ"}
    active_countries_set = {p.get("country") for p in filtered_schedule if p.get("country") and p.get("country") != "Không rõ"}

    # Tính toán lại calendar_counts cho đối tượng tương ứng
    calendar_counts = {}
    for p_item in (filtered_active + filtered_upcoming + filtered_no_match):
        p_matches = p_item.get("all_matches") or p_item.get("details", {}).get("all_matches", [])
        seen_dates = set()
        for m in p_matches:
            d_key = m.get("date_only_vn")
            if not d_key and m.get("match_date_utc"):
                try:
                    dt_utc = datetime.datetime.fromisoformat(m["match_date_utc"].replace("Z", ""))
                    d_key = (dt_utc + datetime.timedelta(hours=7)).strftime("%Y-%m-%d")
                except Exception:
                    pass
            if d_key and d_key not in seen_dates:
                seen_dates.add(d_key)
                calendar_counts[d_key] = calendar_counts.get(d_key, 0) + 1

    # Giữ nguyên đầy đủ dải ngày từ base_data
    for k in base_data.get("calendar_counts", {}):
        if k not in calendar_counts:
            calendar_counts[k] = 0

    return {
        "today_date_vn": base_data.get("today_date_vn"),
        "server_time_vn": base_data.get("server_time_vn"),
        "server_timestamp": base_data.get("server_timestamp"),
        "server_time_utc": base_data.get("server_time_utc"),
        "active_players": filtered_active,
        "upcoming_players": filtered_upcoming,
        "no_match_players": filtered_no_match,
        "schedule_players": filtered_schedule,
        "calendar_counts": calendar_counts,
        "sports_list": [{"name": s} for s in sorted(active_sports_set)],
        "countries_list": [{"name": c} for c in sorted(active_countries_set)],
        "total_players": base_data.get("total_players", 0),
        "total_national_teams": base_data.get("total_national_teams", 0),
        "total_all": base_data.get("total_all", 0),
        "is_full_load": base_data.get("is_full_load", False)
    }

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
    global _SNAPSHOT_CHECKED_ON_BOOT
    _DASHBOARD_CACHE.clear()
    _SNAPSHOT_CHECKED_ON_BOOT = False
    try:
        if os.path.exists(_DASHBOARD_SNAPSHOT_FILE):
            os.remove(_DASHBOARD_SNAPSHOT_FILE)
    except Exception:
        pass

@router.get("/", response_class=HTMLResponse)
def read_root(request: Request, db: Session = Depends(get_db)):
    all_db_players = db.query(Player).options(joinedload(Player.sport), joinedload(Player.nationality)).all()
    all_db_national_teams = db.query(NationalTeam).options(joinedload(NationalTeam.sport), joinedload(NationalTeam.nationality)).all()
    
    active_sports = {p.sport_name for p in all_db_players if p.sport_name and p.sport_name != "Không rõ"}
    active_sports.update({t.sport_name for t in all_db_national_teams if t.sport_name and t.sport_name != "Không rõ"})
    
    active_countries = {p.country_name for p in all_db_players if p.country_name and p.country_name != "Không rõ"}
    active_countries.update({t.country_name for t in all_db_national_teams if t.country_name and t.country_name != "Không rõ"})

    app_js_path = os.path.join("frontend", "static", "js", "app.js")
    app_version = int(os.path.getmtime(app_js_path)) if os.path.exists(app_js_path) else int(time.time())

    response = templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "sports": sorted(active_sports),
            "countries": sorted(active_countries),
            "app_version": app_version
        }
    )
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

from typing import Optional

@router.get("/api/dashboard")
def get_dashboard_data(
    sport: Optional[str] = None,
    country: Optional[str] = None,
    sport_id: Optional[int] = None,
    country_id: Optional[int] = None,
    entity_type: Optional[str] = Query(None, description="'all', 'player', or 'national_team'"),
    full: Optional[bool] = Query(False, description="True for phase-2 full hydration (historical & deep future)"),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db)
):
    clean_sport = sport if isinstance(sport, str) else None
    clean_country = country if isinstance(country, str) else None
    clean_sport_id = sport_id if isinstance(sport_id, int) else None
    clean_country_id = country_id if isinstance(country_id, int) else None
    clean_entity_type = entity_type if isinstance(entity_type, str) else None

    if not _DASHBOARD_CACHE:
        _load_dashboard_snapshot_if_available()

    cache_key_full = (
        (clean_sport or "").strip().lower(),
        (clean_country or "").strip().lower(),
        clean_sport_id,
        clean_country_id,
        (clean_entity_type or "").strip().lower(),
        True
    )
    cache_key_partial = (
        (clean_sport or "").strip().lower(),
        (clean_country or "").strip().lower(),
        clean_sport_id,
        clean_country_id,
        (clean_entity_type or "").strip().lower(),
        False
    )
    now_ts = datetime.datetime.now().timestamp()

    # 1. Nếu bản Full đã sẵn sàng trong cache, luôn trả về ngay bản Full (0ms)
    if cache_key_full in _DASHBOARD_CACHE:
        c_ts, c_data = _DASHBOARD_CACHE[cache_key_full]
        if now_ts - c_ts < _DASHBOARD_CACHE_TTL:
            return c_data

    # Tối ưu hóa chuyển tab siêu tốc (0.01s): Nếu đã có cache của 'all', trích xuất nhanh
    base_all_full_key = (
        (clean_sport or "").strip().lower(),
        (clean_country or "").strip().lower(),
        clean_sport_id,
        clean_country_id,
        "all",
        True
    )
    base_all_partial_key = (
        (clean_sport or "").strip().lower(),
        (clean_country or "").strip().lower(),
        clean_sport_id,
        clean_country_id,
        "all",
        False
    )
    if clean_entity_type in ["player", "national_team"]:
        for pot_k in [base_all_full_key, ((clean_sport or "").strip().lower(), (clean_country or "").strip().lower(), clean_sport_id, clean_country_id, "", True)]:
            if pot_k in _DASHBOARD_CACHE:
                base_ts, base_data = _DASHBOARD_CACHE[pot_k]
                if now_ts - base_ts < _DASHBOARD_CACHE_TTL:
                    derived_data = _filter_cached_dashboard(base_data, clean_entity_type)
                    _DASHBOARD_CACHE[cache_key_full] = (base_ts, derived_data)
                    _DASHBOARD_CACHE[cache_key_partial] = (base_ts, derived_data)
                    return derived_data

    # 2. Nếu người dùng gọi full=True: Cần tính toán hoặc đợi bản Full
    if full:
        with _DASHBOARD_BUILD_LOCK:
            now_ts = datetime.datetime.now().timestamp()
            if cache_key_full in _DASHBOARD_CACHE:
                c_ts, c_data = _DASHBOARD_CACHE[cache_key_full]
                if now_ts - c_ts < _DASHBOARD_CACHE_TTL:
                    return c_data

            full_data = _compute_dashboard_data(
                db=db,
                sport=sport,
                country=country,
                sport_id=sport_id,
                country_id=country_id,
                clean_sport=clean_sport,
                clean_country=clean_country,
                clean_sport_id=clean_sport_id,
                clean_country_id=clean_country_id,
                clean_entity_type=clean_entity_type,
                cache_key=cache_key_full,
                is_full_load=True
            )
            _DASHBOARD_CACHE[cache_key_partial] = (now_ts, full_data)
            return full_data

    # 3. Mặc định full=False (Giai đoạn 1: Khung D-7 đến D+30 siêu nhanh)
    if cache_key_partial in _DASHBOARD_CACHE:
        c_ts, c_data = _DASHBOARD_CACHE[cache_key_partial]
        if now_ts - c_ts < _DASHBOARD_CACHE_TTL:
            if background_tasks and cache_key_full not in _DASHBOARD_CACHE:
                background_tasks.add_task(
                    _run_background_full_hydration,
                    sport, country, sport_id, country_id,
                    clean_sport, clean_country, clean_sport_id, clean_country_id,
                    clean_entity_type, cache_key_full, cache_key_partial
                )
            return c_data

    # Chuyển tab nhanh từ partial all nếu có
    if clean_entity_type in ["player", "national_team"]:
        for pot_k in [base_all_partial_key, ((clean_sport or "").strip().lower(), (clean_country or "").strip().lower(), clean_sport_id, clean_country_id, "", False)]:
            if pot_k in _DASHBOARD_CACHE:
                base_ts, base_data = _DASHBOARD_CACHE[pot_k]
                if now_ts - base_ts < _DASHBOARD_CACHE_TTL:
                    derived_data = _filter_cached_dashboard(base_data, clean_entity_type)
                    _DASHBOARD_CACHE[cache_key_partial] = (base_ts, derived_data)
                    if background_tasks and cache_key_full not in _DASHBOARD_CACHE:
                        background_tasks.add_task(
                            _run_background_full_hydration,
                            sport, country, sport_id, country_id,
                            clean_sport, clean_country, clean_sport_id, clean_country_id,
                            clean_entity_type, cache_key_full, cache_key_partial
                        )
                    return derived_data

    # Chống thundering herd (stampede) trên Render: Chỉ 1 luồng build data tại 1 thời điểm
    with _DASHBOARD_BUILD_LOCK:
        now_ts = datetime.datetime.now().timestamp()
        if cache_key_partial in _DASHBOARD_CACHE:
            c_ts, c_data = _DASHBOARD_CACHE[cache_key_partial]
            if now_ts - c_ts < _DASHBOARD_CACHE_TTL:
                return c_data

        partial_data = _compute_dashboard_data(
            db=db,
            sport=sport,
            country=country,
            sport_id=sport_id,
            country_id=country_id,
            clean_sport=clean_sport,
            clean_country=clean_country,
            clean_sport_id=clean_sport_id,
            clean_country_id=clean_country_id,
            clean_entity_type=clean_entity_type,
            cache_key=cache_key_partial,
            is_full_load=False
        )

        # Kích hoạt nạp ngầm Giai đoạn 2 (Toàn bộ quá khứ sâu & tương lai xa)
        if background_tasks and cache_key_full not in _DASHBOARD_CACHE:
            background_tasks.add_task(
                _run_background_full_hydration,
                sport, country, sport_id, country_id,
                clean_sport, clean_country, clean_sport_id, clean_country_id,
                clean_entity_type, cache_key_full, cache_key_partial
            )

        return partial_data


def _run_background_full_hydration(
    sport, country, sport_id, country_id,
    clean_sport, clean_country, clean_sport_id, clean_country_id,
    clean_entity_type, cache_key_full, cache_key_partial
):
    global _IS_HYDRATING
    with _HYDRATION_LOCK:
        if _IS_HYDRATING:
            return
        _IS_HYDRATING = True

    try:
        logger.info("==> [Background Hydration] Bắt đầu nạp ngầm Giai đoạn 2 (Toàn bộ quá khứ & tương lai)...")
        from backend.core.db.session import SessionLocal
        db_bg = SessionLocal()
        try:
            full_data = _compute_dashboard_data(
                db=db_bg,
                sport=sport,
                country=country,
                sport_id=sport_id,
                country_id=country_id,
                clean_sport=clean_sport,
                clean_country=clean_country,
                clean_sport_id=clean_sport_id,
                clean_country_id=clean_country_id,
                clean_entity_type=clean_entity_type,
                cache_key=cache_key_full,
                is_full_load=True
            )
            now_ts = datetime.datetime.now().timestamp()
            _DASHBOARD_CACHE[cache_key_full] = (now_ts, full_data)
            _DASHBOARD_CACHE[cache_key_partial] = (now_ts, full_data)
            logger.info("==> [Background Hydration] Nạp ngầm Giai đoạn 2 thành công! Đã sẵn sàng phục vụ 100% dữ liệu.")
        finally:
            db_bg.close()
    except Exception as e:
        logger.warning(f"[Background Hydration] Lỗi trong quá trình nạp ngầm Giai đoạn 2: {e}")
    finally:
        with _HYDRATION_LOCK:
            _IS_HYDRATING = False


def _compute_dashboard_data(
    db: Session,
    sport: Optional[str],
    country: Optional[str],
    sport_id: Optional[int],
    country_id: Optional[int],
    clean_sport: Optional[str],
    clean_country: Optional[str],
    clean_sport_id: Optional[int],
    clean_country_id: Optional[int],
    clean_entity_type: Optional[str],
    cache_key: tuple,
    is_full_load: bool = False
) -> dict:
    t_start = time.time()
    logger.info("==> [API] Bắt đầu nạp bảng theo dõi (get_dashboard_data)...")
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
    
    now_ts = datetime.datetime.now().timestamp()
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
    db_past_perfs_by_player = {}
    for perf in all_db_perfs:
        ev_s = str(perf.event_id or "")
        if ev_s.startswith("struct_nt_"):
            continue
        if perf.event_id:
            perf_by_player_event[(perf.player_id, ev_s)] = perf
        if perf.date_str:
            perf_by_player_date[(perf.player_id, str(perf.date_str))] = perf
        if perf.match_state == "post" and perf.match_date is not None and perf.date_str:
            db_past_perfs_by_player.setdefault(perf.player_id, []).append(perf)

    # Pre-warm ĐTQG schedules memo dictionary to avoid redundant network calls across players
    nt_sched_memo = {}

    # Fetch player career schedules in parallel (supporting club transfer history & national team unified timeline)
    def _fetch_player_career(item):
        p, t_name, s_name, c_name = item
        team_id = p.api_team_id or (p.club.api_team_id if p.club else None)
        p_gender = getattr(p, "gender", "Men") or "Men"
        return p.id, fetch_player_career_schedule(
            player_name=p.name,
            current_team=t_name,
            sport_name=s_name,
            api_team_id=team_id,
            country_name=c_name,
            gender=p_gender,
            nt_sched_cache=nt_sched_memo,
            include_deep_history=is_full_load
        )

    sched_map = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for pid, s_list in ex.map(_fetch_player_career, player_data_tuples):
            sched_map[pid] = s_list

    # Prefetch recent past ESPN event summaries in parallel ONLY if not already locked in DB
    # Giai đoạn 1 (is_full_load=False): Khung D-7 đến D
    # Giai đoạn 2 (is_full_load=True): Toàn bộ mùa giải từ đầu (-300.0 <= diff_d < -0.05)
    from backend.core.config import resolve_espn_sport_code
    diff_lower_limit = -300.0 if is_full_load else -7.0
    unique_past_events = set()
    for p, team_name, sport_name, _ in player_data_tuples:
        espn_sport = resolve_espn_sport_code(sport_name)
        if espn_sport and espn_sport not in {"tennis", "golf", "racing", "mma", "boxing"}:
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

                if not has_in_db and ev_id and diff_lower_limit <= diff_d < -0.05 and not str(ev_id).startswith(("non_espn_", "wtt_", "fs_", "fm_", "espn_ov_")):
                    cache_k = f"{p.name}_{ev_id}_post"
                    if cache_k not in MATCH_STATS_CACHE:
                        unique_past_events.add((espn_sport, str(ev_id)))

    def _prefetch_summary(item):
        espn_sport, ev_id = item
        league = {"soccer": "all", "basketball": "nba", "baseball": "mlb", "hockey": "nhl", "football": "nfl"}.get(espn_sport, "all")
        url = f"https://site.api.espn.com/apis/site/v2/sports/{espn_sport}/{league}/summary?event={ev_id}"
        fetch_espn_summary(url, ev_id)

    if unique_past_events:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            list(ex.map(_prefetch_summary, unique_past_events))

    # Khung 48 giờ chuẩn: Từ 00:00:00 ngày hôm trước đến 23:59:59 ngày hôm nay (tính theo giờ Việt Nam UTC+7)
    yesterday_ict = today_ict - datetime.timedelta(days=1)
    today_win_start_utc = datetime.datetime.combine(yesterday_ict, datetime.time.min) - datetime.timedelta(hours=7)
    today_win_end_utc = datetime.datetime.combine(today_ict, datetime.time.max) - datetime.timedelta(hours=7)
    live_scores = get_live_scores_map()

    # Batch load latest match performance and player news to eliminate per-player DB roundtrips
    today_perf_by_player = {}
    for perf in all_db_perfs:
        p_d_str = perf.date_str
        if not p_d_str and perf.match_date:
            try:
                p_d_str = (perf.match_date + datetime.timedelta(hours=7)).strftime("%Y-%m-%d")
            except Exception:
                pass
        if p_d_str in [today_str_vn, yesterday_ict.strftime("%Y-%m-%d")]:
            today_perf_by_player[perf.player_id] = perf

    # Tải tin tức trong 30 ngày từ database qua SQL nhẹ và map vào FastNewsItem
    cutoff_30d = now_utc - datetime.timedelta(days=30)
    raw_news_rows = db.execute(
        text("SELECT player_id, title, source_url, news_type, region, published_at FROM player_news WHERE published_at >= :c ORDER BY published_at DESC"),
        {"c": cutoff_30d}
    ).fetchall()

    news_by_player = {}
    for r in raw_news_rows:
        p_dt = r[5]
        if isinstance(p_dt, str):
            try:
                p_dt = datetime.datetime.fromisoformat(p_dt)
            except Exception:
                p_dt = None
        iso_str = p_dt.isoformat() if p_dt else None
        news_by_player.setdefault(r[0], []).append(FastNewsItem(r[1], r[2], r[3], r[4] or "US", p_dt, iso_str))

    yesterday_str_vn = yesterday_ict.strftime("%Y-%m-%d")

    for p, team_name, sport_name, country_name in player_data_tuples:
        # Kiểm tra VĐV đã giải nghệ (như Lee Hyun-il): Tự động xếp vào nhóm No Match với nhãn Đã giải nghệ
        if is_player_retired(p.name, team_name):
            all_player_news = list(news_by_player.get(p.id, []))
            country_flag = "🌐"
            for info in EN_TO_VI_MAP.values():
                if isinstance(info, dict) and info.get("name") == country_name:
                    country_flag = info.get("flag", "🌐")
                    break
            no_match_players.append({
                "id": p.id,
                "name": p.name,
                "sport": sport_name,
                "country": country_name,
                "country_flag": country_flag,
                "team": "Đã giải nghệ",
                "next_match": "Đã giải nghệ",
                "next_match_date": "N/A",
                "tags": ["Đã giải nghệ 🎖️"],
                "all_matches": [],
                "upcoming_30d_count": 0,
                "upcoming_30d_matches": [],
                "news_count": len(all_player_news),
                "recent_news": [
                    {"title": n.title, "url": n.source_url, "news_type": n.news_type, "published_at": n.published_at_iso}
                    for n in all_player_news[:10]
                ],
                "entity_type": "player",
                "is_retired": True
            })
            continue

        espn_sport = resolve_espn_sport_code(sport_name)
        all_matches_raw = list(sched_map.get(p.id, []))
        # Merge valid archived past DB matches (retains sliding-window Flashscore/older WTT matches permanently)
        archived_perfs = db_past_perfs_by_player.get(p.id, [])
        if archived_perfs and not is_player_retired(p.name, team_name):
            seen_ev_ids = {str(m.get("event_id")) for m in all_matches_raw if m.get("event_id")}
            seen_date_names = {(str(m.get("date_only_vn") or ""), str(m.get("match_name") or "")) for m in all_matches_raw}
            for ap in archived_perfs:
                ap_ev = str(ap.event_id or "")
                ap_dvn = str(ap.date_str or "")
                ap_name = str(ap.match_name or "")
                if (ap_ev and ap_ev in seen_ev_ids) or ((ap_dvn, ap_name) in seen_date_names):
                    continue
                if not ap.match_date:
                    continue
                # Guard against stale legacy NT placeholders without real event IDs
                if not ap_ev.startswith(("wtt_", "fs_", "fm_", "espn_")) and not ap_ev.isdigit():
                    continue
                dt_vn_ap = ap.match_date + datetime.timedelta(hours=7)
                diff_ap = (ap.match_date - now_utc).total_seconds() / 86400.0
                if ap_ev:
                    seen_ev_ids.add(ap_ev)
                seen_date_names.add((ap_dvn, ap_name))
                all_matches_raw.append({
                    "match_name": ap_name,
                    "raw_match_name": f"{p.name} {ap_name}",
                    "match_date_utc": ap.match_date.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "date_vn": dt_vn_ap.strftime("%d/%m %H:%M"),
                    "date_full_vn": dt_vn_ap.strftime("%d/%m/%Y %H:%M"),
                    "date_only_vn": ap_dvn or dt_vn_ap.strftime("%Y-%m-%d"),
                    "time_only_vn": dt_vn_ap.strftime("%H:%M"),
                    "competition": ap.competition or "",
                    "event_id": ap_ev or None,
                    "match_state": "post",
                    "match_result": ap.match_result,
                    "status_detail": ap.match_result or dt_vn_ap.strftime("%d/%m • %H:%M"),
                    "has_played": bool(ap.has_played),
                    "diff_days": diff_ap,
                    "is_past": True,
                    "player_team": team_name,
                    "player_stats": ap.player_stats,
                    "tags": [t.strip() for t in str(ap.impression_tags or "").split(",") if t.strip()],
                })
            all_matches_raw.sort(key=lambda x: str(x.get("match_date_utc") or ""))
        all_player_news = list(news_by_player.get(p.id, []))
        news_today = [n for n in all_player_news if today_win_start_utc <= n.published_at <= today_win_end_utc]
        
        tz_offset = "UTC"
        country_flag = "🌐"
        for info in EN_TO_VI_MAP.values():
            if isinstance(info, dict) and info.get("name") == country_name:
                tz_offset = info.get("tz", "UTC")
                country_flag = info.get("flag", "🌐")
                break

        # ĐÁNH GIÁ TRIỆU TẬP ĐTQG CHO CÁC TRẬN ĐẤU ĐỘI TUYỂN TRONG KHUNG [-7, +30] NGÀY
        p_off_inj_now = get_player_official_injury(p.name, sport_name)
        p_news_titles_pre = [n.title for n in all_player_news[:15]]
        for m in all_matches_raw:
            is_nt_m = bool(
                m.get("is_national_team")
                or m.get("is_nt_match")
                or str(m.get("event_id") or "").startswith("espn_nt_")
                or "đtqg" in str(m.get("competition") or "").lower()
            )
            diff_m = m.get("diff_days", 999)
            if is_nt_m and -7 <= diff_m <= 30:
                nt_status, nt_tag, nt_reason = evaluate_national_team_callup(
                    p.name,
                    team_name,
                    sport_name,
                    country_name,
                    getattr(p, "gender", "Male") or "Male",
                    nt_match=m,
                    player_news_titles=p_news_titles_pre,
                    official_injury=p_off_inj_now,
                    player_aliases=getattr(p, "name_aliases", None),
                )
                m["nt_callup_status"] = nt_status
                m["nt_callup_tag"] = nt_tag
                m["nt_callup_reason"] = nt_reason

        # Đánh dấu các trận CLB diễn ra trong đợt VĐV đang tập trung ĐTQG (vd: giao hữu CLB giữa kỳ FIFA Days)
        called_up_nt_dts = []
        for m in all_matches_raw:
            if m.get("nt_callup_status") == "called_up" and m.get("match_date_utc"):
                try:
                    called_up_nt_dts.append(datetime.datetime.strptime(m["match_date_utc"][:19], "%Y-%m-%dT%H:%M:%S"))
                except Exception:
                    pass
        if called_up_nt_dts:
            for m in all_matches_raw:
                is_nt_m2 = bool(m.get("is_national_team") or m.get("is_nt_match") or str(m.get("event_id") or "").startswith("espn_nt_"))
                if not is_nt_m2 and m.get("match_date_utc"):
                    try:
                        m_dt2 = datetime.datetime.strptime(m["match_date_utc"][:19], "%Y-%m-%dT%H:%M:%S")
                        if any(-4.0 <= (m_dt2 - nt_dt).total_seconds() / 86400.0 <= 1.0 for nt_dt in called_up_nt_dts):
                            m["absent_due_to_nt_duty"] = True
                    except Exception:
                        pass

        # XÁC ĐỊNH CHÍNH XÁC TRẬN ĐẤU TRONG KHUNG 48H (HÔM NAY VÀ HÔM QUA) TỪ LỊCH ĐẤU THỰC TẾ
        sched_today_match = None
        candidate_matches = []
        for m in all_matches_raw:
            if m.get("nt_callup_status") in ("not_called_up", "injured_withdrawal"):
                continue
            if m.get("absent_due_to_nt_duty") and (m.get("match_state", "pre") == "pre" or not m.get("has_played")):
                continue
            m_dvn = m.get("date_only_vn")
            if not m_dvn and m.get("match_date_utc"):
                try:
                    m_dvn = (datetime.datetime.strptime(m["match_date_utc"][:19], "%Y-%m-%dT%H:%M:%S") + datetime.timedelta(hours=7)).strftime("%Y-%m-%d")
                except Exception:
                    pass
            m_state = m.get("match_state", "pre")
            if m_state == "in":
                candidate_matches.append((0, m))
            elif m_dvn == today_str_vn:
                candidate_matches.append((1, m))
            elif m_dvn == yesterday_str_vn:
                vn_h = 12
                if m.get("match_date_utc"):
                    try:
                        vn_h = (datetime.datetime.strptime(m["match_date_utc"][:19], "%Y-%m-%dT%H:%M:%S") + datetime.timedelta(hours=7)).hour
                    except Exception:
                        pass
                if vn_h >= 18:
                    candidate_matches.append((2, m))  # Tối hôm qua (18h-24h)
                else:
                    candidate_matches.append((3, m))  # Rạng sáng / Sáng hôm qua
        if candidate_matches:
            candidate_matches.sort(key=lambda x: x[0])
            sched_today_match = candidate_matches[0][1]

        # Tìm bản ghi hiệu suất tương ứng trong DB (nếu có)
        match_today = None
        if sched_today_match:
            ev_id_str = str(sched_today_match.get("event_id") or "")
            if ev_id_str:
                match_today = perf_by_player_event.get((p.id, ev_id_str))
            if not match_today and sched_today_match.get("date_only_vn"):
                match_today = perf_by_player_date.get((p.id, str(sched_today_match.get("date_only_vn"))))
        if not match_today:
            match_today = today_perf_by_player.get(p.id)

        in_today_activity = False
        is_within_month = False
        next_match_text = "Chưa có dữ liệu lịch đấu"
        diff_days = 999
        match_date_utc = None
        match_state = "pre"
        match_result = None
        raw_stats = None
        rating = None
        raw_tags = []
        comp_name = ""

        if sched_today_match:
            in_today_activity = True
            is_within_month = True
            diff_days = 0
            next_match_text = sched_today_match.get("match_name") or "Thi đấu hôm nay"
            match_date_utc = sched_today_match.get("match_date_utc")
            match_state = sched_today_match.get("match_state", "pre")
            match_result = sched_today_match.get("match_result")
            comp_name = sched_today_match.get("competition") or ""
            
            if match_today:
                if match_today.performance_rating is not None:
                    rating = match_today.performance_rating
                if match_today.player_stats:
                    raw_stats = match_today.player_stats
                if match_today.impression_tags:
                    raw_tags = [t.strip() for t in match_today.impression_tags.split(",") if t.strip()]
                if match_today.match_result and ("-" in str(match_today.match_result) or not match_result):
                    match_result = match_today.match_result
                if match_today.match_state and match_state == "pre":
                    match_state = match_today.match_state
                elif sched_today_match.get("match_state") in ["post", "in"]:
                    match_state = sched_today_match.get("match_state")

            # Kiểm tra live_scores ngay để lấy tỉ số mới nhất theo thời gian thực
            clean_team_key = (team_name or "").lower().strip()
            live_info = live_scores.get(clean_team_key)
            if not live_info:
                for k in live_scores:
                    if k in clean_team_key or clean_team_key in k:
                        live_info = live_scores[k]
                        break
            if live_info:
                if live_info.get("state") in ["in", "post"]:
                    match_state = live_info["state"]
                if live_info.get("match_result"):
                    match_result = live_info["match_result"]
                if live_info.get("competition"):
                    comp_name = live_info["competition"]

            # Nếu trận trong khung 48h đã kết thúc (post), cập nhật thông số và điểm số chính thức
            # Kể cả cầu thủ KHÔNG ra sân, vẫn phải cập nhật tỉ số và lưu trạng thái đã kết thúc
            if match_state == "post":
                ev_id = sched_today_match.get("event_id")
                try:
                    fresh_stats = fetch_player_match_stats(
                        p.name, sport_name, team_name, event_id=ev_id, match_state="post", news_titles=p_news_titles,
                        match_date_utc=sched_today_match.get("match_date_utc"),
                        match_name=sched_today_match.get("match_name")
                    )
                    if fresh_stats:
                        if fresh_stats.get("match_result") and (not match_result or "-" not in str(match_result)):
                            match_result = fresh_stats.get("match_result")
                        if fresh_stats.get("has_played"):
                            rating = fresh_stats.get("rating")
                            raw_stats = fresh_stats.get("stats_text")
                        if fresh_stats.get("tags"):
                            raw_tags = fresh_stats.get("tags", [])
                        
                        m_perf_date = None
                        if sched_today_match.get("match_date_utc"):
                            try:
                                m_perf_date = datetime.datetime.strptime(sched_today_match["match_date_utc"][:19], "%Y-%m-%dT%H:%M:%S")
                            except Exception:
                                pass
                        
                        has_p = fresh_stats.get("has_played", False)
                        if match_today and match_today.has_played and not has_p:
                            if match_today.performance_rating or (match_today.player_stats and "minutes_played" in str(match_today.player_stats)):
                                has_p = True

                        m_name = sched_today_match.get("match_name") or next_match_text
                        clean_opp = re.sub(r'^(@ |vs |vs\. )', '', m_name or '').strip()
                        if team_name and clean_opp and (is_same_team(team_name, clean_opp) or clean_opp.lower() == team_name.lower()):
                            if match_result and " - " in match_result:
                                res_parts = re.sub(r'\s*\([^)]*\)', '', match_result).split(' - ')
                                if len(res_parts) == 2:
                                    left_t = re.sub(r'\s+\d+$', '', res_parts[0]).strip()
                                    right_t = re.sub(r'^\d+\s+', '', res_parts[1]).strip()
                                    other_t = right_t if is_same_team(team_name, left_t) else left_t
                                    m_name = f"vs {other_t}" if is_same_team(team_name, left_t) else f"@ {other_t}"

                        if not match_today:
                            # Tránh tạo trùng lặp row nếu đã tồn tại bản ghi trong ngày hoặc event_id
                            if sched_today_match.get("date_only_vn"):
                                match_today = db.query(MatchPerformance).filter(
                                    MatchPerformance.player_id == p.id,
                                    MatchPerformance.date_str == str(sched_today_match.get("date_only_vn"))
                                ).first()
                            if not match_today and ev_id:
                                match_today = db.query(MatchPerformance).filter(
                                    MatchPerformance.player_id == p.id,
                                    MatchPerformance.event_id == str(ev_id)
                                ).first()

                        if not match_today:
                            match_today = MatchPerformance(
                                player_id=p.id,
                                match_name=m_name,
                                match_date=m_perf_date or now_utc,
                                match_state=match_state,
                                match_result=match_result,
                                has_played=has_p,
                                performance_rating=rating,
                                player_stats=raw_stats,
                                impression_tags=", ".join(raw_tags),
                                competition=comp_name,
                                event_id=str(ev_id) if ev_id else None,
                                date_str=sched_today_match.get("date_only_vn")
                            )
                            db.add(match_today)
                            db.commit()
                        else:
                            match_today.match_name = m_name
                            if m_perf_date:
                                match_today.match_date = m_perf_date
                            match_today.match_state = match_state
                            if match_result:
                                match_today.match_result = match_result
                            match_today.has_played = has_p
                            match_today.performance_rating = rating
                            match_today.player_stats = raw_stats
                            if raw_tags:
                                match_today.impression_tags = ", ".join(raw_tags)
                            if comp_name:
                                match_today.competition = comp_name
                            if ev_id and not match_today.event_id:
                                match_today.event_id = str(ev_id)
                            db.commit()
                except Exception:
                    pass
        elif match_today and match_today.match_date:
            match_ict = match_today.match_date + datetime.timedelta(hours=7)
            match_date_ict = match_ict.date()
            diff_days = (match_date_ict - today_ict).days
            match_date_utc = match_today.match_date.strftime("%Y-%m-%dT%H:%M:%SZ")
            if diff_days == 0 or diff_days == -1:
                in_today_activity = True
                is_within_month = True
                next_match_text = match_today.match_name
                match_state = getattr(match_today, 'match_state', 'pre') or 'pre'
                match_result = getattr(match_today, 'match_result', None)
                raw_stats = getattr(match_today, 'player_stats', None)
                rating = match_today.performance_rating
                raw_tags = (match_today.impression_tags or "").split(",") if match_today.impression_tags else []
                comp_name = getattr(match_today, 'competition', None) or ""
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

        # Xác định mốc giờ VN và Time Phase
        time_phase = "today"
        time_phase_label = "Hôm nay"
        time_phase_badge = "☀️ Hôm nay"
        match_time_vn = ""
        match_timestamp = 0.0

        target_dt_utc = match_date_utc or (sched_today_match.get("match_date_utc") if sched_today_match else None)
        if not target_dt_utc and match_today and match_today.match_date:
            target_dt_utc = match_today.match_date.strftime("%Y-%m-%dT%H:%M:%SZ")

        if target_dt_utc:
            try:
                m_dt_utc = datetime.datetime.strptime(target_dt_utc[:19], "%Y-%m-%dT%H:%M:%S")
                m_dt_vn = m_dt_utc + datetime.timedelta(hours=7)
                match_timestamp = m_dt_vn.timestamp()
                match_time_vn = m_dt_vn.strftime("%d/%m %H:%M")
                m_date_vn_obj = m_dt_vn.date()
                m_hour_vn = m_dt_vn.hour
                hm_str = m_dt_vn.strftime("%H:%M")

                # Tự động đồng bộ trạng thái nếu giờ thi đấu đã trôi qua mà API/cache vẫn ghi là 'pre'
                if match_state == "pre" and m_dt_utc:
                    time_diff_sec = (now_utc - m_dt_utc).total_seconds()
                    if time_diff_sec >= 7200: # Đã qua hơn 2 tiếng -> Đã kết thúc
                        match_state = "post"
                    elif time_diff_sec >= 0: # Đang trong vòng 2 tiếng sau giờ đá -> Đang thi đấu
                        match_state = "in"

                if match_state == "in":
                    time_phase = "live"
                    time_phase_label = "Đang trực tiếp"
                    time_phase_badge = f"🔴 TRỰC TIẾP • {hm_str}"
                elif m_date_vn_obj == today_ict:
                    time_phase = "today"
                    time_phase_label = "Hôm nay"
                    time_phase_badge = f"☀️ Hôm nay • {hm_str}"
                elif m_date_vn_obj == yesterday_ict:
                    if m_hour_vn >= 18:
                        time_phase = "yesterday_evening"
                        time_phase_label = "Tối hôm qua (18h-24h)"
                        time_phase_badge = f"🌙 Tối qua • {hm_str}"
                    else:
                        time_phase = "yesterday_morning"
                        time_phase_label = "Rạng sáng hôm qua"
                        time_phase_badge = f"⏳ Rạng sáng qua • {hm_str}"
                else:
                    time_phase = "older"
                    time_phase_label = m_dt_vn.strftime("%d/%m")
                    time_phase_badge = f"📅 {m_dt_vn.strftime('%d/%m %H:%M')}"
            except Exception:
                pass

        p_news_titles = [n.title for n in news_today]
        if len(p_news_titles) < 15:
            seen_t = set(p_news_titles)
            for n in all_player_news:
                if n.title not in seen_t:
                    p_news_titles.append(n.title)
                    seen_t.add(n.title)
                if len(p_news_titles) >= 20:
                    break

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
            if live_state == "in" or (live_state == "post" and diff_days in [0, -1]):
                match_state = live_state
                in_today_activity = True
                is_within_month = True
                if live_info.get("match_result"):
                    match_result = live_info["match_result"]
                if live_info.get("competition"):
                    comp_name = live_info["competition"]
                
                # Cập nhật thông số thi đấu trực tiếp cho cầu thủ
                ev_id = live_info.get("event_id")
                stats_info = fetch_player_match_stats(
                    p.name, sport_name, team_name, event_id=ev_id, match_state=match_state, news_titles=p_news_titles,
                    match_date_utc=live_info.get("match_date_utc") or (sched_today_match.get("match_date_utc") if sched_today_match else None),
                    match_name=live_info.get("match_name") or (sched_today_match.get("match_name") if sched_today_match else None)
                )
                if stats_info.get("match_result") and (not match_result or "-" not in str(match_result)):
                    match_result = stats_info.get("match_result")
                if stats_info.get("tags"):
                    raw_tags = stats_info.get("tags", [])
                has_p = stats_info.get("has_played", False)
                if match_today and match_today.has_played and not has_p:
                    if match_today.performance_rating or (match_today.player_stats and "minutes_played" in str(match_today.player_stats)):
                        has_p = True
                if has_p:
                    rating = stats_info.get("rating")
                    raw_stats = stats_info.get("stats_text")
                
                if match_today:
                    match_today.match_state = match_state
                    if match_result:
                        match_today.match_result = match_result
                    if comp_name:
                        match_today.competition = comp_name
                    if raw_tags:
                        match_today.impression_tags = ", ".join(raw_tags)
                    match_today.has_played = has_p
                    if has_p:
                        match_today.performance_rating = rating
                        match_today.player_stats = raw_stats
                    try:
                        db.commit()
                    except Exception:
                        pass

        if not comp_name and sport_name == "Bóng đá":
            for m in all_matches_raw:
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
        curr_match_headline = sched_today_match.get("match_name") if sched_today_match else (match_today.match_name if match_today else "")
        _, tags = format_player_stats_and_tags(
            p.name, sport_name, team_name,
            curr_match_headline,
            match_state, raw_stats_summary, raw_tags,
            competition_name=comp_name,
            news_titles=p_news_titles,
            is_no_match=is_player_no_match
        )
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
            if in_today_activity:
                m_ev_id = str(m.get("event_id") or "")
                sched_ev_id = str(sched_today_match.get("event_id") or "") if sched_today_match else ""
                sched_dvn = sched_today_match.get("date_only_vn") if sched_today_match else ""
                if (m_ev_id and sched_ev_id and m_ev_id == sched_ev_id) or (m_date_vn and sched_dvn and m_date_vn == sched_dvn):
                    is_matching_today_perf = True

            if is_matching_today_perf:
                h_played = (match_today.has_played if match_today else True)
                db_tags = [t.strip() for t in (match_today.impression_tags or "").split(",") if t.strip()] if match_today else []
                is_no_play = not h_played or any(no_play_kw in t for t in (db_tags or tags) for no_play_kw in ["Không đăng ký", "Không thi đấu", "Dự bị (Không vào sân)", "Chấn thương"])
                
                m["has_played"] = not is_no_play
                m["rating"] = None if is_no_play else rating
                m["player_stats"] = None if is_no_play else raw_stats
                # Include competition tag + impression tags directly from match_today
                m_tags = [clean_comp] if clean_comp else []
                for t in (db_tags or tags):
                    if t:
                        t_low = t.lower()
                        if t_low == "bàn quyết định":
                            t = "Bàn mở tỉ số"
                            t_low = t.lower()
                        if "scored an own goal" in t_low or t_low == "own goal":
                            t = "Phản lưới"
                            t_low = t.lower()
                        if "red card" in t_low or "thẻ đỏ" in t_low or "bị thẻ đỏ" in t_low:
                            t = "Thẻ đỏ"
                            t_low = t.lower()
                        if "yellow card" in t_low or "thẻ vàng" in t_low:
                            t = "Thẻ vàng"
                            t_low = t.lower()
                        m_save = re.match(r'^(\d+)\s+pha\s+cứu\s+thua(\s+xuất\s+sắc)?$', t_low)
                        if m_save:
                            t = f"{m_save.group(1)} cứu thua"
                        if t not in m_tags:
                            m_tags.append(t)
                def _m_tag_sort_key(tag_str):
                    tl = tag_str.lower()
                    if tag_str == clean_comp: return (0, 0)
                    if any(w in tl for w in ["bàn", "hattrick", "cú đúp", "kiến tạo", "cứu thua", "save", "phản lưới", "own goal", "goal", "assist", "thẻ đỏ", "red card", "thẻ vàng", "yellow card"]): return (1, 0)
                    if any(w in tl for w in ["đá chính", "xuất phát", "vào sân", "phút"]): return (2, 0)
                    if any(w in tl for w in ["mvp", "xuất sắc nhất", "kỷ lục"]): return (3, 0)
                    return (4, 0)
                m_tags.sort(key=_m_tag_sort_key)
                m["tags"] = m_tags
                m["has_played"] = False if is_no_play else h_played
                is_fb = False
                if espn_sport == "soccer" and m.get("rating"):
                    _, c_details = unpack_stats(raw_stats)
                    if not (c_details and c_details.get("source") == "FotMob"):
                        is_fb = True
                m["is_fallback_rating"] = is_fb
                # CẬP NHẬT CHÍNH XÁC KẾT QUẢ VÀ TRẠNG THÁI CHO TRẬN ĐẤU HÔM NAY TRONG LỊCH ALL_MATCHES
                if match_result:
                    m["match_result"] = match_result
                elif match_today and match_today.match_result:
                    m["match_result"] = match_today.match_result
                m["match_state"] = match_state
                m["is_past"] = (match_state == "post" or diff_d < -0.05)
            elif is_m_past:
                ev_id = m.get("event_id")
                match_team = m.get("player_team") or team_name
                db_perf = None
                if ev_id:
                    db_perf = perf_by_player_event.get((p.id, str(ev_id)))
                if not db_perf and m_date_vn:
                    cand_perf = perf_by_player_date.get((p.id, str(m_date_vn)))
                    if cand_perf and (not cand_perf.event_id or not ev_id or str(cand_perf.event_id) == str(ev_id) or str(cand_perf.match_name or "") == str(m.get("match_name") or "")):
                        db_perf = cand_perf

                if db_perf and (db_perf.player_stats or db_perf.impression_tags or db_perf.has_played is not None):
                    has_fotmob = bool(db_perf.player_stats and '"source": "FotMob"' in db_perf.player_stats)
                    # Tự động làm sạch dữ liệu DB bị lỗi cũ (espn_nt_ bị cắt prefix, trận cá nhân đã có tỷ số nhưng has_played=False, hoặc "Không thi đấu" không có dữ liệu đội hình)
                    db_tags_low = str(db_perf.impression_tags or "").strip().lower()
                    is_poisoned_nt = bool(ev_id and str(ev_id).startswith("espn_nt_") and not db_perf.has_played and "không đăng ký" in db_tags_low)
                    is_poisoned_ind = bool(ev_id and str(ev_id).startswith(("wtt_", "fs_")) and m.get("match_result") and not db_perf.has_played and not re.search(r'\b(wo|w/o|walkover|cancelled|postponed)\b', str(m.get("match_result") or ""), re.I))
                    is_poisoned_no_lineup = bool(not db_perf.has_played and not db_perf.player_stats and db_tags_low in ("không thi đấu", "không đăng ký thi đấu") and (-7 <= diff_d <= 0 or is_poisoned_nt))
                    if (is_poisoned_nt or is_poisoned_ind or is_poisoned_no_lineup) and ev_id:
                        try:
                            healed = fetch_player_match_stats(
                                p.name, sport_name, match_team, event_id=ev_id, match_state="post", news_titles=p_news_titles,
                                match_date_utc=m.get("match_date_utc") or (db_perf.match_date.strftime("%Y-%m-%dT%H:%M:%SZ") if db_perf.match_date else None),
                                match_name=m.get("match_name") or db_perf.match_name
                            )
                            if healed:
                                db_perf.has_played = bool(healed.get("has_played", db_perf.has_played))
                                db_perf.performance_rating = healed.get("rating") if db_perf.has_played else None
                                db_perf.player_stats = healed.get("stats_text") if db_perf.has_played else None
                                db_perf.impression_tags = ", ".join(healed.get("tags") or [])
                                if healed.get("match_result") and not db_perf.match_result:
                                    db_perf.match_result = healed.get("match_result")
                                db.commit()
                        except Exception:
                            pass

                    # Quy tắc lưu cứng: Trận đấu diễn ra quá 3 ngày (diff_d < -3) được giữ nguyên vĩnh viễn trong DB, KHÔNG gọi lại API.
                    # Chỉ kiểm tra nâng cấp FotMob nếu trận bóng đá vừa diễn ra trong vòng 3 ngày (-3 <= diff_d <= 0) và chưa có điểm chính thức FotMob:
                    if db_perf.has_played and not has_fotmob and -3 <= diff_d <= 0 and espn_sport == "soccer" and ev_id:
                        try:
                            fresh_stats = fetch_player_match_stats(
                                p.name, sport_name, match_team, event_id=ev_id, match_state="post", news_titles=p_news_titles,
                                match_date_utc=m.get("match_date_utc") or (db_perf.match_date.strftime("%Y-%m-%dT%H:%M:%SZ") if db_perf.match_date else None),
                                match_name=m.get("match_name") or db_perf.match_name
                            )
                            if fresh_stats and fresh_stats.get("detailed_stats"):
                                db_perf.performance_rating = fresh_stats.get("rating")
                                db_perf.player_stats = fresh_stats.get("stats_text")
                                is_potm = fresh_stats.get("detailed_stats", {}).get("is_player_of_the_match", False) or ("Cầu thủ xuất sắc nhất (MVP)" in fresh_stats.get("tags", []))
                                cur_tags = [t.strip() for t in (db_perf.impression_tags or "").split(",") if t.strip()]
                                if is_potm:
                                    if "Cầu thủ xuất sắc nhất (MVP)" not in cur_tags:
                                        cur_tags.append("Cầu thủ xuất sắc nhất (MVP)")
                                else:
                                    cur_tags = [t for t in cur_tags if t != "Cầu thủ xuất sắc nhất (MVP)"]
                                db_perf.impression_tags = ",".join(cur_tags)
                                db.commit()
                                has_fotmob = True
                        except Exception:
                            pass

                    m["has_played"] = db_perf.has_played or False
                    m["rating"] = db_perf.performance_rating if m["has_played"] else None
                    m["player_stats"] = db_perf.player_stats if m["has_played"] else None
                    if db_perf.match_result and (not m.get("match_result") or len(str(db_perf.match_result)) > len(str(m.get("match_result")))):
                        m["match_result"] = db_perf.match_result
                    if not m.get("match_result") or m.get("match_result") in ["Đã kết thúc", "Đã kết thúc (FT)", ""]:
                        clean_match_team = (match_team or "").lower().strip()
                        if clean_match_team in live_scores and live_scores[clean_match_team].get("match_result"):
                            m["match_result"] = live_scores[clean_match_team]["match_result"]
                    
                    # Chỉ gắn nhãn ước tính khi: Môn Bóng đá + Trong 3 ngày gần đây + Chưa có FotMob
                    # Tất cả các môn khác (Bóng chuyền, Bóng rổ, Bóng chày...) và các trận quá 3 ngày đều là ĐIỂM CHÍNH THỨC ĐÃ LƯU CỨNG
                    is_fb = False
                    if espn_sport == "soccer" and -3 <= diff_d <= 0 and m["rating"] and not has_fotmob:
                        is_fb = True
                    m["is_fallback_rating"] = is_fb

                    m_tags = [clean_comp] if clean_comp else []
                    db_tags = [t.strip() for t in (db_perf.impression_tags or "").split(",") if t.strip()]
                    for t in db_tags:
                        if t:
                            t_low = t.lower()
                            if t_low == "bàn quyết định":
                                t = "Bàn mở tỉ số"
                                t_low = t.lower()
                            if "scored an own goal" in t_low or t_low == "own goal":
                                t = "Phản lưới"
                                t_low = t.lower()
                            if "red card" in t_low or "thẻ đỏ" in t_low or "bị thẻ đỏ" in t_low:
                                t = "Thẻ đỏ"
                                t_low = t.lower()
                            if "yellow card" in t_low or "thẻ vàng" in t_low:
                                t = "Thẻ vàng"
                                t_low = t.lower()
                            m_save = re.match(r'^(\d+)\s+pha\s+cứu\s+thua(\s+xuất\s+sắc)?$', t_low)
                            if m_save:
                                t = f"{m_save.group(1)} cứu thua"
                            if t not in m_tags:
                                m_tags.append(t)
                    # Ưu tiên thứ tự: Bàn thắng/Kiến tạo/Cứu thua/Phản lưới/Thẻ đỏ/Thẻ vàng trước, số phút/đá chính sau
                    def _m_tag_sort_key(tag_str):
                        tl = tag_str.lower()
                        if tag_str == clean_comp: return (0, 0)
                        if any(w in tl for w in ["bàn", "hattrick", "cú đúp", "kiến tạo", "cứu thua", "save", "phản lưới", "own goal", "goal", "assist", "thẻ đỏ", "red card", "thẻ vàng", "yellow card"]): return (1, 0)
                        if any(w in tl for w in ["đá chính", "xuất phát", "vào sân", "phút"]): return (2, 0)
                        if any(w in tl for w in ["mvp", "xuất sắc nhất", "kỷ lục"]): return (3, 0)
                        return (4, 0)
                    m_tags.sort(key=_m_tag_sort_key)
                    m["tags"] = m_tags
                else:
                    real_stats = None
                    # Giai đoạn 1 (is_full_load=False): Chỉ cào chi tiết thời gian thực cho trận trong 7 ngày qua (-7.0 <= diff_d <= 0)
                    # Giai đoạn 2 (is_full_load=True): Cào thông số cho toàn bộ quá khứ của mùa giải (-300.0 <= diff_d <= 0)
                    stats_lower_limit = -300.0 if is_full_load else -7.0
                    is_rv_match = bool(ev_id and str(ev_id).startswith(("wtt_", "fs_")))
                    if ev_id and (stats_lower_limit <= diff_d <= 0 or is_rv_match):
                        try:
                            real_stats = fetch_player_match_stats(
                                p.name, sport_name, match_team, event_id=ev_id, match_state="post", news_titles=p_news_titles,
                                match_date_utc=m.get("match_date_utc"),
                                match_name=m.get("match_name")
                            )
                        except Exception:
                            real_stats = None
                    elif diff_d < stats_lower_limit:
                        # Trận quá khứ sâu chưa có trong DB:
                        # Giữ nguyên tỷ số chung cuộc từ lịch thi đấu, đánh dấu needs_lazy_load để nạp ngầm khi người dùng bấm vào xem
                        m["rating"] = None
                        m["player_stats"] = None
                        m["tags"] = [clean_comp] if clean_comp else []
                        m["has_played"] = True
                        m["needs_lazy_load"] = True
                    
                    if real_stats:
                        has_p = real_stats.get("has_played", False)
                        p_rating = real_stats.get("rating") if has_p else None
                        p_stats = real_stats.get("stats_text") if has_p else None
                        raw_tags_list = real_stats.get("tags", [])
                        has_fotmob = bool(real_stats.get("detailed_stats"))

                        m["has_played"] = has_p
                        m["rating"] = p_rating
                        m["player_stats"] = p_stats
                        
                        is_fb = False
                        if espn_sport == "soccer" and -3 <= diff_d <= 0 and p_rating and not has_fotmob:
                            is_fb = True
                        m["is_fallback_rating"] = is_fb

                        m_tags = [clean_comp] if clean_comp else []
                        for t in raw_tags_list:
                            if t:
                                t_low = t.lower()
                                if t_low == "bàn quyết định":
                                    t = "Bàn mở tỉ số"
                                    t_low = t.lower()
                                if "cứu thua" in t_low and "xuất sắc" not in t_low:
                                    continue
                                if t not in m_tags:
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

            # 2. Match News Window: [D - 1 day 00:00:00 to D + 1 day 23:59:59]
            # Chặn chính xác từ ngày D-1 đến D+1 (với D là ngày thi đấu theo giờ VN ICT)
            # Hoàn toàn bỏ qua giới hạn số lượng bài báo (lấy trọn vẹn toàn bộ bài trong khoảng thời gian này)
            if m_date_vn:
                try:
                    d_dt = datetime.datetime.strptime(m_date_vn, "%Y-%m-%d").date()
                    d_prev = d_dt - datetime.timedelta(days=1)
                    d_next = d_dt + datetime.timedelta(days=1)
                    win_start = datetime.datetime.combine(d_prev, datetime.time.min) - datetime.timedelta(hours=7)
                    win_end = datetime.datetime.combine(d_next, datetime.time.max) - datetime.timedelta(hours=7)
                    m_news = [
                        {
                            "title": n.title,
                            "url": n.source_url,
                            "news_type": n.news_type,
                            "region": n.region or "US",
                            "published_at": n.published_at_iso
                        }
                        for n in all_player_news
                        if n.published_at and win_start <= n.published_at <= win_end
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
            # 2. Trận đấu trong khoảng 7 ngày trở lại đây (-7 <= diff_d <= 0):
            # Lưu lại báo theo khung 48h. Nếu chưa có bài báo riêng thì bổ sung recap từ ESPN vào m_news
            elif is_m_past and -7.0 <= diff_d <= 0:
                if len(m_news) == 0:
                    ev_id = m.get("event_id")
                    recap_items = fetch_match_recap_news(
                        str(ev_id or ""), sport_name, team_name, p.name, m.get("match_name", ""),
                        m_date_vn, match_result=m.get("match_result"), comp_name=clean_comp
                    )
                    for r_item in recap_items:
                        m_news.append(r_item)
            # 3. Trận đấu từ 8 đến 30 ngày trước: Điểm tin tóm tắt nhanh từ thông tin trận đấu (không gọi HTTP phụ)
            elif is_m_past and -30.0 <= diff_d < -7.0:
                if len(m_news) == 0:
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
            
            # Standardize match_result format to always include team names (e.g. 'TeamA 2 - 0 TeamB (FT)')
            cur_res = m.get("match_result")
            if cur_res:
                clean_sc = re.sub(r'\(.*?\)', '', str(cur_res)).strip()
                if re.match(r'^\d+\s*-\s*\d+$', clean_sc):
                    raw_n = m.get("raw_match_name") or ""
                    if " vs " in raw_n:
                        parts = raw_n.split(" vs ")
                        m["match_result"] = f"{parts[0].strip()} {clean_sc} {parts[1].strip()} (FT)"
                    elif m.get("match_name"):
                        mn = m.get("match_name").strip()
                        if mn.startswith("vs "):
                            m["match_result"] = f"{team_name} {clean_sc} {mn[3:].strip()} (FT)"
                        elif mn.startswith("@ "):
                            m["match_result"] = f"{mn[2:].strip()} {clean_sc} {team_name} (FT)"

            m_s, m_d = unpack_stats(m.get("player_stats"))
            m["player_stats"] = m_s
            m["detailed_stats"] = m_d

            # Gắn tag Vòng đấu (Vòng 1..N, Tứ kết, Bán kết, Chung kết...) và Kết quả (Thắng/Thua/Hòa)
            m_tags_cur = list(m.get("tags") or [])
            round_raw = m.get("round_tag") or (m_d.get("round_raw") if isinstance(m_d, dict) else "") or ""
            resolved_round = extract_round_stage_tag(round_raw, m.get("competition", ""), m.get("raw_match_name", ""))
            if resolved_round and resolved_round not in m_tags_cur:
                m_tags_cur.append(resolved_round)

            if is_m_past or m.get("match_state") == "post":
                outcome_tag = extract_match_outcome_tag(
                    m.get("match_result"),
                    m.get("player_team") or team_name,
                    m.get("match_name"),
                    player_name=p.name,
                )
                if outcome_tag and outcome_tag not in m_tags_cur:
                    m_tags_cur.append(outcome_tag)

            if m.get("nt_callup_status") == "not_called_up":
                m_tags_cur = [t for t in m_tags_cur if not any(k in t.lower() for k in ["không đăng ký", "không thi đấu", "chấn thương"])]
                if "Không lên tuyển" not in m_tags_cur:
                    m_tags_cur.append("Không lên tuyển")
                m["has_played"] = False
                m["rating"] = None
                m["is_not_called_up"] = True
            elif m.get("nt_callup_status") == "injured_withdrawal":
                m_tags_cur = [t for t in m_tags_cur if "không đăng ký" not in t.lower()]
                if "Vắng mặt ĐTQG (Chấn thương)" not in m_tags_cur:
                    m_tags_cur.append("Vắng mặt ĐTQG (Chấn thương)")
                m["has_played"] = False
                m["rating"] = None
            elif m.get("absent_due_to_nt_duty") and (m.get("match_state", "pre") == "pre" or not m.get("has_played")):
                m_tags_cur = [t for t in m_tags_cur if "không đăng ký" not in t.lower() and "không thi đấu" not in t.lower()]
                if "Tập trung ĐTQG" not in m_tags_cur:
                    m_tags_cur.append("Tập trung ĐTQG")
                m["has_played"] = False
                m["rating"] = None
            m["tags"] = m_tags_cur

            # Trận đấu trong vòng 7 ngày (1 tuần) hoặc trận tương lai: Giữ nguyên trọn vẹn toàn bộ bài báo theo trận
            # Trận cũ hơn 7 ngày (quá 1 tuần): Giới hạn tối đa 8 bài để tiết kiệm dung lượng JSON
            is_within_7d = is_matching_today_perf or (m_date_vn in [today_str_vn, yesterday_str_vn]) or (diff_d >= -7.0)
            m["news"] = m_news if is_within_7d else m_news[:8]
            m["news_count"] = len(m_news)
            all_matches.append(m)

            if 0 <= diff_d <= 30 and not is_m_past and m.get("match_state") != "post" and m.get("nt_callup_status") not in ("not_called_up", "injured_withdrawal") and not m.get("absent_due_to_nt_duty"):
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
            if curr_match_result:
                clean_sc = re.sub(r'\(.*?\)', '', str(curr_match_result)).strip()
                if re.match(r'^\d+\s*-\s*\d+$', clean_sc):
                    raw_n = sched_today_match.get("raw_match_name") if sched_today_match else ""
                    if " vs " in raw_n:
                        parts = raw_n.split(" vs ")
                        curr_match_result = f"{parts[0].strip()} {clean_sc} {parts[1].strip()} (FT)"
                    elif curr_match_name:
                        mn = curr_match_name.strip()
                        if mn.startswith("vs "):
                            curr_match_result = f"{team_name} {clean_sc} {mn[3:].strip()} (FT)"
                        elif mn.startswith("@ "):
                            curr_match_result = f"{mn[2:].strip()} {clean_sc} {team_name} (FT)"
            curr_rating = rating
            c_summary, c_details = unpack_stats(raw_stats)
            curr_stats = c_summary
            curr_detailed_stats = c_details
            curr_tags = list(tags or [])
            today_round_raw = (sched_today_match.get("round_tag") if sched_today_match else "") or (c_details.get("round_raw") if isinstance(c_details, dict) else "") or ""
            today_round_tag = extract_round_stage_tag(today_round_raw, comp_name, curr_match_name)
            if today_round_tag and today_round_tag not in curr_tags:
                curr_tags.append(today_round_tag)
            if curr_match_state == "post" and curr_match_result:
                today_outcome = extract_match_outcome_tag(
                    curr_match_result,
                    (sched_today_match.get("player_team") if sched_today_match else None) or team_name,
                    curr_match_name,
                    player_name=p.name,
                )
                if today_outcome and today_outcome not in curr_tags:
                    curr_tags.append(today_outcome)
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
            up_round_tag = first_up.get("round_tag") or extract_round_stage_tag(first_up.get("competition", ""), first_up.get("raw_match_name", ""))
            if up_round_tag and up_round_tag not in curr_tags:
                curr_tags.append(up_round_tag)
            if first_up.get("nt_callup_status") == "injured_withdrawal" and "Vắng mặt ĐTQG (Chấn thương)" not in curr_tags:
                curr_tags.append("Vắng mặt ĐTQG (Chấn thương)")
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
        has_official_inj_feed = resolve_team_league(team_name, sport_name) in {"MLB", "NBA", "NHL", "NFL"}
        if not off_inj and has_official_inj_feed:
            curr_tags = [t for t in curr_tags if "chấn thương" not in str(t).lower() and "đau nhẹ" not in str(t).lower()]
        elif not off_inj and any("chấn thương" in t.lower() or "đau nhẹ" in t.lower() for t in (curr_tags or tags)):
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

        from backend.modules.players.services.news_service import normalize_news_title
        seen_news_urls = set()
        seen_news_titles = set()
        player_news_list = []
        for n in news_today:
            norm_t = normalize_news_title(n.title) if n.title else ""
            if n.source_url not in seen_news_urls and (not norm_t or norm_t not in seen_news_titles):
                player_news_list.append(n)
                seen_news_urls.add(n.source_url)
                if norm_t:
                    seen_news_titles.add(norm_t)
        for n in all_player_news:
            norm_t = normalize_news_title(n.title) if n.title else ""
            if n.source_url not in seen_news_urls and (not norm_t or norm_t not in seen_news_titles):
                player_news_list.append(n)
                seen_news_urls.add(n.source_url)
                if norm_t:
                    seen_news_titles.add(norm_t)

        cutoff_24h_utc = now_utc - datetime.timedelta(hours=24)
        player_news_24h = [
            {
                "title": n.title,
                "url": n.source_url,
                "news_type": n.news_type,
                "region": n.region or "US",
                "published_at": n.published_at_iso
            }
            for n in player_news_list
            if n.published_at and n.published_at >= cutoff_24h_utc
        ]

        # Lấy chính xác bài báo của trận đấu hiện tại (theo đúng khung D-1 đến D+1 hoặc 1 bài tóm tắt nếu >30 ngày)
        curr_match_obj = next((m for m in all_matches if m.get("match_name") == curr_match_name and m.get("match_date_utc") == curr_match_date_utc), None)
        if not curr_match_obj:
            curr_match_obj = next((m for m in all_matches if m.get("match_name") == curr_match_name), None)
        curr_match_news = list(curr_match_obj.get("news", [])) if curr_match_obj else []

        # Cờ fallback cho thẻ cầu thủ: CHỈ áp dụng cho bóng đá trong 3 ngày qua khi chưa có FotMob.
        # Tất cả các môn khác (Bóng chuyền, Bóng rổ, Bóng chày...) đều là điểm chính thức đã chốt
        is_player_fallback = False
        if espn_sport == "soccer" and curr_rating:
            has_fm = bool(curr_detailed_stats and curr_detailed_stats.get("source") == "FotMob")
            if not has_fm and is_within_month:
                is_player_fallback = True

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
            "is_fallback_rating": is_player_fallback,
            "tags": curr_tags,
            "injury": injury_data,
            "is_within_month": is_within_month,
            "match_date_utc": curr_match_date_utc,
            "next_match_date": next_match_date_str,
            "match_time_vn": match_time_vn,
            "match_timestamp": match_timestamp,
            "time_phase": time_phase,
            "time_phase_label": time_phase_label,
            "time_phase_badge": time_phase_badge,
            "news_24h_count": len(player_news_24h),
            "details": {
                "match": curr_match_name,
                "match_date_utc": curr_match_date_utc,
                "match_state": curr_match_state,
                "match_result": curr_match_result,
                "player_stats": curr_stats,
                "detailed_stats": curr_detailed_stats,
                "is_fallback_rating": is_player_fallback,
                "injury": injury_data,
                "upcoming_matches_30d": upcoming_matches_30d,
                "all_upcoming_matches": all_upcoming_matches,
                "all_matches": all_matches,
                "news_24h": player_news_24h,
                "news": curr_match_news,
                "all_news": [
                    {
                        "title": n.title,
                        "url": n.source_url,
                        "news_type": n.news_type,
                        "region": n.region or "US",
                        "published_at": n.published_at_iso
                    }
                    for n in player_news_list[:40]
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
        
        # Nếu chưa có rating hôm nay, lấy rating của trận gần nhất đã thi đấu để hiển thị phong độ ở tab Schedule
        if not sched_item.get("rating"):
            for m_past in reversed(all_matches):
                if (m_past.get("is_past") or m_past.get("match_state") == "post") and m_past.get("rating") and m_past.get("has_played", True):
                    sched_item["rating"] = m_past.get("rating")
                    sched_item["is_fallback_rating"] = m_past.get("is_fallback_rating", False)
                    break

        sched_details = dict(sched_item.get("details", {}))
        sched_details.pop("news", None)
        sched_details.pop("all_matches", None)
        sched_item["details"] = sched_details
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
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
        for tid, s_list in ex.map(_fetch_nt_sched, filtered_nts):
            nt_sched_map[tid] = s_list

    # Batch load national team news from DB qua FastNewsItem
    raw_nt_rows = db.execute(
        text("SELECT team_id, title, source_url, news_type, region, published_at FROM national_team_news ORDER BY published_at DESC")
    ).fetchall()
    nt_news_by_team = {}
    for r in raw_nt_rows:
        p_dt = r[5]
        if isinstance(p_dt, str):
            try:
                p_dt = datetime.datetime.fromisoformat(p_dt)
            except Exception:
                p_dt = None
        iso_str = p_dt.isoformat() if p_dt else None
        nt_news_by_team.setdefault(r[0], []).append(FastNewsItem(r[1], r[2], r[3], r[4] or "US", p_dt, iso_str))

    for nt in filtered_nts:
        nt_id = nt["id"]
        nt_matches = nt_sched_map.get(nt_id, [])
        nt_news = nt_news_by_team.get(nt_id, [])

        nt_upcoming_30d = []
        nt_upcoming_all = []
        nt_match_today = None
        nt_candidates = []

        for m in nt_matches:
            diff_d = m.get("diff_days", 999.0)
            is_m_past = m.get("is_past") or (diff_d < -0.1)
            m_date_vn = m.get("date_only_vn") or ""

            # News window for match: [D-1 to D+1]
            if m_date_vn:
                try:
                    d_dt = datetime.datetime.strptime(m_date_vn, "%Y-%m-%d").date()
                    d_prev = d_dt - datetime.timedelta(days=1)
                    d_next = d_dt + datetime.timedelta(days=1)
                    w_start = datetime.datetime.combine(d_prev, datetime.time.min) - datetime.timedelta(hours=7)
                    w_end = datetime.datetime.combine(d_next, datetime.time.max) - datetime.timedelta(hours=7)
                    m_news = [
                        {
                            "title": n.title,
                            "url": n.source_url,
                            "news_type": n.news_type,
                            "region": n.region or "US",
                            "published_at": n.published_at_iso
                        }
                        for n in nt_news if n.published_at and w_start <= n.published_at <= w_end
                    ]
                except Exception:
                    m_news = []
            else:
                m_news = []

            # Trận đấu diễn ra quá 30 ngày (diff_d < -30): chuyển về đúng 1 báo tóm tắt trận đấu
            if diff_d < -30:
                clean_q = urllib.parse.quote(f"{nt['name']} {m.get('match_name', '')}".strip())
                ev_link = f"https://www.google.com/search?q={clean_q}"
                res_part = f" - {m.get('match_result')}" if m.get("match_result") else ""
                m_news = [{
                    "title": f"Điểm tin trận đấu: {nt['name']} {m.get('match_name', '')}{res_part}",
                    "url": ev_link,
                    "news_type": "Thi đấu",
                    "region": "Quốc tế",
                    "published_at": m.get("match_date_utc")
                }]

            # Trận đấu trong vòng 7 ngày (1 tuần) hoặc trận tương lai: Giữ nguyên trọn vẹn toàn bộ bài báo theo trận
            # Trận cũ hơn 7 ngày (quá 1 tuần): Giới hạn tối đa 8 bài để tiết kiệm dung lượng JSON
            is_nt_within_7d = (m_date_vn in [today_str_vn, yesterday_str_vn]) or (m.get("match_state") == "in") or (diff_d >= -7.0)
            m["news"] = m_news if is_nt_within_7d else m_news[:8]
            m["news_count"] = len(m_news)

            m_state = m.get("match_state", "pre")
            if m_state == "in":
                nt_candidates.append((0, m))
            elif m_date_vn == today_str_vn:
                nt_candidates.append((1, m))
            elif m_date_vn == yesterday_str_vn:
                vn_h = 12
                if m.get("match_date_utc"):
                    try:
                        vn_h = (datetime.datetime.strptime(m["match_date_utc"][:19], "%Y-%m-%dT%H:%M:%S") + datetime.timedelta(hours=7)).hour
                    except Exception:
                        pass
                if vn_h >= 18:
                    nt_candidates.append((2, m))
                else:
                    nt_candidates.append((3, m))

            if not is_m_past and diff_d >= 0:
                nt_upcoming_all.append(m)
                if diff_d <= 30:
                    nt_upcoming_30d.append(m)

        if nt_candidates:
            nt_candidates.sort(key=lambda x: x[0])
            nt_match_today = nt_candidates[0][1]

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

        # Xác định mốc giờ VN và Time Phase cho Đội tuyển
        nt_time_phase = "today"
        nt_time_phase_label = "Hôm nay"
        nt_time_phase_badge = "☀️ Hôm nay"
        nt_match_time_vn = ""
        nt_match_timestamp = 0.0

        if curr_match_date_utc:
            try:
                m_dt_utc = datetime.datetime.strptime(curr_match_date_utc[:19], "%Y-%m-%dT%H:%M:%S")
                m_dt_vn = m_dt_utc + datetime.timedelta(hours=7)
                nt_match_timestamp = m_dt_vn.timestamp()
                nt_match_time_vn = m_dt_vn.strftime("%d/%m %H:%M")
                m_date_vn_obj = m_dt_vn.date()
                m_hour_vn = m_dt_vn.hour
                hm_str = m_dt_vn.strftime("%H:%M")

                if curr_match_state == "in":
                    nt_time_phase = "live"
                    nt_time_phase_label = "Đang trực tiếp"
                    nt_time_phase_badge = f"🔴 TRỰC TIẾP • {hm_str}"
                elif m_date_vn_obj == today_ict:
                    nt_time_phase = "today"
                    nt_time_phase_label = "Hôm nay"
                    nt_time_phase_badge = f"☀️ Hôm nay • {hm_str}"
                elif m_date_vn_obj == yesterday_ict:
                    if m_hour_vn >= 18:
                        nt_time_phase = "yesterday_evening"
                        nt_time_phase_label = "Tối hôm qua (18h-24h)"
                        nt_time_phase_badge = f"🌙 Tối qua • {hm_str}"
                    else:
                        nt_time_phase = "yesterday_morning"
                        nt_time_phase_label = "Rạng sáng hôm qua"
                        nt_time_phase_badge = f"⏳ Rạng sáng qua • {hm_str}"
                else:
                    nt_time_phase = "older"
                    nt_time_phase_label = m_dt_vn.strftime("%d/%m")
                    nt_time_phase_badge = f"📅 {m_dt_vn.strftime('%d/%m %H:%M')}"
            except Exception:
                pass

        tz_offset = "UTC+9"

        nt_curr_match_obj = next((m for m in nt_matches if m.get("match_name") == curr_match_name and m.get("match_date_utc") == curr_match_date_utc), None)
        if not nt_curr_match_obj:
            nt_curr_match_obj = next((m for m in nt_matches if m.get("match_name") == curr_match_name), None)
        nt_curr_news = list(nt_curr_match_obj.get("news", [])) if nt_curr_match_obj else []

        nt_news_titles = [n.title for n in nt_news[:12]]
        nt_tags = []
        if nt_curr_match_obj:
            nt_tags = nt_curr_match_obj.get("tags") or []
            if not nt_tags:
                nt_tags = format_national_team_match_tags(nt["country_name"], nt["sport_name"], nt.get("tier"), nt_curr_match_obj, recent_news_titles=nt_news_titles)
        elif nt_upcoming_30d:
            first_up = nt_upcoming_30d[0]
            nt_tags = first_up.get("tags") or []
            if not nt_tags:
                nt_tags = format_national_team_match_tags(nt["country_name"], nt["sport_name"], nt.get("tier"), first_up, recent_news_titles=nt_news_titles)
        else:
            nt_tags = ["Chờ lịch thi đấu", "Nghỉ đợt tập trung"]

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
            "tags": nt_tags,
            "injury": {"has_injury": False, "status": "Fit", "severity": "Sẵn sàng", "tag_label": "Sẵn sàng", "tooltip": "Đội hình đầy đủ", "return_date": "Hiện tại", "injury_desc": ""},
            "is_within_month": len(nt_upcoming_30d) > 0,
            "match_date_utc": curr_match_date_utc,
            "next_match_date": next_match_date_str,
            "match_time_vn": nt_match_time_vn,
            "match_timestamp": nt_match_timestamp,
            "time_phase": nt_time_phase,
            "time_phase_label": nt_time_phase_label,
            "time_phase_badge": nt_time_phase_badge,
            "news_24h_count": len([n for n in nt_news if n.published_at and n.published_at >= (now_utc - datetime.timedelta(hours=24))]),
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
                "news_24h": [
                    {
                        "title": n.title,
                        "url": n.source_url,
                        "news_type": n.news_type,
                        "region": n.region or "US",
                        "published_at": n.published_at_iso
                    }
                    for n in nt_news
                    if n.published_at and n.published_at >= (now_utc - datetime.timedelta(hours=24))
                ],
                "news": nt_curr_news,
                "all_news": [
                    {
                        "title": n.title,
                        "url": n.source_url,
                        "news_type": n.news_type,
                        "region": n.region or "US",
                        "published_at": n.published_at_iso
                    }
                    for n in nt_news[:40]
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
        sched_nt_details = dict(sched_nt.get("details", {}))
        sched_nt_details.pop("news", None)
        sched_nt_details.pop("all_matches", None)
        sched_nt["details"] = sched_nt_details
        schedule_players.append(sched_nt)
            
    # Sắp xếp: Ưu tiên có rating lên trước (từ cao đến thấp), rồi mới đến số lượng báo
    def sort_active_today_players(p):
        news_count = len(p.get("details", {}).get("news", []))
        rating_val = p.get("rating")
        has_rating = 1 if (isinstance(rating_val, (int, float)) and rating_val > 0) else 0
        rating_score = float(rating_val) if has_rating else 0.0
        return (has_rating, rating_score, news_count)

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

    now_vn_str = (now_utc + datetime.timedelta(hours=7)).strftime("%H:%M:%S %d/%m/%Y")
    result_data = {
        "today_date_vn": today_str_vn,
        "server_time_vn": now_vn_str,
        "server_timestamp": now_utc.timestamp(),
        "server_time_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "active_players": active_players,
        "upcoming_players": upcoming_players,
        "no_match_players": no_match_players,
        "schedule_players": schedule_players,
        "calendar_counts": calendar_counts,
        "sports_list": sports_list,
        "countries_list": countries_list,
        "total_players": total_filtered_players,
        "total_national_teams": total_filtered_national_teams,
        "total_all": total_filtered_players + total_filtered_national_teams,
        "is_full_load": is_full_load
    }
    _DASHBOARD_CACHE[cache_key] = (now_ts, result_data)
    if not clean_sport and not clean_country and not clean_sport_id and not clean_country_id and (clean_entity_type in [None, "", "all"]):
        _save_dashboard_snapshot(result_data)
    import gc
    gc.collect()
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass
    logger.info(f"<== [API] Hoàn tất nạp bảng theo dõi trong {time.time() - t_start:.2f}s!")
    return result_data


@router.get("/api/players/{player_id}/match-detail")
def get_player_match_detail(
    player_id: int,
    event_id: Optional[str] = Query(None),
    match_date: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Lazy-load chi tiết thông số và rating cho một trận đấu quá khứ sâu (> 7 ngày)
    khi người dùng chủ động bấm vào xem trên giao diện.
    """
    player = db.query(Player).filter(Player.id == player_id).first()
    if not player:
        return {"status": "error", "message": "Player not found"}
    
    sport_name = player.sport_name
    team_name = player.team_name
    
    # 1. Kiểm tra trong DB MatchPerformance
    perf = None
    if event_id:
        perf = db.query(MatchPerformance).filter(
            MatchPerformance.player_id == player_id,
            MatchPerformance.event_id == str(event_id)
        ).first()
    if not perf and match_date:
        perf = db.query(MatchPerformance).filter(
            MatchPerformance.player_id == player_id,
            MatchPerformance.date_str == str(match_date)
        ).first()
        
    if perf and perf.player_stats:
        p_s, p_d = unpack_stats(perf.player_stats)
        tags = [t.strip() for t in (perf.impression_tags or "").split(",") if t.strip()]
        return {
            "status": "success",
            "rating": perf.performance_rating,
            "player_stats": p_s,
            "detailed_stats": p_d,
            "tags": tags,
            "has_played": perf.has_played
        }
        
    # 2. Cào dữ liệu theo nhu cầu (On-Demand Fetching)
    real_stats = fetch_player_match_stats(
        player.name, sport_name, team_name, event_id=event_id, match_state="post",
        match_date_utc=match_date or (perf.match_date.strftime("%Y-%m-%dT%H:%M:%SZ") if perf and perf.match_date else None),
        match_name=perf.match_name if perf else None
    )
    if real_stats:
        has_p = real_stats.get("has_played", False)
        p_r = real_stats.get("rating") if has_p else None
        p_s = real_stats.get("stats_text") if has_p else None
        p_d = real_stats.get("detailed_stats")
        tags = real_stats.get("tags", [])
        
        # Lưu vào DB để lần sau có ngay lập tức (0ms)
        try:
            if not perf:
                perf = MatchPerformance(
                    player_id=player_id,
                    event_id=str(event_id) if event_id else None,
                    date_str=match_date,
                    match_name=real_stats.get("match_name") or "Trận đấu",
                    performance_rating=p_r,
                    player_stats=real_stats.get("stats_text"),
                    impression_tags=",".join(tags),
                    has_played=has_p,
                    match_state="post"
                )
                db.add(perf)
            else:
                perf.performance_rating = p_r
                perf.player_stats = real_stats.get("stats_text")
                perf.impression_tags = ",".join(tags)
                perf.has_played = has_p
            db.commit()
        except Exception:
            pass
            
        return {
            "status": "success",
            "rating": p_r,
            "player_stats": p_s,
            "detailed_stats": p_d,
            "tags": tags,
            "has_played": has_p
        }
        
    return {"status": "not_found", "message": "Không có thông số chi tiết"}


