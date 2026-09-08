import pytest

from roasloop import dna
from roasloop.judge import AdPerformance, judge_all


def make(copy, obj, ctype, spend, revenue, purchases, ad_id="x"):
    return AdPerformance(
        ad_id=ad_id,
        ad_name=f"26Regular_YulmuMask_{ctype}_{copy}_{obj}_SPF.YulmuMask.PDP_260901",
        spend=spend, revenue=revenue, purchases=purchases,
        impressions=60_000, clicks=900, frequency=1.6, days_active=9,
    )


@pytest.fixture
def report(rules):
    rows = [
        make("승자앵글", "공병템", "Video", 300_000, 900_000, 16, "1"),
        make("승자앵글", "손등테스트", "Video", 280_000, 820_000, 15, "2"),
        make("승자앵글", "공병템", "Image", 200_000, 540_000, 10, "3"),
        make("보통앵글", "공병템", "Video", 260_000, 390_000, 7, "4"),
        make("보통앵글", "손등테스트", "Image", 240_000, 260_000, 5, "5"),
        make("패자앵글", "공병템", "Image", 220_000, 180_000, 3, "6"),
        make("패자앵글", "손등테스트", "Video", 210_000, 150_000, 3, "7"),
    ]
    return dna.build(judge_all(rows, rules), level=0.80, fallback_aov=55_000)


def test_axis_totals_match_source(report):
    winner = next(lv for lv in report.axes["copy"] if lv.value == "승자앵글")
    assert winner.ads == 3
    assert winner.spend == 780_000
    assert winner.revenue == 2_260_000


def test_ranking_finds_the_winning_angle(report):
    assert report.top("copy", n=1)[0].value == "승자앵글"
    assert report.top("copy", n=3)[-1].value == "패자앵글"


def test_aggregate_interval_is_tighter_than_single_ad(report):
    """축 단위로 합치면 표본이 커져 구간이 좁아진다. DNA 분석이 개별 판정보다 믿을 만한 이유."""
    winner = next(lv for lv in report.axes["copy"] if lv.value == "승자앵글")
    from roasloop.stats import roas_interval
    single = roas_interval(300_000, 900_000, 16, 0.80, 55_000)
    agg_width = (winner.interval.upper - winner.interval.lower) / winner.interval.point
    single_width = (single.upper - single.lower) / single.point
    assert agg_width < single_width


def test_constant_axis_is_not_flagged_as_confounder(report):
    """상품이 한 종류뿐인 라운드에서 '상품이 교란이다' 라고 하면 안 된다."""
    winner = next(lv for lv in report.axes["copy"] if lv.value == "승자앵글")
    assert "product" not in winner.confounded
    assert "promo" not in winner.confounded


def test_真_confounder_is_flagged(rules):
    """한 앵글이 오직 Video 로만 만들어졌다면 소재유형이 교란으로 잡혀야 한다."""
    rows = [
        make("비디오전용", "공병템", "Video", 300_000, 900_000, 16, "1"),
        make("비디오전용", "손등테스트", "Video", 280_000, 820_000, 15, "2"),
        make("혼합앵글", "공병템", "Image", 260_000, 390_000, 7, "3"),
        make("혼합앵글", "공병템", "Video", 240_000, 300_000, 6, "4"),
    ]
    r = dna.build(judge_all(rows, rules), 0.80, 55_000)
    only_video = next(lv for lv in r.axes["copy"] if lv.value == "비디오전용")
    mixed = next(lv for lv in r.axes["copy"] if lv.value == "혼합앵글")
    assert "creative_type" in only_video.confounded
    assert "creative_type" not in mixed.confounded


def test_unparseable_names_are_collected_not_crashed(rules):
    rows = [make("앵글", "오브제", "Video", 100_000, 200_000, 4, "1"),
            AdPerformance(ad_id="2", ad_name="구형 광고 이름", spend=50_000, revenue=10_000,
                          purchases=1, impressions=5_000, clicks=100, days_active=7)]
    r = dna.build(judge_all(rows, rules), 0.80, 55_000)
    assert r.unparsed == ["구형 광고 이름"]
    assert r.total_spend == 100_000        # 파싱 실패분은 집계에서 빠진다


def test_next_round_axes_shape(report):
    axes = dna.next_round_axes(report, keep_top=2, min_ads=2)
    assert axes["copy"][0] == "승자앵글"
    assert all(isinstance(v, list) and v for v in axes.values())


def test_min_ads_filters_thin_levels(report):
    assert report.top("copy", n=5, min_ads=3) == [
        lv for lv in report.top("copy", n=5) if lv.ads >= 3
    ]
