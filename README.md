# Vevor 7-in-1 868 MHz receiver — ESP32-C3 SuperMini + CC1101 (ESPHome)

An ESPHome firmware that **decodes** the 868 MHz frames of a Vevor 7-in-1 weather station
(ref. YT60309, Fujian Youtong family) and publishes outdoor temperature, humidity, wind
(speed / gust / direction), rainfall, UV index, illuminance and the sensor's low-battery flag to
Home Assistant — while **rejecting** every invalid frame (header, checksum, TX counter, physical
plausibility gate).

**Status: working and verified.** Frames decoded with checksum and TX counter validated,
**20.0 s cadence**, plausible values, **field-by-field agreement between the C++ firmware and an
independent Python decoder**, and cross-checked against a second receiver (`state/DONE.md`,
`evidence/`).

> Correction worth knowing about: an early validation claimed "60 frames in 10 minutes". It was
> **30 measurements delivered twice** (a stitching rule applied to whole bursts — see pitfall 5).
> The defect is fixed and covered by the off-board tests. Details and evidence: `state/DONE.md`
> and `evidence/`.

---

## Repository layout — production vs. test tooling

The two halves are deliberately kept apart: **`esphome/` is what you flash**, everything else is
how the flash is validated. Nothing under `esphome/` needs the test tooling, and the test tooling
never touches the radio.

| Path | Half | Role |
|---|---|---|
| `esphome/vevor-7in1.yaml` | **Production** | the complete ESPHome configuration (firmware) |
| `esphome/includes/vevor_protocol.h` | **Production** | protocol: pulses → bits → bytes → values, validation gate. Pure C++, **testable off-board** |
| `esphome/components/vevor_7in1/` | **Production** | C++ component: plugs into `remote_receiver`, stitches burst fragments, counts, triggers |
| `esphome/components/cc1101/` | **Production** | local copy of ESPHome's `cc1101` component with the fixes this board needs (`README-LOCAL.md`) |
| `esphome/secrets.yaml.example` | **Production** | template to copy to `esphome/secrets.yaml` (never versioned) |
| `docs/wiring.svg` | **Production** | wiring diagram |
| `docs/forecast-rules.md` | **Rules** | the console's forecast icon is not receivable; tables to reproduce an equivalent in Home Assistant |
| `docs/firmware-design-notes.md` | **Notes** | why the production YAML says what it says: the measured reason behind each setting |
| `tests/` | **Test** | off-board suite: independent Python encoder + C++ unit tests (377 checks, no board needed) |
| `tools/` | **Test** | build, flash, log capture, independent evaluation, frequency scan, A/B comparison (`tools/README.md`) |
| `evidence/` | **Test** | versioned JSON reports backing every claim (`evidence/README.md`) |
| `references/` | Context | protocol description + rtl_433 reference source (GPL-2.0) |
| `state/` | Journal | full iteration log (French) — what worked, what failed, why |

Internal maintenance documents (`state/*`, `tools/README.md`, `evidence/README.md`) and the
in-firmware comments are in French; this README is the English entry point.

---

# PART 1 — PRODUCTION (firmware + Home Assistant integration)

## 1.1 What you need

| Item | Note |
|---|---|
| ESP32-C3 SuperMini | the board this firmware is built for (`board: esp32-c3-devkitm-1`) |
| CC1101 module, **868 MHz** version | 433 MHz modules are the majority in search results and **do not work** here |
| 868 MHz antenna | the supplied helical antenna is enough under ~15 m; a λ/4 wire (8.6 cm) is much better |
| 10 kΩ resistor | pull-up from the module's VCC to CSN — see §1.2 |
| 10 µF / 25 V capacitor | decoupling across the module's GND/VCC — see §1.2 |
| A 5 V supply for the board | the module itself must **never** see 5 V |

## 1.2 Wiring

![Wiring diagram](docs/wiring.png)

Full vector version: [`docs/wiring.svg`](docs/wiring.svg). The table below is the same information in
text form — **wire by signal name, not by header pin number** (module boards number the 8-pin
header differently).

| ESP32-C3 SuperMini | CC1101 module | Signal |
|---|---|---|
| 3V3 | VCC | 3.3 V supply (**never 5 V**) |
| GND | GND | ground |
| GPIO4 | SCLK | SPI clock |
| GPIO6 | MOSI | SPI data out |
| GPIO5 | MISO | SPI data in |
| GPIO7 | CSN | chip select |
| GPIO3 | GDO0 | demodulated data stream, consumed by `remote_receiver` |
| — | GDO2 | not connected |

