# Development tools — inventory of `dev/tools/`

This folder holds the **20 tools the project still uses**: build and flash, capture and evaluate the
board's logs, the radio scans, and the watches. Everything runs offline except the calls that address
the board or Home Assistant, and nothing here touches the radio except through the board's own API. The
one-off probe scripts that accumulated during the investigation are not part of the repository.

**Run everything with the project interpreter**: `python dev/tools/<tool>.py --help` (or
`.venv/bin/python …`). Board tools take the host from `$VEVOR_HOST`; the API key from `$ESPHOME_API_KEY`
or the firmware YAML (`_common.key_from_yaml` resolves `!secret`). The Home Assistant checks take `$HA_URL`
(else the git-ignored `.ha_url`) and read `.ha_token`. `run_tests.sh` needs `.venv-dev` (the C++ test
compiler, `zig`); the entity and template checks need `.venv` (PyYAML, jinja2). A relative `--out`/`--json`
targets the **repository root**, never the current directory.

**Removing a tool.** No file is deleted without checking its references — several scripts dismissed as
"unused" turned out to be load-bearing (one was the probe behind a board button). Before deleting one:

```bash
grep -rn --exclude-dir=logs --exclude-dir=reviews --exclude-dir=.git \
     --exclude-dir=.esphome --exclude-dir=.venv "FILE_NAME.py" .
```

## 1. The tools of the current flow

| Tool | Role |
|---|---|
| `build.sh` | compiles the firmware (`BUILD OK` / `BUILD FAIL` written to a file) |
| `flash.sh` | uploads over USB or OTA |
| `run_tests.sh` | off-board suite (steps 1-6, the entity and template checks included), no board required |
| `capture_logs.py` | captures logs over the native API (port 6053); `--append` to add to a file |
| `eval_frames.py` | independent Python decoder: frame-by-frame verdict against the firmware |
| `summarize_window.py` | window summary **generated from its report** (`--report`); refuses to whitewash a FAIL |
| `read_state.py` | reads the board's entities over the API (captures, frames, frequency…) |
| `press_button.py` | presses a firmware button (`--list-buttons` for the list) |
| `dump_pulses.py` | fetches the raw durations behind the "Dump pulses" button |
| `decoder_dump.py` | decodes those durations off-board (4 periods × 2 polarities × 8 alignments) |
| `scan_freq.py` | sweeps the frequency live, without reflashing |
| `verify_radio_config.py` | replays the component's register math: what the CC1101 will actually receive |
| `board_watch.py` | every-6h watch read from the CARD: counter **deltas** and the reset reason |
| `temperature_spike_watch.py` | every-6h watch: did a temperature spike or a restart happen, and why |
| `find_esp32.py` | discovers the board's IP (native API on 6053) |
| `net_scan.py` | locates Home Assistant and the ESPHome boards on a subnet |
| `serial_log.py` | raw read of the ESP32 serial console — fallback when the board is unreachable |
| `check_ha_card.py` | offline check of both Lovelace cards against `dev/docs/ha-entities.txt` and the firmware |
| `check_ha_templates.py` | posts every card template to Home Assistant; **SKIPPED** if HA is unreachable |
| `_common.py` | shared base: paths, key resolution, connection, variant tables, atomic writes |

`check_ha_card.py` verifies `examples/ha-card-fr.yaml` and `examples/ha-card-en.yaml`, each against the
words of its **own** language (the French card and the English card share their structure and thresholds,
never their labels). `check_ha_templates.py` is the honest complement: instead of re-implementing Home
Assistant's logic (which can only ever test its own version of it), it posts each template to HA and fails
on any refusal.

## 2. What a tool in this folder must never do

- write to a secret, or print it (`esphome/secrets.yaml`, `.ha_token`);
- claim success without a measurement: "nothing measured" → **NULL MEASUREMENT** and exit code 3;
  "measured, no frame" → exit code 0; technical failure → exit code 2;
- conclude on a window without having checked the chip's state: one boot in two brings up a mute chip
  (`Chip ID: 0xFFFF`) on this build;
- be tested on a hand-made log: ESPHome colourises its lines, and a parser that does not strip ANSI
  sequences reports "no frame" on a window that contains 181 of them.

One tool deserves a warning: `decoder_dump.py` replays the **fixed grid** (periods 87-90 µs), not the
current firmware's measured-period estimator or its bounded repair, so its "no valid frame" is **not**
the firmware's verdict — it tells whether the raw stream holds a frame at all, not whether the firmware
would have decoded it.
