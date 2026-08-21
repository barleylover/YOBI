# 팀 피드백 12건 개선·배포·QA 완료 기록

- 기준 브랜치/커밋: `codex/master-spec-completion` @ `935186c`
- 작업 브랜치: `codex/team-feedback-completion-20260821`
- 최종 코드 커밋: `fee180194ae0cede0ae822d103635a790f825258`
- 최종 공개 릴리스: `20260821T010351Z-44d5099b3f4b`
- 공개 주소: `http://217.142.131.216`
- 작성일: 2026-08-21 (Asia/Seoul)

## 1. 기준 코드베이스를 읽고 확정한 현재 구조

### 1.1 사용자 여정과 프런트엔드 상태

React SPA는 `welcome → language/country → profile/preferences → fixed demo address → chat/recommendation → options/note → delivery review → Yogiyo handoff` 순서로 동작한다. Zustand 세션 스토어가 프로필, 세션 ID, 주소, 장바구니 관련 화면 상태를 보존하며, 서버의 `state_version`이 대화·선택 상태의 최종 권위다.

핵심 UI 경계는 다음과 같다.

- 추천 결과는 서버가 저장한 snapshot과 presentation을 카드로 표시한다.
- `Menu` 채널은 추천 대화와 별개의 탐색 진입점이다.
- 장바구니는 한 식당만 허용하는 서버 계약을 따른다.
- 결제·주문·Yogiyo 이동은 실제 외부 거래가 아닌 데모 핸드오프다.

### 1.2 백엔드와 추천 경계

FastAPI 백엔드는 SQLite와 Oracle이 같은 repository 계약을 구현하도록 구성돼 있다. 공개 배포는 Oracle 26ai를 사용하고, 현재 catalog 원천은 `YOGIYO_PUBLIC_WEB`이다.

구조화 추천 v2/v3의 실제 권한 경계는 다음과 같다.

1. 서버가 세션 조건과 hard filter를 적용해 candidate pool을 만든다.
2. 서버가 bounded shortlist를 구성한다.
3. LLM은 그 shortlist 안에서 선택·순서를 제안한다.
4. 서버가 메뉴 소유권, 선택 조건, 근거, 중복, 개수와 출력 스키마를 다시 검증한다.
5. 동일 request ID replay는 저장된 결과를 반환한다.
6. provider 실패나 잘못된 출력은 결정론적 `SEARCH_FALLBACK`으로 종료된다.
7. 메뉴 카드용 presentation은 추천 선택과 별도 단계이며, source 설명·YOBI 설명·review 요약을 서로 다른 필드로 저장한다.

따라서 이번 작업은 UI 문구만 바꾸는 방식으로 해결할 수 없었다. Oracle/SQLite projection, presentation validator, deterministic fallback, 대화 event, 장바구니 순서, session hydration, synthetic enrichment release를 함께 고쳤다.

### 1.3 데이터의 사실 경계

- canonical 외부 메뉴: 15,085개
- 추천 지식에 고신뢰로 연결된 활성 메뉴 profile: 4,558개
- 이번 synthetic enrichment가 관리하는 halal-friendly row: 1,519개
- source localization 활성 행: 영어 582개, 일본어 1,442개
- synthetic review 행: 27,348개

`halal-friendly`는 정식 할랄 인증 정보가 아니다. 현재 공개 원천에 인증 데이터가 없으므로, 명백한 돼지고기·주류 신호를 제외한 데모용 친화 후보라는 의미만 갖는다.

## 2. 실행 계획과 완료 조건

이번 작업은 다음 순서로 수행했다.

1. 기준 커밋의 UI, API, Oracle/SQLite repository, 추천·presentation, cart/order, 배포 스크립트와 테스트를 읽는다.
2. 별도 브랜치에서 12건을 각각 재현 가능한 상태 계약으로 바꾼다.
3. 각 계약을 backend/frontend 회귀 테스트로 고정한다.
4. 로컬 전체 정적검사·단위테스트·브라우저 E2E를 통과시킨다.
5. additive enrichment release를 만들고 protected base fingerprint가 변하지 않았는지 검증한다.
6. 공개 배포 후 API와 실제 브라우저에서 다양한 경로를 누른다.
7. 발견된 추가 결함을 다시 코드·테스트·배포에 반영한다.
8. 마지막 릴리스의 commit, health/readiness, DB 감사값, 임시 네트워크 제거를 확인한다.

