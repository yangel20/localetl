# QA review: VIZ-03 Explorer polish

- Reviewer: qa-engineer (QA-06) · Date: 2026-10-21
- Target: `viz/VIZ-03-explorer-polish` @ **2433c41** (1 commit on `c7d7d71`; `main` has moved on only with tests/e2e and docs). 2 files: `frontend/src/features/explorer/DatasetExplorer.tsx` and `DatasetExplorer.test.tsx`; within VIZ-03's path. No dependency or `src/app/api` changes.
- Spec: board VIZ-03 row; my VIZ-02 notes 1 and 2.

## Verdict: **PASS**

| Check | Result |
|---|---|
| Table stays mounted during page/sort loads | OK. `Selected` keeps the last loaded `DatasetRowPage` in a ref and renders `RowsTable` from it while the next request is `loading`; the section gets `aria-busy="true"`, a small "Updating…" status and reduced opacity instead of unmounting. The first load (no page yet) still uses `ChartFrame` loading/error. `Selected` is keyed by dataset id, so switching dataset starts clean |
| Error states | OK. Tests: datasets-list failure; profile failure isolated from the rows table; rows failure isolated from the profile charts; a later-page failure keeps the previous rows and shows the alert |
| Focus | OK. Tests assert the sort header keeps focus across the sort load and "Next" keeps focus across a page load |
| Safety | No HTML injection; unchanged rendering of cell values |

## Suites (detached 2433c41, `npm ci` first)
- `npm test`: **147 passed** (14 files) · `npm run lint`: clean · `npm run typecheck`: clean · `npm run build`: OK (chunk-size warning, known)
- **E2E** (`scripts/e2e.sh`): 1 passed with the branch's own spec, and again 1 passed with `main`'s current `mvp-demo.spec.ts` (including the QA-08b counter and "of <loaded>" pager assertions) checked out over it temporarily; worker exited 0; no `localetl_e2e_*` databases left. The spec change was undone afterwards.

## Ruling on the known limitation
**Accept** that focus is lost when "Next" becomes disabled on the last page: a disabled button cannot hold focus in any browser, so this is native behavior and the user can still Tab on. Optional follow-up: move focus to "Previous" when Next disables.

## Notes (non-blocking)
1. After a failed later-page or sort request the table keeps the previous page's rows while the header shows the newly requested sort (the alert explains the failure). Retrying means clicking again; there is no retry button.
2. Focus behavior is verified in jsdom only, not in a real browser.
