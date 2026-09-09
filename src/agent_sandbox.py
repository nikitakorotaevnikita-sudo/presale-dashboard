import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

# ВАЖНО (остаточный риск): ограничение через exec() с урезанным __builtins__ —
# это НЕ полноценная граница безопасности (классический obj.__class__.__bases__...
# ...__subclasses__() gadget-chain теоретически достаёт до модулей, доступных
# в процессе интерпретатора). Ниже — статический денай-лист опасных токенов
# как дешёвая дополнительная защита, плюс запуск в отдельном subprocess без
# секретов в окружении. Доступ к файловой системе из пользовательского кода
# дополнительно заблокирован на уровне раннера: builtins.open, io.open и
# pandas.io.common.get_handle подменены на функцию, бросающую OSError, —
# это перекрывает df.to_csv/pd.read_csv/np.save и т.п., которые иначе
# используют собственный open pandas/numpy в обход урезанного namespace.
# Для внутреннего доверенного инструмента этого достаточно; полная изоляция
# (Docker/gVisor и т.п.) — future hardening.
_FORBIDDEN = (
    "__subclasses__", "__bases__", "__mro__", "__globals__", "__builtins__",
    "__class__", "__import__", "__loader__", "__spec__",
    "importlib", "subprocess", "ctypes",
)

# Скрипт-обёртка (доверенный): грузит данные, строит df, урезает окружение и
# исполняет пользовательский код из user_code.py с белым списком импортов.
_RUNNER = r'''
import json, sys, builtins, traceback

with open("data.json", encoding="utf-8") as f:
    _rows = json.load(f)
import pandas as pd
_df = pd.DataFrame(_rows)

_ALLOWED = {"pandas", "numpy", "math", "statistics", "json", "datetime", "collections"}
_real_import = builtins.__import__
def _safe_import(name, *a, **k):
    if name.split(".")[0] not in _ALLOWED:
        raise ImportError("Импорт запрещён в песочнице: " + name)
    return _real_import(name, *a, **k)

try:
    import socket
    def _no_net(*a, **k):
        raise OSError("Сеть недоступна в песочнице")
    socket.socket.connect = _no_net
except Exception:
    pass
try:
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
except Exception:
    pass

_names = ("abs", "min", "max", "sum", "len", "range", "round", "sorted",
          "enumerate", "zip", "map", "filter", "list", "dict", "set", "tuple",
          "str", "int", "float", "bool", "print", "any", "all", "reversed",
          "isinstance", "repr")
_sb = {n: getattr(builtins, n) for n in _names if hasattr(builtins, n)}
_sb["__import__"] = _safe_import
_sb["True"], _sb["False"], _sb["None"] = True, False, None

with open("user_code.py", encoding="utf-8") as f:
    _code = f.read()

import io as _io
def _no_fs(*_a, **_k):
    raise OSError("Доступ к файловой системе запрещён в песочнице")
builtins.open = _no_fs
_io.open = _no_fs
try:
    import pandas.io.common as _pcommon
    _pcommon.get_handle = _no_fs
except Exception:
    pass

_ns = {"__builtins__": _sb, "df": _df.copy(), "pd": pd, "result": None, "explanation": ""}
try:
    exec(_code, _ns)
except Exception:
    sys.stderr.write(traceback.format_exc())
    sys.exit(1)

sys.stdout.write("\n" + json.dumps(
    {"result": _ns.get("result"), "explanation": str(_ns.get("explanation") or "")},
    ensure_ascii=False, default=str))
'''


def run_code(code, events, timeout=15):
    for token in _FORBIDDEN:
        if token in code:
            return {"ok": False, "result": None, "explanation": "",
                    "error": "Обнаружена запрещённая конструкция: " + token}
    rows = [asdict(e) for e in events]
    child_env = {k: v for k, v in os.environ.items()
                 if k not in ("LLM_TOKEN", "PRESALE_DB")}
    child_env["PYTHONIOENCODING"] = "utf-8"
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d)
        (dp / "data.json").write_text(
            json.dumps(rows, ensure_ascii=False, default=str), encoding="utf-8")
        (dp / "user_code.py").write_text(code, encoding="utf-8")
        (dp / "runner.py").write_text(_RUNNER, encoding="utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, "runner.py"], cwd=d, env=child_env,
                capture_output=True, text=True, encoding="utf-8", timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"ok": False, "result": None, "explanation": "",
                    "error": "Превышен лимит времени выполнения"}
        if proc.returncode != 0:
            return {"ok": False, "result": None, "explanation": "",
                    "error": (proc.stderr or "неизвестная ошибка")[-2000:]}
        try:
            out = json.loads((proc.stdout or "").strip().splitlines()[-1])
        except Exception:
            return {"ok": False, "result": None, "explanation": "",
                    "error": "Некорректный вывод песочницы: " + (proc.stdout or "")[-500:]}
        return {"ok": True, "result": out.get("result"),
                "explanation": out.get("explanation", ""), "error": None}
