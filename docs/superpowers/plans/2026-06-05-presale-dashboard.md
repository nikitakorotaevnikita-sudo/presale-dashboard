# Дашборд пресейла ОГВ — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Веб-приложение: загрузка большого xlsx «Статистика по выполненным работам» → дашборд с 5 показателями, фильтрами и drill-down + экспорт привычного маленького Excel.

**Architecture:** FastAPI backend читает лист «Исх данные», нормализует строки и кладёт в SQLite. Чистые функции в `metrics.py` считают показатели из событий с учётом фильтров. Vanilla-JS фронтенд (вкладки, графики Chart.js, drill-down) ходит в JSON-эндпоинты. Экспорт собирает xlsx через openpyxl.

**Tech Stack:** Python 3.10+, FastAPI, Uvicorn, openpyxl, SQLite (stdlib), pytest+pytest-cov, Playwright, Chart.js (локально).

**Спецификация:** `docs/superpowers/specs/2026-06-05-presale-dashboard-design.md`

**Точные имена колонок листа «Исх данные»** (по индексам): 0 «Месяц начала текущего статуса», 1 «Длительность проработки запроса (раб. дн.)», 2 «Продукт», 3 «Масштаб», 4 «Услуга», 5 «ИД запроса», 6 «Запрос на пресейл», 8 «Организация», 11 «Инициатор», 14 «Команда», 15 «Бизнес-единица», 21 «Предыдущий статус», 22 «Статус», 23 «Дата начала статуса», 24 «Дата окончания статуса», 25 «Длительность, р.д.», 28 «Отработано часов», 29 «Примечание».

**Статусы в данных:** Инициализация, В работе, На контроле, На уточнении, Принято, Закрыто, Отказано.

---

## Task 0: Каркас проекта

**Files:**
- Create: `pyproject.toml`, `src/__init__.py`, `src/config.py`, `src/main.py`, `tests/__init__.py`, `tests/unit/__init__.py`, `static/.gitkeep`, `data/.gitkeep`

- [ ] **Step 1: Создать venv и pyproject**

`pyproject.toml`:

```toml
[project]
name = "presale-dashboard"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "openpyxl>=3.1",
    "python-multipart>=0.0.9",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-cov>=5", "httpx>=0.27", "playwright>=1.44"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"

[tool.coverage.run]
source = ["src"]
```

- [ ] **Step 2: Создать venv и поставить зависимости**

Run:
```bash
cd "C:/Users/Korotaev_NO/Desktop/Проекты/presale-dashboard"
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"
```
Expected: установка без ошибок.

- [ ] **Step 3: Минимальный config и app**

`src/config.py`:
```python
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "presale.db"
STATIC_DIR = BASE_DIR / "static"
SHEET_NAME = "Исх данные"
```

`src/main.py`:
```python
from fastapi import FastAPI

app = FastAPI(title="Дашборд пресейла ОГВ")

@app.get("/api/health")
def health():
    return {"status": "ok"}
```

- [ ] **Step 4: Проверить запуск**

Run:
```bash
.venv/Scripts/python.exe -m uvicorn src.main:app --port 8010 &
sleep 3 && curl -s http://localhost:8010/api/health
```
Expected: `{"status":"ok"}`. Остановить процесс.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: каркас проекта (FastAPI + pyproject + health)"
```

---

## Task 1: Модель и парсинг листа «Исх данные»

**Files:**
- Create: `src/models.py`, `src/parsing.py`
- Test: `tests/unit/test_parsing.py`

- [ ] **Step 1: Написать модель**

`src/models.py`:
```python
from dataclasses import dataclass, fields
from typing import Optional


@dataclass
class StatusEvent:
    request_id: str
    request: str
    org: str
    product: str
    scale: str
    service: str
    initiator: str
    team: str
    business_unit: str
    status: str
    prev_status: str
    date_start: str
    date_end: str
    month: Optional[int]
    duration_rd: float
    work_duration_rd: float  # «Длительность проработки запроса (раб. дн.)»
    hours: Optional[float]
    note: str


EVENT_FIELDS = [f.name for f in fields(StatusEvent)]

# Разрез (имя на русском в UI) -> атрибут StatusEvent
DIMENSION_ATTR = {
    "услуга": "service",
    "продукт": "product",
    "масштаб": "scale",
    "инициатор": "initiator",
    "команда": "team",
}
```

- [ ] **Step 2: Написать падающий тест парсинга**

`tests/unit/test_parsing.py`:
```python
from pathlib import Path
import openpyxl
import pytest
from src.parsing import parse_workbook, ParseError

FIXTURE = Path("tests/fixtures/statistika_source_v14.xlsx")


def test_parse_returns_events():
    events = parse_workbook(FIXTURE)
    assert len(events) == 232
    e = events[0]
    assert e.request_id  # не пустой
    assert e.status in {
        "Инициализация", "В работе", "На контроле",
        "На уточнении", "Принято", "Закрыто", "Отказано",
    }
    assert isinstance(e.month, int) and 1 <= e.month <= 12


def test_parse_missing_sheet(tmp_path):
    p = tmp_path / "bad.xlsx"
    wb = openpyxl.Workbook()
    wb.save(p)
    with pytest.raises(ParseError, match="Исх данные"):
        parse_workbook(p)


def test_parse_missing_columns(tmp_path):
    p = tmp_path / "nocols.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Исх данные"
    ws.append(["ИД запроса", "Статус"])  # не хватает колонок
    wb.save(p)
    with pytest.raises(ParseError, match="отсутствуют колонки"):
        parse_workbook(p)
```

- [ ] **Step 3: Запустить — тест падает**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_parsing.py -v`
Expected: FAIL (нет модуля `src.parsing`).

- [ ] **Step 4: Реализовать парсинг**

