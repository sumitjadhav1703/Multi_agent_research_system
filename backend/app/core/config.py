"""Typed application settings with free-only model validation at startup."""
from __future__ import annotations

import os
import secrets
import socket
from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

RoleName = Literal["planner", "researcher", "verifier", "writer", "eval_judge"]

# Default free-tier LiteLLM model IDs for the student demo.
# Real capability must still be verified before enabling a role in production demos.
# gemini/gemini-2.0-flash was shut down by Google on 2026-06-01. The Milestone 2
# live smoke got HTTP 404 for that id. gemini/gemini-flash-latest is LiteLLM's
# documented alias for the current Gemini Flash route. Milestone 3 did not
# re-run a live call, so this alias is not capability-verified.
# The retired id stays allowlisted so an environment that still names it can boot.
DEFAULT_FREE_ALLOWLIST: tuple[str, ...] = (
    "groq/openai/gpt-oss-20b",
    "gemini/gemini-flash-latest",
    "gemini/gemini-2.0-flash",
    "mistral/mistral-small-latest",
    "openrouter/meta-llama/llama-3.2-3b-instruct:free",
    "mock/free-model",
)

def make_worker_id() -> str:
    """One id per process so two replicas do not share a lease owner."""
    host = socket.gethostname().split(".")[0]
    safe = "".join(char if char.isalnum() or char in "-_" else "-" for char in host)[:24] or "host"
    return f"{safe}-{os.getpid()}-{secrets.token_hex(4)}"


# Explicit denylist patterns that must never appear even if misconfigured.
PAID_MODEL_MARKERS: tuple[str, ...] = (
    "gpt-4",
    "gpt-5",
    "o1-",
    "o3-",
    "claude-opus",
    "claude-sonnet-4",
    "claude-3-5",
    "claude-3.5",
    "command-r-plus",
)


