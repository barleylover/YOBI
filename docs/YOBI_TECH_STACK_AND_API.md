# YOBI 코드 구조 및 기술 스택 분석

## 1. 프로젝트 개요

YOBI는 외국인 관광객을 대상으로 음식 추천과 주문 연결 경험을 제공하는 모바일 중심 웹 애플리케이션이다. 사용자는 언어와 주소를 설정하고, 구조화된 음식 선호 조건을 선택한 뒤, 근거가 연결된 메뉴 추천을 받을 수 있다.

전체 구조는 다음과 같다.

```text
React/TypeScript SPA
        │ REST API
        ▼
FastAPI
        │
        ├─ 구조화 추천 서비스
        ├─ 대화·세션 상태 관리
        ├─ 주소 OCR/주소 확인
        ├─ 장바구니·Mock Checkout
        ├─ RAG/Embedding
        └─ OCI Generative AI
        │
        ▼
Repository 추상화
   ├─ Oracle AI Database 26ai — 운영
   └─ SQLite — 로컬 개발·테스트
```

핵심 설계 문서는 `docs/ARCHITECTURE.md`, API 문서는 `docs/API.md`다.

---

## 2. Oracle DB

### 2.1 사용 제품과 계정

운영 데이터베이스는 Oracle AI Database 26ai다. 애플리케이션 스키마는 `YOBI_APP` 계정이 소유하며 런타임에서 `ADMIN` 사용을 금지한다.

관련 코드 및 문서:

- `database/README.md`
- `backend/app/core/config.py`
- `backend/app/db/oracle_pool.py`
- `backend/app/db/oracle_repository.py`

### 2.2 연결 방식

Python `oracledb` 드라이버의 Thin mode connection pool을 사용한다.

```python
oracledb.create_pool(
    user=settings.db_username,
    password=password,
    dsn=dsn,
    min=1,
    max=3,
    increment=1,
    getmode=oracledb.POOL_GETMODE_TIMEDWAIT,
    wait_timeout=5000,
    timeout=60,
    ping_interval=60,
)
```

주요 특징:

- 최소 1개, 최대 3개 커넥션
- 커넥션 획득 최대 대기 시간 5초
- 반환 전 정상 처리 시 commit
- 예외 발생 시 rollback
- idle timeout 및 ping interval 60초
- 작은 OCI VM 환경을 고려한 제한된 풀 크기

### 2.3 Repository 패턴

비즈니스 로직은 DB 구현체를 직접 참조하지 않고 `YobiRepository` 인터페이스를 사용한다.

```text
YobiRepository
 ├─ OracleYobiRepository
 └─ SQLiteYobiRepository
```

`DEMO_DB_BACKEND` 값에 따라 저장소 구현체가 선택된다.

```python
if settings.demo_db_backend == "oracle":
    repository = OracleYobiRepository(settings)
else:
    repository = SQLiteYobiRepository(settings.sqlite_path)
```

관련 코드:

- `backend/app/dependencies.py`
- `backend/app/db/repository.py`
- `backend/app/db/oracle_repository.py`
- `backend/app/db/sqlite_repository.py`

### 2.4 주요 데이터 영역

| 영역 | 주요 테이블 |
|---|---|
| 사용자 | `USER_PROFILE` |
| 세션/대화 | `CHAT_SESSION`, `CHAT_MESSAGE`, `CONVERSATION_EVENT` |
| 상점/메뉴 | `MERCHANT`, `MENU`, `MENU_OPTION_GROUP`, `MENU_OPTION_ITEM` |
| 외부 카탈로그 | `CATALOG_IMPORT_BATCH`, `MENU_SOURCE_DETAIL`, `MERCHANT_SOURCE_DETAIL` |
| 주소 | `ADDRESS_PLACE`, `ADDRESS_REF`, `SERVICE_AREA` |
| 주문 | `CART`, `CART_ITEM`, `DELIVERY_PREFERENCE` |
| 결제·주문 Mock | `MOCK_CHECKOUT`, `MOCK_ORDER` |
| 음식 지식 | `DISH_CONCEPT`, `CONCEPT_CLAIM`, `KNOWLEDGE_DOCUMENT`, `KNOWLEDGE_CHUNK` |
| 지식 그래프 | `DISH_RELATION`, `DISH_CONCEPT_CLOSURE`, `MENU_CONCEPT_MAP` |
| 추천 | `SESSION_RECOMMENDATION_CRITERIA`, `STRUCTURED_RECOMMENDATION_REQUEST` |
| 배포 버전 | `KNOWLEDGE_RELEASE`, `RECOMMENDATION_RELEASE_FAMILY` |
| 인증·안전 | `MERCHANT_CERTIFICATION`, `MENU_ALLERGEN`, `MENU_DIETARY_ATTRIBUTE` |

