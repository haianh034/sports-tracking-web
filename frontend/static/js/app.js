const REGION_FLAGS = {
    'US': { flag: '🇺🇸', label: 'Báo Quốc Tế (US)' },
    'JP': { flag: '🇯🇵', label: 'Báo Nhật Bản (JP)' },
    'KR': { flag: '🇰🇷', label: 'Báo Hàn Quốc (KR)' },
    'FR': { flag: '🇫🇷', label: 'Báo Pháp (FR)' },
    'ES': { flag: '🇪🇸', label: 'Báo Tây Ban Nha (ES)' },
    'GB': { flag: '🇬🇧', label: 'Báo Anh (GB)' },
    'DE': { flag: '🇩🇪', label: 'Báo Đức (DE)' },
    'IT': { flag: '🇮🇹', label: 'Báo Ý (IT)' },
    'BR': { flag: '🇧🇷', label: 'Báo Brazil (BR)' },
    'AR': { flag: '🇦🇷', label: 'Báo Argentina (AR)' },
    'PT': { flag: '🇵🇹', label: 'Báo Bồ Đào Nha (PT)' },
    'VN': { flag: '🇻🇳', label: 'Báo Việt Nam (VN)' }
};

window.activePlayersMap = {};

const NEWS_CATEGORIES = {
    match: { label: 'Thi đấu', icon: '⚽', color: 'bg-emerald-950/80 text-emerald-300 border-emerald-800/80' },
    transfer: { label: 'Chuyển nhượng', icon: '🔄', color: 'bg-rose-950/80 text-rose-300 border-rose-800/80' },
    transfer_rumor: { label: 'Chuyển nhượng', icon: '🔄', color: 'bg-rose-950/80 text-rose-300 border-rose-800/80' },
    statement: { label: 'Phát biểu', icon: '🎙️', color: 'bg-purple-950/80 text-purple-300 border-purple-800/80' },
    analysis: { label: 'Chuyên môn', icon: '📊', color: 'bg-blue-950/80 text-blue-300 border-blue-800/80' },
    side_news: { label: 'Bên lề', icon: '📰', color: 'bg-gray-800/80 text-gray-300 border-gray-700/80' }
};

let selectedNewsCategories = new Set(); // Rỗng = "Tất cả"

function renderCardNewsBadges(p, customNewsList = null) {
    const newsList = customNewsList !== null ? customNewsList : ((p.details && p.details.news) ? p.details.news : []);
    const count = newsList.length;
    if (count === 0) {
        return '<span class="text-xs text-gray-500">Chưa có tin mới</span>';
    }
    return `
        <span class="text-xs text-amber-300/90 font-medium flex items-center gap-1 bg-amber-950/40 border border-amber-800/40 px-2 py-0.5 rounded-md" title="Tin tức tổng hợp xoay quanh trận đấu">
            📰 ${count} tin
        </span>
    `;
}

function formatMatchTimezones(utcDateStr, targetTz, flagStr) {
    if (!utcDateStr) return { vnTime: 'N/A', localTime: 'N/A', tzLabel: 'Giờ bản địa', countryFlag: flagStr || '📍' };
    const d = new Date(utcDateStr);
    if (isNaN(d.getTime())) return { vnTime: 'N/A', localTime: 'N/A', tzLabel: 'Giờ bản địa', countryFlag: flagStr || '📍' };

    const vnTime = new Intl.DateTimeFormat('vi-VN', {
        timeZone: 'Asia/Ho_Chi_Minh',
        hour: '2-digit', minute: '2-digit',
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour12: false
    }).format(d);

    let tzLabel = `Giờ ${targetTz.split('/').pop().replace('_', ' ')}`;
    let countryFlag = flagStr || '📍';
    
    let localTime = 'N/A';
    try {
        localTime = new Intl.DateTimeFormat('vi-VN', {
            timeZone: targetTz,
            hour: '2-digit', minute: '2-digit',
            day: '2-digit', month: '2-digit', year: 'numeric',
            hour12: false
        }).format(d);
    } catch(e) {
        localTime = vnTime;
    }

    return { vnTime, localTime, tzLabel, countryFlag };
}

let currentActiveTab = 'active';

function switchTab(tab) {
    currentActiveTab = tab;
    
    // Clear date filter results panel
    const dateResults = document.getElementById('dateFilteredResultsPanel');
    if (dateResults && !dateResults.classList.contains('hidden')) {
        dateResults.classList.add('hidden');
    }
    const badgeLabel = document.getElementById('activeDateBadgeLabel');

    if (tab === 'active') {
        // When clicking Today's Activities, date filter jumps directly to Today
        const todayStr = getTodayVNDateStr();
        const todayParts = todayStr.split('-');
        const todayYear = parseInt(todayParts[0], 10) || 2026;

        selectedCalendarDate = todayStr;
        if (selectedCalendarYear !== todayYear) {
            selectedCalendarYear = todayYear;
            renderCalendarTimeline();
        }

        const picker = document.getElementById('topDatePicker');
        if (picker) picker.value = todayStr;
        const displayInput = document.getElementById('topDatePickerDisplay');
        if (displayInput) displayInput.value = `${todayParts[2]}/${todayParts[1]}/${todayParts[0]}`;
        const yearSelect = document.getElementById('calendarYearSelect');
        if (yearSelect) yearSelect.value = String(todayYear);

        if (badgeLabel) {
            badgeLabel.innerText = `Hôm nay: ${todayParts[2]}/${todayParts[1]}/${todayParts[0]}`;
            badgeLabel.classList.remove('hidden');
        }

        const container = document.getElementById('topDateStripContainer');
        if (container) {
            container.querySelectorAll('button').forEach(btn => {
                const btnDate = btn.getAttribute('data-date');
                const isToday = (btnDate === todayStr);
                btn.className = isToday 
                    ? "shrink-0 flex flex-col items-center justify-center min-w-[58px] sm:min-w-[62px] p-2 rounded-xl border text-center transition-all cursor-pointer border-emerald-500 bg-emerald-950/80 ring-2 ring-emerald-500/50 shadow-md shadow-emerald-500/20"
                    : "shrink-0 flex flex-col items-center justify-center min-w-[58px] sm:min-w-[62px] p-2 rounded-xl border text-center transition-all cursor-pointer border-gray-800 bg-gray-900/60 hover:border-gray-700 hover:bg-gray-800/80";
            });
            const activeBtn = document.getElementById(`topDateBtn_${todayStr}`);
            if (activeBtn) {
                activeBtn.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
            }
        }
    } else {
        if (badgeLabel) badgeLabel.classList.add('hidden');
        selectedCalendarDate = null;
        const picker = document.getElementById('topDatePicker');
        if (picker) picker.value = '';
        const displayInput = document.getElementById('topDatePickerDisplay');
        if (displayInput) displayInput.value = '';

        const container = document.getElementById('topDateStripContainer');
        if (container) {
            container.querySelectorAll('button').forEach(btn => {
                const isToday = btn.getAttribute('data-today') === 'true';
                btn.className = isToday 
                    ? "shrink-0 flex flex-col items-center justify-center min-w-[58px] sm:min-w-[62px] p-2 rounded-xl border text-center transition-all cursor-pointer border-emerald-500/80 bg-gray-900/90 hover:bg-gray-800" 
                    : "shrink-0 flex flex-col items-center justify-center min-w-[58px] sm:min-w-[62px] p-2 rounded-xl border text-center transition-all cursor-pointer border-gray-800 bg-gray-900/60 hover:border-gray-700 hover:bg-gray-800/80";
            });
        }
    }

    const activeTabBtn = document.getElementById('tabActiveBtn');
    const upcomingTabBtn = document.getElementById('tabUpcomingBtn');
    const noMatchTabBtn = document.getElementById('tabNoMatchBtn');
    const scheduleTabBtn = document.getElementById('tabScheduleBtn');

    const activePanel = document.getElementById('activeTabPanel');
    const upcomingPanel = document.getElementById('upcomingTabPanel');
    const noMatchPanel = document.getElementById('noMatchTabPanel');
    const schedulePanel = document.getElementById('scheduleTabPanel');

    const activeClass = "tab-btn py-3 px-1 border-b-2 font-semibold text-sm flex items-center gap-2 border-blue-500 text-blue-400 transition-colors duration-150";
    const inactiveClass = "tab-btn py-3 px-1 border-b-2 font-semibold text-sm flex items-center gap-2 border-transparent text-gray-400 hover:text-gray-200 hover:border-gray-700 transition-colors duration-150";

    if (activeTabBtn) activeTabBtn.className = tab === 'active' ? activeClass : inactiveClass;
    if (upcomingTabBtn) upcomingTabBtn.className = tab === 'upcoming' ? activeClass : inactiveClass;
    if (noMatchTabBtn) noMatchTabBtn.className = tab === 'no_match' ? activeClass : inactiveClass;
    if (scheduleTabBtn) scheduleTabBtn.className = tab === 'schedule' ? activeClass : inactiveClass;

    [activePanel, upcomingPanel, noMatchPanel, schedulePanel].forEach(p => {
        if (p) p.classList.add('hidden');
    });

    if (tab === 'active' && activePanel) activePanel.classList.remove('hidden');
    else if (tab === 'upcoming' && upcomingPanel) upcomingPanel.classList.remove('hidden');
    else if (tab === 'no_match' && noMatchPanel) noMatchPanel.classList.remove('hidden');
    else if (tab === 'schedule' && schedulePanel) schedulePanel.classList.remove('hidden');
}

function isSameTeamName(teamA, teamB) {
    if (!teamA || !teamB) return false;
    const a = String(teamA).toLowerCase().trim();
    const b = String(teamB).toLowerCase().trim();
    if (a === b) return true;

    const aliases = [
        ['los angeles clippers', 'la clippers', 'clippers'],
        ['los angeles lakers', 'la lakers', 'lakers'],
        ['los angeles fc', 'lafc', 'la fc', 'los angeles football club'],
        ['los angeles galaxy', 'la galaxy', 'galaxy'],
        ['manchester united', 'man utd', 'man united'],
        ['manchester city', 'man city'],
        ['ac milan', 'milan'],
        ['internazionale', 'inter milan', 'inter'],
        ['real madrid', 'real'],
        ['atletico madrid', 'atlético madrid', 'atletico'],
        ['bayern munich', 'bayern münchen', 'bayern', 'fc bayern'],
        ['schalke 04', 'schalke', 'fc schalke 04', 's04'],
        ['real sociedad', 'sociedad', 'la real'],
        ['brighton & hove albion', 'brighton and hove albion', 'brighton'],
        ['aston villa', 'villa', 'avfc'],
        ['eintracht frankfurt', 'frankfurt', 'sge'],
        ['mainz 05', 'fsv mainz', 'mainz'],
        ['beşiktaş', 'besiktas', 'bjk'],
        ['chicago white sox', 'white sox', 'chisox'],
        ['chicago cubs', 'cubs'],
        ['boston red sox', 'red sox'],
        ['los angeles dodgers', 'la dodgers', 'dodgers'],
        ['toronto blue jays', 'blue jays', 'jays']
    ];
    for (const group of aliases) {
        if (group.some(x => a.includes(x)) && group.some(x => b.includes(x))) return true;
    }
    const cityPairs = [
        [['clippers'], ['lakers']],
        [['lafc', 'los angeles fc'], ['la galaxy', 'galaxy']],
        [['city', 'manchester city'], ['united', 'manchester united']],
        [['ac milan'], ['inter']],
        [['real'], ['atletico']],
        [['white sox'], ['cubs']]
    ];
    for (const [g1, g2] of cityPairs) {
        if ((g1.some(x => a.includes(x)) && g2.some(x => b.includes(x))) ||
            (g2.some(x => a.includes(x)) && g1.some(x => b.includes(x)))) {
            return false;
        }
    }
    const stopWords = ['fc', 'cf', 'sc', 'the', 'de', 'la', 'los', 'san', 'st', 'angeles', 'city', 'york', 'town', 'club', 'united', 'real', 'madrid', 'milan'];
    const wA = a.replace(/[^a-z0-9\s]/g, '').split(/\s+/).filter(w => !stopWords.includes(w));
    const wB = b.replace(/[^a-z0-9\s]/g, '').split(/\s+/).filter(w => !stopWords.includes(w));
    return wA.some(w => w.length >= 4 && wB.includes(w));
}

function getOpponentName(matchName, playerTeam) {
    if (!matchName) return 'Chưa rõ đối thủ';
    let raw = matchName.trim();
    if (raw.startsWith('@ ') || raw.startsWith('vs ') || raw.startsWith('vs. ')) {
        const prefix = raw.startsWith('@ ') ? '@ ' : 'vs ';
        const opponent = raw.substring(prefix.length).trim();
        if (playerTeam && isSameTeamName(opponent, playerTeam)) {
            return 'Chưa rõ đối thủ';
        }
        return raw;
    }
    let parts = [];
    let isAway = false;
    if (raw.includes(' at ')) {
        parts = raw.split(' at ');
        isAway = true;
    } else if (raw.includes(' vs. ')) {
        parts = raw.split(' vs. ');
    } else if (raw.includes(' vs ')) {
        parts = raw.split(' vs ');
    } else if (raw.includes(' - ')) {
        parts = raw.split(' - ');
    }

    if (parts.length === 2) {
        const p1 = parts[0].trim();
        const p2 = parts[1].trim();
        const p1IsPlayer = playerTeam && isSameTeamName(p1, playerTeam);
        const p2IsPlayer = playerTeam && isSameTeamName(p2, playerTeam);
        
        if (p1IsPlayer && !p2IsPlayer) {
            return isAway ? `@ ${p2}` : `vs ${p2}`;
        } else if (p2IsPlayer && !p1IsPlayer) {
            return isAway ? `vs ${p1}` : `@ ${p1}`;
        } else {
            return isAway ? `@ ${p2}` : `vs ${p2}`;
        }
    }
    return raw.startsWith('@ ') || raw.startsWith('vs ') ? raw : `vs ${raw}`;
}

