// Template job siap pakai — "Mulai dari contoh" untuk mahasiswa/dosen awam.
// Semua contoh mandiri (data sintetis/bawaan sklearn), tanpa unduh dataset.

export interface JobTemplate {
  id: string
  label: string
  desc: string
  code: string
}

export const JOB_TEMPLATES: JobTemplate[] = [
  {
    id: 'cek-gpu',
    label: 'Cek GPU',
    desc: 'Pastikan CUDA & GPU terbaca',
    code: `# Cek GPU & CUDA — jalankan ini dulu untuk memastikan lingkungan siap.
import torch

print("PyTorch :", torch.__version__)
print("CUDA    :", torch.cuda.is_available())
if torch.cuda.is_available():
    print("GPU     :", torch.cuda.get_device_name(0))
    x = torch.rand(4096, 4096, device="cuda")
    y = x @ x  # perkalian matriks di GPU
    print("Matmul 4096x4096 OK, hasil:", y.shape)
`,
  },
  {
    id: 'training-pytorch',
    label: 'Training PyTorch',
    desc: 'Jaringan saraf sederhana di GPU',
    code: `# Training jaringan saraf sederhana (data sintetis) di GPU.
import torch
import torch.nn as nn

device = "cuda" if torch.cuda.is_available() else "cpu"
print("Device:", device)

# Data sintetis: y = 3x1 - 2x2 + noise
torch.manual_seed(0)
X = torch.randn(5000, 2, device=device)
y = (3 * X[:, 0] - 2 * X[:, 1] + 0.1 * torch.randn(5000, device=device)).unsqueeze(1)

model = nn.Sequential(nn.Linear(2, 64), nn.ReLU(), nn.Linear(64, 1)).to(device)
opt = torch.optim.Adam(model.parameters(), lr=1e-3)
loss_fn = nn.MSELoss()

for epoch in range(200):
    opt.zero_grad()
    loss = loss_fn(model(X), y)
    loss.backward()
    opt.step()
    if (epoch + 1) % 50 == 0:
        print(f"epoch {epoch + 1:3d} | loss {loss.item():.5f}")

print("Selesai. Loss akhir:", loss.item())
`,
  },
  {
    id: 'klasifikasi-sklearn',
    label: 'Klasifikasi sklearn',
    desc: 'RandomForest dataset iris (CPU)',
    code: `# Klasifikasi klasik (CPU): RandomForest pada dataset iris bawaan sklearn.
# Catatan: pilih Perangkat = CPU untuk job seperti ini (tidak butuh GPU).
from sklearn.datasets import load_iris
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import train_test_split

X, y = load_iris(return_X_y=True)
Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.25, random_state=42)

clf = RandomForestClassifier(n_estimators=200, random_state=42)
clf.fit(Xtr, ytr)
pred = clf.predict(Xte)

print("Akurasi:", accuracy_score(yte, pred))
print(classification_report(yte, pred))
`,
  },
  {
    id: 'analisis-pandas',
    label: 'Analisis data',
    desc: 'pandas + grafik matplotlib',
    code: `# Analisis data sederhana: pandas + simpan grafik ke file output.
import matplotlib

matplotlib.use("Agg")  # tanpa layar — simpan ke file
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Data sintetis penjualan 12 bulan
rng = np.random.default_rng(7)
df = pd.DataFrame({
    "bulan": pd.date_range("2026-01-01", periods=12, freq="MS"),
    "penjualan": rng.integers(80, 200, 12),
})
df["rata3"] = df["penjualan"].rolling(3).mean()
print(df.to_string(index=False))

fig, ax = plt.subplots(figsize=(8, 4))
ax.bar(df["bulan"].dt.strftime("%b"), df["penjualan"], label="Penjualan")
ax.plot(df["bulan"].dt.strftime("%b"), df["rata3"], "r-o", label="Rata-rata 3 bln")
ax.legend()
fig.tight_layout()
fig.savefig("grafik_penjualan.png", dpi=120)
print("Grafik disimpan: grafik_penjualan.png (lihat di Unduh Output)")
`,
  },
]
