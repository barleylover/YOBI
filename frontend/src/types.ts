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
  /** Legacy read compatibility only. The v2 UI never collects or applies this value. */
  allergy_severity?: "mild" | "moderate" | "severe";
  consent_demo_data: boolean;
  remember_profile: boolean;
}

export type SpiceReferenceCountry = "KR" | "US";

export interface DietaryFiltersV2 {
  halal_certified_only: boolean;
  vegan: boolean;
}

export interface RecommendationCriteriaV2 {
  schema_version: "2";
  cuisine_origins: string[];
  flavors: string[];
  main_ingredients: string[];
  food_forms: string[];
  temperatures: string[];
  price_bands: string[];
  textures: string[];
  cooking_methods: string[];
  dietary_filters: DietaryFiltersV2;
  max_spice_level: 1 | 2 | 3 | 4 | 5;
  spice_reference_country: SpiceReferenceCountry;
}

export type PreferenceCategoryCode =
  | "cuisine_origins"
  | "flavors"
  | "main_ingredients"
  | "food_forms"
  | "temperatures"
  | "price_bands"
  | "textures"
  | "cooking_methods";

export type PreferenceCategoryGroup = "core" | "additional" | "exact";

export interface PreferenceCatalogOption {
  code: string;
  label: string;
  description?: string | null;
}

export interface PreferenceCatalogCategory {
  code: PreferenceCategoryCode;
  group: PreferenceCategoryGroup;
  label: string;
  description?: string | null;
  options: PreferenceCatalogOption[];
}

export interface SpiceReferenceLevel {
  level: 1 | 2 | 3 | 4 | 5;
  label: string;
  example: string;
  description?: string | null;
}

export interface SpiceReferenceGroup {
  country: SpiceReferenceCountry;
  label: string;
  levels: SpiceReferenceLevel[];
}

export interface PreferenceCatalog {
  schema_version: "2";
  catalog_version: string;
  knowledge_release_id: string;
  locale: string;
  categories: PreferenceCatalogCategory[];
  spice_references: SpiceReferenceGroup[];
  capabilities?: {
    halal_certified_only?: { enabled: boolean; reason?: string | null };
    vegan?: { enabled: boolean; reason?: string | null };
    max_spice_level?: { enabled: boolean; reason?: string | null };
  };
}

export interface RecommendationPreviewV2 {
  eligible_menu_count: number;
  eligible_merchant_count: number;
  zero_reason_codes: string[];
  release_id: string;
  support_manifest_sha256: string;
  ranking_policy_version: string;
  timing_ms: number;
  unsupported_controls?: string[];
}

export type RecommendationMode = "INITIAL" | "SIMILAR" | "RETRY";
export type RecommendationPhase =
  | "SELECTING"
  | "RETRIEVING"
  | "GENERATING"
  | "RESULTS"
  | "SEARCH_FALLBACK"
  | "NO_RESULTS"
  | "ERROR"
  | "ORDERING";

export type VeganEvidenceStatus = "LIKELY_FIT" | "POSSIBLE_WITH_CHECKS" | "CONFLICT" | "UNKNOWN";

export interface CriterionMatch {
  category_code: string;
  selected_value_codes: string[];
  labels?: string[];
  evidence_ids?: string[];
}

export interface RecommendationWikiEvidence {
  evidence_id: string;
  evidence_type: "WIKI_PASSAGE" | "ESSENTIAL_FACT" | "MENU_FACT" | "CERTIFICATION";
  chunk_id?: string;
  content: string;
  score: number | null;
}

export interface StructuredRecommendation {
  rank: number;
  menu: MenuSummary;
  title: string;
  selection_reason: string;
  description: string;
  matched_criteria: CriterionMatch[];
  wiki_passages: RecommendationWikiEvidence[];
  caution_codes: string[];
  halal_certified?: boolean | null;
  halal_scope_label?: string | null;
  vegan_status?: VeganEvidenceStatus | null;
  vegan_warning?: string | null;
}

export interface RecommendationBatchV2 {
  session_id: string;
  request_id: string;
  snapshot_id?: string | null;
  state_version: number;
  criteria_version: number;
  status: "PENDING" | "RECOMMENDED" | "NO_MATCH" | "SEARCH_FALLBACK" | "FAILED";
  phase?: "RETRIEVING" | "GENERATING" | "COMPLETE" | null;
  criteria_summary?: string | null;
  recommendations: StructuredRecommendation[];
  unmatched_category_codes: string[];
  failure_code?: string | null;
}

export interface RecommendationComparisonItemV2 {
  menu_id: string;
  name: string;
  key_difference: string;
  taste_texture: string;
  ingredients_form: string;
  spice_heaviness: string;
  eating_context: string;
  best_for: string;
  unverified_dietary_info: string;
}

