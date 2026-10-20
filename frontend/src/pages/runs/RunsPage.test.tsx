import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { IDS, rejections, runRunning, runSucceeded } from '../../app/api/fixtures';
import { createMockFetch, errorResponse } from '../../app/api/mockFetch';
import { routes } from '../../app/routes';

type Overrides = Parameters<typeof createMockFetch>[0];
const json = (b: unknown, status = 200) =>
  new Response(JSON.stringify(b), { status, headers: { 'Content-Type': 'application/json' } });

function renderAt(path: string, overrides: Overrides = {}) {
  const fetchMock = vi.fn(createMockFetch(overrides));
  vi.stubGlobal('fetch', fetchMock);
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  const calls = (suffix: string) =>
    fetchMock.mock.calls.filter(([u]) => new URL(String(u)).pathname.endsWith(suffix));
  return { fetchMock, router, calls };
}
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('run history', () => {
  it('lists runs with status text, counters and metrics as text', async () => {
    renderAt('/runs');
    expect(await screen.findAllByRole('link', { name: 'Orders cleanup' })).toHaveLength(2);
    const table = screen.getByRole('table');
    expect(within(table).getByText('Running')).toBeInTheDocument();
    expect(within(table).getByText('Succeeded')).toBeInTheDocument();
    const metrics = await screen.findByRole('region', { name: 'Metrics' });
    expect(metrics).toHaveTextContent('Total runs');
    expect(metrics).toHaveTextContent('Succeeded: 1');
    expect(metrics).toHaveTextContent('2.0 s');
  });

  it('filters by pipeline and status through query parameters and resets paging', async () => {
    const { calls } = renderAt('/runs');
    await screen.findAllByRole('link', { name: 'Orders cleanup' });
    await userEvent.selectOptions(screen.getByLabelText('Status'), 'failed');
    await waitFor(() => expect(calls('/runs').some(([u]) => String(u).includes('status=failed'))).toBe(true));
    const history = screen.getByRole('region', { name: 'History' });
    await userEvent.selectOptions(within(history).getByLabelText('Pipeline'), IDS.pipeline);
    await waitFor(() => {
      const last = String(calls('/runs').at(-1)![0]);
      expect(last).toContain(`pipeline_id=${IDS.pipeline}`);
      expect(last).toContain('status=failed');
      expect(last).toContain('offset=0');
    });
  });

  it('shows filtered-empty and error states', async () => {
    renderAt('/runs', {
      'GET /runs': ({ url }) =>
        url.searchParams.has('status')
          ? json({ total: 0, limit: 20, offset: 0, items: [] })
          : errorResponse(500, 'internal_error', 'history unavailable'),
    });
    expect(await screen.findByText('history unavailable')).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText('Status'), 'failed');
    expect(await screen.findByText('No runs match these filters.')).toBeInTheDocument();
  });

  it('paginates the history', async () => {
    const { calls } = renderAt('/runs', {
      'GET /runs': ({ url }) => json({ total: 45, limit: 20, offset: Number(url.searchParams.get('offset')), items: [runSucceeded] }),
    });
    await screen.findByText('1–20 of 45');
    await userEvent.click(screen.getByRole('button', { name: 'Next' }));
    await screen.findByText('21–40 of 45');
    expect(calls('/runs').some(([u]) => String(u).includes('offset=20'))).toBe(true);
  });
});

describe('run starter', () => {
  it('queues a run and opens its detail page', async () => {
    const { router, calls } = renderAt('/runs');
    const starter = await screen.findByRole('region', { name: 'Start a run' });
    const run = within(starter).getByRole('button', { name: 'Run' });
    expect(run).toBeDisabled();
    await userEvent.selectOptions(await within(starter).findByLabelText('Pipeline'), IDS.pipeline);
    await userEvent.click(run);
    await waitFor(() => expect(router.state.location.pathname).toMatch(/^\/runs\/4444/));
    expect(calls(`/pipelines/${IDS.pipeline}/runs`)).toHaveLength(1);
  });

  it('shows a 409 clearly and stays on the page', async () => {
    const { router } = renderAt('/runs', {
      'POST /pipelines/[^/]+/runs': () => errorResponse(409, 'conflict', 'Pipeline already has a queued or running run'),
    });
    const starter = await screen.findByRole('region', { name: 'Start a run' });
    await userEvent.selectOptions(await within(starter).findByLabelText('Pipeline'), IDS.pipeline);
    await userEvent.click(within(starter).getByRole('button', { name: 'Run' }));
    expect(await within(starter).findByRole('alert')).toHaveTextContent('Pipeline already has a queued or running run');
    expect(starter).toHaveTextContent(/Wait for it to finish/);
    expect(router.state.location.pathname).toBe('/runs');
  });
});

