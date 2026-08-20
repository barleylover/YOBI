# YOBI 추천 요청·Wiki·Semantic 경로 개선 보고서

작성일: 2026-08-19  
작업 브랜치: `codex/recommendation-v2-hybrid`  
상태: 운영 OCI 배포 완료. 릴리스 `20260819T041159Z-147947c74fd4`가 활성 `PROVISIONAL`이며, 사전 Grok 1회 통과 후 사후 5회 게이트는 4/5 품질 통과·지연 목표 실패로 최종 `FAIL`이다.

## 1. 이번 개선의 결론

1. 화면의 추천 요청은 긴 POST 한 번에 의존하지 않고, 요청을 먼저 영속화한 뒤 같은 request ID를 GET으로 조회하고 재개하는 구조로 변경했다.
2. 검토된 공개 Wiki passage가 있는 메뉴만 각 검색 채널의 후보가 될 수 있도록 Wiki eligibility를 후보 합집합 이전으로 옮겼다.
3. 운영 semantic 경로는 더 이상 임시 deterministic hash vector를 Cohere vector처럼 취급하지 않는다. 런타임 provider/model/version/dimension과 저장 vector가 일치할 때만 semantic 점수를 사용한다.
4. 최종 설명의 Wiki passage는 단순 저장 순서가 아니라 사용자가 선택한 카테고리·값과 해당 메뉴의 evidence ID를 기준으로 다시 정렬한다.
5. Wiki 문서와 preference support를 정적 감사하는 품질 게이트를 추가하고, 불확실·부정 문장에서 긍정 특성을 만드는 오류를 막았다.

## 2. 요청 수명주기

```text
화면 POST
  -> DB에 request를 CREATED로 저장
  -> HTTP 202 + request ID 즉시 반환
  -> 백그라운드 처리 시작
화면 GET polling
  -> CREATED면 같은 request를 재개
  -> DISPATCHED면 새 provider 호출 없이 기존 결과를 기다림
  -> COMPLETED/FAILED면 최종 결과 표시
```

- 한 프로세스 안에서는 claim registry로 중복 실행을 막는다.
- 여러 worker가 동시에 같은 요청을 보더라도 DB dispatch marker에서 두 번째 worker가 provider를 호출하지 않도록 막는다.
- 서버가 POST 직후 재시작되어도 DB에 남은 `CREATED` 요청은 다음 GET에서 같은 입력으로 복구한다.
- provider 호출을 이미 시작한 `DISPATCHED` 요청은 임의 재호출하지 않는다. 이 경계는 중복 과금보다 결과 확인 실패를 택하는 fail-closed 정책이다.
- 프론트는 transient GET 오류를 즉시 최종 실패로 바꾸지 않고 최대 150초 동안 같은 request ID를 조회한다.
- POST timeout은 30초다. 실제 추천 완료 timeout이 아니라 “요청 접수” timeout이다.

## 3. Wiki eligibility의 적용 위치

이전에는 feature/concept/vector 검색으로 후보를 만든 뒤 Wiki 유무를 확인할 수 있어, Wiki가 없는 메뉴가 제한된 후보 슬롯과 실행 시간을 소비했다. 이제 다음 공통 집합을 먼저 만든다.

```text
검토된 public Wiki chunk
  -> concept closure의 허용된 descendant
  -> menu_concept_membership
  -> eligible menu ID 집합
```

그 뒤 menu feature, concept support, semantic vector, preview, final query 모두 이 집합 안에서만 후보를 만든다. 이 집합은 `menu_wiki_eligibility`에 release별로 한 번 컴파일한다. SQLite schema와 Oracle additive migration `014_wiki_eligibility_indexes.sql`에 table/index/backfill을 추가했다.

15,085-menu 로컬 미러의 두 knowledge release에서 각각 정확히 4,558개 메뉴가 컴파일됐다. 기존처럼 매 요청에 document/chunk/closure JSON을 다시 조인한 방식은 일부 objective preview에서 1분 이상 걸릴 수 있었지만, compiled lookup으로 바꾼 뒤 개별 확인은 single 207ms, price 51ms, multi 118ms, hard NO_MATCH 120ms였다. 20회 반복에서 price preview 중앙값은 16.2ms, 전체 preview 중앙값은 53.0ms였다.

## 4. Semantic vector 계약

- 운영 provider: OCI Generative AI native `embed_text`
- 모델: `cohere.embed-v4.0`
- 차원: 1536
- 문서 입력: `SEARCH_DOCUMENT`
- 질의 입력: `SEARCH_QUERY`
- 자동 retry: 없음
- 한 dispatch 최대 입력: 96

운영 menu vector는 기존 `menu` 행을 덮어쓰지 않고 `menu_semantic_embedding`에 `catalog_release_id + menu_id + model + version`으로 저장한다. semantic text hash와 전체 embedding manifest도 함께 고정한다. 저장된 recommendation family, 불변 vector 집합, 런타임 provider/model/version/dimension이 모두 일치해야 vector channel을 활성화한다. 하나라도 다르면 semantic channel은 `DISABLED_MODEL_MISMATCH`로 기록되고, 해당 요청은 근거 기반 feature/concept 채널만 사용한다.

