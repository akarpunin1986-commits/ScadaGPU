"""
Sandbox Runner v2: HTTP-сервер, выполняет Python-код с ограничениями.
Решает П4 (безопасность) на уровне процесса.
"""
import json, logging, os, signal, sys, traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from io import StringIO

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sandbox")

MAX_CPU_TIME_SEC = 60
MAX_OUTPUT_SIZE = 100_000
OUTPUT_DIR = "/output"

# ═══════════ SECURITY: IMPORT CONTROL ═══════════

ALLOWED_TOP_MODULES = {
    # Стандартные (безопасные)
    "json", "math", "re", "datetime", "collections", "itertools",
    "functools", "decimal", "statistics", "hashlib", "uuid",
    "io", "csv", "textwrap", "string", "copy", "operator",
    "dataclasses", "typing", "enum", "pathlib", "os",
    # Стандартные (дополнительные — нужны openpyxl/pandas/matplotlib внутри)
    "time", "struct", "zipfile", "warnings", "calendar", "locale",
    "random", "abc", "numbers", "types", "traceback", "weakref",
    "platform", "xml", "tempfile", "base64", "binascii", "logging",
    "inspect", "array", "bisect", "contextlib", "fnmatch",
    "html", "urllib", "mimetypes", "pprint", "textwrap",
    # Анализ и отчёты
    "openpyxl", "matplotlib", "pandas", "numpy", "PIL",
    # Сеть (контролируемая)
    "httpx",
    # БД (read-only через DSN)
    "psycopg2",
    "sqlalchemy",
    # Redis (read-only)
    "redis",
    # PDF-генерация
    "reportlab",
    "fpdf2", "fpdf",
}

BLOCKED_MODULES = {
    "sys", "subprocess", "shutil", "socket", "ctypes",
    "importlib", "code", "codeop", "multiprocessing", "threading",
    "signal", "resource", "webbrowser", "http.server",
    "pickle", "shelve", "marshal", "asyncio",
    "xmlrpc", "ftplib", "smtplib", "telnetlib",
}


def _make_safe_globals():
    """Безопасное окружение для exec()."""
    import builtins as _b

    _real_import = _b.__import__
    def _safe_import(name, *args, **kwargs):
        top = name.split(".")[0]
        if top in BLOCKED_MODULES:
            raise ImportError(f"Module '{name}' is blocked")
        if top not in ALLOWED_TOP_MODULES:
            raise ImportError(f"Module '{name}' is not allowed in sandbox. "
                              f"Available: {', '.join(sorted(ALLOWED_TOP_MODULES))}")
        return _real_import(name, *args, **kwargs)

    _real_open = _b.open
    def _safe_open(path, mode="r", *a, **kw):
        p = os.path.abspath(str(path))
        if any(c in mode for c in "wax"):
            if not p.startswith(OUTPUT_DIR):
                raise PermissionError(f"Write only to {OUTPUT_DIR}/")
        else:
            if not (p.startswith(OUTPUT_DIR) or p.startswith("/workspace/")):
                raise PermissionError(f"Read denied: {path}")
        return _real_open(path, mode, *a, **kw)

    safe_builtins = {k: v for k, v in vars(_b).items()
                     if k not in {"exec", "eval", "compile", "breakpoint", "exit", "quit"}}
    safe_builtins["__import__"] = _safe_import
    safe_builtins["open"] = _safe_open

    return {"__builtins__": safe_builtins}


# ═══════════ EXECUTION ═══════════

def execute_code(code: str, context: dict) -> dict:
    stdout_buf = StringIO()
    old_stdout = sys.stdout
    result = {"stdout": "", "files": [], "error": None, "return_value": None}

    try:
        sys.stdout = stdout_buf
        g = _make_safe_globals()
        g["OUTPUT_DIR"] = OUTPUT_DIR
        g["CONTEXT"] = context
        g["context"] = context  # lowercase alias (GPT often uses this)
        # Inject context vars as top-level variables
        g["DB_DSN"] = context.get("db_dsn", "")
        g["REDIS_URL"] = context.get("redis_url", "")
        g["NOW_MSK"] = context.get("now_msk", "")
        g["SITES"] = context.get("sites", {})
        g["DEVICES"] = context.get("devices", {})
        g["BITRIX_WEBHOOK"] = context.get("bitrix_webhook", "")
        g["BITRIX_GROUP_ID"] = context.get("bitrix_group_id", 0)

        signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError(f"Timeout {MAX_CPU_TIME_SEC}s")))
        signal.alarm(MAX_CPU_TIME_SEC)

        exec(compile(code, "<sandbox>", "exec"), g)

        signal.alarm(0)
        exec_error = None

    except TimeoutError as e:
        exec_error = str(e)
    except MemoryError:
        exec_error = "Memory limit exceeded"
    except (PermissionError, ImportError) as e:
        exec_error = str(e)
    except Exception as e:
        tb = traceback.format_exc()
        lines = tb.strip().split("\n")
        short = "\n".join(lines[-5:]) if len(lines) > 5 else tb
        exec_error = f"{type(e).__name__}: {e}\n{short}"
    finally:
        sys.stdout = old_stdout
        signal.alarm(0)

    out = stdout_buf.getvalue()
    result["stdout"] = out[:MAX_OUTPUT_SIZE] + ("...[truncated]" if len(out) > MAX_OUTPUT_SIZE else "")

    # Scan output files
    try:
        for f in os.listdir(OUTPUT_DIR):
            fp = os.path.join(OUTPUT_DIR, f)
            if os.path.isfile(fp):
                result["files"].append({"name": f, "path": f"/reports/{f}",
                                        "size_kb": round(os.path.getsize(fp)/1024, 1)})
    except Exception:
        pass

    # Files present → success even without result variable
    if result["files"]:
        result["return_value"] = g.get("result", g.get("RESULT", f"Файлов: {len(result['files'])}"))
        if exec_error:
            result["warning"] = exec_error
        # Don't set error — files were generated
    elif exec_error:
        result["error"] = exec_error
    elif "result" in g:
        result["return_value"] = g["result"]
    elif "RESULT" in g:
        result["return_value"] = g["RESULT"]

    return result


# ═══════════ HTTP SERVER ═══════════

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/execute":
            self.send_error(404); return
        body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
        try:
            p = json.loads(body)
        except Exception:
            self.send_error(400, "Invalid JSON"); return

        code = p.get("code", "").strip()
        if not code:
            self.send_error(400, "Empty code"); return

        # Don't clean /output/ — files may be needed by previous calls
        # Cleanup handled by reports_cleanup_loop in main.py (24h TTL)

        r = execute_code(code, p.get("context", {}))
        resp = json.dumps(r, ensure_ascii=False, default=str)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(resp.encode())

    def log_message(self, fmt, *args): logger.info(fmt, *args)


if __name__ == "__main__":
    port = int(os.environ.get("SANDBOX_PORT", 9999))
    logger.info("Sandbox v2 on port %d", port)
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
