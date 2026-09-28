"""Minimal Telegram Bot API client (server-side only; the token never leaves the backend)."""
from __future__ import annotations

import httpx

from app.settings import get_settings


class TelegramError(Exception):
    def __init__(self, msg: str, ambiguous: bool = False):
        super().__init__(msg)
        # ambiguous=True: the request may have reached Telegram (network drop), so we
        # must NOT assume it wasn't sent.
        self.ambiguous = ambiguous


class TelegramClient:
    def __init__(self, token: str | None = None, api_base: str | None = None, http: httpx.Client | None = None):
        s = get_settings()
        self.token = token if token is not None else s.telegram_bot_token
        self.api_base = (api_base or s.telegram_api_base).rstrip("/")
        self.http = http or httpx.Client(timeout=20.0)

    def _call(self, method: str, payload: dict) -> dict:
        if not self.token:
            raise TelegramError("TELEGRAM_BOT_TOKEN is not set")
        url = f"{self.api_base}/bot{self.token}/{method}"
        try:
            r = self.http.post(url, json=payload)
        except httpx.HTTPError as e:
            raise TelegramError(f"network error calling {method}: {type(e).__name__}",
                                ambiguous=not isinstance(e, httpx.ConnectError)) from e
        try:
            data = r.json()
        except ValueError as e:
            raise TelegramError(f"{method}: non-JSON response (HTTP {r.status_code})") from e
        if not data.get("ok"):
            raise TelegramError(f"{method} failed: {data.get('description', 'unknown error')}")
        return data["result"]

    def get_me(self) -> dict:
        return self._call("getMe", {})

    def get_chat(self, chat_id: str) -> dict:
        return self._call("getChat", {"chat_id": chat_id})

    def get_my_member_status(self, chat_id: str) -> dict:
        me = self.get_me()
        return self._call("getChatMember", {"chat_id": chat_id, "user_id": me["id"]})

    def send_message(self, chat_id: str, text: str) -> int:
        result = self._call("sendMessage", {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        })
        return int(result["message_id"])
