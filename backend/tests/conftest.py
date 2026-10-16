"""All tests use disposable databases; never connect to a deployment database."""
import os
import sys
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["APP_ENV"] = "testing"
os.environ["SECRET_KEY"] = "isolated-tests-only-42e77368071baf60a39e476b196052bd"
os.environ["SEED_DEMO"] = "false"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import Role, User
from app.auth import hash_password


@pytest.fixture
def db():
    from app import auth_models  # register session/rate-limit tables
    from app import notifications  # noqa: F401 — tabel notifikasi + mesin notifikasi otomatis
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture(scope="session")
def password_hash():
    return hash_password("ValidPass-2026!")


@pytest.fixture
def users(db, password_hash):
    result = {}
    for role in Role:
        user = User(name=role.value, email=f"{role.value.lower()}@example.com", password_hash=password_hash, role=role)
        db.add(user)
        result[role] = user
    db.commit()
    return result


@pytest.fixture
def headers(db, users):
    from app.auth import create_access_token

    def for_role(role):
        user = users[Role(role)] if not isinstance(role, User) else role
        token = create_access_token(user, db)
        db.commit()
        return {"Authorization": f"Bearer {token}"}

    return for_role


@pytest.fixture
def client(db):
    from fastapi.testclient import TestClient
    from app.main import app

    def isolated_db():
        try:
            yield db
        except Exception:
            db.rollback()
            raise

    app.dependency_overrides[get_db] = isolated_db
    # No lifespan entry: tests explicitly own schema/seed and may not bootstrap prod.
    client = TestClient(app)
    try:
        yield client
    finally:
        client.close()
        app.dependency_overrides.clear()
