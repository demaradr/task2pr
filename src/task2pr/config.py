"""Environment-based configuration for task2pr.

Settings are loaded lazily (via Settings.load()), not at import time, so that
importing this module never fails just because .env isn't set up yet -
only commands that actually need credentials will raise.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    wrike_api_token: str
    github_token: str
    anthropic_api_key: str
    log_level: str = "INFO"

    @classmethod
    def load(cls) -> "Settings":
        load_dotenv()

        required = {
            "WRIKE_API_TOKEN": "wrike_api_token",
            "GITHUB_TOKEN": "github_token",
            "ANTHROPIC_API_KEY": "anthropic_api_key",
        }
        values: dict[str, str] = {}
        missing: list[str] = []
        for env_name, _field in required.items():
            value = os.environ.get(env_name)
            if not value:
                missing.append(env_name)
            else:
                values[required[env_name]] = value

        if missing:
            raise MissingConfigError(missing)

        return cls(
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            **values,
        )


class MissingConfigError(RuntimeError):
    def __init__(self, missing_vars: list[str]) -> None:
        self.missing_vars = missing_vars
        super().__init__(
            "Missing required environment variables: "
            + ", ".join(missing_vars)
            + ". Copy .env.example to .env and fill them in."
        )
