# LocalETL checkpoint (compact)

Updated 2026-10-20 by the orchestrator. Read this first; `docs/task-board.md` has detail, `SESSION_HANDOFF.md` is the 2026-10-19 history.

## Main
- `main` = see `git log -1` (last milestone: Q12-1 contract + FE-02s merge (Wave 1 exit criteria met)). `scripts/test-all.sh` 16/16 green.
- Shared Postgres: compose project `localetl`, container `localetl-db-1`, `127.0.0.1:55432`. Start with `POSTGRES_PORT=55432 scripts/dev-up.sh` (use `docker compose up -d --pull never db` first if offline). Tests use throwaway DBs.
- Full check: `PYTHON=<venv>/bin/python DATABASE_URL=…:55432/localetl TEST_DATABASE_URL=…:55432/localetl_test scripts/test-all.sh`. Install: `pip install -e 'backend[dev]'`.

## Done (Wave 1)
ETL-01, 02, 03, 03b, 04, 05, 06, 07 (engine complete) · BE-01, 01b, 02, 03, 04, 05, 06 · FE-01, 02, 02r, 03, 04, 05 · QA-01, 02, 02b, 03, 03b, 03c, 03d, 04, 05, 05b.

## Active
| Ticket | Owner | State |
|---|---|---|
| Wave 1 | — | **exit criteria met**: all tickets Done, test-all green, QA-07 PASS, no open contract proposals |
| Wave 2 | — | plan proposed, awaiting user approval (WK-01..03, VIZ-01..02, FE-06, QA-07b, QA-08, QA-09) |
| Wave 2 (WK-01..03, VIZ-01..02, QA-08) | — | not started; after QA-07 PASS |

## Decided (binding, in architecture §5/§6, contracts)
Q1 405 code · Q3 five counters · Q4 CSV structure (+Q4-a..d) · Q6-1 `format` wording · Q6-3 casting (+C-a..e, shared `app/etl/casting.py`) · Q7 validation semantics · Q8-1 `VITE_MAX_UPLOAD_MB` · Q11 runner (earliest-stage fail_run, `failed`+"interrupted", `EtlError.rejected_sample`) · Q12-1 declared 422/500 responses.

## Open for the user (board "Open questions")
Q8-2..12 (edge cases: `_localetl_` prefix, replace lock/timeout, strptime validity, quoting-fault value, config trimming, append order, faulty first record) · Q9 transform semantics (notably #3 replace_values config check, #5 round_number) · Q10 (constraints.txt, contracts/tools lint, NUL bytes) · Q12-2/3 (tmp cleanup, ETL-07 notes). None blocks current work.

## Process (unchanged)
One branch per ticket from `main`; agents rebase with a `-prerebase` backup; QA reviews every ticket (orchestrator reviews QA-owned tickets); orchestrator trial-merges `--no-commit`, runs checks, merges the reviewed commit, never the agent checkpoint commits. BE-0x merges together with its QA-05x coverage update.
Workflow: compact prompts and reports (ticket+commit, files, tests, blockers, QA readiness); focused tests while developing, `test-all.sh` at merges; no status polling.
