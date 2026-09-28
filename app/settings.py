"""Application settings, loaded from environment variables / .env.

Secrets (bot token, API keys, DB password) are only ever read from the
environment. Nothing here is sent to the browser.
"""
from __future__ import annotations

import os
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
    telegram_join_links: str = Field("", alias="TELEGRAM_JOIN_LINKS")  # baseball=https://t.me/...

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
        return os.environ.get(self.channel_env_var(sport), "").strip()


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
