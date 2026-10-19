import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { BenchmarkRun } from '../types/api';

export function BenchmarkPanel({ results }: { results: BenchmarkRun[] }) {
  if (results.length === 0) return null;

  const data = results.map((run) => ({
    name: run.mode === 'go' ? 'Go gateway' : 'Direct',
    p50: Number(run.latency.p50_ms.toFixed(1)),
    p99: Number(run.latency.p99_ms.toFixed(1)),
    rps: Number(run.latency.rps.toFixed(1)),
  }));

  return (
    <div className="card">
      <p className="card-title">Latency by path</p>
      <div className="mt-4 h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data}>
            <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="name" stroke="#475569" fontSize={11} />
            <YAxis
              stroke="#475569"
              fontSize={11}
              tickFormatter={(v) => `${Number(v).toFixed(0)}ms`}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: '#0f172a',
                border: '1px solid #334155',
                borderRadius: '0.375rem',
                fontSize: '12px',
              }}
              formatter={(value: number, name) => [
                `${Number(value).toFixed(1)}ms`,
                name === 'p50' ? 'P50' : 'P99',
              ]}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Bar dataKey="p50" fill="#38bdf8" radius={[4, 4, 0, 0]} />
            <Bar dataKey="p99" fill="#a78bfa" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 border-t border-slate-800 pt-4">
        {results.map((run) => (
          <div key={`${run.mode}-${run.timestamp}`}>
            <p className="text-xs font-medium text-slate-400">
              {run.mode === 'go' ? 'Go gateway' : 'Direct FastAPI'}
            </p>
            <dl className="mt-1 space-y-0.5 text-xs text-slate-500">
              <div className="flex justify-between">
                <dt>target</dt>
                <dd className="text-slate-400">{run.target}</dd>
              </div>
              <div className="flex justify-between">
                <dt>concurrency</dt>
                <dd className="tabular-nums text-slate-400">{run.concurrency}</dd>
              </div>
              <div className="flex justify-between">
                <dt>requests</dt>
                <dd className="tabular-nums text-slate-400">{run.latency.requests}</dd>
              </div>
              <div className="flex justify-between">
                <dt>errors</dt>
                <dd className="tabular-nums text-slate-400">{run.latency.errors}</dd>
              </div>
              <div className="flex justify-between">
                <dt>throughput</dt>
                <dd className="tabular-nums text-slate-400">{run.latency.rps} rps</dd>
              </div>
            </dl>
          </div>
        ))}
      </div>
    </div>
  );
}