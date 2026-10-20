import type { RunStatus } from '../../app/api/types';

export const POLL_INTERVAL_MS = 2000;

export function isTerminal(status: RunStatus): boolean {
  return status === 'succeeded' || status === 'failed' || status === 'interrupted';
}

export const STATUS_LABEL: Record<RunStatus, string> = {
  queued: 'Queued',
  running: 'Running',
  succeeded: 'Succeeded',
  failed: 'Failed',
  interrupted: 'Interrupted',
};

export const STATUS_CLASS: Record<RunStatus, string> = {
  queued: 'text-fg-muted',
  running: 'text-primary',
  succeeded: 'text-success',
  failed: 'text-danger',
  interrupted: 'text-warning',
};

export function formatDuration(ms: number | null): string {
  if (ms === null) return '—';
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}
