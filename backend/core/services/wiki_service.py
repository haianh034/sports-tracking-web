import urllib.request
import urllib.parse
import json
import re
import unicodedata
from backend.core.config import EN_TO_VI_MAP

def fetch_free_player_info(player_name: str) -> dict:
    headers = {'User-Agent': 'SportsTrackingWeb/2.0 (contact: admin@sportstracker.local)'}
    search_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote(player_name)}&utf8=&format=json&srlimit=5"
    
    try:
        req_search = urllib.request.Request(search_url, headers=headers)
        with urllib.request.urlopen(req_search, timeout=10) as response:
            search_data = json.loads(response.read().decode())
            results = search_data.get('query', {}).get('search', [])
            if not results:
                return {"found": False}
            
            # Ưu tiên chọn trang thuộc lĩnh vực thể thao / cầu thủ nếu có nhiều kết quả (tránh trùng tên diễn viên, địa danh)
            title = results[0]['title']
            for res in results:
                t = res.get('title', '')
                snip = re.sub(r'<[^>]+>', '', res.get('snippet', '')).lower()
                if any(k in (t.lower() + " " + snip) for k in [
                    "footballer", "soccer", "baseball", "basketball", "volleyball", 
                    "striker", "defender", "centre-back", "midfielder", "winger", 
                    "pitcher", "infielder", "athlete", "player"
                ]):
                    title = t
                    break
            
        summary_url = f"https://en.wikipedia.org/w/api.php?action=query&prop=extracts|langlinks|revisions&exintro&explaintext&rvprop=content&rvsection=0&titles={urllib.parse.quote(title)}&lllimit=500&format=json"
        req_summary = urllib.request.Request(summary_url, headers=headers)
        with urllib.request.urlopen(req_summary, timeout=10) as response:
            pages = json.loads(response.read().decode()).get('query', {}).get('pages', {})
            if not pages: return {"found": False}
            
            page = list(pages.values())[0]
            summary_raw = page.get('extract', '')
            summary = summary_raw.lower()
            
            # Đọc wikitext phần đầu trang (Infobox + Lead) để trích xuất thông tin cho mượn và CLB chủ quản
            wikitext = ""
            if "revisions" in page and page["revisions"]:
                wikitext = page["revisions"][0].get("*", "")
            
            aliases = [player_name]
            from backend.modules.players.services.news_service import PLAYER_NATIVE_NAMES
            p_low = player_name.lower().strip()
            for k, v in PLAYER_NATIVE_NAMES.items():
                if k in p_low or p_low in k:
                    aliases.extend(v)

            # 1. Trích xuất tên bản địa (Hàn, Nhật, Trung...) từ langlinks (loại bỏ ngoặc định danh như "(축구 선수)")
            if 'langlinks' in page:
                for ll in page['langlinks']:
                    l_code = ll.get('lang')
                    raw_val = ll.get('*', '')
                    if l_code in ['ja', 'ko', 'zh', 'ar', 'es', 'pt', 'fr', 'de', 'vi']:
                        clean_val = re.sub(r'\(.*?\)', '', raw_val).strip()
                        if clean_val and len(clean_val) >= 2:
                            aliases.append(clean_val)
                            # Cầu thủ Nhật thường viết liền không dấu cách trong tiếng Nhật (ví dụ: 奈良岡功大, 高丘陽平)
                            # Bổ sung thêm biến thể có khoảng trắng họ - tên để công cụ tìm kiếm dễ nhận diện
                            if l_code == 'ja' and ' ' not in clean_val and 3 <= len(clean_val) <= 5:
                                if len(clean_val) == 4:
                                    aliases.append(f"{clean_val[:2]} {clean_val[2:]}")
                                elif len(clean_val) == 5:
                                    aliases.append(f"{clean_val[:3]} {clean_val[3:]}")
                                    aliases.append(f"{clean_val[:2]} {clean_val[2:]}")

            # 2. Bóc tách chữ Hangul, Kanji, Hanja, Katakana/Hiragana từ phần giới thiệu đầu bài (e.g. "(Korean: 송민규; born...)")
            first_paren = re.search(r'\((.*?)\)', summary_raw)
            if first_paren:
                pc = first_paren.group(1)
                # Bóc tách tên tiếng Hàn Hangul thuần túy (2 - 4 ký tự)
                for km in re.findall(r'[\uac00-\ud7af]{2,4}', pc):
                    if km not in aliases:
                        aliases.append(km)
                # Bóc tách tên chữ Hán / Kanji thuần túy (2 - 5 ký tự)
                for jm in re.findall(r'[\u4e00-\u9fff]{2,5}', pc):
                    if jm not in aliases:
                        aliases.append(jm)
                        if len(jm) == 4 and f"{jm[:2]} {jm[2:]}" not in aliases:
                            aliases.append(f"{jm[:2]} {jm[2:]}")
                # Bóc tách tên Katakana / Hiragana (2 - 8 ký tự)
                for knm in re.findall(r'[\u3040-\u309f\u30a0-\u30ff]{2,8}', pc):
                    if knm not in aliases:
                        aliases.append(knm)

            # 3. Bóc tách từ Infobox wikitext nếu có (hangul, hanja, kanji, native_name)
            if wikitext:
                for pat in [r'\|\s*hangul\s*=\s*([^\n\|\}]+)', r'\|\s*hanja\s*=\s*([^\n\|\}]+)', r'\|\s*kanji\s*=\s*([^\n\|\}]+)', r'\|\s*native_name\s*=\s*([^\n\|\}]+)']:
                    for m in re.finditer(pat, wikitext, re.IGNORECASE):
                        val = re.sub(r'\(.*?\)|<[^>]+>|\[\[|\]\]', '', m.group(1)).strip()
                        for pn in re.findall(r'[\u4e00-\u9fff\uac00-\ud7af\u3040-\u30ff\s]{2,}', val):
                            pn_clean = pn.strip()
                            if len(pn_clean) >= 2 and pn_clean not in aliases:
                                aliases.append(pn_clean)

            # Làm sạch aliases: loại bỏ ngoặc còn sót lại, lọc trùng lặp
            clean_alias_list = []
            for a in aliases:
                a_c = re.sub(r'\(.*?\)', '', a).strip()
                if a_c and len(a_c) >= 2 and a_c not in clean_alias_list:
                    clean_alias_list.append(a_c)

            aliases_str = ", ".join(clean_alias_list)
            
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
            
            first_sentence = summary_raw.split('.')[0] if '.' in summary_raw else summary_raw

            patterns = [
                r'\bfor\s+(?:the\s+)?([A-Z0-9\u00C0-\u024F][a-zA-Z0-9\u00C0-\u024F\s\.\-&\']+?)\s+of\s+(?:Major League Baseball|the NBA|the National Basketball Association|NPB|Nippon Professional Baseball|the Premier League|La Liga|Serie A|Bundesliga|Ligue 1)',
                r'(?:is a(?:n)?|currently plays|plays)\s+.*?\bfor\s+(?:the\s+)?(?:[^\.\n,]+ (?:club|team|side|franchise)\s+)?([A-Z0-9\u00C0-\u024F][a-zA-Z0-9\u00C0-\u024F\s\.\-&\']+?)(?:\s+of\s+|\s+in\s+|\s*\/\s*|,|\.|\b(?:and|who)\b)',
                r'\bfor\s+(?:the\s+)?(?:[^\.\n,]+ (?:club|team|side|franchise)\s+)?([A-Z0-9\u00C0-\u024F][a-zA-Z0-9\u00C0-\u024F\s\.\-&\']+?)(?:\s+of\s+|\s+in\s+|\s*\/\s*|,|\.|\b(?:and|who)\b)'
            ]

            # 1. Check current club from the standard Wikipedia lead sentence first
            for pattern in patterns:
                match = re.search(pattern, first_sentence)
                if match:
                    extracted = match.group(1).strip()
                    extracted = re.sub(r'^(?:Premier League|La Liga|Bundesliga|2\.\s*Bundesliga|Serie A|Ligue 1|MLS|EFL Championship)\s+club\s+', '', extracted, flags=re.IGNORECASE)
                    if extracted.lower() not in blacklist and len(extracted) > 2:
                        team_name = extracted
                        break

            # 2. Check explicit current loan club in first sentence if mentioned as 'on loan at/to'
            if team_name == "Tự do":
                loan_match = re.search(r'\bon loan (?:at|to)\s+(?:the\s+)?(?:[^\.\n,]+ (?:club|team|side|franchise)\s+)?([A-Z0-9\u00C0-\u024F][a-zA-Z0-9\u00C0-\u024F\s\.\-&\']+?)(?:\s+from\s+|\s+of\s+|\s+in\s+|\s*\/\s*|,|\.|\b(?:and|who)\b)', first_sentence, re.IGNORECASE)
                if loan_match:
                    extracted = loan_match.group(1).strip()
                    extracted = re.sub(r'^(?:Premier League|La Liga|Bundesliga|2\.\s*Bundesliga|Serie A|Ligue 1|MLS|EFL Championship)\s+club\s+', '', extracted, flags=re.IGNORECASE)
                    if extracted.lower() not in blacklist and len(extracted) > 2:
                        team_name = extracted

            # 3. Fallback to full extract if lead sentence did not yield a club
            if team_name == "Tự do":
                for pattern in patterns:
                    match = re.search(pattern, summary_raw)
                    if match:
                        extracted = match.group(1).strip()
                        extracted = re.sub(r'^(?:Premier League|La Liga|Bundesliga|2\.\s*Bundesliga|Serie A|Ligue 1|MLS|EFL Championship)\s+club\s+', '', extracted, flags=re.IGNORECASE)
                        if extracted.lower() not in blacklist and len(extracted) > 2:
                            team_name = extracted
                            break

            # 4. Phân tích Infobox từ wikitext để phát hiện CLB đang thi đấu theo dạng cho mượn (loan) và CLB chủ quản
            active_loan_club = None
            parent_club = None
            if wikitext:
                import datetime
                current_year = datetime.datetime.now().year
                years_dict = {}
                clubs_dict = {}
                for line in wikitext.splitlines():
                    line_s = line.strip()
                    m_yr = re.match(r'\|\s*years(\d+)\s*=\s*(.+)', line_s)
                    if m_yr:
                        years_dict[int(m_yr.group(1))] = m_yr.group(2).strip()
                    m_cl = re.match(r'\|\s*clubs(\d+)\s*=\s*(.+)', line_s)
                    if m_cl:
                        clubs_dict[int(m_cl.group(1))] = m_cl.group(2).strip()
                
                m_curr = re.search(r'\|\s*current_club\s*=\s*(?:\[\[([^\]|]+)(?:\|[^\]]+)?\]\]|([^\n\r\|{}]+))', wikitext)
                if m_curr:
                    raw_curr = (m_curr.group(1) or m_curr.group(2) or '').strip()
                    raw_curr = re.sub(r'\s+F\.?C\.?$', '', raw_curr, flags=re.IGNORECASE).strip()
                    if raw_curr.lower() not in blacklist and len(raw_curr) > 2:
                        parent_club = raw_curr

                if clubs_dict:
                    max_idx = max(clubs_dict.keys())
                    last_club_raw = clubs_dict[max_idx]
                    last_yr = years_dict.get(max_idx, '').replace('–', '-').replace('&ndash;', '-')
                    is_last_loan = bool(re.search(r'\(loan\)|[→\->]', last_club_raw, re.IGNORECASE))
                    
                    yr_matches = [int(y) for y in re.findall(r'\b(20\d\d)\b', last_yr)]
                    is_last_active = False
                    if yr_matches:
                        if max(yr_matches) >= current_year - 1:
                            is_last_active = True
                    elif '-' in last_yr or 'present' in last_yr.lower() or not last_yr:
                        is_last_active = True

                    if is_last_active:
                        m_name = re.search(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]', last_club_raw)
                        if m_name:
                            c_name = (m_name.group(2) or m_name.group(1)).strip()
                        else:
                            c_name = re.sub(r'[{}\[\]→\->]|loan', '', last_club_raw).strip()
                        c_name = re.sub(r'\s+F\.?C\.?$', '', c_name, flags=re.IGNORECASE).strip()
                        if c_name.lower() not in blacklist and len(c_name) > 2:
                            if is_last_loan:
                                active_loan_club = c_name
                            elif team_name == "Tự do":
                                team_name = c_name

            if active_loan_club:
                if not parent_club:
                    parent_club = team_name if team_name != "Tự do" else None
                team_name = active_loan_club

            if sport in ["Quần vợt", "Cầu lông", "Bóng bàn"] and (team_name == "Tự do" or any(b in team_name.lower() for b in blacklist)):
                team_name = f"Đội tuyển {country_name}"

            # 5. Nhận diện giới tính (Gender detection: Men / Women)
            is_female = bool(re.search(r'\b(she|her|female|woman|women|women\'s|frauen|we league|wsl|nwsl|liga f|wnba|nadeshiko|ladies|dames|femeni)\b', summary_raw, re.IGNORECASE))
            if not is_female and wikitext:
                is_female = bool(re.search(r'\b(she|her|female|woman|women|women\'s|frauen|we league|wsl|nwsl|liga f|wnba|nadeshiko|ladies|dames|femeni)\b', wikitext, re.IGNORECASE))
            if not is_female and parent_club and any(w in parent_club.lower() for w in ["women", "frauen", "ladies", "(w)"]):
                is_female = True

            gender = "Women" if is_female else "Men"

            # Nếu là VĐV nữ, chuẩn hóa tên CLB rõ ràng để phân biệt với đội nam
            if is_female and team_name and team_name not in ["Tự do", "Chưa rõ CLB"] and not team_name.startswith("Đội tuyển"):
                if not any(w in team_name.lower() for w in ["(nữ)", "(women)", "(w)", "women", "frauen", "ladies", "femeni"]):
                    team_name = f"{team_name} (Nữ)"

            return {
                "display_name": title,
                "api_player_id": f"wiki_p_{abs(hash(title)) % 90000}",
                "api_team_id": f"wiki_t_{abs(hash(team_name)) % 9000}",
                "team_name": team_name,
                "loan_club": active_loan_club,
                "parent_club": parent_club,
                "country_name": country_name,
                "timezone": tz,
                "country_flag": flag,
                "sport_name": sport,
                "aliases": aliases_str,
                "gender": gender,
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
        "feyenoord": ["Feyenoord", "Feyenoord Rotterdam"],
        "bayern munich": ["Bayern München", "FC Bayern München", "Bayern"],
        "bayern münchen": ["Bayern Munich", "FC Bayern Munich", "Bayern"],
        "borussia mönchengladbach": ["Borussia Moenchengladbach", "Mönchengladbach", "Gladbach"],
        "borussia dortmund": ["BVB", "Dortmund"],
        "inter milan": ["Internazionale", "Inter"],
        "ac milan": ["Milan"],
        "beşiktaş": ["Besiktas", "Besiktas JK"],
        "c.d. nacional": ["C.D. Nacional", "CD Nacional", "Nacional da Madeira"],
        "cd nacional": ["C.D. Nacional", "CD Nacional", "Nacional da Madeira"],
        "jong az alkmaar": ["Jong AZ Alkmaar", "Jong AZ"],
        "jong az": ["Jong AZ Alkmaar", "Jong AZ"],
        "jong ajax": ["Jong Ajax", "Jong Ajax Amsterdam"],
        "jong psv": ["Jong PSV", "Jong PSV Eindhoven"],
        "jong utrecht": ["Jong FC Utrecht", "Jong Utrecht"]
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

    # Luôn tìm kiếm bằng tên đầy đủ của câu lạc bộ hoặc các tên viết tắt chính thức, không bao giờ cắt vụn từ
    norm_name = unicodedata.normalize('NFKD', clean_name).encode('ASCII', 'ignore').decode('utf-8')
    if norm_name != clean_name:
        aliases.append(norm_name)
    return list(dict.fromkeys([a for a in aliases if a and len(a) > 1]))
