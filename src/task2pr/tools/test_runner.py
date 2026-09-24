"""Runs the target repo's test suite as a deterministic step controlled by
the harness - not something Claude can invoke itself. Claude only ever gets
file read/write tools; deciding when to run tests, and with what command,
stays outside model control. The test command comes from the operator (a
CLI flag), never from the Wrike task text, so untrusted task content can
never smuggle in an arbitrary shell command.
"""
from __future__ import annotations

import logging
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_OUTPUT_CHARS = 6000


@dataclass(frozen=True)
class RunResult:
    passed: bool
    returncode: int
    output: str


def run_tests(command: str, repo_root: Path, timeout: int = 120) -> RunResult:
    args = shlex.split(command)
    try:
        proc = subprocess.run(
            args,
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return RunResult(
            passed=False,
            returncode=-1,
            output=f"Test command timed out after {timeout}s: {command!r}",
        )
    except FileNotFoundError as exc:
        return RunResult(
            passed=False,
            returncode=-1,
            output=f"Could not run test command {command!r}: {exc}",
        )

    combined = (proc.stdout or "") + (proc.stderr or "")
    if len(combined) > MAX_OUTPUT_CHARS:
        combined = "... (output truncated, showing the end)\n" + combined[-MAX_OUTPUT_CHARS:]
    return RunResult(passed=proc.returncode == 0, returncode=proc.returncode, output=combined)
