# QA review: VIZ-04 Pager keyboard focus

- Reviewer: qa-engineer (QA-06) · Date: 2026-10-21
- Target: `viz/VIZ-04-pager-focus` @ **b1a6e22** (1 commit on `main` c360e36, no rebase needed). 2 files: `frontend/src/features/explorer/RowsTable.tsx` (+32/-4) and new `RowsTable.focus.test.tsx` (5 tests); within `features/explorer/**`. No dependency or `src/app/api` changes.
- Spec: the user's requirement (follow-up to the VIZ-03 ruling), board VIZ-04 row.

## Verdict: **PASS**

| Requirement | Result |
|---|---|
| Next onto the last page → Previous has focus | OK (jsdom test, keyboard `{Enter}`; and in a real Chromium, see below) |
| Previous onto the first page → Next has focus | OK (jsdom test; real Chromium) |
| Single page → status element (`tabIndex=-1`) has focus | OK (test rerenders a refreshed 10-row page; both buttons disabled; status focused) |
| `aria-live="polite"` range | OK. The range span is now `role="status" aria-live="polite"` with `data-testid="pager-status"`; real-browser check confirms the attribute |
| Focus never on `<body>` | OK in all focus tests and in Chromium (`document.activeElement !== body` after reaching the last page) |
| Never take back focus the user moved | OK. The layout effect acts only if focus is still on the activated button or on `<body>`; test moves focus to a column header before the new page renders and it stays there. A sort click clears the pending state |
| Keyboard-driven tests | OK. All pager tests focus the button and press Enter via `userEvent.keyboard` |
| Non-final pages unchanged | OK. Focus stays on the activated button (tested for Next and Previous) |

## Old component check
With `main`'s `RowsTable.tsx` and the new test file: **4 of 5 fail** (last page, first page, non-final Previous, single page); the fifth ("does not steal focus") passes on the old code, as expected, because the old code never moved focus. Confirms agent-viz's claim.

## Suites (detached b1a6e22, `npm ci` first)
- `npm test`: 152 passed when it runs clean (the 5 new tests pass 3/3 in isolation) · `npm run lint`: clean · `npm run typecheck`: clean · `npm run build`: OK
- **E2E** (`scripts/e2e.sh`, `main`'s spec with the QA-08b "of <loaded>" pager assertion): 1 passed; the added `role="status"` span does not break `toContainText('of 200')`. Worker exit 0, no e2e databases left.
- **Real-browser focus check** (temporary Playwright spec built from the demo, not committed, removed afterwards): 200 loaded rows, Next pressed with Enter 7 times to the last page → Next disabled, Previous focused, body not focused; Previous back off the last page → Previous still focused; live region attribute present. 1 passed. This closes the "jsdom only" gap I noted for VIZ-03.

## Notes (non-blocking)
1. **Flaky full suite under load.** Over 8 full runs of `npm test` on this branch the suite failed 3 times, with `Test timed out in 5000ms` in "Next onto the last page" (twice), `DatasetExplorer > sorts a single column` and `PipelinesPage > creates a pipeline`, and a `RunsPage` lookup failure once. The machine load average was about 200 (other sessions running), and `main` itself failed 1 of 4 runs (the `DatasetExplorer` sort test). So the flakiness predates VIZ-04 and is a load effect, but the new first test is the slowest (about 1.9 s alone) and is exposed to the default 5 s timeout. Suggested follow-up: raise `testTimeout` in `frontend/vite.config.ts` (e.g. 15 s) or trim the test; orchestrator-visible, I did not change anything.
2. If a page request fails after Next/Previous, `pending` stays set until the next page change, and only acts if focus is on the button or `<body>`; harmless.
