import { existsSync, mkdirSync, readFileSync } from 'node:fs'
import path from 'node:path'

import type { Page, TestInfo, APIRequestContext } from '@playwright/test'

import { API_PREFIX, INFO_FILE, SCREENSHOT_DIR, type AuthInfo } from './constants'

/** Baca metadata akun uji (id/email/username admin & student). */
export function readInfo(): AuthInfo {
  return JSON.parse(readFileSync(INFO_FILE, 'utf-8')) as AuthInfo
}

/** Baca token bearer dari storageState (untuk uji API langsung). */
export function tokenFromState(stateFile: string): string {
  const st = JSON.parse(readFileSync(stateFile, 'utf-8')) as {
    origins: { localStorage: { name: string; value: string }[] }[]
  }
  const ls = st.origins[0]?.localStorage ?? []
  const tok = ls.find((e) => e.name === 'unismuh_token')?.value
  if (!tok) throw new Error(`Token tidak ada di ${stateFile}`)
  return tok
}

/**
 * Ambil screenshot bernama & ter-organisir ke screenshots/<group>/<nama>.png,
 * sekaligus lampirkan ke laporan HTML (TestInfo.attach).
 */
export async function shot(
  page: Page,
  group: string,
  name: string,
  testInfo?: TestInfo,
): Promise<string> {
  const dir = path.join(SCREENSHOT_DIR, group)
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true })
  const safe = name.replace(/[^\w.-]+/g, '_')
  const file = path.join(dir, `${Date.now()}-${safe}.png`)
  try {
    await page.screenshot({ path: file, fullPage: false })
    if (testInfo) await testInfo.attach(`${group}/${safe}`, { path: file, contentType: 'image/png' })
  } catch {
    /* halaman mungkin sedang transisi — abaikan kegagalan screenshot */
  }
  return file
}

/** Pasang penangkap error console & pageerror; kembalikan array yang terisi seiring waktu. */
export function captureConsole(page: Page): { errors: string[]; pageErrors: string[] } {
  const errors: string[] = []
  const pageErrors: string[] = []
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(msg.text())
  })
  page.on('pageerror', (err) => pageErrors.push(String(err)))
  return { errors, pageErrors }
}

/** Helper request API ber-otorisasi. */
export async function apiGet(
  request: APIRequestContext,
  pathname: string,
  token?: string,
) {
  return request.get(`${API_PREFIX}${pathname}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
}

export async function apiPost(
  request: APIRequestContext,
  pathname: string,
  body: unknown,
  token?: string,
) {
  return request.post(`${API_PREFIX}${pathname}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    data: body as Record<string, unknown>,
  })
}

/** Tunggu app SPA selesai boot (token ter-inject -> render terotentikasi). */
export async function waitAppReady(page: Page): Promise<void> {
  await page.waitForLoadState('domcontentloaded')
  // Beri waktu React render + fetch /auth/me.
  await page.waitForTimeout(800)
}

/** Tunggu shell terotentikasi (sidebar/navigasi) benar-benar tampil. */
export async function waitForShell(page: Page): Promise<void> {
  await page.waitForLoadState('domcontentloaded')
  await page
    .getByRole('navigation')
    .first()
    .waitFor({ state: 'visible', timeout: 15_000 })
    .catch(() => {
      /* mungkin viewport mobile (bottom-nav) — abaikan */
    })
  await page.waitForTimeout(400)
}
