import { Link, Navigate, useParams } from 'react-router-dom'

import ThemeToggle from '../components/ThemeToggle'

// Dokumen kebijakan (publik) — ditautkan dari footer situs. Konten disusun sebagai
// data agar satu komponen melayani tiga dokumen (route /legal/:doc).
type Block =
  | { h: string } // sub-judul seksi
  | { p: string } // paragraf
  | { ul: string[] } // daftar butir

type LegalDoc = {
  slug: string
  title: string
  intro: string
  blocks: Block[]
}

const UPDATED = '24 Juli 2026'
const CONTACT = 'Admin ComputeHub'

const DOCS: Record<string, LegalDoc> = {
  privasi: {
    slug: 'privasi',
    title: 'Kebijakan Privasi',
    intro:
      'Kebijakan ini menjelaskan data apa yang kami kumpulkan saat Anda memakai UNISMUH ComputeHub, untuk apa data itu dipakai, dan bagaimana kami menjaganya.',
    blocks: [
      { h: '1. Data yang Kami Kumpulkan' },
      {
        ul: [
          'Data akun: nama, email/NIM, username, dan peran (mahasiswa/dosen/admin) — diberikan oleh administrator kampus.',
          'Data aktivitas: riwayat job, penggunaan GPU/CPU, kuota harian, log sesi, dan alamat IP saat login (untuk keamanan).',
          'File kerja Anda: berkas yang Anda simpan di penyimpanan pribadi (/persist), notebook, dan paket yang Anda pasang.',
          'Preferensi: tema tampilan (terang/gelap) yang disimpan di peramban Anda.',
        ],
      },
      { h: '2. Tujuan Penggunaan Data' },
      {
        ul: [
          'Mengautentikasi Anda dan mengamankan akun.',
          'Mengalokasikan sumber daya GPU/CPU dan menegakkan kuota yang adil bagi semua pengguna.',
          'Menampilkan riwayat pekerjaan, statistik, dan notifikasi (mis. job selesai/gagal).',
          'Mendeteksi penyalahgunaan dan menjaga kestabilan layanan bersama.',
        ],
      },
      { h: '3. Penyimpanan & Keamanan' },
      {
        p: 'Data dan file Anda disimpan di server kampus (Fakultas Teknik UNISMUH). Setiap pekerjaan berjalan dalam kontainer terisolasi sehingga file dan paket satu pengguna tidak dapat diakses pengguna lain. Cadangan (backup) data dienkripsi. Kami menerapkan pembatasan akses berbasis peran.',
      },
      { h: '4. Berbagi Data' },
      {
        p: 'Kami TIDAK menjual atau menyewakan data pribadi Anda kepada pihak mana pun. Data hanya diakses oleh administrator yang berwenang untuk keperluan pengelolaan layanan, atau bila diwajibkan oleh peraturan kampus/hukum yang berlaku.',
      },
      { h: '5. Layanan Pihak Ketiga' },
      {
        p: 'Bila Anda menggunakan fitur yang terhubung ke layanan luar (mis. clone/push repositori GitHub, unduh dataset), interaksi tersebut tunduk pada kebijakan privasi layanan bersangkutan. Token atau kredensial yang Anda masukkan disimpan di penyimpanan pribadi Anda sendiri dan tidak dibagikan.',
      },
      { h: '6. Hak Anda' },
      {
        ul: [
          'Meminta salinan data akun Anda.',
          'Meminta koreksi data yang keliru.',
          'Mengunduh atau menghapus file di penyimpanan pribadi Anda kapan saja.',
          'Meminta penonaktifan/penghapusan akun melalui administrator lab.',
        ],
      },
      { h: '7. Perubahan Kebijakan' },
      {
        p: 'Kebijakan ini dapat diperbarui sewaktu-waktu. Tanggal pembaruan terakhir tercantum di bagian atas halaman ini.',
      },
    ],
  },
  ketentuan: {
    slug: 'ketentuan',
    title: 'Syarat & Ketentuan',
    intro:
      'Dengan mengakses dan menggunakan UNISMUH ComputeHub, Anda menyetujui syarat dan ketentuan berikut.',
    blocks: [
      { h: '1. Kelayakan & Akun' },
      {
        ul: [
          'Layanan diperuntukkan bagi civitas akademika Universitas Muhammadiyah Makassar (mahasiswa, dosen, dan staf) yang berkepentingan akademik.',
          'Akun dibuat oleh administrator. Anda bertanggung jawab menjaga kerahasiaan kata sandi dan seluruh aktivitas pada akun Anda.',
          'Satu akun untuk satu orang. Dilarang membagikan akun kepada pihak lain.',
        ],
      },
      { h: '2. Penggunaan yang Wajar' },
      {
        p: 'Sumber daya GPU/CPU dipakai bersama. Gunakan seperlunya sesuai kuota, dan hindari menahan sumber daya tanpa komputasi nyata (mis. menjalankan loop kosong hanya untuk memesan GPU).',
      },
      { h: '3. Larangan' },
      {
        ul: [
          'Penambangan kripto (crypto-mining) dalam bentuk apa pun.',
          'Menjalankan atau menyebarkan malware, serangan jaringan, atau upaya meretas sistem/pengguna lain.',
          'Memproses data ilegal, melanggar hak cipta, atau melanggar etika akademik.',
          'Berupaya menembus isolasi kontainer, meningkatkan hak akses, atau mengganggu pengguna lain.',
          'Menggunakan layanan untuk tujuan komersial di luar kepentingan akademik tanpa izin.',
        ],
      },
      { h: '4. Data & Cadangan' },
      {
        p: 'Anda bertanggung jawab atas data dan hasil kerja Anda. Meskipun kami melakukan pencadangan berkala, kami menganjurkan Anda menyimpan salinan pekerjaan penting Anda sendiri (mis. ke repositori atau penyimpanan pribadi).',
      },
      { h: '5. Ketersediaan Layanan' },
      {
        p: 'Layanan disediakan "sebagaimana adanya" (as is). Dapat terjadi pemeliharaan terjadwal, gangguan, atau perubahan fitur. Kami berupaya menjaga ketersediaan namun tidak menjamin layanan bebas gangguan.',
      },
      { h: '6. Penangguhan Akun' },
      {
        p: 'Pelanggaran terhadap ketentuan ini dapat mengakibatkan pembatasan kuota, penangguhan, atau penghapusan akun, sesuai kebijakan pengelola dan peraturan kampus.',
      },
      { h: '7. Kekayaan Intelektual' },
      {
        p: 'Kode, model, dan hasil karya yang Anda buat tetap menjadi milik Anda. Anda memberi izin kepada pengelola untuk menyimpan dan memproses berkas tersebut sebatas yang diperlukan untuk menjalankan layanan.',
      },
    ],
  },
  cookie: {
    slug: 'cookie',
    title: 'Kebijakan Cookie',
    intro:
      'Halaman ini menjelaskan penggunaan cookie dan penyimpanan lokal (local storage) di UNISMUH ComputeHub.',
    blocks: [
      { h: '1. Apa yang Kami Simpan di Peramban' },
      {
        ul: [
          'Token sesi login — agar Anda tetap masuk selama memakai aplikasi. Disimpan di penyimpanan lokal peramban Anda.',
          'Preferensi tampilan — pilihan tema terang/gelap.',
          'Catatan tampilan sementara — mis. status panel yang Anda tutup, agar pengalaman konsisten.',
        ],
      },
      { h: '2. Yang TIDAK Kami Lakukan' },
      {
        p: 'Kami tidak menggunakan cookie iklan, pelacak lintas-situs, atau analitik pihak ketiga untuk tujuan komersial. Penyimpanan lokal hanya dipakai agar aplikasi berfungsi.',
      },
      { h: '3. Mengelola Cookie' },
      {
        p: 'Anda dapat menghapus penyimpanan lokal melalui pengaturan peramban Anda kapan saja. Perlu diketahui, menghapus token sesi akan membuat Anda keluar (logout) dan harus masuk kembali.',
      },
      { h: '4. Kontak' },
      {
        p: `Pertanyaan seputar cookie dapat diajukan ke ${CONTACT}.`,
      },
    ],
  },
}

