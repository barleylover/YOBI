-- Wiki eligibility is evaluated before the bounded candidate union. Materialize
-- public Wiki passages -> inherited concepts -> menus once per immutable release
-- so runtime queries do not repeatedly parse passage metadata JSON.

BEGIN
  EXECUTE IMMEDIATE q'^
    CREATE TABLE menu_wiki_eligibility (
      knowledge_release_id VARCHAR2(80) NOT NULL,
      menu_id VARCHAR2(160) NOT NULL,
      reviewed_chunk_count NUMBER(10) NOT NULL,
      compiled_at TIMESTAMP WITH TIME ZONE NOT NULL,
      CONSTRAINT pk_menu_wiki_eligibility PRIMARY KEY (knowledge_release_id,menu_id),
      CONSTRAINT fk_menu_wiki_release FOREIGN KEY (knowledge_release_id)
        REFERENCES knowledge_release(release_id),
      CONSTRAINT fk_menu_wiki_menu FOREIGN KEY (menu_id) REFERENCES menu(menu_id),
      CONSTRAINT ck_menu_wiki_chunk_count CHECK (reviewed_chunk_count > 0)
    )^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^
    CREATE TABLE menu_semantic_embedding (
      catalog_release_id VARCHAR2(160) NOT NULL,
      menu_id VARCHAR2(160) NOT NULL,
      embedding_model VARCHAR2(120) NOT NULL,
      embedding_version VARCHAR2(80) NOT NULL,
      embedding_dimension NUMBER(5) NOT NULL,
      semantic_text_sha256 VARCHAR2(64) NOT NULL,
      embedding_manifest_sha256 VARCHAR2(64) NOT NULL,
      embedding_vector VECTOR(1536, FLOAT32) NOT NULL,
      created_at TIMESTAMP WITH TIME ZONE NOT NULL,
      CONSTRAINT pk_menu_semantic_embedding PRIMARY KEY (
        catalog_release_id,menu_id,embedding_model,embedding_version
      ),
      CONSTRAINT fk_menu_semantic_menu FOREIGN KEY (menu_id) REFERENCES menu(menu_id),
      CONSTRAINT ck_menu_semantic_dimension CHECK (embedding_dimension=1536),
      CONSTRAINT ck_menu_semantic_text_hash CHECK (LENGTH(semantic_text_sha256)=64),
      CONSTRAINT ck_menu_semantic_manifest_hash CHECK (LENGTH(embedding_manifest_sha256)=64)
    )^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
INSERT INTO menu_wiki_eligibility (
  knowledge_release_id,menu_id,reviewed_chunk_count,compiled_at
)
SELECT reviewed.release_id,membership.menu_id,
       COUNT(DISTINCT reviewed.chunk_id),SYSTIMESTAMP
FROM (
  SELECT chunk.release_id,chunk.chunk_id,closure.descendant_concept_id
  FROM knowledge_chunk chunk
  JOIN knowledge_document document
    ON document.release_id=chunk.release_id
   AND document.document_id=chunk.document_id
  JOIN dish_concept_closure closure
    ON closure.release_id=chunk.release_id
   AND closure.ancestor_concept_id=chunk.concept_id
   AND closure.inherit_claims=1
  WHERE document.source_type='SYNTHETIC_WIKI'
    AND document.review_status='REVIEWED_DEMO'
    AND LOWER(chunk.facet)<>'safety'
    AND (
      JSON_VALUE(chunk.metadata_json,'$.recommendation_visibility')='PUBLIC_RAG'
      OR JSON_VALUE(chunk.metadata_json,'$.recommendation_visibility') IS NULL
    )
) reviewed
JOIN menu_concept_membership membership
  ON membership.knowledge_release_id=reviewed.release_id
 AND membership.concept_id=reviewed.descendant_concept_id
LEFT JOIN menu_wiki_eligibility existing
  ON existing.knowledge_release_id=reviewed.release_id
 AND existing.menu_id=membership.menu_id
WHERE existing.menu_id IS NULL
GROUP BY reviewed.release_id,membership.menu_id
-- +YOBI STATEMENT

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_dish_closure_ancestor ON dish_concept_closure(release_id,ancestor_concept_id,inherit_claims,descendant_concept_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_menu_concept_membership_concept ON menu_concept_membership(knowledge_release_id,concept_id,menu_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_menu_wiki_eligibility_menu ON menu_wiki_eligibility(menu_id,knowledge_release_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_menu_semantic_identity ON menu_semantic_embedding(catalog_release_id,embedding_model,embedding_version,embedding_dimension,menu_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
