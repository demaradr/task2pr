"""Environment-based configuration for task2pr.

Settings.load() never raises by itself - it reads whatever env vars are
present and leaves the rest as None. Each CLI command then calls
settings.require(...) naming only the fields *it* needs, so running
`poll-wrike` doesn't demand a GitHub or Anthropic token it never touches.
`check-config` is the one command that requires everything, since its whole
job is validating the full setup.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

_ENV_VAR_NAMES = {
    "wrike_api_token": "WRIKE_API_TOKEN",
    "github_token": "GITHUB_TOKEN",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
}


@dataclass(frozen=True)
class Settings:
    wrike_api_token: str | None
    github_token: str | None
    anthropic_api_key: str | None
    log_level: str = "INFO"

    @classmethod
    def load(cls) -> "Settings":
        load_dotenv()
        return cls(
            wrike_api_token=os.environ.get("WRIKE_API_TOKEN") or None,
            github_token=os.environ.get("GITHUB_TOKEN") or None,
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
        )

    def require(self, *field_names: str) -> None:
        """Raise MissingConfigError if any named field is unset.

        Usage: settings.require("wrike_api_token", "github_token")
        """
        missing = [
            _ENV_VAR_NAMES[name] for name in field_names if getattr(self, name) is None
        ]
        if missing:
            raise MissingConfigError(missing)


class MissingConfigError(RuntimeError):
    def __init__(self, missing_vars: list[str]) -> None:
        self.missing_vars = missing_vars
        super().__init__(
            "Missing required environment variables: "
            + ", ".join(missing_vars)
            + ". Copy .env.example to .env and fill them in."
        )
