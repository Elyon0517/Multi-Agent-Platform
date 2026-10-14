import type { StatusKind } from '@/components/PixelBadge';
import type { AccentColorName } from '@/design/tokens';
import type { OfficeCharacterName } from '@/scene/office/cast';
import type { MessageAct } from '@/scene/office/MessageEnvelope';
import type { ToolKind } from '@/store/store';
import type { LabEvent, RosterEntry, RunStatus } from '@/api/client';

export interface Seat {
  character: OfficeCharacterName;
  accent: AccentColorName;
  name: string;
  description: string;
  isGod?: boolean;
}

export const SEATS: Record<string, Seat> = {
  root: { character: 'aster', accent: 'lemon', name: 'Root', description: 'Conversation', isGod: true },
  supervisor: { character: 'cedar', accent: 'mint', name: 'Supervisor', description: 'Task orchestration' },
  'project-planner': { character: 'cedar', accent: 'lemon', name: 'Project Planner', description: 'Phases and steps' },
  planner: { character: 'lumen', accent: 'mint', name: 'Planner', description: 'Plans and acceptance criteria' },
  coder: { character: 'byte', accent: 'sky', name: 'Coder', description: 'Implements the plan' },
  'correctness-reviewer': { character: 'quartz', accent: 'coral', name: 'Correctness', description: 'Correctness review' },
  'arch-reviewer': { character: 'atlas', accent: 'lilac', name: 'Architecture', description: 'Architecture review' },
  'test-style-reviewer': { character: 'iris', accent: 'peach', name: 'Test & Style', description: 'Tests and style' },
  arbiter: { character: 'sage', accent: 'lilac', name: 'Arbiter', description: 'Deterministic arbitration' },
  summarizer: { character: 'moss', accent: 'mint', name: 'Summarizer', description: 'Episodic memory' },
  gate: { character: 'flint', accent: 'coral', name: 'Gate', description: 'build / type / lint / test' },
};

export const FALLBACK_SEAT: Seat = { character: 'nova', accent: 'sky', name: '', description: '' };

export function seatFor(role: string): Seat {
  return SEATS[role] ?? { ...FALLBACK_SEAT, name: role };
}

export interface AgentPatch {
  id: string;
  status?: StatusKind;
  action?: string;
  carrying?: ToolKind;
  lastPrompt?: string;
}

export interface Handoff {
  from: string;
  to: string;
  act: MessageAct;
  needsHuman: boolean;
}

export type BoardStatus = 'todo' | 'doing' | 'blocked' | 'done';

export const BOARD_BY_RUN_STATUS: Record<RunStatus, BoardStatus> = {
  PLANNING: 'doing', CODING: 'doing', GATING: 'doing', REVIEWING: 'doing', ARBITRATING: 'doing',
  WAITING_HUMAN: 'blocked', DONE: 'done', CANCELLED: 'done',
};

export const OWNER_BY_RUN_STATUS: Record<RunStatus, string> = {
  PLANNING: 'planner', CODING: 'coder', GATING: 'gate', REVIEWING: 'correctness-reviewer',
  ARBITRATING: 'arbiter', WAITING_HUMAN: 'supervisor', DONE: 'supervisor', CANCELLED: 'supervisor',
};

const TOOL_BY_ROLE: Record<string, ToolKind> = { gate: 'Bash', coder: 'Edit', planner: 'Read' };
const ACT_BY_ARTIFACT: Record<string, MessageAct> = {
  plan: 'propose', diff: 'request', review: 'inform', gate: 'refuse', arbiter: 'request', feedback: 'request',
};

export function rosterIds(roster: RosterEntry[]): string[] {
  return [...roster.map((r) => r.role), 'gate'];
}

export interface Translation {
  patches: AgentPatch[];
  handoffs: Handoff[];
  runStatus?: RunStatus;
}

export function translate(e: LabEvent, agents: ReadonlyArray<{ id: string; status: StatusKind }> = []): Translation {
  const p = e.payload;
  switch (e.type) {
    case 'step.started': {
      const role = String(p.role ?? e.actor);
      return { patches: [{ id: role, status: 'thinking', action: `iteration ${p.iteration ?? ''}`.trim(),
        carrying: TOOL_BY_ROLE[role] }], handoffs: [] };
    }
    case 'step.tool_call':
      return { patches: [{ id: e.actor, status: 'working', carrying: p.tool as ToolKind }], handoffs: [] };
    case 'step.finished':
      return { patches: [{ id: String(p.role ?? e.actor), status: 'success', action: String(p.model ?? '') }],
        handoffs: [] };
    case 'gate.finished':
      return { patches: [{ id: 'gate', status: p.passed ? 'success' : 'blocked',
        action: p.passed ? 'gate passed' : `failed at ${p.failed_at ?? '?'}` }], handoffs: [] };
    case 'artifact.created': {
      if (!p.to) return { patches: [], handoffs: [] };
      return { patches: [], handoffs: [{
        from: e.actor, to: String(p.to), act: ACT_BY_ARTIFACT[String(p.kind)] ?? 'inform', needsHuman: false }] };
    }
    case 'arbiter.decision':
      return { patches: [{ id: 'arbiter', status: p.action === 'ESCALATE' ? 'looping' : 'success',
        action: String(p.action) }], handoffs: [] };
    case 'approval.requested':
      return { patches: [{ id: 'supervisor', status: 'blocked', action: String(p.reason) }],
        handoffs: [{ from: 'arbiter', to: 'supervisor', act: 'query', needsHuman: true }] };
    case 'approval.decided':
      return { patches: [{ id: 'supervisor', status: 'success', action: String(p.decision) }], handoffs: [] };
    case 'budget.warning':
      return { patches: [{ id: 'supervisor', status: 'waiting', action: 'budget 80%' }], handoffs: [] };
    case 'run.status': {
      const dst = p.dst as RunStatus;
      const idle: AgentPatch[] = dst === 'DONE' || dst === 'CANCELLED'
        ? Object.keys(SEATS).map((id) => ({ id, status: 'idle' as StatusKind, action: '' }))
        : dst === 'WAITING_HUMAN'
          ? agents.filter((a) => a.status === 'thinking' || a.status === 'working')
            .map((a) => ({ id: a.id, status: 'idle' as StatusKind, action: '' }))
          : [];
      return { patches: idle, handoffs: [], runStatus: dst };
    }
    default:
      return { patches: [], handoffs: [] };
  }
}