완료 조건은 “화면이 한 번 보임”이 아니라 아래 전부다.

- 12개 피드백별 기능 계약 충족
- SQLite/Oracle 동작 일치
- source/review/YOBI 설명 provenance 분리
- 장바구니·옵션·새로고침 상태 복구
- 로컬 테스트와 브라우저 E2E 통과
- 공개 릴리스의 정확한 Git commit 확인
- temporary SSH/LB 경로 제거
- synthetic/mock/live 경계 문서화

## 3. 피드백 12건별 진단과 해결

### 3.1 최소주문금액 표시

진단:

- merchant의 최소주문금액은 DB에 있었지만 추천 `MenuSummary` projection과 카드 계약에 포함되지 않았다.
- 탐색 랭킹도 같은 값을 표시할 방법이 없었다.

해결:

- `MenuSummary.minimum_order_amount`를 추가했다.
- SQLite와 Oracle의 추천·탐색 query projection을 동일하게 연결했다.
- 추천 카드와 Food rankings 카드에 0보다 큰 경우 작은 `Minimum order` chip/text를 표시한다.
- 장바구니에는 현재 subtotal과 최소주문 부족액을 함께 계산한다.

### 3.2 YOGIYO 설명 누락·미번역·한글 노출

진단:

- 여러 카드의 presentation을 한 번에 처리해 한 항목의 validation 실패가 다른 항목까지 무효화할 수 있었다.
- source 설명 번역에서 숫자·수량 표기 정규화 차이가 전체 번역을 거부시키는 경우가 있었다.
- fallback이 음역 또는 원문 한글을 비한국어 UI에 그대로 내보낼 수 있었다.
- source 설명이 실제로 없는 메뉴와, 번역이 실패한 메뉴가 UI에서 구분되지 않았다.

해결:

- presentation을 메뉴별로 격리해 한 카드 실패가 다른 카드에 전파되지 않게 했다.
- 검증된 source 번역을 항목별로 보존하고, 숫자·수량 비교는 의미가 유지되는 정규화 비교를 사용한다.
- source description fallback은 대상 언어에 맞춘 안전한 문장만 허용한다.
- 음역·한글 누출·수량 변경이 감지되면 잘못된 `YOGIYO:` 문구를 표시하지 않는다.
- 원천 설명이 실제로 비어 있으면 설명을 꾸며내지 않고 `YOGIYO:` 행 자체를 숨긴다.

결과적으로 “원천이 없어서 안 보임”은 정직하게 유지하고, “원천이 있는데 한글 그대로 보임”은 차단했다.

### 3.3 전체의 1/3 halal-friendly 지정

진단:

- 기존 enrichment의 halal 값이 데모 필터를 충분히 시연할 수 있는 분포가 아니었다.
- 초기 금지어에는 `한돈`, `돈카츠`, `돈코츠`, `차슈`, `잠봉` 같은 한국어·외래어 별칭이 빠져 있었다.
- 랭킹 browse path가 추천 strict filter와 같은 hard constraint를 적용하지 않는 결함도 있었다.

해결:

- 활성 추천 profile 4,558개 중 최근접 정확한 1/3인 1,519개를 `halal_fit=true`로 생성한다.
- 이름·설명·분류·옵션에 명백한 돼지고기, 돼지 부위, 햄류, 조리 주류, 술 메뉴 신호가 있으면 제외한다.
- v8에서 `한돈`, 돈가스 계열, 돈코츠, 차슈, 하몽, 잠봉, 포크, 부대찌개, 뼈해장국, 맛술·미림 등 별칭 범위를 확장했다.
- Food rankings와 K-pop feature에도 세션의 strict dietary filter와 hard-conflict 검사를 동일하게 적용한다.
- UI 문구를 인증처럼 보이는 `Halal: yes`에서 `Halal-friendly: yes`로 고쳤다.

배포 DB 감사:

- `menu_profile_count=4558`
- `halal_fit_count=1519`
- `expected_nearest_one_third=1519`
- `halal_exclusion_conflict_count=0`
- generator: `yobi-synthetic-enrichment-v8-halal-alias-coverage`

주의: 이는 합성 데모 metadata이며 정식 인증이 아니다. 가게·공급망·도축 방식까지 확인하는 실제 할랄 판정으로 사용하면 안 된다.

### 3.4 Menu 기능 목업

진단:

