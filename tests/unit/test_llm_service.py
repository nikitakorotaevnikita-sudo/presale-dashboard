import types
from src import llm_service

CFG = {"provider": "local", "base_url": "http://x/v1", "model": "m", "token": "t"}


class _FakeStream:
    def __iter__(self):
        for text in ["Прив", "ет"]:
            yield types.SimpleNamespace(
                choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content=text))])


class _FakeClient:
    class chat:
        class completions:
            @staticmethod
            def create(**kwargs):
                if kwargs.get("stream"):
                    return _FakeStream()
                return types.SimpleNamespace(
                    choices=[types.SimpleNamespace(
                        message=types.SimpleNamespace(content="ok"))])


def test_stream_chat_yields_text(monkeypatch):
    monkeypatch.setattr(llm_service, "_make_client", lambda cfg: _FakeClient())
    out = "".join(llm_service.stream_chat(CFG, [{"role": "user", "content": "hi"}]))
    assert out == "Привет"


def test_test_connection_ok(monkeypatch):
    monkeypatch.setattr(llm_service, "_make_client", lambda cfg: _FakeClient())
    ok, msg = llm_service.test_connection(CFG)
    assert ok is True


def test_test_connection_error(monkeypatch):
    def boom(cfg):
        raise RuntimeError("нет связи")
    monkeypatch.setattr(llm_service, "_make_client", boom)
    ok, msg = llm_service.test_connection(CFG)
    assert ok is False and "нет связи" in msg
