"""① FastAPI 앱. 다른 역할의 라우터는 routers 에 더하기만 합니다. 오류는 모두 api.error 모양입니다.

실행: uv run uvicorn --factory slotagent.api.eng_app:create_app   (로그인이 정해지기 전이라 127.0.0.1 에서만)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import partial

import psycopg
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from slotagent.api import eng_errors, eng_experiments
from slotagent.common import db, queue
from slotagent.common.checks import CheckError

log = logging.getLogger(__name__)
HTTP_STATUS = {"not_found": 404, "invalid_spec": 422, "invalid_plan": 422, "limit_exceeded": 422, "internal": 500}
GENERIC = "처리하지 못했습니다. 잠시 뒤 다시 시도하세요."


def _error(code: str, message: str, status: int | None = None) -> JSONResponse:
    return JSONResponse({"code": code, "message": message}, status_code=status or HTTP_STATUS.get(code, 409))


def _check(_: Request, exc: CheckError):
    return _error(exc.code, "; ".join(exc.errors))


def _validation(_: Request, exc: Exception):
    return _error("invalid_spec", "요청 형식이 올바르지 않습니다.")


def _http(_: Request, exc: HTTPException):
    if exc.status_code == 404:
        return _error("not_found", "없는 주소입니다.")
    return _error("invalid_spec", "지원하지 않는 요청입니다.", exc.status_code)


def _database(_: Request, exc: psycopg.Error):
    if isinstance(exc, (*queue.TRANSIENT_ERRORS, psycopg.OperationalError)):
        return _error("internal", GENERIC, 503)
    error = eng_errors.to_api_error(exc)
    if error["code"] == "internal":
        # DB 원문에는 값이 들어 있을 수 있어 화면에 보내지 않습니다.
        log.error("처리하지 못한 DB 오류: %s", error["detail"]["sqlstate"])
        return _error("internal", GENERIC)
    return _error(error["code"], error["message"])


def _unready(_: Request, exc: Exception):
    if isinstance(exc, db.DatabaseConfigurationError):
        return _error("internal", GENERIC, 503)
    return _error("internal", "아직 준비되지 않은 기능입니다.", 501)


def _unexpected(_: Request, exc: Exception):
    return _error("internal", GENERIC, 500)


def create_app(connect: Callable | None = None) -> FastAPI:
    app = FastAPI(title="SlotAgent")
    app.state.connect = connect or partial(db.connect, autocommit=True)
    app.include_router(eng_experiments.router)
    app.add_exception_handler(CheckError, _check)
    app.add_exception_handler(RequestValidationError, _validation)
    app.add_exception_handler(HTTPException, _http)
    app.add_exception_handler(psycopg.Error, _database)
    app.add_exception_handler(db.DatabaseConfigurationError, _unready)
    app.add_exception_handler(NotImplementedError, _unready)
    app.add_exception_handler(Exception, _unexpected)
    return app
