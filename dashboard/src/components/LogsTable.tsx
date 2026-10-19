import type { RequestLog } from '../types/api';
import { formatLatency, formatNumber, formatTimestamp, formatUsd } from '../utils/format';

function rowTone(row: RequestLog): string {
  if (row.injection_blocked) return 'bg-red-950/40';
  if (row.pii_redacted) return 'bg-amber-950/30';
  if (row.cache_hit) return 'bg-emerald-950/30';
  return '';
}

function FallbackTag({ from }: { from: string | null }) {
  if (!from) return null;
  return (
    <span className="badge ml-1 bg-slate-700 text-slate-300" title={`fell back from ${from}`}>
      ↩ {from}
    </span>
  );
}

export function LogsTable({ rows }: { rows: RequestLog[] }) {
  return (
    <div className="card overflow-x-auto p-0">
      <table className="min-w-full divide-y divide-slate-800">
        <thead className="bg-slate-900/60">
          <tr>
            <th className="th">Time</th>
            <th className="th">Provider</th>
            <th className="th">Model</th>
            <th className="th">Tokens</th>
            <th className="th">Cost</th>
            <th className="th">Latency</th>
            <th className="th">Signals</th>
            <th className="th">Mode</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/70">
          {rows.map((row) => (
            <tr key={row.id} className={rowTone(row)}>
              <td className="td whitespace-nowrap text-slate-400">
                {formatTimestamp(row.created_at)}
              </td>
              <td className="td">{row.provider}</td>
              <td className="td">
                {row.model}
                <FallbackTag from={row.fallback_from} />
              </td>
              <td className="td whitespace-nowrap text-slate-400">
                {formatNumber(row.tokens_in)} → {formatNumber(row.tokens_out)}
              </td>
              <td className="td">{formatUsd(row.cost)}</td>
              <td className="td">{formatLatency(row.latency_ms)}</td>
              <td className="td">
                <span className="flex flex-wrap gap-1">
                  {row.injection_blocked && (
                    <span className="badge bg-red-900 text-red-200">injection</span>
                  )}
                  {row.pii_redacted && <span className="badge bg-amber-900 text-amber-200">pii</span>}
                  {row.cache_hit && (
                    <span
                      className="badge bg-emerald-900 text-emerald-200"
                      title={
                        row.cache_similarity !== null
                          ? `similarity ${row.cache_similarity.toFixed(3)}`
                          : undefined
                      }
                    >
                      cache hit
                    </span>
                  )}
                  {!row.injection_blocked &&
                    !row.pii_redacted &&
                    !row.cache_hit && (
                      <span className="text-slate-600">—</span>
                    )}
                </span>
              </td>
              <td className="td text-slate-400">{row.gateway_mode}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}