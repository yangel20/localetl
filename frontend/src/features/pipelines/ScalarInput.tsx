import { useState } from 'react';
import type { ColumnType } from '../../app/api/types';
import { parseScalarInput, type ScalarValue } from './casting';
import { fieldClass } from './ui';

/**
 * Text box that stores the config's JSON scalar in the right type for the column
 * (number for integer/float, boolean, ISO string for dates, string as typed).
 * Invalid text is not committed; the message shows locally.
 */
export function ScalarInput({
  label,
  type,
  value,
  onCommit,
}: {
  label: string;
  type: ColumnType;
  value: ScalarValue | undefined;
  onCommit: (v: ScalarValue) => void;
}) {
  const [text, setText] = useState(value === undefined ? '' : String(value));
  const [problem, setProblem] = useState<string | null>(null);
  // Resync when the value changes from outside (e.g. the item was reordered), not while typing.
  const [seen, setSeen] = useState(value);
  if (seen !== value) {
    setSeen(value);
    if (!(parseScalarInput(text, type).ok && (parseScalarInput(text, type) as { value: ScalarValue }).value === value)) {
      setText(value === undefined ? '' : String(value));
      setProblem(null);
    }
  }
  return (
    <label className="flex flex-col gap-1 text-sm">
      {label}
      <input
        className={fieldClass}
        value={text}
        aria-invalid={problem !== null}
        placeholder={type === 'date' ? 'YYYY-MM-DD' : type === 'datetime' ? 'YYYY-MM-DDTHH:MM:SS' : undefined}
        onChange={(e) => {
          setText(e.target.value);
          const r = parseScalarInput(e.target.value, type);
          if (r.ok) {
            setProblem(null);
            onCommit(r.value);
          } else setProblem(r.message);
        }}
      />
      {problem && <span className="text-xs text-danger">{problem}</span>}
    </label>
  );
}
