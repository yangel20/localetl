import { useMemo, useState, type FormEvent } from 'react';
import { api } from '../../app/api/client';
import { ApiError } from '../../app/api/errors';
import type { DataSource, ErrorDetail, PipelineConfig, PipelineCreate } from '../../app/api/types';
import { checkConfig, normalizeErrorPath } from './clientChecks';
import { ColumnsEditor } from './ColumnsEditor';
import { columnsFromSource, emptyConfig } from './configModel';
import { SettingsEditor } from './SettingsEditor';
import { TransformationsEditor } from './TransformationsEditor';
import { fieldClass, PathErrors } from './ui';
import { ValidationsEditor } from './ValidationsEditor';

export interface PipelineDraft {
  name: string;
  description: string;
  source_id: string;
  config: PipelineConfig;
}

export function emptyDraft(): PipelineDraft {
  return { name: '', description: '', source_id: '', config: emptyConfig() };
}

function dedupe(list: ErrorDetail[]): ErrorDetail[] {
  const seen = new Set<string>();
  return list.filter((e) => {
    const k = `${e.path}\u0000${e.message}`;
    return seen.has(k) ? false : (seen.add(k), true);
  });
}

export function PipelineForm({
  initial,
  sources,
  submitLabel = 'Save pipeline',
  onSave,
}: {
  initial: PipelineDraft;
  sources: DataSource[];
  submitLabel?: string;
  /** Resolve on success; reject with ApiError to show server errors at their paths. */
  onSave: (body: PipelineCreate) => Promise<void>;
}) {
  const [draft, setDraft] = useState<PipelineDraft>(initial);
  const [attempted, setAttempted] = useState(false);
  const [serverErrors, setServerErrors] = useState<ErrorDetail[]>([]);
  const [status, setStatus] = useState<{ kind: 'idle' | 'busy' | 'valid' | 'error'; message?: string }>({ kind: 'idle' });

  const source = sources.find((s) => s.id === draft.source_id);
  const clientErrors = useMemo(
    () =>
      [
        ...checkConfig(draft.config, { sourceColumns: source?.columns.map((c) => c.name) }),
        ...(draft.name.trim() === '' ? [{ path: '/name', message: 'Enter a name.' }] : []),
        ...(draft.source_id === '' ? [{ path: '/source_id', message: 'Choose a data source.' }] : []),
      ],
    [draft, source],
  );
  const errors = attempted ? dedupe([...clientErrors, ...serverErrors]) : [];

  const set = (patch: Partial<PipelineDraft>) => {
    setDraft((d) => ({ ...d, ...patch }));
    setServerErrors([]);
    setStatus({ kind: 'idle' });
  };
  const setConfig = (config: PipelineConfig) => set({ config });

  function chooseSource(id: string) {
    const s = sources.find((x) => x.id === id);
    const fresh = draft.config.columns.length === 0 && s;
    set({
      source_id: id,
      config: fresh ? { ...draft.config, columns: columnsFromSource(s) } : draft.config,
    });
  }

  function toServerErrors(e: unknown): ApiError {
    const err = e instanceof ApiError ? e : new ApiError(0, 'network_error', 'Request failed');
    setServerErrors(err.details.map((d) => ({ path: normalizeErrorPath(d.path), message: d.message })));
    return err;
  }

  async function validate() {
    setAttempted(true);
    setStatus({ kind: 'busy' });
    try {
      const r = await api.validatePipelineConfig(draft.config, draft.source_id || undefined);
      setServerErrors(r.errors.map((d) => ({ path: normalizeErrorPath(d.path), message: d.message })));
      const total = dedupe([...clientErrors, ...r.errors.map((d) => ({ path: normalizeErrorPath(d.path), message: d.message }))]);
      setStatus(total.length === 0 && r.valid ? { kind: 'valid' } : { kind: 'error', message: `${total.length} problem(s) found.` });
    } catch (e) {
      setStatus({ kind: 'error', message: toServerErrors(e).message });
    }
  }

  async function submit(ev: FormEvent) {
    ev.preventDefault();
    setAttempted(true);
    if (clientErrors.length > 0) {
      return setStatus({ kind: 'error', message: `${clientErrors.length} problem(s) to fix before saving.` });
    }
    setStatus({ kind: 'busy' });
    try {
      await onSave({
        name: draft.name.trim(),
        description: draft.description.trim() || null,
        source_id: draft.source_id,
        config: draft.config,
      });
      setStatus({ kind: 'idle' });
    } catch (e) {
      setStatus({ kind: 'error', message: toServerErrors(e).message });
    }
  }

  const busy = status.kind === 'busy';
  return (
    <form onSubmit={submit} className="space-y-6" aria-label="Pipeline">
      <section className="grid gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-sm">
          Name
          <input className={fieldClass} value={draft.name} maxLength={200} onChange={(e) => set({ name: e.target.value })} />
          <PathErrors errors={errors} path="/name" />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Data source
          <select className={fieldClass} value={draft.source_id} onChange={(e) => chooseSource(e.target.value)}>
            <option value="">Choose…</option>
            {sources.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
          <PathErrors errors={errors} path="/source_id" />
        </label>
        <label className="flex flex-col gap-1 text-sm sm:col-span-2">
          Description (optional)
          <textarea className={fieldClass} rows={2} maxLength={2000} value={draft.description} onChange={(e) => set({ description: e.target.value })} />
        </label>
        {source && (
          <div className="sm:col-span-2">
            <button
              type="button"
              className="rounded border border-border px-2 py-1 text-sm"
              onClick={() => setConfig({ ...draft.config, columns: columnsFromSource(source) })}
            >
              Reset columns from "{source.name}"
            </button>
          </div>
        )}
      </section>

      <ColumnsEditor columns={draft.config.columns} errors={errors} onChange={(columns) => setConfig({ ...draft.config, columns })} />
      <TransformationsEditor
        columns={draft.config.columns}
        items={draft.config.transformations ?? []}
        errors={errors}
        onChange={(transformations) => setConfig({ ...draft.config, transformations })}
      />
      <ValidationsEditor
        columns={draft.config.columns}
        items={draft.config.validations ?? []}
        errors={errors}
        onChange={(validations) => setConfig({ ...draft.config, validations })}
      />
      <SettingsEditor config={draft.config} errors={errors} onChange={setConfig} />

      {errors.length > 0 && (
        <section aria-label="Problems" className="rounded border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
          <h2 className="font-semibold">Problems</h2>
          <ul className="list-disc pl-5">
            {errors.map((e, i) => (
              <li key={i}>
                <code>{e.path}</code>: {e.message}
              </li>
            ))}
          </ul>
        </section>
      )}
      {status.kind === 'valid' && <p role="status" className="text-sm text-success">The configuration is valid.</p>}
      {status.kind === 'error' && status.message && <p role="alert" className="text-sm text-danger">{status.message}</p>}

      <div className="flex gap-3">
        <button type="button" disabled={busy} onClick={validate} className="rounded border border-border px-4 py-2 text-sm">
          Validate
        </button>
        <button type="submit" disabled={busy} className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-fg disabled:opacity-60">
          {busy ? 'Working…' : submitLabel}
        </button>
      </div>
    </form>
  );
}
