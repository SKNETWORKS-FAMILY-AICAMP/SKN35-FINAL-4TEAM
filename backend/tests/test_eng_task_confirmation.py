"""0004 sa_tasks.confirmation: NULL과 객체만 저장합니다."""
import psycopg
import psycopg.sql
import pytest


def test_column(pg):
    with psycopg.connect(pg) as c:
        row = c.execute("SELECT data_type, is_nullable, column_default FROM information_schema.columns "
                        "WHERE table_schema='public' AND table_name='sa_tasks' AND column_name='confirmation'").fetchone()
    assert row == ("jsonb", "YES", None)


@pytest.mark.parametrize("value, ok", [
    (None, True), ("{}", True), ('{"schema_version":1,"responses":[]}', True),
    ("null", False), ("[]", False), ('"approve"', False), ("1", False),
])
def test_object_or_null(pg, value, ok):
    with psycopg.connect(pg) as c:
        # 실제 테이블의 CHECK만 옮긴 임시 표라 FK 준비와 남는 행이 없습니다.
        c.execute("CREATE TEMP TABLE t (LIKE sa_tasks INCLUDING CONSTRAINTS)")
        for (name,) in c.execute("SELECT attname FROM pg_attribute WHERE attrelid='t'::regclass AND attnum>0 AND attnotnull").fetchall():
            c.execute(psycopg.sql.SQL("ALTER TABLE t ALTER {} DROP NOT NULL").format(psycopg.sql.Identifier(name)))
        if ok:
            c.execute("INSERT INTO t(confirmation) VALUES (%s::jsonb)", (value,))
        else:
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute("INSERT INTO t(confirmation) VALUES (%s::jsonb)", (value,))
        c.rollback()
