"""Lite-smoke: основной сценарий API на SQLite без PostgreSQL."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_lite_smoke_script(tmp_path: Path) -> None:
    db_path = tmp_path / "lite.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "lite_smoke.py"), "--db-url", db_url],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "lite smoke: OK" in proc.stdout
