from datetime import date

import pytest

from roasloop.matrix import AdSpec, asset_key, expand, load_history


BASE = {
    "round": "T1",
    "defaults": {"country": "US", "language": "EN", "product_line": "Yulmu",
                 "objective": "Conversion", "ad_product": "bau"},
    "creatives": {
        "promo": "26Regular", "product": "YulmuMask", "landing_id": "SPF.YulmuMask.PDP",
        "creative_type": ["Video", "Image"],
        "copy": ["앵글A", "앵글B"],
        "object": ["오브제1"],
    },
    "adsets": [{"target": "Demo", "target_detail": "Broad", "gender_age": "F2554",
                "opt_event": "Purchase"}],
}


def test_expands_cartesian_product(cfg):
    plan = expand(BASE, cfg, live_date=date(2026, 9, 1))
    assert len(plan.specs) == 2 * 2 * 1 * 1     # 유형 × 카피 × 오브제 × 광고셋


def test_multiple_adsets_multiply(cfg):
    m = {**BASE, "adsets": BASE["adsets"] + [
        {"target": "Re", "target_detail": "180d", "gender_age": "F2554", "opt_event": "Purchase"}]}
    plan = expand(m, cfg, live_date=date(2026, 9, 1))
    assert len(plan.specs) == 8


def test_generated_names_are_parseable(cfg):
    from roasloop.naming import AdName
    plan = expand(BASE, cfg, live_date=date(2026, 9, 1))
    for spec in plan.specs:
        assert AdName.parse(spec.ad_name).live_date == "260901"


def test_history_blocks_repeat_combinations(cfg):
    plan = expand(BASE, cfg, live_date=date(2026, 9, 1))
    already = {plan.specs[0].ad_name}
    again = expand(BASE, cfg, live_date=date(2026, 9, 1), history=already)
    assert len(again.specs) == len(plan.specs) - 1
    assert again.skipped_duplicates == list(already)


def test_invalid_axis_value_is_collected_not_raised(cfg):
    m = {**BASE, "creatives": {**BASE["creatives"], "copy": ["앵글 A"]}}   # 공백 포함
    plan = expand(m, cfg, live_date=date(2026, 9, 1))
    assert plan.specs == []
    assert plan.invalid and "공백" in plan.invalid[0][1]


def test_ready_requires_both_asset_and_copy(cfg):
    m = {
        **BASE,
        "assets": {"앵글A|오브제1|Video": {"image_hash": "h1"}},
        "copy": {"앵글A": {"primary_text": "본문"}},
    }
    plan = expand(m, cfg, live_date=date(2026, 9, 1))
    ready = plan.ready
    assert len(ready) == 1
    assert ready[0].asset_key == "앵글A|오브제1|Video"
    assert all("소재파일" in s.missing or "카피" in s.missing for s in plan.pending)


def test_limit_caps_output(cfg):
    plan = expand(BASE, cfg, live_date=date(2026, 9, 1), limit=2)
    assert len(plan.specs) == 2


def test_missing_axis_raises(cfg):
    m = {**BASE, "creatives": {k: v for k, v in BASE["creatives"].items() if k != "copy"}}
    with pytest.raises(ValueError, match="copy"):
        expand(m, cfg, live_date=date(2026, 9, 1))


def test_no_adsets_raises(cfg):
    with pytest.raises(ValueError, match="adsets"):
        expand({**BASE, "adsets": []}, cfg, live_date=date(2026, 9, 1))


def test_url_tags_use_macros_when_enabled(cfg):
    plan = expand(BASE, cfg, live_date=date(2026, 9, 1))
    spec = plan.specs[0]
    assert "{{campaign.name}}" in spec.url_tags
    assert "utm_medium=paid_social" in spec.url_tags
    assert "utm_" not in spec.landing_url          # 매크로를 쓰면 URL 은 깨끗하게 둔다


def test_asset_key_order():
    assert asset_key({"copy": "A", "object": "B", "creative_type": "Video"}) == "A|B|Video"


def test_load_history_missing_file(tmp_path):
    assert load_history(tmp_path / "nope.txt") == set()
