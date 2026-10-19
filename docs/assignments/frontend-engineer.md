# Assignment: Frontend Engineer, Wave 1

You are the **frontend-engineer** for LocalETL, running in your own Git worktree `.claude/worktrees/agent-frontend`.
Your lane is **FE-01 → FE-05** in `docs/task-board.md`. Work on nothing else.

## 0. Re-sync (do this first in a fresh session)
Your worktree was created before the project foundation existed. Earlier context you may have is obsolete.
1. Confirm you are on the foundation: `git log --oneline -3` must show the foundation commit recorded at the end of `docs/task-board.md`, and `git status` must be clean.
2. Reread, in this order: `CLAUDE.md`, `docs/requirements.md`, `docs/architecture.md` (focus: §2 toolchain, §3 ownership, §9 frontend), `contracts/openapi.yaml`, `contracts/pipeline.schema.json`, `contracts/examples/pipeline/`, and `docs/task-board.md`.
3. If any of these files is missing or empty, **stop** and report "Blocked: foundation not present in worktree".

## 1. Gate check (before every ticket)
- Start the first ticket in your order below whose dependencies are **Done** on the board (merged to `main`).
- A "*before review*" dependency lets you code now, but you may not submit until it is Done.
- Within your own lane you may stack on a predecessor that is *In review*: branch from its branch, say so in your report, and rebase onto `main` after it merges. Never stack on another lane's branch.
- If nothing is startable, report which dependency each ticket is waiting on and stop.

## 2. Working protocol
- Per ticket: `git switch -c fe/<TICKET-ID>-<slug> main`. Your worktree shares refs with the main checkout, so `main` is always current; no fetch needed.
- Edit only the ticket's listed files plus new files inside paths you own (architecture §3). Never edit `contracts/`, `docs/` (except `docs/qa/` for QA), `CLAUDE.md`, `.claude/agents/`, `.env.example`, or another agent's paths.
- If a contract or the architecture does not answer a question, stop and report the gap. Do not guess interfaces.
- No dependency outside architecture §2 without a one-line justification in your report.
- Commits are small and prefixed with the ticket ID (`FE-01: ...`).
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
| 1 | FE-01 Scaffold and app shell | W0 | Install Recharts now so Wave 2 doesn't touch `package.json`. |
| 2 | FE-02 Generated types, client, typed mocks | FE-01 | Generate types; never hand-write API types. |
| 3 | FE-04 Pipeline builder | FE-02 | Most complex screen; use the contract examples as test inputs. |
| 4 | FE-03 Sources upload and preview | FE-02 | |
| 5 | FE-05 Run controls, monitoring, history | FE-02 | Metrics as text; charts are Wave 2. |

No backend is needed: develop against the typed mocks from FE-02. Do not create `src/features/analytics/` or `src/features/explorer/` (visualization-engineer, Wave 2). If you build a shared component visualization will need, note it in your report.

## 5. Commands
- `npm --prefix frontend ci` · `npm --prefix frontend test` · `npm --prefix frontend run lint` · `npm --prefix frontend run build` · `npx --prefix frontend tsc --noEmit -p frontend`
- Types: `npx openapi-typescript contracts/openapi.yaml -o frontend/src/app/api/schema.d.ts`

## Start now
Do steps 0 and 1, then begin FE-01.
