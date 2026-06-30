// Klien API terpusat untuk backend UNISMUH AI Cloud.

import type {
  AssistantMessage,
  AssistantStatus,
  Capabilities,
  Job,
  JobCreate,
  JobLogs,
  JobStatus,
  LintResult,
  MonitoringOverview,
  PoolStatus,
  QueueItem,
  ResourceSample,
  SystemSettings,
  SystemSnapshot,
  Token,
  Usage,
  User,
  UserCreateResult,
  UserPolicy,
  UserPolicyUpdate,
  UserRole,
  UserUsage,
  FullReport,
  DiskReport,
  UserReport,
  AlertConfig,
  AlertConfigUpdate,
  AlertItem,
  AlertRunResult,
  EmailTestResult,
  InteractiveSession,
  InteractiveSessionAdmin,
  CreateSessionResult,
  InteractiveQueueStatus,
  FileNode,
  InteractiveFile,
  InteractivePushResult,
  WorkspaceOverview,
} from './types'

// Base URL backend. Default kosong = relatif (same-origin, saat frontend disajikan
// oleh backend). Untuk deploy terpisah (mis. Vercel) set VITE_API_BASE_URL ke URL
// backend publik, contoh: https://computehub.contoh.com
const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/+$/, '')
const API_PREFIX = `${API_BASE}/api/v1`
const TOKEN_KEY = 'unismuh_token'
const REFRESH_KEY = 'unismuh_refresh'

// ---------------------------------------------------------------- token utils
export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}
export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY)
}
// Simpan pasangan token (access + refresh) hasil login / refresh.
export function setSession(t: Token): void {
  localStorage.setItem(TOKEN_KEY, t.access_token)
  if (t.refresh_token) localStorage.setItem(REFRESH_KEY, t.refresh_token)
}
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(REFRESH_KEY)
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

// Kunci sessionStorage berisi ALASAN logout terakhir (mis. sesi diambil alih di
// perangkat lain). Ditampilkan sekali di halaman Login lalu dihapus.
export const LOGOUT_REASON_KEY = 'unismuh_logout_reason'

// --- Silent refresh: tukar refresh token -> access token baru saat access
// kedaluwarsa (HTTP 401). Single-flight: banyak request 401 berbarengan hanya
// memicu SATU panggilan /auth/refresh.
let refreshInFlight: Promise<string | null> | null = null

async function doRefresh(): Promise<string | null> {
  const refresh = getRefreshToken()
  if (!refresh) return null
  try {
    const res = await fetch(`${API_PREFIX}/auth/refresh`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'ngrok-skip-browser-warning': 'true',
      },
      body: JSON.stringify({ refresh_token: refresh }),
    })
    if (!res.ok) return null
    const data = (await res.json()) as Token
    setSession(data)
    return data.access_token
  } catch {
    return null
  }
}

function refreshAccessToken(): Promise<string | null> {
  if (!refreshInFlight) {
    refreshInFlight = doRefresh().finally(() => {
      refreshInFlight = null
    })
  }
  return refreshInFlight
}

