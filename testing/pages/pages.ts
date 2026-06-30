import { expect, type Locator, type Page } from '@playwright/test'

/** Dasar semua POM. */
export class BasePage {
  constructor(public readonly page: Page) {}

  async goto(pathname: string): Promise<void> {
    await this.page.goto(pathname, { waitUntil: 'domcontentloaded' })
    await this.page.waitForTimeout(600)
  }

  heading(name: RegExp | string): Locator {
    return this.page.getByRole('heading', { name }).first()
  }
}

/** Halaman Login (publik). */
export class LoginPage extends BasePage {
  get email(): Locator {
    return this.page.locator('#email')
  }
  get password(): Locator {
    return this.page.locator('#password')
  }
  get submit(): Locator {
    return this.page.getByRole('button', { name: /Masuk ke Dashboard|Masuk…/ })
  }
  get error(): Locator {
    return this.page.locator('.bg-rose-50')
  }
  get togglePw(): Locator {
    return this.page.getByRole('button', { name: /password/i })
  }

  async open(): Promise<void> {
    await this.goto('/login')
  }

  async login(email: string, password: string): Promise<void> {
    await this.email.fill(email)
    await this.password.fill(password)
    await this.submit.click()
  }
}

/** Sidebar / navigasi (Layout). */
export class NavBar extends BasePage {
  link(name: string): Locator {
    return this.page.getByRole('link', { name, exact: false }).first()
  }

  async open(name: string): Promise<void> {
    await this.link(name).click()
    await this.page.waitForTimeout(500)
  }

  /** Tombol logout (di menu user). Mengembalikan locator bila ada. */
  logoutButton(): Locator {
    return this.page.getByRole('button', { name: /Keluar|Logout/i }).first()
  }

  userMenuButton(): Locator {
    // tombol profil/menu user — fleksibel
    return this.page.getByRole('button', { name: /Profil|Akun|Menu|Keluar/i }).first()
  }
}

/** Dashboard. */
export class DashboardPage extends BasePage {
  async open(): Promise<void> {
    await this.goto('/')
  }
}

/** Daftar Job + filter/cari. */
export class JobsPage extends BasePage {
  async open(): Promise<void> {
    await this.goto('/jobs')
  }
  get table(): Locator {
    return this.page.locator('table').first()
  }
  get rows(): Locator {
    return this.page.locator('table tbody tr')
  }
  searchBox(): Locator {
    return this.page.getByPlaceholder(/cari|search/i).first()
  }
  statusFilter(): Locator {
    return this.page.locator('select').first()
  }
}

/** Penyimpanan (file browser /persist). */
export class StoragePage extends BasePage {
  async open(): Promise<void> {
    await this.goto('/storage')
  }
  uploadButton(): Locator {
    return this.page.getByRole('button', { name: /Unggah|Upload/i }).first()
  }
  fileInput(): Locator {
    return this.page.locator('input[type=file]')
  }
}

/** Laporan (admin) + seksi disk. */
export class ReportPage extends BasePage {
  async open(): Promise<void> {
    await this.goto('/report')
  }
  diskSection(): Locator {
    return this.page.locator('#disk')
  }
  downloadButton(): Locator {
    return this.page.getByRole('button', { name: /Unduh Laporan/i }).first()
  }
}

/** Pengguna (admin). */
export class UsersPage extends BasePage {
  async open(): Promise<void> {
    await this.goto('/users')
  }
  get table(): Locator {
    return this.page.locator('table').first()
  }
  searchBox(): Locator {
    return this.page.getByPlaceholder(/cari|search/i).first()
  }
  addButton(): Locator {
    return this.page.getByRole('button', { name: /Tambah|Buat|Baru/i }).first()
  }
}

/** Monitor (admin). */
export class MonitorPage extends BasePage {
  async open(): Promise<void> {
    await this.goto('/monitor')
  }
}

/** Peringatan (admin). */
export class AlertsPage extends BasePage {
  async open(): Promise<void> {
    await this.goto('/alerts')
  }
}

/** Profil. */
export class ProfilePage extends BasePage {
  async open(): Promise<void> {
    await this.goto('/profile')
  }
}

/** Submit (code/notebook/zip/github). */
export class SubmitPage extends BasePage {
  constructor(page: Page, public readonly source: string) {
    super(page)
  }
  async open(): Promise<void> {
    await this.goto(`/submit/${this.source}`)
  }
  submitButton(): Locator {
    return this.page.getByRole('button', { name: /Jalankan|Submit|Kirim|Mulai/i }).first()
  }
}

/** Util: cek tak ada teks error fatal khas React/error boundary. */
export async function expectNoFatalError(page: Page): Promise<void> {
  const body = (await page.locator('body').innerText().catch(() => '')) || ''
  expect(body).not.toMatch(/Something went wrong|Application error|Cannot read properties of/i)
}
