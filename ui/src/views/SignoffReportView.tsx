import { useTranslation } from 'react-i18next';
import type { SignoffReport } from '@/api/client';

export function SignoffReportView({ report }: { report: SignoffReport }) {
  const { t } = useTranslation();
  return (
    <section aria-label={t('lab.signoffGoalCriteria')} style={{ overflowWrap: 'anywhere' }}>
      <h4>{t('lab.signoffGoalCriteria')}</h4>
      <p style={{ whiteSpace: 'pre-wrap' }}>{report.goal}</p>
      <strong>{t('lab.signoffCriteria')}</strong>
      {report.acceptance_criteria.length ? <ul>{report.acceptance_criteria.map((criterion, i) =>
        <li key={i} style={{ whiteSpace: 'pre-wrap' }}>{criterion}</li>)}</ul> : <p>{t('lab.signoffNone')}</p>}
      <h4>{t('lab.signoffChecks')}</h4>
      <p role="status"><strong>{t(report.automated_checks === 'passed' ? 'lab.signoffFullPassed' : 'lab.untestedSignoff')}</strong></p>
      <h4>{t('lab.signoffFindings')}</h4>
      {report.findings.length ? <ul>{report.findings.map((finding, i) => <li key={i}>
        <span>{finding.severity} · {finding.file}{finding.line !== null ? `:${finding.line}` : ''} · {finding.reviewer_id}</span>
        <p style={{ whiteSpace: 'pre-wrap' }}>{finding.issue}</p>
      </li>)}</ul> : <p>{t('lab.signoffNone')}</p>}
    </section>
  );
}
