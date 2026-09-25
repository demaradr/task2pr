"""GitHub webhook receiver: closes the loop by marking a Wrike task done
when the PR task2pr opened for it gets merged.

This is the one part of task2pr that has to be reachable from the public
internet - GitHub needs to be able to POST to it. Locally, run it behind a
tunnel (e.g. `ngrok http 8000`) and register a GitHub webhook against the
target repo pointing at the tunnel's URL + /webhooks/github, with the same
secret set here via GITHUB_WEBHOOK_SECRET.

Every request's signature is verified with HMAC-SHA256 against that shared
secret before anything in the payload is trusted (see _verify_signature) -
without this, anyone who finds the URL could POST fake "PR merged" events
and get arbitrary Wrike tasks marked complete.
"""
from __future__ import annotations

import hashlib
import hmac
import logging

from fastapi import FastAPI, Header, HTTPException, Request

from task2pr.config import Settings
from task2pr.store import TaskMappingStore
from task2pr.wrike import WrikeAPIError, WrikeClient

logger = logging.getLogger(__name__)


def _verify_signature(secret: str, payload: bytes, signature_header: str | None) -> None:
    if not signature_header or not signature_header.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Missing or malformed signature.")
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    provided = signature_header.removeprefix("sha256=")
    if not hmac.compare_digest(expected, provided):
        raise HTTPException(status_code=401, detail="Invalid signature.")


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="task2pr webhook receiver")
    store = TaskMappingStore(settings.state_path)

    @app.post("/webhooks/github")
    async def github_webhook(
        request: Request,
        x_hub_signature_256: str | None = Header(default=None),
        x_github_event: str | None = Header(default=None),
    ) -> dict:
        raw_body = await request.body()
        _verify_signature(settings.github_webhook_secret, raw_body, x_hub_signature_256)

        if x_github_event != "pull_request":
            return {"status": "ignored", "reason": f"event {x_github_event!r} not handled"}

        payload = await request.json()
        pr = payload.get("pull_request", {})
        if payload.get("action") != "closed" or not pr.get("merged"):
            return {"status": "ignored", "reason": "not a merged pull_request"}

        owner = payload["repository"]["owner"]["login"]
        repo = payload["repository"]["name"]
        pr_number = pr["number"]

        mapping = store.find_by_pr(owner, repo, pr_number)
        if mapping is None:
            logger.info("No task2pr mapping for %s/%s#%d; ignoring.", owner, repo, pr_number)
            return {"status": "ignored", "reason": "no mapping for this PR"}

        wrike_client = WrikeClient(settings.wrike_api_token)
        try:
            wrike_client.mark_task_complete(mapping.wrike_task_id)
        except WrikeAPIError as exc:
            logger.error("Failed to mark Wrike task %s complete: %s", mapping.wrike_task_id, exc)
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        logger.info(
            "Marked Wrike task %s complete (merged %s/%s#%d).",
            mapping.wrike_task_id,
            owner,
            repo,
            pr_number,
        )
        return {"status": "ok", "wrike_task_id": mapping.wrike_task_id}

    return app
