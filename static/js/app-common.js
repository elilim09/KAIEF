import { argbFromHex, themeFromSourceColor, applyTheme } from "https://esm.run/@material/material-color-utilities";

export const STORAGE_KEYS = { theme: 'kaief_theme', seed: 'kaief_seed', lang: 'kaief_lang' };

export const translations = {
  ko: {
    brandLarge: "대한민국 행사 AI 파인더",
    brandSmall: "KAIEF",
    paletteAria: "브랜드 색 설정",
    themeAria: "테마 전환",
    navChat: "AI 챗봇",
    navFeed: "행사 피드",
    languageAria: "언어 전환",
    fabChatLabel: "AI 챗봇",
    fabChatAria: "AI 챗봇 페이지로 이동",
    fabFeedLabel: "행사 피드",
    fabFeedAria: "행사 피드 페이지로 이동",
    fabLanguageLabel: "한/영",
    fabLanguageAria: "언어 전환",
    documentTitle: "KAIEF – 대한민국 행사 AI 파인더",
    assistantBadge: "AI 어시스턴트",
    assistantIntro: "안녕하세요! 🎉<br/>대한민국의 주요 문화·예술 행사를 실시간으로 찾아드립니다. 일정이나 관심사를 알려주세요!",
    assistantSuggestion: "관심 키워드를 누르면 질문이 입력돼요.",
    chipLabel: "빠른 질문",
    placeholder: "무엇이든 물어보세요...",
    sendLabel: "전송",
    sendAria: "메시지 전송",
    moreAria: "추가 옵션",
    typingLabel: "입력 중...",
    keywordTitle: "🔎 추출된 키워드",
    noEvent: "관련된 행사를 찾지 못했어요. 키워드를 조금 바꿔보시겠어요? (예: 날짜/지역/분야 추가)",
    errorMessage: "요청 처리 중 오류가 발생했어요.",
    errorRetry: "다시 시도",
    feedTitle: "실시간 행사 피드",
    feedDescription: "국립 문화·예술 기관의 최신 행사 소식을 모아서 제공합니다.",
    feedFilterLabel: "주요 기관 바로보기",
    feedSortLabel: "정렬",
    feedSortAria: "행사 정렬 기준 선택",
    feedSortRecent: "최신순",
    feedSortTitle: "제목순",
    feedLoading: "행사 데이터를 불러오는 중이에요...",
    feedTranslating: "행사 정보를 영어로 번역하는 중이에요...",
    feedEmpty: "현재 조건에 맞는 행사가 없습니다.",
    feedEmptyDesc: "필터를 변경하거나 나중에 다시 확인해주세요.",
    feedError: "행사 데이터를 불러오지 못했어요.",
    feedFootnote: "데이터 출처: 문화체육관광부 산하 국립기관 실시간 수집",
    feedSearchPlaceholder: "행사를 검색해보세요",
    feedSearchAria: "피드 검색",
    feedSearchClear: "검색어 지우기",
    feedSearchSubmit: "검색",
    feedSearchEmpty: "검색 결과가 없습니다.",
    feedSearchEmptyDesc: "다른 키워드를 입력하거나 필터를 변경해보세요.",
    feedScrollTop: "최상단으로 이동",
    inputHint: "Enter로 전송 · Shift+Enter로 줄바꿈",
    scrollToBottom: "최신 메시지로 이동",
    actions: { viewDetail: "자세히 보기", openMap: "이동" },
    eventLabels: { category: "분류", schedule: "일정", location: "장소", host: "주관", status: "상태", cost: "참가비" },
    costFree: "무료",
    unknownTitle: "제목 미상",
    unknownValue: "정보 없음",
    chips: [
      { label: "🎪 이번 주말 추천", prompt: "이번 주말에 갈 만한 전국 문화 행사를 추천해줘." },
      { label: "🎨 미술 전시 찾기", prompt: "국립현대미술관에서 진행 중인 전시를 알려줘." },
      { label: "📚 도서관 프로그램", prompt: "국립중앙도서관에서 참여할 수 있는 체험이나 강연이 있을까?" },
      { label: "🎵 국악 공연", prompt: "국립국악원에서 곧 진행되는 공연을 알려줘." }
    ],
  },
  en: {
    brandLarge: "Korea Event AI Finder",
    brandSmall: "KAIEF",
    paletteAria: "Set brand color",
    themeAria: "Toggle theme",
    navChat: "AI Chatbot",
    navFeed: "Event feed",
    languageAria: "Switch language",
    fabChatLabel: "Chatbot",
    fabChatAria: "Go to AI chatbot page",
    fabFeedLabel: "Event feed",
    fabFeedAria: "Go to event feed page",
    fabLanguageLabel: "EN/KR",
    fabLanguageAria: "Toggle language",
    documentTitle: "KAIEF – Korea Event AI Finder",
    assistantBadge: "AI Assistant",
    assistantIntro: "Hello! 🎉<br/>I surface cultural and arts events across Korea in real time. Tell me about your schedule or interests!",
    assistantSuggestion: "Tap a quick prompt to pre-fill your question.",
    chipLabel: "Quick prompts",
    placeholder: "Ask anything about events...",
    sendLabel: "Send",
    sendAria: "Send message",
    moreAria: "More options",
    typingLabel: "Typing...",
    keywordTitle: "🔎 Extracted keywords",
    noEvent: "I couldn't find a matching event. Try adding date, region, or theme keywords.",
    errorMessage: "Something went wrong.",
    errorRetry: "Retry",
    feedTitle: "Live event feed",
    feedDescription: "Fresh cultural and arts programs curated from national institutions across Korea.",
    feedFilterLabel: "Featured institutions",
    feedSortLabel: "Sort",
    feedSortAria: "Select how to sort events",
    feedSortRecent: "Newest first",
    feedSortTitle: "Title A-Z",
    feedLoading: "Loading event data...",
    feedTranslating: "Translating event information...",
    feedEmpty: "No events match the current filter.",
    feedEmptyDesc: "Try another option or check back later.",
    feedError: "Unable to load event data right now.",
    feedFootnote: "Sources: Ministry of Culture, Sports and Tourism national institutions",
    feedSearchPlaceholder: "Search events in the feed",
    feedSearchAria: "Search feed",
    feedSearchClear: "Clear search term",
    feedSearchSubmit: "Search",
    feedSearchEmpty: "No events match your search.",
    feedSearchEmptyDesc: "Try different keywords or adjust the filters.",
    feedScrollTop: "Back to top",
    inputHint: "Enter to send · Shift+Enter for new line",
    scrollToBottom: "Scroll to latest",
    actions: { viewDetail: "View details", openMap: "Directions" },
    eventLabels: { category: "Category", schedule: "Schedule", location: "Location", host: "Organizer", status: "Status", cost: "Admission" },
    costFree: "Free",
    unknownTitle: "Untitled event",
    unknownValue: "Not available",
    chips: [
      { label: "🎪 Weekend picks", prompt: "What cultural events this weekend are worth visiting around Korea?" },
      { label: "🎨 Exhibition finder", prompt: "Show me exhibitions currently running at the National Museum of Modern and Contemporary Art." },
      { label: "📚 Library programs", prompt: "Are there any workshops or lectures at the National Library of Korea?" },
      { label: "🎵 Gugak performance", prompt: "Which performances are coming up at the National Gugak Center?" }
    ],
  }
};

