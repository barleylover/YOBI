# YOBI LLM 번역 하드닝·국가별 설명 보완 최종 작업 계획

- 작성일: 2026-08-23
- 판단 기준 브랜치: `master`
- 판단 기준 HEAD: `ad3513f4085323f3f2defa74cb28848c9e6ad88c`
- 실제 구현 브랜치: `codex/llm-translation-hardening`
- 현재 상태: 구현·로컬 검증 완료, 운영 DB·prewarm·배포 미실행
- 목표: 데모의 기존 영어 경로를 즉시 복구할 수 있게 보존하면서 16개 언어의 메뉴 설명과 근거 있는 국가별 비교 설명을 안전하게 지원한다.

## 1. 최종 결론

이번 작업은 단순히 “한국어 설명을 번역해 저장”하는 변경이 아니다. 다음 네 계약을 분리해서 구현한다.

1. 식당 원문 번역
   - `localized_source_description`은 식당이 제공한 한국어 원문의 충실한 번역이다.
   - 같은 원문·같은 언어라면 미국과 영국 사용자에게 원칙적으로 같은 번역을 사용한다.
   - 국가별 표현 수정이나 음식 비교는 이 필드에 넣지 않는다.
2. YOBI 설명
   - `yobi_short_explanation`·`yobi_long_explanation`은 사용자 언어로 생성한다.
   - 서버가 제공한 국가·대표 음식·매운맛 기준 근거가 있을 때만 친숙한 표현이나 비교를 넣을 수 있다.
3. 국가별 메뉴 선호도
   - `country_preference`는 사용자 국가 설정이 아니라 `{country_code, preference_percent, sample_size}` 형태의 메뉴별 합성 데모 통계다.
   - 정상 국가의 UI 블록은 유지하지만, 국가를 모르는 `ZZ`는 표시하지 않는다.
   - 합성 퍼센트·표본 수를 LLM의 문화적 비교 근거로 사용하지 않는다.
4. 사용자 국가와 매운맛 비교 국가
   - `profile.country_code`는 사용자가 온보딩에서 선택한 국가다.
   - `criteria.spice_reference_country`는 사용자가 매운맛 비교 기준으로 선택한 국가다.
   - 두 값이 다르면 “사용자 국가”라고 합쳐 부르지 않고 역할을 구분한다.

추천 후보 생성·최종 3개 선택·순서는 이번 변경으로 바꾸지 않는다. 언어와 국가는 선택 완료 후 프레젠테이션 단계에만 영향을 준다.

## 2. 용어와 최종 데이터 계약

| 값 | 소유자 | 용도 | LLM 사용 정책 |
|---|---|---|---|
| `profile.preferred_language` | 사용자 프로필 | 목표 표시 언어 결정 | 정규화한 16개 로케일 코드를 프레젠테이션에 사용 |
| `profile.country_code` | 사용자 프로필 | 사용자 국가, 국가별 캐시 분리 | `ZZ`가 아니면 친숙한 표현의 국가 맥락으로 사용 |
| `criteria.spice_reference_country` | 추천 조건 | 매운맛 하드필터·비교 기준 | 대표 음식과 기준값이 있을 때 매운맛 비교에 사용 |
| `country_preference` | 합성 메뉴 보강 데이터 | 국가별 메뉴 선호도 UI 블록 | 새 국가별 설명 프롬프트에는 퍼센트·표본 수를 전달하지 않음 |
| `localized_source_description` | 식당 원문 번역 | 원문을 대상 언어로 충실하게 전달 | 국가별 각색 금지 |
| `yobi_short/long_explanation` | YOBI 프레젠테이션 | 근거 기반 설명·필요 시 국가별 비교 | 국가별 표현은 이 필드에서만 허용 |

새 프레젠테이션 입력에는 다음처럼 역할이 분리된 서버 소유 컨텍스트를 사용한다.

```json
{
  "target_locale": "en",
  "user_country_code": "GB",
  "spice_reference": {
    "country_code": "GB",
    "representative_dish_en": "Chicken tikka masala",
    "spice_baseline": 2,
    "menu_spice_level": 3,
    "relationship": "MORE"
  }
}
```

규칙은 다음과 같다.

- `user_country_code`가 없거나 `ZZ`이면 국가 친숙화 문장을 만들지 않는다.
- 매운맛 대표 음식 비교는 `spice_reference`의 서버 제공 값이 완전할 때만 허용한다.
- `profile.country_code`와 `spice_reference.country_code`가 같으면 사용자 국가 기준이라고 설명할 수 있다.
- 두 값이 다르면 “사용자가 선택한 매운맛 기준 국가”라고 설명한다.
- 음식의 재료·조리법·문화적 유사성에 대한 일반 비유는 Wiki/메뉴 근거가 없으면 만들지 않는다.
- 합성 `country_preference.preference_percent`와 `sample_size`를 근거로 “영국인은 이 메뉴를 좋아한다” 같은 문장을 만들지 않는다.
- 국가 언급을 모든 메뉴에 강제하지 않는다. 매운맛 비교가 유용하고 근거가 완전한 메뉴의 긴 설명에서만 한 번 사용할 수 있다.
- 국가 맥락을 실제 문장에 사용했을 때만 `personalization_applied=true`로 기록한다.

