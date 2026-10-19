import { useState } from 'react';
import { fetchLogs } from '../api/endpoints';
import { LogsTable } from '../components/LogsTable';
import { EmptyState, ErrorPanel, Loading, PageHeader } from '../components/ui';
import { usePolling } from '../hooks/usePolling';
import { formatNumber } from '../utils/format';

const PAGE_SIZE = 50;
const REFRESH_MS = 30_000;

export default function Logs() {
  const [page, setPage] = useState(0);
  const offset = page * PAGE_SIZE;

  const { data, error, loading } = usePolling(
    () => fetchLogs(PAGE_SIZE, offset),
    REFRESH_MS,
    [offset],
  );

  const total = data?.total ?? 0;
  const lastPage = Math.max(0, Math.ceil(total / PAGE_SIZE) - 1);

  return (
    <>
      <PageHeader
        title="Logs"
        description="Every request served, with security and cache signals"
        action={
          <span className="text-xs text-slate-500">
            {formatNumber(total)} total · refreshes every {REFRESH_MS / 1000}s
          </span>
        }
      />

      {error && <ErrorPanel error={error} />}
      {loading && !data && <Loading />}

      {data?.error && (
        <div className="card mb-4 border-amber-900/60 text-xs text-amber-300">{data.error}</div>
      )}

      {data && data.rows.length === 0 ? (
        <EmptyState message="No requests logged yet — send one through /v1/chat/completions" />
      ) : (
        data && <LogsTable rows={data.rows} />
      )}

      {data && data.rows.length > 0 && (
        <div className="mt-4 flex items-center justify-between">
          <button
            type="button"
            disabled={page === 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            className="rounded border border-slate-800 px-3 py-1.5 text-xs text-slate-300 disabled:opacity-40 hover:bg-slate-800/50"
          >
            ← Newer
          </button>

          <span className="text-xs tabular-nums text-slate-500">
            {formatNumber(offset + 1)}–{formatNumber(offset + data.rows.length)} of{' '}
            {formatNumber(total)}
          </span>

          <button
            type="button"
            disabled={!data.has_more || page >= lastPage}
            onClick={() => setPage((p) => p + 1)}
            className="rounded border border-slate-800 px-3 py-1.5 text-xs text-slate-300 disabled:opacity-40 hover:bg-slate-800/50"
          >
            Older →
          </button>
        </div>
      )}
    </>
  );
}