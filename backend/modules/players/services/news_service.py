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

def normalize_news_title(title: str) -> str:
    if not title:
        return ""
    cleaned = re.sub(r'\s*[-–|]\s*[^-–|]+$', '', title.strip())
    target = cleaned if len(cleaned) >= 15 else title.strip()
    return " ".join(target.lower().split())

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
            if len(p) >= 3 and p.lower() not in COMMON_BAD_SURNAMES and p not in COMMON_BAD_SURNAMES and (p.isalpha() or any('\u4e00' <= c <= '\u9fff' or '\u3040' <= c <= '\u30ff' or '\uac00' <= c <= '\ud7af' for c in p)):
                valid_tokens.add(p)

    return [t for t in valid_tokens if len(t) >= 2 and t.lower() not in COMMON_BAD_SURNAMES and t not in COMMON_BAD_SURNAMES]

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
    "lee kang-in": ["이강인"],
    "song min-kyu": ["송민규"],
    "kim ji-soo": ["김지수"],
    "yohei takaoka": ["高丘陽平", "高丘 陽平"],
    "satoshi tanaka": ["田中聡", "田中 聡"],
    "kodai naraoka": ["奈良岡功大", "奈良岡 功大"],
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
    "yuito suzuki": ["鈴木唯人", "鈴木 唯人"],
    "hinata suzuki": ["鈴木陽向", "鈴木 陽向"],
    "yushi tanaka": ["田中湧士", "田中 湧士"],
    "mima ito": ["伊藤美誠", "伊藤 美誠"],
    "tomokazu harimoto": ["張本智和", "張本 智和"],
    "miwa harimoto": ["張本美和", "張本 美和"],
    "koki watanabe": ["渡邉航貴", "渡邊航貴", "渡辺航貴"],
    "tsuyoshi watanabe": ["渡辺剛", "渡辺 剛", "渡邊剛"],
    "rui hachimura": ["八村塁", "八村 塁"],
    "shohei ohtani": ["大谷翔平", "大谷 翔平"],
    "yoshinobu yamamoto": ["山本由伸", "山本 由伸"],
    "momoko tanikawa": ["谷川萌々子", "谷川 萌々子"],
    "yui hasegawa": ["長谷川唯", "長谷川 唯"],
    "hinata miyazawa": ["宮澤ひなた", "宮澤 ひなた"],
    "fuka nagano": ["長野風花", "長野 風花"],
    "aoba fujino": ["藤野あおば", "藤野 あおば"],
    "maika hamano": ["浜野まいか", "浜野 まいか"],
    "kiko seike": ["清家貴子", "清家 貴子"],
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
    "yukinari sugawara": ["菅原由勢", "菅原 由勢"],
    "jens castrop": ["옌스 카스트로프", "카스트로프"],
    "keita kosugi": ["小杉啓太", "小杉 啓太"],
    "keisuke goto": ["後藤啓介", "後藤 啓介"],
    "shuto machino": ["町野修斗", "町野 修斗"],
    "daiki hashioka": ["橋岡大樹", "橋岡 大樹"],
    "zento uno": ["宇野禅斗", "宇野 禅斗"],
    "shio fukuda": ["福田師王", "福田 師王"],
    "takehiro tomiyasu": ["冨安健洋", "冨安 健洋", "富安健洋"],
    "hidemasa morita": ["守田英正", "守田 英正"],
    "kaishu sano": ["佐野海舟", "佐野 海舟"],
    "maya yoshida": ["吉田麻也", "吉田 麻也"],
    "ayase ueda": ["上田綺世", "上田 綺世"],
    "tatsuhiro sakamoto": ["坂元達裕", "坂元 達裕"],
    "rion ichihara": ["市原吏音", "市原 吏音"],
    "seiya maikuma": ["毎熊晟矢", "毎熊 晟矢"],
    "kodai sano": ["佐野航大", "佐野 航大"],
    "shunsuke mito": ["三戸舜介", "三戸 舜介"],
    "ryunosuke sato": ["佐藤龍之介", "佐藤 龍之介"],
    "taichi fukui": ["福井太智", "福井 太智"],
    "sota kawasaki": ["川﨑颯太", "川﨑 颯太", "川崎颯太"],
    "rihito yamamoto": ["山本理仁", "山本 理仁"],
    "ayumu seko": ["瀬古歩夢", "瀬古 歩夢"],
    "kento shiogai": ["塩貝健人", "塩貝 健人"],
    "yuji nishida": ["西田有志", "西田 有志"],
    "kota takai": ["高井幸大", "高井 幸大"]
}

