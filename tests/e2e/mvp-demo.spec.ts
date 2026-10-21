import { expect, test } from '@playwright/test';
import path from 'node:path';

// Source of truth for the numbers: tests/fixtures/expected.json (orders_clean.csv, orders_full.json).
const CSV = path.resolve(__dirname, '../fixtures/csv/orders_clean.csv');
const TABLE = 'e2e_orders';

test('MVP demo: upload -> pipeline -> run -> results, explorer and charts', async ({ page }) => {
  // 1. Upload a CSV and see its preview.
  await page.goto('/sources');
  await page.getByLabel('CSV file').setInputFiles(CSV);
  await page.getByLabel('Name (optional)').fill('Orders demo');
  await page.getByRole('button', { name: 'Upload', exact: true }).click();
  await expect(page).toHaveURL(/\/sources\/[0-9a-f-]{36}$/);
  await expect(page.getByRole('columnheader', { name: 'Order ID' })).toBeVisible();

  // 2. Configure and save a pipeline.
  await page.goto('/pipelines/new');
  await page.getByLabel('Name', { exact: true }).fill('Orders pipeline');
  await page.getByLabel('Data source').selectOption({ label: 'Orders demo' });
  await page.getByLabel('Target table').fill(TABLE);
  await page.getByLabel('Load mode').selectOption('replace');
  await page.getByRole('button', { name: 'Validate' }).click();
  await expect(page.getByText('The configuration is valid.')).toBeVisible();
  await page.getByRole('button', { name: 'Create pipeline' }).click();
  await expect(page).toHaveURL(/\/pipelines$/);
  await expect(page.getByText('Orders pipeline')).toBeVisible();

  // 3. Run it and watch it reach "Succeeded" (the real worker executes it).
  await page.goto('/runs');
  const starter = page.getByRole('region', { name: 'Start a run' });
  await starter.getByLabel('Pipeline').selectOption({ label: 'Orders pipeline' });
  await starter.getByRole('button', { name: 'Run', exact: true }).click();
  await expect(page).toHaveURL(/\/runs\/[0-9a-f-]{36}$/);
  await expect(page.getByText('Succeeded', { exact: true }).first()).toBeVisible({ timeout: 60_000 });

  // 4. Run results: counters reconcile (200 extracted = loaded + rejected + dropped).
  const counters = page.getByRole('region', { name: 'Row counters' });
  await expect(counters).toBeVisible();
  const value = async (label: string) =>
    Number((await counters.locator('dt', { hasText: label }).first().locator('xpath=following-sibling::dd[1]').innerText()).replace(/\D/g, ''));
  const extracted = await value('Extracted');
  const loaded = await value('Loaded');
  const rejected = await value('Rejected');
  const dup = await value('Duplicates dropped');
  const nulls = await value('Null rows dropped');
  expect(extracted).toBe(200);
  expect(loaded).toBeGreaterThan(0);
  expect(extracted).toBe(loaded + rejected + dup + nulls);

  // 5. Dataset rows and profile charts in the explorer.
  await page.goto('/datasets');
  await page.getByRole('button', { name: new RegExp(TABLE) }).click();
  await expect(page.getByRole('region', { name: 'Rows' }).locator('tbody tr').first()).toBeVisible();
  await expect(page.getByText(`${loaded.toLocaleString('en-US')} rows`).first()).toBeVisible();
  await expect(
    page.getByRole('region', { name: 'Column profiles' }).locator('.recharts-wrapper > svg.recharts-surface').first(),
  ).toBeVisible();

  // 6. Charts on Home.
  await page.goto('/');
  const stats = page.getByRole('list', { name: 'Run statistics' }).or(page.getByLabel('Run statistics'));
  await expect(stats).toContainText('Total runs');
  // Real browser layout: the chart surface is drawn and the bars for our one succeeded run exist.
  for (const id of ['run-outcomes-chart', 'rows-loaded-chart']) {
    const chart = page.getByTestId(id);
    await expect(chart.locator('.recharts-wrapper > svg.recharts-surface')).toBeVisible();
    await expect(chart.locator('.recharts-bar-rectangle path.recharts-rectangle').first()).toBeVisible();
  }
});
