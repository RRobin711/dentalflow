import type { Patient, Claim, ClaimCreateRequest, EligibilityRequest, EligibilityResponse, HealthResponse } from './types';

const BASE = import.meta.env.VITE_API_URL || '/api';
const HEALTH_URL = import.meta.env.VITE_API_URL
  ? `${import.meta.env.VITE_API_URL.replace(/\/api$/, '')}/health`
  : '/health';

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export const api = {
  getPatients: () => fetchJSON<Patient[]>(`${BASE}/patients`),

  getClaims: () => fetchJSON<Claim[]>(`${BASE}/claims`),

  getClaim: (id: string) => fetchJSON<Claim>(`${BASE}/claims/${id}`),

  createClaim: (data: ClaimCreateRequest) =>
    fetchJSON<Claim>(`${BASE}/claims`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),

  checkEligibility: (data: EligibilityRequest) =>
    fetchJSON<EligibilityResponse>(`${BASE}/eligibility`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),

  getHealth: () => fetchJSON<HealthResponse>(HEALTH_URL),
};