function Doc({ doc }: { doc: LegalDoc }) {
  return (
    <article className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-slate-800 dark:text-slate-100 sm:text-3xl">
          {doc.title}
        </h1>
        <p className="mt-1 text-xs text-slate-400">Terakhir diperbarui: {UPDATED}</p>
      </div>
      <p className="text-sm leading-relaxed text-slate-600 dark:text-slate-300">{doc.intro}</p>
      <div className="space-y-4">
        {doc.blocks.map((b, i) =>
          'h' in b ? (
            <h2
              key={i}
              className="pt-1 text-base font-bold text-slate-800 dark:text-slate-100"
            >
              {b.h}
            </h2>
          ) : 'p' in b ? (
            <p key={i} className="text-sm leading-relaxed text-slate-600 dark:text-slate-300">
              {b.p}
            </p>
          ) : (
            <ul
              key={i}
              className="list-disc space-y-1.5 pl-5 text-sm leading-relaxed text-slate-600 dark:text-slate-300"
            >
              {b.ul.map((li, j) => (
                <li key={j}>{li}</li>
              ))}
            </ul>
          ),
        )}
      </div>
      <div className="rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-600 ring-1 ring-inset ring-slate-200 dark:bg-slate-800/60 dark:text-slate-300 dark:ring-slate-700">
        Ada pertanyaan? Hubungi kami di{' '}
        <a href={`mailto:${CONTACT}`} className="font-semibold text-brand-600 hover:underline">
          {CONTACT}
        </a>
        .
      </div>
    </article>
  )
}

