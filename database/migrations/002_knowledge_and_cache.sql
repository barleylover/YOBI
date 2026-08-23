CREATE TABLE menu_knowledge (
  knowledge_id VARCHAR2(64) PRIMARY KEY,
  menu_id VARCHAR2(32) NOT NULL REFERENCES menu(menu_id),
  knowledge_type VARCHAR2(80) NOT NULL,
  language VARCHAR2(16) DEFAULT 'en' NOT NULL,
  content CLOB NOT NULL,
  source_type VARCHAR2(120) NOT NULL,
  source_ref VARCHAR2(500),
  license_state VARCHAR2(80) DEFAULT 'SYNTHETIC' NOT NULL,
  embedding_text CLOB NOT NULL,
  embedding_vector VECTOR(1536, FLOAT32),
  embedding_model VARCHAR2(120),
  embedding_dimension NUMBER(5),
  embedding_version VARCHAR2(80),
  updated_at VARCHAR2(32) NOT NULL
)
-- +YOBI STATEMENT
CREATE TABLE explanation_cache (
  cache_key VARCHAR2(128) PRIMARY KEY,
  menu_id VARCHAR2(32) NOT NULL REFERENCES menu(menu_id),
  language VARCHAR2(16) NOT NULL,
  profile_signature VARCHAR2(64) NOT NULL,
  explanation_json CLOB NOT NULL CHECK (explanation_json IS JSON),
  source_version VARCHAR2(80) NOT NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL
)
-- +YOBI STATEMENT
CREATE INDEX idx_knowledge_menu ON menu_knowledge(menu_id, knowledge_type)

