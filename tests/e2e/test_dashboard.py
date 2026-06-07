"""E2E Playwright тесты дашборда пресейла ОГВ.

Каждый прогон запускает приложение на свободном порту против ВРЕМЕННОЙ
базы данных (PRESALE_DB -> temp), поэтому реальные данные не затрагиваются.
"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import expect, sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "statistika_source_v14.xlsx"
SHOTS = REPO_ROOT / "tmp" / "screenshots"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def base_url(tmp_path_factory):
    """Поднимает uvicorn в подпроцессе против временной БД, отдаёт base URL."""
    SHOTS.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path_factory.mktemp("db") / "e2e.db"
    port = _free_port()

    env = dict(os.environ)
    env["PRESALE_DB"] = str(db_path)
    env["PYTHONIOENCODING"] = "utf-8"

    # ВАЖНО: лог uvicorn пишем в ФАЙЛ, а не в subprocess.PIPE. Несчитываемый
    # PIPE переполняется после нескольких сотен строк access-лога за прогон,
    # uvicorn блокируется на записи в stdout и перестаёт обслуживать запросы —
    # отсюда зависание загрузки страницы в N-м тесте. Файл этого лишён.
    log_path = db_path.parent / "uvicorn.log"
    log_file = open(log_path, "w", encoding="utf-8")

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.main:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(REPO_ROOT), env=env,
        stdout=log_file, stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            if proc.poll() is not None:
                log_file.flush()
                out = log_path.read_text(encoding="utf-8", errors="replace")
                raise RuntimeError(f"uvicorn упал на старте:\n{out}")
            try:
                r = httpx.get(f"{url}/api/health", timeout=1.0)
                if r.status_code == 200:
                    break
            except Exception:
                time.sleep(0.25)
        else:
            raise RuntimeError("uvicorn не поднялся за 30с")
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log_file.close()


@pytest.fixture()
def page():
    """Свежий браузер на каждый тест.

    Один общий браузер на всю сессию приводил к зависанию загрузки страницы
    в 4-м по счёту контексте (накопление состояния браузер/keep-alive против
    одно-воркерного uvicorn). Отдельный браузер на тест устраняет гонку и
    стоит ~1с на запуск — пренебрежимо на фоне разовой загрузки фикстуры.
    """
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(accept_downloads=True)
        pg = ctx.new_page()
        try:
            yield pg
        finally:
            ctx.close()
            b.close()


def _open_dashboard(page, base_url):
    """Открыть страницу и дождаться завершения init() (KPI отрисованы).

    Используем domcontentloaded + явные expect-ожидания вместо networkidle:
    networkidle капризен (Chart.js / keep-alive соединения держат сеть
    «занятой»), а готовность приложения надёжно определяется появлением
    KPI-карточек.
    """
    page.goto(base_url, wait_until="domcontentloaded")
    cards = page.locator("#kpi .kpi__card")
    try:
        expect(cards.first).to_be_visible(timeout=20000)
    except AssertionError:
        # init() делает несколько последовательных fetch (status/filters/
        # summary); под одним воркером uvicorn один из них изредка
        # подвисает и KPI не отрисовываются. Один reload это лечит;
        # если KPI реально сломаны — упадёт и после перезагрузки.
        page.reload(wait_until="domcontentloaded")
        expect(cards.first).to_be_visible(timeout=20000)
    expect(page.locator("#status-line")).not_to_have_text("Загрузка…", timeout=20000)


@pytest.fixture(scope="session")
def uploaded(base_url):
    """Однократно загружает фикстуру в общую временную БД.

    Фикстура statistika_source_v14.xlsx весит ~72 МБ и парсится openpyxl
    около 100 секунд, поэтому грузим её один раз на всю сессию, а отдельные
    тесты просто переоткрывают уже наполненный дашборд.

    Загружаем штатным UX-путём: клик по «⬆ Загрузить файл» открывает file
    chooser, который перехватывает Playwright (надёжнее set_input_files по
    скрытому input — тот теряет files при синхронном e.target.value = "").
    """
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(accept_downloads=True)
        pg = ctx.new_page()
        try:
            _open_dashboard(pg, base_url)
            with pg.expect_response(
                    lambda r: "/api/upload" in r.url and r.request.method == "POST",
                    timeout=180000) as resp_info:
                with pg.expect_file_chooser() as fc_info:
                    pg.locator("#upload-btn").click()
                fc_info.value.set_files(str(FIXTURE))
            assert resp_info.value.status == 200, f"upload вернул {resp_info.value.status}"
            # статус-строка показывает имя файла / число строк после загрузки
            expect(pg.locator("#status-line")).to_contain_text("строк", timeout=30000)
        finally:
            ctx.close()
            b.close()
    yield base_url


def test_upload_and_kpi(page, base_url, uploaded):
    _open_dashboard(page, base_url)

    # ожидаемое значение «Поступило» берём из API после загрузки,
    # чтобы не зашивать число жёстко (фикстура -> 44)
    expected = httpx.get(f"{base_url}/api/summary", timeout=10).json()["поступило"]
    assert expected == 44, f"ожидали 44 из фикстуры, получили {expected}"

    # KPI-карточка «Поступило» — первая в KPI_CARDS
    first_card = page.locator("#kpi .kpi__card").first
    expect(first_card.locator(".kpi__label")).to_have_text("Поступило")
    expect(first_card.locator(".kpi__value")).to_have_text(str(expected))

    page.screenshot(path=str(SHOTS / "01-loaded.png"), full_page=True)


def test_table_and_tabs(page, base_url, uploaded):
    _open_dashboard(page, base_url)

    # вкладка «Поступило» активна по умолчанию, разрез «Услуга» по умолчанию
    matrix = page.locator("#matrix")
    expect(matrix.locator("td", has_text="Оценка внедрения")).to_be_visible(timeout=10000)

    # переключаем разрез на «Продукт»
    page.locator(".seg .seg__btn", has_text="Продукт").click()
    expect(matrix.locator("td", has_text="RX")).to_be_visible(timeout=10000)

    # переключаем показатель на «Ср. трудоёмкость» — заголовок графика обновляется,
    # таблица перерисовывается (формат avg -> значения с десятичной частью)
    page.locator(".tabs .tab", has_text="Ср. трудоёмкость").click()
    expect(page.locator(".tabs .tab--active")).to_have_text("Ср. трудоёмкость")
    # таблица всё ещё содержит строки разреза «Продукт»
    expect(matrix.locator("td", has_text="RX")).to_be_visible(timeout=10000)

    page.screenshot(path=str(SHOTS / "02-table.png"), full_page=True)


def test_drilldown(page, base_url, uploaded):
    _open_dashboard(page, base_url)

    matrix = page.locator("#matrix")
    expect(matrix.locator("td", has_text="Оценка внедрения")).to_be_visible(timeout=10000)

    # кликаем непустую ячейку: строка «Оценка внедрения», месяц 1 (data-month="1")
    cell = matrix.locator(
        'td.cell--clickable[data-row="Оценка внедрения"][data-month="1"]')
    expect(cell).to_be_visible()
    cell.click()

    overlay = page.locator("#drill-overlay")
    expect(overlay).to_be_visible()
    expect(page.locator("#drill-title")).to_contain_text("Оценка внедрения")
    # в панели появляются строки запросов (есть хотя бы один <tr> в tbody с данными)
    expect(page.locator("#drill-table tbody tr").first).to_be_visible(timeout=10000)
    rows = page.locator("#drill-table tbody tr")
    assert rows.count() >= 1
    # не «Запросы не найдены» / «Ошибка»
    first_cell_text = page.locator("#drill-table tbody tr").first.locator("td").first.inner_text()
    assert "не найдены" not in first_cell_text.lower()
    assert "ошибка" not in first_cell_text.lower()

    page.screenshot(path=str(SHOTS / "03-drilldown.png"), full_page=True)


def test_export_download(page, base_url, uploaded):
    _open_dashboard(page, base_url)

    with page.expect_download() as dl_info:
        page.locator("#export-btn").click()
    download = dl_info.value

    suggested = download.suggested_filename
    assert suggested.endswith(".xlsx"), suggested

    dest = SHOTS / "export.xlsx"
    download.save_as(str(dest))
    assert dest.exists() and dest.stat().st_size > 0