`scripts/backfill_menu_semantic_embeddings.py`는 다음 안전 계약을 지킨다.

- 전체 semantic text snapshot과 manifest를 먼저 확정한 뒤 vector를 생성한다.
- 96개씩 OCI native `embed_text`를 호출하며 SDK retry를 사용하지 않는다.
- DML은 별도 단일 transaction에서 신규 행만 INSERT한다.
- `menu`, catalog batch, knowledge/recommendation pointer를 수정하지 않는다.
- 기존 집합이 완전하고 manifest가 같으면 provider 호출 없이 종료한다.
- 일부 행만 있거나 manifest가 다르면 덮어쓰지 않고 실패한다.

배포 환경 생성·복원 스크립트도 `EMBEDDING_PROVIDER=oci`와 instance-principal 인증을 고정한다. 이전 protected env에 `OCI_COMPARTMENT_ID`가 없으면 잘못된 provider로 자동 전환하지 않고 배포 전에 중단한다.

운영 적용에서는 승인된 staged backfill을 실행해 15,085개 메뉴 vector를 96개 이하 batch, 158회 provider dispatch, 자동 retry 0으로 생성했다. 불변 집합 manifest는 `6027fe3f8f01733be8a7ba60b9ed4af16b2e3f8714c83f4256a2eae76106f9e4`이며, 즉시 실행한 `--verify-only`는 15,085/15,085와 semantic text hash mismatch 0, active pointer 불변을 확인했다. 이후 동일 집합은 `ALREADY_PRESENT`로 검증되어 재호출되지 않았다.

## 5. 사용자 조건과 가장 관련 있는 Wiki passage 선택

최종 메뉴마다 가능한 passage를 모두 가져온 뒤 다음 순서로 점수를 계산한다.

1. 메뉴 선택의 실제 evidence ID와 같은 chunk
2. 사용자가 고른 category/value의 정규화 토큰 및 명시적 alias 일치
3. 관련 facet 일치
4. concept 상속 깊이가 얕은 직접 근거
5. 안정적인 source 순서

Unicode NFKC, casefold, 단어 경계를 사용하므로 `heat`가 `wheat`에 잘못 맞는 방식의 raw substring 비교를 하지 않는다. 동일 passage는 중복 제거한다.

## 6. Wiki 품질 게이트

새 감사기는 문서 provenance, review 상태, 라이선스, synthetic/public source 경계, passage 공개 여부, evidence 소유권, 중복 문단, 안전성 과장, 불확실 문장의 긍정 support 변환을 검사한다.

로컬 최종 감사 결과:

- 문서 198개, compiled chunk 1,551개, preference support 1,291개
- critical issue 0
- 누락되거나 internal-only인 evidence 0
- boilerplate evidence 0
- informative paragraph exact duplicate group 0
- 선택된 evidence가 passage 1순위인 비율 100%
- lexical evidence가 상위 2 passage 안에 있는 비율 90.70%
- 모든 문서의 metadata source-boundary 표기 100%
- 본문 disclaimer가 없는 문서 114개는 warning으로 유지

본문 disclaimer 114개를 일괄 삽입하면 검색 passage 자체를 불필요하게 부풀리므로 이번에는 critical gate로 만들지 않았다. 대신 모든 문서 metadata의 synthetic/reviewed 경계를 강제한다.

또한 `may`, `might`, `can`, `sometimes`, `optional`, `vary`, `not`, `without` 등이 포함된 clause는 일반 Wiki에서 긍정 메뉴 특성으로 컴파일하지 않는다. 메뉴 직접 근거가 있는 경우만 강한 support가 된다.

## 7. 자동 평가 결과

15,085-menu 미러와 200-query `source-evidence-silver-v2` 라벨로 실행했다. 이 라벨은 사람 정답지가 아니므로 출시 승인 지표가 아니라 회귀 탐지용이다.

| 구간 | Precision@3 | NDCG@3 | Recall@20 | 3-result coverage | hard 위반 | median |
|---|---:|---:|---:|---:|---:|---:|
| 신규 holdout 60 | 1.0000 | 1.0000 | 0.9359 | 1.0000 | 0 | 843.5ms |
| 기존 holdout 60 | 0.2364 | 0.1582 | 0.0745 | 1.0000 | 0 | 2,513.5ms |
| 신규 tune 140 | 0.9947 | 1.0000 | 0.9461 | 0.9840 | 0 | 829.8ms |

한국어/영어 짝 query의 top-20 집합 일치율은 100%였다. 신규 holdout의 최대 repository latency는 1,036.5ms였다. 평가 artifact manifest는 `4d1f0e1ae902be80685c887e8019c957d4f16a331f8181ede3dbca5b452e30c1`, `metrics_silver.json` SHA-256은 `d4ce38bb54ff38e8ddc9b9874007d7620736e1fa4c6225a0823b1c69a2f67d1a`이다.