## 3. 미국 영어와 영국 영어의 최종 동작

| 항목 | 영어/미국 | 영어/영국 | 같아야 하는가 |
|---|---|---|---|
| 추천 메뉴 3개와 순서 | 기존 선택 결과 | 기존 선택 결과 | 같아야 함 |
| 식당 원문 영어 번역 | 충실한 영어 번역 | 동일 원문의 충실한 영어 번역 | 원칙적으로 같아야 함 |
| YOBI 설명 | 미국 국가 맥락, 필요 시 `Buffalo wings` 기준 | 영국 국가 맥락, 필요 시 `Chicken tikka masala` 기준 | 근거가 있으면 달라질 수 있음 |
| 프레젠테이션 캐시 | `US`가 포함된 키 | `GB`가 포함된 키 | 반드시 달라야 함 |
| 국가 선호도 UI | 유효한 US 통계 표시 | 유효한 GB 통계 표시 | 각 국가 데이터대로 표시 |

새 기능 플래그가 꺼져 있으면 현재 `en/ko/ja` 프레젠테이션 경로와 기존 캐시를 그대로 사용한다. 플래그가 켜져 있을 때만 새 16개 언어·국가 컨텍스트 경로와 별도 캐시를 사용한다. 따라서 운영에서 문제가 생기면 기존 영어 데모 경로로 즉시 되돌릴 수 있다.

기능적 회귀 방지 대상은 다음과 같다.

- 추천 메뉴 ID와 순서
- 영어 API 응답 필드와 타입
- 제목과 원문 설명의 안전한 fallback
- 옵션 선택·장바구니·결제 데모 흐름
- 프레젠테이션 실패 시 결정론적 영어 fallback
- 플래그가 꺼진 상태의 기존 provider 요청·캐시 사용·호출 횟수

새 플래그를 켠 영어 설명은 국가 컨텍스트를 추가하는 의도적 변경이므로 문구가 기존과 완전히 동일하다고 보장하지 않는다. 대신 fake provider로 계약·캐시 분리·fallback·선택 결과 불변을 검증한다.

## 4. 시작 전 작업 원칙

실제 구현을 시작할 때 다음 순서를 반드시 지킨다.

1. `git branch --show-current`, `git rev-parse HEAD`, `git status --short --branch`를 다시 확인한다.
2. 기준 HEAD가 달라졌다면 이 문서의 파일·라인 판단을 새 HEAD에 맞춰 다시 점검한다.
3. 기존 변경을 보존한 채 `codex/llm-translation-hardening` 브랜치를 생성하거나 전환한다.
4. 다음 기존 미추적 파일은 수정·삭제·스테이징·커밋하지 않는다.
   - `docs/design/yobi-oci-physical-architecture-743436b.png`
   - `docs/design/yobi-recommendation-erd-743436b.png`
   - `output/presentations/YOBI_10분_발표_스크립트_master_기준.md`
5. SQLite와 Oracle repository의 메서드 시그니처와 동작을 동시에 변경한다.
6. 실제 OCI LLM을 반복 호출하지 않는다. 테스트는 fake provider와 결정론적 실패 주입을 사용한다.
7. OCI DB 마이그레이션 적용, 운영 데이터 변경, 기존 캐시 삭제, prewarm, 배포, 공개 환경 변경은 수행하지 않는다.
8. 관련 파일만 명시적으로 스테이징하며 `git add .`를 사용하지 않는다.

## 5. 목표 데이터 흐름

```text
profile.preferred_language ── normalize_preference_locale() ── target_locale 16개
profile.country_code ───────────────────────────────────────── user_country_code
criteria.spice_reference_country ── country spice row ─────── comparison context
한국어 식당 원문 + Wiki/menu evidence ─────────────────────── grounded source

                         feature flag OFF
                                   │
                                   └─ 기존 en/ko/ja 경로 + 기존 캐시 그대로

                         feature flag ON
                                   │
                    ┌──────────────┴──────────────┐
                    │                             │
             안전한 원문 번역                국가별 YOBI 설명
             언어 기준 저장                  언어+국가+비교기준 캐시
                    │                             │
                    └──────────────┬──────────────┘
                                   │
                           API 응답 및 UI 표시
```

새 경로가 실패하면 메뉴 선택 결과를 버리지 않는다. 해당 메뉴는 안전한 기존 번역 또는 결정론적 영어 fallback과 기존 YOBI fallback 설명으로 반환하고, 실패·빈 값을 새 캐시에 저장하지 않는다.

## 6. 구현 작업 순서

### 6.1 1단계 — 번역·제목 저장 안전성부터 고정

가장 먼저 잘못된 빈 설명이 DB와 캐시에 들어가는 경로를 차단한다.

구현 내용:

