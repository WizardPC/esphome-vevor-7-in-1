# External context — `WizardPC/esphome-vevor-7in1` project (analysis, NOT a code base)

Project analysed on 30/09/2026: <https://github.com/WizardPC/esphome-vevor-7in1> (MIT licence).
Source, like ours: `rtl_433/src/devices/vevor_7in1.c`.

> **User's instruction: do NOT use it as a code base.** Our implementation
> stays independent (that is what keeps its value for cross-checking between our C++ and our
> Python decoder). This document only reports **measured parameters** and **protocol
> pitfalls**, to be treated as hypotheses to test, with supporting evidence.

> **Status as of 02/10/2026** (banner added, commit 9693dbe). This document is a **snapshot of 30/09**:
> the hypotheses in its section 1 have been **settled since**. Our radio settings have been **aligned on
> the reference's** (868.35 MHz / 70 kHz / 100 kHz / 11 111 baud) and the cause of the "0 frame" was
> not the radio but the **200 kHz SPI clock** set in our `cc1101` driver (fixed on
> 02/10; `state/PROGRESS.md`, entries of 02/10). The "Us (current)" column of the table in
> section 1 therefore describes the **state of 30/09**, not the current state. The `WizardPC` project remains **external**:
> never copied (only its behaviour served as a reference).


## 1. The most important point: our radio settings are probably wrong

Configuration published as working (868 MHz EU station):

| Parameter | Them (working) | Us (current) | Gap |
|---|---|---|---|
| `frequency` | **868.35 MHz** | 868.30 MHz | to re-centre |
| `modulation_type` | 2-FSK | 2-FSK | ✓ |
| `symbol_rate` | **11 111** (bit period 90 µs; **88.3 µs** announced by the user → 11 325 baud) | 11 494 (87 µs) | close, within the CC1101's tolerance |
| `fsk_deviation` | **70 kHz** | 37 kHz | **×1.9 — suspect #1** |
| `filter_bandwidth` | **100 kHz** | 200 kHz | **2× too wide — suspect #2** |

Consistency: `symbol_rate` 11 111 ↔ bit period 90 µs (ours: 87 µs per rtl_433, 11 494).

Why this would explain our 0 valid frames: with a real deviation of ~70 kHz announced as
37 kHz in the register, the CC1101's FSK demodulator works on a false hypothesis, and
our 200 kHz filter lets in twice as much noise — hence syncword locks on
noise (−105…−108 dBm, LQI=127) and **never** a coherent frame. To test as a priority:
`868.35 MHz / 70 kHz / 100 kHz / 11111 baud`, then a fine sweep of the frequency.

## 2. Different architecture (to know as a documented fallback, not to copy)

They **do not use packet mode**: ESPHome's `cc1101` component puts the chip in
**asynchronous 2-FSK**, the demodulated bits come out on GDO0/GDO2, are captured by
`remote_receiver` (their setting: `filter: 65us`, `idle: 2000us`), and an external component
converts the pulses back to bits (`bit_period` default **90 µs**).

Two protocol lessons valid regardless of the architecture:

- **The frames arrive cut.** Their decoder contains a reconstitution logic
  (`prev_fragment_` / `stitched_`, « Trame coupée reconstruite avec succès »). An incomplete
  capture therefore does not necessarily mean "no signal": a fragment may be missing.
- They handle a **skew of the bit rate** (`timings_to_bits_(raw, skew_us)`): the
  receiver may have a slightly shifted clock and several shifts must be tried.

Our build already has GDO0 on GPIO3, so switching to this asynchronous path is possible without
rewiring — it is a credible fallback if packet mode stays mute after correcting the deviation.

## 3. Documented protocol pitfalls (to integrate into our self-evaluation)

- **A valid checksum does not guarantee a correct rain value.** The station reads its
  16-bit counter while it carries over and may publish the low byte wrapped with a stale high
  byte: exactly **256 ticks (59.6 mm) less**, valid checksum, about once
  every 59.6 mm of rain. → A checksum OK is not enough: a rain consistency check is needed
  (suspicious jump to be confirmed on the next frame at ±2 ticks).
- **Rain can only go up**, or restart at zero right after a battery change.
  A non-zero decrease is a corruption — whatever its repetition. A zero is accepted
  only after **3 consecutive frames** (a corruption does not repeat, a reset does).
