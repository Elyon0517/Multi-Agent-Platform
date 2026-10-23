import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useStore } from '@/store/store';
import { PixelButton } from './PixelButton';
export function OfficeThemePicker() {
  const theme = useStore(s => s.officeTheme), change = useStore(s => s.setOfficeTheme);
  const [enabled, setEnabled] = useState(theme !== 'studio');
  const [choice, setChoice] = useState(theme);
  const { t } = useTranslation();
  return <section><header style={{ font: '8px/12px var(--cth-font-display)', marginBottom: 10 }}>{t('officeTheme.title')}</header>
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
      <div><div style={{ fontSize: 13 }}>{t('officeTheme.originalThemes')} ({t('officeTheme.experimental')})</div>
        <small>{t('officeTheme.desc')}</small></div>
      <PixelButton size="sm" variant={enabled ? 'primary' : 'secondary'} onClick={() => {
        setEnabled(!enabled); change(enabled ? 'studio' : choice);
      }}>{t(enabled ? 'common.on' : 'common.off')}</PixelButton>
    </div>
    {enabled && <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 12 }}>
      {(['studio', 'atrium'] as const).map(id => <button type="button" key={id} aria-pressed={theme === id}
        onClick={() => { setChoice(id); change(id); }} style={{ padding: 8, display: 'flex', alignItems: 'center', gap: 8,
          border: `1px solid var(--cth-ink-${theme === id ? '500' : '300'})`,
          background: theme === id ? 'var(--cth-paper-100)' : 'transparent', textAlign: 'left', cursor: 'pointer' }}>
        <span aria-hidden style={{ display: 'block', width: 28, height: 28, flexShrink: 0,
          background: id === 'studio' ? '#ba8f68' : '#7cae94' }} />
        <span style={{ minWidth: 0 }}><strong style={{ fontSize: 12 }}>{id === 'studio' ? 'Studio' : 'Atrium'}</strong>
          {theme === id && <small style={{ color: 'var(--cth-mint)', marginLeft: 6 }}>{t('officeTheme.current')}</small>}
          <span className="lab-ellipsis" style={{ display: 'block', fontSize: 11 }}>
            {id === 'studio' ? 'A warm workspace for building together' : 'A green workspace with room to think'}</span></span>
      </button>)}
    </div>}
  </section>;
}
