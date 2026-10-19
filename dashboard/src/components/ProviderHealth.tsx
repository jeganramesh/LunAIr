import type { CircuitState, GatewayHealth, HealthResponse } from '../types/api';
import { formatTimestamp } from '../utils/format';

const STATE_STYLES: Record<CircuitState['state'], string> = {
  closed: 'bg-emerald-950 text-emerald-300',
  half_open: 'bg-amber-950 text-amber-300',
  open: 'bg-red-950 text-red-300',
};

export function ProviderHealth({
  name,
  state,
  configured,
}: {
  name: string;
  state?: CircuitState;
  configured: boolean;
}) {
  const circuitState = state?.state ?? 'closed';

  return (
    <div className="card">
      <div className="flex items-start justify-between">
        <p className="card-title">{name}</p>
        <span
          className={
            configured
              ? 'badge bg-emerald-950 text-emerald-300'
              : 'badge bg-slate-800 text-slate-400'
          }
        >
          {configured ? 'key set' : 'no key'}
        </span>
      </div>

      <div className="mt-3 flex items-center gap-2">
        <span className={`badge ${STATE_STYLES[circuitState]}`}>{circuitState}</span>
        {state && state.retry_in_s > 0 && (
          <span className="text-xs text-slate-500">retry in {state.retry_in_s}s</span>
        )}
      </div>

      <dl className="mt-3 space-y-1 text-xs text-slate-500">
        <div className="flex justify-between">
          <dt>Consecutive failures</dt>
          <dd className="tabular-nums text-slate-400">{state?.consecutive_failures ?? 0}</dd>
        </div>
        <div className="flex justify-between">
          <dt>Total failures</dt>
          <dd className="tabular-nums text-slate-400">{state?.total_failures ?? 0}</dd>
        </div>
        <div className="flex justify-between">
          <dt>Last failure</dt>
          <dd>{formatTimestamp(state?.last_failure_at)}</dd>
        </div>
      </dl>
    </div>
  );
}

export function LayerStatus({
  label,
  up,
  detail,
}: {
  label: string;
  up: boolean;
  detail: string;
}) {
  return (
    <div className="card flex items-center justify-between">
      <div>
        <p className="card-title">{label}</p>
        <p className="mt-1 text-xs text-slate-500">{detail}</p>
      </div>
      <span
        className={up ? 'badge bg-emerald-950 text-emerald-300' : 'badge bg-slate-800 text-slate-400'}
      >
        {up ? 'online' : 'offline'}
      </span>
    </div>
  );
}

export function healthDetail(health: HealthResponse | null): string {
  if (!health) return 'unreachable';
  const ready = health.details?.providers_ready ?? 0;
  const total = health.details?.providers_total ?? 0;
  return `v${health.version} · ${ready}/${total} providers ready`;
}

export function gatewayDetail(gateway: GatewayHealth | null): string {
  if (!gateway) return 'not running (GATEWAY_MODE=fastapi_only?)';
  return `${gateway.mode} mode · up ${gateway.uptime_s}s`;
}