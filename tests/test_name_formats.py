"""계정에 실제로 쓰이는 광고명 형식 파싱.

여기 나오는 이름들은 리터니티 계정의 실제 광고명이다. 한 계정 안에 인하우스와
대행사가 서로 다른 형식을 쓰고 있고, 둘 다 읽어 같은 축으로 정규화해야 한다.
"""

import pytest

from roasloop.naming import AdName, NamingError

AGENCY = [
    "26Regular_YulmuMask_VID_눈가요요철조지는音_대표님_P.SPF_YulmuMask_260731",
    "26Regular_YulmuMask_IMG_비싸게살뻔_자사몰특가_P.SPF_YulmuMask_260731",
    "26Regular_BBRpack_GIF_BundleReview_IGStory_P.SPF_BBRpack_260814",
    "26SummerFlash_YulmuBBR_IMG_이미구매죄송_파격세일_P.SPF_YulmuBBR_260821",
]
INHOUSE = [
    "YulmuMask_KR_Video_Regular-SPFOFF_중년요철모공_피부확대_SPF.YulmuMask.PDP_260902",
    "YulmuMask_KR_GIF_Regular-SPFOFF_닭살피부부터요철_전후사진상품컷_SPF.YulmuMask.PDP_260902",
    "BBRMask_KR_adcode_NoOffer_잡티좋아질까요_흑자시연_SPF.BBRpack.PDP_260908",
    "YulmuMask_KR_Video_NoOffer_피부볼록요철템_율무씨텍스쳐_SPF.YulmuMask.PDP_260908",
]


@pytest.fixture
def parser(cfg):
    return cfg.parser


@pytest.mark.parametrize("name", AGENCY)
def test_agency_format_is_recognized(parser, name):
    assert AdName.parse(name, parser).format_name == "대행사"


@pytest.mark.parametrize("name", INHOUSE)
def test_inhouse_format_is_recognized(parser, name):
    assert AdName.parse(name, parser).format_name == "인하우스"


def test_agency_slots_land_in_the_right_places(parser):
    a = AdName.parse(AGENCY[0], parser)
    assert a.promo == "26Regular"
    assert a.product == "YulmuMask"
    assert a.creative_type == "Video"        # VID 를 정규화
    assert a.copy == "눈가요요철조지는音"
    assert a.object == "대표님"
    assert a.live_date == "260731"


def test_inhouse_slots_land_in_the_right_places(parser):
    a = AdName.parse(INHOUSE[0], parser)
    assert a.product == "YulmuMask"
    assert a.creative_type == "Video"
    assert a.promo == "Regular-SPFOFF"       # 인하우스는 이 칸이 오퍼다
    assert a.copy == "중년요철모공"
    assert a.object == "피부확대"
    assert a.landing_id == "SPF.YulmuMask.PDP"
    assert a.live_date == "260902"
    assert dict(a.extra)["language"] == "KR"


def test_creative_type_aliases_unify_the_two_conventions(parser):
    """VID 와 Video 가 다른 값으로 집계되면 승자 비교가 통째로 어긋난다."""
    agency = AdName.parse(AGENCY[0], parser)
    inhouse = AdName.parse(INHOUSE[0], parser)
    assert agency.creative_type == inhouse.creative_type == "Video"

    assert AdName.parse(AGENCY[1], parser).creative_type == "Image"


def test_product_alias_unifies_bbr(parser):
    """인하우스는 BBRMask, 대행사는 BBRpack 으로 쓰지만 같은 제품이다."""
    assert AdName.parse(INHOUSE[2], parser).product == "BBRpack"
    assert AdName.parse(AGENCY[2], parser).product == "BBRpack"


def test_both_formats_yield_the_same_dna_axes(parser):
    for name in AGENCY + INHOUSE:
        dna = AdName.parse(name, parser).dna()
        assert set(dna) == {"promo", "product", "creative_type", "copy", "object"}
        assert dna["copy"] and dna["object"] and dna["creative_type"]


def test_v1_names_still_parse(parser):
    """규칙 시트 원문(7칸)도 계속 읽어야 한다. 남아 있을 수 있다."""
    a = AdName.parse("26Regular_YulmuMask_Video_사우나필수템_공병템_SPF.YulmuMask.PDP_260730", parser)
    assert a.format_name == "v1.0"
    assert a.copy == "사우나필수템"


def test_unknown_shape_still_raises(parser):
    with pytest.raises(NamingError, match="어느 형식에도"):
        AdName.parse("[US] 율무팩 영상소재 A안", parser)


def test_ambiguity_is_resolved_by_validators(parser):
    """대행사와 인하우스 형식은 둘 다 8칸이다. 값 검사로 갈라야 한다."""
    agency = AdName.parse(AGENCY[3], parser)
    inhouse = AdName.parse(INHOUSE[3], parser)
    assert agency.format_name != inhouse.format_name
    assert agency.promo == "26SummerFlash"          # 대행사는 1번 칸이 프로모션
    assert inhouse.product == "YulmuMask"           # 인하우스는 1번 칸이 상품
