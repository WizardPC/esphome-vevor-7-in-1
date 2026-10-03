# Why single bits go wrong — functional analysis of the 03/10 discovery

Scope: the production receiver (`ESP32-C3 + CC1101`, GPIO3/GDO0 into `remote_receiver`, decoder in
`esphome/includes/vevor_protocol.h`). Written after the owner challenged the first fix ("if 5 of 6
bursts carry the sync word, that cannot be chance — the problem comes from elsewhere"), and after a
literature check to make sure we were not shipping a placebo.

## 1. What was observed

Six "clean" bursts in one dump (162-167 pulses each, short-pulse median 90 µs, visually identical).
One decoded. Decoding the other five by hand, byte by byte, gave this:

| capture | payload found after the sync word | vs the valid frame |
|---|---|---|
| 21 | `aa 00 84 cb 16 02 90 50 01 01 00 02 22 01 ff 02 31 df 33 5c 34` | reference |
| 20 | `ea 00 84 cb 16 02 90 50 01 01 00 02 22 01 ff 02 31 df 33 5c 34` | byte 0 differs |
| 13 | `ab 00 84 cb 16 02 90 50 01 01 00 02 22 01 ff 02 31 …` | byte 0 differs |
| 16 | `ae 00 84 cb 16 02 90 50 01 01 00 02 22 01 ff 02 39 …` | byte 0 differs |
| 12 | `aa 00 84 cb 16 02 90 50 01 02 00 04 44 03 fe 04 63 …` | diverges at byte 9 |
| 17 | `aa 00 84 cb 16 02 90 50 01 01 00 04 44 07 fc 08 c7 …` | diverges at byte 11 |

Two facts matter here. **The frames are present** — same station ID (33995), same temperature
(15.6 °C), same humidity (80 %). And **the errors are localised**: one wrong bit in the header byte,
or a divergence point after which every value is doubled (`04 44` instead of `02 22`) — the signature
of a one-bit shift, already documented in `vevor_protocol.h`.

The owner's statistical argument is what settled it: a 16-bit sync word appears by chance in roughly
0.6 % of bursts. Seeing it in *every* burst, one every 20 s, is not chance. The syncs are real, so the
frames are real, so the failures are in reconstruction, not in reception.

## 2. Root cause: pulse-width jitter, and no bit-clock recovery

Measuring the demodulated pulse widths of those bursts:

* 1-bit pulses span **47 µs to 93 µs** — a 40 % spread around the nominal 90 µs bit;
* 2-bit pulses follow the same pattern (179-181 µs for 180 expected).

Every conversion of pulses to bits must decide "how many bit periods does this pulse hold?". With a
40 % spread, that decision is a coin flip on the pulses that land near a rounding boundary, and
**one wrong decision shifts every following bit** — which is exactly what the payloads above show.

Two aggravating factors, both structural:

1. **the asynchronous path has no bit clock.** `remote_receiver` measures pulse *lengths*; nothing
   recovers the transmitter's clock. The CC1101's own bit synchroniser is not in this path — the
   datasheet (and TI's answer on E2E, "in synchronous serial mode the MCU is responsible for sync and
   preamble") leaves preamble and synchronisation to the host. Our decoder therefore had to *assume*
   the bit period, trying four fixed candidates {87, 88, 89, 90 µs};
2. **the pulses are not the transmitter's.** They are what our own demodulator produces after its
   channel filter, its slicer and its AGC have had their say.

## 3. What the literature says (checked, not assumed)

* **rtl_433**, the reference implementation for this protocol, does not assume anything either: its
  decoder architecture is "demodulate to a pulse list, then search the preamble in the bit stream"
  (`bitbuffer_search`). From rtl_433 issue #3239: *"Finding a preamble is a common operation in
  decoders, look in other decoders for `bitbuffer_search`."* The same thread describes a real capture
  with a **warm-up pulse** whose payload appeared **shifted by 10 bits** — the same class of defect.
* On the cause of width distortion, a rtl_433 discussion is explicit: *"AGC action, filtering, uneven
  zero and one distribution, and sample rate may be giving the apparent pulse distortion"*, with
  samples quantised in 4 µs steps in that example. "Varying the sample rate slightly up and down may
  help find an optimum rate for that signal and best decode."
* rtl_433's own analysis guide (`docs/ANALYZE.md`) describes the same pipeline we are missing: analyse
  pulses → determine the coding → build the bit slicer → decode the protocol. Nothing in it suggests
  accepting a corrupted header bit.

Conclusion: **the industry-standard answer is to align on the preamble and reconstruct the bit clock
from the burst, not to tolerate errors afterwards.** Our firmware does neither — it rounds pulses
independently against a fixed period.

## 4. Verdict on the first fix

The 03/10 change (correct **one** bit of the constant header byte, only if checksum + counter +
plausibility gate all pass afterwards) is a **bounded safety net**, not the fix. It recovered 1 → 3
of 6 captures offline, which is worth keeping, but it treats the symptom: it repairs the frames where
the bit damage happens to land on a byte whose value is known in advance. It cannot repair a shift
that starts at byte 9 or 11, and it says nothing about the other four bursts.

It is kept, with a test that bounds it (one bit passes, two are refused), and it is documented as a
net — never as the answer.

## 5. The real levers

Ordered by expected value, all measurable:

1. **Recover the bit clock per burst (the proper fix).** The Vevor preamble is `AA AA AA` — an
   alternating pattern, i.e. a square wave at exactly the bit rate, sent before every frame. It is a
   free clock reference: measure it, lock a bit clock on the burst's edges, and sample the level at
   bit centres instead of rounding each pulse independently. This is the rtl_433 approach and it
   tolerates the jitter that defeats our current rounding. It also makes the fixed period grid and
   the header tolerance unnecessary.

   **Status: attempted, not achieved.** A first rough prototype (first-order phase loop, gain
   0.2-0.5, period from the median of the leading edge spacings) decoded **0 of 6** bursts on the same
   dump — worse than the fixed grid. That is not evidence against the approach (rtl_433 decodes this
   protocol this way); it is evidence that a phase loop cannot be improvised in a shell script: it
   needs the edges to be trusted in the right order, a defensible initial period, and host tests
   pinning the behaviour on synthetic bursts before going anywhere near the board. Treat it as the
   next real piece of work, not as a quick win.

2. **Reduce the jitter at the source (physical layer).** The 100 nF ceramic at the module's VCC is
   still not fitted; decoupling affects exactly the fast edges that become our pulse widths. A 40 %
   spread on 1-bit pulses is *not* something a decoder should have to absorb, and the console
   decodes this station out of the box with a hardware demodulator — which is the owner's argument
   for looking here first, and it is a good one.
3. **Question the demodulator's settings as a measured experiment**, one variable at a time: the
   filter bandwidth (100 kHz for 70 kHz deviation is at the Carson limit), the AGC target, and the
   RMT's `filter` threshold — the last one being the reason 45-50 µs glitches can still enter the
   bit stream.

## 6. How to tell a fix from a palliative, for this project

* A fix changes the **rate of decodable bursts**, measured on the same dump, offline, with the same
  script before and after. The number to publish is `decoded / bursts`, never "it works now".
* A palliative raises the rate only where the damage is *predictable* (a constant byte), and leaves
  the rest untouched. Its own counter-example must be stated: here, bursts 12 and 17.
* Every intermediate analysis script must use **the firmware's own arithmetic** (rounding rule
  included) before it accuses the firmware of anything — paid for twice on 03/10.
