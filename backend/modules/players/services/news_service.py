import re
import feedparser
import urllib.parse
import datetime
from sqlalchemy.orm import Session
from backend.core.config import CLUB_BLACKLIST
from backend.core.db.models import Player, PlayerNews

TRANSFER_KEYWORDS = [
    "transfer", "rumor", "rumour", "signed", "signing", "deal", "bid", "fee", "contract",
    "loan", "swap", "clause", "release clause", "target", "agreed terms",
    "chuyển nhượng", "hợp đồng", "gia hạn", "chiêu mộ", "tin đồn", "mượn", "thương vụ",
    "移籍", "契約", "残留", "獲得", "退団", "加入", "オファー", "違約金",
    "이적", "계약", "영입", "방출", "재계약", "임대", "바이아웃"
]

STATEMENT_KEYWORDS = [
    "interview", "quotes", "quote", "reveals", "revealed", "speaks", "speak", "spoke",
    "says", "said", "press conference", "opens up", "admits", "claimed", "claims",
    "phỏng vấn", "phát biểu", "chia sẻ", "lên tiếng", "họp báo", "bày tỏ", "khẳng định",
    "語る", "明かす", "会見", "インタビュー", "発言", "コメント", "激白",
    "인터뷰", "기자회견", "밝혔다", "언급", "말했다", "소감"
]

ANALYSIS_KEYWORDS = [
    "rating", "ratings", "stats", "statistics", "analysis", "tactics", "tactical",
    "breakdown", "award", "mvp", "man of the match", "motm", "milestone", "record", "praised",
    "chấm điểm", "thống kê", "đánh giá", "kỷ lục", "phân tích", "chiến thuật", "xuất sắc nhất",
    "採点", "評価", "スタッツ", "分析", "戦術", "最高評価",
    "평점", "분석", "통계", "전술", "최고 평점"
]

MATCH_KEYWORDS = [
    "goal", "goals", "assist", "assists", "score", "scores", "scored", "match", "vs", "versus",
    "against", "fixture", "lineup", "line-up", "start", "starts", "started", "starting",
    "bench", "injury", "injured", "return", "win", "wins", "won", "loss", "lost", "draw",
    "highlights", "debut", "red card", "clean sheet", "clash",
    "bàn thắng", "kiến tạo", "ra sân", "đá chính", "dự bị", "chấn thương", "ghi bàn",
    "thắng", "thua", "hòa", "trận đấu", "đối đầu", "đội hình", "tái xuất",
    "ゴール", "アシスト", "得点", "先発", "スタメン", "怪我", "負傷", "復帰", "勝利", "敗戦", "試合",
    "골", "도움", "어시스트", "선발", "출전", "부상", "복귀", "승리", "패배", "경기"
]

def _matches_any_keyword(text: str, kw_list: list) -> bool:
    for kw in kw_list:
        if kw.isascii() and " " not in kw:
            if re.search(r'\b' + re.escape(kw) + r'\b', text, re.IGNORECASE):
                return True
        else:
            if kw.lower() in text:
                return True
    return False

def build_valid_player_names(player_name: str, aliases: str = "") -> list:
    raw_names = [player_name]
    if aliases:
        raw_names.extend([a.strip() for a in aliases.split(",") if a.strip()])
    
    valid_tokens = set()
    for raw in raw_names:
        clean = raw.strip()
        if not clean or clean.lower() in CLUB_BLACKLIST:
            continue
        valid_tokens.add(clean)
        
        unspaced = clean.replace(" ", "")
        if unspaced != clean:
            valid_tokens.add(unspaced)
            
        parts = clean.split()
        for p in parts:
            if len(p) >= 3 and (p.isalpha() or any('\u4e00' <= c <= '\u9fff' or '\u3040' <= c <= '\u30ff' or '\uac00' <= c <= '\ud7af' for c in p)):
                valid_tokens.add(p)

    return [t for t in valid_tokens if len(t) >= 2]

def classify_news_article(title: str, summary: str = "") -> str:
    clean_summary = re.sub(r'<[^>]+>', ' ', summary)
    combined = f"{title} {clean_summary}".lower()

    if _matches_any_keyword(combined, TRANSFER_KEYWORDS):
        return "transfer"
    if _matches_any_keyword(combined, STATEMENT_KEYWORDS):
        return "statement"
    if _matches_any_keyword(combined, ANALYSIS_KEYWORDS):
        return "analysis"
    if _matches_any_keyword(combined, MATCH_KEYWORDS):
        return "match"

    return "side_news"

