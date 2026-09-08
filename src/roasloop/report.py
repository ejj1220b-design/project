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


# --------------------------------------------------------------- 소유별 보고서
def ownership_summary(judgements: list[Judgement], ownership, currency: str = "KRW") -> str:
    """캠페인 소유별 성과 요약. 대행사 성과와 내 성과를 갈라서 본다."""
    from .ownership import Owner

    groups = ownership.split(judgements, key=lambda j: j.perf.campaign_name)
    lines = [
        f"{'구분':<8}{'광고':>5}{'지출':>14}{'매출':>15}{'ROAS':>8}{'끌 것':>7}{'확장':>6}",
        "─" * 63,
    ]
    for owner in (Owner.MINE, Owner.AGENCY, Owner.UNKNOWN):
        rows = groups[owner]
        if not rows:
            continue
        spend = sum(j.perf.spend for j in rows)
        revenue = sum(j.perf.revenue for j in rows)
        lines.append(
            f"{ownership.labels[owner]:<8}{len(rows):>5}{spend:>14,.0f}{revenue:>15,.0f}"
            f"{(revenue / spend if spend else 0):>8.2f}"
            f"{sum(1 for j in rows if j.verdict == Verdict.KILL):>7}"
            f"{sum(1 for j in rows if j.verdict == Verdict.SCALE):>6}"
        )
    return "\n".join(lines)


def action_list(judgements: list[Judgement], ownership, currency: str = "KRW") -> str:
    """제안 목록. roasloop 은 이걸 실행하지 않는다 — 사람이 보고 결정한다."""
    from .ownership import Owner

    kills = [j for j in judgements if j.verdict == Verdict.KILL]
    scales = [j for j in judgements if j.verdict == Verdict.SCALE]
    if not kills and not scales:
        return "제안할 조치가 없습니다."

    groups = ownership.split(kills, key=lambda j: j.perf.campaign_name)
    out: list[str] = []

    if kills:
        out.append(f"■ 중단 제안 {len(kills)}개 "
                   f"(해당 지출 {sum(j.perf.spend for j in kills):,.0f} {currency})")
        for owner in (Owner.MINE, Owner.AGENCY, Owner.UNKNOWN):
            rows = groups[owner]
            if not rows:
                continue
            note = "" if owner is Owner.MINE else "  ← roasloop 이 건드리지 않음. 공유용."
            out.append(f"\n  [{ownership.labels[owner]}] {len(rows)}개{note}")
            for j in rows:
                out.append(
                    f"    ✕ {j.perf.ad_name}\n"
                    f"      지출 {j.perf.spend:,.0f} · ROAS {j.interval.point:.2f} "
                    f"(구간 {j.interval.lower:.2f}~{j.interval.upper:.2f}) · 구매 {j.perf.purchases} — {j.reason}"
                )
    if scales:
        out.append(f"\n■ 확장 제안 {len(scales)}개")
        for j in scales:
            out.append(
                f"    ▲ {j.perf.ad_name}  [{ownership.label(j.perf.campaign_name)}]\n"
                f"      지출 {j.perf.spend:,.0f} · ROAS {j.interval.point:.2f} "
                f"(구간 {j.interval.lower:.2f}~{j.interval.upper:.2f}) · 구매 {j.perf.purchases}"
            )
    return "\n".join(out)


