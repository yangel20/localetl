# QA review: VIZ-02 Dataset explorer with profile charts

- Reviewer: qa-engineer (QA-06) · Date: 2026-10-21
- Target: `viz/VIZ-02-dataset-explorer` @ **1aedbe2** (3 commits on `29546fb`). `git diff --name-only 29546fb..1aedbe2` is entirely under `frontend/src/features/explorer/**`; no changes to `src/app/api`, `package.json` or lockfile; no new dependency. It imports `ChartFrame`, `useApiData` and `format` from the merged `features/analytics`.
- Spec: board VIZ-02 row; REQ-53..55.

## Verdict: **PASS**

| Check | Result |
|---|---|
| Datasets list | OK. `listDatasets({limit:100})`: table name, row count, column count, published time (UTC); selecting a dataset mounts `Selected` keyed by id (state resets per dataset) |
| Paged rows table | OK. 25 per page, Previous/Next disabled at the ends, "from–to of total"; "No rows." row when empty |
| Single-column sort | OK. Header click cycles asc → desc (new column → asc); sends `sort=<column>&order=asc|desc`, matching the contract (`sort` = dataset column, `order` enum asc/desc); paging resets to offset 0; `aria-sort` set. Test asserts `sort=amount`, `order=asc`, `offset=0` in the request URL. Only one column at a time |
| Profile charts | OK. Per column: top-values bar chart, null/non-null pie, null %, distinct count, min–max range, sr-only top-values table; from `getDatasetProfile` |
| Loading / empty / error | OK via `ChartFrame` for list, rows, profile. Tests: empty datasets message, rows API error shown. Profile-error and empty-columns paths share the same component |
| Text rendering | OK. Cell values rendered as React text through `formatCell` (null → "∅"); no `dangerouslySetInnerHTML`, `innerHTML`, `eval`, `new Function` |
| VIZ-01 note 2 (`client` stability) | Verified. `DatasetExplorer({ client = defaultApi })` defaults to the module singleton; no client is created during render in `features/explorer`; `client` is in the hook deps and stays stable |

## Suites (detached 1aedbe2, `npm ci` first)
- `npm test`: **139 passed** (13 files) · `npm run lint`: clean · `npm run typecheck`: clean · `npm run build`: OK (bundle unchanged at 273.77 kB because the explorer is not mounted until FE-06)

## Notes (non-blocking)
1. While a new sort/page request loads, the whole rows frame switches to "Loading…" and the table (with its headers) unmounts, causing a flash and loss of scroll/focus on the sort button. Consider keeping the previous page visible (FE-06 or follow-up).
2. Tests cover list, selection, profile charts, sort/paging, empty and rows error; no dedicated test for a profile error or an error on the datasets list.
3. Not checked visually in a browser (jsdom only); QA-08 covers the real UI.
