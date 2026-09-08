"""insights 의 action_type 해석은 조용히 틀리기 쉬운 곳이라 따로 검증한다."""

from datetime import date

from roasloop.judge import AdPerformance
from roasloop.meta.insights import _pick, apply_true_age, default_window

TYPES = ["omni_purchase", "purchase", "offsite_conversion.fb_pixel_purchase"]


def test_pick_follows_priority_order():
    rows = [{"action_type": "purchase", "value": "100"},
            {"action_type": "omni_purchase", "value": "250"}]
    assert _pick(rows, TYPES) == 250.0        # 리스트 순서가 아니라 우선순위를 따른다


def test_pick_falls_through_to_next_type():
    rows = [{"action_type": "offsite_conversion.fb_pixel_purchase", "value": "77"},
            {"action_type": "link_click", "value": "9999"}]
    assert _pick(rows, TYPES) == 77.0


def test_pick_ignores_unrelated_actions():
    rows = [{"action_type": "landing_page_view", "value": "5000"},
            {"action_type": "add_to_cart", "value": "300"}]
    assert _pick(rows, TYPES) == 0.0


def test_pick_handles_missing_and_malformed():
    assert _pick(None, TYPES) == 0.0
    assert _pick([], TYPES) == 0.0
    assert _pick([{"action_type": "omni_purchase", "value": "N/A"}], TYPES) == 0.0
    assert _pick([{"action_type": "omni_purchase"}], TYPES) == 0.0


def test_true_age_overrides_query_window():
    """어제 만든 광고가 30일 조회에서 days_active=30 으로 잡히면 게이트를 부당 통과한다."""
    perfs = [AdPerformance(ad_id="a", ad_name="n", days_active=30),
             AdPerformance(ad_id="b", ad_name="n", days_active=30)]
    apply_true_age(perfs, {"a": 2})
    assert perfs[0].days_active == 2
    assert perfs[1].days_active == 30      # 조회 결과가 없으면 건드리지 않는다


def test_true_age_never_extends_window():
    perfs = [AdPerformance(ad_id="a", ad_name="n", days_active=7)]
    apply_true_age(perfs, {"a": 400})
    assert perfs[0].days_active == 7       # 조회 기간보다 길어질 수는 없다


def test_default_window_excludes_today():
    since, until = default_window(14)
    assert (until - since).days == 13
    assert until < date.today()            # 당일 데이터는 미확정이라 뺀다