let currentLang = localStorage.getItem(STORAGE_KEYS.lang) === 'en' ? 'en' : 'ko';
let currentSeed = localStorage.getItem(STORAGE_KEYS.seed) || '#6366F1';
let langTransitionTimer = null;
let langTransitionFinishTimer = null;

export const getLang = () => currentLang;
export const setLang = (lang, options = {}) => {
  const nextLang = lang === 'en' ? 'en' : 'ko';
  if (nextLang === currentLang) return;

  const animated = options.animated !== false && !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const root = document.documentElement;

  const commitLanguage = () => {
    currentLang = nextLang;
    root.setAttribute('data-lang', currentLang);
    root.setAttribute('data-lang-transition', animated ? 'in' : '');
    if (!animated) root.removeAttribute('data-lang-transition');

    localStorage.setItem(STORAGE_KEYS.lang, currentLang);
    applyI18n();
    window.dispatchEvent(new CustomEvent('kaief:lang', { detail: { lang: currentLang } }));

    if (animated) {
      clearTimeout(langTransitionFinishTimer);
      langTransitionFinishTimer = setTimeout(() => {
        root.removeAttribute('data-lang-transition');
      }, 190);
    }
  };

  clearTimeout(langTransitionTimer);
  clearTimeout(langTransitionFinishTimer);

  if (!animated) {
    commitLanguage();
    return;
  }

  root.setAttribute('data-lang-transition', 'out');
  langTransitionTimer = setTimeout(commitLanguage, 95);
};

