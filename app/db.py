from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base
from app.settings import get_settings

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def _normalize_url(url: str) -> str:
    # Supabase gives postgres:// or postgresql:// URLs; use the psycopg3 driver.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def init_engine(url: str | None = None) -> Engine:
    global _engine, _SessionLocal
    url = _normalize_url(url or get_settings().database_url)
    kwargs = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    _engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(_engine, "connect")
        def _fk_on(dbapi_conn, _):  # enforce FKs in sqlite like Postgres
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def get_engine() -> Engine:
    return _engine or init_engine()


def create_all() -> None:
    Base.metadata.create_all(get_engine())


def SessionLocal() -> Session:
    if _SessionLocal is None:
        init_engine()
    return _SessionLocal()  # type: ignore[misc]


@contextmanager
def session_scope() -> Iterator[Session]:
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
