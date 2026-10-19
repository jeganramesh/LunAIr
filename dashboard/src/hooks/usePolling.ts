import { useCallback, useEffect, useRef, useState } from 'react';

interface AsyncState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
}

/**
 * Runs an async fetcher on mount and on an interval, cancelling in-flight
 * work on unmount so a slow response cannot overwrite fresher state.
 */
export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs: number,
  deps: unknown[] = [],
): AsyncState<T> & { refetch: () => void } {
  const [state, setState] = useState<AsyncState<T>>({
    data: null,
    error: null,
    loading: true,
  });

  const [nonce, setNonce] = useState(0);
  const active = useRef(true);

  const refetch = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    active.current = true;

    const run = async () => {
      try {
        const data = await fetcher();
        if (active.current) setState({ data, error: null, loading: false });
      } catch (err) {
        if (active.current) {
          setState((prev) => ({
            data: prev.data,
            error: err instanceof Error ? err.message : String(err),
            loading: false,
          }));
        }
      }
    };

    void run();

    if (intervalMs > 0) {
      const timer = window.setInterval(() => void run(), intervalMs);
      return () => {
        active.current = false;
        window.clearInterval(timer);
      };
    }

    return () => {
      active.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, nonce, ...deps]);

  return { ...state, refetch };
}