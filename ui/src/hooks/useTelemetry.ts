import { useEffect, useState } from 'react';

export interface AgentUsageSample {
  agentId: string;
  sessionId: string;
  ts: number;
  input: number;
  output: number;
  cacheRead: number;
  cacheCreation: number;
  model: string;
  usd: number;
}

export interface ToolSpan {
  agentId: string;
  sessionId: string;
  ts: number;
  tool: string;
  success: boolean;
  durationMs: number;
  decision?: 'accept' | 'reject';
  error?: string;
}

export interface BreakerState {
  agentId: string;
  level: 'healthy' | 'steering' | 'constrained' | 'stopped';
  reason: string;
  ts: number;
}

export type TelemetryEvent =
  | { kind: 'usage'; sample: AgentUsageSample }
  | { kind: 'tool_result'; span: ToolSpan }
  | { kind: 'api_error'; agentId: string; sessionId: string; ts: number; error: string };


export function totalTokens(sample: AgentUsageSample): number {
  return [sample.input, sample.output, sample.cacheRead, sample.cacheCreation].reduce((sum, n) => sum + n, 0);
}
export function cacheFraction(sample: AgentUsageSample): number {
  return totalTokens(sample) ? sample.cacheRead / totalTokens(sample) : 0;
}
export interface FleetTelemetry {
  samples: Record<string, AgentUsageSample>; spark: Record<string, number[]>; rate: Record<string, number>;
  lastTool: Record<string, string>; breakers: Record<string, BreakerState>;
}
const empty = (): FleetTelemetry => ({ samples: {}, spark: {}, rate: {}, lastTool: {}, breakers: {} });
export function foldUsage(state: FleetTelemetry, sample: AgentUsageSample): FleetTelemetry {
  const old = state.samples[sample.agentId];
  if (old && (old.ts > sample.ts || (old.ts === sample.ts && old.sessionId === sample.sessionId &&
    (totalTokens(old) > totalTokens(sample) || JSON.stringify(old) === JSON.stringify(sample))))) return state;
  const change = old ? Math.max(0, totalTokens(sample) - totalTokens(old)) : 0;
  const elapsed = old ? Math.max(1000, sample.ts - old.ts) : 0;
  return { ...state, samples: { ...state.samples, [sample.agentId]: sample },
    spark: { ...state.spark, [sample.agentId]: [...(state.spark[sample.agentId] ?? []), change].slice(-14) },
    rate: { ...state.rate, [sample.agentId]: elapsed ? change * 60000 / elapsed : 0 } };
}
export function useFleetTelemetry(): FleetTelemetry {
  const [state, update] = useState<FleetTelemetry>(empty);
  useEffect(() => {
    let cancelled = false;
    const usage = (sample: AgentUsageSample) => { if (!cancelled) update(current => foldUsage(current, sample)); };
    const stopEvents = window.cth.onTelemetryEvent(event => {
      if (event.kind === 'usage') usage(event.sample);
      if (event.kind === 'tool_result') update(current => ({ ...current,
        lastTool: { ...current.lastTool, [event.span.agentId]: event.span.tool } }));
    });
    const stopBreakers = window.cth.onBreakerState(breaker => update(current => ({ ...current,
      breakers: { ...current.breakers, [breaker.agentId]: breaker } })));
    void window.cth.telemetrySnapshot().then(snapshot => {
      if (cancelled) return;
      for (const sample of snapshot.usage) usage(sample);
      update(current => {
        const lastTool = { ...current.lastTool };
        for (const [id, spans] of Object.entries(snapshot.spans))
          if (!lastTool[id] && spans.length) lastTool[id] = spans.at(-1)!.tool;
        return { ...current, lastTool };
      });
    }).catch(() => undefined);
    return () => { cancelled = true; stopEvents(); stopBreakers(); };
  }, []);
  return state;
}
export function mergeSpans(current: ToolSpan[], incoming: ToolSpan[]): ToolSpan[] {
  const unique = new Map<string, ToolSpan>();
  for (const span of [...incoming, ...current]) unique.set(JSON.stringify([span.agentId,span.sessionId,span.ts,span.tool,span.durationMs,span.success,span.decision,span.error]), span);
  return [...unique.values()].sort((a, b) => a.ts - b.ts).slice(-200);
}
export function useAgentSpans(agentId: string): ToolSpan[] {
  const [state, update] = useState<{ id: string; spans: ToolSpan[] }>({ id: agentId, spans: [] });
  useEffect(() => {
    let cancelled = false;
    update({ id: agentId, spans: [] });
    const append = (spans: ToolSpan[]) => {
      if (!cancelled) update(current => ({ id: agentId,
        spans: mergeSpans(current.id === agentId ? current.spans : [], spans) }));
    };
    const stop = window.cth.onTelemetryEvent(event => {
      if (event.kind === 'tool_result' && event.span.agentId === agentId) append([event.span]);
      if (event.kind === 'api_error' && event.agentId === agentId) append([{ agentId, sessionId: event.sessionId,
        ts: event.ts, tool: 'api_error', success: false, durationMs: 0, error: event.error }]);
    });
    void window.cth.telemetrySpans(agentId).then(append).catch(() => undefined);
    return () => { cancelled = true; stop(); };
  }, [agentId]);
  return state.id === agentId ? state.spans : [];
}
