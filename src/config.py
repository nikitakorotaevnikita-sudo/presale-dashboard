from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "presale.db"
STATIC_DIR = BASE_DIR / "static"
SHEET_NAME = "Исх данные"
