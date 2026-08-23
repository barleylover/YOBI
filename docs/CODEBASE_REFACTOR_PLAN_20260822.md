# YOBI 코드베이스 검토 및 장기 리팩터링 계획

기준일: 2026-08-22
기준 브랜치: `codex/team-feedback-completion-20260821`
범위: 추천 로직, 백엔드/API/DB, 프런트엔드, 테스트·안정성, 성능
제외: 보안 감사와 보안 정책 변경

## 1. 이번 검토의 경계

이번 작업은 현재 로컬 worktree와 추적 중인 GitHub 브랜치를 기준으로 수행했다. 기존의
사용자 소유 미추적 설계 이미지는 변경하지 않았다. 로컬 SQLite와 테스트 픽스처만
사용했으며, Oracle/OCI 운영 데이터 변경, 배포, Git 커밋·푸시·PR 갱신은 수행하지 않았다.
따라서 이 문서에서 “검증됨”은 별도 표기가 없는 한 현재 로컬 소스와 로컬 테스트에 대한
의미다. 과거 문서의 배포 기록을 현재 운영 상태로 재해석하지 않는다.

## 2. 현재 구조와 집중 위험

구조화 추천의 현재 계약은 다음과 같다.

```text
고정된 release family와 criteria
  -> 객관적 eligibility와 다중 recall channel
  -> fusion/rerank/diversity
  -> 서버 shortlist(최대 15)
  -> 선택 모델이 shortlist 안에서 정확히 3개 ID 선택
  -> 서버 hard-constraint/evidence/diversity 재검증
  -> 별도 presentation 생성
  -> snapshot + request ledger 영속화
  -> 실패 시 같은 shortlist 기반 deterministic fallback
```

이는 “서버가 최종 3개 순서를 먼저 고정하고 LLM은 설명만 한다”는 이전 계약과 다르다.
같은 `request_id`는 저장된 canonical 결과를 재생하며, provider 호출 이후 불명확한 요청을
임의로 재호출하지 않는다.

현재 가장 큰 유지보수 집중점은 다음과 같다.

| 영역 | 현재 크기/신호 | 핵심 위험 |
|---|---:|---|
| SQLite repository | 약 10,064줄 | 여러 bounded context와 순수 규칙이 한 클래스에 결합 |
| Oracle repository | 약 9,399줄 | SQLite와 동작 계약이 쉽게 어긋날 수 있음 |
| `ChatService` | 약 3,353줄 | 대화 상태, 추천, 카드 조립, 폴백 책임 혼재 |
| structured recommendation service | 약 1,467줄 | 요청 수명주기, retrieval, provider, snapshot 책임 혼재 |
| FastAPI `main.py` | 약 1,458줄 | route와 오류 매핑이 한 파일에 집중 |
| `ChatPage` | 약 874줄 | 복구·polling·criteria·결과·주문 상태 결합 |
| `OrderFlowPanel` | 약 841줄 | 옵션 선택, 장바구니 편집, UI 표현 결합 |
| 정적 복잡도 확장 감사 | C901 78건, PLR0915 45건 | 정상 lint는 통과하지만 장기 분할 필요 |

이 수치는 big-bang 재작성을 정당화하지 않는다. 오히려 DB 방언 parity와 요청 재실행
계약 때문에, 순수 규칙과 adapter seam을 먼저 만든 뒤 작은 단계로 분할해야 한다.

## 3. 이번 변경에서 완료한 리팩터링

### 추천과 요청 안정성

- 점수 가중치를 `RANKING_SCORE_WEIGHTS` 하나로 모아 정책 manifest와 실제 계산이 같은
  값을 사용하도록 했다. 기존 정책 SHA와 결과 순서는 유지한다.
- v2 가격 band 경계를 공유 함수로 옮겨 SQLite와 Oracle의 중복 판정을 제거했다.
- `max_spice_level`만 선택한 criteria도 명시적 선호로 인정하도록 빈 criteria 판정을
  수정했다.
- request/comparison keyed lock을 참조 수명 기반 registry로 교체했다. 같은 키는 직렬화하고,
  마지막 waiter가 끝나면 lock을 제거해 장기 실행 시 키 수가 무한히 늘지 않는다.
