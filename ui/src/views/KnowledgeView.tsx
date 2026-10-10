import { useTranslation } from 'react-i18next';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, type DocumentSummary, type MemoryHit, type MemoryItem, type MemoryScope, type MemoryStats } from '@/api/client';
import { PixelPanel } from '@/components/PixelPanel';
import { PixelButton } from '@/components/PixelButton';
import { useStore } from '@/store/store';
import { Field, Muted, Status, errorText, inputStyle } from '@/views/ui';

const ACCEPT = '.pdf,.md,.markdown,.txt';

function GlobalDocuments({ onChange }: { onChange: () => void }) {
  const { t } = useTranslation();
  const [docs, setDocs] = useState<DocumentSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const refresh = useCallback(() => { api.documents().then(setDocs).catch((e) => setError(errorText(e))); }, []);
  useEffect(refresh, [refresh]);

  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true);
    setError(null);
    setOk(null);
    try {
      for (const f of Array.from(files)) {
        const d = await api.uploadDocument(f);
        setOk(t('lab.indexed', { source: d.source, count: d.chunks }));
      }
      refresh();
      onChange();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
      if (input.current) input.current.value = '';
    }
  };

  const remove = async (source: string) => {
    await api.deleteDocument(source);
    refresh();
    onChange();
  };

  return (
    <PixelPanel title={t('lab.globalKnowledgeAllAgents')}>
      <Muted>{t('lab.resumeBackgroundPreferencesPdfMarkdownTextSplitIntoChunksAndEmbeddedForRag')}</Muted>
      <Field id="kb-upload" label={t('lab.uploadDocuments')}>
        <input id="kb-upload" ref={input} type="file" accept={ACCEPT} multiple disabled={busy}
          onChange={(e) => void upload(e.target.files)} />
      </Field>
      <Status error={error} ok={busy ? t('lab.indexing') : ok} />
      <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {docs.map((d) => (
          <li key={d.source} style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12, padding: '2px 0' }}>
            <span style={{ flex: 1 }}>{d.source}</span>
            <span style={{ color: 'var(--cth-ink-500)' }}>{t('lab.chunks', { count: d.chunks, chars: Math.round(d.chars / 1000) })}</span>
            <PixelButton size="sm" variant="secondary" onClick={() => void remove(d.source)}>{t('lab.remove')}</PixelButton>
          </li>
        ))}
      </ul>
      {docs.length === 0 && <Muted>{t('lab.noDocumentsYet')}</Muted>}
    </PixelPanel>
  );
}