function renderTagBadge(tag) {
    if (!tag) return '';
    const t = tag.trim();

    let label = t;
    let customTooltip = null;
    if (t.includes('::')) {
        const parts = t.split('::');
        label = parts[0].trim();
        customTooltip = parts[1].trim();
    }

    // Clean simplified tier badge (ĐTQG, U23, U21, U20, U19, U18, U17, Tuyển trẻ) - Bỏ JP/KR thừa
    let cleanTier = label.replace(/^(JP|KR)\s*[-•:]*\s*/i, '').trim();
    if (cleanTier.toLowerCase() === 'senior' || cleanTier.toLowerCase().includes('đội tuyển quốc gia')) {
        cleanTier = 'ĐTQG';
    } else if (cleanTier.toLowerCase().includes('u23')) {
        cleanTier = 'U23';
    } else if (cleanTier.toLowerCase().includes('u20')) {
        cleanTier = 'U20';
    } else if (cleanTier.toLowerCase().includes('u19')) {
        cleanTier = 'U19';
    } else if (cleanTier.toLowerCase().includes('u18')) {
        cleanTier = 'U18';
    } else if (cleanTier.toLowerCase().includes('u17')) {
        cleanTier = 'U17';
    } else if (cleanTier.toLowerCase().includes('u21')) {
        cleanTier = 'U21';
    } else if (cleanTier.toLowerCase().includes('tuyển trẻ') || cleanTier.toLowerCase() === 'youth') {
        cleanTier = 'Tuyển trẻ';
    }

    if (['ĐTQG', 'U23', 'U21', 'U20', 'U19', 'U18', 'U17', 'Tuyển trẻ'].includes(cleanTier)) {
        return '';
    }

    const tLow = label.toLowerCase();

    // 1. Chấn thương (Phân biệt rõ nhẹ vs nặng theo NBA, MLB, Bóng đá với Tooltip chi tiết)
    const isInjury = (
        tLow.includes('chấn thương') || tLow.includes('questionable') || tLow.includes('probable') || 
        tLow.includes('doubtful') || tLow.includes('day-to-day') || tLow.includes('nghi ngờ') ||
        tLow.includes('-day il') || tLow.includes('il10') || tLow.includes('il15') || tLow.includes('il60') || 
        tLow.includes('out for season') || tLow.includes('out') || tLow.includes('treo giò') || 
        tLow.includes('vắng mặt') || tLow.includes('không đăng ký') || tLow.includes('quá tải')
    );

    if (isInjury) {
        let tooltip = customTooltip;
        if (!tooltip) {
            if (tLow.includes('questionable')) tooltip = 'Questionable (50% cơ hội thi đấu): Đang chấn thương nhẹ hoặc đau cơ, cần đánh giá trước giờ bóng lăn';
            else if (tLow.includes('probable')) tooltip = 'Probable (75% cơ hội thi đấu): Chấn thương nhẹ, khả năng cao sẽ thi đấu';
            else if (tLow.includes('doubtful')) tooltip = 'Doubtful (25% cơ hội thi đấu): Chấn thương tiến triển chậm, khả năng ra sân rất thấp';
            else if (tLow.includes('day-to-day')) tooltip = 'Day-To-Day: Chấn thương nhẹ, theo dõi tiến độ hồi phục từng ngày';
            else if (tLow.includes('10-day il') || tLow.includes('il10')) tooltip = '10-Day IL: Danh sách chấn thương 10 ngày (Chấn thương trung bình)';
            else if (tLow.includes('15-day il') || tLow.includes('il15')) tooltip = '15-Day IL: Danh sách chấn thương 15 ngày dành cho Pitcher (MLB)';
            else if (tLow.includes('60-day il') || tLow.includes('il60')) tooltip = '60-Day IL: Danh sách chấn thương 60 ngày (Nghỉ dài hạn)';
            else if (tLow.includes('out for season')) tooltip = 'Out For Season: Chấn thương nghiêm trọng phải phẫu thuật hoặc nghỉ hết mùa giải';
            else if (tLow.includes('out')) tooltip = 'Out: Xác nhận vắng mặt, không thể thi đấu trận này';
            else if (tLow.includes('không đăng ký')) tooltip = 'Không có tên trong danh sách đăng ký thi đấu';
            else if (tLow.includes('treo giò')) tooltip = 'Bị treo giò do án phạt thẻ phạt hoặc kỷ luật';
            else tooltip = 'Tình trạng sức khỏe & chấn thương của vận động viên';
        }

        const isMild = tLow.includes('questionable') || tLow.includes('probable') || tLow.includes('day-to-day') || tLow.includes('đau nhẹ') || tLow.includes('nghi ngờ');
        const colorClass = isMild 
            ? "bg-amber-950/80 text-amber-300 border-amber-700/80 shadow-amber-900/20" 
            : "bg-rose-950/80 text-rose-300 border-rose-800/80 shadow-rose-900/20";
        const icon = isMild ? "⚠️" : "🚨";

        return `<span title="${escapeHtml(tooltip)}" class="inline-flex items-center gap-1 ${colorClass} text-[11px] px-2.5 py-1 rounded-md border font-semibold shadow-sm cursor-help transition-transform hover:scale-105">
            <span>${icon}</span><span>${escapeHtml(label)}</span>
        </span>`;
    }

    // 2. Dự bị, Không vào sân, Quyết định HLV, Nghỉ ngơi (Hổ phách / Amber)
    if (tLow.includes('dự bị') || tLow.includes('xoay tua') || tLow.includes('không vào sân') || tLow.includes('nghỉ ngơi') || tLow.includes('không thi đấu')) {
        return `<span class="inline-flex items-center gap-1 bg-amber-950/60 text-amber-300 text-[11px] px-2.5 py-1 rounded-md border border-amber-800/60 font-medium shadow-sm">
            <span>⏱️</span><span>${escapeHtml(label)}</span>
        </span>`;
    }

    // 3. Highlight / Milestone / Game Winner / Clutch / MVP / Double-Double / Triple-Double / Phá kỷ lục / Volleyball / Badminton Highlights (Vàng kim rực rỡ kèm giải thích)
    if (tLow.includes('game winner') || tLow.includes('clutch') || tLow.includes('kỷ lục') || tLow.includes('mvp') || 
        tLow.includes('double-double') || tLow.includes('triple-double') || tLow.includes('hattrick') || tLow.includes('cú đúp') || 
        tLow.includes('siêu phẩm') || tLow.includes('bàn quyết định') || tLow.includes('grand slam') || tLow.includes('mưa 3') || 
        tLow.includes('monster block') || tLow.includes('ace') || tLow.includes('top ghi điểm') || tLow.includes('hiệu suất tấn công') ||
        tLow.includes('lội ngược dòng') || tLow.includes('match-point') || tLow.includes('tấn công áp đảo') ||
        tLow.includes('30+') || tLow.includes('40+') || tLow.includes('nghẹt thở')) {
        let icon = '🔥';
        let tooltip = customTooltip || 'Thành tích nổi bật trong trận đấu';
        if (tLow.includes('game winner') || tLow.includes('bàn quyết định')) {
            icon = '🎯';
            tooltip = 'Pha bóng / bàn thắng định đoạt trận đấu (Game Winner / Clutch)';
        } else if (tLow.includes('kỷ lục')) {
            icon = '📜';
            tooltip = 'Kỷ lục thi đấu: Cột mốc hoặc kỷ lục thành tích mới trong sự nghiệp (Career-High / Record-Breaking)';
        } else if (tLow.includes('mvp')) {
            icon = '⭐';
            tooltip = 'Cầu thủ xuất sắc nhất trận đấu (MVP)';
        } else if (tLow.includes('monster block')) {
            icon = '🧱';
            tooltip = 'Pha chắn bóng đơn điểm ghi điểm trực tiếp ngoạn mục (Monster Block)';
        } else if (tLow.includes('ace')) {
            icon = '⚡';
            tooltip = 'Phát bóng ghi điểm trực tiếp (Ace Service)';
        } else if (tLow.includes('top ghi điểm')) {
            icon = '👑';
            tooltip = 'Vận động viên ghi nhiều điểm nhất toàn trận đấu';
        } else if (tLow.includes('lội ngược dòng')) {
            icon = '🌪️';
            tooltip = 'Lội ngược dòng ngoạn mục sau khi bị dẫn trước';
        } else if (tLow.includes('clutch')) {
            icon = '🏹';
            tooltip = 'Thể hiện bản lĩnh ghi điểm ở thời khắc nghẹt thở cuối trận';
        }
        return `<span title="${escapeHtml(tooltip)}" class="inline-flex items-center gap-1 bg-gradient-to-r from-amber-950/90 to-yellow-950/90 text-yellow-300 text-[11px] px-2.5 py-1 rounded-md border border-yellow-600/70 font-bold shadow-sm cursor-help transition-transform hover:scale-105">
            <span>${icon}</span><span>${escapeHtml(label)}</span>
        </span>`;
    }

    // 4. Vị trí đặc thù Bóng chuyền, Cầu lông, Bóng bàn: OH, OP, MB, S, L, Đơn nam, Đơn nữ
    if (tLow.includes('chủ công') || tLow.includes('đối chuyền') || tLow.includes('phụ công') || 
        tLow.includes('chuyền hai') || tLow.includes('libero') || tLow.includes('đơn nam') || tLow.includes('đơn nữ') ||
        tLow.includes('tứ kết') || tLow.includes('bán kết')) {
        let icon = '🏐';
        if (tLow.includes('đơn nam') || tLow.includes('đơn nữ') || tLow.includes('tứ kết') || tLow.includes('bán kết')) {
            icon = tLow.includes('bàn') ? '🏓' : '🏸';
        }
        return `<span class="inline-flex items-center gap-1 bg-indigo-950/80 text-indigo-300 text-[11px] px-2.5 py-1 rounded-md border border-indigo-800/70 font-semibold shadow-sm">
            <span>${icon}</span><span>${escapeHtml(label)}</span>
        </span>`;
    }

    // 5. In-game Stats: PTS, REB, AST, STL, BLK, phút, bàn, kiến tạo, hit, hr, cứu thua, +/- (Xanh ngọc / Emerald)
    if (tLow.includes('điểm') || tLow.includes('pts') || tLow.includes('reb') || tLow.includes('ast') || 
        tLow.includes('stl') || tLow.includes('blk') || tLow.includes('phút') || tLow.includes('bàn') || 
        tLow.includes('kiến tạo') || tLow.includes('hit') || tLow.includes('home run') || tLow.includes('rbi') || 
        tLow.includes('cứu thua') || tLow.includes('sạch lưới') || tLow.includes('+/-') || tLow.includes('3pt')) {
        return `<span class="inline-flex items-center gap-1 bg-emerald-950/80 text-emerald-300 text-[11px] px-2.5 py-1 rounded-md border border-emerald-800/70 font-medium shadow-sm">
            <span>${escapeHtml(label)}</span>
        </span>`;
    }

    // 6. Default / Tournaments & Roles: NBA, Champions League, Xuất phát, Đá chính (Xanh dương / Blue)
    return `<span class="inline-flex items-center gap-1 bg-blue-950/80 text-blue-300 text-[11px] px-2.5 py-1 rounded-md border border-blue-800/60 font-medium shadow-sm">
        <span>${escapeHtml(label)}</span>
    </span>`;
}

let currentEntityTypeFilter = 'all'; // 'all' | 'player' | 'national_team'

function setEntityTypeFilter(type) {
    currentEntityTypeFilter = type;
    const allBtn = document.getElementById('entityFilterAllBtn');
    const playersBtn = document.getElementById('entityFilterPlayersBtn');
    const nationalBtn = document.getElementById('entityFilterNationalBtn');

    const activeClass = "px-3.5 py-1.5 rounded-xl text-xs sm:text-sm font-bold flex items-center gap-2 transition-all bg-blue-600 text-white shadow-md shadow-blue-600/30";
    const inactiveClass = "px-3.5 py-1.5 rounded-xl text-xs sm:text-sm font-semibold flex items-center gap-2 transition-all text-gray-400 hover:text-gray-200 hover:bg-gray-800/80";

    if (allBtn) allBtn.className = (type === 'all') ? activeClass : inactiveClass;
    if (playersBtn) playersBtn.className = (type === 'player') ? activeClass : inactiveClass;
    if (nationalBtn) nationalBtn.className = (type === 'national_team') ? activeClass : inactiveClass;

    loadDashboard(true);
}

