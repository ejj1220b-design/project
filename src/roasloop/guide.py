"""안내 모드 — `roasloop` 만 쳤을 때 실행된다.

명령어를 외우지 않아도 되게 만드는 것이 목적이다. 지금 상태를 보고 다음에 할 일을
하나 골라 추천하고, 번호만 누르면 실행한다.

두 가지를 지킨다.
    · 한 화면에 결정은 하나. 선택지를 늘어놓지 않고 추천을 먼저 보여준다.
    · 끝나면 반드시 다음 할 일을 알려준다. 사용자가 '이제 뭐하지' 를 겪지 않게 한다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

RUNS = Path("data/runs")


@dataclass
class State:
    has_token: bool
    latest_run: Path | None
    age_days: int | None
    ads: int
    has_judgement: bool
    has_report: bool
    unreadable_names: int

    @property
    def has_data(self) -> bool:
        return self.latest_run is not None and self.ads > 0

    @property
    def stale(self) -> bool:
        return self.age_days is not None and self.age_days >= 3


def diagnose(cfg) -> State:
    import json

    runs = sorted(RUNS.iterdir()) if RUNS.exists() else []
    latest = runs[-1] if runs else None
    ads = 0
    unreadable = 0
    age = None

    if latest and (latest / "perf.json").exists():
        try:
            rows = json.loads((latest / "perf.json").read_text(encoding="utf-8"))
            ads = len(rows)
            from .naming import AdName, NamingError

            parser = cfg.parser
            for r in rows:
                try:
                    AdName.parse(r.get("ad_name", ""), parser)
                except NamingError:
                    unreadable += 1
        except (ValueError, OSError):
            ads = 0
        mtime = datetime.fromtimestamp((latest / "perf.json").stat().st_mtime)
        age = (datetime.now() - mtime).days

    return State(
        has_token=bool(os.environ.get("META_ACCESS_TOKEN")),
        latest_run=latest,
        age_days=age,
        ads=ads,
        has_judgement=bool(latest and (latest / "judgement.csv").exists()),
        has_report=bool(latest and (latest / "report.html").exists()),
        unreadable_names=unreadable,
    )


def headline(state: State) -> list[str]:
    """지금 상태 한 줄. 길게 쓰지 않는다."""
    if not state.has_token:
        return ["설정이 아직 안 됐습니다."]
    if not state.has_data:
        return ["아직 성과 데이터가 없습니다."]

    when = "오늘" if state.age_days == 0 else f"{state.age_days}일 전"
    lines = [f"광고 {state.ads}개 · {when} 수집"]
    if state.unreadable_names:
        lines.append(
            f"⚠ 광고명 {state.unreadable_names}개를 못 읽습니다 — 소재 분석이 그만큼 빕니다"
        )
    if state.stale:
        lines.append("데이터가 오래됐습니다. 다시 가져오는 게 좋습니다.")
    return lines


NEXT_HINT = {
    "harvest": ("2", "대행사와 비교하기"),
    "scoreboard": ("3", "뭐가 이겼는지 보기"),
    "dna": ("5", "보고서 만들기"),
    "judge": ("5", "보고서 만들기"),
    "names": ("2", "대행사와 비교하기"),
    "doctor": ("1", "성과 가져오기"),
    "report": (None, None),
}


@dataclass
class Action:
    key: str
    label: str
    hint: str
    command: str


def wrap(text: str, width: int = 48, indent: str = "    ") -> list[str]:
    """긴 문장을 화면 폭에 맞춰 자른다. 한 줄로 흘러가면 읽히지 않는다."""
    import textwrap

    return textwrap.wrap(text, width=width, initial_indent=indent, subsequent_indent=indent)


def actions_for(state: State, last: str | None = None) -> tuple[list[Action], int]:
    """(할 수 있는 일 목록, 추천 항목 index)

    last 는 방금 실행한 명령. 순서대로 따라갈 수 있게 그 다음 단계를 추천한다.
    """
    if not state.has_token:
        return [
            Action("1", "설정 점검하기", "뭐가 빠졌는지 알려줍니다", "doctor"),
        ], 0

    items = [
        Action("1", "성과 가져오기", "최근 14일 · 계정을 읽기만 합니다", "harvest"),
        Action("2", "대행사와 비교하기", "물량 · 효율 · 학습", "scoreboard"),
        Action("3", "뭐가 이겼는지 보기", "대행사가 검증한 승자도 함께", "dna"),
        Action("4", "끌 것 확인하기", "중단·확장 제안", "judge"),
        Action("5", "보고서 만들기", "브라우저에서 열리는 파일", "report"),
        Action("6", "광고명 진단", "소재 분석이 비어 있을 때", "names"),
        Action("7", "설정 점검", "토큰 · 연결 상태", "doctor"),
    ]

    if not state.has_data or state.stale:
        return items, 0
    if state.unreadable_names > state.ads * 0.3:
        return items, 5

    # 방금 뭔가를 했다면 그 다음 단계로 넘긴다. 같은 걸 계속 추천하면 진도가 안 나간다.
    if last:
        nxt_key, _ = NEXT_HINT.get(last, (None, None))
        if nxt_key:
            for idx, action in enumerate(items):
                if action.key == nxt_key:
                    return items, idx

    if not state.has_judgement:
        return items, 1
    if not state.has_report:
        return items, 4
    return items, 1

