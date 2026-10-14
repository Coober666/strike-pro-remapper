import { defineConfig, devices } from '@playwright/test';

const port = 8767;

export default defineConfig({
  testDir: './tests/browser',
  globalSetup: './tests/browser/global-setup.js',
  globalTeardown: './tests/browser/global-teardown.js',
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure'
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] }
    },
    {
      name: 'ipad-webkit',
      testMatch: ['**/factory-controller.spec.js', '**/wifi-editor.spec.js', '**/workflow-polish.spec.js', '**/zz-recovery-touch.spec.js', '**/midi-toolkit.spec.js', '**/wifi-midi.spec.js', '**/zz-setlists.spec.js', '**/zzz-release-polish.spec.js'],
      use: { ...devices['iPad Pro 11'], browserName: 'webkit' }
    }
  ]
});
