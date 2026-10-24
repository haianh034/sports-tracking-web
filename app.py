from main import app
from backend.db.session import SessionLocal, get_db
from backend.db.models import init_db, Sport, Nationality, Club, Player, MatchPerformance, PlayerNews
from backend.services.espn_service import fetch_real_schedule, fetch_player_match_stats, fetch_player_upcoming_schedule_30d
from backend.services.wiki_service import fetch_free_player_info, get_team_aliases_from_wiki
from backend.services.sports_service import resolve_team_league, get_tournament_tag, format_player_stats_and_tags
from backend.services.candidate_service import search_athlete_candidates
from backend.services.news_service import scan_player_news, fetch_player_news_entries
from backend.routers.dashboard import get_dashboard_data

__all__ = [
    "app", "SessionLocal", "get_db", "init_db",
    "Sport", "Nationality", "Club", "Player", "MatchPerformance", "PlayerNews",
    "fetch_real_schedule", "fetch_player_match_stats", "fetch_player_upcoming_schedule_30d",
    "fetch_free_player_info", "get_team_aliases_from_wiki",
    "resolve_team_league", "get_tournament_tag", "format_player_stats_and_tags",
    "search_athlete_candidates", "scan_player_news", "fetch_player_news_entries",
    "get_dashboard_data"
]
