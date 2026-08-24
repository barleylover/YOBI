import { asEffectiveLanguage, type SupportedLanguage } from "./locale";

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
  searchConsentHint: string;
  selectAddressHint: string;
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
  foundForYou: string;
  morePreferences: (count: number) => string;
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
  findingMenus: string;
  makingExplanation: string;
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
  yobiLabel: string;
  spiceLess: string;
  spiceSimilar: string;
  spiceMore: string;
  spiceRangeSelection: (minimum: number, maximum: number) => string;
  spiceRangeInstruction: (firstEndpoint: number | null) => string;
  representativeSpice: (country: string, dish: string, level: number) => string;
  spiceScaleGuide: string;
  spiceScaleAnchor: (level: number, familiarDish: string, shuMin: number, shuMax: number) => string;
  priceRange: string;
  priceMinimum: string;
  priceMaximum: string;
  countryPreference: string;
  sampleSize: (count: number) => string;
  reviewSummary: string;
  spiceOk: (level: number) => string;
  spiceComparison: (level: number, comparison: -1 | 0 | 1, referenceDish: string) => string;
  estimatedArrival: string;
  halalYes: string;
  halalNo: string;
  adventurousChoice: string;
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
  optionalTap: string;
  noneOption: string;
  doneOptions: string;
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
  restaurantNote: string;
  restaurantNoteHelp: string;
  translateNote: string;
  translatingNote: string;
  koreanTranslation: string;
  backTranslation: string;
  retryTranslation: string;
  addWithoutNote: string;
  restaurantNotePlaceholder: string;
  handoffFrontDesk: string;
  handoffDoor: string;
  handoffMeetOutside: string;
  includeCutlery: string;
  noCutlery: string;
  ringBell: string;
  doNotRingBell: string;
  restaurantRequest: string;
  courierRequest: string;
  cancelChanges: string;
  saveChanges: string;
  estimatedTotalHelp: string;
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
  searchConsentHint: "Allow address use before searching.",
  selectAddressHint: "Search for and select an address to continue.",
  demoDeliveryBanner: "Delivery area confirmed.",
  demoFootnote: "",
  back: "Back",
  stepOf: (step, total, label) => `Step ${step} of ${total} · ${label}`,
  sectionCore: "Core",
  sectionTaste: "Taste",
  sectionConditions: "Conditions",
  sectionPreferences: "Preferences",
  craveTitle: "What are you craving?",
  craveSubtitle: "Pick as many as you like. Results update live.",
  foundForYou: "I found these for you.",
  morePreferences: (count) => `+${count} more`,
  liveCount: (menus, merchants) => `${menus.toLocaleString()} dishes from ${merchants.toLocaleString()} restaurants currently fit`,
  any: "Any",
  clear: "Clear",
  next: "Next",
  findMyDish: "Find my dish",
  upTo: (level) => `Up to ${level}`,
  mild: "Mild",
  veryHot: "Very hot",
  halalLabel: "Halal-friendly only",
  veganLabel: "Vegan options only",
  capabilityUnavailable: "Not enough reviewed dishes yet",
  findingTitle: "Finding your dish",
  findingMenus: "YOBI is finding dishes for YOU!",
  makingExplanation: "Writing your recommendations",
  matchingSummary: (conditions, menus) => (menus == null
    ? `Matching ${conditions} condition${conditions === 1 ? "" : "s"} against today’s dishes.`
    : `Matching ${conditions} condition${conditions === 1 ? "" : "s"} against ${menus.toLocaleString()} dishes.`),
  stageChecking: "Checking available dishes",
  stageReading: "Reading the wiki and preparing matches",
  stageRanking: "Ranking your matches",
  usuallyFewSeconds: "This usually takes about 20 seconds",
  preparingTip: "Your saved choices stay unchanged while YOBI prepares the explanation.",
  cancelAndEdit: "Cancel and edit conditions",
  alwaysOn: "K-food recommendations · always on",
  today: "Today",
  foundSummary: (menus, merchants) => `Found ${menus.toLocaleString()} dishes from ${merchants.toLocaleString()} restaurants for your choices.`,
  editChip: "Edit",
  yobiPick: "YOBI’s pick",
  pickCount: (index, total) => `${index} / ${total}`,
  yogiyoLabel: "YOGIYO:",
  yobiLabel: "YOBI:",
  spiceLess: "Less spicy",
  spiceSimilar: "About the same",
  spiceMore: "More spicy",
  spiceRangeSelection: (minimum, maximum) => minimum === 1 && maximum === 5
    ? "Any spice · levels 1–5"
    : minimum === maximum
      ? `Spice level ${minimum} only`
      : `Spice levels ${minimum}–${maximum}`,
  spiceRangeInstruction: (firstEndpoint) => firstEndpoint == null
    ? "Tap the first endpoint, then tap the second. Tap the same level twice for an exact match."
    : `Level ${firstEndpoint} selected. Tap the other endpoint, or tap ${firstEndpoint} again for this level only.`,
  representativeSpice: (country, dish, level) => `${country} reference: ${dish} · spice ${level}/5`,
  spiceScaleGuide: "Familiar anchors use approximate Scoville ranges. Ingredients and preparation can change perceived heat.",
  spiceScaleAnchor: (level, familiarDish, shuMin, shuMax) => `Level ${level}: ${familiarDish} · ${shuMin === shuMax ? `about ${shuMin.toLocaleString()}` : `${shuMin.toLocaleString()}–${shuMax.toLocaleString()}`} SHU`,
  priceRange: "Price range",
  priceMinimum: "Minimum price",
  priceMaximum: "Maximum price",
  countryPreference: "Travelers from your country who liked this dish",
  sampleSize: (count) => `Based on ${count.toLocaleString()} visitors`,
  reviewSummary: "What diners say",
  spiceOk: (level) => `Spice ${level}/5`,
  spiceComparison: (level, comparison, referenceDish) => `Spice ${level}/5 · ${comparison < 0 ? "less spicy than" : comparison > 0 ? "hotter than" : "about as spicy as"} ${referenceDish}`,
  estimatedArrival: "ETA",
  halalYes: "No obvious pork or alcohol detected · not halal-certified",
  halalNo: "Halal status not verified",
  adventurousChoice: "Adventurous choice · check the texture and ingredients",
  viewExplanation: "Why YOBI picked this",
  chooseThisMenu: "Choose this dish",
  additionalExplanation: "Why YOBI picked this",
  aiGenerated: "AI generated",
  wikiEvidence: "Wiki evidence",
  gotIt: "Got it",
  seeOtherMenus: "See other dishes",
  editFilters: "Edit filters",
  menuBar: "Menu",
  openCart: "Open cart",
  editMyInfo: "Edit my info",
  orderSetup: (index, total) => `Order setup · Option ${index} of ${total}`,
  requiredTapOne: "Required · tap one",
  optionalTap: "Optional · choose one or none",
  noneOption: "None",
  doneOptions: "Done",
  useDefaults: "Use defaults for remaining options",
  changeMenu: "Pick a different dish",
  niceChoice: (count) => (count > 0
    ? `Nice choice. Just ${count} quick option${count === 1 ? "" : "s"} and your order is ready to prepare.`
    : "Nice choice. Your order is almost ready to prepare."),
  orderReady: "Order summary",
  deliverTo: "Deliver to",
  yourMenu: "Your order",
  totalEstimated: "Estimated total",
  demoOrderWarning: "Review the dish, options and delivery details before continuing.",
  prepareOrder: (total) => `Place order · ${total}`,
  changeAddress: "Change address",
  changeOptions: "Change options",
  startOver: "Start over",
  readyToOrder: "Ready to order",
  itemsSummary: (count, name) => `${count} item${count === 1 ? "" : "s"} · ${name}`,
  subtotal: "Subtotal",
  openInYogiyo: "Open in Yogiyo",
  backToMenus: "Back to dishes",
  handoffDemoNotice: "YOBI hands this basket to Yogiyo to continue your order.",
  restaurantNote: "How should we say it? Restaurant note",
  restaurantNoteHelp: "Write in your language, then translate to Korean before adding it.",
  translateNote: "Translate to Korean",
  translatingNote: "Translating…",
  koreanTranslation: "Message to restaurant",
  backTranslation: "In your words",
  retryTranslation: "Try Korean translation again",
  addWithoutNote: "Add without restaurant note",
  restaurantNotePlaceholder: "Example: Please make it as mild as possible.",
  handoffFrontDesk: "Leave at the hotel front desk",
  handoffDoor: "Leave at my door",
  handoffMeetOutside: "Meet me outside",
  includeCutlery: "Include disposable cutlery",
  noCutlery: "No disposable cutlery",
  ringBell: "Ring the bell on arrival",
  doNotRingBell: "Do not ring the bell",
  restaurantRequest: "Restaurant request",
  courierRequest: "Courier handoff request",
  cancelChanges: "Cancel changes",
  saveChanges: "Save changes",
  estimatedTotalHelp: "The final amount is confirmed in Yogiyo before payment.",
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
  searchConsentHint: "검색 전에 주소 사용 동의에 체크해 주세요.",
  selectAddressHint: "계속하려면 주소를 검색하고 하나를 선택해 주세요.",
  demoDeliveryBanner: "배달 가능 지역을 확인했어요.",
  demoFootnote: "",
  back: "뒤로",
  stepOf: (step, total, label) => `${step}/${total} 단계 · ${label}`,
  sectionCore: "핵심",
  sectionTaste: "맛",
  sectionConditions: "조건",
  sectionPreferences: "취향",
  craveTitle: "어떤 음식이 당기세요?",
  craveSubtitle: "원하는 만큼 고르세요. 결과가 실시간으로 바뀌어요.",
  foundForYou: "이 메뉴들을 찾았어요.",
  morePreferences: (count) => `외 ${count}개`,
  liveCount: (menus, merchants) => `지금 메뉴 ${menus.toLocaleString()}개 · 가게 ${merchants.toLocaleString()}곳이 조건에 맞아요`,
  any: "무관",
  clear: "초기화",
  next: "다음",
  findMyDish: "내 메뉴 찾기",
  upTo: (level) => `${level}단계까지`,
  mild: "순한맛",
  veryHot: "아주 매움",
  halalLabel: "할랄 친화만",
  veganLabel: "비건 옵션만",
  capabilityUnavailable: "아직 검토된 메뉴가 충분하지 않아요",
  findingTitle: "메뉴를 찾고 있어요",
  findingMenus: "YOBI가 당신을 위한 메뉴를 찾고 있어요!",
  makingExplanation: "YOBI가 당신을 위한 설명을 만들고 있어요!",
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
  yobiLabel: "YOBI:",
  spiceLess: "기준보다 덜 맵게",
  spiceSimilar: "기준과 비슷하게",
  spiceMore: "기준보다 더 맵게",
  spiceRangeSelection: (minimum, maximum) => minimum === 1 && maximum === 5
    ? "맵기 제한 없음 · 1–5단계"
    : minimum === maximum
      ? `맵기 ${minimum}단계만`
      : `맵기 ${minimum}–${maximum}단계`,
  spiceRangeInstruction: (firstEndpoint) => firstEndpoint == null
    ? "범위의 시작과 끝을 차례로 누르세요. 같은 단계를 두 번 누르면 그 단계만 선택됩니다."
    : `${firstEndpoint}단계를 골랐어요. 다른 끝점을 누르거나, 같은 단계를 다시 눌러 정확히 선택하세요.`,
  representativeSpice: (country, dish, level) => `${country} 기준: ${dish} · 맵기 ${level}/5`,
  spiceScaleGuide: "친숙한 예시는 근사 스코빌 범위 기준입니다. 재료와 조리법에 따라 체감 맵기는 달라질 수 있어요.",
  spiceScaleAnchor: (level, familiarDish, shuMin, shuMax) => `${level}단계: ${familiarDish} · ${shuMin === shuMax ? `약 ${shuMin.toLocaleString()}` : `${shuMin.toLocaleString()}–${shuMax.toLocaleString()}`} SHU`,
  priceRange: "가격 범위",
  priceMinimum: "최소 가격",
  priceMaximum: "최대 가격",
  countryPreference: "같은 국가 여행객의 메뉴 선호도",
  sampleSize: (count) => `여행객 ${count.toLocaleString()}명 기준`,
  reviewSummary: "리뷰 요약",
  spiceOk: (level) => `맵기 ${level}/5`,
  spiceComparison: (level, comparison, referenceDish) => `맵기 ${level}/5 · ${referenceDish}${comparison < 0 ? "보다 덜 매워요" : comparison > 0 ? "보다 더 매워요" : "와 비슷해요"}`,
  estimatedArrival: "예상 도착",
  halalYes: "할랄 친화 프로필 · 인증 아님",
  halalNo: "할랄 여부 미확인",
  adventurousChoice: "도전적인 음식 · 식감과 재료를 확인하세요",
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
  optionalTap: "선택 · 고르거나 선택하지 않아도 돼요",
  noneOption: "선택 안 함",
  doneOptions: "선택 완료",
  useDefaults: "나머지는 기본값 사용",
  changeMenu: "메뉴 변경",
  niceChoice: (count) => (count > 0
    ? `좋은 선택이에요. 옵션 ${count}개만 고르면 주문 준비가 끝나요.`
    : "좋은 선택이에요. 주문 준비가 거의 끝났어요."),
  orderReady: "주문 준비 완료",
  deliverTo: "배달 주소",
  yourMenu: "주문 메뉴",
  totalEstimated: "총액 (예상)",
  demoOrderWarning: "메뉴, 옵션과 배달 정보를 확인한 뒤 계속해 주세요.",
  prepareOrder: (total) => `이 주문 준비하기 · ${total}`,
  changeAddress: "주소 변경",
  changeOptions: "옵션 변경",
  startOver: "처음부터",
  readyToOrder: "주문 준비 완료",
  itemsSummary: (count, name) => `${count}개 항목 · ${name}`,
  subtotal: "소계",
  openInYogiyo: "요기요에서 열기",
  backToMenus: "메뉴로 돌아가기",
  handoffDemoNotice: "YOBI가 주문을 계속할 수 있도록 이 장바구니를 요기요로 전달합니다.",
  restaurantNote: "식당에는 어떻게 전할까요?",
  restaurantNoteHelp: "사용 중인 언어로 적고, 담기 전에 한국어로 번역해 주세요.",
  translateNote: "한국어로 번역",
  translatingNote: "번역 중…",
  koreanTranslation: "식당에 보낼 메시지",
  backTranslation: "내 언어로 다시 확인",
  retryTranslation: "번역 다시 시도",
  addWithoutNote: "요청사항 없이 장바구니에 담기",
  restaurantNotePlaceholder: "예: 가능한 한 맵지 않게 해 주세요.",
  handoffFrontDesk: "호텔 프런트에 맡기기",
  handoffDoor: "문 앞에 놓기",
  handoffMeetOutside: "건물 밖에서 만나기",
  includeCutlery: "일회용 수저 포함",
  noCutlery: "일회용 수저 제외",
  ringBell: "도착하면 벨 누르기",
  doNotRingBell: "벨 누르지 않기",
  restaurantRequest: "가게 요청사항",
  courierRequest: "배달 인계 요청",
  cancelChanges: "수정 취소",
  saveChanges: "변경사항 저장",
  estimatedTotalHelp: "최종 금액은 결제 전 Yogiyo에서 확인합니다.",
};

