"""꾸준히 오래 구매를 일으킨 소재 — '스테디' 판정.

왜 따로 보는가.
    기간 합계 ROAS 만 보면 두 가지가 같은 줄에 선다.

        A  14일 내내 매일 1~2건씩 팔린 소재
        B  이틀 몰아서 팔리고 열이틀 조용한 소재

    합계는 같아도 다음 달에 기대할 수 있는 것이 전혀 다르다. A 는 매출 기반이고
    B 는 운이다. 그런데 스냅샷 판정에서는 구분되지 않고, 심하면 A 가 목표선을
    살짝 밑돈다는 이유로 꺼진다. 그러면 안정적인 매출 기반이 사라진다.

무엇으로 재는가.
    살아 있던 날 (지출이 발생한 날)
    구매가 난 날
    구매가 난 날의 비율 = 구매일 / 활동일
    광고 나이 (만들어진 지 며칠)

    '오래' 는 나이로, '꾸준히' 는 구매일 비율로 잰다. 둘을 같이 봐야 한다.
    나이만 보면 오래 켜두기만 한 소재가 올라오고, 비율만 보면 사흘 살고 사흘 다
    판 신규 소재가 올라온다.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class AdHistory:
    ad_id: str
    ad_name: str
    campaign_name: str = ""
    days: dict[str, dict] = field(default_factory=dict)   # 날짜 → {spend, revenue, purchases}
    age_days: int | None = None

    @property
    def active_days(self) -> int:
        return sum(1 for d in self.days.values() if d["spend"] > 0)

    @property
    def purchase_days(self) -> int:
        return sum(1 for d in self.days.values() if d["purchases"] > 0)

    @property
    def purchase_day_rate(self) -> float:
        return self.purchase_days / self.active_days if self.active_days else 0.0

    @property
    def spend(self) -> float:
        return sum(d["spend"] for d in self.days.values())

    @property
    def revenue(self) -> float:
        return sum(d["revenue"] for d in self.days.values())

    @property
    def purchases(self) -> int:
        return sum(d["purchases"] for d in self.days.values())

    @property
    def roas(self) -> float:
        return self.revenue / self.spend if self.spend else 0.0

    @property
    def first_day(self) -> str:
        active = [k for k, v in sorted(self.days.items()) if v["spend"] > 0]
        return active[0] if active else ""

    @property
    def last_day(self) -> str:
        active = [k for k, v in sorted(self.days.items()) if v["spend"] > 0]
        return active[-1] if active else ""

    @property
    def longest_dry_spell(self) -> int:
        """구매 없이 지나간 최장 연속 일수 (활동한 날 기준)."""
        streak = worst = 0
        for _, day in sorted(self.days.items()):
            if day["spend"] <= 0:
                continue
            if day["purchases"] > 0:
                streak = 0
            else:
                streak += 1
                worst = max(worst, streak)
        return worst

    def sparkline(self, width: int = 14) -> str:
        """구매가 난 날은 채우고 없는 날은 비운다. 리듬이 눈에 보이게."""
        marks = []
        for _, day in sorted(self.days.items())[-width:]:
            if day["spend"] <= 0:
                marks.append("·")
            elif day["purchases"] > 0:
                marks.append("█")
            else:
                marks.append("▁")
        return "".join(marks)


@dataclass
class SteadyReport:
    #: 오래됐고 구매가 꾸준한 소재. 매출 기반이다.
    steady: list[AdHistory] = field(default_factory=list)
    #: 리듬은 좋은데 아직 어린 소재. 스테디 후보다.
    rising: list[AdHistory] = field(default_factory=list)
    #: 매출은 났지만 몰려서 난 소재. 같은 ROAS 라도 다음 달 기대치가 다르다.
    spiky: list[AdHistory] = field(default_factory=list)
    all_histories: list[AdHistory] = field(default_factory=list)
    window_days: int = 0

    @property
    def steady_ids(self) -> set[str]:
        return {h.ad_id for h in self.steady}


def build_histories(
    daily_rows: list[dict],
    ages: dict[str, int] | None = None,
    campaigns: dict[str, str] | None = None,
) -> list[AdHistory]:
    ages = ages or {}
    campaigns = campaigns or {}
    by_ad: dict[str, AdHistory] = {}
    for row in daily_rows:
        ad_id = row.get("ad_id", "")
        if not ad_id:
            continue
        h = by_ad.get(ad_id)
        if h is None:
            h = by_ad[ad_id] = AdHistory(
                ad_id=ad_id, ad_name=row.get("ad_name", ""),
                campaign_name=campaigns.get(ad_id, ""), age_days=ages.get(ad_id),
            )
        h.days[row.get("date", "")] = {
            "spend": float(row.get("spend") or 0),
            "revenue": float(row.get("revenue") or 0),
            "purchases": int(row.get("purchases") or 0),
        }
    return list(by_ad.values())


def build(daily_rows: list[dict], rules: dict,
          ages: dict[str, int] | None = None,
          campaigns: dict[str, str] | None = None) -> SteadyReport:
    cfg = rules.get("steady", {}) or {}
    min_active = int(cfg.get("min_active_days", 7))
    min_pdays = int(cfg.get("min_purchase_days", 4))
    min_rate = float(cfg.get("min_purchase_day_rate", 0.4))
    min_age = int(cfg.get("min_age_days", 21))
    min_roas = float(cfg.get("min_roas", 1.5))

    histories = build_histories(daily_rows, ages, campaigns)
    report = SteadyReport(all_histories=histories)
    report.window_days = len({r.get("date") for r in daily_rows if r.get("date")})

    for h in histories:
        if h.purchases == 0 or h.roas < min_roas:
            continue
        # 리듬 — 구매가 끊기지 않는가. 표본 길이와는 별개의 질문이다.
        good_rhythm = h.purchase_day_rate >= min_rate and h.purchase_days >= 2
        # 표본 — 판단할 만큼 오래 돌았는가.
        enough_data = h.active_days >= min_active and h.purchase_days >= min_pdays
        old_enough = h.age_days is None or h.age_days >= min_age

        if good_rhythm and enough_data and old_enough:
            report.steady.append(h)
        elif good_rhythm:
            # 리듬은 좋은데 아직 짧거나 어리다. '몰려서 났다' 와는 다른 물건이다.
            # 어린 소재는 활동일이 짧은 게 당연하므로 표본 조건을 걸지 않는다.
            report.rising.append(h)
        elif h.purchases >= 3:
            report.spiky.append(h)

    report.steady.sort(key=lambda h: (-h.purchase_days, -h.roas))
    report.rising.sort(key=lambda h: (-h.purchase_day_rate, -h.roas))
    report.spiky.sort(key=lambda h: -h.purchases)
    return report
