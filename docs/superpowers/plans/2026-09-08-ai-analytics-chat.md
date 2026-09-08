# ИИ-чат аналитики пресейла — План реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить в дашборд ИИ-чат аналитики, который по точным данным (без галлюцинаций) помогает находить узкие места пресейла, и вкладку бэкофиса для настройки LLM.

**Architecture:** Подход A (грудинг): все числа считаются детерминированно в коде (через `metrics.py`) и вкладываются в контекст LLM как блок ДАННЫЕ. LLM только интерпретирует и советует, не считает арифметику. Локальный OpenAI-совместимый провайдер (Qwen), стриминг ответов. Настройки LLM в SQLite, редактируются в бэкофисе.

**Tech Stack:** Python 3.10+, FastAPI, Uvicorn, openai SDK, SQLite, Vanilla JS, pytest + Playwright.

**Spec:** `docs/superpowers/specs/2026-09-08-ai-analytics-chat-design.md`

## Global Constraints

- Python **3.10+**; фронтенд — **Vanilla JS**, без фреймворков.
- Новая зависимость: **`openai>=1.30`** (OpenAI-совместимый SDK).
- Общение с пользователем и весь UI — **на русском**.
- **TDD** (тест до реализации); покрытие **≥70%**; реальный LLM в тестах **не вызывается** (мок).
- Секреты (токен LLM) **не в git и не в логах**; в API токен только **замаскирован**.
- Декабрь исключается из аналитики через `metrics.drop_excluded_months` (существующее правило).
- Значение по умолчанию провайдера: base_url `https://llm.ario.directum360.ru/v1`, модель `Qwen/Qwen3-8-27B` (уточнить точное имя через `GET {base_url}/models`), токен — из env `LLM_TOKEN`, иначе пусто.
- Коммиты: `git -c core.safecrlf=false commit` (Windows CRLF). Ветка `main`.
- Все команды выполнять из `C:/Users/Korotaev_NO/Desktop/Проекты/presale-dashboard`; Python — `.venv/Scripts/python.exe`.

---

## Файловая структура

| Файл | Ответственность |
|---|---|
| `src/settings_store.py` (создать) | Таблица `app_settings` в SQLite: конфиг LLM, сидинг дефолта, маскирование токена |
| `src/analytics_brief.py` (создать) | Индикаторы узких мест + текстовая сводка ДАННЫЕ (через `metrics.py`) |
| `src/llm_service.py` (создать) | OpenAI-совместимый клиент: стриминг чата, `test_connection` |
| `src/chat_service.py` (создать) | Системный промпт, сборка сообщений (ДАННЫЕ + история), `analyze` |
| `src/main.py` (изменить) | Эндпоинты бэкофиса и чата |
| `static/index.html`, `static/app.js`, `static/style.css` (изменить) | Вкладки «ИИ-аналитик» и «Бэкофис» |
| `pyproject.toml` (изменить) | Зависимость `openai` |
| `tests/unit/test_*.py`, `tests/e2e/test_ai_chat.py` (создать) | Тесты |

---

## Task 1: Зависимость openai + хранилище настроек LLM

**Files:**
- Modify: `pyproject.toml`
- Create: `src/settings_store.py`
- Test: `tests/unit/test_settings_store.py`

**Interfaces:**
- Produces:
  - `ensure(conn)` — создать таблицу `app_settings` и засеять дефолт (идемпотентно)
  - `get_llm_config(conn) -> dict` — `{"provider","base_url","model","token"}` (реальный токен)
  - `masked_config(conn) -> dict` — то же, но `token` замаскирован (`••••386d` или `""`)
  - `save_llm_config(conn, provider, base_url, model, token) -> None` — пустой `token` (пустая строка/None) НЕ затирает прежний
  - `mask_token(token) -> str`

- [ ] **Step 1: Добавить зависимость**

В `pyproject.toml` в списке `dependencies` добавить строку `"openai>=1.30",` после `"python-multipart>=0.0.9",`. Затем установить:
```
cd "C:/Users/Korotaev_NO/Desktop/Проекты/presale-dashboard" && .venv/Scripts/python.exe -m pip install -e ".[dev]"
```
Ожидается: установка без ошибок, доступен `import openai`.

- [ ] **Step 2: Написать падающий тест** `tests/unit/test_settings_store.py`