마이그레이션은 `database/migrations/001_*.sql`부터 `012_*.sql`까지 순차 관리된다. 적용된 SQL의 SHA-256 체크섬은 `SCHEMA_MIGRATION`에 저장되어 이미 적용된 마이그레이션의 변경을 감지한다.

---

## 3. Oracle 설정

### 3.1 주요 환경변수

```env
APP_ENV=production
DEMO_DB_BACKEND=oracle

ADB_DSN=...
DB_USERNAME=YOBI_APP
DB_PASSWORD=...

EMBEDDING_PROVIDER=oci
OCI_EMBED_MODEL=cohere.embed-v4.0
OCI_EMBED_DIMENSION=1536
```

설정은 `backend/app/core/config.py`의 Pydantic Settings로 관리된다.

- `.env` 자동 로딩
- 환경변수 이름 대소문자 구분 없음
- 비밀번호, API key, DSN은 `SecretStr`
- DB 사용자가 `ADMIN`이면 설정 오류
- Embedding 차원이 1536이 아니면 설정 오류

### 3.2 DB 초기 구성

```bash
make db-bootstrap
make db-migrate
make db-seed
python scripts/seed_demo.py --verify-only
```

| 명령 | 역할 |
|---|---|
| `make db-bootstrap` | `YOBI_APP` 스키마와 초기 권한 구성 |
| `make db-migrate` | 마이그레이션 순차 적용 및 체크섬 관리 |
| `make db-seed` | 메뉴, 상점, 주소, 지식, Embedding 데이터 입력 |
| `seed_demo.py --verify-only` | 데이터 무결성 및 필수 행 검증 |

운영 비밀값은 Git에 저장하지 않고 `/etc/yobi/yobi.env`에 `root:root`, 권한 `0600`으로 배치하도록 설계되어 있다.

---

## 4. Oracle Embedding Vector DB

### 4.1 Vector 컬럼

Oracle 네이티브 Vector 타입을 사용한다.

```sql
embedding_vector VECTOR(1536, FLOAT32)
```

주요 적용 테이블:

- `MENU`
- `REVIEW_SNIPPET`
- `MENU_KNOWLEDGE`
- `KNOWLEDGE_CHUNK`

관련 마이그레이션:

- `database/migrations/001_core_schema.sql`
- `database/migrations/002_knowledge_and_cache.sql`
- `database/migrations/006_knowledge_graph.sql`

### 4.2 Embedding 모델

운영 기본값은 OCI Cohere Embedding이다.

```env
OCI_EMBED_MODEL=cohere.embed-v4.0
OCI_EMBED_DIMENSION=1536
```

Embedding 요청은 문서 저장과 검색 질의를 구분한다.

- `SEARCH_DOCUMENT`: 지식 문서 또는 chunk 저장용
- `SEARCH_QUERY`: 사용자 검색 및 추천 질의용

```python
client.embeddings.create(
    model=self.model,
    input=texts,
    dimensions=self.dimension,
    extra_body={"input_type": mode},
)
```

구현은 `backend/app/rag/providers.py`에 있다.

### 4.3 로컬 Embedding

로컬 개발에서는 외부 OCI 호출 없이 deterministic embedding을 사용한다.

| 항목 | 값 |
|---|---|
| 모델명 | `yobi-semantic-hash-v1` |
| 차원 | 1536 |
| 버전 | `2026-08-06` |

토큰을 SHA-256으로 해싱하여 고정 차원의 정규화 벡터를 생성한다. 이는 OCI Embedding 품질을 재현하는 모델이 아니라, 로컬 테스트에서 동일 입력에 동일 결과를 제공하기 위한 대체 구현이다.

### 4.4 Vector 검색

Oracle 검색은 cosine distance를 사용한다.

```sql
VECTOR_DISTANCE(
    chunk.embedding_vector,
    :query_vector,
    COSINE
)
```

실제 검색 구현은 `backend/app/db/oracle_repository.py`에 있다.

### 4.5 Hybrid RAG

추천은 Vector 유사도만으로 결정되지 않는다.

