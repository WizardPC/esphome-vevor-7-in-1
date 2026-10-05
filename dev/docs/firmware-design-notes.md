# Firmware design notes — why the YAML says what it says

The production configuration lives in `esphome/vevor-7in1.yaml` and is deliberately kept short: it
carries one-line comments and pointers, this document carries the reasoning and the measurements
behind them. Every value below was measured on this board, not copied from an example.

## 1. Wiring

| ESP32-C3 | CC1101 module |
|---|---|
| 3V3 | VCC (the module is a 3.3 V part — 3.6 V absolute maximum) |
| GND | GND (common ground with the ESP32) |
| GPIO6 | MOSI |
| GPIO4 | SCLK |
| GPIO5 | MISO |
| GPIO7 | CSN — plus a **10 kΩ pull-up to 3V3, soldered at the pin** |
| GPIO3 | GDO0 (single data wire); GDO2 not connected |

Decoupling actually fitted: **10 µF / 25 V between GND and the module's VCC**, soldered on the pins.
Still recommended and **not** fitted: a **100 nF** ceramic as close as possible to the module's VCC.
An earlier note mentions a transistor to power-cycle the module: **no transistor is fitted**.

## 2. Radio parameters

868.35 MHz, 2-FSK, 11 111 baud, 70 kHz deviation, 100 kHz filter bandwidth.

These are the values of the reference build that decodes this station on this board (frequency read
back from its driver at boot: 868 349 824 Hz). A compiled test at 868.30 MHz produced **zero frames**
while the write check confirmed FREQ2/1/0 were correctly applied — so the station is not at 868.30.
Deviation and bandwidth are not suspects either: the reference decodes with exactly these values.

## 3. Framework

