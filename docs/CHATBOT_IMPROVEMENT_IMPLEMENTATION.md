# YOBI chatbot improvement implementation matrix

- 기준 명세: `YOBI_CHATBOT_IMPROVEMENT_CODEX_GOAL.md`
- 작업 브랜치: `codex/master-spec-completion`
- 점검일: 2026-08-11 KST
- 상태 의미: **연결됨**은 현재 작업 트리의 실제 런타임 경로가 존재한다는 뜻이며,
  **PASS**는 해당 경계의 실제 검증을 통과했다는 뜻이다. 로컬, Oracle, OCI GenAI,
  Public, Git/Draft PR 증거는 서로 대체하지 않고 별도로 기록한다.

이 문서는 구현 파일 목록을 완료 증거로 대신하지 않는다. 로컬 전체 검증, Oracle
Migration/seed, OCI release 전환, Public E2E, Git push는 서로 다른 증거다. 특히
아래 2026-08-11 항목은 **로컬 작업 트리 구현 상태**이며 아직 OCI/Public 증거가
아니다. 2026-08-09 배포 기록은 그 뒤에 역사적 증거로 보존한다.

## 2026-08-11 내부 메뉴 지식 그래프 기반 데모 개선

현재 로컬 구현은 가게 설명과 리뷰 대신 재사용 가능한 음식 Wiki를 추천·설명의
중심에 둔다. 지식 노드는 특정 가게 상품이 아니라 `FAMILY`와 `VARIANT` 수준까지
내려간다. 예를 들어 가게별 참치김밥 상품은 공통 `참치김밥` 지식에 매핑되고,
가게 이름을 포함한 별도 Wiki 노드를 만들지 않는다.

| 영역 | 현재 로컬 계약 |
|---|---|
| 목업 catalog | 60 가게, 600 메뉴, 1,200 evidence, 1,202 option group, 2,405 option item |
| Wiki graph | 102 concept/document (`CUISINE` 2/`FAMILY` 30/`VARIANT` 70), relation 100, closure 281, claim 1,997, chunk 918, 600 `MAPPED` menu |
| claim 구성 | ingredient 361, allergen 371, dietary 247, preparation 100, facet 918 |
| 불완전 메뉴 사실 | ingredient: 206 메뉴/565행, allergen: 221 메뉴/595행, dietary: 20 속성/1,217행 |
| 가게·옵션 범위 | origin 13, shared-kitchen cross-contact ingredient 119, option effect 4 |
| 리뷰 | 2,400 합성 행 유지, ranking/safety/LLM grounded context 가중치 `0` |
| 버전 | base catalog `demo-2026.08.11-knowledge-v3`, knowledge catalog `demo-knowledge-catalog-2026.08.11-v3`, migration package `001`–`009` |

검색은 서비스 지역·가용성·알레르기·식단 하드 필터를 먼저 적용한다. cap `600`은
남은 데모 후보 전체를 exact 한국어/영어 alias, 한국어 facet, vector, 구조화
rerank까지 보존한다. 인원수 기준 총비용·예산·부정 선호는 최종 출력 전에 적용한다.
최종 점수는 정확히 **Wiki 60% + 구조화 선호 25% + 운영/메뉴 메타데이터 15%**로
합성한다. 운영 신호는 메뉴 semantic relevance, 가격, 배달비, ETA만 사용하고 rating,
리뷰, 가게 설명 prose는 점수와 안전 판정에 참여하지 않는다.

생성 프롬프트와 validator의 근거 우선순위는
`OPTION > MENU > VARIANT_WIKI > FAMILY_WIKI`다. 응답 계약은 기존 menu/claim ID에
`referenced_passage_ids`, `grounding_scope`, `uncertainty_codes`를 추가한다. 따라서
Wiki의 `POSSIBLE`/`UNKNOWN`, 메뉴의 `NOT_PROVIDED`, 가게 공유주방 정보는 확정 재료,
확정 부재, 안전 인증처럼 강화할 수 없다.

명시적 부재 대안은 `VERIFIED` 합성 메뉴 evidence를 가진 메뉴 범위 사실만 사용하며,
교차접촉 상태는 계속 `UNKNOWN`이다. 따라서 설명 가능한 대안이지 알레르기 안전
인증은 아니다.

이 로컬 변경의 전체 테스트, Oracle seed/migration, OCI GenAI, health/readiness,
공개 브라우저, rollback 검증 결과는 완료 후 `TEST_REPORT.md`에 별도로 기록해야
한다. 현재 공개 환경은 아래 2026-08-09 release이며 이 v3 catalog가 아니다.

## 2026-08-09 배포 기록 (역사적)

## 핵심 결과

