import urllib.request
import urllib.parse
import json
import re
from backend.config import LEAGUE_SLUG_MAP

TEAM_LEAGUE_CACHE = {}

KNOWN_CLUB_LEAGUES = {
    # Germany Bundesliga & Bundesliga 2
    "schalke 04": "Bundesliga",
    "schalke": "Bundesliga",
    "karlsruher sc": "Bundesliga 2",
    "karlsruher": "Bundesliga 2",
    "hertha bsc": "Bundesliga 2",
    "hertha": "Bundesliga 2",
    "hamburger sv": "Bundesliga 2",
    "1. fc köln": "Bundesliga 2",
    "fc köln": "Bundesliga 2",
    "fortuna düsseldorf": "Bundesliga 2",
    "hannover 96": "Bundesliga 2",
    "1. fc nürnberg": "Bundesliga 2",
    "nürnberg": "Bundesliga 2",
    "1. fc magdeburg": "Bundesliga 2",
    "magdeburg": "Bundesliga 2",
    "sv elversberg": "Bundesliga 2",
    "elversberg": "Bundesliga 2",
    "sc paderborn": "Bundesliga 2",
    "paderborn": "Bundesliga 2",
    "1. fc kaiserslautern": "Bundesliga 2",
    "kaiserslautern": "Bundesliga 2",
    "greuther fürth": "Bundesliga 2",
    "sv darmstadt 98": "Bundesliga 2",
    "darmstadt": "Bundesliga 2",
    "eintracht braunschweig": "Bundesliga 2",
    "preußen münster": "Bundesliga 2",
    "ssv jahn regensburg": "Bundesliga 2",
    "jahn regensburg": "Bundesliga 2",
    "ssv ulm 1846": "Bundesliga 2",
    "ssv ulm": "Bundesliga 2",
    
    # England Championship
    "leeds united": "Championship",
    "leeds": "Championship",
    "coventry city": "Championship",
    "coventry": "Championship",
    "hull city": "Championship",
    "hull": "Championship",
    "burnley": "Championship",
    "sheffield united": "Championship",
    "luton town": "Championship",
    "west bromwich albion": "Championship",
    "west brom": "Championship",
    "sunderland": "Championship",
    "middlesbrough": "Championship",
    "norwich city": "Championship",
    "watford": "Championship",
    "blackburn rovers": "Championship",
    "derby county": "Championship",
    "stoke city": "Championship",
    "portsmouth": "Championship",
    
    # France Ligue 2
    "fc metz": "Ligue 2",
    "metz": "Ligue 2",
    "fc lorient": "Ligue 2",
    "lorient": "Ligue 2",
    "clermont foot": "Ligue 2",
    "guingamp": "Ligue 2",
    "paris fc": "Ligue 2",
    
    # Spain La Liga 2
    "real zaragoza": "La Liga 2",
    "zaragoza": "La Liga 2",
    "sporting gijón": "La Liga 2",
    "sporting gijon": "La Liga 2",
    "real oviedo": "La Liga 2",
    "racing santander": "La Liga 2",
    "levante ud": "La Liga 2",
    "levante": "La Liga 2",
    "elche cf": "La Liga 2",
    "eibar": "La Liga 2",
    "cádiz cf": "La Liga 2",
    "almería": "La Liga 2",
    "granada cf": "La Liga 2",
    "deportivo la coruña": "La Liga 2",
    
    # Italy Serie B
    "palermo": "Serie B",
    "sampdoria": "Serie B",
    "us sassuolo": "Serie B",
    "sassuolo": "Serie B",
    "salernitana": "Serie B",
    "frosinone": "Serie B",
    "spezia": "Serie B",
    "bari": "Serie B",
    "cremonese": "Serie B",
    "pisa": "Serie B"
}