const TABS = [
  { slug: 'privasi', label: 'Kebijakan Privasi' },
  { slug: 'ketentuan', label: 'Syarat & Ketentuan' },
  { slug: 'cookie', label: 'Kebijakan Cookie' },
]

export default function Legal() {
  const { doc } = useParams()
  const active = doc && DOCS[doc] ? DOCS[doc] : null
  if (!active) return <Navigate to="/legal/privasi" replace />

  return (
    <div className="min-h-screen bg-white dark:bg-slate-950">
      {/* Header ringkas */}
      <header className="border-b border-slate-200 dark:border-slate-800">
        <div className="mx-auto flex max-w-4xl items-center justify-between px-6 py-4">
          <Link to="/welcome" className="flex items-center gap-2.5">
            <img src="/logos/teknik-merah.png" alt="" className="h-9 w-9 object-contain" />
            <div>
              <p className="font-bold text-slate-800 dark:text-slate-100">UNISMUH ComputeHub</p>
              <p className="text-[11px] uppercase tracking-wide text-slate-400">
                Sistem Komputasi Terpadu
              </p>
            </div>
          </Link>
          <div className="flex items-center gap-2.5">
            <ThemeToggle />
            <Link to="/welcome" className="btn-ghost text-sm">
              ← Beranda
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-6 py-8">
        {/* Tab dokumen */}
        <nav className="mb-8 flex flex-wrap gap-2">
          {TABS.map((t) => (
            <Link
              key={t.slug}
              to={`/legal/${t.slug}`}
              className={
                t.slug === active.slug
                  ? 'rounded-full bg-brand-600 px-4 py-1.5 text-sm font-semibold text-white'
                  : 'rounded-full bg-slate-100 px-4 py-1.5 text-sm font-medium text-slate-600 transition hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700'
              }
            >
              {t.label}
            </Link>
          ))}
        </nav>

        <Doc doc={active} />

        <p className="mt-10 border-t border-slate-200 pt-5 text-xs text-slate-400 dark:border-slate-800">
          © {new Date().getFullYear()} UNISMUH ComputeHub · Fakultas Teknik · Universitas
          Muhammadiyah Makassar
        </p>
      </main>
    </div>
  )
}
