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


def _pot(s, lebar_mm: float) -> str:
    """Potong teks agar muat satu sel: `cell()` fpdf tidak membungkus teks sendiri."""
    t = _san(s)
    maks = max(3, int(lebar_mm / 1.75))  # ~1,75 mm per karakter pada 8,5 pt
    return t if len(t) <= maks else t[: maks - 1] + "."


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
        _kv(pdf, "PID / status", f"{main['pid']} / {main.get('status', 'aktif')}")
        _kv(pdf, "Mulai", main["started"])
        _kv(pdf, "CPU", f"{main['cpu_percent']:.0f}% (~{main['cpu_cores_eq']:.0f} core)")
        _kv(pdf, "RAM / VRAM", f"{_gb(main['memory_mb'])} / {_mib(main['gpu_vram_mb']) if main['gpu_vram_mb'] else '-'}")
        _para(pdf, f"Command: {main['command']}", size=8.5)
    else:
        _para(pdf, "Tidak ada proses aktif.")

    # 6. Pihak terhubung ke layanan LLM bersama (jembatan atribusi Ollama dsb)
    llm = report.get("llm_connections") or {}
    if llm.get("total"):
        port = ", ".join(str(p) for p in llm.get("ports", []))
        _h2(pdf, "6. Pihak Terhubung ke Layanan LLM Bersama")
        _para(
            pdf,
            f"Snapshot socket kernel saat laporan dibuat (port {port}). Berguna untuk "
            "menelusuri siapa yang memakai layanan bersama, karena bebannya tercatat "
            "atas nama akun layanan, bukan pemakainya.",
            size=9,
        )
        if llm.get("klien"):
            _h3(pdf, "6.1 Pemakai (pemilik socket klien)")
            _table(
                pdf,
                ["User", "UID", "Koneksi"],
                [60, 30, 30],
                [[k["user"], str(k["uid"]), str(k["koneksi"])] for k in llm["klien"]],
            )
        if llm.get("server"):
            _h3(pdf, "6.2 Asal koneksi masuk")
            _table(
                pdf,
                ["Asal (host / container)", "Koneksi"],
                [110, 30],
                [[s["asal"], str(s["koneksi"])] for s in llm["server"]],
            )

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

    _riwayat_user(pdf, report)

    out = pdf.output()
    return bytes(out)


def _riwayat_user(pdf: _PDF, rep: dict) -> None:
    """Bagian 14-16: riwayat dari arsip -- tak terlihat pada potret sesaat."""
    if not any(rep.get(k) for k in ("harian", "jam", "llm_harian")):
        return
    hari = int(rep.get("days") or 0)

    _h2(pdf, f"14. Riwayat Pemakaian Harian ({hari} hari terakhir)")
    w = [26, 26, 26, 28, 26, 20]
    _table(
        pdf,
        ["Tanggal", "CPU rata2", "CPU puncak", "RAM puncak", "VRAM puncak", "Menit"],
        w,
        [
            [
                r["tanggal"],
                f"{r['cpu_cores_avg']:.2f} core",
                f"{r['cpu_max_percent']:.0f}%",
                _gb(r["ram_max_mb"]),
                _mib(r["vram_max_mb"]) if r["vram_max_mb"] else "-",
                f"{r['menit_aktif']:.0f}",
            ]
            for r in rep.get("harian", [])
        ]
        or [["-", "-", "-", "-", "-", "-"]],
    )

    jam = rep.get("jam") or []
    if jam:
        _h2(pdf, "15. Rincian Per Jam (waktu server)")
        w = [24, 26, 24, 26, 26, 18, 20]
        _table(
            pdf,
            ["Tanggal", "Jam", "CPU rata2", "RAM puncak", "VRAM puncak", "Menit", "Aktivitas"],
            w,
            [
                [
                    r["tanggal"],
                    r["rentang"],
                    f"{r['cpu_cores_avg']:.2f} core",
                    _gb(r["ram_max_mb"]),
                    _mib(r["vram_max_mb"]) if r["vram_max_mb"] else "-",
                    f"{r['menit_aktif']:.0f}",
                    _pot(r["aktivitas"], 20),
                ]
                for r in jam[:120]
            ],
        )

    _h2(pdf, "16. Pemakaian Layanan LLM Bersama")
    llm = rep.get("llm_harian") or []
    if llm:
        _para(
            pdf,
            '"Waktu aktif" = lama socket benar-benar mengalirkan data (hasil ukur). '
            '"Perkiraan VRAM" = beban layanan dibagi menurut waktu aktif itu; ESTIMASI, '
            "karena layanan LLM satu proses dan memorinya tak bisa dipecah per pemakai.",
            size=8.5,
        )
        w = [28, 24, 30, 34, 36]
        _table(
            pdf,
            ["Tanggal", "Koneksi", "Waktu aktif", "Beban VRAM layanan", "Perkiraan VRAM"],
            w,
            [
                [
                    r["tanggal"],
                    str(r["koneksi_max"]),
                    f"{r['detik_aktif'] / 60:.1f} menit",
                    _mib(r["layanan_vram_max_mb"]) if r["layanan_vram_max_mb"] else "-",
                    _mib(r["est_vram_max_mb"]) if r["est_vram_max_mb"] else "-",
                ]
                for r in llm
            ],
        )
    else:
        _para(pdf, "Tidak ada jejak pemakaian layanan LLM pada rentang ini.")


