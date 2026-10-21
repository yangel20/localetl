import { useLayoutEffect, useRef } from 'react';
import type { DatasetRowPage } from '../../app/api/types';
import { formatCell, nextSort, pageRange, type SortState } from './format';

const btn = 'rounded border border-border px-2 py-1 text-sm disabled:opacity-50';

export function RowsTable({
  page, sort, onSort, onOffset,
}: {
  page: DatasetRowPage;
  sort: SortState | null;
  onSort: (s: SortState) => void;
  onOffset: (offset: number) => void;
}) {
  const r = pageRange(page.total, page.limit, page.offset);
  const prevRef = useRef<HTMLButtonElement>(null);
  const nextRef = useRef<HTMLButtonElement>(null);
  const statusRef = useRef<HTMLSpanElement>(null);
  // Which pager button the user activated; resolved once the new page has rendered.
  const pending = useRef<'prev' | 'next' | null>(null);

  useLayoutEffect(() => {
    const was = pending.current;
    if (!was) return;
    const active = document.activeElement;
    const own = was === 'prev' ? prevRef.current : nextRef.current;
    // Only act if focus is still on the activated button or was dropped to <body>;
    // never steal focus the user moved elsewhere.
    if (active && active !== document.body && active !== own) { pending.current = null; return; }
    const other = was === 'prev' ? nextRef.current : prevRef.current;
    const target = own && !own.disabled ? own : other && !other.disabled ? other : statusRef.current;
    target?.focus();
    pending.current = null;
  }, [page.offset, page.total, page.limit]);
  return (
    <div className="flex flex-col gap-2">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr>
              {page.columns.map((c) => {
                const active = sort?.column === c.name;
                return (
                  <th key={c.name} scope="col" className="border-b border-border p-1 text-left"
                    aria-sort={active ? (sort.order === 'asc' ? 'ascending' : 'descending') : 'none'}>
                    <button type="button" onClick={() => { pending.current = null; onSort(nextSort(sort, c.name)); }}>
                      {c.name}{active ? (sort.order === 'asc' ? ' ▲' : ' ▼') : ''}
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {page.items.map((row, i) => (
              <tr key={page.offset + i} className="odd:bg-surface-muted">
                {page.columns.map((c) => {
                  const v = row[c.name];
                  return <td key={c.name} className={`p-1 ${v === null ? 'text-fg-muted' : ''}`}>{formatCell(v)}</td>;
                })}
              </tr>
            ))}
            {page.items.length === 0 && (
              <tr><td colSpan={Math.max(page.columns.length, 1)} className="p-2 text-fg-muted">No rows.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <nav aria-label="Pagination" className="flex items-center gap-2 text-sm">
        <button ref={prevRef} type="button" className={btn} disabled={!r.hasPrev}
          onClick={() => { pending.current = 'prev'; onOffset(Math.max(0, page.offset - page.limit)); }}>Previous</button>
        <span ref={statusRef} tabIndex={-1} role="status" aria-live="polite" data-testid="pager-status">
          {r.from}–{r.to} of {page.total}
        </span>
        <button ref={nextRef} type="button" className={btn} disabled={!r.hasNext}
          onClick={() => { pending.current = 'next'; onOffset(page.offset + page.limit); }}>Next</button>
      </nav>
    </div>
  );
}
