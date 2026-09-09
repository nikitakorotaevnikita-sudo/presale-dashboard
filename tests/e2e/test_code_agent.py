"""E2E Playwright тест режима «Глубокий анализ (код)» ИИ-чата (LLM замокан через LLM_FAKE).

Переиспользует паттерн tests/e2e/test_ai_chat.py: сервер uvicorn на
свободном порту против временной БД (PRESALE_DB), лог в файл (не PIPE —
иначе переполнение и зависание), ожидание /api/health перед загрузкой
фикстуры. Реальный LLM не вызывается: LLM_FAKE=1 переключает /api/agent
на детерминированный фиктивный ответ.
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


@pytest.fixture(scope="module")
def base_url(tmp_path_factory):
    """Поднимает uvicorn в подпроцессе против временной БД с LLM_FAKE=1."""
    SHOTS.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path_factory.mktemp("db") / "e2e.db"
    port = _free_port()

    env = dict(os.environ)
    env["PRESALE_DB"] = str(db_path)
    env["PYTHONIOENCODING"] = "utf-8"
    env["LLM_FAKE"] = "1"

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

        # загрузить фикстуру (парсинг ~1.5 мин на этой машине)
        with open(FIXTURE, "rb") as f:
            resp = httpx.post(
                f"{url}/api/upload",
                files={"file": f},
                data={"uploaded_by": "e2e"},
                timeout=180,
            )
        assert resp.status_code == 200, f"upload вернул {resp.status_code}: {resp.text}"

        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log_file.close()


def test_agent_mode_flow(base_url):
    SHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context()
        pg = ctx.new_page()
        try:
            pg.goto(base_url, wait_until="domcontentloaded")

            pg.click("button[data-view='ai']")
            expect(pg.locator("#chat-suggestions .suggestion").first).to_be_visible(timeout=20000)

            pg.check("#agent-mode")
            pg.fill("#chat-input", "Посчитай число строк")
            pg.click("#chat-form button[type='submit']")

            bubble = pg.locator(".bubble--assistant").last
            expect(bubble).to_be_visible(timeout=30000)
            assert bubble.inner_text().strip(), "ответ ассистента пуст"

            pg.screenshot(path=str(SHOTS / "code-agent.png"))
        finally:
            ctx.close()
            b.close()
