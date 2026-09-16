# Readiness repairs — 16 September 2026

The application now has a working Antigravity inference adapter, process-owned execution controls, transactional history, isolated test execution, a verified repair pipeline, and a functioning packaged dashboard. It is ready for a controlled dry-run on this macOS environment. Live contribution support is implemented, but no external comment, fork, push, or PR was created during validation. Universal repository compatibility and uninterrupted production availability are not established.

## Evidence

- Real Antigravity inference succeeded for `gemini-3.8-flash-high`, `claude-sonnet-4-6`, and `gpt-oss-120b-medium`. Each returned the requested JSON and established provider health as `ONLINE`. Other model IDs/reasoning variants were not individually inferred. See `model-readiness.json`.
- The new `doctor` command verified actual GitHub authentication/quota, real Gemini inference through Antigravity, and a passing disposable isolated pytest suite. See `doctor-results.json`. These were read-only GitHub operations.
- A 30.85-second scheduler fixture completed seven inbox and seven hunter attempts, recovered from injected transient failures, prevented work during Pause, and stopped through a separate CLI process. Final status was `STOPPED`, with zero owned cycles remaining. See `soak-results.json`. This establishes short fixture continuity, not multi-hour availability or continuous successful inference.
- Real local Git/pytest fixtures establish a passing baseline, a failing regression before repair, and passing verification of the committed repair. An incorrect patch and a failed live-path push both prevent PR creation. External GitHub operations are mocked in these fixtures.
- Native macOS isolation tests verify denial of host-secret reads, writes outside the checkout, Git metadata writes, network connections, and signals to the host process. Test credentials are absent. Owned children terminate on timeout, cancellation, and Pause; excessive output terminates execution.
- Chromium verifies all five tabs, real settings values, persistence, rejection handling, unsaved edits across polls, task filters/search, keyboard inspection/focus restoration, escaped telemetry, persistent terminal clearing, theme persistence, mobile navigation/layout, and visible disconnection. See `repaired-desktop.png` and `repaired-mobile.png`.
- Frontend compilation succeeds. A wheel installed outside the checkout serves the real HTML, JavaScript, CSS, and API; `scripts/check_wheel.py` reproduces that check. The isolated Python environment has no broken dependency requirements.
- CI now covers Python 3.10/3.12/3.14, Chromium, frontend synchronization, and an installed-wheel smoke check. The local runtime is Python 3.14; remote CI has not been executed or published.

The final local suite passed **55 tests in 19.28 seconds**, with no skips. Results are recorded in `validation-results.txt`. Browser checks require the optional Playwright runtime and Chromium; CI treats a missing browser as a failure.

## Audit coverage

| Original findings | Repairs |
|---|---|
| A01 | Explicit Antigravity/Gemini/Anthropic/OpenAI-compatible routing, actual CLI model aliases, real completion validation, provider health, and no fabricated repair/reply fallback |
| A02, A16 | Authenticated cross-process Stop; admission gate; Pause waits for active cycles; idempotent cancellation and owned process-group termination; cancelled task finalization |
| A03, A04 | Required confident patch, nonempty baseline tests, new red/green regression, patched tests, and verification of the committed code; missing/disabled verification blocks submission |
| A05, A06 | Contained paths with symlink/traversal/secret/Git exclusions; source repairs preserve existing tests; Docker isolation or native macOS sandbox; sanitized test environment, timeout, and bounded output |
| A07, A08 | Escaped worker/task/toast data; validated PR links; CSP excludes inline scripts; loopback Host/Origin checks; authenticated mutations with strict content type/body bounds |
| A09 | Fresh checkout per attempt, dedicated branch, checked Git operations, verified fork discovery/creation, separate submission remote, authenticated push, and draft PR creation only after success |
| A10 | Relevant source and baseline evidence supplied to patch generation; contribution instructions and templates supplied to patch/PR generation; DCO sign-off and detected CLA gate. Generic language/framework support remains bounded as described below |
| A11, A12 | Correct issue-only search, repository metadata star checks, deduplication, linked-PR/assignment checks including immediately before submission; authoritative REST errors, real quota, search-bucket gate, bounded read retries |
| A13, A15 | Failed/unverified/low-confidence inbox actions remain unresolved; only confirmed actions are archived/handled; simulation has separate ephemeral deduplication and does not consume live caps; failed repairs remain retryable |
| A14 | SQLite transactional history and submission-slot claims, task transactions, process execution lease; single-pass inbox/solve commands cannot overlap the continuous owner |
| A17, A24 | Manual triggers wake actual workers; Hunt is discovery-only; configured semaphore bounds concurrent repairs; Resume wakes interval waits |
| A18–A21 | Normalized API task schema, accurate task metrics, corrected event serialization, clear cursor, worker persistence round-trip, actual cycle counters, heartbeat/uptime, and visible stopped/stale/disconnected states |
| A22 | Complete typed validation before mutation, rollback on persistence failure, durable settings, stable manual model selection, opt-in conversation-bound IDE synchronization, consistent interval bounds, actual input values, and error propagation |
| A23 | Reachable mobile menu, wrapping header without overlap, stacked settings, keyboard task actions, dialog/focus trapping/restoration, status announcements, and readable light-theme navigation |
| A25, A26 | Built frontend shipped as package resources; isolated wheel check; reproducible tests and CI; dependency constraints; corrected README/environment example/runbook and explicit live flag |

