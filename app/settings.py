"""Application settings, loaded from environment variables / .env.

Secrets (bot token, API keys, DB password) are only ever read from the
environment. Nothing here is sent to the browser.
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SPORT_KEYS = (
    "baseball",
    "football",
    "softball",
    "mens_basketball",
    "womens_basketball",
    "mens_soccer",
    "womens_soccer",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- modes -------------------------------------------------------------
    test_mode: bool = Field(True, alias="TEST_MODE")
    dry_run: bool = Field(False, alias="DRY_RUN")

    # --- core --------------------------------------------------------------
    database_url: str = Field("sqlite:///./roster_intel.db", alias="DATABASE_URL")
    app_timezone: str = Field("America/Los_Angeles", alias="APP_TIMEZONE")
    public_base_url: str = Field("http://localhost:8000", alias="PUBLIC_BASE_URL")

    # --- admin -------------------------------------------------------------
    admin_username: str = Field("admin", alias="ADMIN_USERNAME")
    admin_password: str = Field("", alias="ADMIN_PASSWORD")

    # --- telegram ----------------------------------------------------------
    telegram_bot_token: str = Field("", alias="TELEGRAM_BOT_TOKEN")
    telegram_api_base: str = Field("https://api.telegram.org", alias="TELEGRAM_API_BASE")
    # private admin chat: new items arrive there with Approve / Reject buttons (optional)
    telegram_admin_chat_id: str = Field("", alias="TELEGRAM_ADMIN_CHAT_ID")
    telegram_admin_user_ids: str = Field("", alias="TELEGRAM_ADMIN_USER_IDS")  # comma separated; default = chat id
    telegram_webhook_secret: str = Field("", alias="TELEGRAM_WEBHOOK_SECRET")

    # --- LLM (optional) ----------------------------------------------------
    anthropic_api_key: str = Field("", alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field("claude-opus-5", alias="ANTHROPIC_MODEL")
    llm_enabled: bool = Field(False, alias="LLM_ENABLED")

    # --- collection --------------------------------------------------------
    crawler_user_agent: str = Field(
        "TAMRosterIntelBot/0.1 (+https://theathletemarket.com; roster research)",
        alias="CRAWLER_USER_AGENT",
    )
    crawler_min_delay_seconds: float = Field(10.0, alias="CRAWLER_MIN_DELAY_SECONDS")
    cache_dir: str = Field("./.cache/http", alias="CACHE_DIR")
    cache_ttl_hours: float = Field(12.0, alias="CACHE_TTL_HOURS")

    # --- publishing / freshness -------------------------------------------
    publish_times: str = Field(
        "baseball=09:00,football=09:15,softball=09:30,mens_basketball=09:45,"
        "womens_basketball=10:00,mens_soccer=10:15,womens_soccer=10:30",
        alias="PUBLISH_TIMES",
    )
    research_cron_hour: int = Field(3, alias="RESEARCH_CRON_HOUR")
    revalidate_after_hours: float = Field(48.0, alias="REVALIDATE_AFTER_HOURS")
    opportunity_ttl_days: int = Field(21, alias="OPPORTUNITY_TTL_DAYS")
    enable_scheduler: bool = Field(False, alias="ENABLE_SCHEDULER")
    # AUTO_APPROVE=true: pending items approve themselves before each daily post if they pass the same
    # rules as a human approval (guardrails, not LOW confidence, not expired). Rejected items stay rejected.
    auto_approve: bool = Field(False, alias="AUTO_APPROVE")
    telegram_join_links: str = Field("", alias="TELEGRAM_JOIN_LINKS")  # baseball=https://t.me/...

    @field_validator("*", mode="before")
    @classmethod
    def _strip_text(cls, v):
        # secrets pasted into GitHub/Render often carry a stray newline or space
        return v.strip() if isinstance(v, str) else v

    @field_validator("app_timezone")
    @classmethod
    def _valid_tz(cls, v: str) -> str:
        ZoneInfo(v)  # raises if invalid
        return v

    # ---------------------------------------------------------------------
    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.app_timezone)

    @property
    def publishing_disabled(self) -> bool:
        """True when nothing may be sent to real Telegram channels."""
        return self.test_mode or self.dry_run

    def publish_time_for(self, sport: str) -> tuple[int, int] | None:
        for part in self.publish_times.split(","):
            if "=" not in part:
                continue
            k, v = part.split("=", 1)
            if k.strip() == sport:
                hh, mm = v.strip().split(":")
                return int(hh), int(mm)
        return None

    def join_link_for(self, sport: str) -> str:
        for part in self.telegram_join_links.split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                if k.strip() == sport:
                    return v.strip()
        return ""

    @property
    def admin_user_ids(self) -> set[int]:
        """Telegram user ids allowed to press Approve/Reject. A private chat's id is the user's id."""
        raw = self.telegram_admin_user_ids or self.telegram_admin_chat_id
        return {int(x) for x in raw.replace(" ", "").split(",") if x.lstrip("-").isdigit() and int(x) > 0}

    @staticmethod
    def channel_env_var(sport: str) -> str:
        short = {
            "mens_basketball": "MBB",
            "womens_basketball": "WBB",
            "mens_soccer": "MSOC",
            "womens_soccer": "WSOC",
        }.get(sport, sport.upper())
        return f"TELEGRAM_{short}_CHANNEL_ID"

    def channel_id_for(self, sport: str) -> str:
        # read at call time so the value never needs to live in code or DB
        return normalize_chat_id(os.environ.get(self.channel_env_var(sport), ""))


def normalize_chat_id(raw: str) -> str:
    """Accept what people paste: '@name', 'name', 't.me/name', 'https://t.me/name' -> '@name';
    numeric ids ('-100123...') unchanged. Private invite links ('t.me/+abc') can't be used as ids."""
    v = (raw or "").strip()
    m = re.match(r"^(?:https?://)?(?:www\.)?(?:t|telegram)\.me/(.+?)/?$", v, re.I)
    if m:
        v = m.group(1)
        if v.startswith(("+", "joinchat/")):
            return v and "invite-link:" + v  # not usable; check-telegram explains
    if re.fullmatch(r"-?\d+", v):
        return v
    if re.fullmatch(r"@?[A-Za-z][A-Za-z0-9_]{3,}", v):
        return v if v.startswith("@") else "@" + v
    return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