PLAYER_NATIVE_NAMES = {
    "takefusa kubo": ["久保建英", "久保 建英"],
    "son heung-min": ["손흥민"],
    "kim min-jae": ["김민재"],
    "hwang hee-chan": ["황희찬"],
    "hwang in-beom": ["황인범"],
    "oh hyeon-gyu": ["오현규"],
    "lee kang-in": ["이강in", "이강인"],
    "lee jae-sung": ["이재성"],
    "kim min-su": ["김민수"],
    "bae jun-ho": ["배준호"],
    "seol young-woo": ["설영우"],
    "yang min-hyuk": ["양민혁"],
    "cho gue-sung": ["조규성"],
    "jeong woo-yeong": ["정우영"],
    "paik seung-ho": ["백승호"],
    "eom ji-sung": ["엄지성"],
    "daichi kamada": ["鎌田大地", "鎌田 大地"],
    "ko itakura": ["板倉滉", "板倉 滉"],
    "wataru endo": ["遠藤航", "遠藤 航"],
    "kaoru mitoma": ["三笘薫", "三笘 薫"],
    "ao tanaka": ["田中碧", "田中 碧"],
    "zion suzuki": ["鈴木彩艶", "鈴木 彩艶"],
    "seiya suzuki": ["鈴木誠也", "鈴木 誠也"],
    "rui hachimura": ["八村塁", "八村 塁"],
    "shohei ohtani": ["大谷翔平", "大谷 翔平"],
    "yoshinobu yamamoto": ["山本由伸", "山本 由伸"],
    "roki sasaki": ["佐々木朗希", "佐々木 朗希"],
    "shota imanaga": ["今永昇太", "今永 昇太"],
    "masataka yoshida": ["吉田正尚", "吉田 正尚"],
    "munetaka murakami": ["村上宗隆", "村上 宗隆"],
    "kazuma okamoto": ["岡本和真", "岡本 和真"],
    "ritsu doan": ["堂安律", "堂安 律"],
    "hiroki ito": ["伊藤洋輝", "伊藤 洋輝"],
    "yuki ishikawa": ["石川祐希", "石川 祐希"],
    "keito nakamura": ["中村敬斗", "中村 敬斗"],
    "daizen maeda": ["前田大然", "前田 大然"],
    "kyogo furuhashi": ["古橋亨梧", "古橋 亨梧"],
    "reo hatate": ["旗手怜央", "旗手 怜央"],
    "takumi minamino": ["南野拓実", "南野 拓実"],
    "koki machida": ["町田浩樹", "町田 浩樹"],
    "koki ogawa": ["小川航基", "小川 航基"],
    "yukinari sugawara": ["菅原由勢", "菅原 由勢"]
}

