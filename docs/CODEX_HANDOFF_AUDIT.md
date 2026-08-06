# YOBI Codex 인수 감사 보고서

- 감사 기준일: 2026-08-06 (Asia/Seoul)
- 최종 기준 문서: `YOBI_FINAL_MVP_CODEX_MASTER_PROMPT.md`
- 감사 방식: 로컬 Repository 정적 검사, 기존 테스트 실행, 배포 VM/Oracle/OCI 상태의 읽기 전용 확인, 배포 화면 확인
- 비밀정보 처리: Secret 값, OCID, 공인 IP, API Key는 이 문서와 명령 출력에 기록하지 않았다.

## 1. 결론

현재 구현은 **보존해서 개선할 가치가 있는 공개 데모 기반**이다. 모바일/데스크톱 UI, FastAPI 서비스, Oracle 연결, 실제 Vector SQL, 서버 계산 가격, Mock Payment의 기본 멱등성, Systemd/Nginx 배포는 이미 작동한다.

그러나 **Master Spec 완료 상태는 아니다.** 다음 항목은 완료 판정을 막는 핵심 결함이다.

1. 실제 OCI GenAI 호출은 모델 선택과 도구 실행까지 성공하지만, 도구 결과를 모델에 돌려보내 최종 답변을 받는 단계가 최근 실행의 대부분에서 실패한다. 결정론적 fallback이 사용자 응답을 대신해 장애가 가려져 있다.
2. 결제 확정 직전 장바구니가 현재 메뉴/옵션/가격/배달비/최소주문 조건으로 재검증되지 않는다.
3. 주소 이미지는 안전하게 디코딩되고 canonical hash fallback은 동작하지만 실제 OCR provider/adapter가 없다.
4. Oracle Vector Search는 실제 사용되지만 저장 임베딩은 OCI Cohere가 아닌 결정론적 semantic-hash이며, 리뷰/지식 벡터를 활용한 완전한 hybrid RAG가 아니다.
5. 식이 조건은 DB hard filter로 재검증되지만, Master Spec의 정규화된 식이·알레르기 스키마와 evidence-ID 연결 계약이 축약되어 있다.
6. 일부 Master API와 사용자 흐름(프로필 수정, 장바구니 수정/삭제, 데모 초기화, 주소 직접 입력/수정 등)이 없다.
7. 현재 테스트는 좋은 로컬 회귀 기준이지만 실제 Oracle/GenAI/OCR 및 주요 Acceptance Criteria를 전부 자동 검증하지 않는다.

따라서 상태는 다음과 같이 판정한다.

- 로컬 결정론적 데모: **통과**
- 공개 배포 기본 동작: **통과**
- Oracle 실제 연결: **통과**
- 실제 Agent Loop 완주: **실패/수정 필요**
- Master Spec 전체 구현: **미완료**
- 최종 승인: **보류**

## 2. 감사 범위와 근거

다음 자료를 확인했다.

- Master Spec 및 OCI 인프라 인수 문서
- `references/`의 기획 원고와 PDF 3종 전체 페이지 렌더링
- Repository 파일 구조, 소스, 테스트, 배포 및 운영 문서
- `deploy/run_secure_bootstrap.sh`, bootstrap Python 코드와 checkpoint 처리
- Migration `001_core_schema.sql`, `002_knowledge_and_cache.sql`, migration runner, seed
- 로컬 lint/type/unit/E2E/retrieval 평가
- 배포 VM의 환경 파일 메타데이터, 사용자, symlink, Systemd, Nginx, bootstrap state
- 실제 Oracle migration 기록과 핵심 테이블 수량
- Secret 값을 제외한 최근 구조화 로그와 health/readiness
- SSH local tunnel을 통한 현재 배포 UI의 모바일/데스크톱 화면

오래된 기획 문서와 Master Spec이 충돌하는 경우 Master Spec을 우선했다. 예를 들어 초기 기획의 주 사용자가 거주자에 가깝더라도 현재 구현 기준은 관광객/호텔 배송 데모다.

## 3. Git 및 Secret 감사

### Git 상태