- The rain counter **saturates at 15 209.8 mm = 65 278 ticks (0xFEFE)**. Consistent with
  the "+1 per byte" encoding: `0xFF` is unreachable, hence the max value `0xFE 0xFE`.
- **Wind plausibility check**: a frame with `wind > 0` and `gust == 0` is rejected
  (a gust cannot be zero if the average wind is not).
- **Luminance/UV filter**: reject `lux == 0` with a non-zero UV, and lux incompatible
  with the UV index of the same frame.
- **Battery**: the indicator (`0x9d` low / `0x1d` normal) requires **confirmation over
  several frames** before being published (it is ambiguous, rtl_433 suspects it is also the
  pairing button).
- **The station ID changes at every power-up** (battery change). Consequence:
  pin the ID, and expect to have to find it again after a battery change. Important corollary for
  us: **another nearby station on the same protocol would overwrite our values** if we
  do not pin the ID. Our firmware already publishes the ID — we must use it.
- The station counting is **per block**: each decoder tracks its own rain total.

## 4. Hardware (reminder)

CC1101 module **868 MHz band** AND **868 MHz antenna** mandatory (the 433 MHz
modules/antennas, the majority in search results, do not work). Our module is
indeed an 868 MHz one and the user confirmed it.

## 5. What this concretely changes for us

1. **Before any new sweep**, reflash with `868.35 MHz / 70 kHz / 100 kHz / 11111 baud`
   (our current values are suspected wrong on the deviation and the bandwidth).
2. Then sweep **finely** around 868.35 MHz (±150 kHz in steps of 10–25 kHz): the
   real centre depends on the unit (rtl_433 measures offsets of a few tens of kHz).
3. Enrich `tools/eval_frames.py`: reject `wind > 0` with `gust == 0`; treat non-zero rain
   decreases as corruption; require 3 consecutive zeros before accepting a reset
   to zero; check the lux/UV consistency.
4. If packet mode stays mute after these corrections, try the asynchronous path
   (`remote_receiver` on GDO0/GPIO3 with `filter: 65us`, `idle: 2000us`) — it is a documented
   fallback, not a code reuse.

## 6. Bit rate: 88.3 µs and the "re-centring" function

The user reports that the real bit period is **88.3 µs** (→ 11 325 baud), not the
90 µs (11 111 baud) that this project sets by default. It is consistent: their README presents
`bit_period` as "to touch only if your receiver's timing is shifted and the
frames never validate". Our current value, 11 494 baud (87 µs), is −1.5 % from
88.3 µs: the three values bracket reality.

What their re-centring exactly does (`vevor_decoder.cpp`):

- `timings_to_bits_(raw, skew_us)` converts the pulses to bits with
  `num = (duration + period/2) / period`: rounding to the nearest multiple of the bit period;
- the shift is applied to each pulse: `duration = (val > 0) ? (val - skew) : (-val + skew)`;
- `try_decode_raw_()` tries **8 fixed shifts**: `SKEW_CANDIDATES[] = {0, 7, -7, 14, -14, 21, 25, 28}`
  and accepts the first that yields `0xAA` + a valid checksum — by testing all candidates instead of
  stopping at the first failure;
- the list is asymmetric (many more positive values): their receiver measures pulses
  systematically **longer** than ideal, and the skew realigns them.

**Consequence for us: it is not our problem, and it is structural.** In packet mode,
it is the **CC1101 itself** that does the bit synchronisation (locking on the syncword, with
`symbol_rate` as a nominal value only): it tolerates a few percent of error and
requires no per-receiver shift. Their mechanism exists because their architecture is
**asynchronous**: `remote_receiver` delivers raw pulse durations, and it is up to the decoder to
convert them to bits with a divider, hence the sensitivity to the exact period and to the measurement
bias. Looking for a fine setting at 88.3 µs will therefore not unblock anything as long as we stay in
packet mode — the real suspects remain the **deviation (37 → 70 kHz)** and the **band (200 → 100 kHz)**.

What does matter, however:

- if the frames still do not validate after correcting the deviation and the band,
  try `symbol_rate` ≈ **11 325** (88.3 µs) — it is a one-parameter test, cheap;
- if we ever switch to the asynchronous path, this skew search (8 candidates) and the
  88.3 µs value become **essential**: without them, the asynchronous path cannot
  correctly convert the pulses to bits.
