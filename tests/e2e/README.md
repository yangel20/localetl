# End-to-end demo (QA-08, MVP gate)

One Playwright test drives the real product through a browser: upload a CSV, configure and save a
pipeline, run it, wait for `Succeeded`, check the run counters, see the dataset rows and profile
charts in the explorer, and see the run charts on Home.

## Run

```sh
docker compose up -d db                       # PostgreSQL (role can CREATE DATABASE)
python -m pip install -e 'backend[dev]'       # once
npm --prefix frontend ci                      # once
npm --prefix tests/e2e ci                     # once
npm --prefix tests/e2e run install:browser    # once: downloads Chromium for the pinned Playwright
PYTHON=python scripts/e2e.sh                  # starts the stack, runs the test, stops everything
```

`scripts/e2e.sh` creates a throwaway database (`localetl_e2e_*`) and data directory, runs
`alembic upgrade head`, starts uvicorn (`:18000`), the real worker (`python -m app.worker`) and a
built frontend served by `vite preview` (`:15173`), then runs the suite and always tears everything
down. It fails if the worker does not exit 0 on SIGTERM. Use `--stack-only` to keep the stack up for
manual exploration, or `-- <command>` to run something else against it (`E2E_WEB_URL`,
`E2E_API_URL`, `E2E_DATABASE_URL` are exported). Ports: `E2E_API_PORT`, `E2E_WEB_PORT`.

## Artifacts

Video, trace and screenshot of each run are written to `tests/e2e/test-results/`, and the HTML report
to `tests/e2e/playwright-report/`. Both directories are gitignored (root `.gitignore`).
View a trace with `npx playwright show-trace tests/e2e/test-results/<test>/trace.zip`.

## Dependencies

| Package | Version | Why |
|---|---|---|
| `@playwright/test` | 1.62.1 (exact) | Browser automation, assertions, video and trace recording. It is the only dependency; it downloads its own Chromium. |
