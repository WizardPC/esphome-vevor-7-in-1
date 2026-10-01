#!/usr/bin/env python3
"""Balaye la fréquence du CC1101 en direct via l'API native ESPHome et mesure le signal.

C'est l'outil d'autonomie principal : il n'y a PAS besoin de recompiler/reflasher pour
chercher la station. On pilote l'entité `number` « Fréquence CC1101 » du firmware, et on
lit le nombre de trames reçues (valides + rejetées) et le RSSI pendant chaque palier.

Usage:
    scan_freq.py --host 192.168.2.50 [--key CLE] [--start 867.8 --stop 868.6 --step 0.05]
                 [--dwell 25] [--out scan.json]
    scan_freq.py --host 192.168.2.50 --list          # liste les entités exposées
    scan_freq.py --host 192.168.2.50 --set 868.30    # règle juste la fréquence

Un palier doit durer au moins ~25 s : la station n'émet qu'une rafale toutes les 20 s.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import pathlib
import re
import statistics
import sys
import time

import aioesphomeapi

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_YAML = ROOT / "esphome" / "vevor-7in1.yaml"

# ANCRÉ au début du nom, volontairement : `fr[ée]quence` sans ancre matchait aussi
# « Offset fréquence » (un capteur), et `key_of()` prend le premier nom qui correspond dans
# l'ordre de livraison des entités. Un `number_command` envoyé à la clé d'un capteur est
# silencieusement ignoré par l'appareil : le réglage de fréquence ne faisait RIEN, sans aucune
# erreur. Ne jamais désancrer ce motif.
FREQ_NAME_RE = re.compile(r"^\s*fr[ée]quence", re.I)  # « Fréquence CC1101 »
VALID_RE = re.compile(r"trames valides", re.I)
REJECT_RE = re.compile(r"trames rejet", re.I)
RSSI_RE = re.compile(r"rssi", re.I)


def key_from_yaml() -> str | None:
    """Clé de chiffrement de l'API : lue dans le YAML en résolvant `!secret <nom>`.

    Le YAML ne contient que `key: !secret api_key` : la valeur est dans esphome/secrets.yaml.
    """
    if not DEFAULT_YAML.exists():
        return None
    text = DEFAULT_YAML.read_text(encoding="utf-8", errors="replace")
    # Même piège que dans capture_logs.py : `(\S+)` ne prenait que le premier mot, donc
    # "!secret" seul au lieu de "!secret api_key".
    m = re.search(r"encryption:\s*\n(?:[ \t].*\n)*?[ \t]+key:\s*(.+?)\s*$", text, re.M)
    if not m:
        return None
    val = m.group(1).strip().strip("\"'")
    if val.startswith("!secret"):
        parts = val.split(None, 1)
        name = parts[1] if len(parts) > 1 else ""
        secrets = DEFAULT_YAML.parent / "secrets.yaml"
        if name and secrets.exists():
            sm = re.search(rf"^{re.escape(name)}:\s*(\S+)",
                           secrets.read_text(encoding="utf-8", errors="replace"), re.M)
            if sm:
                return sm.group(1).strip().strip("\"'")
        return None
    return val or None


class Device:
    def __init__(self, host: str, port: int, key: str | None):
        self.host, self.port, self.key = host, port, key
        # noise_psk = chiffrement ESPHome ; passer la clé en 3e position la traitait comme un
        # mot de passe -> « Connection requires encryption ».
        self.cli = aioesphomeapi.APIClient(
            host, port, None, noise_psk=None if key in (None, "", "None") else key
        )
        self.state: dict[int, float] = {}
        self.keys: dict[str, int] = {}

    async def __aenter__(self) -> "Device":
        await self.cli.connect(login=True)
        info = await self.cli.device_info()
        self.info = info
        entities, _ = await self.cli.list_entities_services()
        for e in entities:
            name = getattr(e, "name", "") or ""
            self.keys[name] = e.key
            if hasattr(e, "state"):
                self.state[e.key] = e.state
        self.cli.subscribe_states(lambda s: self.state.__setitem__(s.key, getattr(s, "state", None)))
        return self

    async def __aexit__(self, *exc) -> None:
        await self.cli.disconnect()

    def key_of(self, pattern: re.Pattern) -> int | None:
        for name, k in self.keys.items():
            if pattern.search(name):
                return k
        return None

    def get(self, name: str) -> float | None:
        k = self.keys.get(name)
        return self.state.get(k) if k is not None else None

    def set_freq(self, mhz: float) -> None:
        k = self.key_of(FREQ_NAME_RE)
        if k is None:
            raise SystemExit("entité « Fréquence CC1101 » introuvable — firmware à jour ? (--list)")
        self.cli.number_command(k, mhz)

    def counts(self) -> tuple[float, float, float | None]:
        # NaN = capteur jamais publié (aucune trame depuis le démarrage) : à traiter comme 0,
        # sinon int(NaN) fait planter le palier (ValueError: cannot convert float NaN to integer).
        def num(v) -> float:
            try:
                return 0.0 if v is None or math.isnan(float(v)) else float(v)
            except (TypeError, ValueError):
                return 0.0

        rssi = self.get("RSSI")
        try:
            if rssi is None or math.isnan(float(rssi)):
                rssi = None
        except (TypeError, ValueError):
            rssi = None
        return num(self.get("Trames valides")), num(self.get("Trames rejetées")), rssi


async def do_list(dev: Device) -> None:
    print(f"# {dev.info.name} — esphome {dev.info.esphome_version}")
    for name, k in sorted(dev.keys.items()):
        print(f"{k:>6}  {name}")


async def do_set(dev: Device, mhz: float) -> None:
    dev.set_freq(mhz)
    await asyncio.sleep(1.5)
    # Contrôle de l'écriture : sans lui, une commande perdue (mauvaise clé d'entité) était
    # annoncée comme réussie. L'entité est `optimistic: true`, donc si elle ne relit pas la
    # valeur demandée, c'est que la commande n'est pas arrivée.
    got = dev.get("Fréquence CC1101")
    print(f"# fréquence réglée sur {mhz} MHz — entité relue : {got}")
    if got is None or abs(float(got) - mhz) > 0.001:
        print(f"# ATTENTION : la carte n'a pas pris la valeur (lue {got}) — voir FREQ_NAME_RE",
              file=sys.stderr)
        return 0


async def scan(dev: Device, start: float, stop: float, step: float, dwell: float, settle: float) -> list[dict]:
    freqs = []
    f = start
    while f <= stop + 1e-9:
        freqs.append(round(f, 4))
        f += step
    results = []
    for mhz in freqs:
        dev.set_freq(mhz)
        await asyncio.sleep(settle)
        v0, r0, _ = dev.counts()
        rssis: list[float] = []
        t_end = time.monotonic() + dwell
        while time.monotonic() < t_end:
            await asyncio.sleep(0.5)
            r = dev.get("RSSI")
            try:
                if r is not None and not math.isnan(float(r)):
                    rssis.append(float(r))
            except (TypeError, ValueError):
                pass
        v1, r1, _ = dev.counts()
        row = {
            "freq_mhz": mhz,
            "frames": (v1 - v0) + (r1 - r0),
            "valid": v1 - v0,
            "rejected": r1 - r0,
            "rssi_max": round(max(rssis), 1) if rssis else None,
            "rssi_mean": round(statistics.fmean(rssis), 1) if rssis else None,
        }
        results.append(row)
        print(
            f"{mhz:8.3f} MHz  trames={int(row['frames']):3d} "
            f"(valides={int(row['valid']):3d} rejetées={int(row['rejected']):3d})  "
            f"rssi_max={row['rssi_max']}  rssi_moy={row['rssi_mean']}",
            flush=True,
        )
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=6053)
    ap.add_argument("--key", default=None)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--set", type=float, dest="set_mhz")
    ap.add_argument("--start", type=float, default=867.8)
    ap.add_argument("--stop", type=float, default=868.6)
    ap.add_argument("--step", type=float, default=0.05)
    ap.add_argument("--dwell", type=float, default=25.0, help="secondes par palier (>=25 recommandé)")
    ap.add_argument("--settle", type=float, default=1.0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    key = args.key or os.environ.get("ESPHOME_API_KEY") or key_from_yaml()

    async def run() -> list[dict]:
        async with Device(args.host, args.port, key) as dev:
            if args.list:
                await do_list(dev)
                return []
            if args.set_mhz is not None:
                await do_set(dev, args.set_mhz)
                return []
            return await scan(dev, args.start, args.stop, args.step, args.dwell, args.settle)

    try:
        rows = asyncio.run(run())
    except Exception as exc:
        print(f"# ERREUR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if rows:
        best = max(rows, key=lambda r: (r["frames"], -(r["rssi_mean"] or -999)))
        print(f"\n# meilleur palier: {best['freq_mhz']} MHz "
              f"({int(best['frames'])} trames, rssi_moy={best['rssi_mean']})")
        total = sum(r["frames"] for r in rows)
        if total == 0:
            print("# AUCUN signal sur toute la plage : vérifier SPI/alim, puis déviation, "
                  "bande passante, syncword, câblage et antenne (voir MISSION.md § ordre de diagnostic)")
        if args.out:
            pathlib.Path(args.out).write_text(json.dumps({"rows": rows, "best": best}, indent=2), encoding="utf-8")
            print(f"# rapport écrit: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
