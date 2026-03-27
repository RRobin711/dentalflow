import { useState } from 'react';
import { api } from '../api';

interface DemoBannerProps {
  onDemoComplete: () => void;
}

const DEMO_CLAIMS = [
  {
    patient_index: 4, // Sarah Kim (DHMO, 99% annual usage)
    cdt_code: 'D6010',
    charged_amount_cents: 350000,
    has_xray: false,
    has_narrative: false,
    has_perio_chart: false,
    label: 'High risk — implant, no documentation (DHMO)',
  },
  {
    patient_index: 1, // James Chen
    cdt_code: 'D2750',
    charged_amount_cents: 125000,
    has_xray: false,
    has_narrative: false,
    has_perio_chart: false,
    label: 'Medium risk — crown without X-ray',
  },
  {
    patient_index: 2, // Maria Garcia (PPO)
    cdt_code: 'D1110',
    charged_amount_cents: 12500,
    has_xray: true,
    has_narrative: false,
    has_perio_chart: false,
    label: 'Low risk — adult prophylaxis with X-ray (PPO)',
  },
];

export function DemoBanner({ onDemoComplete }: DemoBannerProps) {
  const [dismissed, setDismissed] = useState(false);
  const [running, setRunning] = useState(false);
  const [status, setStatus] = useState('');

  if (dismissed) return null;

  async function runDemo() {
    setRunning(true);
    try {
      const patients = await api.getPatients();
      for (let i = 0; i < DEMO_CLAIMS.length; i++) {
        const d = DEMO_CLAIMS[i];
        const patient = patients[d.patient_index];
        if (!patient) continue;
        setStatus(`Submitting ${i + 1}/${DEMO_CLAIMS.length}: ${d.label}`);
        await api.createClaim({
          idempotency_key: crypto.randomUUID(),
          patient_id: patient.id,
          cdt_code: d.cdt_code,
          procedure_date: new Date().toISOString().split('T')[0],
          charged_amount_cents: d.charged_amount_cents,
          has_xray: d.has_xray,
          has_narrative: d.has_narrative,
          has_perio_chart: d.has_perio_chart,
        });
        if (i < DEMO_CLAIMS.length - 1) {
          await new Promise(r => setTimeout(r, 500));
        }
      }
      setStatus('All 3 claims submitted — watch them get scored in real time below');
      onDemoComplete();
    } catch (e: any) {
      setStatus(`Error: ${e.message}`);
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="bg-teal-700 text-white px-4 py-3 flex items-center gap-4 text-sm">
      <div className="flex-1">
        <strong>DentalFlow Technical Demo</strong>
        <span className="hidden sm:inline"> — Async dental claims processing with ML-based denial prediction. Submit a claim and watch it move through the pipeline in real-time.</span>
        {status && <span className="ml-3 text-teal-200">{status}</span>}
      </div>
      <button
        onClick={runDemo}
        disabled={running}
        className="px-3 py-1.5 bg-white text-teal-700 font-medium rounded text-xs hover:bg-teal-50 disabled:opacity-50 whitespace-nowrap"
      >
        {running ? 'Running...' : 'Run Demo'}
      </button>
      <button
        onClick={() => setDismissed(true)}
        className="text-teal-200 hover:text-white text-lg leading-none"
        aria-label="Dismiss"
      >
        &times;
      </button>
    </div>
  );
}
