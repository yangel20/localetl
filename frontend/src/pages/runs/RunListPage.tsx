import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../../app/api/client';
import type { RunStatus } from '../../app/api/types';
import { ErrorMessage } from '../../components/ErrorMessage';
import { Pager } from '../../components/Pager';
import { MetricsText } from '../../components/runs/MetricsText';
import { RunStarter } from '../../components/runs/RunStarter';
import { formatDuration, STATUS_LABEL } from '../../components/runs/runStatus';
import { StatusBadge } from '../../components/runs/StatusBadge';
import { useAsync } from '../../components/useAsync';

const PAGE_SIZE = 20;
const field = 'rounded border border-border bg-surface px-2 py-1 text-sm';

export function RunListPage() {
  const navigate = useNavigate();
  const [pipelineId, setPipelineId] = useState('');
  const [status, setStatus] = useState<RunStatus | ''>('');
  const [offset, setOffset] = useState(0);

  const pipelines = useAsync((signal) => api.listPipelines({ limit: 200 }, signal), []);
  const metrics = useAsync((signal) => api.getMetricsSummary(30, signal), []);
  const runs = useAsync(
    (signal) =>
      api.listRuns(
        { pipeline_id: pipelineId || undefined, status: status || undefined, limit: PAGE_SIZE, offset },
        signal,
      ),
    [pipelineId, status, offset],
  );

  return (
    <section className="space-y-6">
      <h1 className="text-2xl font-semibold">Runs</h1>
      <RunStarter onStarted={(run) => navigate(`/runs/${run.id}`)} />

      {metrics.status === 'success' && <MetricsText metrics={metrics.data} />}
      {metrics.status === 'error' && <ErrorMessage error={metrics.error} onRetry={metrics.reload} />}

      <section aria-label="History" className="space-y-3">
        <h2 className="text-lg font-semibold">History</h2>
        <div className="flex flex-wrap gap-3">
          <label className="flex flex-col gap-1 text-sm">
            Pipeline
            <select
              className={field}
              value={pipelineId}
              onChange={(e) => {
                setPipelineId(e.target.value);
                setOffset(0);
              }}
            >
              <option value="">All pipelines</option>
              {pipelines.status === 'success' &&
                pipelines.data.items.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            Status
            <select
              className={field}
              value={status}
              onChange={(e) => {
                setStatus(e.target.value as RunStatus | '');
                setOffset(0);
              }}
            >
              <option value="">Any status</option>
              {(Object.keys(STATUS_LABEL) as RunStatus[]).map((s) => (
                <option key={s} value={s}>{STATUS_LABEL[s]}</option>
              ))}
            </select>
          </label>
        </div>

        {runs.status === 'loading' && <p role="status">Loading runs…</p>}
        {runs.status === 'error' && <ErrorMessage error={runs.error} onRetry={runs.reload} />}
        {runs.status === 'success' && runs.data.items.length === 0 && (
          <p className="text-fg-muted">{pipelineId || status ? 'No runs match these filters.' : 'No runs yet.'}</p>
        )}
        {runs.status === 'success' && runs.data.items.length > 0 && (
          <>
            <div className="overflow-x-auto rounded border border-border">
              <table className="min-w-full text-left text-sm">
                <thead className="bg-surface-muted">
                  <tr>
                    <th scope="col" className="px-3 py-2">Pipeline</th>
                    <th scope="col" className="px-3 py-2">Status</th>
                    <th scope="col" className="px-3 py-2">Queued</th>
                    <th scope="col" className="px-3 py-2">Duration</th>
                    <th scope="col" className="px-3 py-2">Loaded</th>
                    <th scope="col" className="px-3 py-2">Rejected</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.data.items.map((r) => (
                    <tr key={r.id} className="border-t border-border">
                      <td className="px-3 py-1.5">
                        <Link className="text-primary underline" to={`/runs/${r.id}`}>{r.pipeline_name}</Link>
                      </td>
                      <td className="px-3 py-1.5"><StatusBadge status={r.status} /></td>
                      <td className="px-3 py-1.5">{new Date(r.queued_at).toLocaleString()}</td>
                      <td className="px-3 py-1.5">{formatDuration(r.duration_ms)}</td>
                      <td className="px-3 py-1.5">{r.loaded_count}</td>
                      <td className="px-3 py-1.5">{r.rejected_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager total={runs.data.total} limit={runs.data.limit} offset={runs.data.offset} onChange={setOffset} />
          </>
        )}
      </section>
    </section>
  );
}
