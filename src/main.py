import tempfile
import zipfile
from contextlib import closing
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from openpyxl.utils.exceptions import InvalidFileException

from src import config, storage, metrics, export
from src.parsing import parse_workbook, ParseError

app = FastAPI(title="Дашборд пресейла ОГВ")


def _conn():
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = storage.connect(config.DB_PATH)
    storage.init_db(conn)
    return conn


def _fix_form_encoding(value: str) -> str:
    """Чинит кириллицу из не-UTF-8 полей multipart-формы.

    Starlette при ошибке UTF-8-декода текстового поля формы молча откатывается
    на latin-1. Windows-клиенты (curl/PowerShell) шлют кириллицу в cp1251 —
    получается мозаика («Тест» -> «Òåñò»). Корректно декодированная UTF-8
    кириллица содержит кодпоинты > U+00FF, поэтому .encode("latin-1") для неё
    падает — такие строки оставляем как есть. Чиним только артефакты
    latin-1-фоллбэка (все символы ≤ U+00FF), пере-декодируя их как cp1251.
    """
    try:
        raw = value.encode("latin-1")
    except UnicodeEncodeError:
        return value  # уже корректная UTF-8 строка (символы вне latin-1)
    try:
        return raw.decode("cp1251")
    except UnicodeDecodeError:
        return value


def _events_filtered(conn, q):
    events = storage.load_events(conn)
    return metrics.filter_events(
        events,
        services=q.get("services"), products=q.get("products"),
        scales=q.get("scales"), teams=q.get("teams"),
        initiators=q.get("initiators"))


def _filters_from_query(services, products, scales, teams, initiators):
    # фильтры приходят повторяющимися query-параметрами (list[str]),
    # поэтому значения с запятыми («Встречи (демо, консультации)») не рвутся
    return {"services": services or None, "products": products or None,
            "scales": scales or None, "teams": teams or None,
            "initiators": initiators or None}


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...), uploaded_by: str = Form("")):
    suffix = Path(file.filename or "f.xlsx").suffix or ".xlsx"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        events = parse_workbook(tmp_path)
    except (ParseError, InvalidFileException, zipfile.BadZipFile) as exc:
        raise HTTPException(status_code=400, detail=f"Не удалось прочитать файл: {exc}")
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)
    uploaded_by = _fix_form_encoding(uploaded_by)
    filename = _fix_form_encoding(file.filename or "")
    with closing(_conn()) as conn:
        storage.replace_events(conn, events, filename, uploaded_by)
        return {"row_count": len(events), "upload": storage.last_upload(conn)}


@app.get("/api/status")
def status():
    with closing(_conn()) as conn:
        return {"upload": storage.last_upload(conn)}


@app.get("/api/filters")
def filters():
    with closing(_conn()) as conn:
        return storage.distinct_values(conn)


@app.get("/api/metrics")
def get_metrics(metric: str, dimension: str,
                services: list[str] = Query(default=[]),
                products: list[str] = Query(default=[]),
                scales: list[str] = Query(default=[]),
                teams: list[str] = Query(default=[]),
                initiators: list[str] = Query(default=[])):
    if metric not in metrics.METRICS:
        raise HTTPException(400, f"Неизвестный показатель: {metric}")
    with closing(_conn()) as conn:
        events = _events_filtered(conn, _filters_from_query(
            services, products, scales, teams, initiators))
    return metrics.build_matrix(events, metric, dimension)


@app.get("/api/requests")
def get_requests(metric: str, dimension: str, value: str, month: int,
                 services: list[str] = Query(default=[]),
                 products: list[str] = Query(default=[]),
                 scales: list[str] = Query(default=[]),
                 teams: list[str] = Query(default=[]),
                 initiators: list[str] = Query(default=[])):
    with closing(_conn()) as conn:
        events = _events_filtered(conn, _filters_from_query(
            services, products, scales, teams, initiators))
    return metrics.drilldown(events, metric, dimension, value, month)


@app.get("/api/summary")
def get_summary(services: list[str] = Query(default=[]),
                products: list[str] = Query(default=[]),
                scales: list[str] = Query(default=[]),
                teams: list[str] = Query(default=[]),
                initiators: list[str] = Query(default=[])):
    with closing(_conn()) as conn:
        events = _events_filtered(conn, _filters_from_query(
            services, products, scales, teams, initiators))
    return metrics.summary(events)


@app.get("/api/export")
def get_export(dimension: str = "услуга", months: str = "",
               services: list[str] = Query(default=[]),
               products: list[str] = Query(default=[]),
               scales: list[str] = Query(default=[]),
               teams: list[str] = Query(default=[]),
               initiators: list[str] = Query(default=[])):
    month_list = sorted([int(x) for x in months.split(",") if x.strip()]) if months else list(range(1, 13))
    with closing(_conn()) as conn:
        events = _events_filtered(conn, _filters_from_query(
            services, products, scales, teams, initiators))
    data = export.build_export(events, dimension=dimension, months=month_list)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="presale_metrics.xlsx"'})


# статика монтируется последней, чтобы не перехватывать /api/*
if config.STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(config.STATIC_DIR), html=True), name="static")
