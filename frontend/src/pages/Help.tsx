import type { ReactNode } from 'react'

import { IconHelp } from '../components/icons'
import { useAuth } from '../lib/auth'

const DOMAIN = 'https://computehub.lab.if.unismuh.ac.id/'

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="card card-pad space-y-3">
      <h2 className="text-base font-bold text-slate-800">{title}</h2>
      <div className="space-y-2 text-sm leading-relaxed text-slate-600">{children}</div>
    </section>
  )
}

function Code({ children }: { children: ReactNode }) {
  return (
    <code className="rounded bg-slate-100 px-1 py-0.5 text-[12px] text-slate-700">
      {children}
    </code>
  )
}

function Row({ k, v }: { k: ReactNode; v: ReactNode }) {
  return (
    <tr className="border-b border-slate-100 last:border-0">
      <td className="w-52 py-1.5 pr-3 align-top font-medium text-slate-700">{k}</td>
      <td className="py-1.5 align-top text-slate-600">{v}</td>
    </tr>
  )
}

export default function Help() {
  const { user } = useAuth()
  const isStudent = user?.role === 'mahasiswa'
  const isAdmin = user?.role === 'admin' // role 'admin' sudah mencakup super admin

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      {/* Hero */}
      <div className="flex items-center gap-3">
        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-sky-500 to-indigo-500 text-white shadow">
          <IconHelp className="h-6 w-6" />
        </span>
        <div>
          <h1 className="text-lg font-bold text-slate-800">Bantuan &amp; Panduan</h1>
          <p className="text-sm text-slate-500">
            Semua yang perlu kamu tahu untuk memakai UNISMUH ComputeHub.
          </p>
        </div>
        <a
          href="/panduan-mahasiswa.pdf"
          download
          className="ml-auto inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-brand-50 px-3 py-1.5 text-xs font-semibold text-brand-700 ring-1 ring-inset ring-brand-600/20 transition hover:bg-brand-100"
        >
          ⤓ Unduh Panduan (PDF)
        </a>
      </div>

      <Section title="Mulai cepat">
        <ul className="list-disc space-y-1 pl-5">
          <li>
            Akses lewat <b>{DOMAIN}</b> — bisa dari dalam maupun luar jaringan kampus.
          </li>
          <li>
            Login dengan <b>username &amp; password</b> dari admin. Ganti password lewat
            menu profil (ikon kunci di sidebar).
          </li>
          <li>
            Server: <b>2× NVIDIA L40S 46&nbsp;GB</b>. Setiap pekerjaan berjalan{' '}
            <b>terisolasi</b> di container milikmu sendiri (data &amp; paket tak tercampur
            antar-user).
          </li>
        </ul>
      </Section>

      <Section title="GPU atau CPU? Kapan pakai apa">
        <p>
          Saat submit job kamu memilih <b>Perangkat komputasi: GPU atau CPU</b>. Pilih
          sesuai jenis pekerjaan:
        </p>
        <table className="w-full">
          <tbody>
            <Row
              k="Pakai GPU (CUDA)"
              v={
                <>
                  Deep learning (PyTorch/TensorFlow), training neural network / CNN / RNN,
                  LLM &amp; transformers, computer vision, diffusion / image-gen, dan
                  operasi matriks/tensor besar.
                </>
              }
            />
            <Row
              k="Pakai CPU"
              v={
                <>
                  scikit-learn (<b>Random Forest</b>, SVM, KNN, decision tree), pandas /
                  numpy, pengolahan &amp; analisis data, statistik, atau algoritma yang tak
                  mendukung CUDA, dan data kecil.
                </>
              }
            />
          </tbody>
        </table>
        <div className="rounded-lg bg-emerald-50 px-3 py-2 text-emerald-800 ring-1 ring-inset ring-emerald-600/15">
          ✅ <b>Memilih CPU TIDAK akan ditolak.</b> Untuk pekerjaan CPU (mis. Random
          Forest), pilih device <b>CPU</b> — job tetap jalan tanpa perlu GPU. Kalau memaksa
          GPU untuk kode yang CPU-only, GPU dialokasikan tapi menganggur (mubazir).
        </div>
        <p className="text-xs text-slate-500">
          Catatan: Random Forest &amp; sklearn memang <b>tidak</b> memakai GPU — jalannya di
          CPU.
        </p>
      </Section>

      <Section title="Versi Python (3.10 – 3.13)">
        <p>
          Setiap job &amp; notebook interaktif bisa memilih <b>versi Python</b>:{' '}
          <b>3.10 (default)</b>, 3.11, 3.12, atau 3.13. Pilihannya ada di{' '}
          <b>form Submit Job</b> (di bawah nama job) dan di <b>toolbar notebook
          interaktif</b> (dropdown — terkunci selama kernel hidup; matikan kernel dulu
          untuk berganti versi).
        </p>
        <ul className="list-disc space-y-1 pl-5">
          <li>
            <b>Semua versi berisi library lengkap yang sama</b>: PyTorch (CUDA),
            TensorFlow, scikit-learn, transformers, ultralytics/YOLO, pandas, OpenCV,
            dan ratusan lainnya — tidak perlu install ulang.
          </li>
          <li>
            Python <b>3.13</b> memakai <b>PyTorch 2.6 (CUDA 12.4)</b> yang lebih baru;
            versi lain memakai PyTorch 2.5.1 (CUDA 12.1).
          </li>
          <li>
            Paket yang kamu <code>pip install</code> tersimpan per-versi Python di
            workspace pribadimu — instalasi di 3.10 tidak memengaruhi sesi 3.13.
          </li>
          <li>
            Ragu pilih yang mana? Pakai <b>3.10 (default)</b> — paling teruji. Pilih
            versi lain hanya bila kodemu butuh fitur Python/torch yang lebih baru.
          </li>
        </ul>
      </Section>

      <Section title="Presisi komputasi di NVIDIA L40S (FP32 / TF32 / FP16 / FP8)">
        <p>
          L40S mendukung beberapa tingkat presisi. Makin rendah presisi → makin{' '}
          <b>cepat &amp; hemat VRAM</b>, tapi sedikit kurang akurat. Untuk deep learning:
        </p>
        <table className="w-full">
          <tbody>
            <Row
              k="FP32 · 91,6 TFLOPS"
              v={
                <>
                  Presisi penuh — paling akurat, paling lambat. <b>Default</b>. Untuk
                  perhitungan yang butuh akurasi tinggi atau saat debugging.
                </>
              }
            />
            <Row
              k="TF32 · 366 TFLOPS"
              v={
                <>
                  Hampir seakurat FP32 tapi jauh lebih cepat untuk matmul. Aktifkan di
                  PyTorch:{' '}
                  <Code>torch.backends.cuda.matmul.allow_tf32 = True</Code>. Cocok untuk
                  training umum.
                </>
              }
            />
            <Row
              k="FP16 / mixed precision · 733 TFLOPS"
              v={
                <>
                  Setengah presisi — training &amp; inference <b>jauh lebih cepat + hemat
                  VRAM</b>. Pakai <Code>torch.cuda.amp.autocast()</Code> (AMP). Standar
                  modern untuk model besar.
                </>
              }
            />
            <Row
              k="FP8 · 1.466 TFLOPS"
              v={
                <>
                  Presisi sangat rendah — inference LLM sangat cepat. Perlu library khusus
                  (mis. Transformer Engine). Untuk inference / produksi model besar
                  (tingkat lanjut).
                </>
              }
            />
          </tbody>
        </table>
        <p className="text-xs text-slate-500">
          Rekomendasi umum: mulai dengan <b>FP32/TF32</b> saat pengembangan, lalu{' '}
          <b>FP16 (AMP)</b> untuk mempercepat training bila model besar / terasa lambat.
        </p>
      </Section>

      <Section title="Batch vs Interaktif — mana yang jalan walau laptop mati?">
        <table className="w-full">
          <tbody>
            <Row
              k="Job Batch (Daftar Job → Submit Job)"
              v={
                <>
                  Masuk <b>antrian</b>, dikerjakan <b>server</b>.{' '}
                  <b>✅ Tetap jalan walau laptop dimatikan.</b> Hasil diambil kapan saja
                  nanti.
                </>
              }
            />
            <Row
              k="Notebook Interaktif (menu Submit)"
              v={
                <>
                  Kernel live ala Colab (lihat hasil langsung, ubah sel).{' '}
                  <b>Butuh browser tetap terbuka</b>; kernel auto-mati setelah 30 menit
                  idle.
                </>
              }
            />
          </tbody>
        </table>
        <p>
          Jadi kalau mau <b>“submit lalu ditinggal (laptop dimatikan)”</b> → pakai{' '}
          <b>Job Batch</b>, bukan notebook interaktif.
        </p>
      </Section>

      <Section title="Menjalankan / render notebook (.ipynb) lama">
        <ol className="list-decimal space-y-1 pl-5">
          <li>
            Buka <b>Daftar Job</b> → klik tombol <b>Submit Job</b>.
          </li>
          <li>
            Pilih sumber <b>Notebook (.ipynb)</b> → unggah file-nya.
          </li>
          <li>
            Pilih device (GPU/CPU) lalu <b>Submit</b>. Job masuk antrian.
          </li>
          <li>
            Laptop boleh dimatikan. Setelah selesai, buka detail job → unduh{' '}
            <b>notebook_executed.ipynb</b> (lengkap dengan output).
          </li>
        </ol>
      </Section>

      <Section title="Penyimpanan (workspace /persist)">
        <ul className="list-disc space-y-1 pl-5">
          <li>
            Setiap user punya workspace pribadi (menu <b>Penyimpanan</b>) yang{' '}
            <b>persisten</b> — file &amp; paket <Code>pip install --user</Code> tetap ada
            antar-sesi.
          </li>
          <li>
            Kuota default <b>30&nbsp;GB</b> per user. Ada peringatan email di 90%; di 100%
            job/sesi baru ditolak sampai kamu menghapus sebagian file.
          </li>
          <li>Data antar-user terisolasi — kamu tak bisa melihat file user lain.</li>
        </ul>
      </Section>

      {isStudent && (
        <Section title="Kuota GPU harian (mahasiswa)">
          <p>
            Pemakaian GPU mahasiswa dibatasi per 24 jam (rolling). Sisa kuota tampil di
            halaman <b>Daftar Job</b>. Kalau habis, job GPU baru menunggu sampai kuota
            pulih — kamu tetap bisa memakai <b>CPU</b>.
          </p>
        </Section>
      )}

      <Section title="Peringatan otomatis (email)">
        {isAdmin ? (
          <p>
            Email peringatan otomatis dikirim ke <b>user terkait, semua admin, dan super
            admin</b> bila ada pelanggaran batas (penyimpanan hampir penuh, pemakaian
            resource berlebih, dll). Sebagai admin, <b>kamu menerima semua peringatan</b>{' '}
            otomatis — tak perlu menambahkan email penerima.
          </p>
        ) : (
          <p>
            Bila pemakaianmu mendekati atau melewati batas (mis. penyimpanan hampir
            penuh), kamu akan <b>diberi tahu lewat email otomatis</b>. Kamu tak perlu
            menyetel apa pun.
          </p>
        )}
      </Section>

      {isAdmin && (
        <Section title="Untuk Admin & Super Admin">
          <ul className="list-disc space-y-1 pl-5">
            <li>
              <b>Pengguna</b> — buat akun (username &amp; password dibuat otomatis + dikirim
              ke email user), reset password, aktif/nonaktif, hapus, dan atur{' '}
              <b>kebijakan per-user</b> (kuota GPU harian, penyimpanan, RAM/VRAM, thread
              CPU).
            </li>
            <li>
              <b>Laporan</b> — pemakaian resource per akun &amp; per user OS; unduh
              HTML/PDF.
            </li>
            <li>
              <b>Peringatan</b> — atur ambang CPU/RAM/VRAM/disk, aktif/nonaktif email,
              kirim email uji.
            </li>
            <li>
              <b>Monitor</b> — grafik CPU/RAM/GPU real-time seluruh server.
            </li>
            <li>
              <b>Pengaturan platform</b> (enforce GPU, kuota default, batas per-peran) —
              sebagian <b>khusus super admin</b>.
            </li>
          </ul>
        </Section>
      )}

      <Section title="Masalah umum">
        <ul className="list-disc space-y-1 pl-5">
          <li>
            <b>“Preflight GPU gagal / CPU tidak diizinkan”</b> → kamu memilih device{' '}
            <b>GPU</b> tapi GPU sedang penuh / tak terlihat. Untuk kode CPU-only
            (RF/sklearn), pilih device <b>CPU</b>.
          </li>
          <li>
            <b>Notebook berhenti sendiri</b> → sesi interaktif mati setelah 30 menit idle
            atau maksimal 2 jam. Untuk pekerjaan panjang, pakai <b>Job Batch</b>.
          </li>
          <li>
            <b>Job “antri” lama</b> → GPU sedang dipakai; job jalan otomatis saat GPU bebas
            (diurus server, laptop boleh mati).
          </li>
        </ul>
      </Section>
    </div>
  )
}
