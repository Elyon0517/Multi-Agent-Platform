import { expect, test } from '@playwright/test';
import { mkdirSync } from 'node:fs';

// Opt-in: this test needs the real API. The default office suite uses UI fixtures.
test('a real Gate failure converges through review to an in-place delivery', async ({ page, request }) => {
  test.skip(!process.env.AGENTLAB_SHOWCASE_E2E, 'Run npm run test:showcase for the API-backed walkthrough.');
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/?follow=1');
  await expect(page.getByRole('region', { name: 'Office floor' }).locator('canvas')).toBeVisible();
  await expect.poll(async () => {
    const runs = await (await request.get('/api/runs')).json();
    return runs[0]?.status;
  }, { timeout: 60000, intervals: [200] }).toBe('REVIEWING');
  mkdirSync('../docs/screenshots', { recursive: true });
  await page.screenshot({ path: '../docs/screenshots/office-review.png' });
  await expect.poll(async () => {
    const runs = await (await request.get('/api/runs')).json();
    return runs[0]?.status;
  }, { timeout: 60000 }).toBe('DONE');
  const runs = await (await request.get('/api/runs')).json();
  expect(runs).toHaveLength(1);
  const response = await request.get(`/api/runs/${runs[0].id}`);
  const detail = await response.json();
  expect(detail.run.status).toBe('DONE');
  expect(detail.pending_approval).toBeNull();
  expect(detail.gate_reports.some((gate: { passed: boolean }) => !gate.passed)).toBe(true);
  expect(detail.gate_reports.at(-1).passed).toBe(true);
  expect(detail.iterations.length).toBeGreaterThan(1);
  expect(JSON.stringify(detail)).toContain('public function lacks a docstring');
  await expect(page.getByRole('button', { name: /\[S2\].*DONE/ })).toBeVisible();
  await page.screenshot({ path: '../docs/screenshots/completed-run.png' });
  expect(errors).toEqual([]);
});
