"""Settings loaded from environment variables (optionally from a local ``.env``).

All paths are resolved to absolute paths here, so nothing depends on the
current working directory.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_DB_PATH = Path.home() / ".clinicdesk" / "clinicdesk.db"
PROVIDERS = ("offline", "openai")


class ConfigError(ValueError):
    """Raised when the environment holds an invalid or incomplete configuration."""


def _int_env(env: dict[str, str], name: str, default: int, minimum: int = 0) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc
    if value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}, got {value}")
    return value


@dataclass(frozen=True)
class Settings:
    db_path: Path = DEFAULT_DB_PATH
    timezone: str = "UTC"
    llm_provider: str = "offline"
    llm_model: str = "gpt-4o-mini"
    llm_base_url: str | None = None
    openai_api_key: str | None = field(default=None, repr=False)
    max_tool_steps: int = 4
    max_active_bookings: int = 3
    emergency_number: str = "911"
    seed: int = 7
    seed_days: int = 14

    @property
    def tz(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ConfigError(f"Unknown time zone {self.timezone!r}") from exc

    def clinic_now(self) -> datetime:
        """Current wall-clock time in the clinic's time zone, as a naive datetime."""
        return datetime.now(self.tz).replace(tzinfo=None, second=0, microsecond=0)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = dict(os.environ if env is None else env)
        provider = env.get("CLINICDESK_LLM_PROVIDER", "offline").strip().lower() or "offline"
        if provider not in PROVIDERS:
            raise ConfigError(f"CLINICDESK_LLM_PROVIDER must be one of {PROVIDERS}, got {provider!r}")
        raw_path = env.get("CLINICDESK_DB_PATH", "").strip()
        db_path = Path(raw_path).expanduser().resolve() if raw_path else DEFAULT_DB_PATH
        settings = cls(
            db_path=db_path,
            timezone=env.get("CLINICDESK_TIMEZONE", "UTC").strip() or "UTC",
            llm_provider=provider,
            llm_model=env.get("CLINICDESK_LLM_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
            llm_base_url=env.get("CLINICDESK_LLM_BASE_URL", "").strip() or None,
            openai_api_key=env.get("OPENAI_API_KEY", "").strip() or None,
            max_tool_steps=_int_env(env, "CLINICDESK_MAX_TOOL_STEPS", 4, minimum=1),
            max_active_bookings=_int_env(env, "CLINICDESK_MAX_ACTIVE_BOOKINGS", 3, minimum=1),
            emergency_number=env.get("CLINICDESK_EMERGENCY_NUMBER", "911").strip() or "911",
            seed=_int_env(env, "CLINICDESK_SEED", 7),
            seed_days=_int_env(env, "CLINICDESK_SEED_DAYS", 14, minimum=1),
        )
        settings.tz  # validate early
        if settings.llm_provider == "openai" and not settings.openai_api_key and not settings.llm_base_url:
            raise ConfigError("CLINICDESK_LLM_PROVIDER=openai needs OPENAI_API_KEY (or CLINICDESK_LLM_BASE_URL "
                              "for a local OpenAI-compatible server)")
        return settings


def load_dotenv_if_present(path: Path | None = None) -> None:
    """Load ``.env`` with python-dotenv when it is installed; silently skip otherwise."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(dotenv_path=path, override=False)
