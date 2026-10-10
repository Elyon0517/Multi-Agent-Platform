import type { components } from './schema';

export type RunStatus = components['schemas']['RunStatus'];
export type EventType = components['schemas']['EventType'];
export type LabEvent = components['schemas']['Event'];
export type Run = components['schemas']['Run'];
export type Step = components['schemas']['Step'];
export type Approval = components['schemas']['Approval'];
export type SignoffReport = components['schemas']['SignoffReport'];
export type Artifact = components['schemas']['Artifact'];
export type RunDetail = components['schemas']['RunDetail'];
export type RosterEntry = components['schemas']['RosterEntry'];
export type SettingView = components['schemas']['SettingView'];
export type MemoryScope = components['schemas']['NoteBody']['scope'];
export type MemoryItem = components['schemas']['MemoryItem'];
export type MemoryHit = components['schemas']['Hit'];
export type MemoryStats = components['schemas']['MemoryStatus'];
export type DocumentSummary = components['schemas']['DocumentSummary'];
export type StepStatus = components['schemas']['StepStatus'];
export type ProjectStep = ProjectPhase['steps'][number];
export type ProjectPhase = Project['phases'][number];
export type ProjectSettings = components['schemas']['ProjectSettings-Output'];
export type Message = components['schemas']['Message'];
export type Conversation = components['schemas']['Conversation'];
export type ModelCatalog = components['schemas']['ModelCatalog'];
export type Project = components['schemas']['Project'];
export type CreateRunBody = components['schemas']['CreateRun'];
export type UsageSummary = components['schemas']['UsageSummary'];
export type MonitorUsage = components['schemas']['MonitorUsage'];
export type GateResult = components['schemas']['GateResult'];
export type Verdict = components['schemas']['Verdict'];

const BASE = '/api';

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const isForm = init?.body instanceof FormData;
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: isForm ? init?.headers : { 'content-type': 'application/json', ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const text = await res.text();
    let detail = text;
    try { detail = (JSON.parse(text) as { detail?: string }).detail ?? text; } catch { /* plain text */ }
    throw new Error(`${init?.method ?? 'GET'} ${path}: ${res.status} ${detail}`);
  }
  return res.json() as Promise<T>;
}

const post = <T>(path: string, body: unknown, method = 'POST') =>
  json<T>(path, { method, body: JSON.stringify(body) });

