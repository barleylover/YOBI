import { getExtendedCopy } from "./extendedI18n";
import { getProfileCopy, getUiCopy } from "./i18n";
import type { SupportedLanguage } from "./locale";
import { getRecommendationCopy } from "./recommendationI18n";

export interface EntryCopy {
  heroTitle: string;
  heroBuddy: string;
  pitchTitle: string;
  pitchDescription: string;
  benefitFlavor: string;
  benefitDietary: string;
  benefitDelivery: string;
  languageLabel: string;
  countryLabel: string;
  countryHelp: (language: string) => string;
  start: string;
  localeApplies: string;
  experienceNotice: string;
}

export interface ProductCopy {
  entry: EntryCopy;
  address: {
    step: string;
    title: string;
    description: string;
    search: string;
    bookingImage: string;
    searchLabel: string;
    searchPlaceholder: string;
    chooseImage: string;
    useDemoImage: string;
    currentAddress: string;
    keepAddress: string;
    demoNotice: string;
    consent: string;
    check: string;
    select: string;
    changeLocale: string;
  };
  recommendation: {
    assistantName: string;
    ready: string;
    foodDescription: string;
    deliveryFee: string;
    freeDelivery: string;
    previous: string;
    next: string;
    cardPosition: (current: number, total: number) => string;
    compareLoading: string;
    compareFailed: string;
    compareTitle: string;
    exhaustedTitle: string;
    exhaustedDescription: string;
    retrievingStage: string;
    evidenceStage: string;
    generatingStage: string;
    previewCount: (menus: number, merchants: number) => string;
    previewUnavailable: string;
    zeroCombination: string;
  };
  navigation: {
    expand: string;
    collapse: string;
    foodRankings: string;
    feature: string;
    close: string;
    demoRankingNotice: string;
    reviews: string;
    orders: string;
    koreanPopularity: string;
    loading: string;
    unavailable: string;
    noFeatureMenus: string;
    featureTitle: string;
    featureDescription: string;
    selectMenu: string;
  };
  handoff: {
    eyebrow: string;
    title: string;
    description: string;
    account: string;
    cta: string;
    done: string;
    boundary: string;
    back: string;
  };
}

const entryEn: EntryCopy = {
  heroTitle: "Hi, I’m YOBI!",
  heroBuddy: "Your Korean food buddy.",
  pitchTitle: "Order K-food with context, not guesswork.",
  pitchDescription: "Choose the cuisines, flavours, ingredients and food styles you want, then confirm where the food should arrive. YOBI uses those choices to prepare your recommendations.",
  benefitFlavor: "Understand flavour & texture",
  benefitDietary: "Use halal & vegan guidance",
  benefitDelivery: "Check delivery before choosing",
  languageLabel: "Language",
  countryLabel: "Country",
  countryHelp: (language) => `Countries commonly using ${language} appear first.`,
  start: "Get started!",
  localeApplies: "Language applies to recommendations, ordering and the pre-payment handoff.",
  experienceNotice: "Restaurant and order information is prepared for this experience. No real order or charge is made.",
};

const entryKo: EntryCopy = {
  heroTitle: "안녕하세요, YOBI예요!",
  heroBuddy: "당신의 한국 음식 친구.",
  pitchTitle: "추측 대신 맥락으로 한국 음식을 골라보세요.",
  pitchDescription: "원하는 음식 계통, 맛, 재료와 형태를 고르고 배달받을 장소를 확인하세요. YOBI가 선택한 조건을 바탕으로 추천을 준비합니다.",
  benefitFlavor: "맛과 식감 이해하기",
  benefitDietary: "할랄·비건 안내 확인하기",
  benefitDelivery: "메뉴 선택 전 배달 확인하기",
  languageLabel: "언어",
  countryLabel: "국가",
  countryHelp: () => "선택한 언어를 많이 사용하는 국가가 먼저 표시됩니다.",
  start: "시작하기",
  localeApplies: "선택한 언어는 추천, 주문과 결제 직전 안내까지 적용됩니다.",
  experienceNotice: "가게와 주문 정보는 체험을 위해 구성되어 있으며 실제 주문이나 결제는 이루어지지 않습니다.",
};

const entryVariants: Partial<Record<SupportedLanguage, Partial<EntryCopy>>> = {
  "日本語": { heroTitle: "こんにちは、YOBIです！", heroBuddy: "韓国料理の相棒。", languageLabel: "言語", countryLabel: "国・地域", start: "始める" },
  "中文（简体）": { heroTitle: "你好，我是 YOBI！", heroBuddy: "你的韩国美食伙伴。", languageLabel: "语言", countryLabel: "国家/地区", start: "开始" },
  "中文（繁體）": { heroTitle: "你好，我是 YOBI！", heroBuddy: "你的韓國美食夥伴。", languageLabel: "語言", countryLabel: "國家/地區", start: "開始" },
  Español: { heroTitle: "¡Hola, soy YOBI!", heroBuddy: "Tu compañero de comida coreana.", languageLabel: "Idioma", countryLabel: "País", start: "Empezar" },
  Français: { heroTitle: "Bonjour, je suis YOBI !", heroBuddy: "Votre compagnon de cuisine coréenne.", languageLabel: "Langue", countryLabel: "Pays", start: "Commencer" },
  Deutsch: { heroTitle: "Hallo, ich bin YOBI!", heroBuddy: "Dein Begleiter für koreanisches Essen.", languageLabel: "Sprache", countryLabel: "Land", start: "Los geht’s" },
  Italiano: { heroTitle: "Ciao, sono YOBI!", heroBuddy: "Il tuo compagno per il cibo coreano.", languageLabel: "Lingua", countryLabel: "Paese", start: "Inizia" },
  Português: { heroTitle: "Olá, eu sou YOBI!", heroBuddy: "Seu parceiro de comida coreana.", languageLabel: "Idioma", countryLabel: "País", start: "Começar" },
  "ไทย": { heroTitle: "สวัสดี ฉันคือ YOBI!", heroBuddy: "เพื่อนคู่ใจเรื่องอาหารเกาหลี", languageLabel: "ภาษา", countryLabel: "ประเทศ", start: "เริ่มต้น" },
  "Tiếng Việt": { heroTitle: "Xin chào, tôi là YOBI!", heroBuddy: "Người bạn ẩm thực Hàn Quốc.", languageLabel: "Ngôn ngữ", countryLabel: "Quốc gia", start: "Bắt đầu" },
  "Bahasa Indonesia": { heroTitle: "Hai, saya YOBI!", heroBuddy: "Teman makanan Korea Anda.", languageLabel: "Bahasa", countryLabel: "Negara", start: "Mulai" },
  "العربية": { heroTitle: "مرحبًا، أنا YOBI!", heroBuddy: "رفيقك للطعام الكوري.", languageLabel: "اللغة", countryLabel: "البلد", start: "ابدأ" },
  "हिन्दी": { heroTitle: "नमस्ते, मैं YOBI हूँ!", heroBuddy: "आपका कोरियाई भोजन साथी।", languageLabel: "भाषा", countryLabel: "देश", start: "शुरू करें" },
  "Русский": { heroTitle: "Здравствуйте, я YOBI!", heroBuddy: "Ваш спутник по корейской кухне.", languageLabel: "Язык", countryLabel: "Страна", start: "Начать" },
};

