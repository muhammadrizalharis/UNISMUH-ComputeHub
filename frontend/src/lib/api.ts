// Klien API terpusat untuk backend UNISMUH AI Cloud.

import type {
  Capabilities,
  Job,
  JobCreate,
  JobLogs,
  JobStatus,
  MonitoringOverview,
  QueueItem,
  ResourceSample,
  SystemSettings,
  SystemSnapshot,
  Token,
  Usage,
  User,
  UserPolicy,
  UserPolicyUpdate,
  UserRole,
  UserUsage,
  FullReport,
  UserReport,
  AlertConfig,
  AlertConfigUpdate,
  AlertItem,
  AlertRunResult,
  EmailTestResult,
} from './types'

const API_PREFIX = '/api/v1'
const TOKEN_KEY = 'unismuh_token'

// ---------------------------------------------------------------- token utils
export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

// ---------------------------------------------------------------- error type
export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

// Event global saat token tidak valid (didengar AuthProvider).
export const UNAUTHORIZED_EVENT = 'auth:unauthorized'

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken()
  const headers = new Headers(options.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (options.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const res = await fetch(`${API_PREFIX}${path}`, { ...options, headers })

  if (res.status === 401) {
    clearToken()
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
    throw new ApiError(401, 'Sesi berakhir. Silakan login kembali.')
  }

  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const data = await res.json()
      if (data?.detail) {
        detail =
          typeof data.detail === 'string'
            ? data.detail
            : JSON.stringify(data.detail)
      }
    } catch {
      /* abaikan body non-json */
    }
    throw new ApiError(res.status, detail)
  }

  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

