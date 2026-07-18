"""Driver eksekusi notebook (disalin ke folder job lalu dijalankan).

Mengeksekusi semua sel KODE notebook di kernel GPU (ipykernel), MENYIMPAN output tiap
sel kembali ke notebook (in-place / NB_OUT), dan mencetak ringkasan ke log.

PENTING: HANYA memakai `jupyter_client` + `json` (keduanya SUDAH ADA di image ch-compute
bersama ipykernel) — TIDAK butuh nbformat/nbclient. Ini mencegah kegagalan
'ModuleNotFoundError' & tak perlu memasang paket tambahan. Standalone: tidak meng-import
paket aplikasi.
"""

from __future__ import annotations

import json
import os
import queue
import sys

from jupyter_client import KernelManager

# Path notebook input/output — bisa DI-OVERRIDE lewat env (mis. notebook di subfolder
# project) supaya output tersimpan PER-SEL kembali ke berkasnya. Default = mode 'notebook'.
NB_IN = os.environ.get("CH_NB_IN", "notebook.ipynb")
NB_OUT = os.environ.get("CH_NB_OUT", "notebook_executed.ipynb")


def _make_kernelspec() -> str:
    """Buat kernelspec lokal 'computehub' -> interpreter INI (punya GPU + torch)."""
    base = os.path.abspath("_jkernel")
    kernel_dir = os.path.join(base, "kernels", "computehub")
    os.makedirs(kernel_dir, exist_ok=True)
    with open(os.path.join(kernel_dir, "kernel.json"), "w", encoding="utf-8") as fh:
        json.dump(
            {
                "argv": [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
                "display_name": "ComputeHub",
                "language": "python",
            },
            fh,
        )
    os.environ["JUPYTER_PATH"] = base + os.pathsep + os.environ.get("JUPYTER_PATH", "")
    return "computehub"


def _cell_source(cell: dict) -> str:
    src = cell.get("source", "")
    return "".join(src) if isinstance(src, list) else str(src)


def _run_cell(kc, source: str, timeout: int) -> tuple[list, int | None]:
    """Jalankan satu sel, kumpulkan output IOPub sampai kernel idle. Return (outputs, count)."""
    msg_id = kc.execute(source, allow_stdin=False, stop_on_error=False)
    outputs: list = []
    exec_count: int | None = None
    while True:
        try:
            msg = kc.get_iopub_msg(timeout=timeout)
        except queue.Empty:
            break
        if msg.get("parent_header", {}).get("msg_id") != msg_id:
            continue
        mtype = msg["header"]["msg_type"]
        content = msg["content"]
        if mtype == "status":
            if content.get("execution_state") == "idle":
                break
        elif mtype == "execute_input":
            exec_count = content.get("execution_count", exec_count)
        elif mtype == "stream":
            outputs.append(
                {"output_type": "stream", "name": content.get("name", "stdout"),
                 "text": content.get("text", "")}
            )
        elif mtype == "execute_result":
            exec_count = content.get("execution_count", exec_count)
            outputs.append(
                {"output_type": "execute_result",
                 "execution_count": content.get("execution_count"),
                 "data": content.get("data", {}),
                 "metadata": content.get("metadata", {})}
            )
        elif mtype == "display_data":
            outputs.append(
                {"output_type": "display_data",
                 "data": content.get("data", {}),
                 "metadata": content.get("metadata", {})}
            )
        elif mtype == "error":
            outputs.append(
                {"output_type": "error", "ename": content.get("ename", ""),
                 "evalue": content.get("evalue", ""),
                 "traceback": content.get("traceback", [])}
            )
    # Ambil balasan shell (execution_count otoritatif) tanpa menggantung lama.
    try:
        reply = kc.get_shell_msg(timeout=10)
        ec = reply.get("content", {}).get("execution_count")
        if ec is not None:
            exec_count = ec
    except queue.Empty:
        pass
    return outputs, exec_count


def main() -> int:
    timeout = int(os.environ.get("CH_TIMEOUT", "3600"))
    kernel_name = _make_kernelspec()

    with open(NB_IN, encoding="utf-8") as fh:
        nb = json.load(fh)
    cells = nb.get("cells", []) if isinstance(nb, dict) else []

    # Kernel dijalankan dari FOLDER notebook supaya akses berkas relatif benar.
    nb_dir = os.path.dirname(os.path.abspath(NB_IN)) or "."
    km = KernelManager(kernel_name=kernel_name)
    km.start_kernel(cwd=nb_dir)
    kc = km.client()
    kc.start_channels()
    try:
        kc.wait_for_ready(timeout=90)
    except RuntimeError as exc:
        sys.stderr.write(f"[NB] kernel gagal siap: {exc}\n")
        kc.stop_channels()
        km.shutdown_kernel(now=True)
        return 1

    print("[NB] menjalankan notebook di kernel GPU...", flush=True)
    errors = 0
    code_cells = 0
    cells_with_output = 0
    try:
        for cell in cells:
            if cell.get("cell_type") != "code":
                continue
            code_cells += 1
            source = _cell_source(cell)
            if not source.strip():
                cell["outputs"] = []
                cell["execution_count"] = None
                continue
            outputs, exec_count = _run_cell(kc, source, timeout)
            cell["outputs"] = outputs
            cell["execution_count"] = exec_count
            if outputs:
                cells_with_output += 1
            for out in outputs:
                if out.get("output_type") == "error":
                    errors += 1
                    sys.stderr.write("\n".join(out.get("traceback", [])) + "\n")
    finally:
        kc.stop_channels()
        km.shutdown_kernel(now=True)

    # Simpan notebook (in-place / NB_OUT) dengan output tiap sel.
    with open(NB_OUT, "w", encoding="utf-8") as fh:
        json.dump(nb, fh, ensure_ascii=False, indent=1)

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