1. `source_translation_is_safe()`를 generator 전용 함수에서 공용 순수 도메인 함수로 이동하고, 기존 import 사용처가 깨지지 않도록 generator에서 호환 re-export한다.
2. 공용 함수는 최소한 다음을 함께 검사한다.
   - 대상 문자열이 비어 있지 않음
   - 원문과 번역의 수량·숫자·단위 보존
   - Latin 브랜드명·상품 코드 보존
   - 대상 언어 문자 검증
   - 원문과 대상 언어가 같은 경우 안전한 원문 복사 허용
3. generator가 빈 문자열을 반환하거나 안전 검사를 통과하지 못하면 서비스는 이를 “새 번역 없음”으로 취급한다.
4. 기존 안전 번역이 있으면 그대로 유지한다.
5. 기존 안전 번역이 없으면 설명 번역 UPSERT만 생략한다.
6. 설명을 생략해도 유효한 제목·YOBI 설명·리뷰 요약은 독립적으로 처리한다.
7. SQLite와 Oracle의 `save_menu_runtime_localizations()` 인자를 제목과 설명 각각 `str | None`으로 받을 수 있게 동일하게 조정한다.
8. repository 저장 직전에 원문·대상 언어를 다시 확인하고 안전하지 않은 설명은 UPSERT하지 않는다.
9. 기존 `menu_source_description_localization` 행을 삭제하지 않는다.
10. 캐시에는 빈 `localized_source_description` 키를 쓰지 않는다. 캐시 읽기에서도 기존 빈 키는 무시하고 안전한 DB 값 또는 결정론적 fallback을 사용한다.
11. `Korean menu`, `韓国料理メニュー` 같은 generic sentinel 제목은 화면 최종 fallback으로는 허용하되 `menu_localization`에 `VALID`로 저장하지 않는다.

완료 조건:

- 이전 성공 번역이 새 빈 번역으로 덮이지 않는다.
- 수량·Latin token 검증 실패 번역이 DB와 캐시에 저장되지 않는다.
- 유효 번역은 계속 저장된다.
- 설명 저장을 건너뛰어도 유효 제목 저장은 유지된다.
- sentinel 제목이 영구 저장되지 않는다.
- SQLite와 Oracle의 결과가 같다.

### 6.2 2단계 — 국가 컨텍스트를 명시적으로 구성

`country_preference`를 국가 컨텍스트의 대용품으로 쓰지 않고, 서버 소유의 별도 구조를 만든다.

구현 내용:

1. `PresentationCountryContext` 도메인 모델을 추가한다.
2. 필드는 다음으로 고정한다.
   - `user_country_code: str | None`
   - `spice_reference_country_code: str | None`
   - `representative_dish_en: str | None`
   - `spice_baseline: int | None`
   - `menu_spice_level: int | None`
   - `spice_relationship: LESS | SIMILAR | MORE | None`
3. 사용자 국가는 `profile.country_code`에서만 가져오고 `ZZ`는 `None`으로 정규화한다.
4. 매운맛 비교 국가는 `criteria.spice_reference_country`에서 가져온다.
5. SQLite와 Oracle 후보 조회에서 기존 `synthetic_country_spice_example`의 영어 대표 음식과 기준값을 함께 읽는다.
6. 대표 음식 데이터가 없거나 메뉴 매운맛 값이 없으면 비교 컨텍스트를 부분적으로 추측하지 않고 비교 기능을 끈다.
7. 선택 LLM payload는 현재처럼 국가 필드를 제거한 상태를 유지한다.
8. 새 프레젠테이션 payload에만 `PresentationCountryContext`를 넣는다.
9. 기존 `country_preference` 객체는 API/UI 표시용으로 유지한다.
10. 새 프롬프트의 `source_hash`에는 실제로 사용한 국가 컨텍스트만 포함하고 합성 퍼센트·표본 수는 제외한다.

완료 조건:

- `en/US`와 `en/GB`는 서로 다른 국가 컨텍스트와 캐시 키를 가진다.
- 같은 언어·같은 원문 번역은 국가가 달라도 재사용할 수 있다.
- 두 국가의 추천 메뉴 ID와 순서는 변하지 않는다.
- `profile.country_code != spice_reference_country`인 경우 두 역할이 응답 provenance에서 구분된다.
- `ZZ` 사용자는 국가 비교 문장을 만들지 않는다.

### 6.3 3단계 — 16개 언어의 새 프레젠테이션 경로 추가

지원 대상 로케일은 정규화된 다음 16개다.

```text
en, ko, ja, zh-CN, zh-TW, es, fr, de, it, pt, th, vi, id, ar, hi, ru
```

구현 내용:

