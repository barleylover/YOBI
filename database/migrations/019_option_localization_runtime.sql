-- +YOBI STATEMENT
-- Additive versioned cache for lazy selected-menu option localization.
-- The legacy localization tables and their existing rows remain untouched.
CREATE TABLE runtime_option_group_localization (
  release_id VARCHAR2(160) NOT NULL REFERENCES synthetic_enrichment_release(release_id),
  option_group_id VARCHAR2(64) NOT NULL REFERENCES menu_option_group(option_group_id),
  language_code VARCHAR2(8) NOT NULL CHECK (language_code IN ('en','ja')),
  prompt_version VARCHAR2(80) NOT NULL,
  display_name VARCHAR2(300) NOT NULL,
  model_id VARCHAR2(120) NOT NULL,
  source_hash VARCHAR2(64) NOT NULL,
  generated_at TIMESTAMP WITH TIME ZONE NOT NULL,
  PRIMARY KEY (release_id,option_group_id,language_code,prompt_version)
)

-- +YOBI STATEMENT
CREATE TABLE runtime_option_item_localization (
  release_id VARCHAR2(160) NOT NULL REFERENCES synthetic_enrichment_release(release_id),
  option_item_id VARCHAR2(80) NOT NULL REFERENCES menu_option_item(option_item_id),
  language_code VARCHAR2(8) NOT NULL CHECK (language_code IN ('en','ja')),
  prompt_version VARCHAR2(80) NOT NULL,
  display_name VARCHAR2(300) NOT NULL,
  model_id VARCHAR2(120) NOT NULL,
  source_hash VARCHAR2(64) NOT NULL,
  generated_at TIMESTAMP WITH TIME ZONE NOT NULL,
  PRIMARY KEY (release_id,option_item_id,language_code,prompt_version)
)

-- +YOBI STATEMENT
CREATE INDEX idx_runtime_option_group_menu
  ON runtime_option_group_localization(release_id,language_code,prompt_version,option_group_id)

-- +YOBI STATEMENT
CREATE INDEX idx_runtime_option_item_menu
  ON runtime_option_item_localization(release_id,language_code,prompt_version,option_item_id)
