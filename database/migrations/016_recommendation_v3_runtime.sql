CREATE TABLE recommendation_provider_attempt (
  session_id VARCHAR2(64) NOT NULL,
  request_id VARCHAR2(100) NOT NULL,
  attempt_no NUMBER(2) NOT NULL CHECK (attempt_no BETWEEN 1 AND 9),
  provider VARCHAR2(40) NOT NULL,
  model_id VARCHAR2(120) NOT NULL,
  status VARCHAR2(24) NOT NULL CHECK (status IN ('STARTED','SUCCEEDED','FAILED')),
  error_code VARCHAR2(160),
  latency_ms NUMBER(12) CHECK (latency_ms IS NULL OR latency_ms >= 0),
  input_tokens NUMBER(12) CHECK (input_tokens IS NULL OR input_tokens >= 0),
  output_tokens NUMBER(12) CHECK (output_tokens IS NULL OR output_tokens >= 0),
  created_at TIMESTAMP WITH TIME ZONE NOT NULL,
  completed_at TIMESTAMP WITH TIME ZONE,
  PRIMARY KEY (session_id, request_id, attempt_no),
  FOREIGN KEY (session_id, request_id)
    REFERENCES structured_recommendation_request(session_id, request_id) ON DELETE CASCADE
)
-- +YOBI STATEMENT
CREATE TABLE restaurant_note_translation (
  translation_id VARCHAR2(64) PRIMARY KEY,
  session_id VARCHAR2(64) NOT NULL REFERENCES chat_session(session_id) ON DELETE CASCADE,
  source_language VARCHAR2(16) NOT NULL,
  source_text VARCHAR2(1000) NOT NULL,
  korean_text VARCHAR2(1000),
  back_translation VARCHAR2(1000),
  provider VARCHAR2(40) NOT NULL,
  model_id VARCHAR2(120) NOT NULL,
  status VARCHAR2(24) NOT NULL CHECK (status IN ('SUCCEEDED','FAILED')),
  error_code VARCHAR2(160),
  request_hash VARCHAR2(64) NOT NULL,
  created_at TIMESTAMP WITH TIME ZONE NOT NULL
)
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE user_profile ADD country_code VARCHAR2(2)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE structured_recommendation_request ADD client_cancelled_at TIMESTAMP WITH TIME ZONE';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE cart_item ADD note_translation_id VARCHAR2(64)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE cart_item ADD CONSTRAINT fk_cart_note_translation FOREIGN KEY (note_translation_id) REFERENCES restaurant_note_translation(translation_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-2264, -2275) THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
CREATE INDEX idx_provider_attempt_request
  ON recommendation_provider_attempt(session_id, request_id, attempt_no)
-- +YOBI STATEMENT
CREATE INDEX idx_note_translation_session
  ON restaurant_note_translation(session_id, created_at)
-- +YOBI STATEMENT
CREATE INDEX idx_rec_request_cancelled
  ON structured_recommendation_request(session_id, client_cancelled_at, created_at)
