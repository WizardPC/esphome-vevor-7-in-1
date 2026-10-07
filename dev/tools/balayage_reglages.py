#!/usr/bin/env python3
"""LIVE sweep of a radio setting: which rate, which deviation, which filter decodes best?

Two unknowns of the radio chain were never settled:
  * the RATE: 11111 baud configured vs 11312 measured on the frames (88.4 µs period);
  * the DEVIATION: 70 kHz for us vs 37 kHz in the rtl_433 reference — a contradiction never
    resolved, and possibly moot if the register has no effect on reception.
The driver registers cc1101.set_symbol_rate / set_fsk_deviation / set_filter_bandwidth: a setting
changes WITHOUT recompiling, as long as the matching entity is declared in the YAML.

Main metric: the DECODE RATIO (frames / bursts), continuous and insensitive to position in
time. Secondary: rejects, repairs, the gap between frames (the station emits every 20 s) and
the state of the internal counters published by the board.

Each value is set, READ BACK (a write that was not taken must not count as a trial), left to
settle, then sampled. The starting value is restored at the end, whatever happens.

Outputs: dev/state/balayage_<label>.jsonl and .log
Usage:
  balayage_reglages.py --reglage "Data rate" --valeurs 11111,11200,11312,11400 --secondes 150
  balayage_reglages.py --serie            # the three settings in a row, default values
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import DEV, ROOT, PY, resolve_key, maybe_await  # noqa: E402

HOTE = os.environ.get("VEVOR_HOST") or "172.16.0.205"
PORT = 6053
ETAT = DEV / "state"

RE_TRAME = re.compile(r"V7IN1 OK (\{.*\})")
RE_COMPTEURS = re.compile(
    r"captures=(\d+) \(\+(\d+)\), frames=(\d+), rejects=(\d+), repaired=(\d+)"
    r"(?: \((?:dont )?(\d+) refus(?:ées|ed)\))?.*(?:dernières|last) pulses=(\d+), longest=(\d+)")
CAPTEURS = {"rmt captures": "captures", "valid frames": "trames",
            "rejected frames": "rejets", "duplicates ignored": "duplicates"}

# (entity name, values to try, seconds per value, unit)
SERIE = [
    ("Data rate", [11111, 11200, 11312, 11400, 11000], 150),
    ("FSK deviation", [70, 37, 50, 90, 100], 150),
    ("RX filter bandwidth", [100, 162, 203, 232, 58], 150),
]


class Balayage:
    def __init__(self, etiquette: str):
        self.jsonl = open(ETAT / f"balayage_{etiquette}.jsonl", "a", buffering=1)
        self.log = open(ETAT / f"balayage_{etiquette}.log", "a", buffering=1)
        self.noms_cles: dict[int, str] = {}
        self.cles: dict[str, int] = {}
        self.compteurs: dict[str, int] = {}
        self.trames = 0
        self.derniere_trame = 0.0
        self.ecarts: list[float] = []

    def note(self, **kw) -> None:
        kw = {"t": round(time.time(), 3),
              "h": datetime.datetime.now().strftime("%H:%M:%S"), **kw}
        self.jsonl.write(json.dumps(kw, ensure_ascii=False) + "\n")

    def sur_log(self, reponse) -> None:
        try:
            texte = (reponse.message.decode("utf8", "replace")
                     if isinstance(reponse.message, (bytes, bytearray)) else str(reponse.message))
        except Exception:                                        # pragma: no cover
            return
        for ligne in texte.splitlines():
            self.log.write(ligne + "\n")
            if RE_TRAME.search(ligne):
                self.trames += 1
                if self.derniere_trame:
                    self.ecarts.append(round(time.time() - self.derniere_trame, 1))
                self.derniere_trame = time.time()
            m = RE_COMPTEURS.search(ligne)
            if m:
                self.compteurs.update(captures=int(m.group(1)), trames_c=int(m.group(3)),
                                      rejects=int(m.group(4)), reparees=int(m.group(5)),
                                      pulses=int(m.group(7)))

    def sur_etat(self, etat) -> None:
        nom = (self.noms_cles.get(etat.key, "") or "").strip().lower()
        if nom in CAPTEURS:
            try:
                self.compteurs[CAPTEURS[nom]] = int(float(etat.state))
            except (TypeError, ValueError):
                pass

    def instantane(self) -> dict:
        return dict(self.compteurs)


async def balayer(reglage: str, valeurs: list[float], secondes: float, etiquette: str) -> int:
    import aioesphomeapi
    b = Balayage(etiquette)
    cle_api = resolve_key()

    async def connecter():
        """A connected client, or None. The mode is detected once (plain then encrypted)."""
        for psk, nom in ((None, "plain"), (cle_api, "encrypted")):
            essai = aioesphomeapi.APIClient(HOTE, PORT, None, noise_psk=psk)
            try:
                await asyncio.wait_for(essai.connect(login=True), 25)
                print(f"[mode] API as {nom}", flush=True)
                return essai
            except Exception as exc:
                print(f"[mode] {nom} refused: {exc!r}"[:140], flush=True)
                try:
                    await asyncio.wait_for(essai.disconnect(force=True), 8)
                except Exception:
                    pass
        return None

    async def rejoindre():
        """(re)connection + subscriptions. MUST NEVER let the tool die: on 05/10 the series
        stopped on "Not connected" and two full runs were lost."""
        essai = await connecter()
        if essai is None:
            return None, None
        try:
            ent, _ = await asyncio.wait_for(essai.list_entities_services(), 25)
        except Exception as exc:
            print(f"!! entity list unavailable: {exc!r}"[:140], flush=True)
            try:
                await asyncio.wait_for(essai.disconnect(force=True), 8)
            except Exception:
                pass
            return None, None
        b.noms_cles = {e.key: (getattr(e, "name", "") or "") for e in ent}
        cible = next((e for e in ent
                      if (getattr(e, "name", "") or "").strip().lower() == reglage.strip().lower()),
                     None)
        etats: dict[int, float] = {}

        def sur_etat(etat) -> None:
            etats[etat.key] = getattr(etat, "state", None)
            b.sur_etat(etat)

        try:
            await maybe_await(essai.subscribe_states(sur_etat))
            try:
                from aioesphomeapi.model import LogLevel
                niveau = LogLevel.LOG_LEVEL_DEBUG
            except Exception:                                     # pragma: no cover
                niveau = 5
            await maybe_await(essai.subscribe_logs(b.sur_log, log_level=niveau))
        except Exception as exc:
            print(f"!! subscriptions unavailable: {exc!r}"[:140], flush=True)
        return essai, (cible, etats)

    cli = None
    cible = etats = None
    for tentative in range(12):
        cli, paquet = await rejoindre()
        if cli is not None and paquet is not None:
            cible, etats = paquet
            break
        print(f"  connection {tentative + 1}/12 failed, retry in 20 s", flush=True)
        await asyncio.sleep(20)
    if cli is None or cible is None:
        print("!! board unreachable: nothing can be measured", file=sys.stderr)
        return 2
    print(f"[target] {cible.name} (key {cible.key})", flush=True)
    await asyncio.sleep(3)
    depart = etats.get(cible.key)
    b.note(ev="debut", reglage=reglage, cle=cible.key, depart=depart, valeurs=valeurs,
           secondes=secondes)
    print(f"[target] {cible.name} = {depart} (starting value) | {len(valeurs)} values × "
          f"{secondes:.0f} s ≈ {len(valeurs) * (secondes + 15) / 60:.0f} min", flush=True)

    resultats = []
    for value in valeurs:
        # Robustness: a command can block or hit a dead socket (the board accepts
        # only a limited number of clients). Without these bounds, the loop stayed stuck on the first
        # value — observed on the evening of 05/10: twenty minutes without a single measurement.
        try:
            await asyncio.wait_for(maybe_await(cli.number_command(cible.key, float(value))), 20)
        except Exception as exc:
            print(f"  !! command \"{value}\" impossible ({exc!r}) — reconnecting", flush=True)
            b.note(ev="perte_pendant_valeur", value=value, detail=repr(exc)[:120])
            nouveau, paquet = await rejoindre()
            if nouveau is not None and paquet is not None and paquet[0] is not None:
                cli, (cible, etats) = nouveau, paquet
                await asyncio.sleep(3)
                try:
                    await asyncio.wait_for(
                        maybe_await(cli.number_command(cible.key, float(value))), 20)
                except Exception as exc2:
                    b.note(ev="valeur_abandonnee", value=value, detail=repr(exc2)[:120])
                    print(f"  !! value \"{value}\" abandoned: {exc2!r}"[:140], flush=True)
                    continue
            else:
                continue
        await asyncio.sleep(2)
        relu = etats.get(cible.key)
        try:
            pris = relu is not None and abs(float(relu) - float(value)) <= 0.01
        except (TypeError, ValueError):
            pris = False
        await asyncio.sleep(12)                    # chip settling
        avant, t0 = b.instantane(), time.time()
        tr0, ec0 = b.trames, len(b.ecarts)
        await asyncio.sleep(secondes)
        apres = b.instantane()
        dc = apres.get("captures", 0) - avant.get("captures", 0)
        dt = apres.get("trames_c", 0) - avant.get("trames_c", 0)
        dr = apres.get("rejets", 0) - avant.get("rejets", 0)
        ecarts = b.ecarts[ec0:]
        res = {"reglage": reglage, "value": value, "prise": pris, "relu": relu,
               "dcaptures": dc, "dtrames": dt, "drejets": dr,
               "pulses": apres.get("pulses"),
               "rapport": round(dt / dc, 3) if dc else None,
               "ecarts": ecarts, "secondes": round(time.time() - t0, 1)}
        resultats.append(res)
        b.note(ev="value", **res)
        print(f"  {reglage} = {value} : bursts +{dc}, frames +{dt}, rejects +{dr}, "
              f"ratio={res['rapport']}, gaps={ecarts}"
              + ("" if pris else "  [VALUE NOT TAKEN]"), flush=True)

    await maybe_await(cli.number_command(cible.key, float(depart if depart is not None else valeurs[0])))
    await asyncio.sleep(1.5)
    b.note(ev="restauration", reglage=reglage, value=depart, relu=etats.get(cible.key))
    print(f"[end] {reglage} restored to {depart} (read back {etats.get(cible.key)})", flush=True)

    print(f"\n=== summary {reglage} ===")
    for r in resultats:
        barre = "" if r["rapport"] is None else "█" * int(r["rapport"] * 40)
        print(f"  {r['value']:>9} : bursts {r['dcaptures']:4d}  frames {r['dtrames']:3d}  "
              f"rejects {r['drejets']:4d}  {barre}")
    b.note(ev="fin", reglage=reglage, resultats=resultats)
    try:
        await asyncio.wait_for(cli.disconnect(force=True), 10)
    except Exception:
        pass
    for f in (b.jsonl, b.log):
        f.flush()
        os.fsync(f.fileno())
    return 0


def serie() -> int:
    python = str(PY) if Path(PY).exists() else sys.executable
    script = str(Path(__file__).resolve())
    for reglage, valeurs, secondes in SERIE:
        etiquette = reglage.lower().replace(" ", "_")
        commande = [python, script, "--reglage", reglage,
                    "--valeurs", ",".join(str(v) for v in valeurs),
                    "--secondes", str(secondes), "--etiquette", etiquette]
        print(f"\n===== SWEEP \"{reglage}\" : {valeurs} =====", flush=True)
        try:
            subprocess.run(commande, timeout=int(secondes * len(valeurs) + 600), check=False,
                           cwd=str(ROOT), env={**os.environ, "VEVOR_HOST": HOTE})
        except subprocess.TimeoutExpired:
            print(f"[{reglage}] sweep killed by the safety timeout", flush=True)
        time.sleep(10)
    print("\n===== SERIES DONE =====", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--serie", action="store_true", help="the three settings in a row")
    ap.add_argument("--reglage", help="EXACT entity name, e.g. \"Data rate\"")
    ap.add_argument("--valeurs", help="comma-separated values")
    ap.add_argument("--secondes", type=float, default=150.0)
    ap.add_argument("--etiquette", default="setting")
    a = ap.parse_args()
    ETAT.mkdir(parents=True, exist_ok=True)
    if a.serie:
        return serie()
    if not a.reglage or not a.valeurs:
        ap.error("--reglage and --valeurs are required (or --serie)")
    return asyncio.run(balayer(a.reglage, [float(x) for x in a.valeurs.split(",")],
                               a.secondes, a.etiquette))


if __name__ == "__main__":
    sys.exit(main())