1. 설정에 `country_aware_presentation_enabled` 기능 플래그를 추가하고 기본값은 `false`로 둔다.
2. 새 프롬프트·스키마 버전 설정을 기존 버전과 별도로 둔다.
3. 플래그가 꺼져 있으면 현재 `ko/ja`, 나머지 `en` 축소 경로를 그대로 실행한다.
4. 플래그가 켜져 있으면 프레젠테이션 단계에서 정규화된 전체 로케일을 사용한다.
5. 추천 선택 단계의 `locale="English"`와 국가 배제 정책은 변경하지 않는다.
6. 기존 `MenuPresentationGenerator.generate()`와 기존 en/ko/ja 프롬프트 문자열은 유지한다.
7. 같은 generator에 별도 `generate_country_aware()` 진입점·프롬프트·검증을 추가한다.
8. 새 경로도 현재 설정의 동일한 primary/fallback 모델 체인을 사용하며 모델 순서나 readiness 정책은 바꾸지 않는다.
9. 새 프롬프트는 다음 필드를 대상 언어로 생성한다.
   - `localized_subtitle`
   - `localized_source_description`
   - `yobi_short_explanation`
   - `yobi_long_explanation`
   - `review_summary`
10. 메뉴 제목 정책은 이번 범위에서 확대하지 않는다.
    - 기존 ko/en/ja title 경로를 유지한다.
    - 나머지 언어는 현재 안전한 영어 제목 fallback을 사용한다.
11. `localized_source_description`에는 국가별 각색을 금지한다.
12. 국가별 음식 비교는 근거가 완전한 경우 `yobi_long_explanation`에만 최대 한 번 허용한다.
13. 해당 국가/언어 출력이 실패하면 영어 결정론적 fallback을 반환하고 실패한 대상 언어 캐시를 쓰지 않는다.
14. 실제 provider 호출 없이 fake provider로 16개 로케일 라우팅·문자 검증·fallback을 테스트한다.

### 6.4 4단계 — 기존 캐시와 분리된 새 저장 구조 추가

기존 `menu_presentation_cache`와 `menu_source_description_localization`의 3개 언어 CHECK를 변경하지 않는다. 기존 영어 데모와 기존 행을 보존하기 위해 migration 020에서 다음 두 테이블을 추가한다.

#### `runtime_menu_source_description_localization`

용도: 국가와 무관한 안전한 식당 원문 번역 저장.

주요 키·필드:

- `release_id`
- `menu_id`
- `language_code` — 16개 정규 로케일
- `prompt_version`
- `description_text`
- `model_id`
- `source_hash`
- `validation_status`
- `generated_at`

정책:

- 언어 단위로 저장하므로 `en/US` 성공 번역을 `en/GB`에서도 안전하게 재사용할 수 있다.
- 새 번역이 무효이면 기존 안전 행을 유지한다.
- 안전한 기존 행이 없으면 UPSERT를 생략한다.
- 빈 문자열을 `VALID`로 저장하지 않는다.

#### `country_aware_menu_presentation_cache`

용도: 언어·사용자 국가·매운맛 비교 국가별 YOBI 설명 저장.

주요 키·필드:

- `cache_key`
- `release_id`
- `menu_id`
- `language_code`
- `user_country_code`
- `spice_reference_country_code`
- `localized_subtitle`
- `short_explanation`
- `long_explanation`
- `review_summary`
- evidence/provenance JSON
- `model_id`
- `prompt_version`
- `content_schema_version`
- `source_hash`
- `personalization_applied`
- `created_at`, `updated_at`

캐시 키 seed:

```text
release_id
+ menu_id
+ target_locale
+ user_country_code 또는 ZZ
+ spice_reference_country_code 또는 ZZ
+ country-aware prompt version
+ country-aware schema version
+ source/evidence/context hash
```

정책:

- `country_preference.preference_percent`·`sample_size`는 새 설명 캐시 hash에서 제외한다.
- `localized_source_description`은 이 캐시에 중복 저장하지 않고 언어 단위 번역 테이블에서 조립한다.
- 설명 번역이 무효여도 유효한 YOBI 설명 캐시는 저장할 수 있다.
- 새 캐시가 실패해도 기존 캐시 행은 삭제하거나 변경하지 않는다.
- 기존 generation lease 테이블은 `cache_key` 기반이므로 새 키에도 재사용한다.
- 기능 플래그를 끄면 즉시 기존 캐시 경로로 복귀한다.

### 6.5 5단계 — `precomputed_only` 옵션 경로 정리

구현 내용:

1. `OptionLocalizationService.get_options()`에 `precomputed_only: bool = False`를 추가한다.
2. API는 일반·precomputed 요청을 모두 서비스로 보낸다.
3. precomputed 경로의 우선순위를 다음으로 고정한다.
   1. 기존 release `option_group_localization`·`option_item_localization`
   2. 현재 release/language/prompt version의 완전한 runtime cache
   3. catalog `name_ko`·`name_en` fallback