```
                ESP32-C3 SuperMini                    CC1101 (868 MHz module)
                +--------------+                      +-------------------+
     3V3  ------| 3V3          |----------------------| VCC                |
     GND  ------| GND          |----------------------| GND      [10 µF]   |  10 µF / 25 V across
     GPIO4------| GPIO4        |----------------------| SCLK               |  GND <-> VCC of the
     GPIO6------| GPIO6        |----------------------| MOSI               |  module, soldered on
     GPIO5------| GPIO5        |----------------------| MISO               |  the module pins
     GPIO7------| GPIO7        |--------+-------------| CSN                |
     GPIO3------| GPIO3        |----------------------| GDO0               |     ANT ---- λ/4, 8.6 cm
                +--------------+        |              +-------------------+                (or the helical
                                        +---[10 kΩ]---+ 3V3                                     antenna)
                                                       ^ pull-up on CSN
```

### Why the two extra components (measured, not guessed)

Symptom treated: the chip **intermittently lost register writes** — a register read back at its
**factory value** (`MDMCFG4` written `0xC8` read `0x8C`), i.e. a chip that was never configured and
therefore demodulated nothing, at any frequency. Reads stayed reliable: the fault was in the
**link**, not in the chip. After fitting both components, the firmware's own write check went from
"1 register permanently not taken" to **"0 registers permanently not taken", four cycles in a row**.

* **10 kΩ between the module's VCC (3.3 V) and CSN (GPIO7)**, soldered on the module pins. Why: at
  reset the ESP32-C3 GPIOs are **high-impedance** (Espressif datasheet Table 2-1: IE, no WPU) — with
  no pull-up, CS floats for the whole boot, the chip can see spurious chip selects and end up in the
  indeterminate state described by the CC1101 datasheet (§4.9). 4.7–10 kΩ works; 10 kΩ is the value
  on the reference ESP32-C3 + CC1101 board. **The YAML option `cs_pin: mode: {pullup: true}` does not
  replace this resistor**: it is only applied at the pin's `setup()`, i.e. after the boot window.
* **10 µF / 25 V capacitor between the module's GND and VCC** (supply-current decoupling).

### Recommended, not fitted yet

* **100 nF** ceramic right at the module's VCC pin — that is the one that acts on fast edges; it
  **complements** the 10 µF, it does not replace it.
* **Separate supply for the module**, not the SuperMini's 3V3 pin: a dedicated 3.3 V LDO (≥ 300 mA)
  fed from 5 V, **common ground mandatory**. SuperMini clones top out around 250 mA and their rail
  collapses during Wi-Fi peaks.
* **22 Ω in series on SCLK** (and possibly MOSI/CS) if the wires stay long.
* **Nothing on the crystal**: the crystal and its load capacitors are inside the module; touching
  them detunes the frequency. Nothing on the RF path between the chip and the antenna either.
* Check that **DCOUPL is not tied to 3.3 V** (a schematic error flagged by TI). On a module it is
  normally not exposed — only relevant on a bare chip board.
* **Never power from 5 V**, and never declare a second SPI device on the chip's bus.

### Cutting the module's power with a transistor (idea, NOT fitted)

The owner confirmed (02/10) that **no transistor is fitted**: the real assembly has exactly the two
components above. The following is a **lead**, not a description of the build.

On this assembly, **roughly every other boot brings up a mute chip** (`Chip ID: 0xFFFF`, all SPI
reads `0xFF`): it never gets configured and stays in IDLE. A software reset does not recover it
(three attempts, three failures); a **real power cut** does. Driving the module's supply from a GPIO
would therefore give the firmware the only remedy that works — and the cycle would be immediate
instead of the ten minutes the current recovery takes.

```
        3.3 V ──┬───────────┬────────────┬──── source of the P-MOSFET
                │           │            │
            [10 kΩ]      [100 nF]     [10 µF]        (10 kΩ = gate pulled to 3.3 V ⇒ off)
                │           │            │
                │           └────────────┴──── drain ⇒ VCC of the CC1101 module
                │
   free GPIO ──[1 kΩ]── gate of the P-MOSFET
```

