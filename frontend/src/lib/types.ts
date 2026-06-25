// Tipe data yang mencerminkan schema backend.

export type UserRole = 'admin' | 'dosen' | 'mahasiswa'

export interface User {
  id: number
  name: string
  email: string
  role: UserRole
  is_active: boolean
  is_superadmin?: boolean
  created_at: string
}

export interface Token {
  access_token: string
  token_type: string
  expires_in: number
}

export type JobStatus =
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'cancelled'

export type JobSource = 'command' | 'git' | 'upload' | 'notebook' | 'paste'

export type JobDevice = 'gpu' | 'cpu'

export interface Job {
  id: number
  name: string
  command: string
  working_dir: string | null
  source_type: JobSource
  repo_url: string | null
  repo_ref: string | null
  upload_name: string | null
  inline_code: string | null
  status: JobStatus
  priority: number
  device: JobDevice
  gpu_index: number | null
  requested_gpu_memory_mb: number
  max_ram_mb: number
  cpu_threads: number
  time_limit_seconds: number | null
  auto_install: boolean
  is_interactive?: boolean
  pid: number | null
  exit_code: number | null
  error_message: string | null
  submitted_at: string
  started_at: string | null
  finished_at: string | null
  estimated_runtime_seconds: number | null
  actual_runtime_seconds: number | null
  peak_ram_mb: number | null
  peak_vram_mb: number | null
  peak_cpu_percent: number | null
  avg_gpu_util_percent: number | null
  user_id: number
  owner_name?: string
  owner_email?: string
}

export interface JobCreate {
  name?: string | null
  source_type?: JobSource
  device?: JobDevice | null
  code?: string | null
  repo_url?: string | null
  repo_ref?: string | null
  command?: string | null
  working_dir?: string | null
  priority?: number | null
  requested_gpu_memory_mb?: number | null
  time_limit_seconds?: number | null
  auto_install?: boolean | null
}

export interface SystemSettings {
  enforce_gpu: boolean
  max_concurrent_jobs: number
  student_max_concurrent_jobs: number
  student_daily_gpu_seconds_quota: number
  default_job_time_limit_seconds: number
  min_job_time_limit_seconds: number
  max_job_time_limit_seconds: number
  runtime_safety_factor: number
  student_max_gpu_memory_mb: number
  student_max_ram_mb: number
  student_max_cpu_threads: number
  dosen_max_concurrent_jobs: number
  dosen_daily_gpu_seconds_quota: number
  dosen_max_gpu_memory_mb: number
  dosen_max_ram_mb: number
  dosen_max_cpu_threads: number
  admin_max_concurrent_jobs: number
  admin_daily_gpu_seconds_quota: number
  admin_max_gpu_memory_mb: number
  admin_max_ram_mb: number
  admin_max_cpu_threads: number
  auto_pip_install: boolean
}

export interface UserPolicyOverrides {
  daily_gpu_seconds_quota: number | null
  max_concurrent_jobs: number | null
  max_time_limit_seconds: number | null
  max_gpu_memory_mb: number | null
  max_ram_mb: number | null
  max_cpu_threads: number | null
}

export interface EffectivePolicy {
  daily_gpu_seconds_quota: number
  max_concurrent_jobs: number
  max_time_limit_seconds: number
  max_gpu_memory_mb: number
  max_ram_mb: number
  max_cpu_threads: number
}

export interface UserPolicy {
  user_id: number
  overrides: UserPolicyOverrides
  effective: EffectivePolicy
}

export type UserPolicyUpdate = Partial<UserPolicyOverrides>

export interface UserUsage {
  user_id: number
  name: string
  email: string
  role: UserRole
  jobs_total: number
  jobs_succeeded: number
  jobs_failed: number
  gpu_seconds_24h: number
  gpu_seconds_total: number
}

// ---- Laporan penggunaan resource (admin) ----
export interface ReportSystem {
  hostname: string
  os: string
  cpu_cores: number
  cpu_physical_cores: number
  cpu_percent: number
  load_avg: number[]
  memory_total_mb: number
  memory_used_mb: number
  memory_available_mb: number
  swap_total_mb: number
  swap_used_mb: number
  disk_total_gb: number
  disk_used_gb: number
  disk_percent: number
  gpus: Gpu[]
  driver_version: string
  cuda_version: string
  uptime_seconds: number
  boot_time: string
  platform_users: number
  now: string
}

export interface GpuProcess {
  gpu_index: number
  pid: number
  username: string
  name: string
  command: string
  vram_mb: number
  workload: string
  is_platform_job: boolean
  job_id: number | null
}

