#!/usr/bin/env python3
"""Capture les logs d'un ESP32 ESPHome via l'API native (port 6053) pendant N secondes.

Usage:
    capture_logs.py --host 192.168.2.50 --seconds 90 [--key CLE_BASE64] [--out fichier.log]

Sans --key, utilise $ESPHOME_API_KEY ou la clé lue dans le YAML du projet.
Écrit sur stdout ET, si --out est donné, dans le fichier (écrasé par défaut, --append pour
ajouter).
Sortie adaptée à un agent : une ligne par message de log, horodatée.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import os
import pathlib
import re
import sys

import aioesphomeapi

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_YAML = ROOT / "esphome" / "vevor-7in1.yaml"


def key_from_yaml(path: pathlib.Path) -> str | None:
    if not path.exists():
        return None
    txt = path.read_text(encoding="utf-8", errors="replace")
    # `(\S+)` ne capturait que le PREMIER mot : sur `key: !secret api_key` on récupérait
    # "!secret" tout seul, la résolution échouait et la clé valait None → la carte répondait
    # « Connection requires encryption » (ce qui ressemble à tort à une carte absente).
    # On prend donc toute la fin de ligne.
    m = re.search(r"encryption:\s*\n(?:[ \t].*\n)*?[ \t]+key:\s*(.+?)\s*$", txt, re.M)
    if not m:
        return None
    val = m.group(1).strip().strip('"\'')
    if val.startswith("!secret"):
        # Le YAML ne contient que `key: !secret api_key` : la valeur réelle est dans secrets.yaml.
        parts = val.split(None, 1)
        name = parts[1] if len(parts) > 1 else ""
        secrets = path.parent / "secrets.yaml"
        if name and secrets.exists():
            sm = re.search(rf"^{re.escape(name)}:\s*(\S+)",
                           secrets.read_text(encoding="utf-8", errors="replace"), re.M)
            if sm:
                return sm.group(1).strip().strip('"\'')
        return None
    return val or None


async def run(host: str, port: int, key: str | None, seconds: float, out) -> int:
    # Le chiffrement ESPHome passe par noise_psk (mot-clé) ; `password` est l'ancien auth en clair.
    # Passer la clé en 3e position la faisait traiter comme un mot de passe -> « requires encryption ».
    cli = aioesphomeapi.APIClient(host, port, None,
                                  noise_psk=None if key in (None, "", "None") else key)
    await cli.connect(login=True)
    info = await cli.device_info()
    print(f"# connecté à {host}:{port} — {info.name} / {info.model} / esphome {info.esphome_version}", flush=True)

    stop = asyncio.Event()
    t0 = dt.datetime.now().strftime("%H:%M:%S")

    def on_log(msg) -> None:
        try:
            if isinstance(msg, (bytes, bytearray)):
                text = msg.decode("utf-8", "replace")
            else:
                raw = getattr(msg, "message", None)
                if raw is None:
                    raw = getattr(msg, "data", b"")
                text = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
        except Exception as exc:  # pragma: no cover - robustesse agent
            text = f"<log undecodable: {exc}>"
        if not text.strip():
            return
        line = f"[{dt.datetime.now().strftime('%H:%M:%S')}] {text.rstrip()}"
        print(line, flush=True)
        if out is not None:
            out.write(line + "\n")
            out.flush()

    # subscribe_logs n'est PAS une coroutine (elle renvoie une fonction de désabonnement) :
    # un `await` dessus lève « object functools.partial can't be used in 'await' expression ».
    cli.subscribe_logs(on_log, log_level=7)
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass
    await cli.disconnect()
    print(f"# fin de capture (démarrée {t0}, {seconds}s)", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=6053)
    ap.add_argument("--key", default=None, help="clé API base64 (défaut: env ESPHOME_API_KEY ou YAML)")
    ap.add_argument("--seconds", type=float, default=90)
    ap.add_argument("--out", default=None)
    ap.add_argument("--append", action="store_true",
                    help="AJOUTER au fichier au lieu de l'écraser (défaut : écraser). "
                         "Le mode ajout a déjà fait relire une fenêtre précédente comme si elle "
                         "était la nouvelle : un fichier de sortie de capture doit être neuf.")
    args = ap.parse_args()

    key = args.key or os.environ.get("ESPHOME_API_KEY") or key_from_yaml(DEFAULT_YAML)
    out = open(args.out, "a" if args.append else "w", encoding="utf-8") if args.out else None
    try:
        return asyncio.run(run(args.host, args.port, key, args.seconds, out))
    except Exception as exc:
        print(f"# ERREUR capture: {type(exc).__name__}: {exc}", flush=True)
        return 2
    finally:
        if out:
            out.close()


if __name__ == "__main__":
    sys.exit(main())