def fetch_player_news_entries(player_name: str, aliases: str = "", country_name: str = "") -> list:
    nat = (country_name or "").strip()
    p_lower = (player_name or "").lower().strip()

    # 1. Clean aliases and filter out irrelevant foreign scripts
    clean_aliases = []
    if aliases:
        for a in aliases.split(","):
            a_clean = a.strip()
            if not a_clean or "(" in a_clean or ")" in a_clean or len(a_clean) < 2 or a_clean.lower() in CLUB_BLACKLIST:
                continue
            if nat == "Nhật Bản":
                if not any('\u4e00' <= c <= '\u9fff' or '\u3040' <= c <= '\u30ff' or c.isascii() for c in a_clean):
                    continue
            elif nat == "Hàn Quốc":
                if not any('\uac00' <= c <= '\ud7af' or c.isascii() for c in a_clean):
                    continue
            clean_aliases.append(a_clean)

    # 2. Search terms: prioritize English name and native script
    search_terms = [player_name]
    native_names = []
    latin_aliases = []
    
    # Auto-populate native names from PLAYER_NATIVE_NAMES lookup
    for k, v in PLAYER_NATIVE_NAMES.items():
        if k in p_lower or p_lower in k:
            for item in v:
                if item not in native_names:
                    native_names.append(item)

    for a in clean_aliases:
        if nat == "Nhật Bản" and any('\u4e00' <= c <= '\u9fff' or '\u3040' <= c <= '\u30ff' for c in a):
            if a not in native_names:
                native_names.append(a)
        elif nat == "Hàn Quốc" and any('\uac00' <= c <= '\ud7af' for c in a):
            if a not in native_names:
                native_names.append(a)
        elif a.lower() != player_name.lower():
            if a not in latin_aliases:
                latin_aliases.append(a)

    # Đảo thứ tự Tên - Họ / Họ - Tên cho cầu thủ Đông Á (Hàn Quốc, Nhật Bản...) trong truyền thông quốc tế
    # Ví dụ: "Oh Hyeon-gyu" <-> "Hyeon-gyu Oh", "Takefusa Kubo" <-> "Kubo Takefusa"
    p_parts = player_name.split()
    if len(p_parts) == 2:
        inverted_name = f"{p_parts[1]} {p_parts[0]}"
        if inverted_name.lower() not in [l.lower() for l in latin_aliases] and inverted_name.lower() != player_name.lower():
            latin_aliases.append(inverted_name)

    for n in native_names:
        if n not in search_terms:
            search_terms.append(n)
    for l in latin_aliases:
        if l not in search_terms:
            search_terms.append(l)

    COUNTRY_NEWS_MAP = {
        "Nhật Bản": {"code": "JP", "hl": "ja", "gl": "JP"},
        "Hàn Quốc": {"code": "KR", "hl": "ko", "gl": "KR"},
        "Việt Nam": {"code": "VN", "hl": "vi", "gl": "VN"},
        "Pháp": {"code": "FR", "hl": "fr", "gl": "FR"},
        "Tây Ban Nha": {"code": "ES", "hl": "es", "gl": "ES"},
        "Mỹ": {"code": "US", "hl": "en", "gl": "US"},
        "Anh": {"code": "GB", "hl": "en", "gl": "GB"},
        "Đức": {"code": "DE", "hl": "de", "gl": "DE"},
        "Argentina": {"code": "AR", "hl": "es", "gl": "AR"},
        "Brazil": {"code": "BR", "hl": "pt", "gl": "BR"},
        "Bồ Đào Nha": {"code": "PT", "hl": "pt", "gl": "PT"},
        "Ý": {"code": "IT", "hl": "it", "gl": "IT"}
    }

    regions = [{"code": "US", "hl": "en", "gl": "US"}]
    if nat in COUNTRY_NEWS_MAP and COUNTRY_NEWS_MAP[nat]["code"] != "US":
        regions.append(COUNTRY_NEWS_MAP[nat])

    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    valid_names = build_valid_player_names(player_name, aliases)
    for nn in native_names:
        if nn not in valid_names:
            valid_names.append(nn)

    all_found = []
    seen_links = set()

    for reg in regions:
        # For native language regions (Japan, Korea), query directly with the native name (e.g. 久保建英 or 손흥민)
        # to unlock all Japanese/Korean news outlets (Yahoo Japan, Nikkan, Naver, etc.)
        if reg["code"] in ["JP", "KR"] and native_names:
            target_q = f'"{native_names[0]}"'
        else:
            query_parts = [f'"{player_name}"']
            for la in latin_aliases[:2]:
                query_parts.append(f'"{la}"')
            target_q = " OR ".join(query_parts)

        encoded_query = urllib.parse.quote(target_q)
        ceid_param = f"&ceid={reg['gl']}:{reg['hl']}" if "hl" in reg and "gl" in reg else ""
        rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl={reg['hl']}&gl={reg['gl']}{ceid_param}"
        try:
            req = urllib.request.Request(rss_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=4) as resp:
                raw_xml = resp.read()
            feed = feedparser.parse(raw_xml)
        except Exception:
            feed = None

        entries = getattr(feed, "entries", []) or []
        for entry in entries:
            title = getattr(entry, "title", "").strip()
            link = getattr(entry, "link", "").strip()
            summary = getattr(entry, "summary", "").strip()
            if not title or not link or link in seen_links:
                continue

            pub_dt = None
            if getattr(entry, "published_parsed", None):
                try:
                    pub_dt = datetime.datetime(*entry.published_parsed[:6])
                except Exception:
                    pub_dt = None
            elif getattr(entry, "updated_parsed", None):
                try:
                    pub_dt = datetime.datetime(*entry.updated_parsed[:6])
                except Exception:
                    pub_dt = None

            seen_links.add(link)
            news_type = classify_news_article(title, summary)

            all_found.append({
                "title": title,
                "source_url": link,
                "news_type": news_type,
                "region": reg["code"],
                "published_at": pub_dt or now_utc
            })

    # Sort all found by published_at descending
    all_found.sort(key=lambda x: x["published_at"], reverse=True)

    # Giữ lại toàn bộ tin tức giá trị cao trong vòng 14 ngày gần nhất (tối đa 100 bài mới nhất)
    cutoff_recent = now_utc - datetime.timedelta(days=14)
    recent_news = [item for item in all_found if item["published_at"] >= cutoff_recent]
    if not recent_news and all_found:
        recent_news = all_found[:30]

    return recent_news[:100]

def scan_player_news(db: Session, player_id: int, player_name: str):
    player = db.query(Player).filter(Player.id == player_id).first()
    if not player:
        return

    nat = (player.country_name or "").strip()
    entries = fetch_player_news_entries(player_name, player.name_aliases or "", nat)

    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    # Dọn dẹp tin tức cũ hơn 30 ngày trong database để bảo tồn khung tin cho các trận gần đây
    cutoff_retention = now_utc - datetime.timedelta(days=30)
    db.query(PlayerNews).filter(
        PlayerNews.player_id == player_id,
        PlayerNews.published_at < cutoff_retention
    ).delete()

    existing_news = db.query(PlayerNews).filter(PlayerNews.player_id == player_id).all()
    existing_map = {n.source_url: n for n in existing_news}

    for item in entries:
        if item["source_url"] in existing_map:
            existing_map[item["source_url"]].news_type = item["news_type"]
            continue
        news_item = PlayerNews(
            player_id=player_id,
            title=item["title"],
            source_url=item["source_url"],
            news_type=item["news_type"],
            region=item["region"],
            published_at=item["published_at"]
        )
        db.add(news_item)
    db.commit()

