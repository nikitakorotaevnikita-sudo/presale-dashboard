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