type LocalizedLanguage = Exclude<SupportedLanguage, "English" | "한국어">;

interface LocalizedEntryVocabulary {
  pitchTitle: string;
  pitchDescription: string;
  benefitFlavor: string;
  benefitDietary: string;
  benefitDelivery: string;
  localeApplies: string;
}

const localizedEntryVocabulary: Record<LocalizedLanguage, LocalizedEntryVocabulary> = {
  "日本語": {
    pitchTitle: "勘ではなく、情報をもとにKフードを選びましょう。",
    pitchDescription: "好みの料理ジャンル、味、食材、スタイルを選び、届け先を確認してください。YOBIがその選択をもとにおすすめを準備します。",
    benefitFlavor: "味と食感を理解する",
    benefitDietary: "ハラール・ヴィーガン案内を確認する",
    benefitDelivery: "選ぶ前に配達を確認する",
    localeApplies: "選択した言語は、おすすめ、注文、支払い前の引き継ぎ案内まで適用されます。",
  },
  "中文（简体）": {
    pitchTitle: "不靠猜测，结合信息选择韩食。",
    pitchDescription: "选择你想要的菜系、口味、食材和餐食形式，再确认送达地点。YOBI 会根据这些选择准备推荐。",
    benefitFlavor: "了解口味与口感",
    benefitDietary: "查看清真与纯素指引",
    benefitDelivery: "选餐前确认配送",
    localeApplies: "所选语言将用于推荐、点餐及付款前的跳转说明。",
  },
  "中文（繁體）": {
    pitchTitle: "不靠猜測，根據資訊選擇韓食。",
    pitchDescription: "選擇想要的菜系、口味、食材與餐點形式，再確認送達地點。YOBI 會根據這些選擇準備推薦。",
    benefitFlavor: "了解口味與口感",
    benefitDietary: "查看清真與純素指引",
    benefitDelivery: "選餐前確認配送",
    localeApplies: "所選語言將用於推薦、點餐及付款前的跳轉說明。",
  },
  Español: {
    pitchTitle: "Elige K-food con contexto, no a ciegas.",
    pitchDescription: "Elige las cocinas, sabores, ingredientes y estilos que prefieras y confirma dónde debe llegar la comida. YOBI preparará recomendaciones a partir de esas elecciones.",
    benefitFlavor: "Comprende el sabor y la textura",
    benefitDietary: "Consulta la guía halal y vegana",
    benefitDelivery: "Comprueba la entrega antes de elegir",
    localeApplies: "El idioma elegido se usa en las recomendaciones, el pedido y la entrega previa al pago.",
  },
  Français: {
    pitchTitle: "Choisissez la K-food avec du contexte, sans deviner.",
    pitchDescription: "Choisissez les cuisines, saveurs, ingrédients et styles souhaités, puis confirmez le lieu de livraison. YOBI prépare ses recommandations à partir de ces choix.",
    benefitFlavor: "Comprendre les saveurs et les textures",
    benefitDietary: "Consulter les conseils halal et véganes",
    benefitDelivery: "Vérifier la livraison avant de choisir",
    localeApplies: "La langue choisie s’applique aux recommandations, à la commande et au transfert avant paiement.",
  },
  Deutsch: {
    pitchTitle: "K-Food mit Kontext wählen – statt zu raten.",
    pitchDescription: "Wähle gewünschte Küchen, Geschmacksrichtungen, Zutaten und Essensarten und bestätige den Lieferort. YOBI erstellt daraus passende Empfehlungen.",
    benefitFlavor: "Geschmack und Textur verstehen",
    benefitDietary: "Halal- und Vegan-Hinweise nutzen",
    benefitDelivery: "Lieferung vor der Auswahl prüfen",
    localeApplies: "Die gewählte Sprache gilt für Empfehlungen, Bestellung und die Übergabe vor der Zahlung.",
  },
  Italiano: {
    pitchTitle: "Scegli il K-food con il giusto contesto, senza tirare a indovinare.",
    pitchDescription: "Scegli cucine, sapori, ingredienti e stili che preferisci, poi conferma dove deve arrivare il cibo. YOBI prepara i consigli in base alle tue scelte.",
    benefitFlavor: "Capisci sapori e consistenze",
    benefitDietary: "Consulta le indicazioni halal e vegane",
    benefitDelivery: "Verifica la consegna prima di scegliere",
    localeApplies: "La lingua scelta si applica ai consigli, all’ordine e al passaggio prima del pagamento.",
  },
  Português: {
    pitchTitle: "Escolha K-food com contexto, sem adivinhações.",
    pitchDescription: "Escolha cozinhas, sabores, ingredientes e estilos que deseja e confirme onde a comida deve chegar. O YOBI prepara recomendações com base nessas escolhas.",
    benefitFlavor: "Entenda sabores e texturas",
    benefitDietary: "Consulte orientações halal e veganas",
    benefitDelivery: "Confira a entrega antes de escolher",
    localeApplies: "O idioma escolhido vale para recomendações, pedido e transição antes do pagamento.",
  },
  "ไทย": {
    pitchTitle: "เลือก K-food ด้วยข้อมูล ไม่ต้องเดา",
    pitchDescription: "เลือกประเภทอาหาร รสชาติ วัตถุดิบ และรูปแบบที่ต้องการ แล้วตรวจสอบสถานที่จัดส่ง YOBI จะเตรียมคำแนะนำจากตัวเลือกเหล่านั้น",
    benefitFlavor: "เข้าใจรสชาติและเนื้อสัมผัส",
    benefitDietary: "ดูคำแนะนำฮาลาลและวีแกน",
    benefitDelivery: "ตรวจสอบการจัดส่งก่อนเลือก",
    localeApplies: "ภาษาที่เลือกจะใช้กับคำแนะนำ การสั่งอาหาร และการส่งต่อก่อนชำระเงิน",
  },
  "Tiếng Việt": {
    pitchTitle: "Chọn K-food với đầy đủ thông tin, không cần đoán.",
    pitchDescription: "Chọn nền ẩm thực, hương vị, nguyên liệu và kiểu món bạn muốn, rồi xác nhận nơi giao. YOBI sẽ chuẩn bị gợi ý dựa trên các lựa chọn đó.",
    benefitFlavor: "Hiểu hương vị và kết cấu",
    benefitDietary: "Xem hướng dẫn halal và thuần chay",
    benefitDelivery: "Kiểm tra giao hàng trước khi chọn",
    localeApplies: "Ngôn ngữ đã chọn được dùng cho phần gợi ý, đặt món và chuyển tiếp trước thanh toán.",
  },
  "Bahasa Indonesia": {
    pitchTitle: "Pilih K-food dengan konteks, tanpa menebak-nebak.",
    pitchDescription: "Pilih jenis masakan, rasa, bahan, dan gaya makanan yang Anda inginkan, lalu pastikan lokasi pengantaran. YOBI menyiapkan rekomendasi berdasarkan pilihan tersebut.",
    benefitFlavor: "Pahami rasa dan tekstur",
    benefitDietary: "Gunakan panduan halal dan vegan",
    benefitDelivery: "Periksa pengantaran sebelum memilih",
    localeApplies: "Bahasa pilihan digunakan untuk rekomendasi, pemesanan, dan pengalihan sebelum pembayaran.",
  },
  "العربية": {
    pitchTitle: "اختر الطعام الكوري بمعلومات واضحة، لا بالتخمين.",
    pitchDescription: "اختر أنواع المطبخ والنكهات والمكونات وأشكال الطعام التي تفضلها، ثم أكد مكان التوصيل. يُعدّ YOBI توصياته بناءً على هذه الاختيارات.",
    benefitFlavor: "تعرّف على النكهة والقوام",
    benefitDietary: "استخدم إرشادات الحلال والنباتي",
    benefitDelivery: "تحقق من التوصيل قبل الاختيار",
    localeApplies: "تُستخدم اللغة المحددة في التوصيات والطلب والانتقال قبل الدفع.",
  },
  "हिन्दी": {
    pitchTitle: "अंदाज़े से नहीं, सही संदर्भ के साथ K-food चुनें।",
    pitchDescription: "अपनी पसंद के व्यंजन, स्वाद, सामग्री और भोजन की शैली चुनें, फिर डिलीवरी स्थान की पुष्टि करें। YOBI इन्हीं चुनावों के आधार पर सुझाव तैयार करता है।",
    benefitFlavor: "स्वाद और बनावट समझें",
    benefitDietary: "हलाल और वीगन मार्गदर्शन देखें",
    benefitDelivery: "चुनने से पहले डिलीवरी जाँचें",
    localeApplies: "चुनी गई भाषा सुझावों, ऑर्डर और भुगतान से पहले के हैंडऑफ़ पर लागू होती है।",
  },
  "Русский": {
    pitchTitle: "Выбирайте K-food с пониманием, а не наугад.",
    pitchDescription: "Выберите желаемую кухню, вкусы, ингредиенты и формат блюда, затем подтвердите место доставки. YOBI подготовит рекомендации на основе этого выбора.",
    benefitFlavor: "Разобраться во вкусе и текстуре",
    benefitDietary: "Использовать подсказки о халяльном и веганском питании",
    benefitDelivery: "Проверить доставку до выбора",
    localeApplies: "Выбранный язык используется в рекомендациях, заказе и переходе перед оплатой.",
  },
};

