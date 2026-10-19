"""karkas.settings — конфигурация сервиса (Д4 §12).

Правило проекта: os.getenv() внутри функций запрещён — все настройки читаются
один раз здесь (pydantic-settings), модули импортируют объект `settings`.
"""

from __future__ import annotations

import json
from decimal import Decimal
from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import AliasChoices, Field, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ModelClass = Literal["struct", "bulk", "embed", "rerank"]

#: Белый список доверенных хостов шлюза Cloud.ru Foundation Models (ЗАД-13)
APPROVED_GATEWAY_HOSTS: frozenset[str] = frozenset(
    {
        "foundation-models.api.cloud.ru",
        "hub.gigaschool.ru",
        "api.cloud.ru",
        "localhost",
        "127.0.0.1",
        "testserver",
        "example.invalid",
    }
)

#: Ключи extra_body, которые нельзя переопределять: они уже заданы шлюзом.
RESERVED_EXTRA_BODY_KEYS: frozenset[str] = frozenset(
    {"model", "messages", "max_tokens", "response_format", "temperature", "stream", "input"}
)

#: Белый список разрешённых моделей Cloud.ru FM (GigaChat-3-Pro, Reasoning, Giga-Embeddings)
APPROVED_MODELS: frozenset[str] = frozenset(
    {
        "GigaChat/GigaChat-3-Pro",
        "GigaChat-3-Pro",
        "GigaChat/GigaChat-3-Pro-preview",
        "GigaChat-3-Pro-preview",
        "GigaChat/Reasoning",
        "GigaChat-Reasoning",
        "Reasoning",
        "ai-sage/GigaChat3.5-432B-A28B-Reasoning",
        "GigaChat3.5-432B-A28B-Reasoning",
        "ai-sage/Giga-Embeddings-instruct-3B",
        "Giga-Embeddings-instruct-3B",
        "ai-sage/Giga-Embeddings",
        "Giga-Embeddings",
    }
)


