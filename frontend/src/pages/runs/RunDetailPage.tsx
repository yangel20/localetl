import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../../app/api/client';
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

          <Rejections runId={run.id} rejectedCount={run.rejected_count} />
        </>
      )}
    </section>
  );
}

function Rejections({ runId, rejectedCount }: { runId: string; rejectedCount: number }) {
  const [offset, setOffset] = useState(0);
  // Refetch as the live rejected count grows, so the table follows the run.
  const page = useAsync(
    (signal) => api.listRunRejections(runId, { limit: REJECTION_PAGE, offset }, signal),
    [runId, offset, rejectedCount],
  );
  return (
    <section aria-label="Rejected rows" className="space-y-2">
      <h2 className="text-lg font-semibold">Rejected rows</h2>
      <p className="text-xs text-fg-muted">
        A row that fails several rules is listed once per failure. At most 1,000 entries are stored per run.
      </p>
      {page.status === 'loading' && <p role="status">Loading rejections…</p>}
      {page.status === 'error' && <ErrorMessage error={page.error} onRetry={page.reload} />}
      {page.status === 'success' && (
        <>
          <RejectionsTable items={page.data.items} />
          <Pager total={page.data.total} limit={page.data.limit} offset={page.data.offset} onChange={setOffset} />
        </>
      )}
    </section>
  );
}
