# Autonomous GitHub Agent

A Python agent with a browser dashboard for continuous GitHub inbox triage, issue discovery, and verified draft PR creation. It can invoke models through the authenticated Antigravity CLI or use a configured Gemini, Anthropic, or OpenAI-compatible API.

The scheduler repeats inbox and issue workflows while its process is alive. Each model operation is a finite inference request. Polling waits, quota limits, pauses, and the rolling submission cap can suspend work. Closing the process, host sleep, or a crash interrupts service; this application does not install a background supervisor.

## Setup

Requires Python 3.10+, Git, and GitHub authentication on macOS or Linux/POSIX. For Antigravity inference, install and authenticate `agy`, then inspect the model IDs with `agy models`. Repository verification requires macOS `sandbox-exec`, or Docker and an appropriate prebuilt test image on other hosts.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -c requirements.lock -e '.[dev]'
cp .env.example .env
```

Set `GITHUB_TOKEN` or authenticate `gh auth login`. GitHub authentication and model authentication are independent. Do not commit `.env` or scratch state.

```bash
./run.sh doctor
./run.sh start --dry-run --port 3000
```

Open [Mission Control](http://127.0.0.1:3000). The dashboard has Overview, Tasks, Workers, Terminal, and Settings tabs. `doctor` makes a minimal real inference request, checks GitHub authentication/quota, and runs a disposable isolated test. It does not process notifications or submit contributions.

When ready to authorize GitHub writes:

```bash
./run.sh start --live --port 3000
```

`--live` enables replies, notification read/archive actions, forks, pushes, and draft PRs. Dry-run is the default. Dry-run still reads GitHub, invokes models, clones repositories, runs isolated tests, edits disposable checkouts, and commits locally. It does not consume live submission history or mark issues permanently handled.

## Execution controls

The dashboard's Pause cancels active cycles, waits for their owned work to terminate, and closes admission of new work. Resume reopens admission. Worker buttons queue another cycle; Hunt discovers candidates without solving them, while Solve runs discovery and repair. Buttons are unavailable when there is no running controller.

Stop from the dashboard, Ctrl+C, SIGTERM, or a separate terminal:

```bash
./run.sh stop
```

CLI Stop sends an authenticated request to the running process and reports `STOPPING` when acknowledged. The process then terminates owned work, closes its control server, finalizes tasks, and records `STOPPED`. A request cannot reverse an external action GitHub already accepted. Only one execution owner can use a scratch directory at a time.

Other commands:

```bash
./run.sh status
./run.sh tasks
./run.sh inbox --dry-run
./run.sh inbox --mark-done --dry-run
./run.sh hunt --limit 5
./run.sh solve --auto --limit 1 --dry-run
./run.sh solve --no-auto --limit 5  # discovery only
./run.sh web --port 3001          # standalone dashboard; no execution controller
```

Standalone dashboard settings apply to the next agent start. Use the dashboard served by `start` to control the running agent. Settings are validated as a complete request and persisted in `scratch/settings.json`; saving active settings cancels the current work before applying them. Explicit CLI `--dry-run`/`--live` overrides the saved mode on start.

## Models

`AI_PROVIDER=antigravity` invokes `agy` in print mode, plan mode, an empty temporary workspace, with CLI sandbox restrictions and slash command expansion disabled. It never adds the repository checkout to that workspace. Repository source needed for a repair is supplied in the prompt. Antigravity CLI permissions and account quotas still apply; the adapter does not bypass them or provide a persistent reasoning session.

Examples of IDs returned by the installed CLI:

- `gemini-3.8-flash-high`, `gemini-3.8-flash-medium`, `gemini-3.8-flash-low`
- `gemini-3.7-flash-high`, `gemini-3.6-flash-medium`, `gemini-3.1-pro-high`
- `claude-sonnet-4-6`, `claude-opus-4-6-thinking`, `gpt-oss-120b-medium`

Availability can change; use `agy models` for your installation/account. Legacy family aliases are translated only for the Antigravity adapter. Direct API providers require their own key and a model ID supported by that endpoint. Claude requests go to Anthropic; they are never sent to Gemini.

`AI_PROVIDER=auto` chooses the model family's configured API key, otherwise the installed Antigravity CLI. Select a provider explicitly to avoid ambiguity. Health shows `UNVERIFIED`, `ONLINE`, `UNAVAILABLE`, or `DEGRADED`; successful inference establishes `ONLINE`. Model failure cannot produce a fabricated repair or fallback reply. Discovery can use a heuristic score, but source repair still requires a valid model-generated patch.

Manual model selection remains stable. Optional `SYNC_IDE_MODEL=true` reads only the transcript identified by `ANTIGRAVITY_CONVERSATION_ID`; it does not scan other conversations. Transcript synchronization is a selection convenience, independent of inference authentication.

Minimal integration checks, without GitHub writes:

```bash
.venv/bin/python scripts/check_models.py gemini-3.8-flash-high claude-sonnet-4-6 gpt-oss-120b-medium
```

## Contribution verification

Discovery searches issues, excludes pull requests, deduplicates results, and verifies repository stars, assignment, archive state, and open linked PRs. Eligibility is checked again before submission. GitHub errors and unknown quota block work rather than appearing as a clean inbox or full quota.

Each repair uses a fresh checkout and a dedicated `codex/` branch. The solver supplies relevant source, baseline output, contributing instructions, and available PR templates to the model. It requires all of the following:

1. A passing, nonempty baseline test suite.
2. A sufficiently confident source-file patch that preserves existing tests, and a new regression test.
3. A failing regression before the fix with assertion evidence.
4. Passing tests after the fix.
5. Passing verification of the committed changes without unsubmitted source changes.
6. Checked fork discovery/creation and a successful push before draft PR creation.

No detected tests, disabled verification, an unsafe/symlink patch target, failing tests, failed pushes, or linked/assigned issues block submission. Cancellation and failed attempts remain retryable; only confirmed live PRs count toward the rolling cap. Claims reserve submission slots transactionally. DCO sign-off is included; repositories with a detected CLA requirement need prior acceptance configured in `ACCEPTED_CLA_REPOS`.

This is a bounded single-patch repair attempt, not universal repository support or proof of all behavior. Relevant source context is limited. Arbitrary natural-language contribution rules and repository-specific lint/build commands require additional integration. A passing generic suite does not establish full project correctness. Draft PRs require human review.

## Isolation and persistence

Docker test runs have no network, an empty home, no GitHub credentials, read-only Git metadata, dropped capabilities, and CPU/memory/process limits. Prepare dependencies in `SANDBOX_IMAGE` before running; the agent does not automatically install untrusted repository dependencies on the host. The macOS sandbox restricts reads, confines writes to the checkout and temporary home, denies network and Git metadata writes, and enforces a timeout with owned process-group termination. It does not provide Docker's resource limits; use a container for stronger isolation.

`ALLOW_HOST_TESTS=true` is an explicit escape hatch for trusted local dry-run fixtures only. Host execution is prohibited in live mode. Unsupported or unavailable test toolchains fail closed.

SQLite sidecars are authoritative for handled work, PR history, slot claims, and task history. JSON files remain compatibility snapshots. Existing valid JSON history migrates on first use. Corrupt history stops initialization instead of resetting caps. Interrupted tasks are marked cancelled and orphaned submission reservations are cleared under the execution lease on the next start. The dashboard displays the most recent 100 tasks; its task/PR counters cover that window.

The control server binds to loopback. Mutations require an authenticated session plus a control header, or the runtime bearer token; Host, Origin, content type, and request size are checked. Keep `scratch/runtime.json` private. Do not expose this development HTTP server publicly.

## Development and validation

```bash
cd frontend
npm ci
npm run build
cd ..
.venv/bin/python -m pip install playwright
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest -q
.venv/bin/python -m pip wheel . --no-deps -w dist
.venv/bin/python scripts/check_wheel.py dist/*.whl
```

Frontend builds synchronize the shipped HTML/CSS/JavaScript into package resources. The wheel smoke check installs outside the checkout and verifies the real dashboard assets and API. CI runs Python tests on 3.10/3.12/3.14 and a Chromium/build/package job. `requirements.lock` pins the resolved shared dependency versions as pip constraints; platform/Python-specific dependencies may still be resolved separately.

See `docs/audits/2026-09-16/AUDIT.md` for the original findings and `REPAIRS.md` in the same directory for repair evidence and remaining operational limits. No multi-hour availability or complete accessibility conformance guarantee is made.