export function initFabDial({ triggerId = 'moreBtn', wrapId = 'moreWrap', dialId = 'fabDial' } = {}) {
  const trigger = typeof triggerId === 'string' ? document.getElementById(triggerId) : triggerId;
  const wrap = typeof wrapId === 'string' ? document.getElementById(wrapId) : wrapId;
  const dial = typeof dialId === 'string' ? document.getElementById(dialId) : dialId;

  if (!trigger || !wrap || !dial) return () => {};

  let open = false;
  const toggle = (force) => {
    open = typeof force === 'boolean' ? force : !open;
    dial.classList.toggle('open', open);
    trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
  };

  const handleTriggerClick = (event) => {
    event.stopPropagation();
    toggle();
  };

  const handleDocumentClick = (event) => {
    if (open && !wrap.contains(event.target)) toggle(false);
  };

  const handleDialClick = (event) => {
    const btn = event.target.closest('.mini-fab');
    if (!btn) return;
    const action = btn.dataset.action;
    if (action === 'go-chat' || action === 'go-feed') {
      const href = btn.dataset.href;
      if (href) window.location.href = href;
    } else if (action === 'toggle-language') {
      setLang(getLang() === 'ko' ? 'en' : 'ko');
    }
    toggle(false);
  };

  trigger.addEventListener('click', handleTriggerClick);
  document.addEventListener('click', handleDocumentClick);
  dial.addEventListener('click', handleDialClick);

  toggle(false);

  return () => {
    trigger.removeEventListener('click', handleTriggerClick);
    document.removeEventListener('click', handleDocumentClick);
    dial.removeEventListener('click', handleDialClick);
  };
}

export const isDark = () => document.documentElement.getAttribute('data-theme') === 'dark';

export function applyThemeFromSeed(hex) {
  try {
    const theme = themeFromSourceColor(argbFromHex(hex));
    applyTheme(theme, { target: document.documentElement, dark: isDark() });
    document.documentElement.style.setProperty(
      '--gradient-primary',
      `linear-gradient(135deg, var(--md-sys-color-primary) 0%, color-mix(in oklab, var(--md-sys-color-primary) 85%, #ffffff) 50%, color-mix(in oklab, var(--md-sys-color-primary) 70%, #ffffff) 100%)`
    );
    currentSeed = hex;
    localStorage.setItem(STORAGE_KEYS.seed, hex);
  } catch (e) {
    console.warn('Dynamic color apply failed', e);
  }
}

export function applyThemeMode(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem(STORAGE_KEYS.theme, theme);
  const sun = document.getElementById('sun');
  const moon = document.getElementById('moon');
  const dark = theme === 'dark';
  if (sun && moon) {
    sun.style.display = dark ? 'none' : 'block';
    moon.style.display = dark ? 'block' : 'none';
  }
  applyThemeFromSeed(currentSeed);
}

function applyI18n() {
  const t = translations[currentLang];
  document.title = t.documentTitle;
  document.documentElement.lang = currentLang === 'ko' ? 'ko' : 'en';
  document.documentElement.setAttribute('data-lang', currentLang);
  document.querySelectorAll('[data-i18n]').forEach((el) => {
    const key = el.dataset.i18n;
    if (t[key]) el.textContent = t[key];
  });
  const languageToggle = document.getElementById('languageToggle');
  if (languageToggle) {
    languageToggle.textContent = currentLang === 'ko' ? 'EN' : 'KO';
    languageToggle.setAttribute('lang', currentLang === 'ko' ? 'en' : 'ko');
    languageToggle.setAttribute('aria-label', t.languageAria);
  }
  const paletteBtn = document.getElementById('paletteBtn');
  if (paletteBtn) paletteBtn.setAttribute('aria-label', t.paletteAria);
  const themeToggle = document.getElementById('themeToggle');
  if (themeToggle) themeToggle.setAttribute('aria-label', t.themeAria);
  const chatFab = document.querySelector('.mini-fab[data-action="go-chat"]');
  if (chatFab) {
    chatFab.setAttribute('aria-label', t.fabChatAria || t.navChat);
    chatFab.setAttribute('title', t.fabChatAria || t.navChat);
  }
  const feedFab = document.querySelector('.mini-fab[data-action="go-feed"]');
  if (feedFab) {
    feedFab.setAttribute('aria-label', t.fabFeedAria || t.navFeed);
    feedFab.setAttribute('title', t.fabFeedAria || t.navFeed);
  }
  const languageFab = document.querySelector('.mini-fab[data-action="toggle-language"]');
  if (languageFab) {
    languageFab.setAttribute('aria-label', t.fabLanguageAria || t.languageAria);
    languageFab.setAttribute('title', t.fabLanguageAria || t.languageAria);
  }
  const moreBtn = document.getElementById('moreBtn');
  if (moreBtn) {
    moreBtn.setAttribute('aria-label', t.moreAria);
    moreBtn.setAttribute('title', t.moreAria);
  }
}