`esp-idf`. The reference build uses it, and ESPHome has made it the default for ESP32 since 2026.1.
An earlier attempt to stay on `arduino` was only due to a Python environment problem
(`ensurepip` missing on Debian's Python), solved by building from the standalone CPython in `.venv`.

## 4. One SPI device per bus — a hard rule

The CC1101 must be the **only** device on its SPI bus. Measured on 01/10: our own register-reading
diagnostic component (`cs_pin` on a free GPIO10, nothing wired to it) made the chip mute — 0 RMT
captures and 0 frames on windows where the reference firmware decoded 6 frames/60 s; the same YAML
without that component decoded 5 frames/60 s, then 60 frames in 10 minutes. The symptom says nothing
about the chip: the bus is the problem.

Consequence for the current file: `allow_other_uses` is gone everywhere, and the pulse-receiving
component `vevor_7in1` has **no SPI access at all**. To instrument the radio, read the counters it
publishes and use the dump button — never a second SPI device.

## 5. The local `cc1101` driver copy

`external_components` loads a local copy of ESPHome's `cc1101` component. What it adds:

* **identity re-reads** — up to 60 non-blocking attempts, one every 250 ms (~15 s), from `loop()`
  instead of one attempt in `setup()`. Blocking re-reads in `setup()` were measured to provoke
  `*** CRASH DETECTED ON PREVIOUS BOOT *** Reason: Task wdt`, after which the ESP32 silently keeps
  running the **previous** image;
* **verified writes** — each configuration register is read back and rewritten until it takes
  (4 attempts). Registers whose read-back *cannot* match are written once and left alone:
  `TEST0/1/2`, and the synthesiser calibration registers `FSCAL3/2/1/0` (0x23-0x26), which the
  **chip itself** rewrites during its VCO calibration. Missing that distinction produced 21 of the
  30 write alarms of one day — a false positive that also rewrote FSCAL2 four times per configure;
* **VCO calibration diagnostics** — logs `FSCAL1` (0x3F means "not locked"; TI errata SWRZ020E says
  the PLL lock detector itself is not fully reliable) together with `MARCSTATE`;
* **SPI at 1 MHz**. Measured: at **200 kHz** the same driver makes the demodulator output a continuum
  of noise (437-510 pulses per capture, durations spread from 45 to 520 µs, zero frames); at 1 MHz it
  decodes every burst (166-182 pulses, a clean 2:1 rhythm).

**The `loop()` method is interrupt-driven.** It calls `disable_loop()` on entry, and only the GDO0
edge interrupt (`gpio_intr` → `enable_loop_soon_any_context`) wakes it again. A branch that returned
from `setup()` before attaching that interrupt therefore left the board configured, with a healthy
radio flag, writes verified — and permanently deaf, its FIFO filling with nobody reading it. That was
a real defect of this copy (fixed 03/10, and `reset()` now re-attaches the interrupt too).

## 6. The chip's state across an ESP32 restart

The CC1101 is a separate chip: it stays powered and **keeps its registers** while the ESP32 restarts.
During that restart its bus lines (CSN, SCLK, MOSI) are floating, and a glitch on CSN is read by the
chip as the beginning of an SPI transaction, which can corrupt its registers. Two mitigations, one
hardware and one firmware, address the same window:

* the **10 kΩ pull-up on CSN** keeps the chip deselected while nobody drives the line. On ESP32-C3
  the GPIOs are high-impedance at reset (Espressif datasheet Table 2-1: input enable, no pull-up), so
  the YAML's `mode: {output: true, pullup: true}` only takes effect after `setup()` — it is kept for
  completeness, it is not what protects the boot window;
* **`on_shutdown` (priority 600) and `ota: on_begin` send `cc1101.set_idle`**, so the chip is parked
  in a known state before any restart. Both blocks come from the reference build, where they "ensure a
  correct start after an OTA"; they had been disabled here for a test and were restored on 03/10.

## 7. The asynchronous reception path

There is deliberately **no `gdo0_pin` in the `cc1101` block**: declaring it makes the component
schedule a deferred `pin_mode(FLAG_INPUT)` that runs after `remote_receiver` has configured its RMT
channel, and the RMT then captures nothing (probe seeing the pin toggle, `captures=0`).

There is deliberately **no `packet_mode`** either: the component then leaves the chip in asynchronous
serial mode (`PKT_FORMAT = 3`) and puts the demodulated signal on GDO0. That path is the one that
works on this build; the packet mode has never produced a single coherent frame here.

`remote_receiver` settings, taken from the reference build's boot log and verified on captures:

* `filter: 45us` — about half a bit period. Filtering too little is worse than nothing: at `10us` the
  26-50 µs glitches each add a spurious edge, shifting every following bit, and no frame ever decodes
  while captures look full;
* `idle: 1100us` — one burst becomes one capture (~170 pulses);
* `receive_symbols: 512` — a software buffer, independent of the C3's 96-symbol hardware block;
* `tolerance: 25%`.

## 8. The watchdog

The station transmits a burst every 20 s, day and night (confirmed by the owner). A silence of several
minutes therefore always means the receiver is at fault, which allows the watchdog to act
unconditionally.

**The policy lives in the component** (`vevor_7in1.cpp`, `surveiller_radio_()`), with its two settings
exposed as Home Assistant `number` entities declared by the component itself. The YAML declares those
entities and nothing else — see §10.

* the criterion is **published frames**, never captures: in the deaf state a few parasitic captures
  still arrive (3 to 5 per window) and would keep a capture-based counter alive. Measured on a 9-minute
  window: 7 "radio EN ECHEC" lines and **zero reboots** with a capture-based criterion;
* **re-arms are spaced**, never one per 20 s slot. Measured on 05/10/2026: the old single-slot trigger
  reset the chip every ~20 s, because the station's period and the slot period are identical — one
  jittered emission was enough. And each re-arm is a lottery on a marginal SPI link: **2 register writes
  failed in a 4-minute run** (measured), and a lost write leaves the chip misconfigured (`registre 0x1D
  NON PRIS`, wanted 0xB1) — the watchdog then *maintains* the fault instead of curing it;
* defaults: a re-arm after **3 silent slots (60 s)**, then one every 3 slots, and a **reboot at 180 s**
  (the only remedy measured so far). Both are runtime-tunable entities:
  `Watchdog crénaux muets avant re-armement` and `Watchdog silence max avant redemarrage`;
* the reboot rate is bounded (past ten consecutive reboots, one slot in 45) and the counter is
  persisted, so a genuinely dead board cannot loop forever;
* the re-arm is **one single `cc1101.reset`**. Never a chain of `cc1101.set_*`: inside the component
  each setter does `if (initialized_) { enter_idle_(); …; enter_rx_(); }`, so a chain of seven means
  seven full reconfiguration cycles — the chip spends its time in IDLE and recalibrating instead of
  listening. Measured: a watchdog replaying that chain every 20 s made the board durably deaf, and it
  stayed invisible because it only fires when no frame is arriving.

## 9. Logging

Every periodic diagnostic is at **DEBUG**, and `logger: level` is **INFO** in production: a normal
build stays quiet, and a debugging session raises the level (or adds `logs: {v7in1: DEBUG}`) to see the
health line, the re-arm attempts and the raw frames.

One line stays at INFO: `V7IN1 OK {...}` on each frame. It is the product of this board, and the host
tools (`tools/capture_logs.py`, `tools/eval_frames.py`, the A/B harness) parse it.

## 10. What is kept in the YAML, and why

**Rule: the YAML carries no business logic — only logs and declarations.** The owner's words:
« Le YAML ne doit JAMAIS contenir de code métier, seulement des logs. » Anything that *decides* lives
in the component (`esphome/components/vevor_7in1/`), and every runtime setting is an entity the
component itself owns (`number/`, `button/`).

* `button: Dump pulses` / `button: Re-apply radio config` — now `platform: vevor_7in1`, declared by
  the component: the YAML only names them. The re-apply button and the watchdog literally share the
  same method (`reapply_radio()`), so they can no longer drift apart;
* `button: Restart board` — a reboot is the only remedy measured against a mute chip, and
  without this button it takes a reflash, i.e. a new state lottery. Declarative platform, no logic;
* `number: Watchdog crénaux muets avant re-armement`, `number: Watchdog silence max avant
  redemarrage` — the watchdog's two settings, exposed by the component (defaults: 3 slots, 180 s).
  The policy itself is `surveiller_radio_()`, see §8;
* `number: CC1101 frequency` — lets a frequency sweep be driven over the API in 25 s steps instead of
  a compile-and-flash per point. `restore_value: false` on purpose: a restored value used to override
  the compiled frequency at boot and made two frequency tests ambiguous;
* the diagnostic sensors (`Valid frames`, `Rejected frames`, `RMT captures`, `Duplicates ignored`,
  `Station ID`, `TX counter`, `Last raw frame`, `Last verdict`) and the 10 s publishing interval are
  **the last piece of logic still in the YAML** (flagged TODO in the file): moving it means handing
  the component the sensor ids.
