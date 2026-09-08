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