- 세션별 preview 계측을 2,048개 LRU 상한으로 제한했다.

### 백엔드/API/DB

- 구조화 추천 예외의 HTTP 상태·오류 코드 매핑을 `app/api/errors.py`로 분리했다.
- deprecated 422 상수를 현재 FastAPI/Starlette 명칭으로 교체했다.
- SQLite/Oracle이 공유해야 하는 demo/release cardinality와 upgrade 허용 규칙을
  `app/db/runtime_contract.py`로 옮겼다.
- v3 장바구니 재검증의 가격·매운맛·halal/vegan 판정과 오류 우선순위를 공통 도메인
  규칙으로 옮겼다.
- 옵션 현지화 ID 완전성 및 제한된 offline 주문 메모 번역을 공통 규칙으로 옮겼다.
- 네 생성기/서비스에 복제된 provider token telemetry 파서를 공통화했다. 기본 소비자는
  input/output만, 추천 계측은 total/cache/reasoning 상세까지 받는 기존 계약을 보존한다.

### 프런트엔드

- API 호출의 timeout/abort/오류 코드 파싱을 공통화하고, 이전에 무기한 대기하던 preference
  catalog 요청에도 8초 제한을 적용했다. 주소 업로드는 30초 제한을 유지한다.
- criteria 비교를 객체 키 순서에 독립적인 canonical 비교로 바꾸고, menu projection 탐색을
  cycle-safe iterative 탐색으로 분리했다.
- 주문 옵션 선택/충돌/default 계획/가격 합계를 순수 함수로 분리했다.
- 필수 옵션의 안전한 기본값이 없으면 note 단계로 잘못 진행하지 않도록 막았다.
- 기존 장바구니 항목 편집에서 빈 메모를 보내면 과거 메모가 실제로 지워지도록 했다.
- 주요 route를 lazy chunk로 분리했다. 초기 단일 JS는 리팩터링 전 605.08 kB에서
  258.57 kB로 줄었다.
- `make build`에 초기 entry와 각 JS chunk의 uncompressed 300 KiB 예산을 추가했다.
- feature 이미지는 실제 크기를 선언하고 lazy decode하여 불필요한 초기 layout/network
  작업을 줄였다.

### 테스트와 개발자 경험

- 손상되거나 다른 Python 버전이 남긴 전역 mypy cache가 전체 검증을 막지 않도록 프로젝트
  전용 cache 경로를 사용한다.
- `make test-backend`와 `make test-frontend`를 분리하고 `make test`가 둘을 순서대로 실행한다.
- 가격 경계, 빈 criteria, keyed lock 수명, API 오류 계약, runtime cardinality, provider usage,
  DB 공통 규칙, API timeout, criteria 복구, 주문 옵션 순수 로직 회귀 테스트를 추가했다.

## 4. 장기 실행 계획

### Release 1 — 저장소 경계 확정 (1~2주)

목표는 거대 repository를 바로 쪼개는 것이 아니라, 두 DB 구현이 반드시 공유해야 할
계약을 executable parity test로 고정하는 것이다.

- `YobiRepository`를 catalog/release, recommendation, conversation, cart/order, localization
  프로토콜로 분리하되 기존 façade는 유지한다.
- SQLite와 Oracle 공통 테스트를 protocol contract suite로 만들어 같은 입력/오류 코드/
  상태 전이를 검증한다.
- SQL 문자열과 row mapping은 방언별 adapter에 남기고, 순수 판정은 domain에 둔다.
- query count와 단계별 latency를 현재 recommendation timing event에 추가한다.
- Oracle 변경은 read-only 계획 및 별도 운영 승인 전에는 실행하지 않는다.

완료 조건: 전체 회귀 통과, public API schema 무변경, SQLite contract 전수 통과, Oracle은
연결 가능한 승인 환경에서 같은 contract suite 및 query-plan evidence 통과.

### Release 2 — 추천 orchestration 분할 (2~3주)

- `StructuredRecommendationService`에서 request lifecycle, candidate retrieval, model selection,
  presentation, snapshot materialization을 각각 작은 collaborator로 추출한다.