```text
1. 주소·서비스 영역 필터
2. 메뉴 판매 여부 필터
3. 가격 조건 필터
4. halal/vegan/spice 등 구조화 조건 필터
5. 메뉴와 음식 개념의 검수된 매핑
6. Vector 검색
7. lexical token overlap
8. exact alias/essential fact 매칭
9. RRF(Reciprocal Rank Fusion)
10. 결정론적 점수와 다양성 정렬
```

안전성, 가격, 서비스 영역, 판매 가능 여부는 관계형 SQL로 먼저 제한한다. Vector distance는 이미 조건을 통과한 후보의 검색·정렬 신호로 사용된다.

---

## 5. Oracle LLM

### 5.1 연결 방식

OCI Generative AI의 OpenAI-compatible endpoint를 OpenAI Python SDK로 호출한다.

```python
OpenAI(
    base_url=settings.oci_genai_base_url,
    api_key=settings.oci_genai_api_key.get_secret_value(),
    timeout=settings.llm_timeout_seconds,
    max_retries=0,
)
```

기본 endpoint:

```text
https://inference.generativeai.us-chicago-1.oci.oraclecloud.com/20231130/actions/v1
```

관련 코드:

- `backend/app/genai/client.py`
- `backend/app/genai/providers.py`
- `backend/app/core/config.py`

### 5.2 모델 설정

```env
OCI_GENAI_MODEL=xai.grok-4.3
OCI_GENAI_FALLBACK_MODEL=openai.gpt-oss-120b
STRUCTURED_RECOMMENDATION_MODEL=openai.gpt-oss-120b
OCI_GENAI_SERVING_MODE=on_demand
```

지원 serving mode:

- `on_demand`: 모델 이름을 API 요청에 전달
- `dedicated`: 모델 이름을 OCI endpoint ID로 변환

### 5.3 LLM의 책임 범위

LLM이 추천 메뉴 자체를 선정하지 않는다.

```text
Oracle SQL + 검수된 지식
        ↓
서버가 후보 필터링
        ↓
결정론적 점수와 다양성 적용
        ↓
최종 메뉴 최대 3개와 순서 고정
        ↓
LLM은 해당 메뉴의 설명만 생성
        ↓
서버가 ID·순서·근거 참조 검증
```

LLM은 다음 작업을 할 수 없다.

- 메뉴 추가 또는 제거
- 메뉴 순서 변경
- 사용자가 지정한 조건 완화
- 근거에 없는 메뉴나 내부 ID 삽입
- 서버가 확정한 후보 교체

LLM 호출이 실패하거나 timeout이 발생하면 메뉴 순서를 유지하고 결정론적 fallback 설명을 반환한다.

### 5.4 안정성 설정

- SDK 자동 retry 비활성화
- 애플리케이션 계층에서 제한된 retry/backoff 관리
- timeout, 429, network, 5xx 오류 분류
- 구조화 추천 동시 실행 기본 최대 2개
- 일반 LLM 동시 실행 기본 최대 4개
- 운영 필수 설정이 없으면 `/readyz` 실패

---

## 6. Frontend 기술 스택

| 구분 | 기술 |
|---|---|
| 언어 | TypeScript 5.9 |
| UI | React 19 |
| 빌드 | Vite 7 |
| 라우팅 | React Router DOM 7 |
| 서버 상태 | TanStack React Query 5 |
| 클라이언트 상태 | Zustand 5 |
| 폼 | React Hook Form |
| 검증 | Zod 4 |
| UI 컴포넌트 | Radix UI Dialog |
| 아이콘 | Lucide React |
| QR 생성 | qrcode |
| 단위 테스트 | Vitest, Testing Library |
| E2E | Playwright |
| 정적 검사 | ESLint, TypeScript ESLint |
| 패키지 관리 | pnpm 10 |

의존성은 `frontend/package.json`에서 확인할 수 있다.

### 6.1 프런트엔드 구조

```text
frontend/src
├─ main.tsx                 # React 진입점과 BrowserRouter
├─ App.tsx                  # 화면 라우팅
├─ types.ts                 # API·도메인 타입
├─ styles.css
├─ routes/                  # 페이지 단위 컴포넌트
├─ components/              # 공통·업무 컴포넌트
├─ lib/
│  ├─ api.ts                # Fetch 기반 API client
│  ├─ i18n.ts               # 다국어
│  ├─ preferenceCatalog.ts
│  └─ recommendationI18n.ts
└─ stores/
   └─ session.ts            # Zustand 세션 상태
```

### 6.2 API 통신

Axios 대신 브라우저 `fetch`를 감싼 자체 API client를 사용한다.

