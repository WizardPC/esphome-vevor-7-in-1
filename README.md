# Vevor 7-in-1 weather station receiver — ESP32-C3 + CC1101 (ESPHome)

An ESPHome firmware that receives a **868 MHz** Vevor / Fujian Youtong 7-in-1 weather station and
publishes its measurements to Home Assistant. If all you want is to solder a board and flash it,
this page is all you need — everything else (design notes, protocol, test tooling) lives in
[`dev/`](dev/README.md).

The station emits a 21-byte frame every 20 seconds. The firmware decodes it from the CC1101's
demodulated output, checks it (header, checksum, counter, physical plausibility) and hands it to
Home Assistant.

> **Frequency band.** 868 MHz is the short-range band used in **Europe**. The station is sold in
> several regional variants and this firmware is written for the **868 MHz** one: the CC1101 module
> must be the 868 MHz version, and the radio settings in the YAML (868.35 MHz, 70 kHz deviation,
> 162 kHz filter) are those of that variant.

---

## 1. What you need

| Item | Note |
|---|---|
| ESP32-C3 | SuperMini or devkit — the firmware targets `board: esp32-c3-devkitm-1` |
| CC1101 module, **868 MHz** | 433 MHz modules are the majority in search results and **do not work** here |
| Antenna for 868 MHz | the module's coil antenna is enough to start; a 8.6 cm wire (λ/4) receives better |
| 1 resistor **10 kΩ** | between the module's VCC and CSN |
| 1 capacitor **10 µF** | between the module's GND and VCC; any voltage rating above the 3.3 V rail works (6.3 V or more) |
| Home Assistant + ESPHome | the **ESPHome Device Builder** add-on is enough — no local toolchain needed |

---

## 2. Wiring

![Wiring diagram](dev/docs/wiring.png)

Full vector version: [`dev/docs/wiring.svg`](dev/docs/wiring.svg). Wire **by signal name, not by
header pin number** (module boards number their 8-pin header differently).

| ESP32-C3 | CC1101 | Signal |
|---|---|---|
| 3V3 | VCC | supply (**never 5 V**) |
| GND | GND | ground |
| GPIO4 | SCLK | SPI clock |
| GPIO6 | MOSI | SPI data out |
| GPIO5 | MISO | SPI data in |
| GPIO7 | CSN | chip select |
| GPIO3 | GDO0 | demodulated data out (feeds the RMT receiver) |
| GPIO10 | GDO2 | not used |

Plus the two components, **soldered on the module's pins**:

* **10 kΩ between VCC (3.3 V) and CSN** — at reset the ESP32-C3's GPIOs are high-impedance, so
  without a pull-up the chip-select line floats during the whole boot and the CC1101 can see
  spurious chip selects. The YAML option `cs_pin: mode: {pullup: true}` does **not** replace it: it
  only takes effect after the pin's `setup()`, i.e. after the boot window.
* **10 µF between GND and VCC** — supply decoupling.

A supply separate from the board's 3V3 pin further improves stability. Do **not** put anything on
the crystal, and do not touch the RF path between the chip and the antenna.

> **Two hard rules.** Never power the module from 5 V. And the CC1101 must stay the **only** SPI
> device on its bus: a second SPI peripheral — even with a free, unwired CS pin — makes the chip
> mute.

---

## 3. Flash it

1. In **ESPHome Device Builder**: *New device* → give it a name → *Skip* the Wi-Fi wizard.
2. Paste the content of [`esphome/vevor-7in1.yaml`](esphome/vevor-7in1.yaml) into the device's
   config. It is self-contained: it pulls its components from this public repository, no file of
   this repo is needed next to it.
3. Create `secrets.yaml` next to it with four keys:
   `wifi_ssid`, `wifi_password`, `ap_password`, `encryption_key`
   ([`esphome/secrets.yaml.example`](esphome/secrets.yaml.example) gives the exact names:
   `encryption_key` is the 32-byte base64 key, generated with `openssl rand -base64 32`).
4. **Install** → *Plug into this computer* the first time (USB), then over the air by IP.

Nothing else is required: the board needs no location, no time zone and no clock, and every value
that depends on *your* installation stays in `secrets.yaml`, which is git-ignored.

Three settings cover the cases where the network or the board gets in the way; all three are
commented in [`esphome/vevor-7in1.yaml`](esphome/vevor-7in1.yaml) and in
[`esphome/secrets.yaml.example`](esphome/secrets.yaml.example):

* **`use_address`** — only if ESPHome cannot find the board over the network. Home Assistant
  normally reaches it by name (mDNS); set a fixed address if your board sits behind a gateway, on
  another subnet or in a VLAN, where that name does not resolve. Symptom: the compile succeeds and
  the upload fails with *no route to host*.