- shortlist payload와 persisted snapshot 사이에 명시적 typed mapper를 둔다.
- deterministic fallback을 독립 정책 객체로 만들고 LLM 선택과 동일한 hard constraint
  validator를 재사용한다.
- retry/model fallback 횟수와 “한 사용자 요청의 provider attempt 수”를 별도 명칭으로
  기록해 dispatch와 provider attempt를 혼동하지 않게 한다.
- criteria v2/v3 호환 코드는 schema adapter에 모으고 새 기능은 최신 schema에만 추가한다.

완료 조건: 동일 seed에서 menu ID/order, fallback, replay 결과 golden parity; interruption과
동시 요청 테스트; provider-disabled/timeout/invalid-output 경로 전수 통과.

### Release 3 — 대화와 API 모듈화 (2주)

- `main.py` route를 profile/session, recommendation, catalog, cart/handoff, operator health
  router로 이동한다.
- `ChatService`의 상태 전이, intent/slot 해석, recommendation bridge, response card 조립을
  분리한다.
- 문자열 예외를 외부 API에서 안정된 typed application error로 변환하되 저장소의 기존
  오류 문자열 호환 layer는 한 release 유지한다.
- OpenAPI snapshot과 representative HTTP contract test를 CI artifact로 남긴다.

완료 조건: OpenAPI breaking diff 0, 기존 E2E 사용자 여정 동일, route별 dependency override
테스트 가능, `main.py`는 wiring과 lifespan 중심으로 축소.

### Release 4 — 프런트 상태 경계 분할 (2주)

- `ChatPage`를 session recovery, preference commit, recommendation polling, result actions
  hook/reducer로 분리한다.
- `OrderFlowPanel`을 명시적 state machine 또는 reducer로 옮겨 단계 전이를 exhaustively
  테스트한다.
- `api.ts`를 session/recommendation/catalog/cart client로 분리하고 공통 transport만 공유한다.
- 225 KiB `productI18n` chunk를 locale별 동적 bundle로 나눈다.
- focus restoration, keyboard carousel, request cancellation을 component contract test로 고정한다.

완료 조건: 초기 JS entry와 모든 chunk 300 KiB 이하 유지, 주요 route별 loading/error/retry
테스트, 네 Playwright viewport 전수 통과, 기존 표시 문구·데모 결제 경계 유지.

### Release 5 — 데이터 접근 성능 (2~3주)

- 추측으로 index를 추가하지 않고, 실제 SQLite `EXPLAIN QUERY PLAN`과 승인된 Oracle
  `DBMS_XPLAN`에서 비용이 큰 추천 query를 선정한다.
- candidate recall, evidence hydration, live projection에서 N+1 여부를 query count로 측정하고
  batch read mapper를 적용한다.
- process-local cache는 모두 상한·TTL·release identity를 갖게 하고 release 전환 시
  무효화 테스트를 둔다.
- warm/cold/provider/concurrency benchmark를 분리해 충분한 표본에서만 percentile을 보고한다.

완료 조건: 기능 parity와 query plan evidence, warm positive scenario별 100회·process-cold
20회·provider path 30회·3-way concurrency라는 기존 release gate 충족. 축소 smoke는
정확성/경향 확인으로만 표기한다.

### Release 6 — 레거시 제거와 문서 정합성 (지속)

- v1 chat/ranking/cache 경로의 실제 호출자와 배포 traffic을 확인한 뒤 deprecation한다.
- 현재 구현과 충돌하는 과거 문서는 historical 표시 또는 archive index로 이동한다.
- 무사용 route, schema adapter, compatibility alias는 한 release의 관찰 기간 뒤 제거한다.
- 매 release마다 현재 source SHA, DB release family, 테스트와 운영 검증의 경계를 별도로 기록한다.

완료 조건: 정적 import/route 검색만이 아니라 runtime/배포 evidence가 있는 제거 목록, rollback
가능한 작은 PR, 문서와 코드의 현재 recommendation contract 일치.

## 5. 지속 검증 매트릭스

