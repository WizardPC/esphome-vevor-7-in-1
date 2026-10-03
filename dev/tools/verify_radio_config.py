#!/usr/bin/env python3
"""Vérifie SANS MATÉRIEL ce que le CC1101 recevra réellement comme registres.

Pourquoi : la spec radio (868,30 MHz / ±37 kHz / 11 494 bauds / 200 kHz) est une
hypothèse. Le CC1101 n'accepte que des valeurs quantifiées (CHANBW_E/M, DEVIATION_E/M,
DRATE_E/M) : ce script rejoue *exactement* les calculs du composant ESPHome
(esphome/components/cc1101/cc1101.cpp : split_float + set_frequency/set_filter_bandwidth/
set_fsk_deviation/set_symbol_rate) sur les substitutions du YAML, puis recalcule les
grandeurs physiques obtenues avec les formules du datasheet utilisées par dump_config().

Écrit logs/radio_config_check.json. Code retour 0 si tout est dans la tolérance, 1 sinon.
"""
from __future__ import annotations

import argparse
import math
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _common import atomic_write_json  # noqa: E402

XTAL = 26000000.0
DEV = pathlib.Path(__file__).resolve().parent.parent   # dev/
ROOT = DEV.parent                                      # racine du dépôt
DEFAULT_YAML = ROOT / "esphome" / "vevor-7in1.yaml"
OUT = DEV / "logs" / "radio_config_check.json"


def split_float(value: float, mbits: int):
    """Portage ligne à ligne de split_float() de cc1101.cpp (frexp + arrondi au bin)."""
    m_tmp, e_tmp = math.frexp(value)
    if e_tmp <= mbits:
        return 0, 0
    e = e_tmp - mbits - 1
    m = int(((m_tmp * 2 - 1) * (1 << (mbits + 1))) + 1) >> 1
    if m == (1 << mbits):
        e = e + 1
        m = 0
    return e, m