async function loadDashboard(refreshDropdowns = true) {
    const sportSelect = document.getElementById('sportFilter');
    const countrySelect = document.getElementById('countryFilter');
    const sportVal = sportSelect.value;
    const countryVal = countrySelect.value;
    let url = '/api/dashboard?';
    if (sportVal) url += `sport=${encodeURIComponent(sportVal)}&`;
    if (countryVal) url += `country=${encodeURIComponent(countryVal)}&`;
    if (currentEntityTypeFilter && currentEntityTypeFilter !== 'all') {
        url += `entity_type=${encodeURIComponent(currentEntityTypeFilter)}&`;
    }

    try {
        const res = await fetch(url);
        if (!res.ok) {
            throw new Error(`HTTP ${res.status}: ${res.statusText}`);
        }
        const data = await res.json();
        window._dashboardRetryAttempted = false;

        if (data.today_date_vn) {
            window.serverTodayVNDate = data.today_date_vn;
        }

        if (refreshDropdowns) {
            if (data.sports_list) {
                const curSport = sportSelect.value;
                const hasSport = data.sports_list.some(s => s.name === curSport);
                sportSelect.innerHTML = '<option value="">Tất cả môn</option>' + 
                    data.sports_list.map(s => `<option value="${escapeHtml(s.name)}" ${(hasSport && s.name === curSport) ? 'selected' : ''}>${escapeHtml(s.name)}</option>`).join('');
                if (!hasSport) {
                    sportSelect.value = "";
                }
            }
            if (data.countries_list) {
                const curCountry = countrySelect.value;
                const hasCountry = data.countries_list.some(c => c.name === curCountry);
                countrySelect.innerHTML = '<option value="">Tất cả quốc tịch</option>' + 
                    data.countries_list.map(c => `<option value="${escapeHtml(c.name)}" ${(hasCountry && c.name === curCountry) ? 'selected' : ''}>${escapeHtml(c.name)}</option>`).join('');
                if (!hasCountry) {
                    countrySelect.value = "";
                }
            }
        }

        const activeList = data.active_players || [];
        const upcomingList = data.upcoming_players || data.inactive_players || [];
        const noMatchList = data.no_match_players || [];
        const scheduleList = data.schedule_players || [];

        document.getElementById('activeCountBadge').innerText = activeList.length;
        document.getElementById('upcomingCountBadge').innerText = upcomingList.length;
        document.getElementById('noMatchCountBadge').innerText = noMatchList.length;
        if (document.getElementById('scheduleCountBadge')) {
            document.getElementById('scheduleCountBadge').innerText = scheduleList.length;
        }

        const totalP = (data.total_players !== undefined) ? data.total_players : 0;
        const totalNT = (data.total_national_teams !== undefined) ? data.total_national_teams : 0;
        const totalAll = (data.total_all !== undefined) ? data.total_all : (totalP + totalNT);
        const pTotalBadge = document.getElementById('playersTotalBadge');
        if (pTotalBadge) pTotalBadge.innerText = totalP;
        const ntTotalBadge = document.getElementById('nationalTotalBadge');
        if (ntTotalBadge) ntTotalBadge.innerText = totalNT;
        const allTotalBadge = document.getElementById('allEntitiesTotalBadge');
        if (allTotalBadge) allTotalBadge.innerText = totalAll;

        window.activePlayersMap = {};
        activeList.forEach(p => { window.activePlayersMap[p.id] = p; });
        upcomingList.forEach(p => { window.activePlayersMap[p.id] = p; });
        noMatchList.forEach(p => { window.activePlayersMap[p.id] = p; });
        scheduleList.forEach(p => { window.activePlayersMap[p.id] = p; });

        function getRatingBadge(rating) {
            if (rating === null || rating === undefined || rating === '' || isNaN(rating) || Number(rating) <= 0) {
                return '';
            }
            const r = Number(rating);
            let colorClass = 'bg-emerald-600 text-white';
            if (r >= 7.5) {
                colorClass = 'bg-emerald-600 text-white';
            } else if (r >= 6.5) {
                colorClass = 'bg-amber-500 text-black';
            } else {
                colorClass = 'bg-rose-600 text-white';
            }
            return `<span class="${colorClass} font-bold px-2 py-0.5 rounded-md text-xs shadow-sm flex items-center gap-1 shrink-0 whitespace-nowrap">★ ${r.toFixed(1)}</span>`;
        }

        const activeContainer = document.getElementById('activeContainer');
        if (activeList.length === 0) {
            activeContainer.innerHTML = `
                <div class="col-span-full py-12 text-center bg-gray-900/40 rounded-2xl border border-gray-800">
                    <span class="text-3xl">📭</span>
                    <p class="text-gray-400 mt-2 text-sm font-medium">Chưa có cầu thủ nào hoạt động hôm nay theo bộ lọc.</p>
                </div>`;
        } else {
            activeContainer.innerHTML = activeList.map(p => {
                const tagsHtml = (p.tags || []).filter(t => !t.toLowerCase().includes('tin tức')).map(t => renderTagBadge(t)).join('');

                const ratingBadge = getRatingBadge(p.rating);
                const tz = p.details && p.details.match_date_utc ? formatMatchTimezones(p.details.match_date_utc, p.country_timezone, p.country_flag) : null;

                const newsBadge = renderCardNewsBadges(p);

                const mState = p.match_state || (p.details && p.details.match_state) || 'pre';
                const mResult = p.match_result || (p.details && p.details.match_result);
                const pStats = p.player_stats || (p.details && p.details.player_stats);

                let matchBoxHtml = '';
                const oppName = getOpponentName(p.details ? p.details.match : '', p.team);
                if (mState === 'post') {
                    matchBoxHtml = `
                        <div class="flex items-center justify-between text-xs gap-2">
                            <span class="w-16 shrink-0 text-gray-400">Đối thủ:</span> 
                            <span class="font-semibold text-gray-100 truncate text-right">${escapeHtml(oppName)}</span>
                        </div>
                        <div class="pt-1.5 border-t border-gray-800/80 flex items-center justify-between text-xs gap-2">
                            <span class="w-16 shrink-0 text-gray-400">Kết quả:</span>
                            <span class="text-emerald-400 font-bold font-mono truncate text-right">${escapeHtml(mResult || 'Đã kết thúc (FT)')}</span>
                        </div>
                        ${(pStats && pStats.trim() && pStats.trim() !== 'Sạch lưới') ? `
                        <div class="pt-1 border-t border-gray-800/60 flex items-center justify-between text-xs gap-2">
                            <span class="w-16 shrink-0 text-blue-400">Thông số:</span>
                            <span class="text-gray-200 font-mono text-[11px] truncate text-right">${escapeHtml(pStats)}</span>
                        </div>` : ''}`;
                } else if (mState === 'in') {
                    matchBoxHtml = `
                        <div class="flex items-center justify-between text-xs gap-2">
                            <span class="w-16 shrink-0 text-gray-400">Đối thủ:</span> 
                            <span class="font-semibold text-gray-100 truncate text-right">${escapeHtml(oppName)}</span>
                        </div>
                        <div class="pt-1.5 border-t border-gray-800/80 flex items-center justify-between text-xs gap-2">
                            <span class="w-24 shrink-0 text-rose-400 font-semibold flex items-center gap-1"><span class="animate-ping w-2 h-2 rounded-full bg-rose-500 inline-block"></span> TRỰC TIẾP:</span>
                            <span class="text-amber-300 font-bold font-mono truncate text-right">${escapeHtml(mResult || 'Đang diễn ra')}</span>
                        </div>`;
                } else {
                    matchBoxHtml = `
                        <div class="flex items-center justify-between text-xs gap-2">
                            <span class="w-16 shrink-0 text-gray-400">Đối thủ:</span> 
                            <span class="font-semibold text-gray-100 truncate text-right">${escapeHtml(oppName)}</span>
                        </div>
                        ${tz ? `
                        <div class="pt-1.5 border-t border-gray-800/80 space-y-1">
                            <div class="flex items-center justify-between text-[11px] gap-2">
                                <span class="shrink-0 text-gray-400 flex items-center gap-1"><span>🇻🇳</span> Giờ VN (UTC+7):</span>
                                <span class="text-emerald-400 font-mono font-semibold truncate text-right">${escapeHtml(tz.vnTime)}</span>
                            </div>
                            <div class="flex items-center justify-between text-[11px] gap-2">
                                <span class="shrink-0 text-gray-400 flex items-center gap-1"><span>${escapeHtml(tz.countryFlag)}</span> ${escapeHtml(tz.tzLabel)}:</span>
                                <span class="text-blue-400 font-mono font-semibold truncate text-right">${escapeHtml(tz.localTime)}</span>
                            </div>
                        </div>` : ''}`;
                }

                const isNT = (p.entity_type === 'national_team');
                const cardTitle = isNT 
                    ? `<span class="text-xl mr-1.5">${p.country_flag || '🌐'}</span>${escapeHtml(p.name)}`
                    : `${escapeHtml(p.name)} <span class="text-gray-400 font-normal text-xs sm:text-sm">- ${escapeHtml(p.team || '')}</span>`;
                const cardSub = isNT 
                    ? `<span>${escapeHtml(p.sport)}</span>`
                    : `<span>${escapeHtml(p.sport)}</span> • <span>${escapeHtml(p.country)}</span>`;

                return `
                    <div onclick="openPlayerModal('${p.id}')" 
                        class="group bg-gray-900/80 hover:bg-gray-900 p-5 rounded-2xl border border-gray-800 hover:border-blue-500/70 shadow-sm hover:shadow-xl hover:shadow-blue-500/10 cursor-pointer transition-all duration-200 flex flex-col justify-between h-full">
                        <div class="flex flex-col flex-1">
                            <div class="flex items-start justify-between gap-2.5 mb-2 min-w-0 min-h-[46px]">
                                <div class="min-w-0 flex-1">
                                    <h3 class="font-bold text-base text-white group-hover:text-blue-400 transition-colors truncate" title="${escapeHtml(p.name)} - ${escapeHtml(p.team || '')}">
                                        ${cardTitle}
                                    </h3>
                                    <div class="text-xs text-gray-400 flex items-center gap-1.5 mt-0.5 truncate">
                                        ${cardSub}
                                    </div>
                                </div>
                                <div class="flex items-center gap-1.5 shrink-0 whitespace-nowrap pt-0.5">
                                    ${ratingBadge}
                                    <button onclick="deletePlayer(event, '${p.id}', '${escapeHtml(p.name)}')" title="Xóa" class="text-gray-500 hover:text-red-400 p-1 rounded-lg hover:bg-red-950/40 transition">
                                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                                    </button>
                                </div>
                            </div>
                            <div class="text-xs text-gray-300 bg-gray-950/60 p-3 rounded-xl border border-gray-800/80 my-2.5 min-h-[82px] flex flex-col justify-center space-y-1.5">
                                ${matchBoxHtml}
                            </div>
                            <div class="flex flex-wrap gap-1.5 mt-2 min-h-[64px] max-h-[88px] overflow-hidden content-start items-start">
                                ${tagsHtml}
                            </div>
                        </div>
                        <div class="mt-4 pt-3 border-t border-gray-800/80 flex items-center justify-between">
                            ${newsBadge}
                            <span class="text-xs text-blue-400 group-hover:translate-x-0.5 transition-transform font-medium flex items-center gap-1">Chi tiết &rarr;</span>
                        </div>
                    </div>`;
            }).join('');
        }

        const inactiveContainer = document.getElementById('inactiveContainer');
        if (!upcomingList || upcomingList.length === 0) {
            inactiveContainer.innerHTML = `
                <div class="col-span-full py-12 text-center bg-gray-900/40 rounded-2xl border border-gray-800">
                    <span class="text-3xl">🗓️</span>
                    <p class="text-gray-400 mt-2 text-sm font-medium">Không có lịch thi đấu trong 30 ngày sắp tới.</p>
                </div>`;
        } else {
            inactiveContainer.innerHTML = upcomingList.map(p => {
                const tz = formatMatchTimezones(p.match_date_utc, p.country_timezone, p.country_flag);
                const newsBadge = renderCardNewsBadges(p);

                const ratingBadge = getRatingBadge(p.rating);
                const tagsHtml = (p.tags || []).filter(t => !t.toLowerCase().includes('tin tức')).map(t => renderTagBadge(t)).join('');

                const isNT = (p.entity_type === 'national_team');
                const cardTitle = isNT 
                    ? `<span class="text-xl mr-1.5">${p.country_flag || '🌐'}</span>${escapeHtml(p.name)}`
                    : `${escapeHtml(p.name)} <span class="text-gray-400 font-normal text-xs sm:text-sm">- ${escapeHtml(p.team || '')}</span>`;
                const cardSub = isNT 
                    ? `<span>${escapeHtml(p.sport)}</span>`
                    : `<span>${escapeHtml(p.sport)}</span> • <span>${escapeHtml(p.country)}</span>`;

                return `
                <div onclick="openPlayerModal('${p.id}')" 
                    class="group bg-gray-900/80 hover:bg-gray-900 p-5 rounded-2xl border border-gray-800 hover:border-blue-500/70 shadow-sm hover:shadow-xl hover:shadow-blue-500/10 cursor-pointer transition-all duration-200 flex flex-col justify-between h-full">
                    <div class="flex flex-col flex-1">
                        <div class="flex items-start justify-between gap-2.5 mb-2 min-w-0 min-h-[46px]">
                            <div class="min-w-0 flex-1">
                                <h3 class="font-bold text-base text-gray-200 group-hover:text-blue-400 transition-colors truncate" title="${escapeHtml(p.name)} - ${escapeHtml(p.team || '')}">
                                    ${cardTitle}
                                </h3>
                                <div class="text-xs text-gray-400 flex items-center gap-1.5 mt-0.5 truncate">
                                    ${cardSub}
                                </div>
                            </div>
                            <div class="flex items-center gap-1.5 shrink-0 whitespace-nowrap pt-0.5">
                                ${ratingBadge}
                                <button onclick="deletePlayer(event, '${p.id}', '${escapeHtml(p.name)}')" title="Xóa" class="text-gray-500 hover:text-red-400 p-1 rounded-lg hover:bg-red-950/40 transition">
                                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                                </button>
                            </div>
                        </div>
                        <div class="text-xs bg-gray-950/60 p-3 rounded-xl border border-gray-800 my-2.5 min-h-[82px] flex flex-col justify-center space-y-1.5">
                            <div class="flex items-center justify-between text-xs gap-2">
                                <span class="w-20 shrink-0 text-gray-400">Trận kế tiếp:</span>
                                <span class="font-semibold text-white truncate text-right">${escapeHtml(getOpponentName((p.next_match || '').replace(/\s*\([^)]*\)\s*$/, '').trim(), p.team))}</span>
                            </div>
                            <div class="pt-1.5 border-t border-gray-800/80 space-y-1">
                                <div class="flex items-center justify-between text-[11px] gap-2">
                                    <span class="shrink-0 text-gray-400 flex items-center gap-1"><span>🇻🇳</span> Giờ VN (UTC+7):</span>
                                    <span class="text-emerald-400 font-mono font-semibold truncate text-right">${escapeHtml(tz.vnTime)}</span>
                                </div>
                                <div class="flex items-center justify-between text-[11px] gap-2">
                                    <span class="shrink-0 text-gray-400 flex items-center gap-1"><span>${escapeHtml(tz.countryFlag)}</span> ${escapeHtml(tz.tzLabel)}:</span>
                                    <span class="text-blue-400 font-mono font-semibold truncate text-right">${escapeHtml(tz.localTime)}</span>
                                </div>
                            </div>
                        </div>
                        <div class="flex flex-wrap gap-1.5 mt-2 min-h-[64px] max-h-[88px] overflow-hidden content-start items-start">
                            ${tagsHtml}
                        </div>
                    </div>
                    <div class="mt-4 pt-3 border-t border-gray-800/80 flex items-center justify-between">
                        ${newsBadge}
                        <span class="text-xs text-blue-400 group-hover:translate-x-0.5 transition-transform font-medium flex items-center gap-1">Chi tiết &rarr;</span>
                    </div>
                </div>`;
            }).join('');
        }

        // TAB 3: NO MATCH
        const noMatchContainer = document.getElementById('noMatchContainer');
        if (!noMatchList || noMatchList.length === 0) {
            noMatchContainer.innerHTML = `
                <div class="col-span-full py-12 text-center bg-gray-900/40 rounded-2xl border border-gray-800">
                    <span class="text-3xl">🎉</span>
                    <p class="text-gray-400 mt-2 text-sm font-medium">Tất cả đối tượng đều có lịch thi đấu sắp tới!</p>
                </div>`;
        } else {
            noMatchContainer.innerHTML = noMatchList.map(p => {
                const newsBadge = renderCardNewsBadges(p);
                const tagsHtml = (p.tags || []).filter(t => !t.toLowerCase().includes('tin tức')).map(t => renderTagBadge(t)).join('');
                const ratingBadge = getRatingBadge(p.rating);

                const isNT = (p.entity_type === 'national_team');
                const cardTitle = isNT 
                    ? `<span class="text-xl mr-1.5">${p.country_flag || '🌐'}</span>${escapeHtml(p.name)}`
                    : `${escapeHtml(p.name)} <span class="text-gray-400 font-normal text-xs sm:text-sm">- ${escapeHtml(p.team || '')}</span>`;
                const cardSub = isNT 
                    ? `<span>${escapeHtml(p.sport)}</span>`
                    : `<span>${escapeHtml(p.sport)}</span> • <span>${escapeHtml(p.country)}</span>`;

                return `
                <div onclick="openPlayerModal('${p.id}')" 
                    class="group bg-gray-900/80 hover:bg-gray-900 p-5 rounded-2xl border border-gray-800 hover:border-amber-500/50 shadow-sm hover:shadow-xl hover:shadow-amber-500/10 cursor-pointer transition-all duration-200 flex flex-col justify-between h-full">
                    <div class="flex flex-col flex-1">
                        <div class="flex items-start justify-between gap-2.5 mb-2 min-w-0 min-h-[46px]">
                            <div class="min-w-0 flex-1">
                                <h3 class="font-bold text-base text-gray-200 group-hover:text-amber-400 transition-colors truncate" title="${escapeHtml(p.name)} - ${escapeHtml(p.team || '')}">
                                    ${cardTitle}
                                </h3>
                                <div class="text-xs text-gray-400 flex items-center gap-1.5 mt-0.5 truncate">
                                    ${cardSub}
                                </div>
                            </div>
                            <div class="flex items-center gap-1.5 shrink-0 whitespace-nowrap pt-0.5">
                                ${ratingBadge}
                                <button onclick="deletePlayer(event, '${p.id}', '${escapeHtml(p.name)}')" title="Xóa" class="text-gray-500 hover:text-red-400 p-1 rounded-lg hover:bg-red-950/40 transition">
                                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                                </button>
                            </div>
                        </div>
                        <div class="text-xs bg-gray-950/60 p-3.5 rounded-xl border border-gray-800 my-2.5 flex-1 flex flex-col justify-center space-y-1.5">
                            <div class="flex items-center justify-between text-gray-300">
                                <span class="text-gray-400">Trạng thái:</span>
                                <span class="font-semibold text-amber-400/90 truncate ml-2 text-right">${escapeHtml(p.next_match)}</span>
                            </div>
                            <div class="pt-1.5 border-t border-gray-800/80 text-[11px] text-gray-500 italic">
                                Không có lịch thi đấu chính thức trong 30 ngày sắp tới.
                            </div>
                        </div>
                        ${tagsHtml ? `
                        <div class="flex flex-wrap gap-1.5 mt-1 min-h-[36px] max-h-[64px] overflow-hidden content-start items-start">
                            ${tagsHtml}
                        </div>` : ''}
                    </div>
                    <div class="mt-4 pt-3 border-t border-gray-800/80 flex items-center justify-between">
                        ${newsBadge}
                        <span class="text-xs text-amber-400 group-hover:translate-x-0.5 transition-transform font-medium flex items-center gap-1">Chi tiết &rarr;</span>
                    </div>
                </div>`;
            }).join('');
        }

        // TAB 4: SCHEDULE
        const scheduleContainer = document.getElementById('scheduleContainer');
        if (scheduleContainer) {
            if (!scheduleList || scheduleList.length === 0) {
                scheduleContainer.innerHTML = `
                    <div class="col-span-full py-12 text-center bg-gray-900/40 rounded-2xl border border-gray-800">
                        <span class="text-3xl">📅</span>
                        <p class="text-gray-400 mt-2 text-sm font-medium">Chưa có dữ liệu lịch thi đấu cho các đối tượng theo dõi.</p>
                    </div>`;
            } else {
                scheduleContainer.innerHTML = scheduleList.map(p => {
                    const newsBadge = renderCardNewsBadges(p);
                    const ratingBadge = getRatingBadge(p.rating);

                    const sched3 = p.upcoming_3_matches || [];
                    let sched3Html = '';
                    if (sched3.length > 0) {
                        sched3Html = sched3.map((m, idx) => `
                            <div class="flex items-center justify-between text-xs py-1.5 ${idx > 0 ? 'border-t border-gray-800/50' : ''} gap-2">
                                <div class="flex items-center gap-2 min-w-0 flex-1">
                                    <span class="text-blue-400 font-mono text-[11px] font-semibold shrink-0">#${idx+1}</span>
                                    <span class="text-gray-200 font-medium truncate text-xs" title="${escapeHtml(m.match_name)}">${escapeHtml(getOpponentName(m.match_name, p.team))}</span>
                                </div>
                                <span class="text-emerald-400 font-mono text-xs font-semibold shrink-0 text-right">${escapeHtml(m.date_vn)}</span>
                            </div>
                        `).join('');
                    } else {
                        sched3Html = `<div class="text-xs text-gray-500 italic py-2 text-center">Chưa có lịch thi đấu trong 30 ngày tới</div>`;
                    }

                    const isNT = (p.entity_type === 'national_team');
                    const cardTitle = isNT 
                        ? `<span class="text-xl mr-1.5">${p.country_flag || '🌐'}</span>${escapeHtml(p.name)}`
                        : `${escapeHtml(p.name)} <span class="text-gray-400 font-normal text-xs sm:text-sm">- ${escapeHtml(p.team || '')}</span>`;
                    const cardSub = isNT 
                        ? `<span>${escapeHtml(p.sport)}</span>`
                        : `<span>${escapeHtml(p.sport)}</span> • <span>${escapeHtml(p.country)}</span>`;

                    return `
                    <div onclick="openPlayerModal('${p.id}')" 
                        class="group bg-gray-900/80 hover:bg-gray-900 p-5 rounded-2xl border border-gray-800 hover:border-blue-500/70 shadow-sm hover:shadow-xl hover:shadow-blue-500/10 cursor-pointer transition-all duration-200 flex flex-col justify-between h-full">
                        <div class="flex flex-col flex-1">
                            <div class="flex items-start justify-between gap-2.5 mb-2 min-w-0 min-h-[46px]">
                                <div class="min-w-0 flex-1">
                                    <h3 class="font-bold text-base text-gray-200 group-hover:text-blue-400 transition-colors truncate" title="${escapeHtml(p.name)} - ${escapeHtml(p.team || '')}">
                                        ${cardTitle}
                                    </h3>
                                    <div class="text-xs text-gray-400 flex items-center gap-1.5 mt-0.5 truncate">
                                        ${cardSub}
                                    </div>
                                </div>
                                <div class="flex items-center gap-1.5 shrink-0 whitespace-nowrap pt-0.5">
                                    ${ratingBadge}
                                    <button onclick="deletePlayer(event, '${p.id}', '${escapeHtml(p.name)}')" title="Xóa" class="text-gray-500 hover:text-red-400 p-1 rounded-lg hover:bg-red-950/40 transition">
                                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                                    </button>
                                </div>
                            </div>
                            <div class="text-xs bg-gray-950/60 p-3.5 rounded-xl border border-gray-800/80 my-2.5 flex-1 flex flex-col justify-start space-y-1.5">
                                <div class="text-[11px] font-semibold text-gray-400 mb-1 flex items-center justify-between">
                                    <span class="flex items-center gap-1.5"><span class="text-blue-400">📅</span> 3 Trận Sắp Tới (Giờ VN)</span>
                                </div>
                                ${sched3Html}
                            </div>
                        </div>
                        <div class="mt-4 pt-3 border-t border-gray-800/80 flex items-center justify-between">
                            ${newsBadge}
                            <span class="text-xs text-blue-400 group-hover:translate-x-0.5 transition-transform font-medium flex items-center gap-1">Lịch 30 ngày &rarr;</span>
                        </div>
                    </div>`;
                }).join('');
            }
        }

        window.calendarAllPlayers = (scheduleList && scheduleList.length > 0) ? scheduleList : [...activeList, ...upcomingList, ...noMatchList];
        window.calendarCounts = data.calendar_counts || {};
        renderCalendarTimeline();
        if (selectedCalendarDate) {
            renderCalendarCards(selectedCalendarDate);
        }
    } catch (err) {
        console.error("Lỗi khi tải dữ liệu dashboard:", err);
        if (!window._dashboardRetryAttempted) {
            window._dashboardRetryAttempted = true;
            console.log("Đang tự động kết nối lại sau 2.5 giây...");
            setTimeout(() => {
                loadDashboard(refreshDropdowns);
            }, 2500);
        }
    }
}

