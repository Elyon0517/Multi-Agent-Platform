import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { usePoll } from '@/hooks/usePoll';
import { PixelPanel } from './PixelPanel';
import { PixelButton } from './PixelButton';
type Message = Awaited<ReturnType<Window['cth']['hiveInbox']>>[number];
export interface ThreadsPanelProps { agentId: string; }
export function conversationGroups(messages: Message[]): Message[][] {
  const groups = new Map<string, Message[]>();
  for (const message of messages) {
    const items = groups.get(message.conversation) ?? []; items.push(message); groups.set(message.conversation, items);
  }
  return [...groups.values()].map(group => group.sort((a, b) => a.created_at.localeCompare(b.created_at)))
    .sort((a, b) => b.at(-1)!.created_at.localeCompare(a.at(-1)!.created_at));
}
export function ThreadsPanel({ agentId }: ThreadsPanelProps) {
  const messages = usePoll(() => window.cth.hiveInbox(agentId), [] as Message[], 3000, agentId);
  const [closed, setClosed] = useState<Set<string>>(new Set()), [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [drafts, setDrafts] = useState<Record<string, string>>({}), [error, setError] = useState('');
  const [sending, setSending] = useState<string | null>(null);
  const { t } = useTranslation();
  const toggle = (values: Set<string>, value: string) => { const result = new Set(values); if (!result.delete(value)) result.add(value); return result; };
  const send = async (last: Message, key: string) => {
    const body = drafts[key]?.trim(); if (!body || sending) return;
    setSending(key); setError('');
    try {
      const result = await window.cth.hiveSend({ to: last.from, act: 'inform', conversation: last.conversation,
        in_reply_to: last.id, subject: `Re: ${last.subject}`, body }, 'human');
      if (!result.ok) setError(result.error ?? 'Reply failed');
      else setDrafts(current => ({ ...current, [key]: '' }));
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setSending(null); }
  };
  const groups = conversationGroups(messages);
  return <section style={{ flex: 1, minHeight: 0, overflowY: 'auto', background: 'var(--cth-paper-200)', padding: 12,
    display: 'flex', flexDirection: 'column', gap: 12 }}>
    {!groups.length && <p style={{ margin: 'auto', fontSize: 13, textAlign: 'center', maxWidth: 280 }}>{t('threads.empty')}</p>}
    {error && <div role="alert">{error}</div>}
    {groups.map(group => {
      const first = group[0], last = group.at(-1)!, key = `${agentId}:${first.conversation}`;
      return <PixelPanel key={key} noPadding>
        <button type="button" aria-expanded={!closed.has(key)} onClick={() => setClosed(toggle(closed, key))}
          style={{ display: 'flex', gap: 8, width: '100%', textAlign: 'start', padding: '6px 10px', border: 0,
            background: 'var(--cth-cream-200)', cursor: 'pointer', font: '8px/14px var(--cth-font-display)' }}>
          <span>{closed.has(key) ? '▸' : '▾'}</span><span className="lab-ellipsis" style={{ flex: 1 }}>
            {(first.subject || t('threads.noSubject')).toUpperCase()}</span><span>{group.length}</span></button>
        {!closed.has(key) && <div style={{ display: 'grid', gap: 8, padding: '8px 10px 10px 18px' }}>
          {group.map(message => <article key={message.id} style={{ borderLeft: '2px solid var(--cth-ink-100)', paddingLeft: 8 }}>
            <header style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
              <strong style={{ fontSize: 13 }}>{message.from}</strong><small>{message.act}</small>
              <time style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--cth-ink-500)' }}>{new Date(message.created_at).toLocaleString()}</time></header>
            <div dir="auto" style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', fontSize: 13, lineHeight: '18px' }}>
              {message.body.length > 120 && !expanded.has(message.id) ? `${message.body.slice(0,120)}…` : message.body}
              {message.body.length > 120 && <button type="button" onClick={() => setExpanded(toggle(expanded, message.id))}
                style={{ border: 0, background: 'transparent', color: 'var(--cth-sky)', fontSize: 12 }}>
                {t(expanded.has(message.id) ? 'threads.less' : 'threads.more')}</button>}</div>
          </article>)}
          <textarea rows={2} value={drafts[key] ?? ''} placeholder={t('threads.replyPlaceholder', { name: last.from })}
            onChange={event => setDrafts({ ...drafts, [key]: event.target.value })}
            style={{ width: '100%', resize: 'vertical', padding: '6px 8px', fontSize: 13, background: 'var(--cth-cream-50)' }} />
          <div style={{ display: 'flex', justifyContent: 'flex-end' }}><PixelButton size="sm"
            disabled={!!sending || !drafts[key]?.trim()} onClick={() => void send(last, key)}>{t('threads.send')}</PixelButton></div>
        </div>}
      </PixelPanel>;
    })}
  </section>;
}
