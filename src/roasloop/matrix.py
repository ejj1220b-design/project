"""조합 매트릭스 전개.

축(axis)을 곱해서 광고 스펙을 대량으로 만든다. 이 모듈이 루프 1단계("대량 발행")와
3단계("승자 DNA 로 재생산")의 공통 엔진이다. 두 단계의 차이는 축에 무엇을 넣느냐뿐이다.

    1단계  넓게 — 카피 앵글 6 × 오브제 4 × 유형 2 = 48개
    3단계  좁게 — 승자 축의 값만 남기고, 새 카피 앵글만 곱한다

중복 방지가 핵심이다. 이미 돌려본 조합을 다시 만들면 라운드가 헛돈다.
history 파일(과거 라운드에서 실제 집행한 광고명)을 받아 걸러낸다.
"""

from __future__ import annotations

import csv
import itertools
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from .naming import AdName, AdsetName, CampaignName, NamingError

#: 조합 축으로 쓸 수 있는 광고명 슬롯
AXES = ("promo", "product", "creative_type", "copy", "object", "landing_id")


@dataclass
class AdSpec:
    """광고 한 개의 발행 명세. 소재가 아직 없어도 만들어진다."""

    campaign_name: str
    adset_name: str
    ad_name: str
    landing_url: str
    url_tags: str
    # 소재 바인딩 — 없으면 '제작 대기' 상태
    image_hash: str = ""
    video_id: str = ""
    thumbnail_url: str = ""
    primary_text: str = ""
    headline: str = ""
    description: str = ""
    call_to_action: str = "SHOP_NOW"
    asset_key: str = ""

    @property
    def ready(self) -> bool:
        """지금 바로 Meta 에 올릴 수 있는가."""
        return bool((self.image_hash or self.video_id) and self.primary_text)

    @property
    def missing(self) -> list[str]:
        gaps = []
        if not (self.image_hash or self.video_id):
            gaps.append("소재파일")
        if not self.primary_text:
            gaps.append("카피")
        return gaps


@dataclass
class RoundPlan:
    round_id: str
    specs: list[AdSpec] = field(default_factory=list)
    skipped_duplicates: list[str] = field(default_factory=list)
    invalid: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ready(self) -> list[AdSpec]:
        return [s for s in self.specs if s.ready]

    @property
    def pending(self) -> list[AdSpec]:
        return [s for s in self.specs if not s.ready]


def asset_key(values: dict[str, str], key_axes: tuple[str, ...] = ("copy", "object", "creative_type")) -> str:
    """소재 매핑 키. matrix.yaml 의 assets 블록이 이 키를 쓴다."""
    return "|".join(values.get(a, "") for a in key_axes)


def load_history(path: Path | str) -> set[str]:
    """이미 집행한 광고명 집합. 없으면 빈 집합."""
    p = Path(path)
    if not p.exists():
        return set()
    with p.open(encoding="utf-8") as fh:
        return {line.strip() for line in fh if line.strip() and not line.startswith("#")}


def append_history(path: Path | str, ad_names: list[str]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        for name in ad_names:
            fh.write(name + "\n")


def expand(
    matrix: dict,
    config,
    live_date: date | None = None,
    history: set[str] | None = None,
    limit: int | None = None,
) -> RoundPlan:
    """matrix.yaml 한 덩어리를 광고 스펙 목록으로 펼친다."""
    from .utm import macro_url_tags, static_url

    history = history or set()
    live = (live_date or date.today()).strftime("%y%m%d")
    plan = RoundPlan(round_id=str(matrix.get("round", "R0")))

    defaults = {**config.defaults, **(matrix.get("defaults") or {})}
    campaign = CampaignName(
        country=defaults["country"], source=defaults["source"], medium=defaults["medium"],
        sales_channel=defaults["sales_channel"], language=defaults["language"],
        product_line=defaults["product_line"], objective=defaults["objective"],
        ad_product=defaults["ad_product"], note=matrix.get("campaign_note", ""),
    ).validate(config.taxonomy)

    axes: dict[str, list[str]] = {}
    for axis in AXES:
        raw = matrix.get("creatives", {}).get(axis, defaults.get(axis))
        if raw is None:
            raise ValueError(f"매트릭스에 '{axis}' 축이 없습니다. creatives 또는 defaults 에 넣으세요.")
        axes[axis] = raw if isinstance(raw, list) else [raw]

    assets: dict[str, dict] = matrix.get("assets", {}) or {}
    copy_bank: dict[str, dict] = matrix.get("copy", {}) or {}
    url_tags = macro_url_tags(config.utm) if config.utm.get("use_dynamic_macros", True) else ""

    adsets = matrix.get("adsets") or []
    if not adsets:
        raise ValueError("매트릭스에 adsets 가 없습니다. 최소 한 개의 광고셋이 필요합니다.")

    combos = list(itertools.product(*(axes[a] for a in AXES)))
    for adset_cfg in adsets:
        adset = AdsetName(
            target=adset_cfg["target"], target_detail=adset_cfg["target_detail"],
            gender_age=adset_cfg["gender_age"],
            opt_event=adset_cfg.get("opt_event", defaults.get("opt_event", "Purchase")),
            note=adset_cfg.get("note", ""),
        ).validate(config.taxonomy)

        for combo in combos:
            values = dict(zip(AXES, combo))
            try:
                ad = AdName(
                    promo=values["promo"], product=values["product"],
                    creative_type=values["creative_type"], copy=values["copy"],
                    object=values["object"], landing_id=values["landing_id"],
                    live_date=live, note=matrix.get("ad_note", ""),
                ).validate(config.taxonomy, config.landings)
            except NamingError as exc:
                plan.invalid.append((str(values), str(exc)))
                continue

            name = ad.render()
            if name in history:
                plan.skipped_duplicates.append(name)
                continue

            key = asset_key(values)
            asset = assets.get(key, {})
            text = copy_bank.get(values["copy"], {})
            base_url = config.landings[values["landing_id"]]

            plan.specs.append(AdSpec(
                campaign_name=campaign.render(),
                adset_name=adset.render(),
                ad_name=name,
                landing_url=(
                    base_url if url_tags
                    else static_url(base_url, config.utm, campaign.render(), adset.render(), name)
                ),
                url_tags=url_tags,
                image_hash=asset.get("image_hash", ""),
                video_id=str(asset.get("video_id", "")),
                thumbnail_url=asset.get("thumbnail_url", ""),
                primary_text=text.get("primary_text", ""),
                headline=text.get("headline", ""),
                description=text.get("description", ""),
                call_to_action=text.get("call_to_action", "SHOP_NOW"),
                asset_key=key,
            ))
            if limit and len(plan.specs) >= limit:
                return plan
    return plan


def write_csv(specs: list[AdSpec], path: Path | str) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    rows = [asdict(s) for s in specs]
    header = list(rows[0].keys()) if rows else [f.name for f in AdSpec.__dataclass_fields__.values()]
    with p.open("w", encoding="utf-8-sig", newline="") as fh:   # utf-8-sig: 엑셀에서 한글 안 깨지게
        writer = csv.DictWriter(fh, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)
    return p
