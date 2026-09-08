from openai import OpenAI


class LLMError(Exception):
    pass


def _make_client(config):
    return OpenAI(base_url=config["base_url"],
                  api_key=config.get("token") or "not-needed",
                  timeout=float(config.get("timeout", 120)))


def stream_chat(config, messages, temperature=0.2, timeout=120):
    try:
        client = _make_client({**config, "timeout": timeout})
        stream = client.chat.completions.create(
            model=config["model"], messages=messages,
            temperature=temperature, stream=True)
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
    except Exception as exc:  # нормализуем любую ошибку SDK/сети
        raise LLMError(str(exc)) from exc


def test_connection(config):
    try:
        client = _make_client({**config, "timeout": 30})
        client.chat.completions.create(
            model=config["model"],
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1)
        return True, "Связь с моделью установлена"
    except Exception as exc:
        return False, f"Ошибка подключения: {exc}"
