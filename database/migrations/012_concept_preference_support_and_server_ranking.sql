BEGIN
  EXECUTE IMMEDIATE q'^
    CREATE TABLE concept_preference_support (
      knowledge_release_id VARCHAR2(80) NOT NULL,
      concept_id VARCHAR2(80) NOT NULL,
      category_code VARCHAR2(80) NOT NULL,
      option_code VARCHAR2(80) NOT NULL,
      support_status VARCHAR2(24) NOT NULL
        CHECK (support_status IN ('SUPPORTED','UNSUPPORTED','REVIEW_REQUIRED')),
      support_strength BINARY_DOUBLE NOT NULL
        CHECK (support_strength >= 0 AND support_strength <= 1),
      evidence_chunk_id VARCHAR2(128),
      provenance_type VARCHAR2(120) NOT NULL,
      source_ref VARCHAR2(1000) NOT NULL,
      review_status VARCHAR2(32) NOT NULL,
      support_method_version VARCHAR2(80) NOT NULL,
      is_synthetic NUMBER(1) DEFAULT 1 NOT NULL CHECK (is_synthetic IN (0,1)),
      updated_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
      PRIMARY KEY (knowledge_release_id, concept_id, category_code, option_code),
      CONSTRAINT fk_concept_pref_concept FOREIGN KEY (knowledge_release_id, concept_id)
        REFERENCES dish_concept(release_id, concept_id),
      CONSTRAINT fk_concept_pref_chunk FOREIGN KEY (knowledge_release_id, evidence_chunk_id)
        REFERENCES knowledge_chunk(release_id, chunk_id),
      CONSTRAINT chk_concept_pref_evidence CHECK (
        support_status != 'SUPPORTED' OR evidence_chunk_id IS NOT NULL
      )
    )
  ^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^ALTER TABLE recommendation_release_family
    ADD support_manifest_sha256 VARCHAR2(64)
    DEFAULT '0000000000000000000000000000000000000000000000000000000000000000' NOT NULL^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^ALTER TABLE recommendation_release_family
    ADD ranking_policy_version VARCHAR2(80) DEFAULT 'legacy-llm-rank-v2' NOT NULL^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^ALTER TABLE recommendation_release_family
    ADD ranking_policy_sha256 VARCHAR2(64)
    DEFAULT '0000000000000000000000000000000000000000000000000000000000000000' NOT NULL^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^ALTER TABLE structured_recommendation_request
    ADD final_candidates_json CLOB DEFAULT '[]' NOT NULL CHECK (final_candidates_json IS JSON)^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^ALTER TABLE structured_recommendation_request
    ADD ranking_trace_json CLOB DEFAULT '{}' NOT NULL CHECK (ranking_trace_json IS JSON)^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^ALTER TABLE structured_recommendation_request
    ADD ranking_policy_version VARCHAR2(80) DEFAULT 'legacy-llm-rank-v2' NOT NULL^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^ALTER TABLE structured_recommendation_request
    ADD support_manifest_sha256 VARCHAR2(64)
    DEFAULT '0000000000000000000000000000000000000000000000000000000000000000' NOT NULL^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE structured_recommendation_request ADD finalized_at TIMESTAMP WITH TIME ZONE';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^ALTER TABLE recommendation_snapshot
    ADD ranking_trace_json CLOB CHECK (ranking_trace_json IS JSON)^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE recommendation_snapshot ADD ranking_policy_version VARCHAR2(80)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE recommendation_snapshot ADD support_manifest_sha256 VARCHAR2(64)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_concept_pref_lookup ON concept_preference_support(knowledge_release_id, category_code, option_code, support_status, concept_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_concept_pref_concept ON concept_preference_support(knowledge_release_id, concept_id, support_status)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_menu_concept_high ON menu_concept_map(release_id, mapping_status, confidence_band, concept_id, menu_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_menu_recommend_filter ON menu(availability, price, merchant_id, menu_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_menu_source_restrict ON menu_source_detail(liquor, is_adult, verified_adult, soldout, menu_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_rec_request_policy ON structured_recommendation_request(session_id, ranking_policy_version, status, created_at)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
