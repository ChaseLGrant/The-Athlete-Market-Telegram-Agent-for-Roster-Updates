"""FastAPI app: admin dashboard + (optional) in-process scheduler.

Run locally:  uvicorn app.main:app --reload
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()  # make TELEGRAM_*_CHANNEL_ID etc. visible via os.environ

from fastapi import FastAPI  # noqa: E402

from app.admin.routes import router  # noqa: E402
from app.publishing.webhook import router as telegram_router  # noqa: E402
from app.db import create_all, session_scope  # noqa: E402
from app.logging_setup import configure_logging, log  # noqa: E402
from app.pipeline.research import ensure_channels  # noqa: E402
from app.settings import get_settings  # noqa: E402


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    create_all()
    with session_scope() as s:
        ensure_channels(s)
    sched = None
    if get_settings().enable_scheduler:
        from app.scheduler import start_scheduler

        sched = start_scheduler()
    log.info("mode=%s", "TEST" if get_settings().test_mode else "DRY_RUN" if get_settings().dry_run else "LIVE")
    yield
    if sched:
        sched.shutdown(wait=False)


app = FastAPI(title="TAM Roster Intelligence", lifespan=lifespan, docs_url=None, redoc_url=None)
app.include_router(router)
app.include_router(telegram_router)


@app.get("/healthz")
def healthz():
    return {"ok": True}
