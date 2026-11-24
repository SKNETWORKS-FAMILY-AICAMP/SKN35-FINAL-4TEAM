"""① 공용 pg 픽스처의 TCP/소켓 URL 호환성을 확인합니다."""

import pytest
from conftest import database_url

from slotagent.common import db

WINDOWS_URL = "postgresql://postgres:@127.0.0.1:49152/postgres?sslmode=disable"
SOCKET_URL = "postgresql://postgres:@/postgres?host=/tmp/tmpabc"


def test_windows_url_changes_only_database():
    assert database_url(WINDOWS_URL, "e2e") == "postgresql://postgres:@127.0.0.1:49152/e2e?sslmode=disable"


def test_socket_url_preserves_host_query():
    assert database_url(SOCKET_URL, "e2e") == "postgresql://postgres:@/e2e?host=/tmp/tmpabc"


@pytest.mark.parametrize("source", [WINDOWS_URL, SOCKET_URL])
def test_database_url_passes_product_validation(monkeypatch, source):
    url = database_url(source, "e2e")
    monkeypatch.setenv("DATABASE_URL", url)
    assert db.get_database_url() == url