- JSON request/response 처리
- 오류 응답 표준화
- `AbortSignal` 지원
- 추천 request polling
- 주소 이미지는 `FormData`로 전송
- 개발 환경에서는 Vite proxy 사용
- 운영 환경에서는 Nginx가 `/api/`, `/healthz`, `/readyz`를 Uvicorn으로 proxy

구현은 `frontend/src/lib/api.ts`에 있다.

---

## 7. Backend 기술 스택

| 구분 | 기술 |
|---|---|
| 언어 | Python 3.9+ |
| API 프레임워크 | FastAPI |
| ASGI 서버 | Uvicorn |
| 모델·검증 | Pydantic 2 |
| 환경설정 | Pydantic Settings |
| Oracle Driver | python-oracledb 3 |
| LLM/Embedding Client | OpenAI Python SDK |
| HTTP Client | HTTPX |
| Multipart upload | python-multipart |
| 이미지 검사 | Pillow |
| 로컬 DB | SQLite |
| 테스트 | pytest, pytest-asyncio |
| 정적 검사 | Ruff, mypy |
| 운영 Proxy | Nginx |
| 운영 프로세스 | systemd |

의존성은 `backend/pyproject.toml`에서 확인할 수 있다.

### 7.1 백엔드 구조

```text
backend/app
├─ main.py
│  └─ FastAPI 생성, middleware, 전체 API endpoint
├─ dependencies.py
│  └─ Repository와 Service dependency injection
├─ core/
│  ├─ config.py
│  └─ logging.py
├─ domain/
│  └─ Pydantic 도메인 모델과 정책
├─ db/
│  ├─ repository.py
│  ├─ oracle_repository.py
│  ├─ sqlite_repository.py
│  ├─ oracle_pool.py
│  └─ schema_sqlite.py
├─ rag/
│  ├─ embeddings.py
│  └─ providers.py
├─ genai/
│  ├─ client.py
│  ├─ providers.py
│  ├─ prompts.py
│  ├─ grounding.py
│  ├─ response_contract.py
│  └─ recommendation_generator.py
├─ knowledge/
│  ├─ authoring.py
│  ├─ catalog_seed.py
│  ├─ oracle_store.py
│  └─ resolver.py
└─ services/
   ├─ structured_recommendation.py
   ├─ chat_service.py
   ├─ dialogue_engine.py
   ├─ address_ocr.py
   └─ demo_control.py
```

### 7.2 요청 처리 흐름

```text
FastAPI endpoint
   ↓
Pydantic request validation
   ↓
StructuredRecommendationService / ChatService
   ↓
YobiRepository interface
   ↓
OracleYobiRepository 또는 SQLiteYobiRepository
   ↓
Oracle SQL + Vector Search
   ↓
RecommendationGenerator
   ↓
OCI GenAI
   ↓
응답 검증 및 DB 저장
```

---

## 8. 라우터

### 8.1 프런트엔드 라우터

React Router를 사용하며 `frontend/src/App.tsx`에 정의되어 있다.

| 경로 | 화면 | 설명 |
|---|---|---|
| `/` | `WelcomePage` | 시작 화면 |
| `/start` | `LocalePage` | 언어·국가 선택 |
| `/profile` | `OnboardingPage` | 프로필·주소 설정 |
| `/chat/:sessionId` | `ChatPage` | 구조화 추천 및 주문 UI |
| `/handoff` | `HandoffPage` | 요기요 이동 Mock |
| `/pay/:checkoutId` | Redirect | `/handoff`로 이동 |
| `/order/:orderId` | Redirect | `/handoff`로 이동 |
| `/demo/qr` | `DemoQrPage` | 데모 QR |
| `/demo/control` | `DemoControlPage` | 운영 데모 제어 |
| 기타 | Redirect | `/`로 이동 |

`PaymentPage`와 `OrderPage` 파일은 존재하지만 현재 `App.tsx`에서는 연결되지 않는다. 공개 브라우저 흐름은 실제 결제·주문 완료 화면이 아니라 `/handoff`에서 종료된다.

### 8.2 백엔드 라우터

별도 `APIRouter` 모듈로 나누지 않고 `backend/app/main.py`에 `@app.get`, `@app.post` 형식으로 등록되어 있다.

기능 그룹:

```text
/healthz, /readyz
/api/v1/profiles
/api/v1/sessions
/api/v1/recommendation
/api/v1/sessions/{id}/recommendations
/api/v1/sessions/{id}/messages
/api/v1/sessions/{id}/address
/api/v1/sessions/{id}/cart
/api/v1/checkout
/api/v1/orders
/api/v1/demo
```

