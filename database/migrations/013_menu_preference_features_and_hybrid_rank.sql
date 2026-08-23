BEGIN
  EXECUTE IMMEDIATE q'^
    CREATE TABLE menu_preference_feature (
      knowledge_release_id VARCHAR2(80) NOT NULL,
      feature_id VARCHAR2(128) NOT NULL,
      menu_id VARCHAR2(160) NOT NULL,
      category_code VARCHAR2(80) NOT NULL,
      option_code VARCHAR2(80) NOT NULL,
      support_status VARCHAR2(24) NOT NULL
        CHECK (support_status IN ('SUPPORTED','CONTRADICTED','REVIEW_REQUIRED')),
      support_strength BINARY_DOUBLE NOT NULL
        CHECK (support_strength >= 0 AND support_strength <= 1),
      confidence BINARY_DOUBLE NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
      specificity BINARY_DOUBLE NOT NULL CHECK (specificity >= 0 AND specificity <= 1),
      evidence_scope VARCHAR2(32) NOT NULL
        CHECK (evidence_scope IN ('MENU_DIRECT','SECTION_CONTEXT','OPTION_AVAILABILITY','CONCEPT_GENERAL')),
      provenance_type VARCHAR2(120) NOT NULL,
      source_ref VARCHAR2(1000) NOT NULL,
      review_status VARCHAR2(32) NOT NULL,
      extractor_version VARCHAR2(80) NOT NULL,
      is_synthetic NUMBER(1) DEFAULT 1 NOT NULL CHECK (is_synthetic IN (0,1)),
      updated_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
      PRIMARY KEY (knowledge_release_id, feature_id),
      CONSTRAINT uq_menu_pref_feature UNIQUE (
        knowledge_release_id,menu_id,category_code,option_code
      ),
      CONSTRAINT fk_menu_pref_feature_release FOREIGN KEY (knowledge_release_id)
        REFERENCES knowledge_release(release_id),
      CONSTRAINT fk_menu_pref_feature_menu FOREIGN KEY (menu_id) REFERENCES menu(menu_id)
    )
  ^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^
    CREATE TABLE menu_preference_feature_evidence (
      knowledge_release_id VARCHAR2(80) NOT NULL,
      evidence_id VARCHAR2(128) NOT NULL,
      feature_id VARCHAR2(128) NOT NULL,
      evidence_role VARCHAR2(32) NOT NULL
        CHECK (evidence_role IN ('SUPPORT','CONTRADICTION','CONTEXT','OVERRIDDEN_GENERAL')),
      source_type VARCHAR2(40) NOT NULL
        CHECK (source_type IN ('MENU_NAME','MENU_DESCRIPTION','MENU_SECTION','MENU_OPTION','WIKI_CHUNK')),
      excerpt VARCHAR2(2000) NOT NULL,
      excerpt_sha256 VARCHAR2(64) NOT NULL,
      source_ref VARCHAR2(1000) NOT NULL,
      provenance_type VARCHAR2(120) NOT NULL,
      is_synthetic NUMBER(1) DEFAULT 1 NOT NULL CHECK (is_synthetic IN (0,1)),
      updated_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
      PRIMARY KEY (knowledge_release_id, evidence_id),
      CONSTRAINT fk_menu_pref_evidence_feature FOREIGN KEY (knowledge_release_id,feature_id)
        REFERENCES menu_preference_feature(knowledge_release_id,feature_id)
    )
  ^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^
    CREATE TABLE menu_concept_membership (
      knowledge_release_id VARCHAR2(80) NOT NULL,
      menu_id VARCHAR2(160) NOT NULL,
      concept_id VARCHAR2(80) NOT NULL,
      membership_role VARCHAR2(24) NOT NULL
        CHECK (membership_role IN ('PRIMARY','COMPONENT','SECONDARY')),
      confidence BINARY_DOUBLE NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
      provenance_type VARCHAR2(120) NOT NULL,
      source_ref VARCHAR2(1000) NOT NULL,
      review_status VARCHAR2(32) NOT NULL,
      extractor_version VARCHAR2(80) NOT NULL,
      is_synthetic NUMBER(1) DEFAULT 1 NOT NULL CHECK (is_synthetic IN (0,1)),
      updated_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
      PRIMARY KEY (knowledge_release_id,menu_id,concept_id),
      CONSTRAINT fk_menu_concept_membership_release FOREIGN KEY (knowledge_release_id)
        REFERENCES knowledge_release(release_id),
      CONSTRAINT fk_menu_concept_membership_menu FOREIGN KEY (menu_id) REFERENCES menu(menu_id),
      CONSTRAINT fk_menu_concept_membership_concept FOREIGN KEY (knowledge_release_id,concept_id)
        REFERENCES dish_concept(release_id,concept_id)
    )
  ^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^ALTER TABLE recommendation_release_family
    ADD feature_manifest_sha256 VARCHAR2(64)
    DEFAULT '0000000000000000000000000000000000000000000000000000000000000000' NOT NULL^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^ALTER TABLE structured_recommendation_request
    ADD feature_manifest_sha256 VARCHAR2(64)
    DEFAULT '0000000000000000000000000000000000000000000000000000000000000000' NOT NULL^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE recommendation_snapshot ADD feature_manifest_sha256 VARCHAR2(64)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_menu_pref_feature_lookup ON menu_preference_feature(knowledge_release_id,category_code,option_code,support_status,menu_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_menu_pref_feature_menu ON menu_preference_feature(knowledge_release_id,menu_id,support_status)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_menu_pref_evidence_feature ON menu_preference_feature_evidence(knowledge_release_id,feature_id,evidence_role)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_menu_concept_membership_lookup ON menu_concept_membership(knowledge_release_id,concept_id,membership_role,menu_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
