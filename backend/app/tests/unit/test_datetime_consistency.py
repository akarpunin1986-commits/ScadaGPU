"""Static analysis test — checks codebase for prohibited datetime patterns."""
from __future__ import annotations

import os
import re

import pytest

# Root of the backend app
APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Patterns that violate the project convention
FORBIDDEN_PATTERNS = [
    # datetime.now() without arguments (local time)
    re.compile(r"datetime\.now\(\s*\)"),
    # datetime.now(timezone.utc) — produces tz-aware timestamps
    re.compile(r"datetime\.now\(\s*timezone\.utc\s*\)"),
    re.compile(r"datetime\.now\(\s*tz\s*=\s*timezone\.utc\s*\)"),
]

# Files/dirs to exclude from the check
EXCLUDE_DIRS = {"__pycache__", ".git", "node_modules", "tests", "alembic", ".venv"}
EXCLUDE_FILES = {"conftest.py"}

# Known exceptions where datetime.now(MSK) is correct (date-level boundaries)
ALLOWED_EXCEPTIONS = {
    # economics.py uses datetime.now(MSK).date() for calendar date — intentional
    os.path.join("api", "economics.py"),
}


def _collect_python_files():
    """Collect all .py files in backend/app/ excluding test dirs."""
    files = []
    for root, dirs, fnames in os.walk(APP_ROOT):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for fname in fnames:
            if fname.endswith(".py") and fname not in EXCLUDE_FILES:
                files.append(os.path.join(root, fname))
    return files


@pytest.mark.unit
def test_no_datetime_now_violations():
    """Scan all Python files for prohibited datetime patterns."""
    violations = []
    py_files = _collect_python_files()
    assert py_files, "No Python files found — check APP_ROOT"

    for filepath in py_files:
        relpath = os.path.relpath(filepath, APP_ROOT)

        # Skip known exceptions
        if any(relpath.endswith(exc) or exc in relpath for exc in ALLOWED_EXCEPTIONS):
            continue

        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for lineno, line in enumerate(f, 1):
                # Skip comments
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue

                for pattern in FORBIDDEN_PATTERNS:
                    if pattern.search(line):
                        violations.append(f"{relpath}:{lineno}: {line.rstrip()}")

    if violations:
        msg = f"Found {len(violations)} prohibited pattern(s):\n"
        msg += "\n".join(f"  {v}" for v in violations[:20])
        if len(violations) > 20:
            msg += f"\n  ... and {len(violations) - 20} more"
        pytest.fail(msg)


@pytest.mark.unit
def test_utcnow_is_used():
    """Verify that datetime.utcnow() is actually used in key files."""
    key_files = [
        os.path.join(APP_ROOT, "services", "alarm_detector.py"),
        os.path.join(APP_ROOT, "services", "auth.py"),
    ]
    pattern = re.compile(r"datetime\.utcnow\(\)")

    for filepath in key_files:
        if not os.path.exists(filepath):
            continue
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        assert pattern.search(content), (
            f"{os.path.basename(filepath)} does not use datetime.utcnow()"
        )
