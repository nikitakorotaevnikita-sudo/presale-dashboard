from pathlib import Path
import importlib
from fastapi.testclient import TestClient


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("PRESALE_DB", str(tmp_path / "ag.db"))
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


def test_agent_streams_with_mock(tmp_path, monkeypatch):
    main, client = make_client(tmp_path, monkeypatch)
    upload_fixture(client)
    monkeypatch.setattr(main.code_agent, "stream_agent",
                        lambda *a, **k: iter(["```python\nresult=1\n```", "\n**Результат:** 1"]))
    r = client.post("/api/agent", json={"messages": [{"role": "user", "content": "q"}]})
    assert r.status_code == 200
    assert "Результат" in r.text and "python" in r.text


def test_agent_no_data(tmp_path, monkeypatch):
    _, client = make_client(tmp_path, monkeypatch)
    r = client.post("/api/agent", json={"messages": [{"role": "user", "content": "q"}]})
    assert r.status_code == 400
    assert "данны" in r.json()["detail"].lower()


def test_agent_llm_error_in_stream(tmp_path, monkeypatch):
    main, client = make_client(tmp_path, monkeypatch)
    upload_fixture(client)
    def boom(*a, **k):
        raise main.llm_service.LLMError("нет связи")
        yield
    monkeypatch.setattr(main.code_agent, "stream_agent", boom)
    r = client.post("/api/agent", json={"messages": [{"role": "user", "content": "q"}]})
    assert r.status_code == 200
    assert "Ошибка модели" in r.text
