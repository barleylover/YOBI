export type EvidenceStatus = "VERIFIED" | "RISK_SIGNAL" | "UNKNOWN" | "CONFLICTING";

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
  selected_menu_id?: string;
  selected_merchant_id?: string;
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
  is_synthetic: boolean;
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

export interface CardPayload {
  type: string;
  title: string;
  subtitle?: string;
  data: Record<string, unknown>;
}

export interface AssistantTurn {
  message_id: string;
  text: string;
  state: string;
  cards: CardPayload[];
  suggested_replies: string[];
  fallback_used: boolean;
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
