import { fetchCacheStats } from '../api/endpoints';
import { CacheStatsPanel } from '../components/CacheStats';
import { ErrorPanel, Loading, PageHeader } from '../components/ui';
import { usePolling } from '../hooks/usePolling';

const REFRESH_MS = 60_000;

export default function Cache() {
  const { data, error, loading, refetch } = usePolling(fetchCacheStats, REFRESH_MS);

  return (
    <>
      <PageHeader
        title="Cache"
        description="Semantic cache hit rate and spend avoided"
        action={
          <span className="text-xs text-slate-500">
            Auto-refreshes every {REFRESH_MS / 1000}s
          </span>
        }
      />

      {error && <ErrorPanel error={error} onRetry={refetch} />}
      {loading && !data && <Loading />}
      {data && <CacheStatsPanel stats={data} />}
    </>
  );
}