import type { LabEvent, RunStatus } from '@/api/client';
import type { AgentUsageSample, ToolSpan } from '@/hooks/useTelemetry';

export const SPAN_LIMIT = 200;

export interface Telemetry {
  usage: Record<string, AgentUsageSample>;
  spans: Record<string, ToolSpan[]>;
}

export const EMPTY_TELEMETRY: Telemetry = { usage: {}, spans: {} };

interface StepPayload {
  role?: string;
  model?: string;
  tokens_in?: number;
  tokens_out?: number;
  cost_cents?: number;
  latency_ms?: number;
}

export function foldTelemetry(t: Telemetry, e: LabEvent): { next: Telemetry; usage?: AgentUsageSample; span?: ToolSpan } {
  const ts = Date.parse(e.ts);
  if (e.type === 'step.finished') {
    const p = e.payload as StepPayload;
    const id = p.role ?? e.actor;
    const prev = t.usage[id];
    const usage: AgentUsageSample = {
      agentId: id, sessionId: e.run_id, ts, model: p.model ?? '',
      input: (prev?.input ?? 0) + (p.tokens_in ?? 0), output: (prev?.output ?? 0) + (p.tokens_out ?? 0),
      cacheRead: 0, cacheCreation: 0, usd: (prev?.usd ?? 0) + (p.cost_cents ?? 0) / 100,
    };
    const span: ToolSpan = { agentId: id, sessionId: e.run_id, ts, tool: `llm:${p.model ?? ''}`, success: true,
      durationMs: p.latency_ms ?? 0 };
    return { next: { usage: { ...t.usage, [id]: usage }, spans: appendSpan(t.spans, span) }, usage, span };
  }
  if (e.type === 'gate.finished') {
    const passed = Boolean(e.payload.passed);
    const span: ToolSpan = { agentId: 'gate', sessionId: e.run_id, ts, tool: `gate:${e.payload.mode ?? 'fast'}`,
      success: passed, durationMs: 0, error: passed ? undefined : `failed at ${String(e.payload.failed_at ?? '?')}` };
    return { next: { ...t, spans: appendSpan(t.spans, span) }, span };
  }
  return { next: t };
}

function appendSpan(spans: Record<string, ToolSpan[]>, s: ToolSpan): Record<string, ToolSpan[]> {
  return { ...spans, [s.agentId]: [...(spans[s.agentId] ?? []), s].slice(-SPAN_LIMIT) };
}

export function stepSummary(e: LabEvent): { id: string; text: string } | null {
  if (e.type !== 'step.finished' || typeof e.payload.summary !== 'string') return null;
  return { id: String(e.payload.role ?? e.actor), text: e.payload.summary };
}

export function approvalQuestion(e: LabEvent): string | null {
  if (e.type !== 'approval.requested') return null;
  const reason = String(e.payload.reason ?? 'decision');
  const detail = (e.payload.payload ?? {}) as Record<string, unknown>;
  const extra = Object.entries(detail).filter(([k]) => k !== 'diff_ref').map(([k, v]) => `${k}: ${String(v)}`);
  return [`Run needs your decision: ${reason}`, ...extra].join('\n');
}

export const isTerminal = (s: RunStatus): boolean => s === 'DONE' || s === 'CANCELLED';
