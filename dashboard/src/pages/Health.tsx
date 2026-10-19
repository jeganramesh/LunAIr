import { useEffect, useState } from 'react';
import { fetchGatewayHealth, fetchHealth } from '../api/endpoints';
import {
  LayerStatus,
  ProviderHealth,
  gatewayDetail,
  healthDetail,
} from '../components/ProviderHealth';
import { ErrorPanel, Loading, PageHeader } from '../components/ui';
import { usePolling } from '../hooks/usePolling';
import type { GatewayHealth } from '../types/api';

const REFRESH_MS = 30_000;

export default function Health() {
  const { data, error, loading } = usePolling(fetchHealth, REFRESH_MS);
  const [gateway, setGateway] = useState<GatewayHealth | null>(null);

  useEffect(() => {
    let active = true;

    const load = async () => {
      const result = await fetchGatewayHealth();
      if (active) setGateway(result);
    };

    void load();
    const timer = window.setInterval(() => void load(), REFRESH_MS);

    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  const providers = data?.details?.providers ?? {};
  const breakers = data?.details?.circuit_breakers ?? {};

  return (
    <>
      <PageHeader
        title="Health"
        description="Layer status, provider credentials and circuit breaker state"
        action={
          <span className="text-xs text-slate-500">
            Auto-refreshes every {REFRESH_MS / 1000}s
          </span>
        }
      />

      {error && <ErrorPanel error={error} />}
      {loading && !data && <Loading />}

      <div className="mb-4 grid gap-4 sm:grid-cols-2">
        <LayerStatus label="FastAPI core" up={!!data && !error} detail={healthDetail(data)} />
        <LayerStatus
          label="Go gateway"
          up={!!gateway}
          detail={gatewayDetail(gateway)}
        />
      </div>

      {data?.details && data.details.providers_ready < data.details.providers_total && (
        <div className="card mb-4 border-amber-900/60">
          <p className="text-sm font-medium text-amber-300">Provider credentials incomplete</p>
          <p className="mt-1 text-xs text-amber-200/80">
            Missing:{' '}
            {Object.entries(data.details.unconfigured_providers)
              .map(([provider, envVar]) => `${provider} (${envVar})`)
              .join(', ')}
          </p>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {Object.entries(providers).map(([name, info]) => (
          <ProviderHealth
            key={name}
            name={name}
            state={breakers[name]}
            configured={info.configured}
          />
        ))}
      </div>
    </>
  );
}