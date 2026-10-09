import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import RefreshButton from './RefreshButton'
import Spinner from './Spinner'
import { IconCheck, IconDownload, IconEye, IconPlay, IconRefresh, IconShield, IconTrash, IconUpload, IconX } from './icons'
import { ApiError, api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { cn, formatDateTime } from '../lib/format'
import type {
  BackupManifest,
  BackupSources,
  OpsAction,
  OpsEvent,
  OpsEventKind,
  OpsPrecheck,
  OpsRequest,
  RestoreScope,
  RestoreSourceType,
} from '../lib/types'

// ---------------------------------------------------------------- label & format
const OPS_KIND_LABEL: Record<OpsEventKind, string> = {
  backup: 'Backup',
  restore: 'Restore',
  restore_drill: 'Restore drill',
  offsite: 'Offsite',
  watchdog: 'Pemantau',
}
const OPS_STATUS_BADGE: Record<OpsEvent['status'], string> = {
  ok: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
  warn: 'bg-amber-50 text-amber-700 ring-amber-600/20',
  fail: 'bg-rose-50 text-rose-700 ring-rose-600/20',
}
const OPS_STATUS_LABEL: Record<OpsEvent['status'], string> = {
  ok: 'Berhasil', warn: 'Peringatan', fail: 'Gagal',
}
const ACTION_LABEL: Record<OpsAction, string> = {
  backup: 'Backup penuh',
  restore: 'Restore',
  drill: 'Uji pulih',
  refresh_sources: 'Segarkan sumber',
  delete_archive: 'Hapus arsip',
}
const REQ_BADGE: Record<OpsRequest['status'], string> = {
  pending: 'bg-slate-100 text-slate-600 ring-slate-500/20',
  running: 'bg-brand-50 text-brand-700 ring-brand-600/20',
  ok: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
  fail: 'bg-rose-50 text-rose-700 ring-rose-600/20',
}
const REQ_LABEL: Record<OpsRequest['status'], string> = {
  pending: 'Menunggu agen', running: 'Berjalan', ok: 'Selesai', fail: 'Gagal',
}
const SOURCE_TYPE_LABEL: Record<RestoreSourceType, string> = {
  archive: 'arsip server',
  snapshot: 'snapshot restic',
  pre_restore: 'titik rollback',
  offsite: 'salinan Drive',
}
const CONFIRM_PHRASE = 'YA PULIHKAN'
const DELETE_PHRASE = 'HAPUS'
const KNOWN_ACTIONS = new Set<string>(Object.keys(ACTION_LABEL))
/** Label manusiawi untuk kunci `data` yang ditulis skrip host (backup.sh, restore.sh, watchdog, agen). */
const DATA_LABEL: Record<string, string> = {
  archive: 'Arsip', archive_size: 'Ukuran arsip', archive_bytes: 'Ukuran arsip', archive_form: 'Bentuk arsip', archive_sha256: 'SHA256 arsip',
  archives_on_server: 'Arsip tersisa di server', db_dump: 'Dump database', offsite_tar: 'Off-site arsip tar (Drive)', restic: 'Snapshot restic',
  restic_check: 'Pemeriksaan integritas restic', restic_offsite: 'Restic off-site (Drive)', restic_snapshot: 'ID snapshot restic',
  disk_free: 'Disk server bebas', disk_free_after_gib: 'Disk bebas sesudahnya (GiB)', restic_repo_before_gib: 'Repo restic sebelum (GiB)',
  restic_repo_after_gib: 'Repo restic sesudah (GiB)', snapshots: 'Jumlah snapshot', tar_local_deleted: 'Tar lokal dihapus', backfill: 'Rekonstruksi riwayat',
  trigger: 'Dipicu oleh', requested_by: 'Diminta oleh', request_id: 'ID permintaan', remote: 'Remote Google Drive', age_hours: 'Umur berkas terbaru (jam)',
  threshold_hours: 'Ambang peringatan (jam)', backup_result: 'Hasil backup', pid_before: 'PID backend sebelum', pid_after: 'PID backend sesudah',
  tables: 'Tabel dipulihkan', users: 'Pengguna dipulihkan', jobs: 'Job dipulihkan', source: 'Sumber pemulihan', scope: 'Cakupan', snapshot_dir: 'Titik rollback',
  bytes_freed: 'Ruang dibebaskan', removed: 'Berkas dihapus',
  core_archive: 'Arsip inti harian', core_bytes: 'Ukuran arsip inti', core_sha256: 'SHA256 arsip inti', core_offsite: 'Arsip inti → Drive',
  restic_repo: 'Repo restic', core_archives_on_server: 'Arsip inti di server', server_backup_size: 'Ukuran backup di server',
}
const ARCHIVE_KIND_LABEL = {
  core: 'arsip inti harian — DB + roles + konfigurasi + log job, tanpa workspace',
  full: 'arsip penuh — termasuk workspace semua akun',
} as const
function archiveKindOf(name: string): 'core' | 'full' {
  return name.includes('-core-') ? 'core' : 'full'
}

function fmtGb(bytes: number): string {
  return bytes >= 1024 ** 3 ? `${(bytes / 1024 ** 3).toFixed(2)} GB` : `${(bytes / 1024 ** 2).toFixed(1)} MB`
}
function fmtBytes(bytes: number | null | undefined): string {
  if (bytes == null || !Number.isFinite(bytes)) return '—'
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${bytes} B`
}
function fmtDur(seconds: number | null | undefined): string {
  if (seconds == null) return '—'
  if (seconds < 90) return `${seconds} detik`
  if (seconds < 3600) return `${Math.round(seconds / 60)} menit`
  return `${Math.floor(seconds / 3600)} jam ${Math.round((seconds % 3600) / 60)} mnt`
}
function fmtInt(n: number | null | undefined): string {
  return n == null ? '—' : n.toLocaleString('id-ID')
}
function umurHari(iso: string | null | undefined): string {
  if (!iso) return '—'
  const hari = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000)
  return hari <= 0 ? 'hari ini' : `${hari} hari lalu`
}
function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}
function simpanBlob(blob: Blob, nama: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = nama
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
/** Backend lama / mock bisa mengembalikan bentuk tak terduga -> normalkan agar UI tak pernah pecah. */
function normalizeSources(raw: unknown): BackupSources {
  const r = isRecord(raw) ? raw : {}
  const restic = isRecord(r.restic) ? r.restic : {}
  const offsite = isRecord(r.offsite) ? r.offsite : {}
  return {
    available: Boolean(r.available),
    generated_at: typeof r.generated_at === 'string' ? r.generated_at : null,
    archives: Array.isArray(r.archives) ? (r.archives as BackupSources['archives']) : [],
    plain_archives: Array.isArray(r.plain_archives) ? (r.plain_archives as BackupSources['plain_archives']) : [],
    pre_restore: Array.isArray(r.pre_restore) ? (r.pre_restore as BackupSources['pre_restore']) : [],
    restic: { available: Boolean(restic.available), snapshots: Array.isArray(restic.snapshots) ? (restic.snapshots as BackupSources['restic']['snapshots']) : [], error: typeof restic.error === 'string' ? restic.error : null },
    offsite: { available: Boolean(offsite.available), remote: typeof offsite.remote === 'string' ? offsite.remote : undefined, archives: Array.isArray(offsite.archives) ? (offsite.archives as BackupSources['offsite']['archives']) : [], error: typeof offsite.error === 'string' ? offsite.error : null },
    disk: isRecord(r.disk) ? (r.disk as BackupSources['disk']) : {},
  }
}
function manifestOf(e: OpsEvent | null | undefined): BackupManifest | null {
  const m = e?.data?.manifest
  return isRecord(m) && (isRecord(m.database) || isRecord(m.archive)) ? (m as BackupManifest) : null
}
function fmtDataValue(key: string, v: unknown): string {
  if (v == null || v === '') return '—'
  if (typeof v === 'boolean') return v ? 'ya' : 'tidak'
  if (typeof v === 'number') return /bytes|freed/.test(key) ? fmtBytes(v) : v.toLocaleString('id-ID')
  if (Array.isArray(v)) return v.map((x) => (isRecord(x) ? String(x.path ?? JSON.stringify(x)) : String(x))).join(', ')
  if (isRecord(v)) return JSON.stringify(v)
  return String(v)
}
/** Tiga angka kunci per jenis catatan untuk kartu ringkas di Detail. */
/** Di mana data catatan ini tersimpan: Server / Drive, dengan status tiap lokasi. */
type StorageMark = { place: 'Server' | 'Drive'; ok: boolean; note: string }
function storageOf(e: OpsEvent): StorageMark[] {
  const d = e.data ?? {}
  const str = (k: string) => (typeof d[k] === 'string' ? (d[k] as string) : '')
  const marks: StorageMark[] = []
  const add = (place: StorageMark['place'], ok: boolean, note: string) => {
    const cur = marks.find((m) => m.place === place)
    if (!cur) marks.push({ place, ok, note })
    else { cur.ok = cur.ok && ok; cur.note += `; ${note}` }
  }
  if (e.kind === 'offsite') {
    add('Drive', e.status === 'ok', `${str('remote') || 'Google Drive'} ${e.status === 'ok' ? 'segar' : 'tidak segar / tidak terbaca'}`)
    return marks
  }
  if (e.kind !== 'backup') return marks
  if (d.backfill) {
    add('Server', true, 'rekonstruksi dari repo restic di server (saat itu)')
    return marks
  }
  if (str('core_archive')) {
    add('Server', true, `arsip inti ${str('core_archive')}`)
    const co = str('core_offsite')
    if (co && co !== 'dilewati') add('Drive', co === 'ok', `arsip inti → Drive ${co}`)
  }
  if (str('archive')) {
    const ot = str('offsite_tar')
    if (d.tar_local_deleted) add('Server', false, 'arsip penuh dihapus dari server setelah terverifikasi di Drive')
    else add('Server', true, `arsip penuh ${str('archive')}`)
    if (ot && ot !== 'dilewati') add('Drive', ot === 'ok', `arsip penuh → Drive ${ot}`)
  }
  if (str('restic') === 'ok') {
    if (str('restic_repo').startsWith('rclone:')) add('Drive', true, 'snapshot restic ditulis langsung ke Drive')
    else {
      add('Server', true, 'snapshot restic (repo lokal)')
      const ro = str('restic_offsite')
      if (ro && ro !== 'dilewati') add('Drive', ro === 'ok', `restic → Drive ${ro}`)
    }
  } else if (str('restic') === 'gagal') {
    add(str('restic_repo').startsWith('rclone:') ? 'Drive' : 'Server', false, 'snapshot restic gagal')
  }
  // Server dihapus + tidak ada data lain di server -> tetap tampil sebagai silang (informatif).
  return marks.sort((a, b) => (a.place === 'Server' ? -1 : 1) - (b.place === 'Server' ? -1 : 1))
}
function StorageBadges({ e, size = 'sm' }: { e: OpsEvent; size?: 'sm' | 'md' }) {
  const marks = storageOf(e)
  if (marks.length === 0) return <span className="text-slate-400">—</span>
  return (
    <span className={cn('inline-flex flex-wrap gap-1', size === 'md' && 'gap-1.5')} data-testid="storage-badges">
      {marks.map((m) => (
        <span
          key={m.place}
          className={cn('badge whitespace-nowrap', m.ok ? 'bg-emerald-50 text-emerald-700 ring-emerald-600/20' : 'bg-rose-50 text-rose-700 ring-rose-600/20', size === 'md' && 'px-2.5 py-1 text-xs')}
          title={m.note}
          aria-label={`${m.place}: ${m.ok ? 'tersimpan' : 'tidak tersimpan'} — ${m.note}`}
        >
          {m.ok ? <IconCheck className="mr-1 h-3 w-3" /> : <IconX className="mr-1 h-3 w-3" />}
          {m.place}
        </span>
      ))}
    </span>
  )
}
function highlightsOf(e: OpsEvent): [string, string][] {
  const d = e.data ?? {}
  const s = (k: string) => fmtDataValue(k, d[k])
  const out: [string, string | null | undefined][] = (() => {
    switch (e.kind) {
      case 'backup': return [
        ['Arsip', typeof d.archive === 'string' && d.archive ? d.archive : typeof d.core_archive === 'string' && d.core_archive ? `inti: ${d.core_archive}` : 'dilewati (restic saja)'],
        ['Durasi proses', fmtDur(e.duration_seconds)],
        ['Drive', d.offsite_tar && d.offsite_tar !== 'dilewati' ? `arsip penuh ${s('offsite_tar')}` : d.core_offsite && d.core_offsite !== 'dilewati' ? `arsip inti ${s('core_offsite')}` : d.restic_offsite ? `restic ${s('restic_offsite')}` : d.restic_snapshot ? `snapshot ${s('restic_snapshot')}` : null],
      ]
      case 'offsite': return [['Remote', s('remote')], ['Berkas terbaru', d.age_hours != null ? `${s('age_hours')} jam lalu` : null], ['Ambang peringatan', d.threshold_hours != null ? `${s('threshold_hours')} jam` : null]]
      case 'restore_drill': return [['Tabel dipulihkan', d.tables != null ? s('tables') : null], ['Pengguna', d.users != null ? s('users') : null], ['Job', d.jobs != null ? s('jobs') : null]]
      case 'restore': return [['Sumber', s('source')], ['Cakupan', s('scope')], ['Durasi proses', fmtDur(e.duration_seconds)]]
      default: return [['Hasil', s('backup_result')], ['PID sebelum', s('pid_before')], ['PID sesudah', s('pid_after')]]
    }
  })()
  const rows = out.filter((x): x is [string, string] => Boolean(x[1]) && x[1] !== '—')
  if (rows.length > 0) return rows
  return Object.entries(d).filter(([, v]) => typeof v !== 'object').slice(0, 3).map(([k, v]) => [DATA_LABEL[k] ?? k, fmtDataValue(k, v)])
}

// ---------------------------------------------------------------- kartu status
function StatusCard({
  title, status, children,
}: {
  title: string
  status: OpsEvent['status'] | 'none'
  children: React.ReactNode
}) {
  return (
    <div className="card card-pad space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</p>
        {status === 'none' ? (
          <span className="badge bg-slate-100 text-slate-600 ring-slate-500/20">Belum ada</span>
        ) : (
          <span className={cn('badge', OPS_STATUS_BADGE[status])}>{OPS_STATUS_LABEL[status]}</span>
        )}
      </div>
      <div className="space-y-0.5 text-sm text-slate-700">{children}</div>
    </div>
  )
}

// ---------------------------------------------------------------- modal dasar
function ModalShell({
  title, subtitle, onClose, children, wide, labelledBy,
}: {
  title: React.ReactNode
  subtitle?: React.ReactNode
  onClose: () => void
  children: React.ReactNode
  wide?: boolean
  labelledBy: string
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  // Portal ke body: halaman dibungkus PageTransition (transform) yang membuat position:fixed
  // dihitung relatif ke konten, bukan viewport.
  return createPortal(
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-slate-900/60 p-4 backdrop-blur-sm"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby={labelledBy}
    >
      <div
        className={cn('card flex max-h-[92vh] w-full animate-fade-in flex-col', wide ? 'max-w-3xl' : 'max-w-xl')}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-slate-100 px-5 py-4">
          <div className="min-w-0">
            <h2 id={labelledBy} className="truncate font-semibold text-slate-800">{title}</h2>
            {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
          </div>
          <button type="button" onClick={onClose} className="btn-ghost !p-1.5" aria-label="Tutup">
            <IconX className="h-4 w-4" />
          </button>
        </div>
        <div className="min-h-0 overflow-y-auto px-5 py-4">{children}</div>
      </div>
    </div>,
    document.body,
  )
}

// ---------------------------------------------------------------- Detail Backup (ala "Detail Backup" sistem lain)
function KV({ k, v, mono }: { k: string; v: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1 text-sm">
      <span className="text-slate-500">{k}</span>
      <span className={cn('text-right font-medium text-slate-800', mono && 'font-mono text-xs')}>{v}</span>
    </div>
  )
}
function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h3 className="mt-4 mb-1 text-sm font-semibold text-slate-800 first:mt-0">{children}</h3>
}

function StatBox({ label, value, sub }: { label: string; value: React.ReactNode; sub?: string }) {
  return (
    <div className="rounded-lg bg-slate-50 px-3 py-2 ring-1 ring-inset ring-slate-200">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</p>
      <p className="truncate text-sm font-semibold text-slate-800" title={typeof value === 'string' ? value : undefined}>{value}</p>
      {sub && <p className="text-[11px] text-slate-500">{sub}</p>}
    </div>
  )
}

/** Isi "Detail Backup" dari manifest (dipakai modal arsip maupun detail catatan riwayat). */
function ManifestSections({ manifest }: { manifest: BackupManifest }) {
  const db = manifest.database ?? {}
  const ws = manifest.workspaces ?? { accounts: [], accounts_total: 0, files_total: 0, bytes_total: 0 }
  const comp = manifest.components ?? {}
  const arch = manifest.archive
  const offsiteOk = manifest.offsite?.tar === 'ok'
  return (
    <>
      <div className="grid gap-2 sm:grid-cols-3" data-testid="backup-detail">
        <StatBox label="Total ukuran" value={fmtBytes(arch?.bytes)} sub={arch?.form} />
        <StatBox label="Durasi proses" value={fmtDur(manifest.duration_seconds)} />
        <StatBox label="Salinan off-site" value={offsiteOk ? 'Drive' : manifest.offsite?.tar ?? '—'} sub={manifest.offsite?.remote ?? undefined} />
      </div>

      <SectionTitle>Basis data PostgreSQL</SectionTitle>
      <div className="grid gap-x-8 sm:grid-cols-2">
        <KV k="Nama database" v={db.name ?? '—'} />
        <KV k="Ukuran file dump" v={fmtBytes(db.dump_bytes)} />
        <KV k="Jumlah tabel" v={fmtInt(db.tables)} />
        <KV k="Perkiraan baris" v={fmtInt(db.estimated_rows)} />
        <KV k="Ukuran database asli" v={fmtBytes(db.size_bytes)} />
        <KV k="Roles/globals" v={db.globals_included ? 'ikut dicadangkan' : 'tidak disertakan'} />
      </div>
      {db.largest_tables && db.largest_tables.length > 0 && (
        <p className="mt-1 text-xs text-slate-500">
          Tabel terbesar: {db.largest_tables.slice(0, 4).map((t) => `${t.table} (${fmtInt(t.rows)})`).join(', ')}
        </p>
      )}
      {db.dump_warnings && <pre className="mt-1 max-h-24 overflow-auto rounded bg-amber-50 p-2 text-[11px] text-amber-800">{db.dump_warnings}</pre>}

      <SectionTitle>
        Workspace pengguna — {fmtInt(ws.accounts_total)} akun · {fmtInt(ws.files_total)} berkas · {fmtBytes(ws.bytes_total)}
      </SectionTitle>
      {ws.accounts.length === 0 ? (
        <p className="text-sm text-slate-500">{ws.note ?? (manifest.archive_kind === 'core' ? 'Arsip inti tidak memuat workspace; workspace dibawa snapshot restic (Drive) dan arsip penuh mingguan.' : 'Tidak ada workspace di arsip ini.')}</p>
      ) : (
        <div className="max-h-48 overflow-auto rounded-lg ring-1 ring-inset ring-slate-200">
          <table className="min-w-full text-sm">
            <thead className="sticky top-0 bg-slate-50 text-[10px] uppercase tracking-wide text-slate-500">
              <tr><th className="px-3 py-1.5 text-left">Akun</th><th className="px-3 py-1.5 text-right">Berkas</th><th className="px-3 py-1.5 text-right">Ukuran</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {ws.accounts.map((a) => (
                <tr key={a.dir}>
                  <td className="px-3 py-1">{a.username ?? `akun #${a.dir}`}{a.user_id != null && <span className="ml-1 text-xs text-slate-400">#{a.user_id}</span>}{a.role && <span className="ml-1 text-xs text-slate-400">· {a.role}</span>}</td>
                  <td className="px-3 py-1 text-right">{fmtInt(a.files)}</td>
                  <td className="px-3 py-1 text-right">{fmtBytes(a.bytes)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <SectionTitle>Komponen lain</SectionTitle>
      <div className="grid gap-x-8 sm:grid-cols-2">
        <KV k="Snapshot Redis" v={comp.redis?.included ? 'disertakan' : 'tidak ada (non-kritis)'} />
        <KV k="Salinan konfigurasi (.env)" v={comp.env?.included ? 'disertakan (terenkripsi)' : 'tidak disertakan'} />
        <KV k="Verifikasi integritas" v={arch?.sha256 ? `SHA256 · ${arch.sha256.slice(0, 12)}…` : 'tidak ada'} mono={Boolean(arch?.sha256)} />
        <KV k="Nama arsip off-site" v={manifest.offsite?.archive_name ?? (offsiteOk ? arch?.name : '—') ?? '—'} mono />
        <KV k="Log eksekusi job" v={comp.joblogs?.included ? `${fmtInt(comp.joblogs.files)} berkas` : 'tidak ada'} />
        <KV k="Agen pemantau host" v={comp.agent?.included ? `${fmtInt(comp.agent.files)} berkas` : 'tidak ada'} />
        <KV k="Snapshot restic" v={manifest.restic?.snapshot ? `${manifest.restic.snapshot} (${manifest.restic.status})` : manifest.restic?.status ?? '—'} mono={Boolean(manifest.restic?.snapshot)} />
        <KV k="Salinan restic off-site" v={manifest.restic?.offsite ?? '—'} />
      </div>

      <SectionTitle>Waktu &amp; lingkungan</SectionTitle>
      <div className="grid gap-x-8 sm:grid-cols-2">
        <KV k="Mulai" v={formatDateTime(manifest.started_at)} />
        <KV k="Selesai" v={formatDateTime(manifest.finished_at)} />
        <KV k="Server" v={manifest.environment?.hostname ?? '—'} />
        <KV k="Mode" v={manifest.environment?.mode ?? 'host'} />
        <KV k="Versi pg_dump" v={db.pg_dump_version ?? '—'} />
        <KV k="Dipicu oleh" v={manifest.trigger === 'web' ? `web (${manifest.requested_by ?? 'admin'})` : 'jadwal systemd'} />
      </div>

      <SectionTitle>Berkas dalam backup</SectionTitle>
      <div className="rounded-lg ring-1 ring-inset ring-slate-200">
        <table className="min-w-full text-sm">
          <tbody className="divide-y divide-slate-100">
            {(manifest.files ?? []).map((f) => (
              <tr key={f.path}>
                <td className="px-3 py-1 font-mono text-xs text-slate-700">{f.path}</td>
                <td className="px-3 py-1 text-right text-slate-600">{fmtBytes(f.bytes)}{f.files != null ? ` · ${fmtInt(f.files)} berkas` : ''}</td>
                <td className="px-3 py-1 text-right text-xs text-slate-400">{f.mtime ? formatDateTime(f.mtime) : ''}</td>
              </tr>
            ))}
            {arch?.name && (
              <tr><td className="px-3 py-1 font-mono text-xs text-slate-700">{arch.name}</td><td className="px-3 py-1 text-right text-slate-600">{fmtBytes(arch.bytes)}</td><td className="px-3 py-1 text-right text-xs text-slate-400">arsip final</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  )
}

function manifestSubtitle(manifest: BackupManifest): string {
  const kind = manifest.archive_kind === 'core' ? 'Arsip inti harian' : 'Arsip penuh'
  return `${kind} · ${manifest.trigger === 'web' ? 'backup manual dari web' : 'backup terjadwal'}${manifest.requested_by ? ` · oleh ${manifest.requested_by}` : ''}${manifest.status ? ` · ${OPS_STATUS_LABEL[manifest.status] ?? manifest.status}` : ''}`
}

export function BackupDetailModal({ manifest, title, onClose }: { manifest: BackupManifest; title: string; onClose: () => void }) {
  return (
    <ModalShell title={title} subtitle={manifestSubtitle(manifest)} onClose={onClose} wide labelledBy="backup-detail-title">
      <ManifestSections manifest={manifest} />
    </ModalShell>
  )
}

// ---------------------------------------------------------------- Detail catatan riwayat (semua jenis) + aksi
type ArchiveRef = { name: string; bytes: number | null }
type EventActions = {
  isSuper: boolean
  disabled: boolean
  onPdf: (event: OpsEvent) => void
  onDrill: (archive: string) => void
  onRestore: (archive: ArchiveRef) => void
  onDelete: (event: OpsEvent, archive: ArchiveRef | null) => void
}

function EventDetailModal({ event: e, archive, actions, onClose }: { event: OpsEvent; archive: ArchiveRef | null; actions: EventActions; onClose: () => void }) {
  const manifest = manifestOf(e)
  const data = Object.entries(e.data ?? {}).filter(([k]) => k !== 'manifest')
  const highlights = highlightsOf(e)
  return (
    <ModalShell
      title={`${OPS_KIND_LABEL[e.kind] ?? e.kind} — ${formatDateTime(e.created_at)}`}
      subtitle={manifest ? manifestSubtitle(manifest) : `Catatan #${e.id} · dicatat oleh ${e.source || 'sumber tidak dicatat'}`}
      onClose={onClose}
      wide
      labelledBy="event-detail-title"
    >
      <div className="space-y-1" data-testid="event-detail">
        <div className="flex flex-wrap items-center gap-2">
          <span className={cn('badge', OPS_STATUS_BADGE[e.status])}>
            {e.status === 'ok' && <IconCheck className="mr-1 h-3 w-3" />}
            {OPS_STATUS_LABEL[e.status]}
          </span>
          <p className="text-sm font-medium text-slate-800">{e.title}</p>
          {e.data?.backfill ? <span className="badge bg-slate-100 text-slate-600 ring-slate-500/20">rekonstruksi</span> : null}
        </div>
        {e.detail && <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-3 font-mono text-[11px] text-slate-700 ring-1 ring-inset ring-slate-200">{e.detail}</pre>}

        {manifest ? (
          <div className="mt-3"><ManifestSections manifest={manifest} /></div>
        ) : (
          highlights.length > 0 && (
            <div className="mt-3 grid gap-2 sm:grid-cols-3">
              {highlights.map(([label, value]) => <StatBox key={label} label={label} value={value} />)}
            </div>
          )
        )}

        {data.length > 0 && (
          <>
            <SectionTitle>Data tercatat</SectionTitle>
            <div className="grid gap-x-8 sm:grid-cols-2">
              {data.map(([k, v]) => (
                <KV key={k} k={DATA_LABEL[k] ?? k} v={fmtDataValue(k, v)} mono={/sha256|snapshot|request_id|archive$/.test(k)} />
              ))}
            </div>
          </>
        )}

        <SectionTitle>Catatan</SectionTitle>
        <div className="grid gap-x-8 sm:grid-cols-2">
          <KV k="Nomor catatan" v={`#${e.id}`} />
          <KV k="Waktu" v={formatDateTime(e.created_at)} />
          <KV k="Jenis" v={OPS_KIND_LABEL[e.kind] ?? e.kind} />
          <KV k="Durasi" v={fmtDur(e.duration_seconds)} />
          <KV k="Dicatat oleh" v={e.source || '—'} mono={Boolean(e.source)} />
          <KV k="Arsip di server" v={archive ? `ada (${fmtBytes(archive.bytes)})` : 'tidak ada / sudah dirotasi'} />
        </div>
        {storageOf(e).length > 0 && (
          <>
            <SectionTitle>Lokasi penyimpanan</SectionTitle>
            <div className="flex flex-wrap items-center gap-2"><StorageBadges e={e} size="md" /></div>
            <ul className="mt-1 space-y-0.5 text-xs text-slate-500">
              {storageOf(e).map((m) => <li key={m.place}><b className="text-slate-700">{m.place}</b> — {m.note}</li>)}
            </ul>
          </>
        )}

        <div className="mt-4 flex flex-wrap items-center justify-end gap-2 border-t border-slate-100 pt-3">
          <button type="button" className="btn-ghost text-sm" onClick={() => actions.onPdf(e)} title="Unduh laporan PDF catatan ini (lampiran audit)">
            <IconDownload className="h-4 w-4" /> Unduh PDF
          </button>
          {actions.isSuper && archive && (
            <>
              <button type="button" className="btn-ghost text-sm" disabled={actions.disabled} onClick={() => actions.onDrill(archive.name)} title="Uji pulih ke Postgres sementara (produksi tidak disentuh)">
                <IconPlay className="h-4 w-4" /> Uji pulih
              </button>
              <button type="button" className="btn-ghost text-sm !text-rose-700" disabled={actions.disabled} onClick={() => actions.onRestore(archive)} title="Pulihkan produksi dari arsip ini">
                <IconRefresh className="h-4 w-4" /> Pulihkan…
              </button>
            </>
          )}
          {actions.isSuper && (
            <button type="button" className="btn-ghost text-sm !text-rose-700" onClick={() => actions.onDelete(e, archive)} title="Hapus catatan ini (dan opsional berkas arsipnya)">
              <IconTrash className="h-4 w-4" /> Hapus…
            </button>
          )}
          <button type="button" className="btn-primary !px-3 !py-1.5 text-sm" onClick={onClose}>Tutup</button>
        </div>
      </div>
    </ModalShell>
  )
}

// ---------------------------------------------------------------- hapus catatan / arsip
function DeleteModal({
  event, archive, agentAlive, onClose, onDone,
}: {
  event: OpsEvent | null
  archive: ArchiveRef | null
  agentAlive: boolean
  onClose: () => void
  onDone: (msg: string) => void
}) {
  const [delRecord, setDelRecord] = useState(Boolean(event))
  const [delArchive, setDelArchive] = useState(Boolean(archive) && !event)
  const [confirm, setConfirm] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const mut = useMutation({
    mutationFn: async () => {
      const done: string[] = []
      if (delArchive && archive) {
        await api.deleteArchive(archive.name, confirm.toUpperCase())
        done.push(`penghapusan arsip ${archive.name} dikirim ke agen host`)
      }
      if (delRecord && event) {
        await api.deleteOpsEvent(event.id)
        done.push(`catatan #${event.id} dihapus`)
      }
      return done.join('; ')
    },
    onSuccess: (msg) => onDone(msg),
    onError: (e) => setErr(e instanceof ApiError ? e.message : 'Gagal menghapus.'),
  })
  const needPhrase = delArchive
  const valid = (delRecord || delArchive) && (!needPhrase || confirm.toUpperCase() === DELETE_PHRASE)
  return (
    <ModalShell title="Hapus?" subtitle="Tindakan tercatat di Log Aktivitas Admin." onClose={onClose} labelledBy="ops-delete-title">
      <div className="space-y-3 text-sm text-slate-700" data-testid="delete-modal">
        {event && (
          <label className="flex items-start gap-2">
            <input type="checkbox" className="mt-0.5 h-4 w-4 rounded border-slate-300" checked={delRecord} disabled={!archive} onChange={(ev) => setDelRecord(ev.target.checked)} />
            <span>
              <b>Hapus catatan riwayat #{event.id}</b> — {OPS_KIND_LABEL[event.kind] ?? event.kind} · {formatDateTime(event.created_at)}
              <br /><span className="text-xs text-slate-500">{event.title}</span>
            </span>
          </label>
        )}
        {archive && (
          <label className={cn('flex items-start gap-2', !agentAlive && 'opacity-60')}>
            <input type="checkbox" className="mt-0.5 h-4 w-4 rounded border-slate-300" checked={delArchive} disabled={!agentAlive} onChange={(ev) => setDelArchive(ev.target.checked)} />
            <span>
              <b>Hapus berkas arsip di server</b> <span className="font-mono text-xs">{archive.name}</span> ({fmtBytes(archive.bytes)})
              <br /><span className="text-xs text-slate-500">
                Beserta .sha256 dan manifest-nya; dijalankan agen host. Salinan di Google Drive <b>tidak</b> dihapus sekarang —
                pada sinkronisasi berikutnya ia dipindah ke folder versi (disimpan 21 hari). Snapshot restic tidak berubah.
                {!agentAlive && ' Agen host sedang tidak aktif, jadi opsi ini belum bisa dipilih.'}
              </span>
            </span>
          </label>
        )}
        {needPhrase && (
          <div>
            <label className="label" htmlFor="delete-confirm">Ketik <b>{DELETE_PHRASE}</b> untuk menghapus berkas arsip</label>
            <input id="delete-confirm" className="input w-full font-mono" value={confirm} onChange={(ev) => setConfirm(ev.target.value.toUpperCase())} autoComplete="off" placeholder={DELETE_PHRASE} />
          </div>
        )}
        {delRecord && event && (
          <p className="text-xs text-slate-500">
            Catatan yang dihapus hilang dari riwayat dan ekspor CSV; jejak penghapusannya (siapa, kapan, catatan apa) tetap tersimpan di audit.
          </p>
        )}
        {err && <p className="text-sm text-rose-600">{err}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onClose}>Batal</button>
          <button type="button" className="btn-danger" disabled={!valid || mut.isPending} onClick={() => { setErr(null); mut.mutate() }}>
            {mut.isPending ? 'Menghapus…' : 'Hapus'}
          </button>
        </div>
      </div>
    </ModalShell>
  )
}

// ---------------------------------------------------------------- konfirmasi aksi sederhana
function ConfirmModal({
  title, body, confirmLabel, danger, busy, error, onConfirm, onClose,
}: {
  title: string
  body: React.ReactNode
  confirmLabel: string
  danger?: boolean
  busy: boolean
  error: string | null
  onConfirm: () => void
  onClose: () => void
}) {
  return (
    <ModalShell title={title} onClose={onClose} labelledBy="ops-confirm-title">
      <div className="space-y-3 text-sm text-slate-700">{body}</div>
      {error && <p className="mt-3 text-sm text-rose-600">{error}</p>}
      <div className="mt-4 flex justify-end gap-2">
        <button type="button" className="btn-ghost" onClick={onClose}>Batal</button>
        <button type="button" className={danger ? 'btn-danger' : 'btn-primary'} disabled={busy} onClick={onConfirm}>
          {busy ? 'Mengirim…' : confirmLabel}
        </button>
      </div>
    </ModalShell>
  )
}

// ---------------------------------------------------------------- wizard restore
function RestoreModal({
  source, onClose, onStarted,
}: {
  source: { type: RestoreSourceType; name: string; label: string; hasUsers: boolean; hasEnv: boolean }
  onClose: () => void
  onStarted: (req: OpsRequest) => void
}) {
  const qc = useQueryClient()
  const [scope, setScope] = useState<RestoreScope[]>(source.hasUsers ? ['db', 'users'] : ['db'])
  const [ack, setAck] = useState(false)
  const [confirm, setConfirm] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const preQ = useQuery({ queryKey: ['ops-precheck'], queryFn: () => api.getOpsPrecheck(), refetchInterval: 5000, retry: false })
  const pre: OpsPrecheck | undefined = preQ.data
  const sessions = pre?.sessions_total ?? 0
  const maintMut = useMutation({
    mutationFn: () => api.setMaintenanceMode(true, 'Pemulihan data sedang disiapkan. Pekerjaan baru ditahan sementara.'),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['maintenance-mode'] }); void preQ.refetch() },
    onError: (e) => setErr(e instanceof ApiError ? e.message : 'Gagal menyalakan mode pemeliharaan.'),
  })
  const mut = useMutation({
    mutationFn: () => api.startRestore({
      source_type: source.type, source: source.name, scope, stop_sessions: sessions > 0 && ack,
      confirm, acknowledge_sessions: ack,
    }),
    onSuccess: (req) => onStarted(req),
    onError: (e) => {
      if (e instanceof ApiError) {
        try {
          const d = JSON.parse(e.message) as { message?: string }
          setErr(d.message ?? e.message)
        } catch { setErr(e.message) }
      } else setErr('Gagal mengirim permintaan restore.')
    },
  })
  const toggle = (s: RestoreScope) => setScope((cur) => (cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s]))
  const agentOk = pre?.agent?.alive ?? false
  const valid = scope.length > 0 && confirm === CONFIRM_PHRASE && agentOk && (sessions === 0 || ack) && !pre?.active_request
  return (
    <ModalShell
      title={`Pulihkan dari ${source.label}`}
      subtitle={`Sumber: ${SOURCE_TYPE_LABEL[source.type]} · ${source.name}`}
      onClose={onClose}
      labelledBy="restore-title"
    >
      <div className="space-y-4 text-sm text-slate-700" data-testid="restore-wizard">
        <div className="rounded-lg bg-rose-50 px-3 py-2 text-rose-800 ring-1 ring-inset ring-rose-600/20">
          <p className="font-semibold">Operasi destruktif.</p>
          <p className="text-xs">
            Data saat ini pada cakupan yang dipilih akan DITIMPA dengan isi sumber. Aplikasi dimatikan beberapa menit
            selama proses (halaman ini akan terputus lalu menyambung kembali). Snapshot kondisi sekarang diambil otomatis
            sebelum menimpa — tersedia sebagai <b>titik rollback</b> bila hasilnya tidak sesuai.
          </p>
        </div>

        <div>
          <p className="label">Cakupan pemulihan</p>
          <div className="space-y-1.5">
            <label className="flex items-start gap-2">
              <input type="checkbox" className="mt-0.5 h-4 w-4 rounded border-slate-300" checked={scope.includes('db')} onChange={() => toggle('db')} />
              <span><b>Database</b> — akun, kebijakan, riwayat job, notifikasi, audit (dari db.sql)</span>
            </label>
            <label className={cn('flex items-start gap-2', !source.hasUsers && 'opacity-50')}>
              <input type="checkbox" className="mt-0.5 h-4 w-4 rounded border-slate-300" disabled={!source.hasUsers} checked={scope.includes('users')} onChange={() => toggle('users')} />
              <span><b>Workspace pengguna</b> — seluruh berkas /persist semua akun (berkas yang lebih baru dari sumber akan hilang)</span>
            </label>
            <label className={cn('flex items-start gap-2', !source.hasEnv && 'opacity-50')}>
              <input type="checkbox" className="mt-0.5 h-4 w-4 rounded border-slate-300" disabled={!source.hasEnv} checked={scope.includes('env')} onChange={() => toggle('env')} />
              <span><b>Konfigurasi backend (.env)</b> — hanya bila konfigurasi saat ini rusak; biasanya tidak perlu</span>
            </label>
          </div>
        </div>

        <div className="rounded-lg bg-slate-50 px-3 py-2 ring-1 ring-inset ring-slate-200">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Pemeriksaan sebelum pulih</p>
          {preQ.isLoading ? (
            <p className="text-xs text-slate-500">Memeriksa…</p>
          ) : pre ? (
            <ul className="mt-1 space-y-0.5 text-xs">
              <li className={agentOk ? 'text-emerald-700' : 'text-rose-700'}>
                Agen host: {agentOk ? 'aktif' : 'TIDAK aktif — restore dari web tidak bisa dijalankan'}
              </li>
              <li className={sessions === 0 ? 'text-emerald-700' : 'text-amber-700'}>
                Pekerjaan berjalan: {pre.jobs_running} job · {pre.kernels_active} kernel notebook · {pre.devboxes_running} Devbox
              </li>
              <li className={pre.maintenance_active ? 'text-emerald-700' : 'text-slate-600'}>
                Mode pemeliharaan: {pre.maintenance_active ? 'aktif (pekerjaan baru ditahan)' : 'tidak aktif'}
                {!pre.maintenance_active && (
                  <button type="button" className="ml-2 text-brand-600 underline" disabled={maintMut.isPending} onClick={() => maintMut.mutate()}>
                    nyalakan sekarang
                  </button>
                )}
              </li>
              {pre.active_request && (
                <li className="text-rose-700">Masih ada permintaan {ACTION_LABEL[pre.active_request.action] ?? pre.active_request.action} yang {REQ_LABEL[pre.active_request.status]}.</li>
              )}
            </ul>
          ) : (
            <p className="text-xs text-rose-600">Pemeriksaan gagal dimuat.</p>
          )}
        </div>

        {sessions > 0 && (
          <label className="flex items-start gap-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800 ring-1 ring-inset ring-amber-600/20">
            <input type="checkbox" className="mt-0.5 h-4 w-4 rounded border-slate-300" checked={ack} onChange={(e) => setAck(e.target.checked)} />
            <span>
              Saya mengerti <b>{sessions} sesi yang sedang berjalan akan dihentikan</b> (hasil yang belum tersimpan hilang).
              Disarankan: nyalakan mode pemeliharaan dan tunggu sampai angka di atas nol.
            </span>
          </label>
        )}

        <div>
          <label className="label" htmlFor="restore-confirm">Ketik <b>{CONFIRM_PHRASE}</b> untuk melanjutkan</label>
          <input id="restore-confirm" className="input w-full font-mono" value={confirm} onChange={(e) => setConfirm(e.target.value.toUpperCase())} autoComplete="off" placeholder={CONFIRM_PHRASE} />
        </div>

        {err && <p className="text-sm text-rose-600">{err}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onClose}>Batal</button>
          <button type="button" className="btn-danger" disabled={!valid || mut.isPending} onClick={() => { setErr(null); mut.mutate() }}>
            {mut.isPending ? 'Mengirim…' : 'Pulihkan sekarang'}
          </button>
        </div>
      </div>
    </ModalShell>
  )
}

