# QA review: DX-01b Root README

- Reviewer: qa-engineer (QA-06) · Date: 2026-10-21
- Target: `orch/DX-01b-readme` @ **f008d45** (3 commits on `main` 66e9f7b, no rebase needed). Files: `README.md` (rewritten, +207), `.gitignore` (+`.localetl/`), `scripts/README.md` (volume name).
- Method: every command, flag, message, port and default in the README checked against the merged scripts, `.env.example`, `docs/requirements.md` and `docs/architecture.md`; cheap commands were run earlier in this session (DX-01a). The suites were not looped.

## Verdict: **CHANGES REQUESTED** (two small text corrections; nothing else blocks)

## Findings
**F1 (medium, instructions that would not work): the "Port 5432 already in use" troubleshooting row.** It says to set `POSTGRES_PORT=55432` in `.env` and change the port in both `DATABASE_URL` and `TEST_DATABASE_URL` there. That works for `scripts/dev.sh` (it reads `.env`), but `scripts/test-all.sh` and `scripts/e2e.sh` do not read `.env` (the README itself says so under Configuration). They derive their URLs from `POSTGRES_PORT`/`DATABASE_URL`/`TEST_DATABASE_URL` in the *environment* (`test-all.sh` lines 29–31; the backend has `env_file=None`). A user who follows the row and then runs `scripts/test-all.sh` would hit 5432 again. Suggested text: "For `dev.sh`: set `POSTGRES_PORT=55432` and the matching port in `DATABASE_URL` in `.env`. For `test-all.sh`, `e2e.sh` and `dev-up.sh` used on their own, export it: `POSTGRES_PORT=55432 scripts/test-all.sh`."

**F2 (low, inaccurate): "The worker finishes its current step and exits"** (Stop section). REQ-44 and WK-03 say the worker stops claiming, stops the current run at the next stage or chunk boundary, marks it `interrupted`, and exits (verified by the signal tests). Suggested: "The worker stops claiming runs, interrupts the active run at the next stage or chunk boundary (it ends `interrupted`) and exits."

## What checks out
| Area | Result |
|---|---|
| Commands and flags | `scripts/setup.sh`, `dev.sh`, `stop.sh [--db]`, `build.sh`, `dev-up.sh`, `test-all.sh [--skip-db] [--skip-frontend]`, `e2e.sh`, `PYTHON_BIN`, `LOCALETL_ALLOW_ANY_NODE=1`, `npm --prefix tests/e2e ci` and `run install:browser`, `LOCALETL_PERF=1 pytest tests/perf -s` all exist and behave as described (all exercised during DX-01a/QA-08/QA-09; the perf run is about 3 minutes) |
| Messages quoted in Troubleshooting | Match the scripts: "the dev stack is already running", "port N is already in use", "backend/.venv not found", "node_modules not found", "Node 22 is required" |
| Configuration | Order environment > `.env` > `.env.example`; plain-`KEY=VALUE` parsing, one layer of quotes, key allowlist from `.env.example`; "backend does not read `.env`" (`env_file=None`); `test-all`/`e2e` use only the environment. Variable table and defaults match `.env.example` and architecture §4 (DATABASE_URL, TEST_DATABASE_URL, LOCALETL_DATA_DIR `./data`, 100 MB, CORS origins, chunk 50000, worker 2/10/60, VITE vars, POSTGRES_*) |
| Features | Match requirements: one CSV at a time, 100 MB default (REQ-01/02), encodings and delimiters (REQ-03, also the UI lists), staging then publish (REQ-30), `replace`/`append`, one running run (REQ-41), recovery and clean shutdown, explorer and profile charts |
| Stack and versions | Python 3.11–3.12, Node 22, PostgreSQL 16 (`postgres:16` in compose), React/Vite/Tailwind/Recharts/Vitest/Playwright all present in the package files |
| Architecture and limitations | Diagram and bullets match §7.2 (SKIP LOCKED claim, queued run, staging/datasets schemas). The "exclusive lock while publishing a replace" matches the publish step (drop + schema move in one transaction); the post-publish crash limitation matches my WK-02 note; Chromium-only matches QA-08 |
| Secrets | None beyond the documented local-dev defaults (`localetl:localetl`); nothing else sensitive added |
| `.gitignore`, `scripts/README.md` | `.localetl/` added; volume name `localetl_localetl_pgdata` matches `docker volume ls` |

## Notes (non-blocking)
1. The Node row says "npm bundled with Node 22", consistent with setup.sh; Node 23 users need the documented override.
2. `git clone <your-repository-url>`: the repository has no remote yet; fine as a placeholder.
