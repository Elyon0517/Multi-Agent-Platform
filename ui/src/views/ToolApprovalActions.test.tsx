import { expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { I18nextProvider } from 'react-i18next';
import i18next from 'i18next';
import en from '@/i18n/locales/en.json';
import type { ToolApproval } from '@/api/client';
import { ToolApprovalActions } from './ToolApprovalActions';

const translation = i18next.createInstance();
void translation.init({ lng: 'en', resources: { en: { translation: en } }, initAsync: false });
const render = (status: ToolApproval['status'] | undefined) => renderToStaticMarkup(
  <I18nextProvider i18n={translation}><ToolApprovalActions status={status} busy={false} onDecision={() => undefined} /></I18nextProvider>,
);

it('only offers execution for a pending approval', () => {
  expect(render('pending')).toContain(en.lab.allowTool);
  for (const status of ['executing', 'done', 'failed', 'denied', 'confirmed_done', 'closed_unknown'] as const) {
    expect(render(status)).not.toContain('<button');
  }
  expect(render(undefined)).not.toContain('<button');
});

it('lets a user reconcile an unknown outcome without offering replay', () => {
  const html = render('unknown_outcome');
  expect(html).toContain(en.lab.toolConfirmDone);
  expect(html).toContain(en.lab.toolCloseUnknown);
  expect(html).not.toContain(en.lab.allowTool);
  expect(html).not.toContain(en.lab.denyTool);
});
