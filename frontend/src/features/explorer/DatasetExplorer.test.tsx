import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { createApiClient } from '../../app/api/client';
import { datasetRows } from '../../app/api/fixtures';
import { createMockFetch, errorResponse } from '../../app/api/mockFetch';
import { DatasetExplorer } from './DatasetExplorer';

const json = (b: unknown) => () => new Response(JSON.stringify(b), { headers: { 'Content-Type': 'application/json' } });
function setup(overrides = {}) {
  const urls: string[] = [];
  const mock = createMockFetch(overrides);
  const fetch: typeof globalThis.fetch = (i, init) => { urls.push(String(i)); return mock(i, init); };
  render(<DatasetExplorer client={createApiClient({ baseUrl: 'http://x/api/v1', fetch })} width={500} />);
  return urls;
}

describe('DatasetExplorer', () => {
  it('lists datasets, shows rows and profile charts after selecting', async () => {
    setup();
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /orders_clean/ }));
    expect(await screen.findByText('Grace')).toBeInTheDocument();
    expect(screen.getByText('∅', { selector: 'td' })).toBeInTheDocument();
    expect(screen.getByText('1–3 of 3')).toBeInTheDocument();
    const prof = await screen.findByLabelText('Profile of customer');
    expect(within(prof).getByText(/33% null/)).toBeInTheDocument();
    expect(within(prof).getByTestId('top-values-customer').querySelector('svg')).not.toBeNull();
  });

  it('sorts a single column through the API and resets paging', async () => {
    const urls = setup({ 'GET /datasets/[^/]+/rows': json({ ...datasetRows, total: 60, limit: 25 }) });
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /orders_clean/ }));
    await user.click(await screen.findByRole('button', { name: 'Next' }));
    await waitFor(() => expect(urls.some((u) => u.includes('offset=25'))).toBe(true));
    await user.click(await screen.findByRole('button', { name: 'amount' }));
    const lastRows = () => urls.filter((u) => u.includes('/rows')).at(-1) ?? '';
    await waitFor(() => expect(lastRows()).toContain('sort=amount'));
    expect(lastRows()).toContain('order=asc');
    expect(lastRows()).toContain('offset=0');
    expect(screen.getByRole('columnheader', { name: /amount/ })).toHaveAttribute('aria-sort', 'ascending');
  });

  it('shows the empty list message', async () => {
    setup({ 'GET /datasets': json({ total: 0, limit: 100, offset: 0, items: [] }) });
    expect(await screen.findByText(/No published datasets/)).toBeInTheDocument();
  });

  it('shows API errors for rows', async () => {
    setup({ 'GET /datasets/[^/]+/rows': () => errorResponse(422, 'validation_error', 'bad sort') });
    await userEvent.setup().click(await screen.findByRole('button', { name: /orders_clean/ }));
    expect(await screen.findByText('bad sort')).toBeInTheDocument();
  });
});

describe('DatasetExplorer polish (VIZ-03)', () => {
  const slowRows = () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => { release = r; });
    return { gate, release };
  };

  it('keeps the table mounted with previous rows while a sort loads, and keeps focus', async () => {
    const { gate, release } = slowRows();
    let calls = 0;
    setup({
      'GET /datasets/[^/]+/rows': async () => {
        if (++calls > 1) await gate;
        return json({ ...datasetRows, total: 60, limit: 25 })();
      },
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /orders_clean/ }));
    const header = await screen.findByRole('button', { name: 'amount' });
    const rowsTable = () => within(screen.getByLabelText('Rows')).getByRole('table');
    const table = rowsTable();
    await user.click(header);
    expect(await screen.findByText('Updating…')).toBeInTheDocument();
    expect(screen.getByText('Grace')).toBeInTheDocument(); // previous rows still shown
    expect(screen.getByRole('button', { name: /amount/ })).toBe(header); // same DOM node
    expect(header).toHaveFocus();
    expect(rowsTable()).toBe(table);
    release();
    await waitFor(() => expect(screen.queryByText('Updating…')).toBeNull());
    expect(screen.getByRole('button', { name: /amount/ })).toBe(header);
    expect(header).toHaveFocus();
    expect(screen.getByRole('columnheader', { name: /amount/ })).toHaveAttribute('aria-sort', 'ascending');
  });

  it('keeps focus on Next while paging', async () => {
    setup({ 'GET /datasets/[^/]+/rows': json({ ...datasetRows, total: 80, limit: 25 }) });
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /orders_clean/ }));
    const next = await screen.findByRole('button', { name: 'Next' });
    await user.click(next);
    await waitFor(() => expect(screen.queryByText('Updating…')).toBeNull());
    expect(screen.getByRole('button', { name: 'Next' })).toBe(next);
    expect(next).toHaveFocus();
  });

  it('keeps previous rows and shows the error when a later page fails', async () => {
    let calls = 0;
    setup({
      'GET /datasets/[^/]+/rows': () =>
        ++calls > 1 ? errorResponse(500, 'internal_error', 'page failed') : json({ ...datasetRows, total: 60, limit: 25 })(),
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /orders_clean/ }));
    await user.click(await screen.findByRole('button', { name: 'Next' }));
    expect(await screen.findByText('page failed')).toBeInTheDocument();
    expect(screen.getByText('Grace')).toBeInTheDocument();
  });

  it('shows an error when the datasets list fails', async () => {
    setup({ 'GET /datasets': () => errorResponse(500, 'internal_error', 'list failed') });
    expect(await screen.findByText('list failed')).toBeInTheDocument();
    expect(screen.queryByTestId('top-values-customer')).toBeNull();
  });

  it('isolates a profile error from the rows table', async () => {
    setup({ 'GET /datasets/[^/]+/profile': () => errorResponse(500, 'internal_error', 'profile failed') });
    await userEvent.setup().click(await screen.findByRole('button', { name: /orders_clean/ }));
    expect(await screen.findByText('profile failed')).toBeInTheDocument();
    expect(await screen.findByText('Grace')).toBeInTheDocument();
  });

  it('isolates a rows error from the profile charts', async () => {
    setup({ 'GET /datasets/[^/]+/rows': () => errorResponse(500, 'internal_error', 'rows failed') });
    await userEvent.setup().click(await screen.findByRole('button', { name: /orders_clean/ }));
    expect(await screen.findByText('rows failed')).toBeInTheDocument();
    expect(await screen.findByLabelText('Profile of customer')).toBeInTheDocument();
  });
});
