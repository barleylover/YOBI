BEGIN
  EXECUTE IMMEDIATE q'[ALTER TABLE chat_session ADD (
    meal_need_state_json CLOB DEFAULT '{}' NOT NULL CHECK (meal_need_state_json IS JSON)
  )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'[ALTER TABLE chat_session ADD (
    dialogue_act VARCHAR2(40) DEFAULT 'COLLECT_NEEDS' NOT NULL
  )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'[ALTER TABLE chat_session ADD (
    state_version NUMBER(10) DEFAULT 0 NOT NULL CHECK (state_version >= 0)
  )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'[CREATE TABLE recommendation_snapshot (
    snapshot_id VARCHAR2(64) PRIMARY KEY,
    session_id VARCHAR2(64) NOT NULL REFERENCES chat_session(session_id) ON DELETE CASCADE,
    assistant_message_id VARCHAR2(64) NOT NULL REFERENCES chat_message(message_id) ON DELETE CASCADE,
    state_version NUMBER(10) NOT NULL,
    meal_need_state_json CLOB NOT NULL CHECK (meal_need_state_json IS JSON),
    result_json CLOB NOT NULL CHECK (result_json IS JSON),
    cards_json CLOB NOT NULL CHECK (cards_json IS JSON),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL
  )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'[CREATE TABLE conversation_event (
    event_id VARCHAR2(64) PRIMARY KEY,
    session_id VARCHAR2(64) NOT NULL REFERENCES chat_session(session_id) ON DELETE CASCADE,
    snapshot_id VARCHAR2(64) REFERENCES recommendation_snapshot(snapshot_id) ON DELETE SET NULL,
    event_type VARCHAR2(40) NOT NULL,
    payload_json CLOB NOT NULL CHECK (payload_json IS JSON),
    result_json CLOB NOT NULL CHECK (result_json IS JSON),
    idempotency_key VARCHAR2(100) NOT NULL,
    resulting_state_version NUMBER(10) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT uq_conversation_event_key UNIQUE (session_id, idempotency_key)
  )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_snapshot_session_created ON recommendation_snapshot(session_id, created_at)';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_conversation_event_session ON conversation_event(session_id, created_at)';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;
END;
