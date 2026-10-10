import { useEffect, useRef, useState } from 'react';

/**
 * Renderer-side consumers of the live telemetry stream (#7B).
 *
 * The main-process collector (telemetry.ts) pushes normalized, PII-free events
 * on `telemetry:event` and breaker state on `control:breakerState`. These hooks
 * subscribe + backfill from the cold-start snapshot, and shape the data for the
 * fleet grid (`useFleetTelemetry`) and the per-agent span waterfall
 * (`useAgentSpans`).
 *
 * Types mirror the LOCKED contract in src/main/telemetry.ts + src/preload (kept
 * in sync by hand, matching the codebase's local-redeclare pattern).
 */

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

/** Total tokens across all kinds — the sparkline/velocity basis. */
export function totalTokens(s: AgentUsageSample): number {
  return s.input + s.output + s.cacheRead + s.cacheCreation;
}

/** How many tokens were fresh vs served from cache, as a 0–1 cache fraction. */
export function cacheFraction(s: AgentUsageSample): number {
  const total = totalTokens(s);
  return total > 0 ? s.cacheRead / total : 0;
}

/** Per-agent rolling token deltas (for the sparkline) plus a simple tokens/min. */
interface Rate {
  deltas: number[]; // most recent first-N token deltas between pushes
  firstTs: number;
  firstTotal: number;
  lastTs: number;
  lastTotal: number;
}

const SPARK_LEN = 14;

export interface FleetTelemetry {
  samples: Record<string, AgentUsageSample>;
  /** sparkline series (token deltas between pushes), oldest→newest, per agent */
  spark: Record<string, number[]>;
  /** tokens/min, derived per agent */
  rate: Record<string, number>;
  /** last tool name seen per agent */
  lastTool: Record<string, string>;
  /** latest breaker state per agent (drives the cost-meter color + ⚠) */
  breakers: Record<string, BreakerState>;
}

/**
 * Subscribe to the whole fleet's live telemetry. One instance (the fleet grid).
 * Backfills from the snapshot on mount, then folds in live pushes.
 */
export function useFleetTelemetry(): FleetTelemetry {
  const [samples, setSamples] = useState<Record<string, AgentUsageSample>>({});
  const [spark, setSpark] = useState<Record<string, number[]>>({});
  const [rate, setRate] = useState<Record<string, number>>({});
  const [lastTool, setLastTool] = useState<Record<string, string>>({});
  const [breakers, setBreakers] = useState<Record<string, BreakerState>>({});
  const rates = useRef<Record<string, Rate>>({});

  useEffect(() => {
    let alive = true;

    const foldUsage = (s: AgentUsageSample): void => {
      setSamples((prev) => ({ ...prev, [s.agentId]: s }));
      const total = totalTokens(s);
      const r = rates.current[s.agentId];
      if (!r) {
        rates.current[s.agentId] = { deltas: [], firstTs: s.ts, firstTotal: total, lastTs: s.ts, lastTotal: total };
      } else {
        const delta = Math.max(0, total - r.lastTotal);
        r.deltas = [...r.deltas, delta].slice(-SPARK_LEN);
        r.lastTs = s.ts;
        r.lastTotal = total;
        const minutes = Math.max(1 / 60, (r.lastTs - r.firstTs) / 60000);
        const perMin = (r.lastTotal - r.firstTotal) / minutes;
        setSpark((prev) => ({ ...prev, [s.agentId]: r.deltas }));
        setRate((prev) => ({ ...prev, [s.agentId]: perMin }));
      }
    };

    // Backfill from the snapshot (we missed the pushes before mount).
    window.cth.telemetrySnapshot?.().then((snap) => {
      if (!alive || !snap) return;
      for (const s of snap.usage ?? []) foldUsage(s as AgentUsageSample);
      const tools: Record<string, string> = {};
      for (const [id, spans] of Object.entries(snap.spans ?? {})) {
        const arr = spans as ToolSpan[];
        if (arr.length) tools[id] = arr[arr.length - 1].tool;
      }
      setLastTool((prev) => ({ ...tools, ...prev }));
    }).catch(() => { /* collector not up — empty grid */ });

    const offEvent = window.cth.onTelemetryEvent?.((e: TelemetryEvent) => {
      if (e.kind === 'usage') foldUsage(e.sample);
      else if (e.kind === 'tool_result') setLastTool((prev) => ({ ...prev, [e.span.agentId]: e.span.tool }));
    });
    const offBreaker = window.cth.onBreakerState?.((s: BreakerState) => {
      setBreakers((prev) => ({ ...prev, [s.agentId]: s }));
    });

    return () => { alive = false; offEvent?.(); offBreaker?.(); };
  }, []);

  return { samples, spark, rate, lastTool, breakers };
}

/**
 * Subscribe to ONE agent's tool spans for the waterfall. Backfills from the
 * collector on mount/agent-change, then appends live `tool_result` pushes.
 */
export function useAgentSpans(agentId: string): ToolSpan[] {
  const [spans, setSpans] = useState<ToolSpan[]>([]);

  useEffect(() => {
    let alive = true;
    setSpans([]);
    window.cth.telemetrySpans?.(agentId).then((s) => {
      if (alive && Array.isArray(s)) setSpans(s as ToolSpan[]);
    }).catch(() => { /* none yet */ });

    const off = window.cth.onTelemetryEvent?.((e: TelemetryEvent) => {
      if (e.kind === 'tool_result' && e.span.agentId === agentId) {
        setSpans((prev) => [...prev, e.span].slice(-200));
      } else if (e.kind === 'api_error' && e.agentId === agentId) {
        setSpans((prev) => [...prev, {
          agentId, sessionId: e.sessionId, ts: e.ts, tool: 'api_error',
          success: false, durationMs: 0, error: e.error
        }].slice(-200));
      }
    });
    return () => { alive = false; off?.(); };
  }, [agentId]);

  return spans;
}
