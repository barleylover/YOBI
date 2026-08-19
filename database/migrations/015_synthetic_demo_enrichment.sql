CREATE TABLE synthetic_enrichment_release (
  release_id VARCHAR2(160) PRIMARY KEY,
  catalog_release_id VARCHAR2(160) NOT NULL,
  knowledge_release_id VARCHAR2(80) NOT NULL REFERENCES knowledge_release(release_id),
  seed_value VARCHAR2(160) NOT NULL,
  generator_version VARCHAR2(80) NOT NULL,
  manifest_sha256 VARCHAR2(64) NOT NULL,
  status VARCHAR2(16) NOT NULL CHECK (status IN ('LOADING','READY','ACTIVE','RETIRED')),
  created_at TIMESTAMP WITH TIME ZONE NOT NULL,
  activated_at TIMESTAMP WITH TIME ZONE
)
-- +YOBI STATEMENT
CREATE TABLE synthetic_enrichment_runtime_state (
  state_key VARCHAR2(16) PRIMARY KEY CHECK (state_key = 'ACTIVE'),
  active_release_id VARCHAR2(160) NOT NULL REFERENCES synthetic_enrichment_release(release_id),
  updated_at TIMESTAMP WITH TIME ZONE NOT NULL
)
-- +YOBI STATEMENT
CREATE TABLE synthetic_country_profile (
  release_id VARCHAR2(160) NOT NULL REFERENCES synthetic_enrichment_release(release_id),
  country_code VARCHAR2(2) NOT NULL,
  spice_baseline NUMBER(1) NOT NULL CHECK (spice_baseline BETWEEN 1 AND 5),
  affinity_score NUMBER(5,4) NOT NULL CHECK (affinity_score BETWEEN 0 AND 1),
  affinity_json CLOB DEFAULT '{}' NOT NULL CHECK (affinity_json IS JSON),
  PRIMARY KEY (release_id, country_code)
)
-- +YOBI STATEMENT
CREATE TABLE synthetic_menu_profile (
  release_id VARCHAR2(160) NOT NULL REFERENCES synthetic_enrichment_release(release_id),
  menu_id VARCHAR2(32) NOT NULL REFERENCES menu(menu_id),
  spice_level NUMBER(1) NOT NULL CHECK (spice_level BETWEEN 1 AND 5),
  halal_fit NUMBER(1) NOT NULL CHECK (halal_fit IN (0,1)),
  vegan_fit NUMBER(1) NOT NULL CHECK (vegan_fit IN (0,1)),
  source_type VARCHAR2(80) DEFAULT 'SYNTHETIC_DEMO' NOT NULL,
  generator_version VARCHAR2(80) NOT NULL,
  seed_hash VARCHAR2(64) NOT NULL,
  PRIMARY KEY (release_id, menu_id)
)
-- +YOBI STATEMENT
CREATE TABLE synthetic_option_profile (
  release_id VARCHAR2(160) NOT NULL REFERENCES synthetic_enrichment_release(release_id),
  option_item_id VARCHAR2(80) NOT NULL REFERENCES menu_option_item(option_item_id),
  halal_conflict NUMBER(1) NOT NULL CHECK (halal_conflict IN (0,1)),
  vegan_conflict NUMBER(1) NOT NULL CHECK (vegan_conflict IN (0,1)),
  source_type VARCHAR2(80) DEFAULT 'SYNTHETIC_DEMO' NOT NULL,
  seed_hash VARCHAR2(64) NOT NULL,
  PRIMARY KEY (release_id, option_item_id)
)
-- +YOBI STATEMENT
CREATE TABLE synthetic_menu_country_preference (
  release_id VARCHAR2(160) NOT NULL REFERENCES synthetic_enrichment_release(release_id),
  menu_id VARCHAR2(32) NOT NULL REFERENCES menu(menu_id),
  country_code VARCHAR2(2) NOT NULL,
  preference_percent NUMBER(3) NOT NULL CHECK (preference_percent BETWEEN 0 AND 100),
  sample_size NUMBER(8) NOT NULL CHECK (sample_size > 0),
  PRIMARY KEY (release_id, menu_id, country_code),
  FOREIGN KEY (release_id, country_code)
    REFERENCES synthetic_country_profile(release_id, country_code)
)
-- +YOBI STATEMENT
CREATE TABLE synthetic_review_snippet (
  review_id VARCHAR2(100) PRIMARY KEY,
  release_id VARCHAR2(160) NOT NULL REFERENCES synthetic_enrichment_release(release_id),
  menu_id VARCHAR2(32) NOT NULL REFERENCES menu(menu_id),
  topic VARCHAR2(32) NOT NULL CHECK (topic IN ('TASTE','TEXTURE','VALUE','PACKAGING','CAVEAT')),
  rating NUMBER(1) NOT NULL CHECK (rating BETWEEN 1 AND 5),
  review_text VARCHAR2(2000) NOT NULL,
  source_type VARCHAR2(80) DEFAULT 'SYNTHETIC_DEMO' NOT NULL,
  display_order NUMBER(3) NOT NULL CHECK (display_order >= 0),
  seed_hash VARCHAR2(64) NOT NULL
)
-- +YOBI STATEMENT
CREATE TABLE menu_localization (
  release_id VARCHAR2(160) NOT NULL REFERENCES synthetic_enrichment_release(release_id),
  menu_id VARCHAR2(32) NOT NULL REFERENCES menu(menu_id),
  language_code VARCHAR2(8) NOT NULL CHECK (language_code IN ('ko','en','ja')),
  display_name VARCHAR2(300) NOT NULL,
  model_id VARCHAR2(120) NOT NULL,
  prompt_version VARCHAR2(80) NOT NULL,
  wiki_evidence_ids_json CLOB DEFAULT '[]' NOT NULL CHECK (wiki_evidence_ids_json IS JSON),
  source_hash VARCHAR2(64) NOT NULL,
  validation_status VARCHAR2(16) NOT NULL CHECK (validation_status IN ('VALID','REJECTED')),
  generated_at TIMESTAMP WITH TIME ZONE NOT NULL,
  PRIMARY KEY (release_id, menu_id, language_code)
)
-- +YOBI STATEMENT
CREATE TABLE option_group_localization (
  release_id VARCHAR2(160) NOT NULL REFERENCES synthetic_enrichment_release(release_id),
  option_group_id VARCHAR2(64) NOT NULL REFERENCES menu_option_group(option_group_id),
  language_code VARCHAR2(8) NOT NULL CHECK (language_code IN ('ko','en','ja')),
  display_name VARCHAR2(300) NOT NULL,
  model_id VARCHAR2(120) NOT NULL,
  source_hash VARCHAR2(64) NOT NULL,
  generated_at TIMESTAMP WITH TIME ZONE NOT NULL,
  PRIMARY KEY (release_id, option_group_id, language_code)
)
-- +YOBI STATEMENT
CREATE TABLE option_item_localization (
  release_id VARCHAR2(160) NOT NULL REFERENCES synthetic_enrichment_release(release_id),
  option_item_id VARCHAR2(80) NOT NULL REFERENCES menu_option_item(option_item_id),
  language_code VARCHAR2(8) NOT NULL CHECK (language_code IN ('ko','en','ja')),
  display_name VARCHAR2(300) NOT NULL,
  model_id VARCHAR2(120) NOT NULL,
  source_hash VARCHAR2(64) NOT NULL,
  generated_at TIMESTAMP WITH TIME ZONE NOT NULL,
  PRIMARY KEY (release_id, option_item_id, language_code)
)
-- +YOBI STATEMENT
CREATE TABLE menu_presentation_cache (
  cache_key VARCHAR2(128) PRIMARY KEY,
  release_id VARCHAR2(160) NOT NULL REFERENCES synthetic_enrichment_release(release_id),
  menu_id VARCHAR2(32) NOT NULL REFERENCES menu(menu_id),
  language_code VARCHAR2(8) NOT NULL CHECK (language_code IN ('ko','en','ja')),
  country_code VARCHAR2(2) NOT NULL,
  localized_title VARCHAR2(300) NOT NULL,
  short_explanation CLOB NOT NULL,
  long_explanation CLOB NOT NULL,
  review_summary CLOB NOT NULL,
  evidence_ids_json CLOB DEFAULT '[]' NOT NULL CHECK (evidence_ids_json IS JSON),
  review_ids_json CLOB DEFAULT '[]' NOT NULL CHECK (review_ids_json IS JSON),
  model_id VARCHAR2(120) NOT NULL,
  source_hash VARCHAR2(64) NOT NULL,
  created_at TIMESTAMP WITH TIME ZONE NOT NULL
)
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE recommendation_release_family ADD synthetic_enrichment_release_id VARCHAR2(160)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE recommendation_release_family ADD CONSTRAINT fk_rec_family_synthetic_release FOREIGN KEY (synthetic_enrichment_release_id) REFERENCES synthetic_enrichment_release(release_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-2264, -2275) THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
CREATE INDEX idx_synthetic_menu_profile_fit
  ON synthetic_menu_profile(release_id, halal_fit, vegan_fit, spice_level, menu_id)
-- +YOBI STATEMENT
CREATE INDEX idx_synthetic_country_menu
  ON synthetic_menu_country_preference(release_id, country_code, menu_id)
-- +YOBI STATEMENT
CREATE INDEX idx_synthetic_review_menu
  ON synthetic_review_snippet(release_id, menu_id, display_order)
-- +YOBI STATEMENT
CREATE INDEX idx_menu_localization_lookup
  ON menu_localization(release_id, language_code, menu_id)
-- +YOBI STATEMENT
CREATE INDEX idx_menu_presentation_lookup
  ON menu_presentation_cache(release_id, menu_id, language_code, country_code)
