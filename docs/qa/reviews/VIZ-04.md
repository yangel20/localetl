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

## Re-check after the test-only fix (2026-10-21) — **PASS** at **66f390f**
- Target: `viz/VIZ-04-pager-focus` @ **66f390f** (adds one commit on b1a6e22; it changes only `explorer/RowsTable.focus.test.tsx`, so `RowsTable.tsx` is identical to the version reviewed above). Trigger: the orchestrator's trial merge timed out (5.8 s) on the old last-page test under load.
1. **Scenarios not weakened.** All five remain: Next onto the last page → Previous focused; Previous onto the first page → Next focused; non-final pages keep focus on the activated button (Next, Next, Previous); a single page → status element focused with both buttons disabled; no focus stealing when the user moved focus to a column header. They are still keyboard-driven (`userEvent.keyboard('{Enter}')`), still assert `document.body` is not focused where relevant, and the text of the status. Changes: `RowsTable` is driven through a small local harness with synchronous paging (no fetch or charts), and the last/first-page tests use 30 rows (2 pages) instead of 60. The assertion `waitFor` calls were dropped, which is valid because paging is now synchronous. What is lost: the tests no longer go through `DatasetExplorer`, so the interplay with the kept-mounted stale page is covered by the real-browser check and the E2E, not by jsdom.
   - **Correction on live-region assertions:** neither b1a6e22 nor 66f390f has a jsdom assertion for the `aria-live="polite"` / `role="status"` attributes (the tests check the status text only). The attribute was verified once in my real-Chromium check and is visible in `RowsTable.tsx`. Not a regression from this fix, but a gap: a one-line `expect(status()).toHaveAttribute('aria-live', 'polite')` would pin it (optional follow-up).
2. **Old component:** with `main`'s `RowsTable.tsx` and the new test file, 4 of 5 fail (last page, first page, non-final, single page); "does not steal focus" passes on old code, as before.
3. **Suites:** `npm test` 152 passed on 3 consecutive full runs (load average ~100–150 at the time); the 5 focus tests take 0.73 s in total (was ~7 s); `npm run lint` and `npm run typecheck` exit 0; `npm run build` OK. The E2E result above stands because `RowsTable.tsx` is unchanged.

## Final re-check (2026-10-21) — **PASS** at **9e381bd**
- Target: `viz/VIZ-04-pager-focus` @ **9e381bd** (test-only, +2/-1 on 66f390f; `RowsTable.tsx` unchanged). `status()` now uses `getByRole('status')`, and the last-page test asserts `aria-live="polite"`. This closes the live-region gap noted above.
- Focus file: **5 passed**. `npm run lint` and `npm run typecheck`: exit 0. (No full-suite loop, per the orchestrator.)
- **Mutations of `RowsTable.tsx`** (each reverted afterwards, worktree clean):
  - without `aria-live="polite"`: **1 of 5 fails** (the last-page test's new assertion);
  - without `role="status"`: **4 of 5 fail** (`getByRole('status')` finds nothing; the no-steal test never queries the status);
  - with `main`'s `RowsTable.tsx`: **4 of 5 fail** (last page, first page, non-final, single page); no-steal passes as before.
- Requirement 5 (polite announcement) is now protected by a test.
