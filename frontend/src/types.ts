export type EvidenceStatus = "VERIFIED" | "RISK_SIGNAL" | "UNKNOWN" | "CONFLICTING";

export type DialogueAct =
  | "GREET"
  | "COLLECT_NEEDS"
  | "HOLD_RECOMMENDATION"
  | "CONFIRM_NEEDS"
  | "REQUEST_RECOMMENDATION"
  | "RECOMMEND"
  | "REQUEST_EXPLANATION"
  | "EXPLAIN"
  | "COMPARE"
  | "REVISE"
  | "REJECT"
  | "SELECT"
  | "ORDER_ACTION"
  | "OUT_OF_SCOPE"
  | "ERROR_RECOVERY";

export type RecommendationReadiness = "NOT_READY" | "READY" | "EXPLICIT_REQUEST" | "HELD";

export type FallbackReason =
  | "RATE_LIMIT"
  | "TIMEOUT"
  | "NETWORK_ERROR"
  | "INVALID_TOOL_ARGUMENT"
  | "NO_TOOL_RESPONSE"
  | "EMPTY_RESPONSE"
  | "GROUNDING_REJECTED"
  | "PROVIDER_UNAVAILABLE"
  | "UNKNOWN_PROVIDER_ERROR";

export interface MealNeedState {
  schema_version: number;
  turn_count: number;
  occasion?: string | null;
  party_size?: number | null;
  budget_krw?: number | null;
  max_spiciness?: number | null;
  service_area_id?: string | null;
  temperature_preferences: string[];
  texture_preferences: string[];
  flavor_preferences: string[];
  preferred_categories: string[];
  excluded_categories: string[];
  excluded_ingredients: string[];
  dietary_rules: string[];
  profile_dietary_rules: string[];
  positive_preferences: string[];
  negative_preferences: string[];
  shown_menu_ids: string[];
  rejected_menu_ids: string[];
  compared_menu_ids: string[];
  selected_menu_id?: string | null;
  option_selections: Record<string, string[]>;
  option_risk_acknowledged: string[];
  recommendation_hold: boolean;
  strictness: "STRICT" | "MODERATE" | "EXPLORATORY";
  last_question_key?: string | null;
}

export interface ReadinessDecision {
  status: RecommendationReadiness;
  score: number;
  information_dimensions: string[];
  missing_fields: string[];
  next_question_key?: string | null;
  reason: string;
}

export interface Profile {
  profile_id: string;
  preferred_language: string;
  nationality: string;
  religion_selection: string;
  spice_tolerance: number;
  dietary_rules: string[];
  favorite_foods: string[];
  age_band: string;
  allergy_severity: "mild" | "moderate" | "severe";
  consent_demo_data: boolean;
  remember_profile: boolean;
}

export interface Session {
  session_id: string;
  profile_id: string;
  state: string;
  selected_menu_id?: string | null;
  selected_merchant_id?: string | null;
  dialogue_act?: DialogueAct;
  meal_need_state?: MealNeedState;
  state_version?: number;
  created_at?: string;
  updated_at?: string;
}

export interface MenuSummary {
  menu_id: string;
  merchant_id: string;
  merchant_name: string;
  name_en: string;
  name_ko: string;
  category: string;
  description: string;
  cultural_description: string;
  price: number;
  delivery_fee: number;
  eta_min: number;
  eta_max: number;
  spice_level: number;
  serves_min: number;
  serves_max: number;
  dietary_summary: string;
  evidence_status: EvidenceStatus;
  match_reasons: string[];
  risk_hints: string[];
  evidence_ids: string[];
  grounded_claim_ids: string[];
  grounded_passage_ids: string[];
  is_synthetic: boolean;
  semantic_score?: number;
}

export interface CategoryRecommendation {
  category: string;
  description?: string;
  match_reasons: string[];
  risk_hints: string[];
  source_ids: string[];
}

export interface Evidence {
  evidence_id: string;
  claim_type: string;
  status: EvidenceStatus;
  source_type: string;
  excerpt: string;
  updated_at: string;
  suggested_action: string;
}

export interface MerchantComparison {
  merchant_id: string;
  merchant_name: string;
  menu_id: string;
  menu_name: string;
  price: number;
  delivery_fee: number;
  eta: string;
  portion: string;
  flavor: string;
  packaging_signal: string;
  dietary_status: EvidenceStatus;
  dietary_note: string;
  best_for: string;
  evidence_ids: string[];
  menu?: MenuSummary;
}

export interface OptionItem {
  option_item_id: string;
  name_en: string;
  name_ko: string;
  description: string;
  price_delta: number;
  available: boolean;
  dietary_conflict?: string;
  conflicting_rules: string[];
}

export interface OptionGroup {
  option_group_id: string;
  name_en: string;
  name_ko: string;
  description: string;
  required: boolean;
  min_select: number;
  max_select: number;
  items: OptionItem[];
}