```python
import sqlite3
from src import settings_store


def _conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    return c


def test_ensure_seeds_default():
    c = _conn()
    settings_store.ensure(c)
    cfg = settings_store.get_llm_config(c)
    assert cfg["base_url"] == "https://llm.ario.directum360.ru/v1"
    assert cfg["model"]  # непустое имя модели
    assert cfg["provider"] == "local"


def test_mask_token():
    assert settings_store.mask_token("100111ac-d413-4721-9357-5d04aaf7386d").endswith("386d")
    assert settings_store.mask_token("100111ac-d413-4721-9357-5d04aaf7386d").startswith("•")
    assert settings_store.mask_token("") == ""


def test_masked_config_hides_token():
    c = _conn()
    settings_store.ensure(c)
    settings_store.save_llm_config(c, "local", "http://x/v1", "m", "secrettoken123")
    assert settings_store.masked_config(c)["token"].endswith("n123")
    assert "secret" not in settings_store.masked_config(c)["token"]
    assert settings_store.get_llm_config(c)["token"] == "secrettoken123"


def test_empty_token_preserves_previous():
    c = _conn()
    settings_store.ensure(c)
    settings_store.save_llm_config(c, "local", "http://x/v1", "m", "keepme")
    settings_store.save_llm_config(c, "local", "http://y/v1", "m2", "")
    cfg = settings_store.get_llm_config(c)
    assert cfg["token"] == "keepme"       # токен сохранён
    assert cfg["base_url"] == "http://y/v1"  # прочее обновлено
```

- [ ] **Step 3: Запустить — тест падает**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_settings_store.py -q`
Expected: FAIL (module/functions not defined).

- [ ] **Step 4: Реализовать** `src/settings_store.py`

```python
import os

_KEYS = ("provider", "base_url", "model", "token")
_DEFAULTS = {
    "provider": "local",
    "base_url": "https://llm.ario.directum360.ru/v1",
    "model": "Qwen/Qwen3-8-27B",  # уточнить точное имя через {base_url}/models
    "token": os.environ.get("LLM_TOKEN", ""),
}


def ensure(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT)")
    existing = {r[0] for r in conn.execute("SELECT key FROM app_settings")}
    for k in _KEYS:
        if f"llm.{k}" not in existing:
            conn.execute("INSERT INTO app_settings (key, value) VALUES (?, ?)",
                         (f"llm.{k}", _DEFAULTS[k]))
    conn.commit()


def get_llm_config(conn):
    rows = dict(conn.execute(
        "SELECT key, value FROM app_settings WHERE key LIKE 'llm.%'").fetchall())
    return {k: rows.get(f"llm.{k}", _DEFAULTS[k]) for k in _KEYS}


def save_llm_config(conn, provider, base_url, model, token):
    updates = {"provider": provider, "base_url": base_url, "model": model}
    if token:  # пустой токен не затирает прежний
        updates["token"] = token
    for k, v in updates.items():
        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (f"llm.{k}", v))
    conn.commit()


def mask_token(token):
    if not token:
        return ""
    tail = token[-4:]
    return "•" * max(4, len(token) - 4) + tail


def masked_config(conn):
    cfg = get_llm_config(conn)
    return {**cfg, "token": mask_token(cfg["token"])}
```

- [ ] **Step 5: Запустить — тесты проходят**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_settings_store.py -q`
Expected: PASS (4 теста).

- [ ] **Step 6: Коммит**

```
git add pyproject.toml src/settings_store.py tests/unit/test_settings_store.py
git -c core.safecrlf=false commit -m "feat: хранилище настроек LLM в SQLite (сидинг дефолта, маскирование токена)"
```

---

## Task 2: Аналитическая сводка (ядро анти-галлюцинаций)

**Files:**
- Create: `src/analytics_brief.py`
- Test: `tests/unit/test_analytics_brief.py`

**Interfaces:**
- Consumes: из `src.metrics` — `drop_excluded_months(events)`, `build_matrix(events, metric, dim)`, `month_totals(events, metric)`, `summary(events)`, `METRICS`; из `src.models` — `StatusEvent`, `DIMENSION_ATTR`.
- Produces:
  - `bottleneck_indicators(events) -> dict` — машинный срез: `{"backlog_by_month": {m:int}, "throughput": float|None, "slowest_teams": [(team, avg_len)], "top_control_teams": [(team, avg_ctrl)], "heaviest_services": [(svc, avg_hours)]}`
  - `build_brief(events, upload=None) -> str` — текстовый блок ДАННЫЕ для LLM

- [ ] **Step 1: Написать падающий тест** `tests/unit/test_analytics_brief.py`

