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
