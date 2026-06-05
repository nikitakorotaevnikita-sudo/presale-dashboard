from pathlib import Path
import importlib
from fastapi.testclient import TestClient


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("PRESALE_DB", str(tmp_path / "api.db"))
    import src.config as cfg
    importlib.reload(cfg)
    import src.main as main
    importlib.reload(main)
    return TestClient(main.app)


def upload_fixture(client):
    p = Path("tests/fixtures/statistika_source_v14.xlsx")
    with p.open("rb") as f:
        return client.post(
            "/api/upload",
            files={"file": (p.name, f,
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={"uploaded_by": "Анна"})


def test_upload_then_metrics(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    r = upload_fixture(client)
    assert r.status_code == 200
    assert r.json()["row_count"] == 232

    r = client.get("/api/metrics", params={"metric": "поступило", "dimension": "услуга"})
    assert r.status_code == 200
    body = r.json()
    assert "Оценка внедрения" in body["rows"]
    assert body["values"]["Оценка внедрения"]["1"] == 5


def test_upload_rejects_bad_file(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    r = client.post("/api/upload",
                    files={"file": ("x.xlsx", b"not an excel", "application/octet-stream")},
                    data={"uploaded_by": "Анна"})
    assert r.status_code == 400


def test_filters_endpoint(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    upload_fixture(client)
    r = client.get("/api/filters")
    assert r.status_code == 200
    assert "услуга" in r.json()


def test_drilldown_endpoint(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    upload_fixture(client)
    r = client.get("/api/requests", params={
        "metric": "поступило", "dimension": "услуга",
        "value": "Оценка внедрения", "month": 1})
    assert r.status_code == 200
    assert len(r.json()) == 5


def test_export_endpoint(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    upload_fixture(client)
    r = client.get("/api/export", params={"dimension": "услуга"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(
        "application/vnd.openxmlformats")
