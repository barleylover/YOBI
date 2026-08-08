# YOBI chatbot improvement implementation matrix

- 기준 명세: `YOBI_CHATBOT_IMPROVEMENT_CODEX_GOAL.md`
- 작업 브랜치: `codex/master-spec-completion`
- 점검일: 2026-08-09 KST
- 상태 의미: **연결됨**은 현재 작업 트리의 실제 런타임 경로가 존재한다는 뜻이며,
  **로컬 PASS**는 최종 로컬 회귀를 통과했다는 뜻이다. Oracle/OCI/Public와 Git은
  별도 증거가 기록될 때까지 계속 대기 상태다.

이 문서는 구현 파일 목록을 완료 증거로 대신하지 않는다. 로컬 전체 검증, Oracle
Migration/seed, OCI release 전환, Public E2E, Git push는 서로 다른 증거다. 아래
Phase 7 표의 빈 항목이 실제 결과로 채워지기 전에는 개선 Goal 전체를 Done 또는
공개 배포 완료로 표현하지 않는다.

## 핵심 결과

현재 작업 트리는 단순한 “메시지 → 즉시 검색” 경로를 다음 구조로 확장한다.

```text
사용자 발화
  → DialogueEngine: DialogueAct + PreferenceDelta + 누적 MealNeedState
  → Readiness gate: 질문/보류 또는 추천 허용
  → SQL 하드 필터 + Wiki 상속 + 메뉴/옵션 사실 재검증
  → lexical/vector 재랭킹
  → 서버 RecommendationResult + RecommendationSnapshot
  → LLM 설명 또는 동일 행위를 보존하는 deterministic fallback
  → UI가 conversation/event API로 서버 상태를 hydrate
```

일반 음식 Wiki는 고품질 기본 지식으로 사용하되 특정 실제 가게 레시피로 가장하지
않는다. `DEFINING`/`CORE` 재료는 `PRESUMED_PRESENT`로 보수적 필터링에 사용하고,
미기재는 부재가 아니다. 합성 리뷰는 저장·표시 호환성을 위해 남아 있지만 추천과
안전 가중치는 모두 `0`이다.

## Phase 0~7 매트릭스

| Phase | 현재 작업 트리 상태 | 실제 산출물 | 최종 증거 상태 |
|---|---|---|---|
| 0. 계약·기준선·평가 | 연결됨 | `domain/dialogue.py`, `domain/knowledge.py`, `genai/contracts.py`, `evaluation/fixtures/*.json` | 로컬 PASS: legacy 100 queries + acceptance 345 assertions, 모든 failure counter 0 |
| 1. 대화 상태·readiness | 연결됨 | `services/dialogue_engine.py`, `services/chat_service.py`, `test_dialogue_state.py` | 로컬 backend/acceptance/E2E PASS |
| 2. 오케스트레이션·UI 계약 | 연결됨 | Migration 005, conversation/snapshot repository와 API, `ChatPage.tsx`, conversation API/Vitest/E2E | 로컬 frontend 및 E2E PASS; Public UI 대기 |
| 3. 지식 그래프·authoring | 연결됨 | Migration 006, `knowledge/authoring.py`, SQLite/Oracle loader, Markdown corpus | Oracle 실제 Migration/load 검증 대기 |
| 4. 합성 Wiki·원산지·매핑 | 연결됨 | 20 카테고리/150 메뉴 매핑, 30 가게 원산지 선언, 정규화 재료, 메뉴 사실, 옵션 효과, `knowledge/dishes/` | 최종 seed exact-count 및 공개 DB 검증 대기 |
| 5. 하이브리드 추천·설명 | 연결됨 | repository `recommend_menus`/`get_grounded_menu_knowledge`, claim resolver, tool grounding, review-weight-0 회귀 | 로컬 acceptance PASS; Oracle Vector 실행 대기 |
| 6. LLM 품질·fallback | 연결됨 | provider/capability adapter, DialogueAct tool routing, structured narrative, response validator, 오류 분류·retry | 로컬 회귀 PASS; 실제 OCI 정상/오류 smoke 대기 |
| 7. 통합·배포 | 로컬 PASS, 외부 증거 대기 | 배포 archive preflight, checksum migration, release marker/정확한 rollback, 문서와 acceptance runner | 로컬 전체 gate PASS; OCI release, Public 3회, Git/PR 기록 필요 |

