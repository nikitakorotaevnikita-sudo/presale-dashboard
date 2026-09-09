# Code-agent (харнесс анализа кодом) — План реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить opt-in режим ИИ-аналитика, где LLM пишет Python, который исполняется в песочнице-подпроцессе над данными, и ответ строится по реально вычисленному результату.

**Architecture:** Подпроцесс-песочница с урезанным namespace (белый список импортов, отключённые builtins, без сети/ФС/секретов, тайм-аут). Агентная петля: кодоген → прогон → самокоррекция по трейсбеку (≤2 повтора) → ответ из фактического `result`. Отдельный эндпоинт `/api/agent`; надёжный чат (подход A) остаётся дефолтом.

**Tech Stack:** Python 3.10+, FastAPI, pandas, SQLite; Vanilla JS; pytest + Playwright.

**Spec:** `docs/superpowers/specs/2026-09-09-code-agent-harness-design.md`

## Global Constraints

- Python **3.10+**; новая зависимость **`pandas>=2.0`**.
- Frontend — **Vanilla JS**, без фреймворков; UI/текст — **на русском**.
- **TDD**; покрытие **≥70%**; реальный LLM в тестах **не вызывается** (мок `llm_service.stream_chat` / `LLM_FAKE=1`).
- Песочница — **отдельный подпроцесс**; секреты (`LLM_TOKEN`, `PRESALE_DB`) **не передаются** в подпроцесс; сеть/ФС-запись/импорты вне белого списка — запрещены; тайм-аут.
- Секреты не в git и не в логах.
- Декабрь исключается из данных так же, как в чате (`metrics.drop_excluded_months`).
- Коммиты: `git -c core.safecrlf=false commit`. Ветка — новая feature-ветка (создаётся исполнителем плана перед стартом). Команды из `C:/Users/Korotaev_NO/Desktop/Проекты/presale-dashboard`; Python — `.venv/Scripts/python.exe`.

---

## Файловая структура

| Файл | Ответственность |
|---|---|
| `src/agent_sandbox.py` (создать) | Раннер подпроцесса: изолированное исполнение сгенерированного кода |
| `src/code_agent.py` (создать) | Промпт кодогенерации + агентная петля с самокоррекцией |
| `src/main.py` (изменить) | Эндпоинт `POST /api/agent` (+ `LLM_FAKE`) |
| `static/index.html`, `static/app.js`, `static/style.css` (изменить) | Тумблер «Глубокий анализ (код)» + сворачиваемый блок кода |
| `pyproject.toml` (изменить) | Зависимость `pandas` |
| `tests/unit/test_*.py`, `tests/e2e/test_code_agent.py` (создать) | Тесты |

---

## Task 1: pandas + песочница (`agent_sandbox.py`)

**Files:**
- Modify: `pyproject.toml`
- Create: `src/agent_sandbox.py`
- Test: `tests/unit/test_agent_sandbox.py`

**Interfaces:**
- Consumes: `src.models.StatusEvent` (dataclass — сериализуется через `dataclasses.asdict`).
- Produces: `run_code(code: str, events: list[StatusEvent], timeout: float = 15) -> dict` → `{"ok": bool, "result": <json|str|None>, "explanation": str, "error": str|None}`.

- [ ] **Step 1: Добавить зависимость и установить**

В `pyproject.toml` в `dependencies` добавить `"pandas>=2.0",` после `"openai>=1.30",`. Установить:
```
cd "C:/Users/Korotaev_NO/Desktop/Проекты/presale-dashboard" && .venv/Scripts/python.exe -m pip install -e ".[dev]"
```
Ожидается: установка без ошибок, `import pandas` доступен.

- [ ] **Step 2: Написать падающие тесты** `tests/unit/test_agent_sandbox.py`

```python
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
```

- [ ] **Step 3: Запустить — падает**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_agent_sandbox.py -q`
Expected: FAIL (module not defined).

- [ ] **Step 4: Реализовать** `src/agent_sandbox.py`

```python
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

