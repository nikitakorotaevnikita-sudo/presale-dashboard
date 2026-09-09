from src import analytics_brief, llm_service

SYSTEM_PROMPT = (
    "Ты — аналитик процесса пресейла ОГВ. Помогаешь руководителю находить узкие "
    "места, оценивать сложности из-за исполнителей и команд.\n"
    "ПРАВИЛА:\n"
    "1. Используй ТОЛЬКО числа из блока ДАННЫЕ. Не пересчитывай и не выдумывай цифры.\n"
    "2. В выводах цитируй конкретные числа (команда/услуга/месяц/значение).\n"
    "3. Если данных для ответа нет — прямо скажи «В данных этого нет».\n"
    "4. Рекомендации опирай на конкретные индикаторы из ДАННЫХ.\n"
    "5. Отвечай по-русски, кратко и по делу."
)

ANALYZE_PROMPT = (
    "Проведи анализ узких мест процесса пресейла по блоку ДАННЫЕ. "
    "Определи 3–5 проблемных зон. Для каждой укажи: (а) в чём проблема, "
    "(б) числа-обоснование из ДАННЫХ, (в) конкретную рекомендацию. "
    "Отсортируй по критичности."
)

SUGGESTIONS = [
    "Какая команда дольше всех держит запросы?",
    "Где копится backlog?",
    "У каких услуг самая высокая трудоёмкость?",
    "Какие команды дольше держат запросы «на контроле»?",
]


def build_messages(events, history, upload=None):
    brief = analytics_brief.build_brief(events, upload)
    # правила и блок ДАННЫЕ — одним system-сообщением: провайдер (Qwen/vLLM)
    # допускает только одно system-сообщение в начале диалога.
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + "\n\n" + brief},
    ]
    messages.extend(history or [])
    return messages


def stream_answer(config, events, history, upload=None):
    yield from llm_service.stream_chat(config, build_messages(events, history, upload))


def stream_analysis(config, events, upload=None):
    history = [{"role": "user", "content": ANALYZE_PROMPT}]
    yield from llm_service.stream_chat(config, build_messages(events, history, upload))
