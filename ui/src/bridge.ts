import { api } from '@/api/client';
import { useStore, type BoardTask, type LogEntry } from '@/store/store';
import type { MessageAct } from '@/scene/office/MessageEnvelope';
import type { AgentUsageSample, BreakerState, TelemetryEvent, ToolSpan } from '@/hooks/useTelemetry';
import { memoryDigest } from '@/views/memoryDigest';

interface HiveRouteEvent {
  id: string;
  from: string;
  to: string;
  act: MessageAct;
  subject: string;
  targets: string[];
  needsHuman: boolean;
}

interface HiveMessage {
  id: string;
  conversation: string;
  in_reply_to: string | null;
  from: string;
  to: string;
  act: MessageAct;
  subject: string;
  body: string;
  hops: number;
  requires_reply: boolean;
  needs_human: boolean;
  created_at: string;
}

type Off = () => void;
type Ok = { ok: boolean; error?: string };
type BinaryResult =
  | { ok: true; bytes: Uint8Array<ArrayBuffer>; mime: string; path: string; size: number }
  | { ok: false; error: string };
type TaskPatch = Partial<Omit<BoardTask, 'id'>>;

function toMessage(e: LogEntry, i: number): HiveMessage {
  return {
    id: `${e.ts}-${i}`, conversation: e.subject, in_reply_to: null, from: e.from, to: e.to, act: e.act,
    subject: e.subject, body: '', hops: 0, requires_reply: false, needs_human: e.needsHuman,
    created_at: new Date(e.ts).toISOString(),
  };
}

const fail = (error: string): Ok => ({ ok: false, error });

async function patchTask(id: string, patch: TaskPatch): Promise<Ok> {
  const st = useStore.getState();
  const qa = patch.humanQA?.at(-1);
  if (qa?.dismissedAt && !qa.a) {
    st.dismissAsk(id, qa.dismissedAt);
    return { ok: true };
  }
  if (qa?.a) {
    const decision = /^\s*(abort|cancel)\b/i.test(qa.a) ? 'abort'
      : /^\s*(approve|yes|ok|lgtm|ship)\b/i.test(qa.a) ? 'approve' : 'reject';
    try {
      await api.decide(id, decision, decision === 'reject' ? qa.a : undefined);
      return { ok: true };
    } catch (e) {
      return fail((e as Error).message);
    }
  }
  if (patch.status === 'done') {
    try {
      await api.decide(id, 'approve');
      return { ok: true };
    } catch (e) {
      return fail((e as Error).message);
    }
  }
  return fail('runs advance through the loop; only answers, approve, or dismiss are accepted');
}

export const labBridge = {
  hiveTasks: async (): Promise<unknown> => ({ tasks: useStore.getState().tasks }),
  hivePatchTask: patchTask,
  hiveLog: async (n = 200): Promise<unknown[]> => useStore.getState().log.slice(-n),
  hiveMemory: async (id: string): Promise<string> => {
    const projectId = useStore.getState().activeProjectId ?? undefined;
    try {
      return memoryDigest(await api.memory('agent', { role: id, projectId }));
    } catch {
      return '';
    }
  },
  hiveInbox: async (id: string): Promise<HiveMessage[]> =>
    useStore.getState().log.map(toMessage).filter((m) => m.to === id || m.from === id),
  hiveSend: async (msg: Partial<HiveMessage>, _from?: string): Promise<Ok & { message?: HiveMessage }> => {
    const runId = useStore.getState().activeRunId;
    if (!runId || !msg.body) return fail('no active run to reply to');
    try {
      await api.decide(runId, 'reject', msg.body);
      return { ok: true };
    } catch (e) {
      return fail((e as Error).message);
    }
  },
  hiveDeleteTask: async (_id: string): Promise<Ok> => fail('runs cannot be deleted'),
  onHiveMessage: (cb: (e: HiveRouteEvent) => void): Off => {
    const listener = (h: { from: string; to: string; act: MessageAct; needsHuman: boolean }) =>
      cb({ id: `${Date.now()}`, from: h.from, to: h.to, act: h.act, subject: '', targets: [h.to],
        needsHuman: h.needsHuman });
    const { handoffListeners } = useStore.getState();
    handoffListeners.add(listener);
    return () => handoffListeners.delete(listener);
  },
  telemetrySnapshot: async (): Promise<{ usage: AgentUsageSample[]; spans: Record<string, ToolSpan[]> }> => {
    const { usage, spans } = useStore.getState().telemetry;
    return { usage: Object.values(usage), spans };
  },
  telemetrySpans: async (agentId: string): Promise<ToolSpan[]> =>
    useStore.getState().telemetry.spans[agentId] ?? [],
  onTelemetryEvent: (cb: (e: TelemetryEvent) => void): Off => {
    const listener = ({ usage, span }: { usage?: AgentUsageSample; span?: ToolSpan }) => {
      if (usage) cb({ kind: 'usage', sample: usage });
      if (span) cb({ kind: 'tool_result', span });
    };
    const { telemetryListeners } = useStore.getState();
    telemetryListeners.add(listener);
    return () => telemetryListeners.delete(listener);
  },
  onBreakerState: (_cb: (s: BreakerState) => void): Off => () => undefined,
  readBinary: async (projectId: string, rel: string, signal?: AbortSignal): Promise<BinaryResult> => {
    try { return { ok: true, ...await api.workspaceImage(projectId, rel, signal) }; }
    catch (e) { return { ok: false, error: e instanceof Error ? e.message : String(e) }; }
  },
  openExternal: async (url: string): Promise<Ok> => {
    window.open(url, '_blank', 'noopener');
    return { ok: true };
  },
};

export type CthApi = typeof labBridge;

declare global {
  interface Window {
    cth: CthApi;
  }
}

export function installBridge(): void {
  window.cth = labBridge;
}