# Скрипт-обёртка (доверенный): грузит данные, строит df, урезает окружение и
# исполняет пользовательский код из user_code.py с белым списком импортов.
_RUNNER = r'''
import json, sys, builtins, traceback

with open("data.json", encoding="utf-8") as f:
    _rows = json.load(f)
import pandas as pd
_df = pd.DataFrame(_rows)

_ALLOWED = {"pandas", "numpy", "math", "statistics", "json", "datetime", "collections"}
_real_import = builtins.__import__
def _safe_import(name, *a, **k):
    if name.split(".")[0] not in _ALLOWED:
        raise ImportError("Импорт запрещён в песочнице: " + name)
    return _real_import(name, *a, **k)

try:
    import socket
    def _no_net(*a, **k):
        raise OSError("Сеть недоступна в песочнице")
    socket.socket.connect = _no_net
except Exception:
    pass
try:
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
except Exception:
    pass

_names = ("abs", "min", "max", "sum", "len", "range", "round", "sorted",
          "enumerate", "zip", "map", "filter", "list", "dict", "set", "tuple",
          "str", "int", "float", "bool", "print", "any", "all", "reversed",
          "isinstance", "hasattr", "getattr", "repr")
_sb = {n: getattr(builtins, n) for n in _names if hasattr(builtins, n)}
_sb["__import__"] = _safe_import
_sb["True"], _sb["False"], _sb["None"] = True, False, None

with open("user_code.py", encoding="utf-8") as f:
    _code = f.read()

_ns = {"__builtins__": _sb, "df": _df.copy(), "pd": pd, "result": None, "explanation": ""}
try:
    exec(_code, _ns)
except Exception:
    sys.stderr.write(traceback.format_exc())
    sys.exit(1)

sys.stdout.write(json.dumps(
    {"result": _ns.get("result"), "explanation": str(_ns.get("explanation") or "")},
    ensure_ascii=False, default=str))
'''


def run_code(code, events, timeout=15):
    rows = [asdict(e) for e in events]
    child_env = {k: v for k, v in os.environ.items()
                 if k not in ("LLM_TOKEN", "PRESALE_DB")}
    child_env["PYTHONIOENCODING"] = "utf-8"
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d)
        (dp / "data.json").write_text(
            json.dumps(rows, ensure_ascii=False, default=str), encoding="utf-8")
        (dp / "user_code.py").write_text(code, encoding="utf-8")
        (dp / "runner.py").write_text(_RUNNER, encoding="utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, "runner.py"], cwd=d, env=child_env,
                capture_output=True, text=True, encoding="utf-8", timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"ok": False, "result": None, "explanation": "",
                    "error": "Превышен лимит времени выполнения"}
        if proc.returncode != 0:
            return {"ok": False, "result": None, "explanation": "",
                    "error": (proc.stderr or "неизвестная ошибка")[-2000:]}
        try:
            out = json.loads((proc.stdout or "").strip().splitlines()[-1])
        except Exception:
            return {"ok": False, "result": None, "explanation": "",
                    "error": "Некорректный вывод песочницы: " + (proc.stdout or "")[-500:]}
        return {"ok": True, "result": out.get("result"),
                "explanation": out.get("explanation", ""), "error": None}
```

- [ ] **Step 5: Запустить — проходит**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_agent_sandbox.py -q`
Expected: PASS (7 тестов). `test_timeout_kills_runaway` длится ~2 c.

- [ ] **Step 6: Коммит**

```
git add pyproject.toml src/agent_sandbox.py tests/unit/test_agent_sandbox.py
git -c core.safecrlf=false commit -m "feat: песочница-подпроцесс для исполнения кода агента (изоляция, белый список, тайм-аут)"
```

---

## Task 2: агентная петля (`code_agent.py`)

**Files:**
- Create: `src/code_agent.py`
- Test: `tests/unit/test_code_agent.py`

