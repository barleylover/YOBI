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
  spice_tolerance INTEGER NOT NULL CHECK (spice_tolerance BETWEEN 1 AND 3),
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
  meal_need_state_json TEXT NOT NULL DEFAULT '{}',
  dialogue_act TEXT NOT NULL DEFAULT 'COLLECT_NEEDS',
  state_version INTEGER NOT NULL DEFAULT 0,
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

CREATE TABLE IF NOT EXISTS recommendation_snapshot (
  snapshot_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES chat_session(session_id) ON DELETE CASCADE,
  assistant_message_id TEXT NOT NULL REFERENCES chat_message(message_id) ON DELETE CASCADE,
  state_version INTEGER NOT NULL,
  meal_need_state_json TEXT NOT NULL,
  result_json TEXT NOT NULL,
  cards_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_event (
  event_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES chat_session(session_id) ON DELETE CASCADE,
  snapshot_id TEXT REFERENCES recommendation_snapshot(snapshot_id) ON DELETE SET NULL,
  event_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  result_json TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  resulting_state_version INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(session_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS merchant (
  merchant_id TEXT PRIMARY KEY,
  service_area TEXT NOT NULL,
  service_area_id TEXT,
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
  category_id TEXT,
  name_ko TEXT NOT NULL,
  name_en TEXT NOT NULL,
  description TEXT NOT NULL,
  cultural_description TEXT NOT NULL,
  price INTEGER NOT NULL CHECK (price >= 0),
  serves_min INTEGER NOT NULL,
  serves_max INTEGER NOT NULL,
  spice_level INTEGER NOT NULL CHECK (spice_level BETWEEN 1 AND 3),
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
  service_area_id TEXT REFERENCES service_area(service_area_id),
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
  service_area_id TEXT REFERENCES service_area(service_area_id),
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
  confirmed_fingerprint TEXT,
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
  agent_request_key TEXT UNIQUE,
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
  cart_version INTEGER,
  cart_fingerprint TEXT,
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

CREATE TABLE IF NOT EXISTS menu_knowledge (
  knowledge_id TEXT PRIMARY KEY,
  menu_id TEXT NOT NULL REFERENCES menu(menu_id),
  knowledge_type TEXT NOT NULL,
  language TEXT NOT NULL,
  content TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_ref TEXT,
  license_state TEXT NOT NULL,
  embedding_text TEXT NOT NULL,
  embedding_vector_json TEXT,
  embedding_model TEXT,
  embedding_dimension INTEGER,
  embedding_version TEXT,
  updated_at TEXT NOT NULL
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

CREATE TABLE IF NOT EXISTS service_area (
  service_area_id TEXT PRIMARY KEY, city TEXT NOT NULL, district TEXT NOT NULL,
  display_name TEXT NOT NULL, active INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS menu_category (
  category_id TEXT PRIMARY KEY, name_ko TEXT NOT NULL, name_en TEXT NOT NULL,
  description TEXT NOT NULL, tags_json TEXT NOT NULL,
  typical_spice_min INTEGER NOT NULL, typical_spice_max INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS ingredient (
  ingredient_id TEXT PRIMARY KEY, name_ko TEXT NOT NULL, name_en TEXT NOT NULL,
  ingredient_group TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS menu_ingredient (
  menu_id TEXT NOT NULL REFERENCES menu(menu_id),
  ingredient_id TEXT NOT NULL REFERENCES ingredient(ingredient_id), status TEXT NOT NULL,
  source_id TEXT, is_optional INTEGER NOT NULL, PRIMARY KEY(menu_id, ingredient_id)
);
CREATE TABLE IF NOT EXISTS allergen (
  allergen_id TEXT PRIMARY KEY, code TEXT UNIQUE NOT NULL, name_en TEXT NOT NULL, name_ko TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS menu_allergen (
  menu_id TEXT NOT NULL REFERENCES menu(menu_id),
  allergen_id TEXT NOT NULL REFERENCES allergen(allergen_id), status TEXT NOT NULL,
  evidence_id TEXT, cross_contamination_status TEXT NOT NULL,
  PRIMARY KEY(menu_id, allergen_id)
);
CREATE TABLE IF NOT EXISTS dietary_attribute (
  attribute_id TEXT PRIMARY KEY, code TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS menu_dietary_attribute (
  menu_id TEXT NOT NULL REFERENCES menu(menu_id),
  attribute_id TEXT NOT NULL REFERENCES dietary_attribute(attribute_id), status TEXT NOT NULL,
  evidence_id TEXT, PRIMARY KEY(menu_id, attribute_id)
);
CREATE TABLE IF NOT EXISTS option_dietary_conflict (
  option_item_id TEXT NOT NULL REFERENCES menu_option_item(option_item_id), rule_code TEXT NOT NULL,
  conflict_status TEXT NOT NULL, evidence_id TEXT, PRIMARY KEY(option_item_id, rule_code)
);

CREATE TABLE IF NOT EXISTS knowledge_release (
  release_id TEXT PRIMARY KEY,
  catalog_version TEXT NOT NULL,
  manifest_sha256 TEXT NOT NULL,
  embedding_model TEXT NOT NULL,
  embedding_dimension INTEGER NOT NULL CHECK (embedding_dimension = 1536),
  embedding_version TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('LOADING','READY','FAILED','RETIRED')),
  expected_counts_json TEXT NOT NULL,
  actual_counts_json TEXT NOT NULL,
  is_synthetic INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  completed_at TEXT
);

CREATE TABLE IF NOT EXISTS dish_concept (
  release_id TEXT NOT NULL REFERENCES knowledge_release(release_id),
  concept_id TEXT NOT NULL,
  concept_type TEXT NOT NULL CHECK (concept_type IN ('CUISINE','FAMILY','VARIANT')),
  canonical_name_ko TEXT NOT NULL,
  canonical_name_en TEXT NOT NULL,
  aliases_json TEXT NOT NULL DEFAULT '[]',
  source_type TEXT NOT NULL,
  source_ref TEXT NOT NULL,
  review_status TEXT NOT NULL,
  is_synthetic INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(release_id, concept_id)
);

CREATE TABLE IF NOT EXISTS dish_relation (
  release_id TEXT NOT NULL,
  relation_id TEXT NOT NULL,
  source_concept_id TEXT NOT NULL,
  target_concept_id TEXT NOT NULL,
  relation_type TEXT NOT NULL CHECK (relation_type IN ('IS_A','VARIANT_OF','SIMILAR_TO')),
  inherit_claims INTEGER NOT NULL DEFAULT 1,
  source_ref TEXT NOT NULL,
  is_synthetic INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(release_id, relation_id),
  FOREIGN KEY(release_id, source_concept_id) REFERENCES dish_concept(release_id, concept_id),
  FOREIGN KEY(release_id, target_concept_id) REFERENCES dish_concept(release_id, concept_id)
);

CREATE TABLE IF NOT EXISTS dish_concept_closure (
  release_id TEXT NOT NULL,
  descendant_concept_id TEXT NOT NULL,
  ancestor_concept_id TEXT NOT NULL,
  depth INTEGER NOT NULL CHECK (depth >= 0),
  inherit_claims INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY(release_id, descendant_concept_id, ancestor_concept_id),
  FOREIGN KEY(release_id, descendant_concept_id) REFERENCES dish_concept(release_id, concept_id),
  FOREIGN KEY(release_id, ancestor_concept_id) REFERENCES dish_concept(release_id, concept_id)
);

CREATE TABLE IF NOT EXISTS concept_claim (
  release_id TEXT NOT NULL,
  claim_id TEXT NOT NULL,
  concept_id TEXT NOT NULL,
  claim_type TEXT NOT NULL CHECK (claim_type IN ('INGREDIENT','ALLERGEN','DIETARY','FACET','PREPARATION')),
  ingredient_id TEXT REFERENCES ingredient(ingredient_id),
  allergen_id TEXT REFERENCES allergen(allergen_id),
  attribute_id TEXT REFERENCES dietary_attribute(attribute_id),
  facet_key TEXT,
  value_text TEXT,
  ingredient_role TEXT,
  assertion_status TEXT NOT NULL,
  inheritance_mode TEXT NOT NULL DEFAULT 'INHERIT',
  source_ref TEXT NOT NULL,
  review_status TEXT NOT NULL,
  is_synthetic INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(release_id, claim_id),
  FOREIGN KEY(release_id, concept_id) REFERENCES dish_concept(release_id, concept_id)
);

CREATE TABLE IF NOT EXISTS knowledge_document (
  release_id TEXT NOT NULL,
  document_id TEXT NOT NULL,
  concept_id TEXT NOT NULL,
  language TEXT NOT NULL,
  title TEXT NOT NULL,
  source_path TEXT NOT NULL,
  front_matter_json TEXT NOT NULL,
  content_markdown TEXT NOT NULL,
  content_sha256 TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_ref TEXT NOT NULL,
  license_state TEXT NOT NULL,
  review_status TEXT NOT NULL,
  is_synthetic INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(release_id, document_id),
  FOREIGN KEY(release_id, concept_id) REFERENCES dish_concept(release_id, concept_id),
  UNIQUE(release_id, source_path)
);

CREATE TABLE IF NOT EXISTS knowledge_chunk (
  release_id TEXT NOT NULL,
  chunk_id TEXT NOT NULL,
  document_id TEXT NOT NULL,
  concept_id TEXT NOT NULL,
  language TEXT NOT NULL,
  facet TEXT NOT NULL,
  chunk_index INTEGER NOT NULL,
  content TEXT NOT NULL,
  content_sha256 TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  embedding_text TEXT NOT NULL,
  embedding_vector_json TEXT,
  embedding_model TEXT NOT NULL,
  embedding_dimension INTEGER NOT NULL CHECK (embedding_dimension = 1536),
  embedding_version TEXT NOT NULL,
  is_synthetic INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(release_id, chunk_id),
  FOREIGN KEY(release_id, document_id) REFERENCES knowledge_document(release_id, document_id),
  FOREIGN KEY(release_id, concept_id) REFERENCES dish_concept(release_id, concept_id),
  UNIQUE(release_id, document_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS menu_concept_map (
  release_id TEXT NOT NULL REFERENCES knowledge_release(release_id),
  menu_id TEXT NOT NULL REFERENCES menu(menu_id),
  concept_id TEXT,
  mapping_status TEXT NOT NULL CHECK (mapping_status IN ('MAPPED','UNMAPPED')),
  mapping_type TEXT NOT NULL CHECK (mapping_type IN ('EXACT','VARIANT','FAMILY','UNMAPPED')),
  unmapped_reason TEXT,
  confidence_band TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_ref TEXT NOT NULL,
  review_status TEXT NOT NULL,
  is_synthetic INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(release_id, menu_id),
  FOREIGN KEY(release_id, concept_id) REFERENCES dish_concept(release_id, concept_id)
);

CREATE TABLE IF NOT EXISTS merchant_origin_declaration (
  release_id TEXT NOT NULL REFERENCES knowledge_release(release_id),
  declaration_id TEXT NOT NULL,
  merchant_id TEXT NOT NULL REFERENCES merchant(merchant_id),
  language TEXT NOT NULL,
  raw_text TEXT NOT NULL,
  content_sha256 TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_ref TEXT NOT NULL,
  source_version TEXT NOT NULL,
  review_status TEXT NOT NULL,
  is_synthetic INTEGER NOT NULL DEFAULT 1,
  valid_from TEXT,
  valid_to TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(release_id, declaration_id)
);

CREATE TABLE IF NOT EXISTS merchant_ingredient (
  release_id TEXT NOT NULL,
  merchant_id TEXT NOT NULL REFERENCES merchant(merchant_id),
  ingredient_id TEXT NOT NULL REFERENCES ingredient(ingredient_id),
  declaration_id TEXT NOT NULL,
  status TEXT NOT NULL,
  origin_text TEXT,
  source_ref TEXT NOT NULL,
  is_synthetic INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(release_id, merchant_id, ingredient_id, declaration_id),
  FOREIGN KEY(release_id, declaration_id)
    REFERENCES merchant_origin_declaration(release_id, declaration_id)
);

CREATE TABLE IF NOT EXISTS option_ingredient_effect (
  release_id TEXT NOT NULL REFERENCES knowledge_release(release_id),
  option_item_id TEXT NOT NULL REFERENCES menu_option_item(option_item_id),
  ingredient_id TEXT NOT NULL REFERENCES ingredient(ingredient_id),
  effect TEXT NOT NULL CHECK (effect IN ('ADD','REMOVE')),
  assertion_status TEXT NOT NULL,
  source_ref TEXT NOT NULL,
  is_synthetic INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(release_id, option_item_id, ingredient_id, effect)
);

CREATE TABLE IF NOT EXISTS knowledge_runtime_state (
  state_key TEXT PRIMARY KEY CHECK (state_key = 'ACTIVE'),
  active_release_id TEXT NOT NULL REFERENCES knowledge_release(release_id),
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_menu_category ON menu(category, availability, price);
CREATE INDEX IF NOT EXISTS idx_menu_merchant ON menu(merchant_id);
CREATE INDEX IF NOT EXISTS idx_evidence_subject ON evidence(subject_id, claim_type);
CREATE INDEX IF NOT EXISTS idx_review_menu ON review_snippet(menu_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_menu ON menu_knowledge(menu_id, knowledge_type);
CREATE INDEX IF NOT EXISTS idx_dietary_menu ON menu_dietary_attribute(menu_id, status);
CREATE INDEX IF NOT EXISTS idx_allergen_menu ON menu_allergen(menu_id, status);
"""
