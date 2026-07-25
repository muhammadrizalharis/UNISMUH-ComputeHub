import { useEffect, useRef, useState } from 'react'
import { Link, Navigate } from 'react-router-dom'

import { Meteors, ParticleField } from '../components/BackgroundFx'
import { usePageTransition } from '../components/PageTransition'
import SiteFooter from '../components/SiteFooter'
import ThemeToggle from '../components/ThemeToggle'
import { useAuth } from '../lib/auth'

const CAMPUS_BG = '/campus.jpg'

const LOGOS = [
  { src: '/logos/unismuh.jpg', alt: 'Universitas Muhammadiyah Makassar' },
  { src: '/logos/teknik-biru.png', alt: 'Fakultas Teknik UNISMUH' },
  { src: '/logos/unggul.png', alt: 'Akreditasi Unggul' },
  { src: '/logos/gift.png', alt: 'GIFT UNISMUH' },
  { src: '/logos/teknik-merah.png', alt: 'Fakultas Teknik UNISMUH' },
]

/* ============================================================== typewriter */
const KATA_BERGANTI = [
  'Masa Depan Akademik',
  'Skripsi & Penelitian',
  'Deep Learning',
  'Data Science',
  'Computer Vision',
]

/** Kata di judul mengetik-menghapus bergantian, tanpa henti. */
function Typewriter() {
  const [idx, setIdx] = useState(0)
  const [len, setLen] = useState(KATA_BERGANTI[0].length)
  const [fase, setFase] = useState<'tahan' | 'hapus' | 'ketik'>('tahan')
  useEffect(() => {
    let t: number
    if (fase === 'tahan') {
      t = window.setTimeout(() => setFase('hapus'), 2100)
    } else if (fase === 'hapus') {
      if (len === 0) {
        setIdx((i) => (i + 1) % KATA_BERGANTI.length)
        setFase('ketik')
      } else t = window.setTimeout(() => setLen(len - 1), 32)
    } else {
      if (len === KATA_BERGANTI[idx].length) setFase('tahan')
      else t = window.setTimeout(() => setLen(len + 1), 65)
    }
    return () => clearTimeout(t)
  }, [fase, len, idx])
  return (
    <span className="whitespace-nowrap">
      <span className="gradient-text">{KATA_BERGANTI[idx].slice(0, len)}</span>
      <span className="caret text-cyan-300" aria-hidden="true" />
    </span>
  )
}

/* ======================================================== terminal hidup */
const BARIS_TERMINAL: Array<{ teks: string; cls: string; ketik?: boolean }> = [
  { teks: '!nvidia-smi', cls: 'text-emerald-300', ketik: true },
  { teks: 'NVIDIA L40S · 48 GB VRAM · CUDA 12.4  ✓', cls: 'text-white/70' },
  { teks: 'model.fit(X_train, y_train, epochs=50)', cls: 'text-sky-300', ketik: true },
  { teks: 'Epoch 50/50 ━━━━━━━━━━━━━━ loss 0.08 · acc 0.97', cls: 'text-white/70' },
  { teks: '✓ Training selesai — GPU kampus, gratis untuk mahasiswa', cls: 'text-emerald-300' },
]

