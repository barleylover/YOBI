import type { SupportedLanguage } from "./locale";

/**
 * Copy for the Figma "YOBI App v2" mobile redesign. Strings that exist in
 * productI18n keep coming from there; this module only adds redesign-specific
 * strings. English and Korean are fully translated; other languages fall back
 * to English (the rest of the product copy stays localized via productI18n).
 */
export interface RedesignCopy {
  localeTitle: string;
  done: string;
  languageTab: (count: number) => string;
  countryTab: (count: number) => string;
  searchLanguage: string;
  searchCountry: string;
  suggested: string;
  stepDelivery: string;
  stepPreferences: string;
  stepPreferencesTaste: string;
  stepPreferencesConditions: string;
  matchingAddresses: (count: number) => string;
  search: string;
  continueWithAddress: string;
  demoDeliveryBanner: string;
  demoFootnote: string;
  back: string;
  stepOf: (step: number, total: number, label: string) => string;
  sectionCore: string;
  sectionTaste: string;
  sectionConditions: string;
  sectionPreferences: string;
  craveTitle: string;
  craveSubtitle: string;
  liveCount: (menus: number, merchants: number) => string;
  any: string;
  clear: string;
  next: string;
  findMyDish: string;
  upTo: (level: number) => string;
  mild: string;
  veryHot: string;
  halalLabel: string;
  veganLabel: string;
  capabilityUnavailable: string;
  findingTitle: string;
  matchingSummary: (conditions: number, menus: number | null) => string;
  stageChecking: string;
  stageReading: string;
  stageRanking: string;
  usuallyFewSeconds: string;
  preparingTip: string;
  cancelAndEdit: string;
  alwaysOn: string;
  today: string;
  foundSummary: (menus: number, merchants: number) => string;
  editChip: string;
  yobiPick: string;
  pickCount: (index: number, total: number) => string;
  yogiyoLabel: string;
  spiceOk: (level: number) => string;
  halalYes: string;
  halalNo: string;
  viewExplanation: string;
  chooseThisMenu: string;
  additionalExplanation: string;
  aiGenerated: string;
  wikiEvidence: string;
  gotIt: string;
  seeOtherMenus: string;
  editFilters: string;
  menuBar: string;
  openCart: string;
  editMyInfo: string;
  orderSetup: (index: number, total: number) => string;
  requiredTapOne: string;
  useDefaults: string;
  changeMenu: string;
  niceChoice: (count: number) => string;
  orderReady: string;
  deliverTo: string;
  yourMenu: string;
  totalEstimated: string;
  demoOrderWarning: string;
  prepareOrder: (total: string) => string;
  changeAddress: string;
  changeOptions: string;
  startOver: string;
  readyToOrder: string;
  itemsSummary: (count: number, name: string) => string;
  subtotal: string;
  openInYogiyo: string;
  backToMenus: string;
  handoffDemoNotice: string;
}

