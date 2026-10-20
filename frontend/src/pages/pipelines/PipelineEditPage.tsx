import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../../app/api/client';
import { ErrorMessage } from '../../components/ErrorMessage';
import { useAsync } from '../../components/useAsync';
import { PipelineForm } from '../../features/pipelines/PipelineForm';

export function PipelineEditPage() {
  const { pipelineId = '' } = useParams();
  const [saved, setSaved] = useState<number | null>(null);
  const state = useAsync(
    async (signal) => {
      const [pipeline, page] = await Promise.all([
        api.getPipeline(pipelineId, signal),
        api.listSources({ limit: 200 }, signal),
      ]);
      // The pipeline's own source may fall outside the first page of sources.
      const sources = page.items.some((s) => s.id === pipeline.source_id)
        ? page.items
        : [await api.getSource(pipeline.source_id, signal), ...page.items];
      return { pipeline, sources };
    },
    [pipelineId],
  );

  return (
    <section className="space-y-4">
      <p className="text-sm"><Link className="text-primary underline" to="/pipelines">← Pipelines</Link></p>
      {state.status === 'loading' && <p role="status">Loading pipeline…</p>}
      {state.status === 'error' && <ErrorMessage error={state.error} onRetry={state.reload} />}
      {state.status === 'success' && (
        <>
          <h1 className="text-2xl font-semibold">Edit {state.data.pipeline.name}</h1>
          <p className="text-sm text-fg-muted">
            Config version {saved ?? state.data.pipeline.config_version}. Saving creates a new version; runs already queued keep their snapshot.
          </p>
          {saved !== null && <p role="status" className="text-sm text-success">Saved (version {saved}).</p>}
          <PipelineForm
            key={state.data.pipeline.id}
            initial={{
              name: state.data.pipeline.name,
              description: state.data.pipeline.description ?? '',
              source_id: state.data.pipeline.source_id,
              config: state.data.pipeline.config,
            }}
            sources={state.data.sources}
            onSave={async (body) => {
              const p = await api.updatePipeline(pipelineId, body);
              setSaved(p.config_version);
            }}
          />
        </>
      )}
    </section>
  );
}
