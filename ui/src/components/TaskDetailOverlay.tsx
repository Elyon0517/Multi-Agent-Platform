import { useCallback, useEffect, useRef, useState } from 'react';
import { useStore } from '@/store/store';
import { TaskDetail, parseTasks, type HiveTask } from './TasksKanban';

/** Shared task detail overlay, refreshed from the ledger every five seconds. */

const POLL_MS = 5000;

export function TaskDetailOverlay() {
  const taskDetailId = useStore((s) => s.taskDetailId);
  const closeTaskDetail = useStore((s) => s.closeTaskDetail);
  const agents = useStore((s) => s.agents);
  const restorable = useStore((s) => s.restorableAgents);
  const [tasks, setTasks] = useState<HiveTask[]>([]);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    // Normalize ledger entries before passing them to TaskDetail.
    try { setTasks(parseTasks(await window.cth.hiveTasks())); } catch { /* keep last good */ }
  }, []);

  useEffect(() => {
    if (!taskDetailId) return;
    void refresh();
    timer.current = setInterval(() => { void refresh(); }, POLL_MS);
    return () => { if (timer.current) clearInterval(timer.current); };
  }, [taskDetailId, refresh]);

  if (!taskDetailId) return null;
  const task = tasks.find((t) => t.id === taskDetailId);
  if (!task) return null;

  const nameFor = (id?: string): string | undefined =>
    id ? (agents.find((a) => a.id === id)?.name ?? restorable.find((a) => a.id === id)?.name ?? id) : undefined;

  // Patch the raw ledger: serializing normalized display data would rewrite unrelated fields.
  const move = async (status: HiveTask['status']) => {
    const next = tasks.map((t) => (t.id === task.id ? { ...t, status } : t));
    setTasks(next); // optimistic
    try {
      const result = await window.cth.hivePatchTask(task.id, { status });
      if (!result.ok) void refresh();
    } catch { void refresh(); }
  };

  const assign = () => {
    // Route through the Command Center's dispatch box (which mails the god —
    // the human never writes into a worker's inbox directly).
    const st = useStore.getState();
    st.setActiveRun(task.id);
    st.requestCommandCenterTab('runs');
    closeTaskDetail();
  };

  return (
    <TaskDetail
      task={task}
      all={tasks}
      assigneeName={nameFor(task.assignee)}
      onMove={(s) => void move(s)}
      onAssign={assign}
      onClose={closeTaskDetail}
    />
  );
}
