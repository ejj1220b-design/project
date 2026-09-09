"""꾸준히 오래 판 소재와 몰아서 판 소재 가르기."""

import pytest

from roasloop import steady as st


def days(pattern: str, spend_per_day: float = 20_000, aov: float = 50_000) -> list[dict]:
    """'█▁█▁·' 같은 문자열로 하루하루를 만든다. █=구매있음 ▁=구매없음 ·=꺼짐"""
    rows = []
    for i, ch in enumerate(pattern):
        d = f"2026-08-{i + 1:02d}"
        if ch == "·":
            rows.append({"date": d, "spend": 0.0, "revenue": 0.0, "purchases": 0})
        elif ch == "█":
            rows.append({"date": d, "spend": spend_per_day, "revenue": aov, "purchases": 1})
        else:
            rows.append({"date": d, "spend": spend_per_day, "revenue": 0.0, "purchases": 0})
    return rows


def ad(ad_id: str, pattern: str, **kw) -> list[dict]:
    return [{"ad_id": ad_id, "ad_name": f"광고{ad_id}", **row, **kw} for row in days(pattern)]


@pytest.fixture
def rules_st(rules):
    return rules


def test_daily_rows_roll_up_into_history():
    h = st.build_histories(ad("1", "█▁█▁█▁█"))[0]
    assert h.active_days == 7
    assert h.purchase_days == 4
    assert h.purchases == 4
    assert h.purchase_day_rate == pytest.approx(4 / 7)


def test_off_days_do_not_count_as_active():
    h = st.build_histories(ad("1", "██··██"))[0]
    assert h.active_days == 4
    assert h.purchase_days == 4
    assert h.purchase_day_rate == 1.0


def test_steady_ad_is_recognized(rules_st):
    """14일 중 12일 살아서 9일 구매 — 매출 기반."""
    rows = ad("steady", "█▁███▁█████▁██")
    report = st.build(rows, rules_st, ages={"steady": 90})
    assert [h.ad_id for h in report.steady] == ["steady"]


def test_spiky_ad_is_separated(rules_st):
    """이틀 몰아서 팔고 열흘 조용 — 같은 매출이라도 다른 물건."""
    rows = []
    for i, ch in enumerate("████▁▁▁▁▁▁▁▁▁▁"):
        d = f"2026-08-{i + 1:02d}"
        rows.append({
            "ad_id": "spiky", "ad_name": "광고spiky", "date": d, "spend": 20_000,
            "revenue": 200_000 if ch == "█" else 0.0, "purchases": 4 if ch == "█" else 0,
        })
    report = st.build(rows, rules_st, ages={"spiky": 90})
    assert [h.ad_id for h in report.spiky] == ["spiky"]
    assert report.steady == []


def test_young_ad_is_not_steady_even_if_consistent(rules_st):
    """사흘 살고 사흘 다 판 신규 소재는 '오래' 가 아니다."""
    report = st.build(ad("new", "██████████████"), rules_st, ages={"new": 5})
    assert report.steady == []


def test_old_but_idle_ad_is_not_steady(rules_st):
    """오래 켜두기만 한 소재도 아니다. 나이와 구매 리듬을 같이 본다."""
    report = st.build(ad("idle", "▁▁▁▁▁▁▁▁▁▁▁▁█▁"), rules_st, ages={"idle": 200})
    assert report.steady == []


def test_low_roas_is_excluded(rules_st):
    rows = [{**r, "revenue": r["revenue"] * 0.2} for r in ad("cheap", "█████████████")]
    report = st.build(rows, rules_st, ages={"cheap": 90})
    assert report.steady == []


def test_missing_age_does_not_block(rules_st):
    """광고 나이를 못 가져온 계정에서도 리듬만으로 판정할 수 있어야 한다."""
    report = st.build(ad("noage", "█▁███▁█████▁██"), rules_st, ages={})
    assert [h.ad_id for h in report.steady] == ["noage"]


def test_longest_dry_spell():
    h = st.build_histories(ad("1", "█▁▁▁█▁█"))[0]
    assert h.longest_dry_spell == 3


def test_sparkline_shows_rhythm():
    h = st.build_histories(ad("1", "█▁·█"))[0]
    assert h.sparkline() == "█▁·█"


def test_steady_ids_for_kill_protection(rules_st):
    report = st.build(ad("s", "█▁███▁█████▁██"), rules_st, ages={"s": 90})
    assert report.steady_ids == {"s"}


def test_young_but_consistent_lands_in_rising_not_spiky(rules_st):
    """어린 소재는 '몰려서 났다' 가 아니라 '아직 어리다' 다. 라벨이 틀리면 판단이 틀린다."""
    report = st.build(ad("young", "██████████████"), rules_st, ages={"young": 5})
    assert [h.ad_id for h in report.rising] == ["young"]
    assert report.spiky == []
    assert report.steady == []


def test_the_three_buckets_do_not_overlap(rules_st):
    rows = ad("steady", "█▁███▁█████▁██") + ad("young", "██████████████")
    report = st.build(rows, rules_st, ages={"steady": 90, "young": 3})
    ids = [h.ad_id for h in report.steady + report.rising + report.spiky]
    assert len(ids) == len(set(ids))
