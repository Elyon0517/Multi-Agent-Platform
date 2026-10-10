import { LANGUAGES, setLanguage } from '@/i18n';
import { useTranslation } from 'react-i18next';
import { useEffect, useState } from 'react';
import { api, type SettingView } from '@/api/client';
import { PixelPanel } from '@/components/PixelPanel';
import { PixelButton } from '@/components/PixelButton';
import { OfficeThemePicker } from '@/components/OfficeThemePicker';
import { Field, Status, errorText, inputStyle } from '@/views/ui';

const LABELS: Record<string, { label: string; hint: string; placeholder: string }> = {
  AGENTLAB_EMBEDDING_BASE_URL: { label: 'Embedding base URL', hint: 'Separate embedding endpoint; model is configured in models.yaml', placeholder: 'https://…/v1' },
  AGENTLAB_EMBEDDING_API_KEY: { label: 'Embedding API key', hint: 'Separate embedding credential', placeholder: 'paste a new key' },
  AGENTLAB_LLM_BASE_URL: { label: 'Gateway base URL', hint: 'OpenAI-compatible endpoint, e.g. https://gateway/v1',
    placeholder: 'https://…/v1' },
  AGENTLAB_LLM_API_KEY: { label: 'API key', hint: 'Saved to the local .env (chmod 600). Never sent back to the browser.',
    placeholder: 'paste a new key to replace' },
};

export function SettingsView() {
  const { t, i18n } = useTranslation();
  const [views, setViews] = useState<SettingView[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [reveal, setReveal] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  useEffect(() => { api.settings().then(setViews).catch((e) => setError(errorText(e))); }, []);

  const save = async () => {
    setError(null);
    setOk(null);
    const values = Object.fromEntries(Object.entries(drafts).filter(([, v]) => v.trim()));
    if (Object.keys(values).length === 0) return;
    try {
      setViews(await api.saveSettings(values));
      setDrafts({});
      setReveal(false);
      setOk(t('lab.savedNewRunsUseTheseValues'));
    } catch (e) {
      setError(errorText(e));
    }
  };

  return (
    <>
      <PixelPanel title={t('lab.language')}>
        <Field id="interface-language" label={t('lab.language')} hint={t('lab.languageHint')}>
          <select id="interface-language" style={inputStyle} value={i18n.resolvedLanguage ?? 'en'} onChange={(e) => setLanguage(e.target.value)}>
            {LANGUAGES.map((language) => <option key={language.code} value={language.code}>{language.label}</option>)}
          </select>
        </Field>
      </PixelPanel>
      <PixelPanel title={t('lab.llmGateway')}>
        <form onSubmit={(e) => { e.preventDefault(); void save(); }} autoComplete="off">
          {views.map((v) => {
            const meta = LABELS[v.key] ?? { label: v.key, hint: '', placeholder: '' };
            const id = `setting-${v.key}`;
            return (
              <Field key={v.key} id={id} label={v.key === 'AGENTLAB_LLM_BASE_URL' ? t('lab.gatewayBaseUrl') : v.key === 'AGENTLAB_LLM_API_KEY' ? t('lab.apiKey') : t(v.secret ? 'lab.embeddingApiKey' : 'lab.embeddingBaseUrl')}
                hint={`${v.key === 'AGENTLAB_LLM_BASE_URL' ? t('lab.openaiCompatibleEndpointEGHttpsGatewayV1') : v.secret ? t('lab.savedToTheLocalEnvChmod600NeverSentBackToTheBrowser') : t('lab.embeddingModelHint')} ${v.is_set ? t('lab.current', { value: v.display }) : t('lab.notSet')}`}>
                <input id={id} style={inputStyle} spellCheck={false} autoComplete="off"
                  type={v.secret && !reveal ? 'password' : 'text'}
                  placeholder={v.secret ? (v.is_set ? v.display : t('lab.pasteANewKeyToReplace')) : (v.display || meta.placeholder)}
                  value={drafts[v.key] ?? ''}
                  onChange={(e) => setDrafts((d) => ({ ...d, [v.key]: e.target.value }))} />
              </Field>
            );
          })}
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <PixelButton onClick={() => void save()}>{t('lab.save')}</PixelButton>
            <label style={{ fontSize: 12, display: 'flex', gap: 4, alignItems: 'center' }}>
              <input type="checkbox" checked={reveal} onChange={(e) => setReveal(e.target.checked)} />
              {t('lab.showWhatIMTyping')}
            </label>
          </div>
          <Status error={error} ok={ok} />
        </form>
      </PixelPanel>
      <PixelPanel title={t('lab.office')}>
        <OfficeThemePicker />
      </PixelPanel>
    </>
  );
}