interface LocalizedAddressVocabulary {
  title: string;
  description: string;
  currentAddress: string;
  keepAddress: string;
  checkAddress: string;
  selectAddress: string;
  demoNotice: string;
}

const localizedAddressVocabulary: Record<LocalizedLanguage, LocalizedAddressVocabulary> = {
  "日本語": {
    title: "YOBIはどこへ配達しますか？", description: "検索か予約画像を選んでください。このデモでは、どちらも同じ事前設定済みの配達先になります。", currentAddress: "現在のデモ住所", keepAddress: "この住所を使う", checkAddress: "デモ住所を検索", selectAddress: "この住所を選ぶ", demoNotice: "デモ専用：事前に用意された固定住所で、全国の住所をリアルタイム検索する機能ではありません。",
  },
  "中文（简体）": {
    title: "YOBI 应该送到哪里？", description: "请选择搜索或预订图片。此演示中的两种方式都会得到同一个预设配送地址。", currentAddress: "当前演示地址", keepAddress: "使用此地址", checkAddress: "查找演示地址", selectAddress: "选择此地址", demoNotice: "仅供演示：这是预先设置的固定地址，并非全国实时地址搜索。",
  },
  "中文（繁體）": {
    title: "YOBI 應該送到哪裡？", description: "請選擇搜尋或預訂圖片。此示範中的兩種方式都會得到同一個預設配送地址。", currentAddress: "目前示範地址", keepAddress: "使用此地址", checkAddress: "尋找示範地址", selectAddress: "選擇此地址", demoNotice: "僅供示範：這是預先設定的固定地址，並非全國即時地址搜尋。",
  },
  Español: {
    title: "¿Dónde debe entregar YOBI?", description: "Elige la búsqueda o una imagen de reserva. En esta demo, ambas opciones llevan a la misma dirección de entrega preparada.", currentAddress: "Dirección demo actual", keepAddress: "Usar esta dirección", checkAddress: "Buscar la dirección demo", selectAddress: "Seleccionar esta dirección", demoNotice: "Solo demo: es una dirección fija preparada, no una búsqueda nacional de direcciones en tiempo real.",
  },
  Français: {
    title: "Où YOBI doit-il livrer ?", description: "Choisissez la recherche ou une image de réservation. Dans cette démo, les deux méthodes donnent la même adresse de livraison préparée.", currentAddress: "Adresse démo actuelle", keepAddress: "Utiliser cette adresse", checkAddress: "Rechercher l’adresse démo", selectAddress: "Choisir cette adresse", demoNotice: "Démo uniquement : il s’agit d’une adresse fixe préparée, et non d’une recherche nationale d’adresses en temps réel.",
  },
  Deutsch: {
    title: "Wohin soll YOBI liefern?", description: "Wähle die Suche oder ein Buchungsbild. In dieser Demo führen beide Wege zur gleichen vorbereiteten Lieferadresse.", currentAddress: "Aktuelle Demo-Adresse", keepAddress: "Diese Adresse verwenden", checkAddress: "Demo-Adresse suchen", selectAddress: "Diese Adresse auswählen", demoNotice: "Nur Demo: Dies ist eine vorbereitete feste Adresse, keine landesweite Adresssuche in Echtzeit.",
  },
  Italiano: {
    title: "Dove deve consegnare YOBI?", description: "Scegli la ricerca o un’immagine di prenotazione. In questa demo entrambe le opzioni portano allo stesso indirizzo di consegna predisposto.", currentAddress: "Indirizzo demo attuale", keepAddress: "Usa questo indirizzo", checkAddress: "Cerca l’indirizzo demo", selectAddress: "Seleziona questo indirizzo", demoNotice: "Solo demo: è un indirizzo fisso predisposto, non una ricerca nazionale degli indirizzi in tempo reale.",
  },
  Português: {
    title: "Onde o YOBI deve entregar?", description: "Escolha a busca ou uma imagem de reserva. Nesta demo, as duas opções levam ao mesmo endereço de entrega preparado.", currentAddress: "Endereço demo atual", keepAddress: "Usar este endereço", checkAddress: "Buscar o endereço demo", selectAddress: "Selecionar este endereço", demoNotice: "Somente demo: este é um endereço fixo preparado, não uma busca nacional de endereços em tempo real.",
  },
  "ไทย": {
    title: "ให้ YOBI จัดส่งไปที่ไหน?", description: "เลือกค้นหาหรือรูปการจอง ในเดโมนี้ทั้งสองวิธีจะได้ที่อยู่จัดส่งที่เตรียมไว้เดียวกัน", currentAddress: "ที่อยู่เดโมปัจจุบัน", keepAddress: "ใช้ที่อยู่นี้", checkAddress: "ค้นหาที่อยู่เดโม", selectAddress: "เลือกที่อยู่นี้", demoNotice: "สำหรับเดโมเท่านั้น: นี่คือที่อยู่คงที่ที่เตรียมไว้ ไม่ใช่การค้นหาที่อยู่ทั่วประเทศแบบเรียลไทม์",
  },
  "Tiếng Việt": {
    title: "YOBI nên giao đến đâu?", description: "Chọn tìm kiếm hoặc ảnh đặt phòng. Trong bản demo này, cả hai cách đều dẫn đến cùng một địa chỉ giao hàng đã chuẩn bị.", currentAddress: "Địa chỉ demo hiện tại", keepAddress: "Dùng địa chỉ này", checkAddress: "Tìm địa chỉ demo", selectAddress: "Chọn địa chỉ này", demoNotice: "Chỉ dành cho demo: đây là địa chỉ cố định đã chuẩn bị, không phải tìm kiếm địa chỉ toàn quốc theo thời gian thực.",
  },
  "Bahasa Indonesia": {
    title: "Ke mana YOBI harus mengantar?", description: "Pilih pencarian atau gambar reservasi. Dalam demo ini, keduanya menghasilkan alamat pengantaran yang sama dan telah disiapkan.", currentAddress: "Alamat demo saat ini", keepAddress: "Gunakan alamat ini", checkAddress: "Cari alamat demo", selectAddress: "Pilih alamat ini", demoNotice: "Khusus demo: ini alamat tetap yang telah disiapkan, bukan pencarian alamat nasional secara langsung.",
  },
  "العربية": {
    title: "إلى أين يجب أن يوصّل YOBI؟", description: "اختر البحث أو صورة الحجز. في هذا العرض تؤدي الطريقتان إلى عنوان التوصيل التجريبي نفسه.", currentAddress: "عنوان العرض الحالي", keepAddress: "استخدام هذا العنوان", checkAddress: "البحث عن عنوان العرض", selectAddress: "اختيار هذا العنوان", demoNotice: "للعرض التجريبي فقط: هذا عنوان ثابت مُعدّ مسبقًا، وليس بحثًا مباشرًا عن العناوين على مستوى البلاد.",
  },
  "हिन्दी": {
    title: "YOBI को कहाँ डिलीवर करना चाहिए?", description: "खोज या बुकिंग चित्र में से एक चुनें। इस डेमो में दोनों तरीके एक ही तैयार डिलीवरी पते पर पहुँचते हैं।", currentAddress: "मौजूदा डेमो पता", keepAddress: "यह पता उपयोग करें", checkAddress: "डेमो पता खोजें", selectAddress: "यह पता चुनें", demoNotice: "केवल डेमो: यह पहले से तैयार स्थिर पता है, देशभर के पतों की लाइव खोज नहीं।",
  },
  "Русский": {
    title: "Куда YOBI должен доставить заказ?", description: "Выберите поиск или изображение бронирования. В этой демо-версии оба способа приводят к одному подготовленному адресу доставки.", currentAddress: "Текущий демо-адрес", keepAddress: "Использовать этот адрес", checkAddress: "Найти демо-адрес", selectAddress: "Выбрать этот адрес", demoNotice: "Только для демо: это заранее подготовленный фиксированный адрес, а не поиск адресов по всей стране в реальном времени.",
  },
};