**Interfaces:**
- Consumes: `src.llm_service.stream_chat(config, messages, ...)` (генератор строк); `src.agent_sandbox.run_code(code, events, timeout)`.
- Produces:
  - `CODEGEN_PROMPT: str`, `MAX_ATTEMPTS: int`
  - `extract_code(text: str) -> str`
  - `build_messages(events, history) -> list[dict]`
  - `stream_agent(config, events, history, upload=None)` — генератор строковых чанков (код + результат)

- [ ] **Step 1: Написать падающие тесты** `tests/unit/test_code_agent.py`

```python
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
```

- [ ] **Step 2: Запустить — падает**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_code_agent.py -q`
Expected: FAIL.

- [ ] **Step 3: Реализовать** `src/code_agent.py`

```python
import json
import re

from src import agent_sandbox, llm_service

MAX_ATTEMPTS = 3

CODEGEN_PROMPT = (
    "Ты пишешь Python (pandas) для анализа процесса пресейла ОГВ.\n"
    "Дан DataFrame `df` (pandas), уже без декабря. Колонки:\n"
    "request_id (ИД запроса), request (название), org, product, scale, service (услуга), "
    "initiator, team (команда), business_unit, status (статус), prev_status, "
    "date_start, date_end, month (1-12), duration_rd (длительность статуса, раб.дн), "
    "work_duration_rd (длительность проработки запроса, раб.дн), hours (отработано часов), note, link.\n"
    "ПРАВИЛА РАСЧЁТА: считай запросы уникально по request_id; «поступило» = строки со "
    "status=='Инициализация'; «проработано» и средние — по status=='Принято'; "
    "длительность проработки берётся из work_duration_rd.\n"
    "ТРЕБОВАНИЯ К КОДУ:\n"
    "- только чтение df; без сети, файлов и импортов кроме pandas/numpy/math/statistics/json/datetime/collections;\n"
    "- присвой переменную result (число, словарь или список — JSON-сериализуемо) и "
    "explanation (краткий текст-вывод по-русски);\n"
    "- верни ТОЛЬКО блок кода ```python ...```, без пояснений вне блока."
)


def extract_code(text):
    m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip()


def build_messages(events, history):
    messages = [{"role": "system", "content": CODEGEN_PROMPT}]
    messages.extend(history or [])
    return messages


def _format_result(res):
    if isinstance(res, (dict, list)):
        return "```json\n" + json.dumps(res, ensure_ascii=False, indent=2) + "\n```"
    return str(res)


def stream_agent(config, events, history, upload=None):
    messages = build_messages(events, history)
    for attempt in range(MAX_ATTEMPTS):
        code_text = "".join(llm_service.stream_chat(config, messages))
        code = extract_code(code_text)
        r = agent_sandbox.run_code(code, events)
        if r["ok"]:
            yield f"```python\n{code}\n```\n\n"
            if r["explanation"]:
                yield r["explanation"] + "\n\n"
            yield "**Результат:** " + _format_result(r["result"])
            return
        messages.append({"role": "assistant", "content": code_text})
        messages.append({"role": "user",
                         "content": "Код упал с ошибкой:\n" + (r["error"] or "") +
                                    "\nИсправь и верни только исправленный блок кода."})
    yield ("Не удалось выполнить анализ кодом после нескольких попыток. "
           "Попробуйте обычный чат (выключите «Глубокий анализ»).")
```

- [ ] **Step 4: Запустить — проходит**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_code_agent.py -q`
Expected: PASS (5 тестов).

- [ ] **Step 5: Коммит**

```
git add src/code_agent.py tests/unit/test_code_agent.py
git -c core.safecrlf=false commit -m "feat: агентная петля code-agent (кодоген, прогон в песочнице, самокоррекция)"
```

---

## Task 3: эндпоинт `POST /api/agent`

**Files:**
- Modify: `src/main.py`
- Test: `tests/unit/test_agent_api.py`

**Interfaces:**
- Consumes: `code_agent.stream_agent`, существующие `_load_events_or_400()` (возвращает `(events, upload, cfg)`), `_fake_stream_response()`, `ChatBody`, `llm_service.LLMError`, `StreamingResponse`.
- Produces (HTTP): `POST /api/agent` (тело `{messages:[{role,content}]}`) → стрим `text/plain; charset=utf-8`.

