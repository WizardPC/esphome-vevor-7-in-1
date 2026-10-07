#!/usr/bin/env python3
"""Reception watch for the Vevor 7-in-1 station (board 172.16.0.205).

Goal: never again miss a decoding failure. The script
  - subscribes to the board's log via the ESPHome API (without encryption) and archives it as-is;
  - monitors the arrival of frames;
  - when reception breaks (no frame published for PANNE_S seconds) while the board still
    receives captures, it presses "Dump pulses" ITSELF to flush the raw pulses of the bursts
    at fault, and writes a snapshot of the log at that instant.

Lessons of 05/10/2026 (the first three were real bugs, observed in service):
  - a MUTE socket raises NO exception in aioesphomeapi: after a board flash, the watch stayed
    alive and frozen for 7 minutes without writing a line. The only reliable detection is the
    absence of lines for CANARI_S — the board publishes a counter every ~20 s;
  - on each reconnection, the old client must be explicitly disconnected, otherwise its
    subscriptions survive and every line is logged twice;
  - the snapshot must be written INSIDE the `with` block that read the log, otherwise the file
    is created empty (two 0-byte snapshots observed);
  - the failure branch must PRESS the button: announcing it without doing it produces no
    pulse, hence no proof (observed: "### FAILURE" marker then zero `capture #N` line).
  - the button key is read by the script (`list_entities_services`), never hardcoded:
    a frozen key survives a reflash poorly.
  - the button press runs in a THREAD: `button_command` is synchronous and, called from the
    asyncio loop, it blocked it without raising — watch frozen twice, once after a board
    restart (5th bug observed in service on 05/10);
  - every network call is bounded by `asyncio.wait_for`: a connection that never completes
    blocked the loop BEFORE reaching the canary, which then served no purpose.

Output: dev/state/veille_reception.log (raw log + markers), and dev/state/panne_*.txt
(snapshot of the log at the moment of each detected failure).
"""
import asyncio
import datetime
import os
import sys
import threading
import time

try:
    from aioesphomeapi import APIClient, LogLevel
except ImportError:
    sys.exit("aioesphomeapi missing from the interpreter: use .venv/bin/python")

HOST = "172.16.0.205"
PORT = 6053
NOM_BOUTON_VIDAGE = "Dump pulses"
PANNE_S = 240                  # no frame for 4 min while captures keep arriving
IMMOBILE_S = 900               # no capture at all for 15 min: board mute, no point insisting
REESSAI_S = 300                # do not request a flush more than once per 5-min slice
VIDAGE_PERIODIQUE_S = 600      # courtesy flush every 10 min of silence
CANARI_S = 45                  # no line at all: the board publishes every ~20 s, so two
                               # missed heartbeats suffice — at 90 s the dead socket was
                               # caught AFTER the failure, and the press fell into the void

ETAT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "state")
JOURNAL = os.path.join(ETAT, "veille_reception.log")


def horodate() -> str:
    return datetime.datetime.now().strftime("%d/%m %H:%M:%S")


