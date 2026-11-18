import { lazy, Suspense, type ReactNode } from 'react'

import { IconHelp } from '../components/icons'
import { useAuth } from '../lib/auth'

// Lazy: chat panduan hanya dimuat saat halaman Bantuan dibuka.
const HelpAssistant = lazy(() => import('../components/HelpAssistant'))

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
      {/* Asisten Panduan — tanya-jawab khusus cara pakai platform */}
      <Suspense fallback={<div className="card h-24 animate-pulse bg-slate-100" />}>
        <HelpAssistant />
      </Suspense>
      <Section title="Mulai cepat">
        <ul className="list-disc space-y-1 pl-5">
          <li>
            Akses lewat <b>{DOMAIN}</b> — bisa dari dalam maupun luar jaringan kampus.
          </li>
          <li>
            Masuk dengan <b>SSO Unismuh</b> (akun kampus). Akun lokal (username &amp;
            password) hanya untuk akun yang dibuatkan admin; ganti password lewat menu{' '}
            <b>Profil</b>.
          </li>
          <li>
            Belum punya akun kampus? Masuk dengan <b>Google pribadi</b> lewat{' '}
            <a href="/welcome/user" className="underline">/welcome/user</a>. Dashboard
            langsung bisa dipakai; fitur lain terbuka setelah kamu mengirim{' '}
            <b>Minta Akses</b> dan admin menyetujuinya.
          </li>
          <li>
            Server: <b>2× NVIDIA L40S 48&nbsp;GB</b>. Setiap pekerjaan berjalan{' '}
            <b>terisolasi</b> di container milikmu sendiri (data &amp; paket tak tercampur
            antar-user).
          </li>
        </ul>
      </Section>

      <Section title="GPU otomatis — tidak perlu memilih GPU atau CPU">
        <ul className="list-disc space-y-1 pl-5">
          <li>
            Semua <b>job, notebook, dan Devbox otomatis mendapat GPU</b>. Kamu tidak perlu
            memilih perangkat lagi.
          </li>
          <li>
            Kode yang <b>tidak memakai CUDA</b> (scikit-learn, Random Forest, pandas, statistik,
            scraping) tetap berjalan normal di CPU dan <b>tidak memakai VRAM maupun kuota
            GPU</b>.
          </li>
          <li>
            Slot GPU dan kuota harian dihitung dari <b>pemakaian VRAM nyata</b>, bukan dari GPU
            yang sekadar dipegang. TensorFlow dan JAX hanya mengambil VRAM sesuai kebutuhan.
          </li>
          <li>
            Bila GPU sedang penuh, job menunggu di antrean. Job yang menunggu{' '}
            <b>lebih dari 10 menit</b> dijalankan tanpa GPU — cek{' '}
            <Code>torch.cuda.is_available()</Code> di log bila training terasa lambat.
          </li>
          <li>
            Selama menunggu, <b>Daftar Job</b> dan detail job menampilkan posisi antrean,{' '}
            <b>perkiraan kapan mulai</b>, dan alasannya: GPU penuh, menunggu jadwal, kuota
            harian habis, atau menunggu job/Devbox milikmu yang lain selesai. Perkiraan
            dihitung dari riwayat durasi job, jadi bisa sedikit meleset.
          </li>
          <li>
            Pengguna yang diberi izin admin bisa memilih <b>2 GPU (eksklusif)</b> untuk model
            yang tidak muat di satu GPU / DDP. Job ini menunggu sampai kedua GPU kosong.
          </li>
        </ul>
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
          <li>
            Memakai <b>Keras</b>? Pilih <b>Python 3.11 ke atas</b>. Keras versi
            terbaru (dengan perbaikan keamanan) tidak tersedia untuk Python 3.10.
          </li>
        </ul>
      </Section>

      <Section title="Keamanan file & model">
        <p>
          Library di ComputeHub diperbarui berkala untuk menutup celah keamanan.
          Sebagian besar celah hanya terpicu saat kodemu membuka file yang sengaja
          dibuat berbahaya, jadi biasakan:
        </p>
        <ul className="list-disc space-y-1 pl-5">
          <li>
            Muat model (<code>.keras</code>, <code>.h5</code>, <code>.pkl</code>,{' '}
            <code>.pt</code>, checkpoint), dataset, dan PDF <b>hanya dari sumber
            tepercaya</b> (mis. akun resmi di Hugging Face, situs penerbit, dosenmu).
          </li>
          <li>
            Hindari <code>pickle</code>/<code>torch.load</code> pada file dari orang
            tak dikenal; untuk Keras jangan matikan <code>safe_mode</code>.
          </li>
          <li>
            Job &amp; notebook baru otomatis memakai versi library terbaru — tidak
            perlu install ulang.
          </li>
        </ul>
      </Section>

      <Section title="Asisten AI — copilot koding di notebook">
        <p>
          Panel <b>Asisten AI</b> di sisi kanan notebook membaca isi sel dan pesan error
          asli, lalu memperbaikinya. Ia juga tahu library dan model yang terpasang di
          server.
        </p>
        <ul className="list-disc space-y-1 pl-5">
          <li>
            Tombol <b>Terapkan</b> menimpa sel aktif dengan kode dari AI; <b>Sel baru</b>{' '}
            menambahkannya di bawah.
          </li>
          <li>
            <b>Gambar</b> — lampirkan, tempel (Ctrl+V), atau seret screenshot error/plot untuk
            dianalisis.
          </li>
          <li>
            <b>Dokumen</b> — tombol klip 📎 untuk melampirkan PDF, Word, Excel, PowerPoint,
            CSV, dll. (maks. 3 dokumen per pesan), lalu minta diringkas atau tanyakan isinya.
            Dokumen hanya dibaca untuk percakapan itu, <b>tidak disimpan</b> di server.
            Dokumen yang sangat panjang dibaca sebagian.
          </li>
          <li>
            <b>Cari di web</b> — aktifkan tombol globe 🌐 untuk pertanyaan tentang informasi
            terbaru (rilis library, dokumentasi). Jawaban mencantumkan <b>daftar sumber</b>{' '}
            bernomor yang bisa diklik. Prosesnya lebih lambat (±5–25 detik).
          </li>
          <li>
            Bot di <b>halaman Bantuan</b> ini khusus menjawab cara memakai ComputeHub dan
            merujuk isi panduan resmi. Untuk pertanyaan kode, pakai Asisten AI di notebook.
          </li>
        </ul>
        <div className="rounded-lg bg-emerald-50 px-3 py-2 text-emerald-800 ring-1 ring-inset ring-emerald-600/15">
          💡 Jalankan dulu sel yang error, lalu tanya <i>"perbaiki error di sel 2"</i> —
          asisten membaca traceback aslinya sehingga jawabannya tepat sasaran.
        </div>
      </Section>

      <Section title="Tanya Dokumen — tanya isi skripsi, jurnal, atau modulmu">
        <p>
          Menu <b>Tanya Dokumen</b> adalah pustaka dokumen pribadi. Unggah PDF, Word,
          PowerPoint, Excel, OpenDocument, atau teks (TXT/MD/CSV/JSON/HTML/TeX), lalu tanyakan
          isinya. Berbeda dengan lampiran di Asisten AI notebook, dokumen di sini{' '}
          <b>disimpan</b> dan bisa ditanya kapan saja.
        </p>
        <ul className="list-disc space-y-1 pl-5">
          <li>
            Berkas asli tersimpan di folder <Code>/persist/Dokumen-AI</Code> dan memakai kuota
            penyimpananmu. Tidak ada batas jumlah atau ukuran selain sisa kuota itu.
          </li>
          <li>
            Setelah diunggah, status dokumen berjalan <b>Antre → Diproses → Siap</b>. Dokumen
            besar atau hasil pindaian bisa butuh beberapa menit. Bila <b>Gagal</b>, baca
            pesannya lalu tekan <b>Proses ulang</b>.
          </li>
          <li>
            Jawaban hanya diambil dari dokumenmu sendiri dan mencantumkan sumber{' '}
            <b>[D1], [D2], …</b> (nama berkas dan bagiannya). Pengguna lain tidak bisa melihat
            atau mencari dokumenmu.
          </li>
          <li>
            Centang dokumen tertentu untuk membatasi pertanyaan hanya ke dokumen itu; tanpa
            centang, semua dokumen yang siap ikut dicari.
          </li>
          <li>
            Menaruh atau menghapus berkas langsung di folder <Code>Dokumen-AI</Code> (lewat
            Penyimpanan, notebook, atau Devbox) juga terdeteksi saat halaman dibuka. Hapus dari
            halaman ini memindahkan berkas ke <b>Tempat Sampah</b> (bisa dipulihkan 7 hari).
          </li>
        </ul>
        <div className="rounded-lg bg-amber-50 px-3 py-2 text-amber-800 ring-1 ring-inset ring-amber-600/15">
          ⚠️ Jawaban AI bisa keliru. Selalu cek kembali ke dokumen asli lewat sumber yang
          dicantumkan, terutama untuk kutipan di karya ilmiah.
        </div>
      </Section>

      <Section title="Template siap-jalan, library lengkap & model bersama">
        <p>
          Menu <b>Template</b> (sidebar, bagian Submit) berisi <b>contoh notebook
          siap-jalan</b>: transkripsi audio Whisper, OCR dokumen Indonesia, NLP
          IndoBERT, deteksi objek YOLO, prediksi time-series, dan uji statistik
          ANOVA. Klik kartu → notebook terbuka lengkap dengan penjelasan — tinggal
          tekan Run, lalu ganti data contohnya dengan datamu.
        </p>
        <ul className="list-disc space-y-1 pl-5">
          <li>
            <b>Library sudah terpasang</b> — cek dulu sebelum <code>pip install</code>.
            Selain paket ML standar, tersedia juga: <code>faster-whisper</code>{' '}
            (speech-to-text), <code>easyocr</code> &amp; <code>pytesseract</code> (OCR,
            termasuk bahasa Indonesia), <code>pdf2image</code>, <code>pmdarima</code>{' '}
            &amp; <code>sktime</code> (time-series), <code>pingouin</code> (statistik ala
            SPSS), <code>duckdb</code> (SQL super cepat ke CSV/Parquet), serta metrik
            NLP (<code>evaluate</code>, <code>rouge-score</code>, <code>sacrebleu</code>,{' '}
            <code>jiwer</code>).
          </li>
          <li>
            <b>Model pre-trained bersama</b> tersedia di <code>/opt/ch-models</code>{' '}
            (read-only): Whisper small &amp; large-v3, IndoBERT, sentence-transformer
            multibahasa, YOLOv8, dan model EasyOCR — <b>langsung pakai tanpa
            download</b>, tidak memakan kuota penyimpananmu.
          </li>
          <li>
            Tanya <b>Asisten AI</b> di notebook — ia tahu persis library &amp; model apa
            saja yang tersedia di server dan memberi contoh kode pemakaiannya.
          </li>
        </ul>
      </Section>

      <Section title="Web scraping — ambil data dari internet">
        <p>
          Server ini <b>bisa mengakses internet</b>, jadi kamu boleh mengambil data
          dari situs web. Library-nya sudah terpasang, tinggal <code>import</code>:
        </p>
        <ul className="ml-5 list-disc space-y-1.5">
          <li>
            <b>Halaman biasa</b> — <code>requests</code> + <code>BeautifulSoup</code>{' '}
            (<code>bs4</code>) + <code>lxml</code>. Ini yang paling sering dipakai.
          </li>
          <li>
            <b>Halaman ber-JavaScript</b> (isinya muncul setelah dirender) —{' '}
            <code>playwright</code> atau <code>selenium</code>. Chromium sudah
            disiapkan di server, tidak perlu instal browser.
          </li>
          <li>
            <b>Crawler banyak halaman</b> — <code>scrapy</code>. Untuk RSS/berita:{' '}
            <code>feedparser</code>.
          </li>
          <li>
            <b>Sopan saat gagal</b> — <code>tenacity</code> untuk mengulang dengan
            jeda bertambah, bukan menghantam terus-menerus.
          </li>
        </ul>
        <pre className="mt-3 overflow-x-auto rounded-lg bg-slate-900 p-3 text-xs leading-relaxed text-slate-100">
{`import requests, time
from bs4 import BeautifulSoup

HEAD = {"User-Agent": "Riset Unismuh (nim@student.unismuh.ac.id)"}

for hal in range(1, 6):
    r = requests.get(f"https://contoh.com/?page={hal}", headers=HEAD, timeout=15)
    r.raise_for_status()
    sup = BeautifulSoup(r.text, "lxml")
    print(hal, sup.title.string)
    time.sleep(2)          # jeda: jangan hantam server orang`}
        </pre>
        <p className="mt-3">
          Untuk situs ber-JavaScript, pakai Playwright dengan{' '}
          <code>args=[&quot;--no-sandbox&quot;]</code> (wajib di dalam container):
        </p>
        <pre className="mt-2 overflow-x-auto rounded-lg bg-slate-900 p-3 text-xs leading-relaxed text-slate-100">
{`from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox"])
    hal = b.new_page()
    hal.goto("https://contoh.com", wait_until="networkidle")
    print(hal.inner_text("h1"))
    b.close()`}
        </pre>
        <div className="mt-4 rounded-lg bg-amber-50 px-3 py-2.5 text-xs text-amber-800">
          <b>Wajib dibaca sebelum scraping.</b> Permintaanmu keluar memakai alamat
          IP kampus. Kalau ada yang melakukan scraping ugal-ugalan, yang diblokir
          atau dikomplain adalah <b>alamat kampus</b> — bukan akunmu pribadi, dan
          itu merugikan semua orang di lab ini.
          <ul className="mt-2 ml-4 list-disc space-y-1">
            <li>Beri jeda antar permintaan (mulai dari 1–3 detik).</li>
            <li>
              Patuhi <code>robots.txt</code> dan syarat layanan situs tersebut.
            </li>
            <li>
              Cantumkan identitas di <code>User-Agent</code> supaya pemilik situs
              bisa menghubungimu bila keberatan.
            </li>
            <li>
              Jangan ambil data pribadi, dan jangan menembus login/paywall.
            </li>
            <li>
              Simpan hasilnya, jangan ulangi permintaan yang sama berkali-kali.
            </li>
          </ul>
        </div>
        <p className="mt-3">
          Scraping tidak memakai VRAM, jadi <b>tidak memotong kuota GPU</b>. Namun job
          scraping tetap memakai slot job-mu (mahasiswa: 1 job berjalan sekaligus) — beri
          batas jumlah halaman supaya tidak berjalan tanpa akhir.
        </p>
      </Section>

      <Section title="Terminal & Git — push ke GitHub dari notebook">
        <p>
          Tekan <b>Ctrl+`</b> (atau tombol <b>Terminal</b> di toolbar notebook) untuk
          membuka <b>terminal bash</b> di dalam sesimu — lengkap dengan <code>git</code>,{' '}
          <code>pip</code>, dan perintah Linux umum. Terminal berjalan di lingkungan
          sesimu sendiri: hanya melihat folder kerjamu (<code>/work</code>) dan
          penyimpanan pribadimu (<code>/persist</code>).
        </p>
        <ul className="list-disc space-y-1 pl-5">
          <li>
            <b>Clone/pull repo publik</b> langsung bisa: <code>git clone URL</code> —
            tanpa token.
          </li>
          <li>
            <b>git push wajib Personal Access Token</b> (GitHub menolak password akun
            sejak 2021). Buat sekali: github.com → foto profil → Settings → Developer
            settings → <b>Fine-grained tokens</b> → Generate; pilih repo-mu; Permissions
            → Contents: <b>Read and write</b>; salin token (hanya tampil sekali).
          </li>
          <li>
            Jalankan <code>git config --global credential.helper store</code> sekali,
            lalu push pertama isi username + <b>tempel token</b> di prompt Password
            (layar tak menampilkan apa-apa saat menempel — itu normal). Token tersimpan
            privat di penyimpananmu; push berikutnya tidak ditanya lagi.
          </li>
          <li>
            Perintah yang <b>bertanya</b> (username/password/konfirmasi) harus dijalankan
            di terminal — sel notebook <code>!git push</code> akan macet karena tidak
            bisa menjawab prompt.
          </li>
          <li>
            Aktivitas di terminal (termasuk proses yang masih mencetak output) menjaga
            sesi tetap hidup dari penutupan otomatis karena idle.
          </li>
          <li>
            Terminal <b>tetap berjalan</b> saat kamu pindah menu atau tab; saat kembali,
            output selama ditinggal diputar ulang. Tombol <b>X</b> hanya menyembunyikan
            panel; tombol <b>Hentikan</b> (atau <Code>exit</Code>) baru menghentikan shell.
          </li>
        </ul>
        <div className="rounded-lg bg-amber-50 px-3 py-2 text-amber-800 ring-1 ring-inset ring-amber-600/15">
          ⚠️ Jangan menaruh token di dalam kode/notebook yang dibagikan — cukup lewat
          prompt password. Bingung? Tanya Asisten AI: <i>"bagaimana cara push ke
          GitHub?"</i> — ia memandu sampai selesai.
        </div>
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
                  idle atau paling lama 8 jam per sesi.
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

      <Section title="Devbox — ngoding di VS Code sendiri, tenaganya dari server">
        <p>
          Kalau lebih nyaman memakai <b>VS Code</b> sendiri (lengkap dengan extension,
          debugger, dan terminal), buka menu <b>Submit → Devbox (VS Code)</b>. Kode,
          terminal, dan GPU berjalan <b>di server kampus</b>; laptop Anda hanya jadi layar.
          Jadi laptop spesifikasi rendah pun tetap dapat <b>NVIDIA L40S</b>.
        </p>
        <ul className="list-disc space-y-1 pl-5">
          <li>
            <b>Cara utama — VS Code Desktop di laptop sendiri</b> (Windows, macOS, Linux):
            klik <b>Nyalakan devbox</b>, lalu di bagian <b>Pakai VS Code Desktop di komputer
            Anda</b> pilih <b>Siapkan tunnel VS Code Desktop</b>, masukkan kode otorisasi
            GitHub (sekali saja), lalu di VS Code pilih <i>Remote Tunnels: Connect to
            Tunnel</i>. Kode, terminal, dan GPU tetap berjalan di server.
          </li>
          <li>
            <b>Pelengkap — lewat browser:</b> buka <b>Buka di browser (opsional)</b> lalu klik
            <b> Buka VS Code di browser</b>. Cocok bila tunnel tersendat, atau bila Anda memakai
            komputer lab/pinjaman karena tidak memasang apa pun. Terbuka di tab baru lewat
            alamat ComputeHub sendiri — <b>tanpa akun GitHub, tanpa layanan Microsoft</b>.
            Kalau tab tidak muncul, izinkan pop-up untuk situs ini.
          </li>
          <li>
            Berkasnya <b>sama</b> dengan yang di menu Penyimpanan, jadi bisa berpindah
            antara notebook dan VS Code tanpa menyalin data.
          </li>
          <li>
            <b>Tidak perlu memilih CPU atau GPU.</b> GPU diberikan otomatis selama masih
            tersedia dan kuota harian Anda belum habis; kalau sedang penuh, devbox tetap
            menyala dengan CPU dan alasannya ditampilkan.
          </li>
          <li>
            <b>AI chat tanpa akun GitHub/Copilot:</b> di panel Chat VS Code (versi 1.122 ke
            atas) buka pemilih model → <b>Manage Models</b> → <b>Add Models</b> →{' '}
            <b>Ollama</b> dengan alamat bawaan <Code>http://localhost:11434</Code>. Model
            asisten AI dari server kampus langsung muncul tanpa login (maks. 2 permintaan
            bersamaan per pengguna).
          </li>
          <li>
            Alokasi GPU dan runtime Devbox bukan berarti GPU terus bekerja. Pada laporan,
            nilai nol berarti terukur nol; <b>Belum diukur</b>, <b>Tidak tersedia</b>, dan{' '}
            <b>Data lama</b> tidak boleh dianggap nol. Pemakaian saat ini dibedakan dari
            nilai puncak selama sesi.
          </li>
        </ul>
        <p>
          <b>Perlu diingat:</b> secara bawaan devbox <b>mati otomatis</b> setelah semua
          koneksi VS Code terputus selama <b>2 menit</b>, diperiksa berkala.
          Sambungan yang kembali sebelum batas itu membatalkan penghentian.
          Program di dalam devbox ikut berhenti, tetapi berkas yang sudah disimpan{' '}
          <b>tidak dihapus</b>. Devbox juga dimatikan setelah <b>60 menit tanpa aktivitas</b>{' '}
          (30 menit bila memegang GPU), dengan peringatan 5 menit sebelumnya. Kuota GPU harian
          hanya terpotong saat kode di devbox benar-benar memakai VRAM; bila kuota habis,
          devbox dihentikan sampai kuota pulih.
        </p>
        <p>
          Untuk pekerjaan panjang yang ingin <b>ditinggal dengan laptop dimatikan</b>,
          tetap pakai <b>Job Batch</b> — devbox butuh Anda tersambung.
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
            Daftar file tidak dibatasi jumlah total item. Buka folder untuk memuat isinya,
            lalu gulir atau tekan <b>Muat berikutnya</b> sampai semua berkas tampil.
            Berlaku juga pada explorer notebook; folder cache internal tetap disembunyikan.
          </li>
          <li>
            Seret file atau folder dari komputer ke Penyimpanan, atau jatuhkan langsung
            di folder tujuan. Struktur subfolder dan folder kosong tetap disimpan;
            batas unggahan tetap 256 MiB per file.
          </li>
          <li>
            Untuk <b>memindahkan</b> file atau folder, seret barisnya ke folder tujuan
            seperti di VS Code; lepaskan di area kosong daftar untuk memindahkannya ke
            tingkat atas. Folder tertutup terbuka sendiri saat kursor ditahan di atasnya.
          </li>
          <li>
            Pada layar desktop, geser pembatas antara daftar folder dan pratinjau untuk
            mengatur lebar. Ukurannya diingat browser; klik ganda untuk ukuran awal.
          </li>
          <li>
            Kuota default <b>30&nbsp;GiB</b> per user (dosen 50&nbsp;GiB; 1&nbsp;GiB = 1024&nbsp;MiB ≈ 1,07&nbsp;GB). Peringatan bertahap
            di <b>80%, 90%, dan 100%</b>: spanduk di semua halaman, notifikasi di lonceng,
            dan email. Di 100% <b>unggahan serta job/notebook/Devbox baru ditolak</b>{' '}
            sampai ada ruang — berkasmu tetap aman, mengunduh dan menghapus tetap bisa.
          </li>
          <li>
            Butuh lebih besar? Klik <b>Ajukan tambahan kuota</b> (di spanduk atau kartu
            pemakaian halaman Penyimpanan), isi besaran dan alasannya. Admin meninjau;
            hasilnya masuk ke notifikasimu dan kuota naik otomatis bila disetujui. Hanya
            satu permintaan yang bisa menunggu pada satu waktu.
          </li>
          <li>
            File/folder yang dihapus masuk <b>Tempat Sampah</b> di menu Penyimpanan dan masih
            bisa dipulihkan selama <b>7 hari</b>; setelah itu dibersihkan otomatis.
          </li>
          <li>Data antar-user terisolasi — kamu tak bisa melihat file user lain.</li>
        </ul>
      </Section>

      {isStudent && (
        <Section title="Kuota GPU harian (mahasiswa)">
          <ul className="list-disc space-y-1 pl-5">
            <li>
              Kuota GPU mahasiswa <b>6 jam per hari</b>, kembali penuh setiap{' '}
              <b>tengah malam (WITA)</b> tanpa perlu lapor. Sisa kuota tampil di{' '}
              <b>Dashboard</b>.
            </li>
            <li>
              Yang dihitung hanya waktu kode benar-benar <b>memakai VRAM</b> — job, notebook,
              dan Devbox. Kode tanpa CUDA tidak memotong kuota.
            </li>
            <li>
              Mahasiswa menjalankan <b>1 job sekaligus</b>; job berikutnya antre otomatis.
              Batas waktu job = sisa kuota saat submit.
            </li>
            <li>
              Kuota habis → job/notebook/Devbox GPU baru <b>ditolak</b> dan Devbox yang berjalan
              dihentikan sampai tengah malam. Berkasmu tetap aman.
            </li>
          </ul>
        </Section>
      )}

      <Section title="Plafon VRAM (memori GPU)">
        <p>
          Tiap akun punya <b>plafon VRAM</b> sesuai kebijakan perannya. Plafon ini{' '}
          <b>ditegakkan di dalam job, notebook, dan Devbox</b>: PyTorch/TensorFlow hanya
          boleh memakai sebesar plafonmu, sehingga satu akun tidak bisa menghabiskan kartu
          GPU milik bersama.
        </p>
        <ul className="list-disc space-y-1 pl-5">
          <li>
            Melebihi plafon memunculkan <Code>CUDA out of memory</Code>{' '}
            <b>pada prosesmu sendiri</b> — pekerjaan pengguna lain tidak ikut mati.
          </li>
          <li>
            Cara hemat: perkecil <i>batch size</i>, pakai AMP{' '}
            (<Code>torch.cuda.amp.autocast()</Code>), atau <i>gradient checkpointing</i>.
          </li>
          <li>
            Masih kurang untuk riset? Minta admin menaikkan plafon lewat{' '}
            <b>kebijakan per-user</b> — tidak perlu mengubah kode.
          </li>
        </ul>
      </Section>

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
              CPU). Plafon VRAM ditegakkan di dalam container ComputeHub, jadi menaikkan
              angkanya di sini langsung berlaku pada job/notebook/Devbox berikutnya.
            </li>
            <li>
              <b>Akun lokal Google</b> — pengguna masuk dengan Google pribadi melalui{' '}
              <a href="/welcome/user" className="underline">/welcome/user</a>.
              Akun otomatis aktif untuk dashboard, tetapi fitur lain hanya pratinjau
              terkunci. Menu Minta Akses mengirim notifikasi ke seluruh admin aktif.
              Tinjau melalui Permintaan Akses atau kolom Akses fitur di Pengguna;
              pilih mahasiswa/dosen untuk membuka seluruh fitur sesuai peran dan kuota.
              Status aktif/nonaktif berbeda dari persetujuan fitur. Akun ini tidak
              memakai password aplikasi dan bukan akun Linux/SSH.
            </li>
            <li>
              <b>Laporan</b> — pemakaian resource per akun &amp; per user OS (termasuk proses
              di dalam container Docker), pemakaian disk server, dan
              pemakai layanan LLM (Asisten web, Copilot devbox, kunci API); unduh PDF per user.
            </li>
            <li>
              <b>Jam GPU Bulanan</b> (di Laporan) — jam GPU per pengguna dan per peran untuk
              bulan yang dipilih, dihitung sama dengan kuota; bisa diunduh CSV untuk pimpinan.
            </li>
            <li>
              <b>Peringatan</b> — selain ambang resource, menampilkan kesehatan email (SMTP).
              Login SMTP diuji otomatis tiap 6 jam; bila gagal, admin diberi tahu lewat
              Telegram.
            </li>
            <li>
              <b>Verifikasi dua langkah (2FA)</b> — akun admin dengan login password bisa
              mengaktifkan authenticator (TOTP) + kode pemulihan dari halaman <b>Profil</b>.
            </li>
            <li>
              <b>Akses API Key Ollama</b> — buat kunci API untuk rekan di luar server (pemilik
              dipilih dari daftar pengguna, model &amp; batas laju per kunci) dan pantau status
              live pemakaiannya.
            </li>
            <li>
              <b>Pengaturan Akun Linux</b> — batas CPU/RAM akun Linux server, bisa permanen
              (bertahan reboot). <b>Log Aktivitas Admin</b> — filter dan ekspor CSV seluruh
              tindakan admin.
            </li>
            <li>
              <b>Model Asisten AI</b> (Pengaturan, per peran, atau Limit khusus pengguna) — bisa
              mencentang beberapa model; model ★ utama dipakai Asisten web, semua model yang
              dicentang tampil di Copilot Chat devbox.
            </li>
            <li>
              <b>ComputeHub Devbox (cadangan VRAM)</b> — khusus super admin di Pengaturan:
              memesan VRAM di server bersama agar pengguna ComputeHub tetap kebagian GPU.
              Aplikasi Docker Compose lain bisa didaftarkan sebagai <b>peminjam</b>; tombol{' '}
              <b>Cara pakai</b> menampilkan perintah pinjam/kembalikan siap salin.
            </li>
            <li>
              <b>Peringatan</b> — atur ambang CPU/RAM/VRAM/disk, aktif/nonaktif email,
              kirim email uji.
            </li>
            <li>
              <b>Monitor</b> — grafik CPU/RAM/GPU real-time seluruh server; super admin juga
              melihat panel Monitoring kesehatan backend (request, error, latensi). Admin
              menerima peringatan Telegram/email saat suhu GPU melewati ambang.
            </li>
            <li>
              <b>Pengaturan platform</b> (enforce GPU, kuota default, batas per-peran) —
              sebagian <b>khusus super admin</b>.
            </li>
            <li>
              <b>Permintaan Kuota Penyimpanan</b> (di Pengaturan) — pengajuan tambahan
              kuota dari pengguna masuk di sini (juga ke lonceng, email, dan Telegram
              admin). <b>Setujui</b> dengan besaran GiB (boleh diubah dari yang diminta) atau{' '}
              <b>Tolak</b> dengan catatan; keputusan langsung tercatat di audit dan
              diberitahukan ke pemohon.
            </li>
            <li>
              <b>Cadangan &amp; Pemulihan</b> (menu Admin › <b>Cadangan</b>, tersendiri) — bukti backup harian, snapshot
              restic, salinan offsite, dan hasil <i>restore drill</i> bulanan tersimpan di
              database (bukan hanya email/Telegram); riwayatnya bisa diunduh sebagai CSV
              untuk keperluan audit. Setiap baris riwayat punya kolom <b>Lokasi</b> (lencana
              <b> Server</b> / <b>Drive</b> dengan centang bila tersimpan, silang bila gagal atau
              salinan server sudah dihapus) dan kolom <b>Aksi</b>: ikon mata membuka
              <b> detail lengkap</b> untuk jenis apa pun (status, keterangan, angka kunci, seluruh data
              tercatat berlabel, sumber pencatat); ikon unduh menghasilkan <b>laporan PDF</b> catatan itu
              (ringkasan, data tercatat, dan Detail Backup bila ada) untuk lampiran audit; catatan backup yang arsipnya masih ada di server
              juga memuat <b>Detail Backup</b> — ukuran, durasi, salinan off-site, isi database (tabel,
              perkiraan baris), workspace per akun, komponen lain, dan berkas di dalam arsip — serta
              tombol uji pulih / pulihkan. Administrator utama dapat <b>menghapus</b> catatan riwayat
              dan/atau berkas arsip di server (ketik <b>HAPUS</b>; dijalankan agen host, salinan Drive
              dipindah ke folder versi pada sinkronisasi berikutnya, restic tidak berubah); setiap
              penghapusan tercatat di Log Aktivitas Admin.
            </li>
            <li>
              <b>Kebijakan penyimpanan cadangan</b> (pesan dosen: yang besar hanya di Drive) — tiap hari
              02:30 dibuat <b>arsip inti</b> kecil (database + roles + konfigurasi + log job, tanpa
              workspace) yang disimpan di server 30 hari dan disalin ke Google Drive (90 hari), serta
              <b> snapshot restic</b> harian (dedup) yang ditulis <b>langsung ke repo di Drive</b> — tidak
              ada repo besar di server. <b>Arsip penuh</b> (dengan workspace, puluhan GB) dibuat tiap Minggu
              atau lewat Backup sekarang, diunggah ke Drive dengan verifikasi md5, lalu salinan server
              dihapus; Drive menyimpan 8 arsip penuh terbaru. Pulih dari arsip penuh/snapshot berarti
              mengunduh dari Drive dulu; pulih database cepat memakai arsip inti di server.
            </li>
            <li>
              <b>Backup &amp; restore dari web</b> (administrator utama) — tombol <b>Backup sekarang</b>
              membuat arsip penuh saat itu juga tanpa menunggu jadwal. Tab <b>Sumber pemulihan</b>
              memuat arsip di server, snapshot restic, salinan Google Drive, dan <b>titik rollback</b>;
              dari tiap sumber tersedia <b>Uji pulih</b> (ke Postgres sementara, produksi tak disentuh)
              dan <b>Pulihkan…</b> dengan pilihan cakupan (database / workspace / konfigurasi),
              pemeriksaan sesi berjalan, dan frasa konfirmasi. Setiap restore otomatis membuat titik
              rollback sehingga hasil yang keliru bisa dikembalikan dari web juga. Seluruh eksekusi
              dilakukan agen di server (bukan oleh aplikasi web) dan tercatat di Log Aktivitas Admin.
            </li>
          </ul>
        </Section>
      )}

      <Section title="Masalah umum">
        <ul className="list-disc space-y-1 pl-5">
          <li>
            <b>“Kuota GPU harian habis”</b> → tunggu sampai tengah malam (WITA); kuota pulih
            otomatis. Sisa kuota terlihat di Dashboard.
          </li>
          <li>
            <b>Training lambat / <Code>torch.cuda.is_available()</Code> bernilai False</b> →
            job menunggu GPU lebih dari 10 menit lalu dijalankan tanpa GPU. Submit ulang saat
            GPU lebih sepi (lihat Monitor).
          </li>
          <li>
            <b><Code>CUDA out of memory</Code></b> → melewati plafon VRAM akunmu; kecilkan batch
            size, pakai AMP, atau minta admin menaikkan plafon.
          </li>
          <li>
            <b>Notebook berhenti sendiri</b> → sesi interaktif mati setelah 30 menit idle
            atau maksimal 8 jam. Untuk pekerjaan panjang tanpa buka browser, pakai{' '}
            <b>Job Batch</b>.
          </li>
          <li>
            <b>Job “antri” lama</b> → lihat alasan dan perkiraan mulai di Daftar Job. Biasanya
            GPU sedang dipakai, atau Devbox/notebook-mu masih menyala (mahasiswa hanya boleh 1
            sekaligus — matikan dulu bila tidak dipakai). Job jalan otomatis (diurus server,
            laptop boleh mati).
          </li>
        </ul>
      </Section>
    </div>
  )
}
