import { useState } from 'react';
import { api } from '../../app/api/client';
import { ApiError } from '../../app/api/errors';
import type { Run } from '../../app/api/types';
import { ErrorMessage } from '../ErrorMessage';
import { useAsync } from '../useAsync';

/** Pick a pipeline and queue a run. A 409 (a run is already queued or running) is shown as returned. */
export function RunStarter({ onStarted }: { onStarted: (run: Run) => void }) {
  const pipelines = useAsync((signal) => api.listPipelines({ limit: 200 }, signal), []);
  const [pipelineId, setPipelineId] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      onStarted(await api.createRun(pipelineId));
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, 'network_error', 'Could not start the run'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-label="Start a run" className="space-y-2 rounded border border-border bg-surface-muted p-4">
      <h2 className="text-lg font-semibold">Start a run</h2>
      {pipelines.status === 'loading' && <p role="status">Loading pipelines…</p>}
      {pipelines.status === 'error' && <ErrorMessage error={pipelines.error} onRetry={pipelines.reload} />}
      {pipelines.status === 'success' && pipelines.data.items.length === 0 && (
        <p className="text-fg-muted">No pipelines to run yet.</p>
      )}
      {pipelines.status === 'success' && pipelines.data.items.length > 0 && (
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-sm">
            Pipeline
            <select
              className="rounded border border-border bg-surface px-2 py-1"
              value={pipelineId}
              onChange={(e) => {
                setPipelineId(e.target.value);
                setError(null);
              }}
            >
              <option value="">Choose…</option>
              {pipelines.data.items.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </label>
          <button
            type="button"
            disabled={busy || pipelineId === ''}
            onClick={() => void start()}
            className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-fg disabled:opacity-60"
          >
            {busy ? 'Starting…' : 'Run'}
          </button>
        </div>
      )}
      {error && (
        <div>
          <ErrorMessage error={error} />
          {error.status === 409 && (
            <p className="mt-1 text-sm text-fg-muted">This pipeline already has a queued or running run. Wait for it to finish, then try again.</p>
          )}
        </div>
      )}
    </section>
  );
}
