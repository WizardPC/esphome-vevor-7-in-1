# Tools — what is active, what is a kept diagnostic

This folder mixes two things, and this file exists so they stop being confused. The underlying rule:
**no tool is removed without checking its references** — the list of "13 dead tools" from the 02/10
review turned out to be wrong at least for `dump_pulses.py`, which is the tool behind the "Dump
impulsions" button and which the same day settled the difference between a clean signal and
demodulator noise. Deleting a tool because it is "not mentioned in the README" throws away the
project's diagnostic toolbox.

To check that a tool is genuinely unused before removing it:

```bash
# References outside the tools/ folder (excluding logs and reviews)
grep -rn --exclude-dir=logs --exclude-dir=reviews --exclude-dir=.git \
     --exclude-dir=.esphome --exclude-dir=.venv "FILE_NAME.py" .
```

## 1. Tools of the current flow

| Tool | Role |
|---|---|
| `build.sh` | compiles the firmware (`BUILD OK` / `BUILD FAIL` written to a file) |
| `flash.sh` | uploads over OTA (USB the first time) |
| `run_tests.sh` | off-board suite (430 checks, no board required) |
| `capture_logs.py` | captures logs over the native API (port 6053); `--append` to add to a file |
| `eval_frames.py` | independent Python decoder: frame-by-frame verdict against the firmware |
| `summarize_window.py` | window summary **generated from its report** (`--rapport`), refuses to whitewash a FAIL |
| `read_state.py` | reads the entities over the API (captures, frames, frequency…) |
| `press_button.py` | presses a firmware button (`--list-buttons` for the list) |
| `dump_pulses.py` | fetches the raw durations behind the "Dump impulsions" button — the tool that separates a signal from noise |
| `decoder_dump.py` | decodes those raw durations off-board (4 periods × 2 polarities × 8 alignments) |
| `ab_cycle.py` | alternates several frozen binaries in interleaved windows (reference / ours) |
| `_common.py` | shared base: reads `api_key`, `maybe_await`, variant tables, atomic writes |
| `check_ha_card.py` | checks `dev/docs/ha-card.yaml` offline: every entity id against the measured HA listing (`dev/docs/ha-entities.txt`), that listing against the firmware's own declarations, and the banner's three templates executed on numeric scenarios (`dev/docs/forecast-rules.md`) |

Related experiment scripts live in `build/`: `valider_etat_b.sh` (only measures in state B of the
chip), `bissect_1mhz.sh`, `loterie_etats.sh`, `experience_*.sh`.

## 2. Kept diagnostics (historical, but functional)

They were used to establish the findings recorded in `state/PROGRESS.md`, and would be needed again
if a symptom came back. They are filed here for readability, not because they are broken.

| Tool | What it established |
|---|---|
| `balayer_frequence.py`, `regler_frequence.py`, `scan_freq.py`, `sweep_summary.py`, `sweep_async.sh` | frequency scan without reflashing; ruled out a detuned crystal |
| `analyze_stream.py`, `analyze_noise.py`, `analyze_radio_log.py`, `gdo0_rate_vs_freq.py` | analysis of the demodulated stream (carrier mode), of noise, and of the probe's output rate |
| `scan_async.py`, `boot_probe.py`, `boot_dump.sh`, `count_probe.py`, `serial_log.py` | boot and counting probes |
| `witness_fetch.py`, `witness_probe.py`, `witness_summary.py` | retrieval and analysis of the reference project (context only, never a code base) |
| `verify_radio_config.py`, `net_scan.py`, `find_esp32.py`, `tcp_probe.py` | configuration check, board and port discovery |
| `fix_python_env.sh`, `loop_monitor.sh` | the container's Python environment; fingerprint filter of the old scheduled loop (cron since removed) |
| `capture_logs.sh` | **replaced** by `capture_logs.py` (native API, not USB: the serial link truncates long lines) |

## 3. What a tool in this folder must never do

- write to a secret, or print it (`esphome/secrets.yaml`, `.ha_token`);
- claim success without a measurement: "nothing measured" → **NULL MEASUREMENT** and exit code 3;
  "measured, no frame" → exit code 0; technical failure → exit code 2;
- conclude on a window without having checked the chip's state: one boot in two brings up a mute chip
  (`Chip ID: 0xFFFF`) on this build — hence `build/valider_etat_b.sh`;
- be tested on a hand-made log: ESPHome colourises its lines, and a parser that does not strip ANSI
  sequences reports "no frame" on a window that contains 181 of them.
