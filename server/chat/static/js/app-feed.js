import { initCommonUI, translations, getLang, handleSurfaceScroll, setLang } from './app-common.js';

let currentLang = getLang();
const feedList = document.getElementById('feedList');
const feedMessage = document.getElementById('feedMessage');
const feedFootnote = document.getElementById('feedFootnote');
const feedFiltersEl = document.getElementById('feedFilters');
const feedSortLabelEl = document.querySelector('.feed-sort-label');
const feedSortSelect = document.getElementById('feedSort');
const feedSearchForm = document.getElementById('feedSearchForm');
const feedSearchInput = document.getElementById('feedSearch');
const feedSearchClear = document.getElementById('feedSearchClear');
const feedSearchSubmit = document.getElementById('feedSearchSubmit');
const feedScrollTopBtn = document.getElementById('feedScrollTop');
const feedFilterEl = document.querySelector('.feed-filter');
const feedFloating = document.getElementById('feedFloating');
const feedMoreWrap = document.getElementById('feedMoreWrap');
const feedMoreBtn = document.getElementById('feedMoreBtn');
const feedFabDial = document.getElementById('feedFabDial');
const root = document.documentElement;

let feedLoaded = false;
let cachedEvents = [];
let activeFeedFilter = 'all';
let activeSort = feedSortSelect?.value || 'recent';
let activeSearchTerm = '';
let activeSearchTermRaw = '';
let lastFeedScrollTop = 0;
let feedDialOpen = false;

initCommonUI({ page: 'feed' });
translations.ko.state = {
  ongoing: "진행중",
  finished: "마감",
  upcoming: "예정",
};

translations.en.state = {
  ongoing: "Ongoing",
  finished: "Finished",
  upcoming: "Upcoming",
};

const feedFilterOptions = [
  { id: 'all', label: { ko: '전체', en: 'All' } },
  { id: 'nmok', label: { ko: '국립중앙박물관', en: 'National Museum of Korea' }, match: ['국립중앙박물관'] },
  { id: 'nlib', label: { ko: '국립중앙도서관', en: 'National Library of Korea' }, match: ['국립중앙도서관'] },
  { id: 'mmca', label: { ko: '국립현대미술관', en: 'MMCA' }, match: ['국립현대미술관'] },
  { id: 'gugak', label: { ko: '국립국악원', en: 'National Gugak Center' }, match: ['국립국악원'] },
  { id: 'folk', label: { ko: '국립민속박물관', en: 'National Folk Museum' }, match: ['국립민속박물관'] }
];

function updateFloatingHeight() {
  if (!feedFloating || !root) return;
  const height = feedFloating.getBoundingClientRect().height || 0;
  if (height > 0) {
    root.style.setProperty('--feed-floating-height', `${Math.ceil(height)}px`);
  }
}

function updateSearchLocalization() {
  const t = translations[currentLang];
  if (feedSearchInput) {
    feedSearchInput.placeholder = t.feedSearchPlaceholder || feedSearchInput.placeholder;
    feedSearchInput.setAttribute('aria-label', t.feedSearchAria || t.feedSearchPlaceholder || '');
    feedSearchInput.value = activeSearchTermRaw;
  }
  if (feedSearchClear) feedSearchClear.setAttribute('aria-label', t.feedSearchClear || '');
  if (feedSearchSubmit) feedSearchSubmit.setAttribute('aria-label', t.feedSearchSubmit || '');
  if (feedScrollTopBtn) feedScrollTopBtn.setAttribute('aria-label', t.feedScrollTop || '');
  if (feedMoreBtn) {
    feedMoreBtn.setAttribute('aria-label', t.moreAria || '');
    feedMoreBtn.setAttribute('title', t.moreAria || '');
  }
}

function updateSearchUI() {
  if (feedSearchClear) feedSearchClear.hidden = activeSearchTerm.length === 0;
}

function toggleFeedDial(force) {
  if (!feedFabDial) return;
  const willOpen = typeof force === 'boolean' ? force : !feedDialOpen;
  feedDialOpen = willOpen;
  feedFabDial.classList.toggle('open', willOpen);
}

