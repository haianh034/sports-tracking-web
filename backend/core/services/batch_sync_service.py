import urllib.request
import urllib.parse
import json
import datetime
import concurrent.futures
from sqlalchemy.orm import Session

from backend.core.db.session import SessionLocal
from backend.core.db.models import Player, MatchPerformance, PlayerNews
from backend.modules.players.services.espn_service import (
    fetch_real_schedule,
    fetch_player_match_stats,
    fetch_player_upcoming_schedule_30d,
    get_espn_team_info,
    SCHEDULE_CACHE,
    SCHEDULE_30D_CACHE
)
from backend.modules.players.services.news_service import fetch_player_news_entries

TOP_LEAGUES = [
    "uefa.champions",
    "uefa.europa",
    "uefa.euro.conf",
    "eng.1",
    "esp.1",
    "ger.1",
    "ita.1",
    "fra.1",
    "usa.1"
]

def fetch_bulk_scoreboards() -> dict:
    """
    Tải hàng loạt bảng điểm của các giải đấu lớn trong 1 lượt (Bulk League Scoreboard).
    Trả về bản đồ: { team_name_lower: event_dict } giúp tra cứu kết quả/lịch đấu trong O(1).
    """
    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    dates_to_check = [
        (now_utc - datetime.timedelta(days=1)).strftime("%Y%m%d"),
        now_utc.strftime("%Y%m%d"),
        (now_utc + datetime.timedelta(days=1)).strftime("%Y%m%d")
    ]

    scoreboard_map = {}
    headers = {'User-Agent': 'Mozilla/5.0'}

    def _fetch_league_date(item):
        league, dt_str = item
        url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard?dates={dt_str}"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode())
            return league, data.get("events", [])
        except Exception:
            return league, []

    tasks = [(lg, dt_str) for lg in TOP_LEAGUES for dt_str in dates_to_check]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        results = list(ex.map(_fetch_league_date, tasks))

    for league, events in results:
        for ev in events:
            comp_obj = ev.get("competitions", [{}])[0]
            competitors = comp_obj.get("competitors", [])
            league_name = (
                comp_obj.get("league", {}).get("description") or
                ev.get("season", {}).get("displayName") or
                ev.get("league", {}).get("name") or
                league
            )
            status_desc = ev.get("status", {}).get("type", {}).get("description", "Scheduled")
            is_completed = ev.get("status", {}).get("type", {}).get("completed", False)
            state = "post" if is_completed else ("in" if "in progress" in status_desc.lower() or "half" in status_desc.lower() else "pre")

            for c in competitors:
                t_name = c.get("team", {}).get("displayName", "")
                t_short = c.get("team", {}).get("name", "")
                score = c.get("score")
                
                info = {
                    "event_id": ev.get("id"),
                    "match_name": ev.get("name"),
                    "date": ev.get("date"),
                    "state": state,
                    "status_desc": status_desc,
                    "competition": league_name,
                    "score": score,
                    "competitors": competitors
                }
                if t_name:
                    scoreboard_map[t_name.lower().strip()] = info
                if t_short and t_short.lower().strip() not in scoreboard_map:
                    scoreboard_map[t_short.lower().strip()] = info

    return scoreboard_map