export interface PresetEntry {
  rank: number;
  label: string;
  description: string;
  menu: MenuSummary;
}

export interface MenuExplanation {
  cultural_analogy: string;
  portion: string;
  unknown_fields: string[];
  evidence_ids: string[];
  category?: string;
  compatible_listing?: boolean;
}

interface CardBase {
  title: string;
  subtitle?: string;
}

export type CardPayload = CardBase & (
  | { type: "category_recommendations"; data: { categories: CategoryRecommendation[] } }
  | { type: "menu_recommendations"; data: { menus: MenuSummary[] } }
  | { type: "menu_explanation"; data: { menu?: MenuSummary; explanation: MenuExplanation } }
  | { type: "dietary_evidence"; data: { evidence: Evidence[]; menu?: MenuSummary } }
  | { type: "merchant_comparison"; data: { merchants: MerchantComparison[] } }
  | { type: "preset_collection"; data: { kind: "weekly_ranking" | "kpop_demon_hunters"; entries: PresetEntry[] } }
  | {
      type:
        | "option_question"
        | "address_upload"
        | "address_confirmation"
        | "translated_note"
        | "cart_summary"
        | "payment_cta"
        | "order_complete"
        | "error_recovery";
      data: Record<string, unknown>;
    }
);

export interface RecommendationCandidate {
  menu_id: string;
  merchant_id: string;
  rank: number;
  score: number;
  match_reasons: string[];
  risk_hints: string[];
  evidence_ids: string[];
  claim_ids: string[];
  passage_ids: string[];
}

export interface RecommendationResult {
  snapshot_id: string;
  candidates: RecommendationCandidate[];
  query_summary: string;
  grounded_claim_ids: string[];
  grounded_passage_ids: string[];
  synthetic_data: boolean;
}

export interface RecommendationSnapshot {
  snapshot_id: string;
  session_id: string;
  assistant_message_id: string;
  state_version: number;
  meal_need_state: MealNeedState;
  result: RecommendationResult;
  cards: CardPayload[];
  created_at: string;
}

export type ConversationEventType = "SELECT_MENU" | "REJECT_MENU" | "COMPARE_MENUS" | "UPDATE_OPTIONS";

export interface ConversationEventInput {
  event_type: ConversationEventType;
  snapshot_id?: string;
  menu_id?: string;
  menu_ids?: string[];
  option_group_id?: string;
  option_item_ids?: string[];
  risk_acknowledged?: boolean;
  expected_state_version?: number;
  idempotency_key: string;
}

export interface ConversationEventResult {
  event_id: string;
  event_type: ConversationEventType;
  state_version: number;
  state: MealNeedState;
  selected_menu_id?: string | null;
  selected_merchant_id?: string | null;
  selected_menu?: MenuSummary | null;
  duplicate: boolean;
}

export interface ConversationMessage {
  message_id: string;
  role: "user" | "assistant";
  content: string;
  message_type: string;
  safe_metadata: Record<string, unknown>;
  created_at: string;
}

export interface ConversationView {
  session_id: string;
  state_version: number;
  meal_need_state: MealNeedState;
  messages: ConversationMessage[];
  latest_snapshot?: RecommendationSnapshot | null;
}

export interface AssistantTurn {
  message_id: string;
  text: string;
  state: string;
  cards: CardPayload[];
  suggested_replies: string[];
  dialogue_act: DialogueAct;
  readiness?: ReadinessDecision | null;
  recommendation_result?: RecommendationResult | null;
  recommendation_snapshot_id?: string | null;
  state_version: number;
  fallback_used: boolean;
  fallback_reason?: FallbackReason | null;
  created_at: string;
}

export interface AddressCandidate {
  place_id: string;
  hotel_name: string;
  road_address: string;
  postal_code: string;
  city: string;
  delivery_hint: string;
  confidence: number;
  source: string;
  needs_confirmation: boolean;
  candidate_token: string;
}

export interface CartPreview {
  cart_id: string;
  version: number;
  items: Array<{
    cart_item_id: string;
    menu_id: string;
    menu_name: string;
    menu_name_ko: string;
    quantity: number;
    unit_price: number;
    options: Array<{ option_item_id: string; name_en: string; name_ko: string; price_delta: number }>;
    line_total: number;
  }>;
  subtotal: number;
  delivery_fee: number;
  total_price: number;
  missing_slots: string[];
  dietary_warnings: string[];
  minimum_order_amount: number;
  minimum_order_shortfall: number;
  ready_to_checkout: boolean;
  confirmed: boolean;
}

export interface Checkout {
  checkout_id: string;
  status: "PENDING" | "SUCCEEDED" | "FAILED" | "CANCELED";
  amount: number;
  payment_method: string;
  payment_url: string;
  order_id?: string;
}
