"""광고 대량 발행.

안전장치 두 개가 기본값이다.

    1. dry_run=True   실제로 만들지 않고 무엇이 만들어질지만 보여준다.
    2. status=PAUSED  만들어도 꺼진 상태로 둔다. 켜는 것은 사람이 확인한 뒤 별도 명령으로.

48개 광고를 한 번에 잘못 켜면 하루 예산이 그대로 나간다. 되돌릴 수 없는 쪽에는
항상 한 번 더 확인을 건다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from ..matrix import AdSpec
from .client import MetaClient

log = logging.getLogger("roasloop.launch")

OBJECTIVE_MAP = {
    "Conversion": "OUTCOME_SALES",
    "ASC": "OUTCOME_SALES",
    "Traffic": "OUTCOME_TRAFFIC",
    "Leads": "OUTCOME_LEADS",
    "Reach": "OUTCOME_AWARENESS",
    "Engagement": "OUTCOME_ENGAGEMENT",
    "Videoview": "OUTCOME_AWARENESS",
    "AppPromotion": "OUTCOME_APP_PROMOTION",
}


@dataclass
class LaunchResult:
    created_ads: list[tuple[str, str]] = field(default_factory=list)   # (ad_name, ad_id)
    reused: dict[str, str] = field(default_factory=dict)               # name → id
    failures: list[tuple[str, str]] = field(default_factory=list)      # (ad_name, error)
    planned: list[str] = field(default_factory=list)                   # dry-run 결과


class Launcher:
    def __init__(
        self,
        client: MetaClient,
        page_id: str,
        pixel_id: str = "",
        instagram_id: str = "",
        dry_run: bool = True,
        status: str = "PAUSED",
        ownership=None,
    ):
        self.client = client
        self.page_id = page_id
        self.pixel_id = pixel_id
        self.instagram_id = instagram_id
        self.dry_run = dry_run
        self.status = status
        #: 캠페인 소유 구분기. 대행사 캠페인에 광고를 만드는 것도 막아야 한다.
        self.ownership = ownership
        self._campaigns: dict[str, str] = {}
        self._adsets: dict[str, str] = {}

    # -------------------------------------------------------------- 조회/생성
    def _find(self, edge: str, name: str) -> str | None:
        """같은 이름의 오브젝트가 이미 있으면 재사용한다 (중복 캠페인 방지)."""
        params = {"fields": "id,name", "limit": 500,
                  "filtering": '[{"field":"name","operator":"EQUAL","value":"%s"}]' % name}
        for obj in self.client.paged(self.client.account_path(edge), params):
            if obj.get("name") == name:
                return obj["id"]
        return None

    def ensure_campaign(self, name: str, objective: str, budget: int | None = None) -> str:
        if name in self._campaigns:
            return self._campaigns[name]
        existing = None if self.dry_run else self._find("campaigns", name)
        if existing:
            log.info("캠페인 재사용: %s (%s)", name, existing)
            self._campaigns[name] = existing
            return existing
        if self.dry_run:
            self._campaigns[name] = f"<신규캠페인:{name}>"
            return self._campaigns[name]

        payload = {
            "name": name,
            "objective": OBJECTIVE_MAP.get(objective, "OUTCOME_SALES"),
            "status": self.status,
            "special_ad_categories": "[]",
        }
        if budget:
            payload["daily_budget"] = int(budget)   # CBO
        cid = self.client.post(self.client.account_path("campaigns"), payload)["id"]
        self._campaigns[name] = cid
        return cid

    def ensure_adset(self, campaign_id: str, name: str, cfg: dict) -> str:
        cache_key = f"{campaign_id}::{name}"
        if cache_key in self._adsets:
            return self._adsets[cache_key]
        existing = None if self.dry_run else self._find("adsets", name)
        if existing:
            log.info("광고셋 재사용: %s (%s)", name, existing)
            self._adsets[cache_key] = existing
            return existing
        if self.dry_run:
            self._adsets[cache_key] = f"<신규광고셋:{name}>"
            return self._adsets[cache_key]

        targeting = cfg.get("targeting") or {}
        payload = {
            "name": name,
            "campaign_id": campaign_id,
            "status": self.status,
            "billing_event": cfg.get("billing_event", "IMPRESSIONS"),
            "optimization_goal": cfg.get("optimization_goal", "OFFSITE_CONVERSIONS"),
            "targeting": json.dumps(targeting),
        }
        if cfg.get("daily_budget"):
            payload["daily_budget"] = int(cfg["daily_budget"])
        if cfg.get("bid_amount"):
            payload["bid_amount"] = int(cfg["bid_amount"])
        if self.pixel_id:
            payload["promoted_object"] = json.dumps({
                "pixel_id": self.pixel_id,
                "custom_event_type": cfg.get("custom_event_type", "PURCHASE"),
            })
        aid = self.client.post(self.client.account_path("adsets"), payload)["id"]
        self._adsets[cache_key] = aid
        return aid

    def create_creative(self, spec: AdSpec) -> str:
        link_data: dict = {
            "link": spec.landing_url,
            "message": spec.primary_text,
            "call_to_action": {"type": spec.call_to_action, "value": {"link": spec.landing_url}},
        }
        if spec.headline:
            link_data["name"] = spec.headline
        if spec.description:
            link_data["description"] = spec.description

        if spec.video_id:
            story: dict = {"video_data": {
                **{k: v for k, v in link_data.items() if k != "link"},
                "video_id": spec.video_id,
                "image_url": spec.thumbnail_url,
                "call_to_action": link_data["call_to_action"],
            }}
        else:
            story = {"link_data": {**link_data, "image_hash": spec.image_hash}}

        object_story_spec = {"page_id": self.page_id, **story}
        if self.instagram_id:
            object_story_spec["instagram_actor_id"] = self.instagram_id

        payload = {
            "name": spec.ad_name,
            "object_story_spec": json.dumps(object_story_spec),
        }
        if spec.url_tags:
            payload["url_tags"] = spec.url_tags
        return self.client.post(self.client.account_path("adcreatives"), payload)["id"]

    # ------------------------------------------------------------------ 실행
    def launch(self, specs: list[AdSpec], adset_configs: dict[str, dict],
               campaign_objective: str = "Conversion",
               campaign_budget: int | None = None) -> LaunchResult:
        result = LaunchResult()
        ready = [s for s in specs if s.ready]

        for spec in ready:
            try:
                if self.ownership is not None:
                    self.ownership.require_mine(spec.campaign_name)
                cid = self.ensure_campaign(spec.campaign_name, campaign_objective, campaign_budget)
                aid = self.ensure_adset(cid, spec.adset_name, adset_configs.get(spec.adset_name, {}))
                if self.dry_run:
                    result.planned.append(
                        f"{spec.campaign_name} / {spec.adset_name} / {spec.ad_name}"
                    )
                    continue
                creative_id = self.create_creative(spec)
                ad = self.client.post(self.client.account_path("ads"), {
                    "name": spec.ad_name,
                    "adset_id": aid,
                    "creative": json.dumps({"creative_id": creative_id}),
                    "status": self.status,
                })
                result.created_ads.append((spec.ad_name, ad["id"]))
                log.info("광고 생성: %s (%s)", spec.ad_name, ad["id"])
            except Exception as exc:                     # noqa: BLE001 — 한 개 실패로 전체를 멈추지 않는다
                result.failures.append((spec.ad_name, str(exc)))
                log.error("광고 생성 실패: %s — %s", spec.ad_name, exc)
        return result


def pause_ads(client: MetaClient, ad_ids: list[str]) -> tuple[list[str], list[tuple[str, str]]]:
    """판정 결과 KILL 인 광고를 끈다."""
    ok, failed = [], []
    for ad_id in ad_ids:
        try:
            client.update_status(ad_id, "PAUSED")
            ok.append(ad_id)
        except Exception as exc:                          # noqa: BLE001
            failed.append((ad_id, str(exc)))
    return ok, failed
