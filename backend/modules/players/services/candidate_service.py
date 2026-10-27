import urllib.request
import urllib.parse
import json
import re
from backend.core.config import EN_TO_VI_MAP
from backend.core.services.wiki_service import fetch_free_player_info

def search_athlete_candidates(query: str) -> tuple[bool, list]:
    q_clean = query.strip()
    if not q_clean or len(q_clean) < 2:
        return False, []
    
    candidates = []
    seen = set()

    # 1. ESPN Search API
    try:
        url = f"https://site.web.api.espn.com/apis/search/v2?query={urllib.parse.quote(q_clean)}&limit=10"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=4) as r:
            d = json.loads(r.read().decode())
        
        for item in d.get("results", []):
            for c in item.get("contents", []):
                if c.get("type") == "player":
                    pname = c.get("displayName", "").strip()
                    desc = (c.get("description", "") or "").strip()
                    subtitle = (c.get("subtitle", "") or "").strip()
                    league_slug = (c.get("defaultLeagueSlug", "") or "").lower()
                    raw_sport = (c.get("sport", "") or "").lower()

                    sport = "Môn khác"
                    if "baseball" in raw_sport or "mlb" in league_slug or "mlb" in desc.lower():
                        sport = "Bóng chày"
                    elif "basketball" in raw_sport or "nba" in league_slug or "nba" in desc.lower():
                        sport = "Bóng rổ"
                    elif any(k in (desc.lower() + " " + raw_sport + " " + league_slug) for k in ["laliga", "premier", "soccer", "fifa", "afc", "uefa", "bundesliga", "serie a", "ligue 1", "mls", "champions", "football"]):
                        sport = "Bóng đá"
                    elif raw_sport in ["volleyball", "badminton", "tennis", "table tennis"]:
                        sport = EN_TO_VI_MAP.get(raw_sport, "Môn khác")

                    # Team resolution: subtitle has "Chicago Cubs", while description has "MLB"
                    team = subtitle or desc or "Tự do"
                    if team.upper() in ["MLB", "NBA", "SOCCER", "EPL", "LALIGA", "MMA"] and subtitle:
                        team = subtitle
                    if team.upper() in ["MLB", "NBA", "MMA"]:
                        team = "Tự do"

                    country = "Quốc tế"
                    flag = "🌐"
                    aliases = pname

                    # Check nationality from free Wikipedia profile
                    wiki_info = fetch_free_player_info(pname)
                    if wiki_info.get("found"):
                        if wiki_info.get("country_name") and wiki_info["country_name"] != "Quốc tế":
                            country = wiki_info["country_name"]
                            flag = wiki_info.get("country_flag", "🌐")
                        if (team in ["Tự do", "Chưa rõ CLB"] or len(team) <= 3) and wiki_info.get("team_name") and wiki_info["team_name"] not in ["Tự do", "Chưa rõ CLB"]:
                            team = wiki_info["team_name"]
                        wiki_sport = wiki_info.get("sport_name")
                        if wiki_sport and wiki_sport != "Môn khác":
                            # Prioritize Wikipedia when ESPN sport is non-soccer/baseball/basketball or matches athlete profile
                            if sport in ["Môn khác", "Thể thao"] or raw_sport not in ["soccer", "football", "baseball", "basketball"]:
                                sport = wiki_sport
                        if wiki_info.get("aliases"):
                            aliases = wiki_info["aliases"]

                    # Fallback check from name
                    if country == "Quốc tế":
                        for nat, info in EN_TO_VI_MAP.items():
                            if isinstance(info, dict) and nat.lower() in (pname.lower() + " " + desc.lower()):
                                country = info["name"]
                                flag = info["flag"]
                                break

                    if pname and pname.lower() not in seen:
                        seen.add(pname.lower())
                        # Exact score 100 if query matches name
                        score = 100 if q_clean.lower() == pname.lower() else (90 if q_clean.lower() in pname.lower() else 75)
                        candidates.append({
                            "name": pname,
                            "sport": sport,
                            "team": team,
                            "country": country,
                            "country_flag": flag,
                            "aliases": aliases,
                            "source": "ESPN",
                            "score": score
                        })
    except Exception:
        pass

    # 2. Wikipedia Search API (only if needed or exact matches)
    try:
        w_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote(q_clean)}&utf8=&format=json&srlimit=5"
        req = urllib.request.Request(w_url, headers={'User-Agent': 'SportsTrackingWeb/2.0 (contact: admin@sportstracker.local)'})
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.loads(r.read().decode())
        for res in d.get("query", {}).get("search", []):
            title = res.get("title", "")
            # MUST contain at least a major token of the searched player name (prevents random pages like "Fly ball pitcher")
            q_tokens = [t.lower() for t in q_clean.split() if len(t) >= 3]
            if q_tokens and not any(t in title.lower() for t in q_tokens):
                continue

            snip = re.sub(r'<[^>]+>', '', res.get("snippet", ""))
            snip_l = snip.lower()
            if any(k in snip_l for k in ["footballer", "soccer", "baseball", "basketball", "volleyball", "badminton", "tennis", "striker", "winger", "pitcher", "infielder", "guard", "forward"]):
                if title.lower() not in seen and not any(b in title.lower() for b in ["season", "list of", "league", "cup", "team", "club", "stadium", "tournament"]):
                    seen.add(title.lower())
                    wiki_info = fetch_free_player_info(title)
                    sport = wiki_info.get("sport_name", "Bóng đá") if wiki_info.get("found") else "Bóng đá"
                    team = wiki_info.get("team_name", "Tự do") if wiki_info.get("found") else "Tự do"
                    country = wiki_info.get("country_name", "Quốc tế") if wiki_info.get("found") else "Quốc tế"
                    flag = wiki_info.get("country_flag", "🌐") if wiki_info.get("found") else "🌐"
                    aliases = wiki_info.get("aliases", title) if wiki_info.get("found") else title

                    score = 100 if q_clean.lower() == title.lower() else (85 if q_clean.lower() in title.lower() else 65)
                    candidates.append({
                        "name": title,
                        "sport": sport,
                        "team": team,
                        "country": country,
                        "country_flag": flag,
                        "aliases": aliases,
                        "source": "Wikipedia",
                        "score": score
                    })
    except Exception:
        pass

    sport_order = {"Bóng đá": 1, "Bóng chày": 2, "Bóng rổ": 3, "Bóng chuyền": 4, "Cầu lông": 5, "Quần vợt": 6, "Bóng bàn": 7, "Môn khác": 8}
    candidates.sort(key=lambda x: (-x.get("score", 0), sport_order.get(x["sport"], 99)))

    # Phân giải giải đấu tương ứng của CLB để người dùng có đầy đủ thông tin Đội + Giải đấu
    from backend.modules.players.services.sports_service import resolve_team_league
    for c in candidates:
        team_name = c.get("team", "")
        sport_name = c.get("sport", "")
        if team_name and team_name not in ["Tự do", "Chưa rõ CLB", "Unknown"]:
            c["team_league"] = resolve_team_league(team_name, sport_name)
        else:
            c["team_league"] = ""

    # AMBIGUITY EVALUATION:
    # If the user typed an exact full name (e.g. "Shota Imanaga") and top candidate matches exactly:
    if len(candidates) == 1:
        return False, candidates
    
    if len(candidates) > 1:
        top = candidates[0]
        # If top score is 100 (exact match) and next candidate is not an exact match
        if top.get("score") == 100 and candidates[1].get("score") < 100:
            return False, [top]
        
        # If multiple candidates have score 100 (genuinely multiple people with same name)
        exact_matches = [c for c in candidates if c.get("score") == 100]
        if len(exact_matches) > 1:
            return True, exact_matches

        # If user searched a generic term like "Kubo" and multiple sports stars appear
        return True, candidates[:5]

    return False, []