2026-08-09 배포 작업은 단순한 “메시지 → 즉시 검색” 경로를 다음 구조로 확장했다.

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

## 역사적 Phase 0~7 매트릭스

| Phase | 2026-08-09 당시 상태 | 당시 산출물 | 역사적 증거 상태 |
|---|---|---|---|
| 0. 계약·기준선·평가 | 연결됨 | `domain/dialogue.py`, `domain/knowledge.py`, `genai/contracts.py`, `evaluation/fixtures/*.json` | 로컬 PASS: legacy 100 queries + acceptance 345 assertions, 모든 failure counter 0 |
| 1. 대화 상태·readiness | 연결됨 | `services/dialogue_engine.py`, `services/chat_service.py`, `test_dialogue_state.py` | 로컬 backend/acceptance/E2E PASS |
| 2. 오케스트레이션·UI 계약 | 연결됨 | Migration 005, conversation/snapshot repository와 API, `ChatPage.tsx`, conversation API/Vitest/E2E | 로컬 frontend 및 Public 대화/주문 E2E PASS |
| 3. 지식 그래프·authoring | 연결됨 | Migration 006, `knowledge/authoring.py`, SQLite/Oracle loader, Markdown corpus | Oracle Migration 001–008 및 active release PASS |
| 4. 합성 Wiki·원산지·매핑 | 연결됨 | 20 카테고리/150 메뉴 매핑, 30 가게 원산지 선언, 정규화 재료, 메뉴 사실, 옵션 효과, `knowledge/dishes/` | 공개 DB exact-count/mapping PASS |
| 5. 하이브리드 추천·설명 | 연결됨 | repository `recommend_menus`/`get_grounded_menu_knowledge`, claim resolver, tool grounding, review-weight-0 회귀 | 로컬 acceptance와 Oracle/Public 실행 PASS |
| 6. LLM 품질·fallback | 연결됨 | provider/capability adapter, DialogueAct tool routing, structured narrative, response validator, 오류 분류·retry | OCI 주 모델·fallback 모델·실제 오류 분류·Oracle fallback PASS |
| 7. 통합·배포 | PASS | 배포 archive preflight, checksum migration, SHA release identity, release marker/정확한 rollback, 문서와 acceptance runner | release 활성화, Public 21개, Primary 3회, NSG cleanup PASS |

## 역사적 Phase별 구현 근거

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
runtime embedding metadata는 모두 release에 남는다. 설명 prewarm cache의
`source_version`은 catalog version과 active knowledge release를 함께 포함하며,
새 release가 활성화되면 같은 메뉴의 낡은 prewarm 행을 삭제하고 새 hash key로
재생성한다.

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
continuation 방식과 최대 input/output, 요청당 tool schema 수, 응답당 tool call 수를
표현한다. AgentLoop는 server/provider 한도의 작은 값을 적용하고 실행 전에 초과를
거절한다. production 또는 dedicated 설정의 key/model/HTTPS region/endpoint/
필수 capability가 누락되면 `/readyz`가 민감값 없이 `GENAI_NOT_READY`로 실패한다.
dedicated endpoint ID가 없으면 실제 dedicated 호출은 configured 상태가 아니며,
contract fixture 통과를 live endpoint 증거로 쓰지 않는다.

timeout/network/재시도 가능한 5xx는 bounded exponential backoff와 jitter를 사용한다.
rate limit은 model cooldown과 fallback으로 분리된다. invalid argument, empty/no-tool
response, grounding rejection은 안전 코드로 분류된다. model narrative는 server card에
존재하는 menu/claim/passage만 참조할 수 있고 내부 tool/ID 노출은 거절된다. 생성
model 전환은 embedding model/version을 변경하지 않는다.

### 역사적 Phase 7 — 2026-08-09 로컬·Oracle·OCI·Public 증거

