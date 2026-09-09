"""브라우저에서 볼 수 있는 HTML 보고서.

터미널 출력은 운영자 본인에게는 충분하지만, 대행사나 상급자에게 보내기에는 부적절하다.
파일 하나로 완결되게 만들어(외부 로딩 없음) 더블클릭하면 열리고, 그대로 인쇄·PDF도 되게 한다.

시각화 원칙
    · 판정은 상태(status) 색을 쓰되 색만으로는 절대 읽히지 않게 한다.
      빨강↔초록은 색각 이상에서 구분되지 않는다(ΔE 4.1). 그래서 모든 판정에
      아이콘 + 한글 라벨 + 숫자를 함께 둔다.
    · ROAS 신뢰구간은 이 도구의 핵심 논리다. 숫자로만 두지 않고 목표선 대비
      막대 위치로 보여준다. "구간 전체가 목표선 왼쪽" 이 한눈에 보여야 한다.
"""

from __future__ import annotations

import html as _html
from datetime import datetime
from pathlib import Path

from .dna import DnaReport
from .judge import Judgement, Verdict, summarize

# 팔레트 — dataviz 레퍼런스 인스턴스
_CSS = """
:root {
  color-scheme: light;
  --surface: #fcfcfb;
  --plane: #f9f9f7;
  --ink: #0b0b0b;
  --ink-2: #52514e;
  --muted: #898781;
  --grid: #e1e0d9;
  --axis: #c3c2b7;
  --border: rgba(11,11,11,0.10);
  --good: #0ca30c;
  --critical: #d03b3b;
  --warning: #fab219;
  --neutral: #2a78d6;
  --track: #ececE6;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --surface: #1a1a19; --plane: #0d0d0d; --ink: #ffffff; --ink-2: #c3c2b7;
    --muted: #898781; --grid: #2c2c2a; --axis: #383835;
    --border: rgba(255,255,255,0.10); --neutral: #3987e5; --track: #2c2c2a;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--plane); color: var(--ink);
  font: 15px/1.6 system-ui, -apple-system, "Segoe UI", "Malgun Gothic", sans-serif;
  -webkit-font-smoothing: antialiased;
}
.wrap { max-width: 1000px; margin: 0 auto; padding: 40px 24px 80px; }
header { margin-bottom: 32px; }
h1 { font-size: 26px; font-weight: 650; margin: 0 0 6px; letter-spacing: -0.01em; }
.sub { color: var(--muted); font-size: 13px; }
h2 {
  font-size: 15px; font-weight: 650; margin: 40px 0 14px; letter-spacing: 0.02em;
  padding-bottom: 8px; border-bottom: 1px solid var(--grid);
}
h3 { font-size: 13px; font-weight: 600; color: var(--ink-2); margin: 22px 0 8px; }
p { margin: 0 0 12px; color: var(--ink-2); font-size: 14px; }

.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1px;
        background: var(--border); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.kpi { background: var(--surface); padding: 16px 18px; }
.kpi .label { font-size: 11px; color: var(--muted); letter-spacing: 0.04em; margin-bottom: 6px; }
.kpi .value { font-size: 24px; font-weight: 600; letter-spacing: -0.02em; }
.kpi .value.hero { font-size: 34px; }
.kpi .note { font-size: 11px; color: var(--muted); margin-top: 3px; }

.callout { background: var(--surface); border: 1px solid var(--border);
           border-left: 3px solid var(--warning); border-radius: 6px; padding: 14px 16px; margin: 16px 0; }
.callout .title { font-weight: 600; font-size: 13px; margin-bottom: 8px; }

table { width: 100%; border-collapse: collapse; font-size: 13px; }
.scroll { overflow-x: auto; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; }
th { text-align: left; font-weight: 600; font-size: 11px; color: var(--muted);
     letter-spacing: 0.04em; padding: 10px 12px; border-bottom: 1px solid var(--grid); white-space: nowrap; }
td { padding: 10px 12px; border-bottom: 1px solid var(--grid); vertical-align: middle; }
tr:last-child td { border-bottom: none; }
.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.name { font-family: ui-monospace, "Cascadia Mono", Consolas, monospace; font-size: 11.5px;
        color: var(--ink-2); word-break: break-all; min-width: 260px; }

.tag { display: inline-flex; align-items: center; gap: 5px; font-size: 12px;
       font-weight: 600; white-space: nowrap; }
.tag .ico { font-size: 11px; width: 14px; text-align: center; }
.tag.good { color: var(--good); }
.tag.crit { color: var(--critical); }
.tag.neut { color: var(--ink-2); }
.tag.mute { color: var(--muted); }
.chip { display: inline-block; font-size: 11px; padding: 1px 7px; border-radius: 10px;
        border: 1px solid var(--border); color: var(--muted); white-space: nowrap; }

/* ROAS 신뢰구간 막대 — 목표선 대비 위치가 핵심 */
.iv { position: relative; height: 22px; min-width: 190px; }
.iv .track { position: absolute; inset: 9px 0 auto 0; height: 4px; background: var(--track); border-radius: 2px; }
.iv .range { position: absolute; top: 9px; height: 4px; border-radius: 2px; background: var(--neutral); opacity: 0.42; }
.iv .range.good { background: var(--good); }
.iv .range.crit { background: var(--critical); }
.iv .dot { position: absolute; top: 5px; width: 12px; height: 12px; border-radius: 50%;
           margin-left: -6px; background: var(--neutral); border: 2px solid var(--surface); }
.iv .dot.good { background: var(--good); }
.iv .dot.crit { background: var(--critical); }
.iv .target { position: absolute; top: 3px; bottom: 3px; width: 2px; background: var(--axis); }
.iv .cap { position: absolute; top: 4px; font-size: 10px; color: var(--muted); }
.legend { display: flex; flex-wrap: wrap; gap: 16px; font-size: 11.5px; color: var(--muted); margin: 10px 0 4px; }
.legend .k { display: inline-flex; align-items: center; gap: 6px; }
.swatch { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }

.axisrow { display: grid; grid-template-columns: 120px 1fr 62px 46px; gap: 12px;
           align-items: center; padding: 7px 0; border-bottom: 1px solid var(--grid); }
.axisrow:last-child { border-bottom: none; }
.axisrow .lab { font-size: 13px; font-weight: 550; }
.axisrow .meta { font-size: 11px; color: var(--muted); text-align: right; font-variant-numeric: tabular-nums; }
.warnflag { color: var(--warning); font-size: 11px; }

footer { margin-top: 48px; padding-top: 20px; border-top: 1px solid var(--grid);
         font-size: 12px; color: var(--muted); }
footer code { background: var(--surface); padding: 1px 5px; border-radius: 3px;
              border: 1px solid var(--border); font-size: 11px; }
@media print {
  body { background: #fff; }
  .wrap { max-width: none; padding: 0; }
  h2 { break-after: avoid; }
  tr, .axisrow { break-inside: avoid; }
}
"""


