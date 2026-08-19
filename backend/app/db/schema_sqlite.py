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
  structured_request_id TEXT,
  criteria_version INTEGER,
  criteria_json TEXT,
  criteria_hash TEXT,
  recommendation_release_family_id TEXT,
  evidence_pool_json TEXT NOT NULL DEFAULT '[]',
  generation_status TEXT,
  generation_call_count INTEGER NOT NULL DEFAULT 0 CHECK (generation_call_count BETWEEN 0 AND 1),
  grounding_validation_json TEXT,
  ranking_trace_json TEXT,
  ranking_policy_version TEXT,
  support_manifest_sha256 TEXT,
  feature_manifest_sha256 TEXT,
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

CREATE TABLE IF NOT EXISTS catalog_import_batch (
  catalog_import_id TEXT PRIMARY KEY,
  catalog_release_id TEXT UNIQUE NOT NULL,
  data_origin TEXT NOT NULL,
  source_platform TEXT NOT NULL,
  source_zip_sha256 TEXT NOT NULL,
  source_xlsx_sha256 TEXT NOT NULL,
  source_summary_sha256 TEXT NOT NULL,
  package_sha256 TEXT NOT NULL,
  selection_manifest_sha256 TEXT NOT NULL,
  selection_algorithm_version TEXT NOT NULL,
  collection_location TEXT NOT NULL,
  source_collected_at TEXT NOT NULL,
  selected_merchant_count INTEGER NOT NULL,
  expected_counts_json TEXT NOT NULL,
  actual_counts_json TEXT NOT NULL,
  diagnostics_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('LOADING','ACTIVE','FAILED','RETIRED')),
  started_at TEXT NOT NULL,
  completed_at TEXT
);

CREATE TABLE IF NOT EXISTS merchant (
  merchant_id TEXT PRIMARY KEY,
  service_area TEXT NOT NULL,
  service_area_id TEXT,
  name_ko TEXT NOT NULL,
  name_en TEXT,
  description TEXT,
  delivery_fee INTEGER NOT NULL,
  eta_min INTEGER NOT NULL,
  eta_max INTEGER NOT NULL,
  min_order_amount INTEGER NOT NULL,
  flavor_profile TEXT,
  packaging_signal TEXT,
  is_synthetic INTEGER NOT NULL DEFAULT 1,
  catalog_import_id TEXT,
  data_origin TEXT,
  source_platform TEXT,
  source_merchant_id TEXT,
  source_collected_at TEXT
);

CREATE TABLE IF NOT EXISTS menu (
  menu_id TEXT PRIMARY KEY,
  merchant_id TEXT NOT NULL REFERENCES merchant(merchant_id),
  category TEXT NOT NULL,
  category_id TEXT,
  name_ko TEXT NOT NULL,
  name_en TEXT,
  description TEXT,
  cultural_description TEXT,
  price INTEGER NOT NULL CHECK (price >= 0),
  serves_min INTEGER,
  serves_max INTEGER,
  spice_level INTEGER CHECK (spice_level BETWEEN 1 AND 5),
  dietary_tags_json TEXT NOT NULL,
  allergen_tags_json TEXT NOT NULL,
  semantic_text TEXT NOT NULL,
  availability TEXT NOT NULL DEFAULT 'AVAILABLE',
  is_synthetic INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL,
  catalog_import_id TEXT,
  data_origin TEXT,
  source_platform TEXT,
  source_menu_id TEXT,
  source_section_id TEXT,
  name_en_status TEXT,
  cultural_description_status TEXT,
  serves_status TEXT,
  spice_status TEXT,
  dietary_data_status TEXT
);

