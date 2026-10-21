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
    await waitFor(() => expect(urls.at(-1)).toMatch(/sort=amount&order=asc|order=asc&sort=amount/));
    expect(urls.filter((u) => u.includes('/rows')).at(-1)).toContain('offset=0');
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
