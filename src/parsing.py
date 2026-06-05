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
