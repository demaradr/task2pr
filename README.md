# task2pr

Agentic automation: a Wrike task tagged "AI Ready" is picked up, an agent
explores a target repo, makes the code change, runs tests, and opens a
GitHub PR for human review. When the PR is merged, a GitHub webhook marks
the Wrike task complete. This service is standalone - it clones/operates
on a separate target repo via the GitHub API and local git commands; it does
not live inside the repo it modifies.

```
Wrike "AI Ready" task
  -> explore agent (read-only tools)        -> plan
  -> edit agent (read + edit tools)         -> change
  -> harness runs the test suite            -> retry on failure (capped)
  -> tests pass? push branch + open PR      -> human reviews and merges
  -> GitHub webhook (HMAC-verified)         -> Wrike task marked Completed
```

## How it works

- **Agent loops** (`src/task2pr/agent/`) - a tool-use loop on the Claude
  API. The explore loop gets `list_directory`, `read_file` (paged in
  500-line windows) and `grep`; the edit loop adds `write_file` and
  `edit_file`. When the model stops calling tools, the harness runs the
  tests and feeds failures back for another attempt.
- **GitHub** (`src/task2pr/github/`) - branch, commit and push via git; the
  PR itself via the REST API. A PR is only ever opened for a change whose
  tests passed.
- **Wrike** (`src/task2pr/wrike/`) - resolves the "AI Ready" custom status
  and fetches matching tasks.
- **Webhook** (`src/task2pr/webhook/`) - FastAPI receiver for GitHub
  `pull_request` events; on merge, looks up the Wrike task recorded at
  PR-creation time and completes it.
- **Eval harness** (`src/task2pr/eval/`, `eval/`) - runs the edit loop
  against seeded fixture repos (add a function, fix a bug, handle
  divide-by-zero) and scores pass/fail by each fixture's test suite.

## Safety

- The agent never gets a shell tool. The test command is fixed by the
  operator (`--test-cmd`) and never derived from task text, so a malicious
  task description can't execute commands.
- All file access is sandboxed to the target repo in code - paths that
  resolve outside it are refused.
- The agent proposes changes; it never merges them.
- The GitHub token is used only for a single push URL, never written to
  `.git/config`, and scrubbed from error output.
- Webhook payloads are rejected unless their HMAC signature verifies.

The reasoning behind these and other choices is in
[DESIGN_DECISIONS.md](DESIGN_DECISIONS.md).

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # fill in your tokens
python -m task2pr check-config
```

## Usage

```bash
# List Wrike tasks waiting for the agent
task2pr poll-wrike

# Read-only: explore a repo and propose a plan
task2pr explore --repo ../target-repo --task-text "Add input validation to parse_date"

# Make the change, run tests, and open a PR if they pass
task2pr run-task --repo ../target-repo --wrike-task-id <ID> --test-cmd "pytest -q" --open-pr

# Receive GitHub merge events and complete Wrike tasks
task2pr serve-webhook --port 8000

# Score the agent against the seeded eval tasks
task2pr eval
```

## Tests

```bash
pytest -q
```

Unit tests mock the Wrike, GitHub and Anthropic APIs, so they run offline.
`task2pr eval` is the one command that makes real model calls.