def prefetch_unique_team_schedules(unique_teams: list):
    """
    Gom nhóm theo câu lạc bộ (Team-Level Batching):
    Chỉ gọi ESPN 1 lần duy nhất cho mỗi đội bóng và lưu vào cache bộ nhớ.
    """
    def _fetch_one(item):
        t_name, s_name = item
        if not t_name:
            return
        try:
            fetch_real_schedule(t_name, s_name)
            fetch_player_upcoming_schedule_30d(t_name, s_name)
        except Exception:
            pass

    workers_count = min(3, max(1, len(unique_teams)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers_count) as ex:
        list(ex.map(_fetch_one, unique_teams))

from backend.core.services.live_score_service import get_live_scores_map
import threading

_SYNC_LOCK = threading.Lock()

def execute_batched_sync(db: Session, update_news: bool = True) -> dict:
    """
    Tiến trình đồng bộ tối ưu hóa kiến trúc:
    1. Lấy danh sách vận động viên.
    2. Gom nhóm câu lạc bộ duy nhất (Team Batching).
    3. Tải scoreboard trực tiếp thời gian thực (Live Scores).
    4. Cập nhật dữ liệu trận đấu và tin tức trong 24h qua.
    """
    if not _SYNC_LOCK.acquire(blocking=False):
        return {"count": 0, "status": "already_syncing", "message": "Quá trình đồng bộ đang chạy ngầm, không chạy trùng lặp"}

    try:
        players = db.query(Player).all()
        if not players:
            return {"count": 0, "status": "no_players"}

        player_data = [
            (p.id, p.name, p.team_name, p.country_name, p.sport_name, p.name_aliases or "")
            for p in players
        ]

        # 1. Gom nhóm câu lạc bộ
        unique_teams = list({(t_name, s_name) for _, _, t_name, _, s_name, _ in player_data if t_name})
        prefetch_unique_team_schedules(unique_teams)

        # 2. Tải bảng điểm trực tiếp các giải lớn
        live_map = get_live_scores_map()

        # 3. Quét tin tức và dữ liệu trận đấu
        def _sync_player(task):
            p_id, p_name, p_team, p_country, p_sport, p_aliases = task
            try:
                sched = fetch_real_schedule(p_team, p_sport, player_name=p_name)
                m_name = sched["match_name"] if sched else "Chưa có dữ liệu lịch đấu"
                m_date = sched["match_date"] if sched else None
                m_state = sched.get("match_state", "pre") if sched else "pre"
                m_res = sched.get("match_result") if sched else None
                h_played = sched.get("has_played", False) if sched else False
                ev_id = sched.get("event_id") if sched else None
                m_comp = sched.get("competition") if sched else ""

                # Bổ sung thông tin từ live_map nếu đội đang thi đấu hoặc vừa thi đấu
                clean_team = (p_team or "").lower().strip()
                live_info = live_map.get(clean_team)
                if not live_info:
                    for k in live_map:
                        if k in clean_team or clean_team in k:
                            live_info = live_map[k]
                            break

                if live_info:
                    if not ev_id:
                        ev_id = live_info.get("event_id")
                    if not m_comp or m_comp == "Giải đấu":
                        m_comp = live_info.get("competition", m_comp)
                    if live_info.get("state") in ["in", "post"]:
                        m_state = live_info.get("state")
                    if live_info.get("match_result"):
                        m_res = live_info.get("match_result")

                news_entries = []
                if update_news:
                    news_entries = fetch_player_news_entries(p_name, p_aliases, p_country)

                p_news_titles = [ne['title'] for ne in news_entries] if news_entries else None
                stats_info = fetch_player_match_stats(p_name, p_sport, p_team, event_id=ev_id, match_state=m_state, news_titles=p_news_titles)

                return (p_id, m_name, m_date, m_state, m_res, h_played, stats_info, m_comp, news_entries)
            except Exception:
                return (p_id, None, None, "pre", None, False, {}, "", [])

        player_workers = min(3, max(1, len(player_data)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=player_workers) as ex:
            results = list(ex.map(_sync_player, player_data))

        # Ghi nhận kết quả vào cơ sở dữ liệu
        for p_id, m_name, m_date, m_state, m_res, h_played, stats_info, m_comp, news_entries in results:
            if m_name:
                actual_played = stats_info.get("has_played", h_played)
                perf = db.query(MatchPerformance).filter(MatchPerformance.player_id == p_id).first()
                if not perf:
                    perf = MatchPerformance(
                        player_id=p_id,
                        match_name=m_name,
                        match_date=m_date,
                        match_state=m_state,
                        match_result=m_res,
                        has_played=actual_played,
                        performance_rating=stats_info.get("rating"),
                        player_stats=stats_info.get("stats_text"),
                        impression_tags=", ".join(stats_info.get("tags", [])),
                        competition=m_comp
                    )
                    db.add(perf)
                else:
                    perf.match_name = m_name
                    perf.match_date = m_date
                    perf.match_state = m_state
                    perf.match_result = m_res
                    perf.has_played = actual_played
                    perf.performance_rating = stats_info.get("rating")
                    perf.player_stats = stats_info.get("stats_text")
                    perf.impression_tags = ", ".join(stats_info.get("tags", []))
                    perf.competition = m_comp

            if news_entries:
                now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
                cutoff_retention = now_utc - datetime.timedelta(days=30)
                db.query(PlayerNews).filter(
                    PlayerNews.player_id == p_id,
                    PlayerNews.published_at < cutoff_retention
                ).delete()

                existing_news = db.query(PlayerNews).filter(PlayerNews.player_id == p_id).all()
                existing_map = {n.source_url: n for n in existing_news}
                for item in news_entries:
                    if item["source_url"] in existing_map:
                        existing_map[item["source_url"]].news_type = item["news_type"]
                        continue
                    news_item = PlayerNews(
                        player_id=p_id,
                        title=item["title"],
                        source_url=item["source_url"],
                        news_type=item["news_type"],
                        region=item["region"],
                        published_at=item["published_at"]
                    )
                    db.add(news_item)
                db.commit()

        db.commit()
        try:
            from backend.core.routers.dashboard import invalidate_dashboard_cache
            invalidate_dashboard_cache()
        except Exception:
            pass
        import gc
        gc.collect()
        try:
            import ctypes
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except Exception:
            pass
        return {"count": len(players), "status": "completed"}
    finally:
        _SYNC_LOCK.release()