const localizedPreviewCount: Record<LocalizedLanguage, (menus: number, merchants: number) => string> = {
  "日本語": (menus, merchants) => `現在、${merchants}店舗の${menus}件のメニューが条件に合います`,
  "中文（简体）": (menus, merchants) => `当前有 ${merchants} 家餐厅的 ${menus} 道菜单符合条件`,
  "中文（繁體）": (menus, merchants) => `目前有 ${merchants} 家餐廳的 ${menus} 道菜單符合條件`,
  Español: (menus, merchants) => `Actualmente coinciden ${menus} menús de ${merchants} restaurantes`,
  Français: (menus, merchants) => `${menus} menus de ${merchants} restaurants correspondent actuellement`,
  Deutsch: (menus, merchants) => `Aktuell passen ${menus} Menüs von ${merchants} Restaurants`,
  Italiano: (menus, merchants) => `Al momento corrispondono ${menus} menu di ${merchants} ristoranti`,
  Português: (menus, merchants) => `No momento, ${menus} menus de ${merchants} restaurantes correspondem`,
  "ไทย": (menus, merchants) => `ขณะนี้มี ${menus} เมนูจาก ${merchants} ร้านที่ตรงเงื่อนไข`,
  "Tiếng Việt": (menus, merchants) => `Hiện có ${menus} món từ ${merchants} nhà hàng phù hợp`,
  "Bahasa Indonesia": (menus, merchants) => `Saat ini ${menus} menu dari ${merchants} restoran cocok`,
  "العربية": (menus, merchants) => `تطابق الشروط حاليًا ${menus} وجبة من ${merchants} مطعمًا`,
  "हिन्दी": (menus, merchants) => `अभी ${merchants} रेस्तराँ के ${menus} मेनू मेल खाते हैं`,
  "Русский": (menus, merchants) => `Сейчас подходят ${menus} меню из ${merchants} ресторанов`,
};

interface ProductVocabulary {
  countryHelp: string;
  search: string;
  free: string;
  menu: string;
  discoveries: string;
  foodRankings: string;
  feature: string;
  rankingNotice: string;
  reviews: string;
  orders: string;
  popularity: string;
  featureTitle: string;
  featureDescription: string;
  availableMenuDescription?: string;
  handoffTitle: string;
  handoffDescription: string;
  handoffAccount: string;
  handoffDone: string;
  handoffBoundary: string;
  back: string;
}

