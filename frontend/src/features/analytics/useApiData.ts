import { useEffect, useState } from 'react';
import { ApiError } from '../../app/api/errors';

export type AsyncState<T> =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; data: T };

/** Runs `load` (with an AbortSignal) whenever `deps` change; stale results are discarded. */
export function useApiData<T>(load: (signal: AbortSignal) => Promise<T>, deps: readonly unknown[]): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({ status: 'loading' });
  useEffect(() => {
    const ctl = new AbortController();
    setState({ status: 'loading' });
    load(ctl.signal).then(
      (data) => { if (!ctl.signal.aborted) setState({ status: 'ready', data }); },
      (e: unknown) => {
        if (ctl.signal.aborted) return;
        setState({ status: 'error', message: e instanceof ApiError || e instanceof Error ? e.message : 'Request failed' });
      },
    );
    return () => ctl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return state;
}