- Repository는 `main` 브랜치지만 감사 시작 시점에 commit이 하나도 없었다.
- 전체 프로젝트가 untracked 상태였으며 비교 가능한 이전 Git 기준선이나 원격 저장소가 없었다.
- 기존 구현을 삭제하거나 되돌리는 작업은 하지 않았다.
- Phase 2에서 현재 상태를 최초 checkpoint commit으로 보존한 뒤 별도 개선 브랜치에서 작업해야 한다.

### Secret 검사

- 추적 대상 소스에서 실제 `.env`, private key, 인증서, bearer token, API key literal은 발견되지 않았다.
- `.env.example`의 민감 변수는 빈 placeholder다.
- Secret처럼 보이는 대입은 bootstrap/복구 코드의 변수 처리와 테스트용 합성 값이었다.
- ignore 대상 OCR 임시 텍스트에는 교육 자료에 포함된 식별자 형태 문자열이 있으므로 `tmp/`는 Git에 추가하면 안 된다.
- Git history가 없으므로 과거 commit의 Secret 유출 여부는 검사 대상 자체가 없다.

판정: **현재 추적 예정 소스에 실제 Secret이 저장됐다는 증거는 없다.** Checkpoint 전 staged diff를 다시 검사한다.

## 4. VM, Oracle, OCI 읽기 전용 확인

| 항목 | 확인 결과 | 판정 |
|---|---|---|
| 앱 VM | 실행 중 | 통과 |
| Oracle Autonomous DB | 26ai, AVAILABLE, private endpoint | 통과 |
| GenAI Project | ACTIVE, 보존 설정 1/1 | 통과 |
| Grok / GPT-OSS / Embedding model | 모두 ACTIVE | 통과 |
| `/etc/yobi/yobi.env` | 존재, `root:root`, mode `600` | 통과 |
| 필수 환경 변수 | 21개 모두 존재하고 non-empty, 값은 미출력 | 통과 |
| 런타임 OS 사용자 | `yobi` 존재 | 통과 |
| `/opt/yobi/current` | 현재 release symlink 존재 | 통과 |
| Systemd | API service enabled/active | 통과 |
| Nginx | enabled/active, 설정 검사 성공 | 통과 |
| Health/readiness | HTTP 200 | 통과 |
| DB runtime user | `YOBI_APP` 연결 확인 | 통과 |
| Migration | 001, 002가 `SCHEMA_MIGRATION`에 기록 | 통과 |
| Seed 수량 | merchant 30, menu 150, evidence 300, review 600 등 최소 기준 충족 | 통과 |
| Vector | 메뉴 150개 모두 1536차원 vector 보유 | 부분 통과 |

현재 vector의 model 표기는 `yobi-semantic-hash-v1`이다. 즉 Oracle `VECTOR_DISTANCE`는 실제로 실행되지만 OCI embedding model이 생성한 vector라고 주장할 수 없다.

최근 로그의 안전한 집계에서는 Grok 및 GPT-OSS 선택, GenAI 응답 수신, `search_menus`/`recommend_categories` 도구 실행 성공을 확인했다. 그러나 assistant turn의 대부분이 최종적으로 fallback 처리되었고 주요 원인은 provider `BADREQUESTERROR`, 일부는 `RUNTIMEERROR`/rate limit이었다. 과거 `/delivery` 500 로그는 현재 release 이전 시간대에 집중되어 있으며 현재 readiness는 정상이다.

## 5. 영역별 평가

### 5.1 Frontend UI/UX — 부분 통과

재사용 가능:

- 모바일 onboarding/chat/order 화면의 시각 완성도, evidence badge, 상태 표현, 반응형 레이아웃
- 데스크톱 발표 화면의 2열 구성과 주문 패널
- 명확한 mock payment 표시와 식이 evidence 표현

수정 필요:

- onboarding 선택지가 사실상 한 개씩이고 식이 선택도 고정되어 일반 사용자 입력처럼 보이지만 데모 persona에 가깝다.
- 헤더 Cart, 주문 후 “대화 보기” 등 일부 버튼이 동작하지 않는다.
- 장바구니 수량/옵션 수정·삭제, 결제 취소, 주소 직접 입력·수정 흐름이 없다.
- 데스크톱 hero 문구 줄바꿈이 어색하다.
- 사용자 메시지 상태가 컴포넌트에만 있어 새로고침 후 서버 대화 복원이 안 된다.