`src/parsing.py`:
```python
import openpyxl
from src.config import SHEET_NAME
from src.models import StatusEvent

REQUIRED_COLUMNS = [
    "Месяц начала текущего статуса",
    "Длительность проработки запроса (раб. дн.)",
    "Продукт", "Масштаб", "Услуга", "ИД запроса", "Запрос на пресейл",
    "Организация", "Инициатор", "Команда", "Бизнес-единица",
    "Предыдущий статус", "Статус", "Дата начала статуса",
    "Дата окончания статуса", "Длительность, р.д.",
    "Отработано часов", "Примечание",
]


class ParseError(Exception):
    pass


def _f(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _i(v):
    f = _f(v)
    return int(f) if f is not None else None


def _s(v):
    return "" if v is None else str(v).strip()


def parse_workbook(path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        if SHEET_NAME not in wb.sheetnames:
            raise ParseError(f"В файле нет листа «{SHEET_NAME}»")
        ws = wb[SHEET_NAME]
        it = ws.iter_rows(values_only=True)
        header = list(next(it))
        idx = {name: i for i, name in enumerate(header) if name is not None}
        missing = [c for c in REQUIRED_COLUMNS if c not in idx]
        if missing:
            raise ParseError("В листе отсутствуют колонки: " + ", ".join(missing))

        def g(row, name):
            i = idx[name]
            return row[i] if i < len(row) else None

        events = []
        for row in it:
            rid = g(row, "ИД запроса")
            if rid in (None, ""):
                continue
            events.append(StatusEvent(
                request_id=_s(rid),
                request=_s(g(row, "Запрос на пресейл")),
                org=_s(g(row, "Организация")),
                product=_s(g(row, "Продукт")),
                scale=_s(g(row, "Масштаб")),
                service=_s(g(row, "Услуга")),
                initiator=_s(g(row, "Инициатор")),
                team=_s(g(row, "Команда")),
                business_unit=_s(g(row, "Бизнес-единица")),
                status=_s(g(row, "Статус")),
                prev_status=_s(g(row, "Предыдущий статус")),
                date_start=_s(g(row, "Дата начала статуса")),
                date_end=_s(g(row, "Дата окончания статуса")),
                month=_i(g(row, "Месяц начала текущего статуса")),
                duration_rd=_f(g(row, "Длительность, р.д.")) or 0.0,
                work_duration_rd=_f(g(row, "Длительность проработки запроса (раб. дн.)")) or 0.0,
                hours=_f(g(row, "Отработано часов")),
                note=_s(g(row, "Примечание")),
            ))
        return events
    finally:
        wb.close()
```

- [ ] **Step 5: Запустить — тесты проходят**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_parsing.py -v`
Expected: PASS (3 теста).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: модель StatusEvent и парсинг листа «Исх данные»"
```

---

## Task 2: Расчёт показателей (metrics.py)

**Files:**
- Create: `src/metrics.py`
- Test: `tests/unit/test_metrics.py`

- [ ] **Step 1: Написать падающие тесты на показатели и дедуп**

`tests/unit/test_metrics.py`:
```python
from src.models import StatusEvent
from src import metrics


def ev(request_id, status, month, service="A", team="T1",
       hours=None, work=0.0, dur=0.0, product="P", scale="S", initiator="I"):
    return StatusEvent(
        request_id=request_id, request="req", org="org", product=product,
        scale=scale, service=service, initiator=initiator, team=team,
        business_unit="BU", status=status, prev_status="", date_start="",
        date_end="", month=month, duration_rd=dur, work_duration_rd=work,
        hours=hours, note="",
    )


def test_postupilo_counts_distinct_init():
    events = [
        ev("1", "Инициализация", 1, service="A"),
        ev("2", "Инициализация", 1, service="A"),
        ev("3", "Инициализация", 2, service="B"),
        ev("1", "В работе", 1, service="A"),  # не считается
    ]
    cells = metrics.compute_cells(events, "поступило", "услуга")
    assert cells[("A", 1)] == 2
    assert cells[("B", 2)] == 1


def test_postupilo_dedups_redirected():
    # перенаправленный запрос: две строки «Инициализация» с одним id → 1
    events = [
        ev("9", "Инициализация", 3, service="A"),
        ev("9", "Инициализация", 3, service="A"),
    ]
    cells = metrics.compute_cells(events, "поступило", "услуга")
    assert cells[("A", 3)] == 1


def test_avg_hours_one_value_per_request():
    events = [
        ev("1", "Принято", 4, service="A", hours=10.0),
        ev("2", "Принято", 4, service="A", hours=20.0),
        ev("3", "Принято", 4, service="B", hours=None),  # пусто → не учитывается
    ]
    cells = metrics.compute_cells(events, "трудоемкость", "услуга")
    assert cells[("A", 4)] == 15.0
    assert ("B", 4) not in cells


def test_avg_duration_sums_work_duration_per_request():
    # «Длительность проработки запроса» суммируется по строкам запроса
    events = [
        ev("1", "Инициализация", 5, service="A", work=3.0),
        ev("1", "В работе", 5, service="A", work=7.0),
        ev("1", "Принято", 5, service="A", work=0.0),  # строка принятия даёт месяц/разрез
    ]
    cells = metrics.compute_cells(events, "длительность", "услуга")
    assert cells[("A", 5)] == 10.0


def test_avg_control_sums_control_duration():
    events = [
        ev("1", "На контроле", 6, service="A", dur=4.0),
        ev("1", "Принято", 6, service="A"),
        ev("2", "Принято", 6, service="A"),  # без контроля → 0
    ]
    cells = metrics.compute_cells(events, "на_контроле", "услуга")
    assert cells[("A", 6)] == 2.0  # (4 + 0) / 2


def test_filter_events_by_team():
    events = [ev("1", "Принято", 1, team="T1"), ev("2", "Принято", 1, team="T2")]
    out = metrics.filter_events(events, teams=["T1"])
    assert [e.request_id for e in out] == ["1"]


def test_build_matrix_shape():
    events = [ev("1", "Инициализация", 1, service="A"),
              ev("2", "Инициализация", 2, service="A")]
    m = metrics.build_matrix(events, "поступило", "услуга", months=[1, 2, 3])
    assert m["rows"] == ["A"]
    assert m["months"] == [1, 2, 3]
    assert m["values"]["A"][1] == 1
    assert m["values"]["A"][3] is None
```

