# YOBI Chatbot Improvement — Codex Goal

- 작성일: 2026-08-09 KST
- 저장소: `https://github.com/barleylover/YOBI`
- 작업 경로: 이 파일이 위치한 Git 저장소 루트 (`.`)
- 기준 브랜치: `codex/master-spec-completion`
- 기존 Pull Request: [Draft PR #1](https://github.com/barleylover/YOBI/pull/1), `codex/master-spec-completion → master`
- 목표: YOBI 챗봇 개선 Phase 0~7을 코드·DB·합성 데이터·테스트·문서·OCI 공개 배포까지 완주한다.

## 1. Goal 운용 계약

이 문서는 챗봇_시스템_차후_개선_방향.md를 바탕으로 제작된 Codex Goal의 실행 계약이다. Goal을 시작한 Codex는 이 파일의 `Done` 조건이 모두 충족될 때까지 동일 목표를 계속 수행한다. 계획 작성, 인터페이스 선언, 빈 테이블, 샘플 데이터 몇 건, 비연결 스캐폴딩, 일부 테스트 통과만으로 완료 처리하지 않는다.

> 모든 Phase를 코드·마이그레이션·합성 데이터·테스트·문서까지 순차적으로 완료한다. 단순 계획이나 스캐폴딩으로 종료하지 않는다. 각 Phase 완료 후 관련 회귀 검증을 수행하고, 기존 주문·장바구니·Mock 결제 기능을 보존한다.

운영 규칙:

1. Phase 0부터 Phase 7까지 순서대로 진행한다.
2. 각 Phase는 산출물이 실제 런타임 경로에 연결되고 해당 Phase 합격 기준을 통과해야 완료다.
3. 다음 Phase 준비를 위한 읽기·조사는 병행할 수 있지만, 앞 Phase의 필수 계약을 생략한 채 뒤 Phase를 완료 처리하지 않는다.
4. 실패한 테스트와 확인된 회귀는 원인을 수정한 후 다시 검증한다. 실패 사실을 문서화하는 것으로 구현 의무를 대체하지 않는다.
5. 컨텍스트가 축약되거나 작업이 여러 턴에 걸쳐도 현재 Phase, 완료 산출물, 미해결 실패, 배포 상태를 이어서 추적한다.
6. 아래 별도 승인 조건이 아닌 한 불필요한 계획 승인 질문 없이 계속 진행한다.
7. Goal은 최종 `Done` 정의를 모두 만족한 뒤에만 완료로 표시한다.

## 2. 참조 명세와 우선순위

충돌 시 다음 순위를 적용한다.

1. 사용자의 최신 지시
2. `YOBI_FINAL_MVP_CODEX_MASTER_PROMPT.md`의 제품·안전·인프라 원칙
3. 이 `YOBI_CHATBOT_IMPROVEMENT_CODEX_GOAL.md`의 실행 범위와 합격 기준
4. `docs/챗봇_시스템_차후_개선_방향.md`의 진단과 상세 설계
5. 기존 코드·테스트·문서

적용 원칙:

- 상위 문서의 명시적 안전·보안·데이터 경계를 하위 구현 편의 때문에 약화하지 않는다.
- 이 문서는 상세 음식 지식이나 UI 문구를 반복 정의하지 않는다. 세부 설계는 개선 방향 문서를 따른다.
- 기존 코드가 명세와 다르면 회귀를 최소화하면서 명세에 맞게 수정한다.
- 현재 Git·OCI·모델·Public URL 상태처럼 변할 수 있는 사실은 실행 시점에 다시 확인한다.

## 3. 구현 범위와 제외 범위

### 3.1 구현 범위

- 다중 턴 대화 상태, `DialogueAct`, `MealNeedState`, `PreferenceDelta`, readiness gate
- 인사·명확화·요약·정정·거절·비교·설명·추천 행위와 상태별 fallback
- 추천 snapshot, 카드 선택·거절·옵션 이벤트의 서버 저장 및 UI-서버 동기화
- 메뉴 지식 그래프의 관계형 스키마, Markdown authoring/ingestion, Vector chunk 적재
- 음식 개념, 핵심 재료 claim, 알레르기·식단 관계, 상속·override 규칙
- 가게 원산지 원문과 정규화된 가게·메뉴 재료 범위
- 현재 목업 카탈로그 전체를 포괄하는 고품질 합성 Wiki·메뉴 매핑·근거 데이터
- 리뷰 추천 가중치 `0` 및 추천·안전 LLM 컨텍스트 제외
- SQL 하드 필터, Wiki 기본 재료 모델, 메뉴·원산지·옵션 근거, lexical/vector 검색을 결합한 추천 파이프라인
- 본문과 카드가 동일한 `RecommendationResult`를 사용하는 grounded 응답
- 음식 설명, 추천, 비교, 안전 경고의 근거 추적
- Oracle과 SQLite 호환 경로, 순차 SQL Migration, deterministic seed
- 백엔드·프론트엔드·DB·GenAI·E2E 테스트와 대화·RAG 평가
- 운영 로그, fallback 원인 구분, 관련 구현·데이터·배포·테스트 문서
- 모델·provider·serving mode를 설정으로 교체할 수 있는 GenAI adapter와 capability 계약
- OCI on-demand와 향후 dedicated endpoint를 동일한 대화·도구·grounding 계약으로 수용하는 이식성 경계
- 기존 OCI VM·Oracle AI Database에 최종 공개 배포하고 Public URL에서 검증

### 3.2 제외 범위

- 실제 요기요 API, 비공개 요기요 데이터, 실시간 주문·배달 연동
- 실제 결제 승인, 실제 금전 거래, 실제 주문 생성
- 합성 원산지·리뷰·메뉴 데이터를 실제 요기요 또는 가게 제공 데이터로 표현하는 행위
- 음식 Wiki만으로 특정 메뉴의 알레르기 무위험·할랄 인증·의학적 안전을 보증하는 기능
- 제품 목표와 무관한 대규모 UI 재설계, K-Food Passport 확장, 신규 사업 기능
- 별도 Graph DB, LangChain, LangGraph, GraphRAG의 선제 도입
- 근거 없는 정밀 확률, 영양·안전 수치, 인증 상태 생성
- 신규 유료 OCI 자원, 기존 OCI 자원 재생성, 광범위한 IAM·네트워크 변경
- 사용자가 별도로 요청하지 않은 PR merge, Draft 해제, `master` 직접 push

## 4. Phase 0~7 실행 순서와 산출물

### Phase 0. 계약·기준선·평가 정의

구체 산출물:

- 현재 Git, Draft PR #1, 로컬 테스트, 공개 서비스, OCI 앱·DB 상태의 기준선 기록
- `DialogueAct`, `MealNeedState`, `PreferenceDelta`, readiness, 추천 snapshot 계약
- 음식 개념, 관계, 재료 역할, claim 상태, 출처 범위, 상속·override 계약
- 합성 데이터·원산지·리뷰·교차접촉 정책
- 현재 GenAI provider·model·serving mode 기준선과 provider capability 계약
- `RATE_LIMIT`, `TIMEOUT`, `NETWORK_ERROR`, `INVALID_TOOL_ARGUMENT`, `NO_TOOL_RESPONSE`, `EMPTY_RESPONSE`, `GROUNDING_REJECTED`, `PROVIDER_UNAVAILABLE` fallback 분류
- 다중 턴 golden transcript와 지식·안전 golden case
- 기존 결함을 재현하는 회귀 기준과 Phase별 합격 체크리스트

Phase 합격 기준:

- 계약이 Pydantic/스키마/평가 fixture 등 실행 가능한 형태로 표현된다.
- 기존 테스트 기준선과 공개 서비스 결함이 확인된 사실과 추론으로 구분되어 기록된다.
- 이후 Phase가 사용할 상태·근거·평가 계약에 모순이 없다.

### Phase 1. 대화 상태 엔진과 추천 readiness gate

구체 산출물:

- 사용자 발화에서 구조화된 상태 delta를 추출·검증·병합하는 로직
- 부정 조건, 정정, 제약 엄격도, 표시·거절·선택 이력의 서버 영속화
- 부족한 정보와 다음 질문을 선택하는 readiness 정책
- 도구·카드 없이도 정상 처리되는 인사·질문·요약 응답
- 현재 대화 행위를 보존하는 deterministic fallback
- 상태 전이와 장기 제약 보존을 검증하는 단위·서비스·다중 턴 테스트

Phase 합격 기준:

- `hi`, 추천 보류 요청, `I don't know yet`가 메뉴 카드 없이 처리된다.
- `no soup`, `no pork`, 알레르기와 정정 내용이 후속 턴에도 보존된다.
- 추천은 readiness가 충족되거나 사용자가 명시적으로 요청한 경우에만 실행된다.

### Phase 2. 오케스트레이션과 UI-서버 계약

구체 산출물:

- 마지막 문장 키워드가 아닌 `DialogueAct + MealNeedState` 기반 도구 선택
- assistant turn, 카드 목록·순서·근거를 포함한 추천 snapshot 저장
- 카드 선택·거절·비교·옵션 변경 이벤트 API와 프론트엔드 연결
- 본문과 카드가 공유하는 구조화된 `RecommendationResult`
- provider·tool·validation·grounding 오류의 원인별 분류와 관측 로그
- `ChatService`와 OCI 호출 세부사항을 분리하는 `GenAIProvider` 또는 동등한 adapter 계약
- Responses API, Function Calling, structured output, streaming 지원 여부를 표현하는 provider capability 모델
- 기존 Function Calling 허용 목록과 mutation 승인 경계 보존

Phase 합격 기준:

- `두 번째 메뉴`와 `아까 추천한 메뉴`를 저장된 snapshot으로 정확히 해석한다.
- 본문과 카드 후보가 일치하며 LLM이 서버 후보를 추가·교체하지 않는다.
- 카드 선택이 서버 대화 상태와 기존 주문 흐름 양쪽에 반영된다.

### Phase 3. 메뉴 지식 그래프 DB와 authoring pipeline

구체 산출물:

- `DISH_CONCEPT`, `DISH_RELATION`, `CONCEPT_CLAIM`, `KNOWLEDGE_DOCUMENT`, `KNOWLEDGE_CHUNK`, `MENU_CONCEPT_MAP`에 해당하는 실제 스키마
- 가게 원산지 원문·버전·출처와 정규화 재료를 저장하는 실제 스키마
- 기존 `MENU_KNOWLEDGE`, 재료·알레르기·식단·옵션·근거 테이블과의 호환 경로
- 음식 Markdown front matter와 본문 계약
- Markdown 검증, 정규화, chunking, embedding, Oracle/SQLite 적재 도구
- source/version 변경 시 embedding과 설명 cache 갱신·무효화 로직
- 신규 Migration, repository/model/API 반영, 마이그레이션 테스트와 문서

Phase 합격 기준:

- 빈 스키마만 존재하지 않고 작은 golden fixture가 authoring부터 검색까지 왕복한다.
- SQLite와 Oracle이 동일한 핵심 데이터 계약을 구현한다.
- 기존 적용 Migration 파일은 변경되지 않고 신규 순차 Migration으로 확장된다.

### Phase 4. 고품질 합성 Wiki·원산지·메뉴 데이터

구체 산출물:

- 현재 음식군과 세부 변형을 포괄하는 재사용 가능한 Markdown Wiki
- `DEFINING`, `CORE`, `COMMON`, `OPTIONAL`, 변형·가공 재료 및 알레르기 관계
- 설명·맛·식감·온도·포만감·문화·외국인용 비유 facet
- 현재 150개 메뉴의 음식 개념 매핑 또는 명시적 `UNMAPPED` 사유
- 핵심 데모 경로의 `UNMAPPED` 0건
- 현재 30개 목업 가게의 합성 원산지 원문과 검증된 정규화 범위
- 메뉴별 사실, 옵션 추가·제거 효과, 교차접촉 상태, 출처·버전
- deterministic seed 재생성과 무결성 검증
- 리뷰를 추천·안전 데이터에서 제외한 설정과 회귀 테스트

Phase 합격 기준:

- 템플릿 문장 수만 늘리지 않고 음식 개념·재료·설명에 실제 구별력이 있다.
- Wiki의 핵심 재료는 `PRESUMED_PRESENT`로 상속할 수 있고, 미기재 재료는 부재로 승격되지 않는다.
- 원산지의 가게 범위와 메뉴 범위가 구분되며 모든 합성 사실에 합성 표시가 있다.

### Phase 5. 하이브리드 추천·안전·설명 파이프라인

구체 산출물:

- 서비스 지역·가용성·가격·사용자 하드 제약을 먼저 적용하는 SQL 후보 필터
- 음식 개념 매핑과 Wiki `DEFINING`·`CORE` 기본 재료 상속
- 메뉴·원산지·옵션 사실에 의한 구체적 override와 최종 재검증
- 누적 `MealNeedState` 기반 lexical/vector 검색 및 취향·실용 조건 재랭킹
- 리뷰 가중치 `0`인 추천 점수 계약
- 낮은 준비도·근거·점수에서 추천 대신 질문하는 정책
- claim과 passage를 포함한 설명·비교·추천 근거 조회
- 하드 제약 위반, 부재 오판, 옵션 충돌, 교차접촉을 검증하는 테스트와 평가

Phase 합격 기준:

- Wiki 핵심 재료와 충돌하는 메뉴는 메뉴별 근거가 없어도 보수적으로 제외된다.
- Wiki에 재료가 없다는 이유로 `CONFIRMED_ABSENT` 또는 안전 판정이 생성되지 않는다.
- 특정 메뉴·옵션의 신뢰 가능한 근거만 범용 상속을 수정한다.
- `no soup`, `no pork`, 예산, 맵기, 서비스 지역 위반이 acceptance set에서 0건이다.

### Phase 6. LLM 프롬프트·응답·fallback 품질

구체 산출물:

- 현재 행위, 누적 니즈, 확정·추정·미확인 정보, readiness, 허용 행동을 포함하는 프롬프트
- 구조화된 LLM 출력과 서버 검증
- Wiki 일반 설명과 메뉴별 확인 사실을 구분하는 사용자 문구
- 내부 ID·도구명·근거보다 강한 안전 표현을 제거하는 응답 검증
- 메뉴 설명만 요청할 때 카드 없이 답하는 경로
- provider 장애에서도 현재 대화 행위를 보존하는 fallback
- 실제 OCI GenAI 정상·오류 경로 smoke 및 회귀 테스트
- 현재 모델 전용 prompt·response adapter를 공통 대화·추천 정책과 분리
- 동일 acceptance set을 provider·model·serving mode 변경 후 재사용할 수 있는 회귀 경로

Phase 합격 기준:

- 인사·질문·요약을 무도구 응답이라는 이유로 실패 처리하지 않는다.
- 모든 메뉴 사실 문장은 서버 claim 또는 passage로 추적된다.
- `UNKNOWN`과 교차접촉 미확인을 안전으로 표현하지 않는다.
- 본문·카드·옵션·가격·근거가 서로 모순되지 않는다.

### Phase 7. 통합 평가·문서·OCI 공개 배포

실행 순서:

1. 전체 로컬 구현과 Migration 파일을 완료한다.
2. 합성 데이터 생성·무결성 검사와 전체 로컬 테스트·평가를 완료한다.
3. 구현·데이터 모델·RAG·테스트·배포·운영 문서를 최신화한다.
4. 기존 OCI 자원을 read-only로 재확인하고 배포 전 상태와 rollback 대상을 기록한다.
5. 기존 Oracle AI Database에 순차 Migration과 seed/update 절차를 실행한다.
6. 기존 OCI VM에 새 release를 배포하고 서비스 상태를 확인한다.
7. Public URL에서 health, readiness, QR, 인증 경계, 대화, 추천, 옵션, 장바구니, Mock 결제·주문 E2E를 검증한다.
8. Primary Demo를 실제 공개 URL에서 3회 연속 성공시킨다.
9. 실패 시 허용된 rollback을 수행하고 원인을 수정한 뒤 전체 배포 검증을 반복한다.
10. Git push와 Draft PR #1의 설명·검증 증거를 갱신한다.

Phase 합격 기준:

- 아래 테스트·품질 기준이 모두 통과한다.
- 공개 release와 DB schema/seed version이 일치한다.
- Public URL에서 새 챗봇 동작과 기존 주문 경로가 함께 검증된다.
- rollback 방법과 실제 배포 release 식별자가 문서화된다.

## 5. DB Migration·호환성 원칙

1. Oracle 전용 순차 SQL Migration Runner와 `SCHEMA_MIGRATION` 기록을 유지한다.
2. 이미 적용된 Migration 파일의 내용이나 checksum을 수정하지 않는다. 신규 번호의 Migration을 추가한다.
3. 런타임에서 필요한 DDL을 임시로 직접 실행하지 않는다. 모든 영구 변경은 저장소 Migration으로 재현 가능해야 한다.
4. 기존 컬럼·테이블·API를 즉시 삭제하거나 의미 변경하지 않는다. 추가형 Migration, 호환 뷰, dual read/write 또는 명시적 데이터 변환을 사용한다.
5. 기존 release가 신규 스키마에서 rollback 실행될 수 있도록 가능한 한 backward-compatible하게 설계한다.
6. 파괴적 DROP, 대량 손실 가능 변환, 되돌릴 수 없는 데이터 재작성은 별도 승인을 받기 전 실행하지 않는다.
7. 기존 합성 catalog의 ID, 장바구니·주문 snapshot 참조 무결성과 외래키를 보존한다.
8. Oracle과 SQLite의 핵심 테이블·상태·검색 결과 계약을 일치시킨다. Oracle 전용 Vector 세부 구현은 provider 차이로 명시한다.
9. embedding model, dimension, version과 source/document version을 함께 저장한다. 모델·차원 변경은 전체 재생성 및 검색 호환 계획을 포함한다.
10. 생성 LLM과 embedding provider를 별도 구성요소로 관리한다. 생성 모델을 변경해도 기존 embedding과 Vector 검색이 암묵적으로 변경되지 않는다.
11. seed는 deterministic하고 반복 실행 결과를 검증할 수 있어야 한다. 부분 적재나 버전 혼합 상태를 readiness에서 감지한다.
12. 배포 전 현재 schema migration, row count, vector null, FK·옵션 무결성을 검사하고 배포 후 다시 검사한다.
13. 앱 rollback과 DB 호환 경로를 배포 문서에 기록한다.

## 6. 테스트 및 품질 합격 기준

### 6.1 필수 검증 묶음

- Backend lint/type check와 전체 pytest
- Frontend lint, type check, component test, production build
- Migration·seed 무결성 테스트
- SQLite repository와 Oracle integration 테스트
- GenAI provider·Function Calling·fallback smoke
- provider capability·on-demand/dedicated adapter·model 교체 회귀 테스트
- 대화 상태·오케스트레이션·추천·지식·안전 단위 및 서비스 테스트
- 실제 다중 턴 golden transcript 평가
- Vector/lexical retrieval 및 grounded explanation 평가
- Public Playwright E2E와 Primary Demo 3회 연속 실행
- secret pattern, `.env`, 내부 ID·디버그 정보 노출 검사

백엔드 pytest는 현재 프로젝트 계약에 따라 `backend/`에서 `../.venv/bin/pytest -q`로 실행한다. 실행 시점에 repository의 최신 공식 명령이 달라졌다면 해당 문서와 CI 설정을 우선 확인한다.

### 6.2 필수 품질 게이트

- 기존 테스트와 새 테스트: 실패 0건
- 필수 다중 턴·지식 회귀 시나리오: 100% 통과
- 하드 제약 위반: 0건
- 심각한 알레르기에서 위험한 안심 표현: 0건
- Wiki 미기재를 재료 부재로 오판: 0건
- 본문과 카드 후보·가격·옵션 불일치: 0건
- 리뷰가 추천·안전 판정에 영향을 준 사례: 0건
- 메뉴 설명의 추적 불가능한 사실 주장: 0건
- 핵심 데모 메뉴의 음식 개념 매핑 누락: 0건
- required option group의 option item 누락: 0건
- 공개 health/readiness/주요 route 실패: 0건
- Primary Demo 공개 E2E: 3회 연속 성공

단순 테스트 개수 증가나 deterministic evaluator의 자기 일치만으로 품질을 선언하지 않는다. 실제 제품 표면과 다중 턴 동작을 함께 검증한다.

## 7. 기존 기능 보존 조건

다음 기능과 계약은 개선 과정 및 최종 공개 배포에서 계속 동작해야 한다.

- 프로필·언어·식이·알레르기 설정과 Demo 표시
- 주소 확인, 합성 숙소 fixture, OCR fallback, 서비스 지역
- Oracle AI Database, Vector 저장·검색, 근거 상태
- 메뉴·비교·근거·옵션 카드와 기존 주요 API 소비자
- required/optional 메뉴 옵션 및 가격 delta
- 서버 장바구니, 최소 주문액, 배달 옵션, 가격 snapshot
- Mock checkout, Mock 결제 성공·실패, Mock 주문, idempotency
- 인증·Demo control 경계, 감사 로그, secret 비노출
- QR 진입, 모바일 웹 Primary Demo, Nginx/systemd 배포 구조
- provider 장애 시 안전한 deterministic fallback

공개 API 또는 데이터 의미를 바꿔야 한다면 기존 소비자를 확인하고 호환 경로 또는 명시적 버전 전환을 구현한다. 기존 테스트를 삭제·완화하여 회귀를 숨기지 않는다.

## 8. 합성 데이터와 실제 데이터의 경계

1. 메뉴, 가게, 리뷰, 원산지, 근거, 호텔, 결제, 주문은 현재 YOBI 데모의 합성·Mock 데이터다.
2. 실제 요기요 데이터나 API를 사용했다고 표현하지 않는다.
3. 합성 원산지 정보는 `SYNTHETIC_MERCHANT_ORIGIN_DECLARATION` 또는 동등한 명시적 source type을 사용한다.
4. UI, API, 문서, seed에 `is_synthetic`, `Demo`, `Mock` 경계를 유지한다.
5. 일반 음식 Wiki는 음식 개념의 기본 지식이며 특정 가게 레시피의 확인 사실로 가장하지 않는다.
6. Wiki `DEFINING`·`CORE` 재료는 필터링을 위한 `PRESUMED_PRESENT`로 사용할 수 있지만, Wiki 미기재는 `CONFIRMED_ABSENT`가 아니다.
7. 가게 전체 원산지 정보는 가게 사용 재료이며, 메뉴명이 명시되지 않으면 모든 메뉴의 포함 사실로 전파하지 않는다.
8. 리뷰는 데모 추천과 안전 판정에서 가중치 `0`이며 LLM grounded context에 포함하지 않는다.
9. 실서비스 검증 없이 알레르기 무위험, 할랄 인증, 비건 보증, 교차접촉 부재를 선언하지 않는다.
10. AI가 생성한 음식 지식은 source/version/review status를 가지며, 실서비스의 검증된 안전 주장으로 자동 승격하지 않는다.

## 9. Git·PR 처리 방식

1. 실행 시작과 각 Phase 전후에 `git status`, 현재 branch, HEAD를 확인한다.
2. 사용자의 기존 변경과 관련 없는 파일을 수정·삭제·stage하지 않는다.
3. 기본 작업 branch는 현재 `codex/master-spec-completion`을 유지한다. 새 branch나 worktree는 사용자가 지시하거나 충돌 회피에 실제로 필요할 때만 만든다.
4. 적용 범위가 명확하고 검증된 변경만 논리적 Phase 또는 응집된 단위로 commit한다.
5. `git reset --hard`, 무단 force push, 광범위 checkout, destructive rebase를 사용하지 않는다.
6. 현재 Draft PR #1을 계속 사용하고 중복 PR을 만들지 않는다.
7. 검증된 commit을 `codex/master-spec-completion`에 push하고 Draft PR 본문에 Phase별 산출물, Migration, 테스트, 공개 배포 증거, 남은 위험을 갱신한다.
8. PR은 전체 Done까지 Draft로 유지한다. 사용자의 명시적 지시 없이 Ready for review로 전환하거나 merge하지 않는다.
9. secret, `.env`, OCI API key, SSH key, 민감한 OCID를 commit·PR 본문·로그에 넣지 않는다.
10. 최종 보고 시 commit, branch, PR URL, 배포 release, 테스트 결과를 정확히 기록한다.

## 10. LLM Provider·Serving Mode 이식성 원칙

### 10.1 목표 구조

LLM 모델과 OCI serving mode는 설정으로 교체 가능해야 한다. 대화 상태, 추천 정책, 지식 검색, 안전 판정, `RecommendationResult`는 특정 모델이나 OCI on-demand/dedicated 호출 방식에 의존하지 않는다.

```text
ChatService
→ GenAIProvider 인터페이스
   ├─ OCI On-Demand adapter
   └─ OCI Dedicated Endpoint adapter
→ 동일한 Tool Contract
→ 동일한 서버 검증
→ 동일한 RecommendationResult
```

Grok 계열과 OpenAI GPT-OSS 계열처럼 모델 동작 특성이 다른 경우에도 차이는 provider/model adapter와 prompt profile 안에 격리한다. 모델이 후보 선정, 하드 제약, 안전 판정의 최종 권한을 가지지 않는다.

### 10.2 구성 계약

환경 설정의 실제 이름은 기존 repository 규칙을 따르되, 최소한 다음 개념을 독립적으로 표현한다.

- GenAI provider
- 생성 model
- serving mode: `ON_DEMAND` 또는 `DEDICATED`
- dedicated endpoint ID 또는 endpoint reference
- region
- request timeout
- bounded retry 횟수와 backoff 정책
- 애플리케이션 동시 호출 제한
- provider/model별 prompt profile

endpoint ID, credential, API key는 코드·seed·로그·PR에 넣지 않는다. 설정 누락과 지원하지 않는 capability 조합은 애플리케이션 시작 또는 readiness에서 명확하게 실패시킨다.

### 10.3 Provider capability와 공통 계약

adapter는 최소한 다음 capability를 명시한다.

- Responses API 또는 현재 사용 inference API 지원
- Function Calling 지원
- structured output 지원 수준
- streaming 지원
- conversation/state API 사용 여부
- 최대 입력·출력 및 도구 제약

공통 서비스 계층은 capability를 검사한 뒤 허용된 경로만 사용한다. 모델이 지원하지 않는 기능을 존재하는 것처럼 가정하거나, 모델별 분기를 추천·안전 도메인 로직 안에 흩뿌리지 않는다.

### 10.4 생성 모델과 embedding 분리

GPT-OSS 120B, Grok 또는 다른 생성 모델로 변경해도 `KNOWLEDGE_CHUNK`와 메뉴 검색 embedding이 자동으로 바뀌지 않는다. 생성 model, embedding model, embedding dimension, embedding version은 별도 설정과 버전으로 관리한다.

embedding provider를 변경하는 경우에만 별도의 재생성·색인·검색 평가·rollback 계획을 수행한다. 생성 LLM 전환을 이유로 지식 그래프나 Vector 데이터를 불필요하게 다시 만들지 않는다.

### 10.5 Retry·fallback·관측

Dedicated mode도 endpoint 장애, timeout, 네트워크·IAM 오류, 잘못된 tool call, 빈 응답, grounding 거절이 발생할 수 있으므로 fallback을 제거하지 않는다.

- 재시도는 bounded exponential backoff와 jitter를 사용한다.
- 재시도 가능한 provider 오류와 재시도하면 안 되는 validation·contract 오류를 구분한다.
- 장바구니·결제·주문 같은 mutation은 LLM 호출 재시도로 중복 실행되지 않게 기존 idempotency와 승인 경계를 유지한다.
- 로그와 지표는 provider, model, serving mode, 오류 유형을 구분하되 credential과 민감한 endpoint 정보를 기록하지 않는다.
- fallback은 오류 유형과 무관하게 현재 `DialogueAct`와 사용자 상태를 보존한다.

### 10.6 현재 Goal과 향후 Dedicated 전환 경계

이 Goal은 현재 승인된 기존 OCI GenAI 사용 방식으로 완료할 수 있어야 하며, GPT-OSS 120B 전용 AI 클러스터 생성은 현재 Goal의 필수 조건이 아니다. 신규 dedicated cluster, 유료 hosting unit, private endpoint, IAM·네트워크 확대는 Section 11의 별도 승인 대상이다.

현재 Goal에서는 다음을 완료한다.

- on-demand/dedicated 차이를 수용하는 adapter와 설정 계약
- fake 또는 contract fixture를 이용한 두 serving mode의 요청 구성·응답 정규화 테스트
- 현재 승인된 on-demand 경로의 실제 OCI smoke와 공개 E2E
- provider·model·serving mode 변경 후 재사용할 acceptance suite

향후 사용자가 dedicated cluster 생성을 별도로 승인하고 endpoint 정보를 제공하면, 도메인 로직 변경 없이 설정·adapter 연결과 실제 dedicated smoke·부하·fallback 검증만 추가한다.

### 10.7 이식성 합격 기준

- model 또는 serving mode 식별자가 `ChatService`, 추천 규칙, 지식 그래프, 안전 판정에 하드코딩되지 않는다.
- 현재 on-demand provider가 기존 기능과 새 acceptance set을 통과한다.
- dedicated endpoint가 없어도 adapter contract와 요청·응답 정규화 테스트가 통과한다.
- provider 변경 후 본문·카드·도구·grounding 서버 검증 계약이 동일하게 유지된다.
- fallback 지표에서 shared throttling과 애플리케이션 contract 실패를 구분할 수 있다.
- 생성 모델 변경이 embedding 재생성을 암묵적으로 유발하지 않는다.

## 11. 실서비스 공개 배포와 승인 조건

### 11.1 이번 Goal에 포함된 배포 승인

이 Goal은 모든 로컬 구현·Migration 파일·합성 데이터·테스트·평가·문서화가 완료되고 로컬 품질 게이트가 통과한 후, 기존 YOBI OCI 환경에 공개 배포하는 작업을 포함한다.

추가 승인 없이 수행 가능한 범위:

- 기존 OCI 자원의 read-only 상태 조회
- 기존 VM·ADB·Nginx·systemd·배포 스크립트 재사용
- 저장소에 포함된 비파괴적 순차 Migration 실행
- 합성 seed 또는 versioned catalog update
- 새 앱 release 업로드·전환·서비스 재시작
- health/readiness/로그/DB/GenAI/Public E2E 검증
- 실패한 새 release의 기존 release rollback

### 11.2 반드시 별도 승인이 필요한 범위

- OCI 자원, VCN, subnet, DB, VM, secret, key의 삭제·재생성
- 신규 유료 자원 또는 비용 구조의 실질적 확대
- IAM policy, NSG, security list, public ingress의 범위 확대
- credential 생성·회전·노출 가능 작업
- 파괴적 DB Migration, 데이터 손실 가능 변환, 기존 백업 삭제
- 실제 요기요·결제·주문 외부 시스템 연결
- `master` merge, Draft 해제 또는 PR merge

별도 승인 조건이 발견되면 해당 변경만 멈추고, 안전한 로컬 구현·테스트·문서·비파괴적 대안을 계속 진행한다. 승인 없이 보안·데이터 무결성 경계를 약화하지 않는다.

## 12. 최종 Done 정의

다음 조건을 모두 충족해야 이 Goal을 `Done`으로 선언할 수 있다.

- [ ] Phase 0~7의 구체 산출물이 실제 코드 경로에 연결되어 있다.
- [ ] 계획·스캐폴딩·샘플 일부가 아니라 요구된 전체 동작이 구현되어 있다.
- [ ] 신규 Oracle Migration이 순차 Runner로 재현 가능하고 SQLite 호환 경로가 있다.
- [ ] 현재 목업 카탈로그를 포괄하는 음식 Wiki·지식 그래프·원산지·메뉴 매핑이 적재되어 있다.
- [ ] 대화 상태, readiness, 정정·부정 조건, snapshot 참조, UI-서버 이벤트가 동작한다.
- [ ] Wiki 상속, 메뉴·원산지·옵션 override, 하드 필터, grounded 설명이 동작한다.
- [ ] 리뷰 추천·안전 가중치가 `0`이며 합성·Mock 경계가 사용자에게 명확하다.
- [ ] 생성 model과 serving mode가 provider adapter·설정으로 분리되고 도메인 로직에 하드코딩되지 않는다.
- [ ] 생성 model과 embedding provider·version이 독립적으로 관리된다.
- [ ] provider·model·serving mode·오류 유형별 fallback 관측과 공통 acceptance 경로가 동작한다.
- [ ] 기존 장바구니·옵션·배달·Mock 결제·Mock 주문·idempotency 기능이 보존된다.
- [ ] 기존 테스트와 신규 테스트가 모두 통과한다.
- [ ] 필수 품질 게이트와 다중 턴·지식 acceptance set이 모두 통과한다.
- [ ] 관련 데이터 모델·RAG·테스트·배포·운영·rollback 문서가 최신 상태다.
- [ ] 기존 OCI VM·ADB에 최종 release와 Migration이 배포되어 있다.
- [ ] Public URL health/readiness와 핵심 보안·인증 경계가 정상이다.
- [ ] Public URL에서 새 챗봇 흐름과 기존 주문 흐름이 검증되었다.
- [ ] Primary Demo가 공개 URL에서 3회 연속 성공했다.
- [ ] 검증된 변경이 현재 branch에 commit·push되고 Draft PR #1이 최신 증거로 갱신되었다.
- [ ] 남은 미검증 사실, 위험, 사람 확인 항목이 최종 보고서에 구분되어 있다.
- [ ] 별도 승인 없이는 수행할 수 없는 필수 항목이 남아 있지 않다.

완료 보고에는 최소한 다음을 포함한다.

1. Phase별 구현 결과와 주요 파일
2. DB Migration·catalog·embedding version
3. 테스트·평가·E2E 실제 결과
4. 보존한 기존 기능과 회귀 검증
5. OCI release·Public URL·health 상태
6. rollback 방법
7. Git commit·branch·Draft PR #1 상태
8. 확인된 한계와 실서비스 전 추가 검증 사항
