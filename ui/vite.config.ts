import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath, URL } from 'node:url';
import { readFileSync } from 'node:fs';

export default defineConfig({
  plugins: [react(), {
    name: 'distribute-license-notices',
    generateBundle() {
      const texts = ['./THIRD_PARTY_NOTICES.md', './src/assets/LICENSE.txt', './src/assets/fonts/LICENSE.txt']
        .map((path) => readFileSync(new URL(path, import.meta.url), 'utf8'));
      this.emitFile({ type: 'asset', fileName: 'THIRD_PARTY_NOTICES.txt', source: texts.join('\n\n') });
    },
  }],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
      '@shared': fileURLToPath(new URL('./src/shared', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: { '/api': { target: process.env.AGENTLAB_API_TARGET ?? 'http://127.0.0.1:8765', rewrite: (p) => p.replace(/^\/api/, '') } },
  },
  test: { environment: 'node', include: ['src/**/*.test.{ts,tsx}'] },
});
