"""인하우스 vs 대행사 스코어보드.

목표가 '대행사보다 잘하는 것' 일 때 필요한 것은 중단 제안 목록이 아니라 비교표다.
물량과 효율을 같은 화면에서 본다. 둘 중 하나만 이기는 것은 이기는 게 아니다.

    물량   광고 수 · 신규 소재 수 · 지출
    효율   ROAS · CPA · 구매
    학습   판정 가능 비율 · 확장 소재 수

'학습' 을 넣은 이유: 소재를 아무리 많이 올려도 광고당 예산이 판정선에 못 미치면
무엇이 좋았는지 알 수 없다. 다음 라운드가 나아지지 않는다. 물량과 효율만 보면
이 함정이 안 보인다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .judge import Judgement, Verdict
from .naming import AdName, NamingError
from .ownership import Owner


@dataclass
class Side:
    label: str
    ads: int = 0
    new_creatives: int = 0
    spend: float = 0.0
    revenue: float = 0.0
    purchases: int = 0
    impressions: int = 0
    clicks: int = 0
    winners: int = 0
    losers: int = 0
    judgeable: int = 0
    copy_angles: set[str] = field(default_factory=set)

    @property
    def roas(self) -> float:
        return self.revenue / self.spend if self.spend else 0.0

    @property
    def cpa(self) -> float:
        return self.spend / self.purchases if self.purchases else 0.0

    @property
    def judgeable_rate(self) -> float:
        return self.judgeable / self.ads if self.ads else 0.0

    @property
    def spend_per_ad(self) -> float:
        return self.spend / self.ads if self.ads else 0.0


@dataclass
class Scoreboard:
    mine: Side
    agency: Side
    period: str = ""

    def rows(self) -> list[tuple[str, str, str, str, bool | None]]:
        """(항목, 인하우스, 대행사, 차이, 내가 이기는가). 이기는가가 None 이면 승패 개념이 없는 항목."""
        m, a = self.mine, self.agency

        def n(v: float) -> str:
            return f"{v:,.0f}"

        def diff_num(x: float, y: float) -> str:
            d = x - y
            return f"{d:+,.0f}"

        def wins(x: float, y: float, lower_is_better: bool = False) -> bool | None:
            """동점이면 승패 표시를 하지 않는다."""
            if x == y:
                return None
            return x < y if lower_is_better else x > y

        return [
            ("― 물량", "", "", "", None),
            ("광고 수", n(m.ads), n(a.ads), diff_num(m.ads, a.ads), wins(m.ads, a.ads)),
            ("신규 소재", n(m.new_creatives), n(a.new_creatives),
             diff_num(m.new_creatives, a.new_creatives), wins(m.new_creatives, a.new_creatives)),
            ("카피 앵글 종류", n(len(m.copy_angles)), n(len(a.copy_angles)),
             diff_num(len(m.copy_angles), len(a.copy_angles)), wins(len(m.copy_angles), len(a.copy_angles))),
            # 지출·매출·구매는 규모가 다르면 머릿수 비교가 무의미하다. 효율 지표로만 승패를 가린다.
            ("지출", n(m.spend), n(a.spend), diff_num(m.spend, a.spend), None),
            ("― 효율", "", "", "", None),
            ("ROAS", f"{m.roas:.2f}", f"{a.roas:.2f}", f"{m.roas - a.roas:+.2f}", wins(m.roas, a.roas)),
            ("매출", n(m.revenue), n(a.revenue), diff_num(m.revenue, a.revenue), None),
            ("구매", n(m.purchases), n(a.purchases), diff_num(m.purchases, a.purchases), None),
            ("CPA", n(m.cpa) if m.cpa else "—", n(a.cpa) if a.cpa else "—",
             diff_num(m.cpa, a.cpa) if (m.cpa and a.cpa) else "—",
             wins(m.cpa, a.cpa, lower_is_better=True) if (m.cpa and a.cpa) else None),
            ("― 학습", "", "", "", None),
            ("판정 가능 비율", f"{m.judgeable_rate:.0%}", f"{a.judgeable_rate:.0%}",
             f"{(m.judgeable_rate - a.judgeable_rate) * 100:+.0f}%p",
             wins(round(m.judgeable_rate, 2), round(a.judgeable_rate, 2))),
            ("광고당 지출", n(m.spend_per_ad), n(a.spend_per_ad),
             diff_num(m.spend_per_ad, a.spend_per_ad), None),
            ("확장 소재", n(m.winners), n(a.winners), diff_num(m.winners, a.winners), wins(m.winners, a.winners)),
        ]

    def verdict(self) -> tuple[bool, bool, list[str]]:
        """(물량에서 이기는가, 효율에서 이기는가, 코멘트)

        물량 기준은 신규 소재 수다. 총 광고 수는 과거에 쌓인 것까지 세므로
        '이번 기간에 얼마나 찍어냈는가' 를 반영하지 못한다. 다만 광고명을 못 읽어
        신규 소재를 셀 수 없을 때는 광고 수로 대신한다.
        """
        m, a = self.mine, self.agency
        # 신규 소재를 셀 수 없으면(광고명 파싱 실패, 기간 정보 없음) 광고 수로 대신 판단한다.
        # 둘 다 0 인 것을 '동률' 로 읽으면 지고 있는데 이긴다고 나온다.
        if m.new_creatives or a.new_creatives:
            vol = m.new_creatives > a.new_creatives
            vol_basis = "신규 소재"
        else:
            vol = m.ads > a.ads
            vol_basis = "광고 수"
        eff = m.roas > a.roas
        notes: list[str] = []
        if not (m.new_creatives or a.new_creatives):
            notes.append(
                "신규 소재 수를 세지 못했습니다 (광고명이 네이밍 규칙과 맞지 않거나 "
                "조회 기간 정보가 없습니다). 물량은 광고 수로만 비교했습니다. "
                "`roasloop names` 로 확인하세요."
            )

        if eff and vol:
            notes.append("물량과 효율 둘 다 앞서 있습니다. 지출을 늘려 격차를 벌릴 구간입니다.")
        elif eff and not vol:
            gap = (f"신규 소재 {m.new_creatives} vs {a.new_creatives}" if vol_basis == "신규 소재"
                   else f"광고 {m.ads}개 vs {a.ads}개")
            notes.append(
                f"효율은 앞서는데 물량이 부족합니다 ({gap}). "
                "지금 효율을 유지한 채 발행량을 올리는 것이 가장 확실한 수입니다."
            )
        elif vol and not eff:
            notes.append(
                "물량은 앞서는데 효율이 뒤집니다. 소재를 더 찍는 것보다 "
                "지고 있는 축을 찾아 빼는 것이 먼저입니다."
            )
        else:
            notes.append("물량과 효율 둘 다 뒤집니다. 먼저 효율 한 축을 골라 좁게 이기는 편이 낫습니다.")

        if m.judgeable_rate < 0.5 and m.ads >= 10:
            notes.append(
                f"내 광고의 {1 - m.judgeable_rate:.0%} 가 판정선에 못 미칩니다 "
                f"(광고당 {m.spend_per_ad:,.0f}). 무엇이 좋았는지 알 수 없는 상태라 "
                "다음 라운드가 나아지지 않습니다. 소재 수를 줄이고 광고당 예산을 올리세요."
            )
        if a.spend > m.spend * 2 and a.ads > m.ads:
            notes.append(
                f"대행사가 {a.spend / max(m.spend, 1):.1f}배를 쓰고 있습니다. "
                "그 지출로 검증된 승자 축은 `roasloop dna --by-owner` 로 공짜로 가져올 수 있습니다."
            )
        return vol, eff, notes


def build(
    judgements: list[Judgement],
    ownership,
    window: tuple[date, date] | None = None,
    period: str = "",
) -> Scoreboard:
    groups = ownership.split(judgements, key=lambda j: j.perf.campaign_name, for_report=True)
    sides = {}
    for owner, label in ((Owner.MINE, "인하우스"), (Owner.AGENCY, "대행사")):
        side = Side(label=ownership.labels.get(owner, label))
        for j in groups[owner]:
            p = j.perf
            side.ads += 1
            side.spend += p.spend
            side.revenue += p.revenue
            side.purchases += p.purchases
            side.impressions += p.impressions
            side.clicks += p.clicks
            if j.verdict == Verdict.SCALE:
                side.winners += 1
            elif j.verdict == Verdict.KILL:
                side.losers += 1
            if j.verdict != Verdict.INSUFFICIENT:
                side.judgeable += 1
            try:
                ad = AdName.parse(p.ad_name)
            except NamingError:
                continue
            side.copy_angles.add(ad.copy)
            if window and _within(ad.live_date, window):
                side.new_creatives += 1
        sides[owner] = side
    return Scoreboard(mine=sides[Owner.MINE], agency=sides[Owner.AGENCY], period=period)


def _within(live_date: str, window: tuple[date, date]) -> bool:
    """광고명의 라이브 일자(YYMMDD)가 조회 기간 안인가."""
    try:
        d = date(2000 + int(live_date[:2]), int(live_date[2:4]), int(live_date[4:6]))
    except (ValueError, IndexError):
        return False
    return window[0] <= d <= window[1]
