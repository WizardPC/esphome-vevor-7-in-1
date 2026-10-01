#!/usr/bin/env python3
"""Retrouve l'IP de l'ESP32 (API native ESPHome sur 6053) — utilisé par la boucle autonome.

Usage: find_esp32.py [--subnet 192.168.2] [--timeout 1.0] [--refresh]

Stratégie : si state/DEVICE_IP existe et répond encore, on le renvoie (rapide) ; sinon on
scanne le /24 sur le port 6053, on mémorise le premier résultat dans state/DEVICE_IP.
Sortie volontairement déterministe : une IP, ou "none" — c'est ce qui permet au planificateur
de la boucle de détecter un changement d'état sans réveiller l'agent inutilement.
"""
from __future__ import annotations

import argparse
import ipaddress
import pathlib
import socket
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "state" / "DEVICE_IP"


def open_port(ip: str, port: int, timeout: float) -> bool:
    with socket.socket() as s:
        s.settimeout(timeout)
        return s.connect_ex((ip, port)) == 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subnets", default="192.168.2,172.16.0",
                    help="sous-réseaux à balayer. IMPORTANT : le Wi-Fi de la carte est sur "
                         "172.16.0.0/24 (use_address 172.16.0.205) alors que ce conteneur est "
                         "sur 192.168.2.0/24 — un scan limité à un seul des deux conclut à tort "
                         "que la carte est absente.")
    ap.add_argument("--port", type=int, default=6053)
    ap.add_argument("--timeout", type=float, default=1.0)
    ap.add_argument("--refresh", action="store_true", help="ignorer le cache et rescanner")
    args = ap.parse_args()

    if not args.refresh and CACHE.exists():
        cached = CACHE.read_text(encoding="utf-8").strip()
        if cached and open_port(cached, args.port, args.timeout):
            print(cached)
            return 0

    hosts: list[str] = []
    for subnet in args.subnets.split(","):
        subnet = subnet.strip()
        if not subnet:
            continue
        hosts += [str(h) for h in ipaddress.ip_network(f"{subnet}.0/24", strict=False).hosts()]
    with ThreadPoolExecutor(max_workers=128) as pool:
        results = pool.map(lambda ip: ip if open_port(ip, args.port, args.timeout) else None, hosts)
    found = [ip for ip in results if ip]

    if not found:
        if CACHE.exists():
            CACHE.unlink()
        # Sortie "none" et code 0 : ce script est un contrôle d'état, pas une action qui
        # échoue. Un code non nul ferait déclencher les filets `|| echo none` des appelants
        # (avec pipefail) et dupliquerait la sortie.
        print("none")
        return 0

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(found[0], encoding="utf-8")
    print(found[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
