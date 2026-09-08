"""ROAS 컷 판정.

입력은 광고 단위 성과 한 줄, 출력은 KILL / KEEP / SCALE / INSUFFICIENT 넷 중 하나다.
판정 순서가 곧 정책이다:

    1. 조기 종료   충분히 썼는데 구매 0건 → KILL (게이트를 못 넘겼어도)
    2. 게이트      지출·노출·기간이 모자라면 → INSUFFICIENT (판정 보류, 계속 돌린다)
    3. KILL        ROAS 신뢰구간 상단 < 목표 → 목표 미달이 거의 확실
    4. SCALE       ROAS 신뢰구간 하단 >= 확장선 → 목표 초과가 거의 확실
    5. KEEP        그 외 — 아직 판단이 안 서는 구간. 더 태운다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .stats import RoasInterval, roas_interval


class Verdict(str, Enum):
    KILL = "KILL"
    KEEP = "KEEP"
    SCALE = "SCALE"
    INSUFFICIENT = "INSUFFICIENT"


@dataclass
class AdPerformance:
    """광고 한 개의 성과. insights 모듈이 이 형태로 정규화해서 넘긴다."""

    ad_id: str
    ad_name: str
    adset_name: str = ""
    campaign_name: str = ""
    spend: float = 0.0
    revenue: float = 0.0
    purchases: int = 0
    impressions: int = 0
    clicks: int = 0
    frequency: float = 0.0
    days_active: int = 0

    @property
    def roas(self) -> float:
        return self.revenue / self.spend if self.spend else 0.0

    @property
    def ctr(self) -> float:
        return self.clicks / self.impressions if self.impressions else 0.0

    @property
    def cpa(self) -> float:
        return self.spend / self.purchases if self.purchases else float("inf")


@dataclass
class Judgement:
    perf: AdPerformance
    verdict: Verdict
    interval: RoasInterval
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def reason(self) -> str:
        return " / ".join(self.reasons)


def judge_one(perf: AdPerformance, rules: dict) -> Judgement:
    targets = rules["targets"]
    gates = rules["gates"]
    early = rules.get("early_kill", {})
    conf = rules.get("confidence", {})
    guards = rules.get("guards", {})

    target_roas = float(targets["target_roas"])
    scale_roas = float(targets["scale_roas"])
    level = float(conf.get("level", 0.80))
    fallback_aov = float(conf.get("fallback_aov", 0.0))

    interval = roas_interval(perf.spend, perf.revenue, perf.purchases, level, fallback_aov)

    warnings: list[str] = []
    if guards.get("max_frequency") and perf.frequency > float(guards["max_frequency"]):
        warnings.append(f"빈도 {perf.frequency:.1f} — 같은 사람에게 반복 노출 중")
    if guards.get("min_ctr") and perf.impressions >= 1000 and perf.ctr < float(guards["min_ctr"]):
        warnings.append(f"CTR {perf.ctr:.2%} — 후킹이 약함")

    # 1. 조기 종료: 충분히 썼는데 구매가 0건
    if early.get("enabled") and perf.purchases == 0:
        threshold = float(early["spend_no_purchase"])
        if perf.spend >= threshold:
            return Judgement(
                perf, Verdict.KILL, interval,
                [f"{perf.spend:,.0f} 지출 · 구매 0건 (조기 종료선 {threshold:,.0f})"],
                warnings,
            )

    # 2. 게이트: 판정할 만큼 데이터가 쌓였는가
    unmet = []
    if perf.spend < float(gates["min_spend"]):
        unmet.append(f"지출 {perf.spend:,.0f}/{float(gates['min_spend']):,.0f}")
    if perf.impressions < int(gates["min_impressions"]):
        unmet.append(f"노출 {perf.impressions:,}/{int(gates['min_impressions']):,}")
    if perf.days_active < int(gates["min_days"]):
        unmet.append(f"기간 {perf.days_active}/{int(gates['min_days'])}일")
    if unmet:
        return Judgement(
            perf, Verdict.INSUFFICIENT, interval,
            ["판정 보류 — " + ", ".join(unmet)], warnings,
        )

    # 3~5. 신뢰구간과 목표선 비교
    if interval.upper < target_roas:
        return Judgement(
            perf, Verdict.KILL, interval,
            [f"ROAS 상단 {interval.upper:.2f} < 목표 {target_roas:.2f} — 목표 미달 확실"],
            warnings,
        )
    if interval.lower >= scale_roas:
        return Judgement(
            perf, Verdict.SCALE, interval,
            [f"ROAS 하단 {interval.lower:.2f} >= 확장선 {scale_roas:.2f} — 승자"],
            warnings,
        )
    return Judgement(
        perf, Verdict.KEEP, interval,
        [f"ROAS {interval.point:.2f} [{interval.lower:.2f}~{interval.upper:.2f}] — 판단 구간, 더 태운다"],
        warnings,
    )


def judge_all(perfs: list[AdPerformance], rules: dict) -> list[Judgement]:
    """전체 판정. 확장 후보가 위로 오도록 정렬한다."""
    order = {Verdict.SCALE: 0, Verdict.KEEP: 1, Verdict.INSUFFICIENT: 2, Verdict.KILL: 3}
    results = [judge_one(p, rules) for p in perfs]
    results.sort(key=lambda j: (order[j.verdict], -j.interval.lower, -j.perf.spend))
    return results


def summarize(judgements: list[Judgement]) -> dict:
    out: dict = {}
    for v in Verdict:
        rows = [j for j in judgements if j.verdict == v]
        spend = sum(j.perf.spend for j in rows)
        revenue = sum(j.perf.revenue for j in rows)
        out[v.value] = {
            "count": len(rows),
            "spend": spend,
            "revenue": revenue,
            "roas": (revenue / spend) if spend else 0.0,
            "purchases": sum(j.perf.purchases for j in rows),
        }
    return out