- [ ] **Step 2: Запустить — падает**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_metrics.py -v`
Expected: FAIL (нет `src.metrics`).

- [ ] **Step 3: Реализовать metrics.py**

`src/metrics.py`:
```python
from collections import defaultdict
from statistics import mean

from src.models import DIMENSION_ATTR

STATUS_INIT = "Инициализация"
STATUS_ACCEPTED = "Принято"
STATUS_IN_WORK = "В работе"
STATUS_ON_CONTROL = "На контроле"

METRICS = ["поступило", "проработано", "трудоемкость", "длительность", "на_контроле"]


def _attr(dim):
    if dim not in DIMENSION_ATTR:
        raise ValueError(f"Неизвестный разрез: {dim}")
    return DIMENSION_ATTR[dim]


def filter_events(events, services=None, products=None, scales=None,
                  teams=None, initiators=None):
    def ok(e):
        if services and e.service not in services:
            return False
        if products and e.product not in products:
            return False
        if scales and e.scale not in scales:
            return False
        if teams and e.team not in teams:
            return False
        if initiators and e.initiator not in initiators:
            return False
        return True
    return [e for e in events if ok(e)]


def _count(events, status, dim):
    attr = _attr(dim)
    buckets = defaultdict(set)
    for e in events:
        if e.status == status and e.month:
            buckets[(getattr(e, attr), e.month)].add(e.request_id)
    return {k: len(v) for k, v in buckets.items()}


def _avg_hours(events, dim):
    attr = _attr(dim)
    buckets = defaultdict(dict)
    for e in events:
        if e.status == STATUS_ACCEPTED and e.month and e.hours is not None:
            buckets[(getattr(e, attr), e.month)][e.request_id] = e.hours
    return {k: mean(d.values()) for k, d in buckets.items() if d}


def _avg_duration(events, dim):
    attr = _attr(dim)
    sums = defaultdict(float)
    for e in events:
        sums[e.request_id] += e.work_duration_rd
    buckets = defaultdict(dict)
    for e in events:
        if e.status == STATUS_ACCEPTED and e.month:
            buckets[(getattr(e, attr), e.month)][e.request_id] = sums[e.request_id]
    return {k: mean(d.values()) for k, d in buckets.items() if d}


def _avg_control(events, dim):
    attr = _attr(dim)
    control = defaultdict(float)
    for e in events:
        if e.status == STATUS_ON_CONTROL:
            control[e.request_id] += e.duration_rd
    buckets = defaultdict(dict)
    for e in events:
        if e.status == STATUS_ACCEPTED and e.month:
            buckets[(getattr(e, attr), e.month)][e.request_id] = control.get(e.request_id, 0.0)
    return {k: mean(d.values()) for k, d in buckets.items() if d}


def compute_cells(events, metric, dim):
    if metric == "поступило":
        return _count(events, STATUS_INIT, dim)
    if metric == "проработано":
        return _count(events, STATUS_ACCEPTED, dim)
    if metric == "трудоемкость":
        return _avg_hours(events, dim)
    if metric == "длительность":
        return _avg_duration(events, dim)
    if metric == "на_контроле":
        return _avg_control(events, dim)
    raise ValueError(f"Неизвестный показатель: {metric}")


def build_matrix(events, metric, dim, months=range(1, 13)):
    cells = compute_cells(events, metric, dim)
    months = list(months)
    rows = sorted({k[0] for k in cells})
    values = {rv: {m: cells.get((rv, m)) for m in months} for rv in rows}
    return {"metric": metric, "dimension": dim, "rows": rows,
            "months": months, "values": values}


def drilldown(events, metric, dim, value, month):
    """Список запросов за конкретной ячейкой (число/среднее)."""
    attr = _attr(dim)
    status = STATUS_INIT if metric == "поступило" else STATUS_ACCEPTED
    work_sums = defaultdict(float)
    control_sums = defaultdict(float)
    for e in events:
        work_sums[e.request_id] += e.work_duration_rd
        if e.status == STATUS_ON_CONTROL:
            control_sums[e.request_id] += e.duration_rd
    seen = {}
    for e in events:
        if e.status == status and e.month == month and getattr(e, attr) == value:
            seen[e.request_id] = e
    out = []
    for rid, e in seen.items():
        item = {"request_id": rid, "request": e.request, "org": e.org,
                "service": e.service, "team": e.team, "status": e.status,
                "date_start": e.date_start}
        if metric == "трудоемкость":
            item["value"] = e.hours
        elif metric == "длительность":
            item["value"] = work_sums[rid]
        elif metric == "на_контроле":
            item["value"] = control_sums.get(rid, 0.0)
        out.append(item)
    return sorted(out, key=lambda x: x["request"])
```

- [ ] **Step 4: Запустить — тесты проходят**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_metrics.py -v`
Expected: PASS (8 тестов).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: расчёт 5 показателей, фильтры, матрица, drill-down"
```

---

## Task 3: Golden-тест против эталона v1

**Files:**
- Test: `tests/unit/test_golden.py`

- [ ] **Step 1: Написать golden-тест**

`tests/unit/test_golden.py`:
```python
from pathlib import Path
import openpyxl
from src.parsing import parse_workbook
from src import metrics

SRC = Path("tests/fixtures/statistika_source_v14.xlsx")
EXPECTED = Path("tests/fixtures/znacheniya_expected_v1.xlsx")


def _expected_sheet(sheet_name):
    """Читает эталонный лист: {(услуга, месяц): значение}."""
    wb = openpyxl.load_workbook(EXPECTED, data_only=True)
    ws = wb[sheet_name]
    rows = list(ws.iter_rows(values_only=True))
    header = rows[0]
    months = {i: c.month for i, c in enumerate(header)
              if hasattr(c, "month")}
    out = {}
    for r in rows[1:]:
        service = r[0]
        if not service:
            continue
        for i, mon in months.items():
            v = r[i] if i < len(r) else None
            if v is not None:
                out[(str(service).strip(), mon)] = v
    wb.close()
    return out


