"""CLI run_eval --kit на reference kits."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_run_eval_kit_tk1_reference_reports_known_gaps() -> None:
    kit_path = ROOT / "data" / "eval" / "tk1.json"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_eval.py"), "--kit", str(kit_path), "--case", "tk1"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    output = proc.stdout + proc.stderr
    # Минимальная фикстура ТК-1 не содержит 10 вопросов, слайдов и глоссария:
    # CLI должен вернуть 1 и перечислить именно эти пробелы.
    assert proc.returncode == 1, output
    for item_id in ("TK1-6", "TK1-7", "TK1-8"):
        assert f"[FAIL] TK-1 {item_id}" in output, output
    assert "[FAIL] TK-1 TK1-1" not in output, output
