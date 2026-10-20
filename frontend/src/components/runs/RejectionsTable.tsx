import type { RejectedRow } from '../../app/api/types';

/** One row per entry: a source row failing several rules appears several times. Values render as text. */
export function RejectionsTable({ items }: { items: RejectedRow[] }) {
  if (items.length === 0) return <p className="text-fg-muted">No rejected rows.</p>;
  return (
    <div className="overflow-x-auto rounded border border-border">
      <table className="min-w-full text-left text-sm">
        <thead className="bg-surface-muted">
          <tr>
            <th scope="col" className="px-3 py-2">Row</th>
            <th scope="col" className="px-3 py-2">Column</th>
            <th scope="col" className="px-3 py-2">Rule</th>
            <th scope="col" className="px-3 py-2">Message</th>
            <th scope="col" className="px-3 py-2">Value</th>
          </tr>
        </thead>
        <tbody>
          {items.map((r, i) => (
            <tr key={`${r.row_number}-${r.rule}-${r.column ?? ''}-${i}`} className="border-t border-border">
              <td className="px-3 py-1.5">{r.row_number}</td>
              <td className="px-3 py-1.5">{r.column ?? <span className="text-fg-muted">(row)</span>}</td>
              <td className="px-3 py-1.5">{r.rule}</td>
              <td className="px-3 py-1.5">{r.message}</td>
              <td className="whitespace-pre px-3 py-1.5">{r.value ?? <span className="text-fg-muted">(empty)</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
