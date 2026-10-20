import type { CsvPreview } from '../../app/api/types';

/** Cells are rendered as React text nodes only; CSV content is never interpreted as HTML. */
export function PreviewTable({ preview }: { preview: CsvPreview }) {
  if (preview.rows.length === 0) {
    return <p className="text-fg-muted">This source has no data rows.</p>;
  }
  return (
    <div className="overflow-x-auto rounded border border-border">
      <table className="min-w-full text-left text-sm">
        <thead className="bg-surface-muted">
          <tr>
            {preview.columns.map((c) => (
              <th key={c.name} scope="col" className="px-3 py-2 font-medium">
                {c.name}
                <span className="block text-xs font-normal text-fg-muted">{c.inferred_type}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {preview.rows.map((row, i) => (
            <tr key={i} className="border-t border-border">
              {preview.columns.map((c) => {
                const v = row[c.name];
                return (
                  <td key={c.name} className="whitespace-pre px-3 py-1.5">
                    {v === null || v === undefined ? <span className="text-fg-muted">(empty)</span> : v}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
