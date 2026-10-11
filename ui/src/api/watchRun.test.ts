import { afterEach, expect, it, vi } from 'vitest';
import { watchRun } from './watchRun';

afterEach(() => vi.useRealTimers());

it('subscribes after recovery from an initial refresh failure and closes on cleanup', async () => {
  vi.useFakeTimers();
  const refresh = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValue(undefined);
  const close = vi.fn();
  const subscribe = vi.fn(() => close);
  const stop = watchRun(refresh, subscribe);
  await vi.advanceTimersByTimeAsync(0);
  expect(subscribe).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(3000);
  expect(subscribe).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(6000);
  expect(subscribe).toHaveBeenCalledTimes(1);
  stop();
  expect(close).toHaveBeenCalledTimes(1);
  const count = refresh.mock.calls.length;
  await vi.advanceTimersByTimeAsync(3000);
  expect(refresh).toHaveBeenCalledTimes(count);
});

it('does not overlap refreshes or subscribe when a pending refresh completes after cleanup', async () => {
  vi.useFakeTimers();
  let resolve!: () => void;
  const refresh = vi.fn(() => new Promise<void>((done) => { resolve = done; }));
  const subscribe = vi.fn(() => vi.fn());
  const stop = watchRun(refresh, subscribe);
  await vi.advanceTimersByTimeAsync(6000);
  expect(refresh).toHaveBeenCalledTimes(1);
  stop();
  resolve();
  await vi.advanceTimersByTimeAsync(0);
  expect(subscribe).not.toHaveBeenCalled();
});
