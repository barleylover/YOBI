BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE knowledge_release (
      release_id VARCHAR2(80) PRIMARY KEY,
      catalog_version VARCHAR2(80) NOT NULL,
      manifest_sha256 VARCHAR2(64) NOT NULL,
      embedding_model VARCHAR2(120) NOT NULL,
      embedding_dimension NUMBER(5) NOT NULL CHECK (embedding_dimension = 1536),
      embedding_version VARCHAR2(80) NOT NULL,
      status VARCHAR2(16) NOT NULL CHECK (status IN ('LOADING','READY','FAILED','RETIRED')),
      expected_counts_json CLOB NOT NULL CHECK (expected_counts_json IS JSON),
      actual_counts_json CLOB NOT NULL CHECK (actual_counts_json IS JSON),
      is_synthetic NUMBER(1) DEFAULT 1 NOT NULL CHECK (is_synthetic IN (0,1)),
      created_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
      completed_at TIMESTAMP WITH TIME ZONE
    )
  ]';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE dish_concept (
      release_id VARCHAR2(80) NOT NULL REFERENCES knowledge_release(release_id),
      concept_id VARCHAR2(80) NOT NULL,
      concept_type VARCHAR2(24) NOT NULL CHECK (concept_type IN ('CUISINE','FAMILY','VARIANT')),
      canonical_name_ko VARCHAR2(200) NOT NULL,
      canonical_name_en VARCHAR2(200) NOT NULL,
      aliases_json CLOB DEFAULT '[]' NOT NULL CHECK (aliases_json IS JSON),
      source_type VARCHAR2(120) NOT NULL,
      source_ref VARCHAR2(1000) NOT NULL,
      review_status VARCHAR2(32) NOT NULL,
      is_synthetic NUMBER(1) DEFAULT 1 NOT NULL CHECK (is_synthetic IN (0,1)),
      updated_at VARCHAR2(32) NOT NULL,
      PRIMARY KEY (release_id, concept_id)
    )
  ]';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE dish_relation (
      release_id VARCHAR2(80) NOT NULL,
      relation_id VARCHAR2(128) NOT NULL,
      source_concept_id VARCHAR2(80) NOT NULL,
      target_concept_id VARCHAR2(80) NOT NULL,
      relation_type VARCHAR2(24) NOT NULL CHECK (relation_type IN ('IS_A','VARIANT_OF','SIMILAR_TO')),
      inherit_claims NUMBER(1) DEFAULT 1 NOT NULL CHECK (inherit_claims IN (0,1)),
      source_ref VARCHAR2(1000) NOT NULL,
      is_synthetic NUMBER(1) DEFAULT 1 NOT NULL CHECK (is_synthetic IN (0,1)),
      updated_at VARCHAR2(32) NOT NULL,
      PRIMARY KEY (release_id, relation_id),
      CONSTRAINT fk_dish_relation_source FOREIGN KEY (release_id, source_concept_id)
        REFERENCES dish_concept(release_id, concept_id),
      CONSTRAINT fk_dish_relation_target FOREIGN KEY (release_id, target_concept_id)
        REFERENCES dish_concept(release_id, concept_id)
    )
  ]';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE dish_concept_closure (
      release_id VARCHAR2(80) NOT NULL,
      descendant_concept_id VARCHAR2(80) NOT NULL,
      ancestor_concept_id VARCHAR2(80) NOT NULL,
      depth NUMBER(4) NOT NULL CHECK (depth >= 0),
      inherit_claims NUMBER(1) DEFAULT 1 NOT NULL CHECK (inherit_claims IN (0,1)),
      PRIMARY KEY (release_id, descendant_concept_id, ancestor_concept_id),
      CONSTRAINT fk_dish_closure_desc FOREIGN KEY (release_id, descendant_concept_id)
        REFERENCES dish_concept(release_id, concept_id),
      CONSTRAINT fk_dish_closure_anc FOREIGN KEY (release_id, ancestor_concept_id)
        REFERENCES dish_concept(release_id, concept_id)
    )
  ]';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE concept_claim (
      release_id VARCHAR2(80) NOT NULL,
      claim_id VARCHAR2(128) NOT NULL,
      concept_id VARCHAR2(80) NOT NULL,
      claim_type VARCHAR2(24) NOT NULL CHECK (claim_type IN ('INGREDIENT','ALLERGEN','DIETARY','FACET','PREPARATION')),
      ingredient_id VARCHAR2(160) REFERENCES ingredient(ingredient_id),
      allergen_id VARCHAR2(160) REFERENCES allergen(allergen_id),
      attribute_id VARCHAR2(160) REFERENCES dietary_attribute(attribute_id),
      facet_key VARCHAR2(40),
      value_text VARCHAR2(2000),
      ingredient_role VARCHAR2(24) CHECK (ingredient_role IN ('DEFINING','CORE','COMMON','OPTIONAL','REGIONAL_VARIANT','UNKNOWN')),
      assertion_status VARCHAR2(32) NOT NULL CHECK (assertion_status IN ('PRESUMED_PRESENT','POSSIBLE','UNKNOWN','CONFLICTING')),
      inheritance_mode VARCHAR2(16) DEFAULT 'INHERIT' NOT NULL CHECK (inheritance_mode IN ('INHERIT','LOCAL_ONLY')),
      source_ref VARCHAR2(1000) NOT NULL,
      review_status VARCHAR2(32) NOT NULL,
      is_synthetic NUMBER(1) DEFAULT 1 NOT NULL CHECK (is_synthetic IN (0,1)),
      updated_at VARCHAR2(32) NOT NULL,
      PRIMARY KEY (release_id, claim_id),
      CONSTRAINT fk_concept_claim_concept FOREIGN KEY (release_id, concept_id)
        REFERENCES dish_concept(release_id, concept_id),
      CONSTRAINT chk_concept_claim_target CHECK (
        (claim_type = 'INGREDIENT' AND ingredient_id IS NOT NULL AND ingredient_role IS NOT NULL)
        OR (claim_type = 'ALLERGEN' AND allergen_id IS NOT NULL)
        OR (claim_type = 'DIETARY' AND attribute_id IS NOT NULL)
        OR (claim_type IN ('FACET','PREPARATION') AND facet_key IS NOT NULL AND value_text IS NOT NULL)
      )
    )
  ]';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE knowledge_document (
      release_id VARCHAR2(80) NOT NULL,
      document_id VARCHAR2(128) NOT NULL,
      concept_id VARCHAR2(80) NOT NULL,
      language VARCHAR2(16) NOT NULL,
      title VARCHAR2(300) NOT NULL,
      source_path VARCHAR2(1000) NOT NULL,
      front_matter_json CLOB NOT NULL CHECK (front_matter_json IS JSON),
      content_markdown CLOB NOT NULL,
      content_sha256 VARCHAR2(64) NOT NULL,
      source_type VARCHAR2(120) NOT NULL,
      source_ref VARCHAR2(1000) NOT NULL,
      license_state VARCHAR2(80) NOT NULL,
      review_status VARCHAR2(32) NOT NULL,
      is_synthetic NUMBER(1) DEFAULT 1 NOT NULL CHECK (is_synthetic IN (0,1)),
      updated_at VARCHAR2(32) NOT NULL,
      PRIMARY KEY (release_id, document_id),
      CONSTRAINT fk_knowledge_doc_concept FOREIGN KEY (release_id, concept_id)
        REFERENCES dish_concept(release_id, concept_id),
      CONSTRAINT uq_knowledge_doc_path UNIQUE (release_id, source_path)
    )
  ]';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE knowledge_chunk (
      release_id VARCHAR2(80) NOT NULL,
      chunk_id VARCHAR2(128) NOT NULL,
      document_id VARCHAR2(128) NOT NULL,
      concept_id VARCHAR2(80) NOT NULL,
      language VARCHAR2(16) NOT NULL,
      facet VARCHAR2(40) NOT NULL,
      chunk_index NUMBER(5) NOT NULL,
      content CLOB NOT NULL,
      content_sha256 VARCHAR2(64) NOT NULL,
      metadata_json CLOB DEFAULT '{}' NOT NULL CHECK (metadata_json IS JSON),
      embedding_text CLOB NOT NULL,
      embedding_vector VECTOR(1536, FLOAT32),
      embedding_model VARCHAR2(120) NOT NULL,
      embedding_dimension NUMBER(5) NOT NULL CHECK (embedding_dimension = 1536),
      embedding_version VARCHAR2(80) NOT NULL,
      is_synthetic NUMBER(1) DEFAULT 1 NOT NULL CHECK (is_synthetic IN (0,1)),
      updated_at VARCHAR2(32) NOT NULL,
      PRIMARY KEY (release_id, chunk_id),
      CONSTRAINT fk_knowledge_chunk_doc FOREIGN KEY (release_id, document_id)
        REFERENCES knowledge_document(release_id, document_id),
      CONSTRAINT fk_knowledge_chunk_concept FOREIGN KEY (release_id, concept_id)
        REFERENCES dish_concept(release_id, concept_id),
      CONSTRAINT uq_knowledge_chunk_pos UNIQUE (release_id, document_id, chunk_index)
    )
  ]';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE menu_concept_map (
      release_id VARCHAR2(80) NOT NULL REFERENCES knowledge_release(release_id),
      menu_id VARCHAR2(32) NOT NULL REFERENCES menu(menu_id),
      concept_id VARCHAR2(80),
      mapping_status VARCHAR2(16) NOT NULL CHECK (mapping_status IN ('MAPPED','UNMAPPED')),
      mapping_type VARCHAR2(16) NOT NULL CHECK (mapping_type IN ('EXACT','VARIANT','FAMILY','UNMAPPED')),
      unmapped_reason VARCHAR2(1000),
      confidence_band VARCHAR2(16) NOT NULL CHECK (confidence_band IN ('high','medium','low')),
      source_type VARCHAR2(120) NOT NULL,
      source_ref VARCHAR2(1000) NOT NULL,
      review_status VARCHAR2(32) NOT NULL,
      is_synthetic NUMBER(1) DEFAULT 1 NOT NULL CHECK (is_synthetic IN (0,1)),
      updated_at VARCHAR2(32) NOT NULL,
      PRIMARY KEY (release_id, menu_id),
      CONSTRAINT fk_menu_map_concept FOREIGN KEY (release_id, concept_id)
        REFERENCES dish_concept(release_id, concept_id),
      CONSTRAINT chk_menu_map_state CHECK (
        (mapping_status = 'MAPPED' AND concept_id IS NOT NULL AND mapping_type != 'UNMAPPED' AND unmapped_reason IS NULL)
        OR (mapping_status = 'UNMAPPED' AND concept_id IS NULL AND mapping_type = 'UNMAPPED' AND unmapped_reason IS NOT NULL)
      )
    )
  ]';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE merchant_origin_declaration (
      release_id VARCHAR2(80) NOT NULL REFERENCES knowledge_release(release_id),
      declaration_id VARCHAR2(128) NOT NULL,
      merchant_id VARCHAR2(32) NOT NULL REFERENCES merchant(merchant_id),
      language VARCHAR2(16) NOT NULL,
      raw_text CLOB NOT NULL,
      content_sha256 VARCHAR2(64) NOT NULL,
      source_type VARCHAR2(120) NOT NULL,
      source_ref VARCHAR2(1000) NOT NULL,
      source_version VARCHAR2(80) NOT NULL,
      review_status VARCHAR2(32) NOT NULL,
      is_synthetic NUMBER(1) DEFAULT 1 NOT NULL CHECK (is_synthetic IN (0,1)),
      valid_from VARCHAR2(32),
      valid_to VARCHAR2(32),
      updated_at VARCHAR2(32) NOT NULL,
      PRIMARY KEY (release_id, declaration_id)
    )
  ]';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE merchant_ingredient (
      release_id VARCHAR2(80) NOT NULL,
      merchant_id VARCHAR2(32) NOT NULL REFERENCES merchant(merchant_id),
      ingredient_id VARCHAR2(160) NOT NULL REFERENCES ingredient(ingredient_id),
      declaration_id VARCHAR2(128) NOT NULL,
      status VARCHAR2(32) NOT NULL CHECK (status IN ('CONFIRMED_PRESENT','POSSIBLE','UNKNOWN','CONFLICTING')),
      origin_text VARCHAR2(500),
      source_ref VARCHAR2(1000) NOT NULL,
      is_synthetic NUMBER(1) DEFAULT 1 NOT NULL CHECK (is_synthetic IN (0,1)),
      updated_at VARCHAR2(32) NOT NULL,
      PRIMARY KEY (release_id, merchant_id, ingredient_id, declaration_id),
      CONSTRAINT fk_merchant_ing_origin FOREIGN KEY (release_id, declaration_id)
        REFERENCES merchant_origin_declaration(release_id, declaration_id)
    )
  ]';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE option_ingredient_effect (
      release_id VARCHAR2(80) NOT NULL REFERENCES knowledge_release(release_id),
      option_item_id VARCHAR2(80) NOT NULL REFERENCES menu_option_item(option_item_id),
      ingredient_id VARCHAR2(160) NOT NULL REFERENCES ingredient(ingredient_id),
      effect VARCHAR2(12) NOT NULL CHECK (effect IN ('ADD','REMOVE')),
      assertion_status VARCHAR2(32) NOT NULL CHECK (assertion_status IN ('CONFIRMED_PRESENT','CONFIRMED_ABSENT','POSSIBLE','UNKNOWN')),
      source_ref VARCHAR2(1000) NOT NULL,
      is_synthetic NUMBER(1) DEFAULT 1 NOT NULL CHECK (is_synthetic IN (0,1)),
      updated_at VARCHAR2(32) NOT NULL,
      PRIMARY KEY (release_id, option_item_id, ingredient_id, effect)
    )
  ]';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE knowledge_runtime_state (
      state_key VARCHAR2(32) PRIMARY KEY,
      active_release_id VARCHAR2(80) NOT NULL REFERENCES knowledge_release(release_id),
      updated_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
      CONSTRAINT chk_knowledge_state_key CHECK (state_key = 'ACTIVE')
    )
  ]';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_concept_claim_lookup ON concept_claim(release_id, concept_id, claim_type)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_knowledge_chunk_lookup ON knowledge_chunk(release_id, concept_id, facet)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_menu_concept_lookup ON menu_concept_map(release_id, concept_id, mapping_status)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
