#!/usr/bin/env python3
"""Capture les logs d'un ESP32 ESPHome via l'API native (port 6053) pendant N secondes.

Usage:
    capture_logs.py --host 192.168.2.50 --seconds 90 [--key CLE_BASE64] [--out fichier.log]

Sans --key, utilise $ESPHOME_API_KEY ou la clé lue dans le YAML du projet
(voir `_common.key_from_yaml`, qui résout `!secret`).
Écrit sur stdout ET, si --out est donné, dans le fichier (écrasé par défaut, --append pour
ajouter). Le fichier est écrit de façon ATOMIQUE (temporaire + os.replace) : jamais de log
tronqué si la capture est interrompue. Un chemin --out relatif vise la RACINE du projet.

Sortie adaptée à un agent : une ligne par message de log, horodatée.

Code retour :
    0  capture faite, au moins une ligne de log reçue (résultat négatif inclus) ;
    2  échec technique (connexion API, exception) ;
    3  MESURE NULLE : connexion réussie mais AUCUNE ligne de log reçue (le firmware émet un
       battement de cœur toutes les 20 s — 0 ligne est anormal, ce n'est pas « aucun signal »).
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _common import (RC_ERREUR, RC_MESURE_NULLE, RC_OK,  # noqa: E402
                     atomic_write_text, out_path, resolve_key)

import aioesphomeapi  # noqa: E402


async def run(host: str, port: int, key: str | None, seconds: float) -> tuple[int, list[str]]:
    # Le chiffrement ESPHome passe par noise_psk (mot-clé) ; `password` est l'ancien auth en clair.
    # Passer la clé en 3e position la faisait traiter comme un mot de passe -> « requires encryption ».
    cli = aioesphomeapi.APIClient(host, port, None,
                                  noise_psk=None if key in (None, "", "None") else key)
    await cli.connect(login=True)
    info = await cli.device_info()
    header = f"# connecté à {host}:{port} — {info.name} / {info.model} / esphome {info.esphome_version}"
    print(header, flush=True)

    stop = asyncio.Event()
    t0 = dt.datetime.now().strftime("%H:%M:%S")
    lines: list[str] = []

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
        lines.append(line)

    # subscribe_logs n'est PAS une coroutine (elle renvoie une fonction de désabonnement) : un
    # `await` dessus lève « object functools.partial can't be used in 'await' expression ».
    cli.subscribe_logs(on_log, log_level=7)
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass
    await cli.disconnect()
    tail = f"# fin de capture (démarrée {t0}, {seconds}s) — {len(lines)} ligne(s) de log reçue(s)"
    print(tail, flush=True)
    return (RC_OK if lines else RC_MESURE_NULLE), [header, *lines, tail]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=6053)
    ap.add_argument("--key", default=None, help="clé API base64 (défaut: env ESPHOME_API_KEY ou YAML)")
    ap.add_argument("--seconds", type=float, default=90)
    ap.add_argument("--out", default=None, help="fichier de sortie (relatif = racine du projet)")
    ap.add_argument("--append", action="store_true",
                    help="AJOUTER au fichier au lieu de l'écraser (défaut : écraser). "
                         "Le mode ajout a déjà fait relire une fenêtre précédente comme si elle "
                         "était la nouvelle : un fichier de sortie de capture doit être neuf.")
    args = ap.parse_args()

    try:
        key = resolve_key(args.key)
        rc, lines = asyncio.run(run(args.host, args.port, key, args.seconds))
    except SystemExit:
        raise
    except Exception as exc:
        print(f"# ERREUR capture: {type(exc).__name__}: {exc}", flush=True)
        return RC_ERREUR

    if args.out:
        p = out_path(args.out)
        body = "\n".join(lines) + "\n"
        if args.append and p.exists():
            body = p.read_text(encoding="utf-8", errors="replace") + body
        atomic_write_text(p, body)
        print(f"# fichier écrit (atomique) : {p}")

    if rc == RC_MESURE_NULLE:
        print("# MESURE NULLE — connexion établie mais AUCUNE ligne de log reçue : "
              "rien n'a été mesuré", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
