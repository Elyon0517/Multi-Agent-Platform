import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { I18nextProvider } from 'react-i18next';
import i18next from 'i18next';
import en from '@/i18n/locales/en.json';
import { GateDiagnostics } from './GateDiagnostics';
import { ApprovalBar } from './ApprovalBar';
import type { Approval, GateResult, RunDetail } from '@/api/client';

const translation = i18next.createInstance();
void translation.init({ lng: 'en', resources: { en: { translation: en } }, initAsync: false });
const render = (content: React.ReactNode) => renderToStaticMarkup(<I18nextProvider i18n={translation}>{content}</I18nextProvider>);

describe('objective check evidence', () => {
  it('shows file/line, diagnostic code and escaped error output', () => {
    const report: GateResult = { language: 'python', mode: 'fast', passed: false, failed_at: 'lint', steps: [{
      name: 'lint', passed: false, exit_code: 1, duration_ms: 2, truncated_log_ref: null,
      log_tail: '<script>unsafe()</script>',
      diagnostics: [{ file: 'module.py', line: 12, col: 3, code: 'F821', message: 'Undefined variable' }],
    }] };
    const html = render(<GateDiagnostics reports={[report]} />);
    expect(html).toContain('module.py:12:3');
    expect(html).toContain('F821');
    expect(html).toContain('Undefined variable');
    expect(html).toContain('&lt;script&gt;');
    expect(html).not.toContain('<script>');
  });
  it('renders nothing instead of crashing when an older backend omits gate reports', () => {
    expect(render(<GateDiagnostics reports={undefined} />)).toBe('');
  });
  it('explicitly labels signoff without automatic checks', () => {
    const approval: Approval = { id: 'a', run_id: 'r', reason: 'signoff', status: 'pending',
      on_approve: 'DONE', report: null, decided_by: null, feedback: null, decided_at: null,
      payload: { automated_checks: 'not_run' } };
    expect(render(<ApprovalBar runId="r" approval={approval} />)).toContain('No automated tests were run');
    expect(render(<ApprovalBar runId="r" approval={{ ...approval, payload: { automated_checks: 'passed' } }} />))
      .not.toContain('No automated tests were run');
  });
});

it('renders the saved signoff evidence and escapes goals and findings', () => {
  const approval: Approval = { id: 'a', run_id: 'r', reason: 'signoff', status: 'pending',
    on_approve: 'DONE', decided_by: null, feedback: null, decided_at: null,
    payload: { automated_checks: 'passed' }, report: {
      goal: '<script>goal</script>', acceptance_criteria: ['Preserve public API'], automated_checks: 'passed',
      findings: [{ severity: 'minor', category: 'arch', file: 'calc.py', line: 1,
        issue: '<script>document types</script>', confidence: 0.9, reviewer_id: 'arch-reviewer', subject: '', suggestion: '', stance: null }],
    } };
  const html = render(<ApprovalBar runId="r" approval={approval} />);
  expect(html).toContain('Task goal and acceptance criteria');
  expect(html).toContain('Preserve public API');
  expect(html).toContain('FULL Gate passed');
  expect(html).toContain('Unresolved findings');
  expect(html).toContain('calc.py:1');
  expect(html).toContain('arch-reviewer');
  expect(html).toContain('&lt;script&gt;document types');
  expect(html).not.toContain('<script>');
  const untested = render(<ApprovalBar runId="r" approval={{ ...approval, report: {
    ...approval.report!, automated_checks: 'not_run', findings: [],
  } }} />);
  expect(untested).toContain('No automated tests were run');
  expect(untested).toContain('None');
  expect(untested).not.toContain('FULL Gate passed');
});

it('explains an oscillation pause and lists the open findings instead of fingerprints', () => {
  const approval: Approval = { id: 'a', run_id: 'r', reason: 'oscillation_detected', status: 'pending',
    on_approve: 'CODING', report: null, decided_by: null, feedback: null, decided_at: null,
    payload: { finding_set: ['086f2c18c3de0196'] } };
  const detail = { iterations: [{ verdicts: [{ reviewer_id: 'arch-reviewer@x', verdict: 'BLOCK', findings: [
    { severity: 'blocking', file: 'src/panel.tsx', line: 12, issue: 'Adapter is not wired into the panel' },
    { severity: 'nit', file: 'src/panel.tsx', line: 3, issue: 'naming' },
  ] }] }] } as unknown as RunDetail;
  const html = render(<ApprovalBar runId="r" approval={approval} detail={detail} />);
  expect(html).toContain('going in circles');
  expect(html).toContain('Adapter is not wired into the panel');
  expect(html).not.toContain('naming');
  expect(html).not.toContain('086f2c18c3de0196');
});

it('prefills a higher iteration limit so Approve can continue past the limit', () => {
  const approval: Approval = { id: 'a', run_id: 'r', reason: 'max_iter_exceeded', status: 'pending',
    on_approve: 'CODING', report: null, decided_by: null, feedback: null, decided_at: null, payload: {} };
  const detail = { run: { max_iter: 5 }, iterations: [] } as unknown as RunDetail;
  expect(render(<ApprovalBar runId="r" approval={approval} detail={detail} />)).toContain('value="10"');
  const capped = { run: { max_iter: 40 }, iterations: [] } as unknown as RunDetail;
  expect(render(<ApprovalBar runId="r" approval={approval} detail={capped} />)).toContain('value="50"');
});