def _esc(v) -> str:
    return _html.escape(str(v))


def _fmt(v: float) -> str:
    return f"{v:,.0f}"


_TAG = {
    Verdict.SCALE: ("good", "▲", "확장 제안"),
    Verdict.KEEP: ("neut", "·", "유지"),
    Verdict.INSUFFICIENT: ("mute", "…", "판정 보류"),
    Verdict.KILL: ("crit", "✕", "중단 제안"),
}


def _tag(verdict: Verdict) -> str:
    cls, ico, label = _TAG[verdict]
    return f'<span class="tag {cls}"><span class="ico">{ico}</span>{label}</span>'


def _interval_bar(point: float, lower: float, upper: float,
                  target: float, scale: float, vmax: float) -> str:
    """신뢰구간 막대. 목표선을 넘는지 아닌지가 위치로 읽혀야 한다."""
    def pct(v: float) -> float:
        return max(0.0, min(100.0, v / vmax * 100.0))

    tone = "crit" if upper < target else ("good" if lower >= scale else "")
    lo, hi = pct(lower), pct(min(upper, vmax))
    over = ' <span class="cap" style="right:0">▸</span>' if upper > vmax else ""
    return (
        f'<div class="iv">'
        f'<div class="track"></div>'
        f'<div class="range {tone}" style="left:{lo:.1f}%;width:{max(hi - lo, 0.8):.1f}%"></div>'
        f'<div class="target" style="left:{pct(target):.1f}%"></div>'
        f'<div class="dot {tone}" style="left:{pct(point):.1f}%"></div>{over}'
        f"</div>"
    )