* **`wifi: output_power:`** — the YAML ships `output_power: 8.5dB`, the lowest accepted value
  (range 8.5-20.5 dB). On boards whose Wi-Fi antenna is a **ceramic chip antenna**, the default
  transmit power couples into the CC1101 sitting next to it and the receiver goes deaf; 8.5 dB is
  what keeps the two apart. Raise it only if your access point refuses that level. Symptom: the
  board never appears on the network after flashing.
* **`station_id:`** — the YAML ships `station_id: 0`, which means *adopt the first station heard*.
  Set your own ID to pin one station: every other ID is then ignored, which keeps a neighbour's
  station on the same protocol out of your Home Assistant. The ID changes when the station's
  batteries are changed; the component logs a warning when another ID appears, and 0 (or the
  `Station ID (0 = learn)` entity in Home Assistant) re-learns.

---

## 4. What it publishes to Home Assistant

All entities below are declared in `esphome/vevor-7in1.yaml`. **`name:` values are English**;
rename them in the YAML if you want another language — the entity `id` and the published *values*
are what automations should bind to. Changing a name in an already-running installation creates
*new* entities in Home Assistant: the old ones go unavailable.

### Measurements

| Entity (`name:`) | Type | Unit | Accepted range | What it is |
|---|---|---|---|---|
| `Outdoor temperature` | sensor, `temperature` | °C | **−40 … +60** | outdoor temperature, 0.1 °C steps, `(raw − 500) × 0.1` |
| `Outdoor humidity` | sensor, `humidity` | % | **0 … 100** | outdoor relative humidity |
| `Wind speed` | sensor, `wind_speed` | km/h | **0 … 180** | average wind speed, `raw / 8.333` |
| `Wind gust` | sensor, `wind_speed` | km/h | **0 … 180** | wind gust of the frame, `raw / 1.25` (always ≥ average) |
| `Wind direction` | sensor | ° | **0 … 359** | wind direction; the station measures 16 sectors, the frame carries a 12-bit angle |
| `Rain total` | sensor, `precipitation` | mm | **0 … 15 209.8** | cumulative rain since the last reset, 0.233 mm per tip. Monotone: a rise of more than 5 mm between two frames, and any non-zero decrease, are rejected as corruption; a decrease to zero is accepted (battery change) |
| `UV index` | sensor | – | **0 … 16** | UV index, `(b15 & 0x1F) − 1` |
| `Illuminance` | sensor, `illuminance` | lx | **0 … 327 670** | illuminance; ×10 when bit 15 of the field is set |

Values outside the accepted ranges are **not** published: the frame is rejected and counted instead
(see the plausibility gate in `vevor_protocol.h`).

### Reception quality

| Entity (`name:`) | Type | Unit | What it is |
|---|---|---|---|
| `Reception rate` | sensor (diagnostic) | % | share of the station's **own** transmissions actually decoded, over its last 30 frames (~10 min), computed from the station's counter — not from elapsed time |
| `Reception window decoded` | sensor (diagnostic) | – | the first term of that ratio, so a dashboard can read `29 / 30` instead of trusting a percentage |
| `Reception window emitted` | sensor (diagnostic) | – | the second term of that ratio |

### Diagnostics

| Entity (`name:`) | Type | Unit | What it is |
|---|---|---|---|
| `Station battery low` | binary_sensor, `battery` | – | low-battery flag of the outdoor sensor |
| `Station ID` | sensor (diagnostic) | – | station ID in decimal (the ID `33995` reads `0x84cb`). **It changes when the sensor's batteries are changed** |
| `TX counter` | sensor (diagnostic) | – | frame counter, +39 every 20 s (used to detect missed or replayed bursts) |
| `Valid frames` | sensor (diagnostic) | – | frames decoded and published since boot |
| `Rejected frames` | sensor (diagnostic) | – | candidates whose sync word was seen but which failed validation (checksum / counter / plausibility) — the real noise counter |
| `RMT captures` | sensor (diagnostic) | – | bursts captured on GDO0 (0 = nothing reaches the chip) |
| `Duplicates ignored` | sensor (diagnostic) | – | burst delivered twice by the RMT within 5 s |
| `Last raw frame` | text_sensor (diagnostic) | – | last decoded frame, as received (21 hex bytes) |
| `Last verdict` | text_sensor (diagnostic) | – | `ok` or a reason — verdict on the last delivered frame |
| `Reset reason` | text_sensor (diagnostic) | – | why the ESP32 restarted (`Brownout`, `Task Watchdog`, `Panic`, `power-on event`, …) |

