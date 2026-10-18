.PHONY: check test benchmark lint format typecheck

check:
	bash scripts/check.sh

test:
	.venv/bin/pytest tests --ignore=tests/payments_audit -q

benchmark:
	.venv/bin/python scripts/benchmark_pipeline.py --markdown

lint:
	.venv/bin/ruff check karkas tests scripts

format:
	.venv/bin/ruff format karkas tests scripts

typecheck:
	.venv/bin/mypy karkas/domain
	cd web && npm run typecheck
