# YOBI 코드 분석 3인 분담안

기준 문서: `architecture.md`

## 분담 원칙

- 파일 수가 아니라 사용자 동작 흐름을 기준으로 나눈다.
- 각 담당자는 프론트엔드 → API → 서비스 → 저장소 → DB를 끝까지 추적한다.
- `main.py`, `api.ts`, 두 repository처럼 큰 공통 파일은 담당 메서드군만 나눠 본다.
- SQLite와 Oracle 구현은 같은 기능끼리 반드시 비교한다.

## A — 사용자 진입·세션·주소·레거시 대화

### 1. 담당 흐름

```text
Welcome/언어 선택
→ 프로필·세션 생성
→ 주소 검색·이미지 확인·확정
→ 세션 저장
→ 레거시 메시지/SSE 대화와 재접속
```

### 2. 핵심 파일

- 프론트: `frontend/src/routes/WelcomePage.tsx`, `frontend/src/routes/LocalePage.tsx`, `frontend/src/routes/OnboardingPage.tsx`, `frontend/src/stores/session.ts`
- API: `frontend/src/lib/api.ts`의 profile/session/address 메서드
- 백엔드: `backend/app/main.py`의 profile/session/message/address 라우트
- 서비스: `backend/app/services/address_ocr.py`, `backend/app/services/dialogue_engine.py`, `backend/app/services/chat_service.py`
- 대화 AI: `backend/app/genai/agent_loop.py`, `backend/app/genai/tool_registry.py`, `backend/app/genai/tool_schemas.py`
- 저장소: 두 repository의 profile/session/message/address/audit/reset 메서드
- DB: `user_profile`, `chat_session`, `chat_message`, `address_place`, `address_ref`, `audit_log`
- 테스트: `backend/tests/test_address_ocr.py`, `backend/tests/test_dialogue_state.py`, `backend/tests/test_chat_fallback.py`, `backend/tests/test_tools_and_agent.py`

### 3. 함께 봐야 하는 이유

온보딩에서 만든 `profile_id`, `session_id`, `address_ref_id`, `state_version`이 추천과 주문 전체의 시작점이다. 주소 확정은 `cart.address_ref_id`와 cart 확정 상태도 변경한다.

### 4. 리뷰 중점

- 개인정보 동의와 `remember_profile` 보존 정책
- 주소 파일 검증과 후보 토큰의 session binding·만료·위변조 방지
- 메시지 `request_id`/`state_version` 멱등성
- user→assistant 메시지 순서
- `GET /messages`의 `safe_metadata` 응답 타입 오류
- SSE 오류가 HTTP 200 안에서 전달되는 경계

### 5. 다른 담당자 연결

- B에게 profile/session/address/state version 전달
- C에게 확정 주소와 service area 전달
- C와 레거시 agent의 cart mutation을 공동 검토

### 6. 권장 순서

`frontend/src/routes/OnboardingPage.tsx` → `frontend/src/stores/session.ts` → `frontend/src/lib/api.ts` → `backend/app/main.py` → 주소/대화 서비스 → repository 두 구현 → 관련 테스트

## B — 구조화 추천·지식·RAG·생성형 AI

### 1. 담당 흐름

```text
추천 조건 선택
→ 조건 버전 확정
→ 추천 request 예약
→ 지식 근거 검색
→ 생성기 1회 또는 검색 폴백
→ grounding 검증
→ snapshot 저장·결과 표시·메뉴 선택
```

### 2. 핵심 파일

- 프론트: `frontend/src/routes/ChatPage.tsx`, `frontend/src/components/PreferenceSelector.tsx`, `frontend/src/components/SpiceReferenceScale.tsx`, `frontend/src/components/RecommendationResults.tsx`, `frontend/src/components/EvidenceBadge.tsx`
- API: `frontend/src/lib/api.ts`의 catalog/criteria/recommendation/conversation/event 메서드
- 도메인: `backend/app/domain/preference_catalog.py`, `backend/app/domain/structured_recommendation.py`, `backend/app/domain/knowledge.py`
- 서비스: `backend/app/services/structured_recommendation.py`
- AI/RAG: `backend/app/genai/recommendation_generator.py`, `backend/app/genai/grounding.py`, `backend/app/genai/providers.py`, `backend/app/rag/`
- 지식: `backend/app/knowledge/`, `knowledge/dishes/**/*.md`
- 저장소: criteria/request/snapshot/search/evidence/release 메서드
- DB: criteria/request/snapshot/release family, knowledge graph, certification 관련 테이블
- 테스트: `backend/tests/test_structured_recommendation_service.py`, `backend/tests/test_structured_recommendation_persistence.py`, `backend/tests/test_recommendation_generator.py`, `backend/tests/test_hybrid_knowledge.py`, `backend/tests/test_knowledge_authoring.py`, `backend/tests/test_knowledge_runtime_readiness.py`, `backend/tests/test_preference_catalog.py`

### 3. 함께 봐야 하는 이유

추천 결과는 모델 출력만으로 결정되지 않는다. 조건 버전, 활성 release family, DB evidence pool, 생성 결과 검증, 저장된 snapshot을 함께 봐야 추천 근거와 멱등성을 이해할 수 있다.

### 4. 리뷰 중점

- 같은 범주 OR·다른 범주 AND 계약
- halal 정식 인증, vegan 경고, v2 allergy filter 부재
- KR/US 5단계 맵기 기준
- request hash·criteria/state version 멱등성
- 생성 dispatch 1회와 orphan request 처리
- evidence pool 밖 menu/claim/passage 차단
- 검색 폴백의 명확한 표시
- Oracle JSON canonicalization과 release pointer 일관성