현재 규모에서는 다음과 같이 `APIRouter` 단위로 분리할 여지가 있다.

```text
api/routes/
├─ health.py
├─ profiles.py
├─ sessions.py
├─ recommendations.py
├─ addresses.py
├─ cart.py
├─ checkout.py
└─ demo.py
```

---

## 9. API 명세서

API prefix는 `/api/v1`이며 FastAPI 실행 시 `/docs`에서 Swagger UI를 확인할 수 있다.

### 9.1 상태 확인

| Method | Endpoint | 설명 |
|---|---|---|
| GET | `/healthz` | 프로세스 생존 여부. 외부 의존성은 검사하지 않음 |
| GET | `/readyz` | DB, 카탈로그, Vector, OCI GenAI 운영 준비 상태 |

### 9.2 프로필·세션

| Method | Endpoint | 설명 |
|---|---|---|
| POST | `/api/v1/profiles` | 사용자 프로필 생성 |
| GET | `/api/v1/profiles/{profile_id}` | 프로필 조회 |
| PATCH | `/api/v1/profiles/{profile_id}` | 프로필 수정 |
| DELETE | `/api/v1/profiles/{profile_id}` | 프로필 및 연결 데이터 삭제 |
| POST | `/api/v1/sessions` | 세션 생성 |
| GET | `/api/v1/sessions/{session_id}` | 세션 상태 조회 |
| POST | `/api/v1/sessions/{session_id}/reset` | 프로필을 유지하고 세션 초기화 |
| GET | `/api/v1/sessions/{session_id}/conversation` | 대화·추천·상태 전체 복구 |

### 9.3 구조화 추천

| Method | Endpoint | 설명 |
|---|---|---|
| GET | `/api/v1/recommendation/preferences/catalog` | 버전 기반 선호도 카탈로그 조회 |
| POST | `/api/v1/sessions/{id}/structured-recommendations/preview` | 추천 조건별 후보 지원 상태 사전 확인 |
| PUT | `/api/v1/sessions/{id}/recommendation-criteria` | 추천 조건 확정 |
| POST | `/api/v1/sessions/{id}/recommendations` | 추천 요청 생성 또는 동일 요청 replay |
| GET | `/api/v1/sessions/{id}/recommendation-requests/{request_id}` | 추천 처리 결과 polling |
| POST | `/api/v1/sessions/{id}/recommendation-comparisons` | 추천 메뉴 2~3개 비교 |
| POST | `/api/v1/sessions/{id}/events` | 메뉴 선택·거절 등의 멱등 이벤트 |
| GET | `/api/v1/menus/{menu_id}/options` | 메뉴 옵션과 추가 가격 조회 |
| GET | `/api/v1/menus/{menu_id}/evidence` | 추천 근거, 출처, excerpt 조회 |

추천 요청은 `request_id`, criteria version, state version 등의 값으로 멱등성을 보장한다. 동일 ID와 동일 payload는 저장된 요청을 replay하고 동일 ID에 다른 payload가 들어오면 충돌로 처리한다.

### 9.4 탐색 API

| Method | Endpoint | 설명 |
|---|---|---|
| GET | `/api/v1/sessions/{id}/food-rankings` | 리뷰, 주문 proxy, 한국 인기 기준 데모 랭킹 |
| GET | `/api/v1/sessions/{id}/featured/kpop-demon-hunters` | K-POP 테마 음식 기능 |
| GET | `/api/v1/sessions/{id}/merchants/{merchant_id}/menus` | 특정 상점 메뉴 조회 |

### 9.5 주소 API

| Method | Endpoint | 설명 |
|---|---|---|
| POST | `/api/v1/sessions/{id}/address/attachments` | 주소 이미지 업로드 및 OCR |
| POST | `/api/v1/sessions/{id}/address/resolve` | 호텔명·주소 문자열을 확인 후보로 변환 |
| POST | `/api/v1/sessions/{id}/address/confirm` | 서명된 후보 또는 정확히 일치하는 주소 확정 |

주소 이미지 업로드에서는 크기, MIME type, magic bytes, 이미지 디코딩 가능 여부를 검사한다. 원본 이미지 바이트는 DB나 파일시스템에 저장하지 않고 digest와 확인된 주소만 유지한다.

### 9.6 장바구니·배송 API

