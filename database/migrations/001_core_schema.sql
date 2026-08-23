CREATE TABLE user_profile (
  profile_id VARCHAR2(64) PRIMARY KEY,
  preferred_language VARCHAR2(80) NOT NULL,
  nationality VARCHAR2(120) NOT NULL,
  age_band VARCHAR2(32) NOT NULL,
  gender VARCHAR2(80) NOT NULL,
  religion_selection VARCHAR2(120) NOT NULL,
  dietary_rules_json CLOB NOT NULL CHECK (dietary_rules_json IS JSON),
  allergy_severity VARCHAR2(16) NOT NULL,
  spice_tolerance NUMBER(1) NOT NULL CHECK (spice_tolerance BETWEEN 0 AND 5),
  favorite_foods_json CLOB NOT NULL CHECK (favorite_foods_json IS JSON),
  consent_demo_data NUMBER(1) NOT NULL CHECK (consent_demo_data IN (0, 1)),
  remember_profile NUMBER(1) NOT NULL CHECK (remember_profile IN (0, 1)),
  created_at TIMESTAMP WITH TIME ZONE NOT NULL
)
-- +YOBI STATEMENT
CREATE TABLE merchant (
  merchant_id VARCHAR2(32) PRIMARY KEY,
  service_area VARCHAR2(80) NOT NULL,
  name_ko VARCHAR2(200) NOT NULL,
  name_en VARCHAR2(200) NOT NULL,
  description VARCHAR2(1000) NOT NULL,
  delivery_fee NUMBER(10) NOT NULL CHECK (delivery_fee >= 0),
  eta_min NUMBER(4) NOT NULL,
  eta_max NUMBER(4) NOT NULL,
  min_order_amount NUMBER(10) NOT NULL,
  flavor_profile VARCHAR2(1000) NOT NULL,
  packaging_signal VARCHAR2(1000) NOT NULL,
  is_synthetic NUMBER(1) DEFAULT 1 NOT NULL CHECK (is_synthetic IN (0, 1))
)
-- +YOBI STATEMENT
CREATE TABLE menu (
  menu_id VARCHAR2(32) PRIMARY KEY,
  merchant_id VARCHAR2(32) NOT NULL REFERENCES merchant(merchant_id),
  category VARCHAR2(120) NOT NULL,
  name_ko VARCHAR2(200) NOT NULL,
  name_en VARCHAR2(200) NOT NULL,
  description VARCHAR2(2000) NOT NULL,
  cultural_description VARCHAR2(2000) NOT NULL,
  price NUMBER(10) NOT NULL CHECK (price >= 0),
  serves_min NUMBER(3) NOT NULL,
  serves_max NUMBER(3) NOT NULL,
  spice_level NUMBER(1) NOT NULL CHECK (spice_level BETWEEN 0 AND 5),
  dietary_tags_json CLOB NOT NULL CHECK (dietary_tags_json IS JSON),
  allergen_tags_json CLOB NOT NULL CHECK (allergen_tags_json IS JSON),
  semantic_text CLOB NOT NULL,
  embedding_vector VECTOR(1536, FLOAT32),
  embedding_model VARCHAR2(120),
  embedding_dimension NUMBER(5),
  embedding_version VARCHAR2(80),
  availability VARCHAR2(24) DEFAULT 'AVAILABLE' NOT NULL,
  is_synthetic NUMBER(1) DEFAULT 1 NOT NULL CHECK (is_synthetic IN (0, 1)),
  updated_at VARCHAR2(32) NOT NULL
)
-- +YOBI STATEMENT
CREATE TABLE evidence (
  evidence_id VARCHAR2(64) PRIMARY KEY,
  subject_id VARCHAR2(64) NOT NULL,
  claim_type VARCHAR2(120) NOT NULL,
  status VARCHAR2(32) NOT NULL,
  source_type VARCHAR2(120) NOT NULL,
  excerpt VARCHAR2(2000) NOT NULL,
  confidence_band VARCHAR2(16) NOT NULL,
  suggested_action VARCHAR2(2000) NOT NULL,
  updated_at VARCHAR2(32) NOT NULL
)
-- +YOBI STATEMENT
CREATE TABLE review_snippet (
  snippet_id VARCHAR2(64) PRIMARY KEY,
  merchant_id VARCHAR2(32) NOT NULL REFERENCES merchant(merchant_id),
  menu_id VARCHAR2(32) NOT NULL REFERENCES menu(menu_id),
  rating NUMBER(1) NOT NULL,
  review_text VARCHAR2(2000) NOT NULL,
  source_type VARCHAR2(80) DEFAULT 'SYNTHETIC_DEMO' NOT NULL,
  is_synthetic NUMBER(1) DEFAULT 1 NOT NULL CHECK (is_synthetic IN (0, 1)),
  embedding_text VARCHAR2(2000),
  embedding_vector VECTOR(1536, FLOAT32),
  embedding_model VARCHAR2(120),
  embedding_dimension NUMBER(5),
  embedding_version VARCHAR2(80),
  updated_at VARCHAR2(32) NOT NULL
)
-- +YOBI STATEMENT
CREATE TABLE menu_option_group (
  option_group_id VARCHAR2(64) PRIMARY KEY,
  menu_id VARCHAR2(32) NOT NULL REFERENCES menu(menu_id),
  name_en VARCHAR2(120) NOT NULL,
  name_ko VARCHAR2(120) NOT NULL,
  description VARCHAR2(500) NOT NULL,
  required NUMBER(1) NOT NULL CHECK (required IN (0, 1)),
  min_select NUMBER(3) NOT NULL,
  max_select NUMBER(3) NOT NULL,
  sort_order NUMBER(4) NOT NULL
)
-- +YOBI STATEMENT
CREATE TABLE menu_option_item (
  option_item_id VARCHAR2(80) PRIMARY KEY,
  option_group_id VARCHAR2(64) NOT NULL REFERENCES menu_option_group(option_group_id),
  name_en VARCHAR2(120) NOT NULL,
  name_ko VARCHAR2(120) NOT NULL,
  description VARCHAR2(500) NOT NULL,
  price_delta NUMBER(10) NOT NULL CHECK (price_delta >= 0),
  availability VARCHAR2(24) DEFAULT 'AVAILABLE' NOT NULL,
  dietary_conflict VARCHAR2(1000),
  sort_order NUMBER(4) NOT NULL
)
-- +YOBI STATEMENT
CREATE TABLE address_place (
  place_id VARCHAR2(64) PRIMARY KEY,
  name_ko VARCHAR2(200) NOT NULL,
  name_en VARCHAR2(200) NOT NULL,
  aliases_json CLOB NOT NULL CHECK (aliases_json IS JSON),
  road_address VARCHAR2(500) NOT NULL,
  postal_code VARCHAR2(20) NOT NULL,
  city VARCHAR2(120) NOT NULL,
  delivery_hint VARCHAR2(1000) NOT NULL,
  fixture_sha256 VARCHAR2(64),
  is_synthetic NUMBER(1) DEFAULT 1 NOT NULL CHECK (is_synthetic IN (0, 1))
)
-- +YOBI STATEMENT
CREATE TABLE chat_session (
  session_id VARCHAR2(64) PRIMARY KEY,
  profile_id VARCHAR2(64) NOT NULL REFERENCES user_profile(profile_id),
  state VARCHAR2(40) NOT NULL,
  selected_menu_id VARCHAR2(32),
  selected_merchant_id VARCHAR2(32),
  state_stack_json CLOB DEFAULT '[]' NOT NULL CHECK (state_stack_json IS JSON),
  required_slots_json CLOB DEFAULT '[]' NOT NULL CHECK (required_slots_json IS JSON),
  created_at TIMESTAMP WITH TIME ZONE NOT NULL,
  updated_at TIMESTAMP WITH TIME ZONE NOT NULL
)
-- +YOBI STATEMENT
CREATE TABLE chat_message (
  message_id VARCHAR2(64) PRIMARY KEY,
  session_id VARCHAR2(64) NOT NULL REFERENCES chat_session(session_id) ON DELETE CASCADE,
  role VARCHAR2(24) NOT NULL,
  content CLOB NOT NULL,
  message_type VARCHAR2(40) NOT NULL,
  safe_metadata_json CLOB DEFAULT '{}' NOT NULL CHECK (safe_metadata_json IS JSON),
  created_at TIMESTAMP WITH TIME ZONE NOT NULL
)
-- +YOBI STATEMENT
CREATE TABLE address_ref (
  address_ref_id VARCHAR2(64) PRIMARY KEY,
  session_id VARCHAR2(64) NOT NULL REFERENCES chat_session(session_id),
  source_type VARCHAR2(32) NOT NULL,
  source_image_hash VARCHAR2(64),
  place_id VARCHAR2(64) REFERENCES address_place(place_id),
  hotel_name VARCHAR2(200) NOT NULL,
  road_address VARCHAR2(500) NOT NULL,
  extraction_confidence BINARY_DOUBLE NOT NULL,
  confirmed NUMBER(1) DEFAULT 0 NOT NULL CHECK (confirmed IN (0, 1)),
  created_at TIMESTAMP WITH TIME ZONE NOT NULL
)
-- +YOBI STATEMENT
CREATE TABLE cart (
  cart_id VARCHAR2(64) PRIMARY KEY,
  session_id VARCHAR2(64) UNIQUE NOT NULL REFERENCES chat_session(session_id),
  address_ref_id VARCHAR2(64) REFERENCES address_ref(address_ref_id),
  version NUMBER(10) DEFAULT 1 NOT NULL,
  status VARCHAR2(24) DEFAULT 'ACTIVE' NOT NULL,
  confirmed NUMBER(1) DEFAULT 0 NOT NULL CHECK (confirmed IN (0, 1)),
  created_at TIMESTAMP WITH TIME ZONE NOT NULL,
  updated_at TIMESTAMP WITH TIME ZONE NOT NULL
)
-- +YOBI STATEMENT
CREATE TABLE cart_item (
  cart_item_id VARCHAR2(64) PRIMARY KEY,
  cart_id VARCHAR2(64) NOT NULL REFERENCES cart(cart_id) ON DELETE CASCADE,
  menu_id VARCHAR2(32) NOT NULL REFERENCES menu(menu_id),
  merchant_id VARCHAR2(32) NOT NULL REFERENCES merchant(merchant_id),
  quantity NUMBER(4) NOT NULL,
  unit_price NUMBER(10) NOT NULL,
  menu_snapshot_json CLOB NOT NULL CHECK (menu_snapshot_json IS JSON),
  option_snapshot_json CLOB NOT NULL CHECK (option_snapshot_json IS JSON),
  line_total NUMBER(12) NOT NULL,
  user_note VARCHAR2(500) DEFAULT '' NOT NULL,
  korean_note VARCHAR2(1000) DEFAULT '' NOT NULL,
  created_at TIMESTAMP WITH TIME ZONE NOT NULL
)
-- +YOBI STATEMENT
CREATE TABLE delivery_preference (
  cart_id VARCHAR2(64) PRIMARY KEY REFERENCES cart(cart_id) ON DELETE CASCADE,
  handoff_method VARCHAR2(32) NOT NULL,
  cutlery NUMBER(1) NOT NULL,
  ring_bell NUMBER(1) NOT NULL,
  front_desk NUMBER(1) NOT NULL,
  user_note VARCHAR2(1000) NOT NULL,
  korean_note VARCHAR2(1000) NOT NULL,
  back_translation VARCHAR2(1000) NOT NULL
)
-- +YOBI STATEMENT
CREATE TABLE mock_checkout (
  checkout_id VARCHAR2(64) PRIMARY KEY,
  cart_id VARCHAR2(64) NOT NULL REFERENCES cart(cart_id),
  idempotency_key VARCHAR2(100) UNIQUE NOT NULL,
  payment_method VARCHAR2(40) NOT NULL,
  status VARCHAR2(24) NOT NULL,
  amount NUMBER(12) NOT NULL,
  payment_url VARCHAR2(300) NOT NULL,
  created_at TIMESTAMP WITH TIME ZONE NOT NULL,
  updated_at TIMESTAMP WITH TIME ZONE NOT NULL
)
-- +YOBI STATEMENT
CREATE TABLE mock_order (
  order_id VARCHAR2(80) PRIMARY KEY,
  checkout_id VARCHAR2(64) UNIQUE NOT NULL REFERENCES mock_checkout(checkout_id),
  cart_snapshot_json CLOB NOT NULL CHECK (cart_snapshot_json IS JSON),
  order_status VARCHAR2(32) NOT NULL,
  estimated_delivery_at TIMESTAMP WITH TIME ZONE NOT NULL,
  created_at TIMESTAMP WITH TIME ZONE NOT NULL
)
-- +YOBI STATEMENT
CREATE TABLE audit_log (
  log_id VARCHAR2(64) PRIMARY KEY,
  session_id VARCHAR2(64),
  tool VARCHAR2(120) NOT NULL,
  input_hash VARCHAR2(64) NOT NULL,
  evidence_ids_json CLOB NOT NULL CHECK (evidence_ids_json IS JSON),
  output_status VARCHAR2(40) NOT NULL,
  latency_ms NUMBER(12) NOT NULL,
  fallback_used NUMBER(1) NOT NULL,
  safe_error_code VARCHAR2(120),
  created_at TIMESTAMP WITH TIME ZONE NOT NULL
)
-- +YOBI STATEMENT
CREATE INDEX idx_menu_category ON menu(category, availability, price)
-- +YOBI STATEMENT
CREATE INDEX idx_menu_merchant ON menu(merchant_id)
-- +YOBI STATEMENT
CREATE INDEX idx_evidence_subject ON evidence(subject_id, claim_type)
-- +YOBI STATEMENT
CREATE INDEX idx_review_menu ON review_snippet(menu_id)