def resolve_team_league(team_name: str, sport_name: str = "") -> str:
    clean = (team_name or "").strip()
    if not clean or clean.lower() in ["tự do", "unknown", ""]:
        return ""
    key = clean.lower()
    if key in KNOWN_CLUB_LEAGUES:
        return KNOWN_CLUB_LEAGUES[key]
    for kn_k, kn_val in KNOWN_CLUB_LEAGUES.items():
        if kn_k in key or key in kn_k:
            return kn_val

    if key in TEAM_LEAGUE_CACHE:
        return TEAM_LEAGUE_CACHE[key]
    
    try:
        url = f"https://site.web.api.espn.com/apis/search/v2?query={urllib.parse.quote(clean)}&limit=3"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=3) as res:
            data = json.loads(res.read().decode())
            for item in data.get("results", []):
                for content in item.get("contents", []):
                    slug = content.get("defaultLeagueSlug", "") or ""
                    sub = (content.get("subtitle", "") or "").lower()
                    if slug in LEAGUE_SLUG_MAP:
                        res_tag = LEAGUE_SLUG_MAP[slug]
                        TEAM_LEAGUE_CACHE[key] = res_tag
                        return res_tag
                    
                    # Check 2nd tiers before 1st tiers
                    if any(k in sub for k in ["2. bundesliga", "2.bundesliga", "bundesliga 2", "zweite"]):
                        TEAM_LEAGUE_CACHE[key] = "Bundesliga 2"
                        return "Bundesliga 2"
                    if "bundesliga" in sub:
                        TEAM_LEAGUE_CACHE[key] = "Bundesliga"
                        return "Bundesliga"
                    
                    if any(k in sub for k in ["la liga 2", "laliga 2", "segunda", "hypermotion"]):
                        TEAM_LEAGUE_CACHE[key] = "La Liga 2"
                        return "La Liga 2"
                    if "la liga" in sub or "laliga" in sub:
                        TEAM_LEAGUE_CACHE[key] = "La Liga"
                        return "La Liga"
                    
                    if "serie b" in sub:
                        TEAM_LEAGUE_CACHE[key] = "Serie B"
                        return "Serie B"
                    if "serie a" in sub:
                        TEAM_LEAGUE_CACHE[key] = "Serie A"
                        return "Serie A"
                    
                    if "ligue 2" in sub:
                        TEAM_LEAGUE_CACHE[key] = "Ligue 2"
                        return "Ligue 2"
                    if "ligue 1" in sub:
                        TEAM_LEAGUE_CACHE[key] = "Ligue 1"
                        return "Ligue 1"
                    
                    if "championship" in sub:
                        TEAM_LEAGUE_CACHE[key] = "Championship"
                        return "Championship"
                    if "premier league" in sub:
                        TEAM_LEAGUE_CACHE[key] = "Premier League"
                        return "Premier League"
                    
                    if "eredivisie" in sub:
                        TEAM_LEAGUE_CACHE[key] = "Eredivisie"
                        return "Eredivisie"
    except Exception:
        pass
    
    TEAM_LEAGUE_CACHE[key] = ""
    return ""

