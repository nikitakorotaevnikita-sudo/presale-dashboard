from pathlib import Path
import importlib
from fastapi.testclient import TestClient

from src.main import _fix_form_encoding


def test_fix_form_encoding_repairs_cp1251_mojibake():
    # Starlette декодирует не-UTF-8 поле формы через latin-1 fallback:
    # cp1251-байты «Тест» (d2 e5 f1 f2) -> строка «Òåñò».
    mojibake = b"\xd2\xe5\xf1\xf2".decode("latin-1")
    assert mojibake == "Òåñò"
    assert _fix_form_encoding(mojibake) == "Тест"


def test_fix_form_encoding_leaves_valid_utf8_cyrillic():
    # Корректная UTF-8 кириллица (кодпоинты > U+00FF) не трогается.
    assert _fix_form_encoding("Веб-интерфейс") == "Веб-интерфейс"
    assert _fix_form_encoding("Тест") == "Тест"


def test_fix_form_encoding_leaves_ascii_and_empty():
    assert _fix_form_encoding("statistika_source_v14.xlsx") == "statistika_source_v14.xlsx"
    assert _fix_form_encoding("") == ""


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


def test_summary_endpoint(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    upload_fixture(client)
    r = client.get("/api/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["поступило"] == 44  # все поступившие за период в фикстуре
    assert set(body) == {"поступило", "проработано", "трудоемкость", "длительность", "на_контроле"}


def test_export_endpoint(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    upload_fixture(client)
    r = client.get("/api/export", params={"dimension": "услуга"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(
        "application/vnd.openxmlformats")


def test_export_respects_month_filter(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    upload_fixture(client)
    import io, openpyxl
    r = client.get("/api/export", params={"dimension": "услуга", "months": "1,2"})
    assert r.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    ws = wb["Поступило"]
    header = [c.value for c in ws[1]]
    # после заголовка-подписи только месяцы 1 и 2
    assert header[1:] == [1, 2]
