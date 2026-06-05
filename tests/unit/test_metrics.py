from src.models import StatusEvent
from src import metrics


def ev(request_id, status, month, service="A", team="T1",
       hours=None, work=0.0, dur=0.0, product="P", scale="S", initiator="I"):
    return StatusEvent(
        request_id=request_id, request="req", org="org", product=product,
        scale=scale, service=service, initiator=initiator, team=team,
        business_unit="BU", status=status, prev_status="", date_start="",
        date_end="", month=month, duration_rd=dur, work_duration_rd=work,
        hours=hours, note="",
    )


def test_postupilo_counts_distinct_init():
    events = [
        ev("1", "Инициализация", 1, service="A"),
        ev("2", "Инициализация", 1, service="A"),
        ev("3", "Инициализация", 2, service="B"),
        ev("1", "В работе", 1, service="A"),  # не считается
    ]
    cells = metrics.compute_cells(events, "поступило", "услуга")
    assert cells[("A", 1)] == 2
    assert cells[("B", 2)] == 1


def test_postupilo_dedups_redirected():
    events = [
        ev("9", "Инициализация", 3, service="A"),
        ev("9", "Инициализация", 3, service="A"),
    ]
    cells = metrics.compute_cells(events, "поступило", "услуга")
    assert cells[("A", 3)] == 1


def test_avg_hours_one_value_per_request():
    events = [
        ev("1", "Принято", 4, service="A", hours=10.0),
        ev("2", "Принято", 4, service="A", hours=20.0),
        ev("3", "Принято", 4, service="B", hours=None),
    ]
    cells = metrics.compute_cells(events, "трудоемкость", "услуга")
    assert cells[("A", 4)] == 15.0
    assert ("B", 4) not in cells


def test_avg_duration_sums_work_duration_per_request():
    events = [
        ev("1", "Инициализация", 5, service="A", work=3.0),
        ev("1", "В работе", 5, service="A", work=7.0),
        ev("1", "Принято", 5, service="A", work=0.0),
    ]
    cells = metrics.compute_cells(events, "длительность", "услуга")
    assert cells[("A", 5)] == 10.0


def test_avg_control_sums_control_duration():
    events = [
        ev("1", "На контроле", 6, service="A", dur=4.0),
        ev("1", "Принято", 6, service="A"),
        ev("2", "Принято", 6, service="A"),
    ]
    cells = metrics.compute_cells(events, "на_контроле", "услуга")
    assert cells[("A", 6)] == 2.0


def test_filter_events_by_team():
    events = [ev("1", "Принято", 1, team="T1"), ev("2", "Принято", 1, team="T2")]
    out = metrics.filter_events(events, teams=["T1"])
    assert [e.request_id for e in out] == ["1"]


def test_build_matrix_shape():
    events = [ev("1", "Инициализация", 1, service="A"),
              ev("2", "Инициализация", 2, service="A")]
    m = metrics.build_matrix(events, "поступило", "услуга", months=[1, 2, 3])
    assert m["rows"] == ["A"]
    assert m["months"] == [1, 2, 3]
    assert m["values"]["A"][1] == 1
    assert m["values"]["A"][3] is None