// ---------------------------------------------------------------- endpoints
export const api = {
  // --- auth ---
  async login(email: string, password: string): Promise<Token> {
    const body = new URLSearchParams({ username: email, password })
    const res = await fetch(`${API_PREFIX}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body,
    })
    if (!res.ok) {
      let detail = 'Email atau password salah.'
      try {
        const d = await res.json()
        if (d?.detail) detail = d.detail
      } catch {
        /* noop */
      }
      throw new ApiError(res.status, detail)
    }
    return (await res.json()) as Token
  },

  me(): Promise<User> {
    return request<User>('/auth/me')
  },

  // --- users (admin) ---
  listUsers(): Promise<User[]> {
    return request<User[]>('/users?limit=200')
  },
  createUser(payload: {
    name: string
    email: string
    password: string
    role: UserRole
  }): Promise<User> {
    return request<User>('/users', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  updateUser(
    id: number,
    payload: Partial<{
      name: string
      password: string
      role: UserRole
      is_active: boolean
    }>,
  ): Promise<User> {
    return request<User>(`/users/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    })
  },
  deleteUser(id: number): Promise<void> {
    return request<void>(`/users/${id}`, { method: 'DELETE' })
  },

  // --- jobs ---
  listJobs(params?: {
    status?: JobStatus
    mineOnly?: boolean
  }): Promise<Job[]> {
    const q = new URLSearchParams()
    if (params?.status) q.set('status', params.status)
    q.set('mine_only', String(params?.mineOnly ?? true))
    q.set('limit', '200')
    return request<Job[]>(`/jobs?${q.toString()}`)
  },
  getJob(id: number): Promise<Job> {
    return request<Job>(`/jobs/${id}`)
  },
  submitJob(payload: JobCreate): Promise<Job> {
    return request<Job>('/jobs', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  async uploadJob(form: FormData): Promise<Job> {
    // Multipart: jangan set Content-Type (biar browser atur boundary).
    const token = getToken()
    const headers = new Headers()
    if (token) headers.set('Authorization', `Bearer ${token}`)
    const res = await fetch(`${API_PREFIX}/jobs/upload`, {
      method: 'POST',
      headers,
      body: form,
    })
    if (res.status === 401) {
      clearToken()
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
      throw new ApiError(401, 'Sesi berakhir. Silakan login kembali.')
    }
    if (!res.ok) {
      let detail = `HTTP ${res.status}`
      try {
        const d = await res.json()
        if (d?.detail) {
          detail = typeof d.detail === 'string' ? d.detail : JSON.stringify(d.detail)
        }
      } catch {
        /* noop */
      }
      throw new ApiError(res.status, detail)
    }
    return (await res.json()) as Job
  },
  getQueue(): Promise<QueueItem[]> {
    return request<QueueItem[]>('/jobs/queue')
  },
  getUsage(): Promise<Usage> {
    return request<Usage>('/jobs/usage')
  },
  cancelJob(id: number): Promise<Job> {
    return request<Job>(`/jobs/${id}/cancel`, { method: 'POST' })
  },
  getJobLogs(id: number, tail = 300): Promise<JobLogs> {
    return request<JobLogs>(`/jobs/${id}/logs?tail=${tail}`)
  },
  getJobSamples(id: number, limit = 200): Promise<ResourceSample[]> {
    return request<ResourceSample[]>(`/jobs/${id}/samples?limit=${limit}`)
  },
  async downloadNotebook(id: number): Promise<Blob> {
    const token = getToken()
    const headers = new Headers()
    if (token) headers.set('Authorization', `Bearer ${token}`)
    const res = await fetch(`${API_PREFIX}/jobs/${id}/notebook`, { headers })
    if (!res.ok) {
      let detail = `HTTP ${res.status}`
      try {
        const d = await res.json()
        if (d?.detail) detail = typeof d.detail === 'string' ? d.detail : JSON.stringify(d.detail)
      } catch {
        /* noop */
      }
      throw new ApiError(res.status, detail)
    }
    return await res.blob()
  },

  // --- monitoring ---
  overview(): Promise<MonitoringOverview> {
    return request<MonitoringOverview>('/monitoring/overview')
  },
  system(): Promise<SystemSnapshot> {
    return request<SystemSnapshot>('/monitoring/system')
  },
  capabilities(): Promise<Capabilities> {
    return request<Capabilities>('/system/capabilities')
  },

  // --- admin settings (policy) ---
  getSettings(): Promise<SystemSettings> {
    return request<SystemSettings>('/admin/settings')
  },
  updateSettings(payload: Partial<SystemSettings>): Promise<SystemSettings> {
    return request<SystemSettings>('/admin/settings', {
      method: 'PATCH',
      body: JSON.stringify(payload),
    })
  },

  // --- admin: kebijakan per-mahasiswa & statistik ---
  getUserPolicy(userId: number): Promise<UserPolicy> {
    return request<UserPolicy>(`/admin/users/${userId}/policy`)
  },
  updateUserPolicy(
    userId: number,
    payload: UserPolicyUpdate,
  ): Promise<UserPolicy> {
    return request<UserPolicy>(`/admin/users/${userId}/policy`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    })
  },
  getAdminUsage(): Promise<UserUsage[]> {
    return request<UserUsage[]>('/admin/usage')
  },
  getReport(): Promise<FullReport> {
    return request<FullReport>('/admin/report')
  },
  getUserReport(username: string): Promise<UserReport> {
    return request<UserReport>(`/admin/report/user/${encodeURIComponent(username)}`)
  },
  async downloadReportBlob(path: string): Promise<Blob> {
    const token = getToken()
    const headers = new Headers()
    if (token) headers.set('Authorization', `Bearer ${token}`)
    const res = await fetch(`${API_PREFIX}${path}`, { headers })
    if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status}`)
    return await res.blob()
  },

  // --- peringatan (alert) ---
  getAlertConfig(): Promise<AlertConfig> {
    return request<AlertConfig>('/admin/alerts/config')
  },
  updateAlertConfig(payload: AlertConfigUpdate): Promise<AlertConfig> {
    return request<AlertConfig>('/admin/alerts/config', {
      method: 'PATCH',
      body: JSON.stringify(payload),
    })
  },
  listAlerts(limit = 50): Promise<AlertItem[]> {
    return request<AlertItem[]>(`/admin/alerts?limit=${limit}`)
  },
  runAlerts(): Promise<AlertRunResult> {
    return request<AlertRunResult>('/admin/alerts/run?ignore_cooldown=true', {
      method: 'POST',
    })
  },
  testAlertEmail(): Promise<EmailTestResult> {
    return request<EmailTestResult>('/admin/alerts/test-email', { method: 'POST' })
  },
  sendUserAlert(username: string): Promise<AlertItem> {
    return request<AlertItem>(
      `/admin/alerts/user/${encodeURIComponent(username)}/send`,
      { method: 'POST' },
    )
  },
}
