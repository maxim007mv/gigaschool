"""karkas.infra.embeddings — эмбеддинги Cloud.ru FM (RAG базы знаний).

Модель — settings.model_embed (Qwen3-Embedding). Вызовы идут только в
Cloud.ru Foundation Models (allowlist); ключ — из окружения.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

from karkas.agent.llm_gateway import TransientError
from karkas.settings import settings


async def embed_texts(
    texts: Sequence[str],
    *,
    batch_size: int = 16,
    meter: Any | None = None,
    skill: str = "embed",
) -> list[list[float]]:
    """Получить эмбеддинги для текстов (батчами). Без ключа — понятная ошибка."""
    if not texts:
        return []
    if not settings.fm_api_key or not settings.model_embed:
        raise TransientError("Эмбеддинги недоступны: не настроены FM_API_KEY / MODEL_EMBED")

    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        base_url=settings.fm_base_url,
        api_key=settings.fm_api_key,
        timeout=settings.llm_timeout_s,
        max_retries=0,
    )
    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = list(texts[start : start + batch_size])
        started = time.monotonic()
        try:
            response = await client.embeddings.create(
                model=settings.model_embed,
                input=batch,
                dimensions=1024,
            )
        except Exception as exc:  # сетевые/429/5xx — транзиентно; 4xx — конфигурация
            status = getattr(exc, "status_code", None)
            transient = status in (429, 500, 502, 503, 504) or isinstance(exc, (ConnectionError, TimeoutError, OSError))
            if transient:
                raise TransientError(f"embeddings: {type(exc).__name__}: {exc}") from exc
            raise ValueError(
                f"embeddings: модель {settings.model_embed!r} недоступна или запрос неверен "
                f"({type(exc).__name__}: {exc})"
            ) from exc
        prompt_tokens = int(getattr(response.usage, "prompt_tokens", 0) or 0)
        latency_ms = (time.monotonic() - started) * 1000.0
        if meter is not None:
            from karkas.agent.skills._base import maybe_await

            await maybe_await(
                meter.record(
                    skill,
                    settings.model_embed,
                    prompt_tokens,
                    0,
                    latency_ms,
                    ok=True,
                    cache_hit=False,
                )
            )
        for item in response.data:
            vec = list(item.embedding)
            if len(vec) > 1024:
                vec = vec[:1024]
            elif len(vec) < 1024:
                vec = vec + [0.0] * (1024 - len(vec))
            vectors.append(vec)
    if len(vectors) != len(texts):
        raise ValueError(f"embeddings: получено {len(vectors)} векторов на {len(texts)} текстов")
    return vectors
