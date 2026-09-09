import json
import re

from src import agent_sandbox, llm_service

MAX_ATTEMPTS = 3

CODEGEN_PROMPT = (
    "Ты пишешь Python (pandas) для анализа процесса пресейла ОГВ.\n"
    "Дан DataFrame `df` (pandas), уже без декабря. Колонки:\n"
    "request_id (ИД запроса), request (название), org, product, scale, service (услуга), "
    "initiator, team (команда), business_unit, status (статус), prev_status, "
    "date_start, date_end, month (1-12), duration_rd (длительность статуса, раб.дн), "
    "work_duration_rd (длительность проработки запроса, раб.дн), hours (отработано часов), note, link.\n"
    "ПРАВИЛА РАСЧЁТА: считай запросы уникально по request_id; «поступило» = строки со "
    "status=='Инициализация'; «проработано» и средние — по status=='Принято'; "
    "длительность проработки берётся из work_duration_rd.\n"
    "ТРЕБОВАНИЯ К КОДУ:\n"
    "- только чтение df; без сети, файлов и импортов кроме pandas/numpy/math/statistics/json/datetime/collections;\n"
    "- присвой переменную result (число, словарь или список — JSON-сериализуемо) и "
    "explanation (краткий текст-вывод по-русски);\n"
    "- верни ТОЛЬКО блок кода ```python ...```, без пояснений вне блока."
)


def extract_code(text):
    m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip()


def build_messages(events, history):
    messages = [{"role": "system", "content": CODEGEN_PROMPT}]
    messages.extend(history or [])
    return messages


def _format_result(res):
    if isinstance(res, (dict, list)):
        return "```json\n" + json.dumps(res, ensure_ascii=False, indent=2) + "\n```"
    return str(res)


def stream_agent(config, events, history, upload=None):
    messages = build_messages(events, history)
    for attempt in range(MAX_ATTEMPTS):
        code_text = "".join(llm_service.stream_chat(config, messages))
        code = extract_code(code_text)
        r = agent_sandbox.run_code(code, events)
        if r["ok"]:
            yield f"```python\n{code}\n```\n\n"
            if r["explanation"]:
                yield r["explanation"] + "\n\n"
            yield "**Результат:** " + _format_result(r["result"])
            return
        messages.append({"role": "assistant", "content": code_text})
        messages.append({"role": "user",
                         "content": "Код упал с ошибкой:\n" + (r["error"] or "") +
                                    "\nИсправь и верни только исправленный блок кода."})
    yield ("Не удалось выполнить анализ кодом после нескольких попыток. "
           "Попробуйте обычный чат (выключите «Глубокий анализ»).")
