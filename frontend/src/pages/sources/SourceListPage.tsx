import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../../app/api/client';
import { ErrorMessage } from '../../components/ErrorMessage';
import { Pager } from '../../components/Pager';
import { UploadForm } from '../../components/sources/UploadForm';
import { formatBytes } from '../../components/sources/uploadRules';
import { useAsync } from '../../components/useAsync';

const PAGE_SIZE = 20;

export function SourceListPage() {
  const [offset, setOffset] = useState(0);
  const navigate = useNavigate();
  const list = useAsync((signal) => api.listSources({ limit: PAGE_SIZE, offset }, signal), [offset]);

  return (
    <section className="space-y-6">
      <h1 className="text-2xl font-semibold">Sources</h1>
      <UploadForm onUploaded={(s) => navigate(`/sources/${s.id}`)} />

      <div>
        <h2 className="mb-2 text-lg font-semibold">Uploaded sources</h2>
        {list.status === 'loading' && <p role="status">Loading sources…</p>}
        {list.status === 'error' && <ErrorMessage error={list.error} onRetry={list.reload} />}
        {list.status === 'success' && list.data.items.length === 0 && (
          <p className="text-fg-muted">No sources yet. Upload a CSV file to get started.</p>
        )}
        {list.status === 'success' && list.data.items.length > 0 && (
          <>
            <div className="overflow-x-auto rounded border border-border">
              <table className="min-w-full text-left text-sm">
                <thead className="bg-surface-muted">
                  <tr>
                    <th scope="col" className="px-3 py-2">Name</th>
                    <th scope="col" className="px-3 py-2">File</th>
                    <th scope="col" className="px-3 py-2">Size</th>
                    <th scope="col" className="px-3 py-2">Rows</th>
                    <th scope="col" className="px-3 py-2">Columns</th>
                    <th scope="col" className="px-3 py-2">Uploaded</th>
                  </tr>
                </thead>
                <tbody>
                  {list.data.items.map((s) => (
                    <tr key={s.id} className="border-t border-border">
                      <td className="px-3 py-1.5">
                        <Link className="text-primary underline" to={`/sources/${s.id}`}>{s.name}</Link>
                      </td>
                      <td className="px-3 py-1.5">{s.original_filename}</td>
                      <td className="px-3 py-1.5">{formatBytes(s.size_bytes)}</td>
                      <td className="px-3 py-1.5">{s.row_count}</td>
                      <td className="px-3 py-1.5">{s.columns.length}</td>
                      <td className="px-3 py-1.5">{new Date(s.created_at).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager total={list.data.total} limit={list.data.limit} offset={list.data.offset} onChange={setOffset} />
          </>
        )}
      </div>
    </section>
  );
}
