import type { Run } from '../../app/api/types';

type Counters = Pick<
  Run,
  | 'extracted_count'
  | 'loaded_count'
  | 'rejected_count'
  | 'duplicate_dropped_count'
  | 'null_dropped_count'
>;

/**
 * The five Q3 counters. Rows removed by deduplicate / drop_null_rows are shown apart from
 * rejections: they are not validation failures.
 */
export function RunCounters({ run, live }: { run: Counters; live: boolean }) {
  return (
    <section aria-label="Row counters" className="space-y-2">
      <h2 className="text-lg font-semibold">
        Rows {live && <span className="text-sm font-normal text-fg-muted">(live)</span>}
      </h2>
      <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
        <Item label="Extracted" value={run.extracted_count} />
        <Item label="Loaded" value={run.loaded_count} />
        <Item label="Rejected" value={run.rejected_count} hint="failed parsing, casting or validation" />
        <Item label="Duplicates dropped" value={run.duplicate_dropped_count} hint="deduplicate, not a rejection" />
        <Item label="Null rows dropped" value={run.null_dropped_count} hint="drop null rows, not a rejection" />
      </dl>
    </section>
  );
}

function Item({ label, value, hint }: { label: string; value: number; hint?: string }) {
  return (
    <div className="rounded border border-border bg-surface-muted p-3">
      <dt className="text-fg-muted">{label}</dt>
      <dd className="text-xl font-semibold">{value.toLocaleString()}</dd>
      {hint && <p className="text-xs text-fg-muted">{hint}</p>}
    </div>
  );
}
