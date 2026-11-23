"""① 공통 DB 연결의 설정 우선순위·조회·커밋·롤백을 확인합니다."""

import os
import traceback
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from slotagent.common import db


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    """실제 .env와 셸 설정을 읽지 않도록 격리합니다."""
    path = tmp_path / ".env"
    monkeypatch.setattr(db, "_ENV_FILE", path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return path


def test_database_url_environment_has_priority(env_file, monkeypatch):
    env_file.write_text("DATABASE_URL=postgresql://file_user@localhost/file_db\n", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", "postgresql://env_user@localhost/env_db")
    assert db.get_database_url() == "postgresql://env_user@localhost/env_db"


def test_database_url_reads_root_env_without_changing_environment(env_file):
    env_file.write_text(
        "DATABASE_URL=postgresql://local_user@localhost/local_db\nOTHER_KEY=private\n", encoding="utf-8"
    )
    before = dict(os.environ)
    assert db.get_database_url() == "postgresql://local_user@localhost/local_db"
    assert dict(os.environ) == before


@pytest.mark.parametrize("value", [None, "", "   "])
def test_database_url_missing_or_empty_is_an_error(env_file, monkeypatch, value):
    if value is not None:
        monkeypatch.setenv("DATABASE_URL", value)
    with pytest.raises(db.DatabaseConfigurationError, match="DATABASE_URL"):
        db.get_database_url()


def test_empty_environment_does_not_fall_back_to_file(env_file, monkeypatch):
    env_file.write_text("DATABASE_URL=postgresql://file_user@localhost/file_db\n", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", "")
    with pytest.raises(db.DatabaseConfigurationError):
        db.get_database_url()


@pytest.mark.parametrize(
    "url", ["sqlite://user:secret_password@localhost/db", "postgresql://user:secret_password@host:bad/db"]
)
def test_bad_url_does_not_expose_credentials(env_file, monkeypatch, url):
    monkeypatch.setenv("DATABASE_URL", url)
    with pytest.raises(db.DatabaseConfigurationError) as exc:
        db.get_database_url()
    rendered = "".join(traceback.format_exception(exc.type, exc.value, exc.tb))
    assert "secret_password" not in rendered


@pytest.mark.parametrize("timeout", [0, -1, True, 1.5])
def test_connect_rejects_invalid_timeout(env_file, timeout):
    with pytest.raises(ValueError, match="connect_timeout"):
        db.connect(connect_timeout=timeout)


def test_connect_reads_existing_product_tables(pg, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", pg)
    with db.connect() as conn:
        assert not conn.autocommit
        assert conn.execute("SELECT 1").fetchone() == (1,)
        assert conn.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' "
            "AND table_type = 'BASE TABLE' AND table_name LIKE 'sa_%'"
        ).fetchone() == (33,)
    assert conn.closed


@pytest.fixture
def transaction_table(pg, monkeypatch):
    """제품 테이블 대신 전용 스키마에서 트랜잭션을 확인합니다."""
    monkeypatch.setenv("DATABASE_URL", pg)
    schema = "eng_db_test_" + uuid4().hex
    table = sql.Identifier(schema, "entries")
    with psycopg.connect(pg, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        admin.execute(sql.SQL("CREATE TABLE {} (value integer NOT NULL)").format(table))
        try:
            yield table
        finally:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_connection_context_commits_and_closes(transaction_table):
    with db.connect() as writer:
        writer.execute(sql.SQL("INSERT INTO {} VALUES (%s)").format(transaction_table), (7,))
    assert writer.closed
    with db.connect() as reader:
        assert reader.execute(sql.SQL("SELECT value FROM {}").format(transaction_table)).fetchall() == [(7,)]


def test_connection_context_rolls_back_and_closes(transaction_table):
    with pytest.raises(RuntimeError, match="롤백 확인"):
        with db.connect() as writer:
            writer.execute(sql.SQL("INSERT INTO {} VALUES (%s)").format(transaction_table), (9,))
            raise RuntimeError("롤백 확인")
    assert writer.closed
    with db.connect() as reader:
        assert reader.execute(sql.SQL("SELECT count(*) FROM {}").format(transaction_table)).fetchone() == (0,)


def test_autocommit_connection(transaction_table):
    with db.connect(autocommit=True) as writer:
        assert writer.autocommit
        writer.execute(sql.SQL("INSERT INTO {} VALUES (%s)").format(transaction_table), (11,))
        with db.connect() as reader:
            assert reader.execute(sql.SQL("SELECT value FROM {}").format(transaction_table)).fetchall() == [(11,)]
    assert writer.closed
