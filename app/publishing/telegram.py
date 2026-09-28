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

    def send_message(self, chat_id: str, text: str, reply_markup: dict | None = None) -> int:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        result = self._call("sendMessage", payload)
        return int(result["message_id"])

    # --- used by the private admin chat (app/publishing/admin_bot.py) ---------------
    def answer_callback(self, callback_id: str, text: str) -> None:
        self._call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:200]})

    def edit_reply_markup(self, chat_id, message_id: int, reply_markup: dict | None) -> None:
        self._call("editMessageReplyMarkup", {"chat_id": chat_id, "message_id": message_id,
                                              "reply_markup": reply_markup or {"inline_keyboard": []}})

    def get_updates(self, offset: int | None = None, timeout: int = 0) -> list[dict]:
        payload: dict = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            payload["offset"] = offset
        return self._call("getUpdates", payload)

    def set_webhook(self, url: str, secret_token: str) -> None:
        self._call("setWebhook", {"url": url, "secret_token": secret_token,
                                  "allowed_updates": ["message", "callback_query"]})

    def delete_webhook(self) -> None:
        self._call("deleteWebhook", {})
