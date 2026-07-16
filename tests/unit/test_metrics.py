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


def test_drilldown_includes_value_field():
    events = [
        ev("1", "Принято", 4, service="A", hours=10.0),
        ev("2", "Инициализация", 1, service="A"),
    ]
    acc = metrics.drilldown(events, "трудоемкость", "услуга", "A", 4)
    assert acc and acc[0]["value"] == 10.0
    init = metrics.drilldown(events, "поступило", "услуга", "A", 1)
    assert init and init[0]["value"] == 1


def test_month_totals_avg_over_all_requests():
    # услуга A: 2 запроса (10, 20); услуга B: 1 запрос (60)
    events = [
        ev("1", "Принято", 4, service="A", hours=10.0),
        ev("2", "Принято", 4, service="A", hours=20.0),
        ev("3", "Принято", 4, service="B", hours=60.0),
    ]
    # среднее из средних по разрезам = (15 + 60)/2 = 37.5 — НЕВЕРНО
    # честное среднее по всем запросам = (10+20+60)/3 = 30
    totals = metrics.month_totals(events, "трудоемкость")
    assert totals[4] == 30.0


def test_build_matrix_totals_over_all_requests():
    events = [
        ev("1", "Принято", 4, service="A", hours=10.0),
        ev("2", "Принято", 4, service="B", hours=20.0),
    ]
    m = metrics.build_matrix(events, "трудоемкость", "услуга", months=[4])
    assert m["totals"][4] == 15.0  # (10+20)/2 по всем запросам


def test_duration_rounds_up_to_integer():
    events = [
        ev("1", "Инициализация", 5, service="A", work=3.0),
        ev("1", "В работе", 5, service="A", work=7.1),  # сумма 10.1
        ev("1", "Принято", 5, service="A"),
    ]
    m = metrics.build_matrix(events, "длительность", "услуга", months=[5])
    assert m["values"]["A"][5] == 11   # ceil(10.1)
    assert m["totals"][5] == 11


def test_summary_duration_rounds_up():
    events = [
        ev("1", "Инициализация", 5, service="A", work=3.0),
        ev("1", "В работе", 5, service="A", work=7.1),
        ev("1", "Принято", 5, service="A"),
    ]
    s = metrics.summary(events)
    assert s["длительность"] == 11
