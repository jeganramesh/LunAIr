import { NavLink, Outlet } from 'react-router-dom';
import { API_BASE } from './api/client';

const NAV = [
  { to: '/balance', label: 'Balance' },
  { to: '/usage', label: 'Usage' },
  { to: '/logs', label: 'Logs' },
  { to: '/cache', label: 'Cache' },
  { to: '/health', label: 'Health' },
  { to: '/benchmark', label: 'Benchmark' },
];

export default function App() {
  return (
    <div className="flex min-h-screen">
      <aside className="w-56 shrink-0 border-r border-slate-800 bg-slate-900/40">
        <div className="border-b border-slate-800 px-4 py-4">
          <p className="text-sm font-semibold text-slate-100">LunAIR</p>
          <p className="mt-0.5 truncate text-xs text-slate-500" title={API_BASE}>
            {API_BASE}
          </p>
        </div>

        <nav className="p-2">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                [
                  'block rounded px-3 py-2 text-sm transition-colors',
                  isActive
                    ? 'bg-slate-800 font-medium text-slate-100'
                    : 'text-slate-400 hover:bg-slate-800/50 hover:text-slate-200',
                ].join(' ')
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>

      <main className="min-w-0 flex-1 overflow-x-hidden p-6">
        <Outlet />
      </main>
    </div>
  );
}