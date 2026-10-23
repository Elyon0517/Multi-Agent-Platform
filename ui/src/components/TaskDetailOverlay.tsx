import { useState } from 'react';
import { useStore } from '@/store/store';
import { usePoll } from '@/hooks/usePoll';
import { parseTasks, TaskDetail, type HiveTask } from './TasksKanban';
export function TaskDetailOverlay() {
  const state = useStore();
  // Mounting the reader only while open prevents an idle background poll.
  return state.taskDetailId ? <SelectedTask key={state.taskDetailId} id={state.taskDetailId} /> : null;
}
function SelectedTask({ id }: { id: string }) {
  const state = useStore();
  const tasks = usePoll(async () => parseTasks(await window.cth.hiveTasks()), [] as HiveTask[], 5000, id);
  const [error, setError] = useState('');
  const task = tasks.find(candidate => candidate.id === id);
  if (!task) return null;
  const assignee = [...state.agents, ...state.restorableAgents].find(agent => agent.id === task.assignee)?.name ?? task.assignee;
  const move = async (status: HiveTask['status']) => {
    try { const result = await window.cth.hivePatchTask(id, { status }); setError(result.ok ? '' : result.error ?? 'Task update failed'); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };
  return <><TaskDetail task={task} all={tasks} assigneeName={assignee} onMove={status => void move(status)}
    onAssign={() => { state.setActiveRun(id); state.requestCommandCenterTab('runs'); state.closeTaskDetail(); }}
    onClose={state.closeTaskDetail} />{error && <div role="alert" style={{ position: 'fixed', bottom: 24, left: '25%', zIndex: 281,
      background: 'var(--cth-coral-light)', padding: 12 }}>{error}</div>}</>;
}