```python
from src.models import StatusEvent
from src import analytics_brief


def ev(rid, status, month, service="A", team="T1", hours=None, work=0.0, dur=0.0):
    return StatusEvent(
        request_id=rid, request="r", org="o", product="P", scale="S",
        service=service, initiator="I", team=team, business_unit="BU",
        status=status, prev_status="", date_start="", date_end="",
        month=month, duration_rd=dur, work_duration_rd=work, hours=hours, note="", link="")


def test_backlog_is_received_minus_processed():
    events = [
        ev("1", "Инициализация", 1), ev("2", "Инициализация", 1),
        ev("3", "Инициализация", 1),
        ev("1", "Принято", 1),  # 3 поступило, 1 проработано в январе
    ]
    ind = analytics_brief.bottleneck_indicators(events)
    assert ind["backlog_by_month"][1] == 2


def test_december_excluded_from_indicators():
    events = [ev("1", "Инициализация", 12), ev("2", "Инициализация", 1)]
    ind = analytics_brief.bottleneck_indicators(events)
    assert 12 not in ind["backlog_by_month"]
    assert ind["backlog_by_month"].get(1) == 1


def test_slowest_teams_ranked_by_duration():
    events = [
        ev("1", "Инициализация", 1, team="Fast", work=2.0), ev("1", "Принято", 1, team="Fast"),
        ev("2", "Инициализация", 1, team="Slow", work=20.0), ev("2", "Принято", 1, team="Slow"),
    ]
    ind = analytics_brief.bottleneck_indicators(events)
    assert ind["slowest_teams"][0][0] == "Slow"  # первым — самая медленная


def test_build_brief_contains_numbers_and_warning():
    events = [ev("1", "Инициализация", 1), ev("1", "Принято", 1, hours=10.0)]
    brief = analytics_brief.build_brief(events)
    assert "ДАННЫЕ" in brief
    assert "рассчитан" in brief.lower()  # предупреждение «числа рассчитаны системой»
    assert "Поступило" in brief and "Проработано" in brief
```

- [ ] **Step 2: Запустить — падает**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_analytics_brief.py -q`
Expected: FAIL.

- [ ] **Step 3: Реализовать** `src/analytics_brief.py`

```python
from collections import defaultdict
from statistics import mean

from src import metrics


def _avg_by_team(events, metric_key):
    """{команда: среднее} по показателю (через month_totals на подмножестве команды)."""
    teams = sorted({e.team for e in events if e.team})
    out = {}
    for t in teams:
        sub = [e for e in events if e.team == t]
        totals = metrics.month_totals(sub, metric_key)  # {month: value}
        vals = [v for v in totals.values() if v is not None]
        if vals:
            out[t] = round(mean(vals), 1)
    return out


def bottleneck_indicators(events):
    events = metrics.drop_excluded_months(events)
    recv = metrics.month_totals(events, "поступило")     # {month:int}
    proc = metrics.month_totals(events, "проработано")   # {month:int}
    backlog = {m: (recv.get(m, 0) - proc.get(m, 0))
               for m in sorted(set(recv) | set(proc))}
    total_recv = sum(recv.values())
    total_proc = sum(proc.values())
    throughput = round(total_proc / total_recv, 2) if total_recv else None

    dur = _avg_by_team(events, "длительность")
    ctrl = _avg_by_team(events, "на_контроле")
    heavy_svc = {}
    for s in sorted({e.service for e in events if e.service}):
        sub = [e for e in events if e.service == s]
        vals = [v for v in metrics.month_totals(sub, "трудоемкость").values() if v is not None]
        if vals:
            heavy_svc[s] = round(mean(vals), 1)

    return {
        "backlog_by_month": backlog,
        "throughput": throughput,
        "slowest_teams": sorted(dur.items(), key=lambda x: -x[1]),
        "top_control_teams": sorted(ctrl.items(), key=lambda x: -x[1]),
        "heaviest_services": sorted(heavy_svc.items(), key=lambda x: -x[1]),
    }


def _matrix_lines(events, metric_key, dim, title):
    m = metrics.build_matrix(events, metric_key, dim)
    months = [mm for mm in m["months"] if any(
        m["values"][r][mm] is not None for r in m["rows"])]
    if not months:
        return []
    head = title + " | " + " | ".join(str(mm) for mm in months) + " | Всего"
    lines = [head]
    for r in m["rows"]:
        cells = [m["values"][r][mm] for mm in months]
        shown = ["" if c is None else str(c) for c in cells]
        nums = [c for c in cells if c is not None]
        total = sum(nums) if metric_key in ("поступило", "проработано") else (
            round(mean(nums), 1) if nums else "")
        lines.append(f"{r} | " + " | ".join(shown) + f" | {total}")
    tot = m.get("totals", {})
    lines.append("ВСЕГО | " + " | ".join(
        "" if tot.get(mm) is None else str(tot.get(mm)) for mm in months) + " |")
    return lines