- 하단 `Menu` 버튼은 존재했지만 실제 사용자 행동으로 이어지는 세 기능이 없었다.
- 주문수와 한국 전체 랭킹의 실제 운영 데이터는 없다.

해결:

- `Edit my info`: 기존 선호도 선택 화면으로 이동한다.
- `Food rankings`: 현재 delivery area와 세션 hard filter 안에서 최대 20개를 반환한다.
  - Most reviewed는 source menu review count를 우선 사용한다.
  - Most ordered는 source review count 기반의 결정론적 데모 proxy다.
  - Popular in Korea도 source count 기반 결정론적 데모 proxy다.
  - 각 metric label과 안내문에서 source 값인지 proxy인지 명시한다.
- `K-POP ANIMATION`: Gimbap, Korean wheat noodles, Tteokbokki, Gukbap, Hotteok, Seolleongtang, Eomuk concept에 연결된 현재 지역 메뉴를 대표 1개씩 보여준다.
- 이 화면에서 고른 메뉴도 서버 browse snapshot으로 허가하고 기존 옵션·장바구니 흐름에 연결한다.

### 3.5 같은 가게의 추가 메뉴가 있을 때만 upsell

진단:

- 장바구니 추가 후 항상 “Would you like anything else...”를 보여줘, 실제로 표시할 다른 메뉴가 없는 경우 빈 단계가 생겼다.

해결:

- 현재 merchant의 호환·판매 가능 메뉴를 현재 메뉴와 이미 담긴 메뉴를 제외해 조회한다.
- 결과가 1개 이상일 때만 upsell 화면을 표시한다.
- 0개이면 바로 delivery 단계로 진행한다.

### 3.6 마지막 Back to YOBI 전체 초기화

진단:

- 일반적인 router back은 이전 chat과 cart를 되살릴 수 있으므로 “새 여행 시작” 계약이 아니었다.
- 핸드오프 상단 화살표와 최종 초기화 버튼이 같은 접근성 이름을 써 자동화와 스크린리더가 혼동할 수 있었다.

해결:

- 마지막 핸드오프 버튼은 `yobi-` prefix의 session/local storage, CacheStorage, in-memory Zustand session/profile/order state를 초기화한다.
- client session ID를 비운 뒤 `/start`로 replace 이동한다.
- 서버 감사용 과거 session row를 파괴하지는 않는다.
- 상단 화살표는 `Back to menus`, 마지막 초기화 CTA만 `Back to YOBI`로 이름을 분리했다.

공개 브라우저에서 마지막 CTA 후 `/start`의 Language & region 화면을 확인했고, 이전 session URL을 다시 열어도 기존 chat/cart가 복구되지 않고 welcome으로 이동하는 것을 확인했다.

### 3.7 장바구니 팝업

해결:

- 헤더 장바구니 버튼에서 `CartSheet` dialog를 연다.
- 메뉴명, 선택 옵션, 수량, 메뉴 금액, subtotal, delivery fee, 예상 총액, 최소주문 부족액을 표시한다.
- 수량 `+/-`, 개별 삭제, 주문 계속하기를 제공한다.
- 서버 cart version을 기준으로 mutation 후 최신 preview를 다시 반영한다.

### 3.8 Try recommendation again 제거

진단:

- `Try recommendation again`과 `See other menus`가 모두 추천 결과를 다시 탐색해 의미가 겹쳤다.

해결:

- retry CTA를 제거하고 `See other menus`와 `Edit filters`만 유지했다.
- provider 실패는 별도 상태·fallback으로 처리하므로 결과 화면에 중복 CTA가 필요하지 않다.

### 3.9 익숙한 매운맛 baseline 문구 제거

`Compare the menu with the familiar spice baseline for your selected country` 문구와 이를 만드는 UI 경로를 제거했다. 메뉴별 실제 설명과 무관한 고정 문구가 더 이상 카드에 나타나지 않는다.

### 3.10 Change menu → Change options 오류

진단:

- `SELECT_MENU`/`REJECT_MENU` 후 이전 메뉴의 option selection과 risk acknowledgment가 남았다.
- 비동기 option 요청과 frontend cache가 새 메뉴 상태를 덮어쓸 수 있었다.

해결:

- 메뉴 변경 event에서 option selections와 risk acknowledgments를 SQLite/Oracle 모두 초기화한다.
- frontend는 서버 `state_version`과 authoritative `selected_menu` projection을 다시 hydrate한다.
- 이전 요청을 중단하고 현재 메뉴 ID에 해당하는 옵션만 반영한다.
- `Change options`는 현재 cart item의 옵션을 편집하는 경로로 복귀한다.

