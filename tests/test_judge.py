import pytest

from roasloop.judge import AdPerformance, Verdict, judge_all, judge_one, summarize


def perf(**kw) -> AdPerformance:
    base = dict(ad_id="1", ad_name="26Regular_YulmuMask_Video_카피_오브제_SPF.YulmuMask.PDP_260901",
                spend=200_000, revenue=400_000, purchases=8, impressions=40_000,
                clicks=600, frequency=1.5, days_active=7)
    base.update(kw)
    return AdPerformance(**base)


def test_gates_hold_judgement_until_enough_data(rules):
    j = judge_one(perf(spend=20_000, impressions=1_000, days_active=1, purchases=0, revenue=0), rules)
    assert j.verdict == Verdict.INSUFFICIENT
    assert "판정 보류" in j.reason


def test_early_kill_fires_before_gates(rules):
    """게이트(노출·기간)를 못 넘겨도, 충분히 쓰고 구매 0이면 끈다."""
    j = judge_one(perf(spend=150_000, revenue=0, purchases=0, impressions=1_000, days_active=1), rules)
    assert j.verdict == Verdict.KILL
    assert "구매 0건" in j.reason


def test_early_kill_does_not_fire_below_threshold(rules):
    j = judge_one(perf(spend=100_000, revenue=0, purchases=0, impressions=40_000, days_active=7), rules)
    assert j.verdict == Verdict.KILL          # 게이트 통과 후 신뢰구간으로 KILL
    assert "상단" in j.reason                  # 조기 종료가 아닌 통계 판정


def test_kill_requires_confidence_not_just_low_roas(rules):
    """구매 3건 ROAS 1.4 는 끄지 않는다. 노이즈일 수 있다."""
    j = judge_one(perf(spend=150_000, revenue=210_000, purchases=3), rules)
    assert j.verdict == Verdict.KEEP
    assert j.interval.upper > 2.0


def test_kill_when_sample_is_large_enough(rules):
    """같은 ROAS 1.4 라도 표본이 충분히 쌓이면 목표 미달이 확실해진다."""
    j = judge_one(
        perf(spend=1_500_000, revenue=2_100_000, purchases=42, impressions=400_000, days_active=14),
        rules,
    )
    assert j.verdict == Verdict.KILL
    assert j.interval.upper < float(rules["targets"]["target_roas"])


def test_lowering_the_target_keeps_borderline_ads_alive(rules):
    """목표선을 내리면 애매한 구간의 소재가 살아남는다. 목표선 변경의 의미가 이것이다."""
    borderline = perf(spend=1_000_000, revenue=1_400_000, purchases=20,
                      impressions=300_000, days_active=14)      # 구간 1.02~1.89

    strict = {**rules, "targets": {**rules["targets"], "target_roas": 2.0}}
    lenient = {**rules, "targets": {**rules["targets"], "target_roas": 1.8}}

    assert judge_one(borderline, strict).verdict == Verdict.KILL
    assert judge_one(borderline, lenient).verdict == Verdict.KEEP


def test_scale_requires_lower_bound_above_scale_line(rules):
    j = judge_one(perf(spend=300_000, revenue=1_500_000, purchases=27, impressions=80_000, days_active=10), rules)
    assert j.verdict == Verdict.SCALE
    assert j.interval.lower >= 2.5


def test_warnings_do_not_change_verdict(rules):
    j = judge_one(perf(frequency=4.2, clicks=50), rules)
    assert j.warnings
    assert j.verdict in {Verdict.KEEP, Verdict.SCALE, Verdict.KILL}


def test_sort_puts_scale_first_and_kill_last(rules):
    rows = [
        perf(ad_id="kill", spend=1_500_000, revenue=2_100_000, purchases=42, impressions=400_000, days_active=14),
        perf(ad_id="scale", spend=300_000, revenue=1_500_000, purchases=27, impressions=80_000, days_active=10),
        perf(ad_id="young", spend=10_000, revenue=0, purchases=0, impressions=500, days_active=1),
    ]
    verdicts = [j.verdict for j in judge_all(rows, rules)]
    assert verdicts[0] == Verdict.SCALE
    assert verdicts[-1] == Verdict.KILL


def test_summary_totals_match_input(rules):
    rows = [perf(ad_id=str(i), spend=100_000, revenue=250_000, purchases=5) for i in range(4)]
    s = summarize(judge_all(rows, rules))
    assert sum(v["count"] for v in s.values()) == 4
    assert sum(v["spend"] for v in s.values()) == 400_000


def test_cpa_is_infinite_without_purchases():
    assert perf(purchases=0).cpa == float("inf")
