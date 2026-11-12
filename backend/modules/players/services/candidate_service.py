import urllib.request
import urllib.parse
import json
import re
from backend.core.config import EN_TO_VI_MAP
from backend.core.services.wiki_service import (
    fetch_free_player_info,
    build_clean_player_aliases,
    _EVENT_TITLE_RE,
    _SPORT_HINT_RE,
    _NON_ATHLETE_DESC_RE,
)
from backend.core.services.fotmob_service import _is_fotmob_name_match

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
                    desc_l = desc.lower()
                    if raw_sport in ("football", "american football", "american-football") or "nfl" in league_slug or "american football" in desc_l:
                        sport = "Bóng bầu dục Mỹ"
                    elif "baseball" in raw_sport or "mlb" in league_slug or "mlb" in desc_l:
                        sport = "Bóng chày"
                    elif "basketball" in raw_sport or "nba" in league_slug or "nba" in desc_l or "wnba" in league_slug:
                        sport = "Bóng rổ"
                    elif "hockey" in raw_sport or "nhl" in league_slug or "nhl" in desc_l:
                        sport = "Khúc côn cầu"
                    elif any(k in (desc_l + " " + raw_sport + " " + league_slug) for k in ["laliga", "premier", "soccer", "fifa", "afc", "uefa", "bundesliga", "serie a", "ligue 1", "mls", "champions league"]):
                        sport = "Bóng đá"
                    elif raw_sport:
                        mapped_sp = EN_TO_VI_MAP.get(raw_sport)
                        if isinstance(mapped_sp, str):
                            sport = mapped_sp
                        else:
                            sport = raw_sport.upper() if len(raw_sport) <= 3 else raw_sport.capitalize()

                    # Team resolution: subtitle has "Chicago Cubs", while description has "MLB"
                    team = subtitle or desc or "Tự do"
                    if team.upper() in ["MLB", "NBA", "SOCCER", "EPL", "LALIGA", "MMA"] and subtitle:
                        team = subtitle
                    if team.upper() in ["MLB", "NBA", "MMA"]:
                        team = "Tự do"

                    country = "Quốc tế"
                    flag = "🌐"
                    aliases = build_clean_player_aliases(pname)

                    # Check nationality and actual club from Wikipedia/Wikidata
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
                            aliases = build_clean_player_aliases(pname, [a.strip() for a in wiki_info["aliases"].split(",")])

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
                    cand_gender = wiki_info.get("gender", "Men") if wiki_info.get("found") else "Men"

                    # 1. Thêm lựa chọn CLB thi đấu chính thức (nếu có từ Wiki hoặc team gốc không phải tuyển QG)
                    primary_team = club_team if (is_national_team and club_team) else team
                    if cand_gender == "Women" and primary_team and not any(w in primary_team.lower() for w in ["(nữ)", "(women)", "(w)", "women", "frauen", "ladies", "(tuyển qg)"]):
                        primary_team = f"{primary_team} (Nữ)"

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
                            "espn_league_slug": league_slug or "",
                            "source": "ESPN",
                            "score": score,
                            "gender": cand_gender
                        })

                    # 1b. Nếu cầu thủ đang được cho mượn sang CLB khác (loan), thêm CLB cho mượn ưu tiên cao nhất
                    if wiki_info.get("found") and wiki_info.get("loan_club"):
                        loan_t = wiki_info["loan_club"]
                        parent_t = wiki_info.get("parent_club") or primary_team
                        if cand_gender == "Women" and loan_t and not any(w in loan_t.lower() for w in ["(nữ)", "(women)", "(w)", "women", "frauen", "ladies"]):
                            loan_t = f"{loan_t} (Nữ)"
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
                                "score": score + 5,
                                "gender": cand_gender
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
                                "score": score - 5,
                                "gender": cand_gender
                            })
    except Exception:
        pass

    # 2. FotMob Player Search (Tìm cả thứ tự đảo họ-tên Đông Á và bỏ gạch nối như "Heung-Min Son")
    try:
        q_parts = q_clean.split()
        fm_queries = [q_clean]
        if "-" in q_clean:
            fm_queries.append(q_clean.replace("-", " "))
        if len(q_parts) >= 2:
            fm_queries.append(" ".join(q_parts[1:]) + " " + q_parts[0])
            fm_queries.append((q_parts[-1] + " " + " ".join(q_parts[:-1])).replace("-", " "))

        fm_seen_q = set()
        for fmq in fm_queries:
            if fmq.lower() in fm_seen_q:
                continue
            fm_seen_q.add(fmq.lower())
            fm_url = f"https://www.fotmob.com/api/data/search/suggest?term={urllib.parse.quote(fmq)}"
            req = urllib.request.Request(fm_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=4) as r:
                fm_data = json.loads(r.read().decode())
            for grp in fm_data:
                for sug in grp.get("suggestions", []):
                    if sug.get("type") == "player":
                        pname = sug.get("name", "").strip()
                        fm_team = (sug.get("teamName", "") or "").strip()
                        if not pname or not fm_team:
                            continue
                        is_name_exact = _is_fotmob_name_match(q_clean, pname)
                        if not is_name_exact and any(c.get("score", 0) >= 95 for c in candidates):
                            continue

                        w_info = fetch_free_player_info(pname)
                        fm_gender = w_info.get("gender", "Men") if w_info.get("found") else "Men"
                        team_id = sug.get("teamId")
                        if team_id == 671935 or "(w)" in fm_team.lower() or "women" in fm_team.lower():
                            fm_gender = "Women"
                        if fm_gender == "Women" and not any(w in fm_team.lower() for w in ["(nữ)", "(women)", "(w)", "women", "frauen", "ladies"]):
                            fm_team = f"{fm_team} (Nữ)"

                        k = (pname.lower(), fm_team.lower())
                        if k not in seen:
                            seen.add(k)
                            score = 100 if is_name_exact else (88 if q_clean.lower() in pname.lower() else 60)
                            c_name = w_info.get("country_name", "Quốc tế") if w_info.get("found") else "Quốc tế"
                            c_flag = w_info.get("country_flag", "🌐") if w_info.get("found") else "🌐"
                            raw_al = [a.strip() for a in w_info.get("aliases", "").split(",") if a.strip()] if w_info.get("found") else []
                            c_aliases = build_clean_player_aliases(pname, raw_al + [q_clean])
                            candidates.append({
                                "name": pname,
                                "sport": "Bóng đá",
                                "team": fm_team,
                                "country": c_name,
                                "country_flag": c_flag,
                                "aliases": c_aliases,
                                "source": "FotMob",
                                "score": score,
                                "gender": fm_gender
                            })

                            if w_info.get("found") and w_info.get("loan_club"):
                                loan_t = w_info["loan_club"]
                                parent_t = w_info.get("parent_club") or fm_team
                                if fm_gender == "Women" and not any(w in loan_t.lower() for w in ["(nữ)", "(women)", "(w)", "women", "frauen", "ladies"]):
                                    loan_t = f"{loan_t} (Nữ)"
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
                                        "score": score + 5,
                                        "gender": fm_gender
                                    })
    except Exception:
        pass

    # 3. Wikipedia / Wikidata Search API
    wiki_added = False
    try:
        w_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote(q_clean)}&utf8=&format=json&srlimit=6"
        req = urllib.request.Request(w_url, headers={'User-Agent': 'SportsTrackingWeb/2.1 (contact@sportstracker.local)'})
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.loads(r.read().decode())
        for res in d.get("query", {}).get("search", []):
            title = res.get("title", "")
            if _EVENT_TITLE_RE.search(title):
                continue
            q_tokens = [t.lower() for t in q_clean.split() if len(t) >= 3]
            if q_tokens and not any(t in title.lower() for t in q_tokens):
                continue

            snip = re.sub(r'<[^>]+>', '', res.get("snippet", ""))
            snip_l = snip.lower()
            if _NON_ATHLETE_DESC_RE.search(snip_l) and not _SPORT_HINT_RE.search(snip_l):
                continue
            if _SPORT_HINT_RE.search(title.lower() + " " + snip_l):
                clean_title = re.sub(r'\s*\([^)]*\)$', '', title).strip()
                if len(q_clean.split()) >= 2 and len(clean_title.split()) < 2:
                    continue
                if not any(b in title.lower() for b in ["season", "list of", "league", "cup", "team", "club", "stadium", "tournament", "at the ", "olympics", "championship"]):
                    wiki_info = fetch_free_player_info(title)
                    if not wiki_info.get("found"):
                        continue
                    sport = wiki_info.get("sport_name", "Bóng đá")
                    team = wiki_info.get("team_name", "Tự do")
                    country = wiki_info.get("country_name", "Quốc tế")
                    flag = wiki_info.get("country_flag", "🌐")
                    aliases = wiki_info.get("aliases") or build_clean_player_aliases(clean_title, [q_clean])
                    cand_gender = wiki_info.get("gender", "Men")

                    is_ex = _is_fotmob_name_match(q_clean, clean_title)
                    score = 100 if is_ex else (85 if q_clean.lower() in clean_title.lower() else 65)

                    title_key = (clean_title.lower(), team.lower())
                    if title_key not in seen:
                        seen.add(title_key)
                        wiki_added = True
                        candidates.append({
                            "name": clean_title,
                            "sport": sport,
                            "team": team,
                            "country": country,
                            "country_flag": flag,
                            "aliases": aliases,
                            "source": "Wikipedia",
                            "score": score,
                            "gender": cand_gender
                        })

                    if wiki_info.get("loan_club"):
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
                                "score": score + 5,
                                "gender": cand_gender
                            })
    except Exception:
        pass

    # 3b. Wikidata fallback nếu Wikipedia EN không có trang hoặc tên bị đảo thứ tự (ví dụ Joo Cheon-hui, Watanabe Yuzuno)
    if not wiki_added and not any(c.get("score", 0) >= 95 for c in candidates):
        try:
            wiki_info = fetch_free_player_info(q_clean)
            if wiki_info.get("found"):
                wname = re.sub(r'\s*\([^)]*\)$', '', wiki_info.get("display_name") or q_clean).strip()
                wteam = wiki_info.get("team_name", "Tự do")
                wkey = (wname.lower(), wteam.lower())
                if wkey not in seen:
                    seen.add(wkey)
                    candidates.append({
                        "name": wname,
                        "sport": wiki_info.get("sport_name", "Môn khác"),
                        "team": wteam,
                        "country": wiki_info.get("country_name", "Quốc tế"),
                        "country_flag": wiki_info.get("country_flag", "🌐"),
                        "aliases": wiki_info.get("aliases") or build_clean_player_aliases(wname, [q_clean]),
                        "source": "Wikidata",
                        "score": 98,
                        "gender": wiki_info.get("gender", "Men")
                    })
        except Exception:
            pass

    sport_order = {"Bóng đá": 1, "Bóng chày": 2, "Bóng rổ": 3, "Bóng chuyền": 4, "Cầu lông": 5, "Quần vợt": 6, "Bóng bàn": 7, "Golf": 8, "Môn khác": 999}
    candidates.sort(key=lambda x: (-x.get("score", 0), sport_order.get(x["sport"], 50)))

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
        cand_gender = c.get("gender", "Men")
        if team_name and team_name not in ["Tự do", "Chưa rõ CLB", "Unknown"]:
            c["team_league"] = resolve_team_league(team_name, sport_name, gender=cand_gender)
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

