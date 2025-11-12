import { initCommonUI, translations, getLang, handleSurfaceScroll, initFabDial } from './app-common.js';

let currentLang = getLang();
const chatList = document.getElementById('chatList');
const input = document.getElementById('input');
const send = document.getElementById('send');
const chips = document.getElementById('chips');
const chipLabel = document.getElementById('chipLabel');
const charCounter = document.getElementById('charCounter');
const inputHint = document.getElementById('inputHint');
const scrollToBottom = document.getElementById('scrollToBottom');
const composer = document.querySelector('.composer');
const root = document.documentElement;
const introBadge = document.getElementById('introBadge');
const introText = document.getElementById('introText');
const introHint = document.getElementById('introHint');

let typingEl = null;
let lastScrollTop = 0;

const SESSION_KEY = 'kaief_chat_client_id';
let clientId = null;
try {
  clientId = window.sessionStorage.getItem(SESSION_KEY);
  if (!clientId) {
    const uuid = typeof crypto !== 'undefined' && crypto.randomUUID
      ? crypto.randomUUID()
      : `anon-${Math.random().toString(36).slice(2, 10)}`;
    clientId = `web-${uuid}`;
    window.sessionStorage.setItem(SESSION_KEY, clientId);
  }
} catch (err) {
  clientId = `web-${Math.random().toString(36).slice(2, 10)}`;
}

initCommonUI({ page: 'chat' });
initFabDial();

function updateComposerHeight() {
  if (!composer || !root) return;
  const height = composer.getBoundingClientRect().height || 0;
  if (height > 0) {
    root.style.setProperty('--composer-height', `${Math.ceil(height)}px`);
  }
}

