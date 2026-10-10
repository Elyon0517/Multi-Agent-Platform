import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { I18nextProvider } from 'react-i18next';
import i18next from 'i18next';
import en from '@/i18n/locales/en.json';
import { GateDiagnostics } from './GateDiagnostics';
import { ApprovalBar } from './ApprovalBar';
import type { Approval, GateResult } from '@/api/client';

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
  it('explicitly labels signoff without automatic checks', () => {
    const approval: Approval = { id: 'a', run_id: 'r', reason: 'signoff', status: 'pending',
      on_approve: 'DONE', decided_by: null, feedback: null, decided_at: null,
      payload: { automated_checks: 'not_run' } };
    expect(render(<ApprovalBar runId="r" approval={approval} />)).toContain('No automated tests were run');
    expect(render(<ApprovalBar runId="r" approval={{ ...approval, payload: { automated_checks: 'passed' } }} />))
      .not.toContain('No automated tests were run');
  });
});
