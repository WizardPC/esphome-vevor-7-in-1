# MISSION — Vevor 7-in-1 868 MHz receiver (ESP32-C3 SuperMini + CC1101) under ESPHome

## Final objective (exit criterion)

A working ESPHome firmware that, continuously:

1. receives the 868 MHz frames from the Vevor 7-in-1 station and **decodes** them (all sensors);
2. publishes to Home Assistant: temperature, humidity, wind speed, gust, direction,
   cumulative rain, UV, illuminance, low battery;
3. **rejects** any invalid frame (checksum + counter);
4. runs stably (no reboot, no memory leak) and is documented.

"Functional" = at least 10 consecutive valid frames, paced at ~20 s, with
plausible values cross-checked against an independent source.

## Work split (anti-collision rule, validated on 30/09)

Two agents work on this repository: the **interactive session** (the human + the assistant in
the chat room) and **the scheduled loop** (the one that posts in #esphome). So they stop
overwriting each other's files:

- **The loop**: the radio and the hardware only — CC1101 parameters, build, flash, captures,
  frequency sweeps, measurements. It writes its trials in `state/PROGRESS.md` and advances
  `state/PHASE`.
- **The interactive session**: the decoder (`esphome/components/vevor_7in1/vevor_protocol.h`), the analysis
  tooling (`tools/eval_frames.py`), the tests and the documentation intended for other
  users.
- Before modifying a file outside its scope, note it in PROGRESS.md. In case of
  collision: `build/last_status.txt` or `logs/last_flash_status.txt` displays
  "BUILD ABORTED code=3" → wait and resume.
- Project goal: that **any user** with a station of this family
  reaches a working receiver with documentation, without depending on the current
  user's particular installation (IP, secrets, paths).

## Iteration loop (adaptive policy validated by the user)

One cycle = compile → flash → capture → evaluate → decide. The cadence **adapts to
the result** (no blind reflash):

| Observation after flash + capture | Decision |
|---|---|
| No valid frame after ~5 min | Fix the radio (frequency, deviation, bandwidth, syncword) then **reflash** |
| Valid frames but irregular, gaps > 25 s over 10 min | Adjust (RSSI/antenna/deviation) then **reflash** |
| Clean cadence ~20 s | **Let it run 30 min** and check the data consistency over the whole window |
| Clean cadence + consistency OK over 30 min | Write `state/DONE.md`, notify the user, stop the loop |

One iteration = one cycle. Do not reflash without having read the logs of the previous flash.

## Iteration loop (one iteration = one cycle)

1. Read `state/PROGRESS.md` (where we are, last hypothesis, next action).
2. Modify the firmware (`esphome/vevor-7in1.yaml`, `esphome/components/vevor_7in1/*.h`).
3. Compile: `tools/build.sh` → if it fails, fix and go back to 2.
4. Flash: `tools/flash.sh <ip_or_port>` (USB the first time, OTA afterwards).
5. Capture the logs: `.venv/bin/python tools/capture_logs.py --host <ip> --seconds <duration_s> --out logs/capture_*.log`.
6. Evaluate: `tools/eval_frames.py logs/capture_*.log` → JSON report.
7. Write in `state/PROGRESS.md`: what worked, what failed, the next action.
   Record the raw frames in `logs/raw_frames.jsonl`.
8. If the exit criterion is met → write `state/DONE.md` and tell the user.

## Non-negotiable rules

- **No invented value.** Any statement about the decoding must cite a raw log
  line. If nothing is captured, say so: "no signal", never "it must work".
- **Read before touching the radio**: `references/EXTERNAL_CONTEXT_WIZARDPC.md` — analysis
  (context, not code to reuse) of a working project on the same protocol. It gives
  **measured** radio settings (868.35 MHz / **70 kHz** deviation / **100 kHz** bandwidth /
  11 111 baud) — exactly the ones we ended up adopting: our old values
  (868.30 MHz / 37 kHz / 200 kHz) decoded nothing. They served as a guide, they are no longer
  hypotheses awaiting a test. It also documents protocol pitfalls to integrate into the self-evaluation
  (rain that can go down with a **valid** checksum, frames arriving cut, Station ID that
  changes at every power-up, rejection of `wind > 0` with `gust == 0`, lux/UV consistency).
- **Never trust the console output of a script passed through a pipe**: `tail` and `tee`
  mask the return codes. Read `build/last_status.txt` (BUILD OK/FAIL) and
  `logs/last_flash_status.txt` (FLASH OK/FAIL) — that is the source of truth for a step's success.
- One hypothesis at a time on the radio side (frequency, deviation, bandwidth), and
  note the measured effect in PROGRESS.md.
- Never delete a log trace: they serve as evidence for the evaluation.
- After 3 iterations without improvement: change strategy, do not repeat the same attempt.
  Do it explicitly in PROGRESS.md.
- Diagnostic order if no packet: (1) does the CC1101 respond to SPI? (2) frequency,
  (3) deviation/bandwidth, (4) syncword/length, (5) wiring/antenna.

## Reference wiring (to be confirmed with the user)

| ESP32-C3 SuperMini | CC1101 | Signal |
|---|---|---|
| 3V3 | VCC (pin 1) | 3.3 V supply |
| GND | GND (pin 2) | ground |
| GPIO6 | MOSI (pin 4) | SPI |
| GPIO4 | SCLK (pin 3) | SPI |
| GPIO5 | MISO (pin 6) | SPI |
| GPIO7 | CSN (pin 8) | chip select |
| GPIO3 | GDO0 (module pin 3) | data / packet interrupt |
| — | GDO2 | not connected |

GPIO2/GPIO8/GPIO9 are strapping pins on ESP32-C3: GPIO2 is avoided for GDO0.

## Environment

- Debian 13 LXC, IP `<container>`; Home Assistant `<home-assistant>` (HA Core was not responding
  on 8123 as of 30/09; the token is in `.ha_token`).
- **The board can be moved**: the user offered to put it elsewhere if the 868 MHz
  reception is bad. Operational consequence: **if `/dev/ttyACM0` disappears** (board
  unplugged from the Proxmox host), USB flashing is no longer possible → flash over **OTA**
  (`tools/flash.sh <board-ip>`). The logs remain available through the native API, but a board
  whose Wi-Fi breaks must be physically brought back to the host to be recovered over USB.
- ESPHome in `~/projets/vevor-7in1/.venv` (standalone Python + `esphome`, `aioesphomeapi`).
- ESP32 logs read via the native API (port 6053) with `tools/capture_logs.py` — **independent
  of Home Assistant**, therefore more reliable than reading the add-on's logs.
- **Compilation: in this container** (already verified, ~4 min, warm cache afterwards).
- **Component sources: `esphome/vevor-7in1.yaml` points to the public repository**
  (`github://WizardPC/esphome-vevor-7-in-1@main`) to stay copyable as-is by anyone.
  Any compilation from THIS repository must therefore force the local source, otherwise ESPHome downloads the
  published version and ignores the working tree: `tools/build.sh` and `tools/flash.sh` do it
  (`-s vevor_components components`) — go through them, or add this option by hand.
- **Flash: OTA from this container** (`tools/flash.sh <IP>`) as soon as the first flash has been
  done. HA's ESPHome Builder add-on is used for the very first flash (it has UART access to the HA
  host) and as a reference for device management.