export interface SystemProcess {
  pid: number
  username: string
  name: string
  cpu_percent: number
  cpu_cores_eq: number
  memory_mb: number
  command: string
  workload: string
}

export interface OsUserUsage {
  username: string
  cpu_percent: number
  cpu_cores_eq: number
  memory_mb: number
  vram_mb: number
  gpu_indices: number[]
  processes: number
  activity: string
}

export interface ReportRunningJob {
  id: number
  name: string
  owner_name: string
  owner_email: string
  role: UserRole
  gpu_index: number | null
  pid: number | null
  source_type: JobSource
  runtime_seconds: number | null
  peak_ram_mb: number | null
  peak_vram_mb: number | null
  avg_gpu_util_percent: number | null
  started_at: string | null
}

export interface PlatformUserUsage {
  user_id: number
  name: string
  email: string
  role: UserRole
  jobs_total: number
  jobs_succeeded: number
  jobs_failed: number
  jobs_cancelled: number
  jobs_running: number
  jobs_queued: number
  gpu_seconds_24h: number
  gpu_seconds_total: number
  peak_ram_mb: number | null
  peak_vram_mb: number | null
  peak_cpu_percent: number | null
  last_activity: string | null
}

export interface FullReport {
  system: ReportSystem
  gpu_processes: GpuProcess[]
  top_processes: SystemProcess[]
  os_users: OsUserUsage[]
  running_jobs: ReportRunningJob[]
  users: PlatformUserUsage[]
}

// ---- Peringatan (alert) batas resource ----
export interface AlertConfig {
  enabled: boolean
  cpu_cores: number
  ram_gb: number
  vram_gb: number
  disk_percent: number
  cooldown_minutes: number
  email_on_breach: boolean
  email_to: string
  updated_at: string | null
  smtp_configured: boolean
  smtp_from: string
  recipients: string[]
}

export type AlertConfigUpdate = Partial<{
  enabled: boolean
  cpu_cores: number
  ram_gb: number
  vram_gb: number
  disk_percent: number
  cooldown_minutes: number
  email_on_breach: boolean
  email_to: string
}>

export interface AlertItem {
  id: number
  created_at: string
  scope: string
  subject: string
  metric: string
  value: number
  threshold: number
  message: string
  emailed: boolean
  email_error: string | null
  pdf_path: string | null
}

export interface AlertRunResult {
  created: number
  smtp_configured: boolean
  alerts: AlertItem[]
}

export interface EmailTestResult {
  ok: boolean
  recipients: string[]
  detail: string
}

// ---- Laporan detail per-user OS ----
export interface ReportProcess {
  pid: number
  username: string
  name: string
  cpu_percent: number
  cpu_cores_eq: number
  memory_mb: number
  cpu_time: number
  status: string
  command: string
  workload: string
  workload_type: string
  gpu_index: number | null
  gpu_vram_mb: number
  started: string
  runtime_seconds: number | null
}

export interface UserReportGpu {
  index: number
  name: string
  util_percent: number
  temperature_c: number
  power_w: number
  user_vram_mb: number
  total_vram_mb: number
}

export interface UserReport {
  username: string
  generated_at: string
  generated_at_iso: string
  profile: {
    username: string
    uid: number | null
    home: string
    shell: string
    sessions: { terminal: string; host: string; started: string }[]
    processes_count: number
  }
  system: ReportSystem
  status: {
    gpu: UserReportGpu[]
    ram: {
      user_rss_mb: number
      percent_of_total: number
      system_total_mb: number
      system_used_mb: number
      system_available_mb: number
      swap_used_mb: number
    }
    cpu: {
      user_cpu_percent: number
      cores_eq: number
      cpu_time_seconds: number
      load_avg: number[]
      system_cores: number
    }
    disk: { fs_total_gb: number; fs_used_gb: number; fs_percent: number; home: string }
  }
  workload: { primary: string; primary_type: string; hint: string; signals: string[] }
  processes: { main: ReportProcess | null; supporting: ReportProcess[] }
  gpu_processes: GpuProcess[]
  findings: { level: string; text: string }[]
  recommendations: { high: string[]; medium: string[]; low: string[] }
  summary: {
    processes: number
    cpu_percent: number
    cpu_cores_eq: number
    cpu_time_seconds: number
    memory_mb: number
    vram_mb: number
    gpu_indices: number[]
  }
  comparison: OsUserUsage[]
  conclusion: string
}

export interface QueueItem {
  job_id: number
  name: string
  user_id: number
  owner_name: string
  position: number
  priority: number
  estimated_runtime_seconds: number
  eta_seconds: number
  device: JobDevice
  waiting_reason: 'cpu_full' | 'gpu_full' | null
}

