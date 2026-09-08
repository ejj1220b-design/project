"""UTM 생성.

두 가지 방식을 지원한다.

1. 동적 매크로 (권장, ``use_dynamic_macros: true``)
   Meta 광고의 [URL 파라미터] 칸에 매크로 한 줄을 넣어두면 Meta 가 캠페인·광고셋·광고
   이름을 자동으로 채우고 URL 인코딩까지 한다. 이름을 바꿔도 URL 을 다시 만들 필요가 없다.

2. 정적 URL
   검수·미리보기용, 그리고 매크로를 못 쓰는 채널용으로 완성된 URL 을 만들어 둔다.
"""

from __future__ import annotations

from urllib.parse import quote, urlencode, urlsplit, urlunsplit

MACRO_TEMPLATE = (
    "utm_source={source}&utm_medium={medium}"
    "&utm_campaign={{{{campaign.name}}}}"
    "&utm_content={{{{adset.name}}}}"
    "&utm_term={{{{ad.name}}}}"
)


def macro_url_tags(utm_cfg: dict) -> str:
    """Meta [URL 파라미터] 칸 / adcreative 의 ``url_tags`` 에 넣을 한 줄."""
    return MACRO_TEMPLATE.format(
        source=utm_cfg.get("source", "meta"),
        medium=utm_cfg.get("medium", "paid_social"),
    )


def static_url(base_url: str, utm_cfg: dict, campaign: str, adset: str, ad: str) -> str:
    """UTM 이 붙은 완성 URL. 한글 카피는 여기서 percent-encoding 된다."""
    params = {
        "utm_source": utm_cfg.get("source", "meta"),
        "utm_medium": utm_cfg.get("medium", "paid_social"),
        "utm_campaign": campaign,
        "utm_content": adset,
        "utm_term": ad,
    }
    parts = urlsplit(base_url)
    query = urlencode(params, quote_via=quote, safe="")
    merged = f"{parts.query}&{query}" if parts.query else query
    return urlunsplit((parts.scheme, parts.netloc, parts.path, merged, parts.fragment))
