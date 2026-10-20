import { Link, useParams } from 'react-router-dom';
import { api } from '../../app/api/client';
import { ErrorMessage } from '../../components/ErrorMessage';
import { PreviewTable } from '../../components/sources/PreviewTable';
import { formatBytes } from '../../components/sources/uploadRules';
import { useAsync } from '../../components/useAsync';

const PREVIEW_ROWS = 50;

export function SourceDetailPage() {
  const { sourceId = '' } = useParams();
  const state = useAsync(
    async (signal) => {
      const [source, preview] = await Promise.all([
        api.getSource(sourceId, signal),
        api.previewSource(sourceId, PREVIEW_ROWS, signal),
      ]);
      return { source, preview };
    },
    [sourceId],
  );

  return (
    <section className="space-y-4">
      <p className="text-sm"><Link className="text-primary underline" to="/sources">← Sources</Link></p>
      {state.status === 'loading' && <p role="status">Loading preview…</p>}
      {state.status === 'error' && <ErrorMessage error={state.error} onRetry={state.reload} />}
      {state.status === 'success' && (
        <>
          <h1 className="text-2xl font-semibold">{state.data.source.name}</h1>
          <p className="text-sm text-fg-muted">
            {state.data.source.original_filename} · {formatBytes(state.data.source.size_bytes)} ·{' '}
            {state.data.source.row_count} rows · {state.data.source.columns.length} columns
          </p>
          <h2 className="text-lg font-semibold">
            Preview ({state.data.preview.sampled_rows} rows sampled)
          </h2>
          <PreviewTable preview={state.data.preview} />
        </>
      )}
    </section>
  );
}