CREATE TABLE IF NOT EXISTS menu_semantic_embedding (
  catalog_release_id TEXT NOT NULL,
  menu_id TEXT NOT NULL REFERENCES menu(menu_id),
  embedding_model TEXT NOT NULL,
  embedding_version TEXT NOT NULL,
  embedding_dimension INTEGER NOT NULL CHECK (embedding_dimension = 1536),
  semantic_text_sha256 TEXT NOT NULL CHECK (length(semantic_text_sha256) = 64),
  embedding_manifest_sha256 TEXT NOT NULL CHECK (length(embedding_manifest_sha256) = 64),
  embedding_vector_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(catalog_release_id,menu_id,embedding_model,embedding_version)
);
CREATE INDEX IF NOT EXISTS idx_menu_semantic_identity
  ON menu_semantic_embedding(
    catalog_release_id,embedding_model,embedding_version,embedding_dimension,menu_id
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
  name_en TEXT,
  name_ko TEXT NOT NULL,
  description TEXT,
  required INTEGER NOT NULL,
  min_select INTEGER NOT NULL,
  max_select INTEGER NOT NULL,
  sort_order INTEGER NOT NULL,
  catalog_import_id TEXT,
  source_option_group_id TEXT,
  normalization_code TEXT
);

CREATE TABLE IF NOT EXISTS menu_option_item (
  option_item_id TEXT PRIMARY KEY,
  option_group_id TEXT NOT NULL REFERENCES menu_option_group(option_group_id),
  name_en TEXT,
  name_ko TEXT NOT NULL,
  description TEXT,
  price_delta INTEGER NOT NULL CHECK (price_delta >= 0),
  availability TEXT NOT NULL DEFAULT 'AVAILABLE',
  dietary_conflict TEXT,
  sort_order INTEGER NOT NULL,
  catalog_import_id TEXT,
  source_option_item_key TEXT
);