* **Logic-level P-MOSFET** in series with the module's VCC (e.g. AO3401, IRLML6402): source to
  3.3 V, drain to the module. Gate pulled to 3.3 V through **10 kΩ** (module **off** by default at
  boot, hence a clean chip at power-up) and driven by a **free GPIO** through **1 kΩ**.
  GPIO **low = module powered**; leaving the GPIO high-impedance = module off.
* **Check the transistor conducts at Vgs = −3.3 V**: a non logic-level MOSFET will not open at that
  voltage. Pick one with Vgs(th) below 1.5 V.
* Keep the **10 µF** (and the 100 nF) **on the module side**, i.e. after the transistor.
* **Simpler but dirtier variant**: switch the module's **ground** (N-MOSFET or 2N2222 NPN, driven
  through 1 kΩ). In that case the SPI lines drive an unpowered chip: add **100 Ω in series on
  SCLK / MOSI / CS** to limit the current in the protection diodes.
* Firmware side: one GPIO output, a cycle **off ≥ 300 ms then on**, then re-initialise the radio
  component. The datasheet asks for a 0 → 1.8 V ramp in ≤ 5 ms and a cut of at least 1 ms — a few
  hundred milliseconds satisfies both comfortably.

## 1.3 Entities published to Home Assistant

All of them come from entities declared in `esphome/vevor-7in1.yaml`. `name:` values are French in
the firmware (changing them would rename existing entities in an already-running installation);
rename them in the YAML if you want another language — the entity `id` and the published *values*
are what automations should bind to.

### Measurements

| Entity (`name:`) | HA type | Unit | Accepted range | What it is |
|---|---|---|---|---|
| `Température extérieure` | sensor, `temperature` | °C | **−40 … +60** (frame encoding −50.0 … +359.5) | outdoor temperature, 0.1 °C steps, `(raw − 500) × 0.1` |
| `Humidité extérieure` | sensor, `humidity` | % | **0 … 100** | outdoor relative humidity |
| `Vent vitesse moyenne` | sensor, `wind_speed` | km/h | **0 … 180** | average wind speed, `raw / 8.333` |
| `Vent rafale` | sensor, `wind_speed` | km/h | **0 … 180** | wind gust of the frame, `raw / 1.25` (always ≥ average) |
| `Vent direction` | sensor | ° | **0 … 359** | wind direction; the station measures 16 sectors, the frame carries a 12-bit angle |
| `Pluie cumulée` | sensor, `precipitation` | mm | **0 … 15 209.8** | cumulative rain since the last reset, 0.233 mm per tip; monotone (a decrease is corruption, a zero is only accepted after 3 consecutive frames) |
| `Index UV` | sensor | – | **0 … 16** | UV index, `(b15 & 0x1F) − 1` |
| `Luminosité` | sensor, `illuminance` | lx | **0 … 327 670** | illuminance; ×10 when bit 15 of the field is set (station spec: 0–200 klux) |

Values outside the accepted range are **not published**: the frame is rejected and counted (see the
plausibility gate in `vevor_protocol.h`). The station's own specifications (manual, p. 26-27) are:
outdoor temperature −40…70 °C, humidity 1…99 %, wind 0…180 km/h, 16 wind directions, rain
0…12 999 mm, UV 0…16, light 0…200 klux — the accepted ranges above are the ones this firmware
enforces.

### Status and diagnostics

| Entity (`name:`) | HA type | Unit | Range | What it is |
|---|---|---|---|---|
| `Batterie station faible` | binary_sensor, `battery` | – | on/off | low-battery flag of the outdoor sensor |
| `ID station` | sensor (diagnostic) | – | 0 … 65 535 | station ID (hex). **It changes when the sensor's batteries are changed** |
| `Compteur TX` | sensor (diagnostic) | – | 0 … 255 | frame counter, +1 every 20 s (used to detect missed/replayed bursts) |
| `Trames valides` | sensor (diagnostic) | – | 0 … 4 294 967 295 | frames decoded and published since boot |
| `Trames rejetées` | sensor (diagnostic) | – | 0 … 4 294 967 295 | candidates whose sync word was seen but which failed validation (checksum / counter / plausibility) — the real noise counter |
| `Captures RMT` | sensor (diagnostic) | – | 0 … 4 294 967 295 | bursts captured on GDO0 (0 = nothing reaches the chip) |
| `Doublons ignorés` | sensor (diagnostic) | – | 0 … 4 294 967 295 | burst delivered twice by the RMT within 5 s |
| `Dernière trame brute` | text_sensor (diagnostic) | – | 21 hex bytes | last decoded frame, as received |
| `Dernier verdict` | text_sensor (diagnostic) | – | `ok` or a reason | safety net: verdict on the last delivered frame |