function applySearchTerm(rawValue, options = {}) {
  const value = typeof rawValue === 'string' ? rawValue : '';
  activeSearchTermRaw = value.trim();
  const normalized = activeSearchTermRaw.toLowerCase();
  if (normalized === activeSearchTerm) {
    updateSearchUI();
    if (feedSearchInput && feedSearchInput.value !== activeSearchTermRaw) feedSearchInput.value = activeSearchTermRaw;
    if (options.forceRender) renderFeed();
    if (!options.skipScroll && feedList) {
      feedList.scrollTo({ top: 0, behavior: 'smooth' });
    }
    return;
  }
  activeSearchTerm = normalized;
  updateSearchUI();
  renderFeed();
  if (!options.skipScroll && feedList) {
    feedList.scrollTo({ top: 0, behavior: 'smooth' });
  }
}

function filterEventsBySearchTerm(events) {
  if (!activeSearchTerm) return events.slice();
  const term = activeSearchTerm;
  return events.filter((ev) => {
    const haystack = [
      ev?.title,
      ev?.description,
      ev?.deep_data,
      ev?.overview,
      ev?.host,
      ev?.organization,
      ev?.category,
      ev?.place,
      ev?.location
    ].map((part) => String(part || '').toLowerCase()).join(' ');
    return haystack.includes(term);
  });
}

function toggleScrollTopButton(scrollTop) {
  if (!feedScrollTopBtn) return;
  const shouldShow = scrollTop > 160;
  feedScrollTopBtn.classList.toggle('visible', shouldShow);
}

function updateFilterVisibility(scrollTop) {
  if (!feedFilterEl) return;
  if (scrollTop < 16) {
    feedFilterEl.classList.remove('collapsed');
    return;
  }
  if (scrollTop > lastFeedScrollTop + 6) {
    feedFilterEl.classList.add('collapsed');
  } else if (scrollTop < lastFeedScrollTop - 6) {
    feedFilterEl.classList.remove('collapsed');
  }
}

function handleFeedScroll() {
  if (!feedList) return;
  const scrollTop = feedList.scrollTop;
  handleSurfaceScroll(feedList);
  updateFilterVisibility(scrollTop);
  toggleScrollTopButton(scrollTop);
  lastFeedScrollTop = scrollTop;
}

