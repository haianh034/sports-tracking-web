import os
from pathlib import Path
import unicodedata
import re

def normalize_player_name(name: str) -> str:
    """
    Chuẩn hóa tên cầu thủ:
    - Loại bỏ dấu thanh, macron (ō -> o, ū -> u, é -> e, ä -> a...)
    - Chuẩn hóa trường âm tiếng Nhật (Kou -> Ko, Ryoutarou -> Ryotaro, Yuuto -> Yuto...)
    - Chuẩn hóa khoảng trắng và chuyển chữ thường
    Giúp chống trùng lặp dữ liệu do typo hoặc khác biệt giữa các hệ chuyển tự Latin (Hepburn, Wāpuro).
    """
    if not name:
        return ""
    nfkd = unicodedata.normalize('NFKD', str(name))
    ascii_str = ''.join(c for c in nfkd if not unicodedata.combining(c))
    clean = re.sub(r'[\s\.\-]+', ' ', ascii_str).strip().lower()

    # Quy chuẩn trường âm tiếng Nhật (ou -> o, uu -> u) cho phụ âm tiếng Nhật
    c_patt = r'(?:ky|gy|sh|ch|ny|hy|by|py|my|ry|ts|[kstnhmyrwgzjdbp])'
    clean = re.sub(rf'\b{c_patt}ou\b', lambda m: m.group(0)[:-2] + 'o', clean)
    clean = re.sub(rf'({c_patt})ou(?=[bcdfghjklmnpqrstvwxyz])', r'\1o', clean)
    clean = re.sub(rf'({c_patt})ou\b', r'\1o', clean)
    clean = re.sub(rf'({c_patt})uu(?=[bcdfghjklmnpqrstvwxyz])', r'\1u', clean)
    clean = re.sub(rf'({c_patt})uu\b', r'\1u', clean)
    return clean