const productVocabulary: Record<LocalizedLanguage, ProductVocabulary> = {
  "日本語": {
    countryHelp: "選択した言語でよく使われる国・地域を先に表示します。", search: "検索", free: "無料", menu: "メニュー", discoveries: "YOBIをもっと見る", foodRankings: "料理ランキング", feature: "K-Demon特集", rankingNotice: "現在のデモ配達地域を基準にした順位で、Yogiyo全体のリアルタイム順位ではありません。", reviews: "レビューが多い順", orders: "注文が多い順", popularity: "韓国で人気", featureTitle: "作品に登場するKフードと、近くで注文できるメニュー", featureDescription: "K-pop Demon Huntersに登場する料理のうち、現在のデモ地域で利用可能な対応メニューだけを紹介します。", availableMenuDescription: "現在のデモ配達地域で注文できる韓国料理メニューです。", handoffTitle: "注文はYogiyoで続けてください", handoffDescription: "選んだ韓国料理を注文する場合は、Yogiyoで続けます。", handoffAccount: "会員登録と支払い情報はYogiyoで扱われます。", handoffDone: "ここでYogiyoアプリを開く想定です。YOBIデモはここで終了します。", handoffBoundary: "移動のモックのみです。カート送信、アプリやURLの起動、決済、注文作成は行っていません。", back: "YOBIに戻る",
  },
  "中文（简体）": {
    countryHelp: "优先显示常用所选语言的国家和地区。", search: "搜索", free: "免费", menu: "菜单", discoveries: "探索 YOBI", foodRankings: "美食排行", feature: "K-Demon 特辑", rankingNotice: "这是当前演示配送区域的排行，并非 Yogiyo 全平台实时排行。", reviews: "评价最多", orders: "下单最多", popularity: "韩国热门", featureTitle: "荧幕上的韩食，附近可点的菜单", featureDescription: "仅展示 K-pop Demon Hunters 中出现的美食，以及当前演示区域内可供应的对应菜单。", handoffTitle: "请在 Yogiyo 继续下单", handoffDescription: "如果想订购已选韩餐，请前往 Yogiyo 继续。", handoffAccount: "注册账号和填写支付信息将在 Yogiyo 内完成。", handoffDone: "此处原本会打开 Yogiyo 应用，YOBI 演示到此结束。", handoffBoundary: "这只是跳转模拟。未发送购物车、未打开应用或链接，也未创建付款或订单。", back: "返回 YOBI",
  },
  "中文（繁體）": {
    countryHelp: "優先顯示常用所選語言的國家與地區。", search: "搜尋", free: "免費", menu: "菜單", discoveries: "探索 YOBI", foodRankings: "美食排行", feature: "K-Demon 特輯", rankingNotice: "這是目前示範配送區域的排行，並非 Yogiyo 全平台即時排行。", reviews: "評論最多", orders: "訂單最多", popularity: "韓國熱門", featureTitle: "螢幕上的韓食，附近可點的菜單", featureDescription: "僅顯示 K-pop Demon Hunters 中出現的美食，以及目前示範區域可供應的對應菜單。", handoffTitle: "請在 Yogiyo 繼續下單", handoffDescription: "如果想訂購已選韓餐，請前往 Yogiyo 繼續。", handoffAccount: "註冊帳號與填寫付款資訊將在 Yogiyo 內完成。", handoffDone: "此處原本會開啟 Yogiyo 應用程式，YOBI 示範到此結束。", handoffBoundary: "這只是跳轉模擬。未傳送購物車、未開啟應用程式或連結，也未建立付款或訂單。", back: "返回 YOBI",
  },
  Español: {
    countryHelp: "Primero aparecen los países donde más se usa el idioma elegido.", search: "Buscar", free: "Gratis", menu: "Menú", discoveries: "Explorar YOBI", foodRankings: "Clasificación de comidas", feature: "Especial K-Demon", rankingNotice: "Clasificación demo del área de entrega preparada, no una clasificación en tiempo real de todo Yogiyo.", reviews: "Más reseñas", orders: "Más pedidos", popularity: "Popular en Corea", featureTitle: "K-food de la pantalla disponible cerca de ti", featureDescription: "Solo mostramos platos de K-pop Demon Hunters y menús asociados disponibles en el área demo actual.", handoffTitle: "Continúa en Yogiyo para pedir", handoffDescription: "Para pedir el menú coreano elegido, continúa en Yogiyo.", handoffAccount: "El registro y los datos de pago se gestionan dentro de Yogiyo.", handoffDone: "Aquí se abriría la aplicación Yogiyo. La demo de YOBI termina aquí.", handoffBoundary: "Es solo una simulación de traspaso. No se envió el carrito, no se abrió ninguna aplicación o enlace y no se creó ningún pago ni pedido.", back: "Volver a YOBI",
  },
  Français: {
    countryHelp: "Les pays où la langue choisie est courante apparaissent en premier.", search: "Rechercher", free: "Gratuit", menu: "Menu", discoveries: "Explorer YOBI", foodRankings: "Classement des plats", feature: "Sélection K-Demon", rankingNotice: "Classement démo de la zone de livraison préparée, et non classement Yogiyo en temps réel.", reviews: "Plus d’avis", orders: "Plus commandés", popularity: "Populaires en Corée", featureTitle: "La K-food à l’écran, disponible près de vous", featureDescription: "Nous présentons uniquement les plats vus dans K-pop Demon Hunters et les menus associés disponibles dans la zone démo.", handoffTitle: "Continuez sur Yogiyo pour commander", handoffDescription: "Pour commander le plat coréen choisi, continuez sur Yogiyo.", handoffAccount: "L’inscription et les informations de paiement sont gérées dans Yogiyo.", handoffDone: "L’application Yogiyo s’ouvrirait ici. La démo YOBI se termine à cette étape.", handoffBoundary: "Il s’agit seulement d’une simulation de transfert. Aucun panier n’a été envoyé, aucune application ni lien n’a été ouvert, et aucun paiement ou commande n’a été créé.", back: "Retour à YOBI",
  },
  Deutsch: {
    countryHelp: "Länder, in denen die gewählte Sprache häufig genutzt wird, erscheinen zuerst.", search: "Suchen", free: "Kostenlos", menu: "Menü", discoveries: "YOBI entdecken", foodRankings: "Essensrangliste", feature: "K-Demon-Special", rankingNotice: "Demo-Rangliste für das vorbereitete Liefergebiet, keine Yogiyo-weite Echtzeit-Rangliste.", reviews: "Meiste Bewertungen", orders: "Meiste Bestellungen", popularity: "In Korea beliebt", featureTitle: "K-Food vom Bildschirm, in deiner Nähe verfügbar", featureDescription: "Wir zeigen nur Speisen aus K-pop Demon Hunters und zugeordnete Menüs, die im aktuellen Demo-Gebiet verfügbar sind.", handoffTitle: "Zum Bestellen in Yogiyo fortfahren", handoffDescription: "Bestelle das gewählte koreanische Menü, indem du in Yogiyo fortfährst.", handoffAccount: "Registrierung und Zahlungsdaten werden in Yogiyo verwaltet.", handoffDone: "Hier würde sich die Yogiyo-App öffnen. Die YOBI-Demo endet an dieser Stelle.", handoffBoundary: "Dies ist nur eine Übergabe-Simulation. Es wurde kein Warenkorb gesendet, keine App oder URL geöffnet und keine Zahlung oder Bestellung erstellt.", back: "Zurück zu YOBI",
  },
  Italiano: {
    countryHelp: "I paesi in cui la lingua scelta è più usata vengono mostrati per primi.", search: "Cerca", free: "Gratis", menu: "Menu", discoveries: "Esplora YOBI", foodRankings: "Classifica dei piatti", feature: "Speciale K-Demon", rankingNotice: "Classifica demo dell’area di consegna preparata, non una classifica Yogiyo in tempo reale.", reviews: "Più recensioni", orders: "Più ordinati", popularity: "Popolari in Corea", featureTitle: "K-food sullo schermo, disponibile vicino a te", featureDescription: "Mostriamo solo i piatti di K-pop Demon Hunters e i menu associati disponibili nell’area demo attuale.", handoffTitle: "Continua su Yogiyo per ordinare", handoffDescription: "Per ordinare il menu coreano scelto, continua su Yogiyo.", handoffAccount: "Registrazione e dati di pagamento vengono gestiti dentro Yogiyo.", handoffDone: "Qui si aprirebbe l’app Yogiyo. La demo YOBI termina a questo punto.", handoffBoundary: "È solo una simulazione di passaggio. Nessun carrello è stato inviato, nessuna app o URL è stata aperta e non è stato creato alcun pagamento o ordine.", back: "Torna a YOBI",
  },
  Português: {
    countryHelp: "Os países onde o idioma escolhido é mais usado aparecem primeiro.", search: "Buscar", free: "Grátis", menu: "Menu", discoveries: "Explorar o YOBI", foodRankings: "Ranking de comidas", feature: "Especial K-Demon", rankingNotice: "Ranking demo da área de entrega preparada, não um ranking em tempo real de todo o Yogiyo.", reviews: "Mais avaliações", orders: "Mais pedidos", popularity: "Populares na Coreia", featureTitle: "K-food das telas disponível perto de você", featureDescription: "Mostramos apenas pratos de K-pop Demon Hunters e menus associados disponíveis na área demo atual.", handoffTitle: "Continue no Yogiyo para pedir", handoffDescription: "Para pedir o menu coreano escolhido, continue no Yogiyo.", handoffAccount: "Cadastro e dados de pagamento são tratados dentro do Yogiyo.", handoffDone: "Aqui o aplicativo Yogiyo seria aberto. A demo do YOBI termina neste ponto.", handoffBoundary: "Esta é apenas uma simulação de transição. Nenhum carrinho foi enviado, nenhum aplicativo ou URL foi aberto e nenhum pagamento ou pedido foi criado.", back: "Voltar ao YOBI",
  },
  "ไทย": {
    countryHelp: "ประเทศที่ใช้ภาษาที่เลือกเป็นหลักจะแสดงก่อน", search: "ค้นหา", free: "ฟรี", menu: "เมนู", discoveries: "สำรวจ YOBI", foodRankings: "อันดับอาหาร", feature: "พิเศษ K-Demon", rankingNotice: "อันดับเดโมสำหรับพื้นที่จัดส่งที่เตรียมไว้ ไม่ใช่อันดับแบบเรียลไทม์ของ Yogiyo ทั้งหมด", reviews: "รีวิวมากที่สุด", orders: "สั่งมากที่สุด", popularity: "ยอดนิยมในเกาหลี", featureTitle: "K-food จากหน้าจอที่สั่งได้ใกล้คุณ", featureDescription: "แสดงเฉพาะอาหารจาก K-pop Demon Hunters และเมนูที่เชื่อมโยงซึ่งพร้อมให้บริการในพื้นที่เดโมปัจจุบัน", handoffTitle: "สั่งอาหารต่อใน Yogiyo", handoffDescription: "หากต้องการสั่งเมนูเกาหลีที่เลือก ให้ดำเนินการต่อใน Yogiyo", handoffAccount: "การสมัครและข้อมูลการชำระเงินจะจัดการภายใน Yogiyo", handoffDone: "ขั้นตอนนี้ควรเปิดแอป Yogiyo และเดโม YOBI จะสิ้นสุดที่นี่", handoffBoundary: "นี่เป็นเพียงการจำลองการส่งต่อ ไม่มีการส่งตะกร้า เปิดแอปหรือลิงก์ หรือสร้างการชำระเงินและคำสั่งซื้อ", back: "กลับไปที่ YOBI",
  },
  "Tiếng Việt": {
    countryHelp: "Các quốc gia thường dùng ngôn ngữ đã chọn sẽ xuất hiện trước.", search: "Tìm kiếm", free: "Miễn phí", menu: "Món", discoveries: "Khám phá YOBI", foodRankings: "Xếp hạng món ăn", feature: "Chuyên đề K-Demon", rankingNotice: "Xếp hạng demo cho khu vực giao hàng đã chuẩn bị, không phải xếp hạng Yogiyo theo thời gian thực.", reviews: "Nhiều đánh giá nhất", orders: "Được đặt nhiều nhất", popularity: "Phổ biến tại Hàn Quốc", featureTitle: "K-food trên màn ảnh, có thể đặt gần bạn", featureDescription: "Chỉ hiển thị món trong K-pop Demon Hunters và thực đơn liên kết đang có tại khu vực demo.", handoffTitle: "Tiếp tục đặt món trong Yogiyo", handoffDescription: "Để đặt món Hàn đã chọn, hãy tiếp tục trong Yogiyo.", handoffAccount: "Đăng ký và thông tin thanh toán được xử lý trong Yogiyo.", handoffDone: "Ứng dụng Yogiyo sẽ được mở tại bước này. Demo YOBI kết thúc ở đây.", handoffBoundary: "Đây chỉ là mô phỏng chuyển tiếp. Không có giỏ hàng nào được gửi, không mở ứng dụng hay liên kết và không tạo thanh toán hoặc đơn hàng.", back: "Quay lại YOBI",
  },
  "Bahasa Indonesia": {
    countryHelp: "Negara yang umum memakai bahasa pilihan ditampilkan lebih dahulu.", search: "Cari", free: "Gratis", menu: "Menu", discoveries: "Jelajahi YOBI", foodRankings: "Peringkat makanan", feature: "Pilihan K-Demon", rankingNotice: "Peringkat demo untuk area pengantaran yang disiapkan, bukan peringkat waktu nyata seluruh Yogiyo.", reviews: "Ulasan terbanyak", orders: "Pesanan terbanyak", popularity: "Populer di Korea", featureTitle: "K-food dari layar yang tersedia di dekat Anda", featureDescription: "Kami hanya menampilkan makanan dari K-pop Demon Hunters dan menu terkait yang tersedia di area demo saat ini.", handoffTitle: "Lanjutkan pemesanan di Yogiyo", handoffDescription: "Untuk memesan menu Korea pilihan Anda, lanjutkan di Yogiyo.", handoffAccount: "Pendaftaran dan informasi pembayaran ditangani di dalam Yogiyo.", handoffDone: "Aplikasi Yogiyo akan dibuka pada langkah ini. Demo YOBI berakhir di sini.", handoffBoundary: "Ini hanya simulasi pengalihan. Tidak ada keranjang yang dikirim, aplikasi atau tautan yang dibuka, serta pembayaran atau pesanan yang dibuat.", back: "Kembali ke YOBI",
  },
  "العربية": {
    countryHelp: "تظهر أولًا البلدان التي يشيع فيها استخدام اللغة المحددة.", search: "بحث", free: "مجاني", menu: "الوجبة", discoveries: "استكشاف YOBI", foodRankings: "ترتيب الأطعمة", feature: "مختارات K-Demon", rankingNotice: "ترتيب تجريبي لمنطقة التوصيل المعدّة حاليًا، وليس ترتيبًا مباشرًا على مستوى Yogiyo.", reviews: "الأكثر مراجعات", orders: "الأكثر طلبًا", popularity: "الأكثر رواجًا في كوريا", featureTitle: "أطعمة كورية من الشاشة ومتاحة بالقرب منك", featureDescription: "نعرض أطعمة ظهرت في K-pop Demon Hunters والقوائم المرتبطة المتاحة حاليًا فقط في منطقة العرض.", handoffTitle: "تابع الطلب في Yogiyo", handoffDescription: "إذا أردت طلب الوجبة الكورية التي اخترتها، فتابع في Yogiyo.", handoffAccount: "يتم إنشاء الحساب وإدخال بيانات الدفع داخل Yogiyo.", handoffDone: "هذه هي الخطوة التي يُفترض أن يفتح فيها تطبيق Yogiyo. ينتهي عرض YOBI هنا.", handoffBoundary: "هذه محاكاة انتقال فقط. لم تُرسل السلة، ولم يُفتح تطبيق أو رابط، ولم يتم إنشاء دفع أو طلب.", back: "العودة إلى YOBI",
  },
  "हिन्दी": {
    countryHelp: "चुनी गई भाषा का सामान्य उपयोग करने वाले देश पहले दिखाए जाते हैं।", search: "खोजें", free: "मुफ़्त", menu: "मेनू", discoveries: "YOBI देखें", foodRankings: "भोजन रैंकिंग", feature: "K-Demon विशेष", rankingNotice: "यह तैयार डिलीवरी क्षेत्र की डेमो रैंकिंग है, पूरे Yogiyo की लाइव रैंकिंग नहीं।", reviews: "सबसे अधिक समीक्षाएँ", orders: "सबसे अधिक ऑर्डर", popularity: "कोरिया में लोकप्रिय", featureTitle: "स्क्रीन का K-food, आपके पास उपलब्ध", featureDescription: "केवल K-pop Demon Hunters में दिखे भोजन और मौजूदा डेमो क्षेत्र में उपलब्ध जुड़े मेनू दिखाए जाते हैं।", handoffTitle: "ऑर्डर के लिए Yogiyo में जारी रखें", handoffDescription: "चुना हुआ कोरियाई मेनू मंगाने के लिए Yogiyo में जारी रखें।", handoffAccount: "साइन-अप और भुगतान जानकारी Yogiyo में संभाली जाएगी।", handoffDone: "इस चरण पर Yogiyo ऐप खुलता। YOBI डेमो यहीं समाप्त होता है।", handoffBoundary: "यह केवल हैंडऑफ़ का अनुकरण है। कोई कार्ट नहीं भेजी गई, ऐप या लिंक नहीं खोला गया और कोई भुगतान या ऑर्डर नहीं बनाया गया।", back: "YOBI पर वापस जाएँ",
  },
  "Русский": {
    countryHelp: "Сначала показаны страны, где выбранный язык используется чаще.", search: "Поиск", free: "Бесплатно", menu: "Меню", discoveries: "Открыть YOBI", foodRankings: "Рейтинг блюд", feature: "Подборка K-Demon", rankingNotice: "Демо-рейтинг для подготовленной зоны доставки, а не общий рейтинг Yogiyo в реальном времени.", reviews: "Больше отзывов", orders: "Больше заказов", popularity: "Популярно в Корее", featureTitle: "K-food с экрана, доступный рядом", featureDescription: "Показываются только блюда из K-pop Demon Hunters и связанные меню, доступные в текущей демо-зоне.", handoffTitle: "Продолжите заказ в Yogiyo", handoffDescription: "Чтобы заказать выбранное корейское блюдо, продолжите в Yogiyo.", handoffAccount: "Регистрация и платёжные данные обрабатываются внутри Yogiyo.", handoffDone: "На этом шаге открылось бы приложение Yogiyo. Демо YOBI завершается здесь.", handoffBoundary: "Это только имитация перехода. Корзина не отправлялась, приложение или ссылка не открывались, платёж и заказ не создавались.", back: "Вернуться в YOBI",
  },
};

