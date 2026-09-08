import math

import pytest

from roasloop.stats import chi2_quantile, poisson_interval, roas_interval


def test_chi2_matches_known_values():
    # 자유도 2 는 정확해가 있다
    assert chi2_quantile(0.95, 2) == pytest.approx(5.991, abs=0.001)
    # 참고표 값과 1% 이내
    assert chi2_quantile(0.95, 10) == pytest.approx(18.307, rel=0.01)
    assert chi2_quantile(0.05, 10) == pytest.approx(3.940, rel=0.02)


def test_chi2_zero_df():
    assert chi2_quantile(0.5, 0) == 0.0


def test_poisson_interval_contains_observation():
    for k in (1, 3, 10, 50):
        lo, hi = poisson_interval(k, 0.80)
        assert lo < k < hi


def test_poisson_interval_narrows_with_more_data():
    lo3, hi3 = poisson_interval(3, 0.80)
    lo30, hi30 = poisson_interval(30, 0.80)
    assert (hi3 - lo3) / 3 > (hi30 - lo30) / 30


def test_zero_purchases_has_zero_lower_bound():
    lo, hi = poisson_interval(0, 0.80)
    assert lo == 0.0 and hi > 0


def test_same_roas_different_sample_sizes():
    """같은 ROAS 라도 표본이 작으면 구간이 넓어야 한다. 이게 이 프로젝트의 핵심 전제다."""
    small = roas_interval(150_000, 210_000, 3)
    large = roas_interval(1_000_000, 1_400_000, 20)
    assert small.point == pytest.approx(large.point, abs=0.01)
    assert (small.upper - small.lower) > (large.upper - large.lower)
    # 표본이 작으면 목표선(2.0)을 배제할 수 없다
    assert small.upper > 2.0
    assert large.upper < 2.0


def test_zero_purchase_uses_fallback_aov():
    iv = roas_interval(120_000, 0, 0, fallback_aov=55_000)
    assert iv.point == 0.0
    assert iv.lower == 0.0
    assert 0 < iv.upper < 2.0        # 12만원 쓰고 0건이면 목표 미달이 거의 확실
    assert iv.aov == 55_000


def test_zero_spend_is_not_a_division_error():
    iv = roas_interval(0, 0, 0)
    assert iv.point == 0.0 and math.isinf(iv.upper)


def test_higher_confidence_widens_interval():
    narrow = roas_interval(500_000, 1_000_000, 10, level=0.80)
    wide = roas_interval(500_000, 1_000_000, 10, level=0.95)
    assert wide.lower < narrow.lower
    assert wide.upper > narrow.upper
