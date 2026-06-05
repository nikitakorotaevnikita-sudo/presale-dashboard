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
