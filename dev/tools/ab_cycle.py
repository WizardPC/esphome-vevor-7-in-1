#!/usr/bin/env python3
"""Compare, dans des fenêtres INTERLEAVÉES, le firmware témoin et nos variantes.

Pourquoi : la station n'émet que par fenêtres (mesuré le 01/10 : émission 08:04-08:09 UTC,
silence le reste de la matinée). Comparer deux firmwares dans deux fenêtres éloignées ne veut
donc rien dire — il faut les mesurer l'un après l'autre, dans la même période.

Chaque tour : pour chaque variante -> flash OTA du binaire déjà compilé, courte attente de
démarrage, capture des logs par l'API native (port 6053) pendant N secondes, puis une ligne
JSON ajoutée dans logs/ab_cycle.jsonl. Sortie = un récapitulatif lisible.

La table des variantes est celle de `_common.VARIANTS` (source de vérité unique, partagée avec
`boot_probe.py`) ; un nom inconnu échoue lisiblement au lieu de lever un KeyError.

Usage :
 dev/tools/ab_cycle.py --rounds 2 --seconds 100 [--variants temoin,prod,origine]

Code retour :
    0  toutes les mesures sont exploitables (« aucune trame » est un RÉSULTAT négatif) ;
    3  MESURE NULLE : au moins une variante a une mesure inexploitable (flash raté, capture en
       échec, ou capture réussie mais vide) — rien n'a été mesuré pour cette variante.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _common import (DEFAULT_HOST, ESPHOME, ROOT, RC_MESURE_NULLE, RC_OK,  # noqa: E402
                     atomic_write_text, variant_of)

# Certaines captures passent par `press_button.py`, qui renvoie 3 quand la capture est vide.
RC_CAPTURE_VIDE = 3


def summarize(variant: str, log: pathlib.Path) -> dict:
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    out: dict = {"lignes": text.count("\n")}
    if variant == "temoin":
        out["rafales_rf_raw"] = len(re.findall(r"rf_raw", text))
        out["trames_decodees"] = len(re.findall(r"\[84CB\]", text))
        imp = [int(m) for m in re.findall(r"Salve RF recue : (\d+) impulsions", text)]
        out["impulsions_max"] = max(imp) if imp else 0
    else:
        out["v7in1_ok"] = len(re.findall(r"V7IN1 OK", text))
        out["v7in1_raw"] = len(re.findall(r"V7IN1 RAW", text))
        out["v7in1_rej"] = len(re.findall(r"V7IN1 REJ", text))
        caps = [int(m) for m in re.findall(r"captures=(\d+)", text)]
        out["captures_max"] = max(caps) if caps else 0
        last = [int(m) for m in re.findall(r"dernières impulsions=(\d+)", text)]
        out["dernieres_impulsions"] = last[-1] if last else 0
        out["gdo0_statique"] = len(re.findall(r"GDO0 STATIQUE", text))
        out["inventaire"] = (re.findall(r"INVENTAIRE[^\n]*", text) or [""])[0][:120]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--seconds", type=int, default=100)
    ap.add_argument("--variants", default="temoin,prod")
    args = ap.parse_args()

    names = [v.strip() for v in args.variants.split(",") if v.strip()]
    # Valider TOUS les noms AVANT de flasher quoi que ce soit : un nom inconnu doit échouer
    # tout de suite, lisiblement, pas au milieu d'un cycle.
    for name in names:
        variant_of(name)
    out_jsonl = DEV / "logs" / "ab_cycle.jsonl"
    stamp = f"{dt.datetime.now(dt.timezone.utc):%Y%m%d_%H%M%S}"
    results = []

    for r in range(1, args.rounds + 1):
        for name in names:
            workdir, yaml, binary, desc = variant_of(name)
            log = DEV / "logs" / f"ab_{stamp}_r{r}_{name}.log"
            flash_log = log.with_suffix(".flash")
            started = dt.datetime.now(dt.timezone.utc)
            if not binary.exists():
                raise SystemExit(f"binaire absent pour {name} : {binary}")
            proc = subprocess.run(
                [str(ESPHOME), "upload", yaml, "--device", DEFAULT_HOST, "--file", str(binary)],
                cwd=workdir, capture_output=True, text=True, timeout=300)
            atomic_write_text(flash_log, proc.stdout + proc.stderr)
            # ESPHome journalise sur STDERR : tester stdout seul fait passer un flash réussi
            # pour un échec (mesuré le 01/10, premier passage du cycle).
            flash_ok = proc.returncode == 0 and "OTA successful" in (proc.stdout + proc.stderr)
            # démarrage : Wi-Fi + API avant de capture
            subprocess.run(["sleep", "12"], check=False)
            # Pour NOS variantes, on arme en plus le dump des durées brutes de la prochaine
            # capture (bouton « Dump impulsions ») : c'est la seule façon de voir CE QUE notre
            # RMT a réellement reçu pendant une fenêtre d'émission.
            if name == "temoin":
                capture_cmd = [str(ROOT / ".venv" / "bin" / "python"),
                               str(DEV / "tools" / "capture_logs.py"),
                               "--host", DEFAULT_HOST, "--seconds", str(args.seconds),
                               "--out", str(log)]
            else:
                capture_cmd = [str(ROOT / ".venv" / "bin" / "python"),
                               str(DEV / "tools" / "press_button.py"),
                               "--host", DEFAULT_HOST, "--name", "Dump impulsions",
                               "--seconds", str(args.seconds), "--out", str(log)]
            cap = subprocess.run(capture_cmd, capture_output=True, text=True,
                                 timeout=args.seconds + 120)
            # Un échec de capture (API injoignable, port occupé) ne doit JAMAIS se lire comme
            # « aucune trame reçue » ; une capture VIDE (code 3) non plus. Les deux sont des
            # mesures nulles, pas des résultats négatifs.
            capture_ok = cap.returncode in (0, RC_CAPTURE_VIDE)
            if not capture_ok:
                print(f"  !! capture en échec (code {cap.returncode}) : mesure à JETER — "
                      f"{(cap.stderr or cap.stdout)[-200:]}", flush=True)
            summary = summarize(name, log)
            # Mesure inexploitable : flash raté, capture en échec, ou capture vide (< 2 lignes).
            mesure_nulle = (not flash_ok) or (not capture_ok) or (summary["lignes"] < 2)
            row = {
                "round": r, "variante": name, "debut_utc": started.isoformat(timespec="seconds"),
                "flash_ok": flash_ok, "capture_ok": capture_ok,
                "capture_rc": cap.returncode, "mesure_nulle": mesure_nulle,
                "yaml": yaml, "log": str(log), "description": desc,
            }
            row.update(summary)
            prev = out_jsonl.read_text(encoding="utf-8", errors="replace") if out_jsonl.exists() else ""
            atomic_write_text(out_jsonl, prev + json.dumps(row, ensure_ascii=False) + "\n")
            results.append(row)
            key = "trames_decodees" if name == "temoin" else "v7in1_ok"
            print(f"[{row['debut_utc']}] {name:8s} flash={'OK' if flash_ok else 'FAIL'} "
                  f"{key}={row.get(key)} captures_max={row.get('captures_max', '-')} "
                  f"rafales={row.get('rafales_rf_raw', '-')} "
                  f"lignes={row['lignes']}{' (MESURE NULLE)' if mesure_nulle else ''}", flush=True)

    print("\n=== récapitulatif ===")
    for row in results:
        print(json.dumps(row, ensure_ascii=False))
    nulles = [row for row in results if row["mesure_nulle"]]
    if nulles:
        print(f"\n# MESURE NULLE : {len(nulles)} variante(s) sur {len(results)} sans mesure "
              "exploitable — rien n'a été mesuré pour elles (code 3)", file=sys.stderr)
        return RC_MESURE_NULLE
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
