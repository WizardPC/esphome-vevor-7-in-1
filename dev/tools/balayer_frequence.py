#!/usr/bin/env python3
"""Frequency sweep of the CC1101: is the chip offset (marginal crystal) or in a wrong state?

In the state "chip present, ready, configured, but no frame decoded", two causes must be told
apart: a FREQUENCY OFFSET (a swept value brings frames back, and the winning offset is fixable in
code) or a WRONG CHIP STATE (no value yields a frame). Each frequency is set in turn
(`set_frequency`, a fresh write of FREQ2/1/0), read back from the entity, and the frames the
firmware publishes during the window are counted.

Usage: tools/balayer_frequence.py [--mhz 868.35,868.30,868.40,868.25,868.45] [--seconds 60]

Return codes: 0 measurement done ("no frame" is a negative result); 2 technical error
(connection, missing entity, frequency write not taken); 3 empty measurement (no log received).
"""
from __future__ import annotations

import os
import argparse
import asyncio
import datetime
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _common import (FREQ_RE, RC_ERREUR, RC_MESURE_NULLE, RC_OK,  # noqa: E402
                     key_from_yaml)

from aioesphomeapi import APIClient  # noqa: E402


def horodate() -> str:
    return f"[{datetime.datetime.now(datetime.timezone.utc):%H:%M:%S}]"


async def run(host: str, port: int, key: str, frequences: list[float], seconds: float) -> int:
    cli = APIClient(host, port, None, noise_psk=key)
    await cli.connect(login=True)
    entities, _ = await cli.list_entities_services()

    # Anchored entity (FREQ_RE): the "Offset" sensor must NOT match.
    cible = None
    for e in entities:
        if FREQ_RE.search(getattr(e, "name", "") or ""):
            cible = e
            break
    if cible is None:
        print("!! entity \"CC1101 frequency\" not found", file=sys.stderr)
        await cli.disconnect()
        return RC_ERREUR
    etats = {e.key: getattr(e, "state", None) for e in entities if hasattr(e, "state")}

    # Counter resets on each frequency change: the log is authoritative.
    compteur = {"trames": 0, "logs": 0}

    def sur_log(message) -> None:
        compteur["logs"] += 1
        texte = message.message.decode(errors="replace") if isinstance(message.message, bytes) else str(message.message)
        if "V7IN1 OK" in texte:
            compteur["trames"] += 1
            print(f"  {horodate()} FRAME {texte[:150]}", flush=True)

    def sur_etat(state) -> None:
        etats[state.key] = getattr(state, "state", None)

    cli.subscribe_logs(sur_log)
    cli.subscribe_states(sur_etat)
    await asyncio.sleep(2)

    resultats = []
    ecritures_ratees = 0
    for mhz in frequences:
        compteur["trames"] = 0
        print(f"{horodate()} frequency {mhz} MHz — window {seconds:.0f} s", flush=True)
        cli.number_command(cible.key, mhz)   # synchronous command (no await)
        await asyncio.sleep(1.5)
        # Read-back check: a lost command must not count as a valid step.
        got = etats.get(cible.key)
        try:
            pris = got is not None and abs(float(got) - mhz) <= 0.001
        except (TypeError, ValueError):
            pris = False
        if not pris:
            ecritures_ratees += 1
            print(f"{horodate()} !! the board did NOT take {mhz} MHz (read back {got!r})", file=sys.stderr)
        await asyncio.sleep(seconds)
        resultats.append((mhz, compteur["trames"]))
        print(f"{horodate()} {mhz} MHz : {compteur['trames']} frame(s)", flush=True)

    print("\n=== bilan du balayage ===")
    for mhz, n in resultats:
        print(f"  {mhz} MHz : {n} trame(s)")
    gagnante = max(resultats, key=lambda r: r[1])
    if gagnante[1] == 0:
        print("  NO frame on any frequency (measurement done) → the chip is not merely "
              "detuned: it is its STATE (configuration not applied) that must be fixed, not the tuning.")
    elif gagnante[0] == frequences[0]:
        print(f"  The reference frequency ({gagnante[0]} MHz) stays the right one → no crystal offset.")
    else:
        print(f"  Offset: {gagnante[0]} MHz decodes better than {frequences[0]} MHz "
              f"({gagnante[1]} vs {resultats[0][1]} frame(s)) → detuned crystal, to fix in code.")
    await cli.disconnect()

    if ecritures_ratees == len(frequences):
        print("# ERROR: NO frequency write was accepted — nothing was swept",
              file=sys.stderr)
        return RC_ERREUR
    if compteur["logs"] == 0:
        print("# NULL MEASUREMENT — no log received: nothing was measured", file=sys.stderr)
        return RC_MESURE_NULLE
    return RC_OK


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("VEVOR_HOST"),
                    required="VEVOR_HOST" not in os.environ,
                    help="board IP address. Otherwise: VEVOR_HOST env var, or "
                         "dev/tools/find_esp32.py to discover it")
    ap.add_argument("--port", type=int, default=6053)
    ap.add_argument("--yaml", default="esphome/vevor-7in1.yaml")
    ap.add_argument("--mhz", default="868.35,868.30,868.40,868.25,868.45")
    ap.add_argument("--seconds", type=float, default=60)
    args = ap.parse_args()
    frequences = [float(x) for x in args.mhz.split(",")]
    try:
        key = key_from_yaml(pathlib.Path(args.yaml))
        return asyncio.run(run(args.host, args.port, key, frequences, args.seconds))
    except SystemExit:
        raise
    except Exception as exc:
        print(f"# ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return RC_ERREUR


if __name__ == "__main__":
    sys.exit(main())
