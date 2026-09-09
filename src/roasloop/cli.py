"""roasloop CLI.

루프 한 바퀴:

    roasloop plan     조합 매트릭스 전개 → 발행 명세 CSV (+ 아직 소재가 없는 조합 목록)
    roasloop launch   명세대로 Meta 에 대량 생성 (기본 dry-run · 기본 PAUSED)
    roasloop harvest  성과 수집 → data/runs/<날짜>/perf.json
    roasloop doctor   설정이 제대로 됐는지 점검 (막히면 이것부터)
    roasloop judge    ROAS 컷 판정 → 표 + CSV
    roasloop campaigns 캠페인 목록과 소유 분류 확인
    roasloop report   대행사·상급자에게 공유할 보고서 (마크다운)
    roasloop dna      살아남은 축 분석 → 다음 라운드 축
    roasloop breed    승자 DNA → 새 카피·기획안 → matrix 블록
    roasloop apply    중단 제안을 실제로 반영 (내 캠페인만, --yes 필요)

roasloop 은 어떤 명령에서도 저절로 광고를 끄지 않는다. judge/report 는 읽기 전용이고,
계정을 바꾸는 것은 launch 와 apply 둘뿐이며 둘 다 config/ownership.yaml 의
mine 에 걸린 캠페인에만 동작한다.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path

from . import report as rp
from .config import Config, MetaCredentials
from .judge import AdPerformance, Verdict, judge_all

RUNS = Path("data/runs")
HISTORY = Path("data/history.txt")


def _log(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )


def _read_text_tolerant(path: Path) -> str:
    """윈도우 메모장이 저장한 파일도 읽는다.

    메모장은 저장 옵션에 따라 UTF-8(BOM 포함) 또는 ANSI(한국어 윈도우에서는 CP949)로
    저장한다. utf-8 로만 읽으면 한글 주석이 들어간 ANSI 파일에서 그대로 터진다.
    """
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def _load_env() -> None:
    """.env 를 있으면 읽는다 (python-dotenv 없이)."""
    p = Path(".env")
    if not p.exists():
        return
    for line in _read_text_tolerant(p).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        value = v.split("#")[0].strip()
        # 값을 따옴표로 감싸는 습관이 흔하다. 벗겨서 넣는다.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1].strip()
        if value:
            os.environ.setdefault(k.strip(), value)


def _run_dir(stamp: str | None = None) -> Path:
    d = RUNS / (stamp or datetime.now().strftime("%Y%m%d"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _latest_run() -> Path:
    if not RUNS.exists() or not any(RUNS.iterdir()):
        sys.exit("성과 데이터가 없습니다. 먼저 `roasloop harvest` 를 실행하세요.")
    return sorted(RUNS.iterdir())[-1]


def _load_perf(path: Path) -> list[AdPerformance]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [AdPerformance(**row) for row in data]


def _scoped(run: Path, cfg: Config) -> tuple[list[AdPerformance], list[tuple]]:
    """판정 대상만 남기고, 제외된 것은 사유와 함께 돌려준다.

    harvest 는 계정 전체를 그대로 저장한다. 범위를 좁히는 것은 판정 시점의 일이라
    설정을 바꿔도 데이터를 다시 받을 필요가 없다.
    """
    perfs = _load_perf(run / "perf.json")
    return cfg.scope.split(perfs, key=lambda p: p.campaign_name)


def _print_excluded(dropped: list[tuple], currency: str) -> None:
    if not dropped:
        return
    from .scope import summarize_excluded

    total = sum(p.spend for p, _ in dropped)
    print(f"■ 판정 제외 {len(dropped)}개 · 지출 {total:,.0f} {currency}")
    for b in summarize_excluded(dropped):
        print(f"    {b['count']:>3}개  {b['spend']:>12,.0f}   {b['reason']}")
    print("    (전환을 측정할 수 없는 캠페인입니다. ROAS 계산에서 뺐습니다)")
    print()


# --------------------------------------------------------------------- 명령들
def cmd_plan(args, cfg: Config) -> None:
    from .matrix import expand, load_history, write_csv

    matrix = cfg.matrix
    if args.matrix:
        import yaml
        matrix = yaml.safe_load(Path(args.matrix).read_text(encoding="utf-8"))
    if not matrix:
        sys.exit("매트릭스가 없습니다. config/matrix.yaml 을 만들거나 --matrix 로 지정하세요.")

    plan = expand(
        matrix, cfg,
        live_date=date.fromisoformat(args.live_date) if args.live_date else None,
        history=load_history(HISTORY) if not args.allow_duplicates else set(),
        limit=args.limit,
    )

    out = _run_dir(args.stamp) / f"plan_{plan.round_id}.csv"
    write_csv(plan.specs, out)

    print(f"라운드 {plan.round_id} — 조합 {len(plan.specs)}개")
    print(f"  발행 가능   {len(plan.ready)}개 (소재·카피 준비됨)")
    print(f"  제작 대기   {len(plan.pending)}개")
    if plan.skipped_duplicates:
        print(f"  중복 제외   {len(plan.skipped_duplicates)}개 (이미 집행한 조합)")
    if plan.invalid:
        print(f"  규칙 위반   {len(plan.invalid)}개")
        for values, err in plan.invalid[:5]:
            print(f"    {err}")
    print(f"\n→ {out}")

    if plan.pending and args.show_pending:
        print("\n[제작 대기 — 이 조합들의 소재를 만들어 assets 에 연결하세요]")
        for s in plan.pending[:40]:
            print(f"  {s.ad_name}  ← 부족: {', '.join(s.missing)}")


def cmd_launch(args, cfg: Config) -> None:
    import csv as _csv

    from .matrix import AdSpec, append_history
    from .meta.client import MetaClient
    from .meta.launch import Launcher

    with Path(args.plan).open(encoding="utf-8-sig") as fh:
        specs = [AdSpec(**row) for row in _csv.DictReader(fh)]

    creds = MetaCredentials.from_env()
    client = MetaClient(creds.access_token, creds.ad_account_id)
    adset_configs = {
        a["name"]: a for a in (cfg.matrix.get("adset_settings") or [])
    } if cfg.matrix else {}

    launcher = Launcher(
        client, creds.page_id, creds.pixel_id, creds.instagram_id,
        dry_run=not args.execute,
        status="ACTIVE" if args.activate else "PAUSED",
        ownership=cfg.ownership,
    )
    result = launcher.launch(
        specs, adset_configs,
        campaign_objective=cfg.defaults.get("objective", "Conversion"),
        campaign_budget=args.campaign_budget,
    )

    ready = [s for s in specs if s.ready]
    skipped = len(specs) - len(ready)
    if not args.execute:
        print(f"[DRY RUN] 생성 예정 {len(result.planned)}개 / 소재 미비로 제외 {skipped}개\n")
        for line in result.planned[:50]:
            print("  " + line)
        if len(result.planned) > 50:
            print(f"  ... 외 {len(result.planned) - 50}개")
        print("\n실제로 만들려면 --execute 를 붙이세요. 광고는 PAUSED 로 생성됩니다.")
        return

    print(f"생성 완료 {len(result.created_ads)}개 / 실패 {len(result.failures)}개 / 제외 {skipped}개")
    for name, err in result.failures:
        print(f"  ✕ {name}\n    {err}")
    if result.created_ads:
        append_history(HISTORY, [n for n, _ in result.created_ads])
        print(f"\n상태: {'ACTIVE' if args.activate else 'PAUSED'}. "
              f"{'' if args.activate else 'Ads Manager 에서 확인 후 켜세요.'}")


def cmd_harvest(args, cfg: Config) -> None:
    from dataclasses import asdict

    from .meta import insights
    from .meta.client import MetaClient

    creds = MetaCredentials.from_env()
    client = MetaClient(creds.access_token, creds.ad_account_id)

    if args.since and args.until:
        since, until = date.fromisoformat(args.since), date.fromisoformat(args.until)
    else:
        since, until = insights.default_window(args.days)

    perfs = insights.fetch(
        client, since, until,
        action_types=cfg.conversion.get("action_types", ["omni_purchase", "purchase"]),
        attribution_windows=cfg.conversion.get("attribution_windows"),
        campaign_filter=args.campaign,
    )
    if perfs and not args.skip_age:
        # 광고 나이는 게이트 정확도를 높이는 보조 정보다. 여기서 실패해도 성과 수집은 살린다.
        try:
            ages = insights.fetch_days_active(client, [p.ad_id for p in perfs if p.ad_id])
            insights.apply_true_age(perfs, ages)
        except Exception as exc:                    # noqa: BLE001
            print(f"참고: 광고 생성일 조회를 건너뜁니다 ({exc})")
            print("      조회 기간을 그대로 가동 일수로 씁니다. 최근 만든 광고가")
            print("      실제보다 오래 돌아간 것처럼 잡힐 수 있습니다.")

    out = _run_dir(args.stamp) / "perf.json"
    out.write_text(
        json.dumps([asdict(p) for p in perfs], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    spend = sum(p.spend for p in perfs)
    revenue = sum(p.revenue for p in perfs)
    print(f"{since} ~ {until} · 광고 {len(perfs)}개")
    print(f"지출 {spend:,.0f} / 매출 {revenue:,.0f} / ROAS {(revenue / spend if spend else 0):.2f}")
    print(f"→ {out}")


def cmd_judge(args, cfg: Config) -> None:
    run = Path(args.run) if args.run else _latest_run()
    perfs, dropped = _scoped(run, cfg)
    if not perfs:
        sys.exit("판정 대상이 없습니다. config/rules.yaml 의 measurement 설정을 확인하세요.")
    judgements = judge_all(perfs, cfg.rules)
    own = cfg.ownership

    _print_excluded(dropped, cfg.currency)
    print(rp.judgement_summary(judgements, cfg.currency))
    print()
    print(rp.ownership_summary(judgements, own, cfg.currency))
    print()
    print(rp.action_list(judgements, own, cfg.currency))
    if not args.brief:
        print()
        print(rp.judgement_table(judgements, cfg.currency, limit=args.limit))

    out = rp.write_judgements_csv(judgements, run / "judgement.csv")
    mine_kills = [
        j.perf.ad_id for j in judgements
        if j.verdict == Verdict.KILL and own.is_mine(j.perf.campaign_name)
    ]
    (run / "kill_ids_mine.txt").write_text("\n".join(mine_kills), encoding="utf-8")
    print(f"\n→ {out}")
    print("\n※ 이 명령은 광고 상태를 바꾸지 않습니다. 위 목록은 제안입니다.")
    if mine_kills:
        print(f"   내 캠페인 중단 제안 {len(mine_kills)}개는 `roasloop apply --yes` 로 반영할 수 있습니다.")


def _mask(value: str, keep: int = 4) -> str:
    """토큰을 화면에 띄울 때 쓰는 마스킹. 스크린샷으로 유출되지 않게 한다."""
    if not value:
        return "(비어 있음)"
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}{'*' * 12}{value[-keep:]}  (길이 {len(value)})"


def cmd_doctor(args, cfg: Config) -> None:
    """설정이 제대로 됐는지 점검한다. 문제가 있으면 무엇을 고쳐야 하는지 알려준다."""
    from .meta.client import MetaAPIError, MetaClient
    from .ownership import Owner

    ok = "✓"
    bad = "✕"
    problems: list[str] = []

    print("■ 설정 파일")
    env_path = Path(".env")
    if env_path.exists():
        print(f"  {ok} .env 파일 있음 — {env_path.resolve()}")
    else:
        print(f"  {bad} .env 파일이 없습니다 (현재 위치: {Path.cwd()})")
        problems.append(".env 파일을 만드세요. .env.example 을 복사해서 이름을 .env 로 바꾸면 됩니다.")

    print("\n■ 환경변수")
    checks = [
        ("META_ACCESS_TOKEN", True, "EAA"),
        ("META_AD_ACCOUNT_ID", True, "act_"),
        ("META_PAGE_ID", False, ""),
        ("META_PIXEL_ID", False, ""),
        ("ANTHROPIC_API_KEY", False, "sk-ant-"),
    ]
    for name, required, prefix in checks:
        value = os.environ.get(name, "")
        if not value:
            mark = bad if required else "-"
            note = " (필수)" if required else " (지금은 없어도 됩니다)"
            print(f"  {mark} {name}: 비어 있음{note}")
            if required:
                problems.append(f"{name} 를 .env 에 채우세요.")
            continue

        issues = []
        if value != value.strip():
            issues.append("앞뒤 공백")
        if value[:1] in {'"', "'"} or value[-1:] in {'"', "'"}:
            issues.append("따옴표")
        if " " in value:
            issues.append("중간 공백")
        if prefix and not value.startswith(prefix):
            issues.append(f"'{prefix}' 로 시작하지 않음")
        if name == "META_ACCESS_TOKEN" and len(value) < 100:
            issues.append("길이가 너무 짧음 — 예시 문구가 그대로 들어있지 않은지 확인")

        if issues:
            print(f"  {bad} {name}: {_mask(value)}  ← {', '.join(issues)}")
            problems.append(f"{name} 값을 고치세요: {', '.join(issues)}")
        else:
            print(f"  {ok} {name}: {_mask(value)}")

    print("\n■ Meta API 연결")
    try:
        creds = MetaCredentials.from_env()
        client = MetaClient(creds.access_token, creds.ad_account_id, max_retries=0)
        me = client.get(creds.ad_account_id, {"fields": "name,account_status,currency,timezone_name"})
        print(f"  {ok} 광고 계정 접속 성공")
        print(f"      이름 {me.get('name')} · 통화 {me.get('currency')} · 시간대 {me.get('timezone_name')}")
        if str(me.get("account_status")) != "1":
            print(f"      ⚠ 계정 상태 코드 {me.get('account_status')} — 활성 상태가 아닐 수 있습니다")
        if me.get("currency") and me["currency"] != cfg.currency:
            print(f"      ⚠ config/account.yaml 의 통화는 {cfg.currency} 인데 계정은 {me['currency']} 입니다")
            problems.append(f"config/account.yaml 의 currency 를 {me['currency']} 로 맞추세요.")
    except MetaAPIError as exc:
        print(f"  {bad} 접속 실패 — {exc}")
        if exc.code == 190:
            problems.append("토큰이 잘못됐거나 만료됐습니다. 그래프 API 탐색기에서 새로 발급하세요.")
        elif exc.code in (100, 200, 10):
            problems.append("토큰 권한이 모자랍니다. ads_read 권한을 넣어 다시 발급하세요.")
        else:
            problems.append("위 오류 메시지를 확인하세요.")
    except RuntimeError as exc:
        # 네트워크 오류의 원문은 길고 무섭게 생겼다. 핵심만 보여준다.
        msg = str(exc)
        if "연결 실패" in msg or "Max retries" in msg:
            print(f"  {bad} 서버에 연결하지 못했습니다 (인터넷 연결 / 사내 방화벽 확인)")
            problems.append("graph.facebook.com 에 연결되지 않습니다. 네트워크를 확인하세요.")
        else:
            print(f"  {bad} {msg.splitlines()[0]}")
            problems.append(msg.splitlines()[0])

    print("\n■ 캠페인 소유 설정")
    own = cfg.ownership
    if not cfg.ownership_config:
        print(f"  {bad} config/ownership.yaml 이 없습니다")
        problems.append("config/ownership.yaml 이 있어야 합니다.")
    else:
        mine_rules = len(cfg.ownership_config.get("mine") or [])
        agency_rules = len(cfg.ownership_config.get("agency") or [])
        print(f"  {ok if agency_rules else '-'} 대행사 규칙 {agency_rules}개")
        if mine_rules:
            print(f"  {ok} 내 캠페인 규칙 {mine_rules}개 — apply/launch 사용 가능")
        else:
            print("  - 내 캠페인 규칙 0개 — apply/launch 는 아무것도 건드리지 않습니다")
            print("    (판정과 보고서는 정상 동작합니다. `roasloop campaigns` 로 이름을 확인해 채우세요)")

    print()
    if problems:
        print(f"■ 고칠 것 {len(problems)}개")
        for i, msg in enumerate(problems, 1):
            print(f"  {i}. {msg}")
    else:
        print("■ 이상 없습니다. `roasloop campaigns` 로 넘어가세요.")


def cmd_campaigns(args, cfg: Config) -> None:
    """계정의 캠페인 목록과 현재 소유 분류. ownership.yaml 을 채울 때 쓴다."""
    from .meta.client import MetaClient
    from .ownership import Owner

    creds = MetaCredentials.from_env()
    client = MetaClient(creds.access_token, creds.ad_account_id)
    params = {"fields": "id,name,status,effective_status", "limit": 200}
    if not args.all:
        params["effective_status"] = '["ACTIVE","PAUSED"]'

    own = cfg.ownership
    rows = list(client.paged(client.account_path("campaigns"), params))
    rows.sort(key=lambda c: c.get("name", ""))

    groups: dict[Owner, list] = {o: [] for o in Owner}
    for c in rows:
        groups[own.classify(c.get("name", ""))].append(c)

    for owner in (Owner.MINE, Owner.AGENCY, Owner.UNKNOWN):
        items = groups[owner]
        if not items:
            continue
        mark = "변경 가능" if owner.actionable else "건드리지 않음"
        print(f"\n[{own.labels[owner]}] {len(items)}개 — {mark}")
        for c in items:
            print(f"  {c.get('effective_status', ''):<10} {c.get('name', '')}")
            print(f"  {'':<10} id={c.get('id')}")

    if groups[Owner.UNKNOWN]:
        print(f"\n※ 미분류 {len(groups[Owner.UNKNOWN])}개는 안전을 위해 건드리지 않습니다.")
        print("   내 캠페인이 맞다면 config/ownership.yaml 의 mine 에 이렇게 추가하세요:\n")
        for c in groups[Owner.UNKNOWN][:5]:
            print(f'     - name: "{c.get("name", "")}"')
    if not groups[Owner.MINE]:
        print("\n※ 내 캠페인으로 분류된 것이 없어 apply/launch 는 아무것도 하지 않습니다.")


def cmd_report(args, cfg: Config) -> None:
    """대행사·상급자에게 그대로 보낼 보고서를 만든다. 계정은 건드리지 않는다."""
    from . import dna as dna_mod

    run = Path(args.run) if args.run else _latest_run()
    perfs, dropped = _scoped(run, cfg)
    judgements = judge_all(perfs, cfg.rules)
    conf = cfg.rules.get("confidence", {})
    dna_report = None
    if not args.no_dna:
        dna_report = dna_mod.build(
            judgements,
            level=float(conf.get("level", 0.80)),
            fallback_aov=float(conf.get("fallback_aov", 0)),
        )

    period = args.period or run.name
    text = rp.markdown_report(
        judgements, dna_report, cfg.ownership,
        period=period, currency=cfg.currency, excluded=dropped,
    )
    md_out = rp.write_markdown(text, Path(args.out) if args.out else run / "report.md")

    from . import html as html_rp

    html_out = html_rp.write(
        html_rp.render(
            judgements, dna_report, cfg.ownership,
            period=period, currency=cfg.currency, excluded=dropped, rules=cfg.rules,
        ),
        (Path(args.out).with_suffix(".html") if args.out else run / "report.html"),
    )
    print(f"→ {html_out.resolve()}")
    print("   브라우저용. 이 파일을 더블클릭하면 열립니다. 인쇄하면 PDF 로도 됩니다.")
    print(f"→ {md_out}")
    print("   텍스트용. 메일이나 메신저에 붙여 넣을 때 씁니다.")
    if args.show:
        print()
        print(text)


def cmd_apply(args, cfg: Config) -> None:
    """중단 제안을 실제로 반영한다. 내 캠페인에만 동작한다."""
    from .meta.client import MetaClient
    from .meta.launch import pause_ads
    from .ownership import Owner

    run = Path(args.run) if args.run else _latest_run()
    perfs, _ = _scoped(run, cfg)
    judgements = judge_all(perfs, cfg.rules)
    own = cfg.ownership

    kills = [j for j in judgements if j.verdict == Verdict.KILL]
    groups = own.split(kills, key=lambda j: j.perf.campaign_name)
    mine, blocked = groups[Owner.MINE], groups[Owner.AGENCY] + groups[Owner.UNKNOWN]

    if blocked:
        print(f"■ 제외 {len(blocked)}개 — 내 캠페인이 아니라서 건드리지 않습니다")
        for j in blocked[:10]:
            print(f"    · [{own.label(j.perf.campaign_name)}] {j.perf.ad_name}")
        if len(blocked) > 10:
            print(f"    ... 외 {len(blocked) - 10}개")
        print("    → 이 항목들은 보고서로 공유하세요: roasloop report\n")

    if not mine:
        print("내 캠페인에는 중단 제안이 없습니다.")
        return

    spend = sum(j.perf.spend for j in mine)
    print(f"■ 중단 대상 {len(mine)}개 · 해당 기간 지출 {spend:,.0f} {cfg.currency}")
    for j in mine:
        print(f"    ✕ {j.perf.ad_name}")
        print(f"      ROAS {j.interval.point:.2f} (구간 {j.interval.lower:.2f}~{j.interval.upper:.2f}) "
              f"· 구매 {j.perf.purchases} · {j.reason}")

    if not args.yes:
        print("\n실제로 중단하려면 --yes 를 붙이세요. 지금은 아무것도 바뀌지 않았습니다.")
        return

    creds = MetaCredentials.from_env()
    ok, failed = pause_ads(MetaClient(creds.access_token, creds.ad_account_id),
                           [j.perf.ad_id for j in mine])
    print(f"\n중단 완료 {len(ok)}개 / 실패 {len(failed)}개")
    for ad_id, err in failed:
        print(f"  ✕ {ad_id}: {err}")


def cmd_dna(args, cfg: Config) -> None:
    from . import dna as dna_mod

    run = Path(args.run) if args.run else _latest_run()
    perfs, dropped = _scoped(run, cfg)
    _print_excluded(dropped, cfg.currency)
    judgements = judge_all(perfs, cfg.rules)
    conf = cfg.rules.get("confidence", {})
    report = dna_mod.build(
        judgements,
        level=float(conf.get("level", 0.80)),
        fallback_aov=float(conf.get("fallback_aov", 0)),
    )

    print(rp.dna_table(report, top=args.top, min_ads=args.min_ads))
    axes = dna_mod.next_round_axes(report, keep_top=args.keep_top, min_ads=args.min_ads)
    print("\n[다음 라운드 축 — matrix.yaml 의 creatives 에 넣으세요]")
    import yaml
    print(yaml.dump({"creatives": axes}, allow_unicode=True, sort_keys=False, indent=2))

    out = run / "dna.json"
    out.write_text(json.dumps({
        "baseline_roas": report.baseline_roas,
        "next_round_axes": axes,
        "unparsed": report.unparsed,
        "axes": {
            axis: [{
                "value": lv.value, "ads": lv.ads, "spend": lv.spend, "revenue": lv.revenue,
                "purchases": lv.purchases, "roas": lv.roas,
                "roas_lower": lv.interval.lower, "roas_upper": lv.interval.upper,
                "winners": lv.winners, "losers": lv.losers, "confounded": lv.confounded,
            } for lv in sorted(levels, key=lambda x: -x.spend)]
            for axis, levels in report.axes.items()
        },
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"→ {out}")


def cmd_breed(args, cfg: Config) -> None:
    from . import dna as dna_mod
    from .briefs import BriefRequest, dna_summary_from_report, generate, to_matrix_blocks

    run = Path(args.run) if args.run else _latest_run()
    perfs, _ = _scoped(run, cfg)
    judgements = judge_all(perfs, cfg.rules)
    conf = cfg.rules.get("confidence", {})
    report = dna_mod.build(judgements, level=float(conf.get("level", 0.80)),
                           fallback_aov=float(conf.get("fallback_aov", 0)))

    reviews = None
    if args.reviews and Path(args.reviews).exists():
        reviews = [l.strip() for l in Path(args.reviews).read_text(encoding="utf-8").splitlines() if l.strip()]

    req = BriefRequest(
        dna_summary=dna_summary_from_report(report, min_ads=args.min_ads),
        product=args.product,
        audience=args.audience,
        n=args.n,
        language=args.language,
        creative_types=args.creative_types,
        vary_axis=args.vary,
        reviews=reviews,
    )
    print(f"승자 DNA 로 소재 {args.n}개 설계 중...\n")
    batch = generate(req)

    for i, c in enumerate(batch.concepts, 1):
        print(f"── {i}. {c.copy_code} / {c.object_code} / {c.creative_type}")
        print(f"   앵글  {c.angle}")
        print(f"   본문  {c.primary_text}")
        print(f"   제목  {c.headline}   설명  {c.description}")
        print(f"   후킹  {c.hook_seconds}")
        for shot in c.shots:
            print(f"     · {shot}")
        print(f"   계승  {c.inherits}")
        print(f"   변주  {c.varies}\n")
    print(f"[설계 근거] {batch.reasoning}\n")

    import yaml
    blocks = to_matrix_blocks(batch)
    out_yaml = run / "next_matrix_blocks.yaml"
    out_yaml.write_text(yaml.dump(blocks, allow_unicode=True, sort_keys=False, indent=2), encoding="utf-8")
    out_json = run / "concepts.json"
    out_json.write_text(batch.model_dump_json(indent=2), encoding="utf-8")
    print(f"→ {out_yaml}  (matrix.yaml 에 붙여 넣으세요)")
    print(f"→ {out_json}  (제작 담당자에게 넘길 기획안)")


# ---------------------------------------------------------------------- 진입점
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="roasloop", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-c", "--config", help="설정 디렉터리 (기본 config/)")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("plan", help="조합 매트릭스 전개")
    sp.add_argument("--matrix", help="매트릭스 yaml 경로 (기본 config/matrix.yaml)")
    sp.add_argument("--live-date", help="라이브 일자 YYYY-MM-DD (기본 오늘)")
    sp.add_argument("--limit", type=int, help="최대 조합 수")
    sp.add_argument("--allow-duplicates", action="store_true", help="과거 집행 조합도 다시 만든다")
    sp.add_argument("--show-pending", action="store_true", help="소재 제작이 필요한 조합을 나열")
    sp.add_argument("--stamp", help="런 디렉터리 이름 (기본 오늘 날짜)")
    sp.set_defaults(func=cmd_plan)

    sp = sub.add_parser("launch", help="Meta 에 대량 생성")
    sp.add_argument("plan", help="plan 이 만든 CSV 경로")
    sp.add_argument("--execute", action="store_true", help="실제로 생성 (없으면 dry-run)")
    sp.add_argument("--activate", action="store_true", help="ACTIVE 로 생성 (기본 PAUSED)")
    sp.add_argument("--campaign-budget", type=int, help="캠페인 일 예산 (CBO)")
    sp.set_defaults(func=cmd_launch)

    sp = sub.add_parser("harvest", help="성과 수집")
    sp.add_argument("--days", type=int, default=14, help="최근 며칠 (기본 14)")
    sp.add_argument("--since"), sp.add_argument("--until")
    sp.add_argument("--campaign", help="캠페인명 부분일치 필터")
    sp.add_argument("--skip-age", action="store_true", help="광고 나이 조회를 건너뛴다")
    sp.add_argument("--stamp")
    sp.set_defaults(func=cmd_harvest)

    sp = sub.add_parser("judge", help="ROAS 컷 판정 (읽기 전용)")
    sp.add_argument("--run", help="런 디렉터리 (기본 최신)")
    sp.add_argument("--limit", type=int, default=0, help="표에 출력할 행 수")
    sp.add_argument("--brief", action="store_true", help="요약과 제안만 보고 전체 표는 생략")
    sp.set_defaults(func=cmd_judge)

    sp = sub.add_parser("doctor", help="설정 점검 — 뭐가 잘못됐는지 알려준다 (읽기 전용)")
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser("campaigns", help="캠페인 목록과 소유 분류 확인 (읽기 전용)")
    sp.add_argument("--all", action="store_true", help="종료된 캠페인까지 전부")
    sp.set_defaults(func=cmd_campaigns)

    sp = sub.add_parser("report", help="공유용 보고서 생성 (읽기 전용)")
    sp.add_argument("--run")
    sp.add_argument("--out", help="저장 경로 (기본 <런>/report.md)")
    sp.add_argument("--period", help="보고서 제목에 넣을 기간 표기")
    sp.add_argument("--no-dna", action="store_true", help="승자 축 분석 섹션 생략")
    sp.add_argument("--show", action="store_true", help="화면에도 전문 출력")
    sp.set_defaults(func=cmd_report)

    sp = sub.add_parser("dna", help="승자 축 분석")
    sp.add_argument("--run")
    sp.add_argument("--top", type=int, default=5)
    sp.add_argument("--keep-top", type=int, default=2, help="다음 라운드에 넘길 축당 값 개수")
    sp.add_argument("--min-ads", type=int, default=2, help="이 개수 미만인 값은 순위에서 뺀다")
    sp.set_defaults(func=cmd_dna)

    sp = sub.add_parser("apply", help="중단 제안 반영 (내 캠페인만)")
    sp.add_argument("--run")
    sp.add_argument("--yes", action="store_true", help="실제로 중단 (없으면 대상만 보여줌)")
    sp.set_defaults(func=cmd_apply)

    sp = sub.add_parser("breed", help="승자 DNA → 새 카피·기획안")
    sp.add_argument("--run")
    sp.add_argument("-n", type=int, default=8, help="생성할 소재 개수")
    sp.add_argument("--product", default="리터니티 율무 스킨클린 마스크 (워시오프 팩, 120g)")
    sp.add_argument("--audience", default="미국 거주 25-44 여성. 모공·피부결 고민. K뷰티 인지 있음.")
    sp.add_argument("--language", default="영어 (미국)")
    sp.add_argument("--creative-types", default="Video")
    sp.add_argument("--vary", default="카피 앵글", help="이번 배치에서 변주할 축")
    sp.add_argument("--reviews", help="리뷰 원문 텍스트 파일 (한 줄에 하나)")
    sp.add_argument("--min-ads", type=int, default=2)
    sp.set_defaults(func=cmd_breed)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _log(args.verbose)
    _load_env()
    try:
        args.func(args, Config.load(args.config))
    except (RuntimeError, FileNotFoundError, ValueError) as exc:
        # OwnershipError 는 RuntimeError 하위라 여기서 함께 잡힌다
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
