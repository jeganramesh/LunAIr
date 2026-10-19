import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { UsageAggregate, UsageRow } from '../types/api';
import { formatDay, formatUsd } from '../utils/format';

const AXIS = { stroke: '#475569', fontSize: 11 };
const GRID = '#1e293b';
const TOOLTIP_STYLE = {
  backgroundColor: '#0f172a',
  border: '1px solid #334155',
  borderRadius: '0.375rem',
  fontSize: '12px',
};

export function TokenTrendChart({ series }: { series: UsageRow[] }) {
  // Aggregate by day so multiple provider rows collapse into one point.
  const byDay = new Map<string, { day: string; tokens_in: number; tokens_out: number }>();

  for (const row of series) {
    const existing = byDay.get(row.day) ?? { day: row.day, tokens_in: 0, tokens_out: 0 };
    existing.tokens_in += row.tokens_in ?? 0;
    existing.tokens_out += row.tokens_out ?? 0;
    byDay.set(row.day, existing);
  }

  const data = [...byDay.values()].sort((a, b) => a.day.localeCompare(b.day));

  return (
    <div className="card">
      <p className="card-title">Token consumption</p>
      <div className="mt-4 h-64">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data}>
            <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
            <XAxis dataKey="day" tickFormatter={formatDay} {...AXIS} />
            <YAxis {...AXIS} />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              labelFormatter={(v) => formatDay(String(v))}
              formatter={(value: number, name) => [
                value.toLocaleString(),
                name === 'tokens_in' ? 'Prompt' : 'Completion',
              ]}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Line
              type="monotone"
              dataKey="tokens_in"
              stroke="#38bdf8"
              strokeWidth={2}
              dot={false}
            />
            <Line
              type="monotone"
              dataKey="tokens_out"
              stroke="#a78bfa"
              strokeWidth={2}
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export function CostTrendChart({ series }: { series: UsageRow[] }) {
  const byDay = new Map<string, { day: string; cost: number }>();

  for (const row of series) {
    const existing = byDay.get(row.day) ?? { day: row.day, cost: 0 };
    existing.cost += row.cost ?? 0;
    byDay.set(row.day, existing);
  }

  const data = [...byDay.values()]
    .sort((a, b) => a.day.localeCompare(b.day))
    .map((d) => ({ ...d, cost: Number(d.cost.toFixed(6)) }));

  return (
    <div className="card">
      <p className="card-title">Cost trend</p>
      <div className="mt-4 h-64">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data}>
            <defs>
              <linearGradient id="costFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#34d399" stopOpacity={0.5} />
                <stop offset="100%" stopColor="#34d399" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
            <XAxis dataKey="day" tickFormatter={formatDay} {...AXIS} />
            <YAxis {...AXIS} tickFormatter={(v) => `$${Number(v).toFixed(2)}`} />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              labelFormatter={(v) => formatDay(String(v))}
              formatter={(value: number) => [formatUsd(value), 'Cost']}
            />
            <Area
              type="monotone"
              dataKey="cost"
              stroke="#34d399"
              strokeWidth={2}
              fill="url(#costFill)"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export function ProviderDistributionChart({ byProvider }: { byProvider: UsageAggregate[] }) {
  const data = byProvider.map((p) => ({
    name: p.provider ?? 'unknown',
    requests: p.requests,
    cost_usd: p.cost_usd,
  }));

  return (
    <div className="card">
      <p className="card-title">Requests by provider</p>
      <div className="mt-4 h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data}>
            <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="name" {...AXIS} />
            <YAxis {...AXIS} />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              cursor={{ fill: 'rgba(148,163,184,0.08)' }}
              formatter={(value: number) => [value.toLocaleString(), 'Requests']}
            />
            <Bar dataKey="requests" fill="#38bdf8" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}