- Sweep frequency: `tools/scan_freq.py` drives the firmware's `number` entity live
  (no reflash needed to search for the signal).

See `references/HOME_ASSISTANT.md` for the HA integration and what is scriptable on the add-on side.

## Review notes (02/10/2026)

- **Objective met, beyond the criterion.** The exit criterion asked for "at least 10 consecutive
  valid frames": the validated window (`evidence/rapport_fenetre_1h.json`) counts **180 in
  one hour**, 0 rejects, verdict `PASS`. The four points (reception, publication, rejection of
  invalid frames, stability) are covered.
- **"No reboot" (objective, point 4) reads as "no suffered reboot".** The firmware now restarts
  **deliberately** as a remedy for the intermittent SPI muteness (see `state/DONE.md` §2):
  this is not an instability, it is the safeguard. The original wording is dated.
- **The split / anti-collision rules**: they targeted two agents writing at the same time.
  They no longer apply if a single session works; keep them when two processes run.
- **Dated environment facts** (LXC `<container>`, HA `<home-assistant>`, HA Core mute on 8123 as of
  30/09): to refresh if the installation changes — not project requirements.
- **Fact corrected**: the decoder file cited at the top of this document (`esphome/components/vevor_7in1/vevor_7in1.h`)
  did not exist; the decoder is `esphome/components/vevor_7in1/vevor_protocol.h` (the `vevor_7in1.h` header is
  the component's own, under `esphome/components/vevor_7in1/`).