// Logout terpusat saat 401 final (refresh gagal/tak ada): bersihkan token,
// simpan alasan untuk ditampilkan di Login, beri tahu AuthProvider.
function failUnauthorized(detail?: string): never {
  clearToken()
  if (detail) {
    try {
      sessionStorage.setItem(LOGOUT_REASON_KEY, detail)
    } catch {
      /* sessionStorage tak tersedia */
    }
  }
  window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
  throw new ApiError(401, detail ?? 'Sesi berakhir. Silakan login kembali.')
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  retry = true,
): Promise<T> {
  const token = getToken()
  const headers = new Headers(options.headers)
  headers.set('ngrok-skip-browser-warning', 'true')
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (options.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const res = await fetch(`${API_PREFIX}${path}`, { ...options, headers })

  if (res.status === 401) {
    // Access token kedaluwarsa -> coba perbarui diam-diam (sekali) lalu ulangi.
    if (retry) {
      const fresh = await refreshAccessToken()
      if (fresh) return request<T>(path, options, false)
    }
    let detail: string | undefined
    try {
      const data = await res.clone().json()
      if (typeof data?.detail === 'string') detail = data.detail
    } catch {
      /* abaikan body non-json */
    }
    failUnauthorized(detail)
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
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'ngrok-skip-browser-warning': 'true',
      },
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
  // Logout: hapus sesi aktif di server (session_token) -> semua token user gugur.
  logout(): Promise<void> {
    return request<void>('/auth/logout', { method: 'POST' })
  },
  changePassword(currentPassword: string, newPassword: string): Promise<void> {
    return request<void>('/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    })
  },
  updateAvatar(avatar: string | null): Promise<User> {
    return request<User>('/auth/avatar', {
      method: 'PUT',
      body: JSON.stringify({ avatar }),
    })
  },

  // --- users (admin) ---
  listUsers(): Promise<User[]> {
    return request<User[]>('/users?limit=200')
  },
  createUser(payload: {
    name: string
    email: string
    role: UserRole
  }): Promise<UserCreateResult> {
    return request<UserCreateResult>('/users', {
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
  resetPassword(id: number): Promise<UserCreateResult> {
    return request<UserCreateResult>(`/users/${id}/reset-password`, {
      method: 'POST',
    })
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
    headers.set('ngrok-skip-browser-warning', 'true')
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
  getPools(): Promise<PoolStatus> {
    return request<PoolStatus>('/jobs/pools')
  },
  lint(code: string): Promise<LintResult> {
    return request<LintResult>('/lint', {
      method: 'POST',
      body: JSON.stringify({ code }),
    })
  },

  // --- asisten AI notebook (chat ala Copilot, provider OpenAI-compatible) ---
  assistantStatus(): Promise<AssistantStatus> {
    return request<AssistantStatus>('/assistant/status')
  },
  // Stream jawaban asisten (SSE). Panggil onDelta tiap potongan teks tiba.
  async assistantChatStream(
    body: { messages: AssistantMessage[]; notebook_context?: string; cell_code?: string },
    onDelta: (text: string) => void,
    signal?: AbortSignal,
  ): Promise<void> {
    const token = getToken()
    const headers = new Headers()
    headers.set('ngrok-skip-browser-warning', 'true')
    headers.set('Content-Type', 'application/json')
    if (token) headers.set('Authorization', `Bearer ${token}`)
    const res = await fetch(`${API_PREFIX}/assistant/chat`, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      signal,
    })
    if (res.status === 401) {
      clearToken()
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
      throw new ApiError(401, 'Sesi berakhir. Silakan login kembali.')
    }
    if (!res.ok || !res.body) {
      throw new ApiError(res.status, `HTTP ${res.status}`)
    }
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      let idx: number
      while ((idx = buf.indexOf('\n\n')) !== -1) {
        const rawEvent = buf.slice(0, idx)
        buf = buf.slice(idx + 2)
        const dataLine = rawEvent.split('\n').find((l) => l.startsWith('data:'))
        if (!dataLine) continue
        const data = dataLine.slice(5).trim()
        if (data === '[DONE]') return
        try {
          const obj = JSON.parse(data) as { delta?: string }
          if (obj.delta) onDelta(obj.delta)
        } catch {
          /* abaikan baris yang belum lengkap */
        }
      }
    }
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
    headers.set('ngrok-skip-browser-warning', 'true')
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

  async downloadOutput(id: number): Promise<Blob> {
    const token = getToken()
    const headers = new Headers()
    headers.set('ngrok-skip-browser-warning', 'true')
    if (token) headers.set('Authorization', `Bearer ${token}`)
    const res = await fetch(`${API_PREFIX}/jobs/${id}/output`, { headers })
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

  // --- sesi interaktif (notebook ala Colab, kernel hidup di GPU) ---
  createInteractiveSession(source = 'paste', ticketId?: string): Promise<CreateSessionResult> {
    const params = new URLSearchParams({ source })
    if (ticketId) params.set('ticket_id', ticketId)
    return request<CreateSessionResult>(`/interactive/sessions?${params.toString()}`, {
      method: 'POST',
    })
  },
  getInteractiveQueue(): Promise<InteractiveQueueStatus> {
    return request<InteractiveQueueStatus>('/interactive/queue')
  },
  leaveInteractiveQueue(): Promise<void> {
    return request<void>('/interactive/queue/leave', { method: 'POST' })
  },
  restartInteractiveSession(id: string): Promise<InteractiveSession> {
    return request<InteractiveSession>(`/interactive/sessions/${id}/restart`, {
      method: 'POST',
    })
  },
  interruptInteractiveSession(id: string): Promise<{ ok: boolean }> {
    return request<{ ok: boolean }>(`/interactive/sessions/${id}/interrupt`, {
      method: 'POST',
    })
  },
  deleteInteractiveSession(id: string): Promise<void> {
    return request<void>(`/interactive/sessions/${id}`, { method: 'DELETE' })
  },
  shutdownMyInteractiveSessions(): Promise<void> {
    return request<void>('/interactive/sessions/shutdown-mine', { method: 'POST' })
  },
  interactiveWsUrl(sessionId: string): string {
    const token = getToken() ?? ''
    let origin: string
    if (API_BASE) {
      origin = API_BASE.replace(/^http/, 'ws')
    } else {
      origin =
        (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host
    }
    return `${origin}/api/v1/interactive/ws/${sessionId}?token=${encodeURIComponent(token)}`
  },

  // --- project sesi interaktif (zip/github + file explorer) ---
  async uploadInteractiveZip(id: string, file: File): Promise<{ tree: FileNode }> {
    // Multipart: jangan set Content-Type (biar browser atur boundary).
    const token = getToken()
    const headers = new Headers()
    headers.set('ngrok-skip-browser-warning', 'true')
    if (token) headers.set('Authorization', `Bearer ${token}`)
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(
      `${API_PREFIX}/interactive/sessions/${id}/upload`,
      { method: 'POST', headers, body: form },
    )
    if (res.status === 401) {
      clearToken()
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
      throw new ApiError(401, 'Sesi berakhir. Silakan login kembali.')
    }
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
    return (await res.json()) as { tree: FileNode }
  },
  cloneInteractiveRepo(
    id: string,
    url: string,
    ref?: string,
  ): Promise<{ tree: FileNode }> {
    return request<{ tree: FileNode }>(
      `/interactive/sessions/${id}/clone`,
      { method: 'POST', body: JSON.stringify({ url, ref: ref || null }) },
    )
  },
  listInteractiveFiles(id: string): Promise<{ tree: FileNode }> {
    return request<{ tree: FileNode }>(`/interactive/sessions/${id}/files`)
  },
  readInteractiveFile(id: string, path: string): Promise<InteractiveFile> {
    return request<InteractiveFile>(
      `/interactive/sessions/${id}/file?path=${encodeURIComponent(path)}`,
    )
  },

  // --- workspace persisten per-user (/persist) ala Colab Drive ---
  getWorkspace(): Promise<WorkspaceOverview> {
    return request<WorkspaceOverview>('/interactive/workspace')
  },
  readWorkspaceFile(path: string): Promise<InteractiveFile> {
    return request<InteractiveFile>(
      `/interactive/workspace/file?path=${encodeURIComponent(path)}`,
    )
  },
  saveWorkspaceFile(
    path: string,
    content: string,
  ): Promise<{ path: string; size: number }> {
    return request<{ path: string; size: number }>('/interactive/workspace/file', {
      method: 'PUT',
      body: JSON.stringify({ path, content }),
    })
  },
  deleteWorkspaceFile(path: string): Promise<void> {
    return request<void>(
      `/interactive/workspace/file?path=${encodeURIComponent(path)}`,
      { method: 'DELETE' },
    )
  },
  async uploadWorkspaceFile(
    file: File,
    dir = '',
  ): Promise<{ path: string; size: number }> {
    const token = getToken()
    const headers = new Headers()
    headers.set('ngrok-skip-browser-warning', 'true')
    if (token) headers.set('Authorization', `Bearer ${token}`)
    const form = new FormData()
    form.append('file', file)
    const q = dir ? `?dir=${encodeURIComponent(dir)}` : ''
    const res = await fetch(
      `${API_PREFIX}/interactive/workspace/upload${q}`,
      { method: 'POST', headers, body: form },
    )
    if (res.status === 401) {
      clearToken()
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
      throw new ApiError(401, 'Sesi berakhir. Silakan login kembali.')
    }
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
    return await res.json()
  },
  async downloadWorkspaceFile(path: string): Promise<Blob> {
    const token = getToken()
    const headers = new Headers()
    headers.set('ngrok-skip-browser-warning', 'true')
    if (token) headers.set('Authorization', `Bearer ${token}`)
    const res = await fetch(
      `${API_PREFIX}/interactive/workspace/download?path=${encodeURIComponent(path)}`,
      { headers },
    )
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
  // Sesi interaktif aktif (admin) untuk monitoring.
  listInteractiveSessionsAdmin(): Promise<InteractiveSessionAdmin[]> {
    return request<InteractiveSessionAdmin[]>('/monitoring/interactive-sessions')
  },
  async downloadInteractiveProject(id: string): Promise<Blob> {
    const token = getToken()
    const headers = new Headers()
    headers.set('ngrok-skip-browser-warning', 'true')
    if (token) headers.set('Authorization', `Bearer ${token}`)
    const res = await fetch(`${API_PREFIX}/interactive/sessions/${id}/download`, { headers })
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
  pushInteractiveRepo(
    id: string,
    message: string,
    token: string,
  ): Promise<InteractivePushResult> {
    return request<InteractivePushResult>(`/interactive/sessions/${id}/push`, {
      method: 'POST',
      body: JSON.stringify({ message, token }),
    })
  },

  // --- monitoring ---
  overview(): Promise<MonitoringOverview> {
    return request<MonitoringOverview>('/monitoring/overview')
  },
  system(): Promise<SystemSnapshot> {
    return request<SystemSnapshot>('/monitoring/system')
  },
  // Stream snapshot sistem real-time (SSE). onSnapshot dipanggil tiap data tiba.
  async streamSystem(
    onSnapshot: (s: SystemSnapshot) => void,
    signal?: AbortSignal,
  ): Promise<void> {
    const token = getToken()
    const headers = new Headers()
    headers.set('ngrok-skip-browser-warning', 'true')
    if (token) headers.set('Authorization', `Bearer ${token}`)
    const res = await fetch(`${API_PREFIX}/monitoring/system/stream`, { headers, signal })
    if (res.status === 401) {
      clearToken()
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
      throw new ApiError(401, 'Sesi berakhir. Silakan login kembali.')
    }
    if (!res.ok || !res.body) throw new ApiError(res.status, `HTTP ${res.status}`)
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      let idx: number
      while ((idx = buf.indexOf('\n\n')) !== -1) {
        const rawEvent = buf.slice(0, idx)
        buf = buf.slice(idx + 2)
        const dataLine = rawEvent.split('\n').find((l) => l.startsWith('data:'))
        if (!dataLine) continue
        const data = dataLine.slice(5).trim()
        if (!data) continue
        try {
          onSnapshot(JSON.parse(data) as SystemSnapshot)
        } catch {
          /* abaikan event tak lengkap */
        }
      }
    }
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
  getDiskReport(): Promise<DiskReport> {
    return request<DiskReport>('/admin/report/disk')
  },
  getUserReport(username: string): Promise<UserReport> {
    return request<UserReport>(`/admin/report/user/${encodeURIComponent(username)}`)
  },
  async downloadReportBlob(path: string): Promise<Blob> {
    const token = getToken()
    const headers = new Headers()
    headers.set('ngrok-skip-browser-warning', 'true')
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
