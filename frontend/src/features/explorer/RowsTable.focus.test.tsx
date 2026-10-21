import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { createApiClient } from '../../app/api/client';
import { datasetRows } from '../../app/api/fixtures';
import { createMockFetch } from '../../app/api/mockFetch';
import type { DatasetRowPage } from '../../app/api/types';
import { DatasetExplorer } from './DatasetExplorer';
import { RowsTable } from './RowsTable';

/** Serves `total` rows in pages of 25, honoring ?offset. */
async function open(total: number) {
  const fetch = createMockFetch({
    'GET /datasets/[^/]+/rows': ({ url }) =>
      new Response(
        JSON.stringify({ ...datasetRows, total, limit: 25, offset: Number(url.searchParams.get('offset') ?? 0) }),
        { headers: { 'Content-Type': 'application/json' } },
      ),
  });
  render(<DatasetExplorer client={createApiClient({ baseUrl: 'http://x/api/v1', fetch })} width={500} />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: /orders_clean/ }));
  await screen.findByText(new RegExp(`of ${total}$`));
  return user;
}
const status = () => screen.getByTestId('pager-status');
const prev = () => screen.getByRole('button', { name: 'Previous' });
const next = () => screen.getByRole('button', { name: 'Next' });

describe('pager keyboard focus', () => {
  it('Next onto the last page moves focus to Previous', async () => {
    const user = await open(60); // pages: 1-25, 26-50, 51-60
    next().focus();
    await user.keyboard('{Enter}');
    await waitFor(() => expect(status()).toHaveTextContent('26–50 of 60'));
    expect(next()).toHaveFocus(); // non-final page keeps focus on the activated button
    await user.keyboard('{Enter}');
    await waitFor(() => expect(status()).toHaveTextContent('51–60 of 60'));
    expect(next()).toBeDisabled();
    expect(prev()).toHaveFocus();
    expect(document.body).not.toHaveFocus();
  });

  it('Previous onto the first page moves focus to Next', async () => {
    const user = await open(60);
    next().focus();
    await user.keyboard('{Enter}');
    await waitFor(() => expect(status()).toHaveTextContent('26–50 of 60'));
    prev().focus();
    await user.keyboard('{Enter}');
    await waitFor(() => expect(status()).toHaveTextContent('1–25 of 60'));
    expect(prev()).toBeDisabled();
    expect(next()).toHaveFocus();
  });

  it('non-final pages keep focus on the activated Previous', async () => {
    const user = await open(80); // 1-25, 26-50, 51-75, 76-80
    next().focus();
    await user.keyboard('{Enter}');
    await waitFor(() => expect(status()).toHaveTextContent('26–50 of 80'));
    next().focus();
    await user.keyboard('{Enter}');
    await waitFor(() => expect(status()).toHaveTextContent('51–75 of 80'));
    prev().focus();
    await user.keyboard('{Enter}');
    await waitFor(() => expect(status()).toHaveTextContent('26–50 of 80'));
    expect(prev()).toHaveFocus();
  });

  it('single-page results move focus to the pager status', async () => {
    const mk = (total: number, offset: number): DatasetRowPage => ({ ...datasetRows, total, limit: 25, offset });
    const user = userEvent.setup();
    const noop = () => undefined;
    const { rerender } = render(<RowsTable page={mk(60, 0)} sort={null} onSort={noop} onOffset={noop} />);
    next().focus();
    await user.keyboard('{Enter}');
    // The refreshed data now fits on one page: both buttons disable.
    rerender(<RowsTable page={mk(10, 0)} sort={null} onSort={noop} onOffset={noop} />);
    expect(prev()).toBeDisabled();
    expect(next()).toBeDisabled();
    expect(status()).toHaveFocus();
    expect(status()).toHaveTextContent('1–10 of 10');
    expect(document.body).not.toHaveFocus();
  });

  it('does not steal focus the user moved elsewhere', async () => {
    const mk = (offset: number): DatasetRowPage => ({ ...datasetRows, total: 60, limit: 25, offset });
    const user = userEvent.setup();
    const noop = () => undefined;
    const { rerender } = render(<RowsTable page={mk(0)} sort={null} onSort={noop} onOffset={noop} />);
    next().focus();
    await user.keyboard('{Enter}');
    screen.getByRole('button', { name: 'amount' }).focus();
    rerender(<RowsTable page={mk(25)} sort={null} onSort={noop} onOffset={noop} />);
    expect(screen.getByRole('button', { name: 'amount' })).toHaveFocus();
  });
});