def build_brief(events, upload=None):
    events = metrics.drop_excluded_months(events)
    out = ["=== ДАННЫЕ (все числа рассчитаны системой из загруженных данных; "
           "не пересчитывай их) ==="]
    if upload:
        out.append(f"Загрузка: {upload.get('filename','')}, "
                   f"строк: {upload.get('row_count','')}.")
    out.append("Примечание: декабрь исключён из расчётов.")

    titles = [("поступило", "Поступило"), ("проработано", "Проработано"),
              ("трудоемкость", "Ср. трудоёмкость (ч)"),
              ("длительность", "Ср. длительность (раб.дн)"),
              ("на_контроле", "Ср. на контроле (раб.дн)")]
    for key, label in titles:
        out.append(f"\n## {label}")
        for dim, dlab in (("услуга", "по услугам"), ("команда", "по командам")):
            lines = _matrix_lines(events, key, dim, dlab)
            out.extend(lines)

    ind = bottleneck_indicators(events)
    out.append("\n## Индикаторы узких мест")
    out.append("Backlog по месяцам (поступило−проработано): " +
               ", ".join(f"{m}:{v}" for m, v in ind["backlog_by_month"].items()))
    out.append(f"Пропускная способность (проработано/поступило): {ind['throughput']}")
    out.append("Команды по ср. длительности (медленные первыми): " +
               ", ".join(f"{t}:{v}" for t, v in ind["slowest_teams"]))
    out.append("Команды по ср. времени 'на контроле': " +
               ", ".join(f"{t}:{v}" for t, v in ind["top_control_teams"]))
    out.append("Услуги по ср. трудоёмкости: " +
               ", ".join(f"{s}:{v}" for s, v in ind["heaviest_services"]))
    return "\n".join(out)
```

- [ ] **Step 4: Запустить — проходит**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_analytics_brief.py -q`
Expected: PASS (4 теста).

- [ ] **Step 5: Коммит**

```
git add src/analytics_brief.py tests/unit/test_analytics_brief.py
git -c core.safecrlf=false commit -m "feat: аналитическая сводка и индикаторы узких мест (грудинг для LLM)"
```

---

## Task 3: LLM-сервис (стриминг + проверка связи)

**Files:**
- Create: `src/llm_service.py`
- Test: `tests/unit/test_llm_service.py`

**Interfaces:**
- Consumes: `openai.OpenAI`.
- Produces:
  - `stream_chat(config, messages, temperature=0.2, timeout=120)` — генератор строковых чанков ответа
  - `test_connection(config) -> tuple[bool, str]` — (успех, сообщение)
  - `LLMError(Exception)` — для нормализованных ошибок
  - `_make_client(config)` — внутренняя фабрика (для мока в тестах)

- [ ] **Step 1: Написать падающий тест** `tests/unit/test_llm_service.py`

```python
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
```

- [ ] **Step 2: Запустить — падает**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_llm_service.py -q`
Expected: FAIL.

- [ ] **Step 3: Реализовать** `src/llm_service.py`

```python
from openai import OpenAI


class LLMError(Exception):
    pass


def _make_client(config):
    return OpenAI(base_url=config["base_url"],
                  api_key=config.get("token") or "not-needed",
                  timeout=float(config.get("timeout", 120)))


def stream_chat(config, messages, temperature=0.2, timeout=120):
    try:
        client = _make_client({**config, "timeout": timeout})
        stream = client.chat.completions.create(
            model=config["model"], messages=messages,
            temperature=temperature, stream=True)
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
    except Exception as exc:  # нормализуем любую ошибку SDK/сети
        raise LLMError(str(exc)) from exc


def test_connection(config):
    try:
        client = _make_client({**config, "timeout": 30})
        client.chat.completions.create(
            model=config["model"],
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1)
        return True, "Связь с моделью установлена"
    except Exception as exc:
        return False, f"Ошибка подключения: {exc}"
```

- [ ] **Step 4: Запустить — проходит**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_llm_service.py -q`
Expected: PASS (3 теста).

- [ ] **Step 5: Коммит**

```
git add src/llm_service.py tests/unit/test_llm_service.py
git -c core.safecrlf=false commit -m "feat: LLM-сервис (стриминг chat-completions, проверка связи, нормализация ошибок)"
```

---

## Task 4: Сервис чата (промпты, сборка, анализ)

**Files:**
- Create: `src/chat_service.py`
- Test: `tests/unit/test_chat_service.py`

**Interfaces:**
- Consumes: `src.analytics_brief.build_brief`, `src.llm_service.stream_chat`.
- Produces:
  - `SYSTEM_PROMPT: str`, `ANALYZE_PROMPT: str`, `SUGGESTIONS: list[str]`
  - `build_messages(events, history, upload=None) -> list[dict]` — system + блок ДАННЫЕ + история
  - `stream_answer(config, events, history, upload=None)` — генератор чанков (делегирует в llm_service)
  - `stream_analysis(config, events, upload=None)` — генератор чанков отчёта

