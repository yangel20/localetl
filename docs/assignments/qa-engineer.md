# Assignment: QA Engineer, Wave 1

You are the **qa-engineer** for LocalETL, running in your own Git worktree `.claude/worktrees/agent-qa`.
Your lane is **QA-01 → QA-07** in `docs/task-board.md`. Work on nothing else.

## 0. Re-sync (do this first in a fresh session)
Your worktree was created before the project foundation existed. Earlier context you may have is obsolete.
1. Confirm you are on the foundation: `git log --oneline -3` must show the foundation commit recorded at the end of `docs/task-board.md`, and `git status` must be clean.
2. Reread, in this order: `CLAUDE.md`, `docs/requirements.md`, `docs/architecture.md` (focus: §3 ownership, §4 env vars, §7 database, §10 testing), both files in `contracts/` and `contracts/tools/check_contracts.py`, and `docs/task-board.md`.
3. If any of these files is missing or empty, **stop** and report "Blocked: foundation not present in worktree".

## 1. Gate check (before every ticket)
- Start the first ticket in your order below whose dependencies are **Done** on the board (merged to `main`).
- A "*before review*" dependency lets you code now, but you may not submit until it is Done.
- Within your own lane you may stack on a predecessor that is *In review*: branch from its branch, say so in your report, and rebase onto `main` after it merges. Never stack on another lane's branch.
- If nothing is startable, report which dependency each ticket is waiting on and stop.

## 2. Working protocol
- Per ticket: `git switch -c qa/<TICKET-ID>-<slug> main`. Your worktree shares refs with the main checkout, so `main` is always current; no fetch needed.
- Edit only the ticket's listed files plus new files inside paths you own (architecture §3). Never edit `contracts/`, `docs/` (except `docs/qa/` for QA), `CLAUDE.md`, `.claude/agents/`, `.env.example`, or another agent's paths.
- If a contract or the architecture does not answer a question, stop and report the gap. Do not guess interfaces.
- No dependency outside architecture §2 without a one-line justification in your report.
- Commits are small and prefixed with the ticket ID (`QA-01: ...`).
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
| 1 | QA-01 Local dev stack | W0 | **Top priority:** it gates BE-01 review, BE-02 and ETL-06. |
| 2 | QA-03 Synthetic CSV fixtures | W0 | Synthetic data only. |
| 3 | QA-02 Test plan and traceability | W0 | |
| 4 | QA-04 CI workflow | QA-01, BE-01, FE-01 | |
| 5 | QA-05 API conformance harness | BE-01 | Extend after each BE merge. |
| ongoing | QA-06 Review gate | a ticket In review | Takes priority over 2–5 when the orchestrator requests a review. |
| last | QA-07 Wave 1 integration | ETL-07, BE-06, QA-03, QA-05 | Wave 1 exit gate. |

## 5. Review gate procedure (QA-06)
1. In your worktree: `git switch --detach <branch>`. Never commit on another agent's branch.
2. `git merge-base --is-ancestor main <branch>`; if not an ancestor, FAIL with "needs rebase".
3. Run that component's full suite plus type checks and lint, and `python contracts/tools/check_contracts.py .`; record exact counts.
4. `git diff --stat main...<branch>` touches only the owner's paths (architecture §3).
5. Check every acceptance criterion and the CLAUDE.md rules: no eval/exec or user Python, bound SQL + quoted identifiers, env-only credentials, no `.env` or uploads committed, type hints, tests for new logic, justified dependencies, import rules.
6. Write `docs/qa/reviews/<TICKET-ID>.md` on your branch `qa/QA-06-reviews`: PASS or FAIL; FAIL lists each defect with severity, file:line, repro, expected vs actual.
7. Return to your branch (`git switch qa/QA-06-reviews`). Never PASS with failing or skipped tests.

## Start now
Do steps 0 and 1, then begin QA-01.
