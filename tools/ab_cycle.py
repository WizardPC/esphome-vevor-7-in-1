#!/usr/bin/env python3
"""Compare, dans des fenêtres INTERLEAVÉES, le firmware témoin et nos variantes.

Pourquoi : la station n'émet que par fenêtres (mesuré le 01/10 : émission 08:04-08:09 UTC,
silence le reste de la matinée). Comparer deux firmwares dans deux fenêtres éloignées ne veut
donc rien dire — il faut les mesurer l'un après l'autre, dans la même période.

Chaque tour : pour chaque variante -> flash OTA du binaire déjà compilé, courte attente de
démarrage, capture des logs par l'API native (port 6053) pendant N secondes, puis une ligne
JSON ajoutée dans logs/ab_cycle.jsonl. Sortie = un récapitulatif lisible.

Usage :
    tools/ab_cycle.py --rounds 2 --seconds 100 [--variants temoin,nous_v0,nous_v1,nous_v2]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
# Dossier (HORS dépôt) où est construit le firmware de référence servant de témoin.
# Paramétrable : VEVOR_TEMOIN_DIR=/chemin/vers/_temoins tools/ab_cycle.py ...
TEMOIN = pathlib.Path(os.environ.get("VEVOR_TEMOIN_DIR",
                                     str(pathlib.Path.home() / "projets" / "_temoins")))
ESPHOME = ROOT / ".venv" / "bin" / "esphome"
HOST = "172.16.0.205"

VARIANTS = {
    # nom : (répertoire de la config, YAML, binaire OTA figé, description)
    # Une variante = une entrée d'ici, avec son binaire DÉJÀ compilé dans build/variants/ : le
    # cycle ne recompile jamais, il flashe et mesure. Les variantes de diagnostic v1/v2/v3 ont
    # servi à isoler la cause du mutisme radio (01/10) puis ont été supprimées : elles
    # contenaient le second périphérique SPI qui rend la puce muette, mauvais exemple à laisser.
    "temoin": (TEMOIN / "witness-test", "witness.yaml",
               TEMOIN / "witness-test/.esphome/build/vevor-weather-station/build/firmware.ota.bin",
               "projet de référence (WizardPC/esphome-vevor-7in1), compilé par nos soins"),
    # 02/10 — même YAML, même câblage, même garde-fou : seul le C++ du composant radio change
    # (pilote d'ORIGINE d'ESPHome contre ma copie locale). C'est l'expérience qui dit lequel des
    # deux rend la puce sourde : le firmware témoin, qui utilise le composant d'origine, décode.
    "origine": (ROOT / "esphome", "vevor-7in1.yaml",
                ROOT / "build/variants/nous_pilote_origine.ota.bin",
                "pilote d'origine d'ESPHome, notre YAML"),
    "prod": (ROOT / "esphome", "vevor-7in1.yaml",
             ROOT / "build/variants/nous_prod.ota.bin",
             "notre firmware de production"),
    # Binaire d'avant la revue de code : c'est LUI qui décodait encore 216 trames le 01/10 à
    # 11:28. Il sert de contrôle : si lui reçoit et que `prod` ne reçoit pas, la régression est
    # dans nos corrections, pas dans l'air. Le YAML n'apporte que les identifiants OTA (identiques).
    "prod_avant_revue": (ROOT / "esphome", "vevor-7in1.yaml",
                         ROOT / "build/variants/prod_avant_revue.ota.bin",
                         "notre firmware d'avant la revue"),
}


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
    out_jsonl = ROOT / "logs" / "ab_cycle.jsonl"
    stamp = f"{dt.datetime.now(dt.timezone.utc):%Y%m%d_%H%M%S}"
    results = []

    for r in range(1, args.rounds + 1):
        for name in names:
            workdir, yaml, binary, desc = VARIANTS[name]
            log = ROOT / "logs" / f"ab_{stamp}_r{r}_{name}.log"
            flash_log = log.with_suffix(".flash")
            started = dt.datetime.now(dt.timezone.utc)
            if not binary.exists():
                raise SystemExit(f"binaire absent pour {name} : {binary}")
            proc = subprocess.run(
                [str(ESPHOME), "upload", yaml, "--device", HOST, "--file", str(binary)],
                cwd=workdir, capture_output=True, text=True, timeout=300)
            flash_log.write_text(proc.stdout + proc.stderr, encoding="utf-8")
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
                               str(ROOT / "tools" / "capture_logs.py"),
                               "--host", HOST, "--seconds", str(args.seconds), "--out", str(log)]
            else:
                capture_cmd = [str(ROOT / ".venv" / "bin" / "python"),
                               str(ROOT / "tools" / "press_button.py"),
                               "--host", HOST, "--name", "Dump impulsions",
                               "--seconds", str(args.seconds), "--out", str(log)]
            cap = subprocess.run(capture_cmd, capture_output=True, text=True,
                                 timeout=args.seconds + 120)
            # Un échec de capture (API injoignable, port occupé) ne doit JAMAIS se lire comme
            # « aucune trame reçue » : c'est la classe d'erreur qui a coûté le plus cher ici.
            capture_ok = cap.returncode == 0
            if not capture_ok:
                print(f"  !! capture en échec (code {cap.returncode}) : mesure à JETER — "
                      f"{(cap.stderr or cap.stdout)[-200:]}", flush=True)
            row = {
                "round": r, "variante": name, "debut_utc": started.isoformat(timespec="seconds"),
                "flash_ok": flash_ok, "capture_ok": capture_ok, "yaml": yaml, "log": str(log),
                "description": desc,
            }
            row.update(summarize(name, log))
            with out_jsonl.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            results.append(row)
            key = "trames_decodees" if name == "temoin" else "v7in1_ok"
            print(f"[{row['debut_utc']}] {name:8s} flash={'OK' if flash_ok else 'FAIL'} "
                  f"{key}={row.get(key)} captures_max={row.get('captures_max', '-')} "
                  f"rafales={row.get('rafales_rf_raw', '-')}", flush=True)

    print("\n=== récapitulatif ===")
    for row in results:
        print(json.dumps(row, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
