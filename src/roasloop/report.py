"""판정·DNA 결과를 사람이 읽는 형태로."""

from __future__ import annotations

import csv
from pathlib import Path

from .dna import DNA_AXES, DnaReport
from .judge import Judgement, Verdict, summarize

_ICON = {Verdict.SCALE: "▲", Verdict.KEEP: "·", Verdict.INSUFFICIENT: "…", Verdict.KILL: "✕"}


def judgement_table(judgements: list[Judgement], currency: str = "KRW", limit: int = 0) -> str:
    rows = judgements[:limit] if limit else judgements
    lines = [
        f"{'':2} {'광고명':<58} {'지출':>11} {'ROAS':>6} {'신뢰구간':>14} {'구매':>4}  사유",
        "─" * 130,
    ]
    for j in rows:
        p, iv = j.perf, j.interval
        name = p.ad_name if len(p.ad_name) <= 58 else p.ad_name[:55] + "…"
        lines.append(
            f"{_ICON[j.verdict]:2} {name:<58} {p.spend:>11,.0f} {iv.point:>6.2f} "
            f"{iv.lower:>6.2f}~{iv.upper:<7.2f} {p.purchases:>4}  {j.reason}"
        )
        for w in j.warnings:
            lines.append(f"{'':2} {'':<58} {'':>11} {'':>6} {'':>14} {'':>4}  ⚠ {w}")
    return "\n".join(lines)


def judgement_summary(judgements: list[Judgement], currency: str = "KRW") -> str:
    s = summarize(judgements)
    lines = [f"{'판정':<14}{'개수':>5}{'지출':>14}{'매출':>15}{'ROAS':>8}{'구매':>7}", "─" * 63]
    for v in (Verdict.SCALE, Verdict.KEEP, Verdict.INSUFFICIENT, Verdict.KILL):
        r = s[v.value]
        lines.append(
            f"{_ICON[v]} {v.value:<12}{r['count']:>5}{r['spend']:>14,.0f}"
            f"{r['revenue']:>15,.0f}{r['roas']:>8.2f}{r['purchases']:>7}"
        )
    total_spend = sum(r["spend"] for r in s.values())
    total_rev = sum(r["revenue"] for r in s.values())
    lines.append("─" * 63)
    lines.append(
        f"{'합계':<14}{sum(r['count'] for r in s.values()):>5}{total_spend:>14,.0f}"
        f"{total_rev:>15,.0f}{(total_rev / total_spend if total_spend else 0):>8.2f}"
        f"{sum(r['purchases'] for r in s.values()):>7}"
    )
    kill = s[Verdict.KILL.value]
    if kill["count"]:
        lines.append(
            f"\n→ KILL {kill['count']}개를 끄면 월 {kill['spend']:,.0f} {currency} 가 확보됩니다 "
            f"(해당 지출의 실제 ROAS {kill['roas']:.2f})."
        )
    return "\n".join(lines)


def dna_table(report: DnaReport, top: int = 5, min_ads: int = 1) -> str:
    labels = {"copy": "카피 앵글", "object": "오브제", "creative_type": "소재유형",
              "product": "상품", "promo": "프로모션"}
    lines = [f"기준선 ROAS {report.baseline_roas:.2f} "
             f"(지출 {report.total_spend:,.0f} / 매출 {report.total_revenue:,.0f})"]
    if report.unparsed:
        lines.append(f"⚠ 네이밍 규칙을 벗어나 DNA 분석에서 빠진 광고 {len(report.unparsed)}개")
    for axis in DNA_AXES:
        rows = report.top(axis, n=top, min_ads=min_ads)
        if not rows:
            continue
        lines.append(f"\n[{labels[axis]}]")
        lines.append(f"  {'값':<20}{'광고':>4}{'지출':>12}{'ROAS':>7}{'신뢰구간':>14}{'승/패':>7}")
        for lv in rows:
            iv = lv.interval
            flag = "  ⚠교란" if lv.confounded else ""
            lines.append(
                f"  {lv.value:<20}{lv.ads:>4}{lv.spend:>12,.0f}{lv.roas:>7.2f}"
                f"{iv.lower:>6.2f}~{iv.upper:<7.2f}{f'{lv.winners}/{lv.losers}':>7}{flag}"
            )
    return "\n".join(lines)


def write_judgements_csv(judgements: list[Judgement], path: Path | str) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "판정", "ad_id", "광고명", "광고셋명", "캠페인명", "지출", "매출", "구매",
            "ROAS", "ROAS하단", "ROAS상단", "노출", "클릭", "CTR", "CPA", "빈도", "일수", "사유", "경고",
        ])
        for j in judgements:
            p_, iv = j.perf, j.interval
            w.writerow([
                j.verdict.value, p_.ad_id, p_.ad_name, p_.adset_name, p_.campaign_name,
                round(p_.spend), round(p_.revenue), p_.purchases,
                f"{iv.point:.2f}", f"{iv.lower:.2f}", f"{iv.upper:.2f}",
                p_.impressions, p_.clicks, f"{p_.ctr:.4f}",
                ("" if p_.cpa == float("inf") else round(p_.cpa)),
                f"{p_.frequency:.2f}", p_.days_active, j.reason, " / ".join(j.warnings),
            ])
    return p
