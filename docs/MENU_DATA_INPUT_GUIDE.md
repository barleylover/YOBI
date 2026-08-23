# YOBI 메뉴 데이터 전달 및 적재 가이드

이 문서는 YOBI 카탈로그에 가게와 메뉴를 추가할 때 필요한 전달 형식, 외부
public-web 원본과 합성 데모 원본의 구분, 그리고 실제 Oracle 적재 경로를 설명한다.

## 1. 현재 데이터 저장 구조

YOBI에는 서로 섞어 말하면 안 되는 두 입력 경로가 있다.

1. **외부 카탈로그 경로**: 공개 Yogiyo 웹에서 수집·전달된 필드를
   `YOGIYO_PUBLIC_WEB`로 보존한다. `prepare_yogiyo_catalog_package.py`가 원본과
   전달용 workbook을 검증해 불변 `yobi-external-catalog-v1` ZIP을 만들고,
   `import_external_catalog.py`가 source-detail/원본 payload/provenance와 함께
   SQLite 또는 Oracle에 적재한다. 이는 실시간 Yogiyo API가 아니다.
2. **합성 fixture 경로**: `backend/app/db/seed_data.py`와
   `knowledge/dishes/**/*.md`가 결정적 `SYNTHETIC_DEMO` 카탈로그를 만들고
   `scripts/seed_demo.py`가 관계형 행과 임베딩을 적재한다. 로컬 개발과 회귀에
   계속 사용한다.

외부 카탈로그에 추천 근거를 붙이는 단계는 별도다.
`knowledge/external_dishes/**/*.md`의 `SYNTHETIC_WIKI`/`REVIEWED_DEMO` 일반 음식
문서와 결정적 메뉴명 규칙을 `build_external_knowledge_release.py`가 컴파일한다.
이 단계가 만드는 `YOBI_DERIVED_DEMO_MAPPING`과 preference-support 행은 일반 음식
지원 레이어이며, 외부 원본이 제공하지 않은 가게별 레시피·재료·정식 인증·맵기·
인원 정보를 만들지 않는다. 모든 메뉴는 high-confidence mapping 또는 명시적인
미매핑 사유 중 하나를 갖는다.

- OCI 운영 환경은 SQLite `.db` 파일을 업로드하여 사용하지 않는다.
- 운영 FastAPI는 `DEMO_DB_BACKEND=oracle` 설정에 따라 Oracle 저장소를 조회한다.
- 로컬 개발에서는 별도로 생성한 SQLite `backend/data/yobi_demo.db`를 사용한다.
- 로컬 SQLite DB 파일은 Git과 배포 패키지에서 제외된다.

따라서 구조는 다음 두 특성을 함께 가진다.

1. 재현 가능한 원본은 checksum이 있는 외부 package 또는 코드/지식 Markdown이다.
2. 실제 OCI 앱은 Oracle DB의 active catalog/recommendation release를 조회한다.

### 2026-08-15 합성 운영 스냅샷(역사 기록)

당시 공개 `/readyz` 응답으로 확인한 상태는 다음과 같다. 아래 60/600 수치는
외부 카탈로그 전환 전의 역사 기록이며 현재 목표 개수로 사용하지 않는다.

| 항목 | 확인 결과 |
|---|---:|
| DB 백엔드 | `oracle-26ai` |
| 가게 | 60 |
| 메뉴 | 600 |
| 메뉴 카테고리 | 100 |
| 메뉴 지식 | 600 |
| 옵션 그룹 | 1,202 |
| 옵션 항목 | 2,405 |
| 리뷰 스니펫 | 2,400 |
| 근거 행 | 1,200 |
| `canonical_ready` | `true` |
| `knowledge_ready` | `true` |
| `vector_ready` | `true` |

당시 가게, 메뉴, 인증, 리뷰 데이터는 실제 요기요 연동 데이터가 아닌 합성
데모 데이터였다.

### 2026-08-16 외부 카탈로그 전환 전 읽기 전용 기준선

| 항목 | 확인 결과 |
|---|---:|
| DB 백엔드 | `oracle-26ai` |
| 데이터 원천 | `YOGIYO_PUBLIC_WEB` |
| 가게 | 200 |
| 메뉴 | 15,085 |
| 옵션 그룹 | 31,293 |
| 옵션 항목 | 208,513 |
| active 외부 Wiki concept/mapping/support | 0 / 0 / 0 |

