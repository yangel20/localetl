import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { createApiClient } from '../../app/api/client';
import { errorResponse, createMockFetch } from '../../app/api/mockFetch';
import { metricsSummary } from '../../app/api/fixtures';
import { RunAnalytics } from './RunAnalytics';

const client = (overrides = {}) => createApiClient({ baseUrl: 'http://x/api/v1', fetch: createMockFetch(overrides) });
const json = (b: unknown) => () => new Response(JSON.stringify(b), { headers: { 'Content-Type': 'application/json' } });

describe('RunAnalytics', () => {
  it('shows loading, then stats and charts from the API client', async () => {
    render(<RunAnalytics client={client()} width={600} />);
    expect(screen.getAllByRole('status')).toHaveLength(2);
    const stats = await screen.findByLabelText('Run statistics');
    expect(within(stats).getByText('2.0 s')).toBeInTheDocument();
    expect(within(stats).getByText('100%')).toBeInTheDocument();
    const outcomes = await screen.findByTestId('run-outcomes-chart');
    expect(within(within(outcomes).getByRole('table', { hidden: true })).getByText('Oct 19')).toBeInTheDocument();
    const rows = await screen.findByTestId('rows-loaded-chart');
    expect(within(rows).getByText('Orders cleanup')).toBeInTheDocument();
    expect(rows.querySelector('svg')).not.toBeNull();
  });

  it('shows empty states', async () => {
    const c = client({
      'GET /metrics/summary': json({ ...metricsSummary, total_runs: 0, avg_duration_ms: null, daily: [] }),
      'GET /runs': json({ total: 0, limit: 50, offset: 0, items: [] }),
    });
    render(<RunAnalytics client={c} />);
    expect(await screen.findByText('No runs yet.')).toBeInTheDocument();
    expect(await screen.findByText('No succeeded runs yet.')).toBeInTheDocument();
  });

  it('shows per-chart errors', async () => {
    const c = client({ 'GET /metrics/summary': () => errorResponse(500, 'internal_error', 'boom') });
    render(<RunAnalytics client={c} width={600} />);
    expect(await screen.findByText('boom')).toBeInTheDocument();
    expect(await screen.findByTestId('rows-loaded-chart')).toBeInTheDocument();
  });
});
