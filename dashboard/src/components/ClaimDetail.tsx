import type { Claim } from '../types';

interface ClaimDetailProps {
  claim: Claim;
}

export function ClaimDetail({ claim }: ClaimDetailProps) {
  return (
    <div className="grid grid-cols-2 gap-6 text-sm">
      <div>
        <h4 className="font-semibold text-slate-700 mb-2">Claim Details</h4>
        <dl className="space-y-1">
          <Row label="Claim ID" value={claim.id} mono />
          <Row label="Idempotency Key" value={claim.idempotency_key} mono />
          <Row label="Procedure Date" value={claim.procedure_date} />
          <Row label="Tooth #" value={claim.tooth_number?.toString() ?? '—'} />
          <Row label="Amount" value={`$${(claim.charged_amount_cents / 100).toFixed(2)}`} />
          <Row label="Has X-ray" value={claim.has_xray ? 'Yes' : 'No'} />
          <Row label="Has Narrative" value={claim.has_narrative ? 'Yes' : 'No'} />
          <Row label="Has Perio Chart" value={claim.has_perio_chart ? 'Yes' : 'No'} />
        </dl>
      </div>

      <div>
        <h4 className="font-semibold text-slate-700 mb-2">Denial Risk Analysis</h4>
        {claim.denial_risk_score !== null ? (
          <>
            <div className="mb-3">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-2xl font-bold font-mono" style={{
                  color: claim.denial_risk_score >= 0.7 ? '#dc2626' :
                         claim.denial_risk_score >= 0.4 ? '#d97706' : '#16a34a'
                }}>
                  {(claim.denial_risk_score * 100).toFixed(1)}%
                </span>
                <span className="text-slate-500 text-xs">denial risk</span>
              </div>
              <div className="w-full h-3 bg-slate-200 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-500 ${
                    claim.denial_risk_score >= 0.7 ? 'bg-red-500' :
                    claim.denial_risk_score >= 0.4 ? 'bg-amber-500' : 'bg-green-500'
                  }`}
                  style={{ width: `${Math.round(claim.denial_risk_score * 100)}%` }}
                />
              </div>
            </div>

            {claim.denial_risk_factors && claim.denial_risk_factors.length > 0 && (
              <div>
                <h5 className="text-xs font-semibold text-slate-500 uppercase mb-1">Risk Factors</h5>
                <ul className="space-y-1">
                  {claim.denial_risk_factors.map((f, i) => (
                    <li key={i} className="flex items-start gap-1.5 text-xs text-slate-600">
                      <span className="text-amber-500 mt-0.5">&#9888;</span>
                      {f}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        ) : (
          <p className="text-slate-400 text-xs italic">
            {claim.status === 'scoring' ? 'ML model is scoring this claim...' : 'Awaiting scoring'}
          </p>
        )}

        <div className="mt-4">
          <h5 className="text-xs font-semibold text-slate-500 uppercase mb-1">Timeline</h5>
          <dl className="space-y-1">
            {claim.created_at && <Row label="Created" value={new Date(claim.created_at).toLocaleString()} />}
            {claim.scored_at && <Row label="Scored" value={new Date(claim.scored_at).toLocaleString()} />}
            {claim.updated_at && <Row label="Updated" value={new Date(claim.updated_at).toLocaleString()} />}
          </dl>
        </div>
      </div>
    </div>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex gap-2">
      <dt className="text-slate-500 w-32 shrink-0">{label}</dt>
      <dd className={mono ? 'font-mono text-xs break-all' : ''}>{value}</dd>
    </div>
  );
}
