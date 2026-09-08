import pytest

from roasloop.ownership import Owner, Ownership, OwnershipError

CFG = {
    "mine": [{"pattern": r"\^Inhouse$"}, {"name": "E_US_Meta_DA_SPF_EN_Yulmu_Conversion_bau"}],
    "agency": [{"pattern": r"\^Agency"}],
}


@pytest.fixture
def own() -> Ownership:
    return Ownership(CFG)


def test_pattern_match_is_mine(own):
    assert own.classify("E_US_Meta_DA_SPF_EN_Yulmu_Conversion_bau^Inhouse") is Owner.MINE


def test_exact_name_match_is_mine(own):
    assert own.classify("E_US_Meta_DA_SPF_EN_Yulmu_Conversion_bau") is Owner.MINE


def test_agency_pattern(own):
    assert own.classify("E_US_Meta_DA_SPF_EN_Yulmu_Conversion_ASC^Agency-루트") is Owner.AGENCY


def test_unmatched_is_unknown_not_mine(own):
    """모르는 캠페인을 내 것으로 넘기면 대행사 캠페인이 꺼진다. 반드시 unknown 이어야 한다."""
    assert own.classify("E_US_Meta_DA_SPF_EN_Yulmu_Conversion_ASC^American") is Owner.UNKNOWN


def test_agency_wins_when_both_match():
    """양쪽 규칙에 다 걸리면 안전한 쪽으로 판정한다."""
    o = Ownership({"mine": [{"pattern": "Yulmu"}], "agency": [{"pattern": "Yulmu"}]})
    assert o.classify("E_US_Meta_DA_SPF_EN_Yulmu_Conversion_ASC") is Owner.AGENCY


def test_empty_config_makes_everything_untouchable():
    """설정이 비어 있으면 아무것도 건드릴 수 없어야 한다."""
    o = Ownership({})
    assert o.classify("무슨 캠페인이든") is Owner.UNKNOWN
    with pytest.raises(OwnershipError):
        o.require_mine("무슨 캠페인이든")


def test_only_mine_is_actionable(own):
    assert Owner.MINE.actionable
    assert not Owner.AGENCY.actionable
    assert not Owner.UNKNOWN.actionable


def test_require_mine_passes_for_mine(own):
    own.require_mine("E_US_Meta_DA_SPF_EN_Yulmu_Conversion_bau^Inhouse")     # 예외 없음


def test_require_mine_blocks_agency_with_clear_message(own):
    with pytest.raises(OwnershipError, match="대행사 캠페인"):
        own.require_mine("E_US_Meta_DA_SPF_EN_Yulmu_Conversion_ASC^Agency-루트")


def test_require_mine_blocks_unknown_with_clear_message(own):
    with pytest.raises(OwnershipError, match="분류되지 않은"):
        own.require_mine("정체불명 캠페인")


def test_split_groups_by_owner(own):
    items = [("a", "X^Inhouse"), ("b", "Y^Agency"), ("c", "Z")]
    groups = own.split(items, key=lambda t: t[1])
    assert [i[0] for i in groups[Owner.MINE]] == ["a"]
    assert [i[0] for i in groups[Owner.AGENCY]] == ["b"]
    assert [i[0] for i in groups[Owner.UNKNOWN]] == ["c"]


def test_malformed_rule_raises_at_load():
    with pytest.raises(ValueError, match="name 도 pattern 도"):
        Ownership({"mine": [{"nope": 1}]})


def test_launcher_refuses_foreign_campaign(own):
    """launch 도 같은 잠금을 통과해야 한다. 남의 캠페인에 광고를 만드는 것도 사고다."""
    from roasloop.matrix import AdSpec
    from roasloop.meta.launch import Launcher

    spec = AdSpec(
        campaign_name="E_US_Meta_DA_SPF_EN_Yulmu_Conversion_ASC^Agency-루트",
        adset_name="Demo.Broad_F2554_Purchase", ad_name="광고",
        landing_url="https://x", url_tags="", image_hash="h", primary_text="본문",
    )
    launcher = Launcher(client=None, page_id="1", dry_run=True, ownership=own)
    result = launcher.launch([spec], {})
    assert result.created_ads == [] and result.planned == []
    assert "대행사 캠페인" in result.failures[0][1]
