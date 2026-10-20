import type { ErrorDetail } from '../../app/api/types';

export const fieldClass = 'rounded border border-border bg-surface px-2 py-1 text-sm';
export const btnClass = 'rounded border border-border px-2 py-1 text-sm disabled:opacity-50';

/** Errors whose path is `prefix` or below it. `exact` limits to the path itself. */
export function errorsAt(errors: readonly ErrorDetail[], prefix: string, exact = false): ErrorDetail[] {
  return errors.filter((e) => e.path === prefix || (!exact && e.path.startsWith(`${prefix}/`)));
}

/** Messages shown right under the control they belong to, each tagged with its JSON Pointer. */
export function PathErrors({ errors, path, exact = true }: { errors: readonly ErrorDetail[]; path: string; exact?: boolean }) {
  const here = errorsAt(errors, path, exact);
  if (here.length === 0) return null;
  return (
    <ul role="alert" className="text-xs text-danger" data-path={path}>
      {here.map((e, i) => (
        <li key={i}>
          {e.message} <code className="text-fg-muted">{e.path}</code>
        </li>
      ))}
    </ul>
  );
}

export function ColumnSelect({
  label,
  value,
  names,
  onChange,
}: {
  label: string;
  value: string;
  names: readonly string[];
  onChange: (v: string) => void;
}) {
  const options = names.includes(value) || value === '' ? names : [value, ...names];
  return (
    <label className="flex flex-col gap-1 text-sm">
      {label}
      <select className={fieldClass} value={value} onChange={(e) => onChange(e.target.value)}>
        {value === '' && <option value="">Choose…</option>}
        {options.map((n) => (
          <option key={n} value={n}>
            {n}
          </option>
        ))}
      </select>
    </label>
  );
}

export function ColumnChecklist({
  label,
  value,
  names,
  onChange,
}: {
  label: string;
  value: readonly string[];
  names: readonly string[];
  onChange: (v: string[]) => void;
}) {
  return (
    <fieldset className="text-sm">
      <legend>{label}</legend>
      <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
        {names.map((n) => (
          <label key={n} className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={value.includes(n)}
              onChange={(e) => onChange(e.target.checked ? [...value, n] : value.filter((x) => x !== n))}
            />
            {n}
          </label>
        ))}
      </div>
    </fieldset>
  );
}
