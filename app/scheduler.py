"""In-process scheduler (APScheduler). Enable with ENABLE_SCHEDULER=true.

Alternative for cheap hosting: disable this and have any cron call
`python -m app.cli research` and `python -m app.cli publish-daily --sport baseball`.
"""
from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db import SessionLocal
from app.logging_setup import record_event
from app.pipeline import workflow
from app.publishing.service import publish_daily
from app.settings import get_settings
from app.sports.registry import registry


def _research_job() -> None:
    from app.pipeline.research import run_research

    s = SessionLocal()
    try:
        for key, cfg in registry().items():
            if cfg.implemented:
                run_research(s, key)
        workflow.expire_stale(s)
        s.commit()
    except Exception as e:  # noqa: BLE001
        s.rollback()
        record_event(s, "research_error", f"scheduled research failed: {e}", level="ERROR")
        s.commit()
    finally:
        s.close()


def _publish_job(sport: str) -> None:
    s = SessionLocal()
    try:
        workflow.expire_stale(s)
        out = publish_daily(s, sport)
        s.commit()
        record_event(s, "daily_publish", f"{sport}: {out.status} — {out.message}", sport=sport)
        s.commit()
    except Exception as e:  # noqa: BLE001
        s.rollback()
        record_event(s, "telegram_failed", f"scheduled publish crashed for {sport}: {e}", level="ERROR", sport=sport)
        s.commit()
    finally:
        s.close()


def start_scheduler() -> BackgroundScheduler:
    st = get_settings()
    sched = BackgroundScheduler(timezone=st.tz)
    sched.add_job(_research_job, CronTrigger(hour=st.research_cron_hour, minute=7, timezone=st.tz),
                  id="research", max_instances=1, coalesce=True)
    for key, cfg in registry().items():
        t = st.publish_time_for(key)
        if t and cfg.implemented:
            sched.add_job(_publish_job, CronTrigger(hour=t[0], minute=t[1], timezone=st.tz), args=[key],
                          id=f"publish-{key}", max_instances=1, coalesce=True)
    sched.start()
    return sched
