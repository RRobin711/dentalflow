import { useEffect, useState } from 'react';
import { api } from '../api';
import type { Patient, EligibilityResponse } from '../types';

const CDT_OPTIONS = [
  ['D0120', 'Periodic oral evaluation'],
  ['D1110', 'Prophylaxis - adult'],
  ['D2750', 'Crown - porcelain fused to metal'],
  ['D3330', 'Root canal - molar'],
  ['D4341', 'Scaling/root planing - 4+ teeth'],
  ['D5110', 'Complete denture - maxillary'],
  ['D6010', 'Implant body - endosteal'],
  ['D7240', 'Extraction - impacted, bony'],
  ['D8090', 'Comprehensive ortho - adult'],
];

function cents(amount: number): string {
  return `$${(amount / 100).toLocaleString('en-US', { minimumFractionDigits: 2 })}`;
}

export function EligibilityCheck() {
  const [patients, setPatients] = useState<Patient[]>([]);
  const [patientId, setPatientId] = useState('');
  const [cdtCode, setCdtCode] = useState('');
  const [checking, setChecking] = useState(false);
  const [result, setResult] = useState<EligibilityResponse | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    api.getPatients().then(setPatients);
  }, []);

  async function handleCheck(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setResult(null);
    setChecking(true);
    try {
      const res = await api.checkEligibility({ patient_id: patientId, cdt_code: cdtCode });
      setResult(res);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className="max-w-xl">
      <h2 className="text-lg font-semibold text-slate-800 mb-4">Eligibility Verification</h2>

      <form onSubmit={handleCheck} className="bg-white border border-slate-200 rounded-lg p-6 space-y-4">
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
          <label className="block text-xs font-medium text-slate-600 mb-1">Procedure (CDT Code)</label>
          <select
            required
            value={cdtCode}
            onChange={e => setCdtCode(e.target.value)}
            className="w-full border border-slate-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-600"
          >
            <option value="">Select procedure...</option>
            {CDT_OPTIONS.map(([code, desc]) => (
              <option key={code} value={code}>{code} — {desc}</option>
            ))}
          </select>
        </div>

        <button
          type="submit"
          disabled={checking}
          className="w-full bg-teal-700 text-white py-2.5 rounded font-medium text-sm hover:bg-teal-600 disabled:opacity-50 transition-colors"
        >
          {checking ? 'Checking...' : 'Check Eligibility'}
        </button>
      </form>

      {error && (
        <div className="mt-4 bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {result && (
        <div className="mt-4 bg-white border border-slate-200 rounded-lg p-5">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <span className={`inline-block w-3 h-3 rounded-full ${result.eligible ? 'bg-green-500' : 'bg-red-500'}`} />
              <span className={`font-semibold ${result.eligible ? 'text-green-700' : 'text-red-700'}`}>
                {result.eligible ? 'Eligible' : 'Not Eligible'}
              </span>
            </div>
            <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
              result.cache_hit
                ? 'bg-amber-100 text-amber-700'
                : 'bg-blue-100 text-blue-700'
            }`}>
              <span className={`inline-block w-1.5 h-1.5 rounded-full ${result.cache_hit ? 'bg-amber-500' : 'bg-blue-500'}`} />
              {result.cache_hit ? 'Cache HIT (Redis)' : 'Cache MISS (fetched)'}
            </span>
          </div>

          {result.reason && (
            <div className="mb-3 text-sm text-red-600">{result.reason}</div>
          )}

          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
            <div>
              <dt className="text-slate-500 text-xs">Patient</dt>
              <dd className="font-medium">{result.patient_name}</dd>
            </div>
            <div>
              <dt className="text-slate-500 text-xs">Insurance</dt>
              <dd>{result.insurance_provider} ({result.plan_type})</dd>
            </div>
            <div>
              <dt className="text-slate-500 text-xs">Procedure Category</dt>
              <dd>{result.cdt_category}</dd>
            </div>
            <div>
              <dt className="text-slate-500 text-xs">Coverage</dt>
              <dd className="font-semibold text-teal-700">{result.coverage_percent}%</dd>
            </div>
            <div>
              <dt className="text-slate-500 text-xs">Insurance Pays</dt>
              <dd>{cents(result.estimated_insurance_pays_cents)}</dd>
            </div>
            <div>
              <dt className="text-slate-500 text-xs">Patient Pays</dt>
              <dd>{cents(result.estimated_patient_cost_cents)}</dd>
            </div>
            <div>
              <dt className="text-slate-500 text-xs">Annual Maximum</dt>
              <dd>{cents(result.annual_maximum_cents)}</dd>
            </div>
            <div>
              <dt className="text-slate-500 text-xs">Annual Remaining</dt>
              <dd className={result.annual_remaining_cents < 20000 ? 'text-red-600 font-semibold' : ''}>
                {cents(result.annual_remaining_cents)}
              </dd>
            </div>
          </dl>
        </div>
      )}
    </div>
  );
}
