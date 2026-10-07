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
import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
HA_URL = "http://192.168.2.104"
PREFIX = "sensor.jardin_vevor_7_in_1_weather_station_"
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
        octets = [int(x, 16) for x in raw.split()]
    except ValueError:
        return None
    if len(octets) < 21 or octets[0] != 0xAA:
        return None
    temp = (octets[5] * 256 + octets[6] - 500) / 10.0
    return {
        "temperature": temp,
        "station_id": octets[2] * 256 + octets[3],
        "humidity": octets[7],
        "wind_raw": octets[8] * 256 + octets[9],
        "gust_raw": octets[10],
        "direction_raw": octets[11] * 256 + octets[12],
        "rain_raw": octets[13] * 256 + octets[14],
        "uv": octets[15],
        "lux_raw": octets[16] * 256 + octets[17],
        "tx_counter": octets[18],
        "byte19": octets[19],
        "byte20": octets[20],
        "counter_pair_ok": octets[20] == (octets[18] + 1) & 0xFF,
    }


def main() -> int:
    heures = 6.0
    if "--hours" in sys.argv:
        heures = float(sys.argv[sys.argv.index("--hours") + 1])

    # Window: since the previous run when that is longer, so nothing falls between two ticks.
    now = datetime.datetime.now(datetime.timezone.utc)
    debut = now - datetime.timedelta(hours=heures)
    if STATE.exists():
        try:
            precedent = datetime.datetime.fromisoformat(STATE.read_text(encoding="utf-8").strip())
            debut = min(debut, precedent)
        except ValueError:
            pass

    faits = []
    faits.append("window: %s -> %s UTC (%.1f h)"
                 % (debut.strftime("%d/%m %H:%M"), now.strftime("%d/%m %H:%M"), heures))

    # --- Restarts: the sensor names the cause, that is what it was added for.
    redemarrages = []
    for point in ha_history("reset_reason", debut):
        etat = str(point.get("state"))
        t = point.get("last_changed", point.get("last_updated", ""))
        if etat not in ("unavailable", "unknown"):
            redemarrages.append((t[11:19], etat))
    faits.append("restarts seen: %d" % len(redemarrages))
    for t, etat in redemarrages:
        faits.append("   %s UTC  %s" % (t, etat))

    # --- Temperature spikes, with the raw frame that carried them when HA kept it.
    brut = ha_history("last_raw_frame", debut)
    trame_vers = []
    for point in brut:
        trame_vers.append((point.get("last_changed", point.get("last_updated", "")), str(point.get("state"))))

    pics = []
    precedent = None
    for point in ha_history("outdoor_temperature", debut):
        try:
            valeur = float(point.get("state"))
        except (TypeError, ValueError):
            continue
        t = point.get("last_changed", point.get("last_updated", ""))
        if precedent is not None and abs(valeur - precedent) > SPIKE_C:
            # the raw frame at that instant, if Home Assistant recorded one
            proche = None
            for ts, s in trame_vers:
                if ts <= t:
                    proche = s
            pics.append((t, precedent, valeur, proche))
        precedent = valeur

    faits.append("temperature spikes (> %.1f C between two frames): %d" % (SPIKE_C, len(pics)))
    for t, avant, apres, proche in pics:
        faits.append("   %s UTC  %.1f -> %.1f C" % (t[11:19], avant, apres))
        if proche and "aa 00" in proche:
            faits.append("      raw: %s" % proche)
            detail = decode_temperature(proche)
            if detail:
                faits.append("      decoded: %s" % json.dumps(detail))

    # --- Counters right now: context for whatever is reported above.
    for entite, nom in (("valid_frames", "valid frames"), ("rejected_frames", "rejected frames"),
                        ("rmt_captures", "RMT captures"), ("reset_reason", "reset reason now"),
                        ("outdoor_temperature", "temperature now")):
        points = ha_history(entite, now - datetime.timedelta(minutes=20))
        if points:
            faits.append("%s: %s" % (nom, points[-1].get("state")))

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(now.isoformat(), encoding="utf-8")

    print("\n".join(faits))
    return 0


if __name__ == "__main__":
    sys.exit(main())