let selectedCalendarDate = null;
window.calendarAllPlayers = [];
window.calendarCounts = {};
window.activePlayerMatchMap = {};

function getTodayVNDateStr() {
    if (window.serverTodayVNDate) {
        return window.serverTodayVNDate;
    }
    const now = new Date();
    const utcMs = now.getTime() + (now.getTimezoneOffset() * 60000);
    const vnDate = new Date(utcMs + (7 * 3600000));
    const yyyy = vnDate.getFullYear();
    const mm = String(vnDate.getMonth() + 1).padStart(2, '0');
    const dd = String(vnDate.getDate()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd}`;
}

function getMatchVnDateOnly(m) {
    if (!m) return '';
    if (m.date_only_vn) return m.date_only_vn;
    if (m.match_date_utc) {
        try {
            const dt = new Date(m.match_date_utc);
            const utcMs = dt.getTime() + (dt.getTimezoneOffset() * 60000);
            const vnDate = new Date(utcMs + (7 * 3600000));
            const yyyy = vnDate.getFullYear();
            const mm = String(vnDate.getMonth() + 1).padStart(2, '0');
            const dd = String(vnDate.getDate()).padStart(2, '0');
            return `${yyyy}-${mm}-${dd}`;
        } catch (e) {}
    }
    return '';
}

function formatDateToVietnameseLabel(dateStr) {
    if (!dateStr) return '';
    const parts = dateStr.split('-');
    if (parts.length !== 3) return dateStr;
    const y = parseInt(parts[0], 10);
    const m = parseInt(parts[1], 10) - 1;
    const d = parseInt(parts[2], 10);
    const dateObj = new Date(y, m, d);
    const dayNames = ['Chủ Nhật', 'Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy'];
    const dayOfWeek = dayNames[dateObj.getDay()];
    return `${dayOfWeek}, ngày ${String(d).padStart(2, '0')}/${String(m + 1).padStart(2, '0')}/${y}`;
}

function scrollDateStrip(offset) {
    const container = document.getElementById('topDateStripContainer');
    if (container) {
        container.scrollBy({ left: offset, behavior: 'smooth' });
    }
}

function jumpToCalendarToday() {
    switchTab('active');
    const todayStr = getTodayVNDateStr();
    const activeBtn = document.getElementById(`topDateBtn_${todayStr}`);
    if (activeBtn) {
        activeBtn.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
    }
}

function onTopDatePicked(dateVal) {
    if (dateVal) {
        selectCalendarDate(dateVal);
    }
}

function onCustomDateInput(val) {
    if (!val) {
        clearDateFilter();
        return;
    }
    const clean = val.trim();
    const parts = clean.split(/[\/\-\.]/);
    if (parts.length === 3) {
        let d = parseInt(parts[0], 10);
        let m = parseInt(parts[1], 10);
        let y = parseInt(parts[2], 10);
        if (y < 100) y += 2000;
        if (!isNaN(d) && !isNaN(m) && !isNaN(y) && d >= 1 && d <= 31 && m >= 1 && m <= 12 && y >= 2000) {
            const isoStr = `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
            selectCalendarDate(isoStr);
            return;
        }
    }
    // If invalid format, revert to current selection if any
    if (selectedCalendarDate) {
        const p = selectedCalendarDate.split('-');
        if (p.length === 3) {
            const displayInput = document.getElementById('topDatePickerDisplay');
            if (displayInput) displayInput.value = `${p[2]}/${p[1]}/${p[0]}`;
        }
    }
}

function clearDateFilter() {
    selectedCalendarDate = null;
    const dateResults = document.getElementById('dateFilteredResultsPanel');
    if (dateResults) dateResults.classList.add('hidden');
    const badgeLabel = document.getElementById('activeDateBadgeLabel');
    if (badgeLabel) badgeLabel.classList.add('hidden');
    const picker = document.getElementById('topDatePicker');
    if (picker) picker.value = '';
    const displayInput = document.getElementById('topDatePickerDisplay');
    if (displayInput) displayInput.value = '';

    // Remove active ring from strip
    const container = document.getElementById('topDateStripContainer');
    if (container) {
        const todayStr = getTodayVNDateStr();
        container.querySelectorAll('button').forEach(btn => {
            const btnDate = btn.getAttribute('data-date');
            const isToday = (btnDate === todayStr);
            btn.className = isToday 
                ? "shrink-0 flex flex-col items-center justify-center min-w-[64px] p-2.5 rounded-xl border text-center transition-all cursor-pointer border-emerald-500/80 bg-gray-900/90 hover:bg-gray-800"
                : "shrink-0 flex flex-col items-center justify-center min-w-[64px] p-2.5 rounded-xl border text-center transition-all cursor-pointer border-gray-800 bg-gray-900/60 hover:border-gray-700 hover:bg-gray-800/80";
        });
    }

    // Restore active tab panel
    switchTab(currentActiveTab || 'active');
}

function selectCalendarDate(dateStr) {
    if (!dateStr) return;
    const todayStr = getTodayVNDateStr();

    // If selecting today's date, switch directly to Today's Activities tab
    if (dateStr === todayStr) {
        switchTab('active');
        const activeBtn = document.getElementById(`topDateBtn_${todayStr}`);
        if (activeBtn) {
            activeBtn.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
        }
        return;
    }

    selectedCalendarDate = dateStr;

    const parts = dateStr.split('-');
    if (parts.length === 3) {
        const y = parseInt(parts[0], 10);
        if (y && y !== selectedCalendarYear) {
            selectedCalendarYear = y;
            const yearSelect = document.getElementById('calendarYearSelect');
            if (yearSelect) yearSelect.value = String(y);
            renderCalendarTimeline();
        }
    }

    const picker = document.getElementById('topDatePicker');
    if (picker) picker.value = dateStr;
    const displayInput = document.getElementById('topDatePickerDisplay');
    if (displayInput && dateStr) {
        const p = dateStr.split('-');
        if (p.length === 3) {
            displayInput.value = `${p[2]}/${p[1]}/${p[0]}`;
        }
    }

    // Deselect all standard tab buttons so none is mistakenly highlighted with blue active underline
    const inactiveClass = "tab-btn py-3 px-1 border-b-2 font-semibold text-sm flex items-center gap-2 border-transparent text-gray-400 hover:text-gray-200 hover:border-gray-700 transition-colors duration-150";
    ['tabActiveBtn', 'tabUpcomingBtn', 'tabNoMatchBtn', 'tabScheduleBtn'].forEach(id => {
        const btn = document.getElementById(id);
        if (btn) btn.className = inactiveClass;
    });

    // Show date filter results panel and hide standard tabs
    const dateResults = document.getElementById('dateFilteredResultsPanel');
    if (dateResults) dateResults.classList.remove('hidden');

    ['activeTabPanel', 'upcomingTabPanel', 'noMatchTabPanel', 'scheduleTabPanel'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.classList.add('hidden');
    });

    // Update active badge in top bar
    const badgeLabel = document.getElementById('activeDateBadgeLabel');
    if (badgeLabel) {
        badgeLabel.innerText = `Đang lọc: ${formatDateToVietnameseLabel(dateStr)}`;
        badgeLabel.classList.remove('hidden');
    }

    // Highlight button in strip
    const container = document.getElementById('topDateStripContainer');
    if (container) {
        container.querySelectorAll('button').forEach(btn => {
            const btnDate = btn.getAttribute('data-date');
            const isToday = btn.getAttribute('data-today') === 'true';
            if (btnDate === dateStr) {
                btn.className = "shrink-0 flex flex-col items-center justify-center min-w-[58px] sm:min-w-[62px] p-2 rounded-xl border text-center transition-all cursor-pointer border-blue-500 bg-blue-950/90 shadow-md shadow-blue-500/20 ring-2 ring-blue-500/50";
            } else if (isToday) {
                btn.className = "shrink-0 flex flex-col items-center justify-center min-w-[58px] sm:min-w-[62px] p-2 rounded-xl border text-center transition-all cursor-pointer border-emerald-500/80 bg-gray-900/90 hover:bg-gray-800";
            } else {
                btn.className = "shrink-0 flex flex-col items-center justify-center min-w-[58px] sm:min-w-[62px] p-2 rounded-xl border text-center transition-all cursor-pointer border-gray-800 bg-gray-900/60 hover:border-gray-700 hover:bg-gray-800/80";
            }
        });

        const activeBtn = document.getElementById(`topDateBtn_${dateStr}`);
        if (activeBtn) {
            activeBtn.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
        }
    }

    renderCalendarCards(dateStr);
}

