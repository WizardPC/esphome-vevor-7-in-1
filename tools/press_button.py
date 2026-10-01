#!/usr/bin/env python3
"""Appuie sur un bouton NOMMÉ de la carte et ramène les logs de la fenêtre qui suit.

Généralisation de `dump_pulses.py` : celui-ci n'appuie que sur « Dump impulsions ». Or
« Réappliquer la config radio » est le seul levier à chaud pour trancher « l'état de la puce est
fautif » contre « le chemin RF a changé » — sans reflasher. Le script note aussi l'heure exacte de
l'appui (témoin d'horodatage utilisé pour découper la fenêtre avant/après).

Usage:
    tools/press_button.py --name "Réappliquer la config radio" [--seconds 300] [--out logs/x.log]
"""
from __future__ import annotations

import argparse
import asyncio
import inspect
import pathlib
import re
import time

from aioesphomeapi import APIClient

ROOT = pathlib.Path(__file__).resolve().parent.parent


def key_from_yaml(path: pathlib.Path) -> str:
    m = re.search(r"api_key:\s*(\S+)", path.read_text(encoding="utf-8"))
    if not m:
        raise SystemExit("api_key introuvable dans secrets.yaml")
    return m.group(1).strip("\"'")


async def maybe_await(value):
    return await value if inspect.isawaitable(value) else value


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="172.16.0.205")
    ap.add_argument("--name", required=True, help="nom exact du bouton (voir --list-buttons)")
    ap.add_argument("--seconds", type=float, default=300.0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--list-buttons", action="store_true")
    args = ap.parse_args()

    client = APIClient(args.host, 6053, "", noise_psk=key_from_yaml(ROOT / "esphome" / "secrets.yaml"))
    await client.connect(login=True)
    infos, _ = await client.list_entities_services()
    buttons = {getattr(i, "name", ""): i for i in infos if type(i).__name__ == "ButtonInfo"}
    if args.list_buttons:
        for name in sorted(buttons):
            print(f"  {name}")
        await client.disconnect()
        return 0

    button = buttons.get(args.name)
    if button is None:
        print("boutons disponibles :", ", ".join(sorted(buttons)) or "(aucun)")
        raise SystemExit(f"bouton « {args.name} » introuvable")

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
    print(f"[{t1} UTC] fin de fenêtre ({args.seconds:.0f} s)")

    if args.out:
        out = ROOT / args.out
        out.parent.mkdir(parents=True, exist_ok=True)
        header = f"# appui « {args.name} » a {t0} UTC, fenetre {args.seconds:.0f} s (fin {t1} UTC)\n"
        out.write_text(header + "\n".join(lines), encoding="utf-8")
        print(f"-> {out}")

    for text in lines:
        if any(k in text for k in ("capture #", "impulsion", "trame extraite", "V7IN1", "GDO0",
                                   "PLL", "cc1101", "CC1101")):
            print("  LOG:", text.strip()[:300])
    await client.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
