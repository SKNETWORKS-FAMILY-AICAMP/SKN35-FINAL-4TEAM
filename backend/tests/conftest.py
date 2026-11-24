import json
import pathlib
import sys
from urllib.parse import urlsplit

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "src"))
EX = ROOT / "contracts" / "examples"


def load(name: str) -> dict:
    return json.loads((EX / name).read_text(encoding="utf-8"))


def database_url(url: str, dbname: str) -> str:
    """pgserver URL의 사용자 정보·소켓 query를 보존하고 DB 경로만 바꿉니다."""
    return urlsplit(url)._replace(path=f"/{dbname}").geturl()


@pytest.fixture(scope="session")
def pg():
    """임시 PostgreSQL 16 (pgserver) 에 backend/db/migrations 를 순서대로 넣은 연결 주소."""
    import shutil
    import tempfile

    import pgserver
    import psycopg

    data_dir = pathlib.Path(tempfile.mkdtemp(prefix="slotagent_e2e_"))
    srv = pgserver.get_server(str(data_dir), cleanup_mode="stop")
    server_url = srv.get_uri()
    test_url = database_url(server_url, "e2e")
    with psycopg.connect(database_url(server_url, "postgres"), autocommit=True) as c:
        c.execute("DROP DATABASE IF EXISTS e2e")
        c.execute("CREATE DATABASE e2e")
    with psycopg.connect(test_url, autocommit=True) as c:
        for f in sorted((ROOT / "backend" / "db" / "migrations").glob("*.sql")):
            c.execute(f.read_text(encoding="utf-8"))
    yield test_url
    srv.cleanup()
    shutil.rmtree(data_dir, ignore_errors=True)
