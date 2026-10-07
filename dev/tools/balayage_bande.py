#!/usr/bin/env python3
"""Mapping of the USEFUL bandwidth: up to what distance from the centre does the board decode?

Our receive filter — 100 kHz requested, 101.6 kHz actually written to MDMCFG4 — is narrower
than the band the signal occupies: 2-FSK at ±70 kHz deviation, i.e. ~151-163 kHz in total.
Both tones therefore fall outside the filter, and that is the measured mark/space asymmetry
(118/58 µs).

This tool measures the DIRECT consequence, without reflashing: "CC1101 frequency" is an entity
and the driver exposes cc1101.set_frequency (a fresh write of FREQ2/1/0). The receiver frequency
is shifted step by step, on BOTH sides of the centre, and at each step the number of bursts
received, frames decoded and rejects is recorded. The frames/bursts ratio traces the shape of
the band.

This is NOT a crystal-calibration test (we sweep symmetrically). The order is interleaved
(centre, +step, -step, +2step, -2step…) so that a time drift cannot be confused with the
frequency. The starting frequency is restored at the end.

Outputs: dev/state/balayage_bande_<label>.jsonl (one step per line) and .log (raw log).
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import DEV, resolve_key, maybe_await  # noqa: E402

HOTE = os.environ.get("VEVOR_HOST") or "172.16.0.205"
PORT = 6053
ETAT = DEV / "state"

# Exact name expected, AND a fallback that avoids the traps: the "Offset" sensor must never match.
FREQ_EXACTE = re.compile(r"^\s*cc1101\s+frequency\s*$", re.I)
FREQ_REPLI = re.compile(r"cc1101 frequency|frequency", re.I)
FREQ_EXCLU = re.compile(r"offset", re.I)

RE_TRAME = re.compile(r"V7IN1 OK (\{.*\})")
RE_COMPTEURS = re.compile(r"captures=(\d+) \(\+(\d+)\), frames=(\d+), rejects=(\d+)")
CAPTEURS = {"rmt captures": "captures", "valid frames": "trames",
            "rejected frames": "rejets", "duplicates ignored": "duplicates"}


class Mesure:
    def __init__(self, etiquette: str):
        self.jsonl = open(ETAT / f"balayage_bande_{etiquette}.jsonl", "a", buffering=1)
        self.log = open(ETAT / f"balayage_bande_{etiquette}.log", "a", buffering=1)
        self.noms_cles: dict[int, str] = {}
        self.compteurs: dict[str, int] = {}
        self.trames = 0

    def note(self, **kw) -> None:
        kw = {"t": round(time.time(), 3),
              "h": datetime.datetime.now().strftime("%H:%M:%S"), **kw}
        self.jsonl.write(json.dumps(kw, ensure_ascii=False) + "\n")

    def sur_log(self, reponse) -> None:
        try:
            texte = (reponse.message.decode("utf8", "replace")
                     if isinstance(reponse.message, (bytes, bytearray)) else str(reponse.message))
        except Exception:                                       # pragma: no cover
            return
        for ligne in texte.splitlines():
            self.log.write(ligne + "\n")
            if RE_TRAME.search(ligne):
                self.trames += 1
            m = RE_COMPTEURS.search(ligne)
            if m:
                self.compteurs = {"captures": int(m.group(1)), "trames_c": int(m.group(3)),
                                  "rejets": int(m.group(4))}

    def sur_etat(self, etat) -> None:
        nom = (self.noms_cles.get(etat.key, "") or "").strip().lower()
        if nom in CAPTEURS:
            try:
                self.compteurs[CAPTEURS[nom]] = int(float(etat.state))
            except (TypeError, ValueError):
                pass

    def instantane(self) -> dict:
        return dict(self.compteurs)


async def balayer(a) -> int:
    import aioesphomeapi
    m = Mesure(a.etiquette)
    cle = resolve_key()

    # The centre, then the interleaved offsets: +step, -step, +2step, -2step…
    ecarts = [0.0]
    for k in range(1, int(a.demi_largeur // a.pas) + 1):
        ecarts += [+k * a.pas, -k * a.pas]
    frequences = [round(a.centre + e / 1000.0, 4) for e in ecarts]

    cli = None
    for psk, nom in ((None, "plain"), (cle, "encrypted")):
        essai = aioesphomeapi.APIClient(HOTE, PORT, None, noise_psk=psk)
        try:
            await asyncio.wait_for(essai.connect(login=True), 25)
            cli = essai
            print(f"[mode] API as {nom}", flush=True)
            break
        except Exception as exc:
            print(f"[mode] {nom} refused: {exc!r}"[:140], flush=True)
            try:
                await asyncio.wait_for(essai.disconnect(force=True), 8)
            except Exception:
                pass
    if cli is None:
        print("!! no connection mode accepted", file=sys.stderr)
        return 2

    entites, _ = await asyncio.wait_for(cli.list_entities_services(), 25)
    m.noms_cles = {e.key: (getattr(e, "name", "") or "") for e in entites}
    cible = None
    for e in entites:
        nom = getattr(e, "name", "") or ""
        if FREQ_EXACTE.search(nom):
            cible = e
            break
    if cible is None:
        for e in entites:
            nom = getattr(e, "name", "") or ""
            if FREQ_REPLI.search(nom) and not FREQ_EXCLU.search(nom) and hasattr(e, "state"):
                cible = e
                break
    if cible is None:
        print("!! frequency entity not found (neither \"CC1101 frequency\" nor fallback) "
              + str([n for n in m.noms_cles.values() if FREQ_REPLI.search(n)]), file=sys.stderr)
        return 2
    print(f"[target] {cible.name} (key {cible.key})", flush=True)

    etats: dict[int, float] = {e.key: getattr(e, "state", None) for e in entites if hasattr(e, "state")}
    m.noms_cles = {e.key: (getattr(e, "name", "") or "") for e in entites}

    def sur_etat(etat) -> None:
        etats[etat.key] = getattr(etat, "state", None)
        m.sur_etat(etat)

    await maybe_await(cli.subscribe_states(sur_etat))
    await maybe_await(cli.subscribe_logs(m.sur_log))
    await asyncio.sleep(2)
    # First counters: read from the states pushed by the board.
    for cle_e, nom in m.noms_cles.items():
        if nom.strip().lower() in CAPTEURS and etats.get(cle_e) is not None:
            try:
                m.compteurs[CAPTEURS[nom.strip().lower()]] = int(float(etats[cle_e]))
            except (TypeError, ValueError):
                pass
    m.note(ev="debut", centre=a.centre, pas_khz=a.pas, demi_largeur_khz=a.demi_largeur,
           secondes=a.secondes, compteurs_initial=m.instantane(), frequences=frequences)
    print(f"target={cible.name} | {len(frequences)} steps of {a.pas} kHz over ±{a.demi_largeur} kHz, "
          f"{a.secondes:.0f} s per step ({len(frequences) * (a.secondes + 14) / 60:.0f} min)", flush=True)

    resultats = []
    for mhz in frequences:
        await maybe_await(cli.number_command(cible.key, mhz))
        await asyncio.sleep(1.5)
        relu = etats.get(cible.key)
        try:
            pris = relu is not None and abs(float(relu) - mhz) <= 0.001
        except (TypeError, ValueError):
            pris = False
        await asyncio.sleep(12)                  # chip settling: the 1st burst may be a fragment
        avant = m.instantane()
        trames_avant = m.trames
        await asyncio.sleep(a.secondes)
        apres = m.instantane()
        lignes = {
            "freq_mhz": mhz,
            "ecart_khz": round((mhz - a.centre) * 1000),
            "prise": pris,
            "relu": relu,
            "dcaptures": apres.get("captures", 0) - avant.get("captures", 0),
            "drejets": apres.get("rejets", 0) - avant.get("rejets", 0),
            "dtrames": apres.get("trames_c", 0) - avant.get("trames_c", 0),
            "trames_log": m.trames - trames_avant,
        }
        lignes["rapport"] = (round(lignes["dtrames"] / lignes["dcaptures"], 3)
                             if lignes["dcaptures"] else None)
        resultats.append(lignes)
        m.note(ev="pas", **lignes)
        print(f"  {mhz:.4f} MHz ({lignes['ecart_khz']:+5d} kHz) : "
              f"bursts +{lignes['dcaptures']}, frames +{lignes['dtrames']}, "
              f"rejects +{lignes['drejets']}, ratio={lignes['rapport']}"
              + ("" if pris else "  [FREQUENCY NOT TAKEN]"), flush=True)

    # Restore the starting frequency: the tool must not leave the board detuned.
    await maybe_await(cli.number_command(cible.key, a.centre))
    await asyncio.sleep(1.0)
    relu = etats.get(cible.key)
    m.note(ev="restauration", freq_mhz=a.centre, relu=relu)
    print(f"[end] frequency restored to {a.centre} MHz (read back {relu})", flush=True)

    print("\n=== useful band (frames/bursts ratio per offset) ===")
    for r in resultats:
        barre = "" if r["rapport"] is None else "█" * int(r["rapport"] * 60)
        print(f"  {r['ecart_khz']:+5d} kHz : bursts {r['dcaptures']:4d}  frames {r['dtrames']:3d} "
              f" rejects {r['drejets']:4d}  {barre}")
    m.note(ev="fin", resultats=resultats)
    try:
        await asyncio.wait_for(cli.disconnect(force=True), 10)
    except Exception:
        pass
    for f in (m.jsonl, m.log):
        f.flush()
        os.fsync(f.fileno())
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="mapping of the useful bandwidth")
    ap.add_argument("--etiquette", default="day1")
    ap.add_argument("--centre", type=float, default=868.35)
    ap.add_argument("--pas", type=float, default=20.0, help="kHz")
    ap.add_argument("--demi-largeur", type=float, default=120.0, help="kHz")
    ap.add_argument("--secondes", type=float, default=120.0, help="sampling duration per step")
    a = ap.parse_args()
    ETAT.mkdir(parents=True, exist_ok=True)
    return asyncio.run(balayer(a))


if __name__ == "__main__":
    sys.exit(main())