- [ ] **Step 1: Написать падающий тест** `tests/unit/test_chat_service.py`

```python
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
```

- [ ] **Step 2: Запустить — падает**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_chat_service.py -q`
Expected: FAIL.

- [ ] **Step 3: Реализовать** `src/chat_service.py`

```python
from src import analytics_brief, llm_service

SYSTEM_PROMPT = (
    "Ты — аналитик процесса пресейла ОГВ. Помогаешь руководителю находить узкие "
    "места, оценивать сложности из-за исполнителей и команд.\n"
    "ПРАВИЛА:\n"
    "1. Используй ТОЛЬКО числа из блока ДАННЫЕ. Не пересчитывай и не выдумывай цифры.\n"
    "2. В выводах цитируй конкретные числа (команда/услуга/месяц/значение).\n"
    "3. Если данных для ответа нет — прямо скажи «В данных этого нет».\n"
    "4. Рекомендации опирай на конкретные индикаторы из ДАННЫХ.\n"
    "5. Отвечай по-русски, кратко и по делу."
)

ANALYZE_PROMPT = (
    "Проведи анализ узких мест процесса пресейла по блоку ДАННЫЕ. "
    "Определи 3–5 проблемных зон. Для каждой укажи: (а) в чём проблема, "
    "(б) числа-обоснование из ДАННЫХ, (в) конкретную рекомендацию. "
    "Отсортируй по критичности."
)

SUGGESTIONS = [
    "Какая команда дольше всех держит запросы?",
    "Где копится backlog?",
    "У каких услуг самая высокая трудоёмкость?",
    "Какие команды дольше держат запросы «на контроле»?",
]


def build_messages(events, history, upload=None):
    brief = analytics_brief.build_brief(events, upload)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": brief},
    ]
    messages.extend(history or [])
    return messages


def stream_answer(config, events, history, upload=None):
    yield from llm_service.stream_chat(config, build_messages(events, history, upload))


def stream_analysis(config, events, upload=None):
    history = [{"role": "user", "content": ANALYZE_PROMPT}]
    yield from llm_service.stream_chat(config, build_messages(events, history, upload))
```

- [ ] **Step 4: Запустить — проходит**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_chat_service.py -q`
Expected: PASS (3 теста).

- [ ] **Step 5: Коммит**

```
git add src/chat_service.py tests/unit/test_chat_service.py
git -c core.safecrlf=false commit -m "feat: сервис чата — системный промпт, сборка сообщений с ДАННЫМИ, анализ узких мест"
```

---

## Task 5: API-эндпоинты (бэкофис + чат)

**Files:**
- Modify: `src/main.py`
- Test: `tests/unit/test_ai_api.py`

**Interfaces:**
- Consumes: `settings_store`, `llm_service`, `chat_service`, `storage`, `metrics`.
- Produces (HTTP):
  - `GET /api/settings/llm` → masked_config
  - `POST /api/settings/llm` (body: provider, base_url, model, token) → masked_config
  - `POST /api/llm/test` → `{ok, message}`
  - `GET /api/chat/suggestions` → `{"suggestions": [...]}`
  - `POST /api/chat` (body: `{messages:[{role,content}]}`) → text/plain стрим
  - `POST /api/analyze` → text/plain стрим

- [ ] **Step 1: Написать падающий тест** `tests/unit/test_ai_api.py`

```python
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
```

- [ ] **Step 2: Запустить — падает**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_ai_api.py -q`
Expected: FAIL.

- [ ] **Step 3: Реализовать** — добавить в `src/main.py`

В начало файла (к импортам) добавить:
```python
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from src import settings_store, chat_service, llm_service
```
В функции `_conn()` после `storage.init_db(conn)` добавить `settings_store.ensure(conn)`.

Добавить модель тела и эндпоинты (перед строкой монтирования статики `if config.STATIC_DIR.exists()`):
```python
class LLMSettings(BaseModel):
    provider: str = "local"
    base_url: str
    model: str
    token: str = ""


class ChatBody(BaseModel):
    messages: list[dict]


def _load_events_or_400():
    with closing(_conn()) as conn:
        events = storage.load_events(conn)
        upload = storage.last_upload(conn)
    if not events:
        raise HTTPException(400, "Сначала загрузите данные")
    return events, upload


@app.get("/api/settings/llm")
def get_llm_settings():
    with closing(_conn()) as conn:
        return settings_store.masked_config(conn)


@app.post("/api/settings/llm")
def save_llm_settings(body: LLMSettings):
    with closing(_conn()) as conn:
        settings_store.save_llm_config(
            conn, body.provider, body.base_url, body.model, body.token)
        return settings_store.masked_config(conn)


