import { create } from 'zustand';
import type { AccentColorName } from '@/design/tokens';
import type { OfficeCharacterName } from '@/scene/office/cast';
import type { ThemeId } from '@/scene/office/themeRegistry';
import type { StatusKind } from '@/components/PixelBadge';
import type { HumanQA } from '@/components/TasksKanban';
import type { LabEvent, RosterEntry, Run } from '@/api/client';
import { BOARD_BY_RUN_STATUS, OWNER_BY_RUN_STATUS, rosterIds, seatFor, translate, type Handoff } from '@/scene/adapter/mapping';
import { EMPTY_TELEMETRY, foldTelemetry, stepSummary, type Telemetry } from '@/store/telemetry';
import type { AgentUsageSample, ToolSpan } from '@/hooks/useTelemetry';
import { loadPrefs, savePrefs, type Prefs } from '@/store/prefs';

export type ToolKind =
  | 'Read' | 'Edit' | 'Write' | 'Bash' | 'WebFetch' | 'WebSearch'
  | 'Grep' | 'Glob' | 'TodoWrite' | 'MCP';

export type StationKind = 'shelf' | 'terminal' | 'web' | 'board' | 'mailbox' | 'mcp' | 'desk';

export type ConsoleTab = 'chat' | 'runs' | 'project' | 'tasks' | 'human' | 'memory' | 'graph' | 'activity' | 'monitor' | 'settings';

export interface BlockReason {
  summary: string;
  detail: string;
  command?: string;
  actions: Array<{ label: string; kind: 'approve' | 'deny' | 'neutral'; send?: string }>;
}

export interface Agent {
  id: string;
  name: string;
  character: OfficeCharacterName;
  accent: AccentColorName;
  description: string;
  status: StatusKind;
  action: string;
  progress: number;
  carrying?: ToolKind;
  lastPrompt?: string;
  isGod?: boolean;
  isAssistant?: boolean;
  model?: string;
  project: string;
  note?: string;
  contextTokens?: number;
  contextLimit?: number;
  recentText?: string;
  recentSeq?: number;
  blockReason?: BlockReason;
}

export interface BoardTask {
  id: string;
  title: string;
  description?: string;
  status: 'todo' | 'doing' | 'blocked' | 'done';
  assignee?: string;
  createdAt: string;
  dependsOn: string[];
  priority: number;
  humanQA?: HumanQA[];
}

export interface LogEntry extends Handoff {
  ts: number;
  kind: 'message';
  subject: string;
}

type HandoffListener = (h: Handoff) => void;
type TelemetryListener = (u: { usage?: AgentUsageSample; span?: ToolSpan }) => void;

interface LabState {
  rootBusy: boolean;
  setRootBusy: (busy: boolean) => void;
  agents: Agent[];
  restorableAgents: Agent[];
  selectedId: string | null;
  officeTheme: ThemeId;
  fullscreenAgentId: string | null;
  ideOpen: boolean;
  commandCenterTab: ConsoleTab;
  taskDetailId: string | null;
  runs: Run[];
  activeRunId: string | null;
  activeProjectId: string | null;
  activeThreadId: string | null;
  events: LabEvent[];
  lastEventSeq: number;
  tasks: BoardTask[];
  log: LogEntry[];
  telemetry: Telemetry;
  answerDrafts: Record<string, string>;
  dismissedAsks: Record<string, string>;
  prefs: Prefs;
  handoffListeners: Set<HandoffListener>;
  telemetryListeners: Set<TelemetryListener>;

  select: (id: string | null) => void;
  requestCommandCenterTab: (tab: ConsoleTab) => void;
  openTaskDetail: (id: string) => void;
  closeTaskDetail: () => void;
  setRoster: (roster: RosterEntry[]) => void;
  setRuns: (runs: Run[]) => void;
  setActiveRun: (id: string | null) => void;
  setActiveThread: (id: string | null) => void;
  setActiveProject: (id: string | null) => void;
  applyEvent: (e: LabEvent) => void;
  setOfficeTheme: (theme: ThemeId) => void;
  reorderAgents: (fromId: string, toId: string) => void;
  renameAgent: (id: string, name: string) => Promise<{ ok: boolean; error?: string }>;
  setAgentNote: (id: string, note: string) => void;
  setAnswerDraft: (taskId: string, text: string) => void;
  dismissAsk: (taskId: string, at: string) => void;
}

