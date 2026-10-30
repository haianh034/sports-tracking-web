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

                    # Check nationality and actual club from Wikipedia
                    wiki_info = fetch_free_player_info(pname)
                    if wiki_info.get("found"):
                        if wiki_info.get("country_name") and wiki_info["country_name"] != "Quốc tế":
                            country = wiki_info["country_name"]
                            flag = wiki_info.get("country_flag", "🌐")
                        wiki_sport = wiki_info.get("sport_name")
                        if wiki_sport and wiki_sport != "Môn khác":
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

                    # Kiểm tra xem team từ ESPN có thực chất là tên Quốc gia / Tuyển Quốc gia không (ví dụ "Japan", "South Korea")
                    is_national_team = (
                        team.lower() in [ct.lower() for ct in EN_TO_VI_MAP] or
                        team.lower() in [info["name"].lower() for info in EN_TO_VI_MAP.values() if isinstance(info, dict)] or
                        team.lower() in ["japan", "south korea", "vietnam", "korea", "viet nam", "nhật bản", "hàn quốc", "việt nam"] or
                        team.lower() == country.lower()
                    )

                    club_team = wiki_info.get("team_name") if (wiki_info.get("found") and wiki_info.get("team_name") and wiki_info["team_name"] not in ["Tự do", "Chưa rõ CLB"]) else None

                    # Exact score 100 if query matches name
                    score = 100 if q_clean.lower() == pname.lower() else (90 if q_clean.lower() in pname.lower() else 75)

                    # 1. Thêm lựa chọn CLB thi đấu chính thức (nếu có từ Wiki hoặc team gốc không phải tuyển QG)
                    primary_team = club_team if (is_national_team and club_team) else team
                    cand_key = (pname.lower(), primary_team.lower())
                    if pname and cand_key not in seen:
                        seen.add(cand_key)
                        candidates.append({
                            "name": pname,
                            "sport": sport,
                            "team": primary_team,
                            "country": country,
                            "country_flag": flag,
                            "aliases": aliases,
                            "source": "ESPN",
                            "score": score
                        })

                    # 1b. Nếu cầu thủ đang được cho mượn sang CLB khác (loan), thêm CLB cho mượn ưu tiên cao nhất
                    if wiki_info.get("found") and wiki_info.get("loan_club"):
                        loan_t = wiki_info["loan_club"]
                        parent_t = wiki_info.get("parent_club") or primary_team
                        loan_key = (pname.lower(), loan_t.lower())
                        if loan_key not in seen:
                            seen.add(loan_key)
                            candidates.append({
                                "name": pname,
                                "sport": sport,
                                "team": loan_t,
                                "country": country,
                                "country_flag": flag,
                                "aliases": aliases,
                                "source": f"Cho mượn từ {parent_t}",
                                "score": score + 5
                            })

                    # 2. Nếu cầu thủ có cả thông tin Đội tuyển Quốc gia (như "Japan"), bổ sung thêm làm lựa chọn thứ 2
                    if is_national_team and club_team:
                        nat_key = (pname.lower(), team.lower())
                        if nat_key not in seen:
                            seen.add(nat_key)
                            candidates.append({
                                "name": pname,
                                "sport": sport,
                                "team": f"{team} (Tuyển QG)",
                                "country": country,
                                "country_flag": flag,
                                "aliases": aliases,
                                "source": "ESPN",
                                "score": score - 5
                            })
    except Exception:
        pass

    # 2. FotMob Player Search (Dành riêng cho bóng đá để cập nhật CLB mới nhất như Wolfsburg, Freiburg...)
    try:
        fm_url = f"https://www.fotmob.com/api/data/search/suggest?term={urllib.parse.quote(q_clean)}"
        req = urllib.request.Request(fm_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=4) as r:
            fm_data = json.loads(r.read().decode())
        for grp in fm_data:
            for sug in grp.get("suggestions", []):
                if sug.get("type") == "player":
                    pname = sug.get("name", "").strip()
                    fm_team = (sug.get("teamName", "") or "").strip()
                    if pname and fm_team:
                        k = (pname.lower(), fm_team.lower())
                        if k not in seen:
                            seen.add(k)
                            score = 100 if q_clean.lower() == pname.lower() else (90 if q_clean.lower() in pname.lower() else 75)
                            w_info = fetch_free_player_info(pname)
                            c_name = w_info.get("country_name", "Quốc tế") if w_info.get("found") else "Quốc tế"
                            c_flag = w_info.get("country_flag", "🌐") if w_info.get("found") else "🌐"
                            c_aliases = w_info.get("aliases", pname) if w_info.get("found") else pname
                            candidates.append({
                                "name": pname,
                                "sport": "Bóng đá",
                                "team": fm_team,
                                "country": c_name,
                                "country_flag": c_flag,
                                "aliases": c_aliases,
                                "source": "FotMob",
                                "score": score
                            })

                            if w_info.get("found") and w_info.get("loan_club"):
                                loan_t = w_info["loan_club"]
                                parent_t = w_info.get("parent_club") or fm_team
                                loan_key = (pname.lower(), loan_t.lower())
                                if loan_key not in seen:
                                    seen.add(loan_key)
                                    candidates.append({
                                        "name": pname,
                                        "sport": "Bóng đá",
                                        "team": loan_t,
                                        "country": c_name,
                                        "country_flag": c_flag,
                                        "aliases": c_aliases,
                                        "source": f"Cho mượn từ {parent_t}",
                                        "score": score + 5
                                    })
    except Exception:
        pass

    # 3. Wikipedia Search API (only if needed or exact matches)
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
                clean_title = re.sub(r'\s*\([^)]*\)$', '', title).strip()
                if not any(b in title.lower() for b in ["season", "list of", "league", "cup", "team", "club", "stadium", "tournament"]):
                    wiki_info = fetch_free_player_info(title)
                    sport = wiki_info.get("sport_name", "Bóng đá") if wiki_info.get("found") else "Bóng đá"
                    team = wiki_info.get("team_name", "Tự do") if wiki_info.get("found") else "Tự do"
                    country = wiki_info.get("country_name", "Quốc tế") if wiki_info.get("found") else "Quốc tế"
                    flag = wiki_info.get("country_flag", "🌐") if wiki_info.get("found") else "🌐"
                    aliases = wiki_info.get("aliases", clean_title) if wiki_info.get("found") else clean_title

                    score = 100 if q_clean.lower() == clean_title.lower() else (85 if q_clean.lower() in clean_title.lower() else 65)
                    
                    title_key = (clean_title.lower(), team.lower())
                    if title_key not in seen:
                        seen.add(title_key)
                        candidates.append({
                            "name": clean_title,
                            "sport": sport,
                            "team": team,
                            "country": country,
                            "country_flag": flag,
                            "aliases": aliases,
                            "source": "Wikipedia",
                            "score": score
                        })

                    if wiki_info.get("found") and wiki_info.get("loan_club"):
                        loan_t = wiki_info["loan_club"]
                        parent_t = wiki_info.get("parent_club") or team
                        loan_key = (clean_title.lower(), loan_t.lower())
                        if loan_key not in seen:
                            seen.add(loan_key)
                            candidates.append({
                                "name": clean_title,
                                "sport": sport,
                                "team": loan_t,
                                "country": country,
                                "country_flag": flag,
                                "aliases": aliases,
                                "source": f"Cho mượn từ {parent_t}",
                                "score": score + 5
                            })
    except Exception:
        pass

    sport_order = {"Bóng đá": 1, "Bóng chày": 2, "Bóng rổ": 3, "Bóng chuyền": 4, "Cầu lông": 5, "Quần vợt": 6, "Bóng bàn": 7, "Môn khác": 8}
    candidates.sort(key=lambda x: (-x.get("score", 0), sport_order.get(x["sport"], 99)))

    # Deduplicate candidates across ESPN, FotMob, Wikipedia
    unique_candidates = []
    def _norm_club(name: str) -> str:
        s = re.sub(r'^(vfl|fc|sc|afc|cf|ssv|borussia|spvgg|1\.\s*fc|as|ac)\s+', '', name.lower()).strip()
        return s

    for cand in candidates:
        c_name = cand["name"].strip().lower()
        c_team = cand.get("team", "").strip()
        c_team_norm = _norm_club(c_team)
        
        is_dup = False
        for u in unique_candidates:
            u_name = u["name"].strip().lower()
            u_team = u.get("team", "").strip()
            u_team_norm = _norm_club(u_team)
            if c_name == u_name:
                if c_team.lower() == u_team.lower():
                    is_dup = True
                    break
                # Both are clubs and match normalized club name (e.g. "VfL Wolfsburg" vs "Wolfsburg")
                if "(tuyển qg)" not in c_team.lower() and "(tuyển qg)" not in u_team.lower():
                    if c_team_norm == u_team_norm or (len(c_team_norm) >= 4 and len(u_team_norm) >= 4 and (c_team_norm in u_team_norm or u_team_norm in c_team_norm)):
                        if len(c_team) > len(u_team):
                            u["team"] = c_team
                        is_dup = True
                        break
        if not is_dup:
            unique_candidates.append(cand)
    candidates = unique_candidates

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
    # Nếu chỉ có duy nhất 1 ứng viên, tự động chọn
    if len(candidates) == 1:
        return False, candidates
    
    # Nếu có nhiều ứng viên (ví dụ lựa chọn CLB vs Tuyển QG, hoặc các cầu thủ cùng tên), hiển thị danh sách cho người dùng chọn
    if len(candidates) > 1:
        return True, candidates[:6]

    return False, []