let selectedCalendarYear = 2026;

function changeCalendarYear(yearVal) {
    selectedCalendarYear = parseInt(yearVal, 10) || 2026;
    renderCalendarTimeline();
}

function renderCalendarTimeline() {
    const container = document.getElementById('topDateStripContainer');
    if (!container) return;

    const todayStr = getTodayVNDateStr();
    const todayParts = todayStr.split('-');
    const todayYear = parseInt(todayParts[0], 10) || 2026;
    if (!selectedCalendarYear) {
        selectedCalendarYear = todayYear;
    }

    const yearSelect = document.getElementById('calendarYearSelect');
    if (yearSelect && yearSelect.value != String(selectedCalendarYear)) {
        yearSelect.value = String(selectedCalendarYear);
    }

    // Hiển thị đầy đủ từ 01/01 đến 31/12 của năm được chọn
    const sortedDates = [];
    const isLeapYear = (selectedCalendarYear % 4 === 0 && selectedCalendarYear % 100 !== 0) || (selectedCalendarYear % 400 === 0);
    const daysInMonths = [31, isLeapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

    for (let m = 1; m <= 12; m++) {
        const mm = String(m).padStart(2, '0');
        const numDays = daysInMonths[m - 1];
        for (let d = 1; d <= numDays; d++) {
            const dd = String(d).padStart(2, '0');
            sortedDates.push(`${selectedCalendarYear}-${mm}-${dd}`);
        }
    }

    const dayNames = ['CN', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7'];
    let html = '';

    sortedDates.forEach(dStr => {
        const parts = dStr.split('-');
        if (parts.length !== 3) return;
        const cur = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
        const dayName = dayNames[cur.getDay()];
        const isToday = (dStr === todayStr);
        const isSelected = (dStr === selectedCalendarDate);
        const count = (window.calendarCounts && window.calendarCounts[dStr]) ? window.calendarCounts[dStr] : 0;

        let borderClass = isSelected 
            ? "border-blue-500 bg-blue-950/90 shadow-md shadow-blue-500/20 ring-2 ring-blue-500/50" 
            : (isToday ? "border-emerald-500/80 bg-gray-900/90 hover:bg-gray-800" : "border-gray-800 bg-gray-900/60 hover:border-gray-700 hover:bg-gray-800/80");

        let badgeHtml = count > 0 
            ? `<span class="mt-1 px-1.5 py-0.5 rounded-full text-[10px] font-bold ${isSelected ? 'bg-blue-500 text-white' : (isToday ? 'bg-emerald-500 text-black font-extrabold' : 'bg-blue-950 text-blue-300 border border-blue-800')}">${count}</span>`
            : `<span class="mt-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium text-gray-500 bg-gray-950/40 border border-gray-800/60">0</span>`;

        // Định dạng dd/mm (01/01 đến 31/12), không dài dòng có /2026 ở sau
        html += `
            <button id="topDateBtn_${dStr}" data-date="${dStr}" data-today="${isToday}" onclick="selectCalendarDate('${dStr}')"
                class="shrink-0 flex flex-col items-center justify-center min-w-[58px] sm:min-w-[62px] p-2 rounded-xl border text-center transition-all cursor-pointer ${borderClass}">
                <span class="text-[10px] font-semibold uppercase ${isToday ? 'text-emerald-400 font-bold' : (isSelected ? 'text-blue-300 font-bold' : 'text-gray-400')}">
                    ${isToday ? 'Hôm nay' : dayName}
                </span>
                <span class="text-[11px] font-bold font-mono mt-0.5 ${isSelected ? 'text-white' : (isToday ? 'text-emerald-300 font-bold' : 'text-gray-200')} whitespace-nowrap">
                    ${parts[2]}/${parts[1]}
                </span>
                ${badgeHtml}
            </button>`;
    });

    container.innerHTML = html;

    setTimeout(() => {
        const targetBtn = document.getElementById(`topDateBtn_${selectedCalendarDate || todayStr}`);
        if (targetBtn) {
            targetBtn.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
        }
    }, 150);
}

function renderCalendarCards(dateStr) {
    const calendarContainer = document.getElementById('dateFilteredCardsContainer');
    const selectedTitleElem = document.getElementById('selectedDateTitle');
    const selectedBadgeElem = document.getElementById('selectedDateCountBadge');
    if (!calendarContainer) return;

    const todayStr = getTodayVNDateStr();
    const isToday = (dateStr === todayStr);
    const formattedTitle = formatDateToVietnameseLabel(dateStr) + (isToday ? ' (Hôm nay)' : '');
    if (selectedTitleElem) selectedTitleElem.innerText = formattedTitle;

    const matchedEntries = [];
    const seenPlayerMatch = new Set();
    window.activePlayerMatchMap = {};

    (window.calendarAllPlayers || []).forEach(p => {
        const allMatches = p.all_matches || p.matches_60d || (p.details && (p.details.all_matches || p.details.upcoming_matches_30d)) || [];
        allMatches.forEach(m => {
            const mDate = getMatchVnDateOnly(m);
            if (mDate === dateStr) {
                const uniqueKey = `${p.id}_${m.match_name}_${mDate}`;
                if (!seenPlayerMatch.has(uniqueKey)) {
                    seenPlayerMatch.add(uniqueKey);
                    matchedEntries.push({ player: p, match: m });
                    window.activePlayerMatchMap[uniqueKey] = { player: p, match: m };
                }
            }
        });
    });

    if (selectedBadgeElem) {
        selectedBadgeElem.innerText = `${matchedEntries.length} trận`;
    }

    // Sort matched entries matching Today's Activities hierarchy:
    // 1. Rating high to low (9.5 > 8.0 > 6.7)
    // 2. State priority (in > post > pre)
    // 3. News count (descending)
    // 4. Time
    matchedEntries.sort((a, b) => {
        const getRating = (entry) => {
            const r = (entry.match && entry.match.rating !== undefined && entry.match.rating !== null) 
                ? entry.match.rating 
                : (dateStr === todayStr ? entry.player.rating : null);
            return (r !== null && r !== undefined && !isNaN(r) && Number(r) > 0) ? Number(r) : 0;
        };
        const aR = getRating(a);
        const bR = getRating(b);
        const aHasR = aR > 0 ? 1 : 0;
        const bHasR = bR > 0 ? 1 : 0;
        if (aHasR !== bHasR) return bHasR - aHasR;
        if (aHasR && aR !== bR) return bR - aR;

        const getStatePriority = (entry) => {
            const state = entry.match.match_state || (entry.match.is_past ? 'post' : 'pre');
            if (state === 'in') return 3;
            if (state === 'post') return 2;
            return 1;
        };
        const aState = getStatePriority(a);
        const bState = getStatePriority(b);
        if (aState !== bState) return bState - aState;

        const aN = (a.match.news || []).length;
        const bN = (b.match.news || []).length;
        if (aN !== bN) return bN - aN;

        const aTime = a.match.match_date_utc || '';
        const bTime = b.match.match_date_utc || '';
        return aTime.localeCompare(bTime);
    });

    if (matchedEntries.length === 0) {
        calendarContainer.innerHTML = `
            <div class="col-span-full py-12 text-center bg-gray-900/40 rounded-2xl border border-gray-800">
                <span class="text-3xl">📭</span>
                <p class="text-gray-300 mt-2 text-sm font-semibold">Không có vận động viên nào thi đấu vào ngày ${formattedTitle}.</p>
                <p class="text-gray-500 text-xs mt-1">Gợi ý: Hãy nhấp vào các ngày có huy hiệu số phía trên để xem các trận đấu trong mùa giải.</p>
            </div>`;
        return;
    }

    function getRatingBadge(rating) {
        if (rating === null || rating === undefined || rating === '' || isNaN(rating) || Number(rating) <= 0) {
            return '';
        }
        const r = Number(rating);
        let colorClass = 'bg-emerald-600 text-white';
        if (r >= 7.5) colorClass = 'bg-emerald-600 text-white';
        else if (r >= 6.5) colorClass = 'bg-amber-500 text-black';
        else colorClass = 'bg-rose-600 text-white';
        return `<span class="${colorClass} font-bold px-2 py-0.5 rounded-md text-xs shadow-sm flex items-center gap-1 shrink-0 whitespace-nowrap">★ ${r.toFixed(1)}</span>`;
    }

    calendarContainer.innerHTML = matchedEntries.map(({ player: p, match: m }) => {
        const isPastOrLive = m.is_past || m.match_state === 'post' || m.match_state === 'in' || (dateStr < todayStr);
        const tagsHtml = (m.tags || []).filter(t => !t.toLowerCase().includes('tin tức')).map(t => renderTagBadge(t)).join('');
        const newsBadge = renderCardNewsBadges(p, m.news || []);
        const oppName = getOpponentName(m.match_name, p.team);

        // CRITICAL: Rating ONLY applies to completed/live matches, NEVER to upcoming matches!
        const ratingBadge = isPastOrLive ? getRatingBadge(m.rating) : '';

        let matchBoxHtml = '';
        if (isPastOrLive) {
            if (m.match_state === 'in') {
                matchBoxHtml = `
                    <div class="flex items-center justify-between text-xs gap-2">
                        <span class="w-16 shrink-0 text-gray-400">Đối thủ:</span> 
                        <span class="font-semibold text-gray-100 truncate text-right">${escapeHtml(oppName)}</span>
                    </div>
                    <div class="pt-1.5 border-t border-gray-800/80 flex items-center justify-between text-xs gap-2">
                        <span class="w-24 shrink-0 text-rose-400 font-semibold flex items-center gap-1"><span class="animate-ping w-2 h-2 rounded-full bg-rose-500 inline-block"></span> TRỰC TIẾP:</span>
                        <span class="text-amber-300 font-bold font-mono truncate text-right">${escapeHtml(m.match_result || 'Đang diễn ra')}</span>
                    </div>`;
            } else {
                matchBoxHtml = `
                    <div class="flex items-center justify-between text-xs gap-2">
                        <span class="w-16 shrink-0 text-gray-400">Đối thủ:</span> 
                        <span class="font-semibold text-gray-100 truncate text-right">${escapeHtml(oppName)}</span>
                    </div>
                    <div class="pt-1.5 border-t border-gray-800/80 flex items-center justify-between text-xs gap-2">
                        <span class="w-16 shrink-0 text-gray-400">Kết quả:</span>
                        <span class="text-emerald-400 font-bold font-mono truncate text-right">${escapeHtml(m.match_result || 'Đã kết thúc (FT)')}</span>
                    </div>
                    ${(m.player_stats && m.player_stats.trim() && m.player_stats.trim() !== 'Sạch lưới') ? `
                    <div class="pt-1 border-t border-gray-800/60 flex items-center justify-between text-xs gap-2">
                        <span class="w-16 shrink-0 text-blue-400">Thông số:</span>
                        <span class="text-gray-200 font-mono text-[11px] truncate text-right">${escapeHtml(m.player_stats)}</span>
                    </div>` : ''}`;
            }
        } else {
            // UPCOMING MATCH: No rating, no in-game stats!
            matchBoxHtml = `
                <div class="flex items-center justify-between text-xs gap-2">
                    <span class="w-20 shrink-0 text-gray-400">Trận đấu:</span>
                    <span class="font-semibold text-white truncate text-right">${escapeHtml(oppName)}</span>
                </div>
                <div class="pt-1.5 border-t border-gray-800/80 space-y-1">
                    <div class="flex items-center justify-between text-[11px] gap-2">
                        <span class="shrink-0 text-gray-400 flex items-center gap-1"><span>🇻🇳</span> Giờ VN (UTC+7):</span>
                        <span class="text-emerald-400 font-mono font-semibold truncate text-right">${escapeHtml(m.date_full_vn || m.date_vn)}</span>
                    </div>
                    <div class="flex items-center justify-between text-[11px] gap-2">
                        <span class="shrink-0 text-gray-400 flex items-center gap-1"><span>🏆</span> Giải đấu:</span>
                        <span class="text-blue-400 font-medium truncate text-right">${escapeHtml(m.competition || 'Giải chính thức')}</span>
                    </div>
                </div>`;
        }

        const mMatchNameSafe = escapeHtml(m.match_name);
        const mDateSafe = escapeHtml(m.date_only_vn);

        const isNT = (p.entity_type === 'national_team');
        const cardTitle = isNT 
            ? `<span class="text-xl mr-1.5">${p.country_flag || '🌐'}</span>${escapeHtml(p.name)}`
            : `${escapeHtml(p.name)} <span class="text-gray-400 font-normal text-xs sm:text-sm">- ${escapeHtml(p.team || '')}</span>`;
        const cardSub = isNT 
            ? `<span>${escapeHtml(p.sport)}</span>`
            : `<span>${escapeHtml(p.sport)}</span> • <span>${escapeHtml(p.country)}</span>`;

        return `
            <div onclick="openPlayerModalWithMatch('${p.id}', '${mMatchNameSafe}', '${mDateSafe}')" 
                class="group bg-gray-900/80 hover:bg-gray-900 p-5 rounded-2xl border border-gray-800 hover:border-blue-500/70 shadow-sm hover:shadow-xl hover:shadow-blue-500/10 cursor-pointer transition-all duration-200 flex flex-col justify-between h-full">
                <div class="flex flex-col flex-1">
                    <div class="flex items-start justify-between gap-2.5 mb-2 min-w-0 min-h-[46px]">
                        <div class="min-w-0 flex-1">
                            <h3 class="font-bold text-base text-white group-hover:text-blue-400 transition-colors truncate" title="${escapeHtml(p.name)} - ${escapeHtml(p.team || '')}">
                                ${cardTitle}
                            </h3>
                            <div class="text-xs text-gray-400 flex items-center gap-1.5 mt-0.5 truncate">
                                ${cardSub}
                            </div>
                        </div>
                        <div class="flex items-center gap-1.5 shrink-0 whitespace-nowrap pt-0.5">
                            ${ratingBadge}
                            <button onclick="deletePlayer(event, '${p.id}', '${escapeHtml(p.name)}')" title="Xóa" class="text-gray-500 hover:text-red-400 p-1 rounded-lg hover:bg-red-950/40 transition">
                                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                            </button>
                        </div>
                    </div>
                    <div class="text-xs text-gray-300 bg-gray-950/60 p-3 rounded-xl border border-gray-800/80 my-2.5 min-h-[82px] flex flex-col justify-center space-y-1.5">
                        ${matchBoxHtml}
                    </div>
                    <div class="flex flex-wrap gap-1.5 mt-2 min-h-[64px] max-h-[88px] overflow-hidden content-start items-start">
                        ${tagsHtml}
                    </div>
                </div>
                <div class="mt-4 pt-3 border-t border-gray-800/80 flex items-center justify-between">
                    ${newsBadge}
                    <span class="text-xs text-blue-400 group-hover:translate-x-0.5 transition-transform font-medium flex items-center gap-1">Chi tiết &rarr;</span>
                </div>
            </div>`;
    }).join('');
}

function openPlayerModalWithMatch(playerId, matchName, matchDate) {
    const key = `${playerId}_${matchName}_${matchDate}`;
    const entry = (window.activePlayerMatchMap || {})[key];
    if (entry) {
        openModal(entry.player, true, entry.match);
    } else {
        openPlayerModal(playerId);
    }
}

function openPlayerModal(playerId) {
    const player = window.activePlayersMap[playerId];
    if (player) openModal(player, true, null);
}

function openModal(player, resetFilter = true, customMatch = null) {
    if (typeof player === 'number' || typeof player === 'string') {
        player = window.activePlayersMap[player];
    }
    if (!player) return;

    window.currentModalPlayer = player;

    if (player.entity_type === 'national_team') {
        const flag = player.country_flag || '🌐';
        document.getElementById('modalPlayerName').innerText = `${flag} ${player.name}`;
        document.getElementById('modalPlayerSub').innerText = `${player.sport}`;
        const aliasesElem = document.getElementById('modalPlayerAliases');
        if (aliasesElem) {
            aliasesElem.innerText = '';
            aliasesElem.classList.add('hidden');
        }
    } else {
        document.getElementById('modalPlayerName').innerText = `${player.name} - ${player.team || ''}`;
        document.getElementById('modalPlayerSub').innerText = `${player.sport} • Quốc tịch: ${player.country}`;
        const aliasesElem = document.getElementById('modalPlayerAliases');
        if (aliasesElem) {
            if (player.name_aliases) {
                aliasesElem.innerText = `🏷️ Biến thể tên: ${player.name_aliases}`;
                aliasesElem.classList.remove('hidden');
            } else {
                aliasesElem.classList.add('hidden');
            }
        }
    }

    let opp = customMatch ? getOpponentName(customMatch.match_name, player.team) : getOpponentName(player.details.match, player.team);
    let matchText = opp || "Không có thông tin lịch đấu";
    const mResult = customMatch ? customMatch.match_result : (player.match_result || (player.details && player.details.match_result));
    if (mResult) {
        matchText += ` • Kết quả: ${mResult}`;
    }
    const mStats = customMatch ? customMatch.player_stats : (player.player_stats || (player.details && player.details.player_stats));
    if (mStats && mStats.trim() && mStats.trim() !== 'Sạch lưới') {
        matchText += ` • Thông số: ${mStats}`;
    }
    document.getElementById('modalMatchName').innerText = matchText;

    const ratingContainer = document.getElementById('modalRatingContainer');
    const displayRating = customMatch ? customMatch.rating : player.rating;
    if (ratingContainer) {
        if (displayRating && Number(displayRating) > 0) {
            const r = Number(displayRating);
            let colorClass = 'bg-emerald-600 text-white';
            if (r >= 7.5) colorClass = 'bg-emerald-600 text-white';
            else if (r >= 6.5) colorClass = 'bg-amber-500 text-black';
            else colorClass = 'bg-rose-600 text-white';
            ratingContainer.innerHTML = `<span class="${colorClass} font-bold px-2.5 py-0.5 rounded text-xs inline-flex items-center gap-1">Điểm đánh giá: ★ ${r.toFixed(1)}</span>`;
            ratingContainer.classList.remove('hidden');
        } else {
            ratingContainer.innerHTML = '';
            ratingContainer.classList.add('hidden');
        }
    }

    const tagsContainer = document.getElementById('modalTagsContainer');
    let tagsList = (customMatch ? (customMatch.tags || []) : (player.tags || [])).filter(t => !t.toLowerCase().includes('tin tức'));
    let tagsHtml = tagsList.map(t => renderTagBadge(t)).join('');
    
    const recordTag = tagsList.find(t => t.toLowerCase().includes('kỷ lục') || t.toLowerCase().includes('game winner'));
    if (recordTag) {
        tagsHtml += `
            <div class="w-full mt-2 p-2.5 rounded-xl bg-amber-950/40 border border-yellow-600/50 flex items-start gap-2 text-xs">
                <span class="text-base shrink-0">📜</span>
                <div>
                    <span class="font-bold text-yellow-300">Điểm nhấn: ${escapeHtml(recordTag)}</span>
                    <p class="text-gray-300 text-[11px] mt-0.5">Vận động viên đạt cột mốc / kỷ lục thi đấu cá nhân ấn tượng (career-high / record-breaking) được ghi nhận qua các thông số và bài báo thể thao chính thống gần nhất.</p>
                </div>
            </div>`;
    }
    tagsContainer.innerHTML = tagsHtml;

    // SECTION: THỐNG KÊ CHI TIẾT & ĐIỂM SỐ CÁ NHÂN (OPTICAL METRICS / FOTMOB / NBA STATS)
    const detailedContainer = document.getElementById('modalDetailedStatsContainer');
    const sourceBadge = document.getElementById('modalDetailedStatsSource');
    const specialRatingsRow = document.getElementById('modalSpecialRatingsRow');
    const metricsGrid = document.getElementById('modalMetricsGrid');

    const dtStats = customMatch ? customMatch.detailed_stats : (player.detailed_stats || (player.details && player.details.detailed_stats));

    if (detailedContainer && dtStats && dtStats.metrics && dtStats.metrics.length > 0) {
        detailedContainer.classList.remove('hidden');
        if (sourceBadge) {
            sourceBadge.innerText = dtStats.source || 'Chuyên trang thể thao';
        }

        // Render ratings row (e.g. FotMob Rating)
        if (specialRatingsRow) {
            let rHtml = '';
            if (dtStats.fotmob_rating) {
                const fmR = Number(dtStats.fotmob_rating);
                let fmBg = 'bg-emerald-950/80 border-emerald-700/60 text-emerald-300';
                if (fmR < 6.5) fmBg = 'bg-rose-950/80 border-rose-700/60 text-rose-300';
                else if (fmR < 7.2) fmBg = 'bg-amber-950/80 border-amber-700/60 text-amber-300';

                rHtml += `
                    <div class="px-3 py-1.5 rounded-lg border ${fmBg} flex items-center gap-2 text-xs font-semibold">
                        <span>⭐ FotMob Rating:</span>
                        <span class="font-bold text-sm font-mono">${fmR.toFixed(1)} / 10</span>
                    </div>`;
            }
            specialRatingsRow.innerHTML = rHtml;
            if (!rHtml) specialRatingsRow.classList.add('hidden');
            else specialRatingsRow.classList.remove('hidden');
        }

        // Render metrics grid
        if (metricsGrid) {
            metricsGrid.innerHTML = dtStats.metrics.map(met => {
                const isHighlight = met.highlight;
                const borderClass = isHighlight ? 'border-indigo-600/60 bg-indigo-950/30' : 'border-gray-800/80 bg-gray-900/60';
                const labelColor = isHighlight ? 'text-indigo-300 font-semibold' : 'text-gray-400';
                const valColor = isHighlight ? 'text-amber-300 font-bold' : 'text-gray-200 font-medium';

                return `
                    <div class="p-2.5 rounded-lg border ${borderClass} flex items-center justify-between gap-2">
                        <span class="${labelColor} truncate">${escapeHtml(met.label)}:</span>
                        <span class="${valColor} font-mono shrink-0 text-right">${escapeHtml(met.value)}</span>
                    </div>`;
            }).join('');
        }
    } else if (detailedContainer) {
        detailedContainer.classList.add('hidden');
    }

    // SECTION: THÔNG TIN CHẤN THƯƠNG & THỂ LỰC (DÀNH CHO TẤT CẢ CÁC MÔN)
    const injurySec = document.getElementById('modalInjurySection');
    const injuryIcon = document.getElementById('modalInjuryIcon');
    const injuryTitle = document.getElementById('modalInjuryTitle');
    const injuryBadge = document.getElementById('modalInjuryBadge');
    const injuryDetails = document.getElementById('modalInjuryDetails');

    if (injurySec && injuryDetails) {
        if (player.entity_type === 'national_team') {
            injurySec.classList.add('hidden');
        } else {
            let inj = (player.details && player.details.injury) ? player.details.injury : player.injury;
        
        if (!inj || !inj.has_injury) {
            const rawInjTag = tagsList.find(t => {
                const low = t.toLowerCase();
                return low.includes('chấn thương') || low.includes('questionable') || low.includes('probable') ||
                       low.includes('doubtful') || low.includes('day-to-day') || low.includes('-day il') ||
                       low.includes('out for season') || low.includes('nghi ngờ') || low.includes('đau nhẹ');
            });
            if (rawInjTag) {
                let lbl = rawInjTag;
                let tip = '';
                if (rawInjTag.includes('::')) {
                    const p = rawInjTag.split('::');
                    lbl = p[0].trim();
                    tip = p[1].trim();
                }
                inj = {
                    has_injury: true,
                    tag_label: lbl,
                    tooltip: tip || `Tình trạng chấn thương: ${lbl}`,
                    severity: tip || lbl,
                    status: lbl,
                    injury_desc: tip || 'Đang theo dõi y tế / điều trị phục hồi',
                    return_date: 'Đang cập nhật'
                };
            }
        }

        if (inj && inj.has_injury) {
            injurySec.classList.remove('hidden');
            const isSevere = inj.is_severe || /season|60|out|phẫu thuật|dài hạn|il/i.test(inj.status || '') || /il/i.test(inj.tag_label || '');
            if (isSevere) {
                injurySec.className = "rounded-xl p-4 border bg-rose-950/40 border-rose-800/80 text-rose-200 shadow-lg shadow-rose-950/30 transition-all";
                if (injuryIcon) injuryIcon.innerText = "🚨";
                if (injuryTitle) injuryTitle.className = "text-rose-300 font-bold";
                if (injuryBadge) injuryBadge.className = "text-[11px] px-2.5 py-0.5 rounded-full font-bold bg-rose-900/90 text-rose-200 border border-rose-700";
            } else {
                injurySec.className = "rounded-xl p-4 border bg-amber-950/40 border-amber-700/80 text-amber-200 shadow-lg shadow-amber-950/30 transition-all";
                if (injuryIcon) injuryIcon.innerText = "⚠️";
                if (injuryTitle) injuryTitle.className = "text-amber-300 font-bold";
                if (injuryBadge) injuryBadge.className = "text-[11px] px-2.5 py-0.5 rounded-full font-bold bg-amber-900/90 text-amber-200 border border-amber-600";
            }
            if (injuryBadge) injuryBadge.innerText = inj.tag_label || inj.status || 'Chấn thương';

            let descText = inj.injury_desc || inj.injury_type || 'Đang trong quá trình hồi phục y tế';
            if (inj.side) descText += ` (bên ${inj.side.toLowerCase()})`;
            if (inj.injury_detail && !descText.includes(inj.injury_detail)) descText += ` - ${inj.injury_detail}`;

            let detailHtml = `
                <div class="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-2">
                    <div class="bg-black/40 p-2.5 rounded-lg border border-white/5">
                        <span class="text-[10px] uppercase font-semibold text-gray-400 block mb-0.5">Vấn đề / Loại chấn thương</span>
                        <span class="font-medium text-white">${escapeHtml(descText)}</span>
                    </div>
                    <div class="bg-black/40 p-2.5 rounded-lg border border-white/5">
                        <span class="text-[10px] uppercase font-semibold text-gray-400 block mb-0.5">Mức độ & Khả năng ra sân</span>
                        <span class="font-medium text-white">${escapeHtml(inj.severity || inj.status || 'Nghỉ thi đấu')}</span>
                    </div>
                </div>
            `;
            if (inj.return_date) {
                detailHtml += `
                    <div class="mt-2 bg-black/40 p-2.5 rounded-lg border border-white/5 flex items-center justify-between">
                        <div>
                            <span class="text-[10px] uppercase font-semibold text-gray-400 block">Dự kiến ngày tái xuất</span>
                            <span class="font-bold text-emerald-400">${escapeHtml(inj.return_date)}</span>
                        </div>
                        <span class="text-[11px] text-gray-400 italic">Báo cáo y tế chính thức</span>
                    </div>
                `;
            }
            injuryDetails.innerHTML = detailHtml;
        } else {
            injurySec.classList.remove('hidden');
            injurySec.className = "rounded-xl p-3 border bg-emerald-950/25 border-emerald-800/60 text-emerald-300 transition-all";
            if (injuryIcon) injuryIcon.innerText = "🟢";
            if (injuryTitle) injuryTitle.className = "text-emerald-400 font-bold";
            if (injuryBadge) {
                injuryBadge.className = "text-[11px] px-2.5 py-0.5 rounded-full font-bold bg-emerald-900/60 text-emerald-200 border border-emerald-700/60";
                injuryBadge.innerText = "Khỏe mạnh";
            }
            injuryDetails.innerHTML = `
                <div class="text-xs text-gray-300 flex items-center gap-2 mt-1">
                    <span>Thể lực hoàn toàn đảm bảo, sẵn sàng ra sân thi đấu (không có báo cáo chấn thương hiện tại).</span>
                </div>
            `;
        }
        }
    }

    // SECTION: UPCOMING SCHEDULE (CHỈ HIỂN THỊ LỊCH 30 NGÀY TỚI ĐỂ GỌN GÀNG, KHÔNG DÀI CẢ MÙA)
    const upcoming30d = (player.details && player.details.upcoming_matches_30d) ? player.details.upcoming_matches_30d : [];
    const schedList = (upcoming30d && upcoming30d.length > 0)
        ? upcoming30d
        : ((player.details && player.details.all_upcoming_matches)
            ? player.details.all_upcoming_matches.filter(m => (m.diff_days >= 0 && m.diff_days <= 30))
            : []);
    const modalSchedCount = document.getElementById('modalScheduleCount');
    const modalSchedList = document.getElementById('modalScheduleList');
    if (modalSchedCount && modalSchedList) {
        modalSchedCount.innerText = `${schedList.length} trận`;
        if (schedList.length > 0) {
            modalSchedList.innerHTML = schedList.map((m, idx) => `
                <div class="flex items-center justify-between p-2.5 rounded-lg bg-gray-900/80 border border-gray-800/80 text-xs">
                    <div class="flex items-center gap-2.5 min-w-0 flex-1">
                        <span class="w-5 h-5 rounded-full bg-blue-950 border border-blue-800 text-blue-400 font-mono text-[10px] flex items-center justify-center shrink-0">${idx + 1}</span>
                        <div class="min-w-0 flex-1">
                            <span class="font-semibold text-gray-200 block truncate" title="${escapeHtml(m.match_name)}">${escapeHtml(getOpponentName(m.match_name, player.team))}</span>
                            <span class="text-[10px] text-gray-500 block truncate">${escapeHtml(m.competition || 'Giải đấu')}</span>
                        </div>
                    </div>
                    <div class="text-right shrink-0 ml-3">
                        <span class="text-emerald-400 font-mono font-medium block">${escapeHtml(m.date_full_vn || m.date_vn)}</span>
                        <span class="text-[10px] text-gray-500 font-mono">Giờ VN (UTC+7)</span>
                    </div>
                </div>
            `).join('');
        } else {
            modalSchedList.innerHTML = `
                <div class="text-xs text-gray-500 italic py-2 text-center">
                    Không có lịch thi đấu chính thức trong 30 ngày sắp tới.
                </div>`;
        }
    }

    // Modal News: If customMatch has news, use match news window (yesterday 00:00 to match day 23:59:59), else player.details.news
    window.currentModalNews = (customMatch && customMatch.news) ? customMatch.news : ((player.details && player.details.news) ? player.details.news : []);
    selectedNewsCategories.clear();
    renderModalNews();

    const apiMeta = document.getElementById('modalApiMeta');
    if (apiMeta) apiMeta.innerText = player.api_player_id ? `API ID: ${player.api_player_id}` : '';
    document.getElementById('detailModal').classList.remove('hidden');
}

function toggleNewsCategoryFilter(catId) {
    if (catId === 'all') {
        selectedNewsCategories.clear();
    } else {
        if (selectedNewsCategories.has(catId)) {
            selectedNewsCategories.delete(catId);
        } else {
            selectedNewsCategories.add(catId);
        }
        if (selectedNewsCategories.size === 5) {
            selectedNewsCategories.clear();
        }
    }
    renderModalNews();
}

function renderModalNews() {
    const player = window.currentModalPlayer;
    if (!player) return;
    const allNews = window.currentModalNews || ((player.details && player.details.news) ? player.details.news : []);

    const normalizedNews = allNews.map(n => {
        let t = n.news_type;
        if (t === 'transfer_rumor') t = 'transfer';
        if (!NEWS_CATEGORIES[t]) t = 'side_news';
        return { ...n, type: t };
    });

    const counts = { all: normalizedNews.length, match: 0, transfer: 0, statement: 0, analysis: 0, side_news: 0 };
    normalizedNews.forEach(n => {
        if (counts[n.type] !== undefined) counts[n.type]++;
        else counts.side_news++;
    });

    const isAll = selectedNewsCategories.size === 0;

    const tabsContainer = document.getElementById('modalNewsFilterTabs');
    if (tabsContainer) {
        const catOrder = [
            { id: 'all', label: 'Tất cả', icon: '📑' },
            { id: 'match', label: 'Thi đấu', icon: '⚽' },
            { id: 'transfer', label: 'Chuyển nhượng', icon: '🔄' },
            { id: 'statement', label: 'Phát biểu', icon: '🎙️' },
            { id: 'analysis', label: 'Chuyên môn', icon: '📊' },
            { id: 'side_news', label: 'Bên lề', icon: '📰' }
        ];

        tabsContainer.innerHTML = catOrder.map(c => {
            const count = counts[c.id] || 0;
            const isSelected = (c.id === 'all') ? isAll : selectedNewsCategories.has(c.id);
            const activeClass = isSelected 
                ? 'bg-blue-600 text-white border-blue-400 font-semibold shadow-md ring-2 ring-blue-500/30'
                : 'bg-gray-900/90 hover:bg-gray-800 text-gray-400 hover:text-gray-200 border-gray-800';
            const checkIcon = (!isAll && isSelected) ? '<span class="text-[10px] text-emerald-300 font-bold">✓</span> ' : '';

            return `
                <button type="button" onclick="toggleNewsCategoryFilter('${c.id}')"
                    class="px-3 py-1.5 text-xs rounded-lg border transition duration-150 flex items-center gap-1.5 cursor-pointer active:scale-95 ${activeClass}"
                    title="${c.id === 'all' ? 'Hiển thị tất cả bài báo' : 'Bấm để chọn/bỏ chọn (chọn được nhiều danh mục cùng lúc)'}">
                    <span>${c.icon}</span>
                    <span>${checkIcon}${c.label}</span>
                    <span class="text-[10px] px-1.5 py-0.2 rounded-full font-mono ${isSelected ? 'bg-blue-800 text-white' : 'bg-gray-800 text-gray-400'}">${count}</span>
                </button>
            `;
        }).join('');
    }

    const filteredNews = isAll
        ? normalizedNews
        : normalizedNews.filter(n => selectedNewsCategories.has(n.type));

    const newsContainer = document.getElementById('modalNewsContainer');
    const newsCount = document.getElementById('modalNewsCount');
    if (newsCount) {
        if (isAll) {
            newsCount.innerText = `${allNews.length} bài báo (24h)`;
        } else {
            const names = Array.from(selectedNewsCategories)
                .map(c => NEWS_CATEGORIES[c] ? NEWS_CATEGORIES[c].label : c)
                .join(' + ');
            newsCount.innerText = `${filteredNews.length}/${allNews.length} bài (${names})`;
        }
    }

    if (filteredNews.length > 0) {
        newsContainer.innerHTML = filteredNews.map(n => {
            const regionInfo = REGION_FLAGS[n.region] || { flag: '🌐', label: 'Báo Quốc Tế' };
            const catInfo = NEWS_CATEGORIES[n.type] || NEWS_CATEGORIES.side_news;
            const typeBadge = `<span class="${catInfo.color} border text-[10px] px-2 py-0.5 rounded font-semibold inline-flex items-center gap-1">${catInfo.icon} ${catInfo.label}</span>`;

            return `
                <a href="${escapeHtml(n.url)}" target="_blank" rel="noopener noreferrer" 
                    class="group block p-3.5 rounded-xl bg-gray-950/80 hover:bg-gray-950 border border-gray-800 hover:border-blue-500/60 transition duration-150">
                    <div class="flex items-start gap-3">
                        <span class="text-2xl select-none" title="${regionInfo.label}">${regionInfo.flag}</span>
                        <div class="flex-1 min-w-0">
                            <span class="text-sm font-medium text-blue-400 group-hover:text-blue-300 group-hover:underline line-clamp-2 leading-relaxed">
                                ${escapeHtml(n.title)}
                            </span>
                            <div class="flex items-center gap-2 mt-1.5">
                                <span class="text-[11px] text-gray-400">${regionInfo.label}</span>
                                ${typeBadge}
                            </div>
                        </div>
                        <span class="text-gray-500 group-hover:text-blue-400 text-xs">🔗</span>
                    </div>
                </a>`;
        }).join('');
    } else {
        newsContainer.innerHTML = `
            <div class="p-4 rounded-xl bg-gray-950/50 border border-gray-800 text-center text-gray-500 text-xs italic">
                Không tìm thấy bài báo nào trong 24 giờ qua thuộc phân mục đã chọn.
            </div>`;
    }
}

async function copyAllNewsLinks() {
    if (!window.currentModalPlayer) return;
    const player = window.currentModalPlayer;
    let newsList = (player.details && player.details.news) ? player.details.news : [];
    if (selectedNewsCategories.size > 0) {
        newsList = newsList.filter(n => {
            let t = n.news_type;
            if (t === 'transfer_rumor') t = 'transfer';
            if (!NEWS_CATEGORIES[t]) t = 'side_news';
            return selectedNewsCategories.has(t);
        });
    }
    const validUrls = newsList.map(n => n.url).filter(Boolean);
    if (validUrls.length === 0) {
        showToast("Không có bài báo nào để sao chép liên kết!", "warning");
        return;
    }

    const copyBtn = document.getElementById('btnCopyNewsLinksBottom');
    const copyLabel = document.getElementById('copyBtnLabel');
    const copyIcon = document.getElementById('copyIcon');
    
    if (copyBtn) copyBtn.disabled = true;
    if (copyIcon) copyIcon.innerText = "⏳";
    if (copyLabel) copyLabel.innerText = "Đang giải mã URL cho NotebookLM...";

    let finalUrls = validUrls;
    try {
        const res = await fetch('/api/news/decode-urls', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ urls: validUrls })
        });
        if (res.ok) {
            const data = await res.json();
            if (data.decoded_urls && data.decoded_urls.length > 0) {
                finalUrls = data.decoded_urls;
            }
        }
    } catch (e) {
        console.warn("Decode failed, fallback to raw urls", e);
    } finally {
        if (copyBtn) copyBtn.disabled = false;
        if (copyIcon) copyIcon.innerText = "📋";
        if (copyLabel) copyLabel.innerText = "Copy link báo cho NotebookLM";
    }

    const textToCopy = finalUrls.join('\n');
    navigator.clipboard.writeText(textToCopy).then(() => {
        showToast(`Đã sao chép thành công ${finalUrls.length} liên kết gốc cho NotebookLM!`, "success");
    }).catch(err => {
        const textarea = document.createElement("textarea");
        textarea.value = textToCopy;
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.select();
        try {
            document.execCommand("copy");
            showToast(`Đã sao chép thành công ${finalUrls.length} liên kết gốc cho NotebookLM!`, "success");
        } catch (e) {
            showToast("Không thể sao chép liên kết vào clipboard.", "error");
        }
        document.body.removeChild(textarea);
    });
}