### 5.2 React 구조와 상태 관리 — 부분 통과

- route와 주요 UI 모듈은 분리되어 있고 Zustand session/profile 저장은 작동한다.
- TanStack Query provider가 있으나 실제 데이터 lifecycle에는 거의 쓰이지 않는다.
- `OrderFlowPanel`이 주소·옵션·결제·리뷰 상태를 함께 소유하는 큰 컴포넌트여서 오류 복구와 단계 재진입이 어렵다.
- 서버 cart와 클라이언트 draft 상태의 source of truth가 명확하지 않은 구간이 있다.

### 5.3 FastAPI API — 부분 통과

- health, profile/session, chat, search, address, cart, checkout/payment/order/review의 기본 endpoint가 존재한다.
- 입력 검증과 구조화 오류 응답의 기본 틀은 있다.
- Master Spec의 profile PATCH, cart PATCH/DELETE, demo reset 등이 빠져 있다.
- SSE endpoint는 `respond()` 전체 처리가 끝난 뒤 결과를 한 번에 emit하므로 실제 progressive streaming이 아니다.
- 주소 후보 확인에서 브라우저가 보낸 후보 객체 전체를 신뢰하여 서버 catalog 재조회 없이 저장한다.

### 5.4 Agent loop와 Function Calling — 구현 존재, 운영 실패

- OpenAI-compatible Responses client, allowlist, Pydantic argument 검증, bounded loop, DB-backed tool 실행이 실제로 존재한다.
- 따라서 단순 키워드 챗봇만 구현된 것은 아니다.
- 다만 최근 운영 로그에서 첫 모델 응답/도구 호출 이후 continuation 단계가 대부분 실패한다.
- provider error가 발생하면 결정론적 fallback으로 전환되어 사용자 화면만 보면 정상처럼 보인다.
- Master Spec의 전체 tool surface보다 구현된 read tool 수가 적으며 mutation 계약도 API 쪽으로 분산되어 있다.
- 우선 `function_call_output` continuation payload와 provider별 호환성을 공식 문서 기준으로 수정하고 실제 최종 응답까지 검증해야 한다.

### 5.5 Oracle Repository와 Transaction — 부분 통과

- bind variable, pool, commit/rollback, payment row lock, unique constraint 기반 멱등성이 구현되어 있다.
- search에서 hard filter 후 vector ranking을 수행한다.
- `confirm_cart`가 현재 menu/option availability, 가격, 배달비, 최소주문 조건을 다시 읽지 않는다. 저장 snapshot을 그대로 확정한다.
- 단일 merchant cart 제약이 명시적으로 보장되지 않는다.
- 동시 checkout의 unique 충돌을 안정적인 기존 checkout 반환으로 변환하는 처리가 부족하다.

### 5.6 DB Schema, Migration, Seed — 부분 통과

- 적용된 001/002 checksum 기록과 seed 최소 수량은 정상이다.
- migration runner가 이미 기록된 checksum 변경을 거부하는 점은 안전하다.
- Oracle DDL의 implicit commit 특성 때문에 새 migration이 중간 실패하면 재시도 안전성이 충분하지 않다.
- Master Spec의 정규화된 `SERVICE_AREA`, category, ingredient, allergen, dietary attribute, item-option 관계 등 여러 테이블/필드가 JSON 축약 구조로 대체되었다.
- 적용된 001/002는 수정하지 않고 후속 migration만 추가해야 한다.

### 5.7 챗봇 시스템 및 성능 — 부분 통과

- fallback 응답은 빠르고, 검색/추천/장바구니 안내의 데모 경로는 작동한다.
- 실제 모델 성공률과 fallback 비율을 별도 SLO로 기록하지 않아 운영 품질을 화면 성공 여부로 오판할 수 있다.
- 대화 복원, 일반 번역, 상태 detour 대응은 제한적이다.
- 실질적인 streaming이 없어 첫 token latency 개선 효과가 없다.