@app.post("/api/llm/test")
def test_llm():
    with closing(_conn()) as conn:
        cfg = settings_store.get_llm_config(conn)
    ok, message = llm_service.test_connection(cfg)
    return {"ok": ok, "message": message}


@app.get("/api/chat/suggestions")
def chat_suggestions():
    return {"suggestions": chat_service.SUGGESTIONS}


@app.post("/api/chat")
def chat(body: ChatBody):
    events, upload = _load_events_or_400()
    with closing(_conn()) as conn:
        cfg = settings_store.get_llm_config(conn)

    def gen():
        try:
            yield from chat_service.stream_answer(cfg, events, body.messages, upload)
        except llm_service.LLMError as exc:
            yield f"\n\n[Ошибка модели: {exc}. Проверьте настройки в Бэкофисе.]"

    return StreamingResponse(gen(), media_type="text/plain; charset=utf-8")


@app.post("/api/analyze")
def analyze():
    events, upload = _load_events_or_400()
    with closing(_conn()) as conn:
        cfg = settings_store.get_llm_config(conn)

    def gen():
        try:
            yield from chat_service.stream_analysis(cfg, events, upload)
        except llm_service.LLMError as exc:
            yield f"\n\n[Ошибка модели: {exc}. Проверьте настройки в Бэкофисе.]"

    return StreamingResponse(gen(), media_type="text/plain; charset=utf-8")
```

- [ ] **Step 4: Запустить — проходит**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_ai_api.py -q`
Expected: PASS (5 тестов). Примечание: `test_chat_no_data` проверяет 400 без загрузки; остальные мокают LLM.

- [ ] **Step 5: Коммит**

```
git add src/main.py tests/unit/test_ai_api.py
git -c core.safecrlf=false commit -m "feat: API бэкофиса и чата (настройки LLM, проверка связи, стриминг чата и анализа)"
```

---

## Task 6: Фронтенд — вкладки «ИИ-аналитик» и «Бэкофис»

**Files:**
- Modify: `static/index.html`, `static/app.js`, `static/style.css`

**Interfaces:**
- Consumes (HTTP): `/api/settings/llm`, `/api/llm/test`, `/api/chat/suggestions`, `/api/chat`, `/api/analyze`.

Существующий дашборд — набор «вкладок показателей». Здесь добавляются две **верхнеуровневые вкладки-страницы** (Дашборд / ИИ-аналитик / Бэкофис). Реализовать переключение секций по кнопкам в шапке; существующий контент дашборда обернуть в секцию.

- [ ] **Step 1: Разметка** — в `static/index.html`

Добавить в шапку переключатель верхних вкладок и две новые секции. Рядом с заголовком добавить:
```html
<nav id="top-nav">
  <button class="topnav__btn topnav__btn--active" data-view="dashboard">Дашборд</button>
  <button class="topnav__btn" data-view="ai">ИИ-аналитик</button>
  <button class="topnav__btn" data-view="backoffice">Бэкофис</button>
</nav>
```
Существующий блок дашборда обернуть в `<section id="view-dashboard"></section>`. Добавить:
```html
<section id="view-ai" hidden>
  <div id="chat-suggestions"></div>
  <button id="analyze-btn">Анализ узких мест</button>
  <div id="chat-log"></div>
  <form id="chat-form">
    <input id="chat-input" placeholder="Спросите про узкие места процесса…" autocomplete="off">
    <button type="submit">Отправить</button>
  </form>
</section>
<section id="view-backoffice" hidden>
  <h2>Настройки LLM</h2>
  <form id="llm-form">
    <label>Провайдер <input id="llm-provider" value="local"></label>
    <label>Base URL <input id="llm-base-url"></label>
    <label>Модель <input id="llm-model"></label>
    <label>Токен <input id="llm-token" placeholder="оставьте пустым, чтобы не менять"></label>
    <button type="submit">Сохранить</button>
    <button type="button" id="llm-test">Проверить связь</button>
  </form>
  <div id="llm-status"></div>
</section>
```

- [ ] **Step 2: Переключение верхних вкладок** — в `static/app.js`

```javascript
function switchView(view) {
  for (const v of ["dashboard", "ai", "backoffice"]) {
    document.getElementById("view-" + v).hidden = v !== view;
  }
  document.querySelectorAll(".topnav__btn").forEach((b) =>
    b.classList.toggle("topnav__btn--active", b.dataset.view === view));
  if (view === "ai") initAi();
  if (view === "backoffice") loadLlmSettings();
}
document.getElementById("top-nav").addEventListener("click", (e) => {
  const b = e.target.closest(".topnav__btn");
  if (b) switchView(b.dataset.view);
});
```

- [ ] **Step 3: Бэкофис** — в `static/app.js`

