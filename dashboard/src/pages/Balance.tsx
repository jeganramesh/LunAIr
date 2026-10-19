import { fetchBalance } from '../api/endpoints';
import { BalanceCard } from '../components/BalanceCard';
import { EmptyState, ErrorPanel, Loading, PageHeader } from '../components/ui';
import { usePolling } from '../hooks/usePolling';
import { formatTimestamp, formatUsd } from '../utils/format';

const REFRESH_MS = 60_000;

export default function Balance() {
  const { data, error, loading, refetch } = usePolling(() => fetchBalance(), REFRESH_MS);

  return (
    <>
      <PageHeader
        title="Balance"
        description="Remaining credit across every configured provider, normalized to USD"
        action={
          <span className="text-xs text-slate-500">
            Auto-refreshes every {REFRESH_MS / 1000}s
          </span>
        }
      />

      {error && <ErrorPanel error={error} onRetry={refetch} />}
      {loading && !data && <Loading label="Fetching balances" />}

      {data && data.providers.length === 0 && (
        <EmptyState message="No balance providers configured in config/config.yaml" />
      )}

      {data && data.providers.length > 0 && (
        <>
          <div className="card mb-4 flex items-center justify-between">
            <div>
              <p className="card-title">Total remaining</p>
              <p className="stat-value text-3xl">{formatUsd(data.total_remaining_usd)}</p>
            </div>
            <div className="text-right text-xs text-slate-500">
              <p>
                {data.providers_available}/{data.providers_total} reachable
              </p>
              <p className="mt-1">{formatTimestamp(data.last_refreshed)}</p>
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {data.providers.map((provider) => (
              <BalanceCard key={provider.provider} balance={provider} />
            ))}
          </div>
        </>
      )}
    </>
  );
}