BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE recommendation_provider_attempt ADD attempt_role VARCHAR2(24) DEFAULT ''SELECTION'' NOT NULL';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^
CREATE TABLE restaurant_note_translation_attempt (
  session_id VARCHAR2(64) NOT NULL REFERENCES chat_session(session_id) ON DELETE CASCADE,
  request_hash VARCHAR2(64) NOT NULL,
  attempt_no NUMBER(2) NOT NULL CHECK (attempt_no BETWEEN 1 AND 9),
  provider VARCHAR2(40) NOT NULL,
  model_id VARCHAR2(120) NOT NULL,
  status VARCHAR2(24) NOT NULL CHECK (status IN ('SUCCEEDED','FAILED')),
  error_code VARCHAR2(160),
  latency_ms NUMBER(12) CHECK (latency_ms IS NULL OR latency_ms >= 0),
  input_tokens NUMBER(12) CHECK (input_tokens IS NULL OR input_tokens >= 0),
  output_tokens NUMBER(12) CHECK (output_tokens IS NULL OR output_tokens >= 0),
  created_at TIMESTAMP WITH TIME ZONE NOT NULL,
  completed_at TIMESTAMP WITH TIME ZONE NOT NULL,
  PRIMARY KEY (session_id,request_hash,attempt_no)
)^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_note_translation_attempt_request ON restaurant_note_translation_attempt(session_id,request_hash,attempt_no)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-955,-1408) THEN RAISE; END IF;
END;
