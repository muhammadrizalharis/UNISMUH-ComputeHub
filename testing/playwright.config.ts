import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { defineConfig, devices } from '@playwright/test'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const BASE_URL = process.env.BASE_URL ?? 'http://127.0.0.1:8088'
const ADMIN_STATE = path.join(__dirname, '.auth', 'admin.json')
const STUDENT_STATE = path.join(__dirname, '.auth', 'student.json')

/**
 * Konfigurasi E2E UNISMUH ComputeHub.
 *
 * Catatan operasional:
 *  - Server PRODUKSI bersama -> workers dibatasi (2) agar tidak membebani user nyata.
 *  - Server HEADLESS (DISPLAY kosong) -> headless:true. "Tonton" via video + trace +
 *    screenshot (HTML report memutar ulang setiap langkah).
 *  - slowMo 200ms agar interaksi terlihat jelas pada rekaman.
 */
export default defineConfig({
  testDir: '.',
  globalSetup: './global-setup.ts',
  fullyParallel: false,
  forbidOnly: false,
  retries: 1, // retry sekali untuk meredam flaky (jaringan/animasi)
  workers: 2, // hemat — jangan DoS server bersama
  timeout: 60_000,
  expect: { timeout: 10_000 },
  outputDir: 'test-results',
  reporter: [
    ['list'],
    ['html', { outputFolder: 'reports/html-report', open: 'never' }],
    ['junit', { outputFile: 'reports/junit/results.xml' }],
    ['json', { outputFile: 'reports/json/results.json' }],
  ],
  use: {
    baseURL: BASE_URL,
    headless: true,
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    trace: 'on',
    video: 'on',
    screenshot: 'on',
    launchOptions: { slowMo: 200 },
    ignoreHTTPSErrors: true,
  },
  projects: [
    // --- Tanpa autentikasi (publik) ---
    {
      name: 'public',
      testMatch: /auth\/.*\.spec\.ts$/,
      use: { ...devices['Desktop Chrome'], storageState: { cookies: [], origins: [] } },
    },
    // --- API langsung (bearer di-handle di dalam spec) ---
    {
      name: 'api',
      testMatch: /api\/.*\.spec\.ts$/,
      use: { ...devices['Desktop Chrome'] },
    },
    // --- Security (membuat context sendiri per peran) ---
    {
      name: 'security',
      testMatch: /security\/.*\.spec\.ts$/,
      use: { ...devices['Desktop Chrome'], storageState: { cookies: [], origins: [] } },
    },
    // --- UI utama sebagai ADMIN, desktop ---
    {
      name: 'desktop',
      testMatch: /e2e\/.*\.spec\.ts$/,
      testIgnore: /responsive\.spec\.ts$/,
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
        storageState: ADMIN_STATE,
      },
    },
    // --- Responsive: mobile ---
    {
      name: 'mobile',
      testMatch: /e2e\/responsive\.spec\.ts$/,
      use: {
        ...devices['Pixel 7'],
        storageState: ADMIN_STATE,
      },
    },
    // --- Responsive: tablet ---
    {
      name: 'tablet',
      testMatch: /e2e\/responsive\.spec\.ts$/,
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 820, height: 1180 },
        storageState: ADMIN_STATE,
      },
    },
    // --- Performa (ADMIN) ---
    {
      name: 'performance',
      testMatch: /performance\/.*\.spec\.ts$/,
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
        storageState: ADMIN_STATE,
      },
    },
  ],
})

export { ADMIN_STATE, STUDENT_STATE, BASE_URL }