const ja: RedesignCopy = {
  localeTitle: "言語と地域", done: "完了", languageTab: (count) => `言語・${count}`,
  countryTab: (count) => `国・地域・${count}`, searchLanguage: "言語を検索",
  searchCountry: "国・地域を検索", suggested: "おすすめ", stepDelivery: "ステップ1/3・配達",
  stepPreferences: "ステップ2/3・好み", stepPreferencesTaste: "ステップ2/3・味の好み",
  stepPreferencesConditions: "ステップ2/3・条件", matchingAddresses: (count) => `${count}件の住所が一致`,
  search: "検索", continueWithAddress: "この住所で続ける",
  searchConsentHint: "検索する前に、住所利用への同意を選択してください。",
  selectAddressHint: "続けるには住所を検索して選択してください。", demoDeliveryBanner: "配達可能エリアを確認しました。",
  demoFootnote: "", back: "戻る", stepOf: (step, total, label) => `ステップ${step}/${total}・${label}`,
  sectionCore: "基本", sectionTaste: "味", sectionConditions: "条件", sectionPreferences: "好み",
  craveTitle: "どんな料理が食べたいですか？", craveSubtitle: "好きなだけ選べます。",
  foundForYou: "こちらのメニューを見つけました。", morePreferences: (count) => `ほか${count}件`,
  liveCount: (menus, merchants) => `現在${merchants.toLocaleString()}店・${menus.toLocaleString()}品が条件に一致`, any: "指定なし", clear: "クリア", next: "次へ", findMyDish: "料理を探す",
  upTo: (level) => `${level}まで`, mild: "マイルド", veryHot: "とても辛い",
  halalLabel: "ハラール対応のみ", veganLabel: "ヴィーガンのみ", capabilityUnavailable: "現在利用できません",
  findingTitle: "料理を探しています", findingMenus: "YOBIがあなたのメニューを探しています！",
  makingExplanation: "YOBIがあなたのために説明を作っています！", matchingSummary: () => "",
  stageChecking: "注文可能なメニューを確認", stageReading: "Wikiを読み、説明を準備",
  stageRanking: "おすすめを整理", usuallyFewSeconds: "通常は数秒で完了します",
  preparingTip: "条件はいつでも変更できます。", cancelAndEdit: "キャンセルして条件を編集",
  alwaysOn: "Kフードおすすめ", today: "今日", foundSummary: (menus, merchants) => `${merchants}店から${menus}品を見つけました。`,
  editChip: "編集", yobiPick: "YOBIのおすすめ", pickCount: (index, total) => `${index} / ${total}`,
  yogiyoLabel: "YOGIYO:", yobiLabel: "YOBI:", spiceLess: "基準より辛くない",
  spiceSimilar: "基準と同じくらい", spiceMore: "基準より辛い",
  spiceRangeSelection: (minimum, maximum) => minimum === 1 && maximum === 5
    ? "辛さ指定なし・レベル1〜5"
    : minimum === maximum
      ? `辛さレベル${minimum}のみ`
      : `辛さレベル${minimum}〜${maximum}`,
  spiceRangeInstruction: (firstEndpoint) => firstEndpoint == null
    ? "範囲の始点と終点を順にタップしてください。同じレベルを2回タップすると、そのレベルだけを選べます。"
    : `レベル${firstEndpoint}を選びました。もう一方の端点、または同じレベルをもう一度タップしてください。`,
  priceRange: "価格帯",
  representativeSpice: (country, dish, level) => `${country}の目安：${dish}・辛さ${level}/5`,
  spiceScaleGuide: "身近な例はおおよそのスコヴィル値です。材料や調理法で体感の辛さは変わります。",
  spiceScaleAnchor: (level, familiarDish, shuMin, shuMax) => `レベル${level}：${familiarDish}・${shuMin === shuMax ? `約${shuMin.toLocaleString()}` : `${shuMin.toLocaleString()}〜${shuMax.toLocaleString()}`} SHU`,
  priceMinimum: "最低価格", priceMaximum: "最高価格",
  countryPreference: "同じ国からの旅行者の好み", sampleSize: (count) => `${count.toLocaleString()}人を基準`,
  reviewSummary: "レビュー要約", spiceOk: (level) => `辛さ ${level}/5`,
  spiceComparison: (level, comparison, referenceDish) => `辛さ ${level}/5・${referenceDish}${comparison < 0 ? "より辛くありません" : comparison > 0 ? "より辛い" : "と同じくらい"}`, estimatedArrival: "到着予定",
  halalYes: "ハラール対応候補・認証ではありません", halalNo: "ハラール情報は未確認",
  adventurousChoice: "挑戦的な料理・食感と材料を確認してください", viewExplanation: "詳しい説明を見る", chooseThisMenu: "このメニューを選ぶ",
  additionalExplanation: "詳しい説明", aiGenerated: "YOBIの説明", wikiEvidence: "Wikiの根拠",
  gotIt: "確認", seeOtherMenus: "ほかのメニューを見る", editFilters: "条件を編集", menuBar: "メニュー",
  openCart: "カートを開く", editMyInfo: "情報を編集", orderSetup: (index, total) => `注文設定・${index}/${total}`,
  requiredTapOne: "必須・1つ選択", optionalTap: "任意・選択しなくてもOK", noneOption: "選択しない",
  doneOptions: "選択完了", useDefaults: "残りは標準設定", changeMenu: "メニュー変更",
  niceChoice: (count) => count ? `あと${count}件のオプションを選んでください。` : "注文の準備ができました。",
  orderReady: "注文準備完了", deliverTo: "配達先", yourMenu: "注文メニュー", totalEstimated: "合計（予定）",
  demoOrderWarning: "メニュー、オプション、配達情報を確認して続けてください。",
  prepareOrder: (total) => `この注文を準備・${total}`, changeAddress: "住所変更", changeOptions: "オプション変更",
  startOver: "最初から", readyToOrder: "注文準備完了", itemsSummary: (count, name) => `${count}点・${name}`,
  subtotal: "小計", openInYogiyo: "Yogiyoで開く", backToMenus: "メニューに戻る",
  handoffDemoNotice: "注文を続けるため、YOBIがこのカートをYogiyoへ引き継ぎます。",
  restaurantNote: "お店にはどう伝えますか？", restaurantNoteHelp: "使っている言語で入力し、追加する前に韓国語へ翻訳してください。",
  translateNote: "韓国語に翻訳", translatingNote: "翻訳中…", koreanTranslation: "お店へのメッセージ",
  backTranslation: "自分の言語で確認", retryTranslation: "韓国語への翻訳を再試行",
  addWithoutNote: "お店へのメモなしでカートに追加",
  restaurantNotePlaceholder: "例：できるだけ辛くしないでください。",
  handoffFrontDesk: "ホテルフロントに預ける", handoffDoor: "ドアの前に置く",
  handoffMeetOutside: "建物の外で受け取る", includeCutlery: "使い捨てカトラリーを付ける",
  noCutlery: "使い捨てカトラリー不要", ringBell: "到着時にベルを鳴らす",
  doNotRingBell: "ベルを鳴らさない", restaurantRequest: "店舗への要望",
  courierRequest: "配達員への受け渡し要望", cancelChanges: "変更をキャンセル",
  saveChanges: "変更を保存",
  estimatedTotalHelp: "最終金額は支払い前にYogiyoで確認します。",
};

export function getRedesignCopy(language: SupportedLanguage): RedesignCopy {
  const effective = asEffectiveLanguage(language);
  return effective === "한국어" ? ko : effective === "日本語" ? ja : en;
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