4. release 번역이 있는 필드는 runtime 값으로 덮지 않는다.
5. 화면에 투영된 모든 group/item ID에 대한 runtime cache가 완전할 때만 runtime 값을 사용한다.
6. runtime cache가 하나라도 빠지면 전체 runtime 묶음을 무시하고 release+catalog 결과를 반환한다.
7. `precomputed_only=true`에서는 generator/provider에 도달할 수 없게 조기 반환한다.
8. 일반 선택 메뉴의 lazy 생성·저장은 현재 동작을 유지한다.
9. readiness의 기존 `localized_option_groups/items`는 하위 호환을 위해 유지하되 다음 명시적 수치를 추가한다.
   - `release_localized_option_groups/items`
   - `runtime_localized_option_groups/items`

완료 조건:

- EN/KO catalog fallback이 정확하다.
- 완전한 JA runtime cache가 적용된다.
- 불완전 runtime cache를 일부만 섞어 쓰지 않는다.
- `precomputed_only=true` provider 호출 수가 0이다.
- 일반 lazy 옵션 번역 경로는 회귀하지 않는다.
- SQLite와 Oracle readiness 값의 의미와 이름이 같다.

### 6.6 6단계 — 로케일별 Preference Catalog ETag

구현 내용:

1. repository가 반환한 `payload["locale"]`를 `normalize_preference_locale()`로 정규화한다.
2. 정규화된 locale을 ETag seed에 포함한다.
3. `Cache-Control: private, max-age=300`을 유지한다.
4. 동일 로케일 `If-None-Match`의 304 동작을 유지한다.
5. API가 query `locale`을 사용하므로 `Vary: Accept-Language`를 추가하지 않는다.

완료 조건:

- EN과 JA ETag가 다르다.
- 동일 로케일 재검증은 304다.
- 다른 로케일 ETag로 잘못된 304가 발생하지 않는다.

### 6.7 7단계 — 레스토랑 메모 `source_language` 정규화

구현 내용:

1. 프론트는 프로필 표시명을 그대로 보내지 않고 `LANGUAGE_META[asSupportedLanguage(...)].code`를 보낸다.
2. 서버는 언어 표시명과 코드를 모두 `normalize_preference_locale()`로 정규화해 하위 호환성을 유지한다.
3. canonical code를 다음 모든 위치에 사용한다.
   - request hash
   - cache 조회
   - LLM payload
   - 출력 검증
   - DB 저장
4. 한국어 `ko`는 provider 앞에서 결정론적으로 처리한다.
   - `korean_text = 정리한 원문`
   - `back_translation = 정리한 원문`
   - `model_id = DETERMINISTIC_KOREAN_PASSTHROUGH`
   - provider 호출 0회
5. 영어의 기존 모델 체인과 안전한 deterministic fallback은 유지한다.

완료 조건:

- `English`와 `en`이 같은 hash·캐시 계약을 사용한다.
- `한국어`와 `ko`가 provider 없이 성공한다.
- `日本語`와 `ja`가 정상 모델 경로로 처리된다.
- 기존 표시명 클라이언트가 계속 동작한다.
- 프론트 요청 body가 정규 언어 코드를 보낸다.

### 6.8 8단계 — `ZZ` UI 방어

이 단계는 국가 개인화를 제거하지 않는다.

구현 내용:

- `country_preference`가 없으면 블록을 표시하지 않는다.
- `country_preference.country_code`가 없거나 대문자 정규화 후 `ZZ`이면 블록을 표시하지 않는다.
- `US`, `GB`, `JP` 등 유효한 국가 블록은 현재처럼 유지한다.
- backend의 `profile.country_code`, 새 프레젠테이션 국가 컨텍스트, 국가별 캐시 키를 제거하지 않는다.

완료 조건:

- `ZZ · 54%`, “120명 기준” 블록이 보이지 않는다.
- 유효한 US/GB 통계 블록은 계속 보인다.
- 같은 영어의 US/GB 새 프레젠테이션 캐시는 분리된다.

## 7. 수정할 파일 — 확정 목록

### 7.1 이번 계획 작성에서 추가하는 파일

| 상태 | 파일 | 목적 |
|---|---|---|
| 신규 | `docs/LLM_TRANSLATION_HARDENING_FINAL_PLAN_20260823.md` | 본 최종 작업 계획 |

### 7.2 실제 구현에서 신규 추가할 파일

| 상태 | 파일 | 목적 |
|---|---|---|
| 신규 | `backend/app/domain/presentation_localization.py` | 번역 안전성, sentinel 판정, 16개 로케일, `PresentationCountryContext` 공용 규칙 |
| 신규 | `database/migrations/020_country_aware_menu_presentation.sql` | 언어 단위 원문 번역 테이블과 국가별 설명 캐시 테이블 추가 |
| 신규 | `backend/tests/test_presentation_localization.py` | 공용 안전성·sentinel·국가 컨텍스트 단위 테스트 |
| 신규 | `backend/tests/test_presentation_repository_parity.py` | 동일 저장 시나리오에 대한 SQLite/Oracle field별 저장·생략 parity 검증 |

### 7.3 실제 구현에서 수정할 backend 파일

