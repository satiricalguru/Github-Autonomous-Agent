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
   - Searches top starred repositories (e.g. `stars:>1000`, active commits) for `is:issue is:open no:assignee label:"good first issue"` or `label:"bug"`.
   - Filters for issues with clear repro steps or reproducible error traces.
   - Clones/Forks the repository to a workspace sandbox.
   - Diagnoses root cause, implements the minimal required code fix.
   - Executes unit tests and linter suites.
   - Commits with descriptive conventional commit message.
   - Pushes branch to fork and opens a complete, professional Pull Request.

---

## Operating Instructions

### Step 1: Check Environment & Credentials
Check that GitHub CLI (`gh`) is authenticated and API keys are accessible:
```bash
gh auth status
```
If using Gemini API directly for LLM reasoning, ensure `GEMINI_API_KEY` is loaded or `gh` auth keyring is active.

### Step 2: Running Autonomous Execution
To launch the agent orchestrator in continuous multi-task mode:

- **Dry-run mode (Recommended for first run / preview)**:
  ```bash
  python3 -m src.cli start --dry-run
  ```
- **Live autonomous mode**:
  ```bash
  python3 -m src.cli start
  ```
- **Inbox-only mode**:
  ```bash
  python3 -m src.cli inbox
  ```
- **Issue hunting & solving only**:
  ```bash
  python3 -m src.cli solve --auto
  ```

### Step 3: Stopping Autonomous Execution
When the user says `"stop github action"`, send SIGINT or run:
```bash
python3 -m src.cli stop
```

---

## Strict Quality & Etiquette Checklist
Before any PR is created:
1. `CONTRIBUTING.md` has been read and respected.
2. Issue is not assigned to anyone else and has no active PRs in progress.
3. Code changes pass existing test suites (e.g., `pytest`, `npm test`, `cargo test`, `go test`).
4. PR description explains:
   - Summary of the problem.
   - Root cause analysis.
   - How the fix resolves the problem.
   - Step-by-step verification and test output.