/** Mock notebook yang mengetik & "menjalankan" kode training, berulang terus. */
function TerminalDemo() {
  const [baris, setBaris] = useState(0)
  const [kolom, setKolom] = useState(0)
  useEffect(() => {
    let t: number
    const aktif = BARIS_TERMINAL[baris]
    if (!aktif) {
      // Semua baris tampil -> tahan sejenak, lalu ulang dari awal.
      t = window.setTimeout(() => {
        setBaris(0)
        setKolom(0)
      }, 3600)
    } else if (aktif.ketik && kolom < aktif.teks.length) {
      t = window.setTimeout(() => setKolom(kolom + 1), 48)
    } else {
      t = window.setTimeout(
        () => {
          setBaris(baris + 1)
          setKolom(0)
        },
        aktif.ketik ? 450 : 750,
      )
    }
    return () => clearTimeout(t)
  }, [baris, kolom])

  const tampil = baris
  return (
    <div className="overflow-hidden rounded-2xl bg-slate-950/80 text-left shadow-2xl ring-1 ring-white/15 backdrop-blur">
      <div className="flex items-center gap-1.5 border-b border-white/10 px-4 py-2.5">
        <span className="h-2.5 w-2.5 rounded-full bg-rose-400/90" />
        <span className="h-2.5 w-2.5 rounded-full bg-amber-300/90" />
        <span className="h-2.5 w-2.5 rounded-full bg-emerald-400/90" />
        <span className="ml-2 text-[11px] font-medium text-white/50">
          notebook.ipynb — ComputeHub
        </span>
        <span className="ml-auto inline-flex items-center gap-1 text-[10px] font-semibold text-emerald-300">
          <span className="glow-pulse h-1.5 w-1.5 rounded-full bg-emerald-400" /> GPU aktif
        </span>
      </div>
      <div className="min-h-[10rem] px-4 py-3 font-mono text-xs leading-6 sm:text-[13px]">
        {BARIS_TERMINAL.slice(0, tampil).map((b, i) => (
          <p key={i} className={b.cls}>
            {b.ketik && <span className="mr-1.5 text-white/35">$</span>}
            {b.teks}
          </p>
        ))}
        {BARIS_TERMINAL[baris] && (
          <p className={BARIS_TERMINAL[baris].cls}>
            {BARIS_TERMINAL[baris].ketik && (
              <span className="mr-1.5 text-white/35">$</span>
            )}
            {BARIS_TERMINAL[baris].ketik
              ? BARIS_TERMINAL[baris].teks.slice(0, kolom)
              : null}
            <span className="caret" aria-hidden="true" />
          </p>
        )}
      </div>
    </div>
  )
}

/* ========================================================== marquee chip */
const TEKNOLOGI = [
  '🐍 Python 3.10–3.13',
  '🔥 PyTorch',
  '🧠 TensorFlow',
  '⚡ CUDA 12',
  '📊 pandas',
  '🤖 scikit-learn',
  '👁️ OpenCV',
  '🎯 YOLOv8',
  '🎙️ Whisper',
  '📓 Jupyter',
  '🤗 Transformers',
  '📈 Matplotlib',
]

