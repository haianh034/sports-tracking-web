import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./sports_tracker.db")

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
    "tennis": "Quần vợt"
}

SPORT_TO_ESPN = {
    "Bóng đá": "soccer",
    "Bóng rổ": "basketball",
    "Bóng chày": "baseball"
}

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
    "usa.1": "MLS",
    "jpn.1": "J1 League",
    "kor.1": "K League 1",
    "mlb": "MLB",
    "nba": "NBA"
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