# Load environment variables from .env file if present
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_path.exists():
    with open(_env_path, "r", encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                _k = _k.strip()
                _v = _v.strip().strip("'").strip('"')
                if _k not in os.environ:
                    os.environ[_k] = _v

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./sports_tracker.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
if "?pgbouncer=true" in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("?pgbouncer=true", "")
elif "&pgbouncer=true" in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("&pgbouncer=true", "")

EN_TO_VI_MAP = {
    "Japan": {"name": "Nhật Bản", "tz": "JST", "flag": "🇯🇵"},
    "Japanese": {"name": "Nhật Bản", "tz": "JST", "flag": "🇯🇵"},
    "South Korea": {"name": "Hàn Quốc", "tz": "KST", "flag": "🇰🇷"},
    "Korean": {"name": "Hàn Quốc", "tz": "KST", "flag": "🇰🇷"},
    "Vietnam": {"name": "Việt Nam", "tz": "ICT", "flag": "🇻🇳"},
    "Vietnamese": {"name": "Việt Nam", "tz": "ICT", "flag": "🇻🇳"},
    "France": {"name": "Pháp", "tz": "CET", "flag": "🇫🇷"},
    "French": {"name": "Pháp", "tz": "CET", "flag": "🇫🇷"},
    "Spain": {"name": "Tây Ban Nha", "tz": "CET", "flag": "🇪🇸"},
    "Spanish": {"name": "Tây Ban Nha", "tz": "CET", "flag": "🇪🇸"},
    "United States": {"name": "Mỹ", "tz": "EDT", "flag": "🇺🇸"},
    "American": {"name": "Mỹ", "tz": "EDT", "flag": "🇺🇸"},
    "England": {"name": "Anh", "tz": "BST", "flag": "🏴󠁧󠁢󠁥󠁮󠁧󠁿"},
    "English": {"name": "Anh", "tz": "BST", "flag": "🏴󠁧󠁢󠁥󠁮󠁧󠁿"},
    "Germany": {"name": "Đức", "tz": "CEST", "flag": "🇩🇪"},
    "German": {"name": "Đức", "tz": "CEST", "flag": "🇩🇪"},
    "Argentina": {"name": "Argentina", "tz": "ART", "flag": "🇦🇷"},
    "Argentine": {"name": "Argentina", "tz": "ART", "flag": "🇦🇷"},
    "Brazil": {"name": "Brazil", "tz": "BRT", "flag": "🇧🇷"},
    "Brazilian": {"name": "Brazil", "tz": "BRT", "flag": "🇧🇷"},
    "Portugal": {"name": "Bồ Đào Nha", "tz": "WET", "flag": "🇵🇹"},
    "Portuguese": {"name": "Bồ Đào Nha", "tz": "WET", "flag": "🇵🇹"},
    "Italy": {"name": "Ý", "tz": "CEST", "flag": "🇮🇹"},
    "Italian": {"name": "Ý", "tz": "CEST", "flag": "🇮🇹"},
    
    # Sports map
    "football": "Bóng đá",
    "footballer": "Bóng đá",
    "soccer": "Bóng đá",
    "basketball": "Bóng rổ",
    "baseball": "Bóng chày",
    "pitcher": "Bóng chày",
    "infielder": "Bóng chày",
    "outfielder": "Bóng chày",
    "batter": "Bóng chày",
    "catcher": "Bóng chày",
    "mlb": "Bóng chày",
    "nba": "Bóng rổ",
    "volleyball": "Bóng chuyền",
    "badminton": "Cầu lông",
    "table tennis": "Bóng bàn",
    "ping pong": "Bóng bàn",
    "tennis": "Quần vợt",
    "golf": "Golf",
    "golfer": "Golf",
    "formula 1": "Đua xe F1",
    "formula one": "Đua xe F1",
    "f1": "Đua xe F1",
    "racing": "Đua xe",
    "motorsport": "Đua xe",
    "mma": "MMA / UFC",
    "ufc": "MMA / UFC",
    "mixed martial arts": "MMA / UFC",
    "boxing": "Quyền anh",
    "boxer": "Quyền anh",
    "hockey": "Khúc côn cầu",
    "ice hockey": "Khúc côn cầu",
    "nhl": "Khúc côn cầu",
    "american football": "Bóng bầu dục Mỹ",
    "nfl": "Bóng bầu dục Mỹ",
    "rugby": "Bóng bầu dục",
    "cricket": "Cricket",
    "swimming": "Bơi lội",
    "swimmer": "Bơi lội",
    "athletics": "Điền kinh",
    "track and field": "Điền kinh",
    "gymnastics": "Thể dục dụng cụ",
    "gymnast": "Thể dục dụng cụ",
    "figure skating": "Trượt băng nghệ thuật",
    "figure skater": "Trượt băng nghệ thuật",
    "cycling": "Đua xe đạp",
    "cyclist": "Đua xe đạp",
    "esports": "Esports",
    "snooker": "Billiards / Snooker",
    "billiards": "Billiards / Snooker",
    "handball": "Bóng ném",
    "futsal": "Futsal",
    "darts": "Phi tiêu (Darts)",
    "water polo": "Bóng nước",
    "field hockey": "Khúc côn cầu trên cỏ",
    "floorball": "Floorball",
    "bandy": "Bandy",
    "beach volleyball": "Bóng chuyền bãi biển",
    "beach soccer": "Bóng đá bãi biển",
    "netball": "Bóng lưới",
    "kabaddi": "Kabaddi",
    "rugby union": "Bóng bầu dục",
    "rugby league": "Bóng bầu dục",
    "australian rules football": "Bóng bầu dục Úc",
    "aussie rules": "Bóng bầu dục Úc",
    "judo": "Judo",
    "judoka": "Judo",
    "wrestling": "Đấu vật",
    "fencing": "Đấu kiếm",
    "archery": "Bắn cung",
    "shooting": "Bắn súng",
    "weightlifting": "Cử tạ",
    "taekwondo": "Taekwondo",
    "karate": "Karate",
    "badminton player": "Cầu lông",
    "table tennis player": "Bóng bàn",
}

SPORT_TO_ESPN = {
    "Bóng đá": "soccer",
    "Bóng rổ": "basketball",
    "Bóng chày": "baseball",
    "Khúc côn cầu": "hockey",
    "Quần vợt": "tennis",
    "Tennis": "tennis",
    "Golf": "golf",
    "Đua xe F1": "racing",
    "Đua xe": "racing",
    "F1": "racing",
    "MMA / UFC": "mma",
    "MMA": "mma",
    "UFC": "mma",
    "Quyền anh": "boxing",
    "Boxing": "boxing",
    "Bóng bầu dục Mỹ": "football",
    "NFL": "football",
    "Bóng bầu dục": "rugby",
    "Cricket": "cricket",
    "Bóng vợt": "lacrosse",
    "Bóng bầu dục Úc": "australian-football",
}

ESPN_INDIVIDUAL_SPORT_LEAGUES = {
    "tennis": ["atp", "wta"],
    "golf": ["pga", "lpga", "eur"],
    "racing": ["f1", "irl", "nascar-premier"],
    "mma": ["ufc"],
}

# Flashscore.mobi supported sport slugs (covers 27 live sports)
FLASHSCORE_SPORT_SLUGS = {
    "soccer": "",
    "football": "",
    "bóng đá": "",
    "hockey": "hockey",
    "ice hockey": "hockey",
    "khúc côn cầu": "hockey",
    "khúc côn cầu trên băng": "hockey",
    "tennis": "tennis",
    "quần vợt": "tennis",
    "basketball": "basketball",
    "bóng rổ": "basketball",
    "handball": "handball",
    "bóng ném": "handball",
    "volleyball": "volleyball",
    "bóng chuyền": "volleyball",
    "baseball": "baseball",
    "bóng chày": "baseball",
    "american football": "american-football",
    "am. football": "american-football",
    "bóng bầu dục mỹ": "american-football",
    "rugby": "rugby-union",
    "rugby union": "rugby-union",
    "bóng bầu dục": "rugby-union",
    "rugby league": "rugby-league",
    "aussie rules": "aussie-rules",
    "australian rules football": "aussie-rules",
    "bóng bầu dục úc": "aussie-rules",
    "badminton": "badminton",
    "cầu lông": "badminton",
    "bandy": "bandy",
    "beach soccer": "beach-soccer",
    "bóng đá bãi biển": "beach-soccer",
    "beach volleyball": "beach-volleyball",
    "bóng chuyền bãi biển": "beach-volleyball",
    "boxing": "boxing",
    "quyền anh": "boxing",
    "cricket": "cricket",
    "darts": "darts",
    "phi tiêu": "darts",
    "phi tiêu (darts)": "darts",
    "field hockey": "field-hockey",
    "khúc côn cầu trên cỏ": "field-hockey",
    "floorball": "floorball",
    "futsal": "futsal",
    "kabaddi": "kabaddi",
    "mma": "mma",
    "mma / ufc": "mma",
    "ufc": "mma",
    "netball": "netball",
    "bóng lưới": "netball",
    "snooker": "snooker",
    "billiards": "snooker",
    "billiards / snooker": "snooker",
    "table tennis": "table-tennis",
    "ping pong": "table-tennis",
    "bóng bàn": "table-tennis",
    "water polo": "water-polo",
    "bóng nước": "water-polo",
}

def resolve_flashscore_sport_slug(sport_name: str) -> str | None:
    """Resolve an arbitrary Vietnamese/English sport name to its Flashscore.mobi slug ('' means football)."""
    if not sport_name:
        return None
    s_low = sport_name.strip().lower()
    if s_low in FLASHSCORE_SPORT_SLUGS:
        return FLASHSCORE_SPORT_SLUGS[s_low]
    for k, slug in FLASHSCORE_SPORT_SLUGS.items():
        if k in s_low or s_low in k:
            return slug
    # Dynamic slug normalization for arbitrary English sport names (e.g. "Beach soccer" -> "beach-soccer")
    ascii_s = unicodedata.normalize("NFKD", s_low).encode("ASCII", "ignore").decode("utf-8")
    candidate = re.sub(r"[^a-z0-9]+", "-", ascii_s).strip("-")
    valid_slugs = set(FLASHSCORE_SPORT_SLUGS.values()) - {""}
    if candidate in valid_slugs:
        return candidate
    return None

def resolve_espn_sport_code(sport_name: str) -> str | None:
    """Resolve an arbitrary Vietnamese/English sport name to its ESPN sport slug, or None if not an ESPN sport."""
    if not sport_name:
        return None
    s_clean = sport_name.strip()
    if s_clean in SPORT_TO_ESPN:
        return SPORT_TO_ESPN[s_clean]
    s_low = s_clean.lower()
    for k, v in SPORT_TO_ESPN.items():
        if k.lower() == s_low:
            return v
    if any(k in s_low for k in ["bóng đá", "soccer", "football (soccer)"]):
        return "soccer"
    if any(k in s_low for k in ["bóng rổ", "basketball", "nba", "wnba"]):
        return "basketball"
    if any(k in s_low for k in ["bóng chày", "baseball", "mlb", "npb", "kbo"]):
        return "baseball"
    if any(k in s_low for k in ["khúc côn cầu trên băng", "khúc côn cầu", "hockey", "nhl"]) and "cỏ" not in s_low and "field" not in s_low:
        return "hockey"
    if any(k in s_low for k in ["quần vợt", "tennis"]) and "bàn" not in s_low and "table" not in s_low:
        return "tennis"
    if "golf" in s_low:
        return "golf"
    if any(k in s_low for k in ["đua xe f1", "formula 1", "f1", "motorsport", "racing"]):
        return "racing"
    if any(k in s_low for k in ["mma", "ufc", "võ tổng hợp"]):
        return "mma"
    if any(k in s_low for k in ["boxing", "quyền anh"]):
        return "boxing"
    if any(k in s_low for k in ["bóng bầu dục mỹ", "american football", "nfl"]):
        return "football"
    if "cricket" in s_low:
        return "cricket"
    if "rugby" in s_low:
        return "rugby"
    if any(k in s_low for k in ["lacrosse", "bóng vợt"]):
        return "lacrosse"
    return None

LEAGUE_SLUG_MAP = {
    "eng.1": "Premier League",
    "eng.2": "Championship",
    "esp.1": "La Liga",
    "esp.2": "La Liga 2",
    "ger.1": "Bundesliga",
    "ger.2": "Bundesliga 2",
    "ita.1": "Serie A",
    "ita.2": "Serie B",
    "fra.1": "Ligue 1",
    "fra.2": "Ligue 2",
    "ned.1": "Eredivisie",
    "por.1": "Primeira Liga",
    "tur.1": "Süper Lig",
    "sco.1": "Scottish Premiership",
    "bel.1": "Belgian Pro League",
    "sau.1": "Saudi Pro League",
    "arg.1": "Argentine Primera División",
    "bra.1": "Brasileirão",
    "usa.1": "MLS",
    "jpn.1": "J1 League",
    "kor.1": "K League 1",
    "mlb": "MLB",
    "nba": "NBA",
    "wnba": "WNBA",
    "mens-college-basketball": "NCAA Basketball",
    "womens-college-basketball": "NCAA Basketball (Nữ)",
    "college-baseball": "NCAA Baseball",
    "nhl": "NHL",
    "uefa.champions": "UEFA Champions League",
    "uefa.europa": "UEFA Europa League",
    "uefa.conference": "UEFA Conference League",
    "uefa.w.europa": "UEFA Women's Europa",
    "afc.champions": "AFC Champions League Elite",
    "afc.cup": "AFC Champions League Two",
    "afc.challenge": "AFC Challenge League",
    "afc.asian.cup": "AFC Asian Cup",
    "concacaf.champions": "Concacaf Champions Cup",
    "conmebol.libertadores": "Copa Libertadores",
    "conmebol.sudamericana": "Copa Sudamericana",
    "eng.w.1": "Women's Super League",
    "esp.w.1": "Liga F",
    "ger.w.1": "Frauen-Bundesliga",
    "uefa.wchampions": "UEFA Women's Champions League",
    "uefa.wchamp": "UEFA Women's Champions League",
    "fra.w.1": "Première Ligue (Nữ)",
    "ita.w.1": "Serie A Femminile",
    "jpn.w.1": "WE League",
    "usa.nwsl": "NWSL",
    "usa.w.1": "NWSL"
}

CLUB_BLACKLIST = {
    "liverpool", "aston villa", "dodgers", "brighton", "real sociedad", 
    "bayern munich", "crystal palace", "eintracht frankfurt", "ajax", 
    "chicago cubs", "white sox", "blue jays", "clippers", "los angeles fc",
    "lafc", "atletico madrid", "atlético madrid", "ziraat bankkart", "genk",
    "leeds united", "bayern", "chelsea", "arsenal", "manchester", "barcelona",
    "real madrid", "tottenham", "spurs", "juventus", "milan", "inter",
    "psg", "paris saint-germain", "boca juniors", "dortmund", "monaco",
    "chicago", "cubs", "major league baseball", "the nba"
}

