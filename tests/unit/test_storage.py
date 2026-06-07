from src.models import StatusEvent
from src import storage


def ev(rid, status="Принято", month=1, service="A"):
    return StatusEvent(
        request_id=rid, request="r", org="o", product="P", scale="S",
        service=service, initiator="I", team="T", business_unit="BU",
        status=status, prev_status="", date_start="", date_end="",
        month=month, duration_rd=1.0, work_duration_rd=2.0, hours=5.0, note="",
    )


def test_replace_and_load_roundtrip(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    storage.init_db(conn)
    storage.replace_events(conn, [ev("1"), ev("2")], "file.xlsx", "Анна")
    loaded = storage.load_events(conn)
    assert {e.request_id for e in loaded} == {"1", "2"}
    assert loaded[0].hours == 5.0


def test_replace_is_atomic_overwrite(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    storage.init_db(conn)
    storage.replace_events(conn, [ev("1")], "a.xlsx", "Анна")
    storage.replace_events(conn, [ev("2"), ev("3")], "b.xlsx", "Анна")
    loaded = storage.load_events(conn)
    assert {e.request_id for e in loaded} == {"2", "3"}


def test_last_upload_metadata(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    storage.init_db(conn)
    storage.replace_events(conn, [ev("1")], "stat.xlsx", "Анна")
    up = storage.last_upload(conn)
    assert up["filename"] == "stat.xlsx"
    assert up["row_count"] == 1
    assert up["uploaded_by"] == "Анна"


def test_distinct_values(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    storage.init_db(conn)
    storage.replace_events(conn, [ev("1", service="A"), ev("2", service="B")],
                           "f.xlsx", "Анна")
    vals = storage.distinct_values(conn)
    assert vals["услуга"] == ["A", "B"]
