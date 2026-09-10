"""유지(KEEP) 중인 소재에서 확장 후보 발굴."""

import pytest

from roasloop import grow
from roasloop.judge import AdPerformance, Verdict, judge_all


def ad(ad_id: str, roas: float, purchases: int, freq: float = 1.5,
       status: str = "ACTIVE", spend: float = 300_000) -> AdPerformance:
    return AdPerformance(
        ad_id=ad_id,
        ad_name=f"YulmuMask_KR_Video_NoOffer_앵글{ad_id}_오브제_SPF.YulmuMask.PDP_260901",
        campaign_name="IH_US_Yulmu", adset_name="Demo.Broad_F2554_Purchase",
        spend=spend, revenue=spend * roas, purchases=purchases,
        impressions=int(spend / 9), clicks=int(spend / 600),
        frequency=freq, days_active=14, status=status,
    )


def candidates(rows, rules, **kw):
    return grow.build(judge_all(rows, rules), rules, **kw)


# ------------------------------------------------- 필요 표본 역산
def test_needed_purchases_grows_as_margin_shrinks():
    """확장선에 가까울수록 증명에 필요한 표본이 폭증한다."""
    wide = grow.purchases_needed_for_scale(4.0, 5, 2.5, 0.80)
    narrow = grow.purchases_needed_for_scale(2.6, 5, 2.5, 0.80)
    assert wide is not None and narrow is not None
    assert narrow > wide * 5


def test_below_scale_line_can_never_be_proven():
    assert grow.purchases_needed_for_scale(2.0, 10, 2.5, 0.80) is None


def test_needed_purchases_never_below_current():
    n = grow.purchases_needed_for_scale(5.0, 3, 2.5, 0.80)
    assert n is not None and n >= 3


# ------------------------------------------------- 후보 선별
def test_below_target_is_never_a_candidate(rules):
    """빈도가 낮아도 목표 미달이면 '키울 소재' 가 아니다."""
    rows = [ad("low", roas=1.2, purchases=8, freq=1.2)]
    assert candidates(rows, rules) == []


def test_above_target_with_headroom_is_a_candidate(rules):
    rows = [ad("good", roas=2.3, purchases=14, freq=1.4)]
    out = candidates(rows, rules)
    assert len(out) == 1
    assert any("목표 위" in r for r in out[0].reasons)
    assert any("도달을 더 늘릴 여유" in r for r in out[0].reasons)


def test_saturated_frequency_is_a_blocker(rules):
    rows = [ad("hot", roas=2.3, purchases=14, freq=4.0)]
    out = candidates(rows, rules)
    assert out == [] or any("반복 노출" in b for b in out[0].blockers)


def test_paused_ads_are_excluded_by_default(rules):
    rows = [ad("off", roas=2.4, purchases=14, status="PAUSED")]
    assert candidates(rows, rules) == []
    assert len(candidates(rows, rules, live_only=False)) == 1


def test_adset_paused_counts_as_not_live(rules):
    rows = [ad("parent_off", roas=2.4, purchases=14, status="ADSET_PAUSED")]
    assert candidates(rows, rules) == []


def test_unknown_status_is_treated_as_live(rules):
    """상태를 못 가져온 계정에서 후보가 통째로 비면 안 된다."""
    rows = [ad("unknown", roas=2.4, purchases=14, status="")]
    assert len(candidates(rows, rules)) == 1


def test_only_keep_verdicts_are_considered(rules):
    """확장 판정이 이미 난 소재와 중단 대상은 여기 나오지 않는다."""
    rows = [
        ad("winner", roas=5.0, purchases=30, spend=300_000),
        ad("loser", roas=0.4, purchases=6, spend=900_000),
        ad("keep", roas=2.2, purchases=13),
    ]
    js = judge_all(rows, rules)
    assert {j.perf.ad_id: j.verdict for j in js}["winner"] == Verdict.SCALE
    assert [c.perf.ad_id for c in grow.build(js, rules)] == ["keep"]


def test_extra_spend_is_hidden_when_unrealistic(rules):
    """확장선에 아슬아슬하면 필요한 지출이 폭증한다. 집행할 수 없는 숫자는 감춘다."""
    rows = [ad("tight", roas=2.55, purchases=12, spend=300_000)]
    out = candidates(rows, rules)
    assert out
    c = out[0]
    assert c.extra_spend_to_prove is None
    assert "너무 가까워" in c.prove_note


def test_below_scale_line_says_so_plainly(rules):
    """확장선 아래는 '비현실적' 이 아니라 '원리상 불가' 다. 조언이 달라진다."""
    rows = [ad("under", roas=2.2, purchases=13)]
    out = candidates(rows, rules)
    assert out and "확장선(2.5) 아래" in out[0].prove_note


def test_reachable_extra_spend_is_shown(rules):
    """확장선을 넉넉히 넘지만 표본이 적어 아직 KEEP 인 소재 — 얼마 더 태우면 되는지 나와야 한다."""
    rows = [ad("promising", roas=3.6, purchases=6, spend=90_000)]
    out = candidates(rows, rules)
    assert out, "KEEP 판정이어야 후보로 잡힌다"
    assert out[0].extra_spend_to_prove is not None
    assert out[0].extra_spend_to_prove > 0


def test_ranking_puts_stronger_evidence_first(rules):
    rows = [
        ad("weak", roas=1.9, purchases=9, freq=2.5),
        ad("strong", roas=2.4, purchases=16, freq=1.3),
    ]
    out = candidates(rows, rules)
    assert out[0].perf.ad_id == "strong"


def test_zero_purchase_ads_are_skipped(rules):
    rows = [ad("nosale", roas=0.0, purchases=0)]
    assert candidates(rows, rules) == []