/** Angka menghitung naik saat halaman dibuka — mis. "90 GB" naik dari 0 ke 90. */
function CountUp({ value }: { value: string }) {
  // Pisahkan bagian angka & satuannya: '90 GB' -> 90 + ' GB'; '24/7' -> 24 + '/7'.
  const m = /^(\d+)(.*)$/.exec(value)
  const target = m ? parseInt(m[1], 10) : 0
  const suffix = m ? m[2] : value
  const [n, setN] = useState(0)
  useEffect(() => {
    if (!m) {
      setN(target)
      return
    }
    const t0 = performance.now()
    const DURASI = 1400
    let raf = 0
    const tick = (t: number) => {
      const p = Math.min(1, (t - t0) / DURASI)
      setN(Math.round(target * (1 - Math.pow(1 - p, 3)))) // ease-out cubic
      if (p < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value])
  return (
    <>
      {m ? n : ''}
      {suffix}
    </>
  )
}

/** Sorotan cahaya di kartu mengikuti posisi kursor (diset lewat CSS var). */
function ikutiKursor(e: React.MouseEvent<HTMLDivElement>) {
  const r = e.currentTarget.getBoundingClientRect()
  e.currentTarget.style.setProperty('--mx', `${e.clientX - r.left}px`)
  e.currentTarget.style.setProperty('--my', `${e.clientY - r.top}px`)
}

export default function Landing() {
  const { user } = useAuth()
  const heroRef = useRef<HTMLDivElement>(null)
  const pindah = usePageTransition()

  // Parallax halus: latar gedung bergeser lebih lambat daripada konten saat scroll.
  useEffect(() => {
    const el = heroRef.current
    if (!el) return
    let raf = 0
    const onScroll = () => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => {
        el.style.transform = `translateY(${window.scrollY * 0.25}px) scale(1.1)`
      })
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      window.removeEventListener('scroll', onScroll)
      cancelAnimationFrame(raf)
    }
  }, [])

  if (user) return <Navigate to="/" replace />

  return (
    <div className="bg-white">
      {/* ===== HERO ===== */}
      <section className="relative flex min-h-screen flex-col overflow-hidden">
        {/* Latar gedung UNISMUH (parallax: digeser via ref saat scroll) */}
        <div
          ref={heroRef}
          className="absolute inset-0 scale-110 bg-cover bg-center blur-[6px] will-change-transform"
          style={{ backgroundImage: `url(${CAMPUS_BG})` }}
        />
        <div className="absolute inset-0 bg-gradient-to-br from-slate-950/90 via-slate-900/85 to-[#06122b]/92" />
        <div className="bg-grid-fade pointer-events-none absolute inset-0" />
        <ParticleField />
        <Meteors />
        <div className="blob pointer-events-none absolute -left-20 top-16 h-96 w-96 rounded-full bg-brand-500/30" />
        <div
          className="blob pointer-events-none absolute -right-16 top-1/4 h-[26rem] w-[26rem] rounded-full bg-emerald-500/25"
          style={{ animationDelay: '2.5s' }}
        />
        <div
          className="blob pointer-events-none absolute bottom-10 left-1/3 h-72 w-72 rounded-full bg-cyan-400/20"
          style={{ animationDelay: '4s' }}
        />
        <div
          className="blob pointer-events-none absolute -left-10 top-1/2 h-80 w-80 rounded-full bg-violet-500/20"
          style={{ animationDelay: '6s' }}
        />

        {/* Navbar atas */}
        <header className="relative z-10 flex items-center justify-between px-6 py-5 sm:px-10">
          <div className="flex items-center gap-3.5 text-white">
            <img
              src="/logos/teknik-biru.png"
              alt="Fakultas Teknik UNISMUH"
              className="h-20 w-20 object-contain"
            />
            <div>
              <p className="text-2xl font-bold leading-tight">UNISMUH ComputeHub</p>
              <p className="text-base text-white/60">Fakultas Teknik</p>
            </div>
          </div>
          <div className="flex items-center gap-2.5">
            <ThemeToggle variant="overlay" />
            <Link to="/login" onClick={(e) => pindah('/login', e)} className="btn-primary">
              Masuk
            </Link>
          </div>
        </header>

        {/* Konten hero */}
        <div className="relative z-10 flex flex-1 items-center justify-center px-6 py-10 text-center text-white">
          <div className="max-w-3xl">
            <span
              className="reveal relative mx-auto mb-7 grid h-40 w-40 place-items-center"
              style={{ '--d': '0s' } as React.CSSProperties}
            >
              <span
                className="ring-spin absolute -inset-3 rounded-full opacity-75 blur-lg"
                style={{
                  background:
                    'conic-gradient(from 0deg, #3385fc, #10b981, #06b6d4, #3385fc)',
                }}
              />
              <span className="absolute inset-3 rounded-full bg-brand-400/20 blur-2xl" />
              <img
                src="/logos/unismuh-seal.png"
                alt="Universitas Muhammadiyah Makassar"
                className="float-soft relative h-40 w-40 object-contain drop-shadow-2xl"
              />
            </span>

            <span
              className="reveal inline-flex items-center rounded-full bg-white/10 px-3 py-1 text-xs font-medium text-white/80 ring-1 ring-inset ring-white/20 backdrop-blur"
              style={{ '--d': '0.15s' } as React.CSSProperties}
            >
              Academic HPC Platform · Fakultas Teknik · Informatika
            </span>

            <h1
              className="reveal mt-4 text-4xl font-black leading-[1.15] sm:text-5xl"
              style={{ '--d': '0.25s' } as React.CSSProperties}
            >
              Komputasi <span className="gradient-text">Cerdas</span>
              <br />
              untuk <Typewriter />
            </h1>

            <p
              className="reveal mx-auto mt-5 max-w-2xl text-base leading-relaxed text-white/70"
              style={{ '--d': '0.4s' } as React.CSSProperties}
            >
              Infrastruktur komputasi berkinerja tinggi yang dirancang untuk
              mendukung penelitian, pembelajaran, kecerdasan buatan, dan inovasi
              digital di Fakultas Teknik Universitas Muhammadiyah Makassar.
            </p>

            <div
              className="reveal mt-8 flex items-center justify-center"
              style={{ '--d': '0.55s' } as React.CSSProperties}
            >
              <span className="relative inline-flex">
                {/* Cincin gradien berputar terus di belakang tombol utama */}
                <span
                  className="ring-spin absolute -inset-[3px] rounded-full opacity-80 blur-[3px]"
                  style={{
                    background:
                      'conic-gradient(from 0deg, transparent 20%, #3385fc 45%, #22d3ee 55%, transparent 80%)',
                  }}
                  aria-hidden="true"
                />
                <Link
                  to="/login"
                  onClick={(e) => pindah('/login', e)}
                  className="btn-primary relative px-7 py-3 text-base transition-transform duration-200 hover:scale-105 active:scale-95"
                >
                  Masuk ke Dashboard →
                </Link>
              </span>
            </div>

            {/* Angka unggulan */}
            <div className="mx-auto mt-10 grid max-w-3xl grid-cols-2 gap-3 sm:grid-cols-4">
              {[
                ['2×', 'NVIDIA L40S'],
                ['90 GB', 'VRAM total'],
                ['64', 'core CPU'],
                ['24/7', 'akses via SSO'],
              ].map(([num, label], i) => (
                <div
                  key={label}
                  onMouseMove={ikutiKursor}
                  className="reveal spotlight-card hover-lift rounded-2xl bg-white/5 px-4 py-4 ring-1 ring-white/10 backdrop-blur transition hover:bg-white/10 hover:ring-white/25"
                  style={{ '--d': `${0.65 + i * 0.1}s` } as React.CSSProperties}
                >
                  <p className="gradient-text text-2xl font-extrabold">
                    <CountUp value={num} />
                  </p>
                  <p className="mt-1 text-xs text-white/60">{label}</p>
                </div>
              ))}
            </div>

            {/* Fitur utama */}
            <div className="mx-auto mt-4 grid max-w-3xl gap-3 sm:grid-cols-3">
              {[
                [
                  '⚡ Notebook Interaktif',
                  'Kernel Python hidup di GPU ala Google Colab — variabel bertahan antar-sel, hasil langsung tampil.',
                ],
                [
                  '🛡️ Terisolasi & Adil',
                  'Tiap pengguna berjalan di container terpisah dengan kuota GPU harian — aman dan adil untuk semua.',
                ],
                [
                  '🔔 Selalu Terkabar',
                  'Job jalan di latar belakang walau laptop mati; selesai/gagal langsung dapat notifikasi & email.',
                ],
              ].map(([title, desc], i) => (
                <div
                  key={title}
                  onMouseMove={ikutiKursor}
                  className="reveal spotlight-card hover-lift rounded-2xl bg-white/5 px-4 py-4 text-left ring-1 ring-white/10 backdrop-blur transition hover:bg-white/10 hover:ring-white/25"
                  style={{ '--d': `${1.05 + i * 0.12}s` } as React.CSSProperties}
                >
                  <p className="text-sm font-bold text-white">{title}</p>
                  <p className="mt-1.5 text-xs leading-relaxed text-white/60">{desc}</p>
                </div>
              ))}
            </div>

            {/* Terminal hidup: mengetik & menjalankan kode training berulang */}
            <div
              className="reveal mx-auto mt-6 max-w-xl"
              style={{ '--d': '1.35s' } as React.CSSProperties}
            >
              <TerminalDemo />
            </div>

            {/* Marquee teknologi: bergerak terus, jeda saat disentuh kursor */}
            <div
              className="marquee reveal mx-auto mt-8 max-w-3xl"
              style={{ '--d': '1.5s' } as React.CSSProperties}
            >
              <div className="marquee-track">
                {[...TEKNOLOGI, ...TEKNOLOGI].map((t, i) => (
                  <span
                    key={`${t}-${i}`}
                    className="mr-3 inline-flex items-center whitespace-nowrap rounded-full bg-white/5 px-3.5 py-1.5 text-xs font-medium text-white/75 ring-1 ring-white/10 backdrop-blur"
                  >
                    {t}
                  </span>
                ))}
              </div>
            </div>

            <div className="mt-10 flex flex-wrap items-center justify-center gap-3">
              {LOGOS.map((l, i) => (
                <span
                  key={l.src}
                  className="reveal inline-block"
                  style={{ '--d': `${1.3 + i * 0.08}s` } as React.CSSProperties}
                >
                  {/* Kotak utuh yang mengambang (amplitudo kecil agar rapi),
                      bukan gambar di dalamnya — logo tak keluar dari kotak. */}
                  <span
                    className="keep-light float-soft grid h-14 w-14 place-items-center rounded-2xl bg-white shadow-md ring-1 ring-white/40 transition hover:-translate-y-1 hover:shadow-xl"
                    style={{ '--d': `${i * 0.35}s`, '--fy': '-5px', '--fs': '1.02' } as React.CSSProperties}
                  >
                    <img src={l.src} alt={l.alt} className="h-9 w-9 object-contain" />
                  </span>
                </span>
              ))}
            </div>

            <div
              className="reveal mt-8"
              style={{ '--d': '1.6s' } as React.CSSProperties}
            >
              <span className="scroll-cue text-2xl text-white/70" aria-hidden="true">
                ↓
              </span>
            </div>
          </div>
        </div>
      </section>

      <SiteFooter />
    </div>
  )
}
