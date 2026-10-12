#!/usr/bin/env python3
"""Every-6h watch: did a temperature spike appear, and why? Did the board reboot, and why?

Written for the 07/10/2026 case: a raw frame whose every other field was plausible carried 39.1 C
(bytes 03 7b = 891) while the station read 13 C. The rain gate had already been added for the same
class of fault; the temperature got one too. This script exists to check that the gate is doing its
job, and to say WHY a spike slipped through when one does.

Measured while investigating, and it settles the origin: the station's checksum byte (index 19) is
the sum of bytes 0..18 modulo 256 — verified on 655/655 frames. The temperature IS inside that sum.
So a transmission error in bytes 5-6 would break the checksum, and the 39.1 C frame's checksum was
VALID (sum = 1281, 1281 mod 256 = 1 = byte 19). That frame therefore arrived exactly as the station
emitted it: the anomaly is the station's own reading, not our decoding. It also differs from the
nearest sane frame by exactly one bit in the temperature's high byte (03 7b against 02 7b), which
points at a one-bit glitch inside the station's own sensor path — a narrow hypothesis, not a fact.

Read-only: it reads Home Assistant's history and the card's own reset reasons. It never presses, never
flashes, never writes to the board.

    dev/tools/temperature_spike_watch.py [--hours 6]

Output is a plain facts block consumed by the agent (or by a human). No verdicts here: the
classification is done by whoever reads it, with the raw bytes in hand.
"""

import datetime
import json
import os
import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
# No address and no device name in the code (dev/tools/_common.py is the reference for that rule):
# $HA_URL / $VEVOR_HA_PREFIX, else the git-ignored .ha_url file and the measured entity listing.
HA_URL = os.environ.get("HA_URL") or (
    (ROOT / ".ha_url").read_text(encoding="utf-8").strip() if (ROOT / ".ha_url").exists() else "")
if not HA_URL:
    sys.exit("no Home Assistant address: set $HA_URL or create .ha_url")


def ha_prefix() -> str:
    """The device prefix is an installation value, never a constant: $VEVOR_HA_PREFIX, else the
    measured listing (dev/docs/ha-entities.txt), the same source the dashboard card check uses."""
    prefix = os.environ.get("VEVOR_HA_PREFIX", "").strip()
    if prefix:
        return prefix + "." if prefix.endswith("sensor") else prefix
    for line in (ROOT / "dev/docs/ha-entities.txt").read_text(encoding="utf-8").splitlines():
        entity = line.split("#")[0].strip()
        if entity.endswith("_outdoor_temperature"):
            domain, name = entity.split(".", 1)
            return domain + "." + name[: -len("outdoor_temperature")]
    sys.exit("no device prefix: set $VEVOR_HA_PREFIX, or refresh dev/docs/ha-entities.txt "
             "(dev/tools/check_ha_card.py --refresh)")


PREFIX = ha_prefix()
STATE = ROOT / "dev/state/temperature_watch_last.txt"
# A 20 s frame cannot move the temperature by more than this: sensor and air have thermal mass.
SPIKE_C = 6.0


def ha_history(entity: str, since: datetime.datetime):
    token = (ROOT / ".ha_token").read_text(encoding="utf-8").strip()
    url = "%s/api/history/period/%s?filter_entity_id=%s%s&minimal_response" % (
        HA_URL, since.isoformat(), PREFIX, entity)
    request = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    data = json.load(urllib.request.urlopen(request, timeout=45))
    return data[0] if data else []


def decode_temperature(raw: str):
    """Return (temperature, every other field) from an ESPHome hex frame, or None."""
    try:
        byte_values = [int(x, 16) for x in raw.split()]
    except ValueError:
        return None
    if len(byte_values) < 21 or byte_values[0] != 0xAA:
        return None
    temp = (byte_values[5] * 256 + byte_values[6] - 500) / 10.0
    return {
        "temperature": temp,
        "station_id": byte_values[2] * 256 + byte_values[3],
        "humidity": byte_values[7],
        "wind_raw": byte_values[8] * 256 + byte_values[9],
        "gust_raw": byte_values[10],
        "direction_raw": byte_values[11] * 256 + byte_values[12],
        "rain_raw": byte_values[13] * 256 + byte_values[14],
        "uv": byte_values[15],
        "lux_raw": byte_values[16] * 256 + byte_values[17],
        "tx_counter": byte_values[18],
        "byte19": byte_values[19],
        "byte20": byte_values[20],
        "counter_pair_ok": byte_values[20] == (byte_values[18] + 1) & 0xFF,
    }


def main() -> int:
    hours = 6.0
    if "--hours" in sys.argv:
        hours = float(sys.argv[sys.argv.index("--hours") + 1])

    # Window: since the previous run when that is longer, so nothing falls between two ticks.
    now = datetime.datetime.now(datetime.timezone.utc)
    start = now - datetime.timedelta(hours=hours)
    if STATE.exists():
        try:
            previous_run = datetime.datetime.fromisoformat(STATE.read_text(encoding="utf-8").strip())
            start = min(start, previous_run)
        except ValueError:
            pass

    facts = []
    facts.append("window: %s -> %s UTC (%.1f h)"
                 % (start.strftime("%d/%m %H:%M"), now.strftime("%d/%m %H:%M"), hours))

    # --- Restarts: the sensor names the cause, that is what it was added for.
    restarts = []
    for point in ha_history("reset_reason", start):
        state = str(point.get("state"))
        t = point.get("last_changed", point.get("last_updated", ""))
        if state not in ("unavailable", "unknown"):
            restarts.append((t[11:19], state))
    facts.append("restarts seen: %d" % len(restarts))
    for t, state in restarts:
        facts.append("   %s UTC  %s" % (t, state))

    # --- Temperature spikes, with the raw frame that carried them when HA kept it.
    raw_history = ha_history("last_raw_frame", start)
    raw_frames = []
    for point in raw_history:
        raw_frames.append((point.get("last_changed", point.get("last_updated", "")), str(point.get("state"))))

    spikes = []
    previous = None
    for point in ha_history("outdoor_temperature", start):
        try:
            value = float(point.get("state"))
        except (TypeError, ValueError):
            continue
        t = point.get("last_changed", point.get("last_updated", ""))
        if previous is not None and abs(value - previous) > SPIKE_C:
            # the raw frame at that instant, if Home Assistant recorded one
            nearest = None
            for ts, s in raw_frames:
                if ts <= t:
                    nearest = s
            spikes.append((t, previous, value, nearest))
        previous = value

    facts.append("temperature spikes (> %.1f C between two frames): %d" % (SPIKE_C, len(spikes)))
    for t, before, after, nearest in spikes:
        facts.append("   %s UTC  %.1f -> %.1f C" % (t[11:19], before, after))
        if nearest and "aa 00" in nearest:
            facts.append("      raw: %s" % nearest)
            detail = decode_temperature(nearest)
            if detail:
                facts.append("      decoded: %s" % json.dumps(detail))

    # --- Counters right now: context for whatever is reported above.
    for entity, label in (("valid_frames", "valid frames"), ("rejected_frames", "rejected frames"),
                          ("rmt_captures", "RMT captures"), ("reset_reason", "reset reason now"),
                          ("outdoor_temperature", "temperature now")):
        points = ha_history(entity, now - datetime.timedelta(minutes=20))
        if points:
            facts.append("%s: %s" % (label, points[-1].get("state")))

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(now.isoformat(), encoding="utf-8")

    print("\n".join(facts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