def test_postupilo_matches_v1_counts():
    events = parse_workbook(SRC)
    cells = metrics.compute_cells(events, "поступило", "услуга")
    expected = _expected_sheet("Поступило")
    # счётчики должны совпадать 1-в-1 по пересечению ключей
    for key, exp in expected.items():
        assert cells.get(key, 0) == exp, f"Поступило {key}: {cells.get(key)} != {exp}"


def test_prorabotano_matches_v1_counts():
    events = parse_workbook(SRC)
    cells = metrics.compute_cells(events, "проработано", "услуга")
    expected = _expected_sheet("Проработано")
    for key, exp in expected.items():
        assert cells.get(key, 0) == exp, f"Проработано {key}: {cells.get(key)} != {exp}"


def test_trudoemkost_matches_v1_with_tolerance():
    events = parse_workbook(SRC)
    cells = metrics.compute_cells(events, "трудоемкость", "услуга")
    expected = _expected_sheet("Ср. трудоемкость")
    mismatches = []
    for key, exp in expected.items():
        got = cells.get(key)
        if got is None or abs(got - exp) > 0.1:
            mismatches.append((key, got, exp))
    # допускаем максимум 1 расхождение (переклассифицированный апрельский запрос)
    assert len(mismatches) <= 1, f"Слишком много расхождений: {mismatches}"
```

- [ ] **Step 2: Запустить golden-тест**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_golden.py -v`
Expected: PASS. Если счётчики (Поступило/Проработано) расходятся — баг в логике, чинить metrics. Расхождение трудоёмкости >1 ячейки — тоже баг.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "test: golden-тест расчёта против эталона v1"
```

---

## Task 4: Хранилище SQLite (storage.py)

**Files:**
- Create: `src/storage.py`
- Test: `tests/unit/test_storage.py`

- [ ] **Step 1: Написать падающие тесты**

`tests/unit/test_storage.py`:
```python
from src.models import StatusEvent
from src import storage


def ev(rid, status="Принято", month=1, service="A"):
    return StatusEvent(
        request_id=rid, request="r", org="o", product="P", scale="S",
        service=service, initiator="I", team="T", business_unit="BU",
        status=status, prev_status="", date_start="", date_end="",
        month=month, duration_rd=1.0, work_duration_rd=2.0, hours=5.0, note="",
    )


