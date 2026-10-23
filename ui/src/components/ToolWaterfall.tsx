import { useTranslation } from 'react-i18next';
import { useAgentSpans, useFleetTelemetry, cacheFraction, totalTokens } from '@/hooks/useTelemetry';
const count = (n: number) => n < 1000 ? String(n) : n < 1000000 ? `${(n / 1000).toFixed(0)}K` : `${(n / 1000000).toFixed(1)}M`;
export function ToolWaterfall({ agentId }: { agentId: string }) {
  const history = useAgentSpans(agentId), usage = useFleetTelemetry().samples[agentId];
  const { t } = useTranslation();
  const peak = Math.max(1, ...history.map(span => span.durationMs));
  return <section style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0, background: 'var(--cth-paper-200)' }}>
    <header style={{ display: 'flex', flexWrap: 'wrap', gap: 14, padding: '8px 10px',
      background: 'var(--cth-cream-200)', borderBottom: '2px solid var(--cth-ink-900)', font: '12px var(--cth-font-mono)' }}>
      {usage ? <><strong>${usage.usd.toFixed(2)}</strong>
        <span>{t('toolWaterfall.fresh', { tokens: count(usage.input + usage.cacheCreation) })}</span>
        <span style={{ color: 'var(--cth-sky)' }}>{t('toolWaterfall.cache', { tokens: count(usage.cacheRead), pct: Math.round(cacheFraction(usage) * 100) })}</span>
        <span>{usage.model}</span><span>{t('toolWaterfall.total', { tokens: count(totalTokens(usage)) })}</span></> : t('toolWaterfall.noTelemetry')}
    </header>
    <div style={{ overflowY: 'auto', flex: 1, minHeight: 0, padding: 10 }}>
      {!history.length && <small>{t('toolWaterfall.empty')}</small>}
      {history.slice(-60).map((span, i) => {
        const good = span.success && span.tool !== 'api_error';
        return <div key={i} style={{ display: 'grid', gridTemplateColumns: '88px 1fr 54px 12px', gap: 8,
          alignItems: 'center', marginBottom: 3, fontSize: 11 }}>
          <span className="lab-ellipsis" title={span.error ?? span.tool}>{span.tool}</span>
          <div title={span.error ?? `${span.tool}: ${span.durationMs}ms`} style={{ height: 12, background: 'var(--cth-paper-100)',
            boxShadow: 'inset 0 0 0 1px var(--cth-ink-300)' }}>
            <div style={{ height: '100%', width: `${Math.max(2, span.durationMs / peak * 100)}%`,
              background: `var(--cth-${good ? 'mint' : 'coral'})` }} /></div>
          <span style={{ textAlign: 'right', fontFamily: 'var(--cth-font-mono)' }}>{span.durationMs >= 1000
            ? `${(span.durationMs / 1000).toFixed(1)}s` : `${Math.round(span.durationMs)}ms`}</span>
          <span style={{ color: `var(--cth-${good ? 'mint' : 'coral'})` }}>{good ? '✓' : '✗'}</span>
        </div>;
      })}
    </div>
  </section>;
}
