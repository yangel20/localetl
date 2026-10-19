# Assignment: ETL Engineer, Wave 1

You are the **etl-engineer** for LocalETL, running in your own Git worktree `.claude/worktrees/agent-etl`.
Your lane is **ETL-01 → ETL-07** in `docs/task-board.md`. Work on nothing else.

## 0. Re-sync (do this first in a fresh session)
Your worktree was created before the project foundation existed. Earlier context you may have is obsolete.
1. Confirm you are on the foundation: `git log --oneline -3` must show the foundation commit recorded at the end of `docs/task-board.md`, and `git status` must be clean.
2. Reread, in this order: `CLAUDE.md`, `docs/requirements.md`, `docs/architecture.md` (focus: §3 import rules, §5 engine interface, §6 semantic rules, §7.3 physical tables), `contracts/pipeline.schema.json`, `contracts/examples/pipeline/`, and `docs/task-board.md`.
3. If any of these files is missing or empty, **stop** and report "Blocked: foundation not present in worktree".

## 1. Gate check (before every ticket)
- Start the first ticket in your order below whose dependencies are **Done** on the board (merged to `main`).
- A "*before review*" dependency lets you code now, but you may not submit until it is Done.
- Within your own lane you may stack on a predecessor that is *In review*: branch from its branch, say so in your report, and rebase onto `main` after it merges. Never stack on another lane's branch.
- If nothing is startable, report which dependency each ticket is waiting on and stop.

## 2. Working protocol
- Per ticket: `git switch -c etl/<TICKET-ID>-<slug> main`. Your worktree shares refs with the main checkout, so `main` is always current; no fetch needed.
- Edit only the ticket's listed files plus new files inside paths you own (architecture §3). Never edit `contracts/`, `docs/` (except `docs/qa/` for QA), `CLAUDE.md`, `.claude/agents/`, `.env.example`, or another agent's paths.
- If a contract or the architecture does not answer a question, stop and report the gap. Do not guess interfaces.
- No dependency outside architecture §2 without a one-line justification in your report.
- Commits are small and prefixed with the ticket ID (`ETL-01: ...`).
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

| # | Ticket | Depends on | Why this order |
|---|---|---|---|
| 1 | ETL-01 Public types, errors, stubs | W0 · *before review:* BE-01 | Backend and worker code against these names. Until BE-01 merges, use a temporary venv in your worktree (`python3.11 -m venv .venv && .venv/bin/pip install pandas sqlalchemy jsonschema pytest mypy pandas-stubs`). |
| 2 | ETL-03 Config validation | ETL-01 | Unblocks BE-04. |
| 3 | ETL-02 CSV inspect and preview | ETL-01 | Unblocks BE-03. |
| 4 | ETL-04 Transform stage | ETL-03 | |
| 5 | ETL-05 Validate stage | ETL-03 | Can run in parallel with ETL-04 if you stack. |
| 6 | ETL-06 Load and publish | ETL-01, QA-01 | Needs Postgres (`docker compose up -d db`). |
| 7 | ETL-07 `run_pipeline` | ETL-02, ETL-04, ETL-05, ETL-06 | Worker (Wave 2) depends on it. |

Acceptance criteria and file lists on the board are binding. The signatures in architecture §5 are the agreed engine interface. Do not change them; propose changes instead.

## 5. Commands
- Tests: `pytest backend/tests/etl` · Types: `mypy --strict backend/app/etl`
- After BE-01 merges: `cd backend && pip install -e '.[dev]'`

## Start now
Do steps 0 and 1, then begin ETL-01.
