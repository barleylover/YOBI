-- +YOBI STATEMENT
-- Additive runtime localization tables. Existing en/ko/ja release rows and caches remain intact.
BEGIN
  EXECUTE IMMEDIATE q'^
CREATE TABLE runtime_menu_source_description_localization (
  release_id VARCHAR2(160) NOT NULL REFERENCES synthetic_enrichment_release(release_id),
  menu_id VARCHAR2(32) NOT NULL REFERENCES menu(menu_id),
  language_code VARCHAR2(8) NOT NULL CHECK (
    language_code IN (
      'en','ko','ja','zh-CN','zh-TW','es','fr','de','it','pt','th','vi','id','ar','hi','ru'
    )
  ),
  prompt_version VARCHAR2(80) NOT NULL,
  description_text CLOB NOT NULL,
  model_id VARCHAR2(120) NOT NULL,
  source_hash VARCHAR2(64) NOT NULL,
  validation_status VARCHAR2(16) NOT NULL CHECK (validation_status = 'VALID'),
  generated_at TIMESTAMP WITH TIME ZONE NOT NULL,
  PRIMARY KEY (release_id,menu_id,language_code,prompt_version)
)^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^
CREATE TABLE country_aware_menu_presentation_cache (
  cache_key VARCHAR2(128) PRIMARY KEY,
  release_id VARCHAR2(160) NOT NULL REFERENCES synthetic_enrichment_release(release_id),
  menu_id VARCHAR2(32) NOT NULL REFERENCES menu(menu_id),
  language_code VARCHAR2(8) NOT NULL CHECK (
    language_code IN (
      'en','ko','ja','zh-CN','zh-TW','es','fr','de','it','pt','th','vi','id','ar','hi','ru'
    )
  ),
  user_country_code VARCHAR2(2) NOT NULL,
  spice_reference_country_code VARCHAR2(2) NOT NULL,
  localized_subtitle VARCHAR2(500) NOT NULL,
  short_explanation CLOB NOT NULL,
  long_explanation CLOB NOT NULL,
  review_summary CLOB NOT NULL,
  evidence_ids_json CLOB DEFAULT '[]' NOT NULL CHECK (evidence_ids_json IS JSON),
  review_ids_json CLOB DEFAULT '[]' NOT NULL CHECK (review_ids_json IS JSON),
  evidence_map_json CLOB DEFAULT '{}' NOT NULL CHECK (evidence_map_json IS JSON),
  model_id VARCHAR2(120) NOT NULL,
  prompt_version VARCHAR2(80) NOT NULL,
  content_schema_version VARCHAR2(40) NOT NULL,
  source_hash VARCHAR2(64) NOT NULL,
  personalization_applied NUMBER(1) DEFAULT 0 NOT NULL CHECK (personalization_applied IN (0,1)),
  created_at TIMESTAMP WITH TIME ZONE NOT NULL,
  updated_at TIMESTAMP WITH TIME ZONE NOT NULL
)^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_runtime_menu_source_locale ON runtime_menu_source_description_localization(release_id,language_code,menu_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-955,-1408) THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_country_aware_presentation_lookup ON country_aware_menu_presentation_cache(release_id,menu_id,language_code,user_country_code,spice_reference_country_code)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-955,-1408) THEN RAISE; END IF;
END;
