"""karkas.api.errors — ошибки API в формате RFC 9457 problem+json (Д4 §7).

Каталог кодов строго из таблицы Д4 §7. Все сообщения — на русском, без жаргона.
"""

from __future__ import annotations

from typing import Any, ClassVar

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

ERROR_BASE = "https://karkas/errors"


class KarkasProblem(Exception):
    """Базовая ошибка API. Сериализуется в problem+json."""

    status: ClassVar[int] = 400
    code: ClassVar[str] = "BAD_REQUEST"
    title: ClassVar[str] = "Ошибка запроса"

    def __init__(self, detail: str | None = None, extra: dict[str, Any] | None = None) -> None:
        self.detail = detail or self.title
        self.extra = extra or {}
        super().__init__(self.detail)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": f"{ERROR_BASE}/{self.code.lower().replace('_', '-')}",
            "title": self.title,
            "status": self.status,
            "code": self.code,
            "detail": self.detail,
            **self.extra,
        }


# --- 4xx -------------------------------------------------------------------


class BadRequest(KarkasProblem):
    status = 400
    code = "BAD_REQUEST"
    title = "Некорректный запрос"


class Unauthorized(KarkasProblem):
    status = 401
    code = "UNAUTHORIZED"
    title = "Требуется вход"

    def __init__(self, detail: str = "Нет или истёк токен / API-ключ") -> None:
        super().__init__(detail)


class Forbidden(KarkasProblem):
    status = 403
    code = "FORBIDDEN"
    title = "Недостаточно прав"


class NotFound(KarkasProblem):
    status = 404
    code = "NOT_FOUND"
    title = "Не найдено"


class EditTargetNotFound(KarkasProblem):
    status = 404
    code = "EDIT_TARGET_NOT_FOUND"
    title = "Элемент для правки не найден"


class GateNotPassed(KarkasProblem):
    status = 409
    code = "GATE_NOT_PASSED"
    title = "Каркас не утверждён"

    def __init__(self, detail: str = "Сначала утвердите каркас: цель, компетенции и часы") -> None:
        super().__init__(detail)


class HoursMismatch(KarkasProblem):
    status = 409
    code = "HOURS_MISMATCH"
    title = "Часы не сходятся"

    def __init__(self, issues: list[dict[str, Any]] | None = None) -> None:
        super().__init__(
            "Каркас нельзя утвердить, пока есть ошибки в часах",
            extra={"issues": issues or []},
        )


class ClarificationRequired(KarkasProblem):
    status = 409
    code = "CLARIFICATION_REQUIRED"
    title = "Нужны уточнения"

    def __init__(self, detail: str = "Ответьте на обязательные вопросы, иначе агент не начнёт сборку") -> None:
        super().__init__(detail)


class JobInProgress(KarkasProblem):
    status = 409
    code = "JOB_IN_PROGRESS"
    title = "Задача уже выполняется"


class VersionConflict(KarkasProblem):
    status = 412
    code = "VERSION_CONFLICT"
    title = "Конфликт версий"

    def __init__(self, detail: str = "Каркас изменил другой пользователь — обновите страницу") -> None:
        super().__init__(detail)


class FileTooLarge(KarkasProblem):
    status = 413
    code = "FILE_TOO_LARGE"
    title = "Файл слишком большой"


class UnsupportedFile(KarkasProblem):
    status = 415
    code = "UNSUPPORTED_FILE"
    title = "Неподдерживаемый тип файла"


class ValidationProblem(KarkasProblem):
    status = 422
    code = "VALIDATION_ERROR"
    title = "Ошибка в данных запроса"


class InfeasibleConstraints(KarkasProblem):
    status = 422
    code = "INFEASIBLE_CONSTRAINTS"
    title = "Ограничения часов несовместимы"


class RateLimited(KarkasProblem):
    status = 429
    code = "RATE_LIMITED"
    title = "Слишком много запросов"

    def __init__(self, retry_after_s: int = 30) -> None:
        super().__init__("Превышен лимит запросов, повторите позже", extra={"retry_after": retry_after_s})
        self.retry_after_s = retry_after_s


# --- 5xx -------------------------------------------------------------------


class LlmBadOutputProblem(KarkasProblem):
    status = 502
    code = "LLM_BAD_OUTPUT"
    title = "Модель вернула невалидный ответ"


class LlmUnavailable(KarkasProblem):
    status = 503
    code = "LLM_UNAVAILABLE"
    title = "Сервис генерации временно недоступен"


# --- Обработчики ------------------------------------------------------------


async def problem_handler(_: Request, exc: KarkasProblem) -> JSONResponse:
    headers: dict[str, str] = {}
    if isinstance(exc, RateLimited):
        headers["Retry-After"] = str(exc.retry_after_s)
    return JSONResponse(
        status_code=exc.status,
        content=exc.to_dict(),
        media_type="application/problem+json",
        headers=headers,
    )


async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    """Непредвиденные ошибки — тоже problem+json (RFC 9457), с логированием стектрейса."""
    from karkas.logging_setup import get_logger

    get_logger("karkas.api").exception(
        "api.unhandled_error", path=request.url.path, method=request.method
    )
    return JSONResponse(
        status_code=500,
        content={
            "type": f"{ERROR_BASE}/internal-error",
            "title": "Внутренняя ошибка",
            "status": 500,
            "code": "INTERNAL_ERROR",
            "detail": "Внутренняя ошибка сервера; повторите позже",
        },
        media_type="application/problem+json",
    )


def register_error_handlers(app: FastAPI) -> None:
    """Обработчики problem+json: ошибки домена, 422/404, непредвиденные 500."""
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as StarletteHTTPException

    app.add_exception_handler(KarkasProblem, problem_handler)  # type: ignore[arg-type]

    async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        """Ошибка схемы запроса — тоже problem+json (код VALIDATION_ERROR, Д4 §7)."""
        return JSONResponse(
            status_code=422,
            content={
                "type": f"{ERROR_BASE}/validation-error",
                "title": "Ошибка в данных запроса",
                "status": 422,
                "code": "VALIDATION_ERROR",
                "detail": "Проверьте поля запроса",
                "errors": [
                    {"loc": [str(part) for part in err.get("loc", [])], "msg": err.get("msg", "")}
                    for err in exc.errors()[:20]
                ],
            },
            media_type="application/problem+json",
        )

    async def http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "NOT_FOUND" if exc.status_code == 404 else ("UNAUTHORIZED" if exc.status_code == 401 else "HTTP_ERROR")
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "type": f"{ERROR_BASE}/{code.lower().replace('_', '-')}",
                "title": str(exc.detail) if exc.detail else "Ошибка",
                "status": exc.status_code,
                "code": code,
                "detail": str(exc.detail) if exc.detail else "Ошибка",
            },
            media_type="application/problem+json",
        )

    app.add_exception_handler(RequestValidationError, validation_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_handler)