### 3.11 장바구니 제거·재추가와 타 가게 반복 오류

진단:

- 타 merchant 메뉴를 고른 뒤 옵션 localization을 먼저 기다려 약 24초 뒤에야 cart conflict가 나타났다.
- reload 후 browse/ranking에서 고른 `selected_menu` projection이 사라져 cart만 남는 상태가 있었다.
- 메뉴 제거 후 builder와 cart 상태가 서로 다른 버전을 볼 수 있었다.

해결:

- cart merchant ownership을 옵션 API보다 먼저 확인한다.
- `Clear cart and continue`와 `Keep current cart`를 즉시 제공한다.
- ranking/K-pop pick은 `precomputed_only=true` 옵션 경로를 사용해 새 LLM 호출을 하지 않는다.
- `ConversationView.selected_menu`가 현재 선택 메뉴를 항상 반환하도록 해 reload를 복구한다.
- cart 수량 변경·삭제 후 order builder도 최신 cart preview로 동기화한다.
- 실제 runtime localization이 필요한 정상 경로에는 35초 timeout과 명시적 loading status를 둔다.

공개 측정에서 cross-merchant conflict는 즉시 나타났고, cart clear 후 precomputed options API는 0.05초, UI 옵션 화면은 약 1.5초 안에 열렸다.

### 3.12 YOBI 설명에 리뷰가 섞이는 심각 결함

근본 원인:

- presentation prompt가 음식 지식, 메뉴 source 설명, synthetic review snippets를 한 입력 묶음으로 제공했다.
- 출력 schema가 필드를 나눴지만 validator가 `yobi_short_explanation`과 `yobi_long_explanation`의 리뷰 어휘·review evidence 사용을 충분히 금지하지 않았다.
- 따라서 모델이 리뷰를 잘 요약한 문장을 세 필드에 반복해도 구조 검증을 통과할 수 있었다.
- batch 단위 실패와 결정론적 fallback도 같은 provenance 경계를 강제하지 않았다.

해결:

- prompt에서 cultural/menu knowledge, source description, review snippets의 역할을 명시적으로 분리했다.
- YOBI short/long 설명은 외국인이 자국 언어·문화로 음식의 정체, 맛, 식감, 먹는 방식을 이해하도록 하는 내용만 허용한다.
- YOBI 필드에 `reviewers`, `diners`, rating, packaging, review-count 같은 review signal이 있으면 validation을 거부한다.
- YOBI 설명의 evidence/review ID 소유권을 분리하고 review 근거 사용을 막는다.
- `review_summary`는 synthetic review snippets만 사용할 수 있고 `What diners say`에만 표시한다.
- 잘못된 한 항목만 deterministic cultural fallback으로 교체하고 다른 정상 항목은 보존한다.
- deterministic fallback도 같은 short/long/review 분리 계약을 따른다.

공개 결과 확인:

- 카드 YOBI: kimchi fried rice의 조리 방식, 새콤·감칠맛·매운맛 성격 설명
- Additional Explanation YOBI: 뜨거운 온도, 볶은 쌀의 바삭함과 전체 식감 설명
- What diners say: rating과 taste/texture/value/portion/packaging review 요약만 표시

세 영역의 내용과 근거가 더 이상 중복되지 않았다.

## 4. 추가 QA에서 발견하고 해결한 결함

### 4.1 v3 요청 재검증과 strict underfill

- live criteria revalidation이 v3 payload를 잘못 거부하던 문제를 수정했다.
- strict hard filter 결과가 1~2개뿐일 때 LLM에 3개 선택을 강요하지 않는다.
- `STRICT_MATCH_UNDERFILLED`의 `SEARCH_FALLBACK`으로 가능한 메뉴만 반환하고 provider dispatch는 0이다.
- frontend는 이를 오류 카드가 아니라 “조건에 맞아 고른 결과”로 표시한다.

### 4.2 browse filter 누락

Food rankings/K-pop feature가 추천과 달리 halal/vegan 등의 exact filter를 우회하던 경로를 제거했다. SQL prefilter 뒤에 동일 hard-conflict 검증을 수행한다.

### 4.3 presentation batch blast radius

한 메뉴의 번역·review 문장 수·component coverage 오류가 세 카드 전체를 fallback시키던 문제를 per-item 처리로 격리했다.

### 4.4 release family ID 충돌

