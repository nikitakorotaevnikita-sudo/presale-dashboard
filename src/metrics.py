import math
from collections import defaultdict
from statistics import mean

from src.models import DIMENSION_ATTR

STATUS_INIT = "Инициализация"
STATUS_ACCEPTED = "Принято"
STATUS_IN_WORK = "В работе"
STATUS_ON_CONTROL = "На контроле"

METRICS = ["поступило", "проработано", "трудоемкость", "длительность", "на_контроле"]

# Месяцы, исключаемые из расчётов и визуализации. Декабрь — записи прошлого
# года (номер месяца в модели не различает год), в дашборде их не учитываем.
# Сами строки остаются в БД, исключение применяется только при агрегации.
EXCLUDED_MONTHS = frozenset({12})


def drop_excluded_months(events):
    return [e for e in events if e.month not in EXCLUDED_MONTHS]


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


def _round_metric(metric, value):
    """Округление значения показателя.

    «Ср. длительность» — всегда вверх до целого рабочего дня (math.ceil);
    остальные средние — до 1 знака; счётчики — как есть.
    """
    if value is None:
        return None
    if metric == "длительность":
        return math.ceil(value)
    if metric in ("трудоемкость", "на_контроле"):
        return round(value, 1)
    return value


def _count_total(events, status):
    """Итог по месяцам для счётного показателя: уникальные запросы за месяц."""
    buckets = defaultdict(set)
    for e in events:
        if e.status == status and e.month:
            buckets[e.month].add(e.request_id)
    return {m: len(s) for m, s in buckets.items()}


def _avg_total(events, metric):
    """Итог по месяцам для усредняющего показателя: среднее ПО ВСЕМ запросам
    месяца (а не среднее из средних по разрезам)."""
    work = defaultdict(float)
    control = defaultdict(float)
    hours = {}
    for e in events:
        work[e.request_id] += e.work_duration_rd
        if e.status == STATUS_ON_CONTROL:
            control[e.request_id] += e.duration_rd
        if e.status == STATUS_ACCEPTED and e.hours is not None:
            hours[e.request_id] = e.hours
    buckets = defaultdict(dict)
    for e in events:
        if e.status == STATUS_ACCEPTED and e.month:
            if metric == "трудоемкость":
                if e.request_id in hours:
                    buckets[e.month][e.request_id] = hours[e.request_id]
            elif metric == "длительность":
                buckets[e.month][e.request_id] = work[e.request_id]
            elif metric == "на_контроле":
                buckets[e.month][e.request_id] = control.get(e.request_id, 0.0)
    return {m: mean(d.values()) for m, d in buckets.items() if d}


def month_totals(events, metric):
    """Корректный итог по каждому месяцу (для строки ВСЕГО), не зависящий от разреза."""
    if metric == "поступило":
        return _count_total(events, STATUS_INIT)
    if metric == "проработано":
        return _count_total(events, STATUS_ACCEPTED)
    if metric in ("трудоемкость", "длительность", "на_контроле"):
        return _avg_total(events, metric)
    raise ValueError(f"Неизвестный показатель: {metric}")


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
    month_list = list(months)
    rows = sorted({k[0] for k in cells})
    values = {rv: {m: _round_metric(metric, cells.get((rv, m))) for m in month_list}
              for rv in rows}
    totals_raw = month_totals(events, metric)
    totals = {m: _round_metric(metric, totals_raw.get(m)) for m in month_list}
    return {"metric": metric, "dimension": dim, "rows": rows,
            "months": month_list, "values": values, "totals": totals}


def summary(events):
    """Корректные итоги/средние по всем отфильтрованным событиям (для KPI)."""
    init = {e.request_id for e in events if e.status == STATUS_INIT}
    accepted = {e.request_id for e in events if e.status == STATUS_ACCEPTED}
    hours = {}
    work = defaultdict(float)
    control = defaultdict(float)
    for e in events:
        work[e.request_id] += e.work_duration_rd
        if e.status == STATUS_ON_CONTROL:
            control[e.request_id] += e.duration_rd
        if e.status == STATUS_ACCEPTED and e.hours is not None:
            hours[e.request_id] = e.hours
    acc_work = [work[r] for r in accepted]
    acc_control = [control[r] for r in accepted]
    return {
        "поступило": len(init),
        "проработано": len(accepted),
        "трудоемкость": _round_metric("трудоемкость", mean(hours.values())) if hours else None,
        "длительность": _round_metric("длительность", mean(acc_work)) if acc_work else None,
        "на_контроле": _round_metric("на_контроле", mean(acc_control)) if acc_control else None,
    }


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
                "date_start": e.date_start, "link": e.link}
        item["value"] = 1  # по умолчанию: каждый запрос считается за 1 (поступило/проработано)
        if metric == "трудоемкость":
            item["value"] = e.hours
        elif metric == "длительность":
            item["value"] = work_sums[rid]
        elif metric == "на_контроле":
            item["value"] = control_sums.get(rid, 0.0)
        out.append(item)
    return sorted(out, key=lambda x: x["request"])