// Status pool resource (CPU core pool + GPU VRAM pool) untuk indikator penuh/tersedia.
export interface CpuPoolStatus {
  total: number
  used: number
  free: number
  full: boolean
}

export interface GpuPoolEntry {
  index: number
  workloads: number
  max_workloads: number
  planned_mb: number
  usable_mb: number
  free_mb: number
}

export interface GpuPoolStatus {
  gpus: GpuPoolEntry[]
  count: number
  available: boolean
  full: boolean
}

export interface PoolStatus {
  cpu: CpuPoolStatus
  gpu: GpuPoolStatus
  allow_cpu_jobs: boolean
}

export interface Usage {
  window_hours: number
  used_seconds: number
  quota_seconds: number
  remaining_seconds: number | null
  quota_enabled: boolean
}

export interface InteractiveSession {
  session_id: string
  gpu_index: number
  busy: boolean
  execution_count: number
  idle_seconds: number
  age_seconds?: number
  expires_in_seconds?: number | null
  vram_used_mb?: number
  vram_budget_mb?: number
  ram_used_mb?: number
}

// Balasan saat semua kapasitas GPU penuh -> user masuk antrian (auto-mulai nanti).
export interface InteractiveQueued {
  queued: true
  ticket_id: string
  position: number
  eta_seconds: number | null
}

export type CreateSessionResult = InteractiveSession | InteractiveQueued

// Status antrian sesi interaktif (dipantau frontend saat menunggu giliran).
export interface InteractiveQueueStatus {
  state: 'none' | 'queued' | 'ready'
  ticket_id?: string
  position?: number
  waiting?: number
  eta_seconds?: number | null
  gpu_index?: number | null
}

// Node pohon file project (sesi interaktif zip/github).
export interface FileNode {
  name: string
  path: string
  type: 'dir' | 'file'
  size?: number
  children?: FileNode[]
}

export interface InteractiveFile {
  path: string
  content: string
  language: string
  truncated: boolean
}

export interface InteractivePushResult {
  branch: string
  committed: boolean
  detail: string
}

export interface ResourceSample {
  id: number
  ts: string
  job_id: number | null
  cpu_percent: number
  memory_used_mb: number
  gpu_index: number | null
  gpu_util_percent: number
  gpu_mem_used_mb: number
  gpu_mem_total_mb: number
  gpu_temperature_c: number
  gpu_power_w: number
}

export interface Gpu {
  index: number
  name: string
  uuid: string
  util_percent: number
  mem_used_mb: number
  mem_total_mb: number
  mem_free_mb: number
  temperature_c: number
  power_w: number
}

export interface SystemSnapshot {
  timestamp: string
  cpu_percent: number
  cpu_cores: number
  memory_used_mb: number
  memory_total_mb: number
  gpu_available: boolean
  gpus: Gpu[]
}

export interface MonitoringOverview {
  system: SystemSnapshot
  jobs_queued: number
  jobs_running: number
  jobs_succeeded: number
  jobs_failed: number
  enforce_gpu: boolean
  max_concurrent_jobs: number
  interactive_sessions?: number
}

// Sesi interaktif aktif (untuk monitoring admin).
export interface InteractiveSessionAdmin {
  session_id: string
  gpu_index: number
  busy: boolean
  execution_count: number
  idle_seconds: number
  age_seconds?: number
  expires_in_seconds?: number | null
  user_id: number
  created_at: number
  has_project: boolean
  owner_name: string | null
  owner_email: string | null
  vram_used_mb?: number
  vram_budget_mb?: number
  ram_used_mb?: number
}

export interface JobLogs {
  job_id: number
  total_lines?: number
  lines: string[]
  message?: string
}

export interface Capabilities {
  enforce_gpu: boolean
  allow_cpu_fallback: boolean
  require_cuda_preflight: boolean
  gpu_min_free_memory_mb: number
  max_concurrent_jobs: number
  scheduler_mode: string
  job_execution_enabled: boolean
  gpu_count: number
  gpus: Gpu[]
  busy_gpus: number[]
  running_jobs: number[]
  secret_key_safe: boolean
  policy?: {
    student_max_concurrent_jobs: number
    student_max_gpu_memory_mb: number
    student_max_time_limit_seconds: number
    student_daily_gpu_seconds_quota: number
    default_time_limit_seconds: number
    max_upload_size_mb: number
    auto_pip_install: boolean
    dosen_default_priority: number
    dosen_max_priority: number
    student_priority_locked: boolean
    allowed_git_hosts: string[]
  }
}
