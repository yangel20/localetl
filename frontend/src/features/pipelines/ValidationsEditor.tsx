import { useState } from 'react';
import type { ColumnMapping, ColumnType, ErrorDetail, Validation } from '../../app/api/types';
import { isIsoDate, isIsoDatetime } from './casting';
import { moveItem, newValidation, RULE_LABEL, VALIDATION_RULES } from './configModel';
import { ValueLines } from './ListInputs';
import { btnClass, ColumnChecklist, ColumnSelect, fieldClass, PathErrors } from './ui';

/** Bound input: number for integer/float columns, ISO string for date/datetime. Empty removes the bound. */
function BoundInput({ label, type, value, onCommit }: { label: string; type: ColumnType; value: number | string | undefined; onCommit: (v: number | string | undefined) => void }) {
  const numeric = type === 'integer' || type === 'float';
  const bad = (t: string) => (numeric ? Number.isNaN(Number(t)) : type === 'date' ? !isIsoDate(t) : !isIsoDatetime(t));
  return (
    <label className="flex flex-col gap-1 text-sm">
      {label}
      <input
        className={fieldClass}
        defaultValue={value === undefined ? '' : String(value)}
        placeholder={type === 'date' ? 'YYYY-MM-DD' : type === 'datetime' ? 'YYYY-MM-DDTHH:MM:SS' : undefined}
        onChange={(e) => {
          const t = e.target.value.trim();
          if (t === '') return onCommit(undefined);
          // Invalid text is still committed so the checker reports it at its path.
          onCommit(numeric && !bad(t) ? Number(t) : t);
        }}
      />
    </label>
  );
}

function IntInput({ label, value, min, onCommit }: { label: string; value: number | undefined; min: number; onCommit: (v: number | undefined) => void }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      {label}
      <input
        type="number" min={min} step={1}
        className={fieldClass}
        defaultValue={value ?? ''}
        onChange={(e) => onCommit(e.target.value === '' ? undefined : Number(e.target.value))}
      />
    </label>
  );
}

export function ValidationsEditor({
  columns,
  items,
  errors,
  onChange,
}: {
  columns: ColumnMapping[];
  items: Validation[];
  errors: ErrorDetail[];
  onChange: (v: Validation[]) => void;
}) {
  // Bumped on reorder/remove so uncontrolled inputs remount with their new item's values.
  const [gen, setGen] = useState(0);
  const reshape = (next: Validation[]) => {
    setGen((g) => g + 1);
    onChange(next);
  };
  const names = columns.map((c) => c.name);
  const typeOf = (n: string): ColumnType => columns.find((c) => c.name === n)?.type ?? 'string';
  const set = (i: number, v: Validation) => onChange(items.map((x, j) => (j === i ? v : x)));
  const strip = <T extends object>(o: T, ...keys: string[]) =>
    Object.fromEntries(Object.entries(o).filter(([k]) => !keys.includes(k))) as T;

  return (
    <section aria-label="Validations" className="space-y-2">
      <h2 className="text-lg font-semibold">Validations</h2>
      <PathErrors errors={errors} path="/validations" />
      <ol className="space-y-3">
        {items.map((v, i) => {
          const p = `/validations/${i}`;
          return (
            <li key={`${gen}-${i}-${v.rule}`} className="space-y-2 rounded border border-border p-3" aria-label={`Validation ${i + 1}: ${RULE_LABEL[v.rule]}`}>
              <div className="flex flex-wrap items-center gap-2">
                <strong>{i + 1}. {RULE_LABEL[v.rule]}</strong>
                <span className="grow" />
                <button type="button" className={btnClass} disabled={i === 0} aria-label={`Move validation ${i + 1} up`} onClick={() => reshape(moveItem(items, i, i - 1))}>↑</button>
                <button type="button" className={btnClass} disabled={i === items.length - 1} aria-label={`Move validation ${i + 1} down`} onClick={() => reshape(moveItem(items, i, i + 1))}>↓</button>
                <button type="button" className={btnClass} aria-label={`Remove validation ${i + 1}`} onClick={() => reshape(items.filter((_, j) => j !== i))}>Remove</button>
              </div>
              {v.rule === 'unique' ? (
                <ColumnChecklist label="Columns (together)" names={names} value={v.columns} onChange={(cols) => set(i, { ...v, columns: cols })} />
              ) : (
                <ColumnSelect label="Column" names={names} value={v.column} onChange={(column) => set(i, { ...v, column })} />
              )}
              {v.rule === 'range' && (
                <div className="flex flex-wrap gap-3" key={`${v.column}`}>
                  <BoundInput label="Minimum" type={typeOf(v.column)} value={v.min} onCommit={(min) => set(i, min === undefined ? strip(v, 'min') : { ...v, min })} />
                  <BoundInput label="Maximum" type={typeOf(v.column)} value={v.max} onCommit={(max) => set(i, max === undefined ? strip(v, 'max') : { ...v, max })} />
                </div>
              )}
              {v.rule === 'length' && (
                <div className="flex flex-wrap gap-3">
                  <IntInput label="Minimum length" min={0} value={v.min} onCommit={(min) => set(i, min === undefined ? strip(v, 'min') : { ...v, min })} />
                  <IntInput label="Maximum length" min={1} value={v.max} onCommit={(max) => set(i, max === undefined ? strip(v, 'max') : { ...v, max })} />
                </div>
              )}
              {v.rule === 'allowed_values' && (
                <ValueLines label="Allowed values (one per line)" type={typeOf(v.column)} values={v.values} onCommit={(values) => set(i, { ...v, values })} />
              )}
              {v.rule === 'regex' && (
                <label className="flex flex-col gap-1 text-sm">
                  Pattern (Python regular expression, full match)
                  <input className={fieldClass} value={v.pattern} maxLength={200} onChange={(e) => set(i, { ...v, pattern: e.target.value })} />
                </label>
              )}
              <PathErrors errors={errors} path={p} exact={false} />
            </li>
          );
        })}
      </ol>
      <label className="flex items-center gap-2 text-sm">
        Add validation
        <select
          className={fieldClass}
          value=""
          disabled={names.length === 0}
          onChange={(e) => {
            if (e.target.value) onChange([...items, newValidation(e.target.value as Validation['rule'], names[0] ?? '')]);
          }}
        >
          <option value="">Choose…</option>
          {VALIDATION_RULES.map((r) => (
            <option key={r} value={r}>{RULE_LABEL[r]}</option>
          ))}
        </select>
      </label>
    </section>
  );
}