### 5. 다른 담당자 연결

- A의 session/profile/address를 추천 입력으로 사용
- C에게 선택된 `menu_id`, `merchant_id`, `snapshot_id` 전달
- C와 추천 조건을 cart/checkout에서 다시 검증하는지 공동 확인

### 6. 권장 순서

`frontend/src/routes/ChatPage.tsx` → 추천 도메인 모델 → `backend/app/main.py` 추천 라우트 → `StructuredRecommendationService` → repository evidence/request 메서드 → AI/RAG/지식 → 관련 테스트

## C — 메뉴 옵션·장바구니·결제·주문·DB 운영

### 1. 담당 흐름

```text
추천 메뉴 선택
→ 옵션·추가 메뉴 조회
→ 장바구니 변경
→ 배송 설정·cart 확정
→ checkout 생성
→ 모의 결제
→ 주문 생성·조회
→ migration/seed/배포
```

### 2. 핵심 파일

- 프론트: `frontend/src/components/OrderFlowPanel.tsx`, `frontend/src/routes/PaymentPage.tsx`, `frontend/src/routes/OrderPage.tsx`, `frontend/src/routes/DemoControlPage.tsx`
- API: `frontend/src/lib/api.ts`의 options/cart/delivery/checkout/order 메서드
- 백엔드: `backend/app/main.py`의 menu/cart/delivery/checkout/order/health/demo 라우트
- 저장소: 두 repository의 options/cart/delivery/checkout/order/status 메서드
- DB 기반: `backend/app/db/schema_sqlite.py`, `backend/app/db/seed_data.py`, `backend/app/db/oracle_pool.py`
- SQL: `database/migrations/001_core_schema.sql`~`010_structured_hybrid_rag_recommendation.sql`
- 운영: `scripts/migrate.py`, `scripts/seed_demo.py`, `deploy/deploy.sh`, `deploy/secure_bootstrap.py`, `deploy/rollback.sh`, `deploy/nginx/`, `deploy/systemd/`
- 테스트: `backend/tests/test_cart_payment_integrity.py`, `backend/tests/test_api_contracts.py`, `backend/tests/test_migration_parser.py`, `backend/tests/test_seed_integrity.py`, `backend/tests/test_deploy_release_safety.py`

### 3. 함께 봐야 하는 이유

가격·옵션·배송비는 서버가 다시 계산하며, cart version/fingerprint가 checkout과 주문을 묶는다. SQLite 동작과 Oracle lock/transaction, migration까지 함께 봐야 정확성과 동시성 안전성을 판단할 수 있다.

### 4. 리뷰 중점

- 서버 권위 가격과 필수 옵션 검증
- 한 cart의 단일 merchant 제한
- cart version·confirmed fingerprint 변경 규칙
- checkout idempotency와 `CHECKOUT_STALE`
- 결제 성공 전 현재 가격·가용성·주소 재검증
- 한 cart에서 주문이 중복 생성되지 않는지
- Oracle `FOR UPDATE`와 rollback 범위
- 주문 응답의 내부 cart snapshot 노출
- migration checksum·순서와 `--fresh`/reset 위험
- 일반 API 인증 부재와 HTTP 80 배포

### 5. 다른 담당자 연결

- A의 확정 주소 변경 시 cart 무효화 확인
- B의 선택 메뉴와 추천 조건을 cart/checkout에서 재검증
- B와 knowledge/recommendation release 배포·rollback 공동 확인

### 6. 권장 순서

`frontend/src/components/OrderFlowPanel.tsx` → Payment/Order 화면 → `frontend/src/lib/api.ts` → `backend/app/main.py` → SQLite cart/checkout 구현 → Oracle 비교 → migrations/seed → deploy/rollback → 관련 테스트

## 공통 파일과 협업 지점

| 공통 파일 | 분담 방법 |
|---|---|
| `frontend/src/lib/api.ts` | A는 진입/주소, B는 추천, C는 주문 API |
| `frontend/src/stores/session.ts`, `frontend/src/types.ts` | 각 담당 흐름에서 사용하는 상태·타입만 우선 분석 후 계약을 함께 확인 |
| `backend/app/main.py` | 라우트군을 A/B/C로 나눠 분석 |
| `backend/app/db/repository.py` | 기능별 메서드군 분담 |
| `backend/app/db/sqlite_repository.py`, `backend/app/db/oracle_repository.py` | 각자 담당 메서드를 두 DB에서 비교 |
| `backend/app/domain/models.py` | A는 profile/session/address, B는 추천 연결 타입, C는 menu/cart/order |
| `backend/app/db/schema_sqlite.py`, `database/migrations/` | C가 전체 구조를 총괄하고 A/B가 담당 테이블 제약을 확인 |

반드시 함께 맞출 경계는 다음 세 가지다.

1. A → B: profile/session/address/state version
2. B → C: snapshot/menu/merchant/선택 이벤트
3. C → A: session/profile reset·delete cascade

## 한눈에 보는 최종 분담

| 담당자 | 핵심 흐름 | 주요 책임 | 작업량 균형 근거 |
|---|---|---|---|
| A | 진입 → 프로필/세션 → 주소 → 레거시 대화 | 사용자 context, 주소 보안, 대화 상태·멱등성 | 대형 `ChatService`와 상태 머신 담당 |
| B | 조건 → 지식 검색 → AI 추천 → snapshot/선택 | 구조화 추천, RAG, grounding, release | 지식 corpus와 추천 파이프라인 담당 |
| C | 옵션 → cart → checkout → order → 배포 | 주문 트랜잭션, SQLite/Oracle, migration/deploy | 동시성·DB·운영 범위 담당 |
