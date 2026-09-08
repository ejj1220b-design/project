"""승자 DNA → 다음 라운드 카피 + 소재 기획안.

루프의 3단계다. 2단계에서 살아남은 축(카피 앵글·오브제·소재유형)을 받아서,
그 축을 유지하면서 변주한 새 소재 명세를 대량으로 만든다.

산출물은 두 갈래로 쓰인다.
    · copy 블록  → matrix.yaml 에 그대로 붙여 넣으면 다음 라운드가 발행된다
    · 기획안     → 촬영/편집 담당자에게 넘기는 컷 구성

모델은 Claude Opus 5, 구조화 출력(JSON 스키마)으로 받는다. 자유 텍스트로 받으면
카피 코드에 공백이 섞여 네이밍이 깨지는 사고가 반드시 난다.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, field_validator

MODEL = "claude-opus-5"

#: 광고명 자유입력 칸에 넣을 수 있는 문자만 남긴다.
_UNSAFE = re.compile(r"[\s_^/]+")


def sanitize_code(value: str) -> str:
    """카피 코드/오브제 코드를 네이밍 안전형으로. 한글은 그대로 둔다."""
    return _UNSAFE.sub("-", value.strip()).strip("-")


class CreativeConcept(BaseModel):
    copy_code: str = Field(description="광고명에 들어갈 카피 앵글 코드. 한글 6~12자. 공백·언더스코어 금지.")
    object_code: str = Field(description="화면에 실제로 보이는 핵심 오브제 코드. 한글 3~8자. 공백·언더스코어 금지.")
    creative_type: str = Field(description="Video / Image / GIF / Carousel 중 하나")
    angle: str = Field(description="이 소재가 파고드는 소비자 인식. 한 문장.")
    primary_text: str = Field(description="Meta 본문 카피. 첫 두 줄에서 승부가 난다.")
    headline: str = Field(description="Meta 제목. 40자 이내.")
    description: str = Field(description="Meta 설명. 30자 이내.")
    hook_seconds: str = Field(description="0~3초 후킹 구간에서 화면에 무엇이 보이고 무엇이 들리는지.")
    shots: list[str] = Field(description="컷 구성 3~5개. 각 항목은 '초단위: 화면 / 자막' 형태.")
    inherits: str = Field(description="승자 DNA 중 무엇을 이어받았는지.")
    varies: str = Field(description="승자 대비 무엇을 바꿔 검증하려는지. 라운드마다 한 가지씩만 바꾼다.")

    @field_validator("copy_code", "object_code")
    @classmethod
    def _safe(cls, v: str) -> str:
        return sanitize_code(v)


class ConceptBatch(BaseModel):
    concepts: list[CreativeConcept]
    reasoning: str = Field(description="이번 배치를 이렇게 구성한 근거. 3문장 이내.")


SYSTEM = """\
당신은 한국 스킨케어 브랜드의 글로벌 퍼포먼스 마케터다. Meta 광고 소재를 설계한다.

지켜야 할 것:
- 이미 성과로 검증된 축(승자 DNA)은 유지한다. 한 배치 안에서 바꾸는 변수는 한 가지로 제한한다.
  전부 바꾸면 다음 라운드에서 무엇이 이겼는지 알 수 없게 된다.
- copy_code 와 object_code 는 광고명에 들어간다. 공백·언더스코어·슬래시를 절대 쓰지 않는다.
  이 규칙이 깨지면 성과 집계가 조용히 무너진다.
- 카피는 번역체를 쓰지 않는다. 타겟 언어 사용자가 실제로 쓰는 표현으로 쓴다.
- 효능을 단정하지 않는다. 의약품처럼 읽히는 표현(치료, 재생, 개선 보장)은 쓰지 않는다.
  광고 심사에서 거부되고, 거부 이력은 계정 전체에 남는다.
- 리뷰 인용이 주어지면 실제 표현을 살린다. 소비자가 쓴 단어가 가장 잘 후킹한다.
"""

PROMPT = """\
## 승자 DNA (직전 라운드 성과)
{dna_block}

## 제품
{product_block}

## 타겟
{audience_block}
{review_block}
## 요청
위 승자 DNA 를 이어받는 새 소재 {n}개를 설계하라.

