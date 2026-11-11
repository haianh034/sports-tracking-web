import re
import time
import threading
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

def _is_cjk_char(c: str) -> bool:
    return ('\u4e00' <= c <= '\u9fff') or ('\u3040' <= c <= '\u30ff')

def _is_hangul_char(c: str) -> bool:
    return '\uac00' <= c <= '\ud7af'

def _is_isolated_subtoken(token: str, full_player_name: str, all_aliases: list = None) -> bool:
    """
    Tự động phát hiện và loại bỏ họ/tên đơn lẻ hoặc bị cắt cụt (ví dụ 'Suzuki', '鈴木', '김')
    dựa trên cấu trúc ngôn ngữ và đối chiếu với tên đầy đủ mà không cần danh sách khóa cứng.
    """
    t = (token or "").strip()
    if not t or len(t) < 2:
        return True

    t_low = t.lower()
    p_parts = [w for w in (full_player_name or "").strip().split() if w.strip()]

    # 1. Nếu là tên Latin (ASCII): VĐV có >= 2 từ thì tuyệt đối không chấp nhận token chỉ gồm 1 từ đơn
    if t.isascii():
        if len(p_parts) >= 2 and len(t.split()) < 2:
            return True
        return False

    # 2. Nếu là chữ Hán/Nhật (CJK):
    has_cjk = any(_is_cjk_char(c) for c in t)
    if has_cjk:
        cjk_no_space = t.replace(" ", "")
        # Kiểm tra xem token ngắn (<= 2 chữ CJK) có phải là phần bị cắt của tên CJK đầy đủ (>= 3 chữ) trong aliases không
        if len(cjk_no_space) <= 2:
            if len(p_parts) >= 2:
                return True
            for other in (all_aliases or []):
                o_clean = (other or "").strip().replace(" ", "")
                if len(o_clean) >= 3 and cjk_no_space in o_clean and o_clean != cjk_no_space:
                    return True
        return False

    # 3. Nếu là chữ Hàn (Hangul): họ đơn lẻ thường 1 âm tiết, tên đầy đủ thường >= 3 âm tiết
    has_kr = any(_is_hangul_char(c) for c in t)
    if has_kr:
        kr_no_space = t.replace(" ", "")
        if len(kr_no_space) < 3:
            for other in (all_aliases or []):
                o_clean = (other or "").strip().replace(" ", "")
                if len(o_clean) >= 3 and kr_no_space in o_clean and o_clean != kr_no_space:
                    return True
            if len(kr_no_space) == 1:
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
        if _is_isolated_subtoken(clean, player_name, raw_names):
            continue
        valid_tokens.add(clean)
        
        unspaced = clean.replace(" ", "")
        if unspaced != clean and not _is_isolated_subtoken(unspaced, player_name, raw_names):
            valid_tokens.add(unspaced)

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

_SIBLINGS_CACHE = {"ts": 0.0, "players": []}
_SIBLINGS_CACHE_LOCK = threading.Lock()

SPORT_EXCLUSIVE_PROFILES = {
    "Bóng đá": {
        "サッカー", "jリーグ", "j1", "j2", "premier league", "bundesliga", "la liga",
        "serie a", "ligue 1", "eredivisie", "champions league", "europa league",
        "uefa", "fifa", "gk", "サカノワ", "ゲキサカ", "축구", "k리그", "프리미어리그", "bóng đá"
    },
    "Cầu lông": {
        "バドミントン", "badminton", "bwf", "world tour", "shuttlecock",
        "シングルス", "ダブルス", "ミックスダブルス", "배드민턴", "cầu lông"
    },
    "Bóng bàn": {
        "卓球", "table tennis", "wtt", "ittf", "ping pong", "tリーグ", "탁구", "bóng bàn"
    },
    "Bóng chày": {
        "野球", "プロ野球", "mlb", "npb", "kbo", "home run", "本塁打",
        "ホームラン", "投手", "打率", "カブス", "ドジャース", "야구", "메이저리그", "bóng chày"
    },
    "Bóng rổ": {
        "バスケ", "バスケットボール", "basketball", "nba", "bリーグ", "b.league",
        "fiba", "three-pointer", "ダンク", "농구", "kbl", "bóng rổ"
    },
    "Bóng chuyền": {
        "バレー", "バレーボール", "volleyball", "svリーグ", "vリーグ", "vnl", "배구", "bóng chuyền"
    },
    "Quần vợt": {
        "テニス", "tennis", "atpツアー", "wtaツアー", "wimbledon", "ウィンブルドン",
        "全豪オープン", "全仏オープン", "全米オープン", "테니스", "quần vợt"
    },
    "Golf": {
        "ゴルフ", "golf", "jlpga", "lpga", "pgaツアー", "birdie", "골프"
    }
}