const NAME_MAX = 24;

function agentFromRole(role: string, entry: RosterEntry | undefined, prefs: Prefs): Agent {
  const seat = seatFor(role);
  return {
    id: role, name: prefs.names[role] ?? seat.name, character: seat.character, accent: seat.accent,
    description: seat.description, status: 'idle', action: '', progress: 0, isGod: seat.isGod,
    model: entry?.model, project: entry?.alias ? `${role === 'supervisor' ? 'orchestration' : entry.alias} · ${entry.model}` : 'deterministic',
    note: prefs.notes[`${useStore.getState().activeProjectId ?? 'default'}:${role}`], contextLimit: entry?.ctx_window,
  };
}

function orderAgents(agents: Agent[], order: string[]): Agent[] {
  const rank = (id: string) => { const i = order.indexOf(id); return i < 0 ? order.length : i; };
  return [...agents].sort((a, b) => Number(!!b.isGod) - Number(!!a.isGod) || rank(a.id) - rank(b.id));
}

function taskFor(run: Run, dismissed: Record<string, string>): BoardTask {
  const waiting = run.status === 'WAITING_HUMAN';
  const humanQA: HumanQA[] = waiting
    ? [{ q: `Run needs your decision: ${run.paused_reason ?? 'signoff'}`, askedAt: run.created_at,
         dismissedAt: dismissed[run.id] }]
    : [];
  return {
    id: run.id, title: run.goal, description: `${seatFor(OWNER_BY_RUN_STATUS[run.status]).name} · ${run.status}`, status: BOARD_BY_RUN_STATUS[run.status],
    assignee: OWNER_BY_RUN_STATUS[run.status], createdAt: run.created_at, dependsOn: [], priority: 3, humanQA,
  };
}

const tasksFor = (runs: Run[], dismissed: Record<string, string>): BoardTask[] => runs.map((r) => taskFor(r, dismissed));

function patchRun(run: Run, e: LabEvent, status?: Run['status']): Run {
  const p = e.payload;
  const next = { ...run, status: status ?? run.status };
  if (e.type === 'approval.requested') next.paused_reason = String(p.reason ?? '');
  if (e.type === 'approval.decided') next.paused_reason = null;
  if (e.type === 'step.finished') {
    next.cost_cents = Math.max(run.cost_cents, Number(p.cumulative_cost_cents ?? run.cost_cents));
    next.tokens_in = Math.max(run.tokens_in, Number(p.cumulative_tokens_in ?? run.tokens_in));
    next.tokens_out = Math.max(run.tokens_out, Number(p.cumulative_tokens_out ?? run.tokens_out));
  }
  return next;
}

