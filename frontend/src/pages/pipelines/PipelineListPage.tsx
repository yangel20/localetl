import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../app/api/client';
import { ApiError } from '../../app/api/errors';
import type { Pipeline } from '../../app/api/types';
import { ErrorMessage } from '../../components/ErrorMessage';
import { Pager } from '../../components/Pager';
import { useAsync } from '../../components/useAsync';

const PAGE_SIZE = 20;

export function PipelineListPage() {
  const [offset, setOffset] = useState(0);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<ApiError | null>(null);
  const list = useAsync((signal) => api.listPipelines({ limit: PAGE_SIZE, offset }, signal), [offset]);

  async function remove(p: Pipeline) {
    setDeleteError(null);
    try {
      await api.deletePipeline(p.id);
      setConfirming(null);
      // Step back a page if that deleted the last row of a later page.
      if (list.status === 'success' && list.data.items.length === 1 && offset > 0) setOffset(Math.max(0, offset - PAGE_SIZE));
      else list.reload();
    } catch (e) {
      setConfirming(null);
      setDeleteError(e instanceof ApiError ? e : new ApiError(0, 'network_error', 'Delete failed'));
    }
  }

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Pipelines</h1>
        <Link to="/pipelines/new" className="rounded bg-primary px-3 py-2 text-sm font-medium text-primary-fg">
          New pipeline
        </Link>
      </div>
      {deleteError && <ErrorMessage error={deleteError} />}
      {list.status === 'loading' && <p role="status">Loading pipelines…</p>}
      {list.status === 'error' && <ErrorMessage error={list.error} onRetry={list.reload} />}
      {list.status === 'success' && list.data.items.length === 0 && (
        <p className="text-fg-muted">No pipelines yet. Create one from an uploaded source.</p>
      )}
      {list.status === 'success' && list.data.items.length > 0 && (
        <>
          <div className="overflow-x-auto rounded border border-border">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-surface-muted">
                <tr>
                  <th scope="col" className="px-3 py-2">Name</th>
                  <th scope="col" className="px-3 py-2">Target</th>
                  <th scope="col" className="px-3 py-2">Version</th>
                  <th scope="col" className="px-3 py-2">Last run</th>
                  <th scope="col" className="px-3 py-2">Updated</th>
                  <th scope="col" className="px-3 py-2"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((p) => (
                  <tr key={p.id} className="border-t border-border">
                    <td className="px-3 py-1.5">
                      <Link className="text-primary underline" to={`/pipelines/${p.id}`}>{p.name}</Link>
                    </td>
                    <td className="px-3 py-1.5">{p.config.target.table} ({p.config.target.mode})</td>
                    <td className="px-3 py-1.5">{p.config_version}</td>
                    <td className="px-3 py-1.5">
                      {p.last_run ? <Link to={`/runs/${p.last_run.id}`}><span className="capitalize">{p.last_run.status}</span></Link> : <span className="text-fg-muted">never</span>}
                    </td>
                    <td className="px-3 py-1.5">{new Date(p.updated_at).toLocaleString()}</td>
                    <td className="px-3 py-1.5">
                      {confirming === p.id ? (
                        <span className="flex gap-2">
                          <button type="button" className="rounded bg-danger px-2 py-1 text-primary-fg" onClick={() => void remove(p)}>
                            Confirm delete {p.name}
                          </button>
                          <button type="button" className="rounded border border-border px-2 py-1" onClick={() => setConfirming(null)}>
                            Cancel
                          </button>
                        </span>
                      ) : (
                        <button type="button" className="rounded border border-border px-2 py-1" aria-label={`Delete ${p.name}`} onClick={() => setConfirming(p.id)}>
                          Delete
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pager total={list.data.total} limit={list.data.limit} offset={list.data.offset} onChange={setOffset} />
        </>
      )}
    </section>
  );
}