const en: ProductCopy = {
  entry: entryEn,
  address: {
    step: "Delivery context",
    title: "Where should YOBI deliver?",
    description: "Choose either search or a booking image. This demo always resolves to the same prepared delivery address.",
    search: "Search",
    bookingImage: "Booking image",
    searchLabel: "Hotel, building or road address",
    searchPlaceholder: "Search a hotel, building or road address",
    chooseImage: "Choose a booking image",
    useDemoImage: "Use the demo booking image",
    currentAddress: "Current demo address",
    keepAddress: "Keep this address",
    demoNotice: "Demo only: this is a prepared address, not a live nationwide address search.",
    consent: "I agree to process this synthetic demo address and neutral profile for this browser session.",
    check: "Find the demo address",
    select: "Select this address",
    changeLocale: "Change language or country",
  },
  recommendation: {
    assistantName: "YOBI",
    ready: "I prepared menus that fit your saved choices.",
    foodDescription: "About this food",
    deliveryFee: "Delivery",
    freeDelivery: "Free",
    previous: "Previous menu",
    next: "Next menu",
    cardPosition: (current, total) => `Menu ${current} of ${total}`,
    compareLoading: "YOBI is comparing these menus using the current menu and Wiki evidence…",
    compareFailed: "The comparison could not be prepared. Your recommendations have not changed.",
    compareTitle: "How these menus differ",
    exhaustedTitle: "You’ve seen every new match in this session",
    exhaustedDescription: "YOBI will not repeat a menu. Edit one or two choices to open up a new set.",
    retrievingStage: "Checking eligible menus",
    evidenceStage: "Checking Wiki evidence",
    generatingStage: "Preparing grounded explanations",
    previewCount: (menus, merchants) => `${menus} menus from ${merchants} restaurants currently fit`,
    previewUnavailable: "Live combination preview is temporarily unavailable. You can still review and submit your choices.",
    zeroCombination: "That extra choice would leave no eligible menu, so it was not added.",
  },
  navigation: {
    expand: "Open YOBI discoveries",
    collapse: "Close YOBI discoveries",
    foodRankings: "Food rankings",
    feature: "K-Demon feature",
    close: "Close",
    demoRankingNotice: "Demo rankings for the current prepared delivery area—not live Yogiyo-wide rankings.",
    reviews: "Most reviewed",
    orders: "Most ordered",
    koreanPopularity: "Popular in Korea",
    loading: "Loading available demo menus…",
    unavailable: "This collection is unavailable right now. No unavailable menu has been substituted.",
    noFeatureMenus: "No mapped feature menu is currently available in this demo delivery area.",
    featureTitle: "K-food on screen, available near you",
    featureDescription: "Explore foods featured in K-pop Demon Hunters and only the mapped menus currently available in this demo delivery area.",
    selectMenu: "Choose this menu",
  },
  handoff: {
    eyebrow: "Ready for the next step",
    title: "Continue in Yogiyo to order",
    description: "Want to order the Korean menu you picked? Continue in Yogiyo.",
    account: "Sign-up and payment information would be handled in Yogiyo.",
    cta: "Yogiyo",
    done: "This is the step where the Yogiyo app would open. The YOBI demo ends here.",
    boundary: "Mock handoff only. No cart was sent, no app or URL was opened, and no payment or order was created.",
    back: "Back to YOBI",
  },
};

