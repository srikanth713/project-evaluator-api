"""FastAPI application factory for the MSGI ONE Project Evaluator API."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import Settings
from app.routes import evaluation, health
from app.services.evaluation_service import EvaluationService
from app.services.gemini_service import GeminiService
from app.services.github_service import GitHubService
from app.services.storage import EvaluationStore
from app.utils.errors import AppError, error_body
from app.utils.rate_limit import SlidingWindowRateLimiter

logger = logging.getLogger("project_evaluator")
API_PREFIX = "/api/v1"


def create_app(
    settings: Settings | None = None,
    evaluation_service: EvaluationService | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.validate()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    app = FastAPI(title=settings.app_name, version=settings.app_version)
    app.state.settings = settings
    app.state.rate_limiter = SlidingWindowRateLimiter(
        settings.rate_limit_requests, settings.rate_limit_window_seconds
    )
    app.state.evaluation_service = evaluation_service or EvaluationService(
        settings,
        GitHubService(settings),
        GeminiService(settings),
        EvaluationStore(settings.database_path),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-API-Key"],
    )

    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=error_body(exc.code, exc.message))

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = []
        for err in exc.errors():
            loc = [str(p) for p in err.get("loc", []) if p != "body"]
            msg = str(err.get("msg", "Invalid value")).removeprefix("Value error, ")
            details.append({"field": ".".join(loc), "message": msg})
        return JSONResponse(
            status_code=422,
            content=error_body("INVALID_REQUEST", "The request data is invalid.", details),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
        message = "The requested resource was not found." if exc.status_code == 404 else "Request could not be processed."
        return JSONResponse(status_code=exc.status_code, content=error_body(code, message))

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        # Log the type only: no stack trace, request data or secrets are returned or written.
        logger.error("Unhandled error: %s", type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content=error_body("INTERNAL_ERROR", "An unexpected error occurred."),
        )

    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(evaluation.router, prefix=API_PREFIX)
    return app


app = create_app()
