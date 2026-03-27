import { useEffect, useState } from 'react';
import { api } from '../api';
import type { Claim, ClaimUpdateEvent, Patient } from '../types';
import { ClaimDetail } from './ClaimDetail';

interface ClaimsListProps {
  refreshKey: number;
  lastSSEEvent: ClaimUpdateEvent | null;
}

const STATUS_STYLES: Record<string, string> = {
  created: 'bg-slate-100 text-slate-700',
  queued: 'bg-blue-100 text-blue-700',
  scoring: 'bg-amber-100 text-amber-700',
  scored: 'bg-teal-100 text-teal-700',
  submitted: 'bg-indigo-100 text-indigo-700',
  accepted: 'bg-green-100 text-green-700',
  denied: 'bg-red-100 text-red-700',
  error: 'bg-red-100 text-red-700',
};

function riskColor(score: number | null): string {
  if (score === null) return 'bg-slate-200';
  if (score >= 0.7) return 'bg-red-500';
  if (score >= 0.4) return 'bg-amber-500';
  return 'bg-green-500';
}

function riskLabel(score: number | null): string {
  if (score === null) return '—';
  if (score >= 0.7) return 'High';
  if (score >= 0.4) return 'Medium';
  return 'Low';
}

function cents(amount: number): string {
  return `$${(amount / 100).toLocaleString('en-US', { minimumFractionDigits: 2 })}`;
}

export function ClaimsList({ refreshKey, lastSSEEvent }: ClaimsListProps) {
  const [claims, setClaims] = useState<Claim[]>([]);
  const [patients, setPatients] = useState<Record<string, Patient>>({});
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getPatients().then(list => {
      const map: Record<string, Patient> = {};
      for (const p of list) map[p.id] = p;
      setPatients(map);
    });
  }, []);

  useEffect(() => {
    setLoading(true);
    api.getClaims().then(setClaims).finally(() => setLoading(false));
  }, [refreshKey]);

  // When SSE event arrives, update the matching claim in-place
  useEffect(() => {
    if (!lastSSEEvent) return;
    setClaims(prev =>
      prev.map(c =>
        c.id === lastSSEEvent.claim_id
          ? {
              ...c,
              status: 'scored',
              denial_risk_score: lastSSEEvent.denial_risk_score,
              denial_risk_factors: lastSSEEvent.denial_risk_factors,
            }
          : c
      )
    );
  }, [lastSSEEvent]);

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-slate-800">Claims Pipeline</h2>
        <span className="text-xs text-slate-500">{claims.length} claims</span>
      </div>

      {loading && claims.length === 0 ? (
        <div className="text-center text-slate-400 py-12">Loading claims...</div>
      ) : claims.length === 0 ? (
        <div className="text-center text-slate-400 py-12">No claims yet. Submit one or click "Run Demo" above.</div>
      ) : (
        <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200 text-left text-xs text-slate-500 uppercase tracking-wider">
                <th className="px-4 py-2.5">Patient</th>
                <th className="px-4 py-2.5">CDT Code</th>
                <th className="px-4 py-2.5">Amount</th>
                <th className="px-4 py-2.5">Status</th>
                <th className="px-4 py-2.5">Risk</th>
                <th className="px-4 py-2.5">Score</th>
              </tr>
            </thead>
            <tbody>
              {claims.map(claim => (
                <ClaimRow
                  key={claim.id}
                  claim={claim}
                  patientName={patients[claim.patient_id]?.name ?? '—'}
                  expanded={expandedId === claim.id}
                  onToggle={() => setExpandedId(expandedId === claim.id ? null : claim.id)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ClaimRow({ claim, patientName, expanded, onToggle }: {
  claim: Claim;
  patientName: string;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <>
      <tr
        onClick={onToggle}
        className="border-b border-slate-100 hover:bg-slate-50 cursor-pointer transition-colors"
      >
        <td className="px-4 py-3 font-medium">{patientName}</td>
        <td className="px-4 py-3">
          <span className="font-mono text-xs">{claim.cdt_code}</span>
          {claim.cdt_description && (
            <span className="ml-2 text-slate-500 text-xs">{claim.cdt_description}</span>
          )}
        </td>
        <td className="px-4 py-3">{cents(claim.charged_amount_cents)}</td>
        <td className="px-4 py-3">
          <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${STATUS_STYLES[claim.status] ?? STATUS_STYLES.created}`}>
            {claim.status}
          </span>
        </td>
        <td className="px-4 py-3">
          <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
            claim.denial_risk_score !== null && claim.denial_risk_score >= 0.7 ? 'bg-red-100 text-red-700' :
            claim.denial_risk_score !== null && claim.denial_risk_score >= 0.4 ? 'bg-amber-100 text-amber-700' :
            claim.denial_risk_score !== null ? 'bg-green-100 text-green-700' : 'bg-slate-100 text-slate-500'
          }`}>
            {riskLabel(claim.denial_risk_score)}
          </span>
        </td>
        <td className="px-4 py-3">
          {claim.denial_risk_score !== null ? (
            <div className="flex items-center gap-2">
              <div className="w-16 h-2 bg-slate-200 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full ${riskColor(claim.denial_risk_score)}`}
                  style={{ width: `${Math.round(claim.denial_risk_score * 100)}%` }}
                />
              </div>
              <span className="text-xs text-slate-600 font-mono">
                {(claim.denial_risk_score * 100).toFixed(0)}%
              </span>
            </div>
          ) : (
            <span className="text-xs text-slate-400">
              {claim.status === 'scoring' ? 'Scoring...' : '—'}
            </span>
          )}
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={6} className="bg-slate-50 px-4 py-4">
            <ClaimDetail claim={claim} />
          </td>
        </tr>
      )}
    </>
  );
}