class Settings(BaseSettings):
    """ResearchMind backend settings. Secrets come from the environment only."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = Field(default="development", alias="APP_ENV")
    allow_paid_models: bool = Field(default=False, alias="ALLOW_PAID_MODELS")

    # Provider API keys (optional until a live call is made).
    groq_api_key: str | None = Field(default=None, alias="GROQ_API_KEY")
    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")
    google_api_key: str | None = Field(default=None, alias="GOOGLE_API_KEY")
    mistral_api_key: str | None = Field(default=None, alias="MISTRAL_API_KEY")
    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")
    llama_api_key: str | None = Field(default=None, alias="LLAMA_API_KEY")
    # Meta Model API (https://dev.meta.ai). Preferred for LiteLLM meta/ Muse routes.
    # MODEL_API_KEY / LLAMA_API_KEY remain accepted aliases via resolved_meta_api_key().
    meta_api_key: str | None = Field(default=None, alias="META_API_KEY")
    model_api_key: str | None = Field(default=None, alias="MODEL_API_KEY")
    tavily_api_key: str | None = Field(default=None, alias="TAVILY_API_KEY")
    # Post-chain last resort after free primary+fallback exhaust. Not on FREE_MODEL_ALLOWLIST.
    # None = auto-enable when a Meta key is present.
    meta_last_resort_enabled: bool | None = Field(default=None, alias="META_LAST_RESORT_ENABLED")
    meta_last_resort_model: str = Field(
        default="meta/muse-spark-1.3-contributor",
        alias="META_LAST_RESORT_MODEL",
    )

    free_model_allowlist: str = Field(
        default=",".join(DEFAULT_FREE_ALLOWLIST),
        alias="FREE_MODEL_ALLOWLIST",
    )

    planner_primary_model: str = Field(
        default="groq/openai/gpt-oss-20b", alias="PLANNER_PRIMARY_MODEL"
    )
    planner_fallback_model: str | None = Field(
        default="gemini/gemini-flash-latest", alias="PLANNER_FALLBACK_MODEL"
    )
    research_primary_model: str = Field(
        default="groq/openai/gpt-oss-20b", alias="RESEARCH_PRIMARY_MODEL"
    )
    research_fallback_model: str | None = Field(
        default="gemini/gemini-flash-latest", alias="RESEARCH_FALLBACK_MODEL"
    )
    verifier_primary_model: str = Field(
        default="gemini/gemini-flash-latest", alias="VERIFIER_PRIMARY_MODEL"
    )
    verifier_fallback_model: str | None = Field(
        default="mistral/mistral-small-latest", alias="VERIFIER_FALLBACK_MODEL"
    )
    writer_primary_model: str = Field(
        default="groq/openai/gpt-oss-20b", alias="WRITER_PRIMARY_MODEL"
    )
    writer_fallback_model: str | None = Field(
        default="mistral/mistral-small-latest", alias="WRITER_FALLBACK_MODEL"
    )
    eval_judge_primary_model: str = Field(
        default="gemini/gemini-flash-latest", alias="EVAL_JUDGE_PRIMARY_MODEL"
    )
    eval_judge_fallback_model: str | None = Field(
        default=None, alias="EVAL_JUDGE_FALLBACK_MODEL"
    )

    # Router reliability — keep small; LiteLLM owns retries (underlying SDK retries = 0).
    litellm_num_retries: int = Field(default=0, alias="LITELLM_NUM_RETRIES")
    litellm_request_timeout: float = Field(default=45.0, alias="LITELLM_REQUEST_TIMEOUT")
    litellm_max_fallback_attempts: int = Field(default=1, alias="LITELLM_MAX_FALLBACK_ATTEMPTS")

    use_mock_provider: bool = Field(default=False, alias="USE_MOCK_PROVIDER")

    # Persistence and quotas. Empty DATABASE_URL means the demo has no durable store.
    database_url: str | None = Field(default=None, alias="DATABASE_URL")
    queue_consumer_enabled: bool = Field(default=True, alias="QUEUE_CONSUMER_ENABLED")
    queue_poll_seconds: float = Field(default=0.5, alias="QUEUE_POLL_SECONDS")
    job_lease_seconds: int = Field(default=60, alias="JOB_LEASE_SECONDS")
    job_heartbeat_seconds: int = Field(default=15, alias="JOB_HEARTBEAT_SECONDS")
    job_max_attempts: int = Field(default=3, alias="JOB_MAX_ATTEMPTS")
    global_max_active_runs: int = Field(default=1, alias="GLOBAL_MAX_ACTIVE_RUNS")
    global_daily_run_cap: int = Field(default=3, alias="GLOBAL_DAILY_RUN_CAP")
    max_model_calls_per_run: int = Field(default=12, alias="MAX_MODEL_CALLS_PER_RUN")
    max_run_wall_clock_seconds: int = Field(default=180, alias="MAX_RUN_WALL_CLOCK_SECONDS")
    turnstile_secret_key: str | None = Field(default=None, alias="TURNSTILE_SECRET_KEY")
    turnstile_verify_url: str = Field(
        default="https://challenges.cloudflare.com/turnstile/v0/siteverify",
        alias="TURNSTILE_VERIFY_URL",
    )
    guest_token_ttl_hours: int = Field(default=24 * 14, alias="GUEST_TOKEN_TTL_HOURS")
    # Auto-delete research rows older than this many days (jobs + orphans). Min 1.
    data_retention_enabled: bool = Field(default=True, alias="DATA_RETENTION_ENABLED")
    data_retention_days: int = Field(default=2, alias="DATA_RETENTION_DAYS")
    data_retention_interval_seconds: int = Field(
        default=3600, alias="DATA_RETENTION_INTERVAL_SECONDS"
    )
    data_retention_batch_size: int = Field(default=100, alias="DATA_RETENTION_BATCH_SIZE")
    worker_id: str = Field(default_factory=make_worker_id, alias="WORKER_ID")
    # Exact browser origins, comma-separated. Empty means same-origin only.
    # Never "*": the console sends Authorization, and wildcard credentials are rejected.
    cors_origins: str = Field(default="", alias="CORS_ORIGINS")

    @field_validator(
        "allow_paid_models",
        "use_mock_provider",
        "queue_consumer_enabled",
        "data_retention_enabled",
        mode="before",
    )
    @classmethod
    def _parse_bool(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return value

    @field_validator("meta_last_resort_enabled", mode="before")
    @classmethod
    def _parse_optional_bool(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            return stripped.lower() in {"1", "true", "yes", "on"}
        return value

    @field_validator(
        "database_url",
        "turnstile_secret_key",
        "meta_api_key",
        "model_api_key",
        "llama_api_key",
        mode="before",
    )
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("turnstile_verify_url", mode="before")
    @classmethod
    def _pin_turnstile_verify_url(cls, value: object) -> str:
        # Imported lazily so settings can load without the jobs package cycle.
        from backend.app.jobs.turnstile import OFFICIAL_TURNSTILE_VERIFY_URL, canonical_turnstile_verify_url

        if value is None or (isinstance(value, str) and not value.strip()):
            return OFFICIAL_TURNSTILE_VERIFY_URL
        if not isinstance(value, str):
            raise ValueError("TURNSTILE_VERIFY_URL must be the Cloudflare siteverify URL.")
        return canonical_turnstile_verify_url(value)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _normalize_cors_origins(cls, value: object) -> str:
        if value is None or (isinstance(value, str) and not value.strip()):
            return ""
        if not isinstance(value, str):
            raise ValueError("CORS_ORIGINS must be a comma-separated list of origins.")
        return ",".join(parse_cors_origins(value))

    @field_validator("worker_id", mode="before")
    @classmethod
    def _normalize_worker_id(cls, value: object) -> str:
        if value is None or (isinstance(value, str) and not value.strip()):
            return make_worker_id()
        if not isinstance(value, str):
            raise ValueError("WORKER_ID must be a string.")
        token = value.strip()
        if len(token) > 80 or any(char.isspace() for char in token):
            raise ValueError("WORKER_ID must be one token of at most 80 characters.")
        return token

    @property
    def database_configured(self) -> bool:
        return bool(self.database_url)

    @property
    def cors_origin_list(self) -> list[str]:
        return [part for part in self.cors_origins.split(",") if part]

    @property
    def allowlist(self) -> frozenset[str]:
        items = [part.strip() for part in self.free_model_allowlist.split(",") if part.strip()]
        return frozenset(items)

    def role_models(self) -> dict[RoleName, tuple[str, str | None]]:
        return {
            "planner": (self.planner_primary_model, self.planner_fallback_model),
            "researcher": (self.research_primary_model, self.research_fallback_model),
            "verifier": (self.verifier_primary_model, self.verifier_fallback_model),
            "writer": (self.writer_primary_model, self.writer_fallback_model),
            "eval_judge": (self.eval_judge_primary_model, self.eval_judge_fallback_model),
        }

    def resolved_meta_api_key(self) -> str | None:
        """Preferred META_API_KEY, then MODEL_API_KEY / LLAMA_API_KEY aliases."""
        for candidate in (self.meta_api_key, self.model_api_key, self.llama_api_key):
            if candidate and candidate.strip():
                return candidate.strip()
        return None

    def meta_last_resort_active(self) -> bool:
        """True when last-resort Muse may run after the free chain is exhausted."""
        key = self.resolved_meta_api_key()
        if not key:
            return False
        if self.meta_last_resort_enabled is False:
            return False
        if self.meta_last_resort_enabled is True:
            return True
        # None = auto-enable when a Meta key is present.
        return True

    def configured_model_ids(self) -> list[str]:
        models: list[str] = []
        for primary, fallback in self.role_models().values():
            models.append(primary)
            if fallback:
                models.append(fallback)
        return models

    @model_validator(mode="after")
    def validate_free_only_policy(self) -> Settings:
        if self.allow_paid_models:
            raise ValueError(
                "ALLOW_PAID_MODELS is enabled. ResearchMind demo must keep paid fallback "
                "disabled; set ALLOW_PAID_MODELS=false."
            )
        allow = self.allowlist
        if not allow:
            raise ValueError("FREE_MODEL_ALLOWLIST must contain at least one model ID.")

        for model_id in self.configured_model_ids():
            _assert_model_allowed(model_id, allow)
        last_resort = (self.meta_last_resort_model or "").strip()
        if not last_resort:
            raise ValueError("META_LAST_RESORT_MODEL cannot be empty.")
        if not last_resort.lower().startswith("meta/"):
            raise ValueError(
                "META_LAST_RESORT_MODEL must be a LiteLLM meta/ Muse route "
                f"(got '{last_resort}'). Refusing so a Meta key is never sent elsewhere."
            )
        if self.data_retention_days < 1:
            raise ValueError("DATA_RETENTION_DAYS must be at least 1.")
        if self.data_retention_interval_seconds < 1:
            raise ValueError("DATA_RETENTION_INTERVAL_SECONDS must be at least 1.")
        if self.data_retention_batch_size < 1:
            raise ValueError("DATA_RETENTION_BATCH_SIZE must be at least 1.")
        return self


def parse_cors_origins(raw: str) -> list[str]:
    """Return exact http(s) origins. Reject wildcards, paths, and embedded credentials."""
    origins: list[str] = []
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        if "*" in token:
            raise ValueError(
                "CORS_ORIGINS cannot contain a wildcard. List each frontend origin exactly."
            )
        if token.endswith("/"):
            token = token[:-1]
        parsed = urlsplit(token)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError(
                "CORS_ORIGINS entries must be http or https origins, such as https://console.example."
            )
        if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            raise ValueError(
                "CORS_ORIGINS entries must be origins without userinfo, paths, or queries."
            )
        host = parsed.hostname
        if ":" in host:
            host = f"[{host}]"
        port = parsed.port
        if (parsed.scheme == "https" and port == 443) or (parsed.scheme == "http" and port == 80):
            port = None
        suffix = f":{port}" if port else ""
        origin = f"{parsed.scheme}://{host}{suffix}"
        if origin not in origins:
            origins.append(origin)
    return origins


def _assert_model_allowed(model_id: str, allowlist: frozenset[str]) -> None:
    lowered = model_id.lower().strip()
    if not lowered:
        raise ValueError("Model ID cannot be empty.")
    for marker in PAID_MODEL_MARKERS:
        if marker in lowered:
            raise ValueError(
                f"Model '{model_id}' matches paid marker '{marker}'. "
                "Paid models are not allowed in the demo profile."
            )
    if model_id not in allowlist:
        raise ValueError(
            f"Model '{model_id}' is not in FREE_MODEL_ALLOWLIST. "
            "Only explicitly allowlisted free deployments may be configured."
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
