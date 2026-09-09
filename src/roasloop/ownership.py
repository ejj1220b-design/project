"""캠페인 소유 구분.

대행사와 한 계정을 같이 쓰는 상황을 전제로 한다. 판정은 전체 캠페인에 대해 하되,
계정에 실제로 손대는 동작은 '내 캠페인' 으로 명시한 것에만 허용한다.

핵심 원칙: **모르면 남의 것.**
어느 규칙에도 안 걸린 캠페인은 unknown 이 되고, unknown 은 절대 건드리지 않는다.
설정을 깜빡해서 대행사 캠페인이 꺼지는 것보다, 설정을 깜빡해서 아무것도 안 꺼지는
편이 훨씬 낫기 때문이다.
"""

from __future__ import annotations

import re
from enum import Enum


class Owner(str, Enum):
    MINE = "mine"
    AGENCY = "agency"
    UNKNOWN = "unknown"

    @property
    def actionable(self) -> bool:
        """이 캠페인에 실제 변경을 가해도 되는가."""
        return self is Owner.MINE


class OwnershipError(RuntimeError):
    """내 것이 아닌 캠페인을 건드리려 할 때."""


class Ownership:
    def __init__(self, config: dict | None = None):
        config = config or {}
        self._mine = self._compile(config.get("mine"))
        self._agency = self._compile(config.get("agency"))
        self.labels = {
            Owner.MINE: "인하우스", Owner.AGENCY: "대행사", Owner.UNKNOWN: "미분류",
            **{Owner(k): v for k, v in (config.get("labels") or {}).items() if k in Owner._value2member_map_},
        }
        # 리포팅에서만 쓰는 분류. 실행 권한(require_mine)에는 영향을 주지 않는다.
        # 규칙에 안 걸린 캠페인을 성과 비교에서 어느 쪽으로 셀지만 정한다.
        raw = str(config.get("treat_unknown_as", "separate")).lower()
        self.unknown_reports_as = Owner(raw) if raw in {"mine", "agency"} else Owner.UNKNOWN

    @staticmethod
    def _compile(rules) -> list[tuple[str, object]]:
        out: list[tuple[str, object]] = []
        for rule in rules or []:
            if not isinstance(rule, dict):
                raise ValueError(f"ownership 규칙은 name 또는 pattern 을 가진 항목이어야 합니다: {rule!r}")
            if "name" in rule:
                out.append(("name", str(rule["name"])))
            elif "pattern" in rule:
                out.append(("pattern", re.compile(str(rule["pattern"]))))
            else:
                raise ValueError(f"ownership 규칙에 name 도 pattern 도 없습니다: {rule!r}")
        return out

    @staticmethod
    def _matches(campaign_name: str, rules: list[tuple[str, object]]) -> bool:
        for kind, rule in rules:
            if kind == "name" and campaign_name == rule:
                return True
            if kind == "pattern" and rule.search(campaign_name):    # type: ignore[union-attr]
                return True
        return False

    def classify(self, campaign_name: str) -> Owner:
        """대행사 규칙을 먼저 본다. 둘 다 걸리면 안전한 쪽(대행사)으로 판정한다."""
        if self._matches(campaign_name, self._agency):
            return Owner.AGENCY
        if self._matches(campaign_name, self._mine):
            return Owner.MINE
        return Owner.UNKNOWN

    def label(self, campaign_name: str) -> str:
        return self.labels[self.classify(campaign_name)]

    def is_mine(self, campaign_name: str) -> bool:
        return self.classify(campaign_name) is Owner.MINE

    def require_mine(self, campaign_name: str) -> None:
        """내 캠페인이 아니면 즉시 중단한다. 계정을 바꾸는 모든 경로가 이걸 통과해야 한다."""
        owner = self.classify(campaign_name)
        if owner.actionable:
            return
        if owner is Owner.AGENCY:
            raise OwnershipError(
                f"대행사 캠페인입니다: {campaign_name}\n"
                "  roasloop 은 대행사 캠페인을 변경하지 않습니다. 보고서로 공유하세요."
            )
        raise OwnershipError(
            f"소유가 분류되지 않은 캠페인입니다: {campaign_name}\n"
            "  안전을 위해 건드리지 않았습니다. 내 캠페인이 맞다면 config/ownership.yaml 의 mine 에 추가하세요."
        )

    def report_bucket(self, campaign_name: str) -> Owner:
        """성과 비교에서 어느 쪽으로 셀지. 실행 권한과는 무관하다.

        분류되지 않은 캠페인을 매번 목록에 적지 않고도 '내 성과' 로 셀 수 있게 한다.
        계정을 바꾸는 경로는 여전히 classify() 와 require_mine() 만 본다.
        """
        owner = self.classify(campaign_name)
        return self.unknown_reports_as if owner is Owner.UNKNOWN else owner

    def split(self, items, key=lambda x: x, for_report: bool = False) -> dict[Owner, list]:
        """항목들을 소유별로 나눈다. key 는 캠페인명을 꺼내는 함수."""
        pick = self.report_bucket if for_report else self.classify
        out: dict[Owner, list] = {o: [] for o in Owner}
        for item in items:
            out[pick(key(item))].append(item)
        return out
