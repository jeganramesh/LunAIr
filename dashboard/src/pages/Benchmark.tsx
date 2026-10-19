import { fetchBenchmark } from '../api/endpoints';
import { BenchmarkPanel } from '../components/BenchmarkPanel';
import { EmptyState, ErrorPanel, Loading, PageHeader } from '../components/ui';
import { usePolling } from '../hooks/usePolling';

const REFRESH_MS = 60_000;

export default function Benchmark() {
  const { data, error, loading } = usePolling(fetchBenchmark, REFRESH_MS);

  return (
    <>
      <PageHeader
        title="Benchmark"
        description="Go gateway overhead versus the direct FastAPI path"
      />

      {error && <ErrorPanel error={error} />}
      {loading && !data && <Loading />}

      {data && !data.available && (
        <EmptyState message={data.hint ?? 'No benchmark results available'} />
      )}

      {data?.available && data.results && data.results.length === 0 && (
        <EmptyState message="Benchmark file contains no runs" />
      )}

      {data?.available && data.results && data.results.length > 0 && (
        <>
          <BenchmarkPanel results={data.results} />
          {data.error && (
            <div className="card mt-4 border-amber-900/60 text-xs text-amber-300">
              {data.error}
            </div>
          )}
        </>
      )}
    </>
  );
}