def get_tournament_tag(team_name: str, sport_name: str, match_name: str = "", competition_name: str = "") -> str:
    raw_c = (competition_name or "").strip()
    # Filter out numeric season years like '2026', '2027', '2024-25', '2026/27'
    if raw_c.isdigit() or (len(raw_c) <= 9 and raw_c.replace("-", "").replace("/", "").isdigit()):
        competition_name = ""
    
    c_lower = (competition_name or "").lower()
    m_lower = (match_name or "").lower()
    t_lower = (team_name or "").lower()
    s_lower = (sport_name or "").lower()
    
    # 1. Exact match by competition name from ESPN / official data
    # European cups
    if any(k in c_lower for k in ["champions league", "ucl", "cúp c1", "c1", "uefa.champions"]): return "Champions League"
    if any(k in c_lower for k in ["europa league", "uel", "cúp c2", "c2", "uefa.europa"]): return "Europa League"
    if any(k in c_lower for k in ["conference league", "uecl", "cúp c3", "c3", "uefa.conference"]): return "Conference League"
    
    # Domestic Cups
    if "fa cup" in c_lower: return "FA Cup"
    if "carabao" in c_lower or "efl cup" in c_lower: return "Carabao Cup"
    if "copa del rey" in c_lower: return "Copa del Rey"
    if "dfb-pokal" in c_lower or "german cup" in c_lower: return "DFB-Pokal"
    if "coppa italia" in c_lower: return "Coppa Italia"
    if "coupe de france" in c_lower: return "Coupe de France"

    # Germany: Check Bundesliga 2 BEFORE Bundesliga
    if any(k in c_lower for k in ["2. bundesliga", "2.bundesliga", "bundesliga 2", "zweite bundesliga", "german 2. bundesliga", "german bundesliga 2", "ger.2"]):
        if any(t in t_lower for t in ["schalke"]):
            return "Bundesliga"
        return "Bundesliga 2"
    if "bundesliga" in c_lower or "german bundesliga" in c_lower or "ger.1" in c_lower:
        # Extra guard: Check if team is known to be in Bundesliga 2 (excluding Schalke 04)
        if any(t in t_lower for t in ["karlsruher", "hertha", "hamburger sv", "hsv", "magdeburg", "nürnberg", "paderborn", "kaiserslautern", "düsseldorf", "elversberg", "fürth"]):
            return "Bundesliga 2"
        return "Bundesliga"

    # Spain: Check La Liga 2 BEFORE La Liga
    if any(k in c_lower for k in ["la liga 2", "laliga 2", "segunda division", "segunda división", "hypermotion", "esp.2"]):
        return "La Liga 2"
    if "la liga" in c_lower or "laliga" in c_lower or "esp.1" in c_lower:
        if any(t in t_lower for t in ["zaragoza", "sporting gijon", "oviedo", "racing santander", "levante", "elche", "albacete", "tenerife", "eibar", "cadiz", "almeria", "granada", "deportivo la coruña"]):
            return "La Liga 2"
        return "La Liga"

    # Italy: Check Serie B BEFORE Serie A
    if any(k in c_lower for k in ["serie b", "italian serie b", "ita.2"]):
        return "Serie B"
    if "serie a" in c_lower or "italian serie a" in c_lower or "ita.1" in c_lower:
        if any(t in t_lower for t in ["palermo", "sampdoria", "sassuolo", "salernitana", "frosinone", "spezia", "bari", "cesena", "cremonese", "pisa", "brescia"]):
            return "Serie B"
        return "Serie A"

    # France: Check Ligue 2 BEFORE Ligue 1
    if any(k in c_lower for k in ["ligue 2", "french ligue 2", "fra.2"]):
        return "Ligue 2"
    if "ligue 1" in c_lower or "french ligue 1" in c_lower or "fra.1" in c_lower:
        if any(t in t_lower for t in ["metz", "lorient", "clermont", "bordeaux", "caen", "guingamp", "paris fc", "troyes"]):
            return "Ligue 2"
        return "Ligue 1"

    # England: Check Championship & Premier League
    if "championship" in c_lower or "efl championship" in c_lower or "eng.2" in c_lower:
        return "Championship"
    if "premier league" in c_lower or "epl" in c_lower or "english premier league" in c_lower or "eng.1" in c_lower:
        if any(t in t_lower for t in ["leeds", "burnley", "sheffield united", "luton", "west brom", "sunderland", "middlesbrough", "norwich", "coventry", "hull", "watford", "stoke", "blackburn"]):
            return "Championship"
        return "Premier League"

    # Other Domestic Leagues
    if "super lig" in c_lower or "süper lig" in c_lower or "superlig" in c_lower or "tur.1" in c_lower: return "Süper Lig"
    if "primeira liga" in c_lower or "portuguese primeira liga" in c_lower or "por.1" in c_lower: return "Primeira Liga"
    if "eredivisie" in c_lower or "ned.1" in c_lower: return "Eredivisie"
    if "mls" in c_lower or "major league soccer" in c_lower or "usa.1" in c_lower: return "MLS"
    if "mlb" in c_lower or "major league baseball" in c_lower: return "MLB"
    if "nba" in c_lower: return "NBA"
    
    m_lower = (match_name or "").lower()
    t_lower = (team_name or "").lower()
    s_lower = (sport_name or "").lower()

    if "champions league" in m_lower or "cúp c1" in m_lower or "ucl" in m_lower: return "Champions League"
    if "europa league" in m_lower or "uel" in m_lower or "c2" in m_lower: return "Europa League"
    if "conference league" in m_lower or "uecl" in m_lower: return "Conference League"

    # Cross-league European clashes (teams from different domestic leagues)
    eng_clubs = ["arsenal", "liverpool", "manchester", "chelsea", "aston villa", "tottenham", "brighton", "crystal palace", "newcastle", "west ham"]
    esp_clubs = ["real madrid", "barcelona", "atlético", "atletico", "sociedad", "villarreal", "girona", "sevilla", "mallorca", "athletic club", "bilbao", "betis"]
    ger_clubs = ["bayern", "dortmund", "leverkusen", "leipzig", "stuttgart", "frankfurt", "freiburg", "mainz", "wolfsburg", "heidenheim", "hoffenheim"]
    fra_clubs = ["psg", "paris", "paris saint-germain", "monaco", "marseille", "lille", "lyon", "brest", "nice", "lens"]
    ita_clubs = ["inter", "milan", "juventus", "atalanta", "roma", "lazio", "napoli", "bologna", "fiorentina"]
    por_clubs = ["benfica", "sporting", "porto", "braga", "guimaraes"]
    ned_clubs = ["ajax", "feyenoord", "psv", "alkmaar", "twente"]
    sco_clubs = ["celtic", "rangers"]
    bel_clubs = ["club brugge", "anderlecht", "union sg", "gent", "genk"]
    tur_clubs = ["galatasaray", "fenerbahce", "besiktas", "trabzonspor"]
    other_eu_clubs = ["shakhtar", "salzburg", "sturm graz", "sparta prague", "slavia prague", "viktoria plzen", "dinamo", "crvena zvezda", "young boys", "olympiacos", "paok", "bodø", "bodo", "malmo", "viking", "jablonec", "lillestrom"]

    all_names = f"{m_lower} {t_lower}"
    nations_matched = 0
    groups = [eng_clubs, esp_clubs, ger_clubs, fra_clubs, ita_clubs, por_clubs, ned_clubs, sco_clubs, bel_clubs, tur_clubs, other_eu_clubs]
    for grp in groups:
        if any(c in all_names for c in grp):
            nations_matched += 1

    # Only treat as Champions League if both teams are established top-5 or top-tier European clubs
    if nations_matched >= 2:
        # If any team is typically Europa/Conference league tier (e.g. from smaller leagues), let ESPN competition name handle it or default properly
        return "Champions League"

    if "bóng chày" in s_lower or "baseball" in s_lower:
        return "MLB"
    if "bóng rổ" in s_lower or "basketball" in s_lower:
        return "NBA"
    if "bóng chuyền" in s_lower or "volleyball" in s_lower:
        if "ziraat" in t_lower:
            return "Efeler Ligi"
        if any(c in t_lower for c in ["perugia", "milano", "trentino", "civitanova"]):
            return "SuperLega"
        return "Bóng chuyền"
    if "cầu lông" in s_lower or "badminton" in s_lower:
        return "BWF World Tour"
    if "bóng bàn" in s_lower or "table tennis" in s_lower:
        return "WTT Series"

    # Dynamic resolution via ESPN Search API for any club worldwide
    dyn_tag = resolve_team_league(team_name, sport_name)
    if dyn_tag:
        return dyn_tag

    return ""