### 5.8 Vector Search 및 RAG 성능 — 부분 통과

- Oracle Vector SQL과 hard filter를 실제 사용하며 100-case 로컬 retrieval 평가가 통과한다.
- 평가는 SQLite/결정론적 fixture 중심이므로 실제 Oracle/provider 품질의 증거가 아니다.
- menu vector는 deterministic semantic-hash다.
- review vector와 `MENU_KNOWLEDGE`를 이용한 완전한 hybrid retrieval은 연결되지 않았다.
- 현재 작은 데이터셋에서는 vector index 부재가 기능 장애는 아니지만 확장 성능 근거도 없다.

### 5.9 식이 Evidence 정책 — 부분 통과

- shellfish 등 severe restriction을 SQL hard filter로 강제하며 UI에 evidence 상태를 노출한다.
- “안전하다”는 무근거 확정 문구를 기본 생성하지 않는다.
- 메뉴 summary의 상태가 정규화 Evidence join이 아니라 JSON tag에서 파생되는 구간이 있어 데이터 간 불일치 가능성이 있다.
- 모델/tool 출력의 식이 주장이 항상 구체적 evidence ID에 연결된다는 계약은 충족하지 못한다.

### 5.10 Address OCR — fallback만 통과

- MIME/magic/Pillow decode, 크기 제한, bytes 비영속 처리는 적절하다.
- canonical image digest로 합성 주소 catalog를 찾는 결정론적 fallback은 존재한다.
- 실제 OCR adapter/provider와 이미지 텍스트 추출은 없다.
- 확장자 정책 및 manual correction, source image hash 보존 계약이 불완전하다.

### 5.11 Cart와 Mock Payment — 부분 통과

- 가격/옵션 금액은 서버 DB에서 계산하며 모델이 가격을 만들지 않는다.
- required option/availability를 add 시 검증한다.
- checkout idempotency key와 payment row lock, checkout당 order unique constraint가 중복 주문을 방지한다.
- 결제 확정 직전 전체 cart 재검증이 없어 add 이후 상품 상태/가격 변경을 놓친다.
- 동시 요청과 cart edit/remove API/UI의 Acceptance Coverage가 부족하다.

### 5.12 Deterministic fallback — 구조 통과, 범위 보완 필요

- 별도 fake 데이터 경로가 아니라 같은 repository/domain service/Oracle 데이터를 사용한다.
- fallback 여부를 응답 metadata로 구분한다.
- 규칙이 keyword/state pattern 중심이고 일반 질의, 번역, 복잡한 detour에서 coverage가 좁다.
- 실제 GenAI 장애를 정상 처리처럼 가리지 않도록 관측 지표와 보고 문구를 강화해야 한다.

### 5.13 Test — 로컬 기준 통과, Acceptance 미완료

확인한 결과:

- Ruff: 통과
- MyPy: 29 source files 통과
- Pytest: 35 passed
- Frontend ESLint: 통과
- Frontend Vitest: 2 passed
- TypeScript/Vite build: 통과
- Retrieval eval: 100 cases 통과, mismatch 0
- Playwright local deterministic suite: 11 passed, 9 intentional skips
- Deploy shell syntax 및 deploy Python lint: 통과

누락된 증거:

- 실제 Oracle repository의 자동화된 핵심 계약 검사
- 실제 GenAI가 tool call 이후 최종 자연어 응답까지 완주하는 smoke/E2E
- 실제 OCR provider와 manual correction
- 결제 직전 revalidation, 동시 checkout, cart edit/remove
- 공개 Primary Demo E2E 3회 연속 성공

### 5.14 Systemd, Nginx, 배포 — 부분 통과

- loopback Uvicorn, Nginx reverse proxy, service hardening, root-owned env mode 600은 적절하다.
- 현재 공개 HTTP 배포는 동작하지만 TLS는 없다. 발표용 제한된 MVP라는 경계를 명시해야 한다.
- release symlink가 dependency install/검증 완료 전에 갱신되어 배포 중간 실패 시 불완전 release를 가리킬 수 있다.
- Python dependency 범위가 완전 고정되어 있지 않아 재배포 재현성이 낮다.
- bootstrap checkpoint/resume는 있으나 같은 bootstrap을 상태 확인 없이 반복하면 안 된다.

