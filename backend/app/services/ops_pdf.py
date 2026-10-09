"""PDF satu catatan bukti operasional (backup / restore / uji pulih / offsite / pemantau)
untuk lampiran audit — isi sama dengan "Detail" di web: ringkasan, data tercatat berlabel,
dan Detail Backup (manifest) bila catatan itu membawa manifest. fpdf2, core font Helvetica.
"""

from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.services.pdf import _PDF, _h2, _h3, _kv, _para, _pot, _san, _table

KIND_LABEL = {
    "backup": "Backup",
    "restore": "Restore",
    "restore_drill": "Restore drill (uji pulih)",
    "offsite": "Offsite (Google Drive)",
    "watchdog": "Pemantau",
}
STATUS_LABEL = {"ok": "Berhasil", "warn": "Peringatan", "fail": "Gagal"}
_STATUS_RGB = {"ok": (236, 253, 245, 4, 120, 87), "warn": (255, 251, 235, 180, 83, 9), "fail": (254, 242, 242, 185, 28, 28)}
# Label manusiawi kunci `data` (selaras DATA_LABEL di frontend BackupRestorePanel.tsx).
DATA_LABEL = {
    "archive": "Arsip", "archive_size": "Ukuran arsip", "archive_bytes": "Ukuran arsip", "archive_form": "Bentuk arsip",
    "archive_sha256": "SHA256 arsip", "archives_on_server": "Arsip penuh di server", "db_dump": "Dump database",
    "offsite_tar": "Arsip penuh -> Drive", "tar_local_deleted": "Salinan server dihapus", "core_archive": "Arsip inti harian",
    "core_bytes": "Ukuran arsip inti", "core_sha256": "SHA256 arsip inti", "core_offsite": "Arsip inti -> Drive",
    "core_archives_on_server": "Arsip inti di server", "server_backup_size": "Ukuran backup di server",
    "restic": "Snapshot restic", "restic_repo": "Repo restic", "restic_check": "Pemeriksaan integritas restic",
    "restic_offsite": "Restic off-site (Drive)", "restic_snapshot": "ID snapshot restic", "disk_free": "Disk server bebas",
    "disk_free_after_gib": "Disk bebas sesudahnya (GiB)", "restic_repo_before_gib": "Repo restic sebelum (GiB)",
    "restic_repo_after_gib": "Repo restic sesudah (GiB)", "snapshots": "Jumlah snapshot", "backfill": "Rekonstruksi riwayat",
    "trigger": "Dipicu oleh", "requested_by": "Diminta oleh", "request_id": "ID permintaan", "remote": "Remote Google Drive",
    "age_hours": "Umur berkas terbaru (jam)", "threshold_hours": "Ambang peringatan (jam)", "backup_result": "Hasil backup",
    "pid_before": "PID backend sebelum", "pid_after": "PID backend sesudah", "tables": "Tabel dipulihkan",
    "users": "Pengguna dipulihkan", "jobs": "Job dipulihkan", "source": "Sumber pemulihan", "scope": "Cakupan",
    "snapshot_dir": "Titik rollback", "bytes_freed": "Ruang dibebaskan", "removed": "Berkas dihapus",
    "health": "Health setelah pulih", "sessions_stopped": "Sesi dihentikan", "line": "Baris skrip",
}


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(getattr(settings, "REPORT_TIMEZONE", "Asia/Makassar") or "Asia/Makassar")
    except Exception:  # noqa: BLE001
        return ZoneInfo("Asia/Makassar")


def _waktu(value) -> str:
    if value in (None, ""):
        return "-"
    if isinstance(value, str):
        try:
            value = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.timezone.utc)
        return value.astimezone(_tz()).strftime("%d %b %Y %H:%M:%S WITA")
    return str(value)


def _bytes(n) -> str:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return "-"


def _dur(seconds) -> str:
    if seconds is None:
        return "-"
    s = int(seconds)
    if s < 90:
        return f"{s} detik"
    if s < 3600:
        return f"{round(s / 60)} menit"
    return f"{s // 3600} jam {round((s % 3600) / 60)} menit"


def _int(n) -> str:
    try:
        return f"{int(n):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "-"


def _nilai(key: str, v) -> str:
    if v is None or v == "":
        return "-"
    if isinstance(v, bool):
        return "ya" if v else "tidak"
    if isinstance(v, (int, float)):
        return _bytes(v) if re.search(r"bytes|freed", key) else _int(v) if float(v).is_integer() else f"{v:g}"
    if isinstance(v, list):
        return ", ".join(str(x.get("path", x)) if isinstance(x, dict) else str(x) for x in v) or "-"
    if isinstance(v, dict):
        return ", ".join(f"{k}={_nilai(k, val)}" for k, val in v.items()) or "-"
    return str(v)


