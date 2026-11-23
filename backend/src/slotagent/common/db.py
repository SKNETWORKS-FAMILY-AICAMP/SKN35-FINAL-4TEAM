"""[①] 제품 DB 공통 연결. 환경 변수 DATABASE_URL을 우선하고, 없으면 루트 .env를 읽습니다.

사용 예:
    with connect() as conn:
        row = conn.execute("SELECT 1").fetchone()

기본은 트랜잭션 연결입니다. with 블록이 정상이면 커밋, 예외면 롤백 후 연결을 닫습니다.
작업 임대처럼 즉시 반영할 연결은 connect(autocommit=True)로 명시합니다.
마이그레이션·시드 적용이나 작업 재시도는 이 모듈에서 하지 않습니다.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import psycopg
from dotenv import dotenv_values
from psycopg.conninfo import conninfo_to_dict

_ENV_FILE = Path(__file__).resolve().parents[4] / ".env"


class DatabaseConfigurationError(ValueError):
    """접속 정보가 없거나 형식이 잘못된 경우. 메시지에 접속 문자열을 넣지 않습니다."""


def get_database_url() -> str:
    """접속 URL을 읽고 검사합니다. 환경 변수·다른 .env 값은 변경하지 않습니다."""
    url = os.environ.get("DATABASE_URL")
    if url is None:
        url = dotenv_values(_ENV_FILE).get("DATABASE_URL")
    if not url or not url.strip():
        raise DatabaseConfigurationError("DATABASE_URL을 환경 변수 또는 저장소 루트 .env에 설정하세요.")
    url = url.strip()
    if not url.startswith(("postgresql://", "postgres://")):
        raise DatabaseConfigurationError("DATABASE_URL은 PostgreSQL 접속 URL이어야 합니다.")
    try:
        options = conninfo_to_dict(url)
    except psycopg.ProgrammingError:
        raise DatabaseConfigurationError(
            "DATABASE_URL 형식이 올바르지 않습니다. 호스트·포트·URL 인코딩을 확인하세요."
        ) from None
    # libpq의 URL 파서는 포트를 문자열로만 읽으므로 실제 접속 전에 범위를 확인합니다.
    for port in options.get("port", "").split(","):
        if port and (not port.isascii() or not port.isdecimal() or not 1 <= int(port) <= 65535):
            raise DatabaseConfigurationError("DATABASE_URL의 포트는 1부터 65535 사이의 정수여야 합니다.")
    return url


def connect(*, autocommit: bool = False, connect_timeout: int = 5) -> psycopg.Connection[tuple[Any, ...]]:
    """새 연결을 반환합니다. 호출자는 with 블록이나 close()로 연결을 정리합니다.

    설정 오류는 DatabaseConfigurationError, 실제 접속 실패는 psycopg 오류로 전달합니다.
    SQL의 트랜잭션 범위는 호출자가 정하며, 결과 행은 기존 코드와 같은 tuple입니다.
    """
    if isinstance(connect_timeout, bool) or not isinstance(connect_timeout, int) or connect_timeout < 1:
        raise ValueError("connect_timeout은 1 이상의 정수여야 합니다.")
    return psycopg.connect(get_database_url(), autocommit=autocommit, connect_timeout=connect_timeout)
