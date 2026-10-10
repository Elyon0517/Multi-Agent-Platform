import { useEffect, useState } from 'react';
import { PixelPanel } from '@/components/PixelPanel';
import { api, type RunDetail } from '@/api/client';

interface Finding { severity: string; category: string; file: string; line: number | null; issue: string; confidence: number }
interface Verdict { reviewer_id: string; verdict: string; findings: Finding[] }

export function VerdictBoard({ detail }: { detail: RunDetail }) {
  const [verdicts, setVerdicts] = useState<Verdict[]>([]);
  const reviewIds = detail.artifacts.filter((a) => a.kind === 'review').slice(-3).map((a) => a.id).join(',');

  useEffect(() => {
    if (!reviewIds) return;
    void Promise.all(reviewIds.split(',').map((id) => api.artifact(detail.run.id, id)))
      .then((arts) => setVerdicts(arts.map((a) => JSON.parse(a.content) as Verdict)));
  }, [detail.run.id, reviewIds]);

  if (verdicts.length === 0) return null;
  return (
    <PixelPanel title="Review panel (latest round)">
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
