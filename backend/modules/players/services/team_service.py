import urllib.request
import urllib.parse
import json
import re
from backend.core.config import LEAGUE_SLUG_MAP, SPORT_TO_ESPN

# Catalog các đội bóng chuyền, bóng rổ châu Âu, bóng chày châu Á phổ biến để tra cứu nhanh
KNOWN_GLOBAL_CLUBS = [
    # Volleyball (Bóng chuyền)
    {"name": "Sir Safety Perugia", "short": "Perugia", "sport": "Bóng chuyền", "league": "SuperLega", "league_slug": "ita.superlega", "gender": "Nam", "country": "Ý"},
    {"name": "Allianz Milano", "short": "Milano", "sport": "Bóng chuyền", "league": "SuperLega", "league_slug": "ita.superlega", "gender": "Nam", "country": "Ý"},
    {"name": "Itas Trentino", "short": "Trentino", "sport": "Bóng chuyền", "league": "SuperLega", "league_slug": "ita.superlega", "gender": "Nam", "country": "Ý"},
    {"name": "Cucine Lube Civitanova", "short": "Civitanova", "sport": "Bóng chuyền", "league": "SuperLega", "league_slug": "ita.superlega", "gender": "Nam", "country": "Ý"},
    {"name": "Ziraat Bankkart", "short": "Ziraat Bankkart", "sport": "Bóng chuyền", "league": "Efeler Ligi", "league_slug": "tur.efeler", "gender": "Nam", "country": "Thổ Nhĩ Kỳ"},
    {"name": "Halkbank Ankara", "short": "Halkbank", "sport": "Bóng chuyền", "league": "Efeler Ligi", "league_slug": "tur.efeler", "gender": "Nam", "country": "Thổ Nhĩ Kỳ"},
    {"name": "Suntory Sunbirds", "short": "Suntory Sunbirds", "sport": "Bóng chuyền", "league": "SV.League", "league_slug": "jpn.sv", "gender": "Nam", "country": "Nhật Bản"},
    {"name": "Osaka Bluteon (Panasonic)", "short": "Osaka Bluteon", "sport": "Bóng chuyền", "league": "SV.League", "league_slug": "jpn.sv", "gender": "Nam", "country": "Nhật Bản"},
    {"name": "JTEKT Stings Aichi", "short": "JTEKT Stings", "sport": "Bóng chuyền", "league": "SV.League", "league_slug": "jpn.sv", "gender": "Nam", "country": "Nhật Bản"},
    {"name": "Cheonan Hyundai Capital Skywalkers", "short": "Hyundai Capital", "sport": "Bóng chuyền", "league": "V-League (Hàn Quốc)", "league_slug": "kor.vleague", "gender": "Nam", "country": "Hàn Quốc"},
    {"name": "Incheon Korean Air Jumbos", "short": "Korean Air Jumbos", "sport": "Bóng chuyền", "league": "V-League (Hàn Quốc)", "league_slug": "kor.vleague", "gender": "Nam", "country": "Hàn Quốc"},

    # Baseball (Bóng chày Nhật Bản / Hàn Quốc)
    {"name": "Hanshin Tigers", "short": "Hanshin Tigers", "sport": "Bóng chày", "league": "NPB", "league_slug": "jpn.npb", "gender": "Nam", "country": "Nhật Bản"},
    {"name": "Yomiuri Giants", "short": "Yomiuri Giants", "sport": "Bóng chày", "league": "NPB", "league_slug": "jpn.npb", "gender": "Nam", "country": "Nhật Bản"},
    {"name": "Orix Buffaloes", "short": "Orix Buffaloes", "sport": "Bóng chày", "league": "NPB", "league_slug": "jpn.npb", "gender": "Nam", "country": "Nhật Bản"},
    {"name": "Fukuoka SoftBank Hawks", "short": "SoftBank Hawks", "sport": "Bóng chày", "league": "NPB", "league_slug": "jpn.npb", "gender": "Nam", "country": "Nhật Bản"},
    {"name": "Hiroshima Toyo Carp", "short": "Hiroshima Carp", "sport": "Bóng chày", "league": "NPB", "league_slug": "jpn.npb", "gender": "Nam", "country": "Nhật Bản"},
    {"name": "Chiba Lotte Marines", "short": "Lotte Marines", "sport": "Bóng chày", "league": "NPB", "league_slug": "jpn.npb", "gender": "Nam", "country": "Nhật Bản"},
    {"name": "Kia Tigers", "short": "Kia Tigers", "sport": "Bóng chày", "league": "KBO", "league_slug": "kor.kbo", "gender": "Nam", "country": "Hàn Quốc"},
    {"name": "Samsung Lions", "short": "Samsung Lions", "sport": "Bóng chày", "league": "KBO", "league_slug": "kor.kbo", "gender": "Nam", "country": "Hàn Quốc"},
    {"name": "LG Twins", "short": "LG Twins", "sport": "Bóng chày", "league": "KBO", "league_slug": "kor.kbo", "gender": "Nam", "country": "Hàn Quốc"},

    # Basketball (Bóng rổ Châu Âu & B.League)
    {"name": "Panathinaikos BC", "short": "Panathinaikos", "sport": "Bóng rổ", "league": "EuroLeague", "league_slug": "eu.euroleague", "gender": "Nam", "country": "Hy Lạp"},
    {"name": "Olympiacos BC", "short": "Olympiacos", "sport": "Bóng rổ", "league": "EuroLeague", "league_slug": "eu.euroleague", "gender": "Nam", "country": "Hy Lạp"},
    {"name": "Fenerbahçe Beko", "short": "Fenerbahce", "sport": "Bóng rổ", "league": "EuroLeague", "league_slug": "eu.euroleague", "gender": "Nam", "country": "Thổ Nhĩ Kỳ"},
    {"name": "Real Madrid Baloncesto", "short": "Real Madrid Basket", "sport": "Bóng rổ", "league": "EuroLeague", "league_slug": "eu.euroleague", "gender": "Nam", "country": "Tây Ban Nha"},
    {"name": "FC Barcelona Bàsquet", "short": "Barcelona Basket", "sport": "Bóng rổ", "league": "EuroLeague", "league_slug": "eu.euroleague", "gender": "Nam", "country": "Tây Ban Nha"},
    {"name": "Chiba Jets", "short": "Chiba Jets", "sport": "Bóng rổ", "league": "B.League", "league_slug": "jpn.bleague", "gender": "Nam", "country": "Nhật Bản"},
    {"name": "Utsunomiya Brex", "short": "Utsunomiya Brex", "sport": "Bóng rổ", "league": "B.League", "league_slug": "jpn.bleague", "gender": "Nam", "country": "Nhật Bản"}
]

