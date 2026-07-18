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

# Path notebook input/output — bisa DI-OVERRIDE lewat env (mis. notebook di subfolder
# project) supaya output tersimpan PER-SEL kembali ke berkasnya. Default = mode 'notebook'.
NB_IN = os.environ.get("CH_NB_IN", "notebook.ipynb")
NB_OUT = os.environ.get("CH_NB_OUT", "notebook_executed.ipynb")


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
    nb_dir = os.path.dirname(NB_IN) or "."
    client = NotebookClient(
        nb,
        timeout=timeout,
        kernel_name="computehub",
        resources={"metadata": {"path": nb_dir}},
        allow_errors=True,
    )
    print("[NB] menjalankan notebook di kernel GPU...", flush=True)
    client.execute()
    nbformat.write(nb, NB_OUT)

    # Output tiap sel sudah TERSIMPAN di notebook -> log cukup RINGKAS: hanya ERROR
    # (traceback, penting utk debug) + ringkasan status. Tak membanjiri log dgn seluruh
    # stdout sel (bisa dilihat langsung di tampilan notebook, di bawah tiap kode).
    errors = 0
    code_cells = 0
    cells_with_output = 0
    for cell in nb.cells:
        if cell.get("cell_type") != "code":
            continue
        code_cells += 1
        outs = cell.get("outputs", [])
        if outs:
            cells_with_output += 1
        for out in outs:
            if out.get("output_type") == "error":
                errors += 1
                sys.stderr.write("\n".join(out.get("traceback", [])) + "\n")
    sys.stderr.flush()
    if errors:
        print(f"[NB] selesai dengan {errors} error. Detail output ada di notebook.", flush=True)
    else:
        print(
            f"[NB] eksekusi berhasil: {code_cells} sel kode dijalankan, "
            f"{cells_with_output} menghasilkan output. Output tersimpan di notebook "
            "(lihat di tampilan notebook, di bawah tiap sel).",
            flush=True,
        )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