COMMON_BAD_SURNAMES = {
    '鈴木', '田中', '佐藤', '山本', '伊藤', '渡辺', '渡邉', '小林', '吉田', '中村', 
    '加藤', '山口', '斎藤', '松本', '井上', '木村', '林', '清水', '小杉', '後藤', 
    '福田', '宇野', '橋岡', '町野', '前田', '守田', '佐野', '上田', '菅原', '坂元', 
    '町田', '市原', '毎熊', '小川', '三戸', '福井', '高丘', '瀬古', '塩貝', '西田', 
    '高井', '松島', '戸上', '張本', '保木', '西本', '沖本', '奥原', '明地', '山北', 
    '廣上', '保原', '緑川', '古賀', '村上', '岡本', '大谷', '今永', '堂安', '板倉', 
    '遠藤', '三笘', '久保', '鎌田', '八村', '朗希', '誠也', '彩艶', '唯人', '陽向', 
    '湧士', '拳太', '優大', '希望', '陽菜', '卓朗', '優吾', '奈緒', '瑠依', '彩夏', 
    '大輝', '宗隆', '和真', '翔平', '由伸', '昇太', '正尚', '敬斗', '修斗', '大樹', 
    '禅斗', '師王', '健洋', '拓実', '英正', '海舟', '麻也', '綺世', '由勢', '達裕', 
    '浩樹', '吏音', '晟矢', '航基', '航大', '舜介', '太智', '陽平', '理仁', '歩夢', 
    '健人', '有志', '幸大', '輝空', '智和', '隼輔', 'ひな', '美和', '美誠', '美柚', 
    '幸矢', '谷川', '옌스', '황소', '유진', '김', '이', '박', '최', '정', '강', 
    '조', '윤', '장', '임', '한', '오', '서', '신', '권', '황', '안', '송', '전', '홍',
    'suzuki', 'tanaka', 'sato', 'ito', 'kim', 'lee', 'park', 'watanabe', 'yamamoto', 'yoshida'
}