이 기준선은 외부 merchant/menu/price/option 적재만 증명했으며 추천 준비 완료를
뜻하지 않았다. 2026-08-16 로컬 mirror builder는 15,085개 메뉴 전부를 분류하고
1,955개 high-confidence mapping 및 1,073개 reviewed support 행을 만들었지만,
그 수치는 현재 가족 이전의 역사적 기준이다.

2026-08-17 최종 확장 릴리스는 재현 가능한 동일 package/import 경로 위에서
일반 음식 Wiki 84개를 추가하고 mapping 규칙을 재검토해 3,922개
high-confidence mapping, 1,499개 reviewed support, 198개 concept/document,
1,551개 chunk를 만들었다. 이 가족은 Oracle에 활성화되어 있으며 public readiness와
브라우저까지 검증됐다. 식당별 조리법·인증·알레르기·메뉴 맵기 사실은 추가로
발명하지 않았다. 최종 증거는 `TEST_REPORT.md`, `OCI_DEPLOYMENT.md`,
`evidence/KNOWLEDGE_EXPANSION_20260817.md`에 기록한다.

## 2. 권장 전달 형식

합성 fixture에 메뉴를 수동 추가하거나 원본을 정규화해 전달할 때는 **하나의
Excel `.xlsx` 파일**을 권장한다. 외부 운영 적재는 workbook만 직접 import하지
않고, 원본 payload와 선택 merchant 목록을 함께 검증해 만든
`yobi-external-catalog-v1` package를 사용한다. workbook은 다음 시트로 구분한다.

| 시트 | 용도 | 필수 여부 |
|---|---|---|
| `merchants` | 신규 가게 정보 | 신규 가게가 있을 때만 |
| `menus` | 메뉴 기본 정보 | 필수 |
| `option_groups` | 사이즈, 맵기, 토핑 등의 옵션 그룹 | 옵션이 있을 때 |
| `option_items` | 옵션별 선택 항목과 추가금 | 옵션이 있을 때 |
| `ingredients` | 확인된 재료와 선택 가능 여부 | 권장 |
| `certifications` | 정식 할랄 인증 정보 | 인증이 있을 때만 |

한두 개 메뉴만 추가한다면 이 문서의 YAML 예시와 같은 구조로 채팅에 붙여 넣어도 된다.

## 3. `menus` 시트

메뉴 한 개당 한 행을 작성한다.

| 열 | 설명 | 예시 |
|---|---|---|
| `source_menu_key` | 전달 파일 안에서 사용하는 고유 키 | `new_001` |
| `merchant_ref` | 기존 `merchant_id` 또는 `source_merchant_key` | `mer_001` |
| `name_ko` | 한국어 메뉴명 | `치즈 불고기 덮밥` |
| `name_en` | 영어 메뉴명 | `Cheese Bulgogi Rice Bowl` |
| `category_name` | 음식 카테고리 또는 표준 음식명 | `Bulgogi` |
| `description` | 메뉴 구성과 맛 설명 | `불고기와 치즈를 올린 덮밥` |
| `cultural_description` | 외국인 사용자를 위한 문화적 설명 | `한국식 간장 불고기를 밥과 함께 먹는 메뉴` |
| `price_krw` | 원화 기준 기본 가격 | `12900` |
| `serves_min` | 최소 권장 인원 | `1` |
| `serves_max` | 최대 권장 인원 | `1` |
| `spice_level` | YOBI 5단계 맵기 수준 | `1` |
| `availability` | 판매 상태 | `AVAILABLE` |
| `data_origin` | 데이터 출처 구분 | `SYNTHETIC_DEMO` 또는 검증된 `YOGIYO_PUBLIC_WEB` |

### 값 규칙

- `source_menu_key`는 파일 안에서 중복되지 않아야 한다.
- 맵기 수준은 현재 공개 추천 기준인 `1`부터 `5`까지 사용한다.
- `availability`는 `AVAILABLE`, `SOLD_OUT`, `PAUSED` 중 하나를 사용한다.
- 수동으로 만든 목업 데이터라면 `data_origin`은 반드시 `SYNTHETIC_DEMO`로
  작성한다. `YOGIYO_PUBLIC_WEB`은 원본 payload와 수집 시각/플랫폼 식별자가 함께
  있는 외부 package builder만 설정할 수 있다.
- 설명이 한국어만 있어도 된다. 영문 메뉴명과 설명은 적재 과정에서 정규화할 수 있다.
- 모르는 값은 임의로 추측하지 말고 빈칸 또는 `UNKNOWN`으로 작성한다.
- 기존 메뉴를 수정하는 경우 `source_menu_key` 대신 실제 `menu_id`도 함께 제공한다.