## Phase별 구현 근거

### Phase 0 — 실행 가능한 계약

- `backend/app/domain/dialogue.py`: `DialogueAct`, `MealNeedState`,
  `PreferenceDelta`, `ReadinessDecision`, `RecommendationResult`, snapshot/event
  Pydantic 계약.
- `backend/app/domain/knowledge.py`: concept relation, ingredient role, claim status,
  source scope, resolved ingredient/allergen/passage 계약.
- `backend/app/genai/contracts.py`: provider capability, on-demand/dedicated serving
  mode, 안정적인 오류 taxonomy.
- `backend/evaluation/fixtures/chatbot_golden_transcripts.json`: 실제 다중 턴 상태,
  카드 유무, readiness, snapshot, 하드 제약 기대값.
- `backend/evaluation/fixtures/knowledge_golden_cases.json`: canonical 메뉴 사실,
  concept lineage, facet, claim scope/status 기대값.

### Phase 1 — 대화 상태와 추천 시점

`DialogueEngine`은 매 턴 delta만 추출한 뒤 누적 상태에 병합한다. 인사,
`I don't know yet`, 추천 보류, 부정 조건, 정정, 예산, 맵기, 감각 선호가 서로
다른 필드로 보존된다. readiness가 부족하면 다음 질문을 선택하고 카드·snapshot을
만들지 않는다. 명시적 추천 요청은 hold를 해제할 수 있지만 하드 제약을 완화하지
않는다. provider가 설정된 need-collection 턴은 무도구 LLM 답변을 시도할 수 있고,
실패하면 같은 `DialogueAct`의 deterministic 질문으로 돌아간다.

### Phase 2 — 서버 권위와 브라우저 동기화

- Migration `005_conversation_state.sql`이 session 상태/version,
  `RECOMMENDATION_SNAPSHOT`, `CONVERSATION_EVENT`를 추가한다.
- `GET /api/v1/sessions/{id}/conversation`은 새로고침 시 누적 상태, 메시지, 최신
  snapshot을 반환한다.
- `POST /api/v1/sessions/{id}/events`는 select/reject/compare/options를 snapshot과
  state version에 대해 검증하고 idempotency key로 중복을 막는다.
- 두 message POST의 선택적 `request_id`는 같은 session의 content/intent에 묶인다.
  동일 payload 재전송은 저장된 `AssistantTurn`을 반환하고 상태·snapshot·mutation을
  다시 만들지 않으며, 다른 payload 재사용은 `CHAT_REQUEST_ID_REUSED`로 거절한다.
  필드를 생략하는 기존 client도 계속 허용한다.
- 브라우저는 완료되지 않은 SSE 요청의 ID와 payload를 session storage에 보존한다.
  서버가 이 안정적인 요청 identity로 agent mutation key를 만들기 때문에, mutation
  commit 뒤 provider/응답이 끊겨도 같은 요청을 복구하면서 cart line을 중복 추가하지
  않는다.
- assistant 본문과 카드 후보는 같은 `RecommendationResult`에서 만들어진다.
- 프론트엔드는 내부 DB ID를 사용자 텍스트로 노출하지 않고 서버 응답으로 상태를
  다시 hydrate한다.

### Phase 3 — Markdown을 유지하는 관계형 Wiki

편집 원본은 `knowledge/dishes/**/*.md`이고 런타임 권위는 컴파일된 관계/claim/chunk
release다. `backend/app/knowledge/authoring.py`는 JSON-compatible front matter와
9개 facet, 부모 존재, cycle, 중복, ingredient/allergen 분류, core claim 상태를
검증한다. stable hash/ID, closure, chunk, 1,536차원 vector를 생성한다.

`sqlite_store.py`와 `oracle_store.py`는 release를 `LOADING`으로 만들고 동일 release
소유 행을 원자적으로 적재·검증한 뒤 `READY`/`ACTIVE`로 전환한다. Oracle loader는
배포 시 선택된 embedding vector를 Oracle `VECTOR`로 bind한다. authoring source와
runtime embedding metadata는 모두 release에 남는다.

