interface Props {
  total: number;
  limit: number;
  offset: number;
  onChange: (offset: number) => void;
}

export function Pager({ total, limit, offset, onChange }: Props) {
  if (total <= limit) return null;
  const from = offset + 1;
  const to = Math.min(offset + limit, total);
  return (
    <nav aria-label="Pagination" className="mt-3 flex items-center gap-3 text-sm">
      <button
        type="button"
        className="rounded border border-border px-3 py-1 disabled:opacity-50"
        disabled={offset <= 0}
        onClick={() => onChange(Math.max(0, offset - limit))}
      >
        Previous
      </button>
      <span>
        {from}–{to} of {total}
      </span>
      <button
        type="button"
        className="rounded border border-border px-3 py-1 disabled:opacity-50"
        disabled={offset + limit >= total}
        onClick={() => onChange(offset + limit)}
      >
        Next
      </button>
    </nav>
  );
}
