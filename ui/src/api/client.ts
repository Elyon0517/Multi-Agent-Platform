export type RunStatus =
  | 'PLANNING' | 'CODING' | 'GATING' | 'REVIEWING' | 'ARBITRATING' | 'WAITING_HUMAN' | 'DONE' | 'CANCELLED';

export type EventType =
  | 'run.created' | 'run.status' | 'step.started' | 'step.tool_call' | 'step.finished'
  | 'artifact.created' | 'gate.finished' | 'arbiter.decision'
  | 'approval.requested' | 'approval.decided' | 'budget.warning';

export interface LabEvent {
  run_id: string;
  seq: number;
  ts: string;
  type: EventType;
  actor: string;
  payload: Record<string, unknown>;
}

export interface Run {
  id: string;
  goal: string;
  status: RunStatus;
  max_iter: number;
  budget_cents: number;
  cost_cents: number;
  tokens_in: number;
  tokens_out: number;
  paused_reason: string | null;
  project_id: string;
  created_at: string;
}

export interface Step {
  id: string;
  iteration_n: number;
  role: string;
  model_alias: string;
  model: string;
  usage: { tokens_in: number; tokens_out: number; cost_cents: number };
  latency_ms: number;
  attempt_count: number;
  retry_reasons: string[];
}

export interface Approval {
  id: string;
  reason: string;
  payload: Record<string, unknown>;
  status: string;
}

export interface Artifact {
  id: string;
  kind: string;
  sha256: string;
  created_at: string;
}

export interface RunDetail {
  run: Run;
  iterations: unknown[];
  steps: Step[];
  artifacts: Artifact[];
  pending_approval: Approval | null;
}

export interface RosterEntry {
  role: string;
  kind: 'worker' | 'reviewer' | 'deterministic';
  alias: string;
  model: string;
  ctx_window: number;
}

export interface SettingView {
  key: string;
  secret: boolean;
  is_set: boolean;
  display: string;
}

export type MemoryScope = 'global' | 'project' | 'agent';

export interface MemoryItem {
  id: string;
  project_id: string | null;
  namespace: string;
  kind: 'document' | 'episodic' | 'semantic' | 'note';
  text: string;
  source: string;
  source_run_id: string | null;
  pinned: boolean;
  created_at: string;
}

export interface MemoryHit {
  item: MemoryItem;
  score: number;
}

export interface MemoryStats {
  items: number;
  embedded: number;
  embedding_model: string | null;
  embedding_ready: boolean;
}

export interface DocumentSummary {
  source: string;
  chunks: number;
  chars: number;
}

export type StepStatus = 'todo' | 'doing' | 'done' | 'blocked';

export interface ProjectStep {
  id: string;
  title: string;
  acceptance: string[];
  status: StepStatus;
  run_ids: string[];
}

export interface ProjectPhase {
  id: string;
  title: string;
  steps: ProjectStep[];
}

export interface Project {
  id: string;
  name: string;
  goal: string;
  workspace: string;
  phases: ProjectPhase[];
  created_at: string;
}

export interface CreateRunBody {
  goal: string;
  runtime?: string;
  workspace?: string;
  project_id?: string;
  step_id?: string;
}

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
  roster: () => json<RosterEntry[]>('/roster'),
  runs: () => json<Run[]>('/runs'),
  run: (id: string) => json<RunDetail>(`/runs/${id}`),
  createRun: (body: CreateRunBody) => post<Run>('/runs', body),
  decide: (id: string, decision: 'approve' | 'reject' | 'abort', feedback?: string,
    limits: { budget_cents?: number; max_iter?: number } = {}) =>
    post<Run>(`/runs/${id}/decision`, { decision, feedback, ...limits }),
  artifact: (runId: string, artifactId: string) =>
    json<{ kind: string; content: string }>(`/artifacts/${runId}/${artifactId}`),
  settings: () => json<SettingView[]>('/settings'),
  saveSettings: (values: Record<string, string>) => post<SettingView[]>('/settings', { values }, 'PUT'),
  documents: () => json<DocumentSummary[]>('/knowledge'),
  uploadDocument: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return json<DocumentSummary>('/knowledge', { method: 'POST', body: form });
  },
  deleteDocument: (source: string) =>
    json<{ deleted: number }>(`/knowledge/${encodeURIComponent(source)}`, { method: 'DELETE' }),
  memory: (scope: MemoryScope, opts: { projectId?: string; role?: string } = {}) => {
    const q = new URLSearchParams({ scope });
    if (opts.projectId) q.set('project_id', opts.projectId);
    if (opts.role) q.set('role', opts.role);
    return json<MemoryItem[]>(`/memory?${q}`);
  },
  addMemory: (body: { scope: MemoryScope; text: string; project_id?: string; role?: string; pinned?: boolean }) =>
    post<MemoryItem>('/memory', body),
  searchMemory: (body: { query: string; role?: string; project_id?: string; k?: number }) =>
    post<MemoryHit[]>('/memory/search', body),
  memoryStats: () => json<MemoryStats>('/memory/status'),
  projects: () => json<Project[]>('/projects'),
  project: (id: string) => json<Project>(`/projects/${id}`),
  createProject: (body: { name: string; goal: string; workspace: string; runtime?: string }) =>
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
