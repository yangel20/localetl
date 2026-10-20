import { useEffect, useState } from 'react';
import { api } from '../../app/api/client';
import { ApiError } from '../../app/api/errors';
import type { Run, RunEvent } from '../../app/api/types';
import { isTerminal, POLL_INTERVAL_MS } from './runStatus';

export interface PolledRun {
  run: Run | null;
  events: RunEvent[];
  /** Last request error; cleared by the next successful poll. */
  error: ApiError | null;
  loading: boolean;
  /** True while polling is scheduled (run not yet terminal). */
  polling: boolean;
}

/**
 * Polls GET /runs/{id} and /events every `intervalMs` (architecture §9) until the run reaches
 * succeeded, failed or interrupted. A 404 also stops polling; other errors keep retrying.
 */
export function usePolledRun(runId: string, intervalMs: number = POLL_INTERVAL_MS): PolledRun {
  const [state, setState] = useState<PolledRun>({
    run: null,
    events: [],
    error: null,
    loading: true,
    polling: true,
  });

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    setState({ run: null, events: [], error: null, loading: true, polling: true });

    async function poll() {
      try {
        const [run, events] = await Promise.all([
          api.getRun(runId, controller.signal),
          api.listRunEvents(runId, controller.signal),
        ]);
        if (controller.signal.aborted) return;
        const done = isTerminal(run.status);
        setState({ run, events, error: null, loading: false, polling: !done });
        if (!done) timer = setTimeout(poll, intervalMs);
      } catch (e) {
        if (controller.signal.aborted) return;
        const error = e instanceof ApiError ? e : new ApiError(0, 'network_error', 'Unexpected error');
        const fatal = error.code === 'not_found';
        setState((s) => ({ ...s, error, loading: false, polling: !fatal }));
        if (!fatal) timer = setTimeout(poll, intervalMs);
      }
    }
    void poll();

    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [runId, intervalMs]);

  return state;
}
