import { useEffect, useState, useRef } from 'react';
import { api } from '../api';
import type { Patient, Claim, ClaimUpdateEvent } from '../types';

interface NewClaimFormProps {
  onSubmitted: () => void;
}

const CDT_GROUPS: Record<string, [string, string][]> = {
  'Diagnostic (D0)': [
    ['D0120', 'Periodic oral evaluation'],
    ['D0140', 'Limited oral evaluation - problem focused'],
    ['D0150', 'Comprehensive oral evaluation'],
    ['D0210', 'Intraoral complete series'],
    ['D0220', 'Intraoral periapical first image'],
    ['D0274', 'Bitewings - four images'],
    ['D0330', 'Panoramic image'],
  ],
  'Preventive (D1)': [
    ['D1110', 'Prophylaxis - adult'],
    ['D1120', 'Prophylaxis - child'],
    ['D1206', 'Topical fluoride varnish'],
    ['D1351', 'Sealant - per tooth'],
  ],
  'Restorative (D2)': [
    ['D2140', 'Amalgam - one surface'],
    ['D2150', 'Amalgam - two surfaces'],
    ['D2330', 'Composite - one surface, anterior'],
    ['D2391', 'Composite - one surface, posterior'],
    ['D2740', 'Crown - porcelain/ceramic'],
    ['D2750', 'Crown - porcelain fused to metal'],
  ],
  'Endodontics (D3)': [
    ['D3310', 'Root canal - anterior'],
    ['D3320', 'Root canal - premolar'],
    ['D3330', 'Root canal - molar'],
  ],
  'Periodontics (D4)': [
    ['D4341', 'Scaling/root planing - 4+ teeth'],
    ['D4342', 'Scaling/root planing - 1-3 teeth'],
    ['D4910', 'Periodontal maintenance'],
  ],
  'Prosthodontics (D5)': [
    ['D5110', 'Complete denture - maxillary'],
    ['D5120', 'Complete denture - mandibular'],
    ['D5213', 'Partial denture - cast metal'],
  ],
  'Implant (D6)': [
    ['D6010', 'Implant body - endosteal'],
    ['D6065', 'Implant porcelain crown'],
  ],
  'Oral Surgery (D7)': [
    ['D7140', 'Extraction - erupted tooth'],
    ['D7210', 'Extraction - bone removal'],
    ['D7240', 'Extraction - impacted, bony'],
  ],
  'Orthodontics (D8)': [
    ['D8090', 'Comprehensive ortho - adult'],
  ],
};

