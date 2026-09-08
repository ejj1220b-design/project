# roasloop

Meta 광고를 대량으로 찍어내고 → ROAS 높은 것만 남기고 → 남은 것의 DNA로 다시 대량 생산하는 루프를 자동화한다.

리터니티(returnity.global) 글로벌 퍼포먼스 운영을 전제로 만들었다. 네이밍 규칙, 랜딩 마스터, 목표 ROAS 대역이 전부 기존 시트에서 그대로 옮겨져 있다.

## 루프 한 바퀴

```
plan ──▶ launch ──▶ (며칠 태운다) ──▶ harvest ──▶ judge ──▶ prune
                                                    │
                                                    ▼
              matrix.yaml 갱신 ◀── breed ◀──────── dna
                    │
                    └──▶ 다시 plan
```

| 명령 | 하는 일 |
|---|---|
| `plan` | 조합 매트릭스를 펼쳐 광고 명세 CSV 생성. 소재가 없는 조합은 '제작 대기'로 분리 |
| `launch` | 명세대로 Meta에 대량 생성 (기본 dry-run · 기본 PAUSED) |
| `harvest` | 광고 단위 성과 수집 |
| `judge` | ROAS 컷 판정 → KILL / KEEP / SCALE / INSUFFICIENT |
| `prune` | KILL 판정된 광고를 실제로 중단 (`--yes` 필요) |
| `dna` | 살아남은 축(카피 앵글·오브제·소재유형) 분석 → 다음 라운드 축 |
| `breed` | 승자 DNA로 새 카피 + 촬영 기획안 생성 → matrix 블록 |

## 설치

```bash
pip install -e .
cp .env.example .env      # 토큰 채우기
```

필요한 것: Meta Marketing API 토큰(`ads_management`, `ads_read`), 광고 계정 ID, 페이지 ID, 픽셀 ID, Anthropic API 키(`breed`용).

## 빠른 시작

```bash
# 1. 이번 라운드에 무엇이 만들어질지 확인
roasloop plan --show-pending

# 2. 소재를 config/matrix.yaml 의 assets 에 연결한 뒤, 먼저 dry-run
roasloop launch data/runs/20260908/plan_R1.csv
roasloop launch data/runs/20260908/plan_R1.csv --execute   # PAUSED 로 생성됨

# 3. 며칠 태운 뒤
roasloop harvest --days 14
roasloop judge
roasloop prune --yes

# 4. 승자에서 다음 라운드 만들기
roasloop dna
roasloop breed -n 8 --reviews data/reviews.txt
```

## 설정 파일

| 파일 | 내용 |
|---|---|
| `config/taxonomy.yaml` | 네이밍 코드마스터. 새 값은 **반드시 여기에 먼저** 추가한다 |
| `config/landing.yaml` | 랜딩ID ↔ URL |
| `config/account.yaml` | 계정 기본값, UTM 정책, 전환 action_type |
| `config/rules.yaml` | ROAS 컷 규칙 — 목표선, 게이트, 신뢰수준 |
| `config/matrix.yaml` | 이번 라운드에 무엇을 몇 개 찍을지 |

## 판정 로직 — 왜 그냥 ROAS로 자르지 않는가

구매 3건에 ROAS 1.4인 소재를 목표 2.0 미달이라고 끄면, 실제로는 좋은 소재를 노이즈로 죽인 것일 수 있다. 구매 수가 적을수록 관측 ROAS는 심하게 흔들린다.

roasloop은 구매 건수를 포아송으로 보고 ROAS 신뢰구간을 만든다. 그리고 **구간 전체가 목표선 아래일 때만** 끈다.

| 상황 | 관측 ROAS | 신뢰구간(80%) | 판정 |
|---|---|---|---|
| 구매 3건 / 15만원 | 1.40 | 0.51 ~ 3.11 | **KEEP** — 아직 모른다 |
| 구매 20건 / 100만원 | 1.40 | 1.02 ~ 1.89 | **KILL** — 목표 미달 확실 |
| 구매 0건 / 13만원 | 0.00 | 0.00 ~ 0.97 | **KILL** — 조기 종료 |
| 구매 27건 / 30만원 | 5.00 | 3.28 ~ 7.74 | **SCALE** — 승자 |

판정 순서:

1. **조기 종료** — 목표 CPA의 3배를 쓰고 구매 0건이면, 게이트를 못 넘겼어도 끈다
2. **게이트** — 지출·노출·기간이 모자라면 판정 보류(INSUFFICIENT), 계속 돌린다
3. **KILL** — 신뢰구간 상단 < 목표 ROAS
4. **SCALE** — 신뢰구간 하단 ≥ 확장선
5. **KEEP** — 그 외. 아직 판단이 안 서는 구간