if (composer) {
  updateComposerHeight();
  if (typeof ResizeObserver !== 'undefined') {
    const ro = new ResizeObserver(updateComposerHeight);
    ro.observe(composer);
  }
  window.addEventListener('resize', updateComposerHeight);
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
function formatMultiline(text) {
  if (!text) return '';
  return escapeHTML(String(text)).replace(/\n+/g, '<br/>');
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
  const limit = options.descriptionLimit ?? 600;
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
function assistantHeaderHTML() {
  return `<div class="assistant-header"><div class="w-6 h-6 rounded-full" style="background:linear-gradient(90deg,#34D399,#06B6D4)"></div><span class="text-xs opacity-70 font-medium">${translations[currentLang].assistantBadge}</span></div>`;
}
function renderEventCard(ev, options = {}) {
  const lang = options.lang || currentLang;
  const t = translations[lang];
  if (!ev || Object.keys(ev).length === 0) {
    return `<div class="text-sm opacity-80">${t.noEvent}</div>`;
  }
  const data = extractEvent(ev, lang, options);
  if (!data) return `<div class="text-sm opacity-80">${t.noEvent}</div>`;
  const infoParts = [];
  if (data.category) infoParts.push(`📂 ${t.eventLabels.category}: ${data.category}`);
  if (data.schedule) infoParts.push(`📅 ${t.eventLabels.schedule}: ${data.schedule}`);
  if (data.location) infoParts.push(`📍 ${t.eventLabels.location}: ${data.location}`);
  const metaParts = [];
  if (data.host) metaParts.push(`🏢 ${t.eventLabels.host}: ${data.host}`);
  if (data.status) metaParts.push(`📌 ${t.eventLabels.status}: ${data.status}`);
  if (data.cost) metaParts.push(`💰 ${t.eventLabels.cost}: ${data.cost}`);
  const link = options.showLink && data.link ? `<a href="${data.link}" target="_blank" rel="noopener">${t.actions.viewDetail}</a>` : '';
  return `
    <div class="${options.wrapperClass || 'mt-2 p-3 rounded-[16px] border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-low)] shadow-sm'}">
      <div class="text-base font-semibold mb-1" style="letter-spacing:-0.01em">${data.title}</div>
      ${infoParts.length ? `<div class="flex flex-wrap gap-x-3 gap-y-1 text-sm opacity-80">${infoParts.map((p) => `<div>${p}</div>`).join('')}</div>` : ''}
      ${metaParts.length ? `<div class="flex flex-wrap gap-x-3 gap-y-1 text-xs mt-3 opacity-70">${metaParts.map((p) => `<div>${p}</div>`).join('')}</div>` : ''}
      ${data.description ? `<div class="mt-3 text-sm leading-6">${data.description}</div>` : ''}
      ${link ? `<div class="mt-3 text-sm font-semibold">${link}</div>` : ''}
    </div>
  `;
}
function renderKeywords(kw = []) {
  if (!Array.isArray(kw) || kw.length === 0) return '';
  const pills = kw.slice(0, 8).map((k) => `<span class="px-2 py-1 rounded-full border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container)] text-xs">${escapeHTML(k)}</span>`).join(' ');
  return `<div class="mt-2 flex flex-wrap gap-1 items-center">${pills}</div>`;
}

/* ===== 채팅 UI ===== */
function addBubble(role, html) {
  const row = document.createElement('div');
  row.className = 'flex ' + (role === 'user' ? 'justify-end' : 'justify-start');
  row.innerHTML = `<div class="bubble ${role}">${html}</div>`;
  chatList.appendChild(row);
  chatList.scrollTo({ top: chatList.scrollHeight, behavior: 'smooth' });
}
function showTyping() {
  hideTyping();
  const row = document.createElement('div');
  row.className = 'flex justify-start';
  const t = translations[currentLang];
  row.innerHTML = `
    <div class="bubble assistant">
      ${assistantHeaderHTML()}
      <div class="text-xs opacity-70 mb-2">${t.typingLabel}</div>
      <div class="dots"><span></span><span></span><span></span></div>
    </div>
  `;
  typingEl = row;
  chatList.appendChild(row);
  chatList.scrollTo({ top: chatList.scrollHeight, behavior: 'smooth' });
}
function hideTyping() {
  if (typingEl) { typingEl.remove(); typingEl = null; }
}

function updateCharCounter() {
  const length = input.value.length;
  charCounter.textContent = `${length}/500`;
  if (length >= 450) charCounter.classList.add('warning');
  else charCounter.classList.remove('warning');
}
function updateSend() {
  const hasText = input.value.trim().length > 0;
  send.setAttribute('data-compact', hasText ? 'false' : 'true');
  const labelEl = send.querySelector('.label');
  if (labelEl) labelEl.setAttribute('aria-hidden', hasText ? 'false' : 'true');
}

function handleScrollToBottom() {
  const scrollTop = chatList.scrollTop;
  const scrollHeight = chatList.scrollHeight;
  const clientHeight = chatList.clientHeight;
  const isNearBottom = scrollHeight - scrollTop - clientHeight < 100;
  if (isNearBottom) scrollToBottom.classList.remove('show');
  else if (scrollTop < lastScrollTop) scrollToBottom.classList.add('show');
  lastScrollTop = scrollTop;
}
scrollToBottom.addEventListener('click', () => chatList.scrollTo({ top: chatList.scrollHeight, behavior: 'smooth' }));

input.addEventListener('input', () => { updateSend(); updateCharCounter(); });
input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    sendMessage();
  }
});
send.addEventListener('click', sendMessage);

/* ===== 프리셋 칩 ===== */
function renderChips() {
  chips.innerHTML = '';
  const presets = translations[currentLang].chips || [];
  presets.forEach((preset) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'chip';
    btn.dataset.text = preset.prompt;
    btn.textContent = preset.label;
    chips.appendChild(btn);
  });
}
chips.addEventListener('click', (e) => {
  const btn = e.target.closest('.chip');
  if (!btn) return;
  input.value = btn.dataset.text || '';
  updateSend();
  updateCharCounter();
  input.focus();
});

/* ===== 언어 적용(인트로/힌트/플레이스홀더 등) ===== */
function updateIntroSection() {
  const t = translations[currentLang];
  if (introBadge) introBadge.textContent = t.assistantBadge;
  if (introText) introText.innerHTML = t.assistantIntro;
  if (introHint) introHint.textContent = t.assistantSuggestion;
  if (chipLabel) chipLabel.textContent = t.chipLabel;
  if (input) {
    input.placeholder = t.placeholder;
    input.setAttribute('aria-label', t.placeholder);
  }
  const labelEl = send.querySelector('.label');
  if (labelEl) labelEl.textContent = t.sendLabel;
  const hintEl = inputHint;
  if (hintEl) hintEl.textContent = t.inputHint;
}