```javascript
async function loadLlmSettings() {
  try {
    const c = await api("/api/settings/llm");
    document.getElementById("llm-provider").value = c.provider || "local";
    document.getElementById("llm-base-url").value = c.base_url || "";
    document.getElementById("llm-model").value = c.model || "";
    document.getElementById("llm-token").placeholder =
      c.token ? c.token + " (сохранён — оставьте пустым, чтобы не менять)" : "введите токен";
  } catch (e) { document.getElementById("llm-status").textContent = "Ошибка: " + e.message; }
}
document.getElementById("llm-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = {
    provider: document.getElementById("llm-provider").value,
    base_url: document.getElementById("llm-base-url").value,
    model: document.getElementById("llm-model").value,
    token: document.getElementById("llm-token").value,
  };
  try {
    await fetch("/api/settings/llm", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body) }).then((r) => { if (!r.ok) throw new Error("Ошибка сохранения"); });
    document.getElementById("llm-token").value = "";
    document.getElementById("llm-status").textContent = "Сохранено";
    loadLlmSettings();
  } catch (e) { document.getElementById("llm-status").textContent = e.message; }
});
document.getElementById("llm-test").addEventListener("click", async () => {
  const s = document.getElementById("llm-status");
  s.textContent = "Проверка…";
  try {
    const r = await fetch("/api/llm/test", { method: "POST" }).then((x) => x.json());
    s.textContent = r.message;
  } catch (e) { s.textContent = "Ошибка: " + e.message; }
});
```

- [ ] **Step 4: Чат со стримингом** — в `static/app.js`

```javascript
let aiInited = false;
const chatHistory = [];  // {role, content}

async function initAi() {
  if (aiInited) return;
  aiInited = true;
  try {
    const { suggestions } = await api("/api/chat/suggestions");
    const box = document.getElementById("chat-suggestions");
    box.innerHTML = "";
    for (const s of suggestions) {
      const b = document.createElement("button");
      b.className = "suggestion";
      b.textContent = s;
      b.addEventListener("click", () => sendChat(s));
      box.appendChild(b);
    }
  } catch (_) {}
}

function appendBubble(role, text) {
  const log = document.getElementById("chat-log");
  const d = document.createElement("div");
  d.className = "bubble bubble--" + role;
  d.textContent = text;
  log.appendChild(d);
  log.scrollTop = log.scrollHeight;
  return d;
}

async function streamInto(url, body, bubble) {
  const r = await fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body) });
  if (!r.ok) {
    let msg = "Ошибка " + r.status;
    try { msg = (await r.json()).detail || msg; } catch (_) {}
    bubble.textContent = msg;
    return "";
  }
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let acc = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    acc += dec.decode(value, { stream: true });
    bubble.textContent = acc;
    document.getElementById("chat-log").scrollTop = 1e9;
  }
  return acc;
}

async function sendChat(text) {
  const input = document.getElementById("chat-input");
  const q = text || input.value.trim();
  if (!q) return;
  input.value = "";
  appendBubble("user", q);
  chatHistory.push({ role: "user", content: q });
  const bubble = appendBubble("assistant", "…");
  const answer = await streamInto("/api/chat", { messages: chatHistory }, bubble);
  if (answer) chatHistory.push({ role: "assistant", content: answer });
}

document.getElementById("chat-form").addEventListener("submit", (e) => {
  e.preventDefault(); sendChat();
});
document.getElementById("analyze-btn").addEventListener("click", async () => {
  appendBubble("user", "Анализ узких мест");
  const bubble = appendBubble("assistant", "…");
  await streamInto("/api/analyze", {}, bubble);
});
```

- [ ] **Step 5: Стили** — в `static/style.css` добавить минимальные стили

```css
#top-nav { display: flex; gap: 6px; margin: 8px 0; }
.topnav__btn { padding: 6px 14px; border: 1px solid #cdd6e4; background: #fff; border-radius: 6px; cursor: pointer; }
.topnav__btn--active { background: #1f3a5f; color: #fff; border-color: #1f3a5f; }
#chat-log { height: 52vh; overflow-y: auto; border: 1px solid #e3eaf5; border-radius: 8px; padding: 10px; background: #f6f8fc; }
.bubble { max-width: 80%; margin: 6px 0; padding: 8px 12px; border-radius: 10px; white-space: pre-wrap; }
.bubble--user { margin-left: auto; background: #1f3a5f; color: #fff; }
.bubble--assistant { background: #fff; border: 1px solid #e3eaf5; }
#chat-form { display: flex; gap: 8px; margin-top: 8px; }
#chat-input { flex: 1; padding: 8px; border: 1px solid #cdd6e4; border-radius: 6px; }
#chat-suggestions { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.suggestion { font-size: 12px; padding: 4px 10px; border: 1px solid #cdd6e4; border-radius: 12px; background: #fff; cursor: pointer; }
#llm-form label { display: block; margin: 8px 0; }
#llm-form input { width: 360px; max-width: 100%; padding: 6px; margin-left: 8px; }
```

