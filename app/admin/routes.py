"""Admin dashboard (server-rendered). Protected by HTTP Basic auth + CSRF token."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterator

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.content.guardrails import check_telegram, check_x, school_names, x_length
from app.db import SessionLocal
from app.models import EventLog, Opportunity, PublishedPost, PublishingQueue, School, ScoreHistory, Status, Team
from app.pipeline import workflow
from app.pipeline.opportunities import create_verified_need
from app.pipeline.revalidate import revalidate
from app.publishing.queue import rank_candidates
from app.publishing.service import current_mode, local_today, publish_daily, publish_opportunity
from app.settings import get_settings
from app.sports.registry import registry

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
security = HTTPBasic()


# ------------------------------------------------------------------ deps
def get_db() -> Iterator[Session]:
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def require_admin(creds: HTTPBasicCredentials = Depends(security)) -> str:
    s = get_settings()
    if not s.admin_password:
        raise HTTPException(503, "Set ADMIN_PASSWORD in .env to use the dashboard.")
    ok_user = secrets.compare_digest(creds.username.encode(), s.admin_username.encode())
    ok_pass = secrets.compare_digest(creds.password.encode(), s.admin_password.encode())
    if not (ok_user and ok_pass):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unauthorized", headers={"WWW-Authenticate": "Basic"})
    return creds.username


def csrf_token() -> str:
    key = get_settings().admin_password.encode() or b"x"
    return hmac.new(key, b"roster-intel-csrf", hashlib.sha256).hexdigest()[:40]


def check_csrf(csrf: str = Form(...)) -> None:
    if not secrets.compare_digest(csrf, csrf_token()):
        raise HTTPException(403, "Bad CSRF token — reload the page and try again.")


# ------------------------------------------------------------------ helpers
def telegram_preview(text: str) -> Markup:
    """Render Telegram HTML subset for preview. Only whitelisted tags survive."""
    out, pos = [], 0
    src = text or ""
    for m in re.finditer(r"<[^>]*>", src):
        out.append(src[pos:m.start()].replace("<", "&lt;").replace(">", "&gt;"))
        tag = m.group(0)
        if re.fullmatch(r"</?(b|i|u|s|code|pre|blockquote)>|</a>", tag):
            out.append(tag)
        elif (a := re.fullmatch(r'<a href="(https?://[^"<>\s]+)">', tag)):
            out.append(f'<a href="{a.group(1)}" target="_blank" rel="noopener noreferrer">')
        else:
            out.append(tag.replace("<", "&lt;").replace(">", "&gt;"))
        pos = m.end()
    out.append(src[pos:].replace("<", "&lt;").replace(">", "&gt;"))
    return Markup("".join(out).replace("\n", "<br>"))


def _ctx(request: Request, **kw):
    s = get_settings()
    return {"request": request, "csrf": csrf_token(), "mode": current_mode(), "sports": registry(),
            "tz": s.app_timezone, "now": datetime.now(timezone.utc).astimezone(s.tz), **kw}


def _redirect(url: str, msg: str | None = None, err: str | None = None) -> RedirectResponse:
    from urllib.parse import quote

    q = []
    if msg:
        q.append("msg=" + quote(msg))
    if err:
        q.append("err=" + quote(err))
    sep = "&" if "?" in url else "?"
    return RedirectResponse(url + (sep + "&".join(q) if q else ""), status_code=303)


def _check_sport(sport: str) -> str:
    if sport not in registry():
        raise HTTPException(404, f"unknown sport '{sport}'")
    return sport


def _opp(db: Session, opp_id: int) -> Opportunity:
    o = db.get(Opportunity, opp_id)
    if o is None:
        raise HTTPException(404, "opportunity not found")
    return o


# ------------------------------------------------------------------ pages
@router.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/admin", status_code=303)


@router.get("/admin", response_class=HTMLResponse)
def list_view(request: Request, status_: str = "pending", sport: str = "baseball", db: Session = Depends(get_db),
              _: str = Depends(require_admin)):
    _check_sport(sport)
    status_ = request.query_params.get("status", status_)
    if status_ not in Status.ALL:
        status_ = Status.PENDING
    counts = dict(db.execute(select(Opportunity.status, func.count()).where(Opportunity.sport == sport)
                             .group_by(Opportunity.status)).all())
    opps = db.scalars(select(Opportunity).where(Opportunity.sport == sport, Opportunity.status == status_)
                      .order_by(Opportunity.signal.desc(), Opportunity.id)).all()
    return templates.TemplateResponse(request, "list.html", _ctx(
        request, opps=opps, status=status_, sport=sport, counts=counts, statuses=Status.ALL,
        msg=request.query_params.get("msg"), err=request.query_params.get("err")))


@router.get("/admin/opp/{opp_id}", response_class=HTMLResponse)
def detail_view(request: Request, opp_id: int, db: Session = Depends(get_db), _: str = Depends(require_admin)):
    o = _opp(db, opp_id)
    g = check_telegram(o.telegram_text or "", o.opportunity_type)
    gx = check_x(o.x_teaser or "", o.opportunity_type, school_names(o.school))
    history = db.scalars(select(ScoreHistory).where(ScoreHistory.opportunity_id == o.id)
                         .order_by(ScoreHistory.at.desc())).all()
    posts = db.scalars(select(PublishedPost).where(PublishedPost.opportunity_id == o.id)).all()
    summary = next((e for e in o.evidence if e.kind == "summary"), None)
    return templates.TemplateResponse(request, "detail.html", _ctx(
        request, o=o, g=g, gx=gx, x_len=x_length(o.x_teaser or ""), preview=telegram_preview(o.telegram_text or ""),
        history=history, posts=posts, summary=summary, players=[e for e in o.evidence if e.kind == "player"],
        statements=[e for e in o.evidence if e.kind == "statement"], today=local_today(),
        msg=request.query_params.get("msg"), err=request.query_params.get("err")))


# ------------------------------------------------------------------ actions
@router.post("/admin/opp/{opp_id}/approve")
def approve_action(opp_id: int, override: str | None = Form(None), db: Session = Depends(get_db),
                   _: str = Depends(require_admin), __: None = Depends(check_csrf)):
    o = _opp(db, opp_id)
    try:
        workflow.approve(db, o, override_low_confidence=bool(override))
    except workflow.WorkflowError as e:
        return _redirect(f"/admin/opp/{opp_id}", err=str(e))
    return _redirect(f"/admin/opp/{opp_id}", msg="Approved.")


@router.post("/admin/opp/{opp_id}/reject")
def reject_action(opp_id: int, note: str = Form(""), db: Session = Depends(get_db),
                  _: str = Depends(require_admin), __: None = Depends(check_csrf)):
    o = _opp(db, opp_id)
    try:
        workflow.reject(db, o, note)
    except workflow.WorkflowError as e:
        return _redirect(f"/admin/opp/{opp_id}", err=str(e))
    return _redirect(f"/admin?status=pending&sport={o.sport}", msg=f"Rejected #{opp_id}.")


@router.post("/admin/opp/{opp_id}/edit")
def edit_action(opp_id: int, telegram_text: str = Form(...), x_teaser: str = Form(""),
                db: Session = Depends(get_db), _: str = Depends(require_admin), __: None = Depends(check_csrf)):
    o = _opp(db, opp_id)
    try:
        problems = workflow.edit_copy(db, o, telegram_text, x_teaser)
    except workflow.WorkflowError as e:
        return _redirect(f"/admin/opp/{opp_id}", err=str(e))
    if problems:
        return _redirect(f"/admin/opp/{opp_id}", err="Saved, but blocked until fixed: " + "; ".join(problems))
    return _redirect(f"/admin/opp/{opp_id}", msg="Copy saved.")


@router.post("/admin/opp/{opp_id}/reanalyze")
def reanalyze_action(opp_id: int, db: Session = Depends(get_db), _: str = Depends(require_admin),
                     __: None = Depends(check_csrf)):
    o = _opp(db, opp_id)
    res = revalidate(db, o, force=True)
    db.commit()
    if res.outcome == "blocked":
        return _redirect(f"/admin/opp/{opp_id}", err="Reanalyze failed: " + res.message)
    return _redirect(f"/admin/opp/{opp_id}", msg=f"Reanalyzed: {res.message}")


@router.post("/admin/opp/{opp_id}/publish")
def publish_now_action(opp_id: int, db: Session = Depends(get_db), _: str = Depends(require_admin),
                       __: None = Depends(check_csrf)):
    o = _opp(db, opp_id)
    out = publish_opportunity(db, o)
    db.commit()
    if not out.ok:
        return _redirect(f"/admin/opp/{opp_id}", err=f"Not published ({out.status}): {out.message}")
    return _redirect(f"/admin/opp/{opp_id}", msg=f"Done — {out.message}.")


@router.post("/admin/opp/{opp_id}/schedule")
def schedule_action(opp_id: int, day: str = Form(...), db: Session = Depends(get_db),
                    _: str = Depends(require_admin), __: None = Depends(check_csrf)):
    o = _opp(db, opp_id)
    try:
        d = date.fromisoformat(day)
        if d < local_today():
            raise workflow.WorkflowError("date is in the past")
        workflow.schedule(db, o, d)
    except (ValueError, workflow.WorkflowError) as e:
        return _redirect(f"/admin/opp/{opp_id}", err=str(e))
    return _redirect(f"/admin/opp/{opp_id}", msg=f"Scheduled for {d}.")


@router.post("/admin/opp/{opp_id}/unschedule")
def unschedule_action(opp_id: int, db: Session = Depends(get_db), _: str = Depends(require_admin),
                      __: None = Depends(check_csrf)):
    o = _opp(db, opp_id)
    workflow.unschedule(db, o)
    return _redirect(f"/admin/opp/{opp_id}", msg="Unscheduled (back to approved).")


# ------------------------------------------------------------------ queue / events / research
@router.get("/admin/queue", response_class=HTMLResponse)
def queue_view(request: Request, sport: str = "baseball", db: Session = Depends(get_db),
               _: str = Depends(require_admin)):
    _check_sport(sport)
    rows = db.scalars(select(PublishingQueue).where(PublishingQueue.sport == sport)
                      .order_by(PublishingQueue.publish_date.desc()).limit(60)).all()
    ranked = rank_candidates(db, sport, local_today())
    s = get_settings()
    return templates.TemplateResponse(request, "queue.html", _ctx(
        request, rows=rows, ranked=ranked, sport=sport, publish_time=s.publish_time_for(sport),
        channel_set=bool(s.channel_id_for(sport)), channel_var=s.channel_env_var(sport),
        msg=request.query_params.get("msg"), err=request.query_params.get("err")))


@router.post("/admin/queue/publish-daily")
def publish_daily_action(sport: str = Form(...), db: Session = Depends(get_db), _: str = Depends(require_admin),
                         __: None = Depends(check_csrf)):
    _check_sport(sport)
    out = publish_daily(db, sport)
    db.commit()
    return _redirect(f"/admin/queue?sport={sport}", **({"msg": out.message} if out.ok else {"err": out.message}))


@router.get("/admin/events", response_class=HTMLResponse)
def events_view(request: Request, level: str = "", db: Session = Depends(get_db), _: str = Depends(require_admin)):
    q = select(EventLog).order_by(EventLog.id.desc()).limit(300)
    if level:
        q = q.where(EventLog.level == level)
    return templates.TemplateResponse(request, "events.html", _ctx(request, events=db.scalars(q).all(), level=level))


def _run_research_bg(sport: str) -> None:
    from app.pipeline.research import run_research

    s = SessionLocal()
    try:
        run_research(s, sport)
        workflow.expire_stale(s)
        s.commit()
    finally:
        s.close()


@router.post("/admin/research/run")
def research_action(background: BackgroundTasks, sport: str = Form("baseball"), _: str = Depends(require_admin),
                    __: None = Depends(check_csrf)):
    _check_sport(sport)
    background.add_task(_run_research_bg, sport)
    return _redirect(f"/admin?sport={sport}", msg="Research started in the background (sites are crawled "
                                                  "slowly on purpose). Refresh in a few minutes; see Events.")


@router.get("/admin/verified/new", response_class=HTMLResponse)
def verified_form(request: Request, sport: str = "baseball", db: Session = Depends(get_db),
                  _: str = Depends(require_admin)):
    _check_sport(sport)
    teams = db.scalars(select(Team).join(School).where(Team.sport == sport).order_by(School.name)).all()
    cfg = registry()[sport]
    return templates.TemplateResponse(request, "verified_new.html", _ctx(
        request, teams=teams, sport=sport, positions=cfg.positions, err=request.query_params.get("err")))


@router.post("/admin/verified/new")
def verified_create(team_id: int = Form(...), position_group: str = Form(...), target_season: str = Form(...),
                    summary: str = Form(...), quote: str = Form(...), source_url: str = Form(...),
                    source_label: str = Form(...), tier: str = Form(...), publisher: str = Form(""),
                    author_account: str = Form(""), db: Session = Depends(get_db), _: str = Depends(require_admin),
                    __: None = Depends(check_csrf)):
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(404)
    cfg = registry()[team.sport]
    try:
        spec = cfg.position(position_group)
        opp = create_verified_need(db, team, position_group=spec.key, position_label=spec.label,
                                   target_season=target_season, summary=summary, source_url=source_url,
                                   source_label=source_label, tier=tier, publisher=publisher or None,
                                   author_account=author_account or None, quote=quote)
    except (ValueError, KeyError) as e:
        return _redirect(f"/admin/verified/new?sport={team.sport}", err=str(e))
    db.flush()
    return _redirect(f"/admin/opp/{opp.id}", msg="Verified need created (pending approval).")
