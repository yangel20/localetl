import type { MetricsSummary, Run } from '../../app/api/types';

export type DailyPoint = MetricsSummary['daily'][number];

export function formatCount(n: number): string {
  return new Intl.NumberFormat('en-US').format(n);
}

/** 850 -> "850 ms", 2000 -> "2.0 s", 125000 -> "2 min 5 s". null -> "—". */
export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '—';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)} s`;
  const total = Math.round(s);
  return `${Math.floor(total / 60)} min ${total % 60} s`;
}

/** "2026-10-19" -> "Oct 19" (UTC, so no timezone drift). */
export function formatDay(isoDate: string): string {
  const d = new Date(`${isoDate}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return isoDate;
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' });
}

/** Share of finished runs that succeeded, as "83%"; "—" when nothing finished. */
export function successRate(s: Pick<MetricsSummary, 'runs_by_status'>): string {
  const { succeeded, failed, interrupted } = s.runs_by_status;
  const finished = succeeded + failed + interrupted;
  return finished === 0 ? '—' : `${Math.round((succeeded / finished) * 100)}%`;
}

export interface RunOutcomeRow {
  date: string;
  label: string;
  succeeded: number;
  failed: number;
  interrupted: number;
}

export function toOutcomeRows(daily: readonly DailyPoint[]): RunOutcomeRow[] {
  return daily.map((d) => ({
    date: d.date,
    label: formatDay(d.date),
    succeeded: d.succeeded,
    failed: d.failed,
    interrupted: d.interrupted,
  }));
}

export interface RowsLoadedPoint {
  runId: string;
  label: string;
  pipeline: string;
  loaded: number;
  rejected: number;
}

/**
 * Loaded/rejected rows for the most recent `max` succeeded runs, oldest first
 * (the API lists newest first). Runs without a finish time sort by queued_at.
 */
export function toRowsLoadedPoints(runs: readonly Run[], max = 20): RowsLoadedPoint[] {
  const at = (r: Run) => r.finished_at ?? r.queued_at;
  return runs
    .filter((r) => r.status === 'succeeded')
    .sort((a, b) => at(b).localeCompare(at(a)))
    .slice(0, max)
    .reverse()
    .map((r) => ({
      runId: r.id,
      label: new Date(at(r)).toLocaleString('en-US', {
        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'UTC',
      }),
      pipeline: r.pipeline_name,
      loaded: r.loaded_count ?? 0,
      rejected: r.rejected_count ?? 0,
    }));
}