`rules.yaml`의 `confidence.level`이 이 판정의 공격성을 결정한다. 기본 0.80은 소재 테스트에 맞춘 값이다. 0.95로 올리면 구간이 넓어져 거의 아무것도 끄지 못하고, 0.70으로 내리면 성급하게 끈다.

## DNA 분석 — 개별 판정보다 이쪽이 믿을 만하다

`judge`는 광고 하나하나를 보고, `dna`는 축(카피 앵글 / 오브제 / 소재유형 / 상품 / 프로모션) 단위로 합쳐서 본다. 축으로 합치면 표본이 커져 신뢰구간이 좁아진다.

```
[카피 앵글]
  사우나필수템     광고12  지출 2,122,733  ROAS 3.13  구간 2.77~3.52   승2/패0
  30대부터율무     광고12  지출 1,591,457  ROAS 1.76  구간 1.46~2.11   승0/패1
  모공고민끝       광고12  지출 1,841,505  ROAS 0.95  구간 0.74~1.20   승0/패3
```

개별 광고는 전부 KEEP(판단 보류)이어도, 축으로 합치면 어느 앵글이 이겼는지 명확해진다. 이게 다음 라운드 축이 된다.

**교란 경고(⚠)**를 반드시 본다. `사우나필수템`이 전부 Video로만 만들어졌다면, 그 앵글의 성적은 사실 Video의 성적일 수 있다. roasloop은 각 값이 다른 축의 몇 가지 값과 짝지어졌는지 세어서 이 경우를 표시한다. 교란이 뜨면 다음 라운드에서 그 축을 교차시켜 다시 검증한다.

## 네이밍 — 여기가 무너지면 전부 무너진다

DNA 분석은 광고명 역파싱에 전적으로 의존한다.

```
캠페인  E_US_Meta_DA_SPF_EN_Yulmu_Conversion_ASC^American
광고셋  Demo.180d_F2534_Purchase^American
광고    26Regular_YulmuMask_Video_사우나필수템_공병템_SPF.YulmuMask.PDP_260429^CA
```

자유입력 칸(카피·오브제)에 공백이나 언더스코어가 하나만 섞여도 슬롯이 밀리고, 그 시점부터 집계가 **조용히** 무너진다. 에러가 나지 않아서 더 위험하다. roasloop은 생성할 때 막고(`validate`), 파싱할 때 다시 검사하며, 규칙을 벗어난 광고는 DNA 분석에서 제외하고 개수를 리포트한다.

`breed`가 만드는 카피 코드도 자동으로 안전형으로 정규화된다.

## UTM

`utm_medium`은 `paid_social`로 고정되어 있다.

이전에 쓰던 `DA`는 GA4 기본 채널 그룹의 유료 판정 정규식 `^(.*cp.*|ppc|retargeting|paid.*)$`에 걸리지 않아 Unassigned/Other로 떨어진다. 네이밍 규칙 v1.0 시트에는 `utm_medium = Medium`으로 되어 있으나 이후 UTM 생성기 시트에서 정정되었고, 여기서는 최신 정책을 따른다.

기본값은 동적 매크로 방식이다. 광고 생성 시 `url_tags`에 아래 한 줄이 들어가고, Meta가 이름을 자동으로 채우고 인코딩까지 한다. 광고명을 바꿔도 URL을 다시 만들 필요가 없다.

```
utm_source=meta&utm_medium=paid_social&utm_campaign={{campaign.name}}&utm_content={{adset.name}}&utm_term={{ad.name}}
```

## 안전장치

- `launch`는 기본 dry-run. 실제 생성은 `--execute`
- 생성된 광고는 기본 PAUSED. 켜려면 `--activate`
- `prune`은 기본적으로 대상만 보여준다. 실제 중단은 `--yes`
- 같은 이름의 캠페인·광고셋이 있으면 재사용한다 (중복 생성 방지)
- 집행한 광고명은 `data/history.txt`에 쌓이고, 다음 `plan`에서 같은 조합을 자동으로 제외한다

## 개발

```bash
pip install -e ".[dev]"
pytest -q
```

## 알고 쓸 것

- 신뢰구간은 객단가를 관측값으로 고정한다. 번들과 단품이 섞인 소재는 실제 폭이 계산값보다 조금 넓다.
- 어트리뷰션 지연은 구간에 반영되지 않는다. `rules.yaml`의 `min_days` 게이트가 그 역할을 한다.
- `harvest`는 어제까지만 가져온다. 당일 데이터는 미확정이다.
- 광고 나이를 별도로 조회해 조회 기간과 짧은 쪽을 `days_active`로 쓴다. 어제 만든 광고가 30일 조회에서 게이트를 부당 통과하는 것을 막기 위함이다.