| 파일 | 수정 내용 |
|---|---|
| `backend/app/core/config.py` | 국가별 16개 언어 프레젠테이션 기능 플래그와 별도 prompt/schema version 추가 |
| `backend/app/domain/models.py` | 새 원문 번역·국가별 프레젠테이션 cache entry 모델 추가, 독립 저장이 가능하도록 필드 계약 정의 |
| `backend/app/domain/structured_recommendation.py` | `EvidencePoolItem`에 매운맛 비교 국가·대표 음식 컨텍스트 필드 추가 |
| `backend/app/genai/presentation_generator.py` | 공용 안전 함수 사용, 기존 generate 보존, 별도 `generate_country_aware()`·16개 언어 검증 추가 |
| `backend/app/services/menu_presentation.py` | 기능 플래그 라우팅, 안전한 field별 fallback, 새 번역/설명 캐시 조립, 빈 캐시 방지, sentinel 저장 생략 |
| `backend/app/services/structured_recommendation.py` | 선택 언어는 English로 유지하고 프레젠테이션에 전체 locale·사용자 국가를 전달 |
| `backend/app/services/option_localization.py` | `precomputed_only` 서비스 경로, release 우선·runtime 완전성 검사·provider 0회 보장 |
| `backend/app/services/restaurant_note_translation.py` | 표시명/코드 canonicalization, canonical hash/payload/storage, 한국어 pass-through |
| `backend/app/db/repository.py` | SQLite/Oracle 공통 메서드 시그니처: 선택적 제목/설명 저장, 새 캐시, release 옵션 번역 조회 |
| `backend/app/db/sqlite_repository.py` | 안전한 field별 저장, 국가 컨텍스트 조회, 새 두 테이블 read/write, 옵션·readiness 동작 구현 |
| `backend/app/db/oracle_repository.py` | SQLite와 동일한 저장·조회·옵션·readiness 계약 구현 |
| `backend/app/db/schema_sqlite.py` | migration 020과 동일한 SQLite 신규 테이블·CHECK·index 정의 |
| `backend/app/main.py` | ETag locale seed, options API의 서비스 단일 경로 적용 |

### 7.4 실제 구현에서 수정할 frontend 파일

| 파일 | 수정 내용 |
|---|---|
| `frontend/src/components/OrderFlowPanel.tsx` | `LANGUAGE_META`의 canonical language code로 레스토랑 메모 요청 |
| `frontend/src/components/RecommendationResults.tsx` | country code가 없거나 `ZZ`인 preference 블록 숨김 |

다음 frontend 파일은 기존 기능을 재사용하므로 수정하지 않는다.

- `frontend/src/lib/locale.ts`: 기존 `LANGUAGE_META`, 국가 매핑을 그대로 사용한다.
- `frontend/src/lib/api.ts`: 현재 request body 구조가 이미 `source_language` 인자를 전달하므로 caller 값만 canonical code로 바꾼다.
- `frontend/src/types.ts`: 정상 응답 계약은 유지한다.

### 7.5 실제 구현에서 수정할 migration/deploy 검증 파일

| 파일 | 수정 내용 |
|---|---|
| `deploy/deploy.sh` | 정적 expected migration 목록·개수·최신 버전을 `001-020`, `20`, `020`으로 갱신. 스크립트는 실행하지 않음 |

`scripts/migrate.py`와 `deploy/secure_bootstrap.py`는 migration 목록을 동적으로 읽으므로 동작 변경이 필요 없으면 수정하지 않는다.

### 7.6 실제 구현에서 수정할 backend 테스트 파일

| 파일 | 검증 범위 |
|---|---|
| `backend/tests/test_menu_presentation_service.py` | 기존 번역 유지, 빈 캐시 방지, flag OFF 회귀, 16개 locale, US/GB 캐시 분리, 국가 비교 payload, fallback |
| `backend/tests/test_structured_recommendation_service.py` | 선택 결과 불변, 전체 locale 전달, 국가/매운맛 기준 역할 분리 |
| `backend/tests/test_option_localization_service.py` | EN/KO fallback, 완전/불완전 JA runtime, provider 0회, 일반 lazy 회귀 |
| `backend/tests/test_restaurant_note_translation.py` | 표시명/코드 동일 hash, ko pass-through, ja 정상 경로, 기존 영어 fallback |
| `backend/tests/test_structured_recommendation_persistence.py` | ETag locale 분리, precomputed API 계약, SQLite 저장·캐시 통합 |
| `backend/tests/test_oracle_json_boundary.py` | Oracle JSON/CLOB 경계와 새 캐시 evidence_map canonicalization |
| `backend/tests/test_seed_upgrade_cleanup.py` | repository status의 release/runtime 옵션 readiness 수치 이름과 의미 |
| `backend/tests/test_migration_parser.py` | migration 020 파싱·순서·신규 테이블 검증 |
| `backend/tests/test_deploy_release_safety.py` | deploy 정적 migration gate가 001-020과 일치하는지 검증 |

### 7.7 실제 구현에서 수정할 frontend 테스트 파일