def is_article_strictly_for_player(title: str, summary: str, player_name: str, native_names: list, sport_name: str = "") -> bool:
    content = f"{title} {summary}".lower()
    content_raw = f"{title} {summary}"
    p_low = player_name.lower().strip()
    
    # 1. Negative Cross-Player Conflict Exclusion (Loại trừ người khác trùng họ)
    # 1.1 Nhóm Suzuki:
    if "hinata suzuki" in p_low:
        if any(k in content_raw for k in ["彩艶", "Zion", "唯人", "Yuito", "誠也", "Seiya", "鈴木愛", "パルマ", "Parma", "Aston Villa", "Cubs", "カブス", "GK", "サカノワ"]):
            if "陽向" not in content_raw and "hinata" not in content:
                return False
        if not ("hinata suzuki" in content or "suzuki hinata" in content or "鈴木陽向" in content_raw or "鈴木 陽向" in content_raw or "陽向" in content_raw):
            return False
            
    elif "yuito suzuki" in p_low:
        if any(k in content_raw for k in ["彩艶", "Zion", "誠也", "Seiya", "陽向", "Hinata", "Cubs", "Aston Villa", "GK"]):
            if "唯人" not in content_raw and "yuito" not in content:
                return False
        if not ("yuito suzuki" in content or "suzuki yuito" in content or "鈴木唯人" in content_raw or "鈴木 唯人" in content_raw or "唯人" in content_raw):
            return False
            
    elif "zion suzuki" in p_low:
        if any(k in content_raw for k in ["唯人", "Yuito", "誠也", "Seiya", "陽向", "Hinata", "Cubs"]):
            if "彩艶" not in content_raw and "zion" not in content:
                return False
        if not ("zion suzuki" in content or "suzuki zion" in content or "鈴木彩艶" in content_raw or "鈴木 彩艶" in content_raw or "彩艶" in content_raw):
            return False

    elif "seiya suzuki" in p_low:
        if any(k in content_raw for k in ["彩艶", "Zion", "唯人", "Yuito", "陽向", "Hinata", "Aston Villa", "Parma", "GK"]):
            if "誠也" not in content_raw and "seiya" not in content:
                return False
        if not ("seiya suzuki" in content or "suzuki seiya" in content or "鈴木誠也" in content_raw or "鈴木 誠也" in content_raw or "誠也" in content_raw):
            return False

    # 1.2 Nhóm Tanaka:
    elif "yushi tanaka" in p_low:
        if any(k in content_raw for k in ["田中碧", "Ao Tanaka", "田中聡", "Satoshi Tanaka", "Leeds", "EFL", "ブンデス"]):
            if "湧士" not in content_raw and "yushi" not in content:
                return False
        if not ("yushi tanaka" in content or "tanaka yushi" in content or "田中湧士" in content_raw or "田中 湧士" in content_raw or "湧士" in content_raw):
            return False

    elif "ao tanaka" in p_low:
        if any(k in content_raw for k in ["湧士", "Yushi", "田中聡", "Satoshi Tanaka", "バドミントン", "badminton"]):
            if "田中碧" not in content_raw and "ao tanaka" not in content and "碧" not in content_raw:
                return False

    # 1.3 Nhóm Ito:
    elif "mima ito" in p_low:
        if any(k in content_raw for k in ["洋輝", "Hiroki", "バイエルン", "Bayern", "ブンデス", "シュトゥットガルト"]):
            if "美誠" not in content_raw and "mima" not in content:
                return False
        if not ("mima ito" in content or "ito mima" in content or "伊藤美誠" in content_raw or "伊藤 美誠" in content_raw or "美誠" in content_raw):
            return False

    elif "hiroki ito" in p_low:
        if any(k in content_raw for k in ["美誠", "Mima", "卓球", "table tennis", "WTT"]):
            if "洋輝" not in content_raw and "hiroki" not in content:
                return False
        if not ("hiroki ito" in content or "ito hiroki" in content or "伊藤洋輝" in content_raw or "伊藤 洋輝" in content_raw or "洋輝" in content_raw):
            return False

    # 1.4 Nhóm Harimoto:
    elif "miwa harimoto" in p_low:
        if "張本智和" in content_raw and "美和" not in content_raw and "miwa" not in content:
            return False
        if not ("miwa harimoto" in content or "harimoto miwa" in content or "張本美和" in content_raw or "張本 美和" in content_raw or "美和" in content_raw):
            return False

    elif "tomokazu harimoto" in p_low:
        if "張本美和" in content_raw and "智和" not in content_raw and "tomokazu" not in content:
            return False

    # 2. General Verification: Bài báo phải có ít nhất 1 tên đầy đủ hợp lệ
    required_matches = [player_name.lower()]
    p_parts = player_name.split()
    if len(p_parts) == 2:
        required_matches.append(f"{p_parts[1]} {p_parts[0]}".lower())
    for nn in native_names:
        required_matches.append(nn.lower())
        
    has_name_match = any(m in content for m in required_matches)
    return has_name_match

