import type { ColumnMapping, ColumnType, ErrorDetail } from '../../app/api/types';
import { checkFormat } from './casting';
import { btnClass, fieldClass, PathErrors } from './ui';

const TYPES: ColumnType[] = ['integer', 'float', 'boolean', 'date', 'datetime', 'string'];

export function ColumnsEditor({
  columns,
  errors,
  onChange,
}: {
  columns: ColumnMapping[];
  errors: ErrorDetail[];
  onChange: (c: ColumnMapping[]) => void;
}) {
  const update = (i: number, patch: Partial<ColumnMapping>) =>
    onChange(columns.map((c, j) => (j === i ? { ...c, ...patch } : c)));

  return (
    <section aria-label="Columns" className="space-y-2">
      <h2 className="text-lg font-semibold">Columns</h2>
      <PathErrors errors={errors} path="/columns" />
      <div className="overflow-x-auto rounded border border-border">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-surface-muted">
            <tr>
              <th scope="col" className="px-2 py-2">Source column</th>
              <th scope="col" className="px-2 py-2">Name</th>
              <th scope="col" className="px-2 py-2">Type</th>
              <th scope="col" className="px-2 py-2">Date format</th>
              <th scope="col" className="px-2 py-2">Allow empty</th>
              <th scope="col" className="px-2 py-2"><span className="sr-only">Remove</span></th>
            </tr>
          </thead>
          <tbody>
            {columns.map((c, i) => {
              const p = `/columns/${i}`;
              const dateLike = c.type === 'date' || c.type === 'datetime';
              const formatProblem = c.format ? checkFormat(c.format, c.type) : null;
              return (
                <tr key={i} className="border-t border-border align-top">
                  <td className="px-2 py-1.5">
                    {c.source}
                    <PathErrors errors={errors} path={`${p}/source`} />
                  </td>
                  <td className="px-2 py-1.5">
                    <input
                      aria-label={`Name for ${c.source}`}
                      className={fieldClass}
                      value={c.name}
                      onChange={(e) => update(i, { name: e.target.value })}
                    />
                    <PathErrors errors={errors} path={`${p}/name`} />
                  </td>
                  <td className="px-2 py-1.5">
                    <select
                      aria-label={`Type for ${c.source}`}
                      className={fieldClass}
                      value={c.type}
                      onChange={(e) => {
                        const type = e.target.value as ColumnType;
                        // rule 7: drop a format that the new type does not allow
                        const keep = type === 'date' || type === 'datetime';
                        update(i, { type, ...(keep ? {} : { format: undefined }) });
                      }}
                    >
                      {TYPES.map((t) => (
                        <option key={t}>{t}</option>
                      ))}
                    </select>
                    <PathErrors errors={errors} path={`${p}/type`} />
                  </td>
                  <td className="px-2 py-1.5">
                    {dateLike ? (
                      <>
                        <input
                          aria-label={`Date format for ${c.source}`}
                          className={fieldClass}
                          placeholder="%Y-%m-%d (optional)"
                          value={c.format ?? ''}
                          onChange={(e) => update(i, { format: e.target.value || undefined })}
                        />
                        {formatProblem && <span className="block text-xs text-danger">{formatProblem}</span>}
                      </>
                    ) : (
                      <span className="text-fg-muted">—</span>
                    )}
                    <PathErrors errors={errors} path={`${p}/format`} />
                  </td>
                  <td className="px-2 py-1.5">
                    <input
                      type="checkbox"
                      aria-label={`Allow empty for ${c.source}`}
                      checked={c.nullable ?? true}
                      onChange={(e) => update(i, { nullable: e.target.checked })}
                    />
                  </td>
                  <td className="px-2 py-1.5">
                    <button
                      type="button"
                      className={btnClass}
                      aria-label={`Remove ${c.source}`}
                      onClick={() => onChange(columns.filter((_, j) => j !== i))}
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