function closeModal() {
    document.getElementById('detailModal').classList.add('hidden');
}

function handleBackdropClick(event) {
    if (event.target === document.getElementById('detailModal')) closeModal();
}

function openAddPlayerModal() {
    document.getElementById('inputPlayerName').value = '';
    document.getElementById('addPlayerModal').classList.remove('hidden');
    setTimeout(() => document.getElementById('inputPlayerName').focus(), 100);
}

function closeAddPlayerModal() {
    document.getElementById('addPlayerModal').classList.add('hidden');
}

function handleAddBackdropClick(event) {
    if (event.target === document.getElementById('addPlayerModal')) closeAddPlayerModal();
}

function setPlayerName(name) {
    document.getElementById('inputPlayerName').value = name;
}

async function deletePlayer(event, playerId, playerName) {
    if (event) event.stopPropagation();
    if (!confirm(`Bạn có chắc chắn muốn xóa "${playerName}" khỏi cơ sở dữ liệu không?`)) {
        return;
    }
    try {
        let url = `/api/players/${playerId}`;
        if (typeof playerId === 'string' && playerId.startsWith('nt_')) {
            const teamDbId = playerId.replace('nt_', '');
            url = `/api/national-teams/${teamDbId}`;
        }
        const res = await fetch(url, { method: 'DELETE' });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message || `Đã xóa "${playerName}" thành công!`, 'success');
            await loadDashboard();
        } else {
            showToast(data.detail || 'Không thể xóa.', 'error');
        }
    } catch (err) {
        showToast("Lỗi khi kết nối để xóa.", 'error');
    }
}

