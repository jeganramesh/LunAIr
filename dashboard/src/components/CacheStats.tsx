import type { CacheStats } from '../types/api';
import { formatNumber, formatPercent, formatUsd } from '../utils/format';

export function CacheStatsPanel({ stats }: { stats: CacheStats }) {
  const saved = stats.saved_cost_usd ?? 0;
  const spend = stats.total_cost_usd ?? 0;

  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <div className="card">
        <p className="card-title">Hit rate</p>
        <p className="stat-value">{formatPercent(stats.hit_rate)}</p>
        <p className="mt-1 text-xs text-slate-500">
          {formatNumber(stats.hits)} hits / {formatNumber(stats.total_requests)} requests
        </p>
      </div>

      <div className="card">
        <p className="card-title">Misses</p>
        <p className="stat-value">{formatNumber(stats.misses)}</p>
        <p className="mt-1 text-xs text-slate-500">provider calls made</p>
      </div>

      <div className="card">
        <p className="card-title">Spend avoided</p>
        <p className="stat-value text-emerald-400">{formatUsd(saved)}</p>
        <p className="mt-1 text-xs text-slate-500">of {formatUsd(spend)} total</p>
      </div>

      <div className="card">
        <p className="card-title">Avg similarity</p>
        <p className="stat-value">{stats.avg_similarity.toFixed(3)}</p>
        <p className="mt-1 text-xs text-slate-500">threshold 0.90</p>
      </div>

      <div className="card col-span-2 lg:col-span-4">
        <p className="card-title">Savings share</p>
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-800">
          <div
            className="h-full bg-emerald-500"
            style={{ width: `${spend > 0 ? Math.min(100, (saved / spend) * 100) : 0}%` }}
          />
        </div>
        <p className="mt-2 text-xs text-slate-500">
          Window: last {stats.window_days} days. Semantic caching arrives in Phase 2 — these
          figures stay at zero until then.
        </p>
      </div>
    </div>
  );
}