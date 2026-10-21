import type { ColumnProfile } from './types';

/** Cell values are rendered as text only (never HTML). null -> "∅". */
export function formatCell(v: string | number | boolean | null | undefined): string {
  if (v === null || v === undefined) return '∅';
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : String(Number(v.toPrecision(12)));
  return String(v);
}

export interface SortState { column: string; order: 'asc' | 'desc' }

/** Click cycle on a header: new column -> asc, asc -> desc, desc -> asc. Single column only. */
export function nextSort(current: SortState | null, column: string): SortState {
  if (current?.column === column) return { column, order: current.order === 'asc' ? 'desc' : 'asc' };
  return { column, order: 'asc' };
}

export function pageRange(total: number, limit: number, offset: number): { from: number; to: number; hasPrev: boolean; hasNext: boolean } {
  if (total === 0) return { from: 0, to: 0, hasPrev: false, hasNext: false };
  const to = Math.min(offset + limit, total);
  return { from: offset + 1, to, hasPrev: offset > 0, hasNext: to < total };
}

export function nullPercent(nullCount: number, rowCount: number): string {
  return rowCount === 0 ? '0%' : `${Math.round((nullCount / rowCount) * 100)}%`;
}

export interface TopValuePoint { label: string; count: number }

export function toTopValuePoints(col: Pick<ColumnProfile, 'top_values'>): TopValuePoint[] {
  return col.top_values.map((t) => ({ label: formatCell(t.value), count: t.count }));
}

/** Null vs non-null split for the nulls chart. */
export function toNullSplit(col: Pick<ColumnProfile, 'null_count'>, rowCount: number) {
  const nulls = Math.min(col.null_count, rowCount);
  return [
    { name: 'Non-null', count: rowCount - nulls },
    { name: 'Null', count: nulls },
  ];
}