다음 파생 필드는 전달자가 만들 필요가 없다.

- `menu_id`, `category_id`, `merchant_id` 등의 DB ID
- `semantic_text`
- 임베딩 벡터 및 임베딩 버전
- `evidence_id`, `knowledge_id`
- Wiki `concept_id`와 release ID
- `updated_at`, `is_synthetic`

위 값은 기존 규칙과 충돌하지 않도록 적재 과정에서 생성한다.

## 4. `merchants` 시트

기존 가게에 메뉴만 추가한다면 생략한다. 신규 가게를 추가할 때는 다음 열을 사용한다.

| 열 | 설명 |
|---|---|
| `source_merchant_key` | 전달 파일 내 신규 가게 고유 키 |
| `name_ko` | 한국어 가게명 |
| `name_en` | 영어 가게명 |
| `service_area` | 서비스 지역 |
| `description` | 가게 설명 |
| `delivery_fee_krw` | 배달비 |
| `eta_min` | 최소 배달 예상 시간(분) |
| `eta_max` | 최대 배달 예상 시간(분) |
| `min_order_amount_krw` | 최소 주문 금액 |
| `flavor_profile` | 가게의 대표 맛 특성 |
| `packaging_signal` | 포장 관련 합성 설명 |
| `data_origin` | `SYNTHETIC_DEMO` 또는 검증된 외부 package의 `YOGIYO_PUBLIC_WEB` |

합성 fixture의 서비스 지역은 다음 세 곳이다.

- `Myeongdong`
- `Hongdae`
- `Gangnam`

외부 import는 현재 지원되는 고정 데모 주소와 동일한 서비스 지역으로 정규화한다.
새로운 서비스 지역이 필요하면 기존 값 대신 신규 지역임을 별도로 표시한다. 이
경우 `SERVICE_AREA`, 주소 fixture, browse/recommendation filter, readiness 계약을
함께 변경해야 한다.

## 5. 옵션 데이터

### `option_groups` 시트

| 열 | 설명 |
|---|---|
| `source_group_key` | 전달 파일 내 옵션 그룹 고유 키 |
| `source_menu_key` | 소속 메뉴 키 |
| `name_ko` | 한국어 그룹명 |
| `name_en` | 영어 그룹명 |
| `description` | 옵션 설명 |
| `required` | 필수 선택 여부, `true` 또는 `false` |
| `min_select` | 최소 선택 개수 |
| `max_select` | 최대 선택 개수 |
| `sort_order` | 화면 표시 순서 |

### `option_items` 시트

| 열 | 설명 |
|---|---|
| `source_item_key` | 전달 파일 내 옵션 항목 고유 키 |
| `source_group_key` | 소속 옵션 그룹 키 |
| `name_ko` | 한국어 항목명 |
| `name_en` | 영어 항목명 |
| `description` | 항목 설명 |
| `price_delta_krw` | 기본 가격에서 추가되는 금액 |
| `availability` | `AVAILABLE`, `SOLD_OUT`, `PAUSED` |
| `dietary_conflict` | 선택 시 발생할 수 있는 식단 충돌 설명 |
| `sort_order` | 화면 표시 순서 |

필수 옵션 그룹에서는 `AVAILABLE` 상태인 항목 수가 `min_select`보다 적으면 안 된다.

## 6. `ingredients` 시트

| 열 | 설명 |
|---|---|
| `source_menu_key` | 소속 메뉴 키 |
| `ingredient_name_ko` | 한국어 재료명 |
| `ingredient_name_en` | 영어 재료명 |
| `status` | 재료 확인 상태 |
| `is_optional` | 제거 또는 변경 가능한 재료인지 여부 |
| `source_note` | 해당 판단의 목업 근거 |

`status`는 다음 중 하나를 사용한다.

- `CONFIRMED_PRESENT`: 메뉴에 포함된 것으로 확인됨
- `POSSIBLE`: 포함 가능성이 있음
- `UNKNOWN`: 확인되지 않음
- `CONFLICTING`: 정보가 서로 충돌함

현재 공개 추천 경로에는 알레르기 필터가 없다. 따라서 알레르기 데이터는 신규 메뉴 입력의 필수값이 아니다. 다만 비건 판단에 필요한 동물성 재료와 옵션으로 제거 가능한 재료는 가능한 한 작성한다.

## 7. `certifications` 시트

할랄은 단순한 `halal=true` 값으로 처리하지 않는다. 인증을 표시하려면 다음 정보를 제공해야 한다.