| Gate | 명령/증거 | 2026-08-09 역사적 증거 상태 |
|---|---|---|
| Backend lint | `.venv/bin/ruff check backend scripts deploy/*.py` | PASS — zero errors |
| Backend type | `MYPYPATH=backend:scripts:. .venv/bin/mypy --explicit-package-bases --python-version 3.12 backend/app backend/evaluation scripts deploy/release_state.py deploy/run_with_runtime_env.py deploy/secure_bootstrap.py` | PASS — 62 source files |
| Backend full test | `cd backend && ../.venv/bin/pytest -q` | PASS — 223 passed, 1 warning, 47.11s |
| Legacy + chatbot acceptance | `make evaluate` | PASS — 100 legacy queries; 8 transcripts/15 turns/2 events/3 knowledge cases/345 assertions; all counters zero |
| Frontend lint/test/build | `cd frontend && pnpm lint && pnpm test -- --run && pnpm build` | PASS — 4 files/11 tests; 1,796 modules built |
| Local product E2E | Playwright configured suite | PASS — 21 passed/27 intentional skips, four-viewport Primary + complete iPhone flows |
| Static/repository hygiene | diff/conflict/secret/debug scan + changed shell `bash -n` | PASS — tracked `.env` 0, secret-pattern files 0, debug files 0 |
| Migration/seed | migration checksum + exact counts + mapping/vector/FK/option 검증 | PASS — 001–008, exact catalog/knowledge counts and all readiness checks true |
| OCI GenAI | 승인된 on-demand 정상·오류/fallback smoke | PASS — Grok tool loop, GPT-OSS, invalid-model classification, Oracle fallback |
| Public routes/security | `/healthz`, `/readyz`, `/`, `/demo/qr`, demo auth 403 | PASS — 200/200/200/200/403, four security headers |
| Public product | 대화→추천→옵션→cart→Mock payment/order | PASS — 21 passed/27 intentional skips in 2.4m |
| Primary Demo | 같은 공개 release에서 3회 연속 성공 | PASS — iPhone 13, worker 1, 3/3 in 26.7s |
| Git/PR | current branch push + existing Draft PR #1 head/body | PASS — OPEN/Draft, remote head synchronized, duplicate PR 없음 |

세부 release ID, 데이터 수치, 로그·NSG 정리, 합성 경계는
`docs/TEST_REPORT.md`에 기록했다.

배포 release는 `20260809T084353Z-704f74712d9d`, 검증된 rollback target은
`20260809T083629Z-bfb59275b93f`다. 공개 readiness와 제품 E2E를 마친 뒤 최종
독립 NSG 조회에서 TCP 22는 `0`, 기존 TCP 80은 `1`이었다.

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
- Knowledge release: source-derived immutable
  `knowledge-demo-1c7dd5378736fc75567ba871`.
- Knowledge catalog: `demo-knowledge-catalog-2026.08.09-v2`.
- Authoring default embedding: `yobi-semantic-hash-v1`, dimension `1536`, version
  `2026-08-06`.
- Deployment embedding provider: explicit `deterministic` pin for seed and runtime;
  `auto` is an operator-only one-off override and is not the release default.
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

Deployment packages the full migration directory and `knowledge/`, checks all
`001`–`008` artifacts before upload, derives the release identity from the archive
SHA-256, verifies the remote checksum and manifest, validates the exact migration
ledger, and marks a release ready only after symlink plus health/readiness checks. It
uses a release-and-nonce-specific remote upload, deletes that exact upload on every
exit path, and shares a non-blocking root-owned deploy/rollback lock. Application
release trees are hardened to `root:yobi` without group/world write permission. It
records the exact prior health-verified release in
`/opt/yobi/shared/control/previous_release`.

`sudo /opt/yobi/current/deploy/rollback.sh` switches only to that recorded verified
application release (or an explicitly supplied verified release ID). It does not
reverse additive migrations or delete knowledge rows. Root-owned atomic provenance in
`/opt/yobi/shared/control/release-state/<release-id>.json` binds the app release and
archive SHA-256 to its previous/current knowledge release IDs. Deploy captures the old
pointer before seed; rollback activates only a recorded `READY` target; both use bound
SQL, expected-current validation, commit/readback, and restore the original knowledge
pointer before the original symlink on failure. Bootstrap state is likewise protected
at `/opt/yobi/shared/control/bootstrap_state.json`.

Historical v1 releases without the knowledge manager/state use only the explicit
legacy compatibility path and do not switch the pointer. This is current additive-schema
compatibility evidence, not a global rollback snapshot. Future incompatible global
configuration, base catalog, or destructive state changes require a separate verified
snapshot/restore contract. See `OCI_DEPLOYMENT.md` for operator commands.

## 합성/실데이터 경계와 남은 실서비스 검증

현재 메뉴, 가게, 리뷰, 원산지, 메뉴 사실, 호텔, 결제, 주문은 합성 또는 Mock이다.
실제 요기요 API/리뷰/주문/결제를 사용하지 않는다. 일반 Wiki 역시 합성·reviewed-demo
지식이며, 실제 레시피 검증이나 알레르기 무위험·할랄 인증을 뜻하지 않는다.

실서비스 전에는 실제 가게 제공 menu-level 재료/원산지 provenance, 변경 주기,
전문가 review, 교차접촉 정책, 삭제/정정 흐름, 실제 embedding 품질, 개인정보/동의,
TLS와 실결제·주문 시스템의 별도 안전 계약이 필요하다. 이 항목들은 현재 데모
Goal의 완료 조건으로 가장하지 않는다.
