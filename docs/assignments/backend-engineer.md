# Assignment: Backend Engineer, Wave 1

You are the **backend-engineer** for LocalETL, running in your own Git worktree `.claude/worktrees/agent-backend`.
Your lane is **BE-01 → BE-06** in `docs/task-board.md`. Work on nothing else.

## 0. Re-sync (do this first in a fresh session)
Your worktree was created before the project foundation existed. Earlier context you may have is obsolete.
1. Confirm you are on the foundation: `git log --oneline -3` must show the foundation commit recorded at the end of `docs/task-board.md`, and `git status` must be clean.
2. Reread, in this order: `CLAUDE.md`, `docs/requirements.md`, `docs/architecture.md` (focus: §3 ownership and import rules, §4 env vars, §7 database and run state machine, §8 HTTP notes), `contracts/openapi.yaml`, `contracts/pipeline.schema.json`, and `docs/task-board.md`.
3. If any of these files is missing or empty, **stop** and report "Blocked: foundation not present in worktree".

## 1. Gate check (before every ticket)
- Start the first ticket in your order below whose dependencies are **Done** on the board (merged to `main`).
- A "*before review*" dependency lets you code now, but you may not submit until it is Done.
- Within your own lane you may stack on a predecessor that is *In review*: branch from its branch, say so in your report, and rebase onto `main` after it merges. Never stack on another lane's branch.
- If nothing is startable, report which dependency each ticket is waiting on and stop.

## 2. Working protocol
- Per ticket: `git switch -c be/<TICKET-ID>-<slug> main`. Your worktree shares refs with the main checkout, so `main` is always current; no fetch needed.
- Edit only the ticket's listed files plus new files inside paths you own (architecture §3). Never edit `contracts/`, `docs/` (except `docs/qa/` for QA), `CLAUDE.md`, `.claude/agents/`, `.env.example`, or another agent's paths.
- If a contract or the architecture does not answer a question, stop and report the gap. Do not guess interfaces.
- No dependency outside architecture §2 without a one-line justification in your report.
- Commits are small and prefixed with the ticket ID (`BE-01: ...`).
- Before submitting: `git rebase main`, then rerun every relevant test. Never report done with failing or skipped tests.
- Never merge to `main`, force-push, `git reset --hard`, `git clean`, or remove worktrees.
- When a ticket meets all acceptance criteria, post the completion report and **wait** for the orchestrator before starting the next ticket.

## 3. Completion report (per ticket)
- Ticket ID
- Branch and commit hashes (`git log --oneline main..HEAD`)
- Files changed (`git diff --stat main...HEAD`)
- Tests: exact commands and pass/fail counts
- Known limitations or blockers
- Proposed contract or shared-file changes (or "none")

## 4. Your tickets, in order

| # | Ticket | Depends on | Notes |
|---|---|---|---|
| 1 | BE-01 Scaffold, settings, errors, health | W0 · *before review:* QA-01 | Creates `backend/pyproject.toml`, which every Python agent needs, so treat it as top priority. Until QA-01 merges you may start Postgres ad hoc for local testing, but don't commit compose files (QA owns them). |
| 2 | BE-02 Models and migrations | BE-01, QA-01 | Exactly architecture §7.1, including both partial unique indexes. |
| 3 | BE-03 Sources endpoints | BE-02, ETL-02 | Call `app.etl` public names only. |
| 4 | BE-04 Pipelines endpoints | BE-03, ETL-03 | Validation only via `validate_pipeline_config`. |
| 5 | BE-05 Runs endpoints | BE-04 | Never execute pipelines in the API. |
| 6 | BE-06 Datasets and metrics + drift test | BE-05 | |

Every path, method, status code and field must match `contracts/openapi.yaml`. Replace FastAPI's default 422 body with the contract `Error`. Cross-lane dependencies count only when merged to `main`.
After BE-01 merges, `backend/pyproject.toml` is orchestrator-owned: propose dependency changes in your report.

## 5. Commands
- `cd backend && python3.11 -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]'`
- `pytest backend/tests/api backend/tests/models` · `mypy backend/app` · `alembic -c backend/alembic.ini upgrade head`

## Start now
Do steps 0 and 1, then begin BE-01.
