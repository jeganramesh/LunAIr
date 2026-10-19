export interface ProviderBalance {
  provider: string;
  balance_usd: number | null;
  lifetime_spend_usd: number | null;
  available: boolean;
  note: string | null;
  last_refreshed?: string | null;
}

export interface BalanceResponse {
  providers: ProviderBalance[];
  total_remaining_usd: number | null;
  providers_available: number;
  providers_total: number;
  last_refreshed: string | null;
}

export interface UsageRow {
  day: string;
  provider: string;
  model: string;
  key_id: string;
  tokens_in: number;
  tokens_out: number;
  cost: number;
  requests: number;
}

export interface UsageAggregate {
  provider?: string;
  model?: string;
  requests: number;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
}

export interface UsageResponse {
  range: string;
  days: number;
  filters: { provider?: string | null; model?: string | null; key_id?: string | null };
  series: UsageRow[];
  by_provider: UsageAggregate[];
  by_model: UsageAggregate[];
  totals: {
    tokens_in: number;
    tokens_out: number;
    cost_usd: number;
    requests: number;
  };
  generated_at: string;
  error?: string;
}

export interface RequestLog {
  id: string;
  created_at: string;
  key_id: string;
  model: string;
  provider: string;
  tokens_in: number;
  tokens_out: number;
  cost: number;
  latency_ms: number;
  pii_redacted: boolean;
  injection_blocked: boolean;
  cache_hit: boolean;
  cache_similarity: number | null;
  gateway_mode: string;
  fallback_from: string | null;
  finish_reason: string | null;
}

export interface LogsResponse {
  rows: RequestLog[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
  error?: string;
}

export interface CacheStats {
  enabled: boolean;
  total_requests: number;
  hits: number;
  misses: number;
  hit_rate: number;
  avg_similarity: number;
  saved_cost_usd: number;
  total_cost_usd: number;
  window_days: number;
  error?: string;
}

export interface CircuitState {
  provider: string;
  state: 'closed' | 'open' | 'half_open';
  consecutive_failures: number;
  total_failures: number;
  last_failure_at: string | null;
  retry_in_s: number;
}

export interface HealthDetails {
  fastapi_url: string;
  providers: Record<string, { configured: boolean; env_var: string; model: string }>;
  unconfigured_providers: Record<string, string>;
  providers_ready: number;
  providers_total: number;
  circuit_breakers?: Record<string, CircuitState>;
}

export interface HealthResponse {
  status: string;
  version: string;
  gateway_mode: string | null;
  details?: HealthDetails;
}

export interface GatewayHealth {
  status: string;
  component: string;
  mode: string;
  fastapi_url: string;
  uptime_s: number;
}

export interface BenchmarkLatency {
  p50_ms: number;
  p95_ms: number;
  p99_ms: number;
  mean_ms: number;
  rps: number;
  requests: number;
  errors: number;
}

export interface BenchmarkRun {
  mode: 'go' | 'fastapi_only';
  target: string;
  concurrency: number;
  timestamp: string;
  latency: BenchmarkLatency;
}

export interface BenchmarkResponse {
  available: boolean;
  results?: BenchmarkRun[];
  hint?: string;
  error?: string;
}