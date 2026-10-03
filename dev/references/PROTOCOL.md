# RF protocol — Vevor 7-in-1 weather station, 868 MHz (ref. YT60309 / YT602xx family)

Reference implementation: the rtl_433 decoder `vevor_7in1.c` (merbanan/rtl_433,
`src/devices/vevor_7in1.c`). Actual manufacturer: Fujian Youtong Industries. Documented models:
YT60231 (868 MHz EU), YT60234 (915 MHz US). Same protocol and same checksum in both bands.

> **Status, 02/10/2026.** The **frame table** below was verified against our decoder
> (`esphome/components/vevor_7in1/vevor_protocol.h`): same "-1" offsets, same scales. The values in the "Radio
> layer" section, however (87 µs bit period ≈ 11 494 baud, ±37 kHz deviation, 915.031 MHz centre)
> are **rtl_433's measurements on a 915 MHz unit**. The receiver used here (868 MHz EU) is
> configured for **868.35 MHz / 70 kHz / 100 kHz / 11 111 baud**, the values of the reference build
> that decodes this station (`esphome/vevor-7in1.yaml`, substitutions). Do not mix the two sets.

## Radio layer

- Modulation: **2-FSK** (NRZ / PCM), not OOK.
- Rate: bit period **87 µs** → **~11 494 baud**.
- Deviation: **±37 kHz** (measured on the 915 MHz unit; the 868 MHz EU build that works here uses
  70 kHz).
- Burst: **~85 ms every 20.000 s** (every sensor in every frame).
- Measured centre 915.031 MHz for a nominal 915.000 → expect a **frequency offset** (the CC1101
  reports `freq_offset` on each packet: that is the alignment tool).
- Preamble then sync word: the pattern searched for is **`AA AA CA CA 54`**, followed by the
  payload — `references/vevor_7in1.c:68`, `esphome/components/vevor_7in1/vevor_protocol.h`.

## Frame

After the `AA AA CA CA 54` pattern, **21 bytes** `b[0..20]` are extracted:

| Byte | Field | Decoding |
|---|---|---|
| b[0] | fixed | `0xAA` |
| b[1] | type/channel | high nibble = type (0), low nibble = channel; reads `0x00` |
| b[2..3] | sensor ID | `(b[2]<<8) \| b[3]` (16 bits) |
| b[4] | battery | bit 7 = 1 → battery low (`0x9d` = low, `0x1d` = ok) |
| b[5..6] | temperature | `raw = (b[5]<<8)\|b[6]`; `T°C = (raw - 500) * 0.1` |
| b[7] | humidity | `%` directly |
| b[8..9] | wind speed | **−1 on each byte**, then `km/h = raw / 8.333` |
| b[10] | gust | `km/h = b[10] / 1.25` (no −1) |
| b[11..12] | direction | **−1 on each byte**, then `deg = ((b[11] & 0x0f) << 8) \| b[12]` |
| b[13..14] | rain | **−1 on each byte**, then `mm = raw * 0.233` |
| b[15] | UV | `(b[15] & 0x1f) - 1` |
| b[16..17] | illuminance | **−1 on each byte**; if bit 15 = 1 → `(val & 0x7fff) * 10`, otherwise `val` lux |
| b[18] | TX counter | incremented on every transmission |
| b[19] | checksum | `sum(b[0..18]) & 0xFF` |
| b[20] | TX counter + 1 | must equal `(b[18] + 1) & 0xFF` |

**Order of operations is mandatory**: the checksum is computed on the **raw** bytes; the −1
decrements apply only **after** validation.

**No pressure field.** The frame carries no barometric pressure: the station's 6-icon weather
forecast is computed by the display console from the console's own barometer (owner's manual
YT60309, p. 20). The console's icon is therefore not receivable — see §1.4 of the README and the
header of `esphome/components/vevor_7in1/vevor_forecast.h`.

## Self-evaluation criteria (ground truth, without an SDR)

A decoding counts as valid when:

1. `sum(b[0..18]) & 0xFF == b[19]` (checksum);
2. `b[20] == (b[18] + 1) & 0xFF` (consistent counter);
3. `b[0] == 0xAA` and `b[1] == 0x00`;
4. cadence between frames of the same ID ≈ 20 s ± 1 s;
5. between two consecutive frames of the same ID: TX counter +1, rain **increasing or equal**,
   temperature/humidity varying continuously (no jump of several tens of °C);
6. physical plausibility: `-40 ≤ T ≤ +60 °C`, `0 ≤ RH ≤ 100 %`, `0 ≤ wind ≤ 180 km/h`,
   `0 ≤ direction ≤ 359°`, `0 ≤ UV ≤ 16`, lux ≥ 0;
7. cross-check against an independent source: Open-Meteo (free API, the house's lat/lon) for
   outdoor temperature/humidity, to within ±5 °C / ±20 %.

## Known traps

- A false positive is possible when the LUX value is at maximum → only accept frames whose checksum
  **and** counter are both good.
- The CC1101 in packet mode can sync off-position (`sync_mode: 16/16`, sync `CA 54`): always filter
  by checksum rather than by length.
- If no packet arrives: scan the frequency (867.8 → 868.6 MHz in 50 kHz steps) and watch RSSI +
  `freq_offset`; the supplied helical antenna severely limits range (aim for < 15 m while bringing it
  up, then use a λ/4 antenna).
- **A valid checksum does not guarantee a correct rain value.** The station may read its 16-bit
  counter while it carries over and publish the wrapped low byte with a stale high byte: exactly
  **256 ticks (59.6 mm) too few**, with a valid checksum, roughly once every 59.6 mm of rain.
- **Rain can only go up**, or reset to exactly zero after a battery change. A non-zero decrease is
  corruption, however often it repeats; a zero is only accepted after **3 consecutive frames**.
- The rain counter **saturates at 15 209.8 mm = 65 278 ticks (0xFEFE)** — consistent with the
  "+1 per byte" encoding: `0xFF` is unreachable, hence the maximum value `0xFE 0xFE`.
- **Wind plausibility**: a frame with `wind > 0` and `gust == 0` is rejected (the gust cannot be zero
  if the average is not).
- **Illuminance/UV filter**: reject `lux == 0` with a non-zero UV, and lux values incompatible with
  the UV index of the same frame.
- **Battery**: the flag (`0x9d` low / `0x1d` normal) needs **confirmation over several frames** before
  being published (it is ambiguous; rtl_433 suspects it is also the pairing button).
- **The station ID changes at every power-up** (battery change). Pin the ID, and expect to find it
  again after a battery change. Corollary: **another station in the neighbourhood on the same
  protocol would overwrite your values** if the ID is not pinned. This firmware publishes the ID for
  exactly that purpose.
- Station counting is **per block**: each decoder keeps its own rain total.