SPORT_VI_MAP = {
    'soccer': 'Bóng đá',
    'baseball': 'Bóng chày',
    'basketball': 'Bóng rổ',
    'hockey': 'Khúc côn cầu',
    'football': 'Bóng bầu dục (Mỹ)',
    'volleyball': 'Bóng chuyền',
    'tennis': 'Quần vợt'
}

def search_team_options(query: str, sport: str = None) -> list[dict]:
    """
    Tìm kiếm và trả về danh sách tất cả các CLB / Đội tuyển phù hợp với từ khóa:
    Gồm tên đội, môn thi đấu, giải đấu chính xác, giới tính (Nam/Nữ) và ID trên ESPN.
    Giúp người dùng tự xem và bấm chọn chính xác đội mình cần (vd: Rangers Nam vs Rangers Nữ vs Texas Rangers MLB).
    """
    clean_q = (query or "").strip()
    if not clean_q or len(clean_q) < 2:
        return []

    results = []
    seen = set()
    clean_q_lower = clean_q.lower()
    target_sport_code = SPORT_TO_ESPN.get(sport) if sport else None

    # 1. Tra cứu trực tiếp từ ESPN Search API
    try:
        url = f"https://site.web.api.espn.com/apis/search/v2?query={urllib.parse.quote(clean_q)}&limit=20"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())

        for item in data.get('results', []):
            for c in item.get('contents', []):
                if c.get('type') != 'team':
                    continue

                raw_name = c.get('displayName', '') or ''
                raw_sport = (c.get('sport') or '').lower()
                sport_vi = SPORT_VI_MAP.get(raw_sport, raw_sport.capitalize())

                # Trích xuất slug giải đấu & logo
                slug = (c.get('defaultLeagueSlug') or '').lower()
                link = c.get('link', {}).get('web', '') or ''
                logo = c.get('image', {}).get('default') or ''

                if not slug and link:
                    parts = link.split('/')
                    try:
                        s_idx = parts.index(raw_sport)
                        slug = parts[s_idx + 1]
                    except Exception:
                        pass

                # Trích xuất numerical ID
                uid = c.get('uid', '') or ''
                raw_id = c.get('id', '') or ''
                m = re.search(r'~t:(\d+)', str(uid)) or re.search(r'/id/(\d+)', str(link))
                team_num_id = m.group(1) if m else raw_id

                subtitle = (c.get('subtitle') or '').strip()

                # Xác định tên giải đấu chuẩn xác
                league_name = LEAGUE_SLUG_MAP.get(slug)
                if not league_name:
                    if subtitle:
                        league_name = subtitle
                    elif slug:
                        league_name = slug.upper()
                    else:
                        league_name = "Giải đấu chính"

                # Phân loại giới tính
                is_women = (
                    '.w.' in slug or 
                    'women' in (raw_name + ' ' + subtitle).lower() or 
                    'fem' in slug or 
                    'wfc' in raw_name.lower() or
                    'women' in link.lower()
                )
                gender = "Nữ" if is_women else "Nam"

                # Tránh trùng lặp
                dedup_key = (raw_name.lower(), sport_vi.lower(), str(league_name).lower())
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                # Tính điểm độ phù hợp
                relevance = 100
                if raw_name.lower() == clean_q_lower:
                    relevance += 50
                elif clean_q_lower in raw_name.lower():
                    relevance += 20
                if target_sport_code and raw_sport == target_sport_code:
                    relevance += 30

                results.append({
                    "team_id": str(team_num_id),
                    "name": raw_name,
                    "sport": sport_vi,
                    "league": league_name,
                    "league_slug": slug,
                    "gender": gender,
                    "subtitle": subtitle or league_name,
                    "logo": logo,
                    "is_women": is_women,
                    "score": relevance
                })
    except Exception:
        pass

    # 2. Bổ sung từ danh mục giải đấu ngoài ESPN (Bóng chuyền, NPB, KBO, B.League...)
    for club in KNOWN_GLOBAL_CLUBS:
        c_name = club["name"].lower()
        c_short = club["short"].lower()
        if clean_q_lower in c_name or clean_q_lower in c_short or c_short in clean_q_lower:
            dedup_key = (club["name"].lower(), club["sport"].lower(), club["league"].lower())
            if dedup_key not in seen:
                seen.add(dedup_key)
                rel = 90
                if sport and club["sport"].lower() == sport.lower():
                    rel += 40
                results.append({
                    "team_id": club["league_slug"],
                    "name": club["name"],
                    "sport": club["sport"],
                    "league": club["league"],
                    "league_slug": club["league_slug"],
                    "gender": club["gender"],
                    "subtitle": f"{club['league']} • {club.get('country', '')}",
                    "logo": "",
                    "is_women": False,
                    "score": rel
                })

    # Sắp xếp theo độ liên quan
    results.sort(key=lambda x: -x["score"])
    return results

