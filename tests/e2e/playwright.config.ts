import { defineConfig } from '@playwright/test';

// The stack is started by scripts/e2e.sh, which exports E2E_WEB_URL.
const baseURL = process.env.E2E_WEB_URL ?? 'http://127.0.0.1:15173';

export default defineConfig({
  testDir: '.',
  testMatch: '*.spec.ts',
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  // Both directories are gitignored (root .gitignore: playwright-report/, test-results/).
  outputDir: 'test-results',
  use: {
    baseURL,
    video: 'on',
    trace: 'on',
    screenshot: 'on',
    viewport: { width: 1280, height: 900 },
  },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
});
