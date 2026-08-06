SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS user_profile (
  profile_id TEXT PRIMARY KEY,
  preferred_language TEXT NOT NULL,
  nationality TEXT NOT NULL,
  age_band TEXT NOT NULL,
  gender TEXT NOT NULL,
  religion_selection TEXT NOT NULL,
  dietary_rules_json TEXT NOT NULL,
  allergy_severity TEXT NOT NULL,
  spice_tolerance INTEGER NOT NULL CHECK (spice_tolerance BETWEEN 0 AND 5),
  favorite_foods_json TEXT NOT NULL,
  consent_demo_data INTEGER NOT NULL,
  remember_profile INTEGER NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_session (
  session_id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES user_profile(profile_id),
  state TEXT NOT NULL,
  selected_menu_id TEXT,
  selected_merchant_id TEXT,
  state_stack_json TEXT NOT NULL DEFAULT '[]',
  required_slots_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_message (
  message_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES chat_session(session_id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  message_type TEXT NOT NULL,
  safe_metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS merchant (
  merchant_id TEXT PRIMARY KEY,
  service_area TEXT NOT NULL,
  name_ko TEXT NOT NULL,
  name_en TEXT NOT NULL,
  description TEXT NOT NULL,
  delivery_fee INTEGER NOT NULL,
  eta_min INTEGER NOT NULL,
  eta_max INTEGER NOT NULL,
  min_order_amount INTEGER NOT NULL,
  flavor_profile TEXT NOT NULL,
  packaging_signal TEXT NOT NULL,
  is_synthetic INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS menu (
  menu_id TEXT PRIMARY KEY,
  merchant_id TEXT NOT NULL REFERENCES merchant(merchant_id),
  category TEXT NOT NULL,
  name_ko TEXT NOT NULL,
  name_en TEXT NOT NULL,
  description TEXT NOT NULL,
  cultural_description TEXT NOT NULL,
  price INTEGER NOT NULL CHECK (price >= 0),
  serves_min INTEGER NOT NULL,
  serves_max INTEGER NOT NULL,
  spice_level INTEGER NOT NULL CHECK (spice_level BETWEEN 0 AND 5),
  dietary_tags_json TEXT NOT NULL,
  allergen_tags_json TEXT NOT NULL,
  semantic_text TEXT NOT NULL,
  availability TEXT NOT NULL DEFAULT 'AVAILABLE',
  is_synthetic INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence (
  evidence_id TEXT PRIMARY KEY,
  subject_id TEXT NOT NULL,
  claim_type TEXT NOT NULL,
  status TEXT NOT NULL,
  source_type TEXT NOT NULL,
  excerpt TEXT NOT NULL,
  confidence_band TEXT NOT NULL,
  suggested_action TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_snippet (
  snippet_id TEXT PRIMARY KEY,
  merchant_id TEXT NOT NULL REFERENCES merchant(merchant_id),
  menu_id TEXT NOT NULL REFERENCES menu(menu_id),
  rating INTEGER NOT NULL,
  review_text TEXT NOT NULL,
  source_type TEXT NOT NULL DEFAULT 'SYNTHETIC_DEMO',
  is_synthetic INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS menu_option_group (
  option_group_id TEXT PRIMARY KEY,
  menu_id TEXT NOT NULL REFERENCES menu(menu_id),
  name_en TEXT NOT NULL,
  name_ko TEXT NOT NULL,
  description TEXT NOT NULL,
  required INTEGER NOT NULL,
  min_select INTEGER NOT NULL,
  max_select INTEGER NOT NULL,
  sort_order INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS menu_option_item (
  option_item_id TEXT PRIMARY KEY,
  option_group_id TEXT NOT NULL REFERENCES menu_option_group(option_group_id),
  name_en TEXT NOT NULL,
  name_ko TEXT NOT NULL,
  description TEXT NOT NULL,
  price_delta INTEGER NOT NULL CHECK (price_delta >= 0),
  availability TEXT NOT NULL DEFAULT 'AVAILABLE',
  dietary_conflict TEXT,
  sort_order INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS address_place (
  place_id TEXT PRIMARY KEY,
  name_ko TEXT NOT NULL,
  name_en TEXT NOT NULL,
  aliases_json TEXT NOT NULL,
  road_address TEXT NOT NULL,
  postal_code TEXT NOT NULL,
  city TEXT NOT NULL,
  delivery_hint TEXT NOT NULL,
  fixture_sha256 TEXT,
  is_synthetic INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS address_ref (
  address_ref_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES chat_session(session_id),
  source_type TEXT NOT NULL,
  source_image_hash TEXT,
  place_id TEXT REFERENCES address_place(place_id),
  hotel_name TEXT NOT NULL,
  road_address TEXT NOT NULL,
  extraction_confidence REAL NOT NULL,
  confirmed INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cart (
  cart_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL UNIQUE REFERENCES chat_session(session_id),
  address_ref_id TEXT REFERENCES address_ref(address_ref_id),
  version INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'ACTIVE',
  confirmed INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cart_item (
  cart_item_id TEXT PRIMARY KEY,
  cart_id TEXT NOT NULL REFERENCES cart(cart_id) ON DELETE CASCADE,
  menu_id TEXT NOT NULL REFERENCES menu(menu_id),
  merchant_id TEXT NOT NULL REFERENCES merchant(merchant_id),
  quantity INTEGER NOT NULL,
  unit_price INTEGER NOT NULL,
  menu_snapshot_json TEXT NOT NULL,
  option_snapshot_json TEXT NOT NULL,
  line_total INTEGER NOT NULL,
  user_note TEXT NOT NULL DEFAULT '',
  korean_note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS delivery_preference (
  cart_id TEXT PRIMARY KEY REFERENCES cart(cart_id) ON DELETE CASCADE,
  handoff_method TEXT NOT NULL,
  cutlery INTEGER NOT NULL,
  ring_bell INTEGER NOT NULL,
  front_desk INTEGER NOT NULL,
  user_note TEXT NOT NULL,
  korean_note TEXT NOT NULL,
  back_translation TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mock_checkout (
  checkout_id TEXT PRIMARY KEY,
  cart_id TEXT NOT NULL REFERENCES cart(cart_id),
  idempotency_key TEXT NOT NULL UNIQUE,
  payment_method TEXT NOT NULL,
  status TEXT NOT NULL,
  amount INTEGER NOT NULL,
  payment_url TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mock_order (
  order_id TEXT PRIMARY KEY,
  checkout_id TEXT NOT NULL UNIQUE REFERENCES mock_checkout(checkout_id),
  cart_snapshot_json TEXT NOT NULL,
  order_status TEXT NOT NULL,
  estimated_delivery_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
  log_id TEXT PRIMARY KEY,
  session_id TEXT,
  tool TEXT NOT NULL,
  input_hash TEXT NOT NULL,
  evidence_ids_json TEXT NOT NULL,
  output_status TEXT NOT NULL,
  latency_ms INTEGER NOT NULL,
  fallback_used INTEGER NOT NULL,
  safe_error_code TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS explanation_cache (
  cache_key TEXT PRIMARY KEY,
  menu_id TEXT NOT NULL REFERENCES menu(menu_id),
  language TEXT NOT NULL,
  profile_signature TEXT NOT NULL,
  explanation_json TEXT NOT NULL,
  source_version TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_menu_category ON menu(category, availability, price);
CREATE INDEX IF NOT EXISTS idx_menu_merchant ON menu(merchant_id);
CREATE INDEX IF NOT EXISTS idx_evidence_subject ON evidence(subject_id, claim_type);
CREATE INDEX IF NOT EXISTS idx_review_menu ON review_snippet(menu_id);
"""
