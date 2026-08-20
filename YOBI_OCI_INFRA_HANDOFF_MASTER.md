---
title: "YOBI OCI Infrastructure & Integration Handoff"
version: "1.0"
status: "Current verified state"
as_of: "2026-08-06 KST"
project: "YOBI — AI Food Ordering Agent for Foreign Tourists"
purpose: "Codex용 OCI 환경 인수인계 및 MVP 개발 기준 문서"
classification: "Internal / No secrets included"
---

# YOBI OCI Infrastructure & Integration Handoff

## 0. 문서 목적

이 문서는 YOBI 해커톤 MVP 개발을 위해 지금까지 실제로 구축하고 검증한 OCI 환경을 한 파일에 정리한 인수인계 문서다.

Codex는 이 문서를 기준으로 다음 작업을 수행해야 한다.

- 현재 OCI 아키텍처를 정확히 이해한다.
- 이미 완료된 인프라 작업을 불필요하게 반복하지 않는다.
- 검증된 Oracle Database 및 OCI Generative AI 연동 방식을 그대로 사용한다.
- 실제 Secret·비밀번호·OCID를 소스 코드나 Git에 저장하지 않는다.
- 남아 있는 애플리케이션 구현·DB 마이그레이션·배포 작업만 진행한다.
- OCI 자원의 생성·수정·삭제는 사용자의 명시적 승인 없이 수행하지 않는다.

이 문서에는 실제 API Key Secret, ADB 비밀번호, SSH Private Key, 전체 OCID, 실제 DSN, 공인 IP를 포함하지 않는다.

---

# 1. 가장 중요한 결론

## 1.1 현재 인프라 준비 상태

YOBI MVP 개발에 필요한 핵심 OCI 기능은 모두 실제 동작까지 검증됐다.

```text
사용자 브라우저
    ↓
React 프론트엔드
    ↓
FastAPI 백엔드
    ├─ OCI Generative AI API Key 전용 Endpoint
    │      ↓
    │   xai.grok-4.3
    │      ↓
    │   Function Calling
    │
    └─ Oracle Autonomous AI Database 26ai
           ├─ 관계형 데이터
           └─ VECTOR_DISTANCE 기반 벡터 검색
```

검증 완료 항목:

- OCI CLI Profile 및 대상 Compartment 접근
- VCN / Public Subnet / Private DB Subnet
- Compute VM 생성 및 SSH 접근
- FastAPI/Uvicorn 로컬 실행
- ADB Private Endpoint 연결
- `python-oracledb` Thin Mode + TLS 연결
- 기본 SQL 실행
- `VECTOR_DISTANCE` 실행
- OCI Generative AI Project 생성
- OCI Generative AI API Key 인증
- `xai.grok-4.3` Responses API 호출
- Grok 4.3 Function Calling
- 자연어 조건을 JSON 인자로 보존하는 Tool Call

## 1.2 확정된 GenAI 호출 방식

YOBI MVP는 아래 경로를 사용해야 한다.

```text
Base URL:
https://inference.generativeai.us-chicago-1.oci.oraclecloud.com/20231130/actions/v1

Authentication:
OCI Generative AI API Key Secret

Model:
xai.grok-4.3

Project OCID:
현재 성공한 호출 경로에서는 사용하지 않음
```

다음 Project 기반 경로는 현재 환경에서 사용하지 않는다.

```text
https://inference.generativeai.us-chicago-1.oci.oraclecloud.com/openai/v1
```

Project 기반 `/openai/v1` 호출에 API Key와 Project OCID를 함께 전달했을 때 다음 오류가 발생했다.

```text
404
Authorization failed or requested resource not found.
```

반면 API Key 전용 `/20231130/actions/v1` 경로는 Project OCID 없이 정상 성공했다.

따라서 Codex는 MVP 코드에서 다음을 지켜야 한다.

- `/20231130/actions/v1` 사용
- `OCI_GENAI_API_KEY` 사용
- `project=` 인자 사용 금지
- `/openai/v1` 사용 금지
- `xai.grok-4.3` 사용
- OpenAI Python SDK의 `client.responses.create()` 사용 가능

---

# 2. 프로젝트 및 OCI 기본 컨텍스트

## 2.1 프로젝트 목표

YOBI는 외국인 관광객이 한국어 배달 앱을 직접 탐색하지 않고도 대화형 AI를 통해 음식 탐색부터 주문 완료까지 진행하도록 돕는 AI 주문 에이전트다.

해커톤 MVP의 우선순위:

1. 정해진 데모 시나리오의 완전한 성공
2. 자연어 요구사항 이해
3. 식이 제약·맵기·예산·인원 조건 보존
4. 메뉴 검색 및 추천 근거
5. 옵션 선택 및 장바구니
6. Mock 주문 완료
7. Oracle Database와 OCI Generative AI의 실제 활용 증명
8. 발표 중 장애가 발생해도 흐름을 유지하는 Fallback

프로덕션 상용 서비스 수준의 고가용성, 다중 리전, 복잡한 IAM, 실제 결제, 실제 주문 연동은 현재 범위가 아니다.

## 2.2 OCI 계정 컨텍스트

| 항목 | 값 |
|---|---|
| OCI CLI Profile | `rndmgr` |
| Home / 기본 작업 Region | `ap-seoul-1` |
| Generative AI Region | `us-chicago-1` |
| 대상 Compartment | `HACK-TEAM-05` |
| OCI CLI 확인 버전 | `3.90.0` |
| 로컬 작업 루트 | `/Users/kimjunggil/Documents/YOBI/oci-infra` |

주의:

