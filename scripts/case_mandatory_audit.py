#!/usr/bin/env python3
"""Печать статуса пунктов «Обязательно» из описания кейса (раздел 5)."""

from __future__ import annotations

import sys

from karkas.eval.mandatory_audit import audit_mandatory, format_mandatory_report


def main() -> int:
    rows = audit_mandatory()
    print(format_mandatory_report(rows))
    return 0 if all(ok for _, ok, _ in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
