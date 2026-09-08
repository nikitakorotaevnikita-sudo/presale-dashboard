import sqlite3
from src import settings_store


def _conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    return c


def test_ensure_seeds_default():
    c = _conn()
    settings_store.ensure(c)
    cfg = settings_store.get_llm_config(c)
    assert cfg["base_url"] == "https://llm.ario.directum360.ru/v1"
    assert cfg["model"]  # непустое имя модели
    assert cfg["provider"] == "local"


def test_mask_token():
    assert settings_store.mask_token("100111ac-d413-4721-9357-5d04aaf7386d").endswith("386d")
    assert settings_store.mask_token("100111ac-d413-4721-9357-5d04aaf7386d").startswith("•")
    assert settings_store.mask_token("") == ""


def test_masked_config_hides_token():
    c = _conn()
    settings_store.ensure(c)
    settings_store.save_llm_config(c, "local", "http://x/v1", "m", "secrettoken123")
    assert settings_store.masked_config(c)["token"].endswith("n123")
    assert "secret" not in settings_store.masked_config(c)["token"]
    assert settings_store.get_llm_config(c)["token"] == "secrettoken123"


def test_empty_token_preserves_previous():
    c = _conn()
    settings_store.ensure(c)
    settings_store.save_llm_config(c, "local", "http://x/v1", "m", "keepme")
    settings_store.save_llm_config(c, "local", "http://y/v1", "m2", "")
    cfg = settings_store.get_llm_config(c)
    assert cfg["token"] == "keepme"       # токен сохранён
    assert cfg["base_url"] == "http://y/v1"  # прочее обновлено
