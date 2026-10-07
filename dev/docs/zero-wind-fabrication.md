# Zero-wind fabrication: the insertion repair published 46,0 km/h / 102,4 km/h

Measured 04/10/2026 on the production board (Home Assistant history, entity
`sensor.jardin_vevor_7_in_1_weather_station_last_raw_frame`, which carries the 21 raw bytes of every
published frame). This document records a defect of OUR decoder — not of the station, not of the RF
link — and what was done about it.

## 1. Symptom

Between 15:36 and 22:07 (Paris) the wind entities carried **46,0 km/h** and **102,4 km/h** gusts
while the anemometer was at rest (0,0 km/h in the frames just before and just after), 141 frames in
all, in runs of consecutive frames up to 41 minutes. The frame responsible:

```
aa 00 84 cb 16 02 8f 58 02 80 80 02 0f 01 ff 01 01 01 9c aa 9d      <- published
aa 00 84 cb 16 02 8f 58 01 01 00 02 0f 01 ff 01 01 01 4e 5c 4f      <- the real emission, 20 s earlier
```

Only the three wind/gust bytes differ (b[8..10]), plus the counter (b[18]) and the checksum (b[19])
which follow their normal course (+39 per 20 s, the station's internal counter). Temperature,
humidity, direction, rain, UV and lux are identical to the neighbouring frames: this is not a global
bit shift (the kind the plausibility gate refuses since 01/10), not a scale or unit error.

## 2. Why every guard stays green

The checksum is a plain byte sum, and

```
0x01 + 0x01 + 0x00 = 2        0x02 + 0x80 + 0x80 = 0x102 = 2 (mod 256)
```

so the faulty triple keeps the byte sum **exactly**. Checksum, TX counter, plausibility gate,
continuity guard and duplicate filter all pass: **no stateless check can distinguish it**. The
anomaly appears precisely when the wind and the gust are both zero — the "special case at zero wind"
the owner suspected — because `01 01 00` is the only window whose corruption by one bit stays
sum-neutral.

## 3. Reproducing it off-hardware

`dev/tests/test_decoder.cpp`, section 15 (`test_reparation_vent_nul`), and the throwaway probe used
during the diagnosis: take a real zero-wind frame, build the pulse sequence, shorten by one bit a
pulse of two bits or more (the measured mechanism: a pulse whose duration was rounded DOWN), then
run the decoder.

Before the fix, 4 of the 36 shortened pulses of the reference frame produced a published frame that
was **not** the real one, among them:

```
impulsion 71 shortened (14 bits -> 1) -> 02 80 80   = wind 46,0 km/h, gust 102,4 km/h
```

i.e. exactly the production symptom, reproduced off-board in a few milliseconds.

## 4. Cause

`repair_by_insertion()` (the insertion repair, added to recover bursts that lost a bit) searched
an inserted bit of **any value at any position**, and accepted the **first** candidate passing
header + checksum + counter + plausibility. With a plain-sum checksum, many positions satisfy it: on
the reference frame, the median number of accepted positions is 4 to 7, and 15 for the loss
positions that produce `02 80 80`. The true position was scanned at q = 80…93, the wrong one at
q = 70 — it comes first, so it wins.

Root of it: the repair's search space was not constrained by physics. A lost bit does not appear at
an arbitrary place with an arbitrary value: it comes from a pulse whose duration was rounded down,
so the recovered bit **extends the run of the preceding bit** — it carries the same level.

## 5. Fix

`esphome/components/vevor_7in1/vevor_protocol.h`, `repair_by_insertion()`: the inserted bit now
takes the level of the bit that precedes the insertion point (`bits[payload_bit + q - 1]`, i.e. the
sync word's last bit for q = 0). One line of physics instead of a value blacklist.

Measured effect (throwaway probe, three real frames, every pulse of two bits or more shortened):

| Frame | before: true / none / **false** | after: true / none / **false** |
|---|---|---|
| zero wind (test frame, ID 33995) | 28 / 4 / **4** | 31 / 4 / **1** |
| zero wind (19:25, Paris) | 25 / 4 / **4** | 29 / 4 / **0** |
| wind 3,6 km/h (afternoon) | 35 / 4 / **2** | 37 / 4 / **0** |

The repair recovers *more* true frames and fabricates none of the `46,0 / 102,4` kind. The one
remaining false frame (reference frame, pulse 78) is stopped by the rain continuity guard
(`rain_plausible`: rain 15 270 mm instead of 59,2 mm) and never reaches Home Assistant: the test of
section 15 asserts precisely that — a published frame is either the true frame, or refused by the
rain guard.

## 6. What remains open

- The repair can still accept a wrong position when the corrupted window is sum-neutral for a
  *different* pattern than `01 01 00`. The constraint removes the measured defect; it does not make
  the checksum discriminating. The honest bound is the test of section 15: nothing false is
  published on the two zero-wind frames, and everything false elsewhere is caught by the rain guard
  — that is a measurement on three frames, not a proof for all payloads.
- The upstream project (rtl_433 `vevor_7in1.c`) has no repair and no plausibility gate at all:
  users report "nonsense packets" (issue #3428, and #3020's comments), where the values are doubled
  (humidity 188 %, direction 3838°) — our gate refuses those. Our defect is the opposite: a
  sum-neutral corruption that no stateless guard can see.
- To settle "station or receiver" on the RF side, the decisive measurement is the raw pulse dump of
  an anomalous burst (button "Dump pulses", `idle: 1100 µs`, then offline decoding). Not done: the
  board rejects the API key in `esphome/secrets.yaml` (it runs a build flashed with the owner's own
  secrets), so neither the board's logs nor its API are reachable from here.
