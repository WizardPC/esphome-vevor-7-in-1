# LOCAL copy of ESPHome's `cc1101` component — why it exists

This folder is a copy of `esphome/components/cc1101` from ESPHome **2026.9.1**, declared in
`external_components` in `esphome/vevor-7in1.yaml` so that it **takes precedence** over the native
component.

## Local changes

Every change is marked `LOCAL CHANGE` in the code: **11 markers in total** (9 in
`cc1101.cpp`, 2 declarations in `cc1101.h`). They cover:

1. **identity re-read with retries**: 4 attempts 50 ms apart in `configure()`, then up to **60
   non-blocking re-reads 250 ms apart (≈ 15 s)** handled from `loop()` — never a blocking loop in
   `setup()`, which would trip the watchdog — with **`CHIP_RDYn` logging**;
2. **VERIFIED register write**, retried until taken (4 attempts), plus a **check block** over the
   8 key registers (FREQ2/1/0, MDMCFG4/3/2, PKTCTRL0, IOCFG0);
3. **`delay(20)` settling** before entering RX, and a **VCO calibration check (`FSCAL1`)** after
   entering RX;
4. **`enter_calibrated_` retries the PLL lock** (`PLL_LOCK_RETRIES = 3`) instead of giving up on a
   timeout;
5. **SPI clock restored to `DATA_RATE_1MHZ`** (against the 200 kHz of an earlier iteration, where
   the chip only emitted a stream of noise).

## Why the identity re-read

The original version reads `PARTNUM` then `VERSION` **once**, then calls `mark_failed()`: on this
wiring, one boot in two came up with `Chip ID: 0xFFFF` (every SPI read at 0xFF) and the board stayed
mute **for the whole session**. Yet the CC1101 datasheet (SWRS061I) says:
- §10.1: `CHIP_RDYn` (bit s7 of the status byte) "stays high until power AND crystal are settled" —
  and meanwhile the SPI header returns `0xFF` on SO;
- §4.9 + Table 18: the power ramp must do 5 ms from 0 to 1.8 V, otherwise the chip's state is
  undefined until an `SRES` (and the full reset sequence is only required on first power-up:
  §19.1.2).

So `0xFFFF` does not mean "wrong wiring" but "chip not ready". RadioLib, the reference library, loops
10 re-reads 10 ms apart for that very reason (jgromes/RadioLib, `CC1101.cpp`). Here: 4 attempts 50 ms
apart, then up to 60 re-reads 250 ms apart (≈ 15 s) from `loop()` before giving up, with
**`CHIP_RDYn` logged** on every attempt, which tells the two causes apart:

| Log | Reading |
|---|---|
| `CHIP_RDYn HIGH = power or crystal not ready` | hardware side (power, crystal, POR) |
| `CHIP_RDYn low = chip ready, so the SPI link is at fault` | wiring side (MISO/MOSI/CS, ground) |

## Maintaining the fork

- **Base version**: ESPHome **2026.9.1** (`esphome version`). It is the only reference; the folder is
  not a versioned package, so on every ESPHome upgrade the upstream fixes are **not picked up
  automatically**.
- **Source of truth for the diff**: the installed native component, so the gap stays readable —
  e.g. `.venv/lib/python3.13/site-packages/esphome/components/cc1101/`.
- **Finding the changes**: `grep -rn "LOCAL CHANGE" esphome/components/cc1101/` lists the 11 markers
  (9 in `cc1101.cpp`, 2 in `cc1101.h`).
- **Replaying the changes** after an ESPHome upgrade: compare the local folder with the native
  component of the new version (`diff -ru <native> esphome/components/cc1101/`), then carry the
  marked blocks over. There is **no** patch file: the `LOCAL CHANGE` blocks stand in for a hunk set.
  If the gap becomes hard to follow, generate a `diff -u` (native → local) and drop it in this
  folder.
- **Minimal check after an update**: `configure()` must log the identity (`CC1101 found...`), the
  "write check" must conform over the 8 registers, and the SPI clock must stay `DATA_RATE_1MHZ`.
