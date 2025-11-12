import { initCommonUI, translations, getLang, handleSurfaceScroll } from './app-common.js';

let currentLang = getLang();
const feedList = document.getElementById('feedList');
const feedMessage = document.getElementById('feedMessage');
const feedFootnote = document.getElementById('feedFootnote');
const feedFiltersEl = document.getElementById('feedFilters');

let feedLoaded = false;
let cachedEvents = [];
let activeFeedFilter = 'all';

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

/* ===== 렌더링/로드 ===== */
function renderFeed() {
  if (!feedLoaded) return;
  const t = translations[currentLang];
  const filtered = filterEventsByActiveOption(cachedEvents);
  feedList.innerHTML = '';
  if (filtered.length === 0) {
    feedMessage.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">📭</div>
        <div class="empty-state-title">${t.feedEmpty}</div>
        <div class="empty-state-desc">${t.feedEmptyDesc}</div>
      </div>
    `;
    feedFootnote.textContent = t.feedFootnote;
    return;
  }
  feedMessage.textContent = '';
  const locale = currentLang === 'ko' ? 'ko' : 'en';
  const sorted = filtered.slice().sort((a, b) => {
    const hostA = String(a.host || a.organization || '');
    const hostB = String(b.host || b.organization || '');
    const titleA = String(a.title || '');
    const titleB = String(b.title || '');
    const hostCompare = hostA.localeCompare(hostB, locale, { sensitivity: 'base' });
    if (hostCompare !== 0) return hostCompare;
    return titleA.localeCompare(titleB, locale, { sensitivity: 'base' });
  });
  sorted.forEach((ev) => {
    const card = createFeedCard(ev);
    if (card) feedList.appendChild(card);
  });
  feedFootnote.textContent = t.feedFootnote;
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
feedList.addEventListener('scroll', () => handleSurfaceScroll(feedList));
window.addEventListener('kaief:lang', (ev) => {
  currentLang = ev.detail?.lang || currentLang;
  renderFeedFilters();
  if (feedLoaded) renderFeed();
  else { feedMessage.textContent = ''; feedFootnote.textContent = ''; }
});

/* 초기화 */
renderFeedFilters();
ensureFeed(false);
handleSurfaceScroll(feedList);