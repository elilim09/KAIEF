import { initCommonUI, translations, getLang, handleSurfaceScroll, initFabDial } from './app-common.js';

let currentLang = getLang();
const chatList = document.getElementById('chatList'); // 채팅 메시지 리스트
const input = document.getElementById('input'); // 메시지 입력창
const send = document.getElementById('send'); // 전송 버튼
const chips = document.getElementById('chips'); // 아래 프리셋 칩 컨테이너 - 아래 이번 주말 추천 일정 어쩌구같은거
const chipLabel = document.getElementById('chipLabel'); // 아래 프리셋 칩 라벨
const charCounter = document.getElementById('charCounter'); // 입력 문자 수 카운터
const scrollToBottom = document.getElementById('scrollToBottom'); // 스크롤 하단 이동 버튼
const composer = document.querySelector('.composer'); // 입력창 컨테이너
const root = document.documentElement; 
const introBadge = document.getElementById('introBadge'); // 인트로 섹션 어시스턴트 배지
const introText = document.getElementById('introText'); // 인트로 섹션 텍스트

const inputHint = document.getElementById('inputHint'); // 쓸대없는거
const introHint = document.getElementById('introHint'); // 쓸대없는거

let chatHistory = []; // 대화 기록
let typingEl = null; // 타이핑 중 표시 엘리먼트
let lastScrollTop = 0; // 마지막 스크롤 위치

initCommonUI({ page: 'chat' }); // 공통 UI 초기화
initFabDial(); // 플로팅 액션 버튼 초기화

// 입력창 높이에 따라 CSS 변수 업데이트
function updateComposerHeight() {
  if (!composer || !root) return;
  const height = composer.getBoundingClientRect().height || 0; // 입력창 컨테이너 높이 측정
  if (height > 0) {
    root.style.setProperty('--composer-height', `${Math.ceil(height)}px`); // CSS 변수 업데이트
  }
}

if (composer) { 
  updateComposerHeight() ;
  if (typeof ResizeObserver !== 'undefined') { // ResizeObserver로 입력창 크기 변경 감지
    const ro = new ResizeObserver(updateComposerHeight); // 리사이즈 옵저버 생성
    ro.observe(composer); // 입력창 컨테이너 관찰 시작
  }
  window.addEventListener('resize', updateComposerHeight); // 윈도우 리사이즈 시에도 업데이트
}