- [ ] **Step 1: Написать падающий тест** `tests/unit/test_agent_api.py`

```python
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
```

- [ ] **Step 2: Запустить — падает**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_agent_api.py -q`
Expected: FAIL.

- [ ] **Step 3: Реализовать** — в `src/main.py`

К импортам добавить `code_agent`:
```python
from src import config, storage, metrics, export, settings_store, chat_service, llm_service, code_agent
```
Добавить эндпоинт рядом с `/api/analyze` (перед монтированием статики):
```python
@app.post("/api/agent")
def agent(body: ChatBody):
    events, upload, cfg = _load_events_or_400()
    if os.environ.get("LLM_FAKE") == "1":
        return _fake_stream_response()

    def gen():
        try:
            yield from code_agent.stream_agent(cfg, events, body.messages, upload)
        except llm_service.LLMError as exc:
            yield f"\n\n[Ошибка модели: {exc}. Проверьте настройки в Бэкофисе.]"

    return StreamingResponse(gen(), media_type="text/plain; charset=utf-8")
```
(Проверить, что `import os` уже есть в `main.py` — он добавлялся для `LLM_FAKE`; если нет — добавить.)

- [ ] **Step 4: Запустить — проходит**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_agent_api.py -q`
Expected: PASS (3 теста).

- [ ] **Step 5: Коммит**

```
git add src/main.py tests/unit/test_agent_api.py
git -c core.safecrlf=false commit -m "feat: эндпоинт /api/agent (стриминг code-agent, LLM_FAKE, обработка ошибок)"
```

---

## Task 4: фронтенд — тумблер и сворачиваемый код

**Files:**
- Modify: `static/index.html`, `static/app.js`, `static/style.css`

**Interfaces:**
- Consumes (HTTP): `/api/agent` (стрим), `/api/chat` (существующий).

- [ ] **Step 1: Разметка** — в `static/index.html`, во вкладке `#view-ai`, перед `#chat-suggestions` добавить тумблер:

```html
<label class="agent-toggle"><input type="checkbox" id="agent-mode"> Глубокий анализ (код)</label>
```
Поднять версию ассетов: заменить `?v=20260909` на `?v=20260910` в трёх ссылках (`tokens.css`, `style.css`, `app.js`).

- [ ] **Step 2: Маршрутизация запроса** — в `static/app.js`, в функции `sendChat`, заменить вызов `streamInto("/api/chat", ...)` на выбор URL по тумблеру:

Найти строку вида `const answer = await streamInto("/api/chat", { messages: chatHistory }, bubble);` и заменить на:
```javascript
      const useAgent = document.getElementById("agent-mode") && document.getElementById("agent-mode").checked;
      const answer = await streamInto(useAgent ? "/api/agent" : "/api/chat", { messages: chatHistory }, bubble);
```

- [ ] **Step 3: Сворачиваемый блок кода** — в `static/app.js`, в функции `renderMarkdown`, заменить ветку code-fence так, чтобы код оборачивался в `<details>`:

Найти:
```javascript
      html += `<pre><code>${buf.join("\n")}</code></pre>`; continue;
```
Заменить на:
```javascript
      html += `<details class="md-code"><summary>Код</summary><pre><code>${buf.join("\n")}</code></pre></details>`; continue;
```

- [ ] **Step 4: Стили** — в `static/style.css` добавить:

```css
.agent-toggle { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; color: var(--muted); margin-bottom: 12px; cursor: pointer; }
.agent-toggle input { accent-color: var(--accent); }
.bubble.md .md-code { margin: 8px 0; }
.bubble.md .md-code > summary { cursor: pointer; font-size: 12px; font-weight: 600; color: var(--accent); }
.bubble.md .md-code pre { margin: 8px 0 0; }
```

- [ ] **Step 5: Проверка**

```
cd "C:/Users/Korotaev_NO/Desktop/Проекты/presale-dashboard" && node --check static/app.js && echo JS_OK
```
Запустить сервер, открыть вкладку «ИИ-аналитик», убедиться: тумблер отображается; при выключенном — обычный чат; блок кода в ответах сворачивается. (Реальный ответ агента зависит от Qwen — при недоступности показывается ошибка.)

