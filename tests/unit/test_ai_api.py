from pathlib import Path
import importlib
from fastapi.testclient import TestClient


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("PRESALE_DB", str(tmp_path / "ai.db"))
    import src.config as cfg
    importlib.reload(cfg)
    import src.main as main
    importlib.reload(main)
    return main, TestClient(main.app)


def upload_fixture(client):
    p = Path("tests/fixtures/statistika_source_v14.xlsx")
    with p.open("rb") as f:
        return client.post("/api/upload", files={"file": (p.name, f,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={"uploaded_by": "T"})


def test_settings_get_masked(tmp_path, monkeypatch):
    _, client = make_client(tmp_path, monkeypatch)
    r = client.get("/api/settings/llm")
    assert r.status_code == 200
    assert r.json()["base_url"].startswith("http")
    # токен по умолчанию пуст либо замаскирован — сырой секрет не отдаётся
    assert "•" in r.json()["token"] or r.json()["token"] == ""


def test_settings_save_and_mask(tmp_path, monkeypatch):
    _, client = make_client(tmp_path, monkeypatch)
    r = client.post("/api/settings/llm", json={
        "provider": "local", "base_url": "http://y/v1", "model": "m", "token": "supersecret9"})
    assert r.status_code == 200
    assert r.json()["token"].endswith("ret9") and "super" not in r.json()["token"]


def test_settings_reject_bad_url(tmp_path, monkeypatch):
    _, client = make_client(tmp_path, monkeypatch)
    r = client.post("/api/settings/llm", json={"provider": "local", "base_url": "ftp://x", "model": "m", "token": ""})
    assert r.status_code == 422
    r2 = client.post("/api/settings/llm", json={"provider": "local", "base_url": "", "model": "m", "token": ""})
    assert r2.status_code == 422


def test_suggestions(tmp_path, monkeypatch):
    _, client = make_client(tmp_path, monkeypatch)
    r = client.get("/api/chat/suggestions")
    assert r.status_code == 200 and len(r.json()["suggestions"]) >= 3


def test_chat_streams_with_mock(tmp_path, monkeypatch):
    main, client = make_client(tmp_path, monkeypatch)
    upload_fixture(client)
    monkeypatch.setattr(main.chat_service, "stream_answer",
                        lambda *a, **k: iter(["ана", "лиз"]))
    r = client.post("/api/chat", json={"messages": [{"role": "user", "content": "q"}]})
    assert r.status_code == 200
    assert r.text == "анализ"


def test_chat_no_data(tmp_path, monkeypatch):
    _, client = make_client(tmp_path, monkeypatch)  # без загрузки
    r = client.post("/api/chat", json={"messages": [{"role": "user", "content": "q"}]})
    assert r.status_code == 400
    assert "данны" in r.json()["detail"].lower()


def test_chat_llm_error_in_stream(tmp_path, monkeypatch):
    main, client = make_client(tmp_path, monkeypatch)
    upload_fixture(client)

    def raising_stream(*a, **k):
        raise main.llm_service.LLMError("нет связи")
        yield  # noqa: unreachable, делает функцию генератором

    monkeypatch.setattr(main.chat_service, "stream_answer", raising_stream)
    r = client.post("/api/chat", json={"messages": [{"role": "user", "content": "q"}]})
    assert r.status_code == 200
    assert "Ошибка модели" in r.text
    assert "Бэкофис" in r.text
