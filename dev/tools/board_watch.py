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
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
STATE = ROOT / "dev/state/board_watch_state.json"
SUMMARY = re.compile(
    r"captures=(\d+) \(\+(\d+)\), frames=(\d+), rejects=(\d+), repaired=(\d+) \((\d+) refused\), "
    r"rain_refused=(\d+), temp_refused=(\d+), last pulses=(\d+), longest=(\d+)")
INTERET = re.compile(
    r"refused|restart|reboot|Reboot|Booting|Reset|panic|Brownout|watchdog|re-arm|CC1101|"
    r"safe_mode|V7IN1|definitely not taken", re.I)


def etat_precedent() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return {}


async def main() -> int:
    import aioesphomeapi

    secondes = 30
    if "--seconds" in sys.argv:
        secondes = int(sys.argv[sys.argv.index("--seconds") + 1])

    cle = None
    m = re.search(r"^encryption_key:\s*(\S+)\s*$",
                  (ROOT / "esphome/secrets.yaml").read_text(encoding="utf-8"), re.M)
    if m:
        cle = m.group(1)

    faits = []
    client = aioesphomeapi.APIClient("172.16.0.205", 6053, None, noise_psk=cle)
    try:
        await asyncio.wait_for(client.connect(login=True), 15)
    except Exception as e:
        # An unreachable board is itself the news: say it, do not fail silently.
        print("board unreachable (%s) — rien de lu, aucun etat enregistre" % str(e)[:80])
        return 0

    info = await asyncio.wait_for(client.device_info(), 15)
    faits.append("firmware compiled: %s" % info.compilation_time)

    entites, _ = await asyncio.wait_for(client.list_entities_services(), 20)
    etats = {}
    r = client.subscribe_states(lambda s: etats.__setitem__(s.key, getattr(s, "state", None)))
    if r is not None:
        await r

    cles = {(getattr(x, "name", "") or ""): x.key for x in entites}
    v = lambda n: etats.get(cles.get(n))
    await asyncio.sleep(2)

    resume = {}
    lignes = []

    def on_log(msg):
        try:
            txt = msg.message.decode("utf8", "replace")
        except Exception:
            return
        txt = re.sub(r"\x1b\[[0-9;]*m", "", txt).strip()
        ligne = SUMMARY.search(txt)
        if ligne:
            resume.update({
                "captures": int(ligne.group(1)), "frames": int(ligne.group(3)),
                "rejects": int(ligne.group(4)), "repaired": int(ligne.group(5)),
                "repairs_refused": int(ligne.group(6)), "rain_refused": int(ligne.group(7)),
                "temp_refused": int(ligne.group(8)), "longest": int(ligne.group(10)),
            })
        if INTERET.search(txt):
            lignes.append(txt)

    abonnement = client.subscribe_logs(on_log, log_level=5)
    if abonnement is not None:
        try:
            await abonnement
        except Exception:
            pass
    # The counters that matter (temp_refused, rain_refused, repaired) exist ONLY in the periodic
    # summary, which is emitted every 20 s — and which starts again from zero after a restart. A
    # fixed window therefore misses it exactly when a restart just happened, i.e. when the deltas
    # matter most. So wait for a summary rather than hope to cross one, and say so if none comes.
    limite = max(secondes, 45)
    attendu = 0
    while attendu < limite and not resume:
        await asyncio.sleep(2)
        attendu += 2
    if not resume:
        faits.append("no periodic summary within %d s: counters unavailable for this run" % limite)
    await client.disconnect(force=True)

    actuel = {
        "reset_reason": str(v("Reset reason")),
        "stations": str(v("Station ID")),
        "entities": len(entites),
    }
    actuel.update(resume)

    precedent = etat_precedent()

    faits.append("entities: %d | reset reason: %s | station: %s"
                 % (len(entites), actuel["reset_reason"], actuel["stations"]))
    if not precedent:
        faits.append("first run: no previous state, deltas cannot be computed this time")
    elif "frames" not in precedent:
        faits.append("previous state carries no counters (an earlier run was interrupted): "
                     "deltas unavailable this time")
    else:
        faits.append("deltas since the previous run:")
        for clef in ("frames", "rejects", "captures", "repaired", "repairs_refused",
                     "rain_refused", "temp_refused"):
            avant = precedent.get(clef)
            apres = actuel.get(clef)
            if avant is None or apres is None:
                continue
            delta = apres - avant
            marque = ""
            if delta < 0:
                marque = "  <- NEGATIVE: the board restarted (counters back to zero)"
            elif delta and clef in ("temp_refused", "rain_refused", "repairs_refused"):
                marque = "  <- a gate refused frames"
            elif delta and clef == "repaired":
                marque = "  <- frames rebuilt by the decoder's bounded repair"
            faits.append("   %-16s %6d -> %-6d  (%+d)%s" % (clef, avant, apres, delta, marque))
        if precedent.get("reset_reason") != actuel["reset_reason"]:
            faits.append("restart: the reason changed, %s -> %s"
                         % (precedent.get("reset_reason"), actuel["reset_reason"]))

    if lignes:
        faits.append("lines caught in the %d s window:" % secondes)
        for ligne in lignes[-25:]:
            faits.append("   " + ligne[:180])
    else:
        faits.append("nothing of interest in the %d s window" % secondes)

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(actuel, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(faits))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
