BEGIN
  EXECUTE IMMEDIATE q'^
CREATE TABLE menu_source_description_localization (
  release_id VARCHAR2(160) NOT NULL REFERENCES synthetic_enrichment_release(release_id),
  menu_id VARCHAR2(32) NOT NULL REFERENCES menu(menu_id),
  language_code VARCHAR2(8) NOT NULL CHECK (language_code IN ('ko','en','ja')),
  description_text CLOB NOT NULL,
  model_id VARCHAR2(120) NOT NULL,
  prompt_version VARCHAR2(80) NOT NULL,
  source_hash VARCHAR2(64) NOT NULL,
  validation_status VARCHAR2(16) NOT NULL CHECK (validation_status IN ('VALID','REJECTED')),
  generated_at TIMESTAMP WITH TIME ZONE NOT NULL,
  PRIMARY KEY (release_id,menu_id,language_code)
)^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^
CREATE TABLE synthetic_country_spice_example (
  release_id VARCHAR2(160) NOT NULL,
  country_code VARCHAR2(2) NOT NULL,
  language_code VARCHAR2(8) NOT NULL CHECK (language_code IN ('ko','en','ja')),
  representative_dish VARCHAR2(300) NOT NULL,
  spice_baseline NUMBER(1) NOT NULL CHECK (spice_baseline BETWEEN 1 AND 5),
  source_type VARCHAR2(80) DEFAULT 'SYNTHETIC_DEMO' NOT NULL,
  seed_hash VARCHAR2(64) NOT NULL,
  generated_at TIMESTAMP WITH TIME ZONE NOT NULL,
  PRIMARY KEY (release_id,country_code,language_code),
  FOREIGN KEY (release_id,country_code)
    REFERENCES synthetic_country_profile(release_id,country_code)
)^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE menu_presentation_cache ADD localized_subtitle VARCHAR2(500)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE menu_presentation_cache ADD prompt_version VARCHAR2(80)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE menu_presentation_cache ADD content_schema_version VARCHAR2(40)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE menu_presentation_cache ADD evidence_map_json CLOB';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE menu_presentation_cache ADD personalization_applied NUMBER(1)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE menu_presentation_cache ADD updated_at TIMESTAMP WITH TIME ZONE';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^
CREATE TABLE menu_presentation_generation_lease (
  cache_key VARCHAR2(128) PRIMARY KEY,
  owner_token VARCHAR2(80) NOT NULL,
  status VARCHAR2(16) NOT NULL CHECK (status IN ('GENERATING','FAILED')),
  expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
  retry_after TIMESTAMP WITH TIME ZONE,
  attempt_count NUMBER(6) DEFAULT 1 NOT NULL CHECK (attempt_count > 0),
  error_code VARCHAR2(160),
  created_at TIMESTAMP WITH TIME ZONE NOT NULL,
  updated_at TIMESTAMP WITH TIME ZONE NOT NULL
)^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_menu_source_description_lookup ON menu_source_description_localization(release_id,language_code,menu_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-955,-1408) THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_country_spice_example_lookup ON synthetic_country_spice_example(release_id,country_code,language_code)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-955,-1408) THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_menu_presentation_lease_expiry ON menu_presentation_generation_lease(status,expires_at)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-955,-1408) THEN RAISE; END IF;
END;