class Settings(BaseSettings):
    """Настройки из переменных окружения (см. `.env.example`)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Приложение -------------------------------------------------------
    app_name: str = "karkas"
    environment: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"

    # --- Cloud.ru Foundation Models (единственный разрешённый LLM-провайдер) ---
    fm_base_url: str = Field(
        default="https://foundation-models.api.cloud.ru/v1",
        validation_alias=AliasChoices("FM_BASE_URL"),
    )
    fm_api_key: str = Field(default="", validation_alias=AliasChoices("FM_API_KEY"))
    model_struct: str = "GigaChat/GigaChat-3-Pro"  # экономичная структурная модель (хакатон)
    model_bulk: str = "GigaChat/GigaChat-3-Pro"  # тот же класс — кэш шлюза, меньше сюрпризов по биллингу
    model_embed: str = ""  # ai-sage/Giga-Embeddings-instruct-3B — RAG
    model_rerank: str = ""  # Qwen3-Reranker-0.6B
    model_struct_backup: str = ""  # резервная структурная модель (Д1 §7)
    model_bulk_backup: str = ""  # резервная модель массовой генерации
    model_allowlist: str = ""  # ids через запятую; пусто = разрешены только 4 модели выше
    llm_concurrency: int = Field(default=2, ge=1, le=2)  # лимит хаба: не более 2 параллельных запросов
    llm_timeout_s: int = Field(default=120, ge=5)  # таймаут шлюза хаба
    llm_cache_ttl_h: int = Field(default=168, ge=1)  # 7 суток
    daily_budget_rub: Decimal = Field(default=Decimal("100.0"), ge=Decimal("0.0"))  # дневной лимит 100 ₽
    # Доп. параметры запроса (JSON), напр. '{"reasoning":{"enabled":false}}' для шлюза —
    # отключает скрытое «рассуждение» моделей. Пусто = не слать.
    llm_extra_body_json: str = ""

    @field_validator("fm_base_url")
    @classmethod
    def _validate_fm_base_url(cls, value: str) -> str:
        if not value.strip():
            return value
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        if host and host not in APPROVED_GATEWAY_HOSTS:
            raise ValueError(
                f"Недопустимый хост шлюза {host!r}. Разрешены только хосты Cloud.ru FM: "
                f"{', '.join(sorted(APPROVED_GATEWAY_HOSTS))}"
            )
        return value

    @field_validator("llm_extra_body_json")
    @classmethod
    def _extra_body_is_object(cls, value: str) -> str:
        """LLM_EXTRA_BODY_JSON — JSON-объект; иначе шлюз падал бы при каждом вызове."""
        if not value.strip():
            return ""
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM_EXTRA_BODY_JSON: невалидный JSON ({exc.msg})") from exc
        if not isinstance(parsed, dict):
            raise ValueError('LLM_EXTRA_BODY_JSON: ожидается JSON-объект, например {"reasoning":{"enabled":false}}')
        reserved = sorted(set(parsed) & RESERVED_EXTRA_BODY_KEYS)
        if reserved:
            raise ValueError(
                f"LLM_EXTRA_BODY_JSON: нельзя переопределять служебные поля {', '.join(reserved)} — они задаются шлюзом"
            )
        return value

    llm_max_output_tokens: int = Field(default=4096, ge=0, le=4096)  # хаб: max_tokens ≤ 4096
    llm_max_repairs: int = Field(default=2, ge=0)  # «ремонт» JSON до 2 раз
    llm_backoff_base_s: float = 1.0  # 1 → 2 → 4 с + джиттер
    llm_circuit_failures: int = 10  # 10 ошибок за окно → размыкание (сеть шлюза бывает нестабильной)
    llm_circuit_window_s: int = 60
    llm_circuit_cooldown_s: int = 5  # успевает сработать ретрай навыка (3 попытки)

    # --- Бюджеты и правила домена ----------------------------------------
    framework_slo_s: int = 180
    kit_timeout_min: int = 20
    agent_run_timeout_s: int = Field(default=1200, ge=60)  # wait=true: ожидание воркера
    max_questions: int = Field(default=5, ge=1, le=5)
    min_assessments_per_outcome: int = Field(default=2, ge=1)
    plagiarism_ngram: int = Field(default=5, ge=2)
    plagiarism_max_overlap: float = Field(default=0.15, ge=0, le=1)
    dup_cosine: float = Field(default=0.92, ge=0, le=1)
    hours_cell_max: int = 500
    total_hours_max: int = 2000
    brief_max_chars: int = 20_000
    file_max_bytes: int = 52_428_800  # 50 МБ
    files_per_program_max: int = 10

    # --- БД ---------------------------------------------------------------
    karkas_lite: bool = Field(
        default=False,
        validation_alias=AliasChoices("KARKAS_LITE", "karkas_lite"),
    )
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/karkas"
    db_pool_size: int = Field(default=10, ge=1)
    db_pool_mode: Literal["default", "null"] = "default"  # null — для тестов (нет кросс-loop пула)

    # --- S3 ---------------------------------------------------------------
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket_src: str = "karkas-src"
    s3_bucket_art: str = "karkas-artifacts"
    s3_presign_ttl_s: int = 900  # 15 мин

    # --- Аутентификация ----------------------------------------------------
    jwt_secret: str = "change-me"
    jwt_access_ttl_min: int = 15
    jwt_refresh_ttl_days: int = 14
    agent_api_keys_sha256: str = ""  # хэши ключей тестовой платформы через запятую
    rate_per_min_user: int = 60
    rate_per_min_api_key: int = 30

    # --- Egress ------------------------------------------------------------
    egress_allowlist: str = "foundation-models.api.cloud.ru,hub.gigaschool.ru,pypi.org"

    # --- Прочее ------------------------------------------------------------
    tariffs_json: str = "{}"  # {"<model>": {"in": 0.0, "out": 0.0}} руб. за 1M токенов
    storage_dir: str = "var/storage"  # локальное хранилище (dev); S3 — при заданных ключах
    # База для HTTP-presign локального хранилища (кликабельные ссылки в UI).
    public_api_base: str = "http://127.0.0.1:8000"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def allowed_models(self) -> tuple[str, ...]:
        """Allowlist моделей: только они допускаются к вызову (ЗАД-13)."""
        explicit = tuple(m.strip() for m in self.model_allowlist.split(",") if m.strip())
        if explicit:
            return explicit
        return tuple(m for m in (self.model_struct, self.model_bulk, self.model_embed, self.model_rerank) if m)

    def model_for(self, model_class: ModelClass) -> str:
        """Роутинг класса задач на конкретную модель (Д1 §7)."""
        return {
            "struct": self.model_struct,
            "bulk": self.model_bulk,
            "embed": self.model_embed,
            "rerank": self.model_rerank,
        }[model_class]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def uses_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @model_validator(mode="after")
    def _apply_lite_and_prod(self) -> Settings:
        if self.karkas_lite and not self.database_url.startswith("sqlite"):
            self.database_url = "sqlite+aiosqlite:///./var/karkas.db"
        if self.environment == "prod" and (
            self.jwt_secret in ("", "change-me", "change-me-in-prod") or len(self.jwt_secret) < 32
        ):
            raise ValueError("JWT_SECRET обязателен в проде: не менее 32 символов, без placeholder-значений")
        if self.environment != "test":
            explicit_allowlist = tuple(m.strip() for m in self.model_allowlist.split(",") if m.strip())
            unknown_allowlist = sorted(set(explicit_allowlist) - APPROVED_MODELS)
            if unknown_allowlist:
                raise ValueError(
                    "MODEL_ALLOWLIST может только сужать белый список Cloud.ru FM; "
                    f"неизвестные модели: {', '.join(unknown_allowlist)}"
                )
            allowed = APPROVED_MODELS | set(explicit_allowlist)
            for label, model_name in (
                ("MODEL_STRUCT", self.model_struct),
                ("MODEL_BULK", self.model_bulk),
                ("MODEL_EMBED", self.model_embed),
                ("MODEL_RERANK", self.model_rerank),
                ("MODEL_STRUCT_BACKUP", self.model_struct_backup),
                ("MODEL_BULK_BACKUP", self.model_bulk_backup),
            ):
                if model_name and model_name not in allowed:
                    raise ValueError(
                        f"{label}={model_name!r} не входит в белый список разрешённых моделей Cloud.ru FM: "
                        f"{', '.join(sorted(APPROVED_MODELS))}"
                    )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Кэшированный доступ к настройкам (единственное чтение окружения)."""
    return Settings()


settings = get_settings()
