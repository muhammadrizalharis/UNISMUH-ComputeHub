"""Render laporan user -> PDF (fpdf2, pure-python, tanpa dependency sistem)."""

from __future__ import annotations

import datetime as dt

from fpdf import FPDF

# Karakter non-latin-1 -> pengganti aman (core font Helvetica = latin-1).
_REPL = {
    "—": "-",
    "–": "-",
    "✓": "OK",
    "✗": "X",
    "…": "...",
    "≈": "~",
    "→": "->",
    "•": "-",
}


def _san(s) -> str:
    s = str(s if s is not None else "-")
    for k, v in _REPL.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


def _gb(mb: float) -> str:
    return f"{(mb or 0) / 1024:.1f} GB"


def _mib(mb: float) -> str:
    return f"{(mb or 0):,.0f} MiB"


class _PDF(FPDF):
    title_text = "LAPORAN PENGGUNAAN RESOURCE"

    def header(self) -> None:
        self.set_fill_color(31, 102, 242)
        self.rect(0, 0, self.w, 18, "F")
        self.set_xy(12, 5)
        self.set_text_color(255, 255, 255)
        self.set_font("Helvetica", "B", 13)
        self.cell(0, 8, _san(self.title_text))
        self.set_text_color(20, 20, 20)
        self.set_y(24)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 6, _san(f"UNISMUH ComputeHub  -  halaman {self.page_no()}"), align="C")


