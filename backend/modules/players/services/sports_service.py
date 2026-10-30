import urllib.request
import urllib.parse
import json
import re
from backend.config import LEAGUE_SLUG_MAP

TEAM_LEAGUE_CACHE = {}

def resolve_team_league(team_name: str, sport_name: str = "") -> str:
    clean = (team_name or "").strip()
    if not clean or clean.lower() in ["tự do", "unknown", ""]:
        return ""
    key = (clean.lower(), (sport_name or "").strip().lower())
    if key in TEAM_LEAGUE_CACHE:
        return TEAM_LEAGUE_CACHE[key]
    
    t_low = clean.lower()
    s_low = (sport_name or "").lower()

    # 1. Tra cứu giải đấu nổi tiếng theo môn (đặc biệt các môn ngoài bóng đá)
    # Asian & Global Baseball:
    if "chày" in s_low or "baseball" in s_low:
        kbo_clubs = ["kia tigers", "kia", "lg twins", "twins", "nc dinos", "dinos", "ssg landers", "landers", "samsung lions", "kt wiz", "doosan bears", "lotte giants", "hanwha eagles", "kiwoom heroes"]
        npb_clubs = [
            "hanshin", "yomiuri", "orix", "hiroshima carp", "carp", "chunichi dragons", "dragons", 
            "yakult swallows", "swallows", "baystars", "softbank hawks", "hawks", "seibu lions", 
            "chiba lotte", "marines", "nippon-ham", "fighters", "rakuten", "golden eagles", "buffaloes"
        ]
        if any(c in t_low for c in kbo_clubs):
            TEAM_LEAGUE_CACHE[key] = "KBO"
            return "KBO"
        if any(c in t_low for c in npb_clubs):
            TEAM_LEAGUE_CACHE[key] = "NPB"
            return "NPB"

    # Basketball:
    if "rổ" in s_low or "basketball" in s_low:
        euro_clubs = [
            "panathinaikos", "olympiacos", "fenerbahce", "fenerbahçe", "anadolu efes", 
            "maccabi", "partizan", "crvena zvezda", "virtus", "olimpia milano", 
            "baskonia", "zalgiris", "žalgiris", "asvel", "alba berlin", "monaco"
        ]
        bleague_clubs = ["chiba jets", "brex", "golden kings", "alvark", "brave thunders", "b-corsairs", "sun rockers", "diamond dolphins"]
        if any(c in t_low for c in euro_clubs):
            TEAM_LEAGUE_CACHE[key] = "EuroLeague"
            return "EuroLeague"
        if any(c in t_low for c in bleague_clubs):
            TEAM_LEAGUE_CACHE[key] = "B.League"
            return "B.League"

    # Volleyball:
    if "chuyền" in s_low or "volleyball" in s_low:
        if "ziraat" in t_low or "halkbank" in t_low or "arkas" in t_low:
            TEAM_LEAGUE_CACHE[key] = "Efeler Ligi"
            return "Efeler Ligi"
        if any(c in t_low for c in ["perugia", "milano", "trentino", "civitanova", "lube", "modena", "piacenza", "monza", "verona"]):
            TEAM_LEAGUE_CACHE[key] = "SuperLega"
            return "SuperLega"
        if any(c in t_low for c in ["suntory", "sunbirds", "bluteon", "panasonic", "jtekt", "wolfdogs", "toray", "thunders", "blazers", "great bears"]):
            TEAM_LEAGUE_CACHE[key] = "SV.League"
            return "SV.League"
        if any(c in t_low for c in ["hyundai capital", "korean air", "woori card", "vixtorm", "bluefangs", "kb insurance", "ok financial"]):
            TEAM_LEAGUE_CACHE[key] = "V-League (Hàn Quốc)"
            return "V-League (Hàn Quốc)"

    # 2. Truy vấn trực tiếp ESPN
    try:
        from backend.modules.players.services.espn_service import get_espn_team_info
        info = get_espn_team_info(clean, sport_name)
        if info and info.get("league"):
            slug = info["league"].lower()
            if slug in LEAGUE_SLUG_MAP:
                res_tag = LEAGUE_SLUG_MAP[slug]
                TEAM_LEAGUE_CACHE[key] = res_tag
                return res_tag
            if "sco." in slug:
                TEAM_LEAGUE_CACHE[key] = "Scottish Premiership"
                return "Scottish Premiership"
            if "bel." in slug:
                TEAM_LEAGUE_CACHE[key] = "Belgian Pro League"
                return "Belgian Pro League"
            if "sau." in slug:
                TEAM_LEAGUE_CACHE[key] = "Saudi Pro League"
                return "Saudi Pro League"
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
    
    # Helper for Continental context detection
    asian_club_indicators = [
        "machida", "zelvia", "vissel", "kobe", "kawasaki", "frontale", "urawa", "marinos", 
        "sanfrecce", "hiroshima", "gamba", "cerezo", "osaka", "kashima", "antlers", "nagoya", 
        "grampus", "fukuoka", "shimizu", "s-pulse", "tokyo", "albirex", "niigata", "kyoto sanga",
        "shanghai", "shenhua", "shandong", "taishan", "beijing", "guoan", "guangzhou", "zhejiang",
        "ulsan", "jeonbuk", "pohang", "steelers", "gwangju", "seoul", "incheon", "daegu", "suwon",
        "al hilal", "al-hilal", "al nassr", "al-nassr", "al ahli", "al-ahli", "al ittihad", "al-ittihad", 
        "al ain", "al sadd", "al duhail", "buriram", "bangkok", "johor", "central coast", "melbourne", "sydney fc"
    ]
    is_asian_context = any(k in t_lower or k in m_lower for k in asian_club_indicators)

    concacaf_indicators = [
        "galaxy", "lafc", "whitecaps", "sounders", "inter miami", "timbers", "cruz azul", 
        "america", "monterrey", "tigres", "pachuca", "columbus", "sporting kansas", "san miguelito", "cartaginés", "cartagines"
    ]
    is_concacaf_context = any(k in t_lower or k in m_lower for k in concacaf_indicators)

    # 1. Continental Cups (AFC, CONCACAF, CONMEBOL, CAF) - Check BEFORE UEFA/generic cups
    # AFC Champions League Elite (ACL Elite)
    if any(k in c_lower for k in ["afc champions league elite", "afc champions league 1", "afc cl elite", "afc.champions", "afc champions elite"]):
        return "AFC Champions League Elite"
    # AFC Champions League Two (ACL Two / former AFC Cup)
    if any(k in c_lower for k in ["afc champions league two", "afc champions league 2", "afc cl two", "afc.cup", "afc champions two"]):
        return "AFC Champions League Two"
    # AFC Challenge League
    if any(k in c_lower for k in ["afc challenge", "afc.challenge"]):
        return "AFC Challenge League"
    # AFC Asian Cup (National teams)
    if any(k in c_lower for k in ["afc asian cup", "asian cup", "afc.asian.cup"]):
        return "AFC Asian Cup"
    # Generic AFC Champions League / AFC Cup
    if any(k in c_lower for k in ["afc champions", "afc cl", "cúp c1 châu á"]):
        return "AFC Champions League"
    if "afc cup" in c_lower:
        return "AFC Cup"

    # CONCACAF / CONMEBOL / CAF
    if any(k in c_lower for k in ["concacaf champions", "concacaf.champions"]):
        return "Concacaf Champions Cup"
    if any(k in c_lower for k in ["copa libertadores", "libertadores", "conmebol.libertadores"]):
        return "Copa Libertadores"
    if any(k in c_lower for k in ["copa sudamericana", "sudamericana", "conmebol.sudamericana"]):
        return "Copa Sudamericana"
    if any(k in c_lower for k in ["caf champions", "caf.champions"]):
        return "CAF Champions League"

    # UEFA Continental Cups
    if any(k in c_lower for k in ["uefa champions league", "uefa.champions", "uefa cl"]):
        return "UEFA Champions League"
    if any(k in c_lower for k in ["uefa europa league", "uefa.europa", "uefa el"]):
        return "UEFA Europa League"
    if any(k in c_lower for k in ["uefa conference league", "uefa.conference", "uefa ecl"]):
        return "UEFA Conference League"

    # Context-aware generic "Champions League" / "UCL" / "C1"
    if any(k in c_lower for k in ["champions league", "ucl", "cúp c1", "c1"]):
        if is_asian_context:
            if "two" in c_lower or "2" in c_lower or "two" in m_lower or "2" in m_lower:
                return "AFC Champions League Two"
            elif "elite" in c_lower or "1" in c_lower or "elite" in m_lower:
                return "AFC Champions League Elite"
            return "AFC Champions League"
        if is_concacaf_context:
            return "Concacaf Champions Cup"
        return "UEFA Champions League"

    if any(k in c_lower for k in ["europa league", "uel", "cúp c2", "c2"]):
        return "UEFA Europa League"
    if any(k in c_lower for k in ["conference league", "uecl", "cúp c3", "c3"]):
        return "UEFA Conference League"
    
    # Domestic Cups
    if "fa cup" in c_lower: return "FA Cup"
    if "carabao" in c_lower or "efl cup" in c_lower: return "Carabao Cup"
    if "copa del rey" in c_lower: return "Copa del Rey"
    if "dfb-pokal" in c_lower or "german cup" in c_lower: return "DFB-Pokal"
    if "coppa italia" in c_lower: return "Coppa Italia"
    if "coupe de france" in c_lower: return "Coupe de France"

    # Germany: Check Bundesliga 2 BEFORE Bundesliga
    if any(k in c_lower for k in ["2. bundesliga", "2.bundesliga", "bundesliga 2", "zweite bundesliga", "german 2. bundesliga", "german bundesliga 2", "ger.2"]):
        return "Bundesliga 2"
    if "bundesliga" in c_lower or "german bundesliga" in c_lower or "ger.1" in c_lower:
        return "Bundesliga"

    # Spain: Check La Liga 2 BEFORE La Liga
    if any(k in c_lower for k in ["la liga 2", "laliga 2", "segunda division", "segunda división", "hypermotion", "esp.2"]):
        return "La Liga 2"
    if "la liga" in c_lower or "laliga" in c_lower or "esp.1" in c_lower:
        return "La Liga"

    # Italy: Check Serie B BEFORE Serie A
    if any(k in c_lower for k in ["serie b", "italian serie b", "ita.2"]):
        return "Serie B"
    if "serie a" in c_lower or "italian serie a" in c_lower or "ita.1" in c_lower:
        return "Serie A"

    # France: Check Ligue 2 BEFORE Ligue 1
    if any(k in c_lower for k in ["ligue 2", "french ligue 2", "fra.2"]):
        return "Ligue 2"
    if "ligue 1" in c_lower or "french ligue 1" in c_lower or "fra.1" in c_lower:
        return "Ligue 1"

    # England: Check Championship & Premier League
    if any(k in c_lower for k in ["championship", "efl championship", "eng.2"]):
        return "Championship"
    if "premier league" in c_lower or "epl" in c_lower or "english premier league" in c_lower or "eng.1" in c_lower:
        return "Premier League"

    # Other Domestic Leagues (Football)
    if "super lig" in c_lower or "süper lig" in c_lower or "superlig" in c_lower or "tur.1" in c_lower: return "Süper Lig"
    if "primeira liga" in c_lower or "portuguese primeira liga" in c_lower or "por.1" in c_lower: return "Primeira Liga"
    if "eredivisie" in c_lower or "ned.1" in c_lower: return "Eredivisie"
    if "scottish premiership" in c_lower or "premiership" in c_lower or "sco.1" in c_lower: return "Scottish Premiership"
    if "saudi pro league" in c_lower or "sau.1" in c_lower or "spl" in c_lower: return "Saudi Pro League"
    if "belgian pro league" in c_lower or "jupiler" in c_lower or "bel.1" in c_lower or ("pro league" in c_lower and "saudi" not in c_lower): return "Belgian Pro League"
    if "j1 league" in c_lower or "jpn.1" in c_lower: return "J1 League"
    if "k league" in c_lower or "kor.1" in c_lower: return "K League 1"
    if "mls" in c_lower or "major league soccer" in c_lower or "usa.1" in c_lower: return "MLS"

    # Multi-sport Tournament Resolution
    # 1. Baseball (Bóng chày)
    if any(k in c_lower for k in ["npb", "nippon professional baseball", "japan baseball"]): return "NPB"
    if "kbo" in c_lower: return "KBO"
    if "cpbl" in c_lower: return "CPBL"
    if "wbc" in c_lower or "world baseball classic" in c_lower: return "WBC"
    if "triple-a" in c_lower or "milb" in c_lower: return "MiLB (Triple-A)"
    if "mlb" in c_lower or "major league baseball" in c_lower: return "MLB"

    # 2. Basketball (Bóng rổ)
    if "euroleague" in c_lower or "euro league" in c_lower: return "EuroLeague"
    if "wnba" in c_lower: return "WNBA"
    if any(k in c_lower for k in ["b.league", "bleague", "b1 league"]): return "B.League"
    if "cba" in c_lower or "chinese basketball" in c_lower: return "CBA"
    if "kbl" in c_lower or "korean basketball" in c_lower: return "KBL"
    if "ncaa" in c_lower or "college basketball" in c_lower: return "NCAA"
    if "liga acb" in c_lower or "liga endesa" in c_lower: return "Liga ACB"
    if "nba" in c_lower: return "NBA"

    # 3. Tennis (Quần vợt)
    if "wimbledon" in c_lower: return "Wimbledon"
    if "us open" in c_lower or "u.s. open" in c_lower: return "US Open"
    if "roland garros" in c_lower or "french open" in c_lower: return "Roland Garros"
    if "australian open" in c_lower: return "Australian Open"
    if "atp masters" in c_lower or "masters 1000" in c_lower: return "ATP Masters 1000"
    if "wta 1000" in c_lower: return "WTA 1000"
    if "atp finals" in c_lower: return "ATP Finals"
    if "wta finals" in c_lower: return "WTA Finals"
    if "atp 500" in c_lower: return "ATP 500"
    if "wta 500" in c_lower: return "WTA 500"
    if "atp" in c_lower: return "ATP Tour"
    if "wta" in c_lower: return "WTA Tour"
    if "davis cup" in c_lower: return "Davis Cup"

    # 4. Volleyball (Bóng chuyền)
    if "superlega" in c_lower or "super lega" in c_lower or "italian superlega" in c_lower: return "SuperLega"
    if "efeler" in c_lower: return "Efeler Ligi"
    if "sultanlar" in c_lower: return "Sultanlar Ligi"
    if any(k in c_lower for k in ["sv.league", "sv league", "sv-league", "v.league japan"]): return "SV.League"
    if "cev" in c_lower or "volleyball champions" in c_lower: return "CEV Champions League"
    if "vnl" in c_lower or "nations league" in c_lower: return "Volleyball Nations League"
    if "v-league" in c_lower and ("korea" in c_lower or "hàn" in c_lower): return "V-League (Hàn Quốc)"

    # 5. Badminton (Cầu lông)
    if "all england" in c_lower: return "All England Open"
    if "world championships" in c_lower or "bwf world championships" in c_lower: return "BWF World Championships"
    if "super 1000" in c_lower: return "BWF Super 1000"
    if "super 750" in c_lower: return "BWF Super 750"
    if "super 500" in c_lower: return "BWF Super 500"
    if "super 300" in c_lower: return "BWF Super 300"
    if "bwf" in c_lower or "world tour" in c_lower: return "BWF World Tour"

    # 6. Table Tennis (Bóng bàn)
    if "grand smash" in c_lower: return "WTT Grand Smash"
    if "wtt champions" in c_lower: return "WTT Champions"
    if "star contender" in c_lower: return "WTT Star Contender"
    if "wtt finals" in c_lower: return "WTT Finals"
    if "wtt" in c_lower: return "WTT Series"
    if "ittf" in c_lower: return "ITTF World Tour"
    
    # If a specific, meaningful competition name is given, return it formatted
    if competition_name and len(competition_name.strip()) >= 3 and not competition_name.strip().lower() in ["giải đấu", "unknown", "thể thao"]:
        clean_ret = competition_name.strip()
        # Clean numeric year prefixes or suffixes like '2026/27 '
        clean_ret = re.sub(r'^(20\d\d[-/]\d\d|20\d\d)\s+', '', clean_ret)
        if clean_ret:
            return clean_ret

    m_lower = (match_name or "").lower()
    t_lower = (team_name or "").lower()
    s_lower = (sport_name or "").lower()

    if any(k in m_lower for k in ["afc champions league elite", "afc champions league 1", "afc cl elite"]):
        return "AFC Champions League Elite"
    if any(k in m_lower for k in ["afc champions league two", "afc champions league 2", "afc cl two"]):
        return "AFC Champions League Two"
    if any(k in m_lower for k in ["afc champions", "afc cl", "cúp c1 châu á"]):
        return "AFC Champions League"
    if "concacaf champions" in m_lower:
        return "Concacaf Champions Cup"

    if "champions league" in m_lower or "cúp c1" in m_lower or "ucl" in m_lower:
        if is_asian_context:
            return "AFC Champions League"
        if is_concacaf_context:
            return "Concacaf Champions Cup"
        return "UEFA Champions League"
    if "europa league" in m_lower or "uel" in m_lower or "c2" in m_lower:
        return "UEFA Europa League"
    if "conference league" in m_lower or "uecl" in m_lower:
        return "UEFA Conference League"

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

    # Only treat as European Champions League if both teams are established top-5 or top-tier European clubs
    if nations_matched >= 2:
        return "UEFA Champions League"

    # Dynamic resolution via Team / ESPN Catalog for any club worldwide
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
        # Football - European & Continental Cups
        "UEFA Champions League", "Champions League", 
        "UEFA Europa League", "Europa League", 
        "UEFA Conference League", "Conference League", 
        "AFC Champions League Elite", "AFC Champions League Two", "AFC Champions League",
        "AFC Challenge League", "AFC Cup", "AFC Asian Cup",
        "Concacaf Champions Cup", "Copa Libertadores", "Copa Sudamericana", "CAF Champions League", 
        # Football - Domestic Leagues
        "Premier League", "Championship", 
        "Bundesliga", "Bundesliga 2", 
        "La Liga", "La Liga 2", 
        "Serie A", "Serie B", 
        "Ligue 1", "Ligue 2", 
        "MLS", "Süper Lig", "Eredivisie", "Primeira Liga", 
        "Scottish Premiership", "Belgian Pro League", "Saudi Pro League",
        "J1 League", "K League 1", "Argentine Primera División", "Brasileirão",
        # Football - Cups
        "FA Cup", "Carabao Cup", "Copa del Rey", "DFB-Pokal", "Coppa Italia", "Coupe de France",
        # Baseball
        "MLB", "NPB", "KBO", "CPBL", "WBC", "MiLB (Triple-A)",
        # Basketball
        "NBA", "EuroLeague", "WNBA", "B.League", "CBA", "KBL", "NCAA", "Liga ACB",
        # Tennis
        "Wimbledon", "US Open", "Roland Garros", "Australian Open", 
        "ATP Masters 1000", "WTA 1000", "ATP Finals", "WTA Finals", "ATP 500", "WTA 500", "ATP Tour", "WTA Tour", "Davis Cup",
        # Volleyball
        "SuperLega", "Efeler Ligi", "Sultanlar Ligi", "SV.League", "CEV Champions League", "Volleyball Nations League", "V-League (Hàn Quốc)", "Bóng chuyền",
        # Badminton
        "All England Open", "BWF World Championships", "BWF Super 1000", "BWF Super 750", "BWF Super 500", "BWF Super 300", "BWF World Tour",
        # Table Tennis
        "WTT Grand Smash", "WTT Champions", "WTT Star Contender", "WTT Finals", "WTT Series", "ITTF World Tour"
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
        if t_low == "bàn quyết định": t = "Bàn mở tỉ số"
        if t_low in ["chưa thi đấu", "sắp thi đấu", "chờ lịch/hết mùa", "chờ lịch", "hết mùa", "đã thi đấu"]: continue
        if "tin tức" in t_low: continue
        if len(t) > 40: t = t[:40].strip()
        if t and t not in seen:
            seen.add(t)
            cleaned_tags.append(t)

    return "", cleaned_tags