| 계층 | 매 변경 | release 후보 | 운영 승인 환경 |
|---|---|---|---|
| 정적 검사 | Ruff, mypy, ESLint, TypeScript | 동일 | 동일 source SHA 확인 |
| 단위/통합 | backend pytest, Vitest | 전체 재실행 | 필요한 read-only parity |
| API/UI | focused contract test | 네 viewport Playwright | public smoke |
| 추천 품질 | deterministic/golden/fallback | evaluation + 충분한 샘플 | 승인된 provider 표본 |
| 성능 | bundle budget, 축소 repo smoke | 정식 warm/cold/provider/concurrency gate | query plan과 public timing |
| DB | SQLite migration/seed | Oracle dry-run/plan | 별도 승인 후 migrate/rollback |

## 6. 남아 있는 명시적 위험

- 두 repository와 `ChatService`의 크기는 이번 seam 추출 후에도 크다. 한 PR에서 물리적으로
  분해하면 DB parity와 재실행 의미를 동시에 잃을 위험이 있어 후속 release로 분리했다.
- Python 3.14 환경에서 Starlette TestClient가 `httpx` deprecation 경고를 낸다. 현재 기능
  실패는 아니지만 dependency 지원표를 확인한 뒤 별도 업그레이드해야 한다.
- Node 26 test worker가 file-backed localStorage가 없다는 experimental 경고를 낸다. jsdom
  테스트 결과에는 영향이 없지만 지원 기준 Node 20과 CI Node 버전을 명시적으로 고정하는
  작업이 필요하다.
- 현재 feature hero PNG는 2.8 MB다. 초기 route에는 포함되지 않지만 feature dialog를 열면
  전송된다. 시각 QA와 asset provenance를 보존한 WebP/AVIF 변환을 별도 변경으로 검토한다.
- 로컬 deterministic fallback 통과는 OCI provider 품질이나 Oracle 운영 성능을 증명하지 않는다.

## 7. 변경 원칙

1. public API, criteria, snapshot, error code를 먼저 characterization test로 고정한다.
2. 한 단계에서는 한 경계만 옮기고, 동작 변경과 파일 이동을 같은 대형 diff에 섞지 않는다.
3. SQLite/Oracle 공통 규칙은 한 구현을 공유하고 SQL·transaction 차이만 adapter에 남긴다.
4. 성능 수치는 표본과 측정 경로를 함께 적고, 축소 실행으로 percentile을 주장하지 않는다.
5. 운영 DB 변경·배포·provider 호출·Git 원격 쓰기는 각각 별도 승인과 검증 gate를 거친다.

## 8. 현재 worktree 검증 결과

기능 변경 전체에 대한 표준 검증은 다음과 같다.

- `make test`: Ruff 통과, mypy 115개 source 통과, backend `766 passed`, frontend
  `17 files / 78 tests passed`.
- 최종 diff 재검토에서 unknown price band와 첫 menu projection 순서, stale required option
  보강 후: Ruff/mypy 재통과, backend focused `27 passed`, frontend 전체
  `17 files / 80 tests passed`.
- `make build`: TypeScript/Vite 통과. 초기 entry 258.57 kB(252.5 KiB), 가장 큰 개별
  JS chunk도 258.57 kB로 300 KiB 예산 통과. 리팩터링 전 단일 JS는 605.08 kB였다.
- `make e2e`: 로컬 임시 SQLite와 네 viewport에서 `25 passed`, 조건부 시나리오
  `35 skipped`, 실패 0.
- `make evaluate`: 100개 질의에서 constraint, canonical top3, golden rank, evidence,
  price, option 실패가 모두 0. 멀티턴 acceptance는 369 assertions, 실패 0.
- 축소 repository 성능 smoke(`warm=3`, `process-cold=2`): 상태 `INCONCLUSIVE`.
  warm retrieval median 269.334 ms, process-cold median 345.937 ms였다. 검토 전 같은 축소
  실행의 229.540 ms와 377.748 ms에 비해 방향이 엇갈리므로 개선 또는 퇴행을 주장하지
  않는다. 정식 percentile 판단은 Release 5의 충분한 표본 gate를 사용한다.

남은 경고는 Python 3.14의 Starlette/httpx deprecation과 Node 26의 experimental
localStorage 안내다. 둘 다 현재 테스트 실패는 아니며 위 위험 목록의 후속 항목으로 남겼다.
