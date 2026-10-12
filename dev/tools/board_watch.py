#!/usr/bin/env python3
"""Every-6h watch, read from the CARD ITSELF — never from Home Assistant.

Why the card and not Home Assistant: HA only ever sees what the firmware published. A frame the
temperature gate refused never reaches HA, so HA cannot tell whether the gate fired at all. The
gate's own counters, on the board, are the direct evidence — and the card is also where the restart
reason lives, and where the raw bytes of a refusal are logged.

Read-only. It never presses a button, never flashes, never writes to the board.

    dev/tools/board_watch.py [--seconds 30]

What it reports, as facts and never as verdicts:
  * DELTAS of every counter since the previous run. Absolute counters say nothing: this board has
    restarted 15 times in a day, and every restart zeroes them. The deltas are what happened since.
  * the restart reason the card publishes (that sensor was added precisely to answer this).
  * any refusal/restart line caught in the log window, verbatim, raw bytes included.

The counters that matter for the temperature guard — temp_refused, rain_refused, repaired — exist
ONLY in the periodic log summary, not as entities, so the window is what carries them.
"""

import asyncio
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
STATE = ROOT / "dev/state/board_watch_state.json"
SUMMARY = re.compile(
    r"captures=(\d+) \(\+(\d+)\), frames=(\d+), rejects=(\d+), repaired=(\d+) \((\d+) refused\), "
    r"rain_refused=(\d+), temp_refused=(\d+), last pulses=(\d+), longest=(\d+)")
INTEREST = re.compile(
    r"no frame for|restart #|Rebooting safely|refused|restart|reboot|Reboot|Booting|Reset|panic|"
    r"Brownout|watchdog|re-arm|CC1101|safe_mode|V7IN1|definitely not taken", re.I)


def board_host() -> str:
    """No address in the code (dev/tools/_common.py is the reference for that rule): $VEVOR_HOST,
    else the cache dev/tools/find_esp32.py writes."""
    host = os.environ.get("VEVOR_HOST", "").strip()
    if host:
        return host
    cache = ROOT / "dev/state" / "DEVICE_IP"
    if cache.exists() and cache.read_text(encoding="utf-8").strip():
        return cache.read_text(encoding="utf-8").strip()
    sys.exit("no board address: set $VEVOR_HOST, or run dev/tools/find_esp32.py once "
             "(it writes the cache this tool reads)")


def previous_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return {}


async def main() -> int:
    import aioesphomeapi

    seconds = 30
    if "--seconds" in sys.argv:
        seconds = int(sys.argv[sys.argv.index("--seconds") + 1])

    key = None
    m = re.search(r"^encryption_key:\s*(\S+)\s*$",
                  (ROOT / "esphome/secrets.yaml").read_text(encoding="utf-8"), re.M)
    if m:
        key = m.group(1)

    facts = []
    client = aioesphomeapi.APIClient(board_host(), 6053, None, noise_psk=key)
    try:
        await asyncio.wait_for(client.connect(login=True), 15)
    except Exception as e:
        # An unreachable board is itself the news: say it, do not fail silently.
        print("board unreachable (%s) — nothing read, no state written" % str(e)[:80])
        return 0

    info = await asyncio.wait_for(client.device_info(), 15)
    facts.append("firmware compiled: %s" % info.compilation_time)

    entities, _ = await asyncio.wait_for(client.list_entities_services(), 20)
    states = {}
    r = client.subscribe_states(lambda s: states.__setitem__(s.key, getattr(s, "state", None)))
    if r is not None:
        await r

    keys = {(getattr(x, "name", "") or ""): x.key for x in entities}
    v = lambda n: states.get(keys.get(n))
    await asyncio.sleep(2)

    summary = {}
    lines = []

    def on_log(msg):
        try:
            txt = msg.message.decode("utf8", "replace")
        except Exception:
            return
        txt = re.sub(r"\x1b\[[0-9;]*m", "", txt).strip()
        line = SUMMARY.search(txt)
        if line:
            summary.update({
                "captures": int(line.group(1)), "frames": int(line.group(3)),
                "rejects": int(line.group(4)), "repaired": int(line.group(5)),
                "repairs_refused": int(line.group(6)), "rain_refused": int(line.group(7)),
                "temp_refused": int(line.group(8)), "longest": int(line.group(10)),
            })
        if INTEREST.search(txt):
            lines.append(txt)

    subscription = client.subscribe_logs(on_log, log_level=5)
    if subscription is not None:
        try:
            await subscription
        except Exception:
            pass
    # The counters that matter (temp_refused, rain_refused, repaired) exist ONLY in the periodic
    # summary, which is emitted every 20 s — and which starts again from zero after a restart. A
    # fixed window therefore misses it exactly when a restart just happened, i.e. when the deltas
    # matter most. So wait for a summary rather than hope to cross one, and say so if none comes.
    limit = max(seconds, 45)
    waited = 0
    while waited < limit and not summary:
        await asyncio.sleep(2)
        waited += 2
    if not summary:
        facts.append("no periodic summary within %d s: counters unavailable for this run" % limit)
    await client.disconnect(force=True)

    current = {
        "reset_reason": str(v("Reset reason")),
        "stations": str(v("Station ID")),
        "entities": len(entities),
    }
    current.update(summary)

    previous = previous_state()

    facts.append("entities: %d | reset reason: %s | station: %s"
                 % (len(entities), current["reset_reason"], current["stations"]))
    if not previous:
        facts.append("first run: no previous state, deltas cannot be computed this time")
    elif "frames" not in previous:
        facts.append("previous state carries no counters (an earlier run was interrupted): "
                     "deltas unavailable this time")
    else:
        facts.append("deltas since the previous run:")
        for field in ("frames", "rejects", "captures", "repaired", "repairs_refused",
                     "rain_refused", "temp_refused"):
            before = previous.get(field)
            after = current.get(field)
            if before is None or after is None:
                continue
            delta = after - before
            mark = ""
            if delta < 0:
                mark = "  <- NEGATIVE: the board restarted (counters back to zero)"
            elif delta and field in ("temp_refused", "rain_refused", "repairs_refused"):
                mark = "  <- a gate refused frames"
            elif delta and field == "repaired":
                mark = "  <- frames rebuilt by the decoder's bounded repair"
            facts.append("   %-16s %6d -> %-6d  (%+d)%s" % (field, before, after, delta, mark))
        if previous.get("reset_reason") != current["reset_reason"]:
            facts.append("restart: the reason changed, %s -> %s"
                         % (previous.get("reset_reason"), current["reset_reason"]))

    if lines:
        facts.append("lines caught in the %d s window:" % seconds)
        for line in lines[-25:]:
            facts.append("   " + line[:180])
    else:
        facts.append("nothing of interest in the %d s window" % seconds)

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(current, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(facts))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