긴 release family ID를 160자로 단순 자르면서 서로 다른 enrichment가 같은 ID가 되는 충돌을 발견했다. bounded ID 끝에 내용 hash를 포함하도록 바꿔 v5/v7/v8 activation이 실제 runtime pointer에 반영되게 했다.

### 4.5 fallback의 한국어·음역 누출

영어/일본어 fallback에서 source 원문 한글이나 음역만 반환하는 경우를 차단하고, 검증 가능한 대상 언어 문장이 없으면 해당 source 행을 숨긴다.

### 4.6 한국어 돼지고기 별칭 누락

공개 strict-halal Food rankings에서 `[1.5인] 한돈폭탄 ...`이 노출되는 것을 직접 발견했다. v8 exclusion alias를 확장하고 재배포한 뒤 공개 상위 20개 이름·설명에서 돼지고기/주류 금지 패턴 0건을 확인했다.

### 4.7 collection pick reload 손실

랭킹에서 선택한 메뉴가 reload 후 사라지던 문제를 conversation의 authoritative selected-menu projection으로 복구했다. 공개 reload 후 `meal_need_state.selected_menu_id`와 `selected_menu.menu_id`가 모두 `yogiyo_489611_929937734`로 일치했다.

### 4.8 E2E helper race

옵션 loading status를 추가한 뒤 테스트 helper가 짧은 중간 상태를 완료 상태로 오인해 4건이 실패했다. 실제 옵션 API 로그는 6ms였으므로 제품 timeout이 아니었다. helper가 option card 또는 note screen 중 실제 완료 상태를 기다리도록 고친 뒤 전체 E2E를 재통과시켰다.

### 4.9 핸드오프 접근성 이름 충돌

공개 QA에서 상단 뒤로가기와 마지막 초기화 버튼이 모두 `Back to YOBI`로 읽히는 것을 발견했다. 상단은 `Back to menus`, 마지막 초기화만 `Back to YOBI`로 분리하고 테스트·재배포했다.

## 5. 검증 결과

### 5.1 로컬 자동 검증

| 범위 | 결과 |
|---|---:|
| Backend Pytest | 698 passed, 기존 Starlette deprecation warning 2건 |
| Ruff (`backend scripts`) | PASS |
| MyPy (`backend/app backend/evaluation scripts`, Python 3.12) | 108 source files, 0 issue |
| Frontend Vitest | 15 files, 71 passed |
| Frontend ESLint | PASS |
| Frontend production build | PASS |
| Local Playwright | 25 passed, 35 intentional skips |

Vite는 500 kB 초과 chunk advisory를 출력하지만 build 실패나 현재 기능 오류는 아니다.

### 5.2 로컬 브라우저 QA

- 언어/국가 → 선호도 → 주소 → 추천 3카드
- 카드 이동, 최소주문금액, YOGIYO 설명, YOBI 설명
- Additional Explanation 열기/닫기와 review 분리
- See other menus, Edit filters
- Edit my info, Food rankings 3개 tab, K-pop feature
- 옵션 선택, 기본값, 메모 번역, 장바구니 추가
- upsell 있음/없음 분기
- 수량 증가·감소·삭제·재추가
- 타 식당 cart conflict에서 keep/clear
- Change menu/Change options와 reload
- delivery review, mock Yogiyo handoff, 최종 reset
- mobile/desktop E2E regression

### 5.3 공개 API·브라우저 QA

- `/healthz`: `ok`
- `/readyz`: `ready`
- 공개 Oracle backend: `oracle-26ai`
- data origin: `YOGIYO_PUBLIC_WEB`
- 최종 source commit: `fee180194ae0cede0ae822d103635a790f825258`
- strict halal underfill: 1개 결과, `STRICT_MATCH_UNDERFILLED`, selection/presentation model null, provider dispatch 0
- Food rankings 상위 20개: 확장된 돼지고기·주류 금지 패턴 0건
- precomputed options: 3 groups/13 items, API 0.05초
- cross-merchant conflict: 옵션 호출 전에 즉시 표시
- browse-selected menu reload: ID 일치, order builder 복구
- 장바구니: popup, 수량 `1→2→1`, 삭제 후 empty 상태 확인
- 메모 번역: 영어 문장을 한국어로 변환
- YOBI cultural 설명과 `What diners say` review 영역 분리 확인
- 마지막 `Back to YOBI`: `/start` 국가/언어 화면, 과거 session URL 자동 복구 차단
- 공개 동작 중 확인한 HTTP 5xx 없음