def build_full_pdf(rep: dict, riwayat: dict | None = None) -> bytes:
    """Laporan SERVER (semua user) -> PDF, dari hasil `report.build_report`.

    `riwayat` opsional: rekap harian + rincian jam + disk, untuk bagian 7-10.
    """
    s = rep["system"]
    pdf = _PDF(orientation="P", unit="mm", format="A4")
    pdf.title_text = "LAPORAN PENGGUNAAN RESOURCE SERVER"
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(0, 8, _san(f"Server {s['hostname']}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(120, 120, 120)
    dibuat = dt.datetime.now().astimezone().strftime("%d %b %Y %H:%M:%S %Z")
    pdf.cell(0, 5, _san(f"dibuat {dibuat}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(30, 30, 30)
    pdf.ln(1)

    _h2(pdf, "1. Informasi Sistem")
    _kv(pdf, "Hostname", s["hostname"])
    _kv(pdf, "OS", s["os"])
    beban = " / ".join(str(x) for x in s["load_avg"])
    _kv(pdf, "CPU", f"{s['cpu_cores']} core - util {s['cpu_percent']:.0f}% - load {beban}")
    _kv(pdf, "RAM", f"{_gb(s['memory_used_mb'])} / {_gb(s['memory_total_mb'])}")
    _kv(
        pdf,
        "Disk (/)",
        f"{s['disk_used_gb']:.0f} / {s['disk_total_gb']:.0f} GB ({s['disk_percent']:.0f}%)",
    )
    _kv(pdf, "GPU", f"{len(s['gpus'])} x {s['gpus'][0]['name'] if s['gpus'] else '-'}")
    _kv(pdf, "Driver / CUDA", f"{s['driver_version']} / CUDA {s['cuda_version']}")
    _kv(pdf, "Uptime", f"{s['uptime_seconds'] / 3600:.0f} jam")
    _kv(pdf, "Akun ComputeHub", str(s.get("platform_users", "-")))

    _h2(pdf, "2. Penggunaan GPU Langsung")
    w = [12, 16, 28, 34, 50, 30]
    _table(
        pdf,
        ["GPU", "PID", "User OS", "Workload", "Program", "VRAM"],
        w,
        [
            [
                str(g["gpu_index"]),
                str(g["pid"]),
                _pot(g["username"], w[2]),
                _pot(g["workload"], w[3]),
                _pot(g["command"], w[4]),
                _mib(g["vram_mb"]),
            ]
            for g in rep["gpu_processes"]
        ]
        or [["-", "-", "-", "-", "-", "-"]],
    )

    _h2(pdf, "3. Pengguna Server (OS)")
    w = [32, 26, 30, 24, 18, 40]
    _table(
        pdf,
        ["User OS", "VRAM", "CPU", "RAM", "Proses", "Aktivitas"],
        w,
        [
            [
                _pot(u["username"], w[0]),
                _mib(u["vram_mb"]) if u["vram_mb"] else "-",
                f"{u['cpu_percent']:.0f}% (~{u['cpu_cores_eq']:.0f})",
                _gb(u["memory_mb"]),
                str(u["processes"]),
                _pot(u["activity"], w[5]),
            ]
            for u in rep["os_users"]
        ]
        or [["-", "-", "-", "-", "-", "-"]],
    )

    _h2(pdf, "4. Proses CPU Teratas")
    w = [16, 28, 36, 36, 24, 30]
    _table(
        pdf,
        ["PID", "User", "Proses", "Workload", "CPU", "RAM"],
        w,
        [
            [
                str(p["pid"]),
                _pot(p["username"], w[1]),
                _pot(p["name"], w[2]),
                _pot(p["workload"], w[3]),
                f"{p['cpu_percent']:.0f}%",
                _gb(p["memory_mb"]),
            ]
            for p in rep["top_processes"]
        ]
        or [["-", "-", "-", "-", "-", "-"]],
    )

    _h2(pdf, "5. Statistik per Akun ComputeHub")
    w = [50, 44, 24, 20, 32]
    _table(
        pdf,
        ["Pengguna", "Email", "Role", "Job", "GPU total"],
        w,
        [
            [
                _pot(u["name"], w[0]),
                _pot(u["email"], w[1]),
                _pot(u["role"], w[2]),
                f"{u['jobs_total']} ({u['jobs_running']} jalan)",
                f"{u['gpu_seconds_total'] / 60:.0f} menit",
            ]
            for u in rep["users"]
        ]
        or [["-", "-", "-", "-", "-"]],
    )

    _h2(pdf, "6. Pemakai Layanan LLM Bersama (Ollama)")
    _para(
        pdf,
        "Beban Ollama tercatat atas nama akun layanan, bukan pemakainya. Dua tabel "
        "berikut menutup celah itu: siapa pemilik socket di tingkat sistem, dan akun "
        "ComputeHub mana yang memanggil Asisten AI.",
        size=9,
    )
    llm = rep.get("llm_connections") or {}
    if llm.get("klien") or llm.get("server"):
        _h3(pdf, "6.1 User Linux (pemilik socket klien)")
        _table(
            pdf,
            ["User", "UID", "Koneksi"],
            [60, 30, 30],
            [[k["user"], str(k["uid"]), str(k["koneksi"])] for k in llm.get("klien", [])]
            or [["-", "-", "-"]],
        )
        if llm.get("server"):
            _h3(pdf, "6.2 Asal koneksi masuk (container/host)")
            _table(
                pdf,
                ["Asal", "Koneksi"],
                [110, 30],
                [[_pot(x["asal"], 110), str(x["koneksi"])] for x in llm["server"]],
            )
    else:
        _para(pdf, "Tidak ada koneksi aktif ke layanan LLM saat laporan dibuat.")

    _h3(pdf, "6.3 Akun ComputeHub pemakai Asisten AI (30 hari)")
    w = [46, 44, 22, 20, 38]
    _table(
        pdf,
        ["Pengguna", "Email", "Minta", "Gambar", "Waktu proses"],
        w,
        [
            [
                _pot(u["nama"], w[0]),
                _pot(u["email"], w[1]),
                str(u["permintaan"]),
                str(u["vision"]),
                f"{u['detik'] / 60:.1f} menit",
            ]
            for u in rep.get("llm_users", [])
        ]
        or [["(belum ada permintaan tercatat)", "-", "-", "-", "-"]],
    )

    if riwayat:
        _bagian_riwayat(pdf, riwayat)

    out = pdf.output()
    return bytes(out)


def _bagian_riwayat(pdf: _PDF, riwayat: dict) -> None:
    """Bagian 7-10: riwayat & rincian yang tak terlihat pada potret sesaat."""
    hari = int(riwayat.get("days") or 0)
    label = "hari ini" if hari <= 0 else f"{hari} hari terakhir"

    _h2(pdf, f"7. Riwayat Pemakaian Harian - Server ({label})")
    _para(
        pdf,
        "Rekap per user Linux per hari dari cuplikan berkala. Arsip ini permanen "
        "sehingga pemakaian masa lalu tetap bisa dipertanggungjawabkan.",
        size=9,
    )
    w = [24, 32, 24, 26, 26, 22, 16]
    _table(
        pdf,
        ["Tanggal", "User", "CPU rata2", "RAM puncak", "VRAM puncak", "Aktivitas", "Menit"],
        w,
        [
            [
                r["tanggal"],
                _pot(r["username"], w[1]),
                f"{r['cpu_cores_avg']:.2f} core",
                _gb(r["ram_max_mb"]),
                _mib(r["vram_max_mb"]) if r["vram_max_mb"] else "-",
                _pot(r["aktivitas"], w[5]),
                f"{r['menit_aktif']:.0f}",
            ]
            for r in riwayat.get("os_users", [])
        ]
        or [["-", "-", "-", "-", "-", "-", "-"]],
    )

    jam = riwayat.get("os_jam") or []
    if jam:
        _h2(pdf, f"8. Rincian Per Jam - {riwayat.get('username', '')}")
        _para(pdf, 'Waktu server (WITA). Menjawab "jam berapa dipakai".', size=9)
        w = [24, 28, 26, 28, 28, 20, 16]
        _table(
            pdf,
            ["Tanggal", "Jam", "CPU rata2", "RAM puncak", "VRAM puncak", "Aktivitas", "Menit"],
            w,
            [
                [
                    r["tanggal"],
                    r["rentang"],
                    f"{r['cpu_cores_avg']:.2f} core",
                    _gb(r["ram_max_mb"]),
                    _mib(r["vram_max_mb"]) if r["vram_max_mb"] else "-",
                    _pot(r["aktivitas"], 20),
                    f"{r['menit_aktif']:.0f}",
                ]
                for r in jam
            ],
        )

    _h2(pdf, f"9. Riwayat Layanan LLM per Pihak ({label})")
    _para(
        pdf,
        '"Waktu aktif" = lama socket benar-benar mengalirkan data (hasil ukur tiap '
        '15 detik). "Perkiraan" = beban layanan dibagi menurut waktu aktif itu -- '
        "ESTIMASI, karena Ollama satu proses dan VRAM-nya tak bisa dipecah per pemakai.",
        size=9,
    )
    w = [24, 34, 20, 26, 32, 34]
    _table(
        pdf,
        ["Tanggal", "Pihak", "Koneksi", "Waktu aktif", "Beban VRAM", "Perkiraan VRAM"],
        w,
        [
            [
                r["tanggal"],
                _pot(r["nama"], w[1]),
                str(r["koneksi_max"]),
                f"{r['detik_aktif'] / 60:.1f} menit",
                _mib(r["layanan_vram_max_mb"]) if r["layanan_vram_max_mb"] else "-",
                _mib(r["est_vram_max_mb"]) if r["est_vram_max_mb"] else "-",
            ]
            for r in riwayat.get("llm_harian", [])
        ]
        or [["-", "-", "-", "-", "-", "-"]],
    )

    disk = riwayat.get("disk") or {}
    _h2(pdf, "10. Pemakaian Disk per User")
    total = float(disk.get("total_bytes") or 0)
    if total:
        _kv(
            pdf,
            "Disk terpakai",
            f"{float(disk.get('used_bytes', 0)) / 1024**3:.0f} GB / "
            f"{total / 1024**3:.0f} GB ({float(disk.get('used_percent', 0)):.0f}%)",
        )
    if disk.get("users"):
        _table(
            pdf,
            ["User", "Pemakaian"],
            [90, 50],
            [
                [_pot(u["user"], 90), f"{float(u['bytes']) / 1024**3:.2f} GB"]
                for u in disk["users"][:40]
            ],
        )
    else:
        # Pemindaian du /home berjalan di latar; jangan diam-diam hilangkan bagian ini.
        _para(
            pdf,
            "Rincian per user belum siap: pemindaian ukuran folder sedang berjalan "
            "di latar. Unduh ulang beberapa menit lagi untuk mendapatkannya.",
            size=9,
        )


def build_account_pdf(rep: dict) -> bytes:
    """Laporan DETAIL satu akun ComputeHub -> PDF."""
    a = rep["akun"]
    k = rep["kuota"]
    j = rep["job"]
    pdf = _PDF(orientation="P", unit="mm", format="A4")
    pdf.title_text = f"LAPORAN AKUN - {(a['nama'] or a['email']).upper()}"
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(0, 8, _san(a["nama"] or a["email"]), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(
        0, 5,
        _san(f"Akun ComputeHub  -  dibuat laporan {rep['generated_at']}"),
        new_x="LMARGIN", new_y="NEXT",
    )
    pdf.set_text_color(30, 30, 30)
    pdf.ln(1)

    _h2(pdf, "1. Identitas Akun")
    _kv(pdf, "Nama", a["nama"])
    _kv(pdf, "Email", a["email"])
    _kv(pdf, "Peran", a["role"])
    _kv(pdf, "Status", "aktif" if a["aktif"] else "NONAKTIF")
    _kv(pdf, "Login lewat", "SSO kampus" if a["sso"] else "lokal")
    _kv(pdf, "Akun Linux terkait", a["username_os"] or "-")
    _kv(pdf, "Hak pintu admin", "ya" if a["pintu_admin"] else "tidak")
    _kv(pdf, "Terdaftar sejak", a["dibuat"][:19].replace("T", " ") or "-")

    _h2(pdf, "2. Kuota yang Berlaku")
    _kv(pdf, "VRAM per job", _mib(k["vram_mb"]) if k["vram_mb"] else "tanpa batas")
    _kv(pdf, "RAM per job", _gb(k["ram_mb"]) if k["ram_mb"] else "tanpa batas")
    _kv(pdf, "Thread CPU", str(k["cpu_threads"] or "tanpa batas"))
    _kv(pdf, "Job serempak", str(k["job_serempak"] or "tanpa batas"))
    _kv(
        pdf, "Kuota GPU harian",
        f"{k['gpu_detik_harian'] / 3600:.1f} jam" if k["gpu_detik_harian"] else "tanpa batas",
    )
    _kv(
        pdf, "Batas waktu job",
        f"{k['batas_waktu_detik'] / 60:.0f} menit" if k["batas_waktu_detik"] else "tanpa batas",
    )
    _kv(pdf, "Penyimpanan", _gb(k["storage_mb"]) if k["storage_mb"] else "tanpa batas")
    _kv(pdf, "Model asisten", k["model_asisten"] or "ikut default peran")
    _kv(pdf, "Izin 2 GPU", "ya" if k["boleh_multi_gpu"] else "tidak")

    _h2(pdf, "3. Ringkasan Pemakaian (sepanjang masa)")
    _kv(
        pdf, "Job",
        f"{j['total']} total  -  {j['sukses']} sukses, {j['gagal']} gagal, "
        f"{j['batal']} batal, {j['jalan']} jalan, {j['antre']} antre",
    )
    _kv(pdf, "Waktu GPU", f"{j['gpu_detik'] / 3600:.2f} jam")
    _kv(pdf, "Waktu komputasi total", f"{j['total_detik'] / 3600:.2f} jam")
    _kv(pdf, "VRAM puncak", _mib(j["vram_max_mb"]) if j["vram_max_mb"] else "-")
    _kv(pdf, "RAM puncak", _gb(j["ram_max_mb"]) if j["ram_max_mb"] else "-")
    _kv(pdf, "CPU puncak", f"{j['cpu_max_percent']:.0f}%" if j["cpu_max_percent"] else "-")
    _kv(pdf, "Job pertama", (j["pertama"] or "-")[:19].replace("T", " "))
    _kv(pdf, "Job terakhir", (j["terakhir"] or "-")[:19].replace("T", " "))

    p = rep.get("penyimpanan") or {}
    _kv(
        pdf, "Penyimpanan dipakai",
        f"{_gb(p.get('dipakai_mb', 0))}"
        + (f" dari {_gb(p['kuota_mb'])}" if p.get("kuota_mb") else " (tanpa kuota)"),
    )

    hari = int(rep.get("days") or 0)
    _h2(pdf, f"4. Riwayat Harian: Job & Resource ({hari} hari terakhir)")
    _para(
        pdf,
        "Angka resource diukur langsung pada proses job milik akun ini. Akun Linux "
        "yang tertera di bagian 1 hanya nama logis (bukan akun /etc/passwd), jadi "
        "pemakaian akun platform tidak muncul pada cuplikan per-user OS.",
        size=8.5,
    )
    w = [24, 16, 18, 16, 28, 28, 26, 20]
    _table(
        pdf,
        ["Tanggal", "Job", "Sukses", "Gagal", "Waktu GPU", "VRAM puncak", "RAM puncak", "CPU"],
        w,
        [
            [
                r["tanggal"],
                str(r["jobs"]),
                str(r["sukses"]),
                str(r["gagal"]),
                f"{r['gpu_detik'] / 60:.1f} mnt",
                _mib(r["vram_max_mb"]) if r["vram_max_mb"] else "-",
                _gb(r["ram_max_mb"]) if r["ram_max_mb"] else "-",
                f"{r.get('cpu_max_percent', 0):.0f}%" if r.get("cpu_max_percent") else "-",
            ]
            for r in rep.get("harian", [])
        ]
        or [["-", "-", "-", "-", "-", "-", "-", "-"]],
    )

    _h2(pdf, f"5. Pemakaian Asisten AI ({hari} hari terakhir)")
    asis = rep.get("asisten") or {}
    if asis:
        _kv(pdf, "Permintaan", str(asis.get("permintaan", 0)))
        _kv(pdf, "Memakai gambar", str(asis.get("vision", 0)))
        _kv(pdf, "Waktu proses", f"{float(asis.get('detik', 0)) / 60:.1f} menit")
        _kv(pdf, "Balasan", f"{asis.get('reply_chars', 0):,} karakter")
        _kv(pdf, "Terakhir", (asis.get("terakhir") or "-")[:19].replace("T", " "))
        _para(
            pdf,
            "Catatan: beban GPU asisten ada pada layanan LLM bersama (satu proses), "
            "sehingga VRAM-nya tidak dapat dibebankan persis ke akun ini.",
            size=8.5,
        )
    else:
        _para(pdf, "Belum ada permintaan asisten tercatat pada rentang ini.")

    _h2(pdf, "6. Job Terakhir")
    w = [14, 46, 24, 18, 26, 30]
    _table(
        pdf,
        ["ID", "Nama", "Status", "Device", "Durasi", "VRAM puncak"],
        w,
        [
            [
                str(r["id"]),
                _pot(r["nama"], w[1]),
                r["status"],
                r["device"],
                f"{r['detik'] / 60:.1f} mnt",
                _mib(r["vram_mb"]) if r["vram_mb"] else "-",
            ]
            for r in rep.get("job_terakhir", [])
        ]
        or [["-", "-", "-", "-", "-", "-"]],
    )

    out = pdf.output()
    return bytes(out)


def account_pdf_filename(nama: str) -> str:
    safe = "".join(c for c in (nama or "") if c.isalnum() or c in "-_") or "akun"
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"laporan_akun_{safe}_{stamp}.pdf"


def full_pdf_filename() -> str:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"laporan_server_{stamp}.pdf"


def pdf_filename(username: str) -> str:
    safe = "".join(c for c in username if c.isalnum() or c in "-_") or "user"
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"peringatan_{safe}_{stamp}.pdf"