별도 15,085-menu repository 성능 smoke는 warm retrieval 60건 중앙값 838.2ms·최대 1,174.0ms, NO_MATCH 20건 중앙값 33.0ms·최대 45.6ms였다. process-cold 2건은 중앙값 1,203.1ms·최대 1,232.1ms였다. warm 20회/시나리오와 cold 2회는 정식 P95 최소 표본보다 작으므로 percentile 통과 주장은 하지 않고 `INCONCLUSIVE`로 기록했다.

## 8. 운영 적용 게이트 결과

1. Oracle additive migration 014 적용 및 migration ledger 검증: 통과
2. OCI Cohere Embed 4 불변 vector backfill·verify-only: 통과
3. staged knowledge/recommendation family 생성과 count/manifest 검증: 통과
4. staged query plan과 hard filter 검증: 통과
5. 사전 Grok probe 1회, retry 0: 통과
6. 새 app/family 활성화와 local/public health/readiness: 통과
7. 사후 Grok 5회, 60초 간격, retry 0: 4건 Grok 선택 통과, 1건 OCI rate limit fallback
8. 사후 지연 목표 median 8초·max 10초: 실패

기존 데이터는 삭제하지 않았고, 이전 app release는 수동 rollback 대상으로 보존했다. 사후 게이트 실패 정책에 따라 새 릴리스는 자동 롤백하지 않고 활성 `PROVISIONAL`로 유지했다.

추가로 로컬 초기화의 preference 노출 계산도 raw Wiki/menu 문장 전체를 50개 옵션 alias와 반복 비교하던 방식에서 이미 컴파일된 `concept_preference_support + menu_concept_membership + menu_wiki_eligibility` 집계로 변경했다. 동일한 600-menu fixture에서 초기화 실측은 약 6.2초에서 약 2.1초로 감소했다.

## 9. 최종 로컬 검증

- backend Pytest: 611 passed, 2 warnings, 625.22초
- Ruff: 통과
- MyPy: 61개 source file 통과
- frontend Vitest: 48 passed
- frontend ESLint: 통과
- frontend TypeScript/Vite production build: 통과
- Git diff whitespace 검사: 통과
- 운영 OCI write·embedding backfill·Grok 1+5 호출·배포: 수행 완료

## 10. 운영 배포와 실제 1+5 결과

- application release: `20260819T041159Z-147947c74fd4`
- deployed source commit: `f2a529cd8ef28ea72569a6fc26f84366abb0a9d5`
- recommendation family: `external-recommendation-9db4e004e8ec633257c9ee33-d1ca4461e2-d557ecf273-a76a689867`
- knowledge release: `external-knowledge-9db4e004e8ec633257c9ee33`
- feature manifest: `d1ca4461e26474ed16006f0a6a4a5ae13db5de8cacf8456991df8ac4fd48e6cc`
- postdeploy artifact SHA-256: `e5dcf0595dc8314c1cb25d2628d3095f1c13e302e344f779c9b68dbb12e9364b`

사전 staged-family probe는 `SPICY + FRIED + CHICKEN`으로 provider 1회, retry 0 계약을 통과한 뒤에만 active pointer가 변경됐다. 사후 게이트는 고정 5건을 정확히 한 번씩, 60초 간격으로 실행했다.

| case | 결과 | 지연 | 선택 상태 | 원인 |
|---|---|---:|---|---|
| Korean `SPICY + NOODLES` | 실패 | 4.55초 | deterministic fallback | OCI `RATE_LIMIT` |
| English `CRISPY + CHICKEN + FRIED` | 통과 | 20.26초 | `GROK_SELECTED` | 계약·근거·다양성 통과 |
| Korean `CLEAN_MILD + SOUP + HOT` | 통과 | 21.83초 | `GROK_SELECTED` | 계약·근거·다양성 통과 |
| English `ITALIAN + NOODLES + 10k–19k` | 통과 | 27.06초 | `GROK_SELECTED` | 계약·근거·다양성 통과 |
| Korean `SWEET + FROZEN + DESSERT` | 통과 | 21.28초 | `GROK_SELECTED` | 계약·근거·다양성 통과 |

5건 모두 dispatch count 1, 총 provider call 5, retry 0, shortlist 15, 최종 결과 3개, 매장 3개였다. 성공 4건은 선택 카테고리 근거를 모두 충족했고 grounding rejection은 없었다. 측정 가능한 성공 4건의 사용량은 input 28,933, output 7,068, total 36,001 token이었다. 전체 latency median은 21.28초, max는 27.06초로 목표를 통과하지 못했다.

공개 `/`, `/healthz`, `/readyz`, `/demo/qr`는 HTTP 200, 인증 없는 `/api/v1/demo/status`는 403이었다. readiness는 Grok 4.3, feature 61,341개, Wiki eligible menu 4,558개, semantic embedding 15,085개와 모든 데이터 무결성 check 통과를 보고했다. 임시 LB 경로 제거 후 TCP 22=0, TCP 80 불변, LB 수 복원도 확인했다.

자동 rollback은 수행하지 않았다. 수동 rollback 명령은 `sudo -n /opt/yobi/current/deploy/rollback.sh`이다. 추가 Grok 호출 없이 rate-limit 용량과 20초대 모델 지연을 다음 개선 대상으로 남긴다.
