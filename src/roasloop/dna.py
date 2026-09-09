"""승자 DNA 추출.

"ROAS 높은 것만 남긴다" 로 끝나면 다음 라운드에 쓸 게 없다. 남은 승자에서
'무엇이 이겼는지' 를 뽑아야 그걸로 다시 대량 생산할 수 있다.

방법
    광고명을 역파싱해 축(카피 앵글 / 오브제 / 소재유형 / 상품 / 프로모션)별로 성과를 합친다.
    개별 광고가 아니라 축의 값 단위로 합치기 때문에 표본이 커지고, 판정도 훨씬 안정적이다.

    예) 카피 앵글 '사우나필수템' 이 8개 광고에 걸쳐 지출 240만 · 매출 720만
        → 이 앵글의 ROAS 3.0 은 광고 한 개짜리 ROAS 3.0 보다 훨씬 믿을 만하다.

주의 — 축은 서로 독립이 아니다.
    '사우나필수템' 앵글이 전부 Video 로만 만들어졌다면, 이 앵글의 성적은 Video 의 성적이기도 하다.
    그래서 각 값이 몇 개의 서로 다른 소재유형/오브제에 걸쳐 있는지(coverage)를 같이 보여준다.
    coverage 가 1이면 "이 값이 이긴 게 아니라 같이 묶인 다른 축이 이긴 것" 일 수 있다.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .judge import AdPerformance, Judgement, Verdict
from .naming import AdName, NamingError
from .stats import RoasInterval, roas_interval

#: DNA 로 볼 축
DNA_AXES = ("copy", "object", "creative_type", "product", "promo")


@dataclass
class AxisLevel:
    """축 하나의 값 하나. 예: copy='사우나필수템'"""

    axis: str
    value: str
    ads: int = 0
    spend: float = 0.0
    revenue: float = 0.0
    purchases: int = 0
    impressions: int = 0
    clicks: int = 0
    winners: int = 0
    losers: int = 0
    coverage: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    #: 전체 데이터에서 각 축이 가진 값의 개수. 값이 1개뿐인 축은 상수이지 교란이 아니다.
    global_cardinality: dict[str, int] = field(default_factory=dict)
    interval: RoasInterval | None = None

    @property
    def roas(self) -> float:
        return self.revenue / self.spend if self.spend else 0.0

    @property
    def confounded(self) -> list[str]:
        """이 값과 항상 붙어 다니는 다른 축 — 단독 효과로 읽으면 안 된다.

        전체 데이터에서 값이 하나뿐인 축(예: 이번 라운드가 전부 같은 상품)은 제외한다.
        그건 교란이 아니라 그냥 상수다.
        """
        return [
            axis for axis, vals in self.coverage.items()
            if len(vals) <= 1 and self.global_cardinality.get(axis, 0) > 1
        ]


@dataclass
class DnaReport:
    axes: dict[str, list[AxisLevel]] = field(default_factory=dict)
    unparsed: list[str] = field(default_factory=list)
    total_spend: float = 0.0
    total_revenue: float = 0.0

    @property
    def baseline_roas(self) -> float:
        return self.total_revenue / self.total_spend if self.total_spend else 0.0

    def top(self, axis: str, n: int = 3, min_spend: float = 0.0, min_ads: int = 1) -> list[AxisLevel]:
        """축별 상위 값. 신뢰구간 하단으로 줄을 세운다 — 관측 ROAS 로 세우면 표본 작은 게 위로 온다."""
        rows = [
            lv for lv in self.axes.get(axis, [])
            if lv.spend >= min_spend and lv.ads >= min_ads
        ]
        rows.sort(key=lambda lv: (lv.interval.lower if lv.interval else 0.0, lv.spend), reverse=True)
        return rows[:n]

    def winning_levels(
        self, min_spend: float = 0.0, min_ads: int = 2, n_per_axis: int = 3
    ) -> dict[str, list[str]]:
        """다음 라운드 축으로 바로 넣을 수 있는 형태."""
        return {
            axis: [lv.value for lv in self.top(axis, n_per_axis, min_spend, min_ads)]
            for axis in DNA_AXES
            if self.axes.get(axis)
        }


def build(
    judgements: list[Judgement],
    level: float = 0.80,
    fallback_aov: float = 0.0,
) -> DnaReport:
    """판정 결과 전체에서 축별 성과를 집계한다.

    KILL 된 광고도 포함한다. "무엇이 졌는지" 도 DNA 다 — 진 축을 다음 라운드에서
    빼는 것이 이긴 축을 넣는 것만큼 중요하다.
    """
    report = DnaReport()
    buckets: dict[tuple[str, str], AxisLevel] = {}

    for j in judgements:
        perf: AdPerformance = j.perf
        try:
            ad = AdName.parse(perf.ad_name)
        except NamingError:
            report.unparsed.append(perf.ad_name)
            continue

        report.total_spend += perf.spend
        report.total_revenue += perf.revenue
        dna = ad.dna()

        for axis in DNA_AXES:
            value = dna.get(axis, "")
            if not value:
                continue
            key = (axis, value)
            lv = buckets.get(key)
            if lv is None:
                lv = buckets[key] = AxisLevel(axis=axis, value=value)
            lv.ads += 1
            lv.spend += perf.spend
            lv.revenue += perf.revenue
            lv.purchases += perf.purchases
            lv.impressions += perf.impressions
            lv.clicks += perf.clicks
            if j.verdict == Verdict.SCALE:
                lv.winners += 1
            elif j.verdict == Verdict.KILL:
                lv.losers += 1
            # 이 값이 다른 축의 몇 가지 값과 짝지어졌는지 기록 (교란 판별용)
            for other in DNA_AXES:
                if other != axis and dna.get(other):
                    lv.coverage[other].add(dna[other])

    cardinality = {
        axis: len({value for a, value in buckets if a == axis}) for axis in DNA_AXES
    }
    for lv in buckets.values():
        lv.global_cardinality = cardinality
        lv.interval = roas_interval(lv.spend, lv.revenue, lv.purchases, level, fallback_aov)

    grouped: dict[str, list[AxisLevel]] = defaultdict(list)
    for lv in buckets.values():
        grouped[lv.axis].append(lv)
    report.axes = dict(grouped)
    return report


def next_round_axes(
    report: DnaReport,
    keep_top: int = 2,
    min_spend: float = 0.0,
    min_ads: int = 2,
    baseline_margin: float = 0.0,
) -> dict[str, list[str]]:
    """다음 라운드 matrix.yaml 의 creatives 축으로 넣을 값.

    baseline_margin: 계정 평균 ROAS 보다 이만큼 위인 값만 남긴다. 0 이면 순위만 본다.
    """
    floor = report.baseline_roas + baseline_margin
    out: dict[str, list[str]] = {}
    for axis in DNA_AXES:
        rows = report.top(axis, n=keep_top, min_spend=min_spend, min_ads=min_ads)
        picked = [lv.value for lv in rows if lv.roas >= floor] or [lv.value for lv in rows[:1]]
        if picked:
            out[axis] = picked
    return out


# --------------------------------------------------------- 소유별 비교 · 정보 수집
@dataclass
class Steal:
    """대행사가 지출로 검증했는데 내가 아직 안 쓴 축의 값.

    대행사가 쓴 돈은 이미 나갔다. 거기서 나온 학습은 가져오는 것이 맞다.
    """

    axis: str
    value: str
    their_roas: float
    their_lower: float
    their_spend: float
    their_ads: int
    confounded: list[str]


@dataclass
class OwnerSplit:
    mine: DnaReport
    agency: DnaReport
    steals: list[Steal]
    my_edge: list[Steal]      # 내가 이겼고 대행사는 안 쓰는 축


def _levels(report: DnaReport, axis: str) -> dict[str, AxisLevel]:
    return {lv.value: lv for lv in report.axes.get(axis, [])}


def compare_owners(
    judgements: list[Judgement],
    ownership,
    level: float = 0.80,
    fallback_aov: float = 0.0,
    min_ads: int = 2,
    min_lower: float | None = None,
) -> OwnerSplit:
    """소유별로 DNA 를 따로 뽑고, 한쪽만 검증한 승자를 찾아낸다.

    '가져올 가치가 있는가' 의 기준은 상대의 자기 평균이 아니라 **받는 쪽의 평균**이다.
    대행사 안에서 몇 등인지는 나와 상관이 없다. 내가 지금 얻는 것보다 확실히 나아야
    가져올 이유가 생긴다. min_lower 를 주면 그 위에 하한선을 하나 더 건다
    (보통 목표 ROAS — 나보다 나아도 목표에 못 미치면 가져올 이유가 없다).
    """
    from .ownership import Owner

    groups = ownership.split(judgements, key=lambda j: j.perf.campaign_name, for_report=True)
    mine = build(groups[Owner.MINE], level, fallback_aov)
    agency = build(groups[Owner.AGENCY], level, fallback_aov)

    def _find(source: DnaReport, other: DnaReport) -> list[Steal]:
        bar = max(other.baseline_roas, min_lower or 0.0)
        found: list[Steal] = []
        for axis in DNA_AXES:
            theirs = _levels(source, axis)
            ours = _levels(other, axis)
            for value, lv in theirs.items():
                if lv.ads < min_ads or lv.interval is None:
                    continue
                if lv.interval.lower < bar:
                    continue
                mine_lv = ours.get(value)
                # 내가 아예 안 썼거나, 썼어도 표본이 없어 판단이 안 되는 경우
                if mine_lv is not None and mine_lv.ads >= min_ads:
                    continue
                found.append(Steal(
                    axis=axis, value=value,
                    their_roas=lv.roas, their_lower=lv.interval.lower,
                    their_spend=lv.spend, their_ads=lv.ads, confounded=lv.confounded,
                ))
        found.sort(key=lambda s: -s.their_lower)
        return found

    return OwnerSplit(
        mine=mine, agency=agency,
        steals=_find(agency, mine),
        my_edge=_find(mine, agency),
    )
