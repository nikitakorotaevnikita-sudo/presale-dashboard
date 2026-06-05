import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("PRESALE_DB", BASE_DIR / "data" / "presale.db"))
STATIC_DIR = BASE_DIR / "static"
SHEET_NAME = "Исх данные"
