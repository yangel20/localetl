import type { ErrorDetail, PipelineConfig } from '../../app/api/types';
import { fieldClass, PathErrors } from './ui';

export function SettingsEditor({
  config,
  errors,
  onChange,
}: {
  config: PipelineConfig;
  errors: ErrorDetail[];
  onChange: (c: PipelineConfig) => void;
}) {
  return (
    <section aria-label="Target and failure handling" className="space-y-3">
      <h2 className="text-lg font-semibold">Target and failure handling</h2>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-sm">
          Target table
          <input
            className={fieldClass}
            value={config.target.table}
            onChange={(e) => onChange({ ...config, target: { ...config.target, table: e.target.value } })}
          />
          <PathErrors errors={errors} path="/target/table" />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Load mode
          <select
            className={fieldClass}
            value={config.target.mode}
            onChange={(e) => onChange({ ...config, target: { ...config.target, mode: e.target.value as 'replace' | 'append' } })}
          >
            <option value="replace">Replace the table</option>
            <option value="append">Append to the table</option>
          </select>
          <PathErrors errors={errors} path="/target/mode" />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          When a row fails validation
          <select
            className={fieldClass}
            value={config.on_validation_failure ?? 'reject_row'}
            onChange={(e) => onChange({ ...config, on_validation_failure: e.target.value as 'reject_row' | 'fail_run' })}
          >
            <option value="reject_row">Reject the row and continue</option>
            <option value="fail_run">Fail the run</option>
          </select>
          <PathErrors errors={errors} path="/on_validation_failure" />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Maximum rejected ratio (0–1)
          <input
            type="number" min={0} max={1} step="any"
            className={fieldClass}
            value={config.max_rejected_ratio ?? 1}
            onChange={(e) => onChange({ ...config, max_rejected_ratio: e.target.value === '' ? NaN : Number(e.target.value) })}
          />
          <span className="text-xs text-fg-muted">Rows dropped by deduplicate or drop-null are not rejections.</span>
          <PathErrors errors={errors} path="/max_rejected_ratio" />
        </label>
      </div>
    </section>
  );
}
