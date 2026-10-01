#!/usr/bin/env python3
"""Réécrit explicitement la fréquence du CC1101 depuis l'API, puis ramène les logs de la fenêtre.

Pourquoi : dans l'état « puce présente et prête mais aucune trame décodée » (CHIP_RDYn bas,
Chip ID 0x0014 lu du premier coup), le suspect restant est que la configuration radio ne soit pas
appliquée correctement — registres de fréquence écrits de travers, puce en RX mais pas sur 868,35 MHz.
Cette commande passe par un chemin INDÉPENDANT du démarrage : elle force une écriture fraîche de la
fréquence (action `set_frequency` du composant), sans reflasher et sans redémarrer.

Usage: tools/regler_frequence.py [--mhz 868.35] [--seconds 150]
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from capture_logs import key_from_yaml  # noqa: E402  (résolution de la clé API, une seule copie)

from aioesphomeapi import APIClient  # noqa: E402


async def run(host: str, port: int, key: str, mhz: float, seconds: float) -> int:
    cli = APIClient(host, port, None, noise_psk=key)
    await cli.connect(login=True)
    entities, _ = await cli.list_entities_services()
    cible = None
    for e in entities:
        nom = getattr(e, "name", "")
        if "quence CC1101" in nom:
            cible = e
            break
    if cible is None:
        print("!! entité « Fréquence CC1101 » introuvable", file=sys.stderr)
        for e in entities:
            print("   -", getattr(e, "name", "?"), file=sys.stderr)
        await cli.disconnect()
        return 2

    def horodate(txt: str) -> str:
        return f"[{datetime.datetime.now(datetime.timezone.utc):%H:%M:%S}] {txt}"

    def sur_log(message) -> None:
        print(horodate(message.message.decode(errors="replace")[:170]), flush=True)

    cli.subscribe_logs(sur_log)
    await asyncio.sleep(2)
    print(horodate(f"réglage de {cible.name} = {mhz} MHz (écriture fraîche des registres FREQ2/1/0)"))
    await cli.number_command(cible.key, mhz)
    await asyncio.sleep(seconds)
    await cli.disconnect()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="172.16.0.205")
    ap.add_argument("--port", type=int, default=6053)
    ap.add_argument("--yaml", default="esphome/vevor-7in1.yaml")
    ap.add_argument("--mhz", type=float, default=868.35)
    ap.add_argument("--seconds", type=float, default=150)
    args = ap.parse_args()
    key = key_from_yaml(pathlib.Path(args.yaml))
    return asyncio.run(run(args.host, args.port, key, args.mhz, args.seconds))


if __name__ == "__main__":
    sys.exit(main())
