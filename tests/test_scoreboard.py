from datetime import date

import pytest

from roasloop import dna, scoreboard as sb
from roasloop.judge import AdPerformance, judge_all
from roasloop.ownership import Ownership

OWN = Ownership({"agency": [{"pattern": "^E_US"}], "treat_unknown_as": "mine"})
WINDOW = (date(2026, 8, 26), date(2026, 9, 8))


def ad(owner, copy, spend, revenue, purchases, live="260901", ctype="Video"):
    campaign = "E_US_Meta_DA_SPF_EN_Yulmu_Conversion_ASC" if owner == "a" else "IH_US_Yulmu"
    return AdPerformance(
        ad_id=f"{owner}{copy}{live}{spend}",
        ad_name=f"26Regular_YulmuMask_{ctype}_{copy}_공병템_SPF.YulmuMask.PDP_{live}",
        campaign_name=campaign, adset_name="Demo.Broad_F2554_Purchase",
        spend=spend, revenue=revenue, purchases=purchases,
        impressions=int(spend / 9), clicks=int(spend / 600), frequency=1.6, days_active=14,
    )


@pytest.fixture
def board(rules):
    rows = [
        ad("m", "내앵글", 300_000, 750_000, 14),
        ad("m", "내앵글2", 250_000, 500_000, 9),
        ad("a", "대행앵글", 900_000, 900_000, 17),
        ad("a", "대행앵글2", 800_000, 640_000, 12),
        ad("a", "대행앵글3", 700_000, 490_000, 9),
    ]
    return sb.build(judge_all(rows, rules), OWN, window=WINDOW, period="테스트")


def test_sides_split_by_report_bucket(board):
    assert board.mine.ads == 2
    assert board.agency.ads == 3


def test_totals(board):
    assert board.mine.spend == 550_000
    assert board.agency.spend == 2_400_000
    assert board.mine.roas == pytest.approx(1250_000 / 550_000)


def test_new_creatives_counted_from_live_date(rules):
    rows = [
        ad("m", "신규", 200_000, 400_000, 7, live="260901"),   # 창 안
        ad("m", "구형", 200_000, 400_000, 7, live="260601"),   # 창 밖
    ]
    b = sb.build(judge_all(rows, rules), OWN, window=WINDOW)
    assert b.mine.ads == 2
    assert b.mine.new_creatives == 1


def test_copy_angle_variety_counted(board):
    assert len(board.mine.copy_angles) == 2
    assert len(board.agency.copy_angles) == 3


def test_ties_show_no_winner(rules):
    rows = [ad("m", "A", 100_000, 200_000, 4), ad("a", "B", 100_000, 200_000, 4)]
    b = sb.build(judge_all(rows, rules), OWN, window=WINDOW)
    roas_row = next(r for r in b.rows() if r[0] == "ROAS")
    assert roas_row[4] is None            # 동점이면 승패 표시 없음


def test_revenue_is_not_a_head_to_head(board):
    """지출 규모가 다르면 매출 크기 비교는 무의미하다. 승패 표시가 없어야 한다."""
    for label in ("매출", "구매", "지출", "광고당 지출"):
        row = next(r for r in board.rows() if r[0] == label)
        assert row[4] is None


def test_cpa_lower_is_better(rules):
    rows = [ad("m", "A", 100_000, 300_000, 6), ad("a", "B", 300_000, 300_000, 6)]
    b = sb.build(judge_all(rows, rules), OWN, window=WINDOW)
    cpa_row = next(r for r in b.rows() if r[0] == "CPA")
    assert cpa_row[4] is True             # 내 CPA 가 더 낮으면 이긴 것


def test_verdict_flags(board):
    vol, eff, notes = board.verdict()
    assert vol is False and eff is True
    assert any("물량이 부족" in n for n in notes)
    assert notes


# --------------------------------------------------------- 대행사에서 배우기
def test_steal_finds_agency_verified_angle_i_never_used(rules):
    rows = [
        ad("a", "대행승자", 400_000, 1_400_000, 25),
        ad("a", "대행승자", 380_000, 1_200_000, 22, live="260902"),
        ad("m", "내앵글", 300_000, 400_000, 7),
        ad("m", "내앵글", 280_000, 380_000, 7, live="260902"),
    ]
    split = dna.compare_owners(judge_all(rows, rules), OWN, min_ads=2)
    stolen = [s.value for s in split.steals if s.axis == "copy"]
    assert "대행승자" in stolen


def test_steal_skips_angles_i_already_use(rules):
    rows = [
        ad("a", "공통앵글", 400_000, 1_400_000, 25),
        ad("a", "공통앵글", 380_000, 1_200_000, 22, live="260902"),
        ad("m", "공통앵글", 300_000, 900_000, 16),
        ad("m", "공통앵글", 280_000, 800_000, 15, live="260902"),
    ]
    split = dna.compare_owners(judge_all(rows, rules), OWN, min_ads=2)
    assert "공통앵글" not in [s.value for s in split.steals if s.axis == "copy"]


def test_my_edge_finds_what_agency_does_not_have(rules):
    rows = [
        ad("m", "내독점", 300_000, 900_000, 16),
        ad("m", "내독점", 280_000, 850_000, 15, live="260902"),
        ad("a", "대행앵글", 400_000, 400_000, 7),
        ad("a", "대행앵글", 380_000, 380_000, 7, live="260902"),
    ]
    split = dna.compare_owners(judge_all(rows, rules), OWN, min_ads=2)
    assert "내독점" in [s.value for s in split.my_edge if s.axis == "copy"]


# ------------------------------------------------- 어느 런을 읽는가
def test_latest_run_uses_collection_time_not_name(tmp_path, monkeypatch):
    """이름순으로 고르면 --stamp 로 붙인 이름(month)이 날짜(20260910)보다 뒤로 정렬되어,
    새로 받은 데이터를 두고 옛 폴더를 계속 보게 된다. 실제로 났던 사고다."""
    import json
    import os
    import time

    from roasloop import cli

    runs = tmp_path / "runs"
    old = runs / "month"
    new = runs / "20260910"
    for d in (old, new):
        d.mkdir(parents=True)
        (d / "perf.json").write_text(json.dumps([]), encoding="utf-8")

    # 이름순으로는 month 가 뒤, 실제로는 20260910 이 나중에 수집됨
    assert sorted(p.name for p in runs.iterdir())[-1] == "month"
    now = time.time()
    os.utime(old / "perf.json", (now - 3600, now - 3600))
    os.utime(new / "perf.json", (now, now))

    monkeypatch.setattr(cli, "RUNS", runs)
    assert cli._latest_run().name == "20260910"


def test_latest_run_ignores_directories_without_data(tmp_path, monkeypatch):
    import json

    from roasloop import cli

    runs = tmp_path / "runs"
    (runs / "empty").mkdir(parents=True)
    real = runs / "20260901"
    real.mkdir()
    (real / "perf.json").write_text(json.dumps([]), encoding="utf-8")

    monkeypatch.setattr(cli, "RUNS", runs)
    assert cli._latest_run().name == "20260901"