def _h2(pdf: _PDF, text: str) -> None:
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(17, 24, 39)
    pdf.cell(0, 8, _san(text), new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(225, 228, 233)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(1.5)
    pdf.set_text_color(30, 30, 30)


def _h3(pdf: _PDF, text: str) -> None:
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(55, 65, 81)
    pdf.cell(0, 6, _san(text), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(30, 30, 30)


def _kv(pdf: _PDF, label: str, value: str) -> None:
    pdf.set_font("Helvetica", "", 9.5)
    pdf.set_text_color(110, 116, 128)
    pdf.cell(48, 6, _san(label))
    pdf.set_text_color(30, 30, 30)
    pdf.set_font("Helvetica", "B", 9.5)
    pdf.multi_cell(0, 6, _san(value), new_x="LMARGIN", new_y="NEXT")


def _para(pdf: _PDF, text: str, size: float = 9.5) -> None:
    pdf.set_font("Helvetica", "", size)
    pdf.set_text_color(40, 40, 40)
    pdf.multi_cell(0, 5, _san(text), new_x="LMARGIN", new_y="NEXT")


def _bullets(pdf: _PDF, items: list[str]) -> None:
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(40, 40, 40)
    if not items:
        pdf.multi_cell(0, 5, _san("- (tidak ada)"), new_x="LMARGIN", new_y="NEXT")
        return
    for it in items:
        pdf.multi_cell(0, 5, _san(f"-  {it}"), new_x="LMARGIN", new_y="NEXT")


def _table(pdf: _PDF, headers: list[str], widths: list[float], rows: list[list[str]]) -> None:
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_fill_color(243, 244, 246)
    pdf.set_text_color(90, 96, 108)
    for h, w in zip(headers, widths):
        pdf.cell(w, 7, _san(h), border=0, fill=True)
    pdf.ln(7)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(30, 30, 30)
    for r in rows:
        for v, w in zip(r, widths):
            pdf.cell(w, 6, _san(v), border="B")
        pdf.ln(6)


def build_user_pdf(report: dict, breach: dict | None = None) -> bytes:
    s = report["system"]
    st = report["status"]
    p = report["profile"]
    pdf = _PDF(orientation="P", unit="mm", format="A4")
    pdf.title_text = f"LAPORAN PENGGUNAAN - {report['username'].upper()}"
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.add_page()

    # Judul + waktu
    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(0, 8, _san(f"User: {report['username']}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 5, _san(f"Server {s['hostname']}  -  dibuat {report['generated_at']}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(30, 30, 30)
    pdf.ln(1)

    # Kotak peringatan (kalau ada pelanggaran)
    if breach:
        pdf.set_fill_color(254, 242, 242)
        pdf.set_draw_color(220, 38, 38)
        y0 = pdf.get_y()
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(185, 28, 28)
        pdf.multi_cell(0, 6, _san(f"PERINGATAN: {breach.get('message', '')}"), border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(30, 30, 30)
        pdf.ln(1)
        _ = y0

    # 1. Info sistem
    _h2(pdf, "1. Informasi Sistem")
    _kv(pdf, "Hostname", s["hostname"])
    _kv(pdf, "OS", s["os"])
    _kv(pdf, "CPU", f"{s['cpu_cores']} core")
    _kv(pdf, "RAM", _gb(s["memory_total_mb"]))
    _kv(pdf, "GPU", f"{len(s['gpus'])} x {s['gpus'][0]['name'] if s['gpus'] else '-'}")
    _kv(pdf, "Driver / CUDA", f"{s['driver_version']} / CUDA {s['cuda_version']}")
    _kv(pdf, "Disk (/)", f"{s['disk_used_gb']:.0f} / {s['disk_total_gb']:.0f} GB ({s['disk_percent']:.0f}%)")

    # 2. Profil
    _h2(pdf, "2. Profil User")
    _kv(pdf, "Username", p["username"])
    _kv(pdf, "UID", str(p["uid"]))
    _kv(pdf, "Home", p["home"])
    _kv(pdf, "Shell", p["shell"])
    _kv(pdf, "Proses aktif", str(p["processes_count"]))

    # 3. Status
    _h2(pdf, f"3. Status Resource Saat Ini ({report['generated_at']})")
    _h3(pdf, "3.1 GPU")
    if st["gpu"]:
        _table(
            pdf,
            ["GPU", "Model", "VRAM (user/total)", "Util", "Suhu"],
            [16, 60, 50, 20, 20],
            [
                [f"GPU {g['index']}", g["name"], f"{_mib(g['user_vram_mb'])} / {_mib(g['total_vram_mb'])}", f"{g['util_percent']:.0f}%", f"{g['temperature_c']:.0f}C"]
                for g in st["gpu"]
            ],
        )
    else:
        _para(pdf, "Tidak memakai GPU.")
    pdf.ln(1)
    _h3(pdf, "3.2 RAM")
    _kv(pdf, "RAM user", f"{_gb(st['ram']['user_rss_mb'])} ({st['ram']['percent_of_total']:.1f}%)")
    _kv(pdf, "Swap", _gb(st["ram"]["swap_used_mb"]))
    _h3(pdf, "3.3 CPU")
    _kv(pdf, "CPU user", f"{st['cpu']['user_cpu_percent']:.0f}% (~{st['cpu']['cores_eq']:.0f} core dari {st['cpu']['system_cores']})")
    _kv(pdf, "CPU time", f"{st['cpu']['cpu_time_seconds'] / 60:.0f} menit")
    _kv(pdf, "Load average", " / ".join(str(x) for x in st["cpu"]["load_avg"]))
    _h3(pdf, "3.4 Disk")
    _kv(pdf, "Filesystem /", f"{st['disk']['fs_used_gb']:.0f} / {st['disk']['fs_total_gb']:.0f} GB ({st['disk']['fs_percent']:.0f}%)")

    # 4. Workload
    _h2(pdf, "4. Analisis Pekerjaan (Workload)")
    _kv(pdf, "Jenis utama", report["workload"]["primary"])
    if report["workload"].get("hint"):
        _para(pdf, report["workload"]["hint"])
    _kv(pdf, "Sinyal", ", ".join(report["workload"]["signals"]) or "-")

    # 5. Proses utama
    _h2(pdf, "5. Proses yang Sedang Berjalan")
    main = report["processes"]["main"]
    if main:
        _kv(pdf, "PID / status", f"{main['pid']} / {main['status']}")
        _kv(pdf, "Mulai", main["started"])
        _kv(pdf, "CPU", f"{main['cpu_percent']:.0f}% (~{main['cpu_cores_eq']:.0f} core)")
        _kv(pdf, "RAM / VRAM", f"{_gb(main['memory_mb'])} / {_mib(main['gpu_vram_mb']) if main['gpu_vram_mb'] else '-'}")
        _para(pdf, f"Command: {main['command']}", size=8.5)
    else:
        _para(pdf, "Tidak ada proses aktif.")

    # 9. Temuan
    _h2(pdf, "9. Temuan")
    _bullets(pdf, [f"[{f['level'].upper()}] {f['text']}" for f in report["findings"]])

    # 10. Rekomendasi
    _h2(pdf, "10. Rekomendasi")
    rec = report["recommendations"]
    _h3(pdf, "Prioritas Tinggi")
    _bullets(pdf, rec["high"])
    _h3(pdf, "Prioritas Sedang")
    _bullets(pdf, rec["medium"])
    _h3(pdf, "Prioritas Rendah")
    _bullets(pdf, rec["low"])

    # 12. Perbandingan
    _h2(pdf, "12. Perbandingan dengan User Lain")
    _table(
        pdf,
        ["User OS", "VRAM", "CPU", "RAM", "Aktivitas"],
        [34, 28, 30, 26, 52],
        [
            [
                u["username"],
                _mib(u["vram_mb"]) if u["vram_mb"] else "-",
                f"{u['cpu_percent']:.0f}% (~{u['cpu_cores_eq']:.0f})",
                _gb(u["memory_mb"]),
                u["activity"],
            ]
            for u in report["comparison"][:10]
        ],
    )

    # 13. Kesimpulan
    _h2(pdf, "13. Kesimpulan")
    _para(pdf, report["conclusion"])

    out = pdf.output()
    return bytes(out)


def pdf_filename(username: str) -> str:
    safe = "".join(c for c in username if c.isalnum() or c in "-_") or "user"
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"peringatan_{safe}_{stamp}.pdf"
