const category = document.getElementById('category');
const resolution = document.getElementById('resolution');
const loggerFilter = document.getElementById('loggerFilter');
const loggerFilterButton = document.getElementById('loggerFilterButton');
const loggerFilterMenu = document.getElementById('loggerFilterMenu');
const loggerFilterLabel = document.getElementById('loggerFilterLabel');
const loggerSelectAll = document.getElementById('loggerSelectAll');
const loggerVendorCheckboxes = [...document.querySelectorAll('.logger-vendor-checkbox')];
const periodMode = document.getElementById('periodMode');
const dailyDate = document.getElementById('dailyDate');
const monthDate = document.getElementById('monthDate');
const yearDate = document.getElementById('yearDate');
const dateFrom = document.getElementById('dateFrom');
const dateTo = document.getElementById('dateTo');
const loading = document.getElementById('loading');
const statusLine = document.getElementById('statusLine');
const titleLine = document.getElementById('titleLine');
const table = document.getElementById('monitorTable');
const showBtn = document.getElementById('showBtn');
const downloadBtn = document.getElementById('downloadBtn');
const stationCountMetric = document.getElementById('stationCountMetric');
const warningCountMetric = document.getElementById('warningCountMetric');
const staleWarningMetric = document.getElementById('staleWarningMetric');
const disconnectedMetric = document.getElementById('disconnectedMetric');
const periodMetric = document.getElementById('periodMetric');
const summaryMonitorCategory = document.getElementById('summaryMonitorCategory');
const summaryMonitorResolution = document.getElementById('summaryMonitorResolution');
const summaryMonitorPeriodMode = document.getElementById('summaryMonitorPeriodMode');
const summaryMonitorLogger = document.getElementById('summaryMonitorLogger');
const monitorHydrologyInfo = document.getElementById('monitorHydrologyInfo');
const hourlyPeakBody = document.getElementById('hourlyPeakBody');
const dailyPeakBody = document.getElementById('dailyPeakBody');
const hourlyPeakTable = document.getElementById('hourlyPeakTable');
const dailyPeakTable = document.getElementById('dailyPeakTable');
const hourlyPeakTitle = document.getElementById('hourlyPeakTitle');
const dailyPeakTitle = document.getElementById('dailyPeakTitle');
const downloadHourlyPeakBtn = document.getElementById('downloadHourlyPeakBtn');
const downloadDailyPeakBtn = document.getElementById('downloadDailyPeakBtn');
const rainClassificationLegend = document.getElementById('rainClassificationLegend');
const monitorPeakSummary = document.getElementById('monitorPeakSummary');

let currentBundle = null;
let currentData = null;
let orientation = 'horizontal';
let lastRange = null;

const MONITORING_STATE_KEY = 'hydro.monitoring.state.v2';
const MONITORING_BUNDLE_CACHE_KEY = 'hydro.monitoring.bundle-cache.v4';
const MONITORING_BUNDLE_CACHE_LIMIT = 3;

function readSessionJson(key) {
    try { return JSON.parse(sessionStorage.getItem(key) || 'null'); } catch (_err) { return null; }
}
function writeSessionJson(key, value) {
    try { sessionStorage.setItem(key, JSON.stringify(value)); return true; } catch (_err) { return false; }
}
function readMonitoringState() {
    const value = readSessionJson(MONITORING_STATE_KEY);
    return value && typeof value === 'object' ? value : null;
}
const LOGGER_VENDOR_LABELS = {beacon: 'Beacon', tatonas: 'Tatonas', higertech: 'Higertech', dashindo: 'Dashindo'};
function selectedLoggerVendors() {
    return loggerVendorCheckboxes.filter(el => el.checked).map(el => el.value);
}
function loggerVendorSignature(vendors = selectedLoggerVendors()) {
    return [...vendors].sort().join(',');
}
function syncLoggerFilterUI() {
    const selected = selectedLoggerVendors();
    const allSelected = loggerVendorCheckboxes.length > 0 && selected.length === loggerVendorCheckboxes.length;
    if (loggerSelectAll) {
        loggerSelectAll.checked = allSelected;
        loggerSelectAll.indeterminate = selected.length > 0 && !allSelected;
    }
    const names = selected.map(v => LOGGER_VENDOR_LABELS[v] || v);
    if (loggerFilterLabel) {
        loggerFilterLabel.textContent = allSelected ? 'Semua Logger'
            : selected.length === 0 ? 'Pilih Logger'
                : selected.length <= 2 ? names.join(', ')
                    : `${selected.length} Logger`;
    }
    if (summaryMonitorLogger) {
        summaryMonitorLogger.textContent = allSelected ? 'Semua Logger' : (names.join(', ') || 'Belum dipilih');
    }
    if (showBtn) showBtn.disabled = !category.value || selected.length === 0;
}
function setLoggerMenuOpen(open) {
    if (!loggerFilterMenu || !loggerFilterButton) return;
    loggerFilterMenu.hidden = !open;
    loggerFilterButton.setAttribute('aria-expanded', open ? 'true' : 'false');
}
function saveMonitoringState() {
    const state = {
        category: category.value || '',
        resolution: resolution.value || 'hourly',
        periodMode: periodMode.value || 'custom',
        dailyDate: dailyDate.value || '',
        monthDate: monthDate.value || '',
        yearDate: yearDate.value || '',
        dateFrom: dateFrom.value || '',
        dateTo: dateTo.value || '',
        vendors: selectedLoggerVendors(),
        orientation,
    };
    writeSessionJson(MONITORING_STATE_KEY, state);
}
function monitoringBundleKey(categoryValue, range, vendors = selectedLoggerVendors()) {
    return `${categoryValue}|${range?.[0] || ''}|${range?.[1] || ''}|${loggerVendorSignature(vendors)}`;
}
function cacheMonitoringBundle(bundle) {
    if (!bundle?.category || !bundle?.date_from || !bundle?.date_to) return;
    const cache = readSessionJson(MONITORING_BUNDLE_CACHE_KEY) || {entries: {}};
    cache.entries = cache.entries && typeof cache.entries === 'object' ? cache.entries : {};
    const key = monitoringBundleKey(bundle.category, [bundle.date_from, bundle.date_to], bundle.selected_vendors || selectedLoggerVendors());
    cache.entries[key] = {at: Date.now(), data: bundle};
    const ordered = Object.entries(cache.entries).sort((a, b) => (b[1]?.at || 0) - (a[1]?.at || 0));
    cache.entries = Object.fromEntries(ordered.slice(0, MONITORING_BUNDLE_CACHE_LIMIT));
    const text = JSON.stringify(cache);
    if (text.length <= 3_500_000) {
        try { sessionStorage.setItem(MONITORING_BUNDLE_CACHE_KEY, text); } catch (_err) {}
    }
}
function getCachedMonitoringBundle(categoryValue, range) {
    if (!categoryValue || !range) return null;
    const cache = readSessionJson(MONITORING_BUNDLE_CACHE_KEY);
    return cache?.entries?.[monitoringBundleKey(categoryValue, range, selectedLoggerVendors())]?.data || null;
}
function dropCategoryPlaceholder() {
    const placeholder = category.querySelector('option[value=""]');
    if (placeholder) placeholder.remove();
}
function roundRain(value) {
    return Math.round((Number(value) + Number.EPSILON) * 10) / 10;
}
function displayNumber(value) {
    if (value === null || value === undefined || value === '' || !Number.isFinite(Number(value))) return null;
    return category.value === 'rain' ? roundRain(value) : Number(value);
}
function rainClassification(kind, rawValue) {
    if (category.value !== 'rain' || !Number.isFinite(Number(rawValue))) return null;
    const value = roundRain(rawValue);
    if (kind === 'hourly') {
        if (value >= 1 && value < 5) return {key: 'light', color: '#00DE20'};
        if (value >= 5 && value < 10) return {key: 'moderate', color: '#FDF900'};
        if (value >= 10 && value < 20) return {key: 'heavy', color: '#FD9500'};
        if (value >= 20 && value <= 50) return {key: 'very-heavy', color: '#FF0400'};
        if (value > 50) return {key: 'extreme', color: '#EA11F4'};
        return null;
    }
    if (value >= 0.5 && value < 20) return {key: 'light', color: '#00DE20'};
    if (value >= 20 && value < 50) return {key: 'moderate', color: '#FDF900'};
    if (value >= 50 && value < 100) return {key: 'heavy', color: '#FD9500'};
    if (value >= 100 && value <= 150) return {key: 'very-heavy', color: '#FF0400'};
    if (value > 150) return {key: 'extreme', color: '#EA11F4'};
    return null;
}