export const api = {
  monitorUsage: () => json<MonitorUsage>('/monitor/usage'),
  roster: (projectId?: string, runId?: string) => json<RosterEntry[]>(`/roster?${new URLSearchParams({ ...(projectId ? { project_id: projectId } : {}), ...(runId ? { run_id: runId } : {}) })}`),
  runs: (projectId?: string) => json<Run[]>(`/runs${projectId ? '?project_id=' + encodeURIComponent(projectId) : ''}`),
  run: (id: string) => json<RunDetail>(`/runs/${id}`),
  createRun: (body: CreateRunBody) => post<Run>('/runs', body),
  decide: (id: string, decision: 'approve' | 'reject' | 'abort', feedback?: string,
    limits: { budget_cents?: number; max_iter?: number } = {}) =>
    post<Run>(`/runs/${id}/decision`, { decision, feedback, ...limits }),
  artifact: (runId: string, artifactId: string) =>
    json<components['schemas']['ArtifactContent']>(`/artifacts/${runId}/${artifactId}`),
  settings: () => json<SettingView[]>('/settings'),
  saveSettings: (values: Record<string, string>) => post<SettingView[]>('/settings', { values }, 'PUT'),
  documents: (projectId?: string) => json<DocumentSummary[]>(`/knowledge${projectId ? '?project_id=' + encodeURIComponent(projectId) : ''}`),
  uploadDocument: (file: File, projectId?: string) => {
    const form = new FormData();
    form.append('file', file);
    return json<DocumentSummary>(`/knowledge${projectId ? '?project_id=' + encodeURIComponent(projectId) : ''}`, { method: 'POST', body: form });
  },
  deleteDocument: (source: string, projectId?: string) =>
    json<{ deleted: number }>(`/knowledge/${encodeURIComponent(source)}${projectId ? '?project_id=' + encodeURIComponent(projectId) : ''}`, { method: 'DELETE' }),
  memory: (scope: MemoryScope, opts: { projectId?: string; role?: string } = {}) => {
    const q = new URLSearchParams({ scope });
    if (opts.projectId) q.set('project_id', opts.projectId);
    if (opts.role) q.set('role', opts.role);
    return json<MemoryItem[]>(`/memory?${q}`);
  },
  addMemory: (body: components['schemas']['NoteBody']) =>
    post<MemoryItem>('/memory', body),
  searchMemory: (body: { query: string; role?: string; project_id?: string; k?: number }) =>
    post<MemoryHit[]>('/memory/search', body),
  probeEmbedding: () => post<MemoryStats>('/memory/probe', {}),
  reindexGlobalKnowledge: () => post<MemoryStats>('/knowledge/reindex', {}),
  reindexKnowledge: (id: string) => post<MemoryStats>(`/projects/${id}/knowledge/reindex`, {}),
  memoryStats: () => json<MemoryStats>('/memory/status'),
  projectProfile: async (id: string) => { const response = await fetch(`${BASE}/projects/${id}/profile`); if (!response.ok) throw new Error('Cannot export project profile'); return response.text(); },
  importProjectProfile: (id: string, yaml_text: string) => post<Project>(`/projects/${id}/profile`, { yaml_text }, 'PUT'),
  models: () => json<ModelCatalog>('/models'),
  updateProjectSettings: (id: string, settings: ProjectSettings) => post<Project>(`/projects/${id}/settings`, settings, 'PUT'),
  sendMessage: (id: string, tid: string, text: string) => post<components['schemas']['SendMessageResult']>(`${id === 'global' ? '' : `/projects/${id}`}/threads/${tid}/messages`, { text }),
  threadEvents: (id: string, tid: string, callback: (type: string, payload: Record<string, unknown>) => void) => {
    const es = new EventSource(`${BASE}${id === 'global' ? '' : `/projects/${id}`}/threads/${tid}/events`);
    es.onopen = () => callback('sync', {});
    for (const type of ['message.created', 'message.delta', 'turn.finished']) {
      es.addEventListener(type, (e) => callback(type, JSON.parse((e as MessageEvent).data).payload));
    }
    return () => es.close();
  },
  threads: (id: string) => json<Conversation[]>(`${id === 'global' ? '' : `/projects/${id}`}/threads`),
  createThread: (id: string, title: string) => post<Conversation>(`${id === 'global' ? '' : `/projects/${id}`}/threads`, { title }),
  deleteProject: (id: string) => json<{ deleted: boolean }>(`/projects/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  projects: () => json<Project[]>('/projects'),
  project: (id: string) => json<Project>(`/projects/${id}`),
  createProject: (body: components['schemas']['CreateProject']) =>
    post<Project>('/projects', body),
  patchStep: (projectId: string, stepId: string, status: StepStatus) =>
    post<Project>(`/projects/${projectId}/steps/${stepId}`, { status }, 'PATCH'),
  events: (runId: string, onEvent: (e: LabEvent) => void): (() => void) => {
    const es = new EventSource(`${BASE}/runs/${runId}/events`);
    const handler = (m: MessageEvent<string>) => onEvent(JSON.parse(m.data) as LabEvent);
    const types: EventType[] = [
      'run.created', 'run.status', 'step.started', 'step.tool_call', 'step.finished', 'artifact.created',
      'gate.finished', 'arbiter.decision', 'approval.requested', 'approval.decided', 'budget.warning',
    ];
    for (const t of types) es.addEventListener(t, handler as EventListener);
    return () => es.close();
  },
};