CREATE TABLE IF NOT EXISTS merchant_source_detail (
  merchant_id TEXT PRIMARY KEY REFERENCES merchant(merchant_id),
  catalog_import_id TEXT NOT NULL REFERENCES catalog_import_batch(catalog_import_id),
  latitude TEXT,
  longitude TEXT,
  distance_m REAL,
  vertical_type TEXT,
  vertical_sub_type TEXT,
  current_open_status TEXT,
  review_average REAL,
  review_count INTEGER,
  review_image_count INTEGER,
  review_reply_count INTEGER,
  franchise_json TEXT,
  vendor_categories_json TEXT NOT NULL,
  tags_json TEXT NOT NULL,
  image_json TEXT NOT NULL,
  serving_type_json TEXT NOT NULL,
  representative_menus_json TEXT NOT NULL,
  operational_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS menu_source_detail (
  menu_id TEXT PRIMARY KEY REFERENCES menu(menu_id),
  catalog_import_id TEXT NOT NULL REFERENCES catalog_import_batch(catalog_import_id),
  source_section_id TEXT,
  review_count INTEGER,
  liquor INTEGER NOT NULL,
  is_adult INTEGER NOT NULL,
  verified_adult INTEGER NOT NULL,
  soldout INTEGER NOT NULL,
  stock_amount INTEGER,
  thumbnail_json TEXT NOT NULL,
  badges_json TEXT NOT NULL,
  announcement_json TEXT,
  price_json TEXT NOT NULL,
  point INTEGER,
  point_promotions_json TEXT NOT NULL,
  operational_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS menu_source_section (
  source_section_key TEXT PRIMARY KEY,
  catalog_import_id TEXT NOT NULL REFERENCES catalog_import_batch(catalog_import_id),
  merchant_id TEXT NOT NULL REFERENCES merchant(merchant_id),
  source_section_id TEXT NOT NULL,
  section_type TEXT,
  title TEXT,
  description TEXT,
  liquor INTEGER NOT NULL,
  is_adult INTEGER NOT NULL,
  disposable INTEGER NOT NULL,
  additional_discounted INTEGER NOT NULL,
  sort_order INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS menu_source_section_item (
  source_section_key TEXT NOT NULL REFERENCES menu_source_section(source_section_key),
  menu_id TEXT NOT NULL REFERENCES menu(menu_id),
  sort_order INTEGER NOT NULL,
  PRIMARY KEY(source_section_key, menu_id)
);

CREATE TABLE IF NOT EXISTS source_option (
  source_option_key TEXT PRIMARY KEY,
  catalog_import_id TEXT NOT NULL REFERENCES catalog_import_batch(catalog_import_id),
  merchant_id TEXT NOT NULL REFERENCES merchant(merchant_id),
  source_option_id TEXT NOT NULL,
  name_ko TEXT NOT NULL,
  description TEXT,
  origin_price INTEGER,
  final_price INTEGER,
  discount_percent REAL,
  soldout INTEGER NOT NULL,
  stock_amount INTEGER,
  deposit_json TEXT NOT NULL,
  reusable_packaging INTEGER NOT NULL,
  source_json TEXT NOT NULL,
  UNIQUE(catalog_import_id, merchant_id, source_option_id)
);

CREATE TABLE IF NOT EXISTS option_group_source_detail (
  option_group_id TEXT PRIMARY KEY REFERENCES menu_option_group(option_group_id),
  catalog_import_id TEXT NOT NULL REFERENCES catalog_import_batch(catalog_import_id),
  source_option_group_id TEXT NOT NULL,
  multiple_limit INTEGER,
  available_quantity INTEGER NOT NULL,
  available_multiple INTEGER NOT NULL,
  original_min_select INTEGER NOT NULL,
  original_max_select INTEGER NOT NULL,
  badges_json TEXT NOT NULL,
  tooltip_message TEXT,
  source_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS catalog_source_payload (
  payload_id TEXT PRIMARY KEY,
  catalog_import_id TEXT NOT NULL REFERENCES catalog_import_batch(catalog_import_id),
  entity_type TEXT NOT NULL CHECK (entity_type IN ('SHOP','MENU_RESPONSE')),
  source_entity_id TEXT NOT NULL,
  payload_sha256 TEXT NOT NULL,
  raw_payload TEXT NOT NULL,
  UNIQUE(catalog_import_id, entity_type, source_entity_id)
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
  typical_spice_min INTEGER NOT NULL CHECK (typical_spice_min BETWEEN 1 AND 5),
  typical_spice_max INTEGER NOT NULL CHECK (typical_spice_max BETWEEN 1 AND 5),
  CHECK (typical_spice_min <= typical_spice_max)
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

CREATE TABLE IF NOT EXISTS recommendation_release_family (
  release_family_id TEXT PRIMARY KEY,
  knowledge_release_id TEXT NOT NULL REFERENCES knowledge_release(release_id),
  catalog_release_id TEXT NOT NULL,
  preference_catalog_version TEXT NOT NULL,
  spice_reference_version TEXT NOT NULL,
  certification_release_id TEXT NOT NULL,
  embedding_model TEXT NOT NULL,
  embedding_version TEXT NOT NULL,
  support_manifest_sha256 TEXT NOT NULL DEFAULT '0000000000000000000000000000000000000000000000000000000000000000',
  feature_manifest_sha256 TEXT NOT NULL DEFAULT '0000000000000000000000000000000000000000000000000000000000000000',
  ranking_policy_version TEXT NOT NULL DEFAULT 'legacy-llm-rank-v2',
  ranking_policy_sha256 TEXT NOT NULL DEFAULT '0000000000000000000000000000000000000000000000000000000000000000',
  status TEXT NOT NULL CHECK (status IN ('LOADING','READY','ACTIVE','RETIRED')),
  activated_at TEXT
);

CREATE TABLE IF NOT EXISTS concept_preference_support (
  knowledge_release_id TEXT NOT NULL,
  concept_id TEXT NOT NULL,
  category_code TEXT NOT NULL,
  option_code TEXT NOT NULL,
  support_status TEXT NOT NULL
    CHECK (support_status IN ('SUPPORTED','UNSUPPORTED','REVIEW_REQUIRED')),
  support_strength REAL NOT NULL CHECK (support_strength >= 0 AND support_strength <= 1),
  evidence_chunk_id TEXT,
  provenance_type TEXT NOT NULL,
  source_ref TEXT NOT NULL,
  review_status TEXT NOT NULL,
  support_method_version TEXT NOT NULL,
  is_synthetic INTEGER NOT NULL DEFAULT 1 CHECK (is_synthetic IN (0,1)),
  updated_at TEXT NOT NULL,
  PRIMARY KEY(knowledge_release_id, concept_id, category_code, option_code),
  FOREIGN KEY(knowledge_release_id, concept_id)
    REFERENCES dish_concept(release_id, concept_id),
  FOREIGN KEY(knowledge_release_id, evidence_chunk_id)
    REFERENCES knowledge_chunk(release_id, chunk_id),
  CHECK (support_status != 'SUPPORTED' OR evidence_chunk_id IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS menu_preference_feature (
  knowledge_release_id TEXT NOT NULL REFERENCES knowledge_release(release_id),
  feature_id TEXT NOT NULL,
  menu_id TEXT NOT NULL REFERENCES menu(menu_id),
  category_code TEXT NOT NULL,
  option_code TEXT NOT NULL,
  support_status TEXT NOT NULL
    CHECK (support_status IN ('SUPPORTED','CONTRADICTED','REVIEW_REQUIRED')),
  support_strength REAL NOT NULL CHECK (support_strength >= 0 AND support_strength <= 1),
  confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  specificity REAL NOT NULL CHECK (specificity >= 0 AND specificity <= 1),
  evidence_scope TEXT NOT NULL
    CHECK (evidence_scope IN ('MENU_DIRECT','SECTION_CONTEXT','OPTION_AVAILABILITY','CONCEPT_GENERAL')),
  provenance_type TEXT NOT NULL,
  source_ref TEXT NOT NULL,
  review_status TEXT NOT NULL,
  extractor_version TEXT NOT NULL,
  is_synthetic INTEGER NOT NULL DEFAULT 1 CHECK (is_synthetic IN (0,1)),
  updated_at TEXT NOT NULL,
  PRIMARY KEY(knowledge_release_id, feature_id),
  UNIQUE(knowledge_release_id, menu_id, category_code, option_code)
);

CREATE TABLE IF NOT EXISTS menu_preference_feature_evidence (
  knowledge_release_id TEXT NOT NULL,
  evidence_id TEXT NOT NULL,
  feature_id TEXT NOT NULL,
  evidence_role TEXT NOT NULL
    CHECK (evidence_role IN ('SUPPORT','CONTRADICTION','CONTEXT','OVERRIDDEN_GENERAL')),
  source_type TEXT NOT NULL
    CHECK (source_type IN ('MENU_NAME','MENU_DESCRIPTION','MENU_SECTION','MENU_OPTION','WIKI_CHUNK')),
  excerpt TEXT NOT NULL,
  excerpt_sha256 TEXT NOT NULL,
  source_ref TEXT NOT NULL,
  provenance_type TEXT NOT NULL,
  is_synthetic INTEGER NOT NULL DEFAULT 1 CHECK (is_synthetic IN (0,1)),
  updated_at TEXT NOT NULL,
  PRIMARY KEY(knowledge_release_id, evidence_id),
  FOREIGN KEY(knowledge_release_id, feature_id)
    REFERENCES menu_preference_feature(knowledge_release_id, feature_id)
);

CREATE TABLE IF NOT EXISTS menu_concept_membership (
  knowledge_release_id TEXT NOT NULL REFERENCES knowledge_release(release_id),
  menu_id TEXT NOT NULL REFERENCES menu(menu_id),
  concept_id TEXT NOT NULL,
  membership_role TEXT NOT NULL
    CHECK (membership_role IN ('PRIMARY','COMPONENT','SECONDARY')),
  confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  provenance_type TEXT NOT NULL,
  source_ref TEXT NOT NULL,
  review_status TEXT NOT NULL,
  extractor_version TEXT NOT NULL,
  is_synthetic INTEGER NOT NULL DEFAULT 1 CHECK (is_synthetic IN (0,1)),
  updated_at TEXT NOT NULL,
  PRIMARY KEY(knowledge_release_id, menu_id, concept_id),
  FOREIGN KEY(knowledge_release_id, concept_id)
    REFERENCES dish_concept(release_id, concept_id)
);

CREATE TABLE IF NOT EXISTS menu_wiki_eligibility (
  knowledge_release_id TEXT NOT NULL REFERENCES knowledge_release(release_id),
  menu_id TEXT NOT NULL REFERENCES menu(menu_id),
  reviewed_chunk_count INTEGER NOT NULL CHECK (reviewed_chunk_count > 0),
  compiled_at TEXT NOT NULL,
  PRIMARY KEY(knowledge_release_id, menu_id)
);

CREATE TABLE IF NOT EXISTS recommendation_runtime_state (
  state_key TEXT PRIMARY KEY CHECK (state_key = 'ACTIVE'),
  active_release_family_id TEXT NOT NULL
    REFERENCES recommendation_release_family(release_family_id),
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recommendation_preference_option (
  catalog_version TEXT NOT NULL,
  category_code TEXT NOT NULL,
  option_code TEXT NOT NULL,
  label_ko TEXT NOT NULL,
  label_en TEXT NOT NULL,
  query_aliases_json TEXT NOT NULL,
  display_order INTEGER NOT NULL CHECK (display_order >= 0),
  active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
  PRIMARY KEY(catalog_version, category_code, option_code)
);

CREATE TABLE IF NOT EXISTS spice_reference (
  reference_version TEXT NOT NULL,
  country_code TEXT NOT NULL CHECK (country_code IN ('KR','US')),
  spice_level INTEGER NOT NULL CHECK (spice_level BETWEEN 1 AND 5),
  label_ko TEXT NOT NULL,
  label_en TEXT NOT NULL,
  example_ko TEXT NOT NULL,
  example_en TEXT NOT NULL,
  PRIMARY KEY(reference_version, country_code, spice_level)
);

CREATE TABLE IF NOT EXISTS merchant_certification (
  certification_id TEXT PRIMARY KEY,
  certification_release_id TEXT NOT NULL,
  merchant_id TEXT NOT NULL REFERENCES merchant(merchant_id),
  certification_type TEXT NOT NULL CHECK (certification_type = 'HALAL'),
  status TEXT NOT NULL CHECK (status IN ('ACTIVE','EXPIRED','REVOKED')),
  issuer TEXT NOT NULL,
  certificate_number TEXT NOT NULL,
  valid_from TEXT NOT NULL,
  valid_to TEXT,
  scope_type TEXT NOT NULL CHECK (scope_type IN ('MERCHANT','MENU')),
  scope_ref TEXT,
  source_type TEXT NOT NULL,
  source_ref TEXT NOT NULL,
  last_verified_at TEXT NOT NULL,
  is_synthetic INTEGER NOT NULL DEFAULT 1 CHECK (is_synthetic IN (0,1)),
  CHECK (
    (scope_type='MERCHANT' AND scope_ref IS NULL)
    OR (scope_type='MENU' AND scope_ref IS NOT NULL)
  )
);

CREATE TABLE IF NOT EXISTS session_recommendation_criteria (
  session_id TEXT NOT NULL REFERENCES chat_session(session_id) ON DELETE CASCADE,
  criteria_version INTEGER NOT NULL CHECK (criteria_version >= 1),
  criteria_json TEXT NOT NULL,
  criteria_hash TEXT NOT NULL,
  request_id TEXT NOT NULL,
  state_version INTEGER NOT NULL CHECK (state_version >= 0),
  created_at TEXT NOT NULL,
  PRIMARY KEY(session_id, criteria_version),
  UNIQUE(session_id, request_id)
);

CREATE TABLE IF NOT EXISTS structured_recommendation_request (
  session_id TEXT NOT NULL REFERENCES chat_session(session_id) ON DELETE CASCADE,
  request_id TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  criteria_version INTEGER NOT NULL,
  mode TEXT NOT NULL CHECK (mode IN ('INITIAL','SIMILAR','RETRY')),
  status TEXT NOT NULL CHECK (
    status IN (
      'CREATED','DISPATCHED','COMPLETED','NO_RESULTS','NO_MATCH',
      'SEARCH_FALLBACK','FAILED','UNKNOWN_AFTER_DISPATCH'
    )
  ),
  state_version INTEGER NOT NULL CHECK (state_version >= 0),
  recommendation_release_family_id TEXT NOT NULL
    REFERENCES recommendation_release_family(release_family_id),
  eligibility_as_of TEXT NOT NULL,
  snapshot_id TEXT,
  evidence_pool_json TEXT NOT NULL DEFAULT '[]',
  result_json TEXT,
  final_candidates_json TEXT NOT NULL DEFAULT '[]',
  ranking_trace_json TEXT NOT NULL DEFAULT '{}',
  ranking_policy_version TEXT NOT NULL DEFAULT 'legacy-llm-rank-v2',
  support_manifest_sha256 TEXT NOT NULL DEFAULT '0000000000000000000000000000000000000000000000000000000000000000',
  feature_manifest_sha256 TEXT NOT NULL DEFAULT '0000000000000000000000000000000000000000000000000000000000000000',
  finalized_at TEXT,
  dispatch_count INTEGER NOT NULL DEFAULT 0 CHECK (dispatch_count BETWEEN 0 AND 1),
  failure_code TEXT,
  created_at TEXT NOT NULL,
  dispatched_at TEXT,
  completed_at TEXT,
  PRIMARY KEY(session_id, request_id),
  FOREIGN KEY(session_id, criteria_version)
    REFERENCES session_recommendation_criteria(session_id, criteria_version)
);

CREATE INDEX IF NOT EXISTS idx_rec_criteria_latest
  ON session_recommendation_criteria(session_id, criteria_version DESC);
CREATE INDEX IF NOT EXISTS idx_rec_request_status
  ON structured_recommendation_request(session_id, status, created_at);
CREATE INDEX IF NOT EXISTS idx_menu_pref_feature_lookup
  ON menu_preference_feature(
    knowledge_release_id, category_code, option_code, support_status, menu_id
  );
CREATE INDEX IF NOT EXISTS idx_menu_pref_feature_menu
  ON menu_preference_feature(knowledge_release_id, menu_id, support_status);
CREATE INDEX IF NOT EXISTS idx_menu_pref_evidence_feature
  ON menu_preference_feature_evidence(knowledge_release_id, feature_id, evidence_role);
CREATE INDEX IF NOT EXISTS idx_menu_concept_membership_lookup
  ON menu_concept_membership(knowledge_release_id, concept_id, membership_role, menu_id);
CREATE INDEX IF NOT EXISTS idx_menu_concept_membership_concept
  ON menu_concept_membership(knowledge_release_id, concept_id, menu_id);
CREATE INDEX IF NOT EXISTS idx_menu_wiki_eligibility_menu
  ON menu_wiki_eligibility(menu_id, knowledge_release_id);
CREATE INDEX IF NOT EXISTS idx_dish_closure_ancestor
  ON dish_concept_closure(
    release_id, ancestor_concept_id, inherit_claims, descendant_concept_id
  );
CREATE INDEX IF NOT EXISTS idx_knowledge_chunk_lookup
  ON knowledge_chunk(release_id, concept_id, facet, document_id, chunk_id);
CREATE INDEX IF NOT EXISTS idx_merchant_cert_active
  ON merchant_certification(
    certification_release_id, certification_type, status, merchant_id, valid_from, valid_to
  );
CREATE INDEX IF NOT EXISTS idx_preference_option_active
  ON recommendation_preference_option(catalog_version, category_code, active, display_order);
CREATE INDEX IF NOT EXISTS idx_menu_category ON menu(category, availability, price);
CREATE INDEX IF NOT EXISTS idx_menu_merchant ON menu(merchant_id);
CREATE INDEX IF NOT EXISTS idx_evidence_subject ON evidence(subject_id, claim_type);
CREATE INDEX IF NOT EXISTS idx_review_menu ON review_snippet(menu_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_menu ON menu_knowledge(menu_id, knowledge_type);
CREATE INDEX IF NOT EXISTS idx_dietary_menu ON menu_dietary_attribute(menu_id, status);
CREATE INDEX IF NOT EXISTS idx_allergen_menu ON menu_allergen(menu_id, status);
CREATE INDEX IF NOT EXISTS idx_catalog_batch_status
  ON catalog_import_batch(status, completed_at);
CREATE INDEX IF NOT EXISTS idx_source_section_merchant
  ON menu_source_section(merchant_id, sort_order);
CREATE INDEX IF NOT EXISTS idx_option_group_menu
  ON menu_option_group(menu_id, sort_order);
CREATE INDEX IF NOT EXISTS idx_option_item_group
  ON menu_option_item(option_group_id, availability, sort_order);
CREATE INDEX IF NOT EXISTS idx_source_option_merchant
  ON source_option(merchant_id, source_option_id);
"""