### Phase 4 — 현재 데모 데이터 범위

- 현재 Wiki release는 29개 concept/Markdown 문서, 27개 relation, 66개 closure,
  411개 claim, 261개 facet chunk를 가진다. 현재 20개 메뉴 카테고리와 150개
  메뉴는 `MAPPED`; 새로운 검토되지 않은
  카테고리는 기본적으로 seed를 실패시키며, 허용할 때도 명시적 `UNMAPPED` 사유가
  필요하다.
- taxonomy는 47개 claim-backed ingredient를 사용하고 카테고리명을 재료처럼 만든
  pseudo ingredient를 제거한다. knowledge corpus allergen 8개와 기존 호환 allergen을
  합친 seed 전체 계약은 10개다.
- 30개 가게마다 하나의 합성 merchant-wide 원산지 선언과 정규화 재료가 있다. 이
  정보는 해당 가게가 사용하는 재료 범위이지 모든 메뉴 포함 증명이 아니다.
- canonical 데모 메뉴에는 범위가 명시된 `SYNTHETIC_MENU_SPEC` 사실이 있고,
  cheese/fish-cake 선택에는 4개의 option ingredient effect가 있다.
- 데이터 source/ref/version/review/is_synthetic 필드는 실제 가게·요기요 데이터와의
  혼동을 막는다.

### Phase 5 — 하드 필터와 RAG의 역할 분리

서비스 지역, 가용성, 가격, 맵기, 알레르기·식단·제외 재료는 최종 후보의 하드
계약이다. Wiki의 `DEFINING`/`CORE` 상속 충돌도 보수적으로 제외한다. 메뉴/옵션
사실만 같은 대상의 범용 claim을 구체적으로 수정한다. merchant origin은 설명용
가게 범위로 남는다.

그 후 누적 온도·식감·맛·카테고리 선호를 query에 합쳐 semantic/lexical ranking을
수행한다. 리뷰는 ranking/safety/LLM grounded context에서 제외된다. 설명 도구는
resolved ingredient/allergen claim, Wiki passage, 메뉴 evidence, origin context,
unknown 목록을 함께 반환한다. `UNKNOWN`과 미기재는 안전·부재 근거가 아니다.

### Phase 6 — provider·검증·fallback

`GenAIProvider`는 생성 provider/model/serving mode를 도메인 로직에서 분리한다.
capability 계약은 Responses API, Function Calling, structured output, streaming,
continuation 방식을 표현한다. dedicated endpoint ID가 없으면 실제 dedicated 호출은
configured 상태가 아니며, contract fixture 통과를 live endpoint 증거로 쓰지 않는다.

timeout/network/재시도 가능한 5xx는 bounded exponential backoff와 jitter를 사용한다.
rate limit은 model cooldown과 fallback으로 분리된다. invalid argument, empty/no-tool
response, grounding rejection은 안전 코드로 분류된다. model narrative는 server card에
존재하는 menu/claim/passage만 참조할 수 있고 내부 tool/ID 노출은 거절된다. 생성
model 전환은 embedding model/version을 변경하지 않는다.

### Phase 7 — 로컬 완료 증거와 남은 외부 증거

| Gate | 명령/증거 | 현재 문서 상태 |
|---|---|---|
| Backend lint | `.venv/bin/ruff check backend scripts` | PASS — zero errors |
| Backend type | `.venv/bin/mypy --python-version 3.12 backend/app backend/evaluation scripts` | PASS — 58 source files |
| Backend full test | `cd backend && ../.venv/bin/pytest -q` | PASS — 188 passed, 1 warning, 43.27s |
| Legacy + chatbot acceptance | `make evaluate` | PASS — 100 legacy queries; 8 transcripts/15 turns/2 events/3 knowledge cases/345 assertions; all counters zero |
| Frontend lint/test/build | `cd frontend && pnpm lint && pnpm test -- --run && pnpm build` | PASS — 4 files/10 tests; 1,796 modules built |
| Local product E2E | Playwright configured suite | PASS — 21 passed/27 intentional skips, four-viewport Primary + complete iPhone flows, 1.0m |
| Migration/seed | migration checksum + exact counts + mapping/vector/FK/option 검증 | Oracle 실행 결과 미기록 |
| OCI GenAI | 현재 승인된 on-demand 정상·오류/fallback smoke | 실제 실행 결과 미기록 |
| Public routes/security | `/healthz`, `/readyz`, `/`, `/demo/qr`, demo auth 403 | 개선 release 결과 미기록 |
| Public product | 대화→추천→옵션→cart→Mock payment/order | 개선 release 결과 미기록 |
| Primary Demo | 같은 공개 release에서 3회 연속 성공 | 개선 release 결과 미기록 |
| Git/PR | commit, push, Draft PR #1 증거 갱신 | 미기록 |

