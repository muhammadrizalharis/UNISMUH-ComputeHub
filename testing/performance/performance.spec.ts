import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { test, expect, request as pwRequest } from '@playwright/test'

import { API_PREFIX, BASE_URL, ADMIN_STATE } from '../utils/constants'
import { tokenFromState, waitAppReady } from '../utils/helpers'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const PERF_DIR = path.resolve(__dirname, '..', 'reports', 'perf')

function writeMetric(name: string, data: Record<string, unknown>): void {
  if (!existsSync(PERF_DIR)) mkdirSync(PERF_DIR, { recursive: true })
  writeFileSync(path.join(PERF_DIR, `${name}.json`), JSON.stringify(data, null, 2))
}

const ROUTES = ['/', '/jobs', '/storage', '/report', '/monitor']

test.describe('Performa', () => {
  for (const route of ROUTES) {
    test(`PERF-PAGE ${route} waktu muat`, async ({ page }, testInfo) => {
      const start = Date.now()
      await page.goto(route, { waitUntil: 'load' })
      await waitAppReady(page)
      const wall = Date.now() - start
      const nav = await page.evaluate(() => {
        const e = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined
        if (!e) return null
        return {
          domContentLoaded: Math.round(e.domContentLoadedEventEnd),
          loadEvent: Math.round(e.loadEventEnd),
          responseEnd: Math.round(e.responseEnd),
          transferSize: e.transferSize,
        }
      })
      const metric = { route, wallMs: wall, nav }
      writeMetric(`page${route === '/' ? '_root' : route.replace(/\//g, '_')}`, metric)
      await testInfo.attach(`perf${route}`, {
        body: JSON.stringify(metric, null, 2),
        contentType: 'application/json',
      })
      // eslint-disable-next-line no-console
      console.log(`[perf] ${route} wall=${wall}ms`, nav)
      expect.soft(wall, `muat ${route} < 10s`).toBeLessThan(10_000)
    })
  }

  test('PERF-API latensi endpoint inti', async () => {
    const tok = tokenFromState(ADMIN_STATE)
    const ctx = await pwRequest.newContext()
    const endpoints: { name: string; url: string; auth?: boolean }[] = [
      { name: 'health', url: `${BASE_URL}/health` },
      { name: 'me', url: `${API_PREFIX}/auth/me`, auth: true },
      { name: 'report', url: `${API_PREFIX}/admin/report`, auth: true },
      { name: 'report_disk', url: `${API_PREFIX}/admin/report/disk`, auth: true },
    ]
    const results: Record<string, number> = {}
    for (const ep of endpoints) {
      const t0 = Date.now()
      const res = await ctx.get(ep.url, {
        headers: ep.auth ? { Authorization: `Bearer ${tok}` } : {},
      })
      results[ep.name] = Date.now() - t0
      expect.soft(res.status(), `${ep.name} status`).toBeLessThan(500)
    }
    await ctx.dispose()
    writeMetric('api_latency', results)
    // eslint-disable-next-line no-console
    console.log('[perf api]', results)
  })

  test('PERF-CONCURRENCY sampling RINGAN (5 paralel) — load berat SENGAJA dihindari', async () => {
    // Server PRODUKSI bersama: load test 20/50 user bisa men-DoS user nyata.
    // Hanya 5 request /health paralel sebagai sampel sehat.
    const ctx = await pwRequest.newContext()
    const t0 = Date.now()
    const res = await Promise.all(
      Array.from({ length: 5 }, () => ctx.get(`${BASE_URL}/health`)),
    )
    const elapsed = Date.now() - t0
    await ctx.dispose()
    expect(res.every((r) => r.status() === 200)).toBeTruthy()
    writeMetric('concurrency_light', { parallel: 5, totalMs: elapsed })
    // eslint-disable-next-line no-console
    console.log(`[perf concurrency] 5 paralel /health = ${elapsed}ms`)
  })
})
