import { useTypewriter } from '@/hooks/useTypewriter';
import type { AccentColorName } from '@/design/tokens';
export interface RecentTextProps { accent: AccentColorName; text: string; seed: number | undefined; }
export function RecentText({ accent, text, seed }: RecentTextProps) {
  const reveal = useTypewriter(text, seed);
  if (!text) return null;
  return <section style={{ background: 'var(--cth-cream-50)', borderLeft: `4px solid var(--cth-${accent})`,
    boxShadow: 'inset 0 0 0 1px var(--cth-ink-100)', padding: '8px 10px 8px 12px' }}>
    <header style={{ display: 'flex', justifyContent: 'space-between', font: '8px/12px var(--cth-font-display)',
      color: 'var(--cth-ink-700)', textTransform: 'uppercase', marginBottom: 4 }}>
      <span>recent</span><span>{reveal.done ? 'idle' : 'live'}</span>
    </header>
    <div style={{ minHeight: 36, fontSize: 13, lineHeight: '18px' }}>{reveal.shown}
      {!reveal.done && <span aria-hidden style={{ display: 'inline-block', width: 7, height: 14,
        marginLeft: 2, background: 'currentColor', animation: 'cth-blink 700ms steps(2) infinite' }} />}
    </div>
  </section>;
}