def _extract_surname_and_given(player_name: str, native_names: list = None):
    """
    Trích xuất tự động Họ (surname) và Tên riêng (given name) từ cả tên Latin và tên bản địa (CJK/Hangul)
    để nhận diện và phân tách mọi VĐV trùng họ trong hệ thống.
    """
    p_clean = (player_name or "").strip()
    parts = [re.sub(r'[^a-z0-9\-]', '', w.lower()) for w in p_clean.split() if w.strip()]

    latin_surnames = set()
    latin_givens = set()
    COMMON_KOREAN_FIRST_SURNAMES = {
        "kim", "lee", "park", "choi", "jung", "jeong", "kang", "cho", "yoon",
        "jang", "lim", "han", "oh", "seo", "shin", "kwon", "hwang", "ahn",
        "song", "jeon", "hong", "bae", "seol", "yang", "paik", "eom"
    }
    if len(parts) >= 2:
        if "-" in parts[-1] or (len(parts) == 2 and parts[0] in COMMON_KOREAN_FIRST_SURNAMES):
            latin_surnames.add(parts[0])
            latin_givens.add(parts[-1])
        else:
            latin_surnames.add(parts[-1])
            latin_givens.add(parts[0])
            if len(parts) > 2:
                latin_givens.add(" ".join(parts[:-1]))

    native_surnames = set()
    native_givens = set()
    for nn in (native_names or []):
        nn_clean = (nn or "").strip()
        if " " in nn_clean:
            n_parts = [x.strip() for x in nn_clean.split() if x.strip()]
            if len(n_parts) == 2:
                native_surnames.add(n_parts[0])
                if len(n_parts[1]) >= 2:
                    native_givens.add(n_parts[1])
        else:
            if any(_is_cjk_char(c) for c in nn_clean) and len(nn_clean) >= 3:
                if len(nn_clean) >= 4:
                    native_surnames.add(nn_clean[:2])
                    native_givens.add(nn_clean[2:])
                elif len(nn_clean) == 3:
                    native_surnames.add(nn_clean[:2])
                    native_surnames.add(nn_clean[:1])
                    if len(nn_clean[1:]) >= 2:
                        native_givens.add(nn_clean[1:])
            elif any(_is_hangul_char(c) for c in nn_clean) and len(nn_clean) >= 3:
                native_surnames.add(nn_clean[0])
                if len(nn_clean[1:]) >= 2:
                    native_givens.add(nn_clean[1:])

    return latin_surnames, latin_givens, native_surnames, native_givens

def _get_all_players_profile_map(db: Session = None) -> list:
    """
    Tự động tổng hợp hồ sơ họ-tên của toàn bộ VĐV có trong Database (cache 5 phút)
    để đối chiếu chéo tự động giữa các VĐV cùng họ mà không cần khóa cứng bất kỳ cái tên nào.
    """
    global _SIBLINGS_CACHE
    now_t = time.time()
    with _SIBLINGS_CACHE_LOCK:
        if _SIBLINGS_CACHE["players"] and (now_t - _SIBLINGS_CACHE["ts"] < 300):
            return _SIBLINGS_CACHE["players"]

    close_after = False
    session = db
    if session is None:
        try:
            from backend.core.db.session import SessionLocal
            session = SessionLocal()
            close_after = True
        except Exception:
            return _SIBLINGS_CACHE.get("players", [])

    try:
        rows = session.query(Player).all()
        snapshot = []
        for r in rows:
            p_n = (r.name or "").strip()
            s_n = (r.sport_name or "").strip()
            al = (r.name_aliases or "").strip()
            nat_list = list(PLAYER_NATIVE_NAMES.get(p_n.lower(), []))
            raw_list = [x.strip() for x in al.split(",") if x.strip()] if al else []
            for ac in raw_list:
                if not _is_isolated_subtoken(ac, p_n, raw_list + nat_list) and ac not in nat_list:
                    if any(_is_cjk_char(c) or _is_hangul_char(c) for c in ac):
                        nat_list.append(ac)
            lat_sur, lat_giv, nat_sur, nat_giv = _extract_surname_and_given(p_n, nat_list)
            snapshot.append({
                "name": p_n,
                "name_lower": p_n.lower(),
                "sport": s_n,
                "native_names": nat_list,
                "latin_surnames": lat_sur,
                "latin_givens": lat_giv,
                "native_surnames": nat_sur,
                "native_givens": nat_giv
            })
        with _SIBLINGS_CACHE_LOCK:
            _SIBLINGS_CACHE = {"ts": time.time(), "players": snapshot}
        return snapshot
    except Exception:
        return _SIBLINGS_CACHE.get("players", [])
    finally:
        if close_after and session:
            session.close()

