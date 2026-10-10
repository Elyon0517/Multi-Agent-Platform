import { Fragment, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api, type MonitorUsage, type UsageSummary } from '@/api/client';
import { PixelPanel } from '@/components/PixelPanel';
import { Status, errorText } from '@/views/ui';
import './MonitorView.css';

export function MonitorView() {
  const { t, i18n } = useTranslation();
  const [data, setData] = useState<MonitorUsage | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      try {
        const next = await api.monitorUsage();
        if (alive) { setData(next); setError(null); }
      } catch (e) { if (alive) setError(errorText(e)); }
      // Detect work in other projects too, while this tab remains open.
      if (alive) timer = setTimeout(() => void refresh(), 3000);
    };
    void refresh();
    return () => { alive = false; clearTimeout(timer); };
  }, []);
  const count = (n: number) => n.toLocaleString(i18n.resolvedLanguage);
  const money = (cents: number) => new Intl.NumberFormat(i18n.resolvedLanguage, {
    style: 'currency', currency: 'USD', minimumFractionDigits: 4, maximumFractionDigits: 4,
  }).format(cents / 100);
  const max = Math.max(1, ...(data?.agents.map(r => r.total_tokens) ?? []));
  const aggregate = (r: UsageSummary, label: string) => <tr key={r.role}>
    <th scope="row">{label}</th><td>{count(r.calls)}</td>
    <td>{count(r.total_tokens)}</td><td>{money(r.cost_cents)}</td>
  </tr>;
  return <PixelPanel title={t('lab.monitor')} className="usage-monitor">
    <p className="usage-description">{t('monitor.description')}</p>
    <Status error={error} />
    {!data && !error && <p>{t('monitor.loading')}</p>}
    {data && <>
      <div className="usage-summary">
        <div className="usage-stat"><span>{t('monitor.totalRequests')}</span>
          <strong>{count(data.total.calls)}</strong><small>{t('monitor.allProjects')}</small></div>
        <div className="usage-stat"><span>{t('monitor.totalTokens')}</span>
          <strong>{count(data.total.total_tokens)}</strong>
          <small>{t('monitor.input')}: {count(data.total.tokens_in)} · {t('monitor.output')}: {count(data.total.tokens_out)}</small></div>
        <div className="usage-stat"><span>{t('monitor.totalCost')}</span>
          <strong>{money(data.total.cost_cents)}</strong><small>{t('monitor.estimatedCost')}</small></div>
        <div className="usage-stat"><span>{t('monitor.unmetered')}</span>
          <strong>{count(data.total.unmetered_calls)}</strong><small>{t('monitor.unmeteredHint')}</small></div>
      </div>
      <h3>{t('monitor.byAgent')}</h3>
      <table className="usage-table">
        <thead><tr>{['agent', 'calls', 'totalTokens', 'cost'].map(k =>
          <th key={k} scope="col">{t(`monitor.${k}`)}</th>)}</tr></thead>
        <tbody>{data.agents.map(r => <Fragment key={r.role}>
          <tr className="usage-agent"><th scope="row">{r.role}</th><td>{count(r.calls)}</td>
            <td>{count(r.total_tokens)}</td><td>{money(r.cost_cents)}</td></tr>
          <tr className="usage-agent-detail"><td colSpan={4}>
            <div className="usage-bar" aria-label={`${r.role}: ${count(r.total_tokens)} token`}>
              <div style={{ width: `${100 * r.total_tokens / max}%` }} />
            </div>
            <div>{t('monitor.input')}: {count(r.tokens_in)} · {t('monitor.output')}: {count(r.tokens_out)}
              {r.unmetered_calls > 0 && <> · {t('monitor.unmetered')}: {count(r.unmetered_calls)}</>}</div>
            {r.models.length > 0 && <div className="usage-models">{t('monitor.models')}: {r.models.join(', ')}</div>}
          </td></tr>
        </Fragment>)}</tbody>
        <tfoot>{aggregate(data.reviewers, t('monitor.reviewers'))}{aggregate(data.total, t('monitor.grandTotal'))}</tfoot>
      </table>
    </>}
  </PixelPanel>;
}
