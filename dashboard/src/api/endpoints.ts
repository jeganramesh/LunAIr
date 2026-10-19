import { request } from './client';
import type {
  BalanceResponse,
  BenchmarkResponse,
  CacheStats,
  GatewayHealth,
  HealthResponse,
  LogsResponse,
  UsageResponse,
} from '../types/api';

export const fetchBalance = (maxAge = 300) =>
  request<BalanceResponse>(`/v1/balance?max_age=${maxAge}`);

export function fetchUsage(params: {
  range?: string;
  provider?: string;
  model?: string;
  keyId?: string;
} = {}) {
  const query = new URLSearchParams();
  if (params.range) query.set('range', params.range);
  if (params.provider) query.set('provider', params.provider);
  if (params.model) query.set('model', params.model);
  if (params.keyId) query.set('key_id', params.keyId);

  const suffix = query.toString();
  return request<UsageResponse>(`/v1/usage${suffix ? `?${suffix}` : ''}`);
}

export function fetchLogs(limit = 100, offset = 0) {
  return request<LogsResponse>(`/v1/usage/logs?limit=${limit}&offset=${offset}`);
}

export const fetchCacheStats = () => request<CacheStats>('/v1/usage/cache');

export const fetchHealth = () => request<HealthResponse>('/health');

export const fetchBenchmark = () => request<BenchmarkResponse>('/v1/benchmark');

/**
 * The gateway is a separate origin from FastAPI and is only reachable when
 * the gateway is running. Treat a failure here as "not deployed" rather than
 * a dashboard error.
 */
export async function fetchGatewayHealth(): Promise<GatewayHealth | null> {
  const gatewayBase = (import.meta.env.VITE_GATEWAY_URL || 'http://localhost:8080').replace(
    /\/+$/,
    '',
  );

  try {
    const response = await fetch(`${gatewayBase}/health`);
    if (!response.ok) return null;
    return (await response.json()) as GatewayHealth;
  } catch {
    return null;
  }
}