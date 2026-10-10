import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api, type RunDetail } from '@/api/client';
import { PixelPanel } from '@/components/PixelPanel';
import { Status } from './ui';
export function ArtifactViewer({ detail }: { detail: RunDetail }) {
  const { t } = useTranslation();
  const latest =
    detail.artifacts.filter((a) => a.kind === 'diff').at(-1)?.id ?? detail.artifacts.at(-1)?.id ?? '';
  const [selected, setSelected] = useState(latest);
  const [content, setContent] = useState('');
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setSelected(latest);
  }, [latest]);
  useEffect(() => {
    setContent('');
    setError(null);
    if (!selected) return;
    let alive = true;
    api
      .artifact(detail.run.id, selected)
      .then((a) => {
        if (alive) setContent(a.content);
      })
      .catch((e) => {
        if (alive) setError(String(e));
      });
    return () => {
      alive = false;
    };
  }, [detail.run.id, selected]);
  if (!detail.artifacts.length) return null;
  return (
    <PixelPanel title={t('lab.runArtifacts')}>
      <select
        aria-label={t('lab.runArtifacts')}
        value={selected}
        onChange={(e) => setSelected(e.target.value)}
        style={{ maxWidth: '100%' }}
      >
        {detail.artifacts.map((a, i) => (
          <option key={a.id} value={a.id}>
            {i + 1} · {a.kind} · {a.id}
          </option>
        ))}
      </select>
      <Status error={error} />
      <pre style={{ overflow: 'auto', maxHeight: 450, fontSize: 11, whiteSpace: 'pre' }}>{content}</pre>
    </PixelPanel>
  );
}
