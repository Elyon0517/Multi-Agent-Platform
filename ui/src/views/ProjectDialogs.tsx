import { useTranslation } from 'react-i18next';
import { useEffect, useState } from 'react';
import { api, type Project, type ProjectSettings } from '@/api/client';
import { PixelPanel } from '@/components/PixelPanel';
import { PixelButton } from '@/components/PixelButton';
import { useStore } from '@/store/store';
import { Field, Muted, Status, errorText, inputStyle } from '@/views/ui';
import { ProjectConfigEditor } from './ProjectConfigEditor';
import { Modal } from './Modal';

function NewProjectForm({ runtime, onCreated }: { runtime?: string; onCreated: (p: Project) => void }) {
  const { t } = useTranslation();
  const [settings, setSettings] = useState<ProjectSettings | null>(null);
  const [name, setName] = useState('');
  const [goal, setGoal] = useState('');
  const [workspace, setWorkspace] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [picking, setPicking] = useState(false);
  const pickFolder = async () => {
    setPicking(true); setError(null);
    try {
      const { path } = await api.pickFolder();
      if (path) setWorkspace(path);
    } catch (e) { setError(String(e)); }
    finally { setPicking(false); }
  };

  const create = async () => {
    if (!name.trim() || !goal.trim() || !workspace.trim()) { setError(t('lab.nameGoalAndWorkspaceAreRequired')); return; }
    setBusy(true);
    setError(null);
    try {
      onCreated(await api.createProject({ name, goal, workspace, runtime, settings: settings ?? undefined }));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={(e) => { e.preventDefault(); void create(); }}>
      <Field id="p-name" label={t('lab.name')}><input id="p-name" style={inputStyle} value={name} onChange={(e) => setName(e.target.value)} /></Field>
      <Field id="p-goal" label={t('lab.goal')} hint={t('lab.theProjectPlannerRootModelBreaksThisIntoPhasesAndSteps')}>
        <textarea id="p-goal" rows={3} style={inputStyle} value={goal} onChange={(e) => setGoal(e.target.value)} />
      </Field>
      <Field id="p-ws" label={t('lab.workspacePathGitRepo')}>
        <div style={{ display: 'flex', gap: 6 }}>
          <input id="p-ws" style={{ ...inputStyle, flex: 1, minWidth: 0 }} value={workspace} placeholder="/Users/…/my-repo" onChange={(e) => setWorkspace(e.target.value)} />
          <PixelButton size="sm" variant="secondary" disabled={picking} onClick={() => void pickFolder()}>{t('lab.chooseFolder')}</PixelButton>
        </div>
      </Field>
      <ProjectConfigEditor value={settings} onChange={setSettings} />
      <PixelButton disabled={busy || !settings} onClick={() => void create()}>{busy ? t('lab.planning') : t('lab.createPlan')}</PixelButton>
      <Status error={error} />
    </form>
  );
}

function ProjectConfigForm({ project }: { project: Project }) {
  const { t } = useTranslation();
  const [settings, setSettings] = useState<ProjectSettings | null>(project.settings ?? null);
  const [profile, setProfile] = useState('');
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const save = () => {
    if (!settings) return;
    setError(null);
    void api.updateProjectSettings(project.id, settings).then(() => setSaved(true)).catch((e) => setError(errorText(e)));
  };
  return (
    <>
      <ProjectConfigEditor value={settings} onChange={(next) => { setSettings(next); setSaved(false); }} />
      <PixelButton disabled={!settings} onClick={save}>{t('lab.save')}</PixelButton>
      {saved && <Muted>{t('lab.configurationSaved')}</Muted>}
      <details>
        <summary>{t('lab.yamlProfile')}</summary>
        <textarea aria-label={t('lab.yamlProfile')} style={inputStyle} rows={8} value={profile} onChange={(e) => setProfile(e.target.value)} />
        <PixelButton size="sm" onClick={() => { void api.projectProfile(project.id).then(setProfile).catch((e) => setError(errorText(e))); }}>{t('lab.exportYaml')}</PixelButton>
        <PixelButton size="sm" disabled={!profile.trim()} onClick={() => {
          void api.importProjectProfile(project.id, profile).then((p) => { setSettings(p.settings ?? null); setSaved(true); }).catch((e) => setError(errorText(e)));
        }}>{t('lab.applyYaml')}</PixelButton>
      </details>
      <Status error={error} />
    </>
  );
}

export function ProjectDialogs({ runtime }: { runtime?: string }) {
  const { t } = useTranslation();
  const dialog = useStore((s) => s.projectDialog);
  const close = useStore((s) => s.openProjectDialog);
  const activeProjectId = useStore((s) => s.activeProjectId);
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setProject(null); setError(null);
    if (dialog !== 'config' || !activeProjectId) return;
    let alive = true;
    api.project(activeProjectId).then((p) => { if (alive) setProject(p); }).catch((e) => { if (alive) setError(errorText(e)); });
    return () => { alive = false; };
  }, [dialog, activeProjectId]);

  if (dialog === 'new') {
    return (
      <Modal title={t('lab.newProject')} onClose={() => close(null)}>
        <NewProjectForm runtime={runtime} onCreated={(p) => {
          const store = useStore.getState();
          close(null);
          store.setActiveProject(p.id);
          store.requestCommandCenterTab('chat');
        }} />
      </Modal>
    );
  }
  if (dialog === 'config' && activeProjectId) {
    return (
      <Modal title={t('lab.agentConfiguration')} onClose={() => close(null)}>
        {project ? <ProjectConfigForm key={project.id} project={project} /> : <Status error={error} />}
      </Modal>
    );
  }
  return null;
}
