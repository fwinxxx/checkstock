import os

import pytest
from alembic import command as alembic_command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url

# Never erase the demo database. Tests require an explicitly separate *_test DB.
test_url = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://checkstock:checkstock@127.0.0.1:55432/checkstock_test",
)
if not (make_url(test_url).database or "").endswith("_test"):
    raise RuntimeError("TEST_DATABASE_URL must point to a dedicated database ending in _test")
os.environ["DATABASE_URL"] = test_url

from app.db import SessionLocal, engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.seed import seed  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def migrate():
    alembic_command.upgrade(Config("alembic.ini"), "head")
    yield
    engine.dispose()


@pytest.fixture
def client():
    with SessionLocal.begin() as session:
        session.execute(
            text(
                "TRUNCATE commands, events, flows, stocks, warehouses, products, shops "
                "RESTART IDENTITY CASCADE"
            )
        )
        seed(session)
    with TestClient(create_app()) as client:
        yield client
