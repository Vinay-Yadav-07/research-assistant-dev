"""Maps domain exceptions and framework errors to the shared error envelope."""

import logging

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import (
    AppError,
    AuthenticationError,
    ConflictError,
    DependencyUnavailableError,
    ExternalServiceError,
    FileTooLargeError,
    InvalidInputError,
    NotFoundError,
    PermissionDeniedError,
    UnsupportedFileTypeError,
)
from app.schemas.errors import ErrorBody, ErrorResponse

logger = logging.getLogger(__name__)

STATUS_BY_ERROR: dict[type[AppError], int] = {
    AuthenticationError: status.HTTP_401_UNAUTHORIZED,
    NotFoundError: status.HTTP_404_NOT_FOUND,
    PermissionDeniedError: status.HTTP_403_FORBIDDEN,
    FileTooLargeError: status.HTTP_413_CONTENT_TOO_LARGE,
    UnsupportedFileTypeError: status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    InvalidInputError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    ConflictError: status.HTTP_409_CONFLICT,
    ExternalServiceError: status.HTTP_502_BAD_GATEWAY,
    DependencyUnavailableError: status.HTTP_503_SERVICE_UNAVAILABLE,
}


def _status_for(error: AppError) -> int:
    for error_type in type(error).__mro__:
        if error_type in STATUS_BY_ERROR:
            return STATUS_BY_ERROR[error_type]
    return status.HTTP_500_INTERNAL_SERVER_ERROR


def _envelope(
    status_code: int, body: ErrorBody, headers: dict[str, str] | None = None
) -> JSONResponse:
    content = jsonable_encoder(ErrorResponse(error=body))
    return JSONResponse(status_code=status_code, content=content, headers=headers)


async def _handle_app_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    status_code = _status_for(exc)
    if status_code >= 500:
        logger.error("%s on %s %s: %s", exc.code, request.method, request.url.path, exc.message)
    # RFC 6750: a 401 tells the client which scheme to use.
    headers = {"WWW-Authenticate": "Bearer"} if status_code == 401 else None
    return _envelope(
        status_code, ErrorBody(code=exc.code, message=exc.message, details=exc.details), headers
    )


async def _handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    body = ErrorBody(
        code="validation_error",
        message="The request failed validation.",
        details={"errors": jsonable_encoder(exc.errors())},
    )
    return _envelope(status.HTTP_422_UNPROCESSABLE_CONTENT, body)


async def _handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    body = ErrorBody(code=f"http_{exc.status_code}", message=str(exc.detail))
    return JSONResponse(
        status_code=exc.status_code,
        content=jsonable_encoder(ErrorResponse(error=body)),
        headers=exc.headers,
    )


async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    body = ErrorBody(code="internal_error", message="An unexpected error occurred.")
    return _envelope(status.HTTP_500_INTERNAL_SERVER_ERROR, body)


def register_exception_handlers(app: FastAPI) -> None:
    """Install handlers so every error response uses `ErrorResponse`."""
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(Exception, _handle_unexpected_error)
