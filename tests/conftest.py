"""Test setup. Uses Postgres when TEST_DATABASE_URL is set, otherwise a temp SQLite file."""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

CSUSM_NOW = datetime(2026, 9, 29, 16, 0, tzinfo=timezone.utc)  # a day after the fixtures were captured


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_MODE", "true")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-password")
    monkeypatch.setenv("APP_TIMEZONE", "America/Los_Angeles")
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("TELEGRAM_BASEBALL_CHANNEL_ID", "")
    monkeypatch.setenv("TELEGRAM_JOIN_LINKS", "baseball=https://t.me/tam_baseball_test")
    monkeypatch.setenv("LLM_ENABLED", "false")
    monkeypatch.setenv("DATABASE_URL", os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tmp_path}/test.db")
    monkeypatch.chdir(tmp_path)  # so a developer's real .env is never read by tests
    from app.settings import reset_settings_cache

    reset_settings_cache()
    from app.collectors import registry as creg

    creg.set_fixture_adapter(None)
    creg._fetcher = None
    yield
    reset_settings_cache()


@pytest.fixture
def db():
    from app import db as dbmod
    from app.models import Base

    engine = dbmod.init_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    s = dbmod.SessionLocal()
    try:
        yield s
    finally:
        s.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def now():
    return CSUSM_NOW


@pytest.fixture
def csusm_team_ref():
    from app.collectors.base import TeamRef

    return TeamRef("baseball", "csusm", "Cal State San Marcos", "https://csusmcougars.com", "baseball")
