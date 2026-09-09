import os

_KEYS = ("provider", "base_url", "model", "token")
_DEFAULTS = {
    "provider": "local",
    "base_url": "https://llm.ario.directum360.ru/v1",
    "model": "Qwen/Qwen3.8-27B",  # точное имя модели у провайдера (подтверждено через {base_url}/models)
    "token": os.environ.get("LLM_TOKEN", ""),
}


def ensure(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT)")
    existing = {r[0] for r in conn.execute("SELECT key FROM app_settings")}
    for k in _KEYS:
        if f"llm.{k}" not in existing:
            conn.execute("INSERT INTO app_settings (key, value) VALUES (?, ?)",
                         (f"llm.{k}", _DEFAULTS[k]))
    conn.commit()


def get_llm_config(conn):
    rows = dict(conn.execute(
        "SELECT key, value FROM app_settings WHERE key LIKE 'llm.%'").fetchall())
    return {k: rows.get(f"llm.{k}", _DEFAULTS[k]) for k in _KEYS}


def save_llm_config(conn, provider, base_url, model, token):
    updates = {"provider": provider, "base_url": base_url, "model": model}
    if token:  # пустой токен не затирает прежний
        updates["token"] = token
    for k, v in updates.items():
        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (f"llm.{k}", v))
    conn.commit()


def mask_token(token):
    if not token:
        return ""
    tail = token[-4:]
    return "•" * max(4, len(token) - 4) + tail


def masked_config(conn):
    cfg = get_llm_config(conn)
    return {**cfg, "token": mask_token(cfg["token"])}
