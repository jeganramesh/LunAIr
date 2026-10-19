import { useState } from 'react';
import { fetchUsage } from '../api/endpoints';
import {
  CostTrendChart,
  ProviderDistributionChart,
  TokenTrendChart,
} from '../components/UsageChart';
import { EmptyState, ErrorPanel, Loading, PageHeader } from '../components/ui';
import { usePolling } from '../hooks/usePolling';
import { formatCompact, formatNumber, formatUsd } from '../utils/format';

const RANGES = ['24h', '7d', '30d', '90d'];

export default function Usage() {
  const [range, setRange] = useState('7d');
  const [provider, setProvider] = useState('');

  const { data, error, loading } = usePolling(
    () => fetchUsage({ range, provider: provider || undefined }),
    0,
    [range, provider],
  );

  return (
    <>
      <PageHeader title="Usage" description="Token consumption and cost over time" />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex rounded border border-slate-800 overflow-hidden">
          {RANGES.map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => setRange(r)}
              className={
                range === r
                  ? 'bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-100'
                  : 'px-3 py-1.5 text-xs text-slate-400 hover:bg-slate-800/50'
              }
            >
              {r}
            </button>
          ))}
        </div>

        <select
          value={provider}
          onChange={(e) => setProvider(e.target.value)}
          className="rounded border border-slate-800 bg-slate-900 px-2 py-1.5 text-xs text-slate-300"
        >
          <option value="">All providers</option>
          {(data?.by_provider ?? []).map((p) => (
            <option key={p.provider} value={p.provider ?? ''}>
              {p.provider}
            </option>
          ))}
        </select>
      </div>

      {error && <ErrorPanel error={error} />}
      {loading && !data && <Loading />}

      {data?.error && (
        <div className="card mb-4 border-amber-900/60 text-xs text-amber-300">
          {data.error}
        </div>
      )}

      {data && data.series.length === 0 ? (
        <EmptyState message="No requests logged in this range yet" />
      ) : (
        data && (
          <>
            <div className="mb-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
              <div className="card">
                <p className="card-title">Requests</p>
                <p className="stat-value">{formatCompact(data.totals.requests)}</p>
              </div>
              <div className="card">
                <p className="card-title">Prompt tokens</p>
                <p className="stat-value">{formatCompact(data.totals.tokens_in)}</p>
              </div>
              <div className="card">
                <p className="card-title">Completion tokens</p>
                <p className="stat-value">{formatCompact(data.totals.tokens_out)}</p>
              </div>
              <div className="card">
                <p className="card-title">Total cost</p>
                <p className="stat-value">{formatUsd(data.totals.cost_usd)}</p>
              </div>
            </div>

            <div className="space-y-4">
              <TokenTrendChart series={data.series} />
              <CostTrendChart series={data.series} />
              <ProviderDistributionChart byProvider={data.by_provider} />
            </div>

            <div className="card mt-4 overflow-x-auto p-0">
              <table className="min-w-full divide-y divide-slate-800">
                <thead className="bg-slate-900/60">
                  <tr>
                    <th className="th">Provider</th>
                    <th className="th">Requests</th>
                    <th className="th">Prompt</th>
                    <th className="th">Completion</th>
                    <th className="th">Cost</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/70">
                  {data.by_provider.map((row) => (
                    <tr key={row.provider}>
                      <td className="td">{row.provider}</td>
                      <td className="td">{formatNumber(row.requests)}</td>
                      <td className="td">{formatNumber(row.tokens_in)}</td>
                      <td className="td">{formatNumber(row.tokens_out)}</td>
                      <td className="td">{formatUsd(row.cost_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )
      )}
    </>
  );
}