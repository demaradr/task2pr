# Design decisions

A running log of the key design decisions made while building task2pr, and the
reasoning behind them. Organized by stage, in the order they came up.

## Stage 1 — Project skeleton & config

**Config loads lazily, not at import time.** `Settings.load()` is only called
when a command actually needs credentials, and it never raises by itself — it
reads whatever env vars are present and leaves the rest as `None`. Each CLI
command then calls `settings.require(...)` naming only the fields *it* needs
(e.g. `poll-wrike` only requires `wrike_api_token`, not GitHub or Anthropic
credentials). `check-config` is the one command that requires everything,
since its whole job is validating the full setup. This was actually a bug we
hit and fixed live: the first version required all three tokens unconditionally,
so `poll-wrike` failed even with a valid Wrike token just because
`GITHUB_TOKEN`/`ANTHROPIC_API_KEY` weren't set yet.

**src-layout (`src/task2pr/`), not a flat package at the repo root.** Keeps the
package name meaningful (`import task2pr`, not `import src`) while avoiding a
confusing `task2pr/task2pr/` nesting. It also has a real safety property: it's
structurally impossible for `pytest` or scripts to accidentally import
uninstalled source from the current directory — `task2pr` isn't importable
unless it's actually `pip install -e`'d.

## Stage 2 — Wrike client

