import { useState, useCallback } from 'react';
import type { ClaimUpdateEvent } from './types';
import { useSSE } from './hooks/useSSE';
import { Layout } from './components/Layout';
import { ClaimsList } from './components/ClaimsList';
import { NewClaimForm } from './components/NewClaimForm';
import { EligibilityCheck } from './components/EligibilityCheck';
import { SystemHealth } from './components/SystemHealth';
import { DemoBanner } from './components/DemoBanner';

type View = 'claims' | 'new-claim' | 'eligibility' | 'health';

export default function App() {
  const [view, setView] = useState<View>('claims');
  const [refreshKey, setRefreshKey] = useState(0);
  const [sseEvent, setSSEEvent] = useState<ClaimUpdateEvent | null>(null);

  const handleClaimUpdate = useCallback((event: ClaimUpdateEvent) => {
    setSSEEvent(event);
    setRefreshKey(k => k + 1);
  }, []);

  const { connected } = useSSE(handleClaimUpdate);

  return (
    <div className="min-h-screen flex flex-col">
      <DemoBanner onDemoComplete={() => setRefreshKey(k => k + 1)} />
      <div className="flex flex-1">
        <Layout view={view} onNavigate={setView} sseConnected={connected} />
        <main className="flex-1 p-6 overflow-auto">
          {view === 'claims' && (
            <ClaimsList refreshKey={refreshKey} lastSSEEvent={sseEvent} />
          )}
          {view === 'new-claim' && (
            <NewClaimForm onSubmitted={() => { setView('claims'); setRefreshKey(k => k + 1); }} />
          )}
          {view === 'eligibility' && <EligibilityCheck />}
          {view === 'health' && <SystemHealth />}
        </main>
      </div>
    </div>
  );
}
