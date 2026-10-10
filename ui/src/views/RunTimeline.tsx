import { PixelPanel } from '@/components/PixelPanel';
import type { RunDetail } from '@/api/client';

export function RunTimeline({ detail }: { detail: RunDetail }) {
  const { run, steps } = detail;
  return (
    <PixelPanel title={`Run ${run.id} · ${run.status}`}>
      <p style={{ margin: '0 0 8px' }}>
        {run.goal} · {run.cost_cents.toFixed(2)} / {run.budget_cents.toFixed(0)}c · tokens {run.tokens_in + run.tokens_out}
        {run.paused_reason && <strong> · paused: {run.paused_reason}</strong>}
      </p>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--cth-font-mono)', fontSize: 11 }}>
        <thead>
          <tr><th scope="col">#</th><th scope="col">role</th><th scope="col">model</th>
            <th scope="col">cost</th><th scope="col">attempts</th></tr>
        </thead>
        <tbody>
          {steps.map((s) => (
            <tr key={s.id}>
              <td>{s.iteration_n}</td><td>{s.role}</td><td>{s.model}</td><td>{s.usage.cost_cents.toFixed(2)}</td>
              <td>{s.attempt_count}{s.retry_reasons.length > 0 && ` (${s.retry_reasons.join(',')})`}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </PixelPanel>
  );
}
