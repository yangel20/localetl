import { useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../../app/api/client';
import type { RejectedRowPage } from '../../app/api/types';
import { ErrorMessage } from '../../components/ErrorMessage';
import { Pager } from '../../components/Pager';
import { RejectionsTable } from '../../components/runs/RejectionsTable';
import { RunCounters } from '../../components/runs/RunCounters';
import { formatDuration, isTerminal } from '../../components/runs/runStatus';
import { StageEvents } from '../../components/runs/StageEvents';
import { StatusBadge } from '../../components/runs/StatusBadge';
import { usePolledRun } from '../../components/runs/usePolledRun';
import { useAsync } from '../../components/useAsync';

const REJECTION_PAGE = 50;

export function RunDetailPage() {
  const { runId = '' } = useParams();
  const { run, events, error, loading } = usePolledRun(runId);

  return (
    <section className="space-y-6">
      <p className="text-sm"><Link className="text-primary underline" to="/runs">← Runs</Link></p>
      {loading && !run && <p role="status">Loading run…</p>}
      {error && <ErrorMessage error={error} />}
      {run && (
        <>
          <header className="space-y-1">
            <h1 className="text-2xl font-semibold">{run.pipeline_name}</h1>
            <p className="text-sm">
              <StatusBadge status={run.status} />
              {run.current_stage && !isTerminal(run.status) && <span> · stage: {run.current_stage}</span>}
              {' · '}queued {new Date(run.queued_at).toLocaleString()}
              {' · '}duration {formatDuration(run.duration_ms)}
              {' · '}config version {run.config_version}
            </p>
            {!isTerminal(run.status) && <p className="text-xs text-fg-muted">Updating every 2 seconds.</p>}
            {run.error_message && (
              <p role="alert" className="rounded border border-danger/40 bg-danger/10 p-2 text-sm text-danger">
                {run.error_message}
              </p>
            )}
            {run.dataset_id && <p className="text-sm">Published as dataset <code>{run.dataset_id}</code>.</p>}
          </header>

          <RunCounters run={run} live={!isTerminal(run.status)} />

          <section aria-label="Stage events" className="space-y-2">
            <h2 className="text-lg font-semibold">Stage events</h2>
            <StageEvents events={events} />
          </section>

          <Rejections runId={run.id} rejectedCount={run.rejected_count} terminal={isTerminal(run.status)} />
        </>
      )}
    </section>
  );
}

function Rejections({ runId, rejectedCount, terminal }: { runId: string; rejectedCount: number; terminal: boolean }) {
  const [offset, setOffset] = useState(0);
  // Entries are persisted only when the run finishes, so refetch at the terminal state as well as
  // when the live count grows.
  const page = useAsync(
    (signal) => api.listRunRejections(runId, { limit: REJECTION_PAGE, offset }, signal),
    [runId, offset, rejectedCount, terminal],
  );
  // Keep showing the last page while a refetch is in flight (no flicker back to "Loading").
  const last = useRef<RejectedRowPage | null>(null);
  if (page.status === 'success') last.current = page.data;
  const data = page.status === 'success' ? page.data : last.current;

  return (
    <section aria-label="Rejected rows" className="space-y-2">
      <h2 className="text-lg font-semibold">Rejected rows</h2>
      <p className="text-xs text-fg-muted">
        A row that fails several rules is listed once per failure. At most 1,000 entries are stored per run.
      </p>
      {!data && page.status === 'loading' && <p role="status">Loading rejections…</p>}
      {page.status === 'error' && <ErrorMessage error={page.error} onRetry={page.reload} />}
      {data && (
        <>
          {data.items.length === 0 && !terminal && rejectedCount > 0 ? (
            <p className="text-fg-muted">
              {rejectedCount} row(s) rejected so far. The entries appear here when the run finishes.
            </p>
          ) : (
            <RejectionsTable items={data.items} />
          )}
          <Pager total={data.total} limit={data.limit} offset={data.offset} onChange={setOffset} />
        </>
      )}
    </section>
  );
}
