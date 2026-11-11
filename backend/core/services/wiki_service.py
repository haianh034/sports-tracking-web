import urllib.request
import urllib.parse
import json
import re
import unicodedata
from backend.core.config import EN_TO_VI_MAP, normalize_player_name

_WIKI_HEADERS = {'User-Agent': 'SportsTrackingWeb/2.1 (https://github.com/sports-tracking; contact@sportstracker.local)'}
_WIKI_CACHE = {}

_EVENT_TITLE_RE = re.compile(
    r'\b(at the \d{4}|olympics?|paralympics?|asian games|youth olympic|championships?|world cup|universiade|'
    r'open|smash|contender|masters|grand prix|world tour|season|list of|tv series|television series|'
    r'film|drama|album|single|song|episode|mixed doubles|men\'?s singles|women\'?s singles|'
    r'men\'?s doubles|women\'?s doubles|surname|given name)\b',
    re.IGNORECASE
)

_CLUB_DELEGATION_RE = re.compile(
    r'\b(at the |olympics?|paralympics?|asian games|youth olympic|championships?|world cup|universiade|'
    r'national team|national football|graduat(?:ing|ed)|university|college|high school|since |after |before )\b',
    re.IGNORECASE
)

_NON_ATHLETE_DESC_RE = re.compile(
    r'\b(actor|actress|singer|musician|politician|writer|author|novelist|director|film|movie|drama|television|tv series|song|album|character|municipality|village|river|mountain)\b',
    re.IGNORECASE
)

_SPORT_HINT_RE = re.compile(
    r'\b(footballer|football|soccer|basketball|baseball|pitcher|infielder|outfielder|batter|catcher|guard|forward|'
    r'volleyball|badminton|table tennis|ping pong|tennis|golfer|golf|racing|formula|motorsport|swimmer|swimming|'
    r'athlete|athletics|boxer|boxing|mixed martial|mma|ufc|figure skater|gymnast|cyclist|hockey|cricket|rugby|player)\b',
    re.IGNORECASE
)

def _is_cjk_str(s: str) -> bool:
    return any('\u4e00' <= c <= '\u9fff' or '\u3040' <= c <= '\u30ff' for c in s)

def _is_hangul_str(s: str) -> bool:
    return any('\uac00' <= c <= '\ud7af' for c in s)

def _split_japanese_name_clean(val: str) -> list[str]:
    """Tách họ-tên tiếng Nhật không dấu cách một cách chính xác (chỉ tại ranh giới Kanji-Kana hoặc 4 Kanji 2+2)."""
    v = val.strip()
    if ' ' in v or not _is_cjk_str(v):
        return []
    out = []
    # Ranh giới Kanji -> Kana (ví dụ: 藤野あおば -> 藤野 あおば)
    m_kk = re.match(r'^([\u4e00-\u9fff\u3005]{1,3})([\u3040-\u30ff]{2,6})$', v)
    if m_kk:
        out.append(f"{m_kk.group(1)} {m_kk.group(2)}")
        return out
    # Tên toàn Kanji 4 ký tự (ví dụ: 田中湧士 -> 田中 湧士)
    if re.fullmatch(r'[\u4e00-\u9fff\u3005]{4}', v):
        out.append(f"{v[:2]} {v[2:]}")
    return out

def _is_valid_alias_entry(alias: str, player_name: str, all_pool: list = None) -> bool:
    a = (alias or "").strip()
    if not a or len(a) < 2:
        return False
    if '(' in a or ')' in a or '/' in a:
        return False
    if re.search(r'(?:19|20)\d{2}', a):
        return False
    if re.search(r'(olymp|jugend|jeux|選手団|選手権|锦标赛|錦標賽|大会|試合|競技|オリンピック|运动会|運動會|比赛|比賽|奥林匹克|奧林匹克|mafia|doctor x)', a, re.IGNORECASE):
        return False
    if any(k in a.lower() for k in ["born", "japanese:", "korean:", "kanji:", "hanja:", "hepburn", "revised"]):
        return False
    # Không lưu 1 từ Latin đơn lẻ cho VĐV có tên từ 2 từ trở lên
    p_parts = [p for p in (player_name or "").split() if p]
    if a.isascii() and len(p_parts) >= 2 and len(a.split()) < 2:
        return False
    # Loại bỏ mảnh CJK/Hangul bị cắt cụt nếu nằm trong tên đầy đủ dài hơn hoặc là mảnh Kana đơn lẻ
    compact = a.replace(" ", "")
    if (_is_cjk_str(a) or _is_hangul_str(a)) and len(p_parts) >= 2:
        if len(compact) <= 1:
            return False
        if re.fullmatch(r'[\u3040-\u30ff]+', compact) and len(compact) <= 3:
            return False
        if all_pool and len(compact) <= 3:
            for other in all_pool:
                o_c = re.sub(r'\(.*?\)', '', str(other or '')).strip().replace(" ", "")
                if len(o_c) >= len(compact) + 2 and compact in o_c:
                    return False
    return True

