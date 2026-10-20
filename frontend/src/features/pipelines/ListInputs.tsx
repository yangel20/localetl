import { useState } from 'react';
import type { ColumnType } from '../../app/api/types';
import { parseScalarInput, type ScalarValue } from './casting';
import { fieldClass } from './ui';

/** One value per line, parsed per column type. Commits only when every non-empty line parses. */
export function ValueLines({
  label,
  type,
  values,
  onCommit,
}: {
  label: string;
  type: ColumnType;
  values: readonly ScalarValue[];
  onCommit: (v: ScalarValue[]) => void;
}) {
  const serialize = (v: readonly ScalarValue[]) => v.map(String).join('\n');
  const [text, setText] = useState(serialize(values));
  const [problem, setProblem] = useState<string | null>(null);
  const [seen, setSeen] = useState(JSON.stringify(values));
  const now = JSON.stringify(values);
  if (seen !== now) {
    setSeen(now);
    setText(serialize(values));
    setProblem(null);
  }
  function change(next: string) {
    setText(next);
    const out: ScalarValue[] = [];
    for (const [i, line] of next.split('\n').entries()) {
      if (line === '' ) continue;
      const r = parseScalarInput(line, type);
      if (!r.ok) return setProblem(`Line ${i + 1}: ${r.message}`);
      out.push(r.value);
    }
    setProblem(null);
    setSeen(JSON.stringify(out));
    onCommit(out);
  }
  return (
    <label className="flex flex-col gap-1 text-sm">
      {label}
      <textarea className={fieldClass} rows={4} value={text} onChange={(e) => change(e.target.value)} />
      {problem && <span className="text-xs text-danger">{problem}</span>}
    </label>
  );
}

type Mapping = Record<string, ScalarValue | null>;

/** Editable current-value to replacement pairs. Commits when keys are non-empty, unique and values parse. */
export function MappingEditor({
  type,
  mapping,
  onCommit,
}: {
  type: ColumnType;
  mapping: Mapping;
  onCommit: (m: Mapping) => void;
}) {
  type Row = { from: string; to: string; toNull: boolean };
  const toRows = (m: Mapping): Row[] =>
    Object.entries(m).map(([from, v]) => ({ from, to: v === null ? '' : String(v), toNull: v === null }));
  const [rows, setRows] = useState<Row[]>(toRows(mapping));
  const [problem, setProblem] = useState<string | null>(null);
  const [seen, setSeen] = useState(JSON.stringify(mapping));
  if (seen !== JSON.stringify(mapping)) {
    setSeen(JSON.stringify(mapping));
    setRows(toRows(mapping));
    setProblem(null);
  }

  function commit(next: Row[]) {
    setRows(next);
    const out: Mapping = {};
    for (const [i, r] of next.entries()) {
      if (r.from === '') return setProblem(`Replacement ${i + 1}: enter the current value.`);
      if (r.from in out) return setProblem(`Replacement ${i + 1}: "${r.from}" is already listed.`);
      if (r.toNull) out[r.from] = null;
      else {
        const p = parseScalarInput(r.to, type);
        if (!p.ok) return setProblem(`Replacement ${i + 1}: ${p.message}`);
        out[r.from] = p.value;
      }
    }
    setProblem(null);
    setSeen(JSON.stringify(out));
    onCommit(out);
  }

  return (
    <fieldset className="space-y-1 text-sm">
      <legend>Replacements</legend>
      {rows.map((r, i) => (
        <div key={i} className="flex flex-wrap items-center gap-2">
          <input
            aria-label={`Current value ${i + 1}`}
            className={fieldClass}
            value={r.from}
            onChange={(e) => commit(rows.map((x, j) => (j === i ? { ...x, from: e.target.value } : x)))}
          />
          <span aria-hidden>→</span>
          <input
            aria-label={`Replacement ${i + 1}`}
            className={fieldClass}
            value={r.to}
            disabled={r.toNull}
            onChange={(e) => commit(rows.map((x, j) => (j === i ? { ...x, to: e.target.value } : x)))}
          />
          <label className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={r.toNull}
              onChange={(e) => commit(rows.map((x, j) => (j === i ? { ...x, toNull: e.target.checked } : x)))}
            />
            empty
          </label>
          <button type="button" className="rounded border border-border px-2 py-1" onClick={() => commit(rows.filter((_, j) => j !== i))}>
            Remove
          </button>
        </div>
      ))}
      <button type="button" className="rounded border border-border px-2 py-1" onClick={() => setRows([...rows, { from: '', to: '', toNull: false }])}>
        Add replacement
      </button>
      {problem && <p className="text-xs text-danger">{problem}</p>}
    </fieldset>
  );
}