function MemoryList({ scope, role, projectId, version }: {
  scope: MemoryScope; role?: string; projectId?: string; version: number;
}) {
  const { t } = useTranslation();
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [text, setText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(() => {
    api.memory(scope, { role, projectId }).then(setItems).catch((e) => setError(errorText(e)));
  }, [scope, role, projectId]);
  useEffect(refresh, [refresh, version]);

  const add = async () => {
    if (!text.trim()) return;
    try {
      await api.addMemory({ scope, text: text.trim(), role, project_id: projectId });
      setText('');
      refresh();
    } catch (e) {
      setError(errorText(e));
    }
  };

  const id = `mem-add-${scope}`;
  return (
    <div>
      {items.length === 0 && <Muted>{t('lab.empty')}</Muted>}
      <ul style={{ listStyle: 'none', margin: 0, padding: 0, maxHeight: 180, overflow: 'auto' }}>
        {items.filter((i) => i.kind !== 'document').map((i) => (
          <li key={i.id} style={{ fontSize: 12, padding: '3px 0', borderBottom: '1px dashed var(--cth-ink-100)' }}>
            <span style={{ color: 'var(--cth-ink-500)' }}>[{i.kind}] </span>{i.text}
          </li>
        ))}
      </ul>
      <form onSubmit={(e) => { e.preventDefault(); void add(); }} style={{ display: 'flex', gap: 6, marginTop: 6 }}>
        <label htmlFor={id} style={{ position: 'absolute', left: -9999 }}>{t('lab.addNote')}</label>
        <input id={id} style={inputStyle} value={text} placeholder={t('lab.addANote')} onChange={(e) => setText(e.target.value)} />
        <PixelButton size="sm" onClick={() => void add()}>{t('lab.add')}</PixelButton>
      </form>
      <Status error={error} />
    </div>
  );
}

function SearchBox({ projectId }: { projectId?: string }) {
  const { t } = useTranslation();
  const agents = useStore((s) => s.agents);
  const [query, setQuery] = useState('');
  const [role, setRole] = useState('coder');
  const [hits, setHits] = useState<MemoryHit[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    if (!query.trim()) return;
    try {
      setHits(await api.searchMemory({ query, role, project_id: projectId }));
    } catch (e) {
      setError(errorText(e));
    }
  };

  return (
    <PixelPanel title={t('lab.testRetrieval')}>
      <Muted>{t('lab.seeExactlyWhatAnAgentWouldGetInjectedForAQuery')}</Muted>
      <form onSubmit={(e) => { e.preventDefault(); void run(); }} style={{ display: 'flex', gap: 6 }}>
        <label htmlFor="mem-role" style={{ position: 'absolute', left: -9999 }}>{t('lab.asAgent')}</label>
        <select id="mem-role" value={role} onChange={(e) => setRole(e.target.value)} style={{ ...inputStyle, width: 150 }}>
          {agents.filter((a) => a.id !== 'gate').map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
        <label htmlFor="mem-q" style={{ position: 'absolute', left: -9999 }}>{t('lab.query')}</label>
        <input id="mem-q" style={inputStyle} value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('lab.query')} />
        <PixelButton size="sm" onClick={() => void run()}>{t('lab.search')}</PixelButton>
      </form>
      <Status error={error} />
      {hits && hits.length === 0 && <Muted>{t('lab.nothingMatched')}</Muted>}
      <ol style={{ margin: '6px 0 0', paddingLeft: 18 }}>
        {hits?.map((h) => (
          <li key={h.item.id} style={{ fontSize: 12, marginBottom: 4 }}>
            <span style={{ color: 'var(--cth-ink-500)' }}>{h.item.namespace} · {h.item.source || h.item.kind} · {h.score.toFixed(3)}</span>
            <div style={{ whiteSpace: 'pre-wrap' }}>{h.item.text.slice(0, 300)}</div>
          </li>
        ))}
      </ol>
    </PixelPanel>
  );
}

export function KnowledgeView() {
  const { t } = useTranslation();
  const projectId = useStore((s) => s.activeProjectId) ?? undefined;
  const selected = useStore((s) => s.selectedId);
  const agents = useStore((s) => s.agents);
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [version, setVersion] = useState(0);
  const role = selected && selected !== 'gate' ? selected : 'coder';
  const bump = () => setVersion((v) => v + 1);

  useEffect(() => { api.memoryStats().then(setStats).catch(() => undefined); }, [version]);

  return (
    <>
      <PixelPanel title={t('lab.memoryStatus')}>
        <Muted>
          {stats ? t('lab.stats', { count: stats.items, embedded: stats.embedded, model: stats.embedding_model ?? t('lab.noEmbedder') }) + ' · '
            + (stats.embedding_ready ? t('lab.vectorSearchOn') : t('lab.keywordSearchOnlySetGatewayInSettings')) : '…'}
        </Muted>
      </PixelPanel>
      <GlobalDocuments onChange={bump} />
      <PixelPanel title={projectId ? t('lab.projectMemory') : t('lab.projectMemorySelectAProjectFirst')}>
        {projectId ? <MemoryList scope="project" projectId={projectId} version={version} /> : <Muted>—</Muted>}
      </PixelPanel>
      <PixelPanel title={t('lab.agentMemory', { name: agents.find((a) => a.id === role)?.name ?? role })}>
        <Muted>{t('lab.clickAnAvatarOrCardToSwitchAgent')}</Muted>
        <MemoryList scope="agent" role={role} projectId={projectId} version={version} />
      </PixelPanel>
      <SearchBox projectId={projectId} />
    </>
  );
}
