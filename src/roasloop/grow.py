"""확장 후보 발굴 — 유지(KEEP) 중인 소재에서 키울 것을 찾는다.

왜 필요한가.
    SCALE 판정은 "신뢰구간 하단이 확장선을 넘는가" 를 묻는다. 엄격해서 좀처럼 나오지
    않는다(실제 계정에서 0개였다). 그래서 대부분이 KEEP 에 쌓이는데, KEEP 은
    "아직 모르겠다" 라는 뜻일 뿐 "볼 것 없다" 가 아니다. 그 안에 아직 증명되지 않았을
    뿐인 승자가 섞여 있다.

무엇을 보는가.
    확장 후보는 '지금 좋은 소재' 가 아니라 **'예산을 더 주면 증명될 소재'** 다.
    그래서 성과만이 아니라 여유(headroom)를 함께 본다.

        증거   관측 ROAS 가 목표 위인가 · 신뢰구간 하단이 목표 위인가
        추세   최근 절반이 이전 절반보다 나은가
        리듬   구매가 끊기지 않는가
        여유   빈도가 낮아 도달을 더 늘릴 수 있는가

    그리고 가장 실용적인 숫자 하나를 계산한다:
    **얼마를 더 태우면 확장 판정이 나는가.**
    지금 ROAS 가 유지된다는 가정 아래, 신뢰구간 하단이 확장선을 넘기려면 구매가 몇 건
    더 필요한지 역산해 CPA 를 곱한다. "이 소재에 24만원 더" 처럼 바로 집행할 수 있는
    형태가 된다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .judge import Judgement, Verdict
from .stats import poisson_interval

#: 확장 판정까지 필요한 추가 지출을 계산할 때 훑어볼 최대 구매 건수
_MAX_SEARCH = 2000


def purchases_needed_for_scale(
    point_roas: float, purchases: int, scale_roas: float, level: float
) -> int | None:
    """지금 ROAS 가 유지될 때, 신뢰구간 하단이 확장선을 넘기려면 필요한 총 구매 건수.

    구간 하단은 관측 ROAS × (k 하단 / k) 이므로, 그 비율이 scale/point 이상이 되는
    가장 작은 k 를 찾는다. 표본이 커질수록 비율이 1 에 수렴하므로 단조 증가한다.
    """
    if point_roas <= 0 or scale_roas <= 0:
        return None
    needed_ratio = scale_roas / point_roas
    if needed_ratio > 1:
        return None          # 지금 ROAS 자체가 확장선 아래면 표본을 늘려도 못 넘는다
    for k in range(max(purchases, 1), _MAX_SEARCH):
        lo, _ = poisson_interval(k, level)
        if lo / k >= needed_ratio:
            return k
    return None


@dataclass
class Candidate:
    judgement: Judgement
    score: int = 0
    reasons: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    extra_spend_to_prove: float | None = None
    #: 확장 판정에 필요한 표본이 현실적인 규모를 넘어설 때의 사유
    prove_note: str = ""
    trend: float | None = None          # 최근 절반 ROAS − 이전 절반 ROAS

    @property
    def perf(self):
        return self.judgement.perf

    @property
    def interval(self):
        return self.judgement.interval


def _trend(history) -> float | None:
    """전반부 대비 후반부 ROAS 변화. 날짜별 데이터가 있어야 계산된다."""
    if history is None:
        return None
    days = sorted(history.days.items())
    active = [(d, v) for d, v in days if v["spend"] > 0]
    if len(active) < 6:
        return None
    half = len(active) // 2
    def roas(rows):
        sp = sum(v["spend"] for _, v in rows)
        rv = sum(v["revenue"] for _, v in rows)
        return rv / sp if sp else 0.0
    return roas(active[half:]) - roas(active[:half])


def build(
    judgements: list[Judgement],
    rules: dict,
    steady_report=None,
    live_only: bool = True,
) -> list[Candidate]:
    targets = rules.get("targets", {})
    target = float(targets.get("target_roas", 1.8))
    scale = float(targets.get("scale_roas", 2.5))
    level = float(rules.get("confidence", {}).get("level", 0.80))
    max_freq = float(rules.get("guards", {}).get("max_frequency", 3.0))

    histories = {}
    steady_ids: set[str] = set()
    rising_ids: set[str] = set()
    if steady_report is not None:
        histories = {h.ad_id: h for h in steady_report.all_histories}
        steady_ids = {h.ad_id for h in steady_report.steady}
        rising_ids = {h.ad_id for h in steady_report.rising}

    out: list[Candidate] = []
    for j in judgements:
        if j.verdict != Verdict.KEEP:
            continue
        p = j.perf
        if live_only and not p.is_live:
            continue
        if p.purchases == 0:
            continue
        # 목표 미달 소재는 후보가 아니다. 빈도가 낮다는 이유만으로 '키울 소재' 목록에
        # 오르면 목록 전체를 믿을 수 없게 된다.
        if j.interval.point < target:
            continue

        c = Candidate(judgement=j)

        # 증거 — 지금까지의 성적
        if j.interval.point >= scale:
            c.score += 3
            c.reasons.append(f"관측 ROAS {j.interval.point:.2f} 가 확장선 위")
        elif j.interval.point >= target:
            c.score += 2
            c.reasons.append(f"관측 ROAS {j.interval.point:.2f} 가 목표 위")
        if j.interval.lower >= target:
            c.score += 2
            c.reasons.append(f"신뢰구간 하단 {j.interval.lower:.2f} 도 목표 위 — 목표 초과는 확실")

        # 추세
        c.trend = _trend(histories.get(p.ad_id))
        if c.trend is not None:
            if c.trend > 0.3:
                c.score += 2
                c.reasons.append(f"후반부 ROAS 가 전반부보다 {c.trend:+.2f} — 오르는 중")
            elif c.trend < -0.3:
                c.score -= 2
                c.blockers.append(f"후반부 ROAS 가 {c.trend:+.2f} — 내려가는 중")

        # 리듬
        if p.ad_id in steady_ids:
            c.score += 2
            c.reasons.append("구매가 꾸준히 발생 — 매출 기반")
        elif p.ad_id in rising_ids:
            c.score += 1
            c.reasons.append("구매 리듬이 좋음 (아직 어림)")

        # 여유
        if p.frequency and p.frequency < 1.8:
            c.score += 1
            c.reasons.append(f"빈도 {p.frequency:.1f} — 도달을 더 늘릴 여유가 있음")
        elif p.frequency >= max_freq:
            c.score -= 2
            c.blockers.append(f"빈도 {p.frequency:.1f} — 같은 사람에게 반복 노출 중, 확장 여지가 적음")

        # 얼마를 더 태우면 증명되는가
        # 얼마를 더 태우면 확장 판정이 나는가.
        #
        # 관측 ROAS 가 확장선에 아슬아슬하게 붙어 있으면 필요한 표본이 폭증한다
        # (2.6 으로 2.5 를 넘는다고 증명하려면 구매 1000건이 넘게 든다).
        # 수학은 맞지만 집행할 수 있는 숫자가 아니므로, 감당할 만한 규모일 때만 보여준다.
        # 두 가지 '못 닿음' 을 구분해야 한다.
        #   관측 ROAS 가 확장선 아래   → 표본을 늘려도 원리상 불가
        #   확장선 바로 위             → 가능은 하나 필요한 표본이 비현실적
        need = purchases_needed_for_scale(j.interval.point, p.purchases, scale, level)
        if j.interval.point < scale:
            c.prove_note = (
                f"관측 ROAS 가 확장선({scale:.1f}) 아래라 표본을 늘려도 확장 판정은 안 납니다. "
                "판정과 무관하게 위 근거만으로 예산을 늘릴지 결정하세요"
            )
        elif need is None:
            c.prove_note = (
                f"확장선({scale:.1f})에 너무 가까워, 판정이 나려면 비현실적인 표본이 필요합니다 "
                "— 판정보다 성과를 보고 결정하세요"
            )
        elif p.cpa == float("inf"):
            pass
        else:
            extra = (need - p.purchases) * p.cpa
            if extra <= p.spend * 3:
                c.extra_spend_to_prove = extra
            else:
                c.prove_note = (
                    f"확장선({scale:.1f})에 너무 가까워, 판정이 나려면 지금 지출의 "
                    f"{extra / max(p.spend, 1):.0f}배가 듭니다 — 판정보다 성과를 보고 결정하세요"
                )

        if c.score > 0:
            out.append(c)

    out.sort(key=lambda c: (-c.score, c.extra_spend_to_prove or float("inf")))
    return out
