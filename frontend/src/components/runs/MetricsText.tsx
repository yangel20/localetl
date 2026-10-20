import type { MetricsSummary } from '../../app/api/types';
import { formatDuration, STATUS_LABEL } from './runStatus';

/** Metrics as plain text; charts arrive in Wave 2. */
export function MetricsText({ metrics }: { metrics: MetricsSummary }) {
  const statuses = Object.keys(STATUS_LABEL) as (keyof typeof STATUS_LABEL)[];
  return (
    <section aria-label="Metrics" className="space-y-2">
      <h2 className="text-lg font-semibold">Metrics</h2>
      <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <div><dt className="text-fg-muted">Total runs</dt><dd className="text-xl font-semibold">{metrics.total_runs}</dd></div>
        <div><dt className="text-fg-muted">Rows loaded</dt><dd className="text-xl font-semibold">{metrics.loaded_count_total.toLocaleString()}</dd></div>
        <div><dt className="text-fg-muted">Average duration</dt><dd className="text-xl font-semibold">{formatDuration(metrics.avg_duration_ms === null ? null : Math.round(metrics.avg_duration_ms))}</dd></div>
        <div>
          <dt className="text-fg-muted">By status</dt>
          <dd>{statuses.map((s) => `${STATUS_LABEL[s]}: ${metrics.runs_by_status[s]}`).join(' · ')}</dd>
        </div>
      </dl>
    </section>
  );
}
