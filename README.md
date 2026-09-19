# task2pr

Agentic automation: a Wrike task tagged "AI Ready" is picked up, an agent
explores a target repo, makes the code change, runs tests, and opens a
GitHub PR for human review. This service is standalone - it clones/operates
on a separate target repo via the GitHub API and local git commands; it does
not live inside the repo it modifies.

## Status

Stage 1: project skeleton and config loading. No agent logic yet.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # fill in your tokens
python -m task2pr check-config
```
