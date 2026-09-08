from urllib.parse import parse_qs, urlsplit

from roasloop.briefs import sanitize_code
from roasloop.utm import macro_url_tags, static_url

CFG = {"source": "meta", "medium": "paid_social"}


def test_macro_string_shape():
    tags = macro_url_tags(CFG)
    assert tags.startswith("utm_source=meta&utm_medium=paid_social")
    for macro in ("{{campaign.name}}", "{{adset.name}}", "{{ad.name}}"):
        assert macro in tags


def test_medium_is_paid_social_not_da():
    """DA 는 GA4 유료 판정 정규식에 안 걸려 Unassigned 로 떨어진다."""
    assert "utm_medium=paid_social" in macro_url_tags(CFG)


def test_static_url_encodes_korean_copy():
    url = static_url("https://returnity.global/products/yulmu-skinclean-mask", CFG,
                     "E_US_Meta_DA_SPF_EN_Yulmu_Conversion_ASC",
                     "Demo.180d_F2534_Purchase",
                     "26Regular_YulmuMask_Video_사우나필수템_공병템_SPF.YulmuMask.PDP_260730")
    q = parse_qs(urlsplit(url).query)
    assert q["utm_term"][0].endswith("_260730")
    assert "사우나필수템" in q["utm_term"][0]     # 디코딩하면 원문이 돌아온다
    assert "%EC%82%AC" in url                    # 실제 URL 은 인코딩되어 있다


def test_static_url_preserves_existing_query():
    url = static_url("https://returnity.global/products/x?variant=42", CFG, "c", "a", "d")
    q = parse_qs(urlsplit(url).query)
    assert q["variant"] == ["42"] and q["utm_campaign"] == ["c"]


def test_sanitize_code_makes_naming_safe():
    from roasloop.naming import AdName
    for raw in ["사우나 필수템", "sauna_staple", "a/b^c", "  공백  "]:
        code = sanitize_code(raw)
        AdName("26Regular", "YulmuMask", "Video", code, "오브제",
               "SPF.YulmuMask.PDP", "260901").validate(
            {"promo": ["26Regular"], "product": ["YulmuMask"], "creative_type": ["Video"]})
