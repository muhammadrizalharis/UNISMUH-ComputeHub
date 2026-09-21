import { test, expect } from '@playwright/test'

import { STUDENT_STATE } from '../utils/constants'
import { shot } from '../utils/helpers'
import { expectNoFatalError } from '../pages/pages'

/**
 * UI DEVBOX — halaman "ngoding di VS Code sendiri, sumber daya server".
 *
 * NON-DESTRUKTIF: hanya membuka halaman & memeriksa tampilan awal (devbox TIDAK
 * dinyalakan di sini supaya suite tak menahan resource; alur nyala/mati diuji di
 * `api/devbox.spec.ts`). Memakai storageState mahasiswa = memastikan fitur ini
 * memang terlihat oleh mahasiswa, bukan hanya admin.
 */

test.describe('Devbox VS Code (UI)', () => {
  test('TC-DEVBOX-UI-01 menu Devbox tampil & halaman menjelaskan cara pakai', async ({
    browser,
  }, testInfo) => {
    const ctx = await browser.newContext({ storageState: STUDENT_STATE })
    const page = await ctx.newPage()
    try {
      await page.goto('/devbox', { waitUntil: 'domcontentloaded' })

      // Menu sidebar tersedia untuk mahasiswa.
      await expect(page.getByRole('link', { name: /Devbox/i }).first()).toBeVisible()

      // Judul & penjelasan inti (mengapa fitur ini ada) muncul.
      await expect(page.getByRole('heading', { level: 1 })).toContainText(/Devbox/i)
      await expect(page.getByText(/sumber daya|CPU, RAM, dan GPU/i).first()).toBeVisible()

      // Kontrol utama: tombol nyalakan saja — pilihan CPU/GPU sengaja DIHAPUS karena
      // perangkat kini ditentukan otomatis oleh server.
      const tombolNyala = page.getByRole('button', { name: /Nyalakan devbox/i })
      const sudahJalan = await page.getByText(/Menyala|Menyiapkan|Menunggu otorisasi/i).count()
      if (sudahJalan === 0) {
        await expect(tombolNyala).toBeVisible()
        await expect(page.getByRole('button', { name: /CPU saja/i })).toHaveCount(0)
        await expect(page.getByText(/GPU diberikan otomatis/i).first()).toBeVisible()
      }

      await shot(page, 'devbox', 'devbox-ui', testInfo)
      await expectNoFatalError(page)
    } finally {
      await ctx.close()
    }
  })

  test('TC-DEVBOX-UI-02 koneksi terputus dan tersambung ulang tampil di desktop dan mobile', async ({ browser }, testInfo) => {
    const ctx = await browser.newContext({ storageState: STUDENT_STATE })
    const page = await ctx.newPage()
    let connected = false
    await page.route('**/api/v1/devbox', (route) => route.fulfill({
      json: {
        user_id: 24,
        state: 'running',
        enabled: true,
        device: 'gpu',
        folder: 'CH-qastudent',
        tunnel_name: 'computehub-qa',
        client_connected: connected,
        disconnect_timeout_seconds: 120,
        disconnect_remaining_seconds: connected ? null : 65,
        idle_timeout_seconds: 1800,
        max_lifetime_seconds: 43200,
      },
    }))
    try {
      await page.goto('/devbox', { waitUntil: 'domcontentloaded' })
      for (const viewport of [{ width: 1280, height: 900 }, { width: 390, height: 844 }]) {
        await page.setViewportSize(viewport)
        await expect(page.getByText('Koneksi VS Code: Terputus', { exact: true })).toBeVisible()
        await expect(page.getByRole('status')).toContainText('65 detik')
        await expect(page.getByText(/semua koneksi VS Code terputus selama/)).toContainText('2 menit')
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
        await shot(page, 'devbox', `disconnect-${viewport.width}`, testInfo)
      }
      connected = true
      await page.getByRole('button', { name: 'Segarkan', exact: true }).click()
      await expect(page.getByText('Koneksi VS Code: Tersambung', { exact: true })).toBeVisible()
      await expect(page.getByRole('status')).toHaveCount(0)
      await expectNoFatalError(page)
    } finally {
      await ctx.close()
    }
  })

  test('TC-DEVBOX-UI-03 tunnel Desktop utama + browser opsional', async ({ browser }, testInfo) => {
    const ctx = await browser.newContext({ storageState: STUDENT_STATE })
    const page = await ctx.newPage()
    let tunnelState: string = 'off'
    let tunnelStarts = 0
    let tickets = 0
    const status = () => ({
      user_id: 24,
      state: 'running',
      enabled: true,
      web_enabled: true,
      web_url: '/devbox-ide/24/',
      ssh_enabled: false, // Remote-SSH dimatikan -> tunnel jadi jalur Desktop utama
      tunnel_state: tunnelState,
      tunnel_name: 'computehub-24',
      tunnel_url: tunnelState === 'running' ? 'https://vscode.dev/tunnel/computehub-24' : '',
      device_code: tunnelState === 'needs_login' ? 'ABCD-1234' : '',
      verification_url: tunnelState === 'needs_login' ? 'https://github.com/login/device' : '',
      device: 'cpu',
      folder: 'CH-qastudent',
      client_connected: true,
      disconnect_timeout_seconds: 120,
      idle_timeout_seconds: 3600,
      max_lifetime_seconds: 43200,
    })
    await page.route('**/api/v1/devbox', (route) => route.fulfill({ json: status() }))
    await page.route('**/api/v1/devbox/web-ticket', (route) => {
      tickets++
      return route.fulfill({ json: { url: '/devbox-ide/24/?ch_ticket=uji', path: '/devbox-ide/24/' } })
    })
    await page.route('**/api/v1/devbox/tunnel/start', (route) => {
      tunnelStarts++
      tunnelState = 'needs_login'
      return route.fulfill({ json: status() })
    })
    await page.route('**/devbox-ide/24/**', (route) => route.fulfill({ status: 200, contentType: 'text/html', body: '<title>IDE</title>' }))
    try {
      await page.goto('/devbox', { waitUntil: 'domcontentloaded' })

      // Tunnel = jalur UTAMA: tombolnya langsung terlihat tanpa membuka apa pun.
      await expect(page.getByText('Cara utama', { exact: true })).toBeVisible()
      const tunnelBtn = page.getByTestId('devbox-start-tunnel')
      await expect(tunnelBtn).toBeVisible()

      await tunnelBtn.click()
      expect(tunnelStarts).toBe(1)
      await page.getByRole('button', { name: 'Segarkan', exact: true }).click()
      await expect(page.getByText('ABCD-1234')).toBeVisible()
      await expect(page.getByRole('link', { name: /github\.com\/login\/device/ })).toBeVisible()

      tunnelState = 'running'
      await page.getByRole('button', { name: 'Segarkan', exact: true }).click()
      await expect(page.getByText('Remote Tunnels: Connect to Tunnel', { exact: true })).toBeVisible()
      await expect(page.getByRole('link', { name: /vscode\.dev \(lewat Microsoft\)/ })).toHaveAttribute(
        'href', 'https://vscode.dev/tunnel/computehub-24',
      )

      // Browser = OPSIONAL: tersembunyi di balik "Lihat cara".
      await expect(page.getByTestId('devbox-open-web')).toHaveCount(0)
      await page.getByRole('button', { name: /Buka di browser \(opsional\)/ }).click()
      const tombol = page.getByTestId('devbox-open-web')
      await expect(tombol).toBeVisible()
      const popup = page.waitForEvent('popup')
      await tombol.click()
      const tab = await popup
      await tab.waitForLoadState('domcontentloaded')
      expect(tickets).toBe(1)
      expect(tab.url()).toMatch(/\/devbox-ide\/24\/\?ch_ticket=uji$/)
      await tab.close()

      // Devbox tetap 'Menyala' sepanjang proses tunnel — tunnel tak pernah menggeser status utama.
      await expect(page.getByText('Menyala', { exact: true })).toBeVisible()
      await shot(page, 'devbox', 'tunnel-primary', testInfo)
      await expectNoFatalError(page)
    } finally {
      await ctx.close()
    }
  })

  test('TC-DEVBOX-UI-04 VS Code Desktop jadi jalur utama: satu pemasang, tanpa mengatur SSH sendiri', async ({
    browser,
  }, testInfo) => {
    const ctx = await browser.newContext({ storageState: STUDENT_STATE })
    const page = await ctx.newPage()
    let unduhan = 0
    let rotasi = 0
    await page.route('**/api/v1/devbox', (route) =>
      route.fulfill({
        json: {
          user_id: 24,
          state: 'running',
          enabled: true,
          web_enabled: true,
          web_url: '/devbox-ide/24/',
          ssh_enabled: true,
          ssh_ready: true,
          ssh_host: 'computehub-24',
          tunnel_state: 'off',
          device: 'cpu',
          folder: 'CH-qastudent',
          client_connected: true,
          disconnect_timeout_seconds: 120,
          idle_timeout_seconds: 3600,
          max_lifetime_seconds: 43200,
        },
      }),
    )
    await page.route('**/api/v1/devbox/desktop-setup**', (route) => {
      unduhan++
      return route.fulfill({
        status: 200,
        contentType: 'application/octet-stream',
        headers: { 'content-disposition': 'attachment; filename="computehub-24-setup.sh"' },
        body: '# pemasang uji',
      })
    })
    await page.route('**/api/v1/devbox/desktop-key/rotate', (route) => {
      rotasi++
      return route.fulfill({ status: 204, body: '' })
    })
    try {
      await page.goto('/devbox', { waitUntil: 'domcontentloaded' })

      // Jalur utama: langsung terlihat tanpa perlu membuka apa pun.
      await expect(page.getByText('Cara utama', { exact: true })).toBeVisible()
      await expect(page.getByTestId('devbox-setup-windows')).toBeVisible()
      // Janji utamanya: tanpa GitHub/VPN dan tanpa menyunting konfigurasi SSH.
      await expect(page.getByText(/tanpa perlu WiFi kampus atau VPN/i)).toBeVisible()
      // Cukup dobel-klik pemasang lalu satu tombol; tidak ada hafalan perintah F1.
      await expect(page.getByText('dobel-klik', { exact: true })).toBeVisible()
      await expect(page.getByTestId('devbox-open-desktop')).toHaveAttribute(
        'href',
        'vscode://vscode-remote/ssh-remote+computehub-24/CH-qastudent',
      )
      // Browser turun jadi pelengkap, tapi tetap sekali klik.
      await expect(page.getByTestId('devbox-open-web')).toBeVisible()

      const unduh = page.waitForEvent('download')
      await page.getByTestId('devbox-setup-windows').click()
      expect((await unduh).suggestedFilename()).toMatch(/setup\.(cmd|sh)$/)
      expect(unduhan).toBe(1)

      // "Laptop hilang" harus minta konfirmasi dulu -> tidak mencabut akses tak sengaja.
      page.once('dialog', (d) => void d.accept())
      await page.getByTestId('devbox-rotate-key').click()
      await expect(page.getByRole('status')).toContainText(/Kunci baru/i)
      expect(rotasi).toBe(1)

      // Tunnel Microsoft turun jadi "cara lama" yang terlipat (ada di DOM, tak terlihat).
      await expect(page.getByTestId('devbox-start-tunnel')).toBeHidden()
      await expect(page.getByText(/Cara lama: tunnel Microsoft/)).toBeVisible()
      await shot(page, 'devbox', 'desktop-ssh', testInfo)
      await expectNoFatalError(page)
    } finally {
      await ctx.close()
    }
  })
})