describe('run detail', () => {
  it('shows status, the five counters (drops apart from rejections), events and rejections', async () => {
    renderAt(`/runs/${IDS.runSucceeded}`);
    expect(await screen.findByRole('heading', { level: 1, name: 'Orders cleanup' })).toBeInTheDocument();
    const counters = screen.getByRole('region', { name: 'Row counters' });
    const val = (label: string) => within(counters).getByText(label).closest('div')!;
    expect(val('Extracted')).toHaveTextContent('5');
    expect(val('Loaded')).toHaveTextContent('3');
    expect(val('Rejected')).toHaveTextContent('1');
    expect(val('Duplicates dropped')).toHaveTextContent('1');
    expect(val('Null rows dropped')).toHaveTextContent('0');
    expect(counters).toHaveTextContent('not a rejection');
    expect(counters).not.toHaveTextContent('(live)');
    expect(within(screen.getByRole('region', { name: 'Stage events' })).getAllByRole('row').length).toBe(7);
    const rej = await screen.findByRole('region', { name: 'Rejected rows' });
    expect(await within(rej).findByText('type_cast')).toBeInTheDocument();
    expect(within(rej).getByText('abc')).toBeInTheDocument();
  });

  it('lists several entries for one row and pages them', async () => {
    const items = [
      { row_number: 7, column: 'a', rule: 'type_cast', message: 'bad a', value: 'x' },
      { row_number: 7, column: 'b', rule: 'not_null', message: 'bad b', value: null },
    ] as typeof rejections.items;
    const { calls } = renderAt(`/runs/${IDS.runSucceeded}`, {
      'GET /runs/[^/]+/rejections': ({ url }) => json({ total: 120, limit: 50, offset: Number(url.searchParams.get('offset')), items }),
    });
    const rej = await screen.findByRole('region', { name: 'Rejected rows' });
    expect(await within(rej).findAllByText('7')).toHaveLength(2);
    await userEvent.click(within(rej).getByRole('button', { name: 'Next' }));
    await within(rej).findByText('51–100 of 120');
    expect(calls('/rejections').some(([u]) => String(u).includes('offset=50'))).toBe(true);
  });

  it('shows the error message of a failed run and a 404', async () => {
    renderAt(`/runs/${IDS.runSucceeded}`, {
      'GET /runs/[^/]+': () => json({ ...runSucceeded, status: 'failed', error_message: 'Rejection ratio exceeded', dataset_id: null, loaded_count: 0, extracted_count: 5, rejected_count: 5, duplicate_dropped_count: 0 }),
    });
    expect(await screen.findByText('Rejection ratio exceeded')).toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  it('shows a not-found error', async () => {
    renderAt(`/runs/${IDS.runSucceeded}`, { 'GET /runs/[^/]+': () => errorResponse(404, 'not_found', 'Run not found') });
    expect(await screen.findByRole('alert')).toHaveTextContent('Run not found');
  });

  it('updates live every 2 s while running and stops polling at a terminal state', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: false });
    let n = 0;
    const { calls } = renderAt(`/runs/${IDS.runRunning}`, {
      'GET /runs/[^/]+': () => {
        n++;
        if (n === 1) return json(runRunning);
        if (n === 2) return json({ ...runRunning, extracted_count: 8, rejected_count: 3, duplicate_dropped_count: 2 });
        return json({ ...runSucceeded, id: IDS.runRunning, extracted_count: 8, loaded_count: 3, rejected_count: 3, duplicate_dropped_count: 2, null_dropped_count: 0 });
      },
    });
    const tick = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });
    await tick(0);
    expect(screen.getByRole('region', { name: 'Row counters' })).toHaveTextContent('(live)');
    expect(screen.getByText('Updating every 2 seconds.')).toBeInTheDocument();
    expect(calls(`/runs/${IDS.runRunning}`)).toHaveLength(1);

    await tick(2000);
    expect(screen.getByText('Extracted').closest('div')).toHaveTextContent('8');
    expect(screen.getByText('Duplicates dropped').closest('div')).toHaveTextContent('2');

    await tick(2000);
    expect(screen.getByRole('region', { name: 'Row counters' })).not.toHaveTextContent('(live)');
    expect(screen.queryByText('Updating every 2 seconds.')).toBeNull();
    const after = calls(`/runs/${IDS.runRunning}`).length;
    expect(after).toBe(3);
    await tick(20000);
    expect(calls(`/runs/${IDS.runRunning}`)).toHaveLength(after);
    expect(calls('/events')).toHaveLength(3);
  });

  it('shows rejections that only exist once the run is terminal (QA case)', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: false });
    let polls = 0;
    const entry = { row_number: 4, column: 'amount', rule: 'type_cast', message: 'not a float', value: 'abc' };
    renderAt(`/runs/${IDS.runRunning}`, {
      'GET /runs/[^/]+': () => {
        polls++;
        return polls <= 2
          ? json({ ...runRunning, rejected_count: 1 })
          : json({ ...runSucceeded, id: IDS.runRunning, rejected_count: 1 }); // count unchanged at the end
      },
      // entries are persisted only at the end of the run
      'GET /runs/[^/]+/rejections': () =>
        polls < 3 ? json({ total: 0, limit: 50, offset: 0, items: [] }) : json({ total: 1, limit: 50, offset: 0, items: [entry] }),
    });
    const tick = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });
    await tick(0);
    await tick(2000);
    const rej = screen.getByRole('region', { name: 'Rejected rows' });
    expect(rej).toHaveTextContent('1 row(s) rejected so far');
    expect(rej).not.toHaveTextContent('No rejected rows.');

    await tick(2000); // run is now succeeded
    expect(screen.getByRole('region', { name: 'Rejected rows' })).toHaveTextContent('not a float');
    expect(screen.getByText('abc')).toBeInTheDocument();
    expect(rej).not.toHaveTextContent('No rejected rows.');
  });

  it('keeps the previous rejections visible during a refetch', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: false });
    let polls = 0;
    const entry = { row_number: 2, column: 'a', rule: 'not_null', message: 'm', value: null };
    renderAt(`/runs/${IDS.runRunning}`, {
      'GET /runs/[^/]+': () => (++polls === 1 ? json({ ...runRunning, rejected_count: 1 }) : json({ ...runRunning, rejected_count: 2 })),
      'GET /runs/[^/]+/rejections': () => json({ total: 1, limit: 50, offset: 0, items: [entry] }),
    });
    const tick = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });
    await tick(0);
    expect(screen.getByText('not_null')).toBeInTheDocument();
    await tick(2000); // count changes: refetch, old rows stay
    expect(screen.queryByText('Loading rejections…')).toBeNull();
    expect(screen.getByText('not_null')).toBeInTheDocument();
  });
});