- [ ] **Step 6: Проверка синтаксиса и ручной прогон**

```
cd "C:/Users/Korotaev_NO/Desktop/Проекты/presale-dashboard" && node --check static/app.js && echo JS_OK
```
Запустить сервер (`.venv/Scripts/python.exe -m uvicorn src.main:app --port 8091`), открыть, убедиться: переключение вкладок работает, бэкофис грузит настройки и сохраняет (токен маскируется), вкладка ИИ показывает подсказки. (Реальный ответ модели зависит от доступности Qwen — при недоступности показывается сообщение об ошибке в пузыре.)

- [ ] **Step 7: Коммит**

```
git add static/index.html static/app.js static/style.css
git -c core.safecrlf=false commit -m "feat: вкладки «ИИ-аналитик» (чат со стримингом, подсказки, анализ) и «Бэкофис» (настройки LLM)"
```

---

## Task 7: E2E-тест (Playwright, LLM замокан)

**Files:**
- Create: `tests/e2e/test_ai_chat.py`

**Interfaces:**
- Consumes: запущенный сервер (фикстура uvicorn с temp `PRESALE_DB`), Playwright sync API.

Переиспользовать паттерн существующего `tests/e2e/test_dashboard.py` (session-scoped фикстура uvicorn с temp БД, stdout сервера в файл, ожидание `/api/health`). Чтобы не зависеть от реального LLM, установить переменную окружения `LLM_FAKE=1`, которую бэкенд (в `chat_service.stream_answer`/`stream_analysis` или через отдельную проверку в эндпоинте) распознаёт и отдаёт фиктивный детерминированный ответ.

- [ ] **Step 1: Добавить тестовый режим LLM** — в `src/main.py`

В эндпоинтах `/api/chat` и `/api/analyze`, перед вызовом `chat_service`, добавить ветку:
```python
import os
...
    if os.environ.get("LLM_FAKE") == "1":
        def gen():
            yield "Тестовый ответ: узкое место — команда Slow (ср. длительность высокая)."
        return StreamingResponse(gen(), media_type="text/plain; charset=utf-8")
```
(Разместить в обеих функциях сразу после получения events/cfg.)

- [ ] **Step 2: Написать E2E** `tests/e2e/test_ai_chat.py`

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
    # загрузить фикстуру
    import httpx
    with open(ROOT / "tests/fixtures/statistika_source_v14.xlsx", "rb") as f:
        httpx.post(base + "/api/upload", files={"file": f},
                   data={"uploaded_by": "e2e"}, timeout=180)
    yield base
    proc.terminate(); log.close()


def test_ai_chat_flow(server):
    shots = ROOT / "tmp" / "screenshots"; shots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page()
        pg.goto(server)
        pg.click("button[data-view='ai']")
        expect(pg.locator("#chat-suggestions .suggestion").first).to_be_visible()
        pg.fill("#chat-input", "Где узкое место?")
        pg.click("#chat-form button[type='submit']")
        expect(pg.locator(".bubble--assistant").last).to_contain_text("узкое место")
        pg.screenshot(path=str(shots / "ai-chat.png"))
        # бэкофис
        pg.click("button[data-view='backoffice']")
        expect(pg.locator("#llm-base-url")).to_have_value(lambda v: v.startswith("http") if v else False)
        b.close()
```
Если matcher `to_have_value(lambda…)` недоступен в установленной версии Playwright, заменить на чтение значения: `assert pg.input_value("#llm-base-url").startswith("http")`.

- [ ] **Step 3: Запустить E2E**

Run: `.venv/Scripts/python.exe -m pytest tests/e2e/test_ai_chat.py -v`
Expected: PASS. Скриншот в `tmp/screenshots/ai-chat.png`.

- [ ] **Step 4: Коммит**

```
git add src/main.py tests/e2e/test_ai_chat.py
git -c core.safecrlf=false commit -m "test: E2E ИИ-чата (Playwright, LLM замокан через LLM_FAKE)"
```

---

## Финал

- [ ] Прогнать весь набор: `.venv/Scripts/python.exe -m pytest tests/ -q` — всё зелёное, покрытие ≥70%.
- [ ] Обновить `README.md`: раздел про ИИ-аналитик и бэкофис, переменная `LLM_TOKEN`, что токен не в git.
- [ ] Пересобрать Docker при необходимости (новая зависимость openai) и проверить запуск.
