"""Read-only Wrike API client: auth + fetching tasks by custom status.

Wrike has no generic "tag" concept like GitHub labels. The natural fit for
an "AI Ready" marker is a custom status within one of the account's
workflows, so this client resolves a status *name* to its id (via
/workflows) and then filters /tasks by that id.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://www.wrike.com/api/v4"


class WrikeAPIError(RuntimeError):
    """Raised when the Wrike API returns an error, or a lookup fails."""


@dataclass(frozen=True)
class WrikeTask:
    id: str
    title: str
    description: str
    permalink: str
    status: str
    custom_status_id: str | None


class WrikeClient:
    def __init__(
        self,
        api_token: str,
        base_url: str = BASE_URL,
        session: requests.Session | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._session = session or requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {api_token}"})

    def _get(self, path: str, params: dict[str, str] | None = None) -> dict:
        url = f"{self._base_url}{path}"
        response = self._session.get(url, params=params, timeout=30)
        if not response.ok:
            raise WrikeAPIError(
                f"Wrike API error {response.status_code} for {path}: {response.text}"
            )
        return response.json()

    def list_custom_statuses(self) -> list[dict]:
        """Return every custom status across every workflow as raw dicts."""
        data = self._get("/workflows")
        statuses: list[dict] = []
        for workflow in data.get("data", []):
            statuses.extend(workflow.get("customStatuses", []))
        return statuses

    def resolve_status_id(self, status_name: str) -> str:
        """Look up the custom status id whose name matches (case-insensitive)."""
        target = status_name.strip().lower()
        for status in self.list_custom_statuses():
            if status.get("name", "").strip().lower() == target:
                return status["id"]
        raise WrikeAPIError(
            f"No custom status named {status_name!r} found in any workflow. "
            "Check spelling/case, or create it in Wrike first."
        )

    def get_tasks_by_custom_status(self, custom_status_id: str) -> list[WrikeTask]:
        data = self._get(
            "/tasks",
            params={
                "customStatuses": f'["{custom_status_id}"]',
                "fields": '["description"]',
            },
        )
        return [self._parse_task(raw) for raw in data.get("data", [])]

    def get_tasks_by_status_name(self, status_name: str) -> list[WrikeTask]:
        status_id = self.resolve_status_id(status_name)
        return self.get_tasks_by_custom_status(status_id)

    @staticmethod
    def _parse_task(raw: dict) -> WrikeTask:
        return WrikeTask(
            id=raw["id"],
            title=raw.get("title", ""),
            description=raw.get("description", ""),
            permalink=raw.get("permalink", ""),
            status=raw.get("status", ""),
            custom_status_id=raw.get("customStatusId"),
        )
