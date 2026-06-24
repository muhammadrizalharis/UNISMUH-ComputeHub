"""Driver eksekusi notebook (disalin ke folder job lalu dijalankan).

Dijalankan dengan interpreter platform (GPU + torch). Mengeksekusi semua sel
notebook memakai nbclient, MENYIMPAN output sel kembali ke notebook
(`notebook_executed.ipynb`) agar bisa diunduh, dan mencetak output teks ke log.

Standalone: tidak meng-import paket aplikasi.
"""

from __future__ import annotations

import json
import os
import sys

import nbformat
from nbclient import NotebookClient

NB_IN = "notebook.ipynb"
NB_OUT = "notebook_executed.ipynb"


def main() -> int:
    timeout = int(os.environ.get("CH_TIMEOUT", "3600"))

    # Kernelspec lokal yang menunjuk ke interpreter INI (punya GPU + torch).
    base = os.path.abspath("_jkernel")
    kernel_dir = os.path.join(base, "kernels", "computehub")
    os.makedirs(kernel_dir, exist_ok=True)
    with open(os.path.join(kernel_dir, "kernel.json"), "w", encoding="utf-8") as fh:
        json.dump(
            {
                "argv": [
                    sys.executable,
                    "-m",
                    "ipykernel_launcher",
                    "-f",
                    "{connection_file}",
                ],
                "display_name": "ComputeHub",
                "language": "python",
            },
            fh,
        )
    os.environ["JUPYTER_PATH"] = base + os.pathsep + os.environ.get("JUPYTER_PATH", "")

    nb = nbformat.read(NB_IN, as_version=4)
    client = NotebookClient(
        nb,
        timeout=timeout,
        kernel_name="computehub",
        resources={"metadata": {"path": "."}},
        allow_errors=True,
    )
    print("[NB] menjalankan notebook di kernel GPU...", flush=True)
    client.execute()
    nbformat.write(nb, NB_OUT)

    # Cetak output teks tiap sel + deteksi error.
    errors = 0
    for cell in nb.cells:
        if cell.get("cell_type") != "code":
            continue
        for out in cell.get("outputs", []):
            kind = out.get("output_type")
            if kind == "stream":
                sys.stdout.write(out.get("text", ""))
            elif kind in ("execute_result", "display_data"):
                data = out.get("data", {}).get("text/plain")
                if data:
                    text = "".join(data) if isinstance(data, list) else data
                    sys.stdout.write(text + "\n")
            elif kind == "error":
                errors += 1
                sys.stderr.write("\n".join(out.get("traceback", [])) + "\n")
    sys.stdout.flush()
    print(f"[NB] selesai. Output disimpan -> {NB_OUT}", flush=True)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