// ---------------------------------------------------------------- permintaan aktif + log
function RequestCard({ req, onDone }: { req: OpsRequest; onDone: () => void }) {
  const [showLog, setShowLog] = useState(false)
  const live = req.status === 'pending' || req.status === 'running'
  const detailQ = useQuery({
    queryKey: ['ops-request', req.id],
    queryFn: () => api.getOpsRequest(req.id),
    refetchInterval: live ? 3000 : false,
    retry: false,
    enabled: showLog || live,
  })
  const d = detailQ.data ?? req
  useEffect(() => {
    if (d.status === 'ok' || d.status === 'fail') onDone()
    // onDone hanya memicu refetch daftar; aman dipanggil saat status final berubah.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [d.status])
  const offline = live && detailQ.isError && !(detailQ.error instanceof ApiError)
  return (
    <div className={cn('card card-pad space-y-2', live && 'ring-2 ring-inset ring-brand-500/30')} data-testid="ops-request-card">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {live && <Spinner className="h-4 w-4" />}
          <p className="font-semibold text-slate-800">{ACTION_LABEL[d.action] ?? d.action}</p>
          <span className={cn('badge', REQ_BADGE[d.status] ?? REQ_BADGE.pending)}>{REQ_LABEL[d.status] ?? d.status}</span>
          {d.requested_by?.username && <span className="text-xs text-slate-500">oleh {d.requested_by.username}</span>}
        </div>
        <p className="text-xs text-slate-500">
          #{d.id} · {formatDateTime(d.created_at)}
          {d.finished_at ? ` → selesai ${formatDateTime(d.finished_at)}` : d.started_at ? ` → mulai ${formatDateTime(d.started_at)}` : ''}
        </p>
      </div>
      {d.params?.source && (
        <p className="text-xs text-slate-600">
          Sumber: {SOURCE_TYPE_LABEL[d.params.source_type ?? 'archive']} <span className="font-mono">{d.params.source}</span>
          {d.params.scope ? ` · cakupan ${d.params.scope.join(', ')}` : ''}{d.params.stop_sessions ? ' · sesi berjalan dihentikan' : ''}
        </p>
      )}
      {d.params?.archive && <p className="text-xs text-slate-600">Arsip: <span className="font-mono">{d.params.archive}</span></p>}
      {offline && (
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800 ring-1 ring-inset ring-amber-600/20">
          Aplikasi sedang dimatikan oleh proses pemulihan — koneksi terputus sementara. Halaman ini mencoba menyambung
          kembali otomatis; jangan tutup sampai status menjadi Selesai.
        </p>
      )}
      {d.message && <p className="text-xs text-rose-600">{d.message}</p>}
      {live && d.last_line && !showLog && <p className="truncate font-mono text-[11px] text-slate-500">{d.last_line}</p>}
      <div className="flex items-center gap-2">
        <button type="button" className="btn-ghost !px-2 !py-1 text-xs" onClick={() => setShowLog((v) => !v)}>
          {showLog ? 'Sembunyikan log' : 'Lihat log'}
        </button>
        {d.exit_code != null && <span className="text-[11px] text-slate-400">exit {d.exit_code}</span>}
      </div>
      {showLog && (
        <pre className="max-h-64 overflow-auto rounded-lg bg-slate-900 p-3 font-mono text-[11px] leading-relaxed text-slate-100">
          {(detailQ.data?.log ?? '') || (detailQ.isLoading ? 'Memuat log…' : 'Belum ada keluaran.')}
        </pre>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- panel utama
export default function BackupRestorePanel() {
  const { user } = useAuth()
  const qc = useQueryClient()
  const isSuper = Boolean(user?.is_superadmin)
  const [kind, setKind] = useState<OpsEventKind | ''>('')
  const [eventModal, setEventModal] = useState<OpsEvent | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<{ event: OpsEvent | null; archive: ArchiveRef | null } | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [manifestModal, setManifestModal] = useState<{ manifest: BackupManifest; title: string } | null>(null)
  const [restoreTarget, setRestoreTarget] = useState<{ type: RestoreSourceType; name: string; label: string; hasUsers: boolean; hasEnv: boolean } | null>(null)
  const [confirmAction, setConfirmAction] = useState<{ kind: 'backup' } | { kind: 'drill'; archive: string | null } | null>(null)
  const [tab, setTab] = useState<'archives' | 'restic' | 'offsite' | 'rollback'>('archives')
  const [unduhErr, setUnduhErr] = useState<string | null>(null)
  const [actionErr, setActionErr] = useState<string | null>(null)
  const [showAllRequests, setShowAllRequests] = useState(false)

  const statusQ = useQuery({ queryKey: ['admin-backup-status'], queryFn: () => api.getBackupStatus(), refetchInterval: 60000, retry: false })
  const eventsQ = useQuery({
    queryKey: ['admin-ops-events', kind],
    queryFn: () => api.listOpsEvents(kind || undefined, 200),
    refetchInterval: 60000,
    retry: false,
    enabled: statusQ.isSuccess,
  })
  const agentQ = useQuery({ queryKey: ['ops-agent'], queryFn: () => api.getOpsAgent(), refetchInterval: 10000, retry: false, enabled: statusQ.isSuccess })
  const sourcesQ = useQuery({ queryKey: ['ops-sources'], queryFn: () => api.getBackupSources(), refetchInterval: 60000, retry: false, enabled: statusQ.isSuccess })
  const requestsQ = useQuery({ queryKey: ['ops-requests'], queryFn: () => api.listOpsRequests(30), refetchInterval: 5000, retry: false, enabled: statusQ.isSuccess })

  const s = statusQ.data
  const rows = eventsQ.data ?? []
  const belumAktif = statusQ.error instanceof ApiError && statusQ.error.status === 404
  const agent = isRecord(agentQ.data) ? agentQ.data : null
  const agentAlive = Boolean(agent?.alive)
  const sources = useMemo(() => normalizeSources(sourcesQ.data), [sourcesQ.data])
  const requests = useMemo(() => (Array.isArray(requestsQ.data) ? requestsQ.data.filter((r) => isRecord(r) && KNOWN_ACTIONS.has(String(r.action)) && typeof r.id === 'string') : []), [requestsQ.data])
  const activeReq = requests.find((r) => r.status === 'pending' || r.status === 'running') ?? null
  const recentReqs = showAllRequests ? requests : requests.slice(0, 3)
  const opsReady = agentQ.isSuccess && isRecord(agentQ.data) && 'alive' in agentQ.data

  const refetchAll = () => {
    void statusQ.refetch(); void eventsQ.refetch(); void agentQ.refetch(); void sourcesQ.refetch(); void requestsQ.refetch()
  }
  const invalidateOps = () => {
    void qc.invalidateQueries({ queryKey: ['ops-requests'] })
    void qc.invalidateQueries({ queryKey: ['ops-sources'] })
    void qc.invalidateQueries({ queryKey: ['admin-ops-events'] })
    void qc.invalidateQueries({ queryKey: ['admin-backup-status'] })
  }

  const backupMut = useMutation({
    mutationFn: () => api.startBackup(),
    onSuccess: () => { setConfirmAction(null); setActionErr(null); invalidateOps() },
    onError: (e) => setActionErr(e instanceof ApiError ? e.message : 'Gagal memulai backup.'),
  })
  const drillMut = useMutation({
    mutationFn: (archive: string | null) => api.startDrill(archive),
    onSuccess: () => { setConfirmAction(null); setActionErr(null); invalidateOps() },
    onError: (e) => setActionErr(e instanceof ApiError ? e.message : 'Gagal memulai uji pulih.'),
  })
  const refreshMut = useMutation({
    mutationFn: () => api.refreshBackupSources(),
    onSuccess: () => { setActionErr(null); invalidateOps() },
    onError: (e) => setActionErr(e instanceof ApiError ? e.message : 'Gagal meminta penyegaran sumber.'),
  })

  const unduhCsv = async () => {
    try {
      setUnduhErr(null)
      const blob = await api.downloadOpsEventsCsv(kind || undefined)
      simpanBlob(blob, `bukti_cadangan_${new Date().toISOString().slice(0, 10)}.csv`)
    } catch (e) {
      setUnduhErr(e instanceof ApiError ? e.message : 'Gagal mengunduh CSV.')
    }
  }
  const unduhPdf = async (e: OpsEvent) => {
    try {
      setUnduhErr(null)
      const blob = await api.downloadOpsEventPdf(e.id)
      const stamp = new Date(e.created_at).toISOString().slice(0, 16).replace(/[-:T]/g, '').replace(/(\d{8})(\d{4})/, '$1_$2')
      simpanBlob(blob, `cadangan_${e.kind}_${e.id}_${stamp}.pdf`)
    } catch (err) {
      setUnduhErr(err instanceof ApiError ? err.message : 'Gagal mengunduh PDF.')
    }
  }

  const lb = s?.last_backup
  const ld = s?.last_restore_drill
  const lbData = (lb?.data ?? {}) as Record<string, string | number | undefined>
  const ldData = (ld?.data ?? {}) as Record<string, string | number | undefined>

  const openEvent = (e: OpsEvent) => setEventModal(e)
  /** Arsip yang masih ada di server untuk catatan backup ini (bisa diuji pulih / dipulihkan / dihapus). */
  const archiveOf = (e: OpsEvent): ArchiveRef | null => {
    const name = typeof e.data?.archive === 'string' ? e.data.archive : ''
    if (!name) return null
    const found = sources.archives.find((a) => a.name === name)
    return found ? { name: found.name, bytes: found.bytes } : null
  }
  const restoreOfArchive = (ref: ArchiveRef) => {
    const a = sources.archives.find((x) => x.name === ref.name)
    return {
      type: 'archive' as const, name: ref.name, label: ref.name,
      hasUsers: a?.manifest ? (a.manifest.workspaces?.accounts_total ?? 0) > 0 : true,
      hasEnv: a?.manifest ? Boolean(a.manifest.components?.env?.included) : true,
    }
  }
  const busyLabel = activeReq ? `${ACTION_LABEL[activeReq.action]} sedang ${REQ_LABEL[activeReq.status].toLowerCase()}` : null
  // Permintaan "ringan" (segarkan sumber / hapus arsip) tidak mengunci tombol aksi lain.
  const actionsDisabled = !agentAlive || Boolean(activeReq && !['refresh_sources', 'delete_archive'].includes(activeReq.action))
  const eventActions: EventActions = {
    isSuper,
    disabled: actionsDisabled,
    onPdf: (e) => { void unduhPdf(e) },
    onDrill: (archive) => { setEventModal(null); setActionErr(null); setConfirmAction({ kind: 'drill', archive }) },
    onRestore: (ref) => { setEventModal(null); setRestoreTarget(restoreOfArchive(ref)) },
    onDelete: (e, archive) => { setEventModal(null); setDeleteTarget({ event: e, archive }) },
  }

  return (
    <>
      <div className="space-y-6" data-testid="backup-evidence">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="gradient-text text-2xl font-bold">Cadangan &amp; Pemulihan</h1>
            <p className="text-sm text-slate-500">
              Backup, rincian isi, uji pulih, dan pemulihan dikelola dari sini. Bukti tersimpan permanen di database — siap ditunjukkan saat audit.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {opsReady && (
              <span
                className={cn('badge', agentAlive ? 'bg-emerald-50 text-emerald-700 ring-emerald-600/20' : 'bg-rose-50 text-rose-700 ring-rose-600/20')}
                title={agentAlive ? `Agen host aktif (terakhir terlihat ${agent?.age_seconds ?? 0} dtk lalu)` : 'Agen host computehub-ops-agent tidak terdeteksi — backup/restore dari web tidak tersedia'}
                data-testid="ops-agent-badge"
              >
                <IconShield className="mr-1 h-3 w-3" />
                {agentAlive ? 'Agen host aktif' : 'Agen host tidak aktif'}
              </span>
            )}
            {isSuper && opsReady && (
              <button
                type="button"
                className="btn-primary !px-3 !py-1.5 text-sm"
                disabled={actionsDisabled}
                onClick={() => { setActionErr(null); setConfirmAction({ kind: 'backup' }) }}
                title={busyLabel ?? (agentAlive ? 'Buat arsip penuh sekarang (DB + workspace + konfigurasi) lalu unggah ke Drive' : 'Agen host tidak aktif')}
              >
                <IconUpload className="h-4 w-4" />
                Backup sekarang
              </button>
            )}
            <button type="button" onClick={unduhCsv} disabled={!s || s.events_total === 0} className="btn-ghost" title="Unduh seluruh riwayat sebagai CSV untuk lampiran audit">
              <IconDownload className="h-4 w-4" />
              Unduh CSV
            </button>
            <RefreshButton onRefresh={refetchAll} />
          </div>
        </div>

        {unduhErr && <p className="text-sm text-rose-600">{unduhErr}</p>}
        {actionErr && <p className="text-sm text-rose-600">{actionErr}</p>}
        {notice && (
          <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-700 ring-1 ring-inset ring-emerald-600/20" data-testid="ops-notice">
            {notice}
            <button type="button" className="ml-2 text-xs underline" onClick={() => setNotice(null)}>tutup</button>
          </p>
        )}

        {statusQ.isLoading ? (
          <Spinner label="Memuat bukti cadangan…" className="p-6" />
        ) : belumAktif ? (
          <div className="card card-pad text-sm text-amber-700">
            Backend belum memuat modul bukti cadangan. Riwayat tetap dicatat skrip ke database dan akan
            tampil setelah backend diperbarui pada waktu aman.
          </div>
        ) : statusQ.error ? (
          <div className="card card-pad text-sm text-rose-600">
            {statusQ.error instanceof ApiError ? statusQ.error.message : 'Gagal memuat status cadangan.'}
          </div>
        ) : s ? (
          <>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <StatusCard title="Backup terakhir" status={lb?.status ?? 'none'}>
                {lb ? (
                  <>
                    <p className="font-medium">{formatDateTime(lb.created_at)} <span className="text-slate-400">· {umurHari(lb.created_at)}</span></p>
                    <p className="truncate" title={String(lbData.archive || lbData.core_archive || '')}>
                      {lbData.archive ? `Arsip penuh: ${lbData.archive}` : lbData.core_archive ? `Arsip inti: ${lbData.core_archive}` : 'Arsip tar dilewati (restic tetap jalan)'}
                    </p>
                    <p className="text-xs text-slate-500">
                      {lbData.archive ? `Penuh → Drive: ${String(lbData.offsite_tar ?? '—')}${lbData.tar_local_deleted ? ' (salinan server dihapus)' : ''} · ` : ''}
                      {lbData.core_archive ? `Inti → Drive: ${String(lbData.core_offsite ?? '—')} · ` : ''}
                      Restic{String(lbData.restic_repo ?? '').startsWith('rclone:') ? ' (Drive)' : ''}: {String(lbData.restic ?? '—')}
                      {!lbData.core_archive && lbData.restic_offsite ? ` · Restic offsite: ${lbData.restic_offsite}` : ''}
                    </p>
                    {manifestOf(lb) && (
                      <button type="button" className="text-xs font-medium text-brand-600 hover:underline" onClick={() => openEvent(lb)}>
                        Lihat rincian backup
                      </button>
                    )}
                  </>
                ) : (
                  <p className="text-slate-500">Menunggu backup terjadwal berikutnya (02:30 WITA).</p>
                )}
              </StatusCard>
              <StatusCard title="Snapshot restic" status={s.restic_snapshots_recorded > 0 ? 'ok' : 'none'}>
                <p className="font-medium">{s.restic_snapshots_recorded} snapshot tercatat</p>
                <p className="text-xs text-slate-500">Terbaru: {s.restic_latest_at ? `${formatDateTime(s.restic_latest_at)} (${umurHari(s.restic_latest_at)})` : '—'}</p>
                <p className="text-xs text-slate-500">{s.policy.restic_keep}</p>
              </StatusCard>
              <StatusCard title="Restore drill terakhir" status={ld?.status ?? 'none'}>
                {ld ? (
                  <>
                    <p className="font-medium">{formatDateTime(ld.created_at)} <span className="text-slate-400">· {umurHari(ld.created_at)}</span></p>
                    <p>
                      {ldData.tables != null ? `${ldData.tables} tabel · ${ldData.users} user · ${ldData.jobs} job dipulihkan` : ld.title}
                    </p>
                    <p className="text-xs text-slate-500">{s.policy.restore_drill}</p>
                  </>
                ) : (
                  <p className="text-slate-500">{s.policy.restore_drill}</p>
                )}
              </StatusCard>
              <StatusCard title="Arsip di server" status={s.local.archives.length > 0 ? 'ok' : 'none'}>
                <p className="font-medium">{s.local.archives.length} arsip terenkripsi</p>
                {s.local.archives[0] && (
                  <p className="truncate text-xs text-slate-500" title={s.local.archives[0].name}>
                    Terbaru {fmtGb(s.local.archives[0].bytes)} · {umurHari(s.local.archives[0].mtime)}
                  </p>
                )}
                <p className="text-xs text-slate-500">Mingguan {s.local.weekly} · Bulanan {s.local.monthly} · {s.policy.offsite}</p>
              </StatusCard>
            </div>

            <div className="card overflow-hidden">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-2">
                <p className="text-sm font-semibold text-slate-700">Riwayat ({s.events_total} catatan)</p>
                <select
                  value={kind}
                  onChange={(e) => setKind(e.target.value as OpsEventKind | '')}
                  className="input w-auto py-1 text-xs"
                  aria-label="Saring jenis bukti"
                >
                  <option value="">Semua jenis</option>
                  {(Object.keys(OPS_KIND_LABEL) as OpsEventKind[]).map((k) => (
                    <option key={k} value={k}>{OPS_KIND_LABEL[k]}</option>
                  ))}
                </select>
              </div>
              {eventsQ.isLoading ? (
                <Spinner label="Memuat riwayat…" className="p-6" />
              ) : rows.length === 0 ? (
                <p className="p-6 text-sm text-slate-500">Belum ada catatan untuk jenis ini.</p>
              ) : (
                <div className="max-h-[28rem] overflow-auto">
                  <table className="min-w-full divide-y divide-slate-200">
                    <thead className="sticky top-0 bg-slate-50">
                      <tr>
                        <th className="table-th">Waktu</th>
                        <th className="table-th">Jenis</th>
                        <th className="table-th">Status</th>
                        <th className="table-th">Lokasi</th>
                        <th className="table-th">Keterangan</th>
                        <th className="table-th">Durasi</th>
                        <th className="table-th text-right">Aksi</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {rows.map((e) => {
                        const arch = archiveOf(e)
                        return (
                        <tr
                          key={e.id}
                          className="cursor-pointer hover:bg-slate-50"
                          onClick={() => openEvent(e)}
                          title="Klik untuk detail lengkap"
                        >
                          <td className="table-td whitespace-nowrap text-slate-500">{formatDateTime(e.created_at)}</td>
                          <td className="table-td whitespace-nowrap text-slate-600">{OPS_KIND_LABEL[e.kind] ?? e.kind}</td>
                          <td className="table-td">
                            <span className={cn('badge', OPS_STATUS_BADGE[e.status])}>
                              {e.status === 'ok' && <IconCheck className="mr-1 h-3 w-3" />}
                              {OPS_STATUS_LABEL[e.status]}
                            </span>
                          </td>
                          <td className="table-td whitespace-nowrap"><StorageBadges e={e} /></td>
                          <td className="table-td max-w-[28rem] truncate text-slate-700" title={e.title}>
                            {e.title}
                            {e.data?.backfill ? <span className="ml-1 text-[11px] text-slate-400">(rekonstruksi)</span> : null}
                            {manifestOf(e) ? <span className="ml-1 text-[11px] text-brand-600">(rincian)</span> : null}
                          </td>
                          <td className="table-td whitespace-nowrap text-slate-500">
                            {e.duration_seconds != null ? `${Math.round(e.duration_seconds / 60)} mnt` : '—'}
                          </td>
                          <td className="table-td whitespace-nowrap text-right" onClick={(ev) => ev.stopPropagation()}>
                            <div className="flex items-center justify-end gap-0.5">
                              <button type="button" className="btn-ghost !p-1.5" title="Lihat detail lengkap" aria-label={`Detail catatan ${e.id}`} onClick={() => openEvent(e)}>
                                <IconEye className="h-4 w-4" />
                              </button>
                              <button type="button" className="btn-ghost !p-1.5" title="Unduh laporan PDF catatan ini" aria-label={`Unduh PDF catatan ${e.id}`} onClick={() => { void unduhPdf(e) }}>
                                <IconDownload className="h-4 w-4" />
                              </button>
                              {isSuper && arch && (
                                <>
                                  <button type="button" className="btn-ghost !p-1.5" title="Uji pulih arsip ini (Postgres sementara)" aria-label={`Uji pulih ${arch.name}`} disabled={actionsDisabled} onClick={() => eventActions.onDrill(arch.name)}>
                                    <IconPlay className="h-4 w-4" />
                                  </button>
                                  <button type="button" className="btn-ghost !p-1.5 !text-rose-700" title="Pulihkan produksi dari arsip ini" aria-label={`Pulihkan dari ${arch.name}`} disabled={actionsDisabled} onClick={() => eventActions.onRestore(arch)}>
                                    <IconRefresh className="h-4 w-4" />
                                  </button>
                                </>
                              )}
                              {isSuper && (
                                <button type="button" className="btn-ghost !p-1.5 !text-rose-600" title={arch ? 'Hapus catatan dan/atau berkas arsipnya' : 'Hapus catatan ini'} aria-label={`Hapus catatan ${e.id}`} onClick={() => setDeleteTarget({ event: e, archive: arch })}>
                                  <IconTrash className="h-4 w-4" />
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
            <p className="text-xs text-slate-500">
              Jadwal: {s.policy.backup_schedule}. Retensi tar: {s.policy.tar_keep}.
            </p>
          </>
        ) : null}
      </div>

      {/* ------------------------------------------------ pemulihan: sumber + permintaan (di luar testid bukti) */}
      {s && opsReady && (
        <div className="space-y-3" data-testid="backup-restore">
          {recentReqs.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-sm font-semibold text-slate-700">Permintaan dari web</p>
                {requests.length > 3 && (
                  <button type="button" className="text-xs text-brand-600 hover:underline" onClick={() => setShowAllRequests((v) => !v)}>
                    {showAllRequests ? 'Ringkas' : `Tampilkan semua (${requests.length})`}
                  </button>
                )}
              </div>
              {recentReqs.map((r) => <RequestCard key={r.id} req={r} onDone={invalidateOps} />)}
            </div>
          )}

          <div className="card overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-2">
              <div>
                <p className="text-sm font-semibold text-slate-700">Sumber pemulihan</p>
                <p className="text-[11px] text-slate-500">
                  {sources.available ? `Diperbarui ${formatDateTime(sources.generated_at)}` : 'Belum ada data dari agen host'}
                  {sources.disk?.free_bytes != null ? ` · disk server bebas ${fmtBytes(sources.disk.free_bytes)}` : ''}
                </p>
              </div>
              <div className="flex items-center gap-1">
                {([
                  ['archives', `Arsip server (${sources.archives.length})`],
                  ['restic', `Snapshot restic${sources.restic.location === 'drive' ? ' · Drive' : ''} (${sources.restic.snapshots.length})`],
                  ['offsite', `Arsip di Drive (${sources.offsite.archives.length})`],
                  ['rollback', `Titik rollback (${sources.pre_restore.length})`],
                ] as const).map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    onClick={() => setTab(id)}
                    className={cn('rounded-full px-3 py-1 text-xs font-medium ring-1 ring-inset transition', tab === id ? 'bg-brand-50 text-brand-700 ring-brand-600/30' : 'text-slate-600 ring-slate-200 hover:bg-slate-50')}
                  >
                    {label}
                  </button>
                ))}
                <button type="button" className="btn-ghost !px-2 !py-1 text-xs" disabled={refreshMut.isPending || !agentAlive} onClick={() => refreshMut.mutate()} title="Minta agen host memindai ulang arsip, snapshot, dan Drive">
                  Segarkan
                </button>
              </div>
            </div>

            {!agentAlive && (
              <p className="border-b border-slate-100 bg-rose-50 px-4 py-2 text-xs text-rose-700">
                Agen host <span className="font-mono">computehub-ops-agent.service</span> tidak terdeteksi. Backup, uji pulih, dan restore
                dari web membutuhkannya; data sumber di bawah mungkin tidak terbaru.
              </p>
            )}

            {tab === 'archives' && (
              <SourceTable
                empty="Belum ada arsip terenkripsi di server (arsip inti harian dibuat tiap 02:30; arsip penuh hanya di Drive)."
                rows={sources.archives.map((a) => ({
                  key: a.name,
                  main: a.name,
                  sub: `${ARCHIVE_KIND_LABEL[a.kind ?? archiveKindOf(a.name)]} · ${a.encrypted ? 'terenkripsi' : 'polos'}${a.sha256 ? ' · SHA256 ✓' : ''}${a.manifest?.workspaces?.accounts_total ? ` · ${a.manifest.workspaces.accounts_total} akun` : ''}`,
                  when: a.mtime,
                  size: a.bytes,
                  manifest: a.manifest,
                  restore: { type: 'archive', name: a.name, label: a.name, hasUsers: a.manifest ? (a.manifest.workspaces?.accounts_total ?? 0) > 0 : (a.kind ?? archiveKindOf(a.name)) === 'full', hasEnv: a.manifest ? Boolean(a.manifest.components?.env?.included) : true },
                  drill: a.encrypted ? a.name : null,
                  deletable: a.encrypted ? { name: a.name, bytes: a.bytes } : null,
                }))}
                isSuper={isSuper}
                disabled={actionsDisabled}
                onDetail={(m, title) => setManifestModal({ manifest: m, title })}
                onRestore={setRestoreTarget}
                onDrill={(archive) => { setActionErr(null); setConfirmAction({ kind: 'drill', archive }) }}
                onDelete={(ref) => setDeleteTarget({ event: null, archive: ref })}
              />
            )}
            {tab === 'restic' && (
              sources.restic.available || sources.restic.snapshots.length > 0 ? (
                <SourceTable
                  empty="Belum ada snapshot restic."
                  rows={sources.restic.snapshots.map((sn) => ({
                    key: sn.id,
                    main: `Snapshot ${sn.short_id}`,
                    sub: `${sn.summary?.total_files_processed != null ? `${fmtInt(sn.summary.total_files_processed)} berkas` : 'harian'}${sn.tags?.length ? ` · ${sn.tags.join(', ')}` : ''} · dedup, terenkripsi${sources.restic.location === 'drive' ? ' · tersimpan di Google Drive' : ''}`,
                    when: sn.time,
                    size: sn.summary?.total_bytes_processed ?? null,
                    manifest: null,
                    restore: { type: 'snapshot', name: sn.id, label: `snapshot ${sn.short_id}`, hasUsers: true, hasEnv: true },
                    drill: null,
                  }))}
                  isSuper={isSuper}
                  disabled={actionsDisabled}
                  onDetail={(m, title) => setManifestModal({ manifest: m, title })}
                  onRestore={setRestoreTarget}
                  onDrill={() => undefined}
                />
              ) : (
                <p className="p-6 text-sm text-slate-500">Snapshot restic tidak tersedia{sources.restic.error ? ` (${sources.restic.error})` : ''}.</p>
              )
            )}
            {tab === 'offsite' && (
              sources.offsite.available ? (
                <SourceTable
                  empty="Belum ada arsip di Google Drive."
                  rows={sources.offsite.archives.map((o) => ({
                    key: o.name,
                    main: o.name,
                    sub: `${ARCHIVE_KIND_LABEL[o.kind ?? archiveKindOf(o.name)]} · ${sources.offsite.remote ?? 'Drive'}${o.sha256 ? ' · SHA256 ✓' : ''} · diunduh dulu saat diuji/dipulihkan`,
                    when: o.mtime,
                    size: o.bytes,
                    manifest: o.manifest ?? null,
                    restore: { type: 'offsite', name: o.name, label: `${o.name} (Drive)`, hasUsers: o.manifest ? (o.manifest.workspaces?.accounts_total ?? 0) > 0 : (o.kind ?? archiveKindOf(o.name)) === 'full', hasEnv: o.manifest ? Boolean(o.manifest.components?.env?.included) : true },
                    drill: o.name.endsWith('.gpg') ? o.name : null,
                  }))}
                  isSuper={isSuper}
                  disabled={actionsDisabled}
                  onDetail={(m, title) => setManifestModal({ manifest: m, title })}
                  onRestore={setRestoreTarget}
                  onDrill={(archive) => { setActionErr(null); setConfirmAction({ kind: 'drill', archive }) }}
                />
              ) : (
                <p className="p-6 text-sm text-slate-500">Daftar Drive tidak tersedia{sources.offsite.error ? ` (${sources.offsite.error})` : ''}.</p>
              )
            )}
            {tab === 'rollback' && (
              <SourceTable
                empty="Belum ada titik rollback (dibuat otomatis setiap kali restore dijalankan)."
                rows={sources.pre_restore.map((p) => ({
                  key: p.name,
                  main: p.name,
                  sub: `kondisi tepat sebelum restore${p.source ? ` dari ${p.source}` : ''}${p.scope ? ` (cakupan ${p.scope})` : ''}`,
                  when: p.created_at,
                  size: p.bytes,
                  manifest: null,
                  restore: { type: 'pre_restore', name: p.name, label: 'titik rollback', hasUsers: p.files.some((f) => f.path === 'users-before.tar.gz'), hasEnv: p.files.some((f) => f.path === 'env-before') },
                  drill: null,
                }))}
                isSuper={isSuper}
                disabled={actionsDisabled}
                onDetail={(m, title) => setManifestModal({ manifest: m, title })}
                onRestore={setRestoreTarget}
                onDrill={() => undefined}
              />
            )}
          </div>
          <p className="text-xs text-slate-500">
            Backup &amp; restore dieksekusi oleh agen di server (bukan oleh aplikasi web) dan setiap tindakan tercatat di Log Aktivitas Admin.
            Hanya administrator utama yang dapat memulai backup, uji pulih, dan restore.
          </p>
        </div>
      )}

      {manifestModal && <BackupDetailModal manifest={manifestModal.manifest} title={manifestModal.title} onClose={() => setManifestModal(null)} />}
      {eventModal && <EventDetailModal event={eventModal} archive={archiveOf(eventModal)} actions={eventActions} onClose={() => setEventModal(null)} />}
      {deleteTarget && (
        <DeleteModal
          event={deleteTarget.event}
          archive={deleteTarget.archive}
          agentAlive={agentAlive && !actionsDisabled}
          onClose={() => setDeleteTarget(null)}
          onDone={(msg) => { setDeleteTarget(null); setNotice(msg); invalidateOps() }}
        />
      )}
      {restoreTarget && (
        <RestoreModal
          source={restoreTarget}
          onClose={() => setRestoreTarget(null)}
          onStarted={() => { setRestoreTarget(null); invalidateOps() }}
        />
      )}
      {confirmAction?.kind === 'backup' && (
        <ConfirmModal
          title="Backup penuh sekarang?"
          confirmLabel="Mulai backup"
          busy={backupMut.isPending}
          error={actionErr}
          onConfirm={() => backupMut.mutate()}
          onClose={() => setConfirmAction(null)}
          body={
            <>
              <p>Agen host akan membuat <b>arsip penuh</b> (database, workspace semua pengguna, konfigurasi, log eksekusi), mengenkripsinya,
                mengunggah ke Google Drive dengan verifikasi md5, lalu <b>menghapus salinan besar di server</b> (yang besar hanya di Drive) — ditambah
                arsip inti kecil yang tetap di server dan snapshot restic ke Drive. Sama persis dengan backup Minggu, tanpa menunggu jadwal.</p>
              <p className="text-xs text-slate-500">Layanan tetap berjalan normal selama proses (prioritas CPU/I-O rendah). Lama proses bergantung ukuran data dan
                kecepatan unggah; kemajuan tampil di kartu permintaan.</p>
            </>
          }
        />
      )}
      {confirmAction?.kind === 'drill' && (
        <ConfirmModal
          title="Uji pulih (restore drill)?"
          confirmLabel="Mulai uji pulih"
          busy={drillMut.isPending}
          error={actionErr}
          onConfirm={() => drillMut.mutate(confirmAction.archive)}
          onClose={() => setConfirmAction(null)}
          body={
            <>
              <p>Arsip <span className="font-mono text-xs">{confirmAction.archive ?? 'terbaru'}</span>
                {confirmAction.archive && !sources.archives.some((a) => a.name === confirmAction.archive) ? ' (tidak ada di server — diunduh dulu dari Google Drive)' : ''} akan didekripsi dan dimuat ke Postgres <b>sementara</b> yang terpisah,
                lalu divalidasi jumlah tabel dan penggunanya. <b>Produksi tidak disentuh.</b></p>
              <p className="text-xs text-slate-500">Hasil tercatat sebagai bukti &quot;Restore drill&quot; dan dikirim ke email/Telegram admin.</p>
            </>
          }
        />
      )}
    </>
  )
}

// ---------------------------------------------------------------- tabel sumber
type SourceRow = {
  key: string
  main: string
  sub: string
  when: string | null
  size: number | null
  manifest: BackupManifest | null
  restore: { type: RestoreSourceType; name: string; label: string; hasUsers: boolean; hasEnv: boolean }
  drill: string | null
  deletable?: ArchiveRef | null
}
function SourceTable({
  rows, empty, isSuper, disabled, onDetail, onRestore, onDrill, onDelete,
}: {
  rows: SourceRow[]
  empty: string
  isSuper: boolean
  disabled: boolean
  onDetail: (m: BackupManifest, title: string) => void
  onRestore: (t: SourceRow['restore']) => void
  onDrill: (archive: string | null) => void
  onDelete?: (ref: ArchiveRef) => void
}) {
  if (rows.length === 0) return <p className="p-6 text-sm text-slate-500">{empty}</p>
  return (
    <div className="max-h-72 overflow-auto">
      <table className="min-w-full divide-y divide-slate-100 text-sm">
        <tbody className="divide-y divide-slate-100">
          {rows.map((r) => (
            <tr key={r.key} className="hover:bg-slate-50">
              <td className="px-4 py-2">
                <p className="font-mono text-xs text-slate-800">{r.main}</p>
                <p className="text-[11px] text-slate-500">{r.sub}</p>
              </td>
              <td className="whitespace-nowrap px-3 py-2 text-xs text-slate-500">{r.when ? formatDateTime(r.when) : '—'}</td>
              <td className="whitespace-nowrap px-3 py-2 text-right text-xs text-slate-600">{fmtBytes(r.size)}</td>
              <td className="whitespace-nowrap px-3 py-2 text-right">
                <div className="flex items-center justify-end gap-1">
                  {r.manifest && (
                    <button type="button" className="btn-ghost !px-2 !py-1 text-xs" onClick={() => onDetail(r.manifest as BackupManifest, `Detail Backup — ${r.main}`)}>
                      Rincian
                    </button>
                  )}
                  {isSuper && r.drill && (
                    <button type="button" className="btn-ghost !px-2 !py-1 text-xs" disabled={disabled} onClick={() => onDrill(r.drill)} title="Uji pulih ke Postgres sementara (produksi tidak disentuh)">
                      <IconPlay className="h-3 w-3" /> Uji pulih
                    </button>
                  )}
                  {isSuper && (
                    <button type="button" className="btn-ghost !px-2 !py-1 text-xs !text-rose-700" disabled={disabled} onClick={() => onRestore(r.restore)} title="Pulihkan produksi dari sumber ini">
                      Pulihkan…
                    </button>
                  )}
                  {isSuper && onDelete && r.deletable && (
                    <button type="button" className="btn-ghost !p-1.5 !text-rose-600" disabled={disabled} onClick={() => onDelete(r.deletable as ArchiveRef)} title="Hapus berkas arsip ini dari server" aria-label={`Hapus arsip ${r.main}`}>
                      <IconTrash className="h-4 w-4" />
                    </button>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