const ko: ProductCopy = {
  entry: entryKo,
  address: {
    step: "배달 정보",
    title: "어디로 배달하면 될까요?",
    description: "검색 또는 예약 이미지 중 하나를 선택하세요. 이 데모에서는 항상 준비된 동일 주소로 연결됩니다.",
    search: "검색",
    bookingImage: "예약 이미지",
    searchLabel: "호텔, 건물 또는 도로명 주소",
    searchPlaceholder: "호텔, 건물 또는 도로명 주소 검색",
    chooseImage: "예약 이미지 선택",
    useDemoImage: "데모 예약 이미지 사용",
    currentAddress: "현재 데모 주소",
    keepAddress: "이 주소 유지",
    demoNotice: "데모 전용 주소입니다. 실제 전국 주소 검색 기능이 아닙니다.",
    consent: "이 브라우저 세션에서 합성 데모 주소와 중립 프로필을 처리하는 데 동의합니다.",
    check: "데모 주소 찾기",
    select: "이 주소 선택",
    changeLocale: "언어 또는 국가 변경",
  },
  recommendation: {
    assistantName: "YOBI",
    ready: "저장한 취향에 맞는 메뉴를 준비했어요.",
    foodDescription: "이 음식은요",
    deliveryFee: "배달비",
    freeDelivery: "무료",
    previous: "이전 메뉴",
    next: "다음 메뉴",
    cardPosition: (current, total) => `메뉴 ${current}/${total}`,
    compareLoading: "현재 메뉴와 Wiki 근거만 사용해 차이를 비교하고 있어요…",
    compareFailed: "비교 설명을 준비하지 못했어요. 추천 메뉴는 바뀌지 않았습니다.",
    compareTitle: "추천 메뉴의 차이",
    exhaustedTitle: "이 세션에서 새로운 추천을 모두 확인했어요",
    exhaustedDescription: "이미 본 메뉴는 반복하지 않아요. 조건을 한두 개 바꿔 새로운 범위를 열어보세요.",
    retrievingStage: "주문 가능한 메뉴 확인",
    evidenceStage: "Wiki 근거 확인",
    generatingStage: "근거 기반 설명 준비",
    previewCount: (menus, merchants) => `현재 ${merchants}개 가게의 메뉴 ${menus}개가 조건에 맞아요`,
    previewUnavailable: "조합 미리보기를 잠시 사용할 수 없어요. 선택값을 검토한 뒤 제출할 수 있습니다.",
    zeroCombination: "이 조건을 더하면 가능한 메뉴가 0개라서 추가하지 않았어요.",
  },
  navigation: {
    expand: "YOBI 둘러보기 열기",
    collapse: "YOBI 둘러보기 닫기",
    foodRankings: "음식순위",
    feature: "케데헌 특집",
    close: "닫기",
    demoRankingNotice: "현재 데모 배달 지역 기준 순위이며 요기요 전체의 실시간 순위가 아닙니다.",
    reviews: "리뷰 많은 순",
    orders: "주문 많은 순",
    koreanPopularity: "한국 인기 순",
    loading: "주문 가능한 데모 메뉴를 불러오는 중…",
    unavailable: "지금은 이 목록을 불러올 수 없어요. 주문 불가능한 메뉴로 대체하지 않았습니다.",
    noFeatureMenus: "현재 데모 배달 지역에는 연결된 특집 메뉴가 없습니다.",
    featureTitle: "작품 속 K-푸드, 지금 주문 가능한 메뉴",
    featureDescription: "케이팝 데몬 헌터스에 나온 음식과 현재 데모 지역에서 실제로 선택 가능한 연결 메뉴만 소개합니다.",
    selectMenu: "이 메뉴 선택",
  },
  handoff: {
    eyebrow: "다음 단계 준비 완료",
    title: "주문은 요기요에서 계속하세요",
    description: "마음에 든 한국 메뉴를 주문하고 싶다면, 요기요에서 계속하세요.",
    account: "회원가입과 결제정보 등록은 요기요에서 진행됩니다.",
    cta: "요기요",
    done: "요기요 앱으로 이동하는 단계입니다. YOBI 데모는 여기서 종료됩니다.",
    boundary: "이동 목업만 제공합니다. 장바구니 전송, 앱·URL 실행, 결제와 주문 생성은 이루어지지 않았습니다.",
    back: "YOBI로 돌아가기",
  },
};

