import { useCallback, useEffect, useRef, useState, type DependencyList } from "react";

export interface AsyncState<T> {
  data: T | undefined;
  error: unknown;
  loading: boolean;
  reload: () => Promise<void>;
  setData: (update: T | ((previous: T | undefined) => T)) => void;
}

/** Load once per dependency change; a stale response never overwrites a newer one. */
export function useAsync<T>(load: () => Promise<T>, deps: DependencyList): AsyncState<T> {
  const [data, setDataState] = useState<T | undefined>(undefined);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const generation = useRef(0);
  const loader = useRef(load);
  loader.current = load;

  const run = useCallback(async () => {
    const mine = ++generation.current;
    setLoading(true);
    try {
      const value = await loader.current();
      if (mine === generation.current) {
        setDataState(value);
        setError(null);
      }
    } catch (caught) {
      if (mine === generation.current) setError(caught);
    } finally {
      if (mine === generation.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  const setData = useCallback((update: T | ((previous: T | undefined) => T)) => {
    setDataState((previous) => (typeof update === "function" ? (update as (p: T | undefined) => T)(previous) : update));
  }, []);

  return { data, error, loading, reload: run, setData };
}
