import type { ProviderBalance } from '../types/api';
import { formatTimestamp, formatUsd } from '../utils/format';

export function BalanceCard({
  balance,
  budgetUsd,
}: {
  balance: ProviderBalance;
  budgetUsd?: number | null;
}) {
  const { provider, balance_usd, lifetime_spend_usd, available, note, last_refreshed } = balance;

  const pctUsed =
    budgetUsd && budgetUsd > 0 && lifetime_spend_usd !== null
      ? Math.min(100, (lifetime_spend_usd / budgetUsd) * 100)
      : null;

  return (
    <div className="card">
      <div className="flex items-start justify-between">
        <div>
          <p className="card-title">{provider}</p>
          <p className="stat-value">{available ? formatUsd(balance_usd) : '—'}</p>
        </div>
        <span
          className={
            available
              ? 'badge bg-emerald-950 text-emerald-300'
              : 'badge bg-slate-800 text-slate-400'
          }
        >
          {available ? 'active' : 'unavailable'}
        </span>
      </div>

      {lifetime_spend_usd !== null && (
        <p className="mt-1 text-xs text-slate-500">
          Lifetime spend {formatUsd(lifetime_spend_usd)}
        </p>
      )}

      {pctUsed !== null && (
        <div className="mt-3">
          <div className="mb-1 flex justify-between text-xs text-slate-500">
            <span>Budget used</span>
            <span className="tabular-nums">{pctUsed.toFixed(0)}%</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-slate-800">
            <div
              className={
                pctUsed > 90
                  ? 'h-full bg-red-500'
                  : pctUsed > 70
                    ? 'h-full bg-amber-500'
                    : 'h-full bg-emerald-500'
              }
              style={{ width: `${pctUsed}%` }}
            />
          </div>
        </div>
      )}

      {note && <p className="mt-3 text-xs italic text-slate-500">{note}</p>}

      <p className="mt-3 text-xs text-slate-600">
        Refreshed {formatTimestamp(last_refreshed)}
      </p>
    </div>
  );
}