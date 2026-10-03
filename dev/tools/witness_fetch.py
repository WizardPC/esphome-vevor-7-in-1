#!/usr/bin/env python3
"""Récupère un chemin du serveur web du firmware témoin (non authentifié, port 80) et le sauve.

Utile pour /logs : le serveur du témoin diffuse ses lignes de log, dont le dump_config de
démarrage (fréquence, déviation, bande, gain AGC…). C'est la seule source qui permet de comparer
sa configuration radio à la nôtre champ par champ quand la carte tourne son firmware.

Usage : tools/witness_fetch.py --host <ip-de-la-carte> --path /logs --seconds 20 --out logs/x.log
"""

from __future__ import annotations

import os
import argparse
import datetime as dt
import socket
import sys
import urllib.request
from pathlib import Path

DEV = Path(__file__).resolve().parent.parent   # dev/
ROOT = DEV.parent                               # racine du dépôt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("VEVOR_HOST"),
                    required="VEVOR_HOST" not in os.environ,
                    help="adresse IP de la carte. À défaut : variable d'environnement VEVOR_HOST, ou dev/tools/find_esp32.py pour la découvrir")
    ap.add_argument("--path", default="/logs")
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    socket.setdefaulttimeout(10)
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# Témoin — GET http://{args.host}{args.path} pendant {args.seconds:.0f} s",
        f"# {dt.datetime.now(dt.timezone.utc):%Y-%m-%dT%H:%M:%SZ}",
    ]
    deadline = dt.datetime.now().timestamp() + args.seconds
    try:
        with urllib.request.urlopen(f"http://{args.host}{args.path}", timeout=10) as resp:
            lines.append(f"# HTTP {resp.status} content-type={resp.headers.get('content-type')}")
            for raw in resp:
                lines.append(raw.decode("utf-8", "replace").rstrip("\r\n"))
                if dt.datetime.now().timestamp() >= deadline:
                    break
    except Exception as exc:  # noqa: BLE001 - un échec est un résultat, il est journalisé
        lines.append(f"# ÉCHEC {type(exc).__name__}: {exc}")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"fichier : {out} ({len(lines)} lignes)")
    for line in lines[:12]:
        print(" |", line[:200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
