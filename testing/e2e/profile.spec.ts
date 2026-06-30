import { test, expect } from '@playwright/test'

import { readInfo, shot, waitAppReady } from '../utils/helpers'
import { ProfilePage, expectNoFatalError } from '../pages/pages'

test.describe('Profil', () => {
  test('TC-PROF-01 Profil menampilkan identitas akun', async ({ page }, testInfo) => {
    const info = readInfo()
    const profile = new ProfilePage(page)
    await profile.open()
    await waitAppReady(page)
    await shot(page, 'profile', 'view', testInfo)
    await expectNoFatalError(page)
    const body = await page.locator('body').innerText()
    // Email admin harus muncul di profil.
    expect(body, 'email akun tampil di profil').toContain(info.admin.email)
  })
})
