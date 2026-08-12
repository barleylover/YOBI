BEGIN
  FOR item IN (
    SELECT table_name, constraint_name
    FROM user_constraints
    WHERE constraint_type = 'C'
      AND table_name IN ('MENU', 'MENU_CATEGORY')
      AND (
        UPPER(search_condition_vc) LIKE '%SPICE_LEVEL%'
        OR UPPER(search_condition_vc) LIKE '%TYPICAL_SPICE_MIN%'
        OR UPPER(search_condition_vc) LIKE '%TYPICAL_SPICE_MAX%'
      )
  ) LOOP
    EXECUTE IMMEDIATE 'ALTER TABLE ' || item.table_name
      || ' DROP CONSTRAINT ' || item.constraint_name;
  END LOOP;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE menu ADD CONSTRAINT chk_menu_spice_5 CHECK (spice_level BETWEEN 1 AND 5)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -2264 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE menu_category ADD CONSTRAINT chk_category_spice_min_5 CHECK (typical_spice_min BETWEEN 1 AND 5)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -2264 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE menu_category ADD CONSTRAINT chk_category_spice_max_5 CHECK (typical_spice_max BETWEEN 1 AND 5)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -2264 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE recommendation_snapshot ADD structured_request_id VARCHAR2(100)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE recommendation_snapshot ADD criteria_version NUMBER(10)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^ALTER TABLE recommendation_snapshot ADD criteria_json CLOB CHECK (criteria_json IS JSON)^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE recommendation_snapshot ADD criteria_hash VARCHAR2(64)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE recommendation_snapshot ADD recommendation_release_family_id VARCHAR2(160)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^ALTER TABLE recommendation_snapshot ADD evidence_pool_json CLOB DEFAULT '[]' NOT NULL CHECK (evidence_pool_json IS JSON)^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE recommendation_snapshot ADD generation_status VARCHAR2(40)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^ALTER TABLE recommendation_snapshot ADD generation_call_count NUMBER(1) DEFAULT 0 NOT NULL CHECK (generation_call_count BETWEEN 0 AND 1)^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^ALTER TABLE recommendation_snapshot ADD grounding_validation_json CLOB CHECK (grounding_validation_json IS JSON)^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^
    CREATE TABLE recommendation_release_family (
      release_family_id VARCHAR2(160) PRIMARY KEY,
      knowledge_release_id VARCHAR2(80) NOT NULL REFERENCES knowledge_release(release_id),
      catalog_release_id VARCHAR2(160) NOT NULL,
      preference_catalog_version VARCHAR2(160) NOT NULL,
      spice_reference_version VARCHAR2(160) NOT NULL,
      certification_release_id VARCHAR2(160) NOT NULL,
      embedding_model VARCHAR2(120) NOT NULL,
      embedding_version VARCHAR2(80) NOT NULL,
      status VARCHAR2(16) NOT NULL CHECK (status IN ('LOADING','READY','ACTIVE','RETIRED')),
      activated_at TIMESTAMP WITH TIME ZONE
    )
  ^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^
    CREATE TABLE recommendation_runtime_state (
      state_key VARCHAR2(16) PRIMARY KEY CHECK (state_key = 'ACTIVE'),
      active_release_family_id VARCHAR2(160) NOT NULL
        REFERENCES recommendation_release_family(release_family_id),
      updated_at TIMESTAMP WITH TIME ZONE NOT NULL
    )
  ^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^
    CREATE TABLE recommendation_preference_option (
      catalog_version VARCHAR2(160) NOT NULL,
      category_code VARCHAR2(80) NOT NULL,
      option_code VARCHAR2(80) NOT NULL,
      label_ko VARCHAR2(300) NOT NULL,
      label_en VARCHAR2(300) NOT NULL,
      query_aliases_json CLOB NOT NULL CHECK (query_aliases_json IS JSON),
      display_order NUMBER(5) NOT NULL CHECK (display_order >= 0),
      active NUMBER(1) DEFAULT 1 NOT NULL CHECK (active IN (0,1)),
      PRIMARY KEY (catalog_version, category_code, option_code)
    )
  ^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^
    CREATE TABLE spice_reference (
      reference_version VARCHAR2(160) NOT NULL,
      country_code VARCHAR2(2) NOT NULL CHECK (country_code IN ('KR','US')),
      spice_level NUMBER(1) NOT NULL CHECK (spice_level BETWEEN 1 AND 5),
      label_ko VARCHAR2(300) NOT NULL,
      label_en VARCHAR2(300) NOT NULL,
      example_ko VARCHAR2(300) NOT NULL,
      example_en VARCHAR2(300) NOT NULL,
      PRIMARY KEY (reference_version, country_code, spice_level)
    )
  ^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^
    CREATE TABLE merchant_certification (
      certification_id VARCHAR2(160) PRIMARY KEY,
      certification_release_id VARCHAR2(160) NOT NULL,
      merchant_id VARCHAR2(32) NOT NULL REFERENCES merchant(merchant_id),
      certification_type VARCHAR2(16) NOT NULL CHECK (certification_type = 'HALAL'),
      status VARCHAR2(16) NOT NULL CHECK (status IN ('ACTIVE','EXPIRED','REVOKED')),
      issuer VARCHAR2(300) NOT NULL,
      certificate_number VARCHAR2(160) NOT NULL,
      valid_from TIMESTAMP WITH TIME ZONE NOT NULL,
      valid_to TIMESTAMP WITH TIME ZONE,
      scope_type VARCHAR2(16) NOT NULL CHECK (scope_type IN ('MERCHANT','MENU')),
      scope_ref VARCHAR2(160),
      source_type VARCHAR2(80) NOT NULL,
      source_ref VARCHAR2(1000) NOT NULL,
      last_verified_at TIMESTAMP WITH TIME ZONE NOT NULL,
      is_synthetic NUMBER(1) DEFAULT 1 NOT NULL CHECK (is_synthetic IN (0,1)),
      CONSTRAINT chk_halal_cert_scope CHECK (
        (scope_type='MERCHANT' AND scope_ref IS NULL)
        OR (scope_type='MENU' AND scope_ref IS NOT NULL)
      )
    )
  ^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^
    CREATE TABLE session_recommendation_criteria (
      session_id VARCHAR2(64) NOT NULL REFERENCES chat_session(session_id) ON DELETE CASCADE,
      criteria_version NUMBER(10) NOT NULL CHECK (criteria_version >= 1),
      criteria_json CLOB NOT NULL CHECK (criteria_json IS JSON),
      criteria_hash VARCHAR2(64) NOT NULL,
      request_id VARCHAR2(100) NOT NULL,
      state_version NUMBER(10) NOT NULL CHECK (state_version >= 0),
      created_at TIMESTAMP WITH TIME ZONE NOT NULL,
      PRIMARY KEY (session_id, criteria_version),
      CONSTRAINT uq_rec_criteria_request UNIQUE (session_id, request_id)
    )
  ^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^
    CREATE TABLE structured_recommendation_request (
      session_id VARCHAR2(64) NOT NULL REFERENCES chat_session(session_id) ON DELETE CASCADE,
      request_id VARCHAR2(100) NOT NULL,
      request_hash VARCHAR2(160) NOT NULL,
      criteria_version NUMBER(10) NOT NULL,
      recommendation_release_family_id VARCHAR2(160) NOT NULL
        REFERENCES recommendation_release_family(release_family_id),
      eligibility_as_of TIMESTAMP WITH TIME ZONE NOT NULL,
      mode VARCHAR2(16) NOT NULL CHECK (mode IN ('INITIAL','SIMILAR','RETRY')),
      status VARCHAR2(40) NOT NULL CHECK (status IN (
        'CREATED','DISPATCHED','COMPLETED','NO_RESULTS','NO_MATCH',
        'SEARCH_FALLBACK','FAILED','UNKNOWN_AFTER_DISPATCH'
      )),
      state_version NUMBER(10) NOT NULL CHECK (state_version >= 0),
      snapshot_id VARCHAR2(64),
      evidence_pool_json CLOB DEFAULT '[]' NOT NULL CHECK (evidence_pool_json IS JSON),
      result_json CLOB CHECK (result_json IS JSON),
      dispatch_count NUMBER(1) DEFAULT 0 NOT NULL CHECK (dispatch_count BETWEEN 0 AND 1),
      failure_code VARCHAR2(160),
      created_at TIMESTAMP WITH TIME ZONE NOT NULL,
      dispatched_at TIMESTAMP WITH TIME ZONE,
      completed_at TIMESTAMP WITH TIME ZONE,
      PRIMARY KEY (session_id, request_id),
      CONSTRAINT fk_rec_request_criteria FOREIGN KEY (session_id, criteria_version)
        REFERENCES session_recommendation_criteria(session_id, criteria_version)
    )
  ^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_rec_criteria_latest ON session_recommendation_criteria(session_id, criteria_version DESC)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_rec_request_status ON structured_recommendation_request(session_id, status, created_at)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_merchant_cert_active ON merchant_certification(certification_release_id, certification_type, status, merchant_id, valid_from, valid_to)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_preference_option_active ON recommendation_preference_option(catalog_version, category_code, active, display_order)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
