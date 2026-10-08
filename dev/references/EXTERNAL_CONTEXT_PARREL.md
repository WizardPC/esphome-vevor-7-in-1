# External context: parrel/esphome-vevor-7in1 — CONTEXT ONLY

The owner of this repository pointed at <https://github.com/parrel/esphome-vevor-7in1> while chasing a
reception collapse. It is a reference for UNDERSTANDING, never a code source: the standing rule of
this project is that not one line of it is taken here. This file records what it taught us, and what
it does not settle.

## What it is

A single external component, `vevor_decoder` (~18 KB: `__init__.py`, `vevor_decoder.{h,cpp}`), which
decodes the same 868/915 MHz FSK telegrams and publishes them as native ESPHome sensors. It relies on
ESPHome's `remote_receiver` and on `cc1101`, exactly like this project. Its options are the station
identity (`sensor_id`, its equivalent of our station pinning), a rain hold, and an illuminance filter.

## What it confirms (independently measured, and useful)

* **One telegram burst is ~85 ms and carries the frame TWICE.** Its README states it plainly ("Room
  for the whole ~85 ms burst, which carries the frame twice"), and warns that the default 192 RMT
  symbols "cuts it off after the first copy". Our own notes had measured the same object as a
  "77 ms burst with no internal gap above 2 ms". Two measurements, one object: what we have been
  calling the interferer is a telegram-shaped burst — the station's own retransmission, or a
  neighbour's station — not environmental noise.
* **Its acceptance gate differs from ours** (temperature −45..65 °C, humidity 1..100, gust ≤ 220,
  and it rejects a gust of 0 with a wind speed above 5). On 590 healthy captures the two decoders
  decode 291 and 303 frames: comparable, neither blocks the other.
* **Its bit-period model is a fixed 90 µs plus eight skew candidates**, where ours measures the period
  on the capture and only then falls back to a fixed grid. The difference is real but blocks nothing:
  on the six reference captures ours decodes the frame anyway through the fallback.

## What it does NOT settle

Its documentation announces `filter: 65us` / `idle: 2000us`, but the witness build compiled here uses
`filter: 45us` / `idle: 1100us` — ours. Our own measured note stands: idle 2000 µs lets a whole burst
in as one capture, which overflows the C3's RMT buffer and kills the receiver. **Do not copy its
receiver settings.**

## The rule, restated

Nothing here is a base for our code. It is a second opinion: read for facts, cited in
`dev/docs/firmware-design-notes.md`, and left where it is.
