import { initCommonUI, translations, getLang, handleSurfaceScroll } from './app-common.js';

let currentLang = getLang();
const feedList = document.getElementById('feedList');
const feedMessage = document.getElementById('feedMessage');
const feedFootnote = document.getElementById('feedFootnote');
const feedFiltersEl = document.getElementById('feedFilters');
const feedFilterSection = document.getElementById('feedFilter');
const feedSortLabelEl = document.querySelector('.feed-sort-label');
const feedSortSelect = document.getElementById('feedSort');
const feedFilterSection = document.querySelector('.feed-filter');
const feedSearchForm = document.getElementById('feedSearchForm');
const feedSearchInput = document.getElementById('feedSearchInput');
const feedSearchClear = document.getElementById('feedSearchClear');
const feedScrollTopBtn = document.getElementById('feedScrollTop');

let feedLoaded = false;
let cachedEvents = [];
let activeFeedFilter = 'all';
let activeSort = feedSortSelect?.value || 'recent';
let searchQuery = '';
let searchQueryRaw = '';
let lastFeedScrollTop = 0;

initCommonUI({ page: 'feed' });

const feedFilterOptions = [
  { id: 'all', label: { ko: '전체', en: 'All' } },
  { id: 'nmok', label: { ko: '국립중앙박물관', en: 'National Museum of Korea' }, match: ['국립중앙박물관'] },
  { id: 'nlib', label: { ko: '국립중앙도서관', en: 'National Library of Korea' }, match: ['국립중앙도서관'] },
  { id: 'mmca', label: { ko: '국립현대미술관', en: 'MMCA' }, match: ['국립현대미술관'] },
  { id: 'gugak', label: { ko: '국립국악원', en: 'National Gugak Center' }, match: ['국립국악원'] },
  { id: 'folk', label: { ko: '국립민속박물관', en: 'National Folk Museum' }, match: ['국립민속박물관'] }
];

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
  const limit = options.descriptionLimit ?? 420;
  return {
    title: escapeValue(ev.title, t.unknownTitle),
    category: escapeValue(ev.category),
    schedule: escapeValue(ev.period || ev.date || ev.datetime),
    location: escapeValue(ev.place || ev.location),
    host: escapeValue(ev.host || ev.organization),
    status: escapeValue(ev.state || ev.status),
    cost: formatCost(ev.cost, lang),
    description: formatDescription(ev.deep_data || ev.description || ev.overview || '', limit),
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

  const infoParts = [];
  if (data.category) infoParts.push(`📂 ${data.category}`);
  if (data.schedule) infoParts.push(`📅 ${data.schedule}`);
  if (data.location) infoParts.push(`📍 ${data.location}`);
  const infoHTML = infoParts.length ? `<div class="feed-meta">${infoParts.map((p) => `<span>${p}</span>`).join('')}</div>` : '';

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
    ${data.description ? `<div class="feed-desc">${data.description}</div>` : ''}
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

function filterEventsBySearch(events) {
  const query = searchQuery.trim().toLowerCase();
  if (!query) return events.slice();
  return events.filter((ev) => {
    const segments = [
      ev.title,
      ev.host,
      ev.organization,
      ev.category,
      ev.place,
      ev.location,
      ev.deep_data,
      ev.description,
      ev.overview,
      ev.summary,
      ev.tags,
      ev.keywords
    ];
    return segments.some((segment) => {
      if (!segment) return false;
      if (Array.isArray(segment)) return segment.some((value) => String(value).toLowerCase().includes(query));
      if (typeof segment === 'object') return String(Object.values(segment).join(' ')).toLowerCase().includes(query);
      return String(segment).toLowerCase().includes(query);
    });
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

function updateSearchUIState(value = searchQueryRaw) {
  if (!feedSearchForm) return;
  const hasValue = value.length > 0;
  feedSearchForm.classList.toggle('has-value', hasValue);
}

function updateScrollTopButton() {
  if (!feedScrollTopBtn || !feedList) return;
  const shouldShow = feedList.scrollTop > 140;
  feedScrollTopBtn.classList.toggle('show', shouldShow);
}

function updateFeedFilterVisibility(forceShow = false) {
  if (!feedList || !feedFilterSection) return;
  if (forceShow) {
    feedFilterSection.classList.remove('is-hidden');
    lastFeedScrollTop = feedList.scrollTop;
    return;
  }
  const current = feedList.scrollTop;
  const delta = current - lastFeedScrollTop;
  const threshold = 6;
  if (current <= 12) {
    feedFilterSection.classList.remove('is-hidden');
  } else if (delta > threshold) {
    feedFilterSection.classList.add('is-hidden');
  } else if (delta < -threshold) {
    feedFilterSection.classList.remove('is-hidden');
  }
  lastFeedScrollTop = current;
}

function applyFeedSearchTranslations() {
  const t = translations[currentLang];
  if (feedSearchInput) {
    feedSearchInput.placeholder = t.feedSearchPlaceholder;
    feedSearchInput.setAttribute('aria-label', t.feedSearchAria || t.feedSearchPlaceholder);
  }
  if (feedSearchForm) {
    const label = feedSearchForm.querySelector('label[for="feedSearchInput"]');
    if (label) label.textContent = t.feedSearchLabel;
  }
  if (feedSearchClear) {
    feedSearchClear.setAttribute('aria-label', t.feedSearchClearAria);
    const clearText = feedSearchClear.querySelector('.sr-only');
    if (clearText) clearText.textContent = t.feedSearchClearAria;
  }
  if (feedScrollTopBtn) {
    feedScrollTopBtn.setAttribute('aria-label', t.feedScrollTopAria);
    feedScrollTopBtn.setAttribute('title', t.feedScrollTopAria);
    const sr = feedScrollTopBtn.querySelector('.sr-only');
    if (sr) sr.textContent = t.feedScrollTopAria;
  }
}

function handleFeedScrollEvent() {
  if (!feedList) return;
  handleSurfaceScroll(feedList);
  updateFeedFilterVisibility();
  updateScrollTopButton();
}

/* ===== 렌더링/로드 ===== */
function renderFeed() {
  if (!feedLoaded) return;
  const t = translations[currentLang];
  const filteredByFilter = filterEventsByActiveOption(cachedEvents);
  const filtered = filterEventsBySearch(filteredByFilter);
  const sorted = sortEvents(filtered);
  const isSearching = Boolean(searchQuery.trim());
  const emptyTitle = isSearching ? t.feedSearchEmpty : t.feedEmpty;
  const emptyDesc = isSearching ? t.feedSearchEmptyDesc : t.feedEmptyDesc;
  feedList.innerHTML = '';
  if (sorted.length === 0) {
    feedMessage.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">📭</div>
        <div class="empty-state-title">${emptyTitle}</div>
        <div class="empty-state-desc">${emptyDesc}</div>
      </div>
    `;
    feedFootnote.textContent = t.feedFootnote;
    updateScrollTopButton();
    return;
  }
  feedMessage.textContent = '';
  sorted.forEach((ev) => {
    const card = createFeedCard(ev);
    if (card) feedList.appendChild(card);
  });
  feedFootnote.textContent = t.feedFootnote;
  updateScrollTopButton();
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
  }
}

/* ===== 스크롤/언어 이벤트 ===== */
function updateSearchClearVisibility() {
  if (!feedSearchClear) return;
  const hasValue = Boolean(searchQuery);
  feedSearchClear.classList.toggle('show', hasValue);
  if (!hasValue) feedSearchClear.blur();
}

function updateSearchLocale() {
  const t = translations[currentLang];
  if (feedSearchInput) {
    feedSearchInput.placeholder = t.feedSearchPlaceholder;
    feedSearchInput.setAttribute('aria-label', t.feedSearchAria || t.feedSearchPlaceholder);
  }
  if (feedSearchClear) feedSearchClear.setAttribute('aria-label', t.feedSearchClear);
  if (feedScrollTopBtn) feedScrollTopBtn.setAttribute('aria-label', t.feedScrollTopLabel);
}

function updateFloatingToolsState(scrollTop = 0) {
  if (!feedFloatingTools) return;
  feedFloatingTools.classList.remove('offscreen');
  feedFloatingTools.setAttribute('aria-hidden', 'false');
  feedFloatingTools.classList.toggle('is-raised', scrollTop > 12);
  if (feedScrollTopBtn) {
    const shouldShowTop = scrollTop > 160;
    feedScrollTopBtn.classList.toggle('show', shouldShowTop);
  }
}

function handleFeedScroll() {
  if (!feedList) return;
  const currentTop = feedList.scrollTop;
  handleSurfaceScroll(feedList);
  updateFloatingToolsState(currentTop);
  const scrollingDown = currentTop > lastScrollTop + 4;
  const scrollingUp = currentTop < lastScrollTop - 4;
  if (feedFilterSection) {
    if (currentTop > 56 && scrollingDown) {
      feedFilterSection.classList.add('is-hidden');
    } else if (scrollingUp || currentTop <= 56) {
      feedFilterSection.classList.remove('is-hidden');
    }
  }
  lastScrollTop = currentTop;
}

if (feedList) {
  feedList.addEventListener('scroll', handleFeedScrollEvent, { passive: true });
}
if (feedSortSelect) {
  feedSortSelect.addEventListener('change', (event) => {
    activeSort = event.target.value || 'recent';
    renderFeed();
  });
}
if (feedSearchForm) {
  feedSearchForm.addEventListener('submit', (event) => event.preventDefault());
  feedSearchForm.addEventListener('reset', () => {
    searchQueryRaw = '';
    searchQuery = '';
    updateSearchUIState('');
    renderFeed();
    updateScrollTopButton();
  });
}
if (feedSearchInput) {
  feedSearchInput.addEventListener('input', (event) => {
    const value = event.target.value || '';
    searchQueryRaw = value;
    searchQuery = value.trim();
    updateSearchUIState(value);
    renderFeed();
  });
}
if (feedScrollTopBtn) {
  feedScrollTopBtn.addEventListener('click', () => {
    if (!feedList) return;
    feedList.scrollTo({ top: 0, behavior: 'smooth' });
    updateFeedFilterVisibility(true);
  });
}
window.addEventListener('kaief:lang', (ev) => {
  currentLang = ev.detail?.lang || currentLang;
  renderFeedFilters();
  renderSortControl();
  applyFeedSearchTranslations();
  updateSearchUIState(searchQueryRaw);
  if (feedLoaded) renderFeed();
  else { feedMessage.textContent = ''; feedFootnote.textContent = ''; }
});

/* 초기화 */
renderFeedFilters();
renderSortControl();
applyFeedSearchTranslations();
updateSearchUIState();
ensureFeed(false);
updateFeedFilterVisibility(true);
handleFeedScrollEvent();
