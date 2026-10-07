#!/usr/bin/env python3
"""Capture an ESPHome ESP32's logs via the native API (port 6053) for N seconds.

Usage:
    capture_logs.py --host <board-ip> --seconds 90 [--key BASE64_KEY] [--out file.log]

Without --key, uses $ESPHOME_API_KEY or the key read from the project YAML (see
`_common.key_from_yaml`, which resolves `!secret`). Writes to stdout and, with --out, to the file
(overwritten unless --append). The file is written ATOMICALLY (temp + os.replace); a relative
--out targets the repo ROOT.

Return codes: 0 capture done, at least one log line received; 2 technical error (API, exception);
3 empty measurement: connected but NO log line received (the firmware heartbeats every 20 s).
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _common import (RC_ERREUR, RC_MESURE_NULLE, RC_OK,  # noqa: E402
                     atomic_write_text, out_path, resolve_key)

import aioesphomeapi  # noqa: E402


async def run(host: str, port: int, key: str | None, seconds: float) -> tuple[int, list[str]]:
    # ESPHome encryption goes through noise_psk (keyword); the 3rd positional arg is treated as
    # a plaintext password -> "requires encryption".
    cli = aioesphomeapi.APIClient(host, port, None,
                                  noise_psk=None if key in (None, "", "None") else key)
    await cli.connect(login=True)
    info = await cli.device_info()
    header = f"# connected to {host}:{port} — {info.name} / {info.model} / esphome {info.esphome_version}"
    print(header, flush=True)

    stop = asyncio.Event()
    t0 = dt.datetime.now().strftime("%H:%M:%S")
    lines: list[str] = []

    def on_log(msg) -> None:
        try:
            if isinstance(msg, (bytes, bytearray)):
                text = msg.decode("utf-8", "replace")
            else:
                raw = getattr(msg, "message", None)
                if raw is None:
                    raw = getattr(msg, "data", b"")
                text = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
        except Exception as exc:  # pragma: no cover - agent robustness
            text = f"<log undecodable: {exc}>"
        if not text.strip():
            return
        line = f"[{dt.datetime.now().strftime('%H:%M:%S')}] {text.rstrip()}"
        print(line, flush=True)
        lines.append(line)

    # subscribe_logs is NOT a coroutine (it returns an unsubscribe function); awaiting it raises.
    cli.subscribe_logs(on_log, log_level=7)
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass
    await cli.disconnect()
    tail = f"# capture end (started {t0}, {seconds}s) — {len(lines)} log line(s) received"
    print(tail, flush=True)
    return (RC_OK if lines else RC_MESURE_NULLE), [header, *lines, tail]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=6053)
    ap.add_argument("--key", default=None,
                    help="base64 API key (default: env ESPHOME_API_KEY or YAML)")
    ap.add_argument("--seconds", type=float, default=90)
    ap.add_argument("--out", default=None, help="output file (relative = project root)")
    ap.add_argument("--append", action="store_true",
                    help="APPEND instead of overwriting (default: overwrite). Append mode already "
                         "made a previous window read back as new: a capture file must be fresh.")
    args = ap.parse_args()

    try:
        key = resolve_key(args.key)
        rc, lines = asyncio.run(run(args.host, args.port, key, args.seconds))
    except SystemExit:
        raise
    except Exception as exc:
        print(f"# capture ERROR: {type(exc).__name__}: {exc}", flush=True)
        return RC_ERREUR

    if args.out:
        p = out_path(args.out)
        body = "\n".join(lines) + "\n"
        if args.append and p.exists():
            body = p.read_text(encoding="utf-8", errors="replace") + body
        atomic_write_text(p, body)
        print(f"# file written (atomic): {p}")

    if rc == RC_MESURE_NULLE:
        print("# NULL MEASUREMENT — connection established but NO log line received: "
              "nothing was measured", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