export const useStore = create<LabState>((set, get) => {
  const persist = (patch: Partial<Prefs>) => {
    const prefs = { ...get().prefs, ...patch };
    savePrefs(prefs);
    set({ prefs });
  };
  const initial = loadPrefs();

  return {
    rootBusy: false,
    setRootBusy: (rootBusy) => set({ rootBusy }),
    agents: [],
    restorableAgents: [],
    selectedId: null,
    officeTheme: initial.theme,
    fullscreenAgentId: null,
    ideOpen: false,
    commandCenterTab: 'chat',
    taskDetailId: null,
    runs: [],
    activeRunId: null,
    activeProjectId: null,
    activeThreadId: null,
    events: [],
    lastEventSeq: 0,
    tasks: [],
    log: [],
    telemetry: EMPTY_TELEMETRY,
    answerDrafts: {},
    dismissedAsks: {},
    prefs: initial,
    handoffListeners: new Set(),
    telemetryListeners: new Set(),

    select: (id) => set({ selectedId: id }),
    requestCommandCenterTab: (tab) => set({ commandCenterTab: tab }),
    openTaskDetail: (id) => set({ taskDetailId: id }),
    closeTaskDetail: () => set({ taskDetailId: null }),

    setRoster: (roster) => {
      const byRole = new Map(roster.map((r) => [r.role, r]));
      const { prefs } = get();
      set({ agents: orderAgents(rosterIds(roster).map((id) => { const fresh = agentFromRole(id, byRole.get(id), prefs); const old = get().agents.find(a => a.id === id); return old ? { ...old, ...fresh, status: old.status, action: old.action, carrying: old.carrying } : fresh; }), prefs.order) });
    },

    setRuns: (runs) => set((s) => ({ runs, tasks: tasksFor(runs, s.dismissedAsks) })),
    setActiveRun: (id) => set((s) => ({ agents: s.agents.map(a => ({ ...a, status: 'idle', action: '', progress: 0, carrying: undefined, recentText: undefined, recentSeq: undefined, blockReason: undefined, contextTokens: undefined })), selectedId: null, taskDetailId: null, activeRunId: id, activeThreadId: id ? s.runs.find(r => r.id === id)?.thread_id ?? null : s.activeThreadId, events: [], lastEventSeq: 0, telemetry: EMPTY_TELEMETRY, log: [] })),
    setActiveThread: (id) => { get().setActiveRun(null); set({ activeThreadId: id, commandCenterTab: 'chat', rootBusy: false }); },
    setActiveProject: (id) => {
      if (get().activeProjectId === id) return;
      get().setActiveRun(null);
      set({ activeProjectId: id, activeThreadId: null, agents: [], runs: [], tasks: [], answerDrafts: {}, dismissedAsks: {}, fullscreenAgentId: null, taskDetailId: null });
    },

    applyEvent: (e) => {
      if (e.run_id !== get().activeRunId || e.seq <= get().lastEventSeq) return;
      const { patches, handoffs, runStatus } = translate(e, get().agents);
      const folded = foldTelemetry(get().telemetry, e);
      const recent = stepSummary(e);
      set((s) => {
        const byId = new Map(patches.map((p) => [p.id, p]));
        const agents = s.agents.map((a) => {
          const p = byId.get(a.id);
          let next = p ? { ...a, ...Object.fromEntries(Object.entries(p).filter(([, v]) => v !== undefined)) } : a;
          if (recent?.id === a.id) next = { ...next, recentText: recent.text, recentSeq: e.seq };
          const usage = folded.usage?.agentId === a.id ? folded.usage : undefined;
          if (usage) {
            const tokens = usage.input + usage.output;
            next = { ...next, contextTokens: tokens,
              progress: a.contextLimit ? Math.min(8, Math.ceil((tokens / a.contextLimit) * 8)) : 0 };
          }
          return next;
        });
        const runs = s.runs.map((r) => (r.id === e.run_id ? patchRun(r, e, runStatus) : r));
        const log = handoffs.length === 0 ? s.log : [
          ...s.log, ...handoffs.map((h) => ({ ...h, ts: Date.parse(e.ts), kind: 'message' as const,
            subject: String(e.payload.kind ?? e.type) })),
        ].slice(-500);
        return { lastEventSeq: e.seq, agents, runs, tasks: tasksFor(runs, s.dismissedAsks), log, telemetry: folded.next,
          events: [...s.events, e].slice(-2000) };
      });
      for (const h of handoffs) for (const l of get().handoffListeners) l(h);
      if (folded.usage || folded.span) for (const l of get().telemetryListeners) l(folded);
    },

    setOfficeTheme: (theme) => { persist({ theme }); set({ officeTheme: theme }); },

    reorderAgents: (fromId, toId) => {
      const ids = get().agents.map((a) => a.id);
      const from = ids.indexOf(fromId);
      const to = ids.indexOf(toId);
      if (from < 0 || to < 0) return;
      ids.splice(to, 0, ...ids.splice(from, 1));
      persist({ order: ids });
      set((s) => ({ agents: orderAgents(s.agents, ids) }));
    },

    renameAgent: async (id, name) => {
      const clean = name.trim().slice(0, NAME_MAX);
      if (!clean) return { ok: false, error: 'name cannot be empty' };
      persist({ names: { ...get().prefs.names, [id]: clean } });
      set((s) => ({ agents: s.agents.map((a) => (a.id === id ? { ...a, name: clean } : a)) }));
      return { ok: true };
    },

    setAgentNote: (id, note) => {
      persist({ notes: { ...get().prefs.notes, [`${get().activeProjectId ?? 'default'}:${id}`]: note } });
      set((s) => ({ agents: s.agents.map((a) => (a.id === id ? { ...a, note } : a)) }));
    },

    setAnswerDraft: (taskId, text) => set((s) => ({ answerDrafts: { ...s.answerDrafts, [taskId]: text } })),

    dismissAsk: (taskId, at) => set((s) => {
      const dismissedAsks = { ...s.dismissedAsks, [taskId]: at };
      return { dismissedAsks, tasks: tasksFor(s.runs, dismissedAsks) };
    }),
  };
});
