# QA review: VIZ-01 Run metrics charts

- Reviewer: qa-engineer (QA-06) · Date: 2026-10-21
- Target: `viz/VIZ-01-run-charts` @ **f6e22b1** (1 commit on `0b6c483`; not a descendant of current `main`, but `main` has no frontend changes since `0b6c483`, so no rebase needed for this review). 9 files, all under `frontend/src/features/analytics/**`; no changes to `src/app/api`, `package.json` or the lockfile; no new dependency (Recharts already present).
- Spec: board VIZ-01 row; REQ-52, REQ-55.

## Verdict: **PASS**

| Check | Result |
|---|---|
| REQ-52 stats | OK. Total runs, rows loaded, avg duration, success rate from `/metrics/summary` via the FE-02 client; null duration shown as "—"; success rate "—" when nothing finished |
| REQ-55 charts | OK. Stacked daily outcomes (succeeded/failed/interrupted) from `summary.daily`; loaded/rejected per run from `/runs?status=succeeded&limit=50`, newest 20, oldest first |
| Loading / empty / error | OK. `ChartFrame` handles all three per chart; tests cover loading, both empty states and an isolated per-chart error |
| Accessibility | OK. Each chart has an sr-only data table; `role=status`/`alert` used |
| Safety | OK. No `dangerouslySetInnerHTML`, `innerHTML`, `eval`, `new Function`; contract types only |
| Scope | OK. analytics/** only |

## Suites (detached f6e22b1, `npm ci` first)
- `npm test`: **131 passed** (11 files) · `npm run lint`: clean · `npm run typecheck`: clean · `npm run build`: OK (273.77 kB JS)

## Notes (non-blocking)
1. Rows-per-run chart covers only the latest 50 succeeded runs (20 plotted); failed runs are absent by design.
2. `useApiData` suppresses `react-hooks/exhaustive-deps`; callers must pass stable `client` (the default is a module singleton). VIZ-02 reuses it, so keep this in mind.
3. Chart colors use CSS variables via `rgb(var(--color-*))`; not verified visually in a browser (jsdom only).
