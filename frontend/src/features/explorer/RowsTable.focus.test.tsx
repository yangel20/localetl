import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { datasetRows } from '../../app/api/fixtures';
import type { DatasetRowPage } from '../../app/api/types';
import { RowsTable } from './RowsTable';

const mk = (total: number, offset: number): DatasetRowPage => ({ ...datasetRows, total, limit: 25, offset });
const noop = () => undefined;

/** Pages locally (synchronously), so no fetches or charts run: the test stays cheap under load. */
function Harness({ total }: { total: number }) {
  const [offset, setOffset] = useState(0);
  return <RowsTable page={mk(total, offset)} sort={null} onSort={noop} onOffset={setOffset} />;
}

const status = () => screen.getByRole('status');
const prev = () => screen.getByRole('button', { name: 'Previous' });
const next = () => screen.getByRole('button', { name: 'Next' });

describe('pager keyboard focus', () => {
  it('Next onto the last page moves focus to Previous', async () => {
    const user = userEvent.setup({ delay: null });
    render(<Harness total={30} />); // pages: 1–25, 26–30
    expect(status()).toHaveTextContent('1–25 of 30');
    next().focus();
    await user.keyboard('{Enter}');
    expect(status()).toHaveTextContent('26–30 of 30');
    expect(status()).toHaveAttribute('aria-live', 'polite');
    expect(next()).toBeDisabled();
    expect(prev()).toHaveFocus();
    expect(document.body).not.toHaveFocus();
  });

  it('Previous onto the first page moves focus to Next', async () => {
    const user = userEvent.setup({ delay: null });
    render(<Harness total={30} />);
    next().focus();
    await user.keyboard('{Enter}');
    expect(status()).toHaveTextContent('26–30 of 30');
    expect(prev()).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(status()).toHaveTextContent('1–25 of 30');
    expect(prev()).toBeDisabled();
    expect(next()).toHaveFocus();
    expect(document.body).not.toHaveFocus();
  });

  it('non-final pages keep focus on the activated button', async () => {
    const user = userEvent.setup({ delay: null });
    render(<Harness total={80} />); // 1–25, 26–50, 51–75, 76–80
    next().focus();
    await user.keyboard('{Enter}');
    expect(status()).toHaveTextContent('26–50 of 80');
    expect(next()).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(status()).toHaveTextContent('51–75 of 80');
    expect(next()).toHaveFocus();
    prev().focus();
    await user.keyboard('{Enter}');
    expect(status()).toHaveTextContent('26–50 of 80');
    expect(prev()).toHaveFocus();
  });

  it('single-page results move focus to the pager status', async () => {
    const user = userEvent.setup({ delay: null });
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
    const user = userEvent.setup({ delay: null });
    const { rerender } = render(<RowsTable page={mk(60, 0)} sort={null} onSort={noop} onOffset={noop} />);
    next().focus();
    await user.keyboard('{Enter}');
    screen.getByRole('button', { name: 'amount' }).focus();
    rerender(<RowsTable page={mk(60, 25)} sort={null} onSort={noop} onOffset={noop} />);
    expect(screen.getByRole('button', { name: 'amount' })).toHaveFocus();
  });
});
