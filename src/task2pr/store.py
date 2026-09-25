"""Durable mapping between a Wrike task and the GitHub PR task2pr opened
for it. This is the piece the (upcoming) webhook receiver needs: GitHub
tells us "PR #42 in acme/widgets just merged" and we have to answer "which
Wrike task does that correspond to?"

Deliberately a flat JSON file rather than a database - this runs at
portfolio-project scale (dozens of tasks, not millions), and a JSON file is
trivial to open and read by hand while debugging. It lives outside any
target repo (default: ~/.task2pr/state.json) so it's never accidentally
committed into a repo task2pr is operating on.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock

_lock = Lock()


@dataclass(frozen=True)
class TaskMapping:
    wrike_task_id: str
    github_owner: str
    github_repo: str
    pr_number: int
    branch: str


class TaskMappingStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def _load(self) -> list[dict]:
        if not self._path.exists():
            return []
        content = self._path.read_text().strip()
        return json.loads(content) if content else []

    def _save(self, records: list[dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(records, indent=2))

    def record(self, mapping: TaskMapping) -> None:
        with _lock:
            records = self._load()
            records.append(asdict(mapping))
            self._save(records)

    def find_by_pr(self, owner: str, repo: str, pr_number: int) -> TaskMapping | None:
        for record in self._load():
            if (
                record["github_owner"] == owner
                and record["github_repo"] == repo
                and record["pr_number"] == pr_number
            ):
                return TaskMapping(**record)
        return None
