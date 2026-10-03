#!/usr/bin/env python3
"""Relève l'état et les logs du firmware TÉMOIN (projet de référence) par son serveur web.

Le firmware témoin expose un serveur web NON authentifié sur le port 80 avec deux flux :
  - /        : page d'état (HTML)
  - /events  : flux SSE de l'état (uptime + toutes les entités) ET, en clair, les lignes de log
               de l'appareil — dont « Salve RF recue : N impulsions » et les trames décodées.

Pourquoi cet outil : c'est la seule façon de savoir, SANS toucher à la carte, si le firmware
témoin décode la station à cet instant et à cet endroit. Il sert de mesure de contrôle quand la
carte tourne le témoin (l'API native, elle, est chiffrée avec une autre clé : inaccessible).

Usage :
  tools/witness_probe.py --host 172.16.0.205 --seconds 90
Sortie : logs/witness_probe_<AAAAMMJJ_HHMM>.log + résumé sur la sortie standard.
"""

from __future__ import annotations

import argparse
import datetime as dt
import socket
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import atomic_write_text  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="172.16.0.205")
    ap.add_argument("--seconds", type=float, default=90.0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M")
    out = Path(args.out) if args.out else DEV / "logs" / f"witness_probe_{stamp}.log"
    out.parent.mkdir(parents=True, exist_ok=True)

    base = f"http://{args.host}"
    socket.setdefaulttimeout(10)

    lines: list[str] = []
    header = [
        f"# Témoin (projet de référence) — relevé du serveur web {base}:80",
        f"# /events, {args.seconds:.0f} s, {dt.datetime.now(dt.timezone.utc):%Y-%m-%dT%H:%M:%SZ}",
    ]

    # Page d'état : elle porte le titre, l'uptime et la liste des entités.
    try:
        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            page = resp.read().decode("utf-8", "replace")
        lines.append("### / (page d'état) ###")
        lines.append(f"# HTTP {resp.status}, {len(page)} octets")
        for pat in (r"<title>([^<]*)</title>", r"uptime[^0-9]{0,20}(\d+)"):
            found = __import__("re").search(pat, page, __import__("re").IGNORECASE)
            if found:
                lines.append(f"# {pat} -> {found.group(1)}")
    except Exception as exc:  # noqa: BLE001 - on journalise l'échec, il est un résultat
        lines.append(f"# / -> ÉCHEC {type(exc).__name__}: {exc}")

    # Flux SSE : état des entités + lignes de log.
    lines.append("### /events (SSE) ###")
    decoded: list[str] = []
    bursts: list[str] = []
    deadline = dt.datetime.now().timestamp() + args.seconds
    try:
        with urllib.request.urlopen(base + "/events", timeout=10) as resp:
            for raw in resp:
                if dt.datetime.now().timestamp() >= deadline:
                    break
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                lines.append(line)
                if "Salve RF recue" in line:
                    bursts.append(line)
                if "[84CB]" in line or "vevor_decoder" in line:
                    decoded.append(line)
    except Exception as exc:  # noqa: BLE001
        lines.append(f"# /events interrompu: {type(exc).__name__}: {exc}")

    atomic_write_text(out, "\n".join(lines) + "\n")

    print(f"fichier         : {out}")
    print(f"lignes SSE      : {len(lines)}")
    print(f"rafales RF      : {len(bursts)}")
    for b in bursts[-5:]:
        print(f"  {b}")
    print(f"trames décodées : {len(decoded)}")
    for d in decoded[-5:]:
        print(f"  {d}")
    if not bursts and not decoded:
        print("  aucune rafale RF ni trame décodée dans la fenêtre : pas de signal (ou témoin muet)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
