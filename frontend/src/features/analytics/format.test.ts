import { describe, expect, it } from 'vitest';
import { runSucceeded } from '../../app/api/fixtures';
import { formatCount, formatDay, formatDuration, successRate, toOutcomeRows, toRowsLoadedPoints } from './format';

describe('formatting', () => {
  it('formats counts', () => expect(formatCount(1234567)).toBe('1,234,567'));
  it('formats durations', () => {
    expect(formatDuration(null)).toBe('—');
    expect(formatDuration(850)).toBe('850 ms');
    expect(formatDuration(2000)).toBe('2.0 s');
    expect(formatDuration(125000)).toBe('2 min 5 s');
  });
  it('formats UTC days', () => {
    expect(formatDay('2026-10-19')).toBe('Oct 19');
    expect(formatDay('bad')).toBe('bad');
  });
  it('computes success rate over finished runs', () => {
    const rs = (succeeded: number, failed: number, interrupted: number) => ({
      runs_by_status: { queued: 3, running: 1, succeeded, failed, interrupted },
    });
    expect(successRate(rs(0, 0, 0))).toBe('—');
    expect(successRate(rs(5, 1, 0))).toBe('83%');
  });
  it('maps daily points to outcome rows', () => {
    expect(toOutcomeRows([{ date: '2026-10-19', succeeded: 1, failed: 2, interrupted: 0, loaded_count: 9 }])).toEqual([
      { date: '2026-10-19', label: 'Oct 19', succeeded: 1, failed: 2, interrupted: 0 },
    ]);
  });
  it('rows-loaded points: succeeded only, oldest first, capped, null counts as 0', () => {
    const mk = (id: string, finished: string, over: object = {}) => ({
      ...runSucceeded, id, finished_at: finished, ...over,
    });
    const pts = toRowsLoadedPoints(
      [
        mk('c', '2026-10-21T10:00:00Z'),
        mk('x', '2026-10-21T11:00:00Z', { status: 'failed' }),
        mk('a', '2026-10-19T10:00:00Z', { loaded_count: null, rejected_count: null }),
        mk('b', '2026-10-20T10:00:00Z'),
      ],
      2,
    );
    expect(pts.map((p) => p.runId)).toEqual(['b', 'c']);
    expect(toRowsLoadedPoints([mk('a', '2026-10-19T10:00:00Z', { loaded_count: null })])[0]?.loaded).toBe(0);
    expect(pts[0]?.label).toBe('Oct 20, 10:00 AM');
  });
});
