"""광고 네이밍 생성과 역파싱.

리터니티 US 광고 네이밍 규칙 v1.0 을 코드로 옮긴 것이다.

    캠페인   E_{국가}_{Source}_{Medium}_{판매채널}_{Language}_{ProductLine}_{목표}_{광고상품}^{부가설명}
    광고셋   {타겟}.{상세타겟}_{성별연령}_{최적화이벤트}^{부가설명}
    광고     {프로모션}_{상품명}_{소재유형}_{카피}_{오브제}_{랜딩ID}_{라이브일자}^{부가설명}

구분자
    _   필드 구분 (최상위)
    ^   부가설명 분리 (뒤는 자유입력)
    .   랜딩ID·상세타겟 내부 문법 (구분자가 아님)

이 모듈이 중요한 이유: 루프의 3단계(승자 DNA 추출)가 광고명 역파싱에 전적으로 의존한다.
자유입력 칸에 `_` 나 공백이 하나만 섞여도 슬롯이 밀리고, 그 시점부터 집계가 조용히 무너진다.
그래서 생성할 때 막고(validate), 파싱할 때 다시 검사한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Iterable

FIELD_SEP = "_"
NOTE_SEP = "^"

#: 자유입력(카피/오브제/메모)에서 금지되는 문자. 한글은 허용된다.
FORBIDDEN_IN_FREE = re.compile(r"[\s_^/]")

CAMPAIGN_PREFIX = "E"
CAMPAIGN_SLOTS = (
    "prefix", "country", "source", "medium", "sales_channel",
    "language", "product_line", "objective", "ad_product",
)
ADSET_SLOTS = ("target_block", "gender_age", "opt_event")
AD_SLOTS = (
    "promo", "product", "creative_type", "copy",
    "object", "landing_id", "live_date",
)


class NamingError(ValueError):
    """네이밍 규칙 위반. 광고를 만들기 전에 터뜨린다."""


def _check_free(value: str, field: str) -> str:
    if not value:
        raise NamingError(f"{field}: 비울 수 없습니다. 값이 없으면 'None'/'NoOffer' 같은 자리표시자를 쓰세요.")
    if FORBIDDEN_IN_FREE.search(value):
        raise NamingError(
            f"{field}: 공백·언더스코어·^·/ 를 쓸 수 없습니다 (받은 값: {value!r}). "
            "붙여쓰거나 하이픈(-)을 쓰세요."
        )
    return value


def _check_enum(value: str, allowed: Iterable[str], field: str) -> str:
    allowed = list(allowed)
    if value not in allowed:
        # 대소문자만 틀린 경우가 가장 흔하고, 가장 조용히 망가진다.
        near = [a for a in allowed if a.lower() == value.lower()]
        hint = f" '{near[0]}' 를 쓰려던 것 아닌가요?" if near else ""
        raise NamingError(f"{field}: 코드마스터에 없는 값 {value!r}.{hint}")
    return value


def _split_note(name: str) -> tuple[str, str]:
    body, sep, note = name.partition(NOTE_SEP)
    return body, (note if sep else "")


@dataclass(frozen=True)
class CampaignName:
    country: str
    source: str
    medium: str
    sales_channel: str
    language: str
    product_line: str
    objective: str
    ad_product: str
    note: str = ""

    def render(self) -> str:
        body = FIELD_SEP.join([
            CAMPAIGN_PREFIX, self.country, self.source, self.medium,
            self.sales_channel, self.language, self.product_line,
            self.objective, self.ad_product,
        ])
        return f"{body}{NOTE_SEP}{self.note}" if self.note else body

    @classmethod
    def parse(cls, name: str) -> "CampaignName":
        body, note = _split_note(name)
        parts = body.split(FIELD_SEP)
        if len(parts) != len(CAMPAIGN_SLOTS):
            raise NamingError(
                f"캠페인명 슬롯 수가 맞지 않습니다 (기대 {len(CAMPAIGN_SLOTS)}, 실제 {len(parts)}): {name!r}"
            )
        if parts[0] != CAMPAIGN_PREFIX:
            raise NamingError(f"캠페인명은 '{CAMPAIGN_PREFIX}_' 로 시작해야 합니다: {name!r}")
        return cls(*parts[1:], note=note)

    def validate(self, taxonomy: dict) -> "CampaignName":
        for slot in CAMPAIGN_SLOTS[1:]:
            _check_enum(getattr(self, slot), taxonomy[slot], f"캠페인.{slot}")
        return self


@dataclass(frozen=True)
class AdsetName:
    target: str
    target_detail: str
    gender_age: str
    opt_event: str
    note: str = ""

    def render(self) -> str:
        body = FIELD_SEP.join([
            f"{self.target}.{self.target_detail}", self.gender_age, self.opt_event,
        ])
        return f"{body}{NOTE_SEP}{self.note}" if self.note else body

    @classmethod
    def parse(cls, name: str) -> "AdsetName":
        body, note = _split_note(name)
        parts = body.split(FIELD_SEP)
        if len(parts) != len(ADSET_SLOTS):
            raise NamingError(
                f"광고셋명 슬롯 수가 맞지 않습니다 (기대 {len(ADSET_SLOTS)}, 실제 {len(parts)}): {name!r}"
            )
        target_block, gender_age, opt_event = parts
        target, dot, target_detail = target_block.partition(".")
        if not dot:
            raise NamingError(f"광고셋명의 타겟 블록은 '타겟.상세타겟' 형태여야 합니다: {target_block!r}")
        return cls(target, target_detail, gender_age, opt_event, note=note)

    def validate(self, taxonomy: dict) -> "AdsetName":
        for slot in ("target", "target_detail", "gender_age", "opt_event"):
            _check_enum(getattr(self, slot), taxonomy[slot], f"광고셋.{slot}")
        return self


@dataclass(frozen=True)
class AdName:
    """광고(소재)명. 승자 DNA 를 분해해서 꺼내는 대상이 바로 이 7개 슬롯이다."""

    promo: str
    product: str
    creative_type: str
    copy: str            # 자유입력 — 카피 앵글 코드
    object: str          # 자유입력 — 화면에 실제로 보이는 오브제
    landing_id: str
    live_date: str       # YYMMDD
    note: str = ""

    def render(self) -> str:
        body = FIELD_SEP.join([
            self.promo, self.product, self.creative_type,
            self.copy, self.object, self.landing_id, self.live_date,
        ])
        return f"{body}{NOTE_SEP}{self.note}" if self.note else body

    @classmethod
    def parse(cls, name: str) -> "AdName":
        body, note = _split_note(name)
        parts = body.split(FIELD_SEP)
        if len(parts) != len(AD_SLOTS):
            raise NamingError(
                f"광고명 슬롯 수가 맞지 않습니다 (기대 {len(AD_SLOTS)}, 실제 {len(parts)}): {name!r}\n"
                "자유입력 칸(카피·오브제)에 언더스코어나 공백이 섞이면 이렇게 됩니다."
            )
        return cls(*parts, note=note)

    def validate(self, taxonomy: dict, landings: dict | None = None) -> "AdName":
        _check_enum(self.promo, taxonomy["promo"], "광고.promo")
        _check_enum(self.product, taxonomy["product"], "광고.product")
        _check_enum(self.creative_type, taxonomy["creative_type"], "광고.creative_type")
        _check_free(self.copy, "광고.copy")
        _check_free(self.object, "광고.object")
        if not re.fullmatch(r"\d{6}", self.live_date):
            raise NamingError(f"광고.live_date 는 YYMMDD 6자리여야 합니다: {self.live_date!r}")
        if landings is not None and self.landing_id not in landings:
            raise NamingError(
                f"광고.landing_id: 랜딩 마스터에 없는 ID {self.landing_id!r}. "
                "config/landing.yaml 에 먼저 추가하세요."
            )
        return self

    def dna(self) -> dict[str, str]:
        """DNA 분석 축. 라운드마다 바뀌는 값(날짜·랜딩)은 뺀다."""
        return {
            "promo": self.promo,
            "product": self.product,
            "creative_type": self.creative_type,
            "copy": self.copy,
            "object": self.object,
        }

    def respin(self, **changes: str) -> "AdName":
        """일부 슬롯만 바꾼 새 광고명. 다음 라운드 조합을 만들 때 쓴다."""
        return replace(self, **changes)


def parse_triplet(
    campaign: str, adset: str, ad: str
) -> tuple[CampaignName | None, AdsetName | None, AdName | None]:
    """세 이름을 한 번에 파싱한다. 규칙을 벗어난 이름은 None 으로 떨어뜨린다.

    운영 계정에는 규칙 이전에 만든 광고가 반드시 섞여 있다. 그것 때문에 전체
    파이프라인이 멈추면 안 되므로, 여기서는 예외를 삼키고 호출부가 세도록 한다.
    """
    def _try(fn, value):
        try:
            return fn(value)
        except NamingError:
            return None

    return (
        _try(CampaignName.parse, campaign),
        _try(AdsetName.parse, adset),
        _try(AdName.parse, ad),
    )