export interface RecommendationComparisonV2 {
  snapshot_id: string;
  request_id: string;
  summary: string;
  items: RecommendationComparisonItemV2[];
  generated_by: "LLM" | "DETERMINISTIC_FALLBACK";
}

export interface CriteriaCommitResult {
  session_id: string;
  criteria?: RecommendationCriteriaV2;
  criteria_version: number;
  state_version: number;
  criteria_hash?: string;
  created_at?: string;
}

export interface RecommendationRequestV2 {
  request_id: string;
  expected_state_version: number;
  criteria_version: number;
  mode: RecommendationMode;
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
  spice_level: number | null;
  serves_min: number | null;
  serves_max: number | null;
  dietary_summary: string;
  evidence_status: EvidenceStatus;
  match_reasons: string[];
  risk_hints: string[];
  evidence_ids: string[];
  grounded_claim_ids: string[];
  grounded_passage_ids: string[];
  is_synthetic: boolean;
  semantic_score?: number;
  image_url?: string | null;
}

export type FoodRankingSort = "review_count" | "order_count" | "korean_popularity";

export interface FoodRankingEntry {
  position: number;
  metric_label: string;
  metric_value: number;
  menu: MenuSummary;
}

export interface FoodRankingCollection {
  snapshot_id: string;
  demo_basis: string;
  sort: FoodRankingSort;
  items: FoodRankingEntry[];
}

export interface FeaturedMenuEntry {
  dish_name: string;
  description: string;
  menu: MenuSummary;
}

export interface FeaturedMenuCollection {
  snapshot_id: string;
  items: FeaturedMenuEntry[];
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
  halal_certification_preserved?: boolean | null;
  vegan_status?: VeganEvidenceStatus | null;
  vegan_warning?: string | null;
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

export interface StructuredMenuKnowledge {
  wiki_passages?: WikiPassage[];
  ingredient_claims?: IngredientClaim[];
  allergen_claims?: AllergenClaim[];
  dietary_claims?: DietaryClaim[];
  preparation_claims?: PreparationClaim[];
}

export interface MenuExplanation extends StructuredMenuKnowledge {
  description?: string;
  cultural_analogy: string;
  portion: string;
  unknown_fields: string[];
  evidence_ids: string[];
  category?: string;
  compatible_listing?: boolean;
  is_synthetic?: boolean;
  general_wiki_explanation?: boolean;
}

export type KnowledgeClaimStatus =
  | "CONFIRMED_PRESENT"
  | "CONFIRMED_ABSENT"
  | "PRESUMED_PRESENT"
  | "POSSIBLE"
  | "UNKNOWN"
  | "CONFLICTING";

export type KnowledgeSourceScope =
  | "DISH_CONCEPT"
  | "MERCHANT"
  | "MENU"
  | "OPTION"
  | "KITCHEN";

export interface WikiPassage {
  chunk_id: string;
  document_id: string;
  concept_id?: string | null;
  facet: string;
  content: string;
  source_kind: string;
  source_version: string;
  is_synthetic: boolean;
  score: number;
}

interface KnowledgeClaimBase {
  status: KnowledgeClaimStatus;
  source_scope: KnowledgeSourceScope;
  source_id: string;
  source_version: string;
  confidence_band: string;
  inherited: boolean;
}

export interface IngredientClaim extends KnowledgeClaimBase {
  ingredient_id: string;
  name_en: string;
  name_ko?: string;
  role: "DEFINING" | "CORE" | "COMMON" | "OPTIONAL" | "REGIONAL_VARIANT" | "UNKNOWN";
}

export interface AllergenClaim extends KnowledgeClaimBase {
  allergen_id: string;
  code: string;
  cross_contamination_status: string;
}

export interface DietaryClaim extends KnowledgeClaimBase {
  attribute_id: string;
  code: string;
  display_name: string;
  value_text: string;
}

export interface PreparationClaim extends KnowledgeClaimBase {
  method: string;
  value_text: string;
}

interface CardBase {
  title: string;
  subtitle?: string;
}

export type CardPayload = CardBase & (
  | { type: "category_recommendations"; data: { categories: CategoryRecommendation[] } }
  | { type: "menu_recommendations"; data: { menus: MenuSummary[] } }
  | { type: "menu_explanation"; data: { menu?: MenuSummary; explanation: MenuExplanation } }
  | {
      type: "dietary_evidence";
      data: StructuredMenuKnowledge & {
        evidence: Evidence[];
        menu?: MenuSummary;
        menus?: { menu_id: string }[];
        unknown_fields?: string[];
      };
    }
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
  recommendation_criteria?: RecommendationCriteriaV2 | null;
  criteria_version?: number;
  latest_recommendation?: RecommendationBatchV2 | null;
  active_recommendation?: RecommendationBatchV2 | null;
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