def format_player_stats_and_tags(player_name: str, sport_name: str, team_name: str, match_name: str, match_state: str, existing_stats: str = None, existing_tags: list = None, competition_name: str = "", news_titles: list = None, is_no_match: bool = False) -> tuple:
    tourn_tag = get_tournament_tag(team_name, sport_name, match_name, competition_name)

    final_tags = []
    if tourn_tag and not is_no_match:
        final_tags.append(tourn_tag)

    ALL_TOURNAMENT_TAGS = {
        "Champions League", "Europa League", "Conference League", 
        "Premier League", "Championship", 
        "Bundesliga", "Bundesliga 2", 
        "La Liga", "La Liga 2", 
        "Serie A", "Serie B", 
        "Ligue 1", "Ligue 2", 
        "MLS", "NBA", "MLB", 
        "Süper Lig", "Eredivisie", "Primeira Liga", 
        "FA Cup", "Carabao Cup", "Copa del Rey", "DFB-Pokal", "Coppa Italia", "Coupe de France",
        "Efeler Ligi", "Turkish Efeler Ligi", "Italian SuperLega", "SuperLega", "SV.League", 
        "BWF World Tour", "WTT Champions", "WTT Finals", "WTT Series"
    }
    clean_existing_tags = [t for t in (existing_tags or []) if t not in ALL_TOURNAMENT_TAGS]

    def matches_injury_kw(kw: str, text: str) -> bool:
        if not kw or not text: return False
        if re.match(r'^[a-zA-Z0-9\s\-]+$', kw):
            return bool(re.search(r'\b' + re.escape(kw) + r'\b', text, re.IGNORECASE))
        return kw in text

    # Check for injury keywords in news
    has_injury_in_news = False
    if news_titles and not is_no_match:
        INJURY_KWS = ["chấn thương", "nghỉ thi đấu", "vắng mặt", "phẫu thuật", "rách cơ", "đau cơ", "quá tải", "dây chằng", "đầu gối", "injury", "injured", "out with", "surgery", "sprain", "torn", "acl", "hamstring", "concussion", "fracture", "부상", "결장", "수술", "십자인대", "근육 과부하", "怪我", "負傷", "離脱", "欠場", "手術", "ベンチ外"]
        FALSE_INJURY_PHRASES = [
            "not surgery", "no surgery", "offseason rest", "off-season rest", "avoids injury", 
            "avoid injury", "past injury", "healed", "cleared", "injury scare cleared", 
            "không phải phẫu thuật", "tránh chấn thương", "nghỉ ngơi sau mùa", "hết mùa giải"
        ]
        for nt in news_titles:
            nt_low = nt.lower()
            if any(fp in nt_low for fp in FALSE_INJURY_PHRASES):
                continue
            if any(matches_injury_kw(kw, nt_low) for kw in INJURY_KWS):
                has_injury_in_news = True
                break

    if is_no_match:
        # Offseason / No Match: No injury tag or sideline tag
        pass
    elif match_state == "in":
        if clean_existing_tags:
            for t in clean_existing_tags:
                if t and t not in final_tags:
                    final_tags.append(t)
        else:
            final_tags.append("Đang diễn ra")
    elif match_state == "post":
        if clean_existing_tags:
            for t in clean_existing_tags:
                if t == "Không thi đấu" and has_injury_in_news:
                    final_tags.append("Không đăng ký (Chấn thương)")
                elif t and t not in final_tags:
                    final_tags.append(t)
        else:
            if has_injury_in_news:
                final_tags.append("Không đăng ký (Chấn thương)")
            else:
                final_tags.append("Không thi đấu")
    else:
        # Pre-match or upcoming
        if clean_existing_tags:
            for t in clean_existing_tags:
                if t and t not in final_tags:
                    final_tags.append(t)
        if has_injury_in_news and "Chấn thương" not in final_tags and not any("chấn thương" in t.lower() for t in final_tags):
            final_tags.append("Chấn thương")

    cleaned_tags = []
    seen = set()
    for t in final_tags:
        if not t: continue
        t = t.strip()
        t_low = t.lower()
        if t_low in ["thủ môn", "hậu vệ"]: continue
        if "cứu thua" in t_low and "xuất sắc" not in t_low: continue
        if "vào sân từ ghế dự bị" in t_low: t = "Vào sân"
        if t_low in ["chưa thi đấu", "sắp thi đấu", "chờ lịch/hết mùa", "chờ lịch", "hết mùa", "đã thi đấu"]: continue
        if "tin tức" in t_low: continue
        if len(t) > 40: t = t[:40].strip()
        if t and t not in seen:
            seen.add(t)
            cleaned_tags.append(t)

    return "", cleaned_tags