- Codex가 OCI 전체 Tenancy의 무제한 관리자 권한을 가진 것은 아니다.
- `rndmgr` Profile에 허용된 IAM 권한 범위 안에서만 작업 가능하다.
- 일부 IAM / Billing / Tenancy 전역 자원은 권한 부족일 수 있다.
- 권한 오류가 발생하면 더 넓은 Policy를 임의로 생성하지 않는다.

---

# 3. 현재 OCI 아키텍처

## 3.1 리전 구성

```text
ap-seoul-1
├─ VCN / Networking
├─ Compute: yobi-app-01
└─ Autonomous AI Database: yobi-adb

us-chicago-1
├─ Generative AI Project: yobi-agent
├─ Generative AI API Key: yobi-mvp-api-key
└─ Model: xai.grok-4.3
```

앱과 DB는 서울, GenAI는 Chicago에 있다.

해커톤 MVP에서는 이 Cross-Region 구성을 그대로 사용한다. 모델 호출 지연이 일부 존재할 수 있으나 실제 호출과 Function Calling이 성공했으므로 현재는 리전 재구성을 하지 않는다.

## 3.2 전체 논리 구조

```text
Internet
   │
   │ SSH: 사용자 공인 IP /32만 허용
   ▼
yobi-public-subnet (10.20.10.0/24)
   │
   └─ yobi-app-01
       ├─ Oracle Linux 9.8 x86_64
       ├─ FastAPI
       ├─ React 정적 파일 또는 별도 프론트엔드
       ├─ OpenAI Python SDK
       └─ python-oracledb Thin Mode
            │
            │ TLS TCP 1521
            │ Source: yobi-app-nsg
            ▼
yobi-db-subnet (10.20.20.0/24)
   └─ yobi-adb Private Endpoint
```

GenAI 호출:

```text
yobi-app-01
   │
   │ HTTPS
   ▼
OCI Generative AI API Key Endpoint
us-chicago-1
   │
   ▼
xai.grok-4.3
```

---

# 4. 네트워크 구성

## 4.1 생성된 자원

| 자원 | 이름 | 설정 |
|---|---|---|
| VCN | `yobi-vcn` | `10.20.0.0/16` |
| Public Subnet | `yobi-public-subnet` | `10.20.10.0/24` |
| DB Private Subnet | `yobi-db-subnet` | `10.20.20.0/24` |
| Internet Gateway | `yobi-igw` | Public Subnet 외부 통신 |
| Public Route Table | `yobi-public-rt` | Internet Gateway 경로 |
| DB Route Table | `yobi-db-rt` | 외부 Route 없음 |
| App NSG | `yobi-app-nsg` | Compute 접근 제어 |
| DB NSG | `yobi-db-nsg` | ADB 접근 제어 |

## 4.2 보안 규칙

### Compute SSH

- SSH는 사용자 공인 IP의 `/32`에서만 허용했다.
- Default Security List에 전 세계 대상 Public SSH 규칙을 두지 않았다.
- SSH Private Key는 사용자 로컬에만 보관한다.
- Private Key 파일 내용을 Codex 프롬프트, Git, 문서에 넣지 않는다.

### ADB 연결

- ADB는 Private Endpoint를 사용한다.
- `yobi-db-nsg`는 TCP 1521을 `yobi-app-nsg`에서만 허용한다.
- 일반 인터넷에서 ADB에 직접 접근하는 구조가 아니다.
- Mac 로컬에서 ADB에 직접 접속하는 것이 아니라 VM 내부에서 연결한다.
- VM에서 ADB Private DNS 해석 및 TCP 1521 접근이 성공했다.

## 4.3 아직 열지 않은 앱 포트

현재까지 검증된 네트워크는 SSH 및 VM→ADB 연결 중심이다.

최종 웹 데모를 브라우저에서 외부 공개하려면 다음이 추가로 필요할 수 있다.

- App NSG에 HTTP 80 또는 HTTPS 443 Ingress
- Nginx 또는 Caddy Reverse Proxy
- FastAPI 내부 포트는 Public으로 직접 노출하지 않는 구성
- 필요 시 도메인 및 TLS 인증서

Codex는 사용자 승인 없이 App NSG 규칙을 변경하지 않는다. 먼저 배포 구조와 필요한 포트를 제안하고 승인을 받아야 한다.

---

# 5. Compute 구성

## 5.1 VM 사양

| 항목 | 값 |
|---|---|
| Instance Name | `yobi-app-01` |
| Region | `ap-seoul-1` |
| OS | Oracle Linux 9.8 |
| Architecture | x86_64 |
| Shape | VM.Standard.E4.Flex |
| OCPU | 1 |
| Memory | 6 GB |
| Public IP | Ephemeral |
| Subnet | `yobi-public-subnet` |
| NSG | `yobi-app-nsg` |

Ephemeral Public IP이므로 VM Stop/Start 또는 네트워크 변경 후 IP가 달라질 수 있다. SSH 명령에 IP를 하드코딩한 배포 스크립트는 피한다.

## 5.2 검증된 런타임

- SSH 접속 성공
- Python 가상환경 사용
- 가상환경 경로: `~/venvs/yobi`
- 활성화: `source ~/venvs/yobi/bin/activate`
- FastAPI/Uvicorn 로컬 Smoke Test 성공
- `openai` Python SDK 설치 및 호출 성공
- `python-oracledb` Thin Mode 연결 성공

테스트 시 VM 프롬프트 예:

```text
(yobi) [opc@yobi-app-01 ~]$
```

## 5.3 배포 시 권장 구조

