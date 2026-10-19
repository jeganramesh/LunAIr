import { createRoot } from 'react-dom/client';
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom';
import App from './App';
import Balance from './pages/Balance';
import Usage from './pages/Usage';
import Logs from './pages/Logs';
import Cache from './pages/Cache';
import Health from './pages/Health';
import Benchmark from './pages/Benchmark';
import './index.css';

const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    children: [
      { index: true, element: <Navigate to="/balance" replace /> },
      { path: 'balance', element: <Balance /> },
      { path: 'usage', element: <Usage /> },
      { path: 'logs', element: <Logs /> },
      { path: 'cache', element: <Cache /> },
      { path: 'health', element: <Health /> },
      { path: 'benchmark', element: <Benchmark /> },
      { path: '*', element: <Navigate to="/balance" replace /> },
    ],
  },
]);

createRoot(document.getElementById('root')!).render(
  <RouterProvider router={router} />,
);