### 5.4 LLM 호출 간격

공개 LLM 관련 E2E 시작 시각(UTC):

1. `2026-08-20T22:47:52.858Z`
2. `2026-08-20T23:17:16.005Z`
3. `2026-08-20T23:49:47.626Z`
4. `2026-08-21T00:16:54.508Z`
5. `2026-08-21T00:57:05.721Z`

연속 간격은 약 29분 23초, 32분 32초, 27분 7초, 40분 11초로 모두 요청된 1분보다 길다. 배포 activation 자체는 post-activation provider call 0으로 수행했다.

## 6. 배포 기록

| 릴리스 | 소스 | 목적 |
|---|---|---|
| `20260820T224329Z-76e77e3fb921` | `6023c99` | 12개 피드백 1차 통합 |
| `20260820T231150Z-a69418f6c0eb` | `8628905` | source 번역 보존 |
| `20260820T234354Z-55369598f5f2` | `322daf8` | item 격리·release ID 충돌 수정 |
| `20260821T001052Z-7bc47cc83064` | `710abd8` | strict underfill·fallback·halal v7 |
| `20260821T005147Z-006e7f8bda96` | `132ae16` | halal 별칭 v8·browse/cart/reload 보강 |
| `20260821T010351Z-44d5099b3f4b` | `fee1801` | 핸드오프 접근성 분리, 최종 활성 |

최종 code-only 릴리스는 다음 active data를 재사용한다.

- enrichment release: `synthetic-enrichment-20260821T005147Z-006e7f8bda96`
- protected base fingerprint before/after: `1672277d3fde6a0d4e7761812dfe6c92647e2f68f9080890202ef204e4468a06`로 동일
- canonical source data를 덮어쓰지 않고 additive synthetic enrichment만 활성화

모든 배포에서 임시 source-restricted SSH/LB 경로를 제거했고 최종적으로 TCP 22=0, TCP 80 unchanged, LB count restored를 확인했다.

## 7. 운영상 정직하게 남겨야 할 제한

- halal-friendly는 정식 인증이 아닌 synthetic demo 분류다.
- Food rankings의 주문순·한국 인기도는 실제 Yogiyo 전체 통계가 아니라 명시된 deterministic proxy다.
- K-pop feature는 아이디어를 보여주는 concept 기반 mock collection이다.
- review summary와 국가별 선호 수치는 synthetic demo 데이터다.
- `Open in Yogiyo`는 실제 앱 연동·주문·결제·배달을 발생시키지 않는 mock handoff다.
- 추천·presentation·메모 번역의 OCI provider 호출은 실제지만, strict underfill이나 provider 오류에서는 명시된 deterministic fallback을 사용할 수 있다.
- “관찰된 경로에서 오류 없음”은 모든 미래 입력에 대한 수학적 무결함 보증이 아니다. 이번 범위의 자동검사와 공개 QA에서는 기능 오류와 HTTP 5xx를 남기지 않았다.
- presentation lease의 과거 validation/rate-limit 실패 이력은 운영 감사용으로 보존돼 있다. 현재 readiness 실패나 활성 오류를 뜻하지 않는다.

## 8. 배포 중 디스크 복구 조치

첫 배포 시 VM root disk가 98%이고 여유 공간이 656 MiB라 새 release 설치가 `Errno 28`로 중단됐다. 현재 release, 공식 previous release, shared DB/config/evidence를 보존하는 조건으로 대상 검증을 거친 오래된 release directory 90개(16,764 MiB)를 삭제했다.

- 조치 후 사용률: 약 41%
- 확보 공간: 약 17,866 MiB
- 삭제한 과거 code/venv tree는 직접 복구되지 않지만 source는 Git commit에서 재현 가능하다.
- shared data와 현재/previous release는 삭제하지 않았다.

## 9. 최종 결론

12개 요청은 코드, DB enrichment, 테스트, 로컬 브라우저, OCI 배포, 공개 브라우저까지 연결해 완료했다. 특히 가장 심각했던 리뷰 provenance 누출은 prompt 문구 수정이 아니라 입력 provenance, 출력 validator, evidence ownership, per-item fallback과 UI 표시 위치를 함께 고쳐 재발 방지 계약으로 만들었다.

최종 공개 서비스는 `fee1801` 소스를 실행 중이며 `/readyz`가 `ready`다.
