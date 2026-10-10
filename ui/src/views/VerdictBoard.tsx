import { useTranslation } from 'react-i18next';
import { useEffect, useState } from 'react';
import { PixelPanel } from '@/components/PixelPanel';
import { api, type RunDetail, type Verdict } from '@/api/client';

export function VerdictBoard({ detail }: { detail: RunDetail }) {
  const { t } = useTranslation();
  const [verdicts, setVerdicts] = useState<Verdict[]>([]);
  const reviewIds = detail.artifacts.filter((a) => a.kind === 'review').slice(-3).map((a) => a.id).join(',');

  useEffect(() => {
    setVerdicts([]);
    if (!reviewIds) return;
    let alive = true;
    void Promise.all(reviewIds.split(',').map((id) => api.artifact(detail.run.id, id)))
      .then((arts) => { if (alive) setVerdicts(arts.map((a) => JSON.parse(a.content) as Verdict)); }).catch(() => undefined);
    return () => { alive = false; };
  }, [detail.run.id, reviewIds]);

  if (verdicts.length === 0) return null;
  return (
    <PixelPanel title={t('lab.reviewPanelLatestRound')}>
      <div style={{ display: 'grid', gridTemplateColumns: `repeat(${verdicts.length}, 1fr)`, gap: 6 }}>
        {verdicts.map((v) => (
          <section key={v.reviewer_id} aria-label={v.reviewer_id}>
            <h3 style={{ fontSize: 10, margin: 0 }}>{v.reviewer_id}</h3>
            <p style={{ margin: '2px 0' }}><strong>{v.verdict}</strong></p>
            <ul style={{ paddingLeft: 14, margin: 0 }}>
              {v.findings.map((f, i) => (
                <li key={i}>[{f.severity}] {f.file}:{f.line ?? '-'} {f.issue} ({f.confidence})</li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </PixelPanel>
  );
}
