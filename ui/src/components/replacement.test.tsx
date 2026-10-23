// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PixelButton } from './PixelButton';
import { PixelPanel } from './PixelPanel';
import { PixelBadge } from './PixelBadge';
import { AgentNameEditor } from './AgentNameEditor';
import { AgentCard } from './AgentCard';
import { OfficeThemePicker } from './OfficeThemePicker';
import { parseTasks, openQuestion, waitsOnHuman, TaskDetail } from './TasksKanban';
import { useStore } from '@/store/store';
import { installBridge } from '@/bridge';
import { usePoll } from '@/hooks/usePoll';
import { useWorkspaceImage } from '@/hooks/useWorkspaceImage';
import { foldUsage, mergeSpans, type FleetTelemetry, type AgentUsageSample } from '@/hooks/useTelemetry';
import { MarkdownPreview } from '@/markdown/MarkdownPreview';
import i18n, { setLanguage } from '@/i18n';
import { themeCss, installThemeTokens } from '@/design/tokens';
vi.mock('./SpritePortrait', () => ({ SpritePortrait: ({ character }: { character: string }) => <canvas aria-label={character} /> }));
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
beforeEach(() => { installBridge(); setLanguage('en'); useStore.getState().setOfficeTheme('studio'); });

function deferred<T>() { let resolve!: (v: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }

describe('replacement controls and preserved card structure', () => {
  it('supports button activation by keyboard, and disabled controls never execute', async () => {
    const user = userEvent.setup(), click = vi.fn();
    const view = render(<PixelButton onClick={click}>Continue</PixelButton>);
    await user.tab(); await user.keyboard('{Enter}'); expect(click).toHaveBeenCalledTimes(1);
    view.rerender(<PixelButton disabled onClick={click}>Continue</PixelButton>);
    await user.click(screen.getByRole('button')); expect(click).toHaveBeenCalledTimes(1);
  });
  it('keeps panel variants, custom styles and status labels', () => {
    const view = render(<PixelPanel title="Review" variant="active" accent="mint" style={{ height: 120 }}>
      <PixelBadge status="blocked" label="Approval pending" /></PixelPanel>);
    expect(screen.getByText('Review')).toBeTruthy(); expect(screen.getByText('Approval pending')).toBeTruthy();
    expect(view.container.firstElementChild?.getAttribute('style')).toContain('height: 120px');
    expect(view.container.querySelector('[data-status="blocked"]')).toBeTruthy();
  });
  it('commits an inline rename once across Enter and blur, without swallowing failures', async () => {
    const user = userEvent.setup(), pending = deferred<{ ok: boolean; error?: string }>(), commit = vi.fn(() => pending.promise);
    render(<AgentNameEditor name="Coder" onCommit={commit} />);
    await user.click(screen.getByRole('button', { name: 'Rename Coder' }));
    const input = screen.getByRole('textbox'); await user.clear(input); await user.type(input,'Builder');
    await user.keyboard('{Enter}'); fireEvent.blur(input); expect(commit).toHaveBeenCalledExactlyOnceWith('Builder');
    await act(async () => pending.resolve({ ok: false, error: 'Try another name' }));
    expect(screen.getByRole('textbox').getAttribute('title')).toBe('Try another name');
    expect(screen.getByRole('textbox').getAttribute('aria-invalid')).toBe('true');
  });
  it('IME confirmation and Escape never rename the agent', async () => {
    const user = userEvent.setup(), commit = vi.fn(async () => ({ ok: true }));
    render(<AgentNameEditor name="Coder" onCommit={commit} />);
    await user.click(screen.getByRole('button')); const input = screen.getByRole('textbox');
    fireEvent.keyDown(input,{ key: 'Enter', isComposing: true, keyCode: 229 }); expect(commit).not.toHaveBeenCalled();
    await user.keyboard('{Escape}'); expect(screen.queryByRole('textbox')).toBeNull(); expect(commit).not.toHaveBeenCalled();
  });
  it('maintains card dimensions, selection, bounded context gauge and separate task controls', async () => {
    const user = userEvent.setup(), select = vi.fn(), task = vi.fn();
    render(<AgentCard name="Coder" character="byte" accent="coral" status="working" project="repo" action="Edit"
      progress={12} selected doingCount={2} onClick={select} onTaskNoteClick={task} />);
    const card = screen.getByRole('button',{ name: /CODER/ });
    expect(card.style.width).toBe('220px'); expect(card.style.height).toBe('78px'); expect(card.getAttribute('aria-current')).toBe('true');
    expect(screen.getByRole('meter').getAttribute('aria-valuenow')).toBe('100');
    await user.click(screen.getByRole('button',{ name: '2' })); expect(task).toHaveBeenCalledOnce(); expect(select).not.toHaveBeenCalled();
    card.focus(); await user.keyboard(' '); expect(select).toHaveBeenCalledOnce();
  });
  it('switches both themes without replacing or dropping the agent roster', async () => {
    const user = userEvent.setup(), agents = useStore.getState().agents;
    render(<OfficeThemePicker />); await user.click(screen.getByRole('button',{ name: 'off' }));
    await user.click(screen.getByRole('button',{ name: /Atrium/ })); expect(useStore.getState().officeTheme).toBe('atrium');
    expect(useStore.getState().agents).toBe(agents);
    await user.click(screen.getByRole('button',{ name: 'on' })); expect(useStore.getState().officeTheme).toBe('studio');
  });
});

describe('task contracts and safe document rendering', () => {
  it('normalizes malformed records deterministically and preserves dismissed question history', () => {
    const input = { tasks: [null, { title: 'Repair', dependsOn: ['x',2], priority: NaN,
      humanQA: [{ q: 'Earlier?', a: 'yes' }, { q: 'Dismissed?', dismissedAt: 'today' }, { q: 2 }] }] };
    const first = parseTasks(input), second = parseTasks(input);
    expect(first).toEqual(second); expect(first).toHaveLength(1); expect(first[0].dependsOn).toEqual(['x']);
    expect(first[0].priority).toBe(3); expect(openQuestion(first[0])).toBeUndefined();
    expect(waitsOnHuman({ ...first[0], status: 'blocked', humanQA: [{ q: 'Approve?' }] })).toBe(true);
  });
  it('renders task dependencies and question history without executing markup', () => {
    const task = parseTasks({ tasks: [{ id: 't1', title: 'Repair', status: 'blocked', description: '<script>x()</script>',
      dependsOn: ['t2'], humanQA: [{ q: '**Question**', a: 'Answer' }] }, { id: 't2', title: 'Dependency' }] });
    const view = render(<TaskDetail task={task[0]} all={task} onClose={() => undefined} onMove={() => undefined} onAssign={() => undefined} />);
    expect(screen.getByText('Dependency')).toBeTruthy(); expect(screen.getByText('Question')).toBeTruthy();
    expect(view.container.querySelector('script')).toBeNull(); expect(screen.getByText('<script>x()</script>')).toBeTruthy();
  });
  it('opens external and sibling document links while blocking HTML, remote image loads and schemes', async () => {
    const external = vi.spyOn(window.cth,'openExternal').mockResolvedValue({ ok: true }), open = vi.fn();
    const user = userEvent.setup();
    const view = render(<MarkdownPreview source={'[docs](guide.md) [web](https://example.org) [bad](javascript:alert(1))\n\n![remote](https://example.org/image.png)\n\n<script>alert(1)</script>'}
      baseRel="docs/readme.md" onOpenMarkdownLink={open} />);
    await user.click(screen.getByText('docs')); expect(open).toHaveBeenCalledExactlyOnceWith('docs/guide.md');
    await user.click(screen.getByText('web')); expect(external).toHaveBeenCalledExactlyOnceWith('https://example.org');
    expect(view.container.querySelector('script,img')).toBeNull(); expect(screen.getByText('bad').getAttribute('href')).toBeNull();
  });
  it('retains light/dark appearance values and injects a single stylesheet', () => {
    installThemeTokens(document); installThemeTokens(document);
    expect(document.querySelectorAll('#agentlab-appearance')).toHaveLength(1);
    expect(themeCss()).toContain('--cth-cream-100:#FFF8E7'); expect(themeCss()).toContain('[data-cth-theme="dark"]');
  });
  it('switches English/Chinese without losing the original language preference', async () => {
    await act(async () => { setLanguage('zh-CN'); }); expect(document.documentElement.lang).toBe('zh-CN');
    expect(i18n.t('lab.approve')).not.toBe('lab.approve'); expect(document.documentElement.dir).toBe('ltr');
    setLanguage('unsupported'); expect(i18n.language).toBe('zh-CN'); setLanguage('en');
  });
});

describe('replacement asynchronous readers', () => {
  it('discards a late poll reply from the old agent and stops polling after unmount', async () => {
    const old = deferred<string>(), next = deferred<string>();
    const hook = renderHook(({ id }) => usePoll(() => id === 'old' ? old.promise : next.promise, '', 10000, id), { initialProps: { id: 'old' } });
    hook.rerender({ id: 'new' }); await act(async () => next.resolve('new reply'));
    expect(hook.result.current).toBe('new reply'); await act(async () => old.resolve('stale reply'));
    expect(hook.result.current).toBe('new reply'); hook.unmount();
  });
  it('revokes a completed image URL and never creates a URL for an aborted request', async () => {
    const create = vi.fn(() => 'blob:picture'), revoke = vi.fn();
    vi.stubGlobal('URL', class extends URL { static createObjectURL = create; static revokeObjectURL = revoke; });
    const pending = deferred<Awaited<ReturnType<Window['cth']['readBinary']>>>();
    const read = vi.spyOn(window.cth,'readBinary').mockReturnValueOnce(pending.promise).mockResolvedValueOnce({ ok: true,
      bytes: new Uint8Array([1]), mime: 'image/png', path: 'two.png', size: 1 });
    const hook = renderHook(({ path }) => useWorkspaceImage('project',path),{ initialProps: { path: 'one.png' } });
    hook.rerender({ path: 'two.png' }); await waitFor(() => expect(hook.result.current.status).toBe('ready'));
    await act(async () => pending.resolve({ ok: true, bytes: new Uint8Array([1]), mime: 'image/png', path: 'one.png', size: 1 }));
    expect(create).toHaveBeenCalledOnce(); expect(read.mock.calls[0][2]?.aborted).toBe(true);
    hook.unmount(); expect(revoke).toHaveBeenCalledExactlyOnceWith('blob:picture'); vi.unstubAllGlobals();
  });
  it('keeps new telemetry when an older snapshot arrives and merges replayed tool results once', () => {
    const empty: FleetTelemetry = { samples: {}, spark: {}, rate: {}, lastTool: {}, breakers: {} };
    const sample: AgentUsageSample = { agentId: 'coder', sessionId: 's', ts: 1000, input: 20, output: 10,
      cacheRead: 0, cacheCreation: 0, model: 'm', usd: 0 };
    const first = foldUsage(empty,sample), next = foldUsage(first,{ ...sample, ts: 2000, output: 30 });
    expect(next.rate.coder).toBe(1200); expect(foldUsage(next,sample)).toBe(next);
    expect(foldUsage(first,{ ...sample, output: 50 }).samples.coder.output).toBe(50);
    const span = { agentId: 'coder', sessionId: 's', ts: 1, tool: 'Read', success: true, durationMs: 20 };
    expect(mergeSpans([span],[span])).toEqual([span]);
  });
});
