# YOBI recommendation v2 — representative 30 review sheet

## Review boundary

- Dataset: `yobi-recommendation-golden-v2-2026-08-18-r4`
- Labels: `SILVER_NOT_RELEASE_APPROVAL`
- Selection: deterministic 30-query stratified sample from the 200-query suite
- Purpose: human review before any Oracle/OCI write
- `v2 label` is the automated relevance label for each displayed top-3 item. `3` means all selected categories have direct menu evidence; `2` means a mixture of direct and explicitly discounted general-concept evidence.
- The companion `representative_30.json.gz` contains every candidate, source excerpt, evidence ID, source scope, score, and rank. This table is only the compact review index.

## Review table

| Query | Split / locale | Expected | Criteria | Baseline top 3 | v2 top 3 | v2 label | Hard violations |
|---|---|---|---|---|---|---:|---:|
| `cross-02-3` | HOLDOUT / EN | positive | CRISPY + CHICKEN + FRIED + ₩10k–19,999 | 후라이드치킨(뼈)<br>간장순살치킨<br>양념순살치킨 | 후라이드치킨(Fried chicken)<br>치킨스넥<br>모짜 치킨 바이츠 | 3/3/3 | 0 |
| `cross-04-2` | TUNE / KO | positive | NOODLES + ITALIAN | 크림치즈 딸기미니<br>크림치즈 딸기미니<br>콘샐러드 | 매콤크림 파스타<br>피자+파스타 세트<br>피자+파스타 세트 | 2/2/2 | 0 |
| `cross-04-3` | TUNE / EN | positive | NOODLES + ITALIAN + ₩10k–19,999 | 잔치국수<br>바지락 칼국수<br>바지락생면칼국수 | 옥수수 콘킬리에 파스타<br>매콤크림 파스타<br>오리 크림 파스타 | 2/2/2 | 0 |
| `cross-07-1` | TUNE / EN | positive | JAPANESE + FISH/SEAFOOD | 타코야끼 머스타드<br>양념치킨소스<br>양념치킨컵소스 | 참치오므라이스<br>연어초밥<br>사시미&초밥세트 | 2/2/2 | 0 |
| `cross-08-1` | TUNE / EN | positive | BREAD + AMERICAN + GRILLED | 양념치킨소스류 3건 | JG버거<br>하와이안 버거<br>트러플머쉬룸버거 | 2/2/2 | 0 |
| `cross-09-2` | TUNE / KO | positive | NOODLES + CHINESE + STIR-FRIED | 미니짬뽕국물<br>양념치킨소스류 2건 | 칠리탕수육+짬뽕+볶음밥<br>탕수육+볶음밥+짜장면<br>짬뽕+볶음밥+탕수육 | 2/2/2 | 0 |
| `cross-12-3` | TUNE / EN | positive | KOREAN + PORK + GRILLED + ₩10k–19,999 | 순대국밥류 3건 | 갈비 정식 도시락<br>벌집삼겹살구이<br>삼겹살구이 도시락 | 2/2/2 | 0 |
| `cross-16-2` | HOLDOUT / KO | positive | SWEET + DESSERT/BAKERY + BAKED | 양념치킨소스류 3건 | 아카시아 꿀꽈배기 도넛<br>핑구 초코 퍼지 케이크<br>골든 프랄린 버터 쿠키 샌드 | 2/2/2 | 0 |
| `cross-18-3` | HOLDOUT / EN | positive | CHEWY + NOODLES + STIR-FRIED + ₩10k–19,999 | 고추잡채<br>잡채밥 2건 | 야끼소바<br>저당 불닭볶음면<br>탕수육+볶음밥+짬뽕 | 2/2/2 | 0 |
| `cross-19-3` | TUNE / EN | positive | SOFT + SOUP + SIMMERED + ₩10k–19,999 | 순대국밥류 3건 | 국물닭발떡볶이<br>오소리감투순대국밥<br>소고기 화개장터국밥 | 2/2/2 | 0 |
| `equivalence-04-en` | TUNE / EN | positive | NOODLES + ITALIAN | 콘샐러드<br>양념치킨소스류 2건 | 매콤크림 파스타<br>피자+파스타 세트<br>피자+파스타 세트 | 2/2/2 | 0 |
| `equivalence-04-ko` | TUNE / KO | positive | NOODLES + ITALIAN | 크림치즈 딸기미니 2건<br>콘샐러드 | 매콤크림 파스타<br>피자+파스타 세트<br>피자+파스타 세트 | 2/2/2 | 0 |
| `equivalence-05-ko` | TUNE / KO | positive | SWEET + FROZEN + DESSERT/BAKERY | 양념치킨소스류 3건 | 바바리안 미니도넛<br>딸기 스윗 허니<br>딸기 폴 인 럽 | 3/3/3 | 0 |
| `equivalence-09-en` | TUNE / EN | positive | NOODLES + CHINESE + STIR-FRIED | 미니짬뽕국물<br>양념치킨소스류 2건 | 칠리탕수육+짬뽕+볶음밥<br>탕수육+볶음밥+짜장면<br>짬뽕+볶음밥+탕수육 | 2/2/2 | 0 |
| `equivalence-10-en` | HOLDOUT / EN | positive | NOODLES + SOUP + SOUTHEAST ASIAN | 양념치킨소스류 3건 | 소고기쌀국수<br>쌀국수 3인세트<br>쌀국수 2인세트 | 2/2/2 | 0 |
| `negative-05` | TUNE / EN | NO_MATCH | FROZEN + SOUP + MEXICAN | 양념치킨소스류 3건 | NO_MATCH | — | 0 |
| `negative-06` | TUNE / KO | NO_MATCH | FROZEN + STEW/HOTPOT + ITALIAN | 양념치킨소스류 3건 | NO_MATCH | — | 0 |
| `negative-14` | HOLDOUT / KO | NO_MATCH | verified VEGAN | NO_MATCH | NO_MATCH | — | 0 |
| `negative-18` | TUNE / KO | NO_MATCH | CHEWY + SOUP + AMERICAN | 미니짬뽕국물<br>양념치킨소스류 2건 | NO_MATCH | — | 0 |
| `negative-19` | TUNE / EN | NO_MATCH | FROZEN + DESSERT/BAKERY + FISH/SEAFOOD | 양념치킨소스류 3건 | NO_MATCH | — | 0 |
| `single-cooking_methods-baked-en` | HOLDOUT / EN | positive | BAKED | 연유 소스<br>크림치즈 딸기미니 2건 | 베이크드 스위트 포테이토<br>치즈오븐김치볶음밥<br>투움바 스파게티 | 3/3/3 | 0 |
| `single-cooking_methods-fried-ko` | TUNE / KO | positive | FRIED | 양념치킨소스류 3건 | 후라이드 치킨<br>새우계란볶음밥<br>튀김세트 | 3/3/3 | 0 |
| `single-cuisine_origins-korean-ko` | TUNE / KO | positive | KOREAN | 도시락 김류 3건 | 전통식혜<br>버섯소불고기 국반상<br>본격도시락 | 3/3/3 | 0 |
| `single-flavors-clean_mild-ko` | TUNE / KO | positive | CLEAN_MILD | 도시락 김류 3건 | 담백한 두부 샐러드<br>마일드살사<br>진라면 순한맛 | 3/3/3 | 0 |
| `single-flavors-nutty_savory-en` | TUNE / EN | positive | NUTTY/SAVORY | 양념치킨소스류 3건 | 지파이 고소한맛<br>고소담백 알찜<br>스크램블 볶음밥 도시락 | 3/3/3 | 0 |
| `single-flavors-nutty_savory-ko` | HOLDOUT / KO | positive | NUTTY/SAVORY | 양념치킨소스류 3건 | 지파이 고소한맛<br>고소담백 알찜<br>스크램블 볶음밥 도시락 | 3/3/3 | 0 |
| `single-flavors-sour-en` | TUNE / EN | positive | SOUR | 양념치킨소스류 3건 | 사워크림<br>매콤 닭강정<br>매콤새콤 비빔쫄면 | 3/3/3 | 0 |
| `single-food_forms-grilled_dish-en` | HOLDOUT / EN | positive | GRILLED_DISH | 미니짬뽕국물<br>콘샐러드<br>도넛 깨찰이 | CJ리얼 스팸구이<br>갈비 구이<br>LA갈비구이 한정식 | 3/3/3 | 0 |
| `single-temperatures-hot-en` | TUNE / EN | positive | HOT | 미니짬뽕국물<br>타코야끼 머스타드<br>양념치킨소스 | 컵국(된장국) 2건<br>컵국(미역국) | 3/3/3 | 0 |
| `single-temperatures-warm-ko` | TUNE / KO | positive | WARM | 양념치킨소스류 3건 | 따뜻한 아메리카노 2샷<br>따뜻한 아메리카노 1샷<br>따뜻한 커플세트 | 3/3/3 | 0 |

## Human sign-off checklist

- [ ] 메뉴명과 원문 excerpt가 각 선택 조건을 실제로 지지한다.
- [ ] concept 일반 근거를 메뉴 고유 사실로 오인하지 않았다.
- [ ] 옵션·섹션 근거만으로 식이 안전성이나 기본 조리법을 확정하지 않았다.
- [ ] 반증과 `NO_MATCH` 판단이 타당하다.
- [ ] 한·영 동등 질의가 동일한 top-20 집합을 반환한다.
- [ ] 이 표와 상세 JSON을 검토한 후 Oracle/OCI write gate를 승인한다.
