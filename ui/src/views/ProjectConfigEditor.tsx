import { useEffect, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api, type ModelCatalog, type ProjectSettings } from '@/api/client';
import { Field, Muted, inputStyle } from './ui';
export function ProjectConfigEditor({
  value,
  onChange,
}: {
  value: ProjectSettings | null;
  onChange: (value: ProjectSettings) => void;
}) {
  const { t } = useTranslation();
  const prefix = useId();
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let alive = true;
    api
      .models()
      .then((c) => {
        if (alive) setCatalog(c);
      })
      .catch((e) => {
        if (alive) setError(String(e));
      });
    return () => {
      alive = false;
    };
  }, []);
  useEffect(() => {
    if (catalog && !value)
      onChange({
        mode: 'auto',
        root_alias: catalog.root_alias,
        allowed_aliases: Object.keys(catalog.aliases),
        bindings: catalog.roles,
        budget_cents: 500,
        max_iter: 5,
        retrieval: 'hybrid',
        retrieval_k: 6,
        check_commands: [],
      });
  }, [catalog, value, onChange]);
  if (!catalog || !value) return <Muted>{error || '…'}</Muted>;
  const update = (patch: Partial<ProjectSettings>) => onChange({ ...value, ...patch });
  // The backend treats an empty list as the whole catalog, so show it that way.
  const allowed = value.allowed_aliases.length ? value.allowed_aliases : Object.keys(catalog.aliases);
  const modelSelect = (alias: string, change: (alias: string) => void, id: string) => (
    <select id={`${prefix}-${id}`} style={inputStyle} value={alias} onChange={(e) => change(e.target.value)}>
      {Object.entries(catalog.aliases).map(([a, c]) => (
        <option key={a} value={a}>
          {a} · {c.model}
        </option>
      ))}
    </select>
  );
  return (
    <fieldset style={{ border: '1px solid var(--cth-ink-100)', margin: '8px 0', padding: 8 }}>
      <legend>{t('lab.agentConfiguration')}</legend>
      <Field id={`${prefix}-dispatch-mode`} label={t('lab.dispatchMode')}>
        <select
          id={`${prefix}-dispatch-mode`}
          style={inputStyle}
          value={value.mode}
          onChange={(e) => update({ mode: e.target.value as ProjectSettings['mode'] })}
        >
          <option value="auto">{t('lab.autoDispatch')}</option>
          <option value="manual">{t('lab.manualDispatch')}</option>
        </select>
      </Field>
      <Field id={`${prefix}-root-model`} label={t('lab.rootModel')}>
        {modelSelect(value.root_alias, (root_alias) => update({ root_alias }), 'root-model')}
      </Field>
      {value.mode === 'auto' && (
        <Field id={`${prefix}-available-models`} label={t('lab.availableModels')}>
          <div id={`${prefix}-available-models`}>
            {Object.keys(catalog.aliases).map((alias) => (
              <label key={alias} style={{ display: 'block' }}>
                <input
                  type="checkbox"
                  disabled={allowed.length === 1 && allowed.includes(alias)}
                  checked={allowed.includes(alias)}
                  onChange={(e) =>
                    update({
                      allowed_aliases: e.target.checked
                        ? [...allowed, alias]
                        : allowed.filter((a) => a !== alias),
                    })
                  }
                />
                {alias} · {catalog.aliases[alias].model}
              </label>
            ))}
          </div>
        </Field>
      )}
      {value.mode === 'manual' &&
        Object.keys(catalog.roles).map((role) => (
          <div key={role} style={{ marginBottom: 8 }}>
            <Field id={`${prefix}-model-${role}`} label={role}>
              {modelSelect(
                value.bindings[role]?.alias ?? catalog.roles[role].alias,
                (alias) =>
                  update({ bindings: { ...value.bindings, [role]: { ...value.bindings[role], alias } } }),
                `model-${role}`,
              )}
            </Field>
            <textarea
              aria-label={t('lab.agentTask', { role })}
              rows={2}
              style={inputStyle}
              value={value.bindings[role]?.task ?? ''}
              onChange={(e) =>
                update({
                  bindings: { ...value.bindings, [role]: { ...value.bindings[role], task: e.target.value } },
                })
              }
            />
          </div>
        ))}
      <Field id={`${prefix}-project-budget`} label={t('lab.budgetCents')}>
        <input
          id={`${prefix}-project-budget`}
          type="number"
          min="1"
          style={inputStyle}
          value={value.budget_cents}
          onChange={(e) => update({ budget_cents: Number(e.target.value) })}
        />
      </Field>
      <Field id={`${prefix}-project-max-iter`} label={t('lab.maximumIterations')}>
        <input
          id={`${prefix}-project-max-iter`}
          type="number"
          min="1"
          max="50"
          style={inputStyle}
          value={value.max_iter}
          onChange={(e) => update({ max_iter: Number(e.target.value) })}
        />
      </Field>
      <Field id={`${prefix}-retrieval-mode`} label={t('lab.retrievalMode')}>
        <select
          id={`${prefix}-retrieval-mode`}
          style={inputStyle}
          value={value.retrieval}
          onChange={(e) => update({ retrieval: e.target.value as ProjectSettings['retrieval'] })}
        >
          <option value="off">{t('lab.retrievalOff')}</option>
          <option value="keyword">{t('lab.keywordRetrieval')}</option>
          <option value="hybrid">{t('lab.hybridRetrieval')}</option>
        </select>
      </Field>
      <Field id={`${prefix}-retrieval-k`} label={t('lab.retrievalLimit')}>
        <input
          id={`${prefix}-retrieval-k`}
          type="number"
          min="1"
          max="20"
          style={inputStyle}
          value={value.retrieval_k}
          onChange={(e) => update({ retrieval_k: Number(e.target.value) })}
        />
      </Field>
      <Field id={`${prefix}-check-commands`} label={t('lab.checkCommands')} hint={t('lab.checkCommandsHint')}>
        <textarea
          id={`${prefix}-check-commands`}
          rows={3}
          style={{ ...inputStyle, fontFamily: 'var(--cth-font-mono)' }}
          placeholder={'npm run typecheck\nnpm test -- --run'}
          value={(value.check_commands ?? []).join('\n')}
          onChange={(e) => update({ check_commands: e.target.value.split('\n').map((c) => c.trim()).filter(Boolean).slice(0, 10) })}
        />
      </Field>
      <Muted>{t('lab.configurationFrozen')}</Muted>
      {new Set(Object.values(catalog.aliases).map((c) => c.model)).size === 1 && (
        <Muted>{t('lab.sameModelNotice')}</Muted>
      )}
    </fieldset>
  );
}
