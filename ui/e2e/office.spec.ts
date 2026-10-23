import { expect, test, type Page } from '@playwright/test';
const roster = ['root','planner','coder','correctness-reviewer'].map(role => ({ role, kind: 'worker', alias: 'fixture', model: 'offline', ctx_window: 1000 }));
async function fixture(page: Page, url = '/') {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.text().includes('PixiJS Deprecation')) errors.push(message.text()); });
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const path = new URL(route.request().url()).pathname;
    const body = path === '/api/roster' ? roster : path === '/api/health' ? { ok: true } : [];
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
  });
  await page.goto(url);
  await expect(page.locator('canvas').first()).toBeVisible();
  await page.evaluate(async () => {
    const module = '/src/store/store.ts';
    const { useStore } = await import(/* @vite-ignore */ module);
    const state = useStore.getState();
    useStore.setState({ agents: state.agents.map((a: { id: string }) => ({ ...a,
      status: a.id === 'coder' || a.id.endsWith('reviewer') ? 'working' : 'idle' })),
      tasks: [{ id: 'fixture-task', title: 'Review the SDK handoff', status: 'doing', assignee: 'coder',
        createdAt: '2026-10-23T00:00:00Z', dependsOn: [], priority: 3, description: 'Preserve revision consistency.' }] });
  });
  await page.waitForTimeout(600);
  await expect(page.getByRole('region',{ name: 'Office floor' }).getByRole('alert')).toHaveCount(0);
  return errors;
}

test('renders both room styles, preserves shell geometry and survives repeated remounts', async ({ page }, info) => {
  const errors = await fixture(page);
  const office = page.getByRole('region',{ name: 'Office floor' });
  const canvas = office.locator('canvas');
  await expect(canvas).toHaveCount(1);
  const box = await canvas.boundingBox(); expect(box!.width).toBeGreaterThan(200); expect(box!.height).toBeGreaterThan(300);
  await page.screenshot({ path: info.outputPath('studio.png'), fullPage: true });
  for (const theme of ['atrium','studio','atrium']) {
    await page.evaluate(async id => {
      const module = '/src/store/store.ts'; const { useStore } = await import(/* @vite-ignore */ module);
      useStore.getState().setOfficeTheme(id);
    },theme);
    await expect(canvas).toHaveCount(1); await page.waitForTimeout(350);
  }
  await page.screenshot({ path: info.outputPath('atrium.png'), fullPage: true });
  const minimize = page.getByRole('button',{ name: 'Minimize the office monitor' });
  await minimize.click(); await expect(office.locator('canvas')).toHaveCount(0);
  await page.getByRole('button',{ name: 'Show office', exact: true }).click();
  await expect(canvas).toHaveCount(1);
  await page.setViewportSize({ width: 700, height: 1000 });
  await page.waitForTimeout(300); await expect(canvas).toBeVisible();
  await page.screenshot({ path: info.outputPath('narrow.png'), fullPage: true });
  expect(errors).toEqual([]);
});

test('working agents leave, reappear, and rename without crashing the scene; task details stay usable', async ({ page }, info) => {
  const errors = await fixture(page);
  for (let n = 0; n < 4; n++) {
    await page.evaluate(async busy => {
      const module = '/src/store/store.ts'; const { useStore } = await import(/* @vite-ignore */ module);
      useStore.setState({ agents: useStore.getState().agents.map((agent: { id: string }) => ({ ...agent,
        status: agent.id === 'coder' ? busy ? 'working' : 'idle' : 'idle' })) });
    }, n % 2 === 1);
    await page.waitForTimeout(800);
  }
  const rename = page.getByRole('button',{ name: 'Rename Coder', exact: true });
  await rename.click(); const input = page.getByRole('textbox',{ name: 'Rename Coder', exact: true });
  await input.fill('Builder'); await input.press('Enter');
  await expect(page.getByRole('button',{ name: 'Rename Builder', exact: true })).toBeVisible();
  await page.getByRole('button',{ name: 'tasks', exact: true }).click();
  const floor = await page.getByRole('region',{ name: 'Office floor' }).locator('canvas').boundingBox();
  const scale = Math.min(floor!.width / (36 * 16), floor!.height / (26 * 16));
  await page.mouse.click(floor!.x + (floor!.width - 36 * 16 * scale) / 2 + 263 * scale,
    floor!.y + (floor!.height - 26 * 16 * scale) / 2 + 160 * scale);
  await expect(page.getByRole('button',{ name: 'Conversation', exact: true })).toHaveClass(/lab-button-primary/);
  await page.getByRole('button',{ name: 'tasks', exact: true }).click();
  await page.getByRole('button',{ name: /fixture-task/ }).click();
  await expect(page.getByRole('dialog',{ name: 'TASK', exact: true })).toBeVisible();
  await expect(page.getByText('Preserve revision consistency.')).toBeVisible();
  await page.getByRole('dialog').getByRole('button',{ name: 'close', exact: true }).click();
  await page.screenshot({ path: info.outputPath('tasks.png'), fullPage: true });
  expect(errors).toEqual([]);
});

// Optional migration acceptance: compare against a separately served pre-rewrite checkout.
// No old source is bundled in this repository or in the production application.
test('matches the previous console geometry and palette', async ({ page, context }, info) => {
  test.skip(!process.env.BASELINE_UI_URL, 'Set BASELINE_UI_URL to a pre-rewrite Vite server for migration acceptance.');
  await fixture(page);
  const before = await context.newPage(); await fixture(before, process.env.BASELINE_UI_URL);
  await page.bringToFront(); await page.waitForTimeout(2500);
  await before.bringToFront(); await before.waitForTimeout(2500);
  const geometry = async (view: Page) => ({
    office: await view.getByRole('region',{ name: 'Office floor' }).boundingBox(),
    canvas: await view.getByRole('region',{ name: 'Office floor' }).locator('canvas').boundingBox(),
    strip: await view.locator('[role="button"][draggable="true"]').first().boundingBox(),
    palette: await view.evaluate(() => ['--cth-cream-100','--cth-ink-900','--cth-mint','--cth-font-display'].map(name =>
      getComputedStyle(document.documentElement).getPropertyValue(name).trim())),
  });
  const current = await geometry(page), previous = await geometry(before);
  expect(current.office).toEqual(previous.office); expect(current.canvas).toEqual(previous.canvas);
  expect(current.palette).toEqual(previous.palette);
  expect(current.strip).toEqual(previous.strip);
  await page.bringToFront(); await page.waitForTimeout(600);
  await page.screenshot({ path: info.outputPath('after.png'), fullPage: true });
  await before.bringToFront(); await before.waitForTimeout(600);
  await before.screenshot({ path: info.outputPath('before.png'), fullPage: true });
  await before.close();
});