```text
/opt/yobi/
├─ backend/
├─ frontend/
├─ migrations/
├─ scripts/
└─ current -> release-directory

/etc/yobi/
└─ yobi.env

/etc/systemd/system/
└─ yobi.service
```

실제 경로는 Codex가 최종 프로젝트 구조와 함께 제안할 수 있지만, 민감정보는 소스 디렉터리와 분리해야 한다.

---

# 6. Autonomous AI Database 구성

## 6.1 ADB 사양

| 항목 | 값 |
|---|---|
| Display Name | `yobi-adb` |
| Database Name | `YOBI05MVP` |
| Region | `ap-seoul-1` |
| Workload | OLTP |
| Database Version | Oracle Database 26ai |
| Compute Model | ECPU |
| ECPU | 2 |
| Storage | 20 GB |
| Auto Scaling | OFF |
| License | LICENSE_INCLUDED |
| Network | Private Endpoint |
| mTLS | Disabled |
| TLS Port | 1521 |
| Subnet | `yobi-db-subnet` |
| NSG | `yobi-db-nsg` |

## 6.2 검증된 연결 방식

```text
python-oracledb Thin Mode
+ TLS
+ Private Endpoint
+ ADMIN 계정
```

검증 결과:

- Private DNS 확인 성공
- TCP 1521 연결 성공
- ADMIN 접속 성공
- 기본 SQL `SELECT 1` 성공
- `VECTOR_DISTANCE` COSINE 연산 성공

정확한 DSN, ADMIN 비밀번호, 접속 문자열은 이 문서에 포함하지 않는다.

## 6.3 확정할 런타임 환경변수

FastAPI는 다음 환경변수로 DB에 접속해야 한다.

```dotenv
ADB_DSN=
DB_USERNAME=
DB_PASSWORD=
```

`ADB_DSN`은 ADB TLS Connection String을 사용한다. 세션에서 사용한 방향은 `_tp` 서비스 계열이다.

## 6.4 앱 전용 DB 사용자

현재 실제 연결 검증은 ADMIN 계정으로 수행했다.

최종 앱은 ADMIN으로 실행하지 않는다.

Codex는 다음을 구현해야 한다.

```text
ADMIN
  └─ 최초 1회 YOBI_APP 사용자 생성
       └─ 이후 FastAPI는 YOBI_APP 계정만 사용
```

권장 사용자명: `YOBI_APP`

Oracle에서는 사용자와 같은 이름의 Schema가 생성되므로 YOBI 테이블은 다음과 같은 형태가 된다.

```text
YOBI_APP.RESTAURANTS
YOBI_APP.MENUS
YOBI_APP.MENU_INGREDIENTS
YOBI_APP.REVIEWS
YOBI_APP.MENU_EMBEDDINGS
YOBI_APP.DEMO_SESSIONS
YOBI_APP.DEMO_CART_ITEMS
YOBI_APP.DEMO_ORDERS
```

Codex가 작성해야 할 파일 예:

```text
database/
├─ admin/
│  └─ create_yobi_app_user.sql
├─ migrations/
│  ├─ 001_create_core_tables.sql
│  ├─ 002_create_vector_schema.sql
│  ├─ 003_create_indexes.sql
│  └─ 004_seed_demo_data.sql
└─ verify/
   └─ verify_schema.sql
```

중요:

- 실제 DB 사용자 비밀번호는 SQL 파일에 하드코딩하지 않는다.
- SQL*Plus substitution variable, 환경변수 또는 대화형 입력을 사용한다.
- 앱 실행 계정에는 Tenancy/IAM 권한이 필요 없다.
- 앱 DB 계정에는 필요한 DB 권한만 부여한다.
- ADMIN 비밀번호는 `/etc/yobi/yobi.env`에 넣지 않는다.
- FastAPI가 DDL을 임의로 실행하도록 만들지 않는다.
- 마이그레이션과 런타임 쿼리를 분리한다.

---

# 7. Oracle Vector 기능

## 7.1 검증 상태

ADB에서 `VECTOR_DISTANCE`의 COSINE 거리 계산이 정상 동작했다.

이는 다음 기능을 구현할 기반이 있다는 의미다.

- 메뉴 설명 임베딩 검색
- 리뷰 의미 검색
- 사용자의 자연어 요청과 메뉴 간 유사도
- 식이 제약 필터 후 벡터 랭킹
- 키워드 검색 + 벡터 검색 Hybrid Ranking

## 7.2 아직 미정인 항목

다음은 아직 구현되지 않았다.

- 임베딩 생성 모델
- Vector Dimension
- 메뉴 임베딩 데이터
- Vector Index
- 실제 Hybrid Search SQL
- Embedding Batch Job

Codex는 임의로 Dimension을 확정하지 말고 최종 MVP 명세에 맞춰 결정해야 한다.

MVP에서는 다음 방향을 우선한다.

1. 식이 제약, 알레르기, 돼지고기 제외 등은 SQL의 명시적 필터로 강제한다.
2. 벡터 검색은 취향·메뉴 설명·리뷰 유사도 랭킹에 사용한다.
3. 안전 조건을 벡터 유사도에 맡기지 않는다.
4. 데모 데이터 수가 작으면 Full Scan 기반 `VECTOR_DISTANCE`도 허용한다.
5. Vector Index는 데이터 크기와 구현 복잡도를 보고 선택한다.

---

# 8. OCI Generative AI Project

## 8.1 생성된 Project

