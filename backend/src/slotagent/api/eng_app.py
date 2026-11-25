"""① FastAPI 앱. 다른 역할의 라우터는 routers 에 더하기만 합니다. 오류는 모두 api.error 모양입니다.

실행: uv run uvicorn --factory slotagent.api.eng_app:create_app   (로그인이 정해지기 전이라 127.0.0.1 에서만)
"""

from __future__ import annotations

import logging
import traceback
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


# DB 원문에는 값이 섞일 수 있어 코드마다 정한 문구만 보냅니다.
MESSAGES = {
    "invalid_spec": "요청 내용이 올바르지 않습니다.",
    "invalid_plan": "실험 계획이 올바르지 않습니다.",
    "limit_exceeded": "정해진 개수를 넘었습니다.",
    "baseline_exists": "이 자리에는 이미 기준 후보가 있습니다.",
    "label_taken": "같은 이름의 후보가 있습니다. 다른 이름을 골라 주세요.",
    "wrong_slot": "이 실험의 자리와 다른 자리의 후보입니다.",
    "immutable": "저장한 내용은 바꿀 수 없습니다. 새로 등록해 주세요.",
    "experiment_locked": "시작한 실험은 바꿀 수 없습니다.",
    "not_lockable": "실험을 시작할 조건이 갖춰지지 않았습니다. 평가팩·후보·계획을 확인하세요.",
    "not_found": "찾을 수 없습니다.",
    "budget_exceeded": "예산을 넘었습니다.",
    "proposal_stale": "제안이 바뀌었습니다. 다시 불러와 주세요.",
}


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
    return _error(error["code"], MESSAGES.get(error["code"], GENERIC))


def _unready(_: Request, exc: Exception):
    if isinstance(exc, db.DatabaseConfigurationError):
        return _error("internal", GENERIC, 503)
    return _error("internal", "아직 준비되지 않은 기능입니다.", 501)


def _where(exc: BaseException) -> str:
    """오류 문구 없이 종류와 코드 위치만. 문구에는 접속 정보·입력값이 들어 있을 수 있습니다."""
    frames = traceback.extract_tb(exc.__traceback__)[-5:]
    return f"{type(exc).__name__} " + " > ".join(f"{f.name}:{f.lineno}" for f in frames)


class _SafeErrors:
    """처리하지 못한 예외가 서버 로그에 원문으로 남지 않게 앱 안에서 끝냅니다."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = False

        async def tracked(message):
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, receive, tracked)
        except Exception as exc:
            log.error("처리하지 못한 오류: %s", _where(exc))
            if started:
                raise RuntimeError("응답을 보내는 중 오류가 났습니다.") from None
            await _error("internal", GENERIC, 500)(scope, receive, send)


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
    app.add_middleware(_SafeErrors)
    return app