const en: RedesignCopy = {
  localeTitle: "Language & region",
  done: "Done",
  languageTab: (count) => `Language · ${count}`,
  countryTab: (count) => `Country · ${count}`,
  searchLanguage: "Search language",
  searchCountry: "Search country",
  suggested: "Suggested for you",
  stepDelivery: "Step 1 of 3 · Delivery",
  stepPreferences: "Step 2 of 3 · Preferences",
  stepPreferencesTaste: "Step 2 of 3 · Preferences",
  stepPreferencesConditions: "Step 2 of 3 · Preferences",
  matchingAddresses: (count) => `${count} matching address${count === 1 ? "" : "es"}`,
  search: "Search",
  continueWithAddress: "Continue with this address",
  demoDeliveryBanner: "Demo mode — no real delivery is dispatched.",
  demoFootnote: "Demo service · no real payment or order is placed.",
  back: "Back",
  stepOf: (step, total, label) => `Step ${step} of ${total} · ${label}`,
  sectionCore: "Core",
  sectionTaste: "Taste",
  sectionConditions: "Conditions",
  sectionPreferences: "Preferences",
  craveTitle: "What are you craving?",
  craveSubtitle: "Pick as many as you like. Results update live.",
  liveCount: (menus, merchants) => `${menus.toLocaleString()} menus · ${merchants.toLocaleString()} restaurants fit right now`,
  any: "Any",
  clear: "Clear",
  next: "Next",
  findMyDish: "Find my dish",
  upTo: (level) => `Up to ${level}`,
  mild: "Mild",
  veryHot: "Very hot",
  halalLabel: "Halal-certified only",
  veganLabel: "Vegan options only",
  capabilityUnavailable: "Not enough reviewed menus yet",
  findingTitle: "Finding your dish",
  matchingSummary: (conditions, menus) => (menus == null
    ? `Matching ${conditions} condition${conditions === 1 ? "" : "s"} against today’s menus.`
    : `Matching ${conditions} condition${conditions === 1 ? "" : "s"} against ${menus.toLocaleString()} menus.`),
  stageChecking: "Checking available menus",
  stageReading: "Reading the wiki and preparing matches",
  stageRanking: "Ranking your matches",
  usuallyFewSeconds: "This usually takes a few seconds",
  preparingTip: "You can change your spice limit or diet any time from Menu → Edit my info.",
  cancelAndEdit: "Cancel and edit conditions",
  alwaysOn: "K-food recommendations · always on",
  today: "Today",
  foundSummary: (menus, merchants) => `Found ${menus.toLocaleString()} menus from ${merchants.toLocaleString()} restaurants for your choices.`,
  editChip: "Edit",
  yobiPick: "YOBI PICK ARRIVED",
  pickCount: (index, total) => `${index} / ${total}`,
  yogiyoLabel: "YOGIYO:",
  spiceOk: (level) => `Spice ${level}/5 ok`,
  halalYes: "Halal: yes",
  halalNo: "Halal: no",
  viewExplanation: "View additional explanation",
  chooseThisMenu: "Choose this menu",
  additionalExplanation: "Additional Explanation",
  aiGenerated: "AI generated",
  wikiEvidence: "Wiki evidence",
  gotIt: "Got it",
  seeOtherMenus: "See other menus",
  editFilters: "Edit filters",
  menuBar: "Menu",
  openCart: "Open cart",
  editMyInfo: "Edit my info",
  orderSetup: (index, total) => `Order setup · Option ${index} of ${total}`,
  requiredTapOne: "Required · tap one",
  useDefaults: "Use defaults for the rest",
  changeMenu: "Change menu",
  niceChoice: (count) => (count > 0
    ? `Nice choice. Just ${count} quick option${count === 1 ? "" : "s"} and your order is ready to prepare.`
    : "Nice choice. Your order is almost ready to prepare."),
  orderReady: "Order ready to prepare",
  deliverTo: "Deliver to",
  yourMenu: "Your menu",
  totalEstimated: "Total (estimated)",
  demoOrderWarning: "Demo experience — no payment is taken and nothing is sent to the restaurant.",
  prepareOrder: (total) => `Prepare this order · ${total}`,
  changeAddress: "Change address",
  changeOptions: "Change options",
  startOver: "Start over",
  readyToOrder: "Ready to order",
  itemsSummary: (count, name) => `${count} item${count === 1 ? "" : "s"} · ${name}`,
  subtotal: "Subtotal",
  openInYogiyo: "Open in Yogiyo",
  backToMenus: "Back to menus",
  handoffDemoNotice: "YOBI hands this basket to Yogiyo. No real order is placed and no card is charged in this demo.",
};

