import pytest

from roasloop.naming import AdName, AdsetName, CampaignName, NamingError, parse_triplet


def test_campaign_roundtrip():
    c = CampaignName("US", "Meta", "DA", "SPF", "EN", "Yulmu", "Conversion", "ASC", "American")
    assert c.render() == "E_US_Meta_DA_SPF_EN_Yulmu_Conversion_ASC^American"
    assert CampaignName.parse(c.render()) == c


def test_campaign_roundtrip_without_note():
    c = CampaignName("CA", "Google", "SA", "AMZ", "KR", "SkinHealer", "Traffic", "bau")
    assert "^" not in c.render()
    assert CampaignName.parse(c.render()) == c


def test_adset_roundtrip_keeps_dot_syntax():
    s = AdsetName("Demo", "180d", "F2534", "Purchase", "American")
    assert s.render() == "Demo.180d_F2534_Purchase^American"
    assert AdsetName.parse(s.render()) == s


def test_ad_roundtrip_with_korean_free_fields():
    a = AdName("26Regular", "YulmuMask", "Video", "30대부터율무", "ai목소리",
               "SPF.YulmuMask.PDP", "260429", "CA")
    assert AdName.parse(a.render()) == a
    assert a.dna() == {
        "promo": "26Regular", "product": "YulmuMask", "creative_type": "Video",
        "copy": "30대부터율무", "object": "ai목소리",
    }


def test_landing_id_dots_do_not_split_slots():
    """랜딩ID 안의 점은 구분자가 아니다. 이게 깨지면 슬롯이 전부 밀린다."""
    a = AdName.parse("26Regular_YulmuMask_Video_카피_오브제_SPF.YulmuMask.PDP_260429")
    assert a.landing_id == "SPF.YulmuMask.PDP"
    assert a.live_date == "260429"


@pytest.mark.parametrize("bad_copy", ["사우나 필수템", "sauna_staple", "a^b", "a/b"])
def test_free_field_rejects_separators(cfg, bad_copy):
    a = AdName("26Regular", "YulmuMask", "Video", bad_copy, "공병템", "SPF.YulmuMask.PDP", "260429")
    with pytest.raises(NamingError):
        a.validate(cfg.taxonomy, cfg.landings)


def test_slot_count_mismatch_is_caught():
    with pytest.raises(NamingError, match="슬롯 수"):
        AdName.parse("26Regular_YulmuMask_Video_카피_SPF.YulmuMask.PDP_260429")


def test_enum_typo_suggests_correct_case(cfg):
    a = AdName("26Regular", "YulmuMask", "video", "카피", "오브제", "SPF.YulmuMask.PDP", "260429")
    with pytest.raises(NamingError, match="'Video'"):
        a.validate(cfg.taxonomy, cfg.landings)


def test_unknown_landing_id_is_caught(cfg):
    a = AdName("26Regular", "YulmuMask", "Video", "카피", "오브제", "SPF.Nope.PDP", "260429")
    with pytest.raises(NamingError, match="랜딩 마스터"):
        a.validate(cfg.taxonomy, cfg.landings)


def test_bad_live_date_is_caught(cfg):
    a = AdName("26Regular", "YulmuMask", "Video", "카피", "오브제", "SPF.YulmuMask.PDP", "2026-04-29")
    with pytest.raises(NamingError, match="YYMMDD"):
        a.validate(cfg.taxonomy, cfg.landings)


def test_parse_triplet_tolerates_legacy_names():
    """규칙 이전 광고가 섞여도 파이프라인이 멈추지 않아야 한다."""
    c, s, a = parse_triplet("구형 캠페인", "구형 광고셋", "구형 광고")
    assert (c, s, a) == (None, None, None)


def test_respin_changes_one_slot():
    a = AdName("26Regular", "YulmuMask", "Video", "카피A", "오브제", "SPF.YulmuMask.PDP", "260429")
    b = a.respin(copy="카피B", live_date="260901")
    assert b.copy == "카피B" and b.live_date == "260901"
    assert b.object == a.object