function rainCellClass(kind, rawValue) {
    const classification = rainClassification(kind, rawValue);
    return classification ? ` rain-class rain-class--${classification.key}` : '';
}

function hydrologicalDayKey(dateObj) {
    if (!(dateObj instanceof Date) || Number.isNaN(dateObj.getTime())) return '';
    const effective = new Date(dateObj);
    if (category.value === 'rain' && effective.getHours() < 7) effective.setDate(effective.getDate() - 1);
    return iso(effective);
}

function longestDailyMissingRun(station, periodKeys) {
    const values = station?.values || [];
    let activeDay = '';
    let currentRun = 0;
    let dailyMax = 0;
    let worstRun = 0;
    for (let index = 0; index < periodKeys.length; index++) {
        const dt = parseIsoDateTime(periodKeys[index]);
        if (!dt) continue;
        const dayKey = hydrologicalDayKey(dt);
        if (dayKey !== activeDay) {
            if (activeDay) worstRun = Math.max(worstRun, dailyMax);
            activeDay = dayKey;
            currentRun = 0;
            dailyMax = 0;
        }
        const value = values[index];
        // Hanya slot tanpa data yang dianggap kosong. Nilai 0.0 tetap valid.
        const missing = value === null || value === undefined || value === '';
        if (missing) {
            currentRun += 1;
            dailyMax = Math.max(dailyMax, currentRun);
        } else {
            currentRun = 0;
        }
    }
    return Math.max(worstRun, dailyMax);
}

function monitoringAvailabilityCounts() {
    const view = currentBundle?.views?.hourly;
    const stations = view?.stations || [];
    const periodKeys = view?.period_keys || [];
    if (!currentBundle || !periodKeys.length) return {success: 0, failed: 0, warning: 0, disconnected: 0};
    let success = 0;
    let failed = 0;
    let warning = 0;
    let disconnected = 0;
    for (const station of stations) {
        if (station?.fetch_failed) {
            failed += 1;
            continue;
        }
        const longestGapHours = longestDailyMissingRun(station, periodKeys);
        if (longestGapHours > 12) disconnected += 1;
        else if (longestGapHours > 6) warning += 1;
        else success += 1;
    }
    // Fallback untuk bundle lama/edge-case vendor yang gagal sebelum station row terbentuk.
    const backendFailed = Number(currentBundle?.failed_count);
    if (Number.isFinite(backendFailed) && backendFailed > failed) failed = backendFailed;
    return {success, failed, warning, disconnected};
}

function applyRainExcelStyle(cell, kind, rawValue) {
    if (!cell || category.value !== 'rain') return;
    cell.z = '0.0';
    const classification = rainClassification(kind, rawValue);
    if (!classification) return;
    cell.s = {
        ...(cell.s || {}),
        fill: {patternType: 'solid', fgColor: {rgb: classification.color.replace('#', '')}},
        font: {color: {rgb: '07111F'}, bold: true},
        alignment: {horizontal: 'right'},
    };
}

