import { useEffect, useRef, useState, useCallback } from 'react';
import type { ClaimUpdateEvent } from '../types';

interface UseSSEReturn {
  connected: boolean;
  lastEvent: Date | null;
}

export function useSSE(onClaimUpdate: (event: ClaimUpdateEvent) => void): UseSSEReturn {
  const [connected, setConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState<Date | null>(null);
  const callbackRef = useRef(onClaimUpdate);
  callbackRef.current = onClaimUpdate;

  const connect = useCallback(() => {
    let retryDelay = 1000;
    let es: EventSource | null = null;
    let cancelled = false;

    function open() {
      if (cancelled) return;
      const sseUrl = import.meta.env.VITE_API_URL
        ? `${import.meta.env.VITE_API_URL}/claims/stream`
        : '/api/claims/stream';
      es = new EventSource(sseUrl);

      es.addEventListener('open', () => {
        setConnected(true);
        retryDelay = 1000;
      });

      es.addEventListener('claim_update', (e: MessageEvent) => {
        try {
          const data: ClaimUpdateEvent = JSON.parse(e.data);
          setLastEvent(new Date());
          callbackRef.current(data);
        } catch { /* ignore malformed */ }
      });

      es.addEventListener('heartbeat', () => {
        setLastEvent(new Date());
      });

      es.addEventListener('error', () => {
        setConnected(false);
        es?.close();
        if (!cancelled) {
          setTimeout(open, retryDelay);
          retryDelay = Math.min(retryDelay * 2, 30000);
        }
      });
    }

    open();

    return () => {
      cancelled = true;
      es?.close();
      setConnected(false);
    };
  }, []);

  useEffect(() => {
    const cleanup = connect();
    return cleanup;
  }, [connect]);

  return { connected, lastEvent };
}