| 항목 | 값 |
|---|---|
| Project Name | `yobi-agent` |
| Region | `us-chicago-1` |
| Compartment | `HACK-TEAM-05` |
| Description | `YOBI Responses API project for hackathon MVP` |
| Response Retention | 1 hour |
| Conversation Retention | 1 hour |
| Short-Term Memory | Disabled / Config omitted |
| Long-Term Memory | Disabled / Config omitted |
| Lifecycle | ACTIVE |

## 8.2 생성 과정에서 확인된 이슈

초기 생성 요청:

```json
{
  "conversationsRetentionInHours": 0,
  "responsesRetentionInHours": 0
}
```

결과:

```text
InvalidParameter
```

부분 생성 자원은 없었다.

수정 후:

```json
{
  "conversationsRetentionInHours": 1,
  "responsesRetentionInHours": 1
}
```

두 Memory Option을 Create 명령에서 제거한 뒤 Project 생성이 성공했고 `Overall: PASS`를 확인했다.

## 8.3 현재 역할

`yobi-agent`는 생성되어 있으나 현재 성공한 API Key 전용 호출 경로에서는 Project OCID를 사용하지 않는다.

따라서:

- Project를 삭제하지 않는다.
- 앱 코드에 Project OCID를 강제로 넣지 않는다.
- 현재 동작 경로를 Project 기반으로 되돌리지 않는다.
- 추후 Oracle API 변경 또는 별도 Project 기능이 필요할 때만 재검토한다.

---

# 9. OCI Generative AI API Key 및 IAM Policy

## 9.1 생성된 API Key

| 항목 | 값 |
|---|---|
| API Key Name | `yobi-mvp-api-key` |
| Region | `us-chicago-1` |
| Compartment | `HACK-TEAM-05` |
| Key Secret | Key one / Key two 생성 |
| Secret 보관 | 사용자가 개인적으로 보관 |
| 이 문서 포함 여부 | 포함하지 않음 |

Key one과 Key two Secret 중 하나를 런타임에서 사용하고 다른 하나는 교체·비상용으로 유지할 수 있다.

## 9.2 Policy

Policy Name:

```text
yobi-genai-api-key-policy
```

성공한 정책의 의도:

- `generativeaiapikey` Principal만 허용
- 특정 API Key OCID 하나로 제한
- `HACK-TEAM-05` Compartment 범위
- OCI Generative AI 사용 권한

사용한 정책 패턴:

```text
allow any-user to use generative-ai-family
in compartment HACK-TEAM-05
where ALL {
  request.principal.type='generativeaiapikey',
  request.principal.id='<GENERATIVE_AI_API_KEY_OCID>'
}
```

`any-user`라는 표현만 보고 범위가 무제한이라고 해석하면 안 된다. `where ALL` 조건에서 Principal Type과 특정 API Key OCID로 제한된다.

중요:

- Policy에는 Secret이 아니라 API Key OCID를 넣는다.
- 실제 Secret을 Policy 문장에 넣지 않는다.
- Policy OCID나 실제 API Key OCID를 소스코드에 넣을 필요가 없다.
- Codex는 현재 성공한 Policy를 임의로 수정하지 않는다.

---

# 10. Generative AI 모델 구성

## 10.1 Primary

```text
xai.grok-4.3
```

검증 내용:

- Chicago에서 ACTIVE 확인
- API Key 인증 성공
- Responses API 단순 응답 성공
- Function Calling 성공
- JSON Arguments Parsing 성공
- 사용자 제약 조건 보존 성공

## 10.2 Fallback 후보

```text
openai.gpt-oss-120b
```

확인 내용:

- Chicago에서 ACTIVE 상태 확인

주의:

- 실제 Fallback 추론은 아직 검증하지 않았다.
- Primary와 동일한 Tool Schema 호환성을 아직 검증하지 않았다.
- Codex는 Fallback을 구현할 경우 별도 Integration Test를 추가해야 한다.
- 데모 안정성을 위해 LLM 장애 시 deterministic mock fallback도 별도로 둔다.

---

# 11. 실제 성공한 GenAI 호출

## 11.1 단순 Responses API 테스트

사용한 핵심 구성:

```python
from openai import OpenAI

client = OpenAI(
    base_url=(
        "https://inference.generativeai."
        "us-chicago-1.oci.oraclecloud.com/20231130/actions/v1"
    ),
    api_key=api_key,
    timeout=120.0,
    max_retries=0,
)

response = client.responses.create(
    model="xai.grok-4.3",
    input=(
        "Reply with exactly this text and nothing else: "
        "YOBI_GENAI_OK"
    ),
)
```

실제 결과:

```text
PASS: OCI Generative AI API Key authentication succeeded
Model output: YOBI_GENAI_OK
```

## 11.2 Function Calling 테스트

Tool Name:

```text
search_menu
```

입력 의도:

```text
외국인 관광객 1명
돼지고기 제외
맵지 않음
15,000원 이하
```

실제 Grok 4.3 Tool Call 결과:

```json
{
  "query": "Korean meal for one person",
  "exclude_ingredients": [
    "pork"
  ],
  "max_spiciness": 0,
  "max_price_krw": 15000,
  "servings": 1
}
```

검증 결과:

```text
PASS: Grok requested exactly one function call
PASS: Function name is search_menu
PASS: Function arguments are valid JSON
PASS: Dietary, spice, budget, and serving constraints were preserved
```

이 결과는 다음 핵심 흐름이 기술적으로 가능하다는 의미다.

```text
자연어 사용자 요청
→ Grok 4.3
→ Tool 선택
→ 구조화된 JSON 인자 생성
→ FastAPI 검증
→ Oracle DB 검색
→ Tool 결과를 Grok에 전달
→ 자연어 추천 응답
```

## 11.3 Codex가 구현할 Function Calling Loop