**Wrike's "tag" maps to a custom status, not a label.** Wrike has no
GitHub-style label concept; a custom status within a workflow (e.g. "AI
Ready") is the natural fit, and is how most Wrike-based automations model
this kind of marker. The client resolves the status *name* to an id via
`/workflows`, then filters `/tasks` by that id.

**Account-wide task queries, no pagination.** Wrike's `/tasks` endpoint
without a folder scope searches the whole account, which is what we want for
"any AI Ready task, anywhere." Pagination was deliberately left out — fine at
portfolio-project task volume, and easy to add later if it's ever needed.

**`requests` over stdlib `urllib`.** Simpler ergonomics for headers/params/
JSON, and easily mockable with `requests_mock` in tests without touching the
network.

## Stage 3 — Explore-only agent loop

**Narrow tools over one clever tool.** `list_directory` only lists one level
deep rather than recursing; the model composes calls (list, then list a
subdirectory, then read a file) instead of one tool trying to dump an entire
tree. Narrower tools are easier for a model to use correctly, and cheaper per
call — a broad recursive dump risks blowing the context budget on the same
problem large files have (see below).

**Files are read in windows, not whole.** `read_file` returns at most 500
lines at a time with an explicit "N more lines, call again with offset=X"
hint when truncated. Claude has no memory between API calls except what's
resent in the `messages` list every turn — an unbounded file dump could
crowd out everything else it needs to remember. This mirrors exactly how
Claude Code's own `Read` tool works (offset/limit paging) — same constraint,
same solution, because it's fundamental to how these models are used, not
specific to this project.

**Tool errors are returned as data, not raised as exceptions.** `run_tool()`
catches `ToolError` (bad path, bad regex, missing file) and hands the model a
normal `"Error: ..."` string result instead of letting the exception
propagate and crash the whole loop. The model sees the error like any other
tool output and can adjust its next call.

**Hard sandboxing, not just prompt instructions.** `RepoSandbox.resolve()`
refuses any path that resolves outside the target repo root — `../../etc/passwd`,
absolute paths elsewhere on disk, anything. This is enforced in code, not by
asking the model nicely; no matter what path Claude requests, escaping the
sandbox is structurally impossible.

**No repo cloning in this stage.** `explore` takes `--repo <local path>` and
assumes a clone already exists. Actually cloning/branching belongs to Stage 5
(GitHub integration); pulling it in earlier would blur the stage boundary.

## Stage 4 — Edit-and-test loop

**Claude can edit files, but it never gets a tool to run shell commands.**
This is the single most important safety decision in the whole project.
`write_file`/`edit_file` are Claude-callable tools, but the test suite is
executed by the harness (plain Python code) at a moment *we* control —
right after Claude stops calling tools, signaling "I think I'm done." The
test result is then injected back into the conversation as a normal message.
Because the test command is a fixed, operator-supplied string (`--test-cmd`)
and is never derived from the (externally-sourced, semi-trusted) Wrike task
text, there is no path from "attacker-controlled task description" to
"arbitrary command execution."

**One combined loop, not two nested ones.** Editing and test-retrying share a
single tool-call iteration budget (catches a model stuck looping on tool
calls without ever finishing) and a separate, smaller cap on test *runs*
specifically (catches a clean edit that just never passes). Two different
failure modes, two different caps.

**`edit_file` mirrors this session's own `Edit` tool contract**: exact
string match required, and the match must be unique unless `replace_all` is
set. This is a well-tested pattern for LLM-driven edits — it's the same
contract used to edit this project's own files during our conversation.

## Stage 5 — GitHub integration

**A PR is only opened if tests actually passed — enforced in code, checked
before the `--open-pr` flag is even read.** There is no code path where a
failing `run_edit_loop` result reaches `ship_branch`. This is the sibling of
"the agent never merges its own PR": the agent also shouldn't get to
*propose* a PR for a change it couldn't verify.

**git for branch/commit/push; the GitHub REST API only for the PR itself.**
Opening a PR has no git equivalent — it's a GitHub-specific concept — so
that's the one piece that needs the API. Everything else just operates on
the already-cloned local repo, which needs no GitHub-specific plumbing.

**The GitHub token is used only as an ephemeral push URL, never persisted.**
`push_branch` builds `https://x-access-token:<token>@github.com/...` fresh
for that one `git push` call. It's never written to `.git/config`, and if
the push fails, the token is stripped out of the error message
(`stderr.replace(token, "***")`) before it's raised, so it can't leak into
logs or CLI output.

**Owner/repo auto-detected from the existing `origin` remote**, rather than
new CLI flags — the cloned repo already knows this.

**Auto-generated branch names** (`task2pr/<slugified-title>-<6-char-random>`)
so re-running the same task twice doesn't collide.

## Stage 6 — Wrike status sync (webhook)

**The Wrike-task-to-PR mapping is recorded at PR-creation time, not
reconstructed later.** GitHub has no concept of "this PR is for Wrike task
X" — that link only exists in this system, at the one moment we know both
sides of it (right when the PR opens). Nothing later (a webhook receiving a
bare PR number from GitHub) could recover that link if it wasn't captured
here.

**A flat JSON file, not a database, for the mapping store.** This runs at
portfolio-project scale (dozens of tasks, not millions); being able to `cat
~/.task2pr/state.json` while debugging outweighs any database's query
features here.

**State lives outside the target repo**, in the task2pr service's own home
directory (`~/.task2pr/state.json` by default). Since task2pr operates as a
standalone service across potentially many target repos, storing state
inside whichever repo happens to be checked out would break on re-clone and
risks accidentally committing it into someone else's repository.

**"Mark complete" uses Wrike's built-in status, not a custom status.**
Unlike "AI Ready" (workflow-specific, needed the custom-status machinery),
"done" is universal — every Wrike task has a base status
(Active/Completed/Deferred/Cancelled) regardless of custom workflow. No id
resolution needed.

**HMAC signature verification is the hard security boundary on the webhook
endpoint**, checked before the payload is even parsed. This endpoint is
*designed* to be reachable from the public internet (GitHub has to reach
it) — without verification, anyone who found the URL could POST a fake
"PR merged" event and get arbitrary Wrike tasks marked complete.

**Always return 200 for events we don't act on; 502 specifically when acting
on one fails.** GitHub treats non-2xx as delivery failure and retries, then
eventually disables a webhook that keeps failing. "Not a merge" or "no
mapping for this PR" are correctly-handled cases → 200. A failed call to the
Wrike API is a genuine failure → 502, so GitHub's automatic retry gets a
chance to succeed later (e.g. after a transient Wrike outage).

**The webhook server binds to `127.0.0.1` by default, not `0.0.0.0`.** It's
meant to sit behind a tunnel (ngrok) or reverse proxy; defaulting to
localhost-only is the safer default, and wider exposure is an explicit
opt-in via `--host`.

## Stage 7 — Eval harness

**Eval tasks are fully decoupled from GitHub and Wrike.** They only exercise
`run_edit_loop` against throwaway copies of fixture repos — no PR is ever
opened, no real Wrike task is ever touched. The only side effect of running
an eval is Anthropic API calls, which makes it safe to run repeatedly and
cheap to reason about.

**Each task gets its own fixture directory, copied fresh per run.** Fixtures
are never mutated in place, so re-running the eval (or running it
concurrently) can't corrupt the seeded starting state, and tasks can't leak
state into each other even when they touch a file with the same name.

**Each fixture's starting test suite is self-consistent before any agent
edit** — for a "fix this bug" task, exactly the one test targeting that bug
fails initially, and every other test already passes. This matters because
the pass/fail signal for a task is "did the *whole* test suite pass," so an
unrelated pre-existing failure would make even a perfect fix look like a
failure.
