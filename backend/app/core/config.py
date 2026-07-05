"""Application configuration.

Semua setting dibaca dari environment / file `.env` (lihat `.env.example`).
Tidak perlu mengubah kode untuk pindah stack (SQLite <-> PostgreSQL, dll).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .../backend  (file ini: backend/app/core/config.py -> parents[2] = backend)
BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Konfigurasi aplikasi (di-load sekali saat startup)."""

    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # --- Umum ---
    PROJECT_NAME: str = "UNISMUH ComputeHub"
    ENV: str = "production"
    API_V1_PREFIX: str = "/api/v1"
    HOST: str = "127.0.0.1"
    PORT: int = 8000

    # --- Keamanan ---
    SECRET_KEY: str = "CHANGE_ME_PLEASE"
    ALGORITHM: str = "HS256"
    # Access token UMUR PENDEK (dipasangkan dengan refresh token). 30 menit.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # Refresh token: masa berlaku per peran. Admin lama (30 hari), mahasiswa/dosen
    # pendek (1 hari) — rotasi sesi tunggal tetap mengganti token tiap login.
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 1440  # 1 hari (mahasiswa & dosen)
    REFRESH_TOKEN_EXPIRE_MINUTES_ADMIN: int = 43200  # 30 hari (admin)
    # Refresh token via cookie HttpOnly (OBS-4): saat login/refresh, refresh token JUGA
    # dikirim sebagai cookie HttpOnly (tak terbaca JavaScript -> mitigasi pencurian via XSS).
    # Backward-compatible: refresh token TETAP dikembalikan di body (klien lama/cross-origin
    # yang cookie pihak-ketiganya diblokir tetap jalan). Cookie di-scope ke path /auth saja.
    #   - AUTH_COOKIE_SECURE=True + SAMESITE="none": WAJIB utk cross-site (Vercel<->tunnel) via
    #     HTTPS. Utk deploy same-origin HTTP dev, set SECURE=False & SAMESITE="lax".
    AUTH_REFRESH_COOKIE_ENABLED: bool = True
    AUTH_REFRESH_COOKIE_NAME: str = "ch_refresh"
    AUTH_COOKIE_SECURE: bool = True
    AUTH_COOKIE_SAMESITE: str = "none"  # "none" | "lax" | "strict"
    # Content-Security-Policy (dipasang di main.py). Permisif utk Monaco editor
    # (jsdelivr + eval + worker blob) & backend tunnel dinamis (connect https/wss),
    # tetap mengunci object-src/frame-ancestors/base-uri/form-action.
    CONTENT_SECURITY_POLICY: str = (
        "default-src 'self'; base-uri 'self'; object-src 'none'; "
        "frame-ancestors 'none'; form-action 'self'; "
        "img-src 'self' data: blob: https:; "
        "font-src 'self' data: https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "script-src 'self' 'unsafe-eval' https://cdn.jsdelivr.net; "
        "worker-src 'self' blob:; connect-src 'self' https: wss:"
    )

    # --- Rate limit login (anti brute-force) ---
    LOGIN_RATE_LIMIT_MAX_ATTEMPTS: int = 10    # maks. percobaan GAGAL per window
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 300  # jendela hitung percobaan (5 menit)
    LOGIN_RATE_LIMIT_BLOCK_SECONDS: int = 600   # lama diblokir setelah lewat batas
    # Di balik proxy/tunnel (cloudflared), IP TCP = 127.0.0.1 utk SEMUA user -> rate-limit
    # jadi GLOBAL. Bila True, pakai CF-Connecting-IP / X-Forwarded-For sbg IP asli (per-user).
    TRUST_PROXY_HEADERS: bool = True

    # --- Database ---
    DATABASE_URL: str = "sqlite+aiosqlite:///./unismuh_ai_cloud.db"
    DB_REQUIRE_SSL: bool = True   # wajibkan SSL utk Postgres remote (mis. Supabase)
    # Hardening keamanan Postgres (mis. Supabase): saat startup, AKTIFKAN Row-Level Security
    # + CABUT hak peran API publik (anon/authenticated) pada tabel public MILIK peran koneksi.
    # Peran koneksi = pemilik tabel -> BYPASS RLS (aplikasi tak terpengaruh), tapi PostgREST
    # publik Supabase (/rest/v1) TERBLOKIR -> menutup celah 'rls_disabled_in_public'. Idempoten.
    DB_ENFORCE_RLS: bool = True

    # --- Logging (stdout + file dengan rotasi) ---
    LOG_DIR: str = "./logs"
    LOG_FILE: str = "app.log"
    LOG_LEVEL: str = "INFO"
    LOG_MAX_BYTES: int = 5_000_000   # ~5MB per file sebelum dirotasi
    LOG_BACKUP_COUNT: int = 5        # jumlah berkas rotasi yang disimpan
    LOG_TO_FILE: bool = True

    # --- CORS (comma-separated; lihat properti cors_origins) ---
    BACKEND_CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    # --- Scheduler & monitoring ---
    SCHEDULER_MODE: str = "local"
    SCHEDULER_INTERVAL_SECONDS: float = 8.0
    MONITOR_SAMPLE_INTERVAL_SECONDS: float = 30.0
    # Interval push stream monitor LIVE (SSE) ke UI -> real-time. 500 ms = 2x/detik.
    MONITOR_STREAM_INTERVAL_MS: int = 500
    # Cache auth ringan utk endpoint baca frekuensi-tinggi (monitoring): hindari lookup
    # user ke DB (Supabase Tokyo ~800ms) tiap poll. Deaktivasi user berlaku <= TTL ini.
    AUTH_CACHE_TTL_SECONDS: int = 10
    # Plafon job paralel GLOBAL. Pembatas nyata kini = kolam GPU (VRAM) + kolam
    # CPU (core); angka ini hanya pagar atas supaya loop tidak kebablasan.
    MAX_CONCURRENT_JOBS: int = 32

    # --- Batas CPU proses platform (jadi "warga server" yang baik) ---
    # Proses orkestrasi (web + scheduler + monitor + laporan) WAJIB ringan.
    PLATFORM_NICE: int = 15            # 0..19; makin tinggi makin mengalah ke user lain
    PLATFORM_CPU_THREADS: int = 2      # plafon thread BLAS/OpenMP/torch utk proses ini
    PLATFORM_CPU_AFFINITY: str = ""    # "" = semua core; mis. "0-3" atau "0,1,2,3"
    REPORT_CACHE_TTL_SECONDS: float = 20.0  # cache scan proses OS (hemat CPU saat polling)

    # --- Peringatan (alert) batas resource + email PDF ---
    ALERT_CHECK_INTERVAL_SECONDS: int = 300   # interval cek pelanggaran batas
    ALERTS_DIR: str = "./_alerts"             # tempat simpan PDF peringatan
    # Penerima default laporan peringatan (dipisah koma). Kosong = fallback email admin.
    ALERT_EMAIL_TO: str = ""
    # SMTP (kosongkan SMTP_HOST untuk menonaktifkan pengiriman email)
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_USE_TLS: bool = True
    SMTP_USE_SSL: bool = False
    SMTP_TIMEOUT: int = 20

    # --- Kuota resource (0 = auto-detect) ---
    TOTAL_CPU_CORES: int = 0
    TOTAL_MEMORY_MB: int = 0
    RESERVED_MEMORY_MB: int = 2048
    RESERVED_CPU_CORES: int = 2

    # --- Eksekusi job ---
    JOBS_DIR: str = "./_jobs"
    ENABLE_JOB_EXECUTION: bool = True

    # --- Batas resource keras subprocess job/kernel (mitigasi DoS; 0 = lewati) ---
    # CATATAN: RLIMIT_AS/memori virtual TIDAK dipakai (CUDA/PyTorch reserve address
    # space besar -> akan crash). Plafon memori ditegakkan via sampler (advisory).
    JOB_RLIMIT_NPROC: int = 16384        # maks proses/thread real-UID (cegah fork bomb); 0 = off
    JOB_RLIMIT_FSIZE_MB: int = 0         # maks ukuran 1 file (MB); 0 = off
    JOB_RLIMIT_NOFILE: int = 0           # maks file descriptor terbuka; 0 = off
    JOB_RLIMIT_NO_CORE: bool = True      # True = nonaktifkan core dump (cegah disk fill)

    # --- Sandbox isolasi (user-namespace via unshare; non-root) ---
    # True = bungkus eksekusi job/kernel dalam user+mount namespace yang MENYEMBUNYIKAN
    # file rahasia (backend/.env) dari kode user, sekaligus memblok ptrace ke proses
    # backend. GPU & jaringan TETAP jalan. Otomatis nonaktif bila unshare tak tersedia.
    JOB_SANDBOX_ENABLED: bool = True

    # --- Provisioning Docker per-user (1 user 1 docker) — OPT-IN, OFF default ---
    # KEAMANAN: hanya menyentuh container bernama PERSIS f"{DOCKER_USER_PREFIX}{user_id}".
    # TIDAK pernah prune/rm pola lebar, TIDAK ubah daemon/sudoers/grup. Default NONAKTIF
    # -> tak menjalankan docker apa pun sampai diaktifkan eksplisit (akses docker utk
    # service backend diatur TERPISAH oleh admin, BUKAN otomatis oleh aplikasi).
    DOCKER_PROVISION_ENABLED: bool = False
    # Mode provisioning per-user (saat fitur aktif):
    #   "on_demand" (DEFAULT, EFISIEN): TIDAK menjalankan container idle per-user. Isolasi
    #     "1 user 1 docker" diberikan oleh container EFEMERAL per-job (ch-job-*) & per-sesi
    #     (ch-kernel-*) yang mount volume persisten user (/persist) HANYA saat dipakai, lalu
    #     auto-hapus (--rm). Provision = pastikan folder data user ada. Hasil: 0 container idle.
    #   "eager": juga buat container ch-user-<id> (sleep infinity, --restart unless-stopped)
    #     saat user dibuat -> 1 container idle PER user (boros bila banyak user; container itu
    #     pun TIDAK dipakai utk eksekusi). Dipertahankan utk kompatibilitas/kebutuhan eksplisit.
    DOCKER_PROVISION_MODE: str = "on_demand"
    # Runtime eksekusi job: "unshare" (sandbox host, default) atau "docker" (container
    # efemeral per-job ch-job-<id> dari DOCKER_USER_IMAGE; butuh DOCKER_PROVISION_ENABLED).
    JOB_RUNTIME: str = "unshare"
    # Runtime sesi INTERAKTIF (notebook/kernel): "unshare" (host, default) atau "docker"
    # (kernel jalan di container ch-compute; butuh DOCKER_PROVISION_ENABLED).
    INTERACTIVE_RUNTIME: str = "unshare"
    # Jaringan container kernel interaktif: "bridge" (TERISOLASI: tak bisa akses layanan
    # localhost host lain, port ZMQ di-publish ke 127.0.0.1; default) atau "host" (lama,
    # --network host; kernel bisa menjangkau seluruh localhost server bersama = celah).
    INTERACTIVE_KERNEL_NET: str = "bridge"
    DOCKER_CMD: str = "docker"            # biner docker apa adanya (jangan auto-sudo)
    DOCKER_USER_IMAGE: str = "nvidia/cuda:12.1.0-base-ubuntu22.04"
    DOCKER_USER_PREFIX: str = "ch-user-"  # prefix nama container/volume MILIK KITA
    DOCKER_USER_DATA_ROOT: str = "~/.computehub/users"  # root volume per-user (scope project)
    DOCKER_USER_GPUS: str = "all"         # nilai --gpus; "" = tanpa GPU
    DOCKER_USER_MEMORY: str = "8g"        # batas RAM/container; "" = tak dibatasi
    DOCKER_USER_CPUS: str = "2"           # batas CPU/container; "" = tak dibatasi
    DOCKER_USER_PIDS_LIMIT: int = 2048    # batas proses/container; 0 = off
    DOCKER_CMD_TIMEOUT_SECONDS: float = 30.0
    # --- Hardening container EKSEKUSI (job ch-job-* & kernel ch-kernel-*) ---
    # Jalankan kode (tak tepercaya) mahasiswa dgn hak SEMINIMAL mungkin di container.
    # DOCKER_HARDENING: --cap-drop ALL + --security-opt no-new-privileges (risiko rendah,
    #   tak butuh capability utk Python/torch/pip). DOCKER_RUN_AS_HOST_USER: --user uid:gid
    #   host -> proses non-root DI DALAM container + file hasil dimiliki user host (bukan
    #   root) sehingga cleanup tak perlu sudo. Revert: set salah satu false di .env + restart.
    DOCKER_HARDENING: bool = True
    DOCKER_RUN_AS_HOST_USER: bool = True
    # Kuota penyimpanan /persist per-user (MB); 0 = TANPA batas. Default global di sini;
    # SUPER ADMIN bisa override per-user di Kelola Kebijakan. Ditegakkan saat unggah/simpan
    # file ke workspace (Penyimpanan).
    DEFAULT_STORAGE_QUOTA_MB: float = 0.0
    # Guard kuota disk /persist (services/storage_guard.py): pantau pemakaian tiap user vs
    # max_storage_mb. INERT selama tak ada kuota (max_storage_mb=0 -> tak ada aksi).
    #   - STORAGE_ENFORCE_ENABLED: bila user >= 100% kuota, TOLAK job/sesi baru + hentikan
    #     job/sesi berjalan miliknya (agar berhenti menulis). Revert: set false di .env.
    #   - STORAGE_ALERT_PERCENT: kirim peringatan email (via Alerts) saat pemakaian >= X% kuota.
    STORAGE_ENFORCE_ENABLED: bool = True
    STORAGE_GUARD_INTERVAL_SECONDS: float = 300.0
    STORAGE_ALERT_PERCENT: float = 90.0

    # --- Retensi & pembersihan otomatis (hemat disk server) ---
    JOB_RETENTION_DAYS: int = 14         # hapus folder job terminal > N hari (0 = off)
    ALERT_RETENTION_DAYS: int = 30       # hapus PDF peringatan > N hari (0 = off)
    MONITOR_RETENTION_DAYS: int = 7      # hapus baris resource_samples > N hari (0 = off)
    CLEANUP_INTERVAL_HOURS: float = 6.0  # interval scan pembersihan

    # --- Enforcement GPU (job GPU di-pin & wajib lihat CUDA) ---
    ENFORCE_GPU: bool = True
    ALLOW_CPU_FALLBACK: bool = False
    REQUIRE_CUDA_PREFLIGHT: bool = True
    GPU_VISIBLE_DEVICES: str = ""  # "" = semua GPU; atau "0,1"
    GPU_MIN_FREE_MEMORY_MB: float = 1024.0

    # --- Komputasi CPU (mis. Random Forest/ML klasik) dgn kolam core + antrian ---
    ALLOW_CPU_JOBS: bool = True          # True = job/sesi boleh pilih device CPU
    CPU_POOL_CORES: int = 48             # core utk job platform (0 = nproc - reserved)
    CPU_RESERVED_CORES: int = 16         # core disisakan utk OS + user server lain

    # --- GPU SHARING (banyak beban kerja berbagi 1 GPU sesuai VRAM) ---
    GPU_SHARE_ENABLED: bool = True            # True = boleh >1 job/sesi per GPU
    GPU_MAX_WORKLOADS_PER_GPU: int = 4        # batas beban kerja serempak/GPU (0 = tak terbatas)
    GPU_SHARE_HEADROOM_MB: float = 2048.0     # sisakan VRAM bebas tiap GPU (cadangan aman)

    # --- Sampling resource per-job (RAM/VRAM/GPU) ---
    JOB_SAMPLE_INTERVAL_SECONDS: float = 5.0

    # --- Sesi interaktif (notebook/console ala Colab; kernel hidup di GPU) ---
    INTERACTIVE_ENABLED: bool = True
    INTERACTIVE_MAX_SESSIONS: int = 8              # total kernel hidup serempak (sharing -> > jumlah GPU)
    INTERACTIVE_DEFAULT_VRAM_MB: float = 8192.0    # anggaran VRAM default 1 sesi (bila peran tanpa batas)
    INTERACTIVE_IDLE_TIMEOUT_SECONDS: int = 1800   # 30 mnt idle -> kernel dimatikan (bebaskan GPU)
    INTERACTIVE_MAX_EXEC_SECONDS: int = 600        # batas waktu eksekusi 1 sel (anti runaway)
    INTERACTIVE_MAX_SESSION_SECONDS: int = 7200    # umur maks 1 sesi (2 jam) -> bebaskan GPU
    INTERACTIVE_STARTUP_TIMEOUT_SECONDS: int = 90  # tunggu kernel siap
    # Auto-antrian sesi interaktif (auto-mulai saat slot kosong):
    INTERACTIVE_GRANT_TTL_SECONDS: int = 120       # jatah giliran (klaim slot) sebelum kedaluwarsa
    INTERACTIVE_QUEUE_TTL_SECONDS: int = 180        # tiket antri dibuang bila berhenti dipantau (tab ditutup)

    # --- Asisten AI notebook (chat ala Copilot; provider OpenAI-compatible) ---
    # Default base URL menunjuk GitHub Models. Aktif begitu ASSISTANT_API_KEY diisi
    # (GitHub Personal Access Token, scope: models:read) di .env. Bisa diganti ke
    # OpenAI/OpenRouter/Groq atau server vLLM/Ollama lokal tanpa ubah kode.
    ASSISTANT_ENABLED: bool = True
    ASSISTANT_API_BASE: str = "https://models.github.ai/inference"
    ASSISTANT_API_KEY: str = ""                     # RAHASIA -> isi di .env (JANGAN di .env.example)
    ASSISTANT_MODEL: str = "openai/gpt-4o-mini"
    # Model asisten AI per-peran (mis. Ollama). Bisa diubah admin via Pengaturan.
    # Kosong -> fallback ke ASSISTANT_MODEL. Default: ringan utk mahasiswa, lebih kuat utk dosen/admin.
    ASSISTANT_MODEL_STUDENT: str = "llama3.2:latest"
    ASSISTANT_MODEL_DOSEN: str = "gpt-oss:latest"
    ASSISTANT_MODEL_ADMIN: str = "gpt-oss:latest"
    # Model VISION (multimodal) dipakai OTOMATIS saat pesan menyertakan gambar
    # (upload foto/plot/screenshot). Editable admin via Pengaturan. Kosong -> fitur nonaktif.
    # gemma3:4b TERUJI ~6s & hanya ~7.7GB VRAM (RINGAN, 100% GPU). gemma3:27b lebih pintar tapi
    # ~30GB. qwen2.5vl di Ollama ini RUSAK (jangan dipakai).
    ASSISTANT_MODEL_VISION: str = "gemma3:4b"
    ASSISTANT_MAX_IMAGES: int = 4                    # maks gambar per permintaan
    ASSISTANT_MAX_IMAGE_CHARS: int = 4_000_000       # batas panjang data URL base64/gambar
    # Batas permintaan VISION yang diproses BERSAMAAN. Dgn model ringan (gemma3:4b ~7.7GB) 2
    # aman di 1 GPU; naikkan bila GPU lengang, turunkan ke 1 bila memakai model berat (27b).
    ASSISTANT_VISION_CONCURRENCY: int = 2
    ASSISTANT_PROVIDER_LABEL: str = "GitHub Models"
    ASSISTANT_MAX_TOKENS: int = 1024
    ASSISTANT_TEMPERATURE: float = 0.2
    # Model VISION bisa lambat "cold-load" ke VRAM saat GPU server ramai (dipakai
    # user lain) -> beri jendela lebih lega agar jawaban gambar tak keburu timeout.
    ASSISTANT_TIMEOUT_SECONDS: float = 180.0

    # --- Batas waktu eksekusi job (timeout, detik) ---
    DEFAULT_JOB_TIME_LIMIT_SECONDS: int = 3600       # default 1 jam
    STUDENT_MAX_TIME_LIMIT_SECONDS: int = 7200       # plafon (mahasiswa) 2 jam
    MAX_JOB_TIME_LIMIT_SECONDS: int = 86400          # batas absolut (admin) 24 jam
    MIN_JOB_TIME_LIMIT_SECONDS: int = 120            # lantai batas waktu otomatis
    RUNTIME_SAFETY_FACTOR: float = 1.5               # faktor pengaman estimasi

    # --- Upload project (ZIP) ---
    MAX_UPLOAD_SIZE_MB: int = 200                    # ukuran arsip
    MAX_UPLOAD_UNCOMPRESSED_MB: int = 1024           # anti zip-bomb
    MAX_UPLOAD_FILES: int = 5000                     # batas jumlah file

    # --- Foto profil (avatar) ---
    # Disimpan sbg data URL base64 di kolom users.avatar (terkompres 256px di klien),
    # bukan berkas di disk server. Batas panjang melindungi DB & payload dari kiriman besar.
    AVATAR_MAX_CHARS: int = 300_000                  # ~225KB base64 (cukup utk 256px JPEG)

    # --- Auto install dependency (requirements.txt) ---
    AUTO_PIP_INSTALL: bool = True                    # default install otomatis
    PIP_INSTALL_TIMEOUT_SECONDS: int = 600           # batas waktu pip install

    # --- Kuota GPU harian per mahasiswa (detik, rolling 24 jam) ---
    STUDENT_DAILY_GPU_SECONDS_QUOTA: int = 14400     # 4 jam/hari; 0 = tanpa batas

    # --- Kebijakan peran (mahasiswa dibatasi, dosen bebas) ---
    # Mahasiswa: prioritas TIDAK bisa diatur (mengikuti urutan submit / FIFO),
    # dan jumlah job berjalan dibatasi.
    STUDENT_MAX_CONCURRENT_JOBS: int = 1
    STUDENT_MAX_GPU_MEMORY_MB: float = 8192.0  # plafon VRAM per job (MB); 0 = tanpa batas
    STUDENT_MAX_RAM_MB: float = 8192.0      # plafon RAM proses (MB); 0 = tanpa batas
    STUDENT_MAX_CPU_THREADS: int = 2        # maks core komputasi; 0 = pakai default
    # Dosen: batas pemakaian resource (angka diisi super admin via UI; 0 = tanpa batas).
    DOSEN_MAX_CONCURRENT_JOBS: int = 1               # maks job/sesi GPU berjalan / dosen
    DOSEN_DAILY_GPU_SECONDS_QUOTA: int = 0           # detik/24jam; 0 = tanpa batas
    DOSEN_MAX_GPU_MEMORY_MB: float = 8192.0          # plafon VRAM per job (MB); 0 = penuh
    DOSEN_MAX_RAM_MB: float = 8192.0                 # plafon RAM proses (MB); 0 = tanpa batas
    DOSEN_MAX_CPU_THREADS: int = 2                   # maks core komputasi; 0 = pakai default
    # Admin BIASA juga bisa dibatasi (super admin tetap bebas & jadi pengatur). 0 = tanpa batas.
    ADMIN_MAX_CONCURRENT_JOBS: int = 0
    ADMIN_DAILY_GPU_SECONDS_QUOTA: int = 0
    ADMIN_MAX_GPU_MEMORY_MB: float = 8192.0
    ADMIN_MAX_RAM_MB: float = 8192.0
    ADMIN_MAX_CPU_THREADS: int = 2
    # Core komputasi default per job bila plafon peran = 0 (jaga server bersama).
    JOB_DEFAULT_CPU_THREADS: int = 2
    # Dosen & admin boleh atur prioritas (selalu di atas mahasiswa).
    DOSEN_DEFAULT_PRIORITY: int = 20
    DOSEN_MAX_PRIORITY: int = 50
    ADMIN_MAX_PRIORITY: int = 100

    # --- Sumber job dari Git (GitHub) ---
    ALLOWED_GIT_HOSTS: str = "github.com"
    GIT_CLONE_TIMEOUT_SECONDS: int = 180

    # --- Admin pertama ---
    # WAJIB di-set via .env saat instalasi BARU (tidak ada default demi keamanan).
    FIRST_ADMIN_NAME: str = "Administrator"
    FIRST_ADMIN_EMAIL: str = "admin@unismuh.ac.id"
    FIRST_ADMIN_PASSWORD: str = ""

    # ----------------------------------------------------------------- helpers
    @property
    def cors_origins(self) -> list[str]:
        """Daftar origin CORS (dipisah koma)."""
        return [o.strip() for o in self.BACKEND_CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    @property
    def is_postgres(self) -> bool:
        return self.DATABASE_URL.startswith("postgresql")

    @property
    def jobs_path(self) -> Path:
        """Direktori kerja job (absolut, relatif ke folder backend)."""
        p = Path(self.JOBS_DIR).expanduser()
        if not p.is_absolute():
            p = BACKEND_DIR / p
        return p

    @property
    def docker_user_data_root(self) -> Path:
        """Root volume data per-user (provisioning Docker per-user)."""
        p = Path(self.DOCKER_USER_DATA_ROOT).expanduser()
        if not p.is_absolute():
            p = BACKEND_DIR / p
        return p

    @property
    def alerts_path(self) -> Path:
        """Direktori penyimpanan PDF peringatan."""
        p = Path(self.ALERTS_DIR).expanduser()
        if not p.is_absolute():
            p = BACKEND_DIR / p
        return p

    @property
    def log_dir_path(self) -> Path:
        """Direktori berkas log (absolut, relatif ke folder backend)."""
        p = Path(self.LOG_DIR).expanduser()
        if not p.is_absolute():
            p = BACKEND_DIR / p
        return p

    @property
    def is_first_admin_password_safe(self) -> bool:
        """True bila FIRST_ADMIN_PASSWORD layak dipakai (bukan default lemah)."""
        weak = {"", "admin", "admin123", "password", "password123", "changeme"}
        pwd = self.FIRST_ADMIN_PASSWORD.strip()
        return pwd.lower() not in weak and len(pwd) >= 8

    @property
    def smtp_configured(self) -> bool:
        """True bila SMTP siap mengirim email."""
        return bool(self.SMTP_HOST.strip())

    @property
    def assistant_configured(self) -> bool:
        """True bila asisten AI siap dipakai.

        Provider LOKAL (Ollama/vLLM di localhost) TIDAK butuh kunci API; provider cloud
        (GitHub Models/OpenAI) butuh ASSISTANT_API_KEY.
        """
        if not self.ASSISTANT_ENABLED:
            return False
        return bool(self.ASSISTANT_API_KEY.strip()) or self.assistant_is_local

    @property
    def assistant_is_local(self) -> bool:
        """True bila base URL asisten menunjuk endpoint lokal (Ollama/vLLM) -> tanpa kunci."""
        base = self.ASSISTANT_API_BASE.lower()
        return "localhost" in base or "127.0.0.1" in base or ":11434" in base

    @property
    def assistant_chat_url(self) -> str:
        """Endpoint chat completions (OpenAI-compatible) dari base URL provider."""
        base = self.ASSISTANT_API_BASE.strip().rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    @property
    def gpu_visible_indices(self) -> list[int] | None:
        """Indeks GPU yang boleh dipakai platform; None = semua."""
        raw = self.GPU_VISIBLE_DEVICES.strip()
        if not raw:
            return None
        out: list[int] = []
        for part in raw.split(","):
            part = part.strip()
            if part != "":
                out.append(int(part))
        return out

    @property
    def is_secret_key_safe(self) -> bool:
        weak = {"", "CHANGE_ME", "CHANGE_ME_PLEASE", "GANTI-DENGAN-STRING-ACAK-PANJANG"}
        return self.SECRET_KEY not in weak and len(self.SECRET_KEY) >= 32

    @property
    def allowed_git_hosts(self) -> set[str]:
        return {
            h.strip().lower()
            for h in self.ALLOWED_GIT_HOSTS.split(",")
            if h.strip()
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
