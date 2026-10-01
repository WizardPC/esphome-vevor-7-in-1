#!/usr/bin/env python3
"""Flashe un firmware puis capture IMMÉDIATEMENT ses lignes de démarrage (via l'API native).

Pourquoi : le journal de démarrage du CC1101 (« CC1101 found! Chip ID », entrée en RX, échecs
de verrouillage PLL) est tronqué dans nos captures habituelles, qui démarrent 12 s après le
flash. Or c'est LUI qui dit si la puce a été configurée et mise en écoute. Ce script ne laisse
aucun délai : la connexion API se fait pendant que la carte démarre, et le tampon de logs du
firmware (rejoué à la connexion) contient le setup complet.

Usage : tools/boot_probe.py temoin nous_v0 nous_v1 nous_v3
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
# Dossier (HORS dépôt) où est construit le firmware de référence servant de témoin.
# Paramétrable : VEVOR_TEMOIN_DIR=/chemin/vers/_temoins tools/ab_cycle.py ...
TEMOIN = pathlib.Path(os.environ.get("VEVOR_TEMOIN_DIR",
                                     str(pathlib.Path.home() / "projets" / "_temoins")))
ESPHOME = ROOT / ".venv" / "bin" / "esphome"
PY = ROOT / ".venv" / "bin" / "python"
HOST = "172.16.0.205"

VARIANTS = {
    "temoin": (TEMOIN / "witness-test", "witness.yaml",
               TEMOIN / "witness-test/.esphome/build/vevor-weather-station/build/firmware.ota.bin"),
    "prod": (ROOT / "esphome", "vevor-7in1.yaml", ROOT / "build/variants/nous_prod.ota.bin"),
}

INTERESTING = re.compile(
    r"CC1101 found|Failed to verify|marked as failed|is_failed|Failed to enter|PLL|"
    r"V7IN1 BOOT|Registered with remote_receiver|Vevor 7-in-1|rf_raw|\[84CB\]|"
    r"Remote Receiver|Captures RMT|rx_|BOOT",
    re.I)


def main() -> int:
    names = sys.argv[1:] or ["temoin", "nous_v0"]
    for name in names:
        workdir, yaml, binary = VARIANTS[name]
        log = ROOT / "logs" / f"boot_{name}_{binary.stat().st_mtime_ns}.log"
        print(f"\n=== {name} : flash {binary.name} ({binary.stat().st_size} o) ===", flush=True)
        proc = subprocess.run([str(ESPHOME), "upload", yaml, "--device", HOST, "--file", str(binary)],
                              cwd=workdir, capture_output=True, text=True, timeout=300)
        out = proc.stdout + proc.stderr
        print("flash:", "OK" if "OTA successful" in out else f"FAIL ({proc.returncode})", flush=True)
        # capture IMMÉDIATE (aucune attente) : on veut le setup dans le tampon de logs
        cap = subprocess.run([str(PY), str(ROOT / "tools" / "capture_logs.py"),
                              "--host", HOST, "--seconds", "40", "--out", str(log)],
                             capture_output=True, text=True, timeout=120)
        if cap.returncode != 0:
            print(f"  !! capture en échec (code {cap.returncode}) — rien à conclure", flush=True)
        text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        keep = [l for l in text.splitlines() if INTERESTING.search(l)]
        for line in keep[:25]:
            print("   ", line[:160])
        if not keep:
            print("    (aucune ligne de démarrage dans le tampon — capture trop tardive)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
