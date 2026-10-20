import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { IDS, runRunning, runSucceeded } from '../../app/api/fixtures';
import { createMockFetch, errorResponse } from '../../app/api/mockFetch';
import { usePolledRun } from './usePolledRun';

const json = (b: unknown) => new Response(JSON.stringify(b), { headers: { 'Content-Type': 'application/json' } });

function setup(runs: (n: number) => Response) {
  let runCalls = 0;
  const fetchMock = vi.fn(
    createMockFetch({
      'GET /runs/[^/]+': () => runs(++runCalls),
    }),
  );
  vi.stubGlobal('fetch', fetchMock);
  const count = (suffix: string) =>
    fetchMock.mock.calls.filter(([u]) => new URL(String(u)).pathname.endsWith(suffix)).length;
  return { fetchMock, count, runCalls: () => runCalls };
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const tick = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

describe('usePolledRun', () => {
  it('polls every 2 s while running and stops once the run succeeds', async () => {
    const s = setup((n) => json(n < 3 ? runRunning : { ...runSucceeded, id: runRunning.id }));
    const { result } = renderHook(() => usePolledRun(IDS.runRunning));
    await tick(0);
    expect(s.runCalls()).toBe(1);
    expect(result.current.run?.status).toBe('running');
    expect(result.current.polling).toBe(true);

    await tick(1999);
    expect(s.runCalls()).toBe(1); // not before 2 s
    await tick(1);
    expect(s.runCalls()).toBe(2);
    await tick(2000);
    expect(s.runCalls()).toBe(3);
    expect(result.current.run?.status).toBe('succeeded');
    expect(result.current.polling).toBe(false);
    expect(s.count('/events')).toBe(3); // events are polled with the run

    await tick(20000); // terminal: no further requests
    expect(s.runCalls()).toBe(3);
    expect(s.count('/events')).toBe(3);
  });

  it.each(['failed', 'interrupted'] as const)('stops at %s', async (status) => {
    const s = setup(() => json({ ...runRunning, status, finished_at: '2026-10-19T10:10:02Z' }));
    const { result } = renderHook(() => usePolledRun(IDS.runRunning));
    await tick(0);
    await tick(10000);
    expect(s.runCalls()).toBe(1);
    expect(result.current.polling).toBe(false);
  });

  it('keeps polling after a transient error and clears it on success', async () => {
    const s = setup((n) => (n === 2 ? errorResponse(500, 'internal_error', 'boom') : json(runRunning)));
    const { result } = renderHook(() => usePolledRun(IDS.runRunning));
    await tick(0);
    await tick(2000);
    expect(result.current.error?.message).toBe('boom');
    expect(result.current.run?.status).toBe('running'); // last good data kept
    await tick(2000);
    expect(s.runCalls()).toBe(3);
    expect(result.current.error).toBeNull();
  });

  it('stops on 404', async () => {
    const s = setup(() => errorResponse(404, 'not_found', 'Run not found'));
    const { result } = renderHook(() => usePolledRun(IDS.runRunning));
    await tick(0);
    await tick(10000);
    expect(s.runCalls()).toBe(1);
    expect(result.current.error?.code).toBe('not_found');
    expect(result.current.polling).toBe(false);
  });

  it('stops polling on unmount', async () => {
    const s = setup(() => json(runRunning));
    const { unmount } = renderHook(() => usePolledRun(IDS.runRunning));
    await tick(0);
    unmount();
    await tick(10000);
    expect(s.runCalls()).toBe(1);
  });
});
