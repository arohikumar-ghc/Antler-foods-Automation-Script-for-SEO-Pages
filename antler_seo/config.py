"""
Configuration for the Antler Foods SEO automation.

Configuration is loaded from environment variables (optionally seeded from a
local ``.env`` file). Credentials are never hard-coded and no secret value has a
default in source code. Missing or invalid configuration produces a clear,
friendly error via :class:`ConfigError`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping, Optional

try:
    # python-dotenv is optional at import time; only used when loading .env.
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - exercised only when dependency missing
    load_dotenv = None  # type: ignore[assignment]


# Environment variable names (single source of truth).
ENV_EMAIL = "ANTLER_EMAIL"
ENV_PASSWORD = "ANTLER_PASSWORD"
ENV_BASE_URL = "ANTLER_BASE_URL"
ENV_HEADLESS = "ANTLER_HEADLESS"
ENV_TIMEOUT = "ANTLER_TIMEOUT"
ENV_SLOW_MO = "ANTLER_SLOW_MO"
ENV_SEO_DIR = "ANTLER_SEO_DIR"
ENV_LOGS_DIR = "ANTLER_LOGS_DIR"

# Cloud input (Google) — optional; only needed for the Google Sheet/Doc source.
ENV_GOOGLE_SA_KEY_FILE = "ANTLER_GOOGLE_SA_KEY_FILE"
ENV_GOOGLE_SHEET_URL = "ANTLER_GOOGLE_SHEET_URL"

# Required variables (no defaults; must be supplied by the environment).
REQUIRED_VARS = (ENV_EMAIL, ENV_PASSWORD, ENV_BASE_URL)

# Defaults for non-secret runtime settings only.
DEFAULT_HEADLESS = False
DEFAULT_TIMEOUT_MS = 30000
DEFAULT_SLOW_MO_MS = 100
DEFAULT_SEO_DIR = "seo_files"
DEFAULT_LOGS_DIR = "logs"

MIN_TIMEOUT_MS = 1000


class ConfigError(Exception):
    """Raised when configuration is missing or invalid."""


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_int(name: str, value: str) -> int:
    try:
        return int(value.strip())
    except (TypeError, ValueError):
        raise ConfigError(
            f"{name} must be an integer, got: {value!r}"
        )


@dataclass
class Config:
    """Runtime configuration for the automation.

    Attributes:
        email: Antler CMS login email (required, from env).
        password: Antler CMS login password (required, from env).
        base_url: Antler CMS base URL (required, from env — not invented here).
        headless: Whether the browser runs headless.
        timeout_ms: Default Playwright action/navigation timeout in ms.
        slow_mo_ms: Delay between Playwright operations in ms (debugging aid).
        seo_files_dir: Directory holding local SEO input documents.
        logs_dir: Directory for log files.
        google_sa_key_file: Path to a Google service-account JSON key (optional;
            only needed for the Google Sheet/Doc cloud input source).
        google_sheet_url: URL (or id) of the control-panel Google Sheet
            (optional; only needed for the cloud input source).
    """

    email: str
    password: str
    base_url: str
    headless: bool = DEFAULT_HEADLESS
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    slow_mo_ms: int = DEFAULT_SLOW_MO_MS
    seo_files_dir: str = DEFAULT_SEO_DIR
    logs_dir: str = DEFAULT_LOGS_DIR
    google_sa_key_file: Optional[str] = None
    google_sheet_url: Optional[str] = None

    @classmethod
    def from_env(
        cls,
        env: Optional[Mapping[str, str]] = None,
        load_env_file: bool = True,
    ) -> "Config":
        """Build a :class:`Config` from environment variables.

        Args:
            env: Optional explicit mapping to read from (defaults to
                ``os.environ``). Primarily used for testing.
            load_env_file: When True and reading from ``os.environ``, load a
                local ``.env`` file first (if python-dotenv is available).

        Returns:
            A populated, structurally-valid :class:`Config`.

        Raises:
            ConfigError: If any required variable is missing/empty, or if a
                numeric/boolean value cannot be parsed, or if a value is out of
                range.
        """
        if env is None:
            if load_env_file and load_dotenv is not None:
                load_dotenv()
            env = os.environ

        missing = [
            name
            for name in REQUIRED_VARS
            if not (env.get(name) or "").strip()
        ]
        if missing:
            raise ConfigError(
                "Missing required configuration: "
                + ", ".join(missing)
                + ".\nSet these environment variables (see .env.example):\n"
                + "\n".join(f"  - {name}" for name in missing)
            )

        headless = (
            _parse_bool(env[ENV_HEADLESS])
            if (env.get(ENV_HEADLESS) or "").strip()
            else DEFAULT_HEADLESS
        )
        timeout_ms = (
            _parse_int(ENV_TIMEOUT, env[ENV_TIMEOUT])
            if (env.get(ENV_TIMEOUT) or "").strip()
            else DEFAULT_TIMEOUT_MS
        )
        slow_mo_ms = (
            _parse_int(ENV_SLOW_MO, env[ENV_SLOW_MO])
            if (env.get(ENV_SLOW_MO) or "").strip()
            else DEFAULT_SLOW_MO_MS
        )

        config = cls(
            email=env[ENV_EMAIL].strip(),
            password=env[ENV_PASSWORD],  # do not strip secrets
            base_url=env[ENV_BASE_URL].strip().rstrip("/"),
            headless=headless,
            timeout_ms=timeout_ms,
            slow_mo_ms=slow_mo_ms,
            seo_files_dir=(env.get(ENV_SEO_DIR) or DEFAULT_SEO_DIR).strip(),
            logs_dir=(env.get(ENV_LOGS_DIR) or DEFAULT_LOGS_DIR).strip(),
            google_sa_key_file=(env.get(ENV_GOOGLE_SA_KEY_FILE) or "").strip()
            or None,
            google_sheet_url=(env.get(ENV_GOOGLE_SHEET_URL) or "").strip()
            or None,
        )

        errors = config.validate()
        if errors:
            raise ConfigError(
                "Invalid configuration:\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

        return config

    def validate(self) -> list[str]:
        """Return a list of value-level validation errors (empty if valid)."""
        errors: list[str] = []

        if not self.email.strip():
            errors.append("email is required")
        if not self.password:
            errors.append("password is required")

        if not self.base_url.strip():
            errors.append("base_url is required")
        elif not (
            self.base_url.startswith("http://")
            or self.base_url.startswith("https://")
        ):
            errors.append("base_url must start with http:// or https://")

        if self.timeout_ms < MIN_TIMEOUT_MS:
            errors.append(f"timeout_ms must be at least {MIN_TIMEOUT_MS}")

        if self.slow_mo_ms < 0:
            errors.append("slow_mo_ms must be >= 0")

        return errors

    def is_valid(self) -> bool:
        """Convenience helper: True when there are no validation errors."""
        return not self.validate()

    def redacted(self) -> dict:
        """Return a dict representation safe for logging (secrets masked)."""
        return {
            "email": self.email,
            "password": "***" if self.password else "",
            "base_url": self.base_url,
            "headless": self.headless,
            "timeout_ms": self.timeout_ms,
            "slow_mo_ms": self.slow_mo_ms,
            "seo_files_dir": self.seo_files_dir,
            "logs_dir": self.logs_dir,
            "google_sa_key_file": self.google_sa_key_file,
            "google_sheet_url": self.google_sheet_url,
        }