def is_article_strictly_for_player(
    title: str,
    summary: str,
    player_name: str,
    native_names: list,
    sport_name: str = "",
    db: Session = None
) -> bool:
    """
    Bộ lọc bài báo 4 lớp hoàn toàn tự động (Zero-Hardcode):
    - Lớp 1 & 2: Yêu cầu khớp ít nhất 1 biến thể Tên Đầy Đủ (cấm hoàn toàn họ đơn lẻ).
    - Lớp 3: Loại trừ xung đột Môn Thể thao tự động (Cross-Sport Conflict Guard).
    - Lớp 4: Loại trừ chéo tự động với bất kỳ VĐV nào trùng họ trong DB.
    """
    clean_summary = re.sub(r'<[^>]+>', ' ', summary or "")
    content_raw = f"{title} {clean_summary}"
    content = content_raw.lower()
    p_low = (player_name or "").lower().strip()

    my_lat_sur, my_lat_giv, my_nat_sur, my_nat_giv = _extract_surname_and_given(player_name, native_names)

    # Xây dựng tập biến thể Tên Đầy Đủ bắt buộc
    required_full_names = {p_low}
    p_parts = player_name.split()
    if len(p_parts) == 2:
        required_full_names.add(f"{p_parts[1]} {p_parts[0]}".lower())
    for nn in (native_names or []):
        nn_clean = (nn or "").strip()
        if not _is_isolated_subtoken(nn_clean, player_name, native_names):
            required_full_names.add(nn_clean.lower())
            unspaced = nn_clean.replace(" ", "")
            if len(unspaced) >= 3:
                required_full_names.add(unspaced.lower())

    # LỚP 4: Loại trừ chéo tự động với các VĐV khác cùng họ đang có trong Database
    all_profiles = _get_all_players_profile_map(db=db)
    has_my_given = any(
        (re.search(r'\b' + re.escape(g) + r'\b', content) if g.isascii() else (g in content_raw))
        for g in (my_lat_giv | my_nat_giv) if len(g) >= 2
    )
    for prof in all_profiles:
        if prof["name_lower"] == p_low:
            continue
        shares_surname = bool(my_lat_sur & prof["latin_surnames"]) or bool(my_nat_sur & prof["native_surnames"])
        if not shares_surname:
            continue

        mentions_sibling_full = (
            prof["name_lower"] in content
            or any(nn.lower() in content for nn in prof["native_names"] if len(nn.replace(" ", "")) >= 3)
        )
        mentions_sibling_given = any(
            (re.search(r'\b' + re.escape(g) + r'\b', content) if g.isascii() else (g in content_raw))
            for g in (prof["latin_givens"] | prof["native_givens"]) if len(g) >= 2
        )
        if (mentions_sibling_full or mentions_sibling_given) and not has_my_given:
            return False

    # LỚP 2: Bắt buộc bài báo phải chứa ít nhất 1 Tên Đầy Đủ của VĐV mục tiêu (có word-boundary cho Latin)
    has_full_name_match = False
    for req_name in required_full_names:
        if not req_name:
            continue
        if req_name.isascii():
            if re.search(r'\b' + re.escape(req_name) + r'\b', content):
                has_full_name_match = True
                break
        else:
            if req_name in content:
                has_full_name_match = True
                break

    if not has_full_name_match:
        return False

    # LỚP 3: Kiểm tra xung đột Môn Thể thao Tự động (Cross-Sport Conflict Guard)
    if sport_name and sport_name in SPORT_EXCLUSIVE_PROFILES:
        my_sport_kws = SPORT_EXCLUSIVE_PROFILES[sport_name]
        has_my_sport_kw = _matches_any_keyword(content, list(my_sport_kws))
        if not has_my_sport_kw:
            for other_sport, other_kws in SPORT_EXCLUSIVE_PROFILES.items():
                if other_sport == sport_name:
                    continue
                if _matches_any_keyword(content, list(other_kws)):
                    title_low = (title or "").lower()
                    in_title = any(
                        (re.search(r'\b' + re.escape(rn) + r'\b', title_low) if rn.isascii() else (rn in title_low))
                        for rn in required_full_names if rn
                    )
                    if not in_title:
                        return False

    return True