/* ===== 유틸 ===== */
function escapeHTML(str) {
  return String(str).replace(/[&<>"']/g, (m) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[m]));
}
function trimText(value, limit = 600) {
  const raw = String(value ?? '').trim();
  if (!raw) return '';
  if (raw.length <= limit) return raw;
  return `${raw.slice(0, limit)}…`;
}
function formatDescription(value, limit = 600) {
  const trimmed = trimText(value, limit);
  if (!trimmed) return '';
  return escapeHTML(trimmed).replace(/\n+/g, '<br/>');
}
function escapeValue(value, fallback = '') {
  const raw = value ?? '';
  const text = String(raw).trim();
  if (!text) return fallback ? escapeHTML(fallback) : '';
  return escapeHTML(text);
}
function formatCost(value, lang) {
  if (value === null || value === undefined) return '';
  const trimmed = String(value).trim();
  if (!trimmed) return '';
  if (['0', '무료', 'free'].includes(trimmed.toLowerCase())) {
    return escapeHTML(translations[lang].costFree);
  }
  return escapeHTML(trimmed);
}
function extractEvent(ev, lang, options = {}) {
  if (!ev || typeof ev !== 'object') return null;
  const t = translations[lang];
  
  const title = lang === 'en' ? (ev.title_en ?? ev.title) : ev.title;
  const place = lang === 'en' ? (ev.place_en ?? ev.place) : ev.place;
  const host = lang === 'en' ? (ev.host_en ?? ev.host) : ev.host;
  const schedule = lang === 'en' ? (ev.period_en ?? ev.period) : ev.period;

  // 상태 번역
  let status = ev.state || ev.status || '';
  if (lang === 'en') {
    // 한국어 상태를 영어로 매핑
    if (status === "진행중") status = t.state.ongoing;
    else if (status === "마감") status = t.state.finished;
    else if (status === "예정") status = t.state.upcoming;
  }

  return {
    title: escapeValue(title, t.unknownTitle),
    schedule: escapeValue(schedule),
    location: escapeValue(place),
    host: escapeValue(host),
    status: escapeValue(status),
    cost: formatCost(ev.cost, lang),
    link: escapeValue(ev.url || '')
  };
}

function createSkeletonCard() {
  const card = document.createElement('div');
  card.className = 'skeleton-card';
  card.innerHTML = `
    <div class="skeleton skeleton-title"></div>
    <div class="skeleton skeleton-line"></div>
    <div class="skeleton skeleton-line short"></div>
  `;
  return card;
}
function showFeedSkeleton() {
  feedList.innerHTML = '';
  for (let i = 0; i < 5; i++) feedList.appendChild(createSkeletonCard());
}

function createFeedCard(ev) {
  const data = extractEvent(ev, currentLang, { descriptionLimit: 420 });
  if (!data) return null;
  const t = translations[currentLang];
  const card = document.createElement('article');
  card.className = 'feed-card';
  card.setAttribute('tabindex', '0');

  // info: schedule, location
  const infoParts = [];
  if (data.schedule) infoParts.push(`📅 ${data.schedule}`);
  if (data.location) infoParts.push(`📍 ${data.location}`);
  const infoHTML = infoParts.length ? `<div class="feed-meta">${infoParts.map((p) => `<span>${p}</span>`).join('')}</div>` : '';

  // meta: host, status, cost
  const metaParts = [];
  if (data.host) metaParts.push(`🏢 ${data.host}`);
  if (data.status) metaParts.push(`📌 ${data.status}`);
  if (data.cost) metaParts.push(`💰 ${data.cost}`);

  const footerSegments = [];
  if (metaParts.length) footerSegments.push(`<span>${metaParts.join(' · ')}</span>`);
  if (data.link) footerSegments.push(`<a href="${data.link}" target="_blank" rel="noopener">${t.actions.viewDetail}</a>`);
  const footerHTML = footerSegments.length ? `<div class="feed-footer">${footerSegments.join('')}</div>` : '';

  card.innerHTML = `
    <h3>${data.title}</h3>
    ${infoHTML}
    ${footerHTML}
  `;

  return card;
}

function parseEventDateValue(value) {
  if (!value) return null;
  const str = String(value).trim();
  if (!str) return null;
  const normalized = str
    .replace(/[년]/g, '.')
    .replace(/[월]/g, '.')
    .replace(/[일]/g, '.')
    .replace(/[~]/g, ' ')
    .replace(/[^0-9.\-/ ]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  const fullMatch = normalized.match(/(\d{4})[.\-/ ](\d{1,2})[.\-/ ](\d{1,2})/);
  if (fullMatch) {
    const [, y, m, d] = fullMatch;
    const year = Number(y);
    const month = Number(m);
    const day = Number(d);
    if (!Number.isNaN(year) && !Number.isNaN(month) && !Number.isNaN(day)) {
      return new Date(year, month - 1, day);
    }
  }
  const compactMatch = normalized.match(/(\d{4})(\d{2})(\d{2})/);
  if (compactMatch) {
    const [, y, m, d] = compactMatch;
    const year = Number(y);
    const month = Number(m);
    const day = Number(d);
    if (!Number.isNaN(year) && !Number.isNaN(month) && !Number.isNaN(day)) {
      return new Date(year, month - 1, day);
    }
  }
  const fallback = normalized.match(/(\d{1,2})[.\-/ ](\d{1,2})/);
  if (fallback) {
    const [, m, d] = fallback;
    const month = Number(m);
    const day = Number(d);
    if (!Number.isNaN(month) && !Number.isNaN(day)) {
      const referenceYear = new Date().getFullYear();
      return new Date(referenceYear, month - 1, day);
    }
  }
  return null;
}

function getEventSortDate(ev) {
  if (!ev) return null;
  const candidates = [
    ev.datetime,
    ev.period,
    ev.date,
    ev.start_date,
    ev.startDate,
    ev.begin,
    ev.created_at,
    ev.createdAt,
    ev.updated_at,
    ev.updatedAt
  ];
  for (const candidate of candidates) {
    const parsed = parseEventDateValue(candidate);
    if (parsed) return parsed;
  }
  return null;
}

function alphabeticalSort(a, b, locale) {
  const hostA = String(a.host || a.organization || '');
  const hostB = String(b.host || b.organization || '');
  const titleA = String(a.title || '');
  const titleB = String(b.title || '');
  const hostCompare = hostA.localeCompare(hostB, locale, { sensitivity: 'base' });
  if (hostCompare !== 0) return hostCompare;
  return titleA.localeCompare(titleB, locale, { sensitivity: 'base' });
}

function sortEvents(events) {
  const locale = currentLang === 'ko' ? 'ko' : 'en';
  const list = events.slice();
  if (activeSort === 'recent') {
    list.sort((a, b) => {
      const dateA = getEventSortDate(a);
      const dateB = getEventSortDate(b);
      if (dateA && dateB) return dateB - dateA;
      if (dateA) return -1;
      if (dateB) return 1;
      return alphabeticalSort(a, b, locale);
    });
    return list;
  }
  list.sort((a, b) => alphabeticalSort(a, b, locale));
  return list;
}

/* ===== 필터/정렬 ===== */
function filterEventsByActiveOption(events) {
  const option = feedFilterOptions.find((opt) => opt.id === activeFeedFilter);
  if (!option || !option.match || option.match.length === 0) return events.slice();
  const keywords = option.match.map((m) => m.toLowerCase());
  return events.filter((ev) => {
    const haystack = `${ev.host || ''} ${ev.organization || ''} ${ev.title || ''}`.toLowerCase();
    return keywords.some((keyword) => haystack.includes(keyword));
  });
}
function renderFeedFilters() {
  if (!feedFiltersEl) return;
  feedFiltersEl.innerHTML = '';
  feedFilterOptions.forEach((option) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'chip';
    btn.dataset.filterId = option.id;
    btn.dataset.active = option.id === activeFeedFilter ? 'true' : 'false';
    btn.textContent = option.label[currentLang] || option.label.ko;
    btn.addEventListener('click', () => {
      activeFeedFilter = option.id;
      renderFeedFilters();
      renderFeed();
    });
    feedFiltersEl.appendChild(btn);
  });
}

function renderSortControl() {
  if (!feedSortSelect) return;
  const t = translations[currentLang];
  if (feedSortLabelEl) feedSortLabelEl.textContent = t.feedSortLabel;
  feedSortSelect.setAttribute('aria-label', t.feedSortAria || t.feedSortLabel);
  const optionRecent = feedSortSelect.querySelector('option[value="recent"]');
  if (optionRecent) optionRecent.textContent = t.feedSortRecent;
  const optionTitle = feedSortSelect.querySelector('option[value="title"]');
  if (optionTitle) optionTitle.textContent = t.feedSortTitle;
  feedSortSelect.value = activeSort;
}

/* ===== 렌더링/로드 ===== */
function renderFeed() {
  if (!feedLoaded) return;
  const t = translations[currentLang];
  const filtered = filterEventsByActiveOption(cachedEvents);
  const sorted = sortEvents(filtered);
  const searched = filterEventsBySearchTerm(sorted);
  feedList.innerHTML = '';
  if (searched.length === 0) {
    const emptyTitle = activeSearchTerm ? (t.feedSearchEmpty || t.feedEmpty) : t.feedEmpty;
    const emptyDesc = activeSearchTerm ? (t.feedSearchEmptyDesc || t.feedEmptyDesc) : t.feedEmptyDesc;
    const emptyIcon = activeSearchTerm ? '🔍' : '📭';
    feedMessage.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon ">${emptyIcon}</div>
        <div class="empty-state-title">${emptyTitle}</div>
        <div class="empty-state-desc">${emptyDesc}</div>
      </div>
    `;
    feedFootnote.textContent = activeSearchTerm ? '' : t.feedFootnote;
    updateFloatingHeight();
    return;
  }
  feedMessage.textContent = '';
  searched.forEach((ev) => {
    const card = createFeedCard(ev);
    if (card) feedList.appendChild(card);
  });
  feedFootnote.textContent = t.feedFootnote;
  updateFloatingHeight();
}

async function ensureFeed(forceReload = false) {
  const t = translations[currentLang];
  if (feedLoaded && !forceReload) {
    renderFeed();
    return;
  }
  feedMessage.textContent = t.feedLoading;
  showFeedSkeleton();
  try {
    const res = await fetch('/events');
    const data = await res.json();
    cachedEvents = Array.isArray(data.events) ? data.events : [];
    feedLoaded = true;
    renderFeed();
  } catch (err) {
    console.error('Failed to load events', err);
    feedList.innerHTML = '';
    feedMessage.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">⚠️</div>
        <div class="empty-state-title">${t.feedError}</div>
        <button class="retry-button" onclick="location.reload()">${t.errorRetry}</button>
      </div>
    `;
    feedFootnote.textContent = '';
    updateFloatingHeight();
  }
}

/* ===== 스크롤/언어 이벤트 ===== */
if (feedList) {
  feedList.addEventListener('scroll', handleFeedScroll);
}
if (feedSortSelect) {
  feedSortSelect.addEventListener('change', (event) => {
    activeSort = event.target.value || 'recent';
    renderFeed();
  });
}
if (feedSearchForm && feedSearchInput) {
  feedSearchForm.addEventListener('submit', (event) => {
    event.preventDefault();
    applySearchTerm(feedSearchInput.value, { skipScroll: false, forceRender: true });
  });
}
if (feedSearchInput) {
  feedSearchInput.addEventListener('input', (event) => {
    applySearchTerm(event.target.value, { skipScroll: true });
  });
}
if (feedSearchClear) {
  feedSearchClear.addEventListener('click', () => {
    applySearchTerm('', { skipScroll: false, forceRender: true });
    if (feedSearchInput) feedSearchInput.focus();
  });
}
if (feedMoreBtn && feedMoreWrap && feedFabDial) {
  feedMoreBtn.addEventListener('click', (event) => {
    event.stopPropagation();
    toggleFeedDial();
  });
  document.addEventListener('click', (event) => {
    if (feedDialOpen && !feedMoreWrap.contains(event.target)) toggleFeedDial(false);
  });
  feedFabDial.addEventListener('click', (event) => {
    const btn = event.target.closest('.mini-fab');
    if (!btn) return;
    const action = btn.dataset.action;
    if (action === 'go-chat' || action === 'go-feed') {
      const href = btn.dataset.href;
      if (href) window.location.href = href;
    } else if (action === 'toggle-language') {
      setLang(currentLang === 'ko' ? 'en' : 'ko');
    }
    toggleFeedDial(false);
  });
}
if (feedScrollTopBtn && feedList) {
  feedScrollTopBtn.addEventListener('click', () => {
    feedList.scrollTo({ top: 0, behavior: 'smooth' });
    if (feedFilterEl) feedFilterEl.classList.remove('collapsed');
  });
}
if (feedFloating) {
  updateFloatingHeight();
  if (typeof ResizeObserver !== 'undefined') {
    const ro = new ResizeObserver(updateFloatingHeight);
    ro.observe(feedFloating);
  }
  window.addEventListener('resize', updateFloatingHeight);
}

updateSearchLocalization();
updateSearchUI();
toggleScrollTopButton(feedList?.scrollTop || 0);
window.addEventListener('kaief:lang', (ev) => {
  currentLang = ev.detail?.lang || currentLang;
  renderFeedFilters();
  renderSortControl();
  updateSearchLocalization();
  updateSearchUI();
  if (feedLoaded) renderFeed();
  else { feedMessage.textContent = ''; feedFootnote.textContent = ''; }
  toggleFeedDial(false);
  updateFloatingHeight();
});

/* 초기화 */
renderFeedFilters();
renderSortControl();
ensureFeed(false);
handleFeedScroll();
updateFloatingHeight();