async function syncAllPlayersData() {
    const syncBtn = document.getElementById('syncBtn');
    const syncSpinner = document.getElementById('syncSpinner');
    const syncIcon = document.getElementById('syncIcon');
    
    syncSpinner.classList.remove('hidden');
    syncIcon.classList.add('hidden');
    syncBtn.disabled = true;
    showToast("Đang đồng bộ lại câu lạc bộ, lịch thi đấu và quét tin tức 24h...", "info");

    try {
        const res = await fetch('/api/players/sync', { method: 'POST' });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast(data.message || "Đã đồng bộ dữ liệu thành công!", "success");
            await loadDashboard(true);
        } else {
            showToast(data.detail || data.message || "Có lỗi khi đồng bộ dữ liệu.", "error");
        }
    } catch (err) {
        showToast("Lỗi kết nối khi đồng bộ dữ liệu.", "error");
    } finally {
        syncSpinner.classList.add('hidden');
        syncIcon.classList.remove('hidden');
        syncBtn.disabled = false;
    }
}

window.addPlayerQueue = [];
window.addPlayerTotal = 0;
window.currentDisambigCandidate = null;
window._currentCandidateList = [];

async function submitAddPlayer(event) {
    if (event) event.preventDefault();
    const rawInput = document.getElementById('inputPlayerName').value.trim();
    if (!rawInput) return;

    const names = rawInput.split(/[\n,;]+/).map(s => s.trim()).filter(Boolean);
    if (names.length === 0) return;

    window.addPlayerQueue = names;
    window.addPlayerTotal = names.length;

    await processNextPlayerInQueue();
}

