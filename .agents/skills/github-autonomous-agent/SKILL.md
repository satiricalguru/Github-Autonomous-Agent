---
name: github-autonomous-agent
description: "Autonomous GitHub Agent that monitors and manages inbox notifications/mentions/PRs, searches top-tier repos for bugs/issues, implements verified fixes, and opens Pull Requests while enforcing anti-spam rules. Trigger with 'begin github action'."
---

# GitHub Autonomous Agent Skill

This skill provides comprehensive instructions for running and orchestrating the Autonomous GitHub Agent inside Google Antigravity.

## Triggers
Activate this skill when the user states:
- `"begin github action"`
- `"start github agent"`
- `"run github workflow"`
- Or asks to autonomously triage GitHub inbox or search and fix top-tier repo issues.

---

## Capabilities & Architecture

The system consists of two primary continuous workflows running concurrently:

1. **Inbox & Notification Manager**:
   - Fetches unread notifications across repositories.
   - Evaluates mentions, review requests, issue assignments, and discussion replies.
   - Determines if action/response is needed.
   - Generates contextual, technically sound responses and replies.
   - Marks handled notifications as read.

2. **Top-Tier Open Source Issue Hunter & PR Solver**:
   - Searches issues and verifies repository star counts using repository metadata for `is:issue is:open no:assignee label:"good first issue"` or `label:"bug"`.
   - Filters for issues with clear repro steps or reproducible error traces.
   - Clones/Forks the repository to a workspace sandbox.
   - Diagnoses root cause, implements the minimal required code fix.
   - Requires passing baseline tests, a failing regression before the fix, passing patched tests, and verification of the committed repair. Repository-specific lint rules may require additional integration.
   - Commits with descriptive conventional commit message.
   - Checks fork ownership, pushes successfully, and creates a draft Pull Request with executed verification evidence.

---

## Operating Instructions

### Step 1: Check Environment & Credentials
Check that GitHub CLI (`gh`) is authenticated and API keys are accessible:
```bash
gh auth status
```
GitHub and model authentication are independent. For Antigravity, configure `AI_PROVIDER=antigravity` and authenticate `agy`; use `agy models` for actual model IDs. Direct Gemini inference needs `GEMINI_API_KEY` and a supported Gemini API model. Run `./run.sh doctor` to verify GitHub, real inference, and isolated test execution.

### Step 2: Running Autonomous Execution
To launch the agent orchestrator in continuous multi-task mode:

- **Dry-run mode (Recommended for first run / preview)**:
  ```bash
  ./run.sh start --dry-run
  ```
- **Live autonomous mode**:
  ```bash
  ./run.sh start --live
  ```
- **Inbox-only mode**:
  ```bash
  ./run.sh inbox
  ```
- **Issue hunting & solving only**:
  ```bash
  ./run.sh solve --auto
  ```

Dry-run is the default. Explicit `--live` enables external GitHub writes; honor the user's requested mode. The scheduler repeats while its foreground process is alive, with finite model requests and configured waits. It is not a supervised background service. The dashboard served by `start` can pause/resume and queue work; the standalone `web` command cannot execute workers.

### Step 3: Stopping Autonomous Execution
When the user says `"stop github action"`, send SIGINT or use the authenticated running-process control endpoint through:
```bash
./run.sh stop
```

---

## Strict Quality & Etiquette Checklist
Before any PR is created:
1. `CONTRIBUTING.md` has been read and respected.
2. Issue is not assigned to anyone else and has no active PRs in progress.
3. New regression fails before the fix, then the patched suite and exact committed repair pass existing test suites (e.g., `pytest`, `npm test`, `cargo test`, `go test`).
4. PR description explains:
   - Summary of the problem.
   - Root cause analysis.
   - How the fix resolves the problem.
   - Step-by-step verification and test output.
