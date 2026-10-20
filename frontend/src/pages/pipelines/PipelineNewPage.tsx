import { Link, useNavigate } from 'react-router-dom';
import { api } from '../../app/api/client';
import { ErrorMessage } from '../../components/ErrorMessage';
import { useAsync } from '../../components/useAsync';
import { emptyDraft, PipelineForm } from '../../features/pipelines/PipelineForm';

export function PipelineNewPage() {
  const navigate = useNavigate();
  const sources = useAsync((signal) => api.listSources({ limit: 200 }, signal), []);
  return (
    <section className="space-y-4">
      <p className="text-sm"><Link className="text-primary underline" to="/pipelines">← Pipelines</Link></p>
      <h1 className="text-2xl font-semibold">New pipeline</h1>
      {sources.status === 'loading' && <p role="status">Loading sources…</p>}
      {sources.status === 'error' && <ErrorMessage error={sources.error} onRetry={sources.reload} />}
      {sources.status === 'success' && sources.data.items.length === 0 && (
        <p>
          A pipeline needs a data source. <Link className="text-primary underline" to="/sources">Upload a CSV first.</Link>
        </p>
      )}
      {sources.status === 'success' && sources.data.items.length > 0 && (
        <PipelineForm
          initial={emptyDraft()}
          sources={sources.data.items}
          submitLabel="Create pipeline"
          onSave={async (body) => {
            await api.createPipeline(body);
            navigate('/pipelines');
          }}
        />
      )}
    </section>
  );
}
