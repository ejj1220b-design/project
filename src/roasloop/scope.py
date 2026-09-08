"""판정 대상 범위.

모든 캠페인을 ROAS 로 판정할 수는 없다. 전환을 측정할 수 없는 캠페인이 섞여 있으면
그 지출이 전부 '매출 0' 으로 잡혀 계정 전체 ROAS 를 끌어내리고, 개별 광고는 죄다
KILL 판정을 받는다. 판정 자체가 무의미해진다.

측정할 수 없는 대표적인 경우
    · 아마존 캠페인 — 랜딩이 아마존 내부라 자사몰 픽셀이 구매를 볼 수 없다
    · 트래픽·도달·조회 캠페인 — 애초에 구매가 목표가 아니다

제외한다고 없는 셈 치지는 않는다. 지출은 그대로 집계해서 "측정 제외" 로 따로 보여준다.
아마존에 얼마를 썼는지는 여전히 알아야 하기 때문이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Exclusion:
    pattern: re.Pattern
    reason: str


class MeasurementScope:
    """ROAS 로 판정할 수 있는 캠페인인지 가린다."""

    def __init__(self, config: dict | None = None):
        config = config or {}
        self.exclusions = [
            Exclusion(re.compile(str(rule["pattern"])), str(rule.get("reason", "측정 대상 아님")))
            for rule in (config.get("exclude") or [])
            if isinstance(rule, dict) and "pattern" in rule
        ]
        include = config.get("include") or []
        self.inclusions = [re.compile(str(r["pattern"])) for r in include if isinstance(r, dict) and "pattern" in r]

    def reason_for_exclusion(self, campaign_name: str) -> str | None:
        """제외 사유. 판정 대상이면 None."""
        for ex in self.exclusions:
            if ex.pattern.search(campaign_name):
                return ex.reason
        if self.inclusions and not any(p.search(campaign_name) for p in self.inclusions):
            return "판정 대상 목록(include)에 없음"
        return None

    def is_measurable(self, campaign_name: str) -> bool:
        return self.reason_for_exclusion(campaign_name) is None

    def split(self, items, key=lambda x: x) -> tuple[list, list[tuple]]:
        """(판정 대상, [(항목, 제외사유), ...])"""
        keep, dropped = [], []
        for item in items:
            reason = self.reason_for_exclusion(key(item))
            (dropped.append((item, reason)) if reason else keep.append(item))
        return keep, dropped


def summarize_excluded(dropped: list[tuple], spend_of=lambda x: x.spend) -> list[dict]:
    """제외 사유별 집계. 리포트에 '아마존에 얼마 썼는지' 를 남기기 위한 것."""
    buckets: dict[str, dict] = {}
    for item, reason in dropped:
        b = buckets.setdefault(reason, {"reason": reason, "count": 0, "spend": 0.0})
        b["count"] += 1
        b["spend"] += spend_of(item)
    return sorted(buckets.values(), key=lambda b: -b["spend"])
