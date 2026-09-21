#!/usr/bin/env python3
"""Setel remote.SSH.remotePlatform[<host>] di settings.json VS Code (macOS/Linux).

Kenapa: saat pertama menyambung, VS Code menanyakan "platform remote host". Devbox
adalah container LINUX; bila pengguna keliru memilih Windows/macOS, koneksi gagal dan
pilihan itu tersimpan sehingga terus gagal. Dengan menyetelnya lebih dulu, VS Code tidak
pernah bertanya (dan pilihan lama yang salah ikut dikoreksi).

Aman: hanya menulis bila settings.json bisa diparse sebagai JSON; bila memuat komentar
(JSONC) berkas dibiarkan apa adanya dan pengguna cukup memilih "Linux" sekali. Selalu
menyimpan cadangan .bak. Dipakai oleh pemasang macOS/Linux (Windows memakai PowerShell).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_EDISI = ("Code", "Code - Insiders", "VSCodium")


def _candidates():
    home = Path.home()
    bases = []
    xdg = os.environ.get("XDG_CONFIG_HOME")
    bases.append(Path(xdg) if xdg else home / ".config")  # Linux
    bases.append(home / "Library" / "Application Support")  # macOS
    seen: set[Path] = set()
    for base in bases:
        for nama in _EDISI:
            berkas = base / nama / "User" / "settings.json"
            # Hanya sentuh editor yang memang terpasang (folder induknya ada).
            if berkas.parent.parent.is_dir() and berkas not in seen:
                seen.add(berkas)
                yield berkas


def main() -> int:
    if len(sys.argv) < 3:
        return 0
    host, platform = sys.argv[1], sys.argv[2]
    key = "remote.SSH.remotePlatform"
    for path in _candidates():
        raw = ""
        try:
            if path.exists():
                raw = path.read_text(encoding="utf-8")
                data = json.loads(raw) if raw.strip() else {}
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                data = {}
        except (OSError, ValueError):
            # settings.json memuat komentar / tak terbaca -> jangan disentuh.
            continue
        if not isinstance(data, dict):
            continue
        plat = data.get(key)
        if not isinstance(plat, dict):
            plat = {}
        plat[host] = platform
        data[key] = plat
        try:
            if raw:
                path.with_suffix(path.suffix + ".bak").write_text(raw, encoding="utf-8")
            path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        except OSError:
            continue
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
