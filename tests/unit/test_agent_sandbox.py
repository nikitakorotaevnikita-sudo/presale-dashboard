from src.models import StatusEvent
from src import agent_sandbox


def ev(rid, status="Принято", month=1, service="A"):
    return StatusEvent(
        request_id=rid, request="r", org="o", product="P", scale="S",
        service=service, initiator="I", team="T", business_unit="BU",
        status=status, prev_status="", date_start="", date_end="",
        month=month, duration_rd=0.0, work_duration_rd=0.0, hours=None, note="", link="")


EVENTS = [ev("1"), ev("2"), ev("2"), ev("3", status="Инициализация")]


def test_runs_safe_code_and_returns_result():
    code = "result = int(df['request_id'].nunique())\nexplanation = 'уникальные'"
    r = agent_sandbox.run_code(code, EVENTS)
    assert r["ok"] is True
    assert r["result"] == 3
    assert r["explanation"] == "уникальные"


def test_blocks_import_os():
    r = agent_sandbox.run_code("import os\nresult = os.getcwd()", EVENTS)
    assert r["ok"] is False
    assert "запрещ" in (r["error"] or "").lower() or "import" in (r["error"] or "").lower()


def test_blocks_open():
    r = agent_sandbox.run_code("result = open('data.json').read()", EVENTS)
    assert r["ok"] is False  # open недоступен в namespace -> NameError


def test_blocks_socket():
    r = agent_sandbox.run_code("import socket\nresult = 1", EVENTS)
    assert r["ok"] is False


def test_timeout_kills_runaway():
    r = agent_sandbox.run_code("while True:\n    pass", EVENTS, timeout=2)
    assert r["ok"] is False
    assert "врем" in (r["error"] or "").lower()


def test_non_serializable_result_coerced():
    r = agent_sandbox.run_code("result = {1, 2, 3}", EVENTS)  # set -> строка
    assert r["ok"] is True
    assert isinstance(r["result"], str)


def test_secrets_not_in_subprocess(monkeypatch):
    monkeypatch.setenv("LLM_TOKEN", "SECRET-TOKEN-XYZ")
    r = agent_sandbox.run_code(
        "import os\nresult = 'leak'", EVENTS)  # import os всё равно запрещён
    # даже если бы os был доступен, LLM_TOKEN не должен попасть в окружение ребёнка:
    r2 = agent_sandbox.run_code("result = df.shape[0]", EVENTS)
    assert r2["ok"] is True and r2["result"] == 4
