# QA review: FE-T1 Frontend test stability

- Reviewer: qa-engineer (QA-06) · Date: 2026-10-21
- Scope of my checks (per the orchestrator): focused files, lint and typecheck only. The 10-run before/after comparison, test-all and E2E are the orchestrator's.
- Criteria: test files only (no change to `vite.config.ts`, `testTimeout`, `setup.ts` or components); every `expect(` kept; no weakening (paste only where typing is not under test, `delay: null` does not skip a relied-on state, no needed `waitFor` removed); accessibility, focus and keyboard assertions intact.

## Part 2: `viz/FE-T1-viz-tests` @ **1eb8b22** — **PASS**
Base `e4e1365` (an ancestor of current `main`); files: `explorer/DatasetExplorer.test.tsx`, `explorer/RowsTable.focus.test.tsx`, `analytics/RunAnalytics.test.tsx` (test files only, +14/-14).

| Check | Result |
|---|---|
| Scope | OK. Only the three test files changed; no config, setup or component change |
| Assertion counts (`expect(`) vs `main` | Equal: 32 / 24 / 10 |
| Change content | 13× `userEvent.setup()` → `setup({ delay: null })`, and the RunAnalytics empty-state render gets `width={600}`. No assertion, `waitFor` or query was touched |
| Loading/busy state not vacuous | OK. The "table stays mounted while a sort loads" test holds the rows response behind a gate, so "Updating…", the previous rows, the same DOM node and header focus are observed while the request is genuinely pending and are unaffected by `delay: null`. The test still fails if the unmounting pre-VIZ-03 `DatasetExplorer` is restored (mutation: 3 of 10 fail: the sort test, "keeps focus on Next while paging", "later page fails") |
| Focus/keyboard intact | OK. Mutating `RowsTable.tsx` back to the pre-VIZ-04 version fails 4 of the 19 explorer tests (the four pager-focus scenarios), as before |
| Suites | `vitest run src/features/explorer src/features/analytics`: 5 files, 28 passed · lint exit 0 · typecheck exit 0 |

Observations (not caused by this change):
- **`aria-busy` is not asserted anywhere**, before or after (`main`'s test has 0 mentions): removing `aria-busy` from `DatasetExplorer.tsx` leaves 10 of 10 passing. The orchestrator's list mentioned `aria-busy`; it is covered only by the visible "Updating…" text. Suggested optional follow-up: add `expect(screen.getByLabelText('Rows')).toHaveAttribute('aria-busy', 'true')` to the gated sort test.
- "keeps focus on Next while paging" waits for "Updating…" to be absent, which can already be true if the response lands first; the same shape as on `main`, so not a regression. Its focus check is only meaningful if the table stays mounted, which the gated test covers.

## Part 1: `fe/FE-T1-test-stability` @ **3a1252b** — **PASS**
Two commits on `main` 85ec754 (a102656: `app/routes.test.tsx`, `pages/sources|pipelines|runs` tests; 3a1252b: `features/pipelines/PipelineForm.test.tsx`). The merge base with `main` is e4e1365 (my checkout reports it as the merge base; the diff against `main` lists only those five test files).

| Check | Result |
|---|---|
| Scope | OK. Five test files only: `app/routes.test.tsx`, `pipelines/PipelineForm.test.tsx`, `pages/pipelines/PipelinesPage.test.tsx`, `pages/runs/RunsPage.test.tsx`, `pages/sources/SourcesPage.test.tsx`. No config, setup or component change |
| `expect(` counts vs `main` | Equal: 3/3, 33/33, 28/28, 52/52, 36/36. `waitFor` counts also equal (0, 2, 2, 4, 2) |
| `delay: null` | A per-file `user` from `beforeEach(() => { user = userEvent.setup({ delay: null }) })` replaces the bare `userEvent.*` calls. Interactions are otherwise identical (click, selectOptions, upload, clear) |
| Paste vs typing | 10 `type` calls became click + `paste`, all filling a text field whose per-keystroke behavior is not under test: pipeline name, target table (including the invalid `Bad-Name`, whose assertion is on the whole value), date format `%Y %H`, and the renamed pipeline name. The two cases where input handling matters (`fill_null` with `'abc'` and `'7'` through the scalar input, which parses per change) still use `user.type`. The `clear` + click + paste for the rename keeps the replace-the-text semantics |
| Non-CSV upload | OK. Uses its own `userEvent.setup({ delay: null, applyAccept: false })` instance because `applyAccept` is a setup option; the assertion on the rejected `a.txt` is unchanged |
| Accessibility/keyboard | No role, label or focus assertion was removed or loosened (all label/role queries unchanged) |
| Suites | `vitest run src/app/routes.test.tsx src/features/pipelines/PipelineForm.test.tsx src/pages`: 6 files, 61 passed · lint exit 0 · typecheck exit 0 |

Notes: paste fires one `input` event for the whole string, so a test that began to depend on intermediate per-keystroke state in these four fields would no longer see it; none do today.
