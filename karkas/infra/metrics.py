"""karkas.infra.metrics — метрики Prometheus (Д1 §14).

karkas_skill_seconds{skill}, karkas_llm_tokens_total{model,kind}, karkas_queue_depth,
karkas_validation_errors_total{rule}, karkas_framework_seconds (SLO ≤ 180 с).
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

skill_seconds = Histogram(
    "karkas_skill_seconds",
    "Длительность выполнения навыка",
    labelnames=("skill",),
)

framework_seconds = Histogram(
    "karkas_framework_seconds",
    "Время сборки каркаса (SLO ≤ 180 с)",
)

kit_seconds = Histogram(
    "karkas_kit_seconds",
    "Время сборки комплекта",
)

llm_tokens_total = Counter(
    "karkas_llm_tokens_total",
    "Израсходовано токенов модели",
    labelnames=("model", "kind"),  # kind: prompt|completion
)

llm_cache_hits_total = Counter(
    "karkas_llm_cache_hits_total",
    "Попадания в кэш ответов моделей",
)

validation_errors_total = Counter(
    "karkas_validation_errors_total",
    "Нарушения правил самопроверки",
    labelnames=("rule",),
)

jobs_enqueued_total = Counter(
    "karkas_jobs_enqueued_total",
    "Поставлено задач в очередь",
    labelnames=("kind",),
)

queue_depth = Gauge(
    "karkas_queue_depth",
    "Число задач, ожидающих обработки (queued + retry_wait)",
)