단일 Tool Call을 감지하는 것으로 끝내지 말고 실제 앱에서는 다음 루프가 필요하다.

```text
1. 사용자 메시지를 Responses API에 전달
2. response.output에서 function_call 탐색
3. Pydantic으로 arguments 검증
4. 허용된 Tool Registry에서 함수 조회
5. Oracle DB Query 실행
6. Tool Result를 function_call_output으로 다시 전달
7. 최종 사용자 응답 생성
8. 최대 반복 횟수 초과 시 안전 종료
```

필수 안전장치:

- 허용된 Tool Name만 실행
- JSON Schema와 Pydantic 이중 검증
- SQL 문자열을 모델이 직접 만들게 하지 않음
- 파라미터 바인딩 사용
- Tool Call 최대 횟수 제한
- 타임아웃 설정
- Unknown Tool 거부
- 사용자에게 내부 Stack Trace 미노출
- 식이 제약은 DB Query에서 재검증

---

# 12. 런타임 환경변수

## 12.1 필수 변수

```dotenv
OCI_GENAI_BASE_URL=https://inference.generativeai.us-chicago-1.oci.oraclecloud.com/20231130/actions/v1
OCI_GENAI_API_KEY=
OCI_GENAI_MODEL=xai.grok-4.3

ADB_DSN=
DB_USERNAME=YOBI_APP
DB_PASSWORD=
```

추가 권장 변수:

```dotenv
APP_ENV=production
APP_HOST=127.0.0.1
APP_PORT=8000
LOG_LEVEL=INFO
LLM_TIMEOUT_SECONDS=120
LLM_MAX_RETRIES=1
TOOL_CALL_MAX_STEPS=4
DEMO_FALLBACK_ENABLED=true
```

## 12.2 저장 위치

MVP 권장 위치:

```text
/etc/yobi/yobi.env
```

권한:

```bash
sudo chown root:root /etc/yobi/yobi.env
sudo chmod 600 /etc/yobi/yobi.env
```

Systemd 예:

```ini
[Service]
EnvironmentFile=/etc/yobi/yobi.env
```

## 12.3 절대 저장하면 안 되는 위치

- React 소스
- 브라우저 번들
- GitHub Repository
- `.env.example`
- README
- Codex Prompt
- Migration SQL에 평문
- 테스트 Snapshot
- CI Log
- 프론트엔드 `VITE_*` 또는 `NEXT_PUBLIC_*` 환경변수
- 채팅 메시지

`.env.example`에는 변수 이름과 설명만 넣는다.

---

# 13. Codex의 OCI 접근 범위

## 13.1 Codex가 할 수 있는 일

환경과 권한이 주어졌을 때:

- YOBI 프론트엔드 및 백엔드 코드 작성
- OCI CLI를 이용한 Read-Only 조회
- 기존 VM 배포 스크립트 작성
- VM에서 FastAPI 실행
- ADB Migration 및 Seed Script 작성
- Oracle Vector Search SQL 작성
- Grok Responses API 연동 코드 작성
- Function Calling Loop 구현
- Systemd / Nginx 설정 파일 작성
- Smoke Test / Integration Test 작성

## 13.2 자동으로 할 수 없는 일

- 실제 Secret을 추측하거나 복구
- 사용자 로컬의 Private Key 내용을 안전하게 알아냄
- 권한이 없는 IAM / Billing 작업
- Private ADB에 Mac 로컬에서 직접 접속
- 사용자 승인 없는 Policy 확대
- 사용자 승인 없는 OCI 자원 생성·수정·삭제
- API Key Secret 재표시
- 실제 결제·요기요 주문 API 연동

## 13.3 작업 정책

Codex는 다음 원칙을 따른다.

```text
Read-only discovery
→ 실행 계획 제시
→ 정적 검증
→ 사용자 승인
→ 한 번의 변경
→ 사후 검증
```

특히 다음 명령은 사용자 승인 없이 실행하지 않는다.

```text
create
update
delete
terminate
stop
start
policy change
security rule change
API Key regeneration
```

---

# 14. 인프라 관련 파일 및 스크립트

현재 로컬 기준 주요 문서·스크립트:

```text
/Users/kimjunggil/Documents/YOBI/oci-infra/
├─ OCI_GENAI_PROJECT_PLAN.md
└─ scripts/
   ├─ phase4b_project_create.sh
   ├─ phase4b_project_verify.sh
   ├─ phase4b_instance_principal_probe.sh
   └─ phase4b_project_create.sh 관련 로그
```

## 14.1 `phase4b_project_create.sh`

역할:

- Project 생성 전 Gate
- 모델 ACTIVE 확인
- Project 0개 확인
- Dedicated AI Cluster 0개 확인
- 당시 API Key 0개 확인
- `CREATE YOBI-AGENT` 수동 입력 후 한 번만 Project 생성
- Retention 1/1
- Memory Config 생략
- `--no-retry`
- Work Request `SUCCEEDED` 대기
- 생성 후 Project 검증

중요:

- 이미 Project가 생성되었으므로 다시 실행하지 않는다.
- 현재는 API Key가 생성된 상태이므로 과거 Gate의 `API Key count=0` 조건도 더 이상 현재 상태와 맞지 않는다.
- 재실행 목적의 스크립트가 아니다.

## 14.2 `phase4b_project_verify.sh`

역할:

- Project 1개
- `yobi-agent` 1개
- ACTIVE
- Retention 1/1
- Memory Disabled
- Primary / Fallback Model ACTIVE
- Dedicated AI Cluster 0
- 당시 API Key 0

중요:

