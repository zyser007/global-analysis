const { defineConfig } = require('@playwright/test');
const { PORTS } = require('./tests/helpers');

module.exports = defineConfig({
  testDir: './tests',
  timeout: 120000,
  retries: 0,
  workers: 1,               // live.spec rewrites the mutable server's files: keep tests serial
  fullyParallel: false,
  reporter: [['list']],
  outputDir: './test-results',
  use: {
    browserName: 'chromium',
    headless: true,
    // E2E_IGNORE_CERT_ERRORS=1 only inside the Managed Agents sandbox (editor-agent/e2e.sh sets it): its egress
    // re-signs TLS, so Chromium rejects cdnjs (three.js). Every other request in these tests is plain http to 127.0.0.1.
    launchOptions: { args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']
      .concat(process.env.E2E_IGNORE_CERT_ERRORS === '1' ? ['--ignore-certificate-errors'] : []) },
  },
  webServer: Object.entries(PORTS).map(([mode, port]) => ({
    command: `python3 serve.py ${mode} ${port}`,
    url: `http://127.0.0.1:${port}/global-analysis/`,
    reuseExistingServer: false,
    timeout: 20000,
    stdout: 'ignore',
  })),
});