The original audit and its baseline probes remain historical evidence. Their line references and assumptions describe the code before these repairs; the old probe script is not the repaired application's acceptance suite. Use the committed tests and new smoke scripts for current validation.

## Operating instructions

```bash
./run.sh doctor
./run.sh start --dry-run --port 3000
```

Use the dashboard served by `start` for Pause/Resume and worker triggers. Stop from that dashboard, Ctrl+C, or `./run.sh stop` in another terminal. `start --live` explicitly enables external GitHub writes. No live run was started by these repairs.

Settings changes cancel active work before taking effect; cancelled work remains retryable. Standalone `web` settings are for the next agent start. A response of `STOPPING` acknowledges the command; the owning process performs cleanup and then records `STOPPED`. GitHub actions already accepted cannot be reversed by cancellation. Provider-side inference completion after a disconnected request is outside the local process controller's guarantees.

## Remaining operational limits

1. **Availability:** foreground process, no installed launchd/systemd supervisor or crash-resumable job queue. The scheduler repeats finite operations with waits, quota gates, and the rolling PR cap; it is not a continuously thinking IDE session.
2. **Repository support:** one bounded source-file repair attempt, limited relevant source context, generic manifest-based test detection, and preinstalled dependencies. Unsupported suites/toolchains fail closed. Repository-specific lint/build requirements and arbitrary natural-language contribution rules are not universally automated. Templates are supplied to the model, not checked by a universal compliance parser. Draft PRs need human review.
3. **Isolation:** Docker code paths provide resource limits but could not be run here because Docker is unavailable. Native macOS filesystem/network/process-signal restrictions were exercised; they do not replace container namespaces/resource limits. Host testing is allowed only for explicitly trusted dry-run fixtures. Supported hosts are macOS and Linux/POSIX.
4. **Provider coverage:** three model families were verified through the installed Antigravity account. All reasoning variants, direct cloud-provider accounts, long requests, and quota-exhaustion behavior were not individually live-tested. `doctor` should be run after changing provider/model or account configuration.
5. **External workflow:** the fork/push/draft-PR flow and failure gates are implemented and fixture-tested. No real upstream submission or multi-hour live soak was performed.
6. **Migration:** corrupt history fails closed. Known legacy mock PR submissions are excluded from migration, along with corresponding handled issues where no real PR exists. Legacy handled items without outcome evidence cannot be safely classified automatically. Starting a new execution owner or single-pass solver clears orphaned claims under the workspace lease; graceful shutdown releases active claims. Unmanaged library claims retain a four-hour fallback expiry.
7. **Validation scope:** local Python 3.14 and headless Chromium checks; remote CI matrix pending. The dependency file pins resolved shared versions as constraints rather than hashes for every platform-specific wheel. No full accessibility certification or comprehensive penetration test is claimed.

These limits replace the original unsupported claims of perfect or universal behavior. A successful controlled dry-run and review of its task evidence should precede any live contribution session.