- API Key 생성 이후에는 `API Key count=0` 검사가 실패할 수 있다.
- 현재 전체 환경 검증기로 그대로 사용하지 않는다.
- 필요하면 `phase4c_current_state_verify.sh` 같은 새 Read-Only 검증기를 별도로 작성한다.
- 기존 스크립트의 역사적 목적을 보존하고 함부로 의미를 바꾸지 않는다.

## 14.3 Instance Principal Probe

Instance Principal 방식은 최종 MVP 인증 경로로 채택하지 않았다.

현재 선택:

```text
OCI Generative AI API Key
```

따라서 Dynamic Group / Instance Principal / IAM Policy 확장에 시간을 쓰지 않는다.

---

# 15. 현재 생성되지 않았거나 미완료인 항목

## 15.1 인프라

아직 최종 구성하지 않은 항목:

- Public HTTP/HTTPS Ingress
- Nginx 또는 Caddy
- 도메인
- TLS 인증서
- Load Balancer
- OCI Vault
- Dynamic Group
- Instance Principal 기반 GenAI 인증
- Dedicated AI Cluster
- Autoscaling
- Monitoring Dashboard
- Alert Rule
- Log Analytics
- CI/CD Pipeline
- Container Registry
- Kubernetes
- Multi-Instance HA

MVP에서 필요하지 않으면 만들지 않는다.

## 15.2 애플리케이션

아직 구현되지 않은 항목:

- 최종 React UI
- FastAPI API 설계
- Grok Tool Registry
- 실제 Function Calling Loop
- Oracle Schema
- YOBI_APP 사용자
- Migration
- Seed Data
- Vector Embeddings
- Hybrid Search
- Cart / Mock Order
- Session State
- Demo Fallback
- Systemd Service
- Reverse Proxy
- End-to-End Test

---

# 16. 권장 MVP 애플리케이션 구조

```text
yobi/
├─ frontend/
│  ├─ src/
│  ├─ public/
│  └─ package.json
│
├─ backend/
│  ├─ app/
│  │  ├─ main.py
│  │  ├─ api/
│  │  ├─ core/
│  │  │  ├─ config.py
│  │  │  ├─ logging.py
│  │  │  └─ security.py
│  │  ├─ db/
│  │  │  ├─ connection.py
│  │  │  ├─ repositories/
│  │  │  └─ models/
│  │  ├─ genai/
│  │  │  ├─ client.py
│  │  │  ├─ prompts.py
│  │  │  ├─ tool_schemas.py
│  │  │  ├─ tool_registry.py
│  │  │  └─ agent_loop.py
│  │  ├─ services/
│  │  └─ schemas/
│  ├─ tests/
│  └─ requirements.txt
│
├─ database/
│  ├─ admin/
│  ├─ migrations/
│  ├─ seed/
│  └─ verify/
│
├─ deploy/
│  ├─ yobi.service
│  ├─ nginx.conf
│  ├─ deploy.sh
│  └─ healthcheck.sh
│
├─ scripts/
├─ .env.example
└─ README.md
```

최종 개발 프롬프트에서 다른 구조를 선택할 수 있으나 다음 책임 분리는 유지한다.

- 프론트엔드
- API
- DB Repository
- GenAI Client
- Tool Schema
- Agent Loop
- Migration
- Deployment
- Tests

---

# 17. MVP Tool 후보

최소 Tool Set:

```text
search_menu
get_menu_detail
update_demo_cart
create_demo_order
```

선택 Tool:

```text
compare_menus
translate_order_option
get_restaurant_detail
get_review_summary
validate_dietary_constraints
```

중요:

- 초기 구현은 Tool 수를 최소화한다.
- Tool마다 Pydantic Input/Output Schema를 정의한다.
- Tool은 비즈니스 로직을 실행한다.
- LLM이 DB SQL을 직접 생성하거나 실행하지 않는다.
- 주문·결제는 Mock이다.
- 실제 외부 주문 API 호출은 하지 않는다.

---

# 18. 데모 데이터 원칙

모든 데모 데이터는 합성 또는 Mock 데이터로 구성한다.

```text
가상 사용자
가상 외국인 관광객 프로필
가상 호텔
가상 주소
가상 객실 번호
가상 음식점
가상 메뉴
가상 리뷰
가상 옵션
Mock 장바구니
Mock 결제
Mock 주문 번호
Mock 주문 상태
```

실제 개인정보, 실제 카드정보, 실제 주문은 사용하지 않는다.

Seed 데이터는 데모 시나리오에서 결과가 안정적으로 나오도록 설계한다.

예:

- 돼지고기 포함 메뉴
- 돼지고기 제외 메뉴
- 맵기 0~3
- 다양한 예산
- 1인 메뉴
- Vegetarian / Halal-friendly 후보
- 알레르기 성분
- 긍정·부정 리뷰
- 추천 근거가 분명한 메뉴

---

# 19. 안정적인 데모를 위한 Fallback

실제 기본 경로:

```text
Grok 4.3
→ Tool Call
→ Oracle DB
→ 최종 응답
```

오류 시:

```text
LLM Timeout / 429 / 5xx / Network Error
→ 고정된 Demo Scenario Detector
→ 사전 준비한 DB Query 또는 Fixture
→ 동일한 UI Flow 유지
```

Fallback 원칙:

- 발표 흐름을 깨지 않는다.
- 사용자에게 내부 OCI 오류를 그대로 보여주지 않는다.
- 로그에는 Fallback 사용 여부를 기록한다.
- 데모 화면에는 자연스러운 안내를 표시한다.
- Fallback 응답도 Oracle DB의 Seed 데이터와 일치해야 한다.
- 정상 경로와 Fallback 경로의 화면 결과가 크게 달라지지 않도록 한다.

