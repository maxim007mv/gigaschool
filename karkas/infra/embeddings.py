"""karkas.infra.embeddings — эмбеддинги Cloud.ru FM (RAG базы знаний).

Модель — settings.model_embed (Qwen3-Embedding). Вызовы идут только в
Cloud.ru Foundation Models (allowlist); ключ — из окружения.
"""

from __future__ import annotations

from typing import Sequence

from karkas.agent.llm_gateway import TransientError
from karkas.settings import settings


async def embed_texts(texts: Sequence[str], *, batch_size: int = 16) -> list[list[float]]:
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
        try:
            response = await client.embeddings.create(model=settings.model_embed, input=batch)
        except Exception as exc:  # сетевые/429/5xx — транзиентно; 4xx — конфигурация
            status = getattr(exc, "status_code", None)
            transient = status in (429, 500, 502, 503, 504) or isinstance(
                exc, (ConnectionError, TimeoutError, OSError)
            )
            if transient:
                raise TransientError(f"embeddings: {type(exc).__name__}: {exc}") from exc
            raise ValueError(
                f"embeddings: модель {settings.model_embed!r} недоступна или запрос неверен "
                f"({type(exc).__name__}: {exc})"
            ) from exc
        vectors.extend([list(item.embedding) for item in response.data])
    if len(vectors) != len(texts):
        raise ValueError(f"embeddings: получено {len(vectors)} векторов на {len(texts)} текстов")
    return vectors
