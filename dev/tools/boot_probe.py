#!/usr/bin/env python3
"""Flashe un firmware puis capture IMMÉDIATEMENT ses lignes de démarrage (via l'API native).

Pourquoi : le journal de démarrage du CC1101 (« CC1101 found! Chip ID », entrée en RX, échecs
de verrouillage PLL) est tronqué dans nos captures habituelles, qui démarrent 12 s après le
flash. Or c'est LUI qui dit si la puce a été configurée et mise en écoute. Ce script ne laisse
aucun délai : la connexion API se fait pendant que la carte démarre, et le tampon de logs du
firmware (rejoué à la connexion) contient le setup complet.

Les variantes sont celles de `_common.VARIANTS` (mêmes que `ab_cycle.py` : source de vérité
unique). Un nom inconnu échoue lisiblement ; sans argument, les variantes par défaut sont
`temoin prod` (défaut VALIDE — l'ancien `nous_v0` n'existe plus, il causait un KeyError).

Usage : tools/boot_probe.py [temoin prod origine prod_avant_revue]

Code retour :
    0  toutes les captures ont ramené des lignes ;
    2  au moins une capture a échoué techniquement ;
    3  MESURE NULLE : au moins une capture est vide — rien n'a été mesuré.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _common import (DEFAULT_HOST, ESPHOME, PY, RC_ERREUR, RC_MESURE_NULLE,  # noqa: E402
                     RC_OK, ROOT, variant_of)

INTERESTING = re.compile(
    r"CC1101 found|Failed to verify|marked as failed|is_failed|Failed to enter|PLL|"
    r"V7IN1 BOOT|Registered with remote_receiver|Vevor 7-in-1|rf_raw|\[84CB\]|"
    r"Remote Receiver|Captures RMT|rx_|BOOT",
    re.I)


def main() -> int:
    names = sys.argv[1:] or ["temoin", "prod"]
    worst = RC_OK
    for name in names:
        workdir, yaml, binary, _desc = variant_of(name)   # nom inconnu -> message lisible
        if not binary.exists():
            print(f"# ERREUR : binaire absent pour {name} : {binary}", file=sys.stderr)
            return RC_ERREUR
        log = DEV / "logs" / f"boot_{name}_{binary.stat().st_mtime_ns}.log"
        print(f"\n=== {name} : flash {binary.name} ({binary.stat().st_size} o) ===", flush=True)
        proc = subprocess.run([str(ESPHOME), "upload", yaml, "--device", DEFAULT_HOST,
                               "--file", str(binary)],
                              cwd=workdir, capture_output=True, text=True, timeout=300)
        out = proc.stdout + proc.stderr
        flash_ok = "OTA successful" in out
        print("flash:", "OK" if flash_ok else f"FAIL ({proc.returncode})", flush=True)
        # capture IMMÉDIATE (aucune attente) : on veut le setup dans le tampon de logs
        cap = subprocess.run([str(PY), str(DEV / "tools" / "capture_logs.py"),
                              "--host", DEFAULT_HOST, "--seconds", "40", "--out", str(log)],
                             capture_output=True, text=True, timeout=120)
        print(f"# capture={cap.returncode}", flush=True)
        if cap.returncode not in (RC_OK, RC_MESURE_NULLE):
            print(f"  !! capture en échec (code {cap.returncode}) — rien à conclure", flush=True)
            worst = RC_ERREUR
        elif cap.returncode == RC_MESURE_NULLE:
            # Capture réussie mais VIDE : ce n'est pas « pas de ligne de démarrage », c'est
            # « rien n'a été mesuré ».
            print("  !! capture VIDE (0 ligne) — MESURE NULLE, rien à conclure", flush=True)
            if worst == RC_OK:
                worst = RC_MESURE_NULLE
        text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        keep = [l for l in text.splitlines() if INTERESTING.search(l)]
        for line in keep[:25]:
            print("   ", line[:160])
        if not keep:
            if cap.returncode == RC_MESURE_NULLE:
                print("    (mesure nulle : aucune ligne capturée)")
            else:
                print("    (aucune ligne de démarrage dans le tampon — capture trop tardive)")
    return worst


if __name__ == "__main__":
    sys.exit(main())