### Controls

| Entity (`name:`) | HA type | Range | What it is |
|---|---|---|---|
| `Fréquence CC1101` | number (config) | **430 … 930 MHz**, step 0.005 | live radio frequency: scan for the station without reflashing |
| `Dump impulsions` | button (config) | – | logs the raw pulse durations of the next captures (the only way to analyse the real waveform from outside) |
| `Réappliquer la config radio` | button (config) | – | re-runs the radio re-arm sequence (`cc1101.reset`) |
| `Redémarrer la carte` | button (config) | – | reboot — the measured remedy for the mute-chip condition |

## 1.4 The console's forecast icon is not receivable — rules for Home Assistant

**Read this before expecting a forecast from this board.** The display console shows one of six icons
(Sunny, Partly Cloudy, Cloudy, Rainy, Stormy, Snowy) computed from **its own barometer** (Vevor
YT60309 manual, section *Weather Forecast*, p. 20: range 600-1100 hPa, pressure trend over the past
hour, with the manual's own caveat that such a forecast is "about 65-70%" accurate). The outdoor
7-in-1 sensor **neither measures nor transmits pressure**: its payload is temperature, humidity, wind
speed and direction, rainfall, UV index and illuminance, and the 21-byte frame decoded here has no
pressure field.

> **The station's own forecast icon cannot be read off the air with this hardware.** No firmware can
> do it, and this project does not pretend otherwise. An earlier iteration estimated the six
> categories *inside the firmware*, with a sun-position dependency; it was **removed at the owner's
> request** — when the station cannot provide the information, the receiver must not invent it.

The board therefore publishes **measured quantities only** (see §1.3), and any forecast is left to
Home Assistant, where the decision is visible, editable and testable. The rules — thresholds and their
sources, rain-intensity window, cloudiness proxy, anti-flapping — are documented as tables in
[`docs/forecast-rules.md`](docs/forecast-rules.md), to be applied with Home Assistant's `sun`
integration and the Vevor entities.

* One manual rule needs no firmware support and stays directly usable: the **ice alert** (p. 20,
  "when outdoor temperature is lower than 1 °C, the snowflake icon will appear") is a plain threshold
  on a quantity we *do* receive — one template sensor away.

## 1.5 Install and flash

```bash
# 1. Secrets (once) — never versioned
cp esphome/secrets.yaml.example esphome/secrets.yaml && $EDITOR esphome/secrets.yaml

# 2. Nothing else to configure: the board needs no location, no time zone and no clock (see §1.4)

# 3. Build
tools/build.sh                       # writes BUILD OK / BUILD FAIL to build/last_status.txt

# 4. Flash — USB the first time, then OTA by IP
#    An ESP32-C3 flashed over USB shows up as /dev/ttyACM0 (the C3's USB-Serial-JTAG).
#    /dev/ttyUSB0 may exist as an unusable node (c---------) : do not target it by default.
tools/flash.sh /dev/ttyACM0
tools/flash.sh 172.16.0.205          # OTA afterwards

# 5. Capture the board's logs (native API, port 6053 — no browser needed)
.venv/bin/python tools/capture_logs.py --host 172.16.0.205 --seconds 120 \
    --out logs/capture_$(date +%Y%m%d_%H%M%S).log

# 6. Evaluate the captured frames (independent Python decoder + acceptance criteria)
tools/eval_frames.py logs/capture_*.log --json logs/report.json
```

### Publishing to the repository

The remote is already paired with this machine: `origin` points at
`git@github-vevor:WizardPC/esphome-vevor-7-in-1.git`, an SSH alias backed by a deploy key present on
this host (checked: `ssh -T git@github-vevor` answers *"Hi WizardPC/esphome-vevor-7-in-1!"*).

```bash
git push origin main     # fetch and push through the deploy key: no token required
```

**Do not misdiagnose this.** The deploy key allows `fetch`/`push`, **not** the GitHub API. `gh` is
logged into no host and the `GITHUB_TOKEN` in the environment is a commented-out placeholder, so
**opening a pull request needs a PAT** (or a click in the web UI). In particular, `gh auth status`
reporting "not logged into any GitHub hosts" does **not** mean the repository is out of reach: git
publishing works from any session, because the remote and the key live on disk, not in the agent's
context.

## 1.6 Home Assistant notes

* The board uses the **native API** with encryption; HA's ESPHome integration discovers it on the
  LAN. If mDNS does not cross your router (as here), the `wifi: use_address:` value in the YAML is
  what OTA and log capture target, and HA can be pointed at the IP manually.
* `api: reboot_timeout: 0s` is deliberate: the board must not reboot when no client is connected,
  otherwise a log-capture session gets cut in the middle.
* The board **reboots itself on purpose** when no new frame has been published for 10 minutes
  (`interval: 20s` block): on this hardware, one boot in two brings up a chip that is absent from
  the SPI bus, and a reboot is the only measured remedy. The reboot is a guard rail, not an
  instability — see pitfall 7.
* Everything the firmware exposes is listed in §1.3; diagnose with `Trames rejetées` (a decoding
  problem) vs `Captures RMT` (nothing reaching the chip) before touching anything.
* `Luminosité` is in lux and can be large (up to 327 670 lx); `Index UV` has no unit and ranges
  0…16.

---

# PART 2 — TESTS, VALIDATION AND TOOLING

## 2.1 Off-board test suite (no board needed)

```bash
tools/run_tests.sh
```

Steps: self-check of the independent Python encoder (it must reproduce the rtl_433 reference frame
**byte for byte**) → generation of the test frames and pulse scenarios → compilation of the C++ test
with the compiler bundled in `.venv-dev` (zig) → execution.

Current state: **377 checks, 0 failures.** The suite covers the happy path, inverted polarity,
truncated captures, jitter, timing bias, inter-burst gaps, frame stitching (and the rule that a
*complete* burst must never be stitched), the plausibility gate and its rejection reasons, the
period-selection sweep, the plausibility gate on injected impossible frames, and the fragment
policy (a complete burst is never stitched).

Two properties make it a real check rather than a tautology:

* the C++ decoder and the Python encoder are **written separately from the same specification**, so
  their agreement is meaningful;
* the suite contains **external anchors** — the rtl_433 reference frame, and hand-computed expected
  values for the ×10 lux branch — so an error present in *both* implementations cannot self-validate.
  This has already caught a wrong wind scale copied from one side to the other.

Two non-negotiable rules for the suite itself: it needs **no hardware**, and it is the only place
allowed to define what "decoded correctly" means.

## 2.2 Independent decoder and window reports

`tools/eval_frames.py` re-implements the decoding in Python, independently of the firmware's C++, and
**compares frame by frame** with the values the firmware published. A `PASS` verdict requires
simultaneously:

* at least N valid frames (`--min-valid`, 10 by default);
* values inside the physical ranges **and** a coherent lux/UV pair (zero lux with a non-zero UV, or
  lux out of the UV's reach);
* a TX-counter advance consistent with the elapsed time (~1.95 tick/s: a zero difference means the
  RMT delivered the burst twice, a multiple means missed bursts);
* a ~20 s cadence on the significant intervals;
* **field-by-field agreement with the C++ firmware** on every frame.

A report that contains an anomaly (incoherent sequence, implausible values, disagreement with the
C++) can no longer conclude `PASS`: the list of refusal reasons is in the JSON report.
`tools/summarize_window.py` adds long-window analysis (median/min/max cadence, gaps, rejections,
per-10-minute emission counts, value ranges) and **reuses its report's verdict** — a summary cannot
contradict its own report.

`tools/count_probe.py`, `tools/analyze_*.py` and the capture helpers are documented in
`tools/README.md`, which separates the tools of the current flow from the diagnostic tools kept for
history. Three contracts are enforced there: never write to or print a secret; never announce a
success without a measurement ("nothing measured" → **NULL MEASUREMENT** and exit code 3, "measured,
no frame" → exit code 0, technical failure → exit code 2); never conclude on a window without having
checked the chip's state, since one boot in two brings up a mute chip.

## 2.3 Field tools

| Tool | Role |
|---|---|
| `tools/build.sh` | compile (`BUILD OK` / `BUILD FAIL` written to `build/last_status.txt`) |
| `tools/flash.sh` | flash over OTA (USB the first time) |
| `tools/run_tests.sh` | off-board suite, no board required |
| `tools/capture_logs.py` | capture the board's logs over the native API (port 6053) |
| `tools/eval_frames.py` | independent Python decoder, frame-by-frame verdict |
| `tools/summarize_window.py` | window summary, generated from a report |
| `tools/read_state.py` | read the board's entities over the API |
| `tools/press_button.py` | press a firmware button (`--list-buttons`) |
| `tools/dump_pulses.py` | fetch the raw durations of the "Dump impulsions" button |
| `tools/decoder_dump.py` | decode those raw durations off-board (4 periods × 2 polarities × 8 alignments) |
| `tools/scan_freq.py`, `tools/balayer_frequence.py` | scan the frequency **without reflashing** |
| `tools/ab_cycle.py` | alternate two frozen binaries in interleaved windows (witness / ours) |
| `tools/verify_radio_config.py` | check the radio configuration actually applied |

## 2.4 Evidence kept in the repository

`evidence/` holds the versioned JSON reports that back the claims in `state/DONE.md`: a **validated**
one-hour window (180 frames, 0 rejections, `PASS`) and a **faulty** one (181 frames, `FAIL`, three
refusal reasons) — the second is kept on purpose: it documents the defect that the plausibility gate
and the stitching rule were written for. Each report keeps the raw 21-byte frames, so the claims
remain checkable after a plain `git clone`, even though the full logs (`logs/`) are not versioned.
Details and regeneration commands: `evidence/README.md`.

## 2.5 Method

* **No invented values.** Any statement about decoding must cite a raw log line. If nothing is
  received, say "no signal", never "it should work".
* **Never trust a script's console output through a pipe**: `tail` and `tee` mask exit codes. Read
  `build/last_status.txt` and `logs/last_flash_status.txt` — the source of truth for a step's success.
* **One hypothesis at a time** on the radio side (frequency, deviation, bandwidth) and record the
  measured effect.
* **Never delete a log trace**: traces are the evidence. Raw logs are excluded from the repository
  (`.gitignore`) but the reports that quote them are not.
* After 3 iterations without improvement: change strategy instead of repeating the same attempt, and
  say so explicitly in the journal.
* Diagnostic order when no packet arrives: (1) does the CC1101 answer on SPI? (2) frequency,
  (3) deviation/bandwidth, (4) sync word/length, (5) wiring/antenna.

---

## Known pitfalls of this build (measured, not supposed)

* **`loop()` is interrupt-driven: an early `return` in `setup()` that skips `attach_interrupt` makes
  the board permanently deaf, with no other symptom.** The component calls `disable_loop()` at the
  top of `loop()`; only the GDO0 edge interrupt wakes it again. If the interrupt is not attached, the
  chip still receives: FIFO filled, GDO0 high, `MARCSTATE = 0x0D`, register writes verified,
  `radio=ok` — and **no frame, ever**. This is what our non-blocking identity re-read did until
  03/10: it returned before the `defer()` that attaches GDO0, so any boot where the chip was slow to
  answer (about one in two, and more often right after an OTA) ended up configured and deaf. The
  stock ESPHome driver has no such early return, which is why it looked like it decoded better.
  The interrupt is now attached **before any early return**, and `reset()` re-attaches it so a
  re-arm really recovers.

1. **The CC1101 must remain the ONLY device on its SPI bus.** Declaring a second SPI device in the
   YAML — even with a **free, unwired** CS pin — is enough to silence the chip: 0 captures, 0 frames,
   no error. Measured by alternating with a reference firmware on the same board in the same emission
   windows: 0 frames/60 s with it, 5 frames/60 s without. This is what cost this project the most (a
   diagnostic instrumentation caused it): **instrumenting the chip from the same firmware costs the
   reception.** Measure from outside (log capture) instead.
2. **The station transmits CONTINUOUSLY** — one burst every 20 s, day and night. A "0 frame" is
   therefore **never** silence from the station: it is the receiver. But a "0 frame" proves nothing
   unless a reference receiver decoded in the **same window** — because one boot in two brings up a
   mute chip (pitfall 7), an empty window can be either a mute board or an absence of emission. This
   lesson comes from a corrected mistake: the station's supposed "silent phases" (11:36→12:36 and
   13:53→14:53 on 01/10) were in fact **mute boards**. `tools/ab_cycle.py` alternates two firmwares
   (flash a frozen binary → wait → capture → JSONL line) to compare under equal conditions in time.
3. **No `gdo0_pin` in the `cc1101` block** when `remote_receiver` consumes the same pin: the
   component schedules a deferred `pin_mode(INPUT)` that breaks the RMT channel.
4. **`ota: encryption: {}`** makes the API key serve as the OTA key (no separate password to manage).
   Conversely, to take over a board running third-party firmware you need a fallback YAML **without**
   `encryption:` under `ota:` (`esphome/flash-plain.yaml`) plus the already-compiled binary via
   `--file`.
5. **Only stitch FRAGMENTS of a burst, never a whole burst.** The C3's RMT sometimes delivers a burst
   in two pieces (96 + 82 pulses) and they have to be rejoined by merging same-sign pulses at the
   seam. But applying that stitching to **every** capture makes it re-read the PREVIOUS burst:
   measured on 01/10, the faulty version published **60 frames for 30 measurements** (each TX counter
   exactly twice, 20 s apart, outside the 5 s anti-duplicate window). Hence the rule: decode the
   capture ALONE first, stitch only if it is too short to carry a burst (`MAX_FRAGMENT_TIMINGS`).
   Exercised by the `_coupe_*` tests.
6. **A well-formed frame is not a JUST frame.** Measured on 01/10 over a one-hour window: out of 181
   valid frames (header + checksum + counter all good, 20.0 s cadence), **2 were wrong** — a one-bit
   shift at extraction doubles every value byte, and they reported 178.2 mm of rain instead of 59.2
   and a direction of 779°. The checksum of a bit-shifted frame can therefore pass. Hence two rules:
   (a) a **plausibility gate** in the firmware (`vevor_protocol.h`) refuses what is physically
   impossible — direction > 359°, humidity > 100 %, wind > 180 km/h, UV > 16 — and the component
   counts them in its rejections; (b) **stitching fragments** is not innocent: it applies only to
   captures too short to carry a burst, never to a complete one.
7. **One boot in two can bring up the chip absent from the SPI bus** — and nothing signals it except a
   silent `captures=0`. Measured on 01/10 over 6 flash → measure cycles with the same binary:
   mute / healthy / mute / healthy / mute / healthy. On the mute boots the component reads back
   `Chip ID: 0xFFFF` (all SPI reads `0xFF`): the chip does not answer, is never configured, stays in
   factory IDLE and produces nothing on GDO0. The hot re-arm (`reset` + settings + `begin_rx`) does
   **not** recover it (3 attempts, 3 failures); **the reboot does** — the chip's state flips at each
   boot, because the chip keeps its registers while the ESP32 restarts. Hence the embedded
   supervision (`interval: 20s`): radio state logged every 20 s, 30 soft re-initialisation attempts
   (30 × 20 s = 10 min) while no **new frame** is published, then an **automatic reboot**. The reboot
   is triggered by frame silence alone, without consulting `is_failed()`: since the station transmits
   continuously, any prolonged silence is a receiver fault whatever the cause. Ten reboots in quick
   succession (one per ~10 min cycle), then falling back to one reboot every 15 min.

## USB access from an LXC container (Proxmox)

To flash over USB from a container, pass the host's serial port into the LXC
(`/etc/pve/lxc/<id>.conf`, then restart the container). The ESP32-C3 appears as
**USB-Serial-JTAG**, i.e. as **`/dev/ttyACM0`** (character device, major **166**) — and **not** as
`/dev/ttyUSB0` (major 188), which may exist without being usable (`c---------`):

```
lxc.mount.entry: /dev/ttyACM0 dev/ttyACM0 none bind,optional,create=file
lxc.cgroup2.devices.allow: c 166:* rwm
```

Then check `ls -l /dev/ttyACM0` (the node must be `crw-rw----` and reachable) and membership of the
`dialout` group (`usermod -aG dialout <user>`). Without this, compilation, OTA and logs still work,
but the very first flash has to be done elsewhere (web.esphome.io or the ESPHome add-on).

## Licence and attributions

* **GPL-2.0** (see `LICENSE`).
* The frame format comes from **rtl_433** (`src/devices/vevor_7in1.c`, GPL-2.0); a reference copy is
  kept in `references/vevor_7in1.c`. This repository's decoder derives from it, hence the GPL-2.0
  licence.
* The **`WizardPC/esphome-vevor-7in1`** project (same protocol, asynchronous architecture) served as
  a comparison point — measured radio parameters and protocol pitfalls — never as a code base.
* The **Vevor YT60309 owner's manual** is the source for two facts only: the console computes its six
  forecast icons from its own barometer, and the ice alert trips below 1 °C. No manual text is
  redistributed here beyond those short quotations.