def render(
    judgements: list[Judgement],
    dna_report: DnaReport | None,
    ownership,
    period: str = "",
    currency: str = "KRW",
    excluded: list[tuple] | None = None,
    rules: dict | None = None,
) -> str:
    from .ownership import Owner
    from .scope import summarize_excluded

    rules = rules or {}
    target = float(rules.get("targets", {}).get("target_roas", 2.0))
    scale = float(rules.get("targets", {}).get("scale_roas", 2.5))
    level = float(rules.get("confidence", {}).get("level", 0.80))

    s = summarize(judgements)
    total_spend = sum(r["spend"] for r in s.values())
    total_rev = sum(r["revenue"] for r in s.values())
    total_roas = total_rev / total_spend if total_spend else 0.0
    kills = [j for j in judgements if j.verdict == Verdict.KILL]
    scales = [j for j in judgements if j.verdict == Verdict.SCALE]

    # 막대 눈금 상한 — 표 전체가 같은 눈금을 써야 비교가 된다
    bounds = [j.interval.upper for j in judgements if j.interval.upper != float("inf")]
    vmax = max(4.0, min(8.0, (max(bounds) if bounds else 4.0)))

    o: list[str] = []
    o.append(f'<h1>소재 성과 판정 보고서</h1>')
    o.append(f'<div class="sub">{_esc(period)} · 생성 {datetime.now():%Y-%m-%d %H:%M}</div>')

    # KPI
    o.append('<div class="kpis" style="margin-top:24px">')
    o.append(f'<div class="kpi"><div class="label">판정 대상 ROAS</div>'
             f'<div class="value hero">{total_roas:.2f}</div>'
             f'<div class="note">목표 {target:.2f} · 확장선 {scale:.2f}</div></div>')
    o.append(f'<div class="kpi"><div class="label">지출</div><div class="value">{_fmt(total_spend)}</div>'
             f'<div class="note">{_esc(currency)}</div></div>')
    o.append(f'<div class="kpi"><div class="label">매출</div><div class="value">{_fmt(total_rev)}</div>'
             f'<div class="note">{_esc(currency)}</div></div>')
    o.append(f'<div class="kpi"><div class="label">판정 대상 광고</div>'
             f'<div class="value">{len(judgements)}</div>'
             f'<div class="note">중단 제안 {len(kills)} · 확장 제안 {len(scales)}</div></div>')
    o.append("</div>")

    # 판정 제외
    if excluded:
        ex_spend = sum(p.spend for p, _ in excluded)
        o.append('<div class="callout"><div class="title">판정 제외 '
                 f'{len(excluded)}개 · 지출 {_fmt(ex_spend)} {_esc(currency)}</div>')
        o.append('<table><tbody>')
        for b in summarize_excluded(excluded):
            o.append(f'<tr><td class="num" style="width:56px">{b["count"]}개</td>'
                     f'<td class="num" style="width:120px">{_fmt(b["spend"])}</td>'
                     f'<td>{_esc(b["reason"])}</td></tr>')
        o.append("</tbody></table>")
        o.append('<p style="margin:10px 0 0;font-size:12px">전환을 측정할 수 없는 캠페인입니다. '
                 "ROAS 계산과 판정에서 제외했고, 지출만 참고로 표기합니다.</p></div>")

    # 판정 요약
    o.append("<h2>판정 요약</h2>")
    o.append('<div class="scroll"><table><thead><tr><th>판정</th><th class="num">개수</th>'
             '<th class="num">지출</th><th class="num">매출</th><th class="num">ROAS</th>'
             '<th class="num">구매</th></tr></thead><tbody>')
    for v in (Verdict.SCALE, Verdict.KEEP, Verdict.INSUFFICIENT, Verdict.KILL):
        r = s[v.value]
        o.append(f"<tr><td>{_tag(v)}</td><td class='num'>{r['count']}</td>"
                 f"<td class='num'>{_fmt(r['spend'])}</td><td class='num'>{_fmt(r['revenue'])}</td>"
                 f"<td class='num'>{r['roas']:.2f}</td><td class='num'>{r['purchases']}</td></tr>")
    o.append("</tbody></table></div>")

    # 소유별
    groups = ownership.split(judgements, key=lambda j: j.perf.campaign_name)
    shown = [(ow, rows) for ow in (Owner.MINE, Owner.AGENCY, Owner.UNKNOWN) if (rows := groups[ow])]
    if len(shown) > 1:
        o.append("<h2>캠페인 소유별</h2>")
        o.append('<div class="scroll"><table><thead><tr><th>구분</th><th class="num">광고</th>'
                 '<th class="num">지출</th><th class="num">매출</th><th class="num">ROAS</th>'
                 '<th class="num">중단 제안</th><th class="num">확장 제안</th></tr></thead><tbody>')
        for owner, rows in shown:
            sp = sum(j.perf.spend for j in rows)
            rv = sum(j.perf.revenue for j in rows)
            o.append(
                f"<tr><td>{_esc(ownership.labels[owner])}</td><td class='num'>{len(rows)}</td>"
                f"<td class='num'>{_fmt(sp)}</td><td class='num'>{_fmt(rv)}</td>"
                f"<td class='num'>{(rv / sp if sp else 0):.2f}</td>"
                f"<td class='num'>{sum(1 for j in rows if j.verdict == Verdict.KILL)}</td>"
                f"<td class='num'>{sum(1 for j in rows if j.verdict == Verdict.SCALE)}</td></tr>"
            )
        o.append("</tbody></table></div>")

    legend = (
        '<div class="legend">'
        f'<span class="k"><span class="swatch" style="background:var(--critical)"></span>구간 전체가 목표({target:.1f}) 미만 — 중단 제안</span>'
        f'<span class="k"><span class="swatch" style="background:var(--good)"></span>구간 전체가 확장선({scale:.1f}) 이상 — 확장 제안</span>'
        '<span class="k"><span class="swatch" style="background:var(--neutral);opacity:.45"></span>목표선을 걸침 — 판단 유보</span>'
        '<span class="k">│ 세로선 = 목표 ROAS</span>'
        "</div>"
    )

    def _ad_table(rows: list[Judgement], title: str, why: str) -> None:
        o.append(f"<h2>{_esc(title)}</h2>")
        o.append(f"<p>{why}</p>")
        o.append(legend)
        o.append('<div class="scroll"><table><thead><tr><th>구분</th><th>광고</th>'
                 f'<th style="min-width:190px">ROAS 신뢰구간 ({level:.0%})</th>'
                 '<th class="num">ROAS</th><th class="num">지출</th><th class="num">구매</th>'
                 "</tr></thead><tbody>")
        for j in rows:
            iv = j.interval
            o.append(
                f'<tr><td><span class="chip">{_esc(ownership.label(j.perf.campaign_name))}</span></td>'
                f'<td class="name">{_esc(j.perf.ad_name)}</td>'
                f"<td>{_interval_bar(iv.point, iv.lower, iv.upper, target, scale, vmax)}</td>"
                f'<td class="num">{iv.point:.2f}<div style="font-size:10.5px;color:var(--muted)">'
                f'{iv.lower:.2f}~{iv.upper:.2f}</div></td>'
                f'<td class="num">{_fmt(j.perf.spend)}</td>'
                f'<td class="num">{j.perf.purchases}</td></tr>'
            )
        o.append("</tbody></table></div>")

    if kills:
        _ad_table(kills, f"중단 제안 {len(kills)}개",
                  f"신뢰구간 상단이 목표 ROAS {target:.2f} 에 못 미칩니다. 목표 미달이 통계적으로 확실합니다. "
                  f"해당 기간 지출 <strong>{_fmt(sum(j.perf.spend for j in kills))} {_esc(currency)}</strong>.")
    if scales:
        _ad_table(scales, f"확장 제안 {len(scales)}개",
                  f"신뢰구간 하단이 확장선 {scale:.2f} 이상입니다. 목표 초과가 통계적으로 확실합니다.")

    # 승자 축
    if dna_report and dna_report.axes:
        o.append("<h2>무엇이 이겼나</h2>")
        o.append(f"<p>광고 하나씩이 아니라 소재 속성 단위로 묶어서 본 결과입니다. 묶으면 표본이 커져 "
                 f"구간이 좁아지고, 개별 광고로는 안 보이던 차이가 드러납니다. "
                 f"기준선 ROAS <strong>{dna_report.baseline_roas:.2f}</strong>.</p>")
        o.append(legend)
        labels = {"copy": "카피 앵글", "object": "오브제", "creative_type": "소재유형",
                  "product": "상품", "promo": "프로모션"}
        for axis, label in labels.items():
            rows = dna_report.top(axis, n=8, min_ads=2)
            if len(rows) < 2:
                continue
            o.append(f"<h3>{_esc(label)}</h3>")
            o.append('<div class="scroll" style="padding:6px 14px">')
            for lv in rows:
                iv = lv.interval
                flag = ('<span class="warnflag" title="다른 축과 항상 함께 등장 — 단독 효과로 읽지 마세요">⚠</span>'
                        if lv.confounded else "")
                o.append(
                    f'<div class="axisrow"><div class="lab">{_esc(lv.value)} {flag}</div>'
                    f"<div>{_interval_bar(iv.point, iv.lower, iv.upper, target, scale, vmax)}</div>"
                    f'<div class="meta">{_fmt(lv.spend)}</div>'
                    f'<div class="meta" style="color:var(--ink);font-weight:600">{lv.roas:.2f}</div></div>'
                )
            o.append("</div>")
        if dna_report.unparsed:
            o.append(f'<p style="font-size:12px">네이밍 규칙을 벗어나 이 분석에서 빠진 광고 '
                     f"{len(dna_report.unparsed)}개가 있습니다.</p>")

    o.append("<h2>판정 기준</h2>")
    o.append(
        "<p>관측 ROAS만으로 자르지 않습니다. 구매 건수가 적으면 ROAS는 크게 흔들리기 때문입니다. "
        "구매 건수를 포아송 분포로 보고 ROAS 신뢰구간을 만든 뒤, "
        "<strong>구간 전체가 목표선 아래일 때만</strong> 중단을 제안합니다.</p>"
    )
    o.append(
        f"<p>같은 ROAS 1.40이라도 구매 3건이면 실제 구간이 0.51~3.11이라 판단을 미루고, "
        f"구매 20건이면 1.02~1.89라 중단을 제안합니다. 표본이 작은 소재를 노이즈로 죽이지 않기 위한 장치입니다.</p>"
    )
    o.append(
        '<footer>이 보고서는 <strong>제안</strong>이며, 광고 상태를 자동으로 바꾸지 않습니다. '
        "roasloop 은 판정과 실행을 분리합니다 — 판정·보고 명령은 계정을 읽기만 하고, "
        "실제 변경은 내 캠페인으로 지정한 대상에만 별도 명령으로 이루어집니다."
        f"<br><br>신뢰수준 {level:.0%} · 목표 ROAS {target:.2f} · 확장선 {scale:.2f} · "
        "설정 <code>config/rules.yaml</code></footer>"
    )

    return (
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>소재 성과 판정 보고서 {_esc(period)}</title><style>{_CSS}</style></head>"
        f"<body><div class='wrap'>{''.join(o)}</div></body></html>"
    )


def write(text: str, path: Path | str) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p