const ko: RedesignCopy = {
  localeTitle: "언어 및 지역",
  done: "완료",
  languageTab: (count) => `언어 · ${count}`,
  countryTab: (count) => `국가 · ${count}`,
  searchLanguage: "언어 검색",
  searchCountry: "국가 검색",
  suggested: "추천",
  stepDelivery: "1/3 단계 · 배달",
  stepPreferences: "2/3 단계 · 취향",
  stepPreferencesTaste: "2/3 단계 · 취향",
  stepPreferencesConditions: "2/3 단계 · 취향",
  matchingAddresses: (count) => `주소 ${count}건 일치`,
  search: "검색",
  continueWithAddress: "이 주소로 계속하기",
  demoDeliveryBanner: "데모 모드 — 실제 배달은 이루어지지 않습니다.",
  demoFootnote: "데모 서비스 · 실제 결제나 주문은 이루어지지 않습니다.",
  back: "뒤로",
  stepOf: (step, total, label) => `${step}/${total} 단계 · ${label}`,
  sectionCore: "핵심",
  sectionTaste: "맛",
  sectionConditions: "조건",
  sectionPreferences: "취향",
  craveTitle: "어떤 음식이 당기세요?",
  craveSubtitle: "원하는 만큼 고르세요. 결과가 실시간으로 바뀌어요.",
  liveCount: (menus, merchants) => `지금 메뉴 ${menus.toLocaleString()}개 · 가게 ${merchants.toLocaleString()}곳이 조건에 맞아요`,
  any: "무관",
  clear: "초기화",
  next: "다음",
  findMyDish: "내 메뉴 찾기",
  upTo: (level) => `${level}단계까지`,
  mild: "순한맛",
  veryHot: "아주 매움",
  halalLabel: "할랄 인증만",
  veganLabel: "비건 옵션만",
  capabilityUnavailable: "아직 검토된 메뉴가 충분하지 않아요",
  findingTitle: "메뉴를 찾고 있어요",
  matchingSummary: (conditions, menus) => (menus == null
    ? `조건 ${conditions}개로 오늘의 메뉴를 대조하고 있어요.`
    : `조건 ${conditions}개로 메뉴 ${menus.toLocaleString()}개를 대조하고 있어요.`),
  stageChecking: "주문 가능한 메뉴 확인",
  stageReading: "위키를 읽고 잘 맞는 메뉴 준비",
  stageRanking: "추천 순위 정리",
  usuallyFewSeconds: "보통 몇 초면 끝나요",
  preparingTip: "맵기 한도나 식이 조건은 메뉴 → 내 정보 수정에서 언제든 바꿀 수 있어요.",
  cancelAndEdit: "취소하고 조건 수정",
  alwaysOn: "K-푸드 추천 · 항상 대기 중",
  today: "오늘",
  foundSummary: (menus, merchants) => `조건에 맞는 메뉴 ${menus.toLocaleString()}개를 가게 ${merchants.toLocaleString()}곳에서 찾았어요.`,
  editChip: "수정",
  yobiPick: "YOBI 추천 도착",
  pickCount: (index, total) => `${index} / ${total}`,
  yogiyoLabel: "요기요:",
  spiceOk: (level) => `맵기 ${level}/5 통과`,
  halalYes: "할랄: 예",
  halalNo: "할랄: 아니요",
  viewExplanation: "추가 설명 보기",
  chooseThisMenu: "이 메뉴 선택",
  additionalExplanation: "추가 설명",
  aiGenerated: "AI 생성",
  wikiEvidence: "위키 근거",
  gotIt: "확인",
  seeOtherMenus: "다른 메뉴 보기",
  editFilters: "조건 수정",
  menuBar: "메뉴",
  openCart: "장바구니 열기",
  editMyInfo: "내 정보 수정",
  orderSetup: (index, total) => `주문 설정 · 옵션 ${index}/${total}`,
  requiredTapOne: "필수 · 하나를 선택하세요",
  useDefaults: "나머지는 기본값 사용",
  changeMenu: "메뉴 변경",
  niceChoice: (count) => (count > 0
    ? `좋은 선택이에요. 옵션 ${count}개만 고르면 주문 준비가 끝나요.`
    : "좋은 선택이에요. 주문 준비가 거의 끝났어요."),
  orderReady: "주문 준비 완료",
  deliverTo: "배달 주소",
  yourMenu: "주문 메뉴",
  totalEstimated: "총액 (예상)",
  demoOrderWarning: "데모 체험 — 결제되지 않으며 식당으로 전송되지 않습니다.",
  prepareOrder: (total) => `이 주문 준비하기 · ${total}`,
  changeAddress: "주소 변경",
  changeOptions: "옵션 변경",
  startOver: "처음부터",
  readyToOrder: "주문 준비 완료",
  itemsSummary: (count, name) => `${count}개 항목 · ${name}`,
  subtotal: "소계",
  openInYogiyo: "요기요에서 열기",
  backToMenus: "메뉴로 돌아가기",
  handoffDemoNotice: "YOBI가 이 장바구니를 요기요로 전달합니다. 데모에서는 실제 주문이나 결제가 이루어지지 않습니다.",
};

export function getRedesignCopy(language: SupportedLanguage): RedesignCopy {
  return language === "한국어" ? ko : en;
}

export const LANGUAGE_ENGLISH_NAMES: Record<SupportedLanguage, string> = {
  English: "English (US)",
  "한국어": "Korean",
  "日本語": "Japanese",
  "中文（简体）": "Chinese, Simplified",
  "中文（繁體）": "Chinese, Traditional",
  Español: "Spanish",
  Français: "French",
  Deutsch: "German",
  Italiano: "Italian",
  Português: "Portuguese",
  "ไทย": "Thai",
  "Tiếng Việt": "Vietnamese",
  "Bahasa Indonesia": "Indonesian",
  "العربية": "Arabic",
  "हिन्दी": "Hindi",
  "Русский": "Russian",
};