function buildLocalizedProductCopy(language: LocalizedLanguage): ProductCopy {
  const recommendation = getRecommendationCopy(language);
  const { selectionCopy, journeyCopy } = getExtendedCopy(language);
  const ui = getUiCopy(language);
  const profile = getProfileCopy(language);
  const entry = entryVariants[language] ?? {};
  const entryWords = localizedEntryVocabulary[language];
  const addressWords = localizedAddressVocabulary[language];
  const words = productVocabulary[language];

  return {
    entry: {
      heroTitle: entry.heroTitle ?? recommendation.selectorTitle,
      heroBuddy: entry.heroBuddy ?? recommendation.selectorEyebrow,
      pitchTitle: entryWords.pitchTitle,
      pitchDescription: entryWords.pitchDescription,
      benefitFlavor: entryWords.benefitFlavor,
      benefitDietary: entryWords.benefitDietary,
      benefitDelivery: entryWords.benefitDelivery,
      languageLabel: entry.languageLabel ?? recommendation.selectorEyebrow,
      countryLabel: entry.countryLabel ?? selectionCopy.city,
      countryHelp: () => words.countryHelp,
      start: entry.start ?? selectionCopy.confirmStart,
      localeApplies: entryWords.localeApplies,
      experienceNotice: recommendation.experienceNotice,
    },
    address: {
      step: ui.delivery,
      title: addressWords.title,
      description: addressWords.description,
      search: words.search,
      bookingImage: selectionCopy.chooseImage,
      searchLabel: selectionCopy.hotelOrStay,
      searchPlaceholder: selectionCopy.fullRoad,
      chooseImage: selectionCopy.chooseImage,
      useDemoImage: selectionCopy.useDemoImage,
      currentAddress: addressWords.currentAddress,
      keepAddress: addressWords.keepAddress,
      demoNotice: addressWords.demoNotice,
      consent: profile.consent,
      check: addressWords.checkAddress,
      select: addressWords.selectAddress,
      changeLocale: profile.changeLocale,
    },
    recommendation: {
      assistantName: "YOBI",
      ready: recommendation.resultsTitle,
      foodDescription: recommendation.matchedPreferences,
      deliveryFee: ui.delivery,
      freeDelivery: words.free,
      previous: journeyCopy.previousMenu,
      next: journeyCopy.nextMenu,
      cardPosition: (current, total) => `${words.menu} ${current}/${total}`,
      compareLoading: recommendation.generating,
      compareFailed: recommendation.failedDescription,
      compareTitle: recommendation.compare,
      exhaustedTitle: recommendation.noResultsTitle,
      exhaustedDescription: recommendation.noResultsDescription,
      retrievingStage: recommendation.retrieving,
      evidenceStage: recommendation.evidence,
      generatingStage: recommendation.generating,
      previewCount: localizedPreviewCount[language],
      previewUnavailable: recommendation.failedDescription,
      zeroCombination: recommendation.noResultsDescription,
    },
    navigation: {
      expand: `${words.discoveries} +`,
      collapse: `${words.discoveries} −`,
      foodRankings: words.foodRankings,
      feature: words.feature,
      close: ui.close,
      demoRankingNotice: words.rankingNotice,
      reviews: words.reviews,
      orders: words.orders,
      koreanPopularity: words.popularity,
      loading: recommendation.loadingChoices,
      unavailable: recommendation.failedDescription,
      noFeatureMenus: recommendation.noResultsDescription,
      featureTitle: words.featureTitle,
      featureDescription: words.featureDescription,
      selectMenu: recommendation.chooseMenu,
    },
    handoff: {
      eyebrow: ui.ready,
      title: words.handoffTitle,
      description: words.handoffDescription,
      account: words.handoffAccount,
      cta: "Yogiyo",
      done: words.handoffDone,
      boundary: words.handoffBoundary,
      back: words.back,
    },
  };
}

export function getProductCopy(language: SupportedLanguage): ProductCopy {
  if (language === "한국어") return ko;
  if (language === "English") return en;
  return buildLocalizedProductCopy(language);
}