def fetch_player_news_entries(player_name: str, aliases: str = "", country_name: str = "", sport_name: str = "") -> list:
    nat = (country_name or "").strip()
    p_lower = (player_name or "").lower().strip()

    # 1. Clean aliases and filter out irrelevant foreign scripts & single isolated surnames
    clean_aliases = []
    if aliases:
        for a in aliases.split(","):
            a_clean = a.strip()
            if not a_clean or "(" in a_clean or ")" in a_clean or len(a_clean) < 2:
                continue
            if a_clean.lower() in CLUB_BLACKLIST or a_clean in COMMON_BAD_SURNAMES or a_clean.lower() in COMMON_BAD_SURNAMES:
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
        if k == p_lower or (len(k) >= 5 and (k in p_lower or p_lower in k)):
            for item in v:
                if item not in native_names and item not in COMMON_BAD_SURNAMES:
                    native_names.append(item)

    for a in clean_aliases:
        if nat == "Nhật Bản":
            pure_jp = re.findall(r'[\u4e00-\u9fff\u3040-\u30ff\s]{2,}', a)
            for pj in pure_jp:
                pj_clean = pj.strip()
                if pj_clean and pj_clean not in COMMON_BAD_SURNAMES and pj_clean not in native_names and len(pj_clean) >= 3:
                    native_names.append(pj_clean)
            if any('\u4e00' <= c <= '\u9fff' or '\u3040' <= c <= '\u30ff' for c in a):
                if a not in native_names and a not in COMMON_BAD_SURNAMES and not any(k in a.lower() for k in ["born", "japanese:", "kanji:"]):
                    if len(a.replace(" ", "")) >= 3:
                        native_names.append(a)
        elif nat == "Hàn Quốc":
            pure_kr = re.findall(r'[\uac00-\ud7af]{2,4}', a)
            for pk in pure_kr:
                if pk not in native_names and pk not in COMMON_BAD_SURNAMES:
                    native_names.append(pk)
            if any('\uac00' <= c <= '\ud7af' for c in a):
                if a not in native_names and a not in COMMON_BAD_SURNAMES and not any(k in a.lower() for k in ["born", "korean:", "hanja:"]):
                    native_names.append(a)
        elif a.lower() != player_name.lower() and a.lower() not in COMMON_BAD_SURNAMES:
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
    seen_titles = set()

    for reg in regions:
        # For native language regions (Japan, Korea), query directly with the native name (e.g. 久保建英 or 손흥민)
        # to unlock all Japanese/Korean news outlets (Yahoo Japan, Nikkan, Naver, etc.)
        if reg["code"] in ["JP", "KR"] and native_names:
            native_parts = [f'"{nn}"' for nn in native_names[:2]]
            target_q = " OR ".join(native_parts)
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
            norm_t = normalize_news_title(title)
            if not title or not link or link in seen_links or (norm_t and norm_t in seen_titles):
                continue

            # Kiểm tra nghiêm ngặt bài báo: đúng VĐV đó, loại bỏ 100% người khác trùng họ (như Hinata vs Zion/Yuito/Seiya Suzuki)
            if not is_article_strictly_for_player(title, summary, player_name, native_names, sport_name=sport_name):
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
            if norm_t:
                seen_titles.add(norm_t)
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

def scan_player_news(db: Session, player_id: int, player_name: str, sport_name: str = ""):
    player = db.query(Player).filter(Player.id == player_id).first()
    if not player:
        return

    nat = (player.country_name or "").strip()
    s_name = sport_name or (player.sport_name if player.sport else "")
    entries = fetch_player_news_entries(player_name, player.name_aliases or "", nat, sport_name=s_name)

    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    # Dọn dẹp tin tức cũ hơn 30 ngày trong database để bảo tồn khung tin cho các trận gần đây
    cutoff_retention = now_utc - datetime.timedelta(days=30)
    db.query(PlayerNews).filter(
        PlayerNews.player_id == player_id,
        PlayerNews.published_at < cutoff_retention
    ).delete()

    existing_news = db.query(PlayerNews).filter(PlayerNews.player_id == player_id).all()
    existing_map = {n.source_url: n for n in existing_news}
    existing_titles = {normalize_news_title(n.title): n for n in existing_news if n.title}

    for item in entries:
        norm_t = normalize_news_title(item["title"])
        if item["source_url"] in existing_map:
            existing_map[item["source_url"]].news_type = item["news_type"]
            continue
        if norm_t and norm_t in existing_titles:
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
        existing_map[item["source_url"]] = news_item
        if norm_t:
            existing_titles[norm_t] = news_item
    db.commit()

