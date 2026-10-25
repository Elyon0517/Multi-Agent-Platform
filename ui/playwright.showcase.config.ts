import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './e2e', testMatch: 'showcase.spec.ts', workers: 1, timeout: 120000,
  use: { baseURL: 'http://127.0.0.1:5185', viewport: { width: 1600, height: 1100 },
    trace: 'retain-on-failure', screenshot: 'only-on-failure',
    launchOptions: { args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] } },
  webServer: [
    { cwd: '..', command: 'uv run python scripts/showcase.py --only S2 --manual --speed 3 --port 8877',
      url: 'http://127.0.0.1:8877/health', timeout: 120000, reuseExistingServer: false },
    { command: 'npm run dev -- --host 127.0.0.1 --port 5185',
      env: { AGENTLAB_API_TARGET: 'http://127.0.0.1:8877' },
      url: 'http://127.0.0.1:5185', reuseExistingServer: false },
  ],
});
