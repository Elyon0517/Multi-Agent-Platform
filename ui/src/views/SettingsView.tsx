import { LANGUAGES, setLanguage } from '@/i18n';
import { useTranslation } from 'react-i18next';
import { useEffect, useState } from 'react';
import { api, type RuntimeChoice, type SettingView } from '@/api/client';
import { PixelPanel } from '@/components/PixelPanel';
import { PixelButton } from '@/components/PixelButton';
import { OfficeThemePicker } from '@/components/OfficeThemePicker';
import { Field, Status, errorText, inputStyle } from '@/views/ui';

// i18n keys for each gateway setting; secret keys share the .env storage hint.
const FIELDS: Record<string, { label: string; hint: string }> = {
  AGENTLAB_LLM_BASE_URL: { label: 'lab.gatewayBaseUrl', hint: 'lab.openaiCompatibleEndpointEGHttpsGatewayV1' },
  AGENTLAB_LLM_API_KEY: { label: 'lab.apiKey', hint: 'lab.savedToTheLocalEnvChmod600NeverSentBackToTheBrowser' },
  AGENTLAB_EMBEDDING_BASE_URL: { label: 'lab.embeddingBaseUrl', hint: 'lab.embeddingModelHint' },
  AGENTLAB_EMBEDDING_API_KEY: { label: 'lab.embeddingApiKey', hint: 'lab.savedToTheLocalEnvChmod600NeverSentBackToTheBrowser' },
  AGENTLAB_ANTHROPIC_BASE_URL: { label: 'lab.anthropicBaseUrl', hint: 'lab.anthropicBaseUrlHint' },
  AGENTLAB_ANTHROPIC_API_KEY: { label: 'lab.anthropicApiKey', hint: 'lab.savedToTheLocalEnvChmod600NeverSentBackToTheBrowser' },
};

// Base URL then key, per provider; unknown keys go last.
const order = (key: string) => { const i = Object.keys(FIELDS).indexOf(key); return i < 0 ? Infinity : i; };

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
          {[...views].sort((a, b) => order(a.key) - order(b.key)).map((v) => {
            const field = FIELDS[v.key];
            const id = `setting-${v.key}`;
            return (
              <Field key={v.key} id={id} label={field ? t(field.label) : v.key}
                hint={`${field ? t(field.hint) : ''} ${v.is_set ? t('lab.current', { value: v.display }) : t('lab.notSet')}`}>
                <input id={id} style={inputStyle} spellCheck={false} autoComplete="off"
                  type={v.secret && !reveal ? 'password' : 'text'}
                  placeholder={v.secret ? (v.is_set ? v.display : t('lab.pasteANewKeyToReplace')) : (v.display || 'https://…/v1')}
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
      <AgentRuntime />
      <PixelPanel title={t('lab.office')}>
        <OfficeThemePicker />
      </PixelPanel>
      <McpStatus />
    </>
  );
}

/** Google ADK runs each agent under the same Driver, gateway and budget; applies to new runs and Root turns. */
function AgentRuntime() {
  const { t } = useTranslation();
  const [choice, setChoice] = useState<RuntimeChoice | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  useEffect(() => { api.runtimeChoice().then(setChoice).catch((e) => setError(errorText(e))); }, []);

  const toggle = async (useAdk: boolean) => {
    setError(null);
    setOk(null);
    try {
      setChoice(await api.saveRuntime(useAdk ? 'adk' : 'raw'));
      setOk(t('lab.savedNewRunsUseTheseValues'));
    } catch (e) {
      setError(errorText(e));
    }
  };

  return (
    <PixelPanel title={t('lab.agentRuntime')}>
      <label style={{ fontSize: 12, display: 'flex', gap: 6, alignItems: 'center' }}>
        <input type="checkbox" checked={choice?.runtime === 'adk'}
          disabled={!choice || (!choice.adk_installed && choice.runtime !== 'adk')}
          onChange={(e) => void toggle(e.target.checked)} />
        {t('lab.useGoogleAdk')}
      </label>
      <p style={{ fontSize: 11, margin: '6px 0 0', color: 'var(--cth-ink-500)' }}>
        {choice && !choice.adk_installed ? t('lab.adkNotInstalled') : t('lab.adkHint')}
      </p>
      <Status error={error} ok={ok} />
    </PixelPanel>
  );
}

/** External MCP tool servers (config/mcp.yaml). They start the first time Root or the planner needs them. */
function McpStatus() {
  const { t } = useTranslation();
  const [servers, setServers] = useState<Awaited<ReturnType<typeof api.mcpStatus>>>([]);
  useEffect(() => { api.mcpStatus().then(setServers).catch(() => setServers([])); }, []);
  return (
    <PixelPanel title={t('lab.mcpServers')}>
      <p style={{ fontSize: 12, margin: '0 0 6px' }}>{t('lab.mcpHint')}</p>
      <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12 }}>
        {servers.map((s) => (
          <li key={s.name}>
            <strong>{s.name}</strong> · {s.roles.join(', ')} · {s.error ? `${t('lab.mcpError')}: ${s.error}`
              : s.running ? t('lab.mcpRunning', { count: s.tools }) : t('lab.mcpIdle')}
          </li>
        ))}
      </ul>
    </PixelPanel>
  );
}