/* ===== 유틸 ===== */
function escapeHTML(str) {
  return String(str).replace(/[&<>"']/g, (m) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[m]));
  // 특수문자를 대응되는 HTML 엔티티로 변환
}
function trimText(value, limit = 600) { // 텍스트 자르기
  const raw = String(value ?? '').trim();
  if (!raw) return ''; 
  if (raw.length <= limit) return raw; // 길이가 제한 이내인 경우 그대로 반환
  return `${raw.slice(0, limit)}…`; // 제한 초과 시 자르고 말줄임표 추가
}
function formatDescription(value, limit = 600) { // 설명 텍스트 포맷팅
  const trimmed = trimText(value, limit); // 텍스트 자르기
  if (!trimmed) return '';
  return escapeHTML(trimmed).replace(/\n+/g, '<br/>'); // HTML 이스케이프 및 줄바꿈 변환
}
function formatMultiline(text) { // 여러 줄 텍스트 포맷팅
  if (!text) return ''; 
  return escapeHTML(String(text)).replace(/\n+/g, '<br/>'); // HTML 이스케이프 및 줄바꿈 변환
}
function escapeValue(value, fallback = '') { // 값 이스케이프 및 대체값 처리
  const raw = value ?? '';
  const text = String(raw).trim(); // null/undefined 방지
  if (!text) return fallback ? escapeHTML(fallback) : ''; // 빈 문자열인 경우 대체값 사용
  return escapeHTML(text); // 이스케이프된 값 반환
}
function formatCost(value, lang) { // 비용, 무료 표시 처리
  if (value === null || value === undefined) return '';
  const trimmed = String(value).trim(); // null/undefined 방지
  if (!trimmed) return '';
  if (['0', '무료', 'free'].includes(trimmed.toLowerCase())) { // 무료인 경우
    return escapeHTML(translations[lang].costFree);
  }
  return escapeHTML(trimmed);
}
function extractEvent(ev, lang, options = {}) { //d이벤트 데이터 정리
  if (!ev || typeof ev !== 'object') return null;
  const t = translations[lang]; // 언어별 번역 데이터
  const limit = options.descriptionLimit ?? 600; // 설명 길이 제한
  return {
    title: escapeValue(ev.title, t.unknownTitle),
    schedule: escapeValue(ev.period || ev.date || ev.datetime),
    location: escapeValue(ev.place || ev.location),
    host: escapeValue(ev.host || ev.organization),
    status: escapeValue(ev.state || ev.status),
    cost: formatCost(ev.cost, lang),
    description: formatDescription(ev.deep_data || ev.description || ev.overview || '', limit),
    link: escapeValue(ev.url || '')
  };
}
function assistantHeaderHTML() { // 어시스턴트 헤더 HTML 생성
  return `<div class="assistant-header"><div class="w-6 h-6 rounded-full" style="background:linear-gradient(90deg,#34D399,#06B6D4)"></div><span class="text-xs opacity-70 font-medium">${translations[currentLang].assistantBadge}</span></div>`;
}
function renderEventCard(ev, options = {}) { //이벤트 카드 생성
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

/* ===== 채팅 UI ===== */
function addBubble(role, html) { // 채팅 버블 추가
  const row = document.createElement('div');
  row.className = 'flex ' + (role === 'user' ? 'justify-end' : 'justify-start');
  row.innerHTML = `<div class="bubble ${role}">${html}</div>`;
  chatList.appendChild(row);
  chatList.scrollTo({ top: chatList.scrollHeight, behavior: 'smooth' });
}
function showTyping() { // 타이핑 중 표시
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
function hideTyping() { // 타이핑 중 표시 제거
  if (typingEl) { typingEl.remove(); typingEl = null; }
}

function updateCharCounter() { // 문자 수 카운터 업데이트
  const length = input.value.length;
  charCounter.textContent = `${length}/500`;
  if (length >= 450) charCounter.classList.add('warning');
  else charCounter.classList.remove('warning');
}
function updateSend() { // 전송 버튼 상태 업데이트
  const hasText = input.value.trim().length > 0;
  send.setAttribute('data-compact', hasText ? 'false' : 'true');
  const labelEl = send.querySelector('.label');
  if (labelEl) labelEl.setAttribute('aria-hidden', hasText ? 'false' : 'true');
}

function handleScrollToBottom() { // 스크롤 하단 이동 버튼 처리
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
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { // Shift+Enter는 줄바꿈
    e.preventDefault();
    sendMessage();
  }
});
send.addEventListener('click', sendMessage);

/* ===== 프리셋 칩 ===== */
function renderChips() { // 정해둔 추천 질문 렌더링
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
chips.addEventListener('click', (e) => { //클릭 시 자동 채움
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
  let html = assistantHeaderHTML();

  // reason
  const reasonData = payload.reason;
  const reasonText = typeof reasonData === 'string'
    ? reasonData
    : (reasonData?.[currentLang] || reasonData?.ko || '');
  if (reasonText) html += `<div class="mt-3 text-sm leading-6">${formatMultiline(reasonText)}</div>`;

  // recommended_event 처리
  const events = Array.isArray(payload.recommended_event)
    ? payload.recommended_event
    : [payload.recommended_event || {}];

  events.forEach(ev => {
    html += renderEventCard(ev, { showLink: true });
  });

  return html;
}

async function sendMessage() {
  const text = input.value.trim();
  if (!text) return;
  addBubble('user', escapeHTML(text));

  // 대화 기록에 유저 메시지 추가
  chatHistory.push({ role: 'user', content: text });

  input.value = '';
  updateSend(); updateCharCounter(); showTyping();

  try {
    const res = await fetch('/api/chat', { // 백엔드에 메시지 전송
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: text,
        chat_history: chatHistory,
      })
    });


    const data = await res.json();
    hideTyping();

    const rawResponse = data?.response;
    let responsePayload = {};
    if (typeof rawResponse === 'object') responsePayload = rawResponse;
    else responsePayload = { reason: { ko: rawResponse, en: rawResponse }, recommended_event: {} };

    // ✅ Assistant의 답변도 기록에 추가
    chatHistory.push({ role: 'assistant', content: rawResponse });

    const html = buildAssistantResponse(responsePayload);
    addBubble('assistant', html);

  } catch (err) {
    hideTyping();
    const t = translations[currentLang];
    addBubble('assistant', `
      ${assistantHeaderHTML()}
      <div class="text-sm">${t.errorMessage}</div>
      <div class="mt-2 text-xs opacity-70">${escapeHTML(String(err))}</div>
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
