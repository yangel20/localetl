import { useState } from 'react';
import type { ColumnMapping, ColumnType, ErrorDetail, Transformation } from '../../app/api/types';
import { moveItem, newTransformation, OP_LABEL, TRANSFORMATION_OPS } from './configModel';
import { MappingEditor } from './ListInputs';
import { ScalarInput } from './ScalarInput';
import { btnClass, ColumnChecklist, ColumnSelect, fieldClass, PathErrors } from './ui';

export function TransformationsEditor({
  columns,
  items,
  errors,
  onChange,
}: {
  columns: ColumnMapping[];
  items: Transformation[];
  errors: ErrorDetail[];
  onChange: (t: Transformation[]) => void;
}) {
  const [gen, setGen] = useState(0); // bumped on reorder/remove so item inputs remount
  const reshape = (next: Transformation[]) => {
    setGen((g) => g + 1);
    onChange(next);
  };
  const names = columns.map((c) => c.name);
  const typeOf = (n: string): ColumnType => columns.find((c) => c.name === n)?.type ?? 'string';
  const set = (i: number, t: Transformation) => onChange(items.map((x, j) => (j === i ? t : x)));

  return (
    <section aria-label="Transformations" className="space-y-2">
      <h2 className="text-lg font-semibold">Transformations</h2>
      <p className="text-sm text-fg-muted">They run in the order listed, after columns are mapped and typed.</p>
      <PathErrors errors={errors} path="/transformations" />
      <ol className="space-y-3">
        {items.map((t, i) => {
          const p = `/transformations/${i}`;
          return (
            <li key={`${gen}-${i}`} className="space-y-2 rounded border border-border p-3" aria-label={`Transformation ${i + 1}: ${OP_LABEL[t.op]}`}>
              <div className="flex flex-wrap items-center gap-2">
                <strong>{i + 1}. {OP_LABEL[t.op]}</strong>
                <span className="grow" />
                <button type="button" className={btnClass} disabled={i === 0} aria-label={`Move transformation ${i + 1} up`} onClick={() => reshape(moveItem(items, i, i - 1))}>↑</button>
                <button type="button" className={btnClass} disabled={i === items.length - 1} aria-label={`Move transformation ${i + 1} down`} onClick={() => reshape(moveItem(items, i, i + 1))}>↓</button>
                <button type="button" className={btnClass} aria-label={`Remove transformation ${i + 1}`} onClick={() => reshape(items.filter((_, j) => j !== i))}>Remove</button>
              </div>
              {(t.op === 'trim_whitespace' || t.op === 'change_case' || t.op === 'drop_null_rows') && (
                <ColumnChecklist label="Columns" names={names} value={t.columns} onChange={(columns) => set(i, { ...t, columns })} />
              )}
              {t.op === 'deduplicate' && (
                <ColumnChecklist
                  label="Columns (none selected = whole row)"
                  names={names}
                  value={t.columns ?? []}
                  onChange={(cols) => set(i, cols.length ? { ...t, columns: cols } : { op: 'deduplicate' })}
                />
              )}
              {t.op === 'change_case' && (
                <label className="flex flex-col gap-1 text-sm">
                  Case
                  <select className={fieldClass} value={t.case} onChange={(e) => set(i, { ...t, case: e.target.value as typeof t.case })}>
                    <option value="lower">lower</option>
                    <option value="upper">upper</option>
                    <option value="title">title</option>
                  </select>
                </label>
              )}
              {t.op === 'drop_null_rows' && (
                <label className="flex flex-col gap-1 text-sm">
                  Drop when
                  <select className={fieldClass} value={t.how ?? 'any'} onChange={(e) => set(i, { ...t, how: e.target.value as 'any' | 'all' })}>
                    <option value="any">any listed column is empty</option>
                    <option value="all">all listed columns are empty</option>
                  </select>
                </label>
              )}
              {(t.op === 'replace_values' || t.op === 'fill_null' || t.op === 'round_number') && (
                <ColumnSelect label="Column" names={names} value={t.column} onChange={(column) => set(i, { ...t, column })} />
              )}
              {t.op === 'replace_values' && (
                <MappingEditor type={typeOf(t.column)} mapping={t.mapping} onCommit={(mapping) => set(i, { ...t, mapping })} />
              )}
              {t.op === 'fill_null' && (
                <ScalarInput label="Fill value" type={typeOf(t.column)} value={t.value} onCommit={(value) => set(i, { ...t, value })} />
              )}
              {t.op === 'round_number' && (
                <label className="flex flex-col gap-1 text-sm">
                  Decimal places (0–10)
                  <input
                    type="number" min={0} max={10} step={1}
                    className={fieldClass}
                    value={t.decimals}
                    onChange={(e) => set(i, { ...t, decimals: e.target.value === '' ? NaN : Number(e.target.value) })}
                  />
                </label>
              )}
              <PathErrors errors={errors} path={p} exact={false} />
            </li>
          );
        })}
      </ol>
      <label className="flex items-center gap-2 text-sm">
        Add transformation
        <select
          className={fieldClass}
          value=""
          disabled={names.length === 0}
          onChange={(e) => {
            if (e.target.value) onChange([...items, newTransformation(e.target.value as Transformation['op'], names[0] ?? '')]);
          }}
        >
          <option value="">Choose…</option>
          {TRANSFORMATION_OPS.map((op) => (
            <option key={op} value={op}>{OP_LABEL[op]}</option>
          ))}
        </select>
      </label>
    </section>
  );
}
