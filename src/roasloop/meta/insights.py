"""광고 단위 성과 수집.

Meta insights 응답에서 매출·구매수를 꺼내는 부분이 은근히 함정이다.
`actions` / `action_values` 는 action_type 이 여러 개 섞인 리스트이고, 계정 설정에
따라 `omni_purchase` 만 있거나 `offsite_conversion.fb_pixel_purchase` 만 있기도 하다.
그래서 config 의 우선순위 목록을 순서대로 훑어 첫 번째로 잡히는 것을 쓴다.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from ..judge import AdPerformance
from .client import MetaClient

INSIGHT_FIELDS = [
    "ad_id", "ad_name", "adset_name", "campaign_name",
    "spend", "impressions", "clicks", "frequency",
    "actions", "action_values",
]


def _pick(rows: list[dict] | None, action_types: list[str]) -> float:
    """우선순위대로 훑어 첫 번째로 잡히는 action_type 의 값."""
    if not rows:
        return 0.0
    index = {r.get("action_type"): r.get("value") for r in rows}
    for at in action_types:
        if at in index:
            try:
                return float(index[at])
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def fetch(
    client: MetaClient,
    since: date,
    until: date,
    action_types: list[str],
    attribution_windows: list[str] | None = None,
    campaign_filter: str | None = None,
    level: str = "ad",
) -> list[AdPerformance]:
    """기간 내 광고 단위 성과를 가져온다.

    campaign_filter 는 캠페인명 부분일치. 라운드별로 캠페인을 나눠 뒀다면
    그 캠페인만 골라 판정할 때 쓴다.
    """
    params: dict = {
        "level": level,
        "fields": ",".join(INSIGHT_FIELDS),
        "time_range": f'{{"since":"{since.isoformat()}","until":"{until.isoformat()}"}}',
        "limit": 500,
    }
    if attribution_windows:
        params["action_attribution_windows"] = ",".join(attribution_windows)
    if campaign_filter:
        params["filtering"] = (
            '[{"field":"campaign.name","operator":"CONTAIN","value":"%s"}]' % campaign_filter
        )

    span_days = (until - since).days + 1
    out: list[AdPerformance] = []
    for row in client.paged(client.account_path("insights"), params):
        out.append(AdPerformance(
            ad_id=row.get("ad_id", ""),
            ad_name=row.get("ad_name", ""),
            adset_name=row.get("adset_name", ""),
            campaign_name=row.get("campaign_name", ""),
            spend=float(row.get("spend") or 0),
            revenue=_pick(row.get("action_values"), action_types),
            purchases=int(_pick(row.get("actions"), action_types)),
            impressions=int(row.get("impressions") or 0),
            clicks=int(row.get("clicks") or 0),
            frequency=float(row.get("frequency") or 0),
            days_active=span_days,
        ))
    return out


def fetch_days_active(client: MetaClient, ad_ids: list[str]) -> dict[str, int]:
    """광고별 실제 가동 일수. 기간 전체를 돌지 않은 광고를 게이트에서 구제한다.

    insights 의 time_range 는 조회 기간일 뿐 광고의 나이가 아니다. 어제 만든 광고도
    30일 조회에서는 days_active=30 으로 잡혀서, 게이트를 부당하게 통과해 버린다.

    구현 주의: 예전에는 `?ids=a,b,c` 로 여러 개를 한 번에 조회했으나 v26.0 부터 없어졌다.
    지금은 계정의 ads 엣지를 광고 ID 로 필터링해서 가져온다.
    """
    out: dict[str, int] = {}
    today = datetime.now(timezone.utc).date()
    wanted = set(ad_ids)

    for i in range(0, len(ad_ids), 50):
        chunk = ad_ids[i : i + 50]
        params = {
            "fields": "id,created_time",
            "limit": 200,
            "filtering": json.dumps(
                [{"field": "ad.id", "operator": "IN", "value": chunk}]
            ),
        }
        for obj in client.paged(client.account_path("ads"), params):
            ad_id = obj.get("id")
            if ad_id not in wanted:
                continue
            try:
                created_date = datetime.strptime(obj.get("created_time", "")[:10], "%Y-%m-%d").date()
                out[ad_id] = max(1, (today - created_date).days)
            except ValueError:
                out[ad_id] = 1
    return out


def apply_true_age(perfs: list[AdPerformance], ages: dict[str, int]) -> list[AdPerformance]:
    """조회 기간과 광고 나이 중 짧은 쪽을 days_active 로 삼는다."""
    for p in perfs:
        if p.ad_id in ages:
            p.days_active = min(p.days_active, ages[p.ad_id])
    return perfs


def default_window(days: int = 14) -> tuple[date, date]:
    until = datetime.utcnow().date() - timedelta(days=1)   # 어제까지 (당일은 미확정)
    return until - timedelta(days=days - 1), until
