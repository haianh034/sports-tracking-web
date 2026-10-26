import urllib.request
import urllib.parse
import json
import re
import unicodedata
from backend.core.config import EN_TO_VI_MAP

def fetch_free_player_info(player_name: str) -> dict:
    headers = {'User-Agent': 'SportsTrackingWeb/2.0 (contact: admin@sportstracker.local)'}
    search_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote(player_name)}&utf8=&format=json"
    
    try:
        req_search = urllib.request.Request(search_url, headers=headers)
        with urllib.request.urlopen(req_search, timeout=10) as response:
            search_data = json.loads(response.read().decode())
            if not search_data.get('query', {}).get('search'):
                return {"found": False}
            title = search_data['query']['search'][0]['title']
            
        summary_url = f"https://en.wikipedia.org/w/api.php?action=query&prop=extracts|langlinks&exintro&explaintext&titles={urllib.parse.quote(title)}&lllimit=500&format=json"
        req_summary = urllib.request.Request(summary_url, headers=headers)
        with urllib.request.urlopen(req_summary, timeout=10) as response:
            pages = json.loads(response.read().decode()).get('query', {}).get('pages', {})
            if not pages: return {"found": False}
            
            page = list(pages.values())[0]
            summary_raw = page.get('extract', '')
            summary = summary_raw.lower()
            
            aliases = [player_name]
            from backend.modules.players.services.news_service import PLAYER_NATIVE_NAMES
            p_low = player_name.lower().strip()
            for k, v in PLAYER_NATIVE_NAMES.items():
                if k in p_low or p_low in k:
                    aliases.extend(v)

            if 'langlinks' in page:
                for ll in page['langlinks']:
                    if ll.get('lang') in ['ja', 'ko', 'zh', 'ar', 'es', 'pt', 'fr', 'de', 'vi']:
                        aliases.append(ll.get('*', ''))
            
            # Extract East Asian characters or alternative names inside parenthesis
            first_paren = re.search(r'\((.*?)\)', summary_raw)
            if first_paren:
                parts = [p.strip() for p in first_paren.group(1).split(',') if p.strip()]
                for p in parts:
                    if any('\u4e00' <= c <= '\u9fff' or '\u3040' <= c <= '\u309f' or '\u30a0' <= c <= '\u30ff' or '\uac00' <= c <= '\ud7af' for c in p):
                        aliases.append(p)

            aliases_str = ", ".join(list(dict.fromkeys([a for a in aliases if a and '(' not in a and ')' not in a])))
            
            country_name = "Quốc tế"
            tz = "UTC"
            flag = "🌐"
            
            nat_team_match = re.search(r'(?:represents|plays for) the ([a-z\-]+(?: [a-z]+)?) national', summary)
            if nat_team_match:
                raw_nat = nat_team_match.group(1).strip()
                trans = EN_TO_VI_MAP.get(raw_nat)
                if isinstance(trans, dict):
                    country_name, tz, flag = trans["name"], trans["tz"], trans["flag"]

            if country_name == "Quốc tế":
                nat_match = re.search(r'is a(?:n)? (?:former )?(.*?)\s*(?:professional\s+)?(?:footballer|soccer|basketball|baseball|pitcher|infielder|outfielder|batter|catcher|guard|volleyball|badminton|tennis|player)', summary)
                if nat_match:
                    raw_nat = nat_match.group(1).strip()
                    trans = EN_TO_VI_MAP.get(raw_nat)
                    if isinstance(trans, dict):
                        country_name, tz, flag = trans["name"], trans["tz"], trans["flag"]

            if country_name == "Quốc tế":
                for eng_key, trans in EN_TO_VI_MAP.items():
                    if isinstance(trans, dict) and re.search(r'\b' + eng_key + r'\b', summary_raw, re.IGNORECASE):
                        country_name, tz, flag = trans["name"], trans["tz"], trans["flag"]
                        break
            
            sport = "Môn khác"
            sport_match = re.search(r'\b(football(?:er)?|soccer|basketball|baseball|pitcher|infielder|outfielder|batter|catcher|mlb|nba|npb|volleyball|table tennis|ping pong|badminton|tennis)\b', summary)
            if sport_match:
                raw_sport = sport_match.group(1).lower()
                sport = EN_TO_VI_MAP.get(raw_sport, "Môn khác")

            team_name = "Tự do"
            blacklist = ["national team", "major league baseball", "nba", "premier league", "la liga", "serie a", "bundesliga", "nippon professional baseball", "the national", "protests", "slam", "open", "cup", "world"]
            
            # Check explicit loan club first if mentioned as 'on loan at/to'
            loan_match = re.search(r'\bon loan (?:at|to)\s+(?:the\s+)?(?:[^\.\n,]+ (?:club|team|side|franchise)\s+)?([A-Z0-9\u00C0-\u024F][a-zA-Z0-9\u00C0-\u024F\s\.\-&\']+?)(?:\s+from\s+|\s+of\s+|\s+in\s+|\s*\/\s*|,|\.|\b(?:and|who)\b)', summary_raw, re.IGNORECASE)
            if loan_match:
                extracted = loan_match.group(1).strip()
                extracted = re.sub(r'^(?:Premier League|La Liga|Bundesliga|2\.\s*Bundesliga|Serie A|Ligue 1|MLS|EFL Championship)\s+club\s+', '', extracted, flags=re.IGNORECASE)
                if extracted.lower() not in blacklist and len(extracted) > 2:
                    team_name = extracted

            if team_name == "Tự do":
                patterns = [
                    r'\bfor\s+(?:the\s+)?([A-Z0-9\u00C0-\u024F][a-zA-Z0-9\u00C0-\u024F\s\.\-&\']+?)\s+of\s+(?:Major League Baseball|the NBA|the National Basketball Association|NPB|Nippon Professional Baseball|the Premier League|La Liga|Serie A|Bundesliga|Ligue 1)',
                    r'(?:is a(?:n)?|currently plays|plays)\s+.*?\bfor\s+(?:the\s+)?(?:[^\.\n,]+ (?:club|team|side|franchise)\s+)?([A-Z0-9\u00C0-\u024F][a-zA-Z0-9\u00C0-\u024F\s\.\-&\']+?)(?:\s+of\s+|\s+in\s+|\s*\/\s*|,|\.|\b(?:and|who)\b)',
                    r'\bfor\s+(?:the\s+)?(?:[^\.\n,]+ (?:club|team|side|franchise)\s+)?([A-Z0-9\u00C0-\u024F][a-zA-Z0-9\u00C0-\u024F\s\.\-&\']+?)(?:\s+of\s+|\s+in\s+|\s*\/\s*|,|\.|\b(?:and|who)\b)'
                ]
                for pattern in patterns:
                    match = re.search(pattern, summary_raw)
                    if match:
                        extracted = match.group(1).strip()
                        # Remove common prefix like "Premier League club ", "Bundesliga club "
                        extracted = re.sub(r'^(?:Premier League|La Liga|Bundesliga|2\.\s*Bundesliga|Serie A|Ligue 1|MLS|EFL Championship)\s+club\s+', '', extracted, flags=re.IGNORECASE)
                        if extracted.lower() not in blacklist and len(extracted) > 2:
                            team_name = extracted
                            break

            if sport in ["Quần vợt", "Cầu lông", "Bóng bàn"] and (team_name == "Tự do" or any(b in team_name.lower() for b in blacklist)):
                team_name = f"Đội tuyển {country_name}"

            return {
                "display_name": title,
                "api_player_id": f"wiki_p_{abs(hash(title)) % 90000}",
                "api_team_id": f"wiki_t_{abs(hash(team_name)) % 9000}",
                "team_name": team_name,
                "country_name": country_name,
                "timezone": tz,
                "country_flag": flag,
                "sport_name": sport,
                "aliases": aliases_str,
                "found": True
            }
    except Exception:
        return {"found": False}