export function handleSurfaceScroll(target) {
  const appBar = document.getElementById('appBar');
  if (!target || !appBar) return;
  const shouldCompact = target.scrollTop > 6;
  appBar.classList.toggle('compact', shouldCompact);
}

function wireHeaderCommon() {
  // 테마 초기화
  applyThemeMode(localStorage.getItem(STORAGE_KEYS.theme) || 'light');
  applyThemeFromSeed(currentSeed);

  const themeToggle = document.getElementById('themeToggle');
  if (themeToggle) {
    themeToggle.addEventListener('click', () => {
      applyThemeMode(isDark() ? 'light' : 'dark');
    });
  }

  // 팔레트 패널
  const paletteBtn = document.getElementById('paletteBtn');
  const brandPanel = document.getElementById('brandPanel');
  const customSeed = document.getElementById('customSeed');
  const customSeedHex = document.getElementById('customSeedHex');
  const applySeed = document.getElementById('applySeed');

  const togglePanel = () => brandPanel?.classList.toggle('open');

  if (paletteBtn && brandPanel) {
    paletteBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      togglePanel();
    });
    document.addEventListener('click', (e) => {
      if (!brandPanel.contains(e.target) && e.target !== paletteBtn) {
        brandPanel.classList.remove('open');
      }
    });
    brandPanel.addEventListener('click', (e) => {
      const btn = e.target.closest('.chip');
      if (btn && btn.dataset.seed) {
        if (customSeed) customSeed.value = btn.dataset.seed;
        if (customSeedHex) customSeedHex.value = btn.dataset.seed;
        applyThemeFromSeed(btn.dataset.seed);
      }
    });
  }
  if (customSeed && customSeedHex) {
    customSeed.addEventListener('input', () => { customSeedHex.value = customSeed.value; });
    customSeedHex.addEventListener('input', () => {
      if (/^#([0-9a-fA-F]{6})$/.test(customSeedHex.value)) {
        customSeed.value = customSeedHex.value;
      }
    });
  }
  if (applySeed && customSeed) {
    applySeed.addEventListener('click', () => {
      if (/^#([0-9a-fA-F]{6})$/.test(customSeed.value)) {
        applyThemeFromSeed(customSeed.value);
      }
    });
  }

  // 언어 토글
  const languageToggle = document.getElementById('languageToggle');
  if (languageToggle) {
    languageToggle.addEventListener('click', () => {
      setLang(currentLang === 'ko' ? 'en' : 'ko');
    });
  }

  applyI18n();

  // 초기 언어 이벤트 송출 (각 페이지가 초깃값을 받을 수 있게)
  window.dispatchEvent(new CustomEvent('kaief:lang', { detail: { lang: currentLang } }));
}

export function initCommonUI({ page }) {
  wireHeaderCommon();

  // 네비게이션 탭(이제는 페이지 링크)
  const navChat = document.getElementById('navChat');
  const navFeed = document.getElementById('navFeed');
  if (navChat && navFeed) {
    if (page === 'chat') {
      navChat.classList.add('active');
      navChat.setAttribute('aria-selected', 'true');
      navChat.setAttribute('aria-current', 'page');
      navFeed.classList.remove('active');
      navFeed.removeAttribute('aria-current');
    } else if (page === 'feed') {
      navFeed.classList.add('active');
      navFeed.setAttribute('aria-selected', 'true');
      navFeed.setAttribute('aria-current', 'page');
      navChat.classList.remove('active');
      navChat.removeAttribute('aria-current');
    }
  }

  // 창 리사이즈 시 팝오버 안전 닫기
  const brandPanel = document.getElementById('brandPanel');
  const ro = new ResizeObserver(() => {
    brandPanel?.classList.remove('open');
  });
  ro.observe(document.body);
}
