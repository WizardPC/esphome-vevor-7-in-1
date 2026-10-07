#!/usr/bin/env python3
"""Press the board's "Dump pulses" button and return the raw durations.

The native API does not replay log history, and the first seconds' captures are already past by
the time the API is reachable. The component keeps a pending request (`request_raw_dump()`) and
logs, for the NEXT capture, its first 64 durations — the only way to analyse the real stream from
outside.

Usage:
 dev/tools/dump_pulses.py [--host <board-ip>] [--seconds 45] [--out logs/dump_pulses.log]
"""
from __future__ import annotations

import os
import argparse
import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _common import (atomic_write_text, key_from_yaml,  # noqa: E402
                     maybe_await)

from aioesphomeapi import APIClient


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("VEVOR_HOST"),
                    required="VEVOR_HOST" not in os.environ,
                   help="board IP address. Otherwise: VEVOR_HOST env var, or "
                        "dev/tools/find_esp32.py to discover it")
    ap.add_argument("--seconds", type=float, default=45.0)
    ap.add_argument("--out", default="logs/dump_pulses.log")
    args = ap.parse_args()

    client = APIClient(args.host, 6053, "", noise_psk=key_from_yaml())
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

    button = by_name.get("Dump pulses")
    if button is None:
        raise SystemExit("button \"Dump pulses\" not found (firmware to reflash?)")
    await maybe_await(client.button_command(button.key))
    print("button \"Dump pulses\" pressed — waiting for the next capture…")

    await asyncio.sleep(args.seconds)

    out = atomic_write_text(args.out, "\n".join(lines))

    for name in ("CC1101 frequency", "RMT captures", "Valid frames", "Rejected frames",
                 "Duplicates ignored"):
        ent = by_name.get(name)
        st = latest.get(ent.key) if ent is not None else None
        print(f"  {name:20s} = {getattr(st, 'state', '(never published)')}")

    for text in lines:
        if any(k in text for k in ("capture #", "pulses", "trame extraite", "V7IN1",
                                   "GDO0", "PLL", "RX state")):
            print("  LOG:", text.strip()[:300])
    print(f"-> {out}")
    await client.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
