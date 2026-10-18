"""karkas.logging_setup — структурированное JSON-логирование (Д1 §14).

Правила: JSON в проде, читаемый вывод в dev; корреляция по program_id/job_id;
тексты промптов в логи НЕ пишутся (только хэш и размер — см. llm_gateway);
секреты (token/api_key) в строках логов маскируются.
"""

from __future__ import annotations

import logging
import re
import sys

import structlog

from karkas.settings import settings


class RedactSecretsFilter(logging.Filter):
    """Маскирует значения token/api_key/key в сообщениях логов (access-логи uvicorn)."""

    _PATTERN = re.compile(r"(?i)\b(token|api[_-]?key|password|secret)=([^&\s\"']+)")

    def _redact(self, value: str) -> str:
        return self._PATTERN.sub(lambda match: f"{match.group(1)}=***", value)

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 — API logging
        try:
            if isinstance(record.args, tuple):
                record.args = tuple(self._redact(item) if isinstance(item, str) else item for item in record.args)
            elif isinstance(record.args, dict):
                record.args = {
                    key: (self._redact(value) if isinstance(value, str) else value)
                    for key, value in record.args.items()
                }
            if isinstance(record.msg, str):
                record.msg = self._redact(record.msg)
        except Exception:
            pass  # логирование не должно падать из-за маскирования
        return True


def configure_logging() -> None:
    """Настроить structlog один раз при старте процесса (api, worker, скрипты)."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)

    redactor = RedactSecretsFilter()
    for logger_name in ("uvicorn", "uvicorn.access", "uvicorn.error", "root"):
        logging.getLogger(logger_name).addFilter(redactor)

    processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if settings.environment == "dev":
        processors.append(structlog.dev.ConsoleRenderer())
    else:
        processors.append(structlog.processors.JSONRenderer(ensure_ascii=False))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Логгер модуля (вызывать после configure_logging)."""
    return structlog.get_logger(name)
