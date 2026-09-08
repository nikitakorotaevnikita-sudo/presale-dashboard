from src.models import StatusEvent
from src import chat_service, llm_service


def ev(rid, status, month):
    return StatusEvent(
        request_id=rid, request="r", org="o", product="P", scale="S",
        service="A", initiator="I", team="T1", business_unit="BU",
        status=status, prev_status="", date_start="", date_end="",
        month=month, duration_rd=0.0, work_duration_rd=0.0, hours=None, note="", link="")


def test_build_messages_has_rules_data_and_history():
    events = [ev("1", "Инициализация", 1)]
    msgs = chat_service.build_messages(events, [{"role": "user", "content": "вопрос?"}])
    assert msgs[0]["role"] == "system"
    joined = " ".join(m["content"] for m in msgs)
    assert "ДАННЫЕ" in joined            # сводка вложена
    assert "только" in joined.lower()    # правило анти-галлюцинаций
    assert msgs[-1]["content"] == "вопрос?"  # история сохранена


def test_stream_answer_delegates(monkeypatch):
    captured = {}
    def fake_stream(config, messages, **kw):
        captured["messages"] = messages
        yield "ответ"
    monkeypatch.setattr(llm_service, "stream_chat", fake_stream)
    out = "".join(chat_service.stream_answer(
        {"model": "m"}, [ev("1", "Инициализация", 1)],
        [{"role": "user", "content": "q"}]))
    assert out == "ответ"
    assert captured["messages"][0]["role"] == "system"


def test_stream_analysis_uses_analyze_prompt(monkeypatch):
    seen = {}
    def fake_stream(config, messages, **kw):
        seen["last"] = messages[-1]["content"]
        yield "отчёт"
    monkeypatch.setattr(llm_service, "stream_chat", fake_stream)
    out = "".join(chat_service.stream_analysis({"model": "m"}, [ev("1", "Принято", 1)]))
    assert out == "отчёт"
    assert "узких мест" in seen["last"].lower()
