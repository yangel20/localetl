import { api as defaultApi, type ApiClient } from '../../app/api/client';
import { ChartFrame } from './ChartFrame';
import { formatCount, formatDuration, successRate, toRowsLoadedPoints } from './format';
import { RowsLoadedChart } from './RowsLoadedChart';
import { RunOutcomesChart } from './RunOutcomesChart';
import { useApiData } from './useApiData';

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-border bg-surface p-3">
      <dt className="text-xs text-fg-muted">{label}</dt>
      <dd className="text-xl font-semibold">{value}</dd>
    </div>
  );
}

/** Run statistics + charts (REQ-52, REQ-55). Mount point for Home/Runs pages. */
export function RunAnalytics({ client = defaultApi, days = 30, width }: { client?: Pick<ApiClient, 'getMetricsSummary' | 'listRuns'>; days?: number; width?: number }) {
  const summary = useApiData((s) => client.getMetricsSummary(days, s), [client, days]);
  const runs = useApiData((s) => client.listRuns({ status: 'succeeded', limit: 50 }, s), [client]);

  return (
    <div className="flex flex-col gap-4" data-testid="run-analytics">
      {summary.status === 'ready' && (
        <dl aria-label="Run statistics" className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="Total runs" value={formatCount(summary.data.total_runs)} />
          <Stat label="Rows loaded" value={formatCount(summary.data.loaded_count_total)} />
          <Stat label="Avg duration" value={formatDuration(summary.data.avg_duration_ms)} />
          <Stat label="Success rate" value={successRate(summary.data)} />
        </dl>
      )}
      <ChartFrame
        title={`Run outcomes per day (last ${days} days)`}
        state={summary}
        isEmpty={(d) => d.total_runs === 0}
        emptyText="No runs yet."
      >
        {(d) => <RunOutcomesChart daily={d.daily} width={width} />}
      </ChartFrame>
      <ChartFrame
        title="Rows loaded per run"
        state={runs}
        isEmpty={(d) => toRowsLoadedPoints(d.items).length === 0}
        emptyText="No succeeded runs yet."
      >
        {(d) => <RowsLoadedChart points={toRowsLoadedPoints(d.items)} width={width} />}
      </ChartFrame>
    </div>
  );
}