---

# 20. 비용 및 운영 방침

## 20.1 현재 비용 발생 가능 자원

- ADB가 Active이면 Compute 비용이 누적될 수 있다.
- VM이 Running이면 Compute 비용이 누적될 수 있다.
- Boot Volume / DB Storage는 Stop 상태에서도 비용이 남을 수 있다.
- Grok은 On-Demand 호출 시 사용량 비용이 발생한다.
- Dedicated AI Cluster는 만들지 않았다.
- VCN, Subnet, NSG, Route Table, Project, Policy 자체는 현재 핵심 고정 Compute 비용의 중심이 아니다.

## 20.2 현재 사용자 결정

주최 측에서 팀별 약 250만 원의 OCI Credit을 제공했고 4주 동안 사용 가능하므로, 개발 편의를 위해 ADB와 VM을 계속 켜두는 방향을 허용한다.

그래도 다음은 지킨다.

- Dedicated AI Cluster를 만들지 않는다.
- Autoscaling을 임의로 켜지 않는다.
- Shape / ECPU를 임의로 확장하지 않는다.
- 불필요한 Load Balancer나 추가 VM을 만들지 않는다.
- 비용이 큰 자원 생성 전 사용자 승인을 받는다.
- Billing 접근이 가능하면 Compartment Cost를 주기적으로 확인한다.

---

# 21. 보안 규칙

## 21.1 Secret 목록

다음 값은 Secret 또는 민감 설정이다.

- OCI Generative AI Key one Secret
- OCI Generative AI Key two Secret
- ADB ADMIN Password
- YOBI_APP Password
- ADB DSN / Connection String
- SSH Private Key
- 전체 Resource OCID
- 실제 Public IP
- 운영 로그의 사용자 입력

## 21.2 처리 원칙

```text
Source Code       금지
Git               금지
Frontend          금지
Prompt            금지
README            금지
.env.example      값 저장 금지
VM env file       허용
Password Manager  허용
```

## 21.3 로그

Codex는 다음이 로그에 찍히지 않도록 구현한다.

- API Key
- DB 비밀번호
- 전체 DSN
- Authorization Header
- OpenAI Client 객체 전체
- OCI 오류 Response 전문
- 사용자 민감정보

오류 로그는 다음 정도만 허용한다.

```text
request_id
http_status
safe_error_code
sanitized_message
latency
fallback_used
```

---

# 22. 트러블슈팅 기록

## 22.1 Project Create `InvalidParameter`

증상:

```text
FAIL: Project create request failed (InvalidParameter)
```

원인 후보:

- Retention 0/0
- False Memory Config를 명시적으로 전달

해결:

- Retention 1/1
- Short-Term Memory 옵션 제거
- Long-Term Memory 옵션 제거
- 1회 재시도
- 성공 후 Overall PASS

## 22.2 Responses API 404

실패 구성:

```text
Base URL: /openai/v1
Authentication: Generative AI API Key
Project: yobi-agent Project OCID
```

증상:

```text
404
Authorization failed or requested resource not found.
```

정책 수정만으로 해결되지 않았다.

해결 구성:

```text
Base URL: /20231130/actions/v1
Authentication: Generative AI API Key
Project: 전달하지 않음
```

결과:

```text
PASS: OCI Generative AI API Key authentication succeeded
```

Codex는 이 이력을 무시하고 실패 경로를 다시 시도하지 않는다.

## 22.3 Function Calling

정상 Tool Call을 받았으며 JSON 제약 조건이 보존됐다.

따라서 Tool Calling 가능 여부를 다시 증명하는 데 시간을 쓰지 않고 실제 Agent Loop를 구현한다.

---

# 23. 개발 전 최종 체크리스트

## 23.1 이미 완료

- [x] OCI CLI Profile
- [x] Compartment 접근
- [x] VCN
- [x] Public Subnet
- [x] Private DB Subnet
- [x] Internet Gateway
- [x] Route Tables
- [x] App NSG
- [x] DB NSG
- [x] Compute VM
- [x] SSH
- [x] FastAPI Smoke Test
- [x] ADB
- [x] Private Endpoint
- [x] TLS DB 연결
- [x] Basic SQL
- [x] VECTOR_DISTANCE
- [x] Generative AI Project
- [x] Generative AI API Key
- [x] IAM Policy
- [x] Grok 4.3 Simple Response
- [x] Grok 4.3 Function Calling

## 23.2 Codex가 구현

- [ ] 최종 Monorepo
- [ ] React UI
- [ ] FastAPI
- [ ] Config Loader
- [ ] Oracle Connection Pool
- [ ] YOBI_APP User Script
- [ ] Migration
- [ ] Seed
- [ ] Vector Search
- [ ] GenAI Client
- [ ] Tool Schemas
- [ ] Tool Registry
- [ ] Agent Loop
- [ ] Cart
- [ ] Mock Order
- [ ] Demo Fallback
- [ ] Unit Tests
- [ ] Integration Tests
- [ ] Deployment Script
- [ ] Systemd
- [ ] Reverse Proxy
- [ ] Health Check
- [ ] Demo Reset Script

## 23.3 사용자가 마지막에 주입

- [ ] `OCI_GENAI_API_KEY`
- [ ] `ADB_DSN`
- [ ] `DB_USERNAME`
- [ ] `DB_PASSWORD`
- [ ] 필요 시 최신 VM Public IP
- [ ] NSG HTTP/HTTPS 변경 승인
- [ ] 실제 배포 실행 승인

