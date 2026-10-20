# LocalETL checkpoint (compact)

Updated 2026-10-20 (session end) by the orchestrator. Read this first; `docs/task-board.md` has detail; `SESSION_HANDOFF.md` is the 2026-10-19 history.

## State
- **Wave 1 complete**: all tickets Done, `scripts/test-all.sh` 16/16 on `main`, QA-07 PASS, no open contract proposals. Last merge: Q12-1 contract + FE-02s (`043bb8a`). `main` = `git log -1`.
- **Wave 2 approved, not started** (board "Wave 2"). No agent is working; all worktrees clean; no stashes.
- Shared Postgres: compose project `localetl`, container `localetl-db-1`, `127.0.0.1:55432`.

## Approvals and deferrals (2026-10-20, user)
- Wave 2 plan approved: WK-01→WK-02→WK-03 (worker-engineer), VIZ-01, VIZ-02 (visualization-engineer), FE-06, QA-07b, QA-09, QA-08 (MVP gate).
- New agents worker-engineer and visualization-engineer approved; **not launched** (commands below).
- QA-08: Playwright (`tests/e2e/package.json`) and a full-stack launcher script under `scripts/` approved; implement within QA-08 only.
- Hardening track deferred until Wave 2 core and QA are complete: Q8-2..12, Q9, Q10, Q12-2/3 (board "Open questions").

## Decided (binding)
Q1 · Q3 · Q4 (+a..d) · Q6-1 · Q6-3 (+C-a..e, `app/etl/casting.py`) · Q7 · Q8-1 · Q11 · Q12-1. Details in architecture §5/§6 and contracts.

## Resume
```sh
cd /Users/yangel/Desktop/localetl
git status && git log --oneline -3 && git worktree list
docker compose up -d --pull never db && POSTGRES_PORT=55432 scripts/dev-up.sh
# full check (venv: python3.11 -m venv .venv && .venv/bin/pip install -e 'backend[dev]')
PYTHON=.venv/bin/python DATABASE_URL=postgresql+psycopg://localetl:localetl@127.0.0.1:55432/localetl \
  TEST_DATABASE_URL=postgresql+psycopg://localetl:localetl@127.0.0.1:55432/localetl_test scripts/test-all.sh
```
Create the two new worktrees once (main checkout):
```sh
git worktree add .claude/worktrees/agent-worker -b worktree-agent-worker main
git worktree add .claude/worktrees/agent-viz    -b worktree-agent-viz    main
```
Launch (one terminal each):
```sh
cd /Users/yangel/Desktop/localetl && claude "Resume as LocalETL orchestrator. Read docs/checkpoints/CHECKPOINT.md, verify git state, then coordinate Wave 2 per the board."
cd /Users/yangel/Desktop/localetl/.claude/worktrees/agent-worker && claude --agent worker-engineer -n agent-worker "Read CLAUDE.md and docs/checkpoints/CHECKPOINT.md. Ticket WK-01 per docs/task-board.md (Wave 2). Branch wk/WK-01-claim-loop from main. Compact completion report: ticket+commit, files, tests, blockers, QA readiness."
cd /Users/yangel/Desktop/localetl/.claude/worktrees/agent-viz && claude --agent visualization-engineer -n agent-viz "Read CLAUDE.md and docs/checkpoints/CHECKPOINT.md. Ticket VIZ-01, then VIZ-02, per docs/task-board.md (Wave 2). Branch viz/VIZ-01-run-charts from main. Use the FE-02 client only. Compact completion report."
```
Existing agents (QA, frontend, backend, ETL) relaunch the same way from their worktree with `--agent <name> -n agent-<x>` and the prompt "Read CLAUDE.md and docs/checkpoints/CHECKPOINT.md; wait for assignment."

## Process (unchanged)
One branch per ticket from `main`; rebases keep a `-prerebase` backup; QA reviews every ticket (orchestrator reviews QA-owned ones); trial merge `--no-commit` + `test-all.sh`; merge the reviewed commit, never agent checkpoint commits. Contract changes merge together with the `schema.d.ts` regeneration. Compact prompts and reports; full suite only at merges; no polling.