| 파일 | 검증 범위 |
|---|---|
| `frontend/tests/OrderFlowCheckout.test.tsx` | 레스토랑 메모 요청 body가 `en`, `ko`, `ja` 같은 코드를 전송 |
| `frontend/tests/RecommendationResultsChat.test.tsx` | `ZZ` 숨김과 US/GB 유효 블록 유지 |
| `frontend/tests/apiConversation.test.ts` | 동일 locale 304와 locale별 ETag 프론트 캐시 계약 회귀 확인 |

기존 E2E 파일은 동작이 깨지지 않았는지 실행하되, 테스트 실패로 실제 계약 수정이 필요하다고 확인되지 않으면 변경하지 않는다.

## 8. 항목별 필수 테스트 시나리오

### 8.1 번역 저장 안전성

- 안전한 이전 번역 + 새 빈 응답 → 이전 번역 유지
- 수량 불일치 응답 → 설명 DB UPSERT 없음
- Latin 브랜드 token 누락 → 설명 DB UPSERT 없음
- 설명 무효 + 제목 유효 → 제목만 저장
- 제목 sentinel + 설명 유효 → 제목 미저장, 설명 저장
- 빈 cache evidence 값이 존재하는 기존 행 → 읽을 때 무시하고 안전 fallback
- SQLite와 Oracle에 동일 입력 → 동일한 저장/생략 판단

### 8.2 국가·언어 프레젠테이션

- flag OFF `en/ko/ja` → 현재 provider payload·호출 횟수·기존 cache 경로 유지
- flag ON `en/US`와 `en/GB` → 메뉴 ID/순서 동일, cache key와 country context 다름
- 같은 한국어 원문 + `en/US`, `en/GB` → 안전한 원문 영어 번역 재사용
- `US` 매운맛 비교 → fake output이 `Buffalo wings` 컨텍스트 사용 가능
- `GB` 매운맛 비교 → fake output이 `Chicken tikka masala` 컨텍스트 사용 가능
- 사용자 국가 `US`, 매운맛 기준 `JP` → provenance에서 역할 구분, “사용자 국가 JP”라고 쓰지 않음
- `ZZ` → 국가 컨텍스트 미전달, personalization false
- 13개 확장 locale 각각 → 대상 locale payload·cache key·응답 필드 확인
- 확장 locale provider 실패 → 영어 deterministic fallback, 실패 cache 미저장
- 합성 퍼센트·표본 수 → 새 LLM narrative payload에 없음

### 8.3 옵션 번역

- release 번역이 runtime보다 우선
- EN/KO catalog fallback
- 완전한 JA runtime cache 적용
- 불완전 runtime cache 전체 무시
- `precomputed_only=true` provider 0회
- 일반 선택 메뉴 lazy 생성·저장 유지

### 8.4 ETag

- EN/JA payload ETag 다름
- EN ETag로 EN 재검증 304
- EN ETag로 JA 요청 시 200
- `Cache-Control` 유지
- `Vary: Accept-Language` 없음

### 8.5 레스토랑 메모

- `English`와 `en` 동일 request hash
- `한국어`와 `ko` provider 0회, 동일 원문 반환
- `日本語`와 `ja` 동일 canonical 경로
- 표시명을 보내는 구형 클라이언트 계속 성공
- 프론트 요청 body는 코드 전송

### 8.6 UI

- `country_preference=null` → 블록 없음
- `country_code="ZZ"` → 블록 없음
- `country_code="US"` → 기존 퍼센트·표본 블록 표시
- `country_code="GB"` → 영국 국가명과 해당 값 표시

## 9. 검증 실행 순서

### 9.1 집중 backend 테스트

```bash
backend/.venv/bin/pytest -q \
  backend/tests/test_presentation_localization.py \
  backend/tests/test_presentation_repository_parity.py \
  backend/tests/test_menu_presentation_service.py \
  backend/tests/test_structured_recommendation_service.py \
  backend/tests/test_option_localization_service.py \
  backend/tests/test_restaurant_note_translation.py \
  backend/tests/test_structured_recommendation_persistence.py \
  backend/tests/test_oracle_json_boundary.py \
  backend/tests/test_seed_upgrade_cleanup.py \
  backend/tests/test_migration_parser.py \
  backend/tests/test_deploy_release_safety.py
```

### 9.2 집중 frontend 테스트

`frontend` 디렉터리에서 실행한다.

```bash
pnpm test -- \
  tests/OrderFlowCheckout.test.tsx \
  tests/RecommendationResultsChat.test.tsx \
  tests/apiConversation.test.ts
```

### 9.3 전체 정적·회귀 검증

```bash
backend/.venv/bin/pytest -q
backend/.venv/bin/ruff check backend/app backend/tests scripts deploy
backend/.venv/bin/mypy backend/app
```

`frontend` 디렉터리에서:

```bash
pnpm test
pnpm lint
pnpm build
```

로컬 런타임을 안전하게 띄울 수 있으면 기존 Playwright 데모 E2E를 실행한다. 외부 공개 환경이나 운영 OCI에는 연결하지 않는다.

마지막으로:

