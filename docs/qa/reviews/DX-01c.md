# QA record: DX-01c Clean-clone walkthrough

- Recorder/reviewer: qa-engineer (QA-06) · Date: 2026-10-21
- Walkthrough author: agent-frontend (independent of the script author), reported through the orchestrator. The walkthrough itself was **not repeated by QA**; this file records its report and my independent spot checks.
- Setup reported: fresh clone at `/private/tmp/claude-501/dx01c/localetl` @ **01ed3f4** (current `main` at the time), `COMPOSE_PROJECT_NAME=localetl-dx01c`, `POSTGRES_PORT=55433`, following the README only. Node 23, so `LOCALETL_ALLOW_ANY_NODE=1` was used.

## Reported result: 7 of 7 PASS
| # | Step | Reported outcome |
|---|---|---|
| 1 | `scripts/setup.sh` twice | Idempotent: `.env` sha, venv, `pip freeze` hash and volume list identical |
| 2 | `scripts/build.sh` | OK |
| 3 | `scripts/dev.sh` | Started (API health OK, :5173 returned 200); a second start was refused |
| 4 | CSV run via the API (`orders_full.json`) | Succeeded, 200 extracted / 200 loaded / 0 rejected; the real worker claimed it |
| 5 | Ctrl+C (SIGINT to the process group) and `scripts/stop.sh` | Both: worker exit 0, no orphans, PID file removed, ports free; the main dev stack (`localetl-db-1`, volume `localetl_localetl_pgdata`) untouched |
| 6 | README commands as written | Worked as written |
| 7 | `POSTGRES_PORT=55433 scripts/test-all.sh` | 16/16 |

Final `scripts/stop.sh --db` OK. Left in place by the walkthrough: stopped container `localetl-dx01c-db-1`, volume `localetl-dx01c_localetl_pgdata`, and the clone directory.

## QA spot checks (cheap, independent)
- **Isolation:** `docker ps -a` shows the main `localetl-db-1` Up and healthy, the walkthrough's `localetl-dx01c-db-1` Exited (0), and both volumes present (`localetl_localetl_pgdata`, `localetl-dx01c_localetl_pgdata`). So the second Compose project did not touch the dev stack.
- **No orphans:** no uvicorn/worker/vite processes, ports 8000 and 5173 are free, and the clone's `.localetl/` contains only `logs/` (no PID file).
- **Left-over resources** (for the user to remove; nothing here deletes volumes, and QA will not): container `localetl-dx01c-db-1`, volume `localetl-dx01c_localetl_pgdata`, directory `/private/tmp/claude-501/dx01c/`. Removing them is a manual `COMPOSE_PROJECT_NAME=localetl-dx01c docker compose down -v` in the clone plus deleting the folder.

## Gaps reported and my assessment
| Gap | Assessment |
|---|---|
| G1 second stack / `COMPOSE_PROJECT_NAME` undocumented | Real; addressed by the README change re-checked below |
| G2 port must be edited in three places | Real; addressed by the README change re-checked below |
| G3 `stop.sh` prints alarming "skip … not signalled" lines after a normal launcher shutdown | Confirmed, I saw the same in DX-01a. Cosmetic only (nothing is mis-signalled; the PID file is cleared and the worker exits 0). **Proposed fix, not approved:** after the launcher stops, print one line ("launcher stopped the stack") and list "skip" lines only for entries that still exist but fail verification (mismatched command or start time). Owner: QA (scripts/), needs the user's approval as a new ticket |
| G4 Node override scope | Addressed by the README change re-checked below |
| G5 Ctrl+C not tested in a real interactive terminal | **Untested.** An agent cannot drive a real TTY. SIGINT to the process group (what a terminal Ctrl+C sends) was tested here (DX-01a) and by the walkthrough; a human check in a real terminal is still recommended before calling the DX done |

## Re-check: README fixes for G1, G2, G4 at `orch/DX-01b-readme` @ **3f6c2b4** — **PASS**
Base `main` 01ed3f4; `README.md` only (+4/-1).
1. **G4 (Node scope):** "Only `setup.sh` checks the Node version; the other scripts need no override." Accurate: `dev.sh`, `build.sh` and `e2e.sh` have no Node version check (only npm's `EBADENGINE` warnings appear on Node 23).
2. **G2 (three values):** "edit `POSTGRES_PORT` and the port inside `DATABASE_URL` and `TEST_DATABASE_URL` together." Accurate for `dev.sh`/Compose. As in DX-01b F1, `test-all.sh` does not read `.env`, so the tests need `POSTGRES_PORT=… scripts/test-all.sh` in the environment, which the earlier troubleshooting row already says.
3. **G1 (`COMPOSE_PROJECT_NAME`):** "`export COMPOSE_PROJECT_NAME=localetl-2` in the shell (`dev.sh` ignores keys not in `.env.example`), and a free port such as 55433 in the three `.env` values." **Accurate.** `docker-compose.yml` pins `name: localetl`, and its header comment says `COMPOSE_PROJECT_NAME` (or `-p`) overrides it; the walkthrough's resulting names (`localetl-dx01c-db-1`, `localetl-dx01c_localetl_pgdata`) confirm the override works. Putting it only in `.env` would not be read by `dev.sh` (not an `.env.example` key; it would be skipped with a warning), although Compose itself also reads a root `.env`, so exporting it in the shell is the reliable instruction, as written. "Ports 8000 and 5173 are fixed, so only one stack can run `dev.sh` at a time" is accurate (dev.sh refuses when they are in use).
- Nit (non-blocking): the second-stack row could add "and run tests with `POSTGRES_PORT=55433 scripts/test-all.sh`", the step the walkthrough actually used (step 7).
