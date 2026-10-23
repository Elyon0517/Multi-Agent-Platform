import { describe, expect, it } from 'vitest';

describe('current UI source distribution', () => {
  it('contains neither retired source modules nor inherited-source headers', () => {
    const files = import.meta.glob('./**/*.{ts,tsx,css}',{ eager: true, query: '?raw', import: 'default' });
    const paths = Object.keys(files);
    for (const file of ['SeatPool.ts','SpriteAdapter.ts','AskMeTab.tsx','MemoryGraphPanel.tsx','theme.ts'])
      expect(paths.some(path => path.endsWith(`/${file}`)),file).toBe(false);
    for (const [path,text] of Object.entries(files)) if (!path.includes('.test.'))
      expect(text,path).not.toMatch(/munder[- ]difflin|chaitanyagiri|shahar061|ported (?:verbatim )?from|the-office/i);
  });
  it('ships the original asset and font records without obsolete renderer attribution', () => {
    const records = import.meta.glob(['./assets/ATTRIBUTION.md','../THIRD_PARTY_NOTICES.md'],
      { eager: true, query: '?raw', import: 'default' });
    expect(Object.keys(records)).toHaveLength(2);
    for (const text of Object.values(records)) {
      expect(text).not.toMatch(/munder-difflin|the-office|shahar061|Chaitanya Giri/i);
      expect(text).toContain('SIL OFL');
    }
  });
});
