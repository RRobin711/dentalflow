import { useEffect, useState } from 'react';
import { api } from '../api';
import type { HealthResponse } from '../types';

export function SystemHealth() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState('');
  const [lastCheck, setLastCheck] = useState<Date | null>(null);

  useEffect(() => {
    function check() {
      api.getHealth()
        .then(h => { setHealth(h); setError(''); })
        .catch(e => setError(e.message));
      setLastCheck(new Date());
    }
    check();
    const interval = setInterval(check, 10000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="max-w-lg">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-slate-800">System Health</h2>
        {lastCheck && (
          <span className="text-xs text-slate-500">
            Last check: {lastCheck.toLocaleTimeString()} (every 10s)
          </span>
        )}
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700 mb-4">
          Cannot reach gateway: {error}
        </div>
      )}

      {health && (
        <div className="bg-white border border-slate-200 rounded-lg p-5">
          <div className="flex items-center gap-3 mb-4">
            <span className={`inline-block w-3 h-3 rounded-full ${health.status === 'ok' ? 'bg-green-500' : 'bg-amber-500'}`} />
            <span className="font-semibold text-sm">
              Gateway: {health.status.toUpperCase()}
            </span>
          </div>

          {health.dependencies && (
            <div className="space-y-2">
              {Object.entries(health.dependencies).map(([name, status]) => (
                <div key={name} className="flex items-center justify-between py-2 border-b border-slate-100 last:border-0">
                  <span className="text-sm text-slate-700">{name}</span>
                  <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${
                    status === 'ok' ? 'text-green-600' : 'text-red-600'
                  }`}>
                    <span className={`inline-block w-2 h-2 rounded-full ${
                      status === 'ok' ? 'bg-green-500' : 'bg-red-500'
                    }`} />
                    {status.toUpperCase()}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