async function processNextPlayerInQueue() {
    const box = document.getElementById('disambiguationBox');
    const inputSection = document.getElementById('inputFormSection');
    const submitBtn = document.getElementById('submitBtn');
    const spinner = document.getElementById('submitSpinner');
    const btnText = document.getElementById('submitBtnText');

    if (window.addPlayerQueue.length === 0) {
        box.classList.add('hidden');
        inputSection.classList.remove('hidden');
        submitBtn.classList.remove('hidden');
        submitBtn.disabled = false;
        spinner.classList.add('hidden');
        btnText.innerText = "Tìm Kiếm & Thêm";
        closeAddPlayerModal();
        showToast("Đã hoàn tất quy trình thêm cầu thủ!", "success");
        await loadDashboard();
        return;
    }

    const currentQuery = window.addPlayerQueue.shift();
    const currentIdx = window.addPlayerTotal - window.addPlayerQueue.length;
    
    submitBtn.disabled = true;
    spinner.classList.remove('hidden');
    btnText.innerText = `Đang tìm "${currentQuery}" (${currentIdx}/${window.addPlayerTotal})...`;

    try {
        const res = await fetch(`/api/players/candidates?query=${encodeURIComponent(currentQuery)}`);
        const data = await res.json();
        const candidates = data.candidates || [];

        if (data.has_ambiguity && candidates.length > 1) {
            box.classList.remove('hidden');
            inputSection.classList.add('hidden');
            submitBtn.classList.add('hidden');

            document.getElementById('disambigQueryName').innerText = currentQuery;
            document.getElementById('disambigProgressBadge').innerText = `${currentIdx}/${window.addPlayerTotal}`;
            
            window.currentDisambigCandidate = candidates[0];
            window._currentCandidateList = candidates;

            const listEl = document.getElementById('disambigList');
            listEl.innerHTML = candidates.map((c, i) => `
                <div class="p-3 bg-gray-900 border border-gray-800 hover:border-blue-500/80 rounded-xl flex items-center justify-between gap-3 transition">
                    <div class="min-w-0 flex-1">
                        <div class="flex items-center gap-2 flex-wrap">
                            <span class="font-bold text-white text-sm truncate">${escapeHtml(c.name)}</span>
                            <span class="text-xs bg-blue-950 text-blue-300 border border-blue-800/60 px-2 py-0.5 rounded font-medium">${escapeHtml(c.sport)}</span>
                            <span class="text-xs bg-gray-800 text-gray-300 px-1.5 py-0.5 rounded">${escapeHtml(c.country_flag || '🌐')} ${escapeHtml(c.country)}</span>
                        </div>
                        <div class="text-xs text-gray-400 mt-1 truncate">
                            CLB: <span class="text-emerald-400 font-medium">${escapeHtml(c.team || 'Tự do')}</span>
                            ${c.snippet ? ` • <span class="text-gray-500 italic">${escapeHtml(c.snippet)}</span>` : ''}
                        </div>
                    </div>
                    <button type="button" onclick="confirmSelectCandidate(${i})" 
                        class="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold rounded-lg shrink-0 transition shadow-sm active:scale-95 cursor-pointer">
                        Chọn VĐV này
                    </button>
                </div>
            `).join('');
        } else if (candidates.length >= 1) {
            await addConfirmedCandidate(candidates[0]);
            await processNextPlayerInQueue();
        } else {
            await fallbackAddPlayer(currentQuery);
            await processNextPlayerInQueue();
        }
    } catch (err) {
        console.error("Error searching candidate:", err);
        await fallbackAddPlayer(currentQuery);
        await processNextPlayerInQueue();
    }
}

async function confirmSelectCandidate(index) {
    if (window._currentCandidateList && window._currentCandidateList[index]) {
        const candidate = window._currentCandidateList[index];
        await addConfirmedCandidate(candidate);
        
        const box = document.getElementById('disambiguationBox');
        const inputSection = document.getElementById('inputFormSection');
        const submitBtn = document.getElementById('submitBtn');
        box.classList.add('hidden');
        inputSection.classList.remove('hidden');
        submitBtn.classList.remove('hidden');

        await processNextPlayerInQueue();
    }
}

async function addConfirmedCandidate(cand) {
    showToast(`Đang thêm ${cand.name} và cập nhật lịch đấu...`, 'info');
    try {
        const res = await fetch('/api/players/add-confirmed', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: cand.name,
                team: cand.team || 'Tự do',
                sport: cand.sport || 'Môn khác',
                country: cand.country || 'Quốc tế',
                aliases: cand.aliases || cand.name
            })
        });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message || `Đã thêm ${cand.name} thành công!`, 'success');
        } else {
            showToast(data.detail || `Không thể thêm ${cand.name}`, 'error');
        }
    } catch (e) {
        showToast(`Lỗi kết nối khi thêm ${cand.name}`, 'error');
    }
}

async function fallbackAddPlayer(playerName) {
    showToast(`Đang quét dữ liệu cho "${playerName}"...`, 'info');
    try {
        const res = await fetch('/api/players/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ player_name: playerName })
        });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message || `Đã thêm thành công!`, 'success');
        } else {
            showToast(data.detail || `Không tìm thấy thông tin cho "${playerName}".`, 'error');
        }
    } catch (err) {
        showToast(`Lỗi kết nối khi thêm "${playerName}".`, 'error');
    }
}

function skipCandidateItem() {
    const box = document.getElementById('disambiguationBox');
    const inputSection = document.getElementById('inputFormSection');
    const submitBtn = document.getElementById('submitBtn');
    box.classList.add('hidden');
    inputSection.classList.remove('hidden');
    submitBtn.classList.remove('hidden');
    processNextPlayerInQueue();
}

function promptCustomTeam() {
    if (!window.currentDisambigCandidate) return;
    const cand = window.currentDisambigCandidate;
    const customTeam = prompt(`Nhập tên đội bóng / CLB chính xác cho "${cand.name}":`, cand.team || "");
    if (customTeam !== null && customTeam.trim()) {
        cand.team = customTeam.trim();
        addConfirmedCandidate(cand).then(() => {
            const box = document.getElementById('disambiguationBox');
            const inputSection = document.getElementById('inputFormSection');
            const submitBtn = document.getElementById('submitBtn');
            box.classList.add('hidden');
            inputSection.classList.remove('hidden');
            submitBtn.classList.remove('hidden');
            processNextPlayerInQueue();
        });
    }
}

function showToast(msg, type = 'success') {
    const toast = document.getElementById('toastAlert');
    const toastMsg = document.getElementById('toastMsg');
    toastMsg.innerText = msg;
    if (type === 'success') {
        toast.className = "mb-4 p-3.5 rounded-lg text-sm flex items-center justify-between transition-all bg-emerald-950/80 border border-emerald-800 text-emerald-200";
    } else {
        toast.className = "mb-4 p-3.5 rounded-lg text-sm flex items-center justify-between transition-all bg-red-950/80 border border-red-800 text-red-200";
    }
    toast.classList.remove('hidden');
    setTimeout(() => hideToast(), 5000);
}

function hideToast() {
    document.getElementById('toastAlert').classList.add('hidden');
}

document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') {
        closeModal();
        closeAddPlayerModal();
    }
});

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

async function initApp() {
    // 1. Render immediately from cached database so UI appears with zero delay
    await loadDashboard(true);

    // 2. Automatically sync in background on initial page load / visit if more than 5 minutes since last sync
    const lastSync = localStorage.getItem('last_auto_sync_ts');
    const now = Date.now();
    const shouldSync = !lastSync || (now - parseInt(lastSync, 10)) > 5 * 60 * 1000;

    if (shouldSync) {
        setTimeout(async () => {
            console.log('[Auto-Sync] Tự động cập nhật kết quả và tin tức realtime...');
            const syncSpinner = document.getElementById('syncSpinner');
            const syncIcon = document.getElementById('syncIcon');
            if (syncSpinner && syncIcon) {
                syncSpinner.classList.remove('hidden');
                syncIcon.classList.add('hidden');
            }

            try {
                const res = await fetch('/api/players/sync', { method: 'POST' });
                if (res.ok) {
                    localStorage.setItem('last_auto_sync_ts', Date.now().toString());
                    await loadDashboard(false);
                }
            } catch (e) {
                console.warn('[Auto-Sync Error]', e);
            } finally {
                if (syncSpinner && syncIcon) {
                    syncSpinner.classList.add('hidden');
                    syncIcon.classList.remove('hidden');
                }
            }
        }, 3000);
    }
}

window.onload = initApp;

// ==========================================
// THÊM THEO DÕI: VẬN ĐỘNG VIÊN & ĐỘI TUYỂN / ĐỘI TRẺ
// ==========================================
function openAddModal() {
    const modal = document.getElementById('addPlayerModal');
    if (!modal) return;
    modal.classList.remove('hidden');
    switchAddModalTab('player');
    const input = document.getElementById('inputPlayerName');
    if (input) {
        input.value = '';
        setTimeout(() => input.focus(), 100);
    }
}

function openAddPlayerModal() {
    openAddModal();
}

function switchAddModalTab(tab) {
    const playerTabBtn = document.getElementById('modalTabPlayerBtn');
    const nationalTabBtn = document.getElementById('modalTabNationalBtn');
    const playerSec = document.getElementById('addPlayerTabSection');
    const nationalSec = document.getElementById('addNationalTabSection');

    if (tab === 'player') {
        if (playerTabBtn) playerTabBtn.className = "px-3.5 py-1.5 rounded-lg text-xs font-bold transition bg-blue-600 text-white shadow-sm";
        if (nationalTabBtn) nationalTabBtn.className = "px-3.5 py-1.5 rounded-lg text-xs font-semibold transition text-gray-400 hover:text-gray-200";
        if (playerSec) playerSec.classList.remove('hidden');
        if (nationalSec) nationalSec.classList.add('hidden');
    } else {
        if (nationalTabBtn) nationalTabBtn.className = "px-3.5 py-1.5 rounded-lg text-xs font-bold transition bg-blue-600 text-white shadow-sm";
        if (playerTabBtn) playerTabBtn.className = "px-3.5 py-1.5 rounded-lg text-xs font-semibold transition text-gray-400 hover:text-gray-200";
        if (nationalSec) nationalSec.classList.remove('hidden');
        if (playerSec) playerSec.classList.add('hidden');
        loadNationalCatalog();
    }
}

window.nationalCatalogData = [];

async function loadNationalCatalog() {
    const container = document.getElementById('nationalCatalogList');
    if (!container) return;
    container.innerHTML = `<div class="py-8 text-center text-xs text-gray-400"><span class="animate-spin inline-block mr-2 text-base">🔄</span>Đang tải danh mục đội tuyển chính thức...</div>`;
    try {
        const res = await fetch('/api/national-teams/catalog');
        if (!res.ok) throw new Error('Không thể tải catalog');
        window.nationalCatalogData = await res.json();
        renderNationalCatalog(window.nationalCatalogData);
    } catch (err) {
        container.innerHTML = `<div class="py-6 text-center text-xs text-rose-400">Không thể tải danh mục. Vui lòng thử lại.</div>`;
    }
}

function renderNationalCatalog(list) {
    const container = document.getElementById('nationalCatalogList');
    const countBadge = document.getElementById('catalogCountBadge');
    if (countBadge) countBadge.innerText = `${list.length} đội`;
    if (!container) return;

    if (!list || list.length === 0) {
        container.innerHTML = `<div class="py-8 text-center text-xs text-gray-500">Không tìm thấy đội tuyển phù hợp với từ khóa.</div>`;
        return;
    }

    container.innerHTML = list.map(item => {
        const isAdded = item.is_added;
        const tierBadge = item.tier === 'Senior' ? 'ĐTQG' : item.tier;
        return `
            <div class="flex items-center justify-between p-3 rounded-xl bg-gray-950/80 border border-gray-800 hover:border-gray-700 transition">
                <div class="flex items-center gap-2.5 min-w-0 flex-1">
                    <span class="text-xl shrink-0">${item.flag || '🌐'}</span>
                    <div class="min-w-0 flex-1">
                        <div class="flex items-center gap-1.5 flex-wrap">
                            <span class="font-bold text-xs text-white truncate">${escapeHtml(item.name)}</span>
                            <span class="text-[10px] px-1.5 py-0.5 rounded font-bold bg-amber-950/80 text-amber-300 border border-amber-800">${escapeHtml(tierBadge)}</span>
                        </div>
                        <div class="text-[11px] text-gray-400 mt-0.5 truncate">
                            <span>${escapeHtml(item.sport)}</span> • <span>${escapeHtml(item.country)}</span> ${item.nickname ? `• <span class="text-blue-400 font-semibold">${escapeHtml(item.nickname)}</span>` : ''}
                        </div>
                    </div>
                </div>
                <div class="shrink-0 ml-3">
                    ${isAdded ? `
                        <span class="px-2.5 py-1 text-xs font-semibold rounded-lg bg-emerald-950/80 text-emerald-400 border border-emerald-800/80 flex items-center gap-1">
                            <span>✓</span> Đang theo dõi
                        </span>
                    ` : `
                        <button onclick="addTeamFromCatalog('${escapeHtml(item.id_code)}', this)"
                            class="px-3 py-1.5 text-xs font-semibold rounded-lg bg-blue-600 hover:bg-blue-500 text-white shadow-sm flex items-center gap-1 transition active:scale-95 cursor-pointer">
                            <span>➕</span> Thêm
                        </button>
                    `}
                </div>
            </div>
        `;
    }).join('');
}

function onSearchNationalCatalog(query) {
    if (!window.nationalCatalogData) return;
    const q = (query || '').trim().toLowerCase();
    if (!q) {
        renderNationalCatalog(window.nationalCatalogData);
        return;
    }
    const filtered = window.nationalCatalogData.filter(item => {
        const text = `${item.name} ${item.short_name} ${item.nickname} ${item.sport} ${item.country} ${item.tier} ${item.query_native || ''}`.toLowerCase();
        return text.includes(q);
    });
    renderNationalCatalog(filtered);
}

async function addTeamFromCatalog(idCode, btnElem) {
    if (btnElem) {
        btnElem.disabled = true;
        btnElem.innerHTML = `<span class="animate-spin text-xs">🔄</span> Đang thêm...`;
    }
    try {
        const res = await fetch('/api/national-teams/add-from-catalog', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id_code: idCode })
        });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast(`Đã thêm đội tuyển "${data.name}" vào danh sách theo dõi!`, 'success');
            await loadNationalCatalog();
            await loadDashboard(false);
        } else {
            showToast(data.detail || 'Lỗi khi thêm đội tuyển', 'error');
            if (btnElem) {
                btnElem.disabled = false;
                btnElem.innerHTML = `<span>➕</span> Thêm`;
            }
        }
    } catch (err) {
        showToast('Không thể kết nối đến máy chủ', 'error');
        if (btnElem) {
            btnElem.disabled = false;
            btnElem.innerHTML = `<span>➕</span> Thêm`;
        }
    }
}