def test_replace_and_load_roundtrip(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    storage.init_db(conn)
    storage.replace_events(conn, [ev("1"), ev("2")], "file.xlsx", "Анна")
    loaded = storage.load_events(conn)
    assert {e.request_id for e in loaded} == {"1", "2"}
    assert loaded[0].hours == 5.0


def test_replace_is_atomic_overwrite(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    storage.init_db(conn)
    storage.replace_events(conn, [ev("1")], "a.xlsx", "Анна")
    storage.replace_events(conn, [ev("2"), ev("3")], "b.xlsx", "Анна")
    loaded = storage.load_events(conn)
    assert {e.request_id for e in loaded} == {"2", "3"}  # старое удалено


def test_last_upload_metadata(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    storage.init_db(conn)
    storage.replace_events(conn, [ev("1")], "stat.xlsx", "Анна")
    up = storage.last_upload(conn)
    assert up["filename"] == "stat.xlsx"
    assert up["row_count"] == 1
    assert up["uploaded_by"] == "Анна"


def test_distinct_values(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    storage.init_db(conn)
    storage.replace_events(conn, [ev("1", service="A"), ev("2", service="B")],
                           "f.xlsx", "Анна")
    vals = storage.distinct_values(conn)
    assert vals["услуга"] == ["A", "B"]
```

- [ ] **Step 2: Запустить — падает**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_storage.py -v`
Expected: FAIL.

- [ ] **Step 3: Реализовать storage.py**

`src/storage.py`:
```python
import sqlite3
from datetime import datetime, timezone

from src.models import StatusEvent, EVENT_FIELDS, DIMENSION_ATTR

_COLS = ", ".join(EVENT_FIELDS)
_PLACEHOLDERS = ", ".join("?" for _ in EVENT_FIELDS)


def connect(path):
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn):
    cols_ddl = ", ".join(f"{f} TEXT" if f in (
        "request_id", "request", "org", "product", "scale", "service",
        "initiator", "team", "business_unit", "status", "prev_status",
        "date_start", "date_end", "note",
    ) else f"{f} REAL" if f in ("duration_rd", "work_duration_rd", "hours")
        else f"{f} INTEGER" for f in EVENT_FIELDS)
    conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS status_events ({cols_ddl});
        CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT, uploaded_at TEXT, row_count INTEGER, uploaded_by TEXT
        );
    """)
    conn.commit()


def replace_events(conn, events, filename, uploaded_by):
    rows = [tuple(getattr(e, f) for f in EVENT_FIELDS) for e in events]
    with conn:  # транзакция: всё или ничего
        conn.execute("DELETE FROM status_events")
        conn.executemany(
            f"INSERT INTO status_events ({_COLS}) VALUES ({_PLACEHOLDERS})", rows)
        conn.execute(
            "INSERT INTO uploads (filename, uploaded_at, row_count, uploaded_by) "
            "VALUES (?, ?, ?, ?)",
            (filename, datetime.now(timezone.utc).isoformat(), len(rows), uploaded_by))


def load_events(conn):
    cur = conn.execute(f"SELECT {_COLS} FROM status_events")
    return [StatusEvent(**dict(row)) for row in cur.fetchall()]


def last_upload(conn):
    row = conn.execute(
        "SELECT filename, uploaded_at, row_count, uploaded_by "
        "FROM uploads ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def distinct_values(conn):
    out = {}
    for dim, attr in DIMENSION_ATTR.items():
        cur = conn.execute(
            f"SELECT DISTINCT {attr} FROM status_events "
            f"WHERE {attr} != '' ORDER BY {attr}")
        out[dim] = [r[0] for r in cur.fetchall()]
    return out
```

- [ ] **Step 4: Запустить — проходит**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_storage.py -v`
Expected: PASS (4 теста).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: хранилище SQLite (события, история загрузок, фильтры)"
```

---

## Task 5: Экспорт в Excel (export.py)

**Files:**
- Create: `src/export.py`
- Test: `tests/unit/test_export.py`

- [ ] **Step 1: Написать падающий тест**

`tests/unit/test_export.py`:
```python
import io
import openpyxl
from src.models import StatusEvent
from src.export import build_export


def ev(rid, status, month, service="A", hours=None, work=0.0, dur=0.0):
    return StatusEvent(
        request_id=rid, request="r", org="o", product="P", scale="S",
        service=service, initiator="I", team="T", business_unit="BU",
        status=status, prev_status="", date_start="", date_end="",
        month=month, duration_rd=dur, work_duration_rd=work, hours=hours, note="",
    )


def test_export_has_all_metric_sheets():
    events = [ev("1", "Инициализация", 1), ev("1", "Принято", 2, hours=10.0)]
    data = build_export(events, dimension="услуга")
    wb = openpyxl.load_workbook(io.BytesIO(data))
    assert set(wb.sheetnames) == {
        "Поступило", "Проработано", "Ср. трудоемкость",
        "Ср. длительность", "Ср. на контроле"}


def test_export_values_placed_by_month():
    events = [ev("1", "Инициализация", 3, service="A")]
    data = build_export(events, dimension="услуга")
    wb = openpyxl.load_workbook(io.BytesIO(data))
    ws = wb["Поступило"]
    # шапка: A1 заголовок, B1..M1 = месяцы 1..12; строка услуги "A"
    header = [c.value for c in ws[1]]
    assert header[3] == 3  # колонка месяца 3 (B=1,C=2,D=3)
    row = [c.value for c in ws[2]]
    assert row[0] == "A"
    assert row[3] == 1
```

- [ ] **Step 2: Запустить — падает**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_export.py -v`
Expected: FAIL.

- [ ] **Step 3: Реализовать export.py**

`src/export.py`:
```python
import io
from openpyxl import Workbook

from src import metrics

SHEETS = [
    ("Поступило", "поступило"),
    ("Проработано", "проработано"),
    ("Ср. трудоемкость", "трудоемкость"),
    ("Ср. длительность", "длительность"),
    ("Ср. на контроле", "на_контроле"),
]


def build_export(events, dimension="услуга", months=range(1, 13)):
    months = list(months)
    wb = Workbook()
    wb.remove(wb.active)
    for sheet_name, metric in SHEETS:
        ws = wb.create_sheet(sheet_name)
        ws.append([sheet_name] + months)
        m = metrics.build_matrix(events, metric, dimension, months=months)
        for rv in m["rows"]:
            row = [rv]
            for mon in months:
                v = m["values"][rv][mon]
                row.append(round(v, 1) if isinstance(v, float) else v)
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
```

- [ ] **Step 4: Запустить — проходит**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_export.py -v`
Expected: PASS (2 теста).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: экспорт показателей в xlsx (5 листов, разрез, месяцы)"
```

---

## Task 6: API-эндпоинты (main.py)

**Files:**
- Modify: `src/main.py`
- Test: `tests/unit/test_api.py`

- [ ] **Step 1: Написать падающие тесты API**

`tests/unit/test_api.py`:
```python
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
```

- [ ] **Step 2: Дополнить config поддержкой env-пути к БД**

Изменить `src/config.py` — заменить строку `DB_PATH = ...` на:
```python
import os
DB_PATH = Path(os.environ.get("PRESALE_DB", BASE_DIR / "data" / "presale.db"))
```

- [ ] **Step 3: Запустить — падает**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_api.py -v`
Expected: FAIL (нет эндпоинтов).

- [ ] **Step 4: Реализовать main.py**

`src/main.py`:
```python
import tempfile
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles

from src import config, storage, metrics, export
from src.parsing import parse_workbook, ParseError

app = FastAPI(title="Дашборд пресейла ОГВ")


def _conn():
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = storage.connect(config.DB_PATH)
    storage.init_db(conn)
    return conn


def _events_filtered(conn, q):
    events = storage.load_events(conn)
    return metrics.filter_events(
        events,
        services=q.get("services"), products=q.get("products"),
        scales=q.get("scales"), teams=q.get("teams"),
        initiators=q.get("initiators"))


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...), uploaded_by: str = Form("")):
    suffix = Path(file.filename or "f.xlsx").suffix or ".xlsx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    try:
        events = parse_workbook(tmp_path)
    except (ParseError, Exception) as exc:
        raise HTTPException(status_code=400, detail=f"Не удалось прочитать файл: {exc}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    conn = _conn()
    storage.replace_events(conn, events, file.filename or "", uploaded_by)
    return {"row_count": len(events), "upload": storage.last_upload(conn)}


@app.get("/api/status")
def status():
    return {"upload": storage.last_upload(_conn())}


@app.get("/api/filters")
def filters():
    return storage.distinct_values(_conn())


def _list_param(value):
    return [v for v in value.split(",") if v] if value else None


@app.get("/api/metrics")
def get_metrics(metric: str, dimension: str,
                services: str = "", products: str = "", scales: str = "",
                teams: str = "", initiators: str = ""):
    if metric not in metrics.METRICS:
        raise HTTPException(400, f"Неизвестный показатель: {metric}")
    conn = _conn()
    events = _events_filtered(conn, {
        "services": _list_param(services), "products": _list_param(products),
        "scales": _list_param(scales), "teams": _list_param(teams),
        "initiators": _list_param(initiators)})
    return metrics.build_matrix(events, metric, dimension)


@app.get("/api/requests")
def get_requests(metric: str, dimension: str, value: str, month: int,
                 services: str = "", products: str = "", scales: str = "",
                 teams: str = "", initiators: str = ""):
    conn = _conn()
    events = _events_filtered(conn, {
        "services": _list_param(services), "products": _list_param(products),
        "scales": _list_param(scales), "teams": _list_param(teams),
        "initiators": _list_param(initiators)})
    return metrics.drilldown(events, metric, dimension, value, month)


@app.get("/api/export")
def get_export(dimension: str = "услуга",
               services: str = "", products: str = "", scales: str = "",
               teams: str = "", initiators: str = ""):
    conn = _conn()
    events = _events_filtered(conn, {
        "services": _list_param(services), "products": _list_param(products),
        "scales": _list_param(scales), "teams": _list_param(teams),
        "initiators": _list_param(initiators)})
    data = export.build_export(events, dimension=dimension)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 'attachment; filename="presale_metrics.xlsx"'})


# статика монтируется последней, чтобы не перехватывать /api/*
if config.STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(config.STATIC_DIR), html=True), name="static")
```

> Примечание: `except (ParseError, Exception)` ловит и битые xlsx (openpyxl бросает свои исключения). Это намеренно — любой сбой чтения = 400 с понятным текстом.

- [ ] **Step 5: Запустить — проходит**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_api.py -v`
Expected: PASS (5 тестов).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: API — upload, metrics, filters, requests, export"
```

---

## Task 7: Фронтенд (дашборд, вариант A)

**Files:**
- Create: `static/index.html`, `static/style.css`, `static/app.js`, `static/vendor/chart.umd.min.js`

- [ ] **Step 1: Сохранить Chart.js локально**

Run:
```bash
mkdir -p static/vendor
curl -sL https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js -o static/vendor/chart.umd.min.js
test -s static/vendor/chart.umd.min.js && echo OK
```
Expected: `OK` (файл не пустой). Если интернета нет — скопировать chart.umd.min.js вручную в `static/vendor/`.

- [ ] **Step 2: index.html**

`static/index.html`:
```html
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Дашборд пресейла ОГВ</title>
  <link rel="stylesheet" href="/style.css">
</head>
<body>
  <header class="topbar">
    <div class="title">Пресейл ОГВ · показатели</div>
    <div class="upload-info" id="uploadInfo">Данные не загружены</div>
    <div class="actions">
      <label class="btn">⬆ Загрузить файл
        <input type="file" id="fileInput" accept=".xlsx" hidden>
      </label>
      <button class="btn" id="exportBtn">⬇ Выгрузить Excel</button>
    </div>
  </header>

  <section class="kpis" id="kpis"></section>

  <section class="filters" id="filters"></section>

  <nav class="tabs" id="tabs"></nav>

  <div class="dim-switch">
    Разрез по:
    <select id="dimSelect">
      <option value="услуга">Услуга</option>
      <option value="продукт">Продукт</option>
      <option value="масштаб">Масштаб</option>
      <option value="инициатор">Инициатор</option>
      <option value="команда">Команда</option>
    </select>
  </div>

  <main class="content">
    <div class="chart-box"><canvas id="chart"></canvas></div>
    <div class="table-box" id="tableBox"></div>
  </main>

  <div class="drawer hidden" id="drawer">
    <div class="drawer-head">
      <span id="drawerTitle">Запросы</span>
      <button id="drawerClose">✕</button>
    </div>
    <div id="drawerBody"></div>
  </div>

  <script src="/vendor/chart.umd.min.js"></script>
  <script src="/app.js"></script>
</body>
</html>
```

- [ ] **Step 3: style.css**

`static/style.css`:
```css
* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, Arial, sans-serif; color: #1f2a37; background: #f4f6fb; }
.topbar { display: flex; align-items: center; gap: 16px; background: #1f3a5f; color: #fff; padding: 10px 18px; }
.topbar .title { font-weight: 700; }
.upload-info { font-size: 13px; color: #cdd9ec; margin-left: auto; }
.actions { display: flex; gap: 8px; }
.btn { background: #36527a; color: #fff; border: none; padding: 7px 12px; border-radius: 6px; cursor: pointer; font-size: 13px; }
.btn:hover { background: #436394; }
.kpis { display: flex; gap: 12px; padding: 14px 18px; flex-wrap: wrap; }
.kpi { background: #fff; border-radius: 8px; padding: 12px 16px; min-width: 150px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.kpi .label { font-size: 11px; color: #6b7280; text-transform: uppercase; }
.kpi .value { font-size: 24px; font-weight: 700; }
.filters { display: flex; gap: 10px; padding: 0 18px 12px; flex-wrap: wrap; }
.filters select { padding: 5px 8px; border-radius: 6px; border: 1px solid #cdd6e4; min-width: 120px; }
.tabs { display: flex; gap: 4px; padding: 0 18px; }
.tab { padding: 8px 14px; background: #dde4ef; border-radius: 8px 8px 0 0; cursor: pointer; font-size: 13px; }
.tab.active { background: #fff; font-weight: 700; }
.dim-switch { padding: 8px 18px; font-size: 13px; }
.content { display: flex; gap: 16px; padding: 0 18px 24px; align-items: flex-start; }
.chart-box { flex: 1; background: #fff; border-radius: 8px; padding: 12px; min-height: 320px; }
.table-box { flex: 1; background: #fff; border-radius: 8px; padding: 12px; overflow: auto; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { border: 1px solid #e5e9f0; padding: 5px 8px; text-align: center; }
th:first-child, td:first-child { text-align: left; }
td.cell { cursor: pointer; }
td.cell:hover { background: #e8f0fc; }
.drawer { position: fixed; top: 0; right: 0; width: 460px; height: 100%; background: #fff; box-shadow: -2px 0 12px rgba(0,0,0,.18); padding: 16px; overflow: auto; }
.drawer.hidden { display: none; }
.drawer-head { display: flex; justify-content: space-between; font-weight: 700; margin-bottom: 12px; }
.drawer-head button { border: none; background: none; font-size: 18px; cursor: pointer; }
.req { border-bottom: 1px solid #eee; padding: 8px 0; font-size: 13px; }
.req b { display: block; }
.req .meta { color: #6b7280; font-size: 12px; }
```

- [ ] **Step 4: app.js**

`static/app.js`:
```javascript
const METRICS = [
  { key: "поступило", label: "Поступило", type: "count" },
  { key: "проработано", label: "Проработано", type: "count" },
  { key: "трудоемкость", label: "Ср. трудоёмкость, ч", type: "avg" },
  { key: "длительность", label: "Ср. длительность, р.д.", type: "avg" },
  { key: "на_контроле", label: "Ср. на контроле, р.д.", type: "avg" },
];
const MONTH_NAMES = ["", "янв", "фев", "мар", "апр", "май", "июн",
  "июл", "авг", "сен", "окт", "ноя", "дек"];

let state = { metric: "поступило", dimension: "услуга", filters: {} };
let chart = null;

const qs = (s) => document.querySelector(s);

function filterQuery() {
  const map = { услуга: "services", продукт: "products", масштаб: "scales",
                команда: "teams", инициатор: "initiators" };
  const p = new URLSearchParams();
  for (const [dim, vals] of Object.entries(state.filters)) {
    if (vals && vals.length) p.set(map[dim], vals.join(","));
  }
  return p;
}

async function loadStatus() {
  const r = await fetch("/api/status");
  const { upload } = await r.json();
  qs("#uploadInfo").textContent = upload
    ? `Загружено: ${upload.filename} · строк ${upload.row_count} · ${upload.uploaded_by || ""}`
    : "Данные не загружены";
}

async function loadFilters() {
  const r = await fetch("/api/filters");
  const data = await r.json();
  const box = qs("#filters");
  box.innerHTML = "";
  for (const [dim, values] of Object.entries(data)) {
    const sel = document.createElement("select");
    sel.multiple = false;
    const opt0 = new Option(`Все: ${dim}`, "");
    sel.appendChild(opt0);
    values.forEach((v) => sel.appendChild(new Option(v, v)));
    sel.onchange = () => {
      state.filters[dim] = sel.value ? [sel.value] : [];
      render();
    };
    box.appendChild(sel);
  }
}

function buildTabs() {
  const nav = qs("#tabs");
  nav.innerHTML = "";
  METRICS.forEach((m) => {
    const el = document.createElement("div");
    el.className = "tab" + (m.key === state.metric ? " active" : "");
    el.textContent = m.label;
    el.onclick = () => { state.metric = m.key; render(); };
    nav.appendChild(el);
  });
}

async function loadKpis() {
  const box = qs("#kpis");
  box.innerHTML = "";
  for (const m of METRICS) {
    const r = await fetch(`/api/metrics?metric=${m.key}&dimension=услуга&${filterQuery()}`);
    const data = await r.json();
    let total = 0, n = 0;
    for (const row of data.rows) {
      for (const mon of data.months) {
        const v = data.values[row][mon];
        if (v != null) { total += v; n++; }
      }
    }
    const value = m.type === "count" ? total : (n ? (total / n).toFixed(1) : "—");
    const el = document.createElement("div");
    el.className = "kpi";
    el.innerHTML = `<div class="label">${m.label}</div><div class="value">${value}</div>`;
    box.appendChild(el);
  }
}

async function render() {
  buildTabs();
  const r = await fetch(
    `/api/metrics?metric=${state.metric}&dimension=${state.dimension}&${filterQuery()}`);
  const data = await r.json();
  renderTable(data);
  renderChart(data);
}

function renderTable(data) {
  const box = qs("#tableBox");
  const months = data.months;
  let html = "<table><tr><th>" + state.dimension + "</th>" +
    months.map((m) => `<th>${MONTH_NAMES[m]}</th>`).join("") + "</tr>";
  for (const row of data.rows) {
    html += `<tr><td>${row}</td>`;
    for (const m of months) {
      const v = data.values[row][m];
      const disp = v == null ? "" : (Number.isInteger(v) ? v : v.toFixed(1));
      html += `<td class="cell" data-row="${row}" data-month="${m}">${disp}</td>`;
    }
    html += "</tr>";
  }
  html += "</table>";
  box.innerHTML = html;
  box.querySelectorAll("td.cell").forEach((td) => {
    td.onclick = () => openDrawer(td.dataset.row, parseInt(td.dataset.month, 10));
  });
}

function renderChart(data) {
  const ctx = qs("#chart");
  const labels = data.months.map((m) => MONTH_NAMES[m]);
  const datasets = data.rows.map((row, i) => ({
    label: row,
    data: data.months.map((m) => data.values[row][m] ?? 0),
    backgroundColor: `hsl(${(i * 57) % 360} 60% 55%)`,
    borderColor: `hsl(${(i * 57) % 360} 60% 45%)`,
  }));
  const type = ["поступило", "проработано"].includes(state.metric) ? "bar" : "line";
  if (chart) chart.destroy();
  chart = new Chart(ctx, { type, data: { labels, datasets },
    options: { responsive: true, plugins: { legend: { position: "bottom" } } } });
}

async function openDrawer(value, month) {
  const r = await fetch(`/api/requests?metric=${state.metric}` +
    `&dimension=${state.dimension}&value=${encodeURIComponent(value)}` +
    `&month=${month}&${filterQuery()}`);
  const items = await r.json();
  qs("#drawerTitle").textContent = `${value} · ${MONTH_NAMES[month]} (${items.length})`;
  qs("#drawerBody").innerHTML = items.map((it) => `
    <div class="req">
      <b>${it.request}</b>
      <div class="meta">${it.org} · ${it.service} · ${it.team} · ${it.status}
        ${it.value != null ? " · " + (Number.isInteger(it.value) ? it.value : it.value.toFixed(1)) : ""}</div>
    </div>`).join("") || "<p>Нет запросов</p>";
  qs("#drawer").classList.remove("hidden");
}

qs("#drawerClose").onclick = () => qs("#drawer").classList.add("hidden");
qs("#dimSelect").onchange = (e) => { state.dimension = e.target.value; render(); };
qs("#exportBtn").onclick = () => {
  window.location = `/api/export?dimension=${state.dimension}&${filterQuery()}`;
};
qs("#fileInput").onchange = async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  fd.append("uploaded_by", prompt("Кто загружает?", "Анна") || "");
  const r = await fetch("/api/upload", { method: "POST", body: fd });
  if (!r.ok) { alert((await r.json()).detail || "Ошибка загрузки"); return; }
  await init();
};

async function init() {
  await loadStatus();
  await loadFilters();
  await loadKpis();
  await render();
}
init();
```

- [ ] **Step 5: Ручная проверка в браузере**

Run:
```bash
.venv/Scripts/python.exe -m uvicorn src.main:app --port 8010 &
sleep 3
```
Открыть http://localhost:8010/, загрузить `tests/fixtures/statistika_source_v14.xlsx`, проверить: KPI заполнились, таблица и график показываются, переключение вкладок/разрезов работает, клик по ячейке открывает список запросов, кнопка Excel скачивает файл. Остановить процесс.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: фронтенд дашборда (KPI, вкладки, график, таблица, drill-down, экспорт)"
```

---

## Task 8: E2E-тест (Playwright)

**Files:**
- Create: `tests/e2e/__init__.py`, `tests/e2e/conftest.py`, `tests/e2e/test_dashboard.py`

- [ ] **Step 1: Установить браузер Playwright**

Run: `.venv/Scripts/python.exe -m playwright install chromium`
Expected: установка chromium.

- [ ] **Step 2: conftest — запуск сервера на временной БД**

`tests/e2e/conftest.py`:
```python
import os
import socket
import subprocess
import sys
import time
import urllib.request
import pytest


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="session")
def server(tmp_path_factory):
    port = _free_port()
    env = dict(os.environ, PRESALE_DB=str(tmp_path_factory.mktemp("db") / "e2e.db"))
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.main:app", "--port", str(port)],
        env=env)
    base = f"http://127.0.0.1:{port}"
    for _ in range(40):
        try:
            urllib.request.urlopen(base + "/api/health", timeout=1)
            break
        except Exception:
            time.sleep(0.25)
    yield base
    proc.terminate()
    proc.wait(timeout=10)
```

- [ ] **Step 3: E2E-тест сценария**

`tests/e2e/test_dashboard.py`:
```python
from pathlib import Path
import pytest

playwright = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

FIXTURE = str(Path("tests/fixtures/statistika_source_v14.xlsx").resolve())
SCREENSHOTS = Path("tmp/screenshots")


def test_upload_filter_drilldown_export(server):
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(server + "/")
        # авто-prompt для uploaded_by
        page.on("dialog", lambda d: d.accept("Анна"))
        page.set_input_files("#fileInput", FIXTURE)
        page.wait_for_selector("td.cell")
        # KPI заполнены
        assert page.locator(".kpi").count() == 5
        page.screenshot(path=str(SCREENSHOTS / "dashboard.png"))
        # drill-down по первой непустой ячейке
        page.locator("td.cell", has_text="5").first.click()
        page.wait_for_selector("#drawer:not(.hidden)")
        assert page.locator(".req").count() >= 1
        page.screenshot(path=str(SCREENSHOTS / "drilldown.png"))
        browser.close()
```

- [ ] **Step 4: Запустить E2E**

Run: `.venv/Scripts/python.exe -m pytest tests/e2e/ -v`
Expected: PASS. Скриншоты в `tmp/screenshots/`.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "test: E2E Playwright — загрузка, drill-down, скриншоты"
```

---

## Task 9: Покрытие, README, финал

**Files:**
- Create: `README.md`, `launch.bat`

- [ ] **Step 1: Прогнать всё с покрытием**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/ --cov=src --cov-report=term-missing`
Expected: PASS, покрытие ≥70%. Если ниже — добавить тесты на непокрытые ветки.

- [ ] **Step 2: README.md**

`README.md`:
```markdown
# Дашборд пресейла ОГВ

Загрузка большого файла «Статистика по выполненным работам» → дашборд показателей
(Поступило, Проработано, Ср. трудоёмкость, Ср. длительность, Ср. на контроле)
с фильтрами, drill-down до запросов и выгрузкой привычного Excel.

## Запуск

```powershell
.\launch.bat
```
Открыть http://localhost:8010/

## Тесты

```powershell
.venv\Scripts\python.exe -m pytest tests/unit/ -v --cov=src
.venv\Scripts\python.exe -m pytest tests/e2e/ -v
```

## Как работает

1. Анна раз в месяц загружает кумулятивный xlsx (январь–текущий, все статусы).
2. Бэкенд парсит лист «Исх данные», кладёт в SQLite (`data/presale.db`).
3. Показатели считаются на лету с учётом фильтров; месяц берётся из колонки
   «Месяц начала текущего статуса», запросы дедуплицируются по ИД.
4. Дашборд и экспорт читают последний загруженный датасет (общий для всех).

Правила расчёта: см. `docs/superpowers/specs/2026-06-05-presale-dashboard-design.md`.
```

- [ ] **Step 3: launch.bat**

`launch.bat`:
```bat
@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe -m uvicorn src.main:app --host 0.0.0.0 --port 8010 --reload
```

- [ ] **Step 4: Финальный прогон и commit**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: все тесты зелёные.

```bash
git add -A
git commit -m "docs: README, launch.bat; финальная сборка"
```

---

## Самопроверка плана

- **Покрытие спеки:** парсинг (Task 1) ✓, модель данных (Task 1) ✓, 5 показателей + дедуп + разрезы (Task 2) ✓, golden-валидация (Task 3) ✓, SQLite/история (Task 4) ✓, экспорт 5 листов (Task 5) ✓, API upload/metrics/filters/requests/export (Task 6) ✓, дашборд вариант A с KPI/вкладками/графиком/таблицей/drill-down (Task 7) ✓, E2E (Task 8) ✓, покрытие ≥70% (Task 9) ✓.
- **Имена согласованы:** `compute_cells`, `build_matrix`, `drilldown`, `filter_events`, `build_export`, `replace_events`, `load_events`, `last_upload`, `distinct_values`, `parse_workbook` — используются одинаково в реализации и тестах.
- **Без плейсхолдеров:** весь код приведён целиком.
```
