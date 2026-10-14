# КАРКАС backend: один образ для api и worker (Д1 §8).
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --upgrade pip \
    && pip install \
        "pydantic>=2.7" "pydantic-settings>=2.3" "fastapi>=0.111" "uvicorn[standard]>=0.30" \
        "python-multipart>=0.0.9" "sqlalchemy[asyncio]>=2.0" "asyncpg>=0.29" "alembic>=1.13" \
        "httpx>=0.27" "openai>=1.30" "jinja2>=3.1" "docxtpl>=0.17" "python-docx>=1.1" \
        "python-pptx>=0.6.23" "pypdf>=4.2" "structlog>=24.1" "prometheus-client>=0.20" \
        "orjson>=3.10" "pyjwt>=2.8" "argon2-cffi>=23.1"

COPY karkas ./karkas
COPY migrations ./migrations
COPY templates ./templates

EXPOSE 8000
CMD ["uvicorn", "karkas.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