| 열 | 설명 |
|---|---|
| `issuer` | 인증 발급기관 |
| `certificate_number` | 인증번호 |
| `valid_from` | 인증 유효 시작일 |
| `valid_to` | 인증 유효 종료일. 종료일이 없으면 빈칸 가능 |
| `scope_type` | `MERCHANT` 또는 `MENU` |
| `scope_ref` | 메뉴 범위 인증이면 해당 `source_menu_key` |
| `source_type` | 근거 유형 |
| `source_ref` | 근거 문서 또는 목업 출처 설명 |
| `data_origin` | 목업이면 `SYNTHETIC_DEMO` |

인증 정보가 없으면 빈칸 또는 `null`로 둔다. 현재 외부 public-web package에는
정식 인증 근거가 없으므로 이를 메뉴명·설명·일반 Wiki에서 추론하지 않는다.
목업 인증은 실제 인증으로 오해되지 않도록 발급기관, 인증번호, 출처에 합성
데이터임을 명시해야 한다. 충분한 현재 범위 인증이 없으면 preference catalog가
할랄 control을 `enabled=false`와 이유로 내려준다.

## 8. 한두 개 메뉴 전달용 YAML 예시

```yaml
data_origin: SYNTHETIC_DEMO
merchant_ref: mer_001
source_menu_key: new_001
name_ko: 치즈 불고기 덮밥
name_en: Cheese Bulgogi Rice Bowl
category_name: Bulgogi
description: 불고기와 치즈를 올린 덮밥
cultural_description: 한국식 간장 불고기를 밥과 함께 먹는 메뉴
price_krw: 12900
serves_min: 1
serves_max: 1
spice_level: 1
availability: AVAILABLE

ingredients:
  - name_ko: 소고기
    name_en: Beef
    status: CONFIRMED_PRESENT
    is_optional: false
    source_note: 합성 메뉴 사양
  - name_ko: 치즈
    name_en: Cheese
    status: CONFIRMED_PRESENT
    is_optional: true
    source_note: 옵션으로 제거 가능

options:
  - source_group_key: new_001_cheese
    name_ko: 치즈 선택
    name_en: Cheese option
    required: true
    min_select: 1
    max_select: 1
    items:
      - source_item_key: new_001_cheese_keep
        name_ko: 치즈 포함
        name_en: Keep cheese
        price_delta_krw: 0
        availability: AVAILABLE
      - source_item_key: new_001_cheese_remove
        name_ko: 치즈 제외
        name_en: Remove cheese
        price_delta_krw: 0
        availability: AVAILABLE

halal_certification: null
```

## 9. 적재 시 함께 변경해야 하는 항목

Readiness는 source integrity와 recommendation readiness를 분리해 검사한다.
Oracle에 메뉴 행만 수동으로 추가하면 import checksum, 전체 메뉴 classification,
active knowledge/mapping/support/ranking manifest, demo address, query-plan 조건이
맞지 않아 `/readyz` 또는 외부 release gate가 실패한다.

신규 데이터를 받을 때 다음 작업을 한 묶음으로 수행해야 한다.

1. 원본 유형과 `data_origin`을 정하고 외부 원본이면 payload/수집 시각을 보존
2. 외부 package 또는 결정적 합성 seed를 생성하고 SHA-256/행 수 검증
3. 기존 또는 신규 카테고리와 옵션 원본 연결
4. 모든 메뉴에 high mapping 또는 명시적 미매핑 분류 사유 부여
5. 일반 Wiki 문서와 reviewed preference-support manifest 생성
6. 외부 원본에 없는 재료·인증·맵기·인원은 `UNKNOWN`/미제공으로 유지
7. 로컬 SQLite stage/apply/verify와 SQLite/Oracle query contract 회귀 테스트
8. Oracle에 catalog를 적재하고 knowledge/family를 `READY` 상태로 stage
9. active pointer를 바꾸기 전 exact manifest, query plan, capability/readiness 검증
10. 활성화 후 구조화 추천, browse, 동적 cart→mock order backend smoke와 public
    Yogiyo-handoff UI를 각각 검증

운영 DB에 직접 SQL로만 추가하는 방식은 사용하지 않는다. 소스 package/Markdown,
분류·support manifest, Oracle 데이터가 다음 배포에서도 동일하게 재현되도록
원본과 검증 계약을 함께 갱신한다. 브라우저의 handoff는 주문 적재 경로가 아니며,
`MOCK_CHECKOUT`/`MOCK_ORDER`는 배포 smoke와 회귀 테스트용 백엔드 경계다.
