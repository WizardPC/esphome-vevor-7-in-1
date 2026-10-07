#!/usr/bin/env python3
"""Presses a NAMED board button and returns the logs of the following window.

Generalizes `dump_pulses.py` (which only presses "Dump pulses"): any named button can be
pressed without reflashing. The exact press time is logged to slice the window.

Usage:
 dev/tools/press_button.py --name "Réappliquer la config radio" [--seconds 300] [--out logs/x.log]

Return codes:
    0  window captured, at least one log line received;
    2  technical failure (connection, button not found, exception);
    3  NULL MEASUREMENT: connection succeeded but NO log line received.
"""
from __future__ import annotations

import os
import argparse
import asyncio
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _common import (RC_ERREUR, RC_MESURE_NULLE, RC_OK,  # noqa: E402
                     atomic_write_text, key_from_yaml, maybe_await)

from aioesphomeapi import APIClient  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("VEVOR_HOST"),
                    required="VEVOR_HOST" not in os.environ,
                    help="board IP address. Fallback: VEVOR_HOST environment variable, or dev/tools/find_esp32.py to discover it")
    ap.add_argument("--key", default=None, help="base64 API key (default: ESPHOME_API_KEY env or YAML)")
    ap.add_argument("--name", required=True, help="exact button name (see --list-buttons)")
    ap.add_argument("--seconds", type=float, default=300.0)
    ap.add_argument("--out", default=None, help="output file (relative = project root)")
    ap.add_argument("--list-buttons", action="store_true")
    args = ap.parse_args()

    key = args.key or key_from_yaml()
    client = APIClient(args.host, 6053, "", noise_psk=key)
    await client.connect(login=True)
    infos, _ = await client.list_entities_services()
    buttons = {getattr(i, "name", ""): i for i in infos if type(i).__name__ == "ButtonInfo"}
    if args.list_buttons:
        for name in sorted(buttons):
            print(f"  {name}")
        await client.disconnect()
        return RC_OK

    button = buttons.get(args.name)
    if button is None:
        print("boutons disponibles :", ", ".join(sorted(buttons)) or "(aucun)", file=sys.stderr)
        await client.disconnect()
        print(f"# ERREUR : bouton « {args.name} » introuvable", file=sys.stderr)
        return RC_ERREUR

    lines: list[str] = []

    def on_log(msg):
        text = msg.message.decode("utf-8", "replace") if isinstance(msg.message, bytes) else msg.message
        lines.append(text)

    await maybe_await(client.subscribe_logs(on_log, log_level=7))
    await asyncio.sleep(1.0)

    t0 = time.strftime("%H:%M:%S", time.gmtime())
    print(f"[{t0} UTC] appui sur « {args.name} »")
    await maybe_await(client.button_command(button.key))

    await asyncio.sleep(args.seconds)
    t1 = time.strftime("%H:%M:%S", time.gmtime())
    print(f"[{t1} UTC] fin de fenêtre ({args.seconds:.0f} s) — {len(lines)} ligne(s) reçue(s)")

    if args.out:
        header = f"# appui « {args.name} » a {t0} UTC, fenetre {args.seconds:.0f} s (fin {t1} UTC)"
        print(f"-> {atomic_write_text(args.out, header + '\n' + '\n'.join(lines) + '\n')}")

    for text in lines:
        if any(k in text for k in ("capture #", "impulsion", "trame extraite", "V7IN1", "GDO0",
                                   "PLL", "cc1101", "CC1101")):
            print("  LOG:", text.strip()[:300])
    await client.disconnect()
    if not lines:
        print("# MESURE NULLE — aucune ligne de log reçue : rien n'a été mesuré", file=sys.stderr)
        return RC_MESURE_NULLE
    return RC_OK


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except SystemExit:
        raise
    except Exception as exc:
        print(f"# ERREUR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(RC_ERREUR)
