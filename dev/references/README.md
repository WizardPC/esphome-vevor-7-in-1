# Reference material

| File | What it is | Licence |
|---|---|---|
| [`PROTOCOL.md`](PROTOCOL.md) | the 868 MHz frame layout this project decodes: fields, scales, plausibility rules, and what the station does *not* transmit | this project — GPL-3.0-or-later |
| [`vevor_7in1.c`](vevor_7in1.c) | the rtl_433 decoder for the same station (`merbanan/rtl_433`, `src/devices/vevor_7in1.c`), kept verbatim: the reference the port started from | GPL-2.0-or-later — Copyright (C) 2024 Bruno OCTAU (ProfBoc75) |

The firmware's decoder (`esphome/components/vevor_7in1/vevor_protocol.h`) is a port of the second
file. It adds what upstream does not have: a sync-word filter, a plausibility gate, a repair for
bursts that lost a bit (`repair_by_insertion()`), and the monotone rain guard — see
[`../docs/bit-jitter-analysis.md`](../docs/bit-jitter-analysis.md) and
[`../docs/zero-wind-fabrication.md`](../docs/zero-wind-fabrication.md) for the measurements behind
each of them.