---

# 24. Codex에게 전달할 절대 규칙

1. 이 문서에 적힌 기존 OCI 자원은 재생성하지 않는다.
2. 실제 Secret을 요구하지 않고 환경변수 인터페이스를 만든다.
3. GenAI는 `/20231130/actions/v1`만 사용한다.
4. `project=` 인자를 사용하지 않는다.
5. Primary Model은 `xai.grok-4.3`이다.
6. `openai.gpt-oss-120b`는 검증되지 않은 Fallback 후보일 뿐이다.
7. SQL은 모델이 생성해서 바로 실행하지 않는다.
8. 식이 제약은 DB의 명시적 필터로 강제한다.
9. ADB 앱 계정은 `YOBI_APP` 전용 계정을 사용한다.
10. ADMIN은 초기 사용자 생성 및 관리 작업에만 사용한다.
11. OCI 변경 작업은 사용자 승인 전까지 실행하지 않는다.
12. 기존 Project Create Script를 재실행하지 않는다.
13. 기존 Project Verify Script의 API Key 0개 조건은 현재 상태와 맞지 않는다.
14. API Key Secret은 Frontend에 절대 전달하지 않는다.
15. 실제 결제 및 주문은 Mock 처리한다.
16. 데모 Fallback을 반드시 구현한다.
17. 1 OCPU / 6 GB 환경에 맞춰 경량 구성을 사용한다.
18. 브라우저에 Stack Trace, DSN, OCI 오류 전문을 노출하지 않는다.
19. 완료 후 자동화된 검증 결과를 제공한다.
20. 구현이 끝났다고 선언하기 전에 정해진 End-to-End 데모 시나리오를 반복 실행한다.

---

# 25. Codex 작업 시작 시 권장 순서

```text
1. 이 문서를 읽고 Current State Summary 작성
2. 기존 Repository 조사
3. 변경 없는 Read-Only 확인
4. 최종 아키텍처와 파일 계획 작성
5. 로컬 코드 구현
6. 정적 검사 및 테스트
7. Migration / Seed Script 작성
8. Deployment Script 작성
9. 사용자 리뷰
10. 사용자 승인 후 YOBI_APP 생성
11. 사용자 승인 후 Migration 실행
12. Secret 수동 주입
13. 사용자 승인 후 VM 배포
14. Grok + Oracle DB Integration Test
15. Frontend End-to-End Test
16. Demo Reset 및 Fallback Test
17. 최종 인수인계
```

---

# 26. 최종 현재 상태 요약

```text
OCI Home Region
└─ ap-seoul-1

Compartment
└─ HACK-TEAM-05

Network
├─ yobi-vcn: 10.20.0.0/16
├─ yobi-public-subnet: 10.20.10.0/24
├─ yobi-db-subnet: 10.20.20.0/24
├─ yobi-igw
├─ yobi-public-rt
├─ yobi-db-rt
├─ yobi-app-nsg
└─ yobi-db-nsg

Compute
└─ yobi-app-01
   ├─ Oracle Linux 9.8
   ├─ VM.Standard.E4.Flex
   ├─ 1 OCPU / 6 GB
   ├─ Ephemeral Public IP
   ├─ FastAPI Smoke Test PASS
   └─ GenAI Function Calling PASS

Database
└─ yobi-adb
   ├─ YOBI05MVP
   ├─ Oracle Database 26ai
   ├─ OLTP
   ├─ 2 ECPU
   ├─ 20 GB
   ├─ Private Endpoint
   ├─ TLS 1521
   ├─ python-oracledb Thin PASS
   └─ VECTOR_DISTANCE PASS

Generative AI
└─ us-chicago-1
   ├─ Project: yobi-agent
   │  ├─ ACTIVE
   │  ├─ Retention 1/1
   │  └─ Memory Disabled
   ├─ API Key: yobi-mvp-api-key
   ├─ Policy: yobi-genai-api-key-policy
   ├─ Primary: xai.grok-4.3
   ├─ Fallback Candidate: openai.gpt-oss-120b
   ├─ Endpoint: /20231130/actions/v1
   ├─ Simple Response PASS
   └─ Function Calling PASS
```

---

# 27. 문서 사용법

이 문서는 다음 최종 MVP 개발 프롬프트와 함께 Codex에 제공한다.

```text
1. YOBI 최종 제품/기획 문서
2. YOBI 최종 MVP 개발 명세
3. 본 OCI Infrastructure Handoff 문서
```

Codex는 제품 기능 판단은 최종 MVP 개발 명세를 따르고, OCI 관련 사실과 제약은 본 문서를 따른다.

두 문서가 충돌할 경우:

- OCI 리소스의 실제 이름·리전·연결 방식은 본 문서 우선
- 제품 UX·기능 범위는 최종 MVP 개발 명세 우선
- Secret·보안 규칙은 더 엄격한 쪽 우선
- 불확실한 OCI 변경은 실행하지 말고 사용자에게 질문

---

# 28. 변경 이력

## v1.0 — 2026-08-06

- OCI Network / Compute / ADB 구축 결과 통합
- Project 생성 실패 및 Retention 1/1 해결 기록
- Generative AI API Key / Policy 구성 반영
- `/openai/v1` 404 이슈 기록
- `/20231130/actions/v1` 성공 경로 확정
- Grok 4.3 단순 응답 및 Function Calling 성공 결과 반영
- 최종 MVP 구현에 필요한 런타임 설정과 보안 원칙 정리
- 기존 Phase 4B 검증 스크립트의 API Key 0개 조건이 현재 상태와 맞지 않음을 명시
