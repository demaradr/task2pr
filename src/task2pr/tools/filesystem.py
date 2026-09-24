"""Read-only, sandboxed filesystem tools for the explore agent loop.

Every tool goes through RepoSandbox.resolve() first, which refuses any path
that resolves outside the target repo root (e.g. "../../etc/passwd" or an
absolute path elsewhere on disk). Claude only ever gets to operate inside
the one repo it was pointed at, no matter what path it asks for.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

MAX_GREP_MATCHES = 200
DEFAULT_READ_LIMIT = 500
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache"}


class ToolError(RuntimeError):
    """Raised when a tool call is invalid (bad path, bad regex, etc.)."""


@dataclass(frozen=True)
class RepoSandbox:
    repo_root: Path

    def resolve(self, relative_path: str) -> Path:
        root = self.repo_root.resolve()
        candidate = (root / relative_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            raise ToolError(
                f"Path {relative_path!r} resolves outside the target repo; refusing to access it."
            )
        return candidate


def list_directory(sandbox: RepoSandbox, path: str = ".") -> str:
    target = sandbox.resolve(path)
    if not target.exists():
        raise ToolError(f"{path!r} does not exist.")
    if not target.is_dir():
        raise ToolError(f"{path!r} is not a directory.")

    entries = [
        f"{entry.name}/" if entry.is_dir() else entry.name
        for entry in sorted(target.iterdir())
        if entry.name not in SKIP_DIRS
    ]
    return "\n".join(entries) if entries else "(empty directory)"


def read_file(
    sandbox: RepoSandbox,
    path: str,
    offset: int = 0,
    limit: int = DEFAULT_READ_LIMIT,
) -> str:
    target = sandbox.resolve(path)
    if not target.exists():
        raise ToolError(f"{path!r} does not exist.")
    if not target.is_file():
        raise ToolError(f"{path!r} is not a file.")

    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise ToolError(f"Could not read {path!r}: {exc}")

    window = lines[offset : offset + limit]
    if not window:
        return "(empty file)" if not lines else "(offset is past end of file)"

    numbered = "\n".join(f"{i + offset + 1}\t{line}" for i, line in enumerate(window))
    remaining = len(lines) - (offset + limit)
    if remaining > 0:
        numbered += f"\n... ({remaining} more lines; call again with offset={offset + limit})"
    return numbered


def grep(sandbox: RepoSandbox, pattern: str, path: str = ".") -> str:
    target = sandbox.resolve(path)
    if not target.exists():
        raise ToolError(f"{path!r} does not exist.")

    try:
        regex = re.compile(pattern)
    except re.error as exc:
        raise ToolError(f"Invalid regex {pattern!r}: {exc}")

    if target.is_file():
        files_to_search = [target]
    else:
        files_to_search = []
        for root, dirs, files in os.walk(target):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            files_to_search.extend(Path(root) / name for name in files)

    repo_root = sandbox.repo_root.resolve()
    matches: list[str] = []
    for file_path in files_to_search:
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line_num, line in enumerate(content.splitlines(), start=1):
            if regex.search(line):
                rel = file_path.resolve().relative_to(repo_root)
                matches.append(f"{rel}:{line_num}:{line.strip()}")
                if len(matches) >= MAX_GREP_MATCHES:
                    matches.append(f"... (truncated at {MAX_GREP_MATCHES} matches)")
                    return "\n".join(matches)

    return "\n".join(matches) if matches else "(no matches)"


def write_file(sandbox: RepoSandbox, path: str, content: str) -> str:
    """Create a file or overwrite it entirely. Prefer edit_file for changes
    to existing files so unrelated content isn't discarded."""
    target = sandbox.resolve(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.exists()
    target.write_text(content, encoding="utf-8")
    verb = "Overwrote" if existed else "Created"
    return f"{verb} {path} ({len(content.splitlines())} lines)."


def edit_file(
    sandbox: RepoSandbox,
    path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> str:
    """Replace an exact substring in an existing file. Mirrors the standard
    editor-tool contract: old_string must match exactly (read the file
    first), and must be unique unless replace_all is set."""
    target = sandbox.resolve(path)
    if not target.exists():
        raise ToolError(f"{path!r} does not exist. Use write_file to create it.")
    if not target.is_file():
        raise ToolError(f"{path!r} is not a file.")

    content = target.read_text(encoding="utf-8")
    count = content.count(old_string)
    if count == 0:
        raise ToolError(
            f"old_string not found in {path!r}. Read the file first and copy the exact text."
        )
    if count > 1 and not replace_all:
        raise ToolError(
            f"old_string matches {count} places in {path!r}; it must be unique. "
            "Include more surrounding context, or set replace_all=true."
        )

    if replace_all:
        new_content = content.replace(old_string, new_string)
    else:
        new_content = content.replace(old_string, new_string, 1)
    target.write_text(new_content, encoding="utf-8")
    occurrences = count if replace_all else 1
    return f"Replaced {occurrences} occurrence(s) in {path}."