```bash
git diff --check
git status --short --branch
```

각 명령의 정확한 통과/실패/skip 수와 경고를 최종 보고에 기록한다. 실패한 검증은 추측으로 통과 처리하지 않는다.

## 10. 체크포인트 커밋 계획

모든 필수 검증이 통과한 뒤 관련 파일만 명시적으로 스테이징한다.

예정 커밋 메시지:

```text
feat: harden country-aware menu localization
```

커밋 전 확인:

- 기존 미추적 PNG 2개가 staging에 없음
- 기존 발표 스크립트 Markdown이 staging에 없음
- 운영 환경 파일·비밀·실제 데이터 파일이 staging에 없음
- migration 020은 코드로만 존재하며 OCI에 적용되지 않음
- `git diff --cached --check` 통과

## 11. 명시적 제외 범위

다음은 구현하지 않는다.

- F3 일본어/스페인어 레거시 챗 설명 템플릿
- F4 presentation primary 미지원 시 모델 체인 변경 또는 dedicated readiness 신설
- F6 `time.sleep()`·스레드풀 대기 구조·배포 대기시간 조정
- 추천 선택 LLM의 언어·국가 독립 정책 변경
- 메뉴 제목의 16개 언어 신규 번역 정책
- 옵션 라벨의 16개 언어 전체 일괄 생성
- 국가별 실제 이용자 선호 데이터라고 주장하는 문구 추가
- 운영 DB 기존 번역·캐시 행 삭제 또는 재생성
- 운영 데이터 prewarm
- OCI migration 실행
- OCI 배포·환경 변수 변경·기능 플래그 활성화
- 공개 환경 QA
- unrelated repository 통합 리팩터링

## 12. 운영 적용 전 별도 승인 지점

구현·로컬 검증·체크포인트 커밋이 완료되어도 다음은 자동으로 수행하지 않는다.

1. migration 020을 OCI DB에 적용할지 승인
2. 새 release artifact를 배포할지 승인
3. `country_aware_presentation_enabled=true`를 운영 환경에 설정할지 승인
4. 공개 데모에서 국가별 설명을 활성화할지 승인
5. 필요한 경우 별도 prewarm을 수행할지 승인

권장 운영 순서:

```text
코드 승인
→ migration 020 적용 승인
→ 배포 승인
→ 기능 플래그 OFF 상태 smoke
→ 기능 플래그 ON 승인
→ en/US, en/GB, ko/KR, ja/JP, 확장 언어 표본 QA
→ 공개 데모 활성화
```

문제가 생기면 기능 플래그를 끄고 기존 en/ko/ja 캐시 경로로 복귀한다. 기존 캐시와 번역 행을 삭제하지 않았으므로 데이터 복구 작업 없이 rollback할 수 있어야 한다.

## 13. 최종 완료 보고 형식

최종 보고에는 반드시 다음을 포함한다.

1. 항목별 실제 변경 파일과 동작
2. 계획과 달라진 부분 및 그 근거
3. `profile.country_code`, `spice_reference_country`, `country_preference`의 최종 역할
4. 영어/미국·영어/영국의 선택 결과 불변과 캐시 분리 검증 결과
5. 16개 언어의 성공·fallback 결과
6. 빈/위험 번역과 sentinel 제목의 저장 방어 결과
7. SQLite/Oracle parity
8. 실행한 모든 테스트·lint·타입 검사·build의 정확한 결과
9. 변경하지 않은 범위
10. 기존 미추적 파일이 보존되었다는 확인
11. 운영 DB 변경·prewarm·배포·공개 환경 변경을 수행하지 않았다는 확인
12. 운영 적용 전에 필요한 승인 목록

## 14. 완료 정의

다음 조건이 모두 확인되어야 작업을 완료로 처리한다.

- 빈/위험 번역이 DB 또는 프레젠테이션 캐시에 새로 고정되지 않는다.
- 안전한 기존 번역이 무효한 새 결과로 덮이지 않는다.
- 유효한 다른 필드는 독립적으로 저장된다.
- 기존 en/ko/ja 경로는 플래그 OFF에서 회귀하지 않는다.
- 플래그 ON에서 16개 로케일이 새 프레젠테이션 경로를 사용한다.
- `en/US`와 `en/GB`의 선택 결과는 같고 국가 컨텍스트·캐시는 분리된다.
- 식당 원문 번역과 국가별 YOBI 설명의 책임이 분리된다.
- `country_preference` UI는 유효 국가에서 유지되고 `ZZ`에서는 숨겨진다.
- `precomputed_only=true`에서 provider 호출이 0이다.
- Preference Catalog ETag가 locale별로 분리된다.
- 레스토랑 메모 언어 코드가 canonical하게 처리되고 한국어는 provider를 우회한다.
- SQLite와 Oracle 동작이 일치한다.
- 집중 및 전체 검증 결과가 실제 명령 출력으로 확인된다.
- 관련 변경만 체크포인트 커밋된다.
- OCI DB·prewarm·배포는 수행되지 않는다.
