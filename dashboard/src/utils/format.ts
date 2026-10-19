export function formatUsd(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  if (value === 0) return '$0.00';
  if (Math.abs(value) < 0.01) return `$${value.toFixed(6)}`;
  return `$${value.toFixed(2)}`;
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return new Intl.NumberFormat('en-US').format(value);
}

export function formatCompact(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  if (Math.abs(value) < 1000) return String(Math.round(value));
  return new Intl.NumberFormat('en-US', {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(value);
}

export function formatLatency(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return '—';
  return `${ms.toFixed(0)}ms`;
}

export function formatPercent(ratio: number | null | undefined, digits = 1): string {
  if (ratio === null || ratio === undefined || Number.isNaN(ratio)) return '—';
  return `${(ratio * 100).toFixed(digits)}%`;
}

export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

export function formatDay(day: string | null | undefined): string {
  if (!day) return '—';
  const date = new Date(day);
  if (Number.isNaN(date.getTime())) return day;
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}