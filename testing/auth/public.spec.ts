import { test, expect } from '@playwright/test'

import { LoginPage } from '../pages/pages'
import { shot, captureConsole } from '../utils/helpers'

/**
 * Uji area PUBLIK (tanpa autentikasi): Landing, Login, validasi, redirect, 404.
 * CATATAN: percobaan login gagal dibatasi (≤1) — rate-limiter login mem-block
 * per-IP; di balik tunnel semua user berbagi IP, jadi jangan sampai threshold.
 */
test.describe('Publik & Autentikasi', () => {
  test('TC-AUTH-01 Landing /welcome tampil', async ({ page }, testInfo) => {
    const errs = captureConsole(page)
    await page.goto('/welcome', { waitUntil: 'domcontentloaded' })
    await shot(page, 'login', 'landing', testInfo)
    await expect(page).toHaveURL(/\/welcome/)
    await expect(page.locator('body')).toContainText(/ComputeHub/i)
    expect(errs.pageErrors, 'tidak ada JS pageerror').toEqual([])
  })

  test('TC-AUTH-02 Halaman Login tampil + field lengkap', async ({ page }, testInfo) => {
    const login = new LoginPage(page)
    await login.open()
    await shot(page, 'login', 'login-form', testInfo)
    await expect(login.email).toBeVisible()
    await expect(login.password).toBeVisible()
    await expect(login.submit).toBeVisible()
  })

  test('TC-AUTH-03 Toggle tampil/sembunyi password', async ({ page }, testInfo) => {
    const login = new LoginPage(page)
    await login.open()
    await login.password.fill('rahasia123')
    await expect(login.password).toHaveAttribute('type', 'password')
    await login.togglePw.click()
    await shot(page, 'login', 'password-shown', testInfo)
    await expect(login.password).toHaveAttribute('type', 'text')
  })

  test('TC-AUTH-04 Validasi form kosong (HTML5 required)', async ({ page }, testInfo) => {
    const login = new LoginPage(page)
    await login.open()
    await login.submit.click()
    // Tetap di /login karena field required mencegah submit.
    await expect(page).toHaveURL(/\/login/)
    const emailInvalid = await login.email.evaluate(
      (el: HTMLInputElement) => !el.validity.valid,
    )
    expect(emailInvalid, 'email required harus invalid saat kosong').toBeTruthy()
    await shot(page, 'login', 'empty-validation', testInfo)
  })

  test('TC-AUTH-05 Login salah menampilkan pesan error (1x attempt)', async ({ page }, testInfo) => {
    const login = new LoginPage(page)
    await login.open()
    await shot(page, 'login', 'before-invalid-login', testInfo)
    await login.login('qa.invalid@example.com', 'password-salah-xyz')
    await expect(login.error).toBeVisible({ timeout: 15_000 })
    await shot(page, 'login', 'after-invalid-login', testInfo)
    await expect(page).toHaveURL(/\/login/)
  })

  test('TC-AUTH-06 Rute terproteksi redirect saat belum login', async ({ page }, testInfo) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(800)
    await shot(page, 'login', 'protected-redirect', testInfo)
    await expect(page, 'harus diarahkan keluar dari dashboard').toHaveURL(/\/welcome|\/login/)
  })

  test('TC-AUTH-07 Halaman 404 untuk rute tak dikenal', async ({ page }, testInfo) => {
    await page.goto('/rute-ngawur-zzz-404', { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(500)
    await shot(page, 'login', 'not-found', testInfo)
    await expect(page.locator('body')).toContainText(/404|tidak ditemukan|not found/i)
  })
})
