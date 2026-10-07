#!/usr/bin/env python3
"""Minimal network scanner: locates Home Assistant and the ESP32 ESPHome boards.

Usage:
    net_scan.py --subnet <prefix> [--ports 8123,6052,6053] [--timeout 0.4]

No external dependency. Useful to rediscover the ESP32 IP before/after the first flash
(6053 = ESPHome native API, 6052 = ESPHome dashboard, 8123 = Home Assistant).
"""
from __future__ import annotations

import os
import argparse
import ipaddress
import socket
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

LABELS = {
    8123: "Home Assistant",
    6052: "ESPHome dashboard",
    6053: "ESP32 ESPHome (native API)",
    80: "HTTP",
    443: "HTTPS",
    22: "SSH",
}


def probe(ip: str, port: int, timeout: float) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((ip, port)) == 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subnet", default=os.environ.get("VEVOR_SUBNETS"),
                    required="VEVOR_SUBNETS" not in os.environ,
                    help="subnet prefix to scan (VEVOR_SUBNETS variable)")
    ap.add_argument("--ports", default="8123,6052,6053")
    ap.add_argument("--timeout", type=float, default=1.0,
                    help="1.0s default: too short a timeout yields FALSE NEGATIVES")
    args = ap.parse_args()

    ports = [int(p) for p in args.ports.split(",")]
    net = ipaddress.ip_network(f"{args.subnet}.0/24", strict=False)
    hosts = [str(h) for h in net.hosts()]
    print(f"# scanning {net} on ports {ports} (timeout {args.timeout}s)")

    found: dict[str, list[int]] = {}
    with ThreadPoolExecutor(max_workers=128) as pool:
        jobs = {pool.submit(probe, ip, port, args.timeout): (ip, port) for ip in hosts for port in ports}
        for fut in as_completed(jobs):
            ip, port = jobs[fut]
            try:
                if fut.result():
                    found.setdefault(ip, []).append(port)
            except Exception:
                pass

    if not found:
        print("# nothing found. Leads: another subnet, firewall on the host, machine powered off,")
        print("#   or service not started. Also check this container's ARP table (ip neigh).")
        return 1

    for ip in sorted(found, key=lambda x: tuple(int(o) for o in x.split("."))):
        details = ", ".join(f"{p} ({LABELS.get(p, '?')})" for p in sorted(found[ip]))
        print(f"{ip:16} -> {details}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