class Veille:
    def __init__(self) -> None:
        self.derniere_trame = time.time()
        self.derniere_capture = time.time()
        self.derniere_ligne = time.time()
        self.dernier_vidage = 0.0
        self.frames = 0
        self.dump_key = None
        self.cli = None

    def ligne(self, texte: str) -> None:
        with open(JOURNAL, "a", encoding="utf8") as f:
            f.write(f"[{horodate()}] {texte}\n")

    def on_log(self, message) -> None:
        brut = getattr(message, "message", None)
        if isinstance(brut, (bytes, bytearray)):
            brut = brut.decode("utf8", "replace")
        elif brut is None:
            brut = str(message)
        self.derniere_ligne = time.time()
        self.ligne(brut.rstrip())
        if "V7IN1 OK" in brut:
            self.derniere_trame = time.time()
            self.frames += 1
        elif "captures=" in brut:
            self.derniere_capture = time.time()

    def _vider(self, raison: str) -> None:
        """Press "Dump pulses". Doing so is the ONLY way to get the raw pulses.

        The press runs in a thread: `button_command` is synchronous, and calling it directly in
        the asyncio loop froze it (without raising) — that is the watch failure observed twice
        on 05/10. The thread also updates the canary so the reconnection is immediate.
        """
        if self.cli is None or self.dump_key is None:
            self.ligne(f"### {raison} — flush IMPOSSIBLE (unknown button)")
            return
        self.ligne(f"### {raison} — pulse flush requested")

        def appuyer() -> None:
            try:
                self.cli.button_command(self.dump_key)
                self.dernier_vidage = time.time()   # ONLY if the press went through: a failed press
            except Exception as exc:                 # must be retried right away, not in 5 min
                # A dead socket does not warn: the canary is forced to trigger on the next
                # round, so the reconnection is immediate and the flush replayed right after.
                self.derniere_ligne = 0.0
                self.ligne(f"### button press failed ({exc!r}) — immediate reconnection")

        threading.Thread(target=appuyer, daemon=True).start()

    def _instantane(self) -> None:
        instantane = os.path.join(ETAT, f"panne_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt")
        try:
            with open(JOURNAL, encoding="utf8") as src:
                lignes = src.readlines()[-4000:]                 # read INSIDE the with...
            with open(instantane, "w", encoding="utf8") as dst:  # ...and write in another:
                dst.writelines(lignes)                           # otherwise the file stays empty
            self.ligne(f"### snapshot before failure: {os.path.basename(instantane)}")
        except OSError as exc:                                   # pragma: no cover
            self.ligne(f"### snapshot impossible: {exc}")

    async def surveiller(self) -> None:
        maintenant = time.time()
        if maintenant - self.derniere_capture > IMMOBILE_S:
            return                                    # nothing arrives at all: another problem
        if maintenant - self.derniere_trame < PANNE_S:
            return
        if maintenant - self.dernier_vidage < REESSAI_S:
            return
        self._vider(f"FAILURE: no frame for {int(maintenant - self.derniere_trame)} s "
                    "while captures keep arriving")
        self._instantane()


async def main() -> None:
    veille = Veille()
    veille.ligne("=== watch started ===")
    while True:
        cli = None
        try:
            cli = APIClient(HOST, PORT, None)
            await asyncio.wait_for(cli.connect(login=True), 30)
            ents, _ = await asyncio.wait_for(cli.list_entities_services(), 30)
            for e in ents:
                if getattr(e, "name", "") == NOM_BOUTON_VIDAGE:
                    veille.dump_key = e.key
            veille.cli = cli
            cli.subscribe_logs(veille.on_log, log_level=LogLevel.LOG_LEVEL_DEBUG)
            veille.derniere_ligne = time.time()
            veille.ligne(f"--- connected to the board, logging "
                         f"(flush button: {veille.dump_key}) ---")
            while True:
                await asyncio.sleep(10)
                if time.time() - veille.derniere_ligne > CANARI_S:
                    veille.ligne(f"--- no line for {int(time.time() - veille.derniere_ligne)} s: "
                                 "mute socket, reconnecting ---")
                    break
                if time.time() - veille.derniere_trame > VIDAGE_PERIODIQUE_S:
                    veille._vider(f"### long silence ({int(time.time() - veille.derniere_trame)} s)")
                await veille.surveiller()
        except Exception as exc:                                 # reconnexion permanente
            veille.ligne(f"--- connection lost ({exc!r}), retry in 30 s ---")
            await asyncio.sleep(30)
        finally:
            veille.cli = None
            if cli is not None:
                try:
                    await asyncio.wait_for(cli.disconnect(force=True), 10)   # otherwise: ghost subscriptions
                except Exception:                                # pragma: no cover
                    pass


if __name__ == "__main__":
    asyncio.run(main())