- 승자 축은 유지하고, {vary_axis} 만 변주한다.
- {n}개가 서로 다른 가설을 검증해야 한다. 같은 말을 바꿔 쓴 것은 안 된다.
- 언어: {language}
- 소재유형: {creative_types}
"""


@dataclass
class BriefRequest:
    dna_summary: str
    product: str
    audience: str
    n: int = 8
    language: str = "영어 (미국 거주 비한국계)"
    creative_types: str = "Video"
    vary_axis: str = "카피 앵글"
    reviews: list[str] | None = None


def _build_prompt(req: BriefRequest) -> str:
    review_block = ""
    if req.reviews:
        quoted = "\n".join(f"- {r.strip()}" for r in req.reviews[:15])
        review_block = f"\n## 실제 리뷰 (표현을 빌려 쓸 것)\n{quoted}\n"
    return PROMPT.format(
        dna_block=req.dna_summary,
        product_block=req.product,
        audience_block=req.audience,
        review_block=review_block,
        n=req.n,
        language=req.language,
        creative_types=req.creative_types,
        vary_axis=req.vary_axis,
    )


def generate(req: BriefRequest, api_key: str | None = None) -> ConceptBatch:
    """Claude 로 소재 컨셉 배치를 만든다."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY") or None)

    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM,
        messages=[{"role": "user", "content": _build_prompt(req)}],
        thinking={"type": "adaptive"},
        output_config={
            "effort": "high",
            "format": {"type": "json_schema", "schema": _schema()},
        },
        # 안전 분류기가 요청을 거절하면 서버가 대체 모델로 넘긴다.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )

    if response.stop_reason == "refusal":
        detail = getattr(response, "stop_details", None)
        raise RuntimeError(
            f"모델이 요청을 거절했습니다 (category={getattr(detail, 'category', None)}). "
            "프롬프트에 들어간 제품 주장 표현을 확인하세요."
        )

    text = next(b.text for b in response.content if b.type == "text")
    return ConceptBatch.model_validate(json.loads(text))


def _schema() -> dict[str, Any]:
    schema = ConceptBatch.model_json_schema()
    _strictify(schema)
    return schema


def _strictify(node: Any) -> None:
    """JSON 스키마를 strict 모드가 요구하는 형태로 (additionalProperties: false + required 전부)."""
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node["properties"].keys())
        for value in node.values():
            _strictify(value)
    elif isinstance(node, list):
        for item in node:
            _strictify(item)


def to_matrix_blocks(batch: ConceptBatch) -> dict:
    """matrix.yaml 에 붙여 넣을 수 있는 형태로 변환."""
    copy_bank = {
        c.copy_code: {
            "primary_text": c.primary_text,
            "headline": c.headline,
            "description": c.description,
            "call_to_action": "SHOP_NOW",
        }
        for c in batch.concepts
    }
    return {
        "creatives": {
            "copy": sorted({c.copy_code for c in batch.concepts}),
            "object": sorted({c.object_code for c in batch.concepts}),
            "creative_type": sorted({c.creative_type for c in batch.concepts}),
        },
        "copy": copy_bank,
    }


def dna_summary_from_report(report, keep_top: int = 3, min_ads: int = 2) -> str:
    """DnaReport 를 프롬프트에 넣을 텍스트로."""
    lines = [f"계정 기준선 ROAS: {report.baseline_roas:.2f}"]
    labels = {"copy": "카피 앵글", "object": "오브제", "creative_type": "소재유형",
              "product": "상품", "promo": "프로모션"}
    for axis, label in labels.items():
        rows = report.top(axis, n=keep_top, min_ads=min_ads)
        if not rows:
            continue
        lines.append(f"\n[{label}]")
        for lv in rows:
            note = " (교란 가능 — 다른 축과 함께만 등장)" if lv.confounded else ""
            lines.append(
                f"  {lv.value}: 광고 {lv.ads}개 · 지출 {lv.spend:,.0f} · "
                f"ROAS {lv.roas:.2f} (신뢰구간 {lv.interval.lower:.2f}~{lv.interval.upper:.2f}){note}"
            )
    return "\n".join(lines)
