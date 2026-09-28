"""Telegram webhook for the private admin chat (button presses arrive here instantly).

Telegram sends each update with the secret we registered (header X-Telegram-Bot-Api-Secret-Token).
Without TELEGRAM_WEBHOOK_SECRET set, the endpoint doesn't exist (404).
Register it once with: python -m app.cli telegram-webhook --set
"""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Header, HTTPException, Request

from app.db import session_scope
from app.logging_setup import record_event
from app.publishing import admin_bot
from app.settings import get_settings

router = APIRouter()


@router.post("/telegram/webhook", include_in_schema=False)
async def telegram_webhook(request: Request,
                           x_telegram_bot_api_secret_token: str = Header(default="")):
    expected = get_settings().telegram_webhook_secret
    if not expected:
        raise HTTPException(404)
    if not secrets.compare_digest(x_telegram_bot_api_secret_token.encode(), expected.encode()):
        raise HTTPException(403)
    update = await request.json()
    try:
        with session_scope() as s:
            admin_bot.handle_update(s, update)
    except Exception as e:  # noqa: BLE001 - always 200 so Telegram doesn't retry a bad update forever
        record_event(None, "telegram_failed", f"admin update failed: {type(e).__name__}: {e}", level="ERROR")
    return {"ok": True}
