import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import type { FullConfig } from '@playwright/test'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const BACKEND = path.resolve(__dirname, '..', 'backend')
const VENV_PY = path.join(BACKEND, '.venv', 'bin', 'python')
const MINT = path.join(__dirname, 'scripts', 'mint_tokens.py')
const AUTH_DIR = path.join(__dirname, '.auth')
const BASE_URL = process.env.BASE_URL ?? 'http://127.0.0.1:8088'

/**
 * Global setup:
 *  1) Pastikan aplikasi hidup (GET /health).
 *  2) Mint token admin + student (NON-DESTRUKTIF) -> .auth/*.json (storageState).
 */
async function globalSetup(_config: FullConfig): Promise<void> {
  // 1) Health check — gagal cepat bila backend mati.
  let healthy = false
  for (let i = 0; i < 10 && !healthy; i++) {
    try {
      const res = await fetch(`${BASE_URL}/health`)
      healthy = res.ok
    } catch {
      await new Promise((r) => setTimeout(r, 1000))
    }
  }
  if (!healthy) {
    throw new Error(`Aplikasi tidak merespons di ${BASE_URL}/health — pastikan backend hidup.`)
  }

  // 2) Mint token via venv python (akses model & SECRET_KEY backend).
  if (!existsSync(VENV_PY)) {
    throw new Error(`Python venv tidak ditemukan: ${VENV_PY}`)
  }
  const out = execFileSync(VENV_PY, [MINT, AUTH_DIR], {
    cwd: BACKEND,
    encoding: 'utf-8',
    env: { ...process.env, PYTHONPATH: BACKEND },
  })
  // eslint-disable-next-line no-console
  console.log('[global-setup]', out.trim())
}

export default globalSetup
