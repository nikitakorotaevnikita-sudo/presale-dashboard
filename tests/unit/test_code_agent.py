from src.models import StatusEvent
from src import code_agent, llm_service


def ev(rid, status="Принято", month=1):
    return StatusEvent(
        request_id=rid, request="r", org="o", product="P", scale="S",
        service="A", initiator="I", team="T", business_unit="BU",
        status=status, prev_status="", date_start="", date_end="",
        month=month, duration_rd=0.0, work_duration_rd=0.0, hours=None, note="", link="")


def test_extract_code_from_fence():
    txt = "Вот код:\n```python\nresult = 1\n```\nготово"
    assert code_agent.extract_code(txt).strip() == "result = 1"


def test_build_messages_has_rules_and_question():
    msgs = code_agent.build_messages([ev("1")], [{"role": "user", "content": "сколько?"}])
    assert msgs[0]["role"] == "system"
    joined = " ".join(m["content"] for m in msgs)
    assert "df" in joined and "result" in joined
    assert msgs[-1]["content"] == "сколько?"


def _fake_stream(responses):
    it = iter(responses)
    def fn(config, messages, **kw):
        yield next(it)
    return fn


def test_agent_success(monkeypatch):
    monkeypatch.setattr(llm_service, "stream_chat",
        _fake_stream(["```python\nresult = int(df.shape[0])\nexplanation='строк'\n```"]))
    out = "".join(code_agent.stream_agent({"model": "m"}, [ev("1"), ev("2")],
        [{"role": "user", "content": "сколько строк?"}]))
    assert "result" in out.lower() or "2" in out          # результат виден
    assert "```python" in out                              # код показан
    assert "строк" in out                                  # explanation


def test_agent_retries_on_error(monkeypatch):
    monkeypatch.setattr(llm_service, "stream_chat",
        _fake_stream([
            "```python\nresult = 1/0\n```",                 # падает
            "```python\nresult = 7\n```",                   # чинится
        ]))
    out = "".join(code_agent.stream_agent({"model": "m"}, [ev("1")],
        [{"role": "user", "content": "?"}]))
    assert "7" in out


def test_agent_gives_up_after_max(monkeypatch):
    monkeypatch.setattr(llm_service, "stream_chat",
        _fake_stream(["```python\nresult = 1/0\n```"] * 5))
    out = "".join(code_agent.stream_agent({"model": "m"}, [ev("1")],
        [{"role": "user", "content": "?"}]))
    assert "не удалось" in out.lower()
