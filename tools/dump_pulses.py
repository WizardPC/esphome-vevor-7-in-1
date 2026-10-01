#!/usr/bin/env python3
"""Appuie sur le bouton « Dump impulsions » de la carte et ramène les durées brutes.

Pourquoi un bouton : l'API native ne livre pas l'historique des logs, et les captures des
premières secondes sont déjà passées quand l'API devient joignable. Le composant garde donc une
demande en attente (`request_raw_dump()`) et journalise, pour la PROCHAINE capture, ses 64
premières durées en clair — seule façon d'analyser le flux réel depuis l'extérieur.

Usage :
    tools/dump_pulses.py [--host 172.16.0.205] [--seconds 45] [--out logs/dump_pulses.log]
"""
from __future__ import annotations

import argparse
import asyncio
import inspect
import pathlib
import re

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
    ap.add_argument("--seconds", type=float, default=45.0)
    ap.add_argument("--out", default="logs/dump_pulses.log")
    args = ap.parse_args()

    client = APIClient(args.host, 6053, "", noise_psk=key_from_yaml(ROOT / "esphome" / "secrets.yaml"))
    await client.connect(login=True)
    infos, _ = await client.list_entities_services()
    by_name = {getattr(i, "name", ""): i for i in infos}

    lines: list[str] = []
    latest: dict[int, object] = {}

    def on_log(msg):
        text = msg.message.decode("utf-8", "replace") if isinstance(msg.message, bytes) else msg.message
        lines.append(text)

    def on_state(state):
        latest[state.key] = state

    await maybe_await(client.subscribe_logs(on_log, log_level=7))
    await maybe_await(client.subscribe_states(on_state))
    await asyncio.sleep(1)

    button = by_name.get("Dump impulsions")
    if button is None:
        raise SystemExit("bouton « Dump impulsions » introuvable (firmware à reflasher ?)")
    await maybe_await(client.button_command(button.key))
    print("bouton « Dump impulsions » appuyé — attente de la prochaine capture…")

    await asyncio.sleep(args.seconds)

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")

    for name in ("Fréquence CC1101", "Captures RMT", "Trames valides", "Trames rejetées",
                 "Doublons ignorés"):
        ent = by_name.get(name)
        st = latest.get(ent.key) if ent is not None else None
        print(f"  {name:20s} = {getattr(st, 'state', '(jamais publié)')}")

    for text in lines:
        if any(k in text for k in ("capture #", "impulsions", "trame extraite", "V7IN1",
                                   "GDO0", "PLL", "RX state")):
            print("  LOG:", text.strip()[:300])
    print(f"-> {out}")
    await client.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
