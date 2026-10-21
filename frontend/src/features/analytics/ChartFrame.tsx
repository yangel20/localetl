import type { ReactNode } from 'react';
import type { AsyncState } from './useApiData';

/** Titled card handling loading / error / empty for every chart. */
export function ChartFrame<T>({
  title, state, isEmpty, emptyText, children,
}: {
  title: string;
  state: AsyncState<T>;
  isEmpty: (data: T) => boolean;
  emptyText: string;
  children: (data: T) => ReactNode;
}) {
  return (
    <section aria-label={title} className="rounded border border-border bg-surface p-3">
      <h3 className="mb-2 text-sm font-semibold">{title}</h3>
      {state.status === 'loading' && <p role="status" className="text-sm text-fg-muted">Loading…</p>}
      {state.status === 'error' && <p role="alert" className="text-sm text-danger">{state.message}</p>}
      {state.status === 'ready' && (isEmpty(state.data) ? <p className="text-sm text-fg-muted">{emptyText}</p> : children(state.data))}
    </section>
  );
}

/** Fixed size (tests) or responsive (app). */
export const CHART_HEIGHT = 240;
export const color = (name: 'success' | 'danger' | 'warning' | 'primary' | 'fg-muted' | 'border') =>
  `rgb(var(--color-${name}))`;
