from src.models import StatusEvent
from src import analytics_brief


def ev(rid, status, month, service="A", team="T1", hours=None, work=0.0, dur=0.0):
    return StatusEvent(
        request_id=rid, request="r", org="o", product="P", scale="S",
        service=service, initiator="I", team=team, business_unit="BU",
        status=status, prev_status="", date_start="", date_end="",
        month=month, duration_rd=dur, work_duration_rd=work, hours=hours, note="", link="")


def test_backlog_is_received_minus_processed():
    events = [
        ev("1", "Инициализация", 1), ev("2", "Инициализация", 1),
        ev("3", "Инициализация", 1),
        ev("1", "Принято", 1),  # 3 поступило, 1 проработано в январе
    ]
    ind = analytics_brief.bottleneck_indicators(events)
    assert ind["backlog_by_month"][1] == 2


def test_december_excluded_from_indicators():
    events = [ev("1", "Инициализация", 12), ev("2", "Инициализация", 1)]
    ind = analytics_brief.bottleneck_indicators(events)
    assert 12 not in ind["backlog_by_month"]
    assert ind["backlog_by_month"].get(1) == 1


def test_slowest_teams_ranked_by_duration():
    events = [
        ev("1", "Инициализация", 1, team="Fast", work=2.0), ev("1", "Принято", 1, team="Fast"),
        ev("2", "Инициализация", 1, team="Slow", work=20.0), ev("2", "Принято", 1, team="Slow"),
    ]
    ind = analytics_brief.bottleneck_indicators(events)
    assert ind["slowest_teams"][0][0] == "Slow"  # первым — самая медленная


def test_build_brief_contains_numbers_and_warning():
    events = [ev("1", "Инициализация", 1), ev("1", "Принято", 1, hours=10.0)]
    brief = analytics_brief.build_brief(events)
    assert "ДАННЫЕ" in brief
    assert "рассчитан" in brief.lower()  # предупреждение «числа рассчитаны системой»
    assert "Поступило" in brief and "Проработано" in brief