def markdown_report(
    judgements: list[Judgement],
    dna_report: DnaReport | None,
    ownership,
    period: str = "",
    currency: str = "KRW",
) -> str:
    """대행사·상급자에게 그대로 보낼 수 있는 보고서."""
    from .ownership import Owner

    s = summarize(judgements)
    total_spend = sum(r["spend"] for r in s.values())
    total_rev = sum(r["revenue"] for r in s.values())
    groups = ownership.split(judgements, key=lambda j: j.perf.campaign_name)

    md = [f"# 소재 성과 판정 보고서{f' — {period}' if period else ''}", ""]
    md.append(
        f"광고 {len(judgements)}개 · 지출 {total_spend:,.0f} {currency} · "
        f"매출 {total_rev:,.0f} {currency} · ROAS {(total_rev / total_spend if total_spend else 0):.2f}"
    )
    md.append("")
    md.append("## 판정 요약")
    md.append("")
    md.append("| 판정 | 개수 | 지출 | 매출 | ROAS | 구매 |")
    md.append("|---|---:|---:|---:|---:|---:|")
    names = {Verdict.SCALE: "확장 (SCALE)", Verdict.KEEP: "유지 (KEEP)",
             Verdict.INSUFFICIENT: "판정 보류", Verdict.KILL: "중단 제안 (KILL)"}
    for v in (Verdict.SCALE, Verdict.KEEP, Verdict.INSUFFICIENT, Verdict.KILL):
        r = s[v.value]
        md.append(f"| {names[v]} | {r['count']} | {r['spend']:,.0f} | {r['revenue']:,.0f} "
                  f"| {r['roas']:.2f} | {r['purchases']} |")

    md += ["", "## 캠페인 소유별", "", "| 구분 | 광고 | 지출 | 매출 | ROAS | 중단 제안 | 확장 제안 |",
           "|---|---:|---:|---:|---:|---:|---:|"]
    for owner in (Owner.MINE, Owner.AGENCY, Owner.UNKNOWN):
        rows = groups[owner]
        if not rows:
            continue
        spend = sum(j.perf.spend for j in rows)
        revenue = sum(j.perf.revenue for j in rows)
        md.append(
            f"| {ownership.labels[owner]} | {len(rows)} | {spend:,.0f} | {revenue:,.0f} "
            f"| {(revenue / spend if spend else 0):.2f} "
            f"| {sum(1 for j in rows if j.verdict == Verdict.KILL)} "
            f"| {sum(1 for j in rows if j.verdict == Verdict.SCALE)} |"
        )

    kills = [j for j in judgements if j.verdict == Verdict.KILL]
    if kills:
        md += ["", "## 중단 제안", "",
               f"아래 {len(kills)}개는 목표 ROAS 미달이 통계적으로 확실합니다. "
               f"해당 기간 지출 {sum(j.perf.spend for j in kills):,.0f} {currency}.", "",
               "| 구분 | 광고 | 지출 | ROAS | 신뢰구간 | 구매 | 판단 근거 |",
               "|---|---|---:|---:|---|---:|---|"]
        for j in kills:
            md.append(
                f"| {ownership.label(j.perf.campaign_name)} | `{j.perf.ad_name}` "
                f"| {j.perf.spend:,.0f} | {j.interval.point:.2f} "
                f"| {j.interval.lower:.2f}~{j.interval.upper:.2f} | {j.perf.purchases} | {j.reason} |"
            )

    scales = [j for j in judgements if j.verdict == Verdict.SCALE]
    if scales:
        md += ["", "## 확장 제안", "",
               "| 구분 | 광고 | 지출 | ROAS | 신뢰구간 | 구매 |", "|---|---|---:|---:|---|---:|"]
        for j in scales:
            md.append(
                f"| {ownership.label(j.perf.campaign_name)} | `{j.perf.ad_name}` "
                f"| {j.perf.spend:,.0f} | {j.interval.point:.2f} "
                f"| {j.interval.lower:.2f}~{j.interval.upper:.2f} | {j.perf.purchases} |"
            )

    if dna_report and dna_report.axes:
        md += ["", "## 무엇이 이겼나", "",
               f"기준선 ROAS {dna_report.baseline_roas:.2f}. "
               "광고 단위가 아니라 소재 속성 단위로 묶어서 본 결과입니다.", ""]
        labels = {"copy": "카피 앵글", "object": "오브제", "creative_type": "소재유형"}
        for axis, label in labels.items():
            rows = dna_report.top(axis, n=5, min_ads=2)
            if not rows:
                continue
            md += [f"### {label}", "", "| 값 | 광고 수 | 지출 | ROAS | 신뢰구간 | 비고 |",
                   "|---|---:|---:|---:|---|---|"]
            for lv in rows:
                note = "다른 축과 항상 함께 등장 — 단독 효과로 읽지 말 것" if lv.confounded else ""
                md.append(
                    f"| {lv.value} | {lv.ads} | {lv.spend:,.0f} | {lv.roas:.2f} "
                    f"| {lv.interval.lower:.2f}~{lv.interval.upper:.2f} | {note} |"
                )
            md.append("")

    md += ["", "---", "",
           "### 판정 기준", "",
           "관측 ROAS만으로 자르지 않습니다. 구매 건수가 적으면 ROAS는 크게 흔들리기 때문입니다. "
           "구매 건수를 포아송 분포로 보고 ROAS 신뢰구간을 만든 뒤, **구간 전체가 목표선 아래일 때만** "
           "중단을 제안합니다.", "",
           "- 중단 제안: 신뢰구간 상단 < 목표 ROAS (목표 미달이 확실)",
           "- 확장 제안: 신뢰구간 하단 ≥ 확장선 (목표 초과가 확실)",
           "- 판정 보류: 지출·노출·기간이 판정하기에 아직 모자람", "",
           "이 보고서는 **제안**이며, 광고 상태를 자동으로 바꾸지 않습니다."]
    return "\n".join(md)


def write_markdown(text: str, path: Path | str) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p