def generate_latin_name_variants(player_name: str) -> list[str]:
    """Sinh các biến thể Latin sạch từ tên gốc (bỏ macron, đổi trường âm uu->u, bỏ gạch nối, đảo trật tự Đông Á)."""
    raw = (player_name or "").strip()
    if not raw:
        return []
    variants = [raw]
    # 1. Phiên bản bỏ dấu / macron (Kōta Takai -> Kota Takai)
    nfkd = unicodedata.normalize('NFKD', raw)
    no_diac = ''.join(c for c in nfkd if not unicodedata.combining(c)).strip()
    if no_diac and no_diac not in variants:
        variants.append(no_diac)
    # 2. Wāpuro trường âm (Ryuusei -> Ryusei)
    no_uu = re.sub(r'([kstnhmyrwgzjdbp])uu', r'\1u', no_diac, flags=re.IGNORECASE)
    if no_uu and no_uu not in variants:
        variants.append(no_uu)
    # 3. Tên gạch nối (Son Heung-min -> Son Heung Min)
    if "-" in no_diac:
        no_hyphen = no_diac.replace("-", " ")
        if no_hyphen not in variants:
            variants.append(no_hyphen)
    # 4. Đảo trật tự Họ - Tên cho tên 2 phần
    parts = no_diac.split()
    if len(parts) == 2:
        swapped = f"{parts[1]} {parts[0]}"
        if swapped not in variants:
            variants.append(swapped)
    return list(dict.fromkeys([v for v in variants if v]))

def build_clean_player_aliases(player_name: str, extra_aliases: list = None) -> str:
    """Tổng hợp và làm sạch danh sách biến thể tên VĐV (tự động loại bỏ rác sự kiện và họ đơn lẻ)."""
    raw_pool = [player_name]
    try:
        from backend.modules.players.services.news_service import PLAYER_NATIVE_NAMES
        norm_p = normalize_player_name(player_name)
        for k, v in PLAYER_NATIVE_NAMES.items():
            if normalize_player_name(k) == norm_p:
                raw_pool.extend(v)
    except Exception:
        pass

    if extra_aliases:
        raw_pool.extend(extra_aliases)

    raw_pool.extend(generate_latin_name_variants(player_name))

    clean_list = []
    seen_low = set()
    for item in raw_pool:
        cleaned = re.sub(r'\(.*?\)', '', str(item or '')).strip()
        if not cleaned or not _is_valid_alias_entry(cleaned, player_name, raw_pool):
            continue
        low = cleaned.lower()
        if low not in seen_low:
            seen_low.add(low)
            clean_list.append(cleaned)
        # Tự động bổ sung biến thể bỏ dấu/macron của alias Latin hợp lệ
        if not _is_cjk_str(cleaned) and not _is_hangul_str(cleaned) and cleaned.isascii() is False:
            nfkd = unicodedata.normalize('NFKD', cleaned)
            ascii_ver = ''.join(c for c in nfkd if not unicodedata.combining(c)).strip()
            if ascii_ver and ascii_ver.isascii() and ascii_ver.lower() not in seen_low and _is_valid_alias_entry(ascii_ver, player_name, raw_pool):
                seen_low.add(ascii_ver.lower())
                clean_list.append(ascii_ver)
    return ", ".join(clean_list)

def _title_matches_player(player_name: str, candidate_title: str) -> bool:
    """Xác minh tiêu đề bài viết Wikipedia thực sự là về VĐV đang tìm (cho phép đảo họ-tên & khác biệt macron/uu)."""
    clean_title = re.sub(r'\s*\([^)]*\)$', '', candidate_title or '').strip()
    if not clean_title:
        return False
    p_norm = normalize_player_name(player_name)
    t_norm = normalize_player_name(clean_title)
    if not p_norm or not t_norm:
        return False
    if p_norm == t_norm:
        return True
    p_parts = sorted(p_norm.split())
    t_parts = sorted(t_norm.split())
    if p_parts == t_parts:
        return True
    # Đảo thứ tự bỏ dấu cách ("heung min son" == "son heung min")
    p_set, t_set = set(p_parts), set(t_parts)
    if len(p_set) >= 2 and (p_set.issubset(t_set) or t_set.issubset(p_set)):
        return True
    return False