- [ ] **Step 6: Коммит**

```
git add static/index.html static/app.js static/style.css
git -c core.safecrlf=false commit -m "feat: тумблер «Глубокий анализ (код)» и сворачиваемый блок кода в чате"
```

---

## Task 5: E2E и README

**Files:**
- Create: `tests/e2e/test_code_agent.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: запущенный сервер с `LLM_FAKE=1` (фикстура uvicorn, как в `tests/e2e/test_ai_chat.py`).

- [ ] **Step 1: Написать E2E** `tests/e2e/test_code_agent.py`

Переиспользовать паттерн `tests/e2e/test_ai_chat.py` (session-scoped uvicorn с temp `PRESALE_DB` и `LLM_FAKE=1`, ожидание `/api/health`, загрузка фикстуры). READ `tests/e2e/test_ai_chat.py` для точного рабочего паттерна фикстуры на этой машине, затем:

```python
import os, socket, subprocess, sys, time, urllib.request
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    port = _free_port()
    env = {**os.environ, "PRESALE_DB": str(tmp_path_factory.mktemp("db") / "e2e.db"),
           "LLM_FAKE": "1"}
    log = open(tmp_path_factory.mktemp("log") / "srv.log", "w")
    proc = subprocess.Popen(
        [str(ROOT / ".venv/Scripts/python.exe"), "-m", "uvicorn", "src.main:app",
         "--port", str(port)], cwd=str(ROOT), env=env, stdout=log, stderr=log)
    base = f"http://127.0.0.1:{port}"
    for _ in range(40):
        try:
            if urllib.request.urlopen(base + "/api/health", timeout=2).status == 200:
                break
        except Exception:
            time.sleep(0.5)
    import httpx
    with open(ROOT / "tests/fixtures/statistika_source_v14.xlsx", "rb") as f:
        httpx.post(base + "/api/upload", files={"file": f},
                   data={"uploaded_by": "e2e"}, timeout=180)
    yield base
    proc.terminate(); log.close()


def test_agent_mode_flow(server):
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_context().new_page()
        pg.goto(server)
        pg.click("button[data-view='ai']")
        pg.check("#agent-mode")
        pg.fill("#chat-input", "Посчитай число строк")
        pg.click("#chat-form button[type='submit']")
        expect(pg.locator(".bubble--assistant").last).to_be_visible(timeout=30000)
        b.close()
```
(Ответ приходит из `LLM_FAKE` — фиксированный текст; тест проверяет, что режим агента включается и ответ появляется.)

- [ ] **Step 2: Запустить E2E**

Run: `.venv/Scripts/python.exe -m pytest tests/e2e/test_code_agent.py -q`
Expected: PASS. Если matcher нестабилен — свести к `assert pg.locator(".bubble--assistant").last.inner_text()` непустой.

- [ ] **Step 3: README** — в `README.md`, в раздел «ИИ-аналитик и Бэкофис», добавить абзац:

```markdown
### Глубокий анализ (код)

Тумблер «Глубокий анализ (код)» во вкладке «ИИ-аналитик» включает opt-in режим, где модель пишет Python (pandas), который исполняется в изолированной песочнице-подпроцессе над данными, и ответ строится по реально вычисленному результату. Сгенерированный код виден в сворачиваемом блоке. По умолчанию режим выключен — работает надёжный чат по сводке.
```

- [ ] **Step 4: Коммит**

```
git add tests/e2e/test_code_agent.py README.md
git -c core.safecrlf=false commit -m "test+docs: E2E code-agent и README про режим «Глубокий анализ»"
```

---

## Финал

- [ ] Прогнать весь набор без глобального `LLM_FAKE`: `.venv/Scripts/python.exe -m pytest tests/ -q` — всё зелёное, покрытие ≥70%.
- [ ] Пересобрать Docker при необходимости (новая зависимость `pandas`) и проверить запуск.