def get_team_aliases_from_wiki(team_name: str) -> list:
    clean_name = team_name.strip()
    aliases = [clean_name]
    team_alias_dict = {
        "los angeles dodgers": ["Dodgers", "LA Dodgers", "LAD"],
        "los angeles clippers": ["LA Clippers", "Clippers", "LAC"],
        "los angeles lakers": ["LA Lakers", "Lakers", "LAL"],
        "los angeles fc": ["LAFC", "Los Angeles"],
        "chicago cubs": ["Cubs", "CHC"],
        "aston villa": ["Aston Villa", "Villa"],
        "atletico madrid": ["Atletico Madrid", "Atlético Madrid", "Atletico"],
        "atlético madrid": ["Atletico Madrid", "Atlético Madrid", "Atletico"],
        "brighton & hove albion": ["Brighton", "Brighton & Hove Albion"],
        "tottenham hotspur": ["Tottenham", "Spurs"],
        "paris saint-germain": ["PSG", "Paris Saint-Germain"],
        "ajax": ["Ajax", "Ajax Amsterdam"],
        "psv": ["PSV", "PSV Eindhoven"],
        "feyenoord": ["Feyenoord", "Feyenoord Rotterdam"]
    }
    key = clean_name.lower()
    if key in team_alias_dict:
        aliases.extend(team_alias_dict[key])
    if clean_name.lower().startswith("los angeles "):
        aliases.append("LA " + clean_name[12:])
        aliases.append(clean_name[12:])
    
    # Strip prefixes like 1. FSV, FSV, VfB, 1. FC, FC
    prefix_clean = re.sub(r'^(1\.\s*fsv|fsv|1\.\s*fc|fc|vfb|vfl|tsg|rcd|afc|rb)\s+', '', clean_name, flags=re.IGNORECASE).strip()
    if prefix_clean and prefix_clean != clean_name:
        aliases.append(prefix_clean)
    
    # Strip trailing numbers like 05, 04, 96 (e.g. Mainz 05 -> Mainz, Schalke 04 -> Schalke)
    no_num = re.sub(r'\s+\d+$', '', clean_name).strip()
    if no_num and no_num != clean_name:
        aliases.append(no_num)
    if prefix_clean:
        prefix_no_num = re.sub(r'\s+\d+$', '', prefix_clean).strip()
        if prefix_no_num and prefix_no_num != prefix_clean:
            aliases.append(prefix_no_num)

    words = clean_name.split()
    if len(words) > 1:
        aliases.append(words[-1])
        aliases.append(" ".join(words[1:]))
    norm_name = unicodedata.normalize('NFKD', clean_name).encode('ASCII', 'ignore').decode('utf-8')
    if norm_name != clean_name:
        aliases.append(norm_name)
    return list(dict.fromkeys([a for a in aliases if a and len(a) > 1]))