def _is_pure_country_name(name: str) -> bool:
    low = (name or "").strip().lower()
    if low in ["japan", "south korea", "korea", "vietnam", "viet nam", "china", "france", "germany", "spain", "england", "brazil", "argentina", "portugal", "italy", "united states", "usa"]:
        return True
    for k, v in EN_TO_VI_MAP.items():
        if isinstance(v, dict) and (low == k.lower() or low == v.get("name", "").lower()):
            return True
    return False

def _fetch_from_wikidata(player_name: str) -> dict:
    """Tra cứu dự phòng từ Wikidata khi Wikipedia tiếng Anh không có trang hoặc bị trùng tên giải đấu/phim."""
    parts = player_name.strip().split()
    queries = [player_name.strip()]
    if len(parts) == 2:
        queries.append(f"{parts[1]} {parts[0]}")

    matched_qid = None
    for q in queries:
        try:
            u = f"https://www.wikidata.org/w/api.php?action=wbsearchentities&search={urllib.parse.quote(q)}&language=en&format=json&limit=6"
            req = urllib.request.Request(u, headers=_WIKI_HEADERS)
            with urllib.request.urlopen(req, timeout=6) as r:
                items = json.loads(r.read().decode()).get("search", [])
            for it in items:
                label = it.get("label", "")
                desc = it.get("description", "") or ""
                if _NON_ATHLETE_DESC_RE.search(desc):
                    continue
                if _title_matches_player(player_name, label):
                    if _SPORT_HINT_RE.search(desc) or not desc:
                        matched_qid = it.get("id")
                        if _SPORT_HINT_RE.search(desc):
                            break
            if matched_qid:
                break
        except Exception:
            continue

    if not matched_qid:
        return {"found": False}

    try:
        u = f"https://www.wikidata.org/w/api.php?action=wbgetentities&ids={matched_qid}&props=labels|aliases|sitelinks|descriptions|claims&languages=en|ja|ko|zh|vi&format=json"
        req = urllib.request.Request(u, headers=_WIKI_HEADERS)
        with urllib.request.urlopen(req, timeout=6) as r:
            ent = json.loads(r.read().decode()).get("entities", {}).get(matched_qid, {})
        if not ent:
            return {"found": False}

        # Kiểm tra không phải phim/địa danh (P31 human Q5 hoặc có sport desc)
        claims = ent.get("claims", {})
        p31_ids = [c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id") for c in claims.get("P31", [])]
        desc_en = (ent.get("descriptions", {}).get("en", {}) or {}).get("value", "")
        desc_ja = (ent.get("descriptions", {}).get("ja", {}) or {}).get("value", "")
        desc_ko = (ent.get("descriptions", {}).get("ko", {}) or {}).get("value", "")
        desc_zh = (ent.get("descriptions", {}).get("zh", {}) or {}).get("value", "")
        all_desc = f"{desc_en} {desc_ja} {desc_ko} {desc_zh}"
        if _NON_ATHLETE_DESC_RE.search(all_desc):
            return {"found": False}
        if p31_ids and "Q5" not in p31_ids:
            return {"found": False}

        # Gender P21
        p21_ids = [c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id") for c in claims.get("P21", [])]
        gender = "Women" if "Q6581072" in p21_ids else "Men"

        # Sport (ưu tiên Wikidata claims P641 / P106 rồi mới đến description)
        p641_ids = [c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id") for c in claims.get("P641", [])]
        p106_ids = [c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id") for c in claims.get("P106", [])]
        wd_sport_map = {
            "Q3930": "Bóng bàn", "Q13382519": "Bóng bàn",
            "Q7291": "Cầu lông", "Q13141064": "Cầu lông",
            "Q2736": "Bóng đá", "Q937857": "Bóng đá", "Q18536342": "Bóng đá",
            "Q5369": "Bóng chày", "Q10871364": "Bóng chày",
            "Q5372": "Bóng rổ", "Q3665646": "Bóng rổ",
            "Q1734": "Bóng chuyền", "Q15117302": "Bóng chuyền",
            "Q847": "Quần vợt", "Q10833314": "Quần vợt",
            "Q5377": "Golf", "Q13156709": "Golf",
        }
        sport = "Môn khác"
        for qid in (p641_ids + p106_ids):
            if qid in wd_sport_map:
                sport = wd_sport_map[qid]
                break

        all_desc_low = all_desc.lower()
        if sport == "Môn khác":
            if any(k in all_desc_low for k in ["badminton", "バドミントン", "배드민턴", "羽毛球"]):
                sport = "Cầu lông"
            elif any(k in all_desc_low for k in ["table tennis", "卓球", "탁구", "乒乓球"]):
                sport = "Bóng bàn"
            elif any(k in all_desc_low for k in ["football", "soccer", "サッカー", "축구", "足球"]):
                sport = "Bóng đá"
            elif any(k in all_desc_low for k in ["baseball", "野球", "야구", "棒球"]):
                sport = "Bóng chày"
            elif any(k in all_desc_low for k in ["basketball", "バスケット", "농구", "籃球"]):
                sport = "Bóng rổ"
            elif any(k in all_desc_low for k in ["volleyball", "バレー", "배구", "排球"]):
                sport = "Bóng chuyền"
            elif "tennis" in all_desc_low or "テニス" in all_desc_low or "테니스" in all_desc_low:
                sport = "Quần vợt"
            else:
                m_sp = _SPORT_HINT_RE.search(desc_en.lower())
                if m_sp:
                    sport = EN_TO_VI_MAP.get(m_sp.group(1).lower(), m_sp.group(1).capitalize())

        # Country (ưu tiên P27 trước khi đọc description/sitelink)
        p27_ids = [c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id") for c in claims.get("P27", [])]
        wd_country_map = {
            "Q884": ("Hàn Quốc", "Asia/Seoul", "🇰🇷"),
            "Q17": ("Nhật Bản", "Asia/Tokyo", "🇯🇵"),
            "Q148": ("Trung Quốc", "Asia/Shanghai", "🇨🇳"),
            "Q881": ("Việt Nam", "Asia/Ho_Chi_Minh", "🇻🇳"),
            "Q142": ("Pháp", "Europe/Paris", "🇫🇷"),
            "Q183": ("Đức", "Europe/Berlin", "🇩🇪"),
            "Q145": ("Anh", "Europe/London", "🏴󠁧󠁢󠁥󠁮󠁧󠁿"),
            "Q30": ("Mỹ", "America/New_York", "🇺🇸"),
            "Q29": ("Tây Ban Nha", "Europe/Madrid", "🇪🇸"),
            "Q38": ("Ý", "Europe/Rome", "🇮🇹"),
            "Q155": ("Brazil", "America/Sao_Paulo", "🇧🇷"),
            "Q414": ("Argentina", "America/Argentina/Buenos_Aires", "🇦🇷"),
            "Q45": ("Bồ Đào Nha", "Europe/Lisbon", "🇵🇹"),
            "Q55": ("Hà Lan", "Europe/Amsterdam", "🇳🇱"),
        }
        country_name, tz, flag = "Quốc tế", "UTC", "🌐"
        for cid in p27_ids:
            if cid in wd_country_map:
                country_name, tz, flag = wd_country_map[cid]
                break

        if country_name == "Quốc tế":
            for eng_k, trans in EN_TO_VI_MAP.items():
                if isinstance(trans, dict) and re.search(r'\b' + re.escape(eng_k) + r'\b', desc_en, re.IGNORECASE):
                    country_name, tz, flag = trans["name"], trans["tz"], trans["flag"]
                    break
        if country_name == "Quốc tế":
            if "日本" in all_desc or "japan" in all_desc_low or ent.get("sitelinks", {}).get("jawiki"):
                country_name, tz, flag = "Nhật Bản", "Asia/Tokyo", "🇯🇵"
            elif "한국" in all_desc or "대한민국" in all_desc or "korea" in all_desc_low or ent.get("sitelinks", {}).get("kowiki"):
                country_name, tz, flag = "Hàn Quốc", "Asia/Seoul", "🇰🇷"

        # Thu thập aliases từ labels + aliases + sitelinks
        extra_aliases = []
        for lang in ("en", "ja", "ko", "zh", "vi"):
            lbl = (ent.get("labels", {}).get(lang, {}) or {}).get("value")
            if lbl:
                extra_aliases.append(lbl)
                if lang == "ja":
                    extra_aliases.extend(_split_japanese_name_clean(lbl))
            for al in ent.get("aliases", {}).get(lang, []):
                val = al.get("value")
                if val:
                    extra_aliases.append(val)
        for sk in ("enwiki", "jawiki", "kowiki", "zhwiki"):
            stitle = (ent.get("sitelinks", {}).get(sk, {}) or {}).get("title")
            if stitle:
                clean_st = re.sub(r'\(.*?\)', '', stitle).strip()
                extra_aliases.append(clean_st)
                if sk == "jawiki":
                    extra_aliases.extend(_split_japanese_name_clean(clean_st))

        # Kiểm tra thêm Hangul/Kanji từ kowiki/jawiki/zhwiki nếu chưa đủ thông tin
        zh_title = (ent.get("sitelinks", {}).get("zhwiki", {}) or {}).get("title")
        ko_title = (ent.get("sitelinks", {}).get("kowiki", {}) or {}).get("title")
        ja_title = (ent.get("sitelinks", {}).get("jawiki", {}) or {}).get("title")
        if sport == "Môn khác" or country_name == "Quốc tế":
            for lcode, ltitle in [("ko", ko_title), ("ja", ja_title), ("zh", zh_title)]:
                if not ltitle:
                    continue
                try:
                    lu = f"https://{lcode}.wikipedia.org/w/api.php?action=query&prop=extracts&exintro&explaintext&titles={urllib.parse.quote(ltitle)}&format=json"
                    lreq = urllib.request.Request(lu, headers=_WIKI_HEADERS)
                    with urllib.request.urlopen(lreq, timeout=4) as lr:
                        lpages = json.loads(lr.read().decode()).get("query", {}).get("pages", {})
                    if lpages:
                        lextract = list(lpages.values())[0].get("extract", "")
                        if any(w in lextract for w in ["卓球", "탁구", "乒乓球", "桌球"]):
                            sport = "Bóng bàn"
                        elif any(w in lextract for w in ["バドミントン", "배드민턴", "羽毛球"]):
                            sport = "Cầu lông"
                        elif any(w in lextract for w in ["サッカー", "축구", "足球"]):
                            sport = "Bóng đá"
                        if country_name == "Quốc tế":
                            if any(w in lextract for w in ["韓国", "대한민국", "韓國", "南韓", "韩国", "South Korea"]):
                                country_name, tz, flag = "Hàn Quốc", "Asia/Seoul", "🇰🇷"
                            elif any(w in lextract for w in ["日本", "Japan"]):
                                country_name, tz, flag = "Nhật Bản", "Asia/Tokyo", "🇯🇵"
                        if any(w in lextract for w in ["女子", "彼女", "女", "여자"]):
                            gender = "Women"
                        for km in re.findall(r'[\uac00-\ud7af]{2,4}', lextract[:120]):
                            if _is_valid_alias_entry(km, player_name):
                                extra_aliases.append(km)
                        break
                except Exception:
                    pass

        team_name = f"Đội tuyển {country_name}" if sport in ["Quần vợt", "Cầu lông", "Bóng bàn"] and country_name != "Quốc tế" else "Tự do"
        display_name = (ent.get("labels", {}).get("en", {}) or {}).get("value") or player_name

        return {
            "display_name": display_name,
            "api_player_id": f"wd_{matched_qid}",
            "api_team_id": f"wiki_t_{abs(hash(team_name)) % 9000}",
            "team_name": team_name,
            "loan_club": None,
            "parent_club": None,
            "country_name": country_name,
            "timezone": tz,
            "country_flag": flag,
            "sport_name": sport,
            "aliases": build_clean_player_aliases(display_name, [player_name] + extra_aliases),
            "gender": gender,
            "found": True
        }
    except Exception:
        return {"found": False}

def fetch_free_player_info(player_name: str) -> dict:
    clean_key = (player_name or "").strip().lower()
    if not clean_key:
        return {"found": False}
    if clean_key in _WIKI_CACHE:
        return _WIKI_CACHE[clean_key]

    parts = player_name.strip().split()
    search_queries = [player_name.strip()]
    if len(parts) == 2:
        search_queries.append(f"{parts[1]} {parts[0]}")

    title = None
    try:
        for sq in search_queries:
            search_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote(sq)}&utf8=&format=json&srlimit=6"
            req_search = urllib.request.Request(search_url, headers=_WIKI_HEADERS)
            with urllib.request.urlopen(req_search, timeout=8) as response:
                search_data = json.loads(response.read().decode())
            results = search_data.get('query', {}).get('search', [])
            # Ưu tiên kết quả khớp tên VĐV VÀ là trang tiểu sử thể thao
            for res in results:
                t = res.get('title', '')
                if _EVENT_TITLE_RE.search(t):
                    continue
                if not _title_matches_player(player_name, t):
                    continue
                snip = re.sub(r'<[^>]+>', '', res.get('snippet', '')).lower()
                if _NON_ATHLETE_DESC_RE.search(snip) and not _SPORT_HINT_RE.search(snip):
                    continue
                if _SPORT_HINT_RE.search(t.lower() + " " + snip):
                    title = t
                    break
            if title:
                break

        if not title:
            wd_res = _fetch_from_wikidata(player_name)
            if wd_res.get("found"):
                _WIKI_CACHE[clean_key] = wd_res
                return wd_res
            res_false = {"found": False}
            _WIKI_CACHE[clean_key] = res_false
            return res_false

        summary_url = f"https://en.wikipedia.org/w/api.php?action=query&prop=extracts|langlinks|revisions&exintro&explaintext&rvprop=content&rvsection=0&titles={urllib.parse.quote(title)}&lllimit=500&format=json"
        req_summary = urllib.request.Request(summary_url, headers=_WIKI_HEADERS)
        with urllib.request.urlopen(req_summary, timeout=8) as response:
            pages = json.loads(response.read().decode()).get('query', {}).get('pages', {})
            if not pages:
                return {"found": False}

            page = list(pages.values())[0]
            summary_raw = page.get('extract', '')
            summary = summary_raw.lower()

            wikitext = ""
            if "revisions" in page and page["revisions"]:
                wikitext = page["revisions"][0].get("*", "")

            raw_aliases = [player_name]
            clean_page_title = re.sub(r'\s*\([^)]*\)$', '', title).strip()
            if clean_page_title and clean_page_title.lower() != player_name.lower():
                raw_aliases.append(clean_page_title)

            # 1. Trích xuất tên bản địa (Hàn, Nhật, Trung, Anh, Việt) từ langlinks
            has_native_alias = False
            if 'langlinks' in page:
                for ll in page['langlinks']:
                    l_code = ll.get('lang')
                    raw_val = ll.get('*', '')
                    if l_code in ['ja', 'ko', 'zh', 'vi', 'en']:
                        clean_val = re.sub(r'\(.*?\)', '', raw_val).strip()
                        if _is_valid_alias_entry(clean_val, player_name):
                            raw_aliases.append(clean_val)
                            if l_code in ['ja', 'ko', 'zh']:
                                has_native_alias = True
                            if l_code == 'ja':
                                raw_aliases.extend(_split_japanese_name_clean(clean_val))

            # 2. Bóc tách cụm Hangul, Kanji, Kana đầy đủ từ ngoặc đơn đầu bài (KHÔNG băm nhỏ thành họ/tên lẻ)
            first_paren = re.search(r'\((.*?)\)', summary_raw)
            if first_paren:
                pc = first_paren.group(1)
                for seg in re.split(r'[;,]', pc):
                    seg_clean = re.sub(r'^(?:Japanese|Korean|Chinese|Hanja|Hangul|Kanji|born|also known as)\s*:?\s*', '', seg.strip(), flags=re.IGNORECASE).strip()
                    if not seg_clean:
                        continue
                    for km in re.findall(r'[\uac00-\ud7af]{2,5}(?:\s[\uac00-\ud7af]{1,4})?', seg_clean):
                        if _is_valid_alias_entry(km, player_name):
                            raw_aliases.append(km)
                            has_native_alias = True
                    for jm in re.findall(r'[\u4e00-\u9fff\u3040-\u30ff\u3005]{2,8}(?:\s[\u4e00-\u9fff\u3040-\u30ff\u3005]{1,6})?', seg_clean):
                        if _is_valid_alias_entry(jm, player_name):
                            raw_aliases.append(jm)
                            has_native_alias = True
                            raw_aliases.extend(_split_japanese_name_clean(jm))

            # 3. Bóc tách từ Infobox wikitext nếu có (hangul, kanji, native_name)
            if wikitext:
                for pat in [r'\|\s*hangul\s*=\s*([^\n\|\}]+)', r'\|\s*hanja\s*=\s*([^\n\|\}]+)', r'\|\s*kanji\s*=\s*([^\n\|\}]+)', r'\|\s*native_name\s*=\s*([^\n\|\}]+)']:
                    for m in re.finditer(pat, wikitext, re.IGNORECASE):
                        val = re.sub(r'\(.*?\)|<[^>]+>|\[\[|\]\]|\{\{.*?\}\}', '', m.group(1)).strip()
                        for pn in re.findall(r'[\u4e00-\u9fff\uac00-\ud7af\u3040-\u30ff\u3005\s]{2,}', val):
                            pn_clean = " ".join(pn.split())
                            if _is_valid_alias_entry(pn_clean, player_name):
                                raw_aliases.append(pn_clean)
                                has_native_alias = True
                                raw_aliases.extend(_split_japanese_name_clean(pn_clean))

            # Nếu Wikipedia EN thiếu tên bản địa (ví dụ trang cầu thủ Nhật/Hàn chưa có langlinks), hỏi thêm Wikidata
            if not has_native_alias:
                try:
                    wd_extra = _fetch_from_wikidata(clean_page_title or player_name)
                    if wd_extra.get("found") and wd_extra.get("aliases"):
                        raw_aliases.extend([a.strip() for a in wd_extra["aliases"].split(",") if a.strip()])
                except Exception:
                    pass

            aliases_str = build_clean_player_aliases(player_name, raw_aliases)

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
                nat_match = re.search(r'is a(?:n)? (?:former )?(.*?)\s*(?:professional\s+)?(?:footballer|soccer|basketball|baseball|pitcher|infielder|outfielder|batter|catcher|guard|volleyball|badminton|tennis|golfer|racing driver|formula one|swimmer|athlete|boxer|mixed martial artist|mma fighter|figure skater|gymnast|cyclist|hockey|cricket|player)', summary)
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
            sport_match = re.search(
                r'\b(football(?:er)?|soccer|basketball|baseball|pitcher|infielder|outfielder|batter|catcher|mlb|nba|npb|volleyball|table tennis|ping pong|badminton|tennis|golf(?:er)?|formula one|formula 1|\bf1\b|racing|motorsport|mixed martial arts|mma|ufc|box(?:ing|er)|ice hockey|hockey|nhl|american football|nfl|rugby|cricket|swimm(?:ing|er)|athletics|track and field|gymnast(?:ics)?|figure skat(?:ing|er)|cycl(?:ing|ist)|esports|snooker|billiards)\b',
                summary
            )
            if sport_match:
                raw_sport = sport_match.group(1).lower()
                sport_alias_fix = {
                    "golfer": "golf", "racing": "racing", "boxer": "boxing",
                    "swimmer": "swimming", "gymnast": "gymnastics",
                    "figure skater": "figure skating", "cyclist": "cycling",
                }
                raw_sport = sport_alias_fix.get(raw_sport, raw_sport)
                sport = EN_TO_VI_MAP.get(raw_sport, raw_sport.capitalize())

            team_name = "Tự do"
            if re.search(r'\bis a former\b|\bretired\b', summary[:180]):
                team_name = "Đã giải nghệ"
            blacklist = ["national team", "major league baseball", "nba", "premier league", "la liga", "serie a", "bundesliga", "nippon professional baseball", "the national", "protests", "slam", "open", "cup", "world"]

            def _clean_extracted_club(cand_club: str) -> str | None:
                c = re.sub(r'^(?:Premier League|La Liga|Bundesliga|2\.\s*Bundesliga|Serie A|Ligue 1|MLS|EFL Championship|WE League|J1 League|K League)\s+(?:club|side|team)\s+', '', (cand_club or '').strip(), flags=re.IGNORECASE).strip()
                c = re.sub(r'\s+(?:since|after|following|before|prior to|until|from|where|which|while|during)\b.*$', '', c, flags=re.IGNORECASE).strip()
                if not c or len(c) <= 2:
                    return None
                if c.lower() in blacklist or _is_pure_country_name(c) or _CLUB_DELEGATION_RE.search(c):
                    return None
                return c

            first_sentence = summary_raw.split('.')[0] if '.' in summary_raw else summary_raw
            stop_clauses = r'(?:\s+of\s+|\s+in\s+|\s+since\s+|\s+after\s+|\s+from\s+|\s+until\s+|\s+following\s+|\s+before\s+|\s*\/\s*|,|\.|\b(?:and|who|where|which|while)\b)'
            patterns = [
                r'\bfor\s+(?:the\s+)?([A-Z0-9\u00C0-\u024F][a-zA-Z0-9\u00C0-\u024F\s\.\-&\']+?)\s+of\s+(?:Major League Baseball|the NBA|the National Basketball Association|NPB|Nippon Professional Baseball|the Premier League|La Liga|Serie A|Bundesliga|Ligue 1)',
                r'(?:is a(?:n)?|currently plays|plays)\s+.*?\bfor\s+(?:the\s+)?(?:[^\.\n,]+ (?:club|team|side|franchise)\s+)?([A-Z0-9\u00C0-\u024F][a-zA-Z0-9\u00C0-\u024F\s\.\-&\']+?)' + stop_clauses,
                r'\bfor\s+(?:the\s+)?(?:[^\.\n,]+ (?:club|team|side|franchise)\s+)?([A-Z0-9\u00C0-\u024F][a-zA-Z0-9\u00C0-\u024F\s\.\-&\']+?)' + stop_clauses
            ]

            if team_name == "Tự do":
                for pattern in patterns:
                    match = re.search(pattern, first_sentence)
                    if match:
                        cleaned_c = _clean_extracted_club(match.group(1))
                        if cleaned_c:
                            team_name = cleaned_c
                            break

            if team_name == "Tự do":
                loan_match = re.search(r'\bon loan (?:at|to)\s+(?:the\s+)?(?:[^\.\n,]+ (?:club|team|side|franchise)\s+)?([A-Z0-9\u00C0-\u024F][a-zA-Z0-9\u00C0-\u024F\s\.\-&\']+?)(?:\s+from\s+|\s+of\s+|\s+in\s+|\s*\/\s*|,|\.|\b(?:and|who)\b)', first_sentence, re.IGNORECASE)
                if loan_match:
                    cleaned_c = _clean_extracted_club(loan_match.group(1))
                    if cleaned_c:
                        team_name = cleaned_c

            if team_name == "Tự do":
                for pattern in patterns:
                    match = re.search(pattern, summary_raw)
                    if match:
                        cleaned_c = _clean_extracted_club(match.group(1))
                        if cleaned_c:
                            team_name = cleaned_c
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
                    cleaned_curr = _clean_extracted_club(raw_curr)
                    if cleaned_curr:
                        parent_club = cleaned_curr

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
                        cleaned_c = _clean_extracted_club(c_name)
                        if cleaned_c:
                            if is_last_loan:
                                active_loan_club = cleaned_c
                            elif team_name == "Tự do":
                                team_name = cleaned_c

            if active_loan_club:
                if not parent_club:
                    parent_club = team_name if team_name != "Tự do" else None
                team_name = active_loan_club

            if sport in ["Quần vợt", "Cầu lông", "Bóng bàn"] and (team_name == "Tự do" or _is_pure_country_name(team_name) or _CLUB_DELEGATION_RE.search(team_name)):
                team_name = f"Đội tuyển {country_name}"

            # 5. Nhận diện giới tính (Gender detection: Men / Women — đối chiếu đại từ nhân xưng để tránh nhận nhầm HLV đội nữ là VĐV nữ)
            male_pronouns = len(re.findall(r'\b(he|him|his)\b', summary_raw, re.IGNORECASE))
            female_pronouns = len(re.findall(r'\b(she|her|hers)\b', summary_raw, re.IGNORECASE))
            if male_pronouns > female_pronouns and female_pronouns == 0:
                is_female = False
            else:
                is_female = bool(female_pronouns >= 1 and female_pronouns >= male_pronouns) or bool(
                    male_pronouns == 0 and re.search(r'\b(female|woman|women\'s|frauen|we league|wsl|nwsl|liga f|wnba|nadeshiko|ladies|dames|femeni)\b', summary_raw, re.IGNORECASE)
                )
                if not is_female and male_pronouns == 0 and wikitext:
                    is_female = bool(re.search(r'\b(she|her|female|woman|women\'s|frauen|we league|wsl|nwsl|liga f|wnba|nadeshiko|ladies|dames|femeni)\b', wikitext, re.IGNORECASE))
                if not is_female and parent_club and any(w in parent_club.lower() for w in ["women", "frauen", "ladies", "(w)"]):
                    is_female = True

            gender = "Women" if is_female else "Men"

            # Nếu là VĐV nữ, chuẩn hóa tên CLB rõ ràng để phân biệt với đội nam
            if is_female and team_name and team_name not in ["Tự do", "Chưa rõ CLB", "Đã giải nghệ"] and not team_name.startswith("Đội tuyển"):
                if not any(w in team_name.lower() for w in ["(nữ)", "(women)", "(w)", "women", "frauen", "ladies", "femeni"]):
                    team_name = f"{team_name} (Nữ)"

            result = {
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
            _WIKI_CACHE[clean_key] = result
            return result
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