const pad2 = window.HydroUI?.pad2 || (n => String(n).padStart(2, '0'));
function iso(d) {
    return window.HydroUI?.isoDate
        ? window.HydroUI.isoDate(d)
        : `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}
function esc(v) {
    return window.HydroUI?.escapeHtml ? window.HydroUI.escapeHtml(v) : String(v ?? '');
}
function todayISO() {
    return iso(new Date());
}
function capToToday(value) {
    const text = String(value || '');
    const today = todayISO();
    return text && text > today ? today : text;
}
function parseIsoDateTime(value) {
    const match = String(value || '').match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?$/);
    if (!match) return null;
    return new Date(
        Number(match[1]),
        Number(match[2]) - 1,
        Number(match[3]),
        Number(match[4] || 0),
        Number(match[5] || 0),
        0,
        0,
    );
}

function initPickers() {
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const prev = new Date(today);
    prev.setDate(prev.getDate() - 1);
    const prev2 = new Date(today);
    prev2.setDate(prev2.getDate() - 2);

    if (window.jQuery && jQuery.fn?.datepicker) {
        const base = window.HydroUI?.datepickerBase
            ? window.HydroUI.datepickerBase({endDate: today})
            : {language: 'id', autoclose: true, todayHighlight: true, orientation: 'bottom auto', endDate: today};
        const $day = $('#dailyDate');
        const $from = $('#dateFrom');
        const $to = $('#dateTo');
        const $month = $('#monthDate');
        const $year = $('#yearDate');
        [$day, $from, $to, $month, $year].forEach($el => {
            try { $el.datepicker('destroy'); } catch (_e) {}
        });
        $day.datepicker({...base, format: 'yyyy-mm-dd'});
        $from.datepicker({...base, format: 'yyyy-mm-dd'}).on('changeDate', e => {
            if (e.date) $to.datepicker('setStartDate', e.date);
        });
        $to.datepicker({...base, format: 'yyyy-mm-dd'}).on('changeDate', e => {
            if (e.date) $from.datepicker('setEndDate', e.date);
        });
        $month.datepicker({...base, format: 'MM yyyy', startView: 'months', minViewMode: 'months'});
        $year.datepicker({...base, format: 'yyyy', startView: 'years', minViewMode: 'years', todayHighlight: false});
        $day.datepicker('setDate', today);
        $from.datepicker('setDate', prev2);
        $to.datepicker('setDate', today);
        $month.datepicker('setDate', prev);
        $year.datepicker('setDate', prev);
    } else {
        dailyDate.value = iso(today);
        dateFrom.value = iso(prev2);
        dateTo.value = iso(today);
        monthDate.value = `${prev.getFullYear()}-${pad2(prev.getMonth() + 1)}`;
        yearDate.value = String(prev.getFullYear());
    }
}

function syncMonitoringSummary() {
    const categoryLabels = {'': 'Pilih Kategori', rain: 'Curah Hujan', tma: 'Tinggi Muka Air'};
    const resolutionLabels = {hourly: 'Jam-Jaman', daily: 'Harian'};
    const periodLabels = {day: 'Harian', month: 'Bulanan', year: 'Tahunan', custom: 'Rentang Tanggal'};
    if (summaryMonitorCategory) summaryMonitorCategory.textContent = categoryLabels[category.value] || category.value;
    if (summaryMonitorResolution) summaryMonitorResolution.textContent = resolutionLabels[resolution.value] || resolution.value;
    if (summaryMonitorPeriodMode) summaryMonitorPeriodMode.textContent = periodLabels[periodMode.value] || periodMode.value;
    syncLoggerFilterUI();
    if (monitorHydrologyInfo) {
        monitorHydrologyInfo.textContent = category.value === 'rain'
            ? 'Curah hujan mengikuti hari hidrologis pukul 07:00–06:59 WIB pada pengolahan harian.'
            : category.value === 'tma'
                ? 'Tinggi muka air ditampilkan sesuai interval data yang tersedia dari masing-masing logger.'
                : 'Pilih kategori data terlebih dahulu, lalu tekan Tampilkan Data.';
    }
    if (rainClassificationLegend) rainClassificationLegend.hidden = category.value !== 'rain';
    if (monitorPeakSummary) monitorPeakSummary.hidden = category.value !== 'rain';
    if (showBtn) showBtn.disabled = !category.value || selectedLoggerVendors().length === 0;
}

function updatePeriodFields() {
    ['dayFields', 'monthFields', 'yearFields', 'customFields'].forEach(id => {
        document.getElementById(id).hidden = true;
    });
    const map = {day: 'dayFields', month: 'monthFields', year: 'yearFields', custom: 'customFields'};
    document.getElementById(map[periodMode.value]).hidden = false;
    syncMonitoringSummary();
}

function parseMonthInput(v) {
    const months = {januari: 0, februari: 1, maret: 2, april: 3, mei: 4, juni: 5, juli: 6, agustus: 7, september: 8, oktober: 9, november: 10, desember: 11};
    let m = String(v || '').trim().toLowerCase().match(/^([a-z]+)\s+(\d{4})$/);
    if (m && months[m[1]] !== undefined) return [Number(m[2]), months[m[1]]];
    m = String(v || '').match(/^(\d{4})-(\d{1,2})$/);
    return m ? [Number(m[1]), Number(m[2]) - 1] : null;
}

function selectedRange() {
    const mode = periodMode.value;
    const today = todayISO();
    if (mode === 'day') {
        if (!dailyDate.value || dailyDate.value > today) return null;
        return [dailyDate.value, dailyDate.value];
    }
    if (mode === 'month') {
        const parsed = parseMonthInput(monthDate.value);
        if (!parsed) return null;
        const [y, m] = parsed;
        const start = iso(new Date(y, m, 1));
        if (start > today) return null;
        return [start, capToToday(iso(new Date(y, m + 1, 0)))];
    }
    if (mode === 'year') {
        const y = Number(String(yearDate.value).match(/\d{4}/)?.[0]);
        if (!y) return null;
        const start = `${y}-01-01`;
        if (start > today) return null;
        return [start, capToToday(`${y}-12-31`)];
    }
    if (!dateFrom.value || !dateTo.value || dateFrom.value > today) return null;
    return [dateFrom.value, capToToday(dateTo.value)];
}

function fmt(v) {
    const numeric = displayNumber(v);
    if (numeric === null) return '<span class="empty">-</span>';
    return numeric.toFixed(category.value === 'rain' ? 1 : 2);
}

function hourlyGroups(periods) {
    const groups = [];
    periods.forEach((p, i) => {
        const [date] = String(p).split(' ');
        const last = groups.at(-1);
        if (last && last.date === date) last.count++;
        else groups.push({date, count: 1, start: i});
    });
    return groups;
}

function renderHorizontal(periods, stations) {
    let html = '';
    if (resolution.value === 'hourly' && periods.length) {
        const groups = hourlyGroups(periods);
        table.classList.add('monitor-hourly');
        html = '<thead><tr><th rowspan="2">Nama Pos</th>'
            + groups.map(g => `<th class="date-group" colspan="${g.count}">${esc(g.date)}</th>`).join('')
            + '</tr><tr>'
            + periods.map(p => `<th>${esc(String(p).split(' ')[1] || '')}</th>`).join('')
            + '</tr></thead><tbody>';
    } else {
        table.classList.remove('monitor-hourly');
        html = '<thead><tr><th>Nama Pos</th>'
            + periods.map(p => `<th>${esc(p)}</th>`).join('')
            + '</tr></thead><tbody>';
    }
    for (const st of stations) {
        html += `<tr><td title="${esc(st.vendor || '')}">${esc(st.name)}</td>`
            + (st.values || []).map(v => `<td class="${rainCellClass(resolution.value, v).trim()}">${fmt(v)}</td>`).join('')
            + '</tr>';
    }
    return html + '</tbody>';
}

function renderVertical(periods, stations, periodKeys = []) {
    table.classList.remove('monitor-hourly');
    const rowPeriods = (category.value === 'rain' && resolution.value === 'hourly' && periodKeys.length === periods.length)
        ? periodKeys
        : periods;
    let html = '<thead><tr><th>Waktu</th>'
        + stations.map(st => `<th title="${esc(st.vendor || '')}">${esc(st.name)}</th>`).join('')
        + '</tr></thead><tbody>';
    rowPeriods.forEach((p, i) => {
        html += `<tr><td>${esc(p)}</td>`
            + stations.map(st => {
                const value = (st.values || [])[i];
                return `<td class="${rainCellClass(resolution.value, value).trim()}">${fmt(value)}</td>`;
            }).join('')
            + '</tr>';
    });
    return html + '</tbody>';
}

function render() {
    if (!currentData) return;
    const periods = currentData.periods || [];
    const stations = currentData.stations || [];
    const keys = currentData.period_keys || [];
    table.innerHTML = (orientation === 'horizontal'
        ? renderHorizontal(periods, stations)
        : renderVertical(periods, stations, keys)) || '<tbody><tr><td>Tidak ada pos.</td></tr></tbody>';
}

function updateTitle() {
    if (!lastRange) return;
    const label = category.value === 'rain' ? 'Curah Hujan' : 'Tinggi Muka Air';
    const resLabel = resolution.value === 'hourly' ? 'Jam-Jaman' : 'Harian';
    titleLine.textContent = `Monitoring ${label} ${resLabel} ${lastRange[0]} s.d. ${lastRange[1]}`;
}

function peakUnit(kind) {
    if (category.value === 'rain') return kind === 'hourly' ? 'mm/jam' : 'mm';
    return 'm';
}

function peakTableLabels(kind) {
    if (category.value === 'rain') {
        return kind === 'hourly'
            ? {title: 'Intensitas Hujan Tertinggi', value: 'Intensitas', period: 'Waktu'}
            : {title: 'Hujan Harian Tertinggi', value: 'Hujan Harian', period: 'Tanggal'};
    }
    return kind === 'hourly'
        ? {title: 'Tinggi Muka Air Tertinggi Jam-Jaman', value: 'Tinggi Muka Air', period: 'Waktu'}
        : {title: 'Tinggi Muka Air Tertinggi Harian', value: 'Tinggi Muka Air', period: 'Tanggal'};
}

function stationPeakRows(view, kind) {
    if (!view) return [];
    const periods = view.periods || [];
    const rows = [];
    for (const station of (view.stations || [])) {
        let best = null;
        (station.values || []).forEach((raw, index) => {
            if (raw === null || raw === undefined || raw === '' || !Number.isFinite(Number(raw))) return;
            const value = Number(raw);
            if (!best || value > best.value) best = {value, index};
        });
        if (!best) continue;
        // Pos tanpa kejadian hujan tidak perlu memenuhi tabel ringkasan tertinggi.
        // Aturan ini berlaku untuk intensitas jam-jaman dan akumulasi harian.
        if (category.value === 'rain' && roundRain(best.value) <= 0) continue;
        rows.push({
            station: station.name || 'Pos',
            vendor: station.vendor || '',
            value: best.value,
            period: periods[best.index] || '',
        });
    }
    return rows.sort((a, b) => b.value - a.value || a.station.localeCompare(b.station, 'id'));
}

function setPeakTableHead(tableEl, titleEl, kind) {
    const labels = peakTableLabels(kind);
    if (titleEl) {
        const span = titleEl.querySelector('span');
        if (span) span.textContent = labels.title;
        else titleEl.textContent = labels.title;
    }
    const headers = tableEl?.querySelectorAll('thead th') || [];
    if (headers[0]) headers[0].textContent = 'Nama Pos';
    if (headers[1]) headers[1].textContent = `${labels.value} (${peakUnit(kind)})`;
    if (headers[2]) headers[2].textContent = labels.period;
}

function renderPeakTable(kind, rows) {
    const body = kind === 'hourly' ? hourlyPeakBody : dailyPeakBody;
    const tableEl = kind === 'hourly' ? hourlyPeakTable : dailyPeakTable;
    const titleEl = kind === 'hourly' ? hourlyPeakTitle : dailyPeakTitle;
    const button = kind === 'hourly' ? downloadHourlyPeakBtn : downloadDailyPeakBtn;
    if (!body) return;
    setPeakTableHead(tableEl, titleEl, kind);
    if (!rows.length) {
        const emptyText = category.value === 'rain' ? 'Tidak ada hujan di atas 0 pada periode ini.' : 'Belum ada data pada periode ini.';
        body.innerHTML = `<tr><td colspan="3" class="ui-summary-table__empty">${emptyText}</td></tr>`;
        if (button) button.disabled = true;
        return;
    }
    body.innerHTML = rows.map(row => {
        const value = category.value === 'rain' ? roundRain(row.value) : Number(row.value);
        const classification = rainClassification(kind, value);
        const valueClass = classification ? ` rain-class rain-class--${classification.key}` : '';
        return `
        <tr>
            <td title="${esc(row.vendor)}">${esc(row.station)}</td>
            <td class="peak-value${valueClass}">${value.toFixed(category.value === 'rain' ? 1 : 2)}</td>
            <td>${esc(row.period)}</td>
        </tr>`;
    }).join('');
    if (button) button.disabled = false;
}

function getPeakRows(kind) {
    if (!currentBundle || currentBundle.category !== category.value) return [];
    return stationPeakRows(currentBundle.views?.[kind], kind);
}

function updatePeakTables() {
    if (category.value !== 'rain') {
        if (hourlyPeakBody) hourlyPeakBody.innerHTML = '<tr><td colspan="3" class="ui-summary-table__empty">Ringkasan tertinggi hanya tersedia untuk Curah Hujan.</td></tr>';
        if (dailyPeakBody) dailyPeakBody.innerHTML = '<tr><td colspan="3" class="ui-summary-table__empty">Ringkasan tertinggi hanya tersedia untuk Curah Hujan.</td></tr>';
        if (downloadHourlyPeakBtn) downloadHourlyPeakBtn.disabled = true;
        if (downloadDailyPeakBtn) downloadDailyPeakBtn.disabled = true;
        return;
    }
    renderPeakTable('hourly', getPeakRows('hourly'));
    renderPeakTable('daily', getPeakRows('daily'));
}

function exportPeakTable(kind) {
    if (category.value !== 'rain') return;
    const rows = getPeakRows(kind);
    if (!rows.length) return;
    const labels = peakTableLabels(kind);
    const unit = peakUnit(kind);
    const isHourly = kind === 'hourly';
    const aoa = [['Nama Pos', `${labels.value} (${unit})`, labels.period]];
    const periodCells = [];
    rows.forEach((row, index) => {
        const parsed = parseIsoDateTime(row.period);
        const value = category.value === 'rain' ? roundRain(row.value) : Number(row.value);
        aoa.push([row.station, value, parsed || row.period]);
        if (parsed) periodCells.push({r: index + 1, c: 2});
    });
    const ws = XLSX.utils.aoa_to_sheet(aoa, {cellDates: true});
    periodCells.forEach(({r, c}) => {
        const addr = XLSX.utils.encode_cell({r, c});
        if (ws[addr]) ws[addr].z = isHourly ? 'yyyy-mm-dd hh:mm' : 'yyyy-mm-dd';
    });
    rows.forEach((row, index) => {
        const addr = XLSX.utils.encode_cell({r: index + 1, c: 1});
        const cell = ws[addr];
        if (!cell) return;
        cell.z = category.value === 'rain' ? '0.0' : '0.00';
        const classification = rainClassification(kind, row.value);
        if (classification) {
            cell.s = {
                fill: {patternType: 'solid', fgColor: {rgb: classification.color.replace('#', '')}},
                font: {color: {rgb: '07111F'}, bold: true},
                alignment: {horizontal: 'right'},
            };
        }
    });
    const columnWidths = [
        Math.min(34, Math.max(12, ...rows.map(row => String(row.station || '').length + 2))),
        Math.max(16, String(aoa[0][1] || '').length + 2),
        Math.max(12, isHourly ? 18 : 12),
    ];
    ws['!cols'] = columnWidths.map(wch => ({wch}));
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, isHourly ? 'Tertinggi Jam-Jaman' : 'Tertinggi Harian');
    const categoryLabel = category.value === 'rain' ? (isHourly ? 'Intensitas Hujan Tertinggi' : 'Hujan Harian Tertinggi') : labels.title;
    XLSX.writeFile(wb, `${categoryLabel} ${lastRange?.[0] || ''} s.d. ${lastRange?.[1] || ''}.xlsx`);
}

function updateMetrics() {
    const availability = monitoringAvailabilityCounts();
    if (stationCountMetric) stationCountMetric.textContent = currentBundle ? String(availability.success) : '—';
    if (warningCountMetric) warningCountMetric.textContent = currentBundle ? String(availability.failed) : '—';
    if (staleWarningMetric) staleWarningMetric.textContent = currentBundle ? String(availability.warning) : '—';
    if (disconnectedMetric) disconnectedMetric.textContent = currentBundle ? String(availability.disconnected) : '—';
    if (periodMetric) periodMetric.textContent = lastRange ? `${lastRange[0]} s.d. ${lastRange[1]}` : 'Belum dipilih';
    updatePeakTables();
    syncMonitoringSummary();
}

function controlsMatchBundle() {
    const range = selectedRange();
    return !!(currentBundle && range && currentBundle.category === category.value
        && currentBundle.date_from === range[0] && currentBundle.date_to === range[1]
        && loggerVendorSignature(currentBundle.selected_vendors || []) === loggerVendorSignature());
}

function applyResolutionView(showCacheMessage = false) {
    if (!currentBundle || !controlsMatchBundle()) return false;
    const view = currentBundle.views?.[resolution.value];
    if (!view) return false;
    currentData = {...currentBundle, ...view, resolution: resolution.value};
    lastRange = [currentBundle.date_from, currentBundle.date_to];
    updateTitle();
    render();
    updateMetrics();
    downloadBtn.disabled = false;
    if (showCacheMessage) {
        statusLine.textContent = 'Interval diperbarui dari data yang sudah dimuat.';
        statusLine.className = 'status success';
    }
    lucide.createIcons();
    return true;
}

function logMonitoringPerformance(data) {
    const perf = data?.performance;
    if (!perf || typeof console === 'undefined') return;
    const beacon = perf.vendors?.beacon || {};
    const rows = [
        ['TOTAL request', perf.request_total_ms],
        ['Metadata seluruh vendor', perf.metadata_ms],
        ['Fase fetch vendor paralel', perf.vendor_phase_ms],
        ['Beacon total', beacon.total_ms],
        ['Beacon bulk /monitoring', beacon.bulk_ms],
        ['Beacon metadata /beranda', beacon.selector_metadata_ms],
        ['Beacon supplement exact', beacon.supplement_ms],
        ['Higertech', perf.vendors?.higertech?.total_ms],
        ['Tatonas', perf.vendors?.tatonas?.total_ms],
        ['Dashindo', perf.vendors?.dashindo?.total_ms],
        ['Agregasi + bentuk tabel', perf.aggregate_ms],
    ].filter(([, ms]) => Number.isFinite(Number(ms)))
      .map(([tahap, ms]) => ({tahap, 'waktu (dtk)': (Number(ms) / 1000).toFixed(3)}));
    console.groupCollapsed(`⏱️ Monitoring performance — ${(Number(perf.request_total_ms || 0) / 1000).toFixed(2)} dtk`);
    console.table(rows);
    if (perf.metadata?.vendors_ms) console.table(
        Object.entries(perf.metadata.vendors_ms).map(([vendor, ms]) => ({vendor: `metadata ${vendor}`, 'waktu (dtk)': (Number(ms) / 1000).toFixed(3)}))
    );
    console.log('Beacon detail:', beacon);
    if (Number.isFinite(Number(beacon.token_cache_hits)) || Number.isFinite(Number(beacon.token_cache_misses))) {
        console.log('Beacon token cache:', {
            hit: Number(beacon.token_cache_hits || 0),
            miss: Number(beacon.token_cache_misses || 0),
            stale_refresh: Number(beacon.token_cache_stale || 0),
            ttl_dtk: Number(beacon.token_cache_ttl_s || 0)
        });
    }
    const tatonasDetail = perf.vendors?.tatonas || {};
    if (tatonasDetail.deadline_ms) {
        console.log('Tatonas deadline:', {
            batas_dtk: (Number(tatonasDetail.deadline_ms) / 1000).toFixed(1),
            deadline_exceeded: Boolean(tatonasDetail.deadline_exceeded),
            pos_selesai: tatonasDetail.completed_station_count ?? null,
            pos_dilewati: tatonasDetail.timed_out_station_count ?? 0
        });
    }
    const tatonasStations = tatonasDetail.station_timings;
    if (Array.isArray(tatonasStations) && tatonasStations.length) {
        console.log('Tatonas per pos (terlama dulu):');
        console.table(tatonasStations.map(item => ({
            pos: item.name || item.id_logger || '-',
            id_logger: item.id_logger || '-',
            'waktu (dtk)': (Number(item.total_ms || 0) / 1000).toFixed(3),
            status: item.ok ? 'OK' : (item.deadline_exceeded ? 'TIMEOUT' : 'GAGAL'),
            error: item.error || ''
        })));
    }
    const dashindoDetail = perf.vendors?.dashindo || {};
    if (dashindoDetail.station_count) {
        console.log('Dashindo transport:', {
            transport: dashindoDetail.transport || '-',
            worker: dashindoDetail.worker_count ?? null,
            koneksi_engineio: dashindoDetail.engine_connection_count ?? null,
            hourly_direct: dashindoDetail.hourly_direct_count ?? 0,
            csv_fallback: dashindoDetail.csv_fallback_count ?? 0,
            deadline_exceeded: Boolean(dashindoDetail.deadline_exceeded)
        });
    }
    const dashindoStations = dashindoDetail.station_timings;
    if (Array.isArray(dashindoStations) && dashindoStations.length) {
        console.log('Dashindo per pos (terlama dulu):');
        console.table(dashindoStations.map(item => ({
            pos: item.name || item.id_logger || '-',
            id_logger: item.id_logger || '-',
            'waktu (dtk)': (Number(item.total_ms || 0) / 1000).toFixed(3),
            jalur: item.path || '-',
            status: item.ok ? 'OK' : (item.deadline_exceeded ? 'TIMEOUT' : 'GAGAL'),
            error: item.error || ''
        })));
    }
    console.log('Performance raw:', perf);
    console.groupEnd();
}

async function load() {
    if (!category.value) {
        statusLine.textContent = 'Pilih kategori data terlebih dahulu.';
        statusLine.className = 'status error';
        return;
    }
    const selectedVendors = selectedLoggerVendors();
    if (!selectedVendors.length) {
        statusLine.textContent = 'Pilih minimal satu Logger terlebih dahulu.';
        statusLine.className = 'status error';
        return;
    }
    const range = selectedRange();
    if (!range) {
        statusLine.textContent = 'Periode belum lengkap atau berada setelah tanggal hari ini.';
        statusLine.className = 'status error';
        return;
    }
    if (range[1] < range[0]) {
        statusLine.textContent = 'Tanggal akhir tidak boleh sebelum tanggal awal.';
        statusLine.className = 'status error';
        return;
    }
    lastRange = range;
    saveMonitoringState();
    const sessionBundle = getCachedMonitoringBundle(category.value, range);
    if (sessionBundle) {
        currentBundle = sessionBundle;
        lastRange = [sessionBundle.date_from, sessionBundle.date_to];
        if (!applyResolutionView(false)) {
            const view = sessionBundle.views?.[resolution.value] || sessionBundle;
            currentData = {...sessionBundle, ...view, resolution: resolution.value};
            updateTitle();
            render();
            updateMetrics();
            downloadBtn.disabled = false;
        }
        const loadedCount = (currentData?.stations || []).filter(station => !station?.fetch_failed).length;
        statusLine.textContent = `${loadedCount} pos berhasil dimuat.`;
        statusLine.className = 'status success';
        lucide.createIcons();
        return;
    }
    loading.classList.add('active');
    statusLine.textContent = '';
    statusLine.className = 'status';
    showBtn.disabled = true;
    downloadBtn.disabled = true;
    try {
        const res = await fetch('/api/monitoring/data', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({category: category.value, resolution: resolution.value, date_from: range[0], date_to: range[1], vendors: selectedVendors}),
        });
        let data = {};
        try { data = await res.json(); } catch (_e) { throw new Error('Response server tidak dapat dibaca.'); }
        if (res.status === 401) {
            window.HydroUI?.applyAuthState?.(false, true);
            throw new Error('Silakan autentikasi server telemetri terlebih dahulu di halaman Olah Data.');
        }
        if (!res.ok || !data.ok) throw new Error(data.error || 'Monitoring gagal dimuat.');
        logMonitoringPerformance(data);
        currentBundle = data;
        cacheMonitoringBundle(data);
        lastRange = [data.date_from, data.date_to];
        if (!applyResolutionView(false)) {
            currentData = data;
            updateTitle();
            render();
            updateMetrics();
            downloadBtn.disabled = false;
        }
        const loadedCount = (currentData?.stations || []).filter(station => !station?.fetch_failed).length;
        statusLine.textContent = `${loadedCount} pos berhasil dimuat.`;
        statusLine.className = data.warning_count ? 'status warn' : 'status success';
    } catch (err) {
        currentBundle = null;
        currentData = null;
        updateMetrics();
        table.classList.remove('monitor-hourly');
        table.innerHTML = `<tbody><tr><td style="color:var(--danger)">${esc(err.message || err)}</td></tr></tbody>`;
        statusLine.textContent = String(err.message || err);
        statusLine.className = 'status error';
    } finally {
        loading.classList.remove('active');
        showBtn.disabled = false;
        lucide.createIcons();
    }
}

function exportMonitoring() {
    if (!currentData) return;
    const periods = currentData.periods || [];
    const stations = currentData.stations || [];
    let aoa = [];
    const merges = [];
    const dateCells = [];
    const dateTimeCells = [];

    if (orientation === 'horizontal') {
        if (resolution.value === 'hourly' && periods.length) {
            const groups = hourlyGroups(periods);
            aoa.push(['Nama Pos', ...periods.map(p => parseIsoDateTime(String(p).split(' ')[0]) || String(p).split(' ')[0])]);
            aoa.push(['', ...periods.map(p => String(p).split(' ')[1] || '')]);
            merges.push({s: {r: 0, c: 0}, e: {r: 1, c: 0}});
            groups.forEach(g => {
                if (g.count > 1) merges.push({s: {r: 0, c: g.start + 1}, e: {r: 0, c: g.start + g.count}});
            });
            for (let c = 1; c <= periods.length; c++) dateCells.push({r: 0, c});
        } else {
            aoa.push(['Nama Pos', ...periods.map(p => parseIsoDateTime(p) || p)]);
            for (let c = 1; c <= periods.length; c++) dateCells.push({r: 0, c});
        }
        stations.forEach(st => aoa.push([st.name, ...(st.values || []).map(v => v === null || v === undefined || v === '' ? '' : (category.value === 'rain' ? roundRain(v) : Number(v)))]));
    } else {
        const rowPeriods = (category.value === 'rain' && resolution.value === 'hourly'
            && (currentData.period_keys || []).length === periods.length)
            ? currentData.period_keys
            : periods;
        aoa.push(['Waktu', ...stations.map(st => st.name)]);
        rowPeriods.forEach((p, i) => {
            const parsed = parseIsoDateTime(p);
            aoa.push([parsed || p, ...stations.map(st => { const v=(st.values || [])[i]; return v === null || v === undefined || v === '' ? '' : (category.value === 'rain' ? roundRain(v) : Number(v)); })]);
            if (parsed) {
                (resolution.value === 'hourly' ? dateTimeCells : dateCells).push({r: i + 1, c: 0});
            }
        });
    }

    const ws = XLSX.utils.aoa_to_sheet(aoa, {cellDates: true});
    if (merges.length) ws['!merges'] = merges;
    dateCells.forEach(({r, c}) => {
        const addr = XLSX.utils.encode_cell({r, c});
        if (ws[addr]) ws[addr].z = 'yyyy-mm-dd';
    });
    dateTimeCells.forEach(({r, c}) => {
        const addr = XLSX.utils.encode_cell({r, c});
        if (ws[addr]) ws[addr].z = 'yyyy-mm-dd hh:mm';
    });
    if (category.value === 'rain') {
        if (orientation === 'horizontal') {
            const dataStartRow = resolution.value === 'hourly' ? 2 : 1;
            stations.forEach((station, stationIndex) => {
                (station.values || []).forEach((value, valueIndex) => {
                    if (value === null || value === undefined || value === '' || !Number.isFinite(Number(value))) return;
                    const addr = XLSX.utils.encode_cell({r: dataStartRow + stationIndex, c: 1 + valueIndex});
                    applyRainExcelStyle(ws[addr], resolution.value, value);
                });
            });
        } else {
            periods.forEach((_period, periodIndex) => {
                stations.forEach((station, stationIndex) => {
                    const value = (station.values || [])[periodIndex];
                    if (value === null || value === undefined || value === '' || !Number.isFinite(Number(value))) return;
                    const addr = XLSX.utils.encode_cell({r: 1 + periodIndex, c: 1 + stationIndex});
                    applyRainExcelStyle(ws[addr], resolution.value, value);
                });
            });
        }
    } else if (category.value === 'tma') {
        if (orientation === 'horizontal') {
            const dataStartRow = resolution.value === 'hourly' ? 2 : 1;
            stations.forEach((station, stationIndex) => {
                (station.values || []).forEach((value, valueIndex) => {
                    if (value === null || value === undefined || value === '' || !Number.isFinite(Number(value))) return;
                    const addr = XLSX.utils.encode_cell({r: dataStartRow + stationIndex, c: 1 + valueIndex});
                    if (ws[addr]) ws[addr].z = '0.00';
                });
            });
        } else {
            periods.forEach((_period, periodIndex) => {
                stations.forEach((station, stationIndex) => {
                    const value = (station.values || [])[periodIndex];
                    if (value === null || value === undefined || value === '' || !Number.isFinite(Number(value))) return;
                    const addr = XLSX.utils.encode_cell({r: 1 + periodIndex, c: 1 + stationIndex});
                    if (ws[addr]) ws[addr].z = '0.00';
                });
            });
        }
    }
    ws['!cols'] = [{wch: 30}, ...Array(Math.max(0, (aoa[0]?.length || 1) - 1)).fill({wch: 12})];

    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, 'Monitoring');
    const label = category.value === 'rain' ? 'Curah Hujan' : 'Tinggi Muka Air';
    const resLabel = resolution.value === 'hourly' ? 'Jam-Jaman' : 'Harian';
    XLSX.writeFile(wb, `Monitoring ${label} ${resLabel} ${lastRange?.[0] || ''} s.d. ${lastRange?.[1] || ''}.xlsx`);
}

loggerFilterButton?.addEventListener('click', event => {
    event.stopPropagation();
    setLoggerMenuOpen(loggerFilterMenu?.hidden !== false);
});
loggerFilterMenu?.addEventListener('click', event => event.stopPropagation());
loggerSelectAll?.addEventListener('change', () => {
    loggerVendorCheckboxes.forEach(el => { el.checked = loggerSelectAll.checked; });
    syncLoggerFilterUI();
    saveMonitoringState();
    if (!controlsMatchBundle()) {
        currentData = null;
        downloadBtn.disabled = true;
        statusLine.textContent = selectedLoggerVendors().length
            ? 'Pilihan Logger berubah. Tekan Tampilkan Data untuk memuat ulang.'
            : 'Pilih minimal satu Logger terlebih dahulu.';
        statusLine.className = 'status';
        updateMetrics();
    }
});
loggerVendorCheckboxes.forEach(el => el.addEventListener('change', () => {
    syncLoggerFilterUI();
    saveMonitoringState();
    if (!controlsMatchBundle()) {
        currentData = null;
        downloadBtn.disabled = true;
        statusLine.textContent = selectedLoggerVendors().length
            ? 'Pilihan Logger berubah. Tekan Tampilkan Data untuk memuat ulang.'
            : 'Pilih minimal satu Logger terlebih dahulu.';
        statusLine.className = 'status';
        updateMetrics();
    }
}));
document.addEventListener('click', event => {
    if (loggerFilter && !loggerFilter.contains(event.target)) setLoggerMenuOpen(false);
});
document.addEventListener('keydown', event => {
    if (event.key === 'Escape') setLoggerMenuOpen(false);
});

periodMode.addEventListener('change', () => { updatePeriodFields(); saveMonitoringState(); });
showBtn.addEventListener('click', load);
downloadBtn.addEventListener('click', exportMonitoring);
downloadHourlyPeakBtn?.addEventListener('click', () => exportPeakTable('hourly'));
downloadDailyPeakBtn?.addEventListener('click', () => exportPeakTable('daily'));
resolution.addEventListener('change', () => {
    syncMonitoringSummary();
    saveMonitoringState();
    applyResolutionView(true);
});
category.addEventListener('change', () => {
    if (category.value) dropCategoryPlaceholder();
    syncMonitoringSummary();
    saveMonitoringState();
    updatePeakTables();
    if (!controlsMatchBundle()) {
        downloadBtn.disabled = true;
        statusLine.textContent = category.value
            ? 'Kategori berubah. Tekan Tampilkan Data untuk memuat kategori ini.'
            : 'Pilih kategori data terlebih dahulu.';
        statusLine.className = 'status';
        currentData = null;
        updateMetrics();
    }
});

[dailyDate, monthDate, yearDate, dateFrom, dateTo].forEach(el => {
    el?.addEventListener('change', saveMonitoringState);
    el?.addEventListener('input', saveMonitoringState);
});

const horizontalBtn = document.getElementById('horizontalBtn');
const verticalBtn = document.getElementById('verticalBtn');
horizontalBtn.onclick = () => {
    orientation = 'horizontal';
    horizontalBtn.classList.add('active');
    verticalBtn.classList.remove('active');
    saveMonitoringState();
    render();
};
verticalBtn.onclick = () => {
    orientation = 'vertical';
    verticalBtn.classList.add('active');
    horizontalBtn.classList.remove('active');
    saveMonitoringState();
    render();
};

resolution.value = 'hourly';
periodMode.value = 'custom';
initPickers();
const savedMonitoringState = readMonitoringState();
if (savedMonitoringState) {
    if (['rain', 'tma'].includes(savedMonitoringState.category)) {
        category.value = savedMonitoringState.category;
        dropCategoryPlaceholder();
    } else {
        category.value = '';
    }
    if (['hourly', 'daily'].includes(savedMonitoringState.resolution)) resolution.value = savedMonitoringState.resolution;
    if (['day', 'month', 'year', 'custom'].includes(savedMonitoringState.periodMode)) periodMode.value = savedMonitoringState.periodMode;
    if (savedMonitoringState.dailyDate) dailyDate.value = savedMonitoringState.dailyDate;
    if (savedMonitoringState.monthDate) monthDate.value = savedMonitoringState.monthDate;
    if (savedMonitoringState.yearDate) yearDate.value = savedMonitoringState.yearDate;
    if (savedMonitoringState.dateFrom) dateFrom.value = savedMonitoringState.dateFrom;
    if (savedMonitoringState.dateTo) dateTo.value = savedMonitoringState.dateTo;
    if (Array.isArray(savedMonitoringState.vendors)) {
        const wanted = new Set(savedMonitoringState.vendors);
        loggerVendorCheckboxes.forEach(el => { el.checked = wanted.has(el.value); });
    }
    orientation = savedMonitoringState.orientation === 'vertical' ? 'vertical' : 'horizontal';
} else {
    category.value = '';
    orientation = 'horizontal';
}
horizontalBtn.classList.toggle('active', orientation === 'horizontal');
verticalBtn.classList.toggle('active', orientation === 'vertical');
syncLoggerFilterUI();
updatePeriodFields();
updateMetrics();
syncMonitoringSummary();
saveMonitoringState();
lucide.createIcons();

// Tidak ada request otomatis. Jika pengguna kembali ke halaman ini dalam tab yang
// sama, hasil terakhir yang masih cocok dipulihkan dari sessionStorage tanpa request baru.
if (category.value) {
    const range = selectedRange();
    const cachedBundle = getCachedMonitoringBundle(category.value, range);
    if (cachedBundle) {
        currentBundle = cachedBundle;
        lastRange = [cachedBundle.date_from, cachedBundle.date_to];
        const view = cachedBundle.views?.[resolution.value] || cachedBundle;
        currentData = {...cachedBundle, ...view, resolution: resolution.value};
        updateTitle();
        render();
        updateMetrics();
        downloadBtn.disabled = false;
        statusLine.textContent = 'Data terakhir dipulihkan dari cache sesi.';
        statusLine.className = 'status success';
    }
}