/* ===== 메시지 송수신 ===== */
function buildAssistantResponse(payload) {
  const t = translations[currentLang];
  const keywords = Array.isArray(payload.keywords) ? payload.keywords : [];

  let message = typeof payload.message === 'string' ? payload.message.trim() : '';
  if (!message) {
    const legacyReason = payload.reason;
    if (typeof legacyReason === 'string') message = legacyReason;
    else if (legacyReason && typeof legacyReason === 'object') message = legacyReason[currentLang] || legacyReason.ko || '';
  }

  let events = Array.isArray(payload.events) ? payload.events : [];
  if (!events.length && payload.recommended_event && Object.keys(payload.recommended_event).length) {
    events = [payload.recommended_event];
  }

  const highlights = Array.isArray(payload.highlights) ? payload.highlights : [];
  const notes = typeof payload.notes === 'string' ? payload.notes.trim() : '';

  let html = assistantHeaderHTML();
  if (keywords.length) {
    html += `<div class="text-sm opacity-70 mb-1">${t.keywordTitle}</div>${renderKeywords(keywords)}`;
  }
  if (message) {
    html += `<div class="mt-3 text-sm leading-6">${formatMultiline(message)}</div>`;
  }
  if (highlights.length) {
    const items = highlights.map((item) => `<li>${escapeHTML(item)}</li>`).join('');
    html += `<ul class="mt-3 text-sm leading-6 list-disc pl-5">${items}</ul>`;
  }
  if (events.length) {
    const cards = events.map((ev) => renderEventCard(ev, { showLink: true, lang: currentLang })).join('');
    html += `<div class="mt-3 flex flex-col gap-3">${cards}</div>`;
  }
  if (notes) {
    html += `<div class="mt-3 text-xs opacity-70">${escapeHTML(notes)}</div>`;
  }
  if (!message && !events.length) {
    html += `<div class="mt-2 text-sm opacity-80">${t.noEvent}</div>`;
  }
  return html;
}
async function sendMessage() {
  const text = input.value.trim();
  if (!text) return;
  addBubble('user', escapeHTML(text));
  input.value = '';
  updateSend(); updateCharCounter(); showTyping();
  try {
    const res = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, user_id: clientId })
    });
    if (!res.ok) {
      const errText = await res.text();
      throw new Error(errText || `${res.status} ${res.statusText}`);
    }
    const data = await res.json();
    hideTyping();
    const rawResponse = data?.response;
    let responsePayload = {};
    if (rawResponse && typeof rawResponse === 'object') responsePayload = rawResponse;
    else if (typeof rawResponse === 'string') responsePayload = { message: rawResponse };
    const html = buildAssistantResponse(responsePayload);
    addBubble('assistant', html);
  } catch (err) {
    hideTyping();
    const t = translations[currentLang];
    addBubble('assistant', `
      ${assistantHeaderHTML()}
      <div class="text-sm">${t.errorMessage}</div>
      <div class="mt-2 text-xs opacity-70">${escapeHTML(String(err))}</div>
      <button class="retry-button" onclick="document.getElementById('input').value='${escapeHTML(text)}'; document.getElementById('send').click();">${t.errorRetry}</button>
    `);
  }
}

/* ===== 스크롤/초기화 ===== */
chatList.addEventListener('scroll', () => {
  handleSurfaceScroll(chatList);
  handleScrollToBottom();
});

// 언어 변경 브로드캐스트 수신
window.addEventListener('kaief:lang', (ev) => {
  currentLang = ev.detail?.lang || currentLang;
  updateIntroSection();
  renderChips();
});

updateIntroSection();
renderChips();

updateSend();
updateCharCounter();
handleSurfaceScroll(chatList);
handleScrollToBottom();
