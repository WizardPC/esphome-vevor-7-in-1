#!/usr/bin/env python3
"""Raw read of an ESP32 serial console from this container.

Usage: serial_log.py [--port /dev/ttyACM0] [--seconds 25] [--baud 115200]

Diagnostic when the board is not reachable on the network: reads the boot log (Wi-Fi,
components, CC1101 errors). Opening the port resets the board (DTR/RTS) — intended to
capture the full boot.
"""
from __future__ import annotations

import argparse
import sys
import time

try:
    import serial  # pyserial
except ImportError:
    print("# pyserial absent : .venv/bin/pip install pyserial", file=sys.stderr)
    sys.exit(3)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyACM0")
    ap.add_argument("--seconds", type=float, default=25.0)
    ap.add_argument("--baud", type=int, default=115200)
    args = ap.parse_args()

    try:
        ser = serial.Serial(args.port, args.baud, timeout=1)
    except Exception as exc:
        print(f"# impossible d'ouvrir {args.port}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(f"# lecture de {args.port} pendant {args.seconds}s à {args.baud} bauds", flush=True)
    deadline = time.monotonic() + args.seconds
    buf = b""
    lines = 0
    try:
        while time.monotonic() < deadline:
            chunk = ser.read(4096)
            if not chunk:
                continue
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                print(line.decode("utf-8", "replace").rstrip("\r"), flush=True)
                lines += 1
    except KeyboardInterrupt:
        pass
    finally:
        ser.close()
    print(f"# fin de lecture ({lines} lignes)", flush=True)
    return 0 if lines else 1


if __name__ == "__main__":
    sys.exit(main())
