import { afterEach, expect, it, vi } from 'vitest';
import { loadPrefs } from './prefs';

afterEach(() => vi.unstubAllGlobals());

it('migrates retired themes while preserving personal names and ordering', () => {
  vi.stubGlobal('localStorage', { getItem: () => JSON.stringify({ theme: 'retired-theme', names: { root: 'My Root' }, order: ['coder'] }) });
  expect(loadPrefs()).toMatchObject({ theme: 'studio', names: { root: 'My Root' }, order: ['coder'] });
});

it('keeps the second original theme', () => {
  vi.stubGlobal('localStorage', { getItem: () => JSON.stringify({ theme: 'atrium' }) });
  expect(loadPrefs().theme).toBe('atrium');
});