def fetch_player_news_entries(
    player_name: str,
    aliases: str = "",
    country_name: str = "",
    sport_name: str = "",
    db: Session = None
) -> list:
    nat = (country_name or "").strip()
    p_lower = (player_name or "").lower().strip()

    # Tự động tổng hợp tất cả biến thể tên đầy đủ để làm đối chiếu khi lọc bỏ các họ cộc
    known_native = list(PLAYER_NATIVE_NAMES.get(p_lower, []))
    raw_aliases_list = [a.strip() for a in (aliases or "").split(",") if a.strip()]
    all_candidate_names = [player_name] + known_native + raw_aliases_list

    # 1. Lọc bỏ các token bị cắt cụt / họ đứng đơn lẻ bằng bộ phân tích cấu trúc tự động
    clean_aliases = []
    for a_clean in raw_aliases_list:
        if not a_clean or "(" in a_clean or ")" in a_clean or len(a_clean) < 2:
            continue
        if a_clean.lower() in CLUB_BLACKLIST:
            continue
        if _is_isolated_subtoken(a_clean, player_name, all_candidate_names):
            continue
        if nat == "Nhật Bản":
            if not any(_is_cjk_char(c) or c.isascii() for c in a_clean):
                continue
        elif nat == "Hàn Quốc":
            if not any(_is_hangul_char(c) or c.isascii() for c in a_clean):
                continue
        clean_aliases.append(a_clean)

    # 2. Search terms: prioritize English name and full native script
    search_terms = [player_name]
    native_names = []
    latin_aliases = []

    for k, v in PLAYER_NATIVE_NAMES.items():
        if k == p_lower or (len(k) >= 5 and (k in p_lower or p_lower in k)):
            for item in v:
                if item not in native_names and not _is_isolated_subtoken(item, player_name, all_candidate_names):
                    native_names.append(item)

    for a in clean_aliases:
        if nat == "Nhật Bản":
            pure_jp = re.findall(r'[\u4e00-\u9fff\u3040-\u30ff\s]{2,}', a)
            for pj in pure_jp:
                pj_clean = pj.strip()
                if pj_clean and pj_clean not in native_names and not _is_isolated_subtoken(pj_clean, player_name, all_candidate_names):
                    native_names.append(pj_clean)
            if any(_is_cjk_char(c) for c in a):
                if a not in native_names and not any(k in a.lower() for k in ["born", "japanese:", "kanji:"]):
                    if not _is_isolated_subtoken(a, player_name, all_candidate_names):
                        native_names.append(a)
        elif nat == "Hàn Quốc":
            pure_kr = re.findall(r'[\uac00-\ud7af]{2,4}', a)
            for pk in pure_kr:
                if pk not in native_names and not _is_isolated_subtoken(pk, player_name, all_candidate_names):
                    native_names.append(pk)
            if any(_is_hangul_char(c) for c in a):
                if a not in native_names and not any(k in a.lower() for k in ["born", "korean:", "hanja:"]):
                    if not _is_isolated_subtoken(a, player_name, all_candidate_names):
                        native_names.append(a)
        elif a.lower() != player_name.lower() and not _is_isolated_subtoken(a, player_name, all_candidate_names):
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

            # Kiểm tra nghiêm ngặt bài báo: tự động đối chiếu Tên Đầy Đủ, Xung đột Môn & VĐV trùng họ trong DB
            if not is_article_strictly_for_player(title, summary, player_name, native_names, sport_name=sport_name, db=db):
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
    entries = fetch_player_news_entries(player_name, player.name_aliases or "", nat, sport_name=s_name, db=db)

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

