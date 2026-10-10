import { useState } from 'react';
import { PixelPanel } from '@/components/PixelPanel';
import { PixelButton } from '@/components/PixelButton';
import { PixelBadge } from '@/components/PixelBadge';
import { SpritePortrait } from '@/components/SpritePortrait';
import { RecentText } from '@/components/RecentText';
import { ToolWaterfall } from '@/components/ToolWaterfall';
import { ThreadsPanel } from '@/components/ThreadsPanel';
import { useStore } from '@/store/store';

type Tab = 'activity' | 'tools' | 'messages';

export function AgentDetail() {
  const agent = useStore((s) => s.agents.find((a) => a.id === s.selectedId));
  const select = useStore((s) => s.select);
  const [tab, setTab] = useState<Tab>('activity');
  if (!agent) return null;

  return (
    <PixelPanel title={agent.name} accent={agent.accent}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
        <SpritePortrait character={agent.character} scale={3} />
        <div style={{ flex: 1, minWidth: 0, fontSize: 12 }}>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <PixelBadge status={agent.status} />
            <span style={{ color: 'var(--cth-ink-500)' }}>{agent.project}</span>
          </div>
          <p style={{ margin: '4px 0' }}>{agent.description}</p>
          {agent.action && <p style={{ margin: 0, color: 'var(--cth-ink-500)' }}>{agent.action}</p>}
        </div>
        <PixelButton size="sm" variant="secondary" onClick={() => select(null)}>close</PixelButton>
      </div>
      <nav role="tablist" aria-label="Agent detail" style={{ display: 'flex', gap: 4, margin: '8px 0' }}>
        {(['activity', 'tools', 'messages'] as const).map((t) => (
          <PixelButton key={t} size="sm" variant={t === tab ? 'primary' : 'secondary'} onClick={() => setTab(t)}>{t}</PixelButton>
        ))}
      </nav>
      {tab === 'activity' && (agent.recentText
        ? <RecentText accent={agent.accent} text={agent.recentText} seed={agent.recentSeq ?? 0} />
        : <p style={{ fontSize: 12, color: 'var(--cth-ink-500)' }}>No output yet in this run.</p>)}
      {tab === 'tools' && <ToolWaterfall agentId={agent.id} />}
      {tab === 'messages' && <div style={{ display: 'flex', minHeight: 200 }}><ThreadsPanel agentId={agent.id} /></div>}
    </PixelPanel>
  );
}
