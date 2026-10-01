#!/usr/bin/env python3
"""Balayage de fréquence du CC1101 : la puce est-elle décalée (quartz marginal) ou dans un état faux ?

Pourquoi cet outil : dans l'état « puce présente, prête, configurée, mais aucune trame décodée », il
faut départager deux causes qui se ressemblent :
  - un DÉCALAGE DE FRÉQUENCE (quartz imprécis ou qui dérive) → une des valeurs balayées doit faire
    revenir les trames, et le décalage gagnant est alors corrigeable en code ;
  - un ÉTAT DE PUCE FAUX (configuration non appliquée) → aucune valeur ne donne de trame.
Il programme tour à tour chaque fréquence (action `set_frequency`, donc écriture fraîche des
registres FREQ2/1/0) et compte, pour chacune, les trames publiées par le firmware pendant la fenêtre.

Usage: tools/balayer_frequence.py [--mhz 868.35,868.30,868.40,868.25,868.45] [--seconds 60]
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from capture_logs import key_from_yaml  # noqa: E402

from aioesphomeapi import APIClient  # noqa: E402


def horodate() -> str:
    return f"[{datetime.datetime.now(datetime.timezone.utc):%H:%M:%S}]"


async def run(host: str, port: int, key: str, frequences: list[float], seconds: float) -> int:
    cli = APIClient(host, port, None, noise_psk=key)
    await cli.connect(login=True)
    entities, _ = await cli.list_entities_services()

    cible = next((e for e in entities if "quence CC1101" in getattr(e, "name", "")), None)
    if cible is None:
        print("!! entité « Fréquence CC1101 » introuvable", file=sys.stderr)
        await cli.disconnect()
        return 2

    # Le compteur est remis à zéro à chaque changement de fréquence : c'est le log qui fait foi.
    compteur = {"trames": 0}

    def sur_log(message) -> None:
        texte = message.message.decode(errors="replace")
        if "V7IN1 OK" in texte:
            compteur["trames"] += 1
            print(f"  {horodate()} TRAME {texte[:150]}", flush=True)

    cli.subscribe_logs(sur_log)
    await asyncio.sleep(2)

    resultats = []
    for mhz in frequences:
        compteur["trames"] = 0
        print(f"{horodate()} fréquence {mhz} MHz — fenêtre {seconds:.0f} s", flush=True)
        cli.number_command(cible.key, mhz)   # commande SYNCHRONE (pas de await)
        await asyncio.sleep(seconds)
        resultats.append((mhz, compteur["trames"]))
        print(f"{horodate()} {mhz} MHz : {compteur['trames']} trame(s)", flush=True)

    print(f"\n=== bilan du balayage ===")
    for mhz, n in resultats:
        print(f"  {mhz} MHz : {n} trame(s)")
    gagnante = max(resultats, key=lambda r: r[1])
    if gagnante[1] == 0:
        print("  AUCUNE fréquence ne décode → la puce n'est pas simplement décalée : c'est son ÉTAT "
              "(configuration non appliquée) qu'il faut corriger, pas le calage.")
    elif gagnante[0] == frequences[0]:
        print(f"  La fréquence de référence ({gagnante[0]} MHz) reste la bonne → pas de décalage de quartz.")
    else:
        print(f"  Décalage : {gagnante[0]} MHz décode mieux que {frequences[0]} MHz "
              f"({gagnante[1]} contre {resultats[0][1]} trame(s)) → quartz décalé, à corriger en code.")
    await cli.disconnect()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="172.16.0.205")
    ap.add_argument("--port", type=int, default=6053)
    ap.add_argument("--yaml", default="esphome/vevor-7in1.yaml")
    ap.add_argument("--mhz", default="868.35,868.30,868.40,868.25,868.45")
    ap.add_argument("--seconds", type=float, default=60)
    args = ap.parse_args()
    frequences = [float(x) for x in args.mhz.split(",")]
    key = key_from_yaml(pathlib.Path(args.yaml))
    return asyncio.run(run(args.host, args.port, key, frequences, args.seconds))


if __name__ == "__main__":
    sys.exit(main())
