import { useCallback, useEffect, useState } from 'react';
import { ApiError } from '../app/api/errors';

export type AsyncState<T> =
  | { status: 'loading' }
  | { status: 'error'; error: ApiError }
  | { status: 'success'; data: T };

/** Runs `load` on mount and whenever `deps` change; aborts the previous request. */
export function useAsync<T>(
  load: (signal: AbortSignal) => Promise<T>,
  deps: readonly unknown[],
): AsyncState<T> & { reload: () => void } {
  const [state, setState] = useState<AsyncState<T>>({ status: 'loading' });
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: 'loading' });
    load(controller.signal).then(
      (data) => !controller.signal.aborted && setState({ status: 'success', data }),
      (e: unknown) => {
        if (controller.signal.aborted) return;
        setState({
          status: 'error',
          error:
            e instanceof ApiError ? e : new ApiError(0, 'network_error', 'Unexpected error'),
        });
      },
    );
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  return { ...state, reload };
}