def _status_box(pdf: _PDF, status: str, title: str) -> None:
    bg_r, bg_g, bg_b, fg_r, fg_g, fg_b = _STATUS_RGB.get(status, _STATUS_RGB["warn"])
    pdf.set_fill_color(bg_r, bg_g, bg_b)
    pdf.set_draw_color(fg_r, fg_g, fg_b)
    pdf.set_text_color(fg_r, fg_g, fg_b)
    pdf.set_font("Helvetica", "B", 10.5)
    pdf.multi_cell(0, 7, _san(f"{STATUS_LABEL.get(status, status).upper()}  -  {title}"), border=1, fill=True,
                   new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(30, 30, 30)
    pdf.ln(2)


def _stat_row(pdf: _PDF, items: list[tuple[str, str, str]]) -> None:
    w = (pdf.w - pdf.l_margin - pdf.r_margin - 4 * (len(items) - 1)) / max(1, len(items))
    x0, y0 = pdf.get_x(), pdf.get_y()
    for i, (label, value, sub) in enumerate(items):
        x = x0 + i * (w + 4)
        pdf.set_fill_color(248, 250, 252)
        pdf.set_draw_color(226, 232, 240)
        pdf.rect(x, y0, w, 17, "DF")
        pdf.set_xy(x + 2, y0 + 1.5)
        pdf.set_font("Helvetica", "B", 7)
        pdf.set_text_color(100, 116, 139)
        pdf.cell(w - 4, 4, _pot(label.upper(), w - 4))
        pdf.set_xy(x + 2, y0 + 6)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(15, 23, 42)
        pdf.cell(w - 4, 5.5, _pot(value, (w - 4) * 0.85))
        pdf.set_xy(x + 2, y0 + 11.5)
        pdf.set_font("Helvetica", "", 7.5)
        pdf.set_text_color(100, 116, 139)
        pdf.cell(w - 4, 4, _pot(sub, w - 4))
    pdf.set_xy(x0, y0 + 20)
    pdf.set_text_color(30, 30, 30)


def _manifest_sections(pdf: _PDF, m: dict, nomor: int) -> int:
    db = m.get("database") or {}
    ws = m.get("workspaces") or {}
    comp = m.get("components") or {}
    arch = m.get("archive") or {}
    offsite = m.get("offsite") or {}
    restic = m.get("restic") or {}
    env = m.get("environment") or {}
    jenis = "Arsip inti harian (tanpa workspace)" if m.get("archive_kind") == "core" else "Arsip penuh"
    _h2(pdf, f"{nomor}. Detail Backup - {jenis}")
    _stat_row(pdf, [
        ("Total ukuran", _bytes(arch.get("bytes")), str(arch.get("form") or "")),
        ("Durasi proses", _dur(m.get("duration_seconds")), ""),
        ("Salinan off-site", "Drive" if offsite.get("tar") == "ok" else str(offsite.get("tar") or "-"), str(offsite.get("remote") or "")),
    ])
    _h3(pdf, "Basis data PostgreSQL")
    _kv(pdf, "Nama database", str(db.get("name") or "-"))
    _kv(pdf, "Ukuran file dump", _bytes(db.get("dump_bytes")))
    _kv(pdf, "Jumlah tabel", _int(db.get("tables")))
    _kv(pdf, "Perkiraan baris", _int(db.get("estimated_rows")))
    _kv(pdf, "Ukuran database asli", _bytes(db.get("size_bytes")))
    _kv(pdf, "Roles/globals", "ikut dicadangkan" if db.get("globals_included") else "tidak disertakan")
    terbesar = db.get("largest_tables") or []
    if terbesar:
        _para(pdf, "Tabel terbesar: " + ", ".join(f"{t.get('table')} ({_int(t.get('rows'))})" for t in terbesar[:6]), size=8.5)
    if db.get("dump_warnings"):
        _para(pdf, f"Peringatan pg_dump: {db['dump_warnings']}", size=8)

    akun = ws.get("accounts") or []
    _h3(pdf, f"Workspace pengguna - {_int(ws.get('accounts_total', 0))} akun, {_int(ws.get('files_total', 0))} berkas, {_bytes(ws.get('bytes_total', 0))}")
    if akun:
        rows = [[_pot(f"{a.get('username') or ('akun #' + str(a.get('dir')))}{(' (' + a['role'] + ')') if a.get('role') else ''}", 95),
                 _int(a.get("files")), _bytes(a.get("bytes"))] for a in akun]
        _table(pdf, ["Akun", "Berkas", "Ukuran"], [100, 40, 46], rows)
    else:
        _para(pdf, ws.get("note") or "Tidak ada workspace di arsip ini.", size=8.5)
    pdf.ln(1)

    _h3(pdf, "Komponen lain")
    _kv(pdf, "Salinan konfigurasi (.env)", "disertakan (terenkripsi)" if (comp.get("env") or {}).get("included") else "tidak disertakan")
    _kv(pdf, "Verifikasi integritas", f"SHA256 {arch['sha256']}" if arch.get("sha256") else "tidak ada")
    _kv(pdf, "Nama arsip off-site", str(offsite.get("archive_name") or (arch.get("name") if offsite.get("tar") == "ok" else "-") or "-"))
    _kv(pdf, "Log eksekusi job", f"{_int((comp.get('joblogs') or {}).get('files'))} berkas" if (comp.get("joblogs") or {}).get("included") else "tidak ada")
    _kv(pdf, "Agen pemantau host", f"{_int((comp.get('agent') or {}).get('files'))} berkas" if (comp.get("agent") or {}).get("included") else "tidak ada")
    _kv(pdf, "Snapshot restic", f"{restic.get('snapshot')} ({restic.get('status')})" if restic.get("snapshot") else str(restic.get("status") or "-"))
    _kv(pdf, "Salinan restic off-site", str(restic.get("offsite") or "-"))

    _h3(pdf, "Waktu & lingkungan")
    _kv(pdf, "Mulai", _waktu(m.get("started_at")))
    _kv(pdf, "Selesai", _waktu(m.get("finished_at")))
    _kv(pdf, "Server", str(env.get("hostname") or "-"))
    _kv(pdf, "Mode", str(env.get("mode") or "host"))
    _kv(pdf, "Versi pg_dump", str(db.get("pg_dump_version") or "-"))
    _kv(pdf, "Dipicu oleh", f"web ({m.get('requested_by') or 'admin'})" if m.get("trigger") == "web" else "jadwal systemd")

    berkas = list(m.get("files") or [])
    if arch.get("name"):
        berkas.append({"path": arch["name"], "bytes": arch.get("bytes"), "mtime": None, "catatan": "arsip final"})
    if berkas:
        _h3(pdf, "Berkas dalam backup")
        rows = [[_pot(f.get("path", "-"), 85), _bytes(f.get("bytes")) + (f" / {_int(f['files'])} berkas" if f.get("files") is not None else ""),
                 f.get("catatan") or (_waktu(f.get("mtime")) if f.get("mtime") else "")] for f in berkas]
        _table(pdf, ["Berkas", "Ukuran", "Keterangan"], [88, 44, 54], rows)
    return nomor + 1


def _lokasi(event: dict) -> list[tuple[str, bool, str]]:
    """(tempat, tersimpan?, catatan) — selaras storageOf() di frontend."""
    kind = str(event.get("kind") or "")
    d = event.get("data") or {}
    s = lambda k: str(d.get(k) or "") if isinstance(d.get(k), str) else ""  # noqa: E731
    marks: dict[str, tuple[bool, list[str]]] = {}

    def add(place: str, ok: bool, note: str) -> None:
        cur = marks.get(place)
        marks[place] = (ok, [note]) if cur is None else (cur[0] and ok, cur[1] + [note])

    if kind == "offsite":
        add("Drive", event.get("status") == "ok", f"{s('remote') or 'Google Drive'} {'segar' if event.get('status') == 'ok' else 'tidak segar / tidak terbaca'}")
    elif kind == "backup":
        if d.get("backfill"):
            add("Server", True, "rekonstruksi dari repo restic di server (saat itu)")
        else:
            if s("core_archive"):
                add("Server", True, f"arsip inti {s('core_archive')}")
                if s("core_offsite") not in ("", "dilewati"):
                    add("Drive", s("core_offsite") == "ok", f"arsip inti -> Drive {s('core_offsite')}")
            if s("archive"):
                if d.get("tar_local_deleted"):
                    add("Server", False, "arsip penuh dihapus dari server setelah terverifikasi di Drive")
                else:
                    add("Server", True, f"arsip penuh {s('archive')}")
                if s("offsite_tar") not in ("", "dilewati"):
                    add("Drive", s("offsite_tar") == "ok", f"arsip penuh -> Drive {s('offsite_tar')}")
            if s("restic") == "ok":
                if s("restic_repo").startswith("rclone:"):
                    add("Drive", True, "snapshot restic ditulis langsung ke Drive")
                else:
                    add("Server", True, "snapshot restic (repo lokal)")
                    if s("restic_offsite") not in ("", "dilewati"):
                        add("Drive", s("restic_offsite") == "ok", f"restic -> Drive {s('restic_offsite')}")
            elif s("restic") == "gagal":
                add("Drive" if s("restic_repo").startswith("rclone:") else "Server", False, "snapshot restic gagal")
    urut = sorted(marks.items(), key=lambda kv: 0 if kv[0] == "Server" else 1)
    return [(place, ok, "; ".join(notes)) for place, (ok, notes) in urut]


def build_ops_event_pdf(event: dict, dibuat_oleh: str = "", arsip_di_server: bool | None = None) -> bytes:
    kind = str(event.get("kind") or "")
    status = str(event.get("status") or "warn")
    data = dict(event.get("data") or {})
    manifest = data.pop("manifest", None)
    if not isinstance(manifest, dict) or not (isinstance(manifest.get("database"), dict) or isinstance(manifest.get("archive"), dict)):
        manifest = None

    pdf = _PDF(orientation="P", unit="mm", format="A4")
    pdf.title_text = "LAPORAN CADANGAN & PEMULIHAN"
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(0, 8, _san(f"{KIND_LABEL.get(kind, kind)} - catatan #{event.get('id')}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 5, _san(f"Waktu kejadian {_waktu(event.get('created_at'))}  -  dicatat oleh {event.get('source') or 'sumber tidak dicatat'}"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, _san(f"Dokumen dibuat {_waktu(dt.datetime.now(dt.timezone.utc))}{(' oleh ' + dibuat_oleh) if dibuat_oleh else ''} dari bukti operasional di database UNISMUH ComputeHub"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(30, 30, 30)
    pdf.ln(2)
    _status_box(pdf, status, str(event.get("title") or "-"))

    nomor = 1
    _h2(pdf, f"{nomor}. Ringkasan")
    _kv(pdf, "Jenis", KIND_LABEL.get(kind, kind))
    _kv(pdf, "Status", STATUS_LABEL.get(status, status))
    _kv(pdf, "Waktu", _waktu(event.get("created_at")))
    _kv(pdf, "Durasi", _dur(event.get("duration_seconds")))
    _kv(pdf, "Dicatat oleh", str(event.get("source") or "-"))
    if arsip_di_server is not None:
        _kv(pdf, "Arsip di server", "ada" if arsip_di_server else "tidak ada / sudah dirotasi (salinan di Google Drive)")
    lokasi = _lokasi(event)
    if lokasi:
        _kv(pdf, "Lokasi penyimpanan", "   ".join(f"[{'OK' if ok else 'X'}] {place}" for place, ok, _ in lokasi))
        for place, ok, note in lokasi:
            _para(pdf, f"- {place}: {'tersimpan' if ok else 'tidak tersimpan'} - {note}", size=8.5)
    if data.get("backfill"):
        _kv(pdf, "Catatan", "rekonstruksi riwayat dari arsip/snapshot yang ada, bukan pencatatan langsung")
    if event.get("detail"):
        _h3(pdf, "Keterangan")
        _para(pdf, str(event["detail"]), size=9)
    nomor += 1

    rows = [(DATA_LABEL.get(k, k), _nilai(k, v)) for k, v in data.items()]
    if rows:
        _h2(pdf, f"{nomor}. Data tercatat")
        for label, value in rows:
            _kv(pdf, label, value)
        nomor += 1

    if manifest:
        nomor = _manifest_sections(pdf, manifest, nomor)

    _h2(pdf, f"{nomor}. Keterangan dokumen")
    _para(pdf, "Dokumen ini dihasilkan otomatis dari catatan bukti operasional (tabel ops_events) yang ditulis skrip "
               "backup/restore/pemantau di server dan tersimpan permanen di database, bukan hanya di email/Telegram. "
               "Kebijakan penyimpanan: arsip inti harian (tanpa workspace) di server 30 hari + Google Drive 90 hari; arsip penuh "
               "(dengan workspace) hanya di Google Drive; snapshot restic harian di Google Drive. SHA256 dihitung di server "
               "setelah enkripsi dan dicocokkan ulang sebelum pemulihan.", size=8.5)
    return bytes(pdf.output())


def ops_event_pdf_filename(event: dict) -> str:
    waktu = event.get("created_at")
    if isinstance(waktu, str):
        try:
            waktu = dt.datetime.fromisoformat(waktu.replace("Z", "+00:00"))
        except ValueError:
            waktu = None
    stamp = waktu.astimezone(_tz()).strftime("%Y%m%d_%H%M") if isinstance(waktu, dt.datetime) else "tanpa_waktu"
    kind = re.sub(r"[^a-z0-9_]", "", str(event.get("kind") or "catatan").lower()) or "catatan"
    return f"cadangan_{kind}_{event.get('id')}_{stamp}.pdf"
