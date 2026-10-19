# Wave 1 Runbook (Option B: worktrees)

Orchestrator commands run from the main checkout: `/Users/yangel/Desktop/localetl`.

## 1. Worktrees

| Agent | Worktree | Parking branch | Ticket branches |
|---|---|---|---|
| etl-engineer | `.claude/worktrees/agent-etl` | `worktree-agent-etl` | `etl/ETL-xx-*` |
| backend-engineer | `.claude/worktrees/agent-backend` | `worktree-agent-backend` | `be/BE-xx-*` |
| frontend-engineer | `.claude/worktrees/agent-frontend` | `worktree-agent-frontend` | `fe/FE-xx-*` |
| qa-engineer | `.claude/worktrees/agent-qa` | `worktree-agent-qa` | `qa/QA-xx-*` |

All worktrees share one repository, so `main` is visible everywhere as soon as it is committed. No fetch or push is involved.

## 2. Syncing an existing worktree to `main` (safe procedure)

For each worktree, never in bulk:

```sh
W=.claude/worktrees/agent-etl
git -C $W status --porcelain --untracked-files=all   # must be empty; if not, STOP and preserve (step 2a)
git -C $W log --oneline main..HEAD                   # agent commits not on main
git -C $W merge --ff-only main                       # if HEAD has no own commits
git -C $W merge --no-ff main                         # if it has commits (resolve conflicts; never discard)
git -C $W log --oneline -1                           # verify
test -s $W/CLAUDE.md && test -s $W/contracts/openapi.yaml && echo synced
```

2a. Preserving uncommitted work: `git -C $W stash push --include-untracked -m "pre-sync <date>"`, record the stash ref in the board, merge, then `git -C $W stash apply` (not `pop`) and resolve. Report before continuing.

## 3. Restarting sessions (required)

A running Claude Code session loaded `CLAUDE.md` at startup. Changing files on disk does **not** update it. Each running session must be exited (`/exit`, or Ctrl+C twice) and relaunched. A worktree counts as synchronized only after **both** checks pass:
1. its checkout is on the foundation (step 2 `verify`), and
2. a new session started in it has reported the step-0 re-sync check from its assignment.

## 4. Launch commands

One terminal tab per agent. Create the QA worktree once:

```sh
cd /Users/yangel/Desktop/localetl
git worktree add .claude/worktrees/agent-qa -b worktree-agent-qa main
```

Launch (or relaunch) each session from inside its worktree, with its agent and assignment:

```sh
cd /Users/yangel/Desktop/localetl/.claude/worktrees/agent-qa       && claude --agent qa-engineer       -n agent-qa       "$(cat docs/assignments/qa-engineer.md)"
cd /Users/yangel/Desktop/localetl/.claude/worktrees/agent-backend  && claude --agent backend-engineer  -n agent-backend  "$(cat docs/assignments/backend-engineer.md)"
cd /Users/yangel/Desktop/localetl/.claude/worktrees/agent-etl      && claude --agent etl-engineer      -n agent-etl      "$(cat docs/assignments/etl-engineer.md)"
cd /Users/yangel/Desktop/localetl/.claude/worktrees/agent-frontend && claude --agent frontend-engineer -n agent-frontend "$(cat docs/assignments/frontend-engineer.md)"
```

Launch in this order. QA-01 and BE-01 gate the most work, so they start first.

Note: the original three worktrees were created with `claude --worktree <name>`, which locks them while that session runs. The lock is released when the session exits. If a lock survives a crashed session, check that the PID in `.git/worktrees/<name>/locked` is gone before running `git worktree unlock <path>`.

## 5. Review and merge procedure (per ticket)

1. Agent posts the completion report. Board: **In review**.
2. Confirm the branch is rebased: `git merge-base --is-ancestor main <branch>`. If not, ask the agent to rebase and retest.
3. Ask QA (in `agent-qa`) to run the review gate for `<branch>`. Wait for `docs/qa/reviews/<ID>.md`. FAIL → back to the owner.
4. Orchestrator review: diff, ownership, contract adherence.
5. Trial merge, test, then commit or abort. Nothing is lost on failure:
   ```sh
   git merge --no-ff --no-commit <branch>
   python contracts/tools/check_contracts.py .
   <suites for the touched component, then all suites once QA-04 exists: scripts/test-all.sh>
   git commit -m "Merge <branch> (<ID>)"     # if green
   git merge --abort                         # if red: report to owner
   ```
6. Update the board on `main`: ticket **Done**, newly unblocked tickets **Ready**. Commit.
7. Tell affected agents: owners of newly Ready tickets start them; agents stacked on the merged branch rebase onto `main`.
8. Merge **one branch at a time**. Every later branch must rebase on the new `main` before its own trial merge.
   *Exception (user approved 2026-10-19, BE-01b / FE-01 / QA-03 only):* QA may review at the existing commit without a rebase if the branch is unaffected by Q3. The trial merge into current `main` (step 5), the contract check and the relevant tests are still mandatory; any conflict or incompatibility means rebase or request changes.

## 6. Merge order

Ordered so that each merge unblocks the most work, and so that tickets sharing a file land sequentially.

| Step | Merge | Unblocks |
|---|---|---|
| 1 | Foundation (Wave 0) | Everything |
| 2 | **QA-01** dev stack | BE-01 review, BE-02, ETL-06, QA-04 |
| 3 | **BE-01** scaffold + `pyproject.toml` | ETL-01 review, BE-02, QA-04, QA-05 |
| 4 | **ETL-01** public interface | ETL-02, ETL-03, ETL-06 |
| 5 | FE-01, QA-03, QA-02 (independent; any order) | FE-02, QA-07 input |
| 6 | **ETL-03**, then ETL-02 | BE-04, BE-03, ETL-04, ETL-05 |
| 7 | **BE-02** migrations | BE-03 |
| 8 | FE-02, QA-04 (CI) | FE-03/04/05; full-suite merges from here on |
| 9 | ETL-04, ETL-05, ETL-06 | ETL-07 |
| 10 | BE-03, QA-05 | BE-04 |
| 11 | FE-04, FE-03, FE-05 | none (frontend lane done) |
| 12 | BE-04 → BE-05 → BE-06 (QA-05 extended after each) | QA-07 |
| 13 | ETL-07 | QA-07 |
| 14 | **QA-07** integration, then a full-suite run on `main` | Wave 1 exit → plan Wave 2 |

Wave 1 exit: every ticket Done, `scripts/test-all.sh` green on `main`, QA-07 PASS, no open contract proposals.