A few counters are visible in the board's log rather than as entities — among them the rain
refusals, which is what to look for if the rain value ever stops moving when you expect it to rain.

### Controls

| Entity (`name:`) | Type | Range | What it is |
|---|---|---|---|
| `CC1101 frequency` | number (config) | **430 … 930 MHz**, step 0.005 | live radio frequency: scan for the station without reflashing |
| `RX filter bandwidth` | number (config) | **58 … 812 kHz**, step 1 | live filter bandwidth |
| `Data rate` | number (config) | **600 … 500 000 baud**, step 50 | live symbol rate |
| `FSK deviation` | number (config) | **1.5 … 381 kHz**, step 0.5 | live FSK deviation |
| `Watchdog silent slots before re-arm` | number (config) | – | silent 20 s slots before the component re-arms the radio (`cc1101.reset`); compiled default 3 (60 s) |
| `Watchdog max silence before restart` | number (config) | – | silence after which the board restarts itself; compiled default 180 s |
| `Station ID (0 = learn)` | number (config) | – | 0 adopts the first station heard, any other value pins that station |
| `Dump pulses` | button (config) | – | logs the raw pulse durations of the next captures (the only way to analyse the real waveform from outside) |
| `Re-apply radio config` | button (config) | – | re-runs the radio re-arm sequence (`cc1101.reset`) |
| `Restart board` | button (config) | – | reboot — the remedy for the mute-chip condition |

---

## 5. Known limitations

* **A mute board after a boot is a known state, not a wrong wiring.** On a marginal assembly,
  roughly every other boot brings up a chip that does not answer on the SPI bus at all
  (`Chip ID: 0xFFFF` in the logs). No software recovers it — the firmware restarts the board on its
  own after a few minutes of silence, and a **real power cut** always fixes it. If your board sees
  nothing at all, power-cycle it before suspecting anything else.
* **The console's forecast icon cannot be received.** The outdoor sensor measures and transmits
  temperature, humidity, wind, rain, UV and illuminance — **no barometric pressure**. The station's
  display console derives its six forecast icons (Sunny … Snowy) from its own barometer, so no
  firmware can read that forecast off the air, and this one therefore publishes measured quantities
  only. To rebuild an equivalent icon in Home Assistant, use the rules in
  [`dev/docs/forecast-rules.md`](dev/docs/forecast-rules.md) — with their sources — and the
  ready-to-paste dashboard card under [`examples/`](examples/).
* **Rain jumps are refused on purpose.** The rain counter of this station has been seen jumping by
  physically impossible amounts, so the firmware rejects a rise of more than 5 mm between two
  frames and any non-zero decrease — both are corruption, even when the frame's checksum is valid.
  A decrease to zero is accepted (battery change).

---

## 6. Repository layout

| Where | What |
|---|---|
| [`esphome/`](esphome/) | the firmware: one YAML, the `vevor_7in1` component (frame decoder, watchdog) and a local fork of the `cc1101` component |
| [`examples/`](examples/) | the reference Home Assistant dashboard card, in French and in English |
| [`dev/README.md`](dev/README.md) | the developer document: local install, tooling, tests, entity consistency checks |
| [`dev/docs/`](dev/docs/) | wiring diagram, design notes, bit-timing analysis, forecast rules |
| [`dev/tests/`](dev/tests/) | off-board test suite: an independent Python encoder plus C++ unit tests, no board needed |
| [`dev/tools/`](dev/tools/) | build, flash, log capture, frame evaluation, frequency scan, reception watch |
| [`dev/references/`](dev/references/) | the protocol description and the rtl_433 reference source |
| [`dev/evidence/`](dev/evidence/) | the measurement that closed the project: one hour of reception, and the tool that reads it |

The frame decoder lives in `vevor_protocol.h` inside the `vevor_7in1` component and is testable
without any board: `dev/tools/run_tests.sh`.

## 7. Licence

This project is distributed under the **GNU General Public License, version 3.0 or later** — see
[`LICENSE`](LICENSE). Three parts meet in the firmware, and their licences set that floor:

| Part | Licence |
|---|---|
| everything written here: the YAML, the `vevor_7in1` component, the tests, the tooling | **GPL-3.0-or-later** (SPDX header on each source file) |
| the local fork under [`esphome/components/cc1101/`](esphome/components/cc1101/) | ESPHome's C++ code — **GPLv3** (ESPHome publishes its `.c/.cpp/.h` under the GPLv3, its Python under MIT) |
| [`dev/references/vevor_7in1.c`](dev/references/vevor_7in1.c) | the rtl_433 decoder, **GPL-2.0-or-later**, kept verbatim with its own copyright notice |