export function NewClaimForm({ onSubmitted }: NewClaimFormProps) {
  const [patients, setPatients] = useState<Patient[]>([]);
  const [patientId, setPatientId] = useState('');
  const [cdtCode, setCdtCode] = useState('');
  const [procedureDate, setProcedureDate] = useState(new Date().toISOString().split('T')[0]);
  const [amountDollars, setAmountDollars] = useState('');
  const [toothNumber, setToothNumber] = useState('');
  const [hasXray, setHasXray] = useState(false);
  const [hasNarrative, setHasNarrative] = useState(false);
  const [hasPerioChart, setHasPerioChart] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<Claim | null>(null);
  const [sseResult, setSSEResult] = useState<ClaimUpdateEvent | null>(null);
  const [error, setError] = useState('');
  const sseRef = useRef<EventSource | null>(null);

  useEffect(() => {
    api.getPatients().then(setPatients);
  }, []);

  // Listen for SSE updates on the submitted claim
  useEffect(() => {
    if (!result) return;
    const sseUrl = import.meta.env.VITE_API_URL
      ? `${import.meta.env.VITE_API_URL}/claims/stream`
      : '/api/claims/stream';
    const es = new EventSource(sseUrl);
    sseRef.current = es;
    es.addEventListener('claim_update', (e: MessageEvent) => {
      try {
        const data: ClaimUpdateEvent = JSON.parse(e.data);
        if (data.claim_id === result.id) {
          setSSEResult(data);
          es.close();
        }
      } catch { /* ignore */ }
    });
    return () => es.close();
  }, [result]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setResult(null);
    setSSEResult(null);
    setSubmitting(true);

    try {
      const claim = await api.createClaim({
        idempotency_key: crypto.randomUUID(),
        patient_id: patientId,
        cdt_code: cdtCode,
        procedure_date: procedureDate,
        tooth_number: toothNumber ? parseInt(toothNumber, 10) : undefined,
        charged_amount_cents: Math.round(parseFloat(amountDollars) * 100),
        has_xray: hasXray,
        has_narrative: hasNarrative,
        has_perio_chart: hasPerioChart,
      });
      setResult(claim);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="max-w-xl">
      <h2 className="text-lg font-semibold text-slate-800 mb-4">Submit New Claim</h2>

      <form onSubmit={handleSubmit} className="bg-white border border-slate-200 rounded-lg p-6 space-y-4">
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Patient</label>
          <select
            required
            value={patientId}
            onChange={e => setPatientId(e.target.value)}
            className="w-full border border-slate-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-600"
          >
            <option value="">Select patient...</option>
            {patients.map(p => (
              <option key={p.id} value={p.id}>{p.name} — {p.insurance_provider} ({p.plan_type})</option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">CDT Code</label>
          <select
            required
            value={cdtCode}
            onChange={e => setCdtCode(e.target.value)}
            className="w-full border border-slate-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-600"
          >
            <option value="">Select procedure...</option>
            {Object.entries(CDT_GROUPS).map(([group, codes]) => (
              <optgroup key={group} label={group}>
                {codes.map(([code, desc]) => (
                  <option key={code} value={code}>{code} — {desc}</option>
                ))}
              </optgroup>
            ))}
          </select>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">Procedure Date</label>
            <input
              type="date"
              required
              value={procedureDate}
              onChange={e => setProcedureDate(e.target.value)}
              className="w-full border border-slate-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-600"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">Amount ($)</label>
            <input
              type="number"
              required
              min="0.01"
              step="0.01"
              value={amountDollars}
              onChange={e => setAmountDollars(e.target.value)}
              placeholder="1500.00"
              className="w-full border border-slate-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-600"
            />
          </div>
        </div>

        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Tooth Number (optional, 1-32)</label>
          <input
            type="number"
            min="1"
            max="32"
            value={toothNumber}
            onChange={e => setToothNumber(e.target.value)}
            className="w-full border border-slate-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-600"
          />
        </div>

        <div className="flex gap-6">
          <label className="flex items-center gap-2 text-sm text-slate-600">
            <input type="checkbox" checked={hasXray} onChange={e => setHasXray(e.target.checked)} className="accent-teal-700" />
            Has X-ray
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-600">
            <input type="checkbox" checked={hasNarrative} onChange={e => setHasNarrative(e.target.checked)} className="accent-teal-700" />
            Has Narrative
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-600">
            <input type="checkbox" checked={hasPerioChart} onChange={e => setHasPerioChart(e.target.checked)} className="accent-teal-700" />
            Has Perio Chart
          </label>
        </div>

        <button
          type="submit"
          disabled={submitting}
          className="w-full bg-teal-700 text-white py-2.5 rounded font-medium text-sm hover:bg-teal-600 disabled:opacity-50 transition-colors"
        >
          {submitting ? 'Submitting...' : 'Submit Claim'}
        </button>
      </form>

      {error && (
        <div className="mt-4 bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {result && (
        <div className="mt-4 bg-white border border-slate-200 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-slate-700 mb-2">Claim Submitted</h3>
          <div className="text-xs text-slate-500 font-mono mb-3">ID: {result.id}</div>
          <div className="flex items-center gap-2 mb-2">
            <span className="inline-block px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-700">
              {result.status}
            </span>
          </div>

          {!sseResult ? (
            <div className="flex items-center gap-2 text-sm text-amber-600">
              <span className="inline-block w-2 h-2 bg-amber-500 rounded-full animate-pulse" />
              Waiting for ML scoring...
            </div>
          ) : (
            <div className="mt-2">
              <div className="flex items-center gap-2 text-sm">
                <span className="font-semibold" style={{
                  color: sseResult.denial_risk_score >= 0.7 ? '#dc2626' :
                         sseResult.denial_risk_score >= 0.4 ? '#d97706' : '#16a34a'
                }}>
                  Scored: {(sseResult.denial_risk_score * 100).toFixed(1)}% denial risk
                </span>
                <span className="text-xs text-slate-400">({sseResult.processing_time_ms.toFixed(0)}ms)</span>
              </div>
              <p className="text-xs text-slate-600 mt-1">{sseResult.recommendation}</p>
              <button
                onClick={onSubmitted}
                className="mt-3 text-sm text-teal-700 hover:underline"
              >
                View in Claims List
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