`docs/TEST_REPORT.md`에는 위 표를 실제 숫자, release ID, 시간, 경계와 함께 옮긴다.
로컬 PASS를 Oracle/Public PASS로 복사하지 않는다.

## DB·catalog·embedding 식별자

- Schema migrations: immutable `001`-`004`, additive `005` conversation,
  `006` knowledge graph, `007` service area/agent mutation idempotency, and `008`
  checkout cart-version/fingerprint idempotency.
- Migration `008`은 기존 checkout/order를 수정하지 않고 nullable
  `cart_version`/`cart_fingerprint`와 unique `(cart_id, cart_version)`을 추가한다.
  서버는 cart ID·확정 version·현재 total로 fingerprint를 재계산하고, frontend는
  `confirmCart`가 반환한 version으로 `checkout-{cart_id}-{version}` key를 만든다.
  같은 cart snapshot은 재생되고, 변경·재가격된 cart는 재확정 후 새 version으로만
  checkout을 만들 수 있다.
- Catalog version: `demo-2026.08.09-knowledge-v2`.
- Knowledge release: source-derived immutable `knowledge-demo-<24 hex>` ID (the exact value is
  emitted by seed/readiness evidence for the deployed corpus).
- Knowledge catalog: `demo-knowledge-catalog-2026.08.09-v2`.
- Authoring default embedding: `yobi-semantic-hash-v1`, dimension `1536`, version
  `2026-08-06`.
- Generation default configuration: OCI, logical primary `xai.grok-4.3`, fallback
  `openai.gpt-oss-120b`, `on_demand`; environment can select dedicated endpoint
  references without changing recommendation/safety code.

Generation and embedding identifiers must be reported separately. A successful Grok
or GPT-OSS turn does not prove which chunk embedding is active; `/readyz` and the
knowledge release record do.

## 운영·fallback·rollback

Structured logs distinguish provider, logical model, serving mode, retry attempt,
safe error code, tool outcome, fallback usage, and grounding rejection without
recording credentials or endpoint references. The UI may show continuity mode but
must not expose internal IDs, stack traces, or provider bodies.

Deployment packages the full migration directory and `knowledge/`, checks required
artifacts before upload, validates all known migration checksums before pending DDL,
and marks a release ready only after health/readiness. It records the exact prior
health-verified release in `/opt/yobi/shared/previous_release`.

`sudo /opt/yobi/current/deploy/rollback.sh` switches only to that recorded verified
application release (or an explicitly supplied verified release ID). It does not
reverse additive migrations or delete knowledge rows. If rollback health fails it
restores the original symlink. See `OCI_DEPLOYMENT.md` for operator commands.

## 합성/실데이터 경계와 남은 실서비스 검증

현재 메뉴, 가게, 리뷰, 원산지, 메뉴 사실, 호텔, 결제, 주문은 합성 또는 Mock이다.
실제 요기요 API/리뷰/주문/결제를 사용하지 않는다. 일반 Wiki 역시 합성·reviewed-demo
지식이며, 실제 레시피 검증이나 알레르기 무위험·할랄 인증을 뜻하지 않는다.

실서비스 전에는 실제 가게 제공 menu-level 재료/원산지 provenance, 변경 주기,
전문가 review, 교차접촉 정책, 삭제/정정 흐름, 실제 embedding 품질, 개인정보/동의,
TLS와 실결제·주문 시스템의 별도 안전 계약이 필요하다. 이 항목들은 현재 데모
Goal의 완료 조건으로 가장하지 않는다.
