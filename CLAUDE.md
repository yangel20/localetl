# LocalETL — Project Instructions

## Mission
Build a local-first ETL web application with:
- React + TypeScript + Tailwind + Recharts
- Python FastAPI + Pandas + SQLAlchemy
- PostgreSQL
- A dedicated local background worker

## Architecture
Frontend communicates with FastAPI over HTTP.
The ETL engine must be usable independently of the API.
A worker executes queued pipeline jobs.
PostgreSQL stores application metadata and ETL results.

## Source of Truth
Read these files before implementation:
- docs/architecture.md
- docs/requirements.md
- contracts/openapi.yaml
- contracts/pipeline.schema.json
- docs/task-board.md

Do not invent a competing API contract.

Also binding: `contracts/examples/pipeline/` (valid/invalid configs) and
`.env.example` (the full list of environment variables).

Precedence when sources disagree: `contracts/` > `docs/architecture.md` >
`docs/requirements.md` > ticket text > agent definition. Report the
disagreement instead of picking one silently.

## MVP Scope
- CSV file upload and preview
- Saved pipeline configurations
- Configurable cleaning and validation
- PostgreSQL loading
- Manual job execution and monitoring
- Execution history and metrics
- Dataset preview and basic charts

## Engineering Rules
1. Work only on assigned tickets.
2. Respect file and directory ownership.
3. Do not change shared contracts without approval.
4. Do not add dependencies without documenting why.
5. Use type hints in Python and TypeScript types.
6. Write tests for new business logic.
7. Never use arbitrary eval or execute user Python.
8. Use safe SQL identifiers and parameter binding.
9. Keep database credentials in environment variables.
10. Never commit .env or uploaded user data.
11. Report blockers instead of guessing interfaces.
12. Run relevant tests before reporting completion.

## Completion Report
Every agent must report:
- Ticket IDs completed
- Branch and commit hashes
- Files changed
- Tests executed and their results
- Known limitations or blockers
- Any proposed contract changes

## Orchestrator Rules
- Manage task dependencies before delegation.
- Prefer independent tasks for parallel execution.
- Review each deliverable before integration.
- Do not merge failing tests.
- Do not mark MVP complete without an E2E demo.

## Ownership
The ownership table in `docs/architecture.md` section 3 is authoritative.
Edit only paths you own. Shared files (`CLAUDE.md`, `contracts/`, `docs/`
except `docs/qa/`, `.claude/agents/`, `.env.example`, `.gitignore`,
`README.md`, and `backend/pyproject.toml` after BE-01 merges) are
orchestrator-only. Propose changes in your completion report.

## Interface Rules
- The ETL engine's public API is exactly the names in `docs/architecture.md`
  section 5, exported from `backend/app/etl/__init__.py`.
- `app.etl` must not import FastAPI, `app.api`, `app.models`, `app.schemas`,
  `app.core`, `app.worker` or `app.services`.
- Only the worker changes a run's status after `queued`.
- The ETL engine writes only to the `staging` and `datasets` schemas; app
  metadata lives in `public` and is changed only through Alembic migrations.

## Git Workflow (Option B: one worktree per agent)
- Each agent session runs in its own worktree under `.claude/worktrees/`.
- One branch per ticket, created from `main`:
  `<lane>/<TICKET-ID>-<slug>` with lanes `etl`, `be`, `fe`, `qa`, `wk`, `viz`.
- Commit messages start with the ticket ID, e.g. `ETL-03: validate config`.
- Agents never merge to `main`, rebase `main`, force-push, or run
  `git reset --hard`, `git clean`, or `git worktree remove`.
- Before submitting for review, rebase your ticket branch onto current
  `main` and rerun tests.
- Only the orchestrator merges, from the main checkout, after a QA PASS.

## Commands
- DB: `docker compose up -d db` (after QA-01 merges)
- Python: `cd backend && python3.11 -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]'`
- Python tests: `pytest backend/tests/<area>`; types: `mypy backend/app`
- Frontend: `npm --prefix frontend ci`, `npm --prefix frontend test`,
  `npm --prefix frontend run lint`, `npm --prefix frontend run build`
- Contract types: `npx openapi-typescript contracts/openapi.yaml -o frontend/src/app/api/schema.d.ts`
- Contract lint: `npx @redocly/cli@1.25.0 lint contracts/openapi.yaml`