## 6. 보존·수정·재작성·추가 분류

### 그대로 보존할 기반

- 디자인 토큰, 주요 responsive 화면과 evidence UI
- FastAPI app 구조와 Pydantic contract 기본 틀
- Oracle pool/repository와 bind/transaction 기본 패턴
- vector SQL + dietary hard filter의 실행 순서
- 서버 가격 계산과 mock payment row lock/unique 구조
- secure env, Systemd, Nginx, bootstrap checkpoint
- deterministic fallback이 같은 domain/repository를 사용하는 구조

### 수정/리팩터링할 부분

- GenAI continuation 및 provider failover/관측
- 결제 전 cart revalidation과 동시 멱등성 처리
- 주소 후보 server-side lookup/confirmation 계약
- React 서버 상태 복원, 주문 flow 상태 분리, inert control 제거
- 실제 SSE event lifecycle
- migration runner의 새 DDL resume 전략
- 배포 symlink 전환 시점과 dependency 재현성
- 완료를 과장한 기존 상태/테스트 문서

### 제한적으로 재작성할 부분

- `AgentLoop`의 Responses continuation 부분은 공식 provider 계약에 맞춰 좁게 재작성한다.
- Address OCR 계층은 adapter interface 중심으로 분리하되 canonical hash fallback은 보존한다.
- Cart confirmation은 현재 repository snapshot 확정이 아니라 재조회/reprice domain operation으로 교체한다.

### 추가 구현할 부분

- 누락 API: profile update, cart update/delete, demo reset 및 필요한 조회 계약
- 주소 직접 입력/수정과 server-owned candidate token
- OCI OCR adapter 또는 명확한 제한 모드 provider, timeout/fallback
- evidence-ID가 연결된 dietary claim DTO와 hybrid knowledge/review retrieval
- Master Schema의 꼭 필요한 정규화 항목을 위한 append-only 003+ migration
- frontend cart edit/remove, conversation restore, error recovery, 발표용 polish
- 실제 Oracle/GenAI/Primary Demo acceptance 검사와 최종 runbook/report

## 7. 우선순위 및 구현 순서

1. 현재 상태를 Secret 재검사 후 최초 Git checkpoint로 보존하고 `codex/master-spec-completion` 브랜치를 만든다.
2. 공식 Responses/OCI API 계약과 안전한 로그를 기준으로 Agent Loop continuation을 수정하고 실제 모델 최종 답변을 확인한다.
3. cart confirmation을 현재 DB 상태로 재조회/reprice/revalidate하고 동시 멱등성을 보강한다.
4. 주소 후보를 서버 소유 token으로 확정하고 OCR adapter + canonical fallback + manual correction을 구현한다.
5. 필요한 append-only migration과 evidence/RAG 계약을 구현한다. 적용된 001/002는 변경하지 않는다.
6. 누락 API/React 흐름과 UI polish를 완성한다.
7. 가장 좁은 기존 테스트와 필요한 고위험 경계 테스트를 추가하고 로컬 전체 회귀를 실행한다.
8. 기존 VM/DB에 비파괴적으로 배포하고 Oracle/GenAI/fallback을 각각 검증한다.
9. 공개 Primary Demo E2E를 3회 연속 실행하고 최종 Test Report와 Demo Runbook을 갱신한다.

## 8. 안전 경계

- 기존 OCI 자원, ADB, VM, API key, IAM policy는 삭제·재생성·확대하지 않는다.
- Secret 값을 출력하거나 채팅으로 요구하지 않는다.
- 이미 적용된 migration 파일을 수정하지 않고 append-only migration을 사용한다.
- bootstrap은 현재 checkpoint와 실패 원인을 확인한 뒤 필요한 단계만 수행한다.
- 실제 provider가 제한되면 deterministic fallback 성공과 실제 GenAI 성공을 별도 결과로 보고한다.
- 최종 완료 판정은 공개 배포와 Primary Demo E2E 3회 연속 성공까지 유보한다.