| Method | Endpoint | 설명 |
|---|---|---|
| GET | `/api/v1/sessions/{id}/cart` | 장바구니, 총액, 누락 옵션 조회 |
| POST | `/api/v1/sessions/{id}/cart/items` | 메뉴와 옵션 추가 |
| PATCH | `/api/v1/sessions/{id}/cart/items/{item_id}` | 수량·옵션 수정 |
| DELETE | `/api/v1/sessions/{id}/cart/items/{item_id}` | 장바구니 항목 삭제 |
| PATCH | `/api/v1/sessions/{id}/delivery` | 배송 요청사항 수정 |
| POST | `/api/v1/sessions/{id}/cart/confirm` | 가격·옵션·버전을 검사하고 장바구니 확정 |

가격은 프런트엔드 입력값을 신뢰하지 않고 서버가 DB의 현재 가격으로 계산한다.

### 9.7 Mock checkout·주문 API

| Method | Endpoint | 설명 |
|---|---|---|
| POST | `/api/v1/sessions/{id}/checkout` | 멱등 Mock checkout 생성 |
| GET | `/api/v1/checkout/{checkout_id}` | checkout 조회 |
| POST | `/api/v1/checkout/{checkout_id}/mock-success` | 성공 처리 및 Mock 주문 생성 |
| POST | `/api/v1/checkout/{checkout_id}/mock-failure` | 실패 처리, 장바구니 보존 |
| POST | `/api/v1/checkout/{checkout_id}/cancel` | 대기 checkout 취소 |
| GET | `/api/v1/orders/{order_id}` | 합성 주문 및 ETA 조회 |

위 API는 백엔드 무결성 테스트를 위해 남아 있다. 현재 공개 브라우저는 이를 실제 결제로 노출하지 않고 요기요 handoff Mock에서 종료된다.

### 9.8 Legacy 대화 API

| Method | Endpoint | 설명 |
|---|---|---|
| POST | `/api/v1/sessions/{id}/messages` | 이전 free-chat API |
| POST | `/api/v1/sessions/{id}/messages/stream` | 이전 SSE 스트리밍 API |
| GET | `/api/v1/sessions/{id}/messages` | 사용자에게 보이는 과거 메시지 |

현재 구조화 추천 UI는 free-text 추천 composer를 사용하지 않으므로 POST 메시지 API는 하위 호환 목적으로 유지된다.

### 9.9 데모 운영 API

| Method | Endpoint | 설명 |
|---|---|---|
| GET | `/api/v1/demo/status` | 데모 상태 조회 |
| POST | `/api/v1/demo/reset` | 데모 데이터 초기화 |
| POST | `/api/v1/demo/failure-mode` | 장애 시나리오 설정 |

데모 운영 API는 `DEMO_CONTROL_TOKEN`으로 보호된다.

---

## 10. 핵심 추천 처리 순서

```text
사용자가 주소와 선호 조건 입력
        ↓
FastAPI가 Pydantic 모델로 요청 검증
        ↓
Oracle SQL로 서비스 영역·판매 여부·가격·식이 조건 필터링
        ↓
검수된 음식 개념과 메뉴 매핑 조회
        ↓
Oracle Vector Search + lexical/exact signal 검색
        ↓
RRF와 결정론적 점수로 최대 3개 메뉴 확정
        ↓
후보 ID와 순서를 DB에 동결
        ↓
OCI LLM이 동결된 후보의 설명만 생성
        ↓
서버가 순서·ID·evidence reference 검증
        ↓
검증된 결과 저장 및 프런트엔드 반환
```

## 11. 결론

YOBI의 가장 중요한 설계 특징은 Oracle Vector DB와 OCI LLM을 사용하면서도 최종 추천 결정권을 LLM에 위임하지 않는다는 점이다.

- 관계형 SQL이 객관적 자격 조건을 담당한다.
- 검수된 음식 지식과 메뉴 매핑만 추천 근거로 사용한다.
- Oracle Vector Search는 조건을 통과한 지식과 후보의 검색 순위를 지원한다.
- 서버가 추천 메뉴와 최종 순서를 결정하고 동결한다.
- OCI LLM은 동결된 결과의 설명만 작성한다.
- LLM 실패 시에도 메뉴 조건과 순서는 변하지 않는다.
- 로컬에서는 SQLite와 deterministic embedding으로 동일한 애플리케이션 계약을 테스트한다.

따라서 이 시스템은 일반적인 LLM 중심 추천 구조보다 데이터 무결성, 재현성, 근거 추적, 장애 대응을 강화한 서버 주도형 Hybrid RAG 아키텍처로 볼 수 있다.
