"""CLI run_eval --kit на reference kits."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_run_eval_kit_tk1_reference() -> None:
    kit_path = ROOT / "data" / "eval" / "tk1.json"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_eval.py"), "--kit", str(kit_path), "--case", "tk1"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