def read_subs(path: pathlib.Path) -> dict:
    txt = path.read_text()
    subs = {}
    for name in ("freq_mhz", "deviation_khz", "symbol_rate", "bw_khz"):
        m = re.search(rf'^\s*{name}:\s*"([^"]+)"', txt, re.M)
        if not m:
            raise SystemExit(f"substitution absente du YAML : {name}")
        subs[name] = float(m.group(1))
    # autres réglages radio à contrôler
    for key, default in (("num_preamble", "4"), ("packet_length", "21"),
                         ("sync_mode", "16/16"), ("crc_enable", "false"),
                         ("whitening", "false"), ("manchester", "false")):
        m = re.search(rf"^\s*{key}:\s*([^#\n]+)", txt, re.M)
        subs[key] = m.group(1).strip() if m else default
    m = re.search(r"^\s*sync1:\s*([^#\n]+)", txt, re.M)
    subs["sync1"] = m.group(1).strip() if m else ""
    m = re.search(r"^\s*sync0:\s*([^#\n]+)", txt, re.M)
    subs["sync0"] = m.group(1).strip() if m else ""
    m = re.search(r"^\s*packet_mode:\s*([^#\n]+)", txt, re.M)
    subs["packet_mode"] = m.group(1).strip() if m else "false"
    m = re.search(r"^\s*modulation_type:\s*([^#\n]+)", txt, re.M)
    subs["modulation_type"] = m.group(1).strip() if m else ""
    return subs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yaml", default=str(DEFAULT_YAML))
    ap.add_argument("--tol-hz", type=float, default=2000.0, help="tolérance fréquence")
    args = ap.parse_args()

    y = read_subs(pathlib.Path(args.yaml))
    res: dict = {"yaml": {}, "registers": {}, "verdict": []}

    # --- fréquence : set_frequency() ---
    f_hz = y["freq_mhz"] * 1e6
    word = int(f_hz * (1 << 16) / XTAL)
    FREQ2, FREQ1, FREQ0 = (word >> 16) & 0xFF, (word >> 8) & 0xFF, word & 0xFF
    f_actual = word * XTAL / (1 << 16)
    res["yaml"]["freq_hz"] = f_hz
    res["registers"]["FREQ2"] = f"0x{FREQ2:02X}"
    res["registers"]["FREQ1"] = f"0x{FREQ1:02X}"
    res["registers"]["FREQ0"] = f"0x{FREQ0:02X}"
    res["freq_actual_hz"] = f_actual
    res["freq_err_hz"] = f_actual - f_hz

    # --- bande passante : set_filter_bandwidth() -> CHANBW_E/M de MDMCFG4 ---
    e, m = split_float(XTAL / (y["bw_khz"] * 1000.0 * 8), 2)
    CHANBW_E, CHANBW_M = e, m
    bw_actual = XTAL / (8.0 * (4 + CHANBW_M) * (1 << CHANBW_E))
    res["yaml"]["bw_hz"] = y["bw_khz"] * 1000.0
    res["registers"]["CHANBW_E"] = CHANBW_E
    res["registers"]["CHANBW_M"] = CHANBW_M
    res["bw_actual_hz"] = bw_actual
    res["bw_err_hz"] = bw_actual - y["bw_khz"] * 1000.0

    # --- déviation : set_fsk_deviation() -> DEVIATION_E/M de DEVIATN (0x15) ---
    e, m = split_float(y["deviation_khz"] * 1000.0 * (1 << 17) / XTAL, 3)
    DEVIATION_E, DEVIATION_M = e, m
    dev_actual = (8 + DEVIATION_M) * (1 << DEVIATION_E) * XTAL / (1 << 17)
    DEVIATN = (DEVIATION_E << 4) | DEVIATION_M
    res["yaml"]["dev_hz"] = y["deviation_khz"] * 1000.0
    res["registers"]["DEVIATION_E"] = DEVIATION_E
    res["registers"]["DEVIATION_M"] = DEVIATION_M
    res["registers"]["DEVIATN"] = f"0x{DEVIATN:02X}"
    res["dev_actual_hz"] = dev_actual
    res["dev_err_hz"] = dev_actual - y["deviation_khz"] * 1000.0

    # --- débit : set_symbol_rate() -> DRATE_E (MDMCFG4) / DRATE_M (MDMCFG3) ---
    e, m = split_float(y["symbol_rate"] * (1 << 28) / XTAL, 8)
    DRATE_E, DRATE_M = e, m
    sr_actual = ((256.0 + DRATE_M) * (1 << DRATE_E) / (1 << 28)) * XTAL
    MDMCFG4 = (CHANBW_E << 6) | (CHANBW_M << 4) | (DRATE_E & 0x0F)
    res["yaml"]["symbol_rate"] = y["symbol_rate"]
    res["registers"]["DRATE_E"] = DRATE_E
    res["registers"]["DRATE_M"] = DRATE_M
    res["registers"]["MDMCFG4"] = f"0x{MDMCFG4:02X}"
    res["registers"]["MDMCFG3"] = f"0x{DRATE_M:02X}"
    res["symbol_rate_actual"] = sr_actual
    res["symbol_rate_err"] = sr_actual - y["symbol_rate"]

    # --- cohérence : la déviation tient-elle dans la bande passante ? ---
    res["dev_plus_rate_over_bw2"] = (dev_actual + sr_actual / 2) / (bw_actual / 2)

    # --- divers ---
    res["yaml"]["packet_length"] = y["packet_length"]
    res["yaml"]["sync_mode"] = y["sync_mode"]
    res["yaml"]["sync_word"] = f"{y['sync1']} {y['sync0']}"
    res["yaml"]["num_preamble"] = y["num_preamble"]
    res["yaml"]["modulation_type"] = y["modulation_type"]
    res["yaml"]["crc_enable"] = y["crc_enable"]
    res["yaml"]["whitening"] = y["whitening"]
    res["yaml"]["manchester"] = y["manchester"]

    # --- verdicts ---
    v = res["verdict"]
    ok = True

    def check(name, cond, detail):
        nonlocal ok
        v.append({"check": name, "ok": bool(cond), "detail": detail})
        if not cond:
            ok = False

    check("frequence", abs(res["freq_err_hz"]) <= args.tol_hz,
          f"demandé {f_hz/1e6:.6f} MHz -> réel {f_actual/1e6:.6f} MHz "
          f"(err {res['freq_err_hz']:+.1f} Hz)")
    check("deviation_vs_spec",
          abs(res["dev_err_hz"]) <= 0.10 * y["deviation_khz"] * 1000.0,
          f"demandé {y['deviation_khz']:.0f} kHz -> réel {dev_actual/1000:.1f} kHz")
    check("bande_passante_vs_spec",
          abs(res["bw_err_hz"]) <= 0.25 * y["bw_khz"] * 1000.0,
          f"demandé {y['bw_khz']:.0f} kHz -> réel {bw_actual/1000:.1f} kHz")
    check("debit_vs_spec", abs(res["symbol_rate_err"]) <= 0.02 * y["symbol_rate"],
          f"demandé {y['symbol_rate']:.0f} -> réel {sr_actual:.0f} bauds")
    # règle CC1101 : déviation + débit/2 doit tenir dans BW/2 (sinon repliement)
    check("dev_plus_demi_debit_dans_bw",
          res["dev_plus_rate_over_bw2"] < 1.0,
          f"(dev + débit/2) / (BW/2) = {res['dev_plus_rate_over_bw2']:.2f} "
          f"(< 1 requis, sinon écrêtage des bits)")
    check("sync_16_16_ca_54", y["sync_mode"] == "16/16" and y["sync1"].upper().endswith("CA")
          and y["sync0"].upper().endswith("54"),
          f"sync_mode={y['sync_mode']} sync1={y['sync1']} sync0={y['sync0']} "
          f"(rtl_433 attend ...CA CA 54)")
    check("pas_de_whitening_ni_manchester",
          y["whitening"].lower() == "false" and y["manchester"].lower() == "false"
          and y["crc_enable"].lower() == "false",
          f"whitening={y['whitening']} manchester={y['manchester']} crc={y['crc_enable']} "
          f"(rtl_433 démodule en NRZ sans blanchiment)")
    check("mode_packet_longueur_fixe", y["packet_mode"].lower() == "true"
          and y["packet_length"] == "21",
          f"packet_mode={y['packet_mode']} packet_length={y['packet_length']} (21 octets utiles)")

    res["ok"] = ok
    OUT.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(OUT, res)

    print(f"# rapport -> {OUT}")
    print(f"freq   : {f_hz/1e6:.3f} MHz demandé -> {f_actual/1e6:.6f} MHz "
          f"(FREQ2..0 = 0x{FREQ2:02X} 0x{FREQ1:02X} 0x{FREQ0:02X})")
    print(f"dev    : {y['deviation_khz']:.1f} kHz demandé -> {dev_actual/1000:.2f} kHz "
          f"(DEVIATN=0x{DEVIATN:02X} E={DEVIATION_E} M={DEVIATION_M})")
    print(f"BW     : {y['bw_khz']:.0f} kHz demandé -> {bw_actual/1000:.2f} kHz "
          f"(CHANBW_E={CHANBW_E} M={CHANBW_M})")
    print(f"débit  : {y['symbol_rate']:.0f} demandé -> {sr_actual:.1f} bauds "
          f"(DRATE_E={DRATE_E} M={DRATE_M}, MDMCFG4=0x{MDMCFG4:02X})")
    print(f"(dev + débit/2)/(BW/2) = {res['dev_plus_rate_over_bw2']:.2f}")
    for item in v:
        print(f"  [{'OK ' if item['ok'] else 'KO '}] {item['check']}: {item['detail']}")
    print("VERDICT:", "OK" if ok else "KO")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
