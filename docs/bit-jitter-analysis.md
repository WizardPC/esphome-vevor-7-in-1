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

**Important correction (owner's input, 03/10):** the reference project measured this station at
**88.3 µs per bit** (11 325 baud), not 90 µs. So the spread is not only noise: our 1-bit pulses
measure **+2 to +5 % long** against a real 88.3 µs bit — a *systematic* bias on top of the outliers.
The nominal period in this project (`bit_period: 90us`, inherited from rtl_433) was wrong by ~2 %,
and the fine sweep below landing on 86.0-88.5 µs is consistent with 88.3 µs plus that stretch.
The fixed period grid also stops *just short* of the true value, which is why pulses near a rounding
boundary fall on the wrong side.

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

## 2bis. Hypotheses tested and refuted (03/10, offline, same six bursts)

All tested on the same dump, with the firmware's own rounding rule, so that no arithmetic artefact
can accuse the firmware:

| hypothesis | test | result |
|---|---|---|
| wrong period / grid too coarse | 5 grids, including 85.0-91.0 µs in 0.1 µs steps, both polarities | **1/6, identical for every grid** — refuted |
| the owner's 88.3 µs is the missing key | the same sweep brackets 88.3 µs | no gain — refuted (our decoder is insensitive to it) |
| wrong polarity | both polarities tried at every period | refuted |
| one bit lost / added | delete one bit at **every** position, re-validate | no recovery — refuted |
| one wrong bit in the header byte | tolerate exactly one bit, checksum + counter + gate must pass | **1/6 → 3/6** — real, but a net, not the fix |
| bit clock per burst (the documented fix) | two prototypes, the second primed with 88.3 µs | **0/6 twice** — the prototypes are at fault, not the approach; a phase loop needs a real implementation and tests |

What *is* consistent with all of it: the total number of bits is preserved, but a **bit boundary has
moved between two pulses**. That reproduces both observed signatures — a single wrong bit in the
constant header, and a doubling of every field after a divergence point — and it is precisely what a
per-edge clock removes and what independent per-pulse rounding cannot.

Acceptance criterion for the real implementation, so that nobody can fool themselves: a recovered
frame must pass **checksum + counter + plausibility gate** on bursts where the direct decode fails,
and the implementation must first reproduce the frames that *do* decode today. Any prototype that
cannot reproduce the known-good capture is broken by definition — both of mine were.

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

2. **Reduce the jitter at the source (physical layer).** A **10 µF bulk is already fitted** at the
   module's VCC/GND (03/10). TI's reference application also calls for a **100 nF** at the pin — a
   different job, not a bigger version of the same one: the 10 µF supplies the slow current demand
   but its ESR/ESL make its impedance rise above roughly 1 MHz, so it decouples nothing at the edge
   timescales; the small ceramic acts on the fast current spikes, and works because it is soldered
   as short as possible across the module's pins.

   **Its absence has never been measured as a cause on this board.** It was carried from the project
   notes ("100 nF non monté" — true, but that is not a measurement). Do not present it as the lever
   it was assumed to be. What the chip itself reports — `CHIP_RDYn` high, "supply or crystal not
   ready" — points at supply/quartz **startup**, where the actionable lever is a supply cycle, not
   decoupling.
3. **Question the demodulator's settings as a measured experiment**, one variable at a time: the
   filter bandwidth (100 kHz for 70 kHz deviation is at the Carson limit), the AGC target, and the
   RMT's `filter` threshold — the last one being the reason 45-50 µs glitches can still enter the
   bit stream.

## 5bis. Clock track — what worked, what did not (03/10 evening)

**What worked, and it is the part that matters for a shipped product:**

* **A self-adapting period estimator.** From the burst alone — no per-station constant — the bit rate
  comes out at **88.5-88.9 µs on all six bursts**, i.e. the 88.3 µs measured by the reference project.
  Method: take the durations in the 45-115 µs window, then consolidate with the median of
  `d / round(d / T)` over the pulses above 0.55·T, four times. This removes the "we hard-coded 90 µs"
  class of bug entirely: any board is measured, not assumed.
* **The failure mechanism, proven.** Inserting **one** bit repairs bursts 0 and 3 (positions 151 and
  187 of the bit stream); earlier, deleting one bit repaired nothing. So a pulse that should have
  yielded two bits yielded one — a *missing* bit, not an added one. That is the boundary case, and it
  is what the per-pulse rounding gets wrong.
* **A combination that reaches the acceptance criterion: 5 of 6 bursts decode**, all five carrying the
  same payload. Contributions: 1 direct, 2 via the one-bit header net, 2 via inserting one bit in the
  payload. Every path is gated by header + checksum + counter + plausibility gate.
* **Cost on the target:** the insertion repair is ~168 positions × 21 bytes worst case ≈ 67 k
  operations, under 1 ms at 160 MHz, and only runs when a sync was found but the frame failed —
  ~125 times per 12 minutes in practice. Negligible.

**What did not work:**

* **A true phase-locked clock: three implementations, none better than plain rounding.** The first two
  decoded 0/6 and did not even reproduce the burst that decodes today, which by our own criterion
  means they were broken, not that the approach is wrong.
* **Cumulative position rounding is worse, and this one is a keeper of a result.** It matches plain
  rounding at the correct period (3/6 with the net), but collapses to **0/6 under a period error of
  just +1 %**, while plain rounding holds 3/6 up to ±2 % and only fails at ±4 %. Cumulative rounding
  *accumulates* the period error across 350 bits; per-pulse rounding does not. For a product that must
  work on a stranger's board, **per-pulse rounding with a measured period is the robust choice**, and
  a phase loop only becomes worth it with proper phase tracking — not with a fixed phase search.
* **The parasite threshold** (discarding pulses below α·T and merging their neighbours), tested from
  0.5·T to 0.8·T: no gain at all, and it degrades the net above 0.7·T. The 45-50 µs glitches are a
  plausible story, not the mechanism.

**Honest status:** the bit-level clock recovery is **not achieved**. What is achieved is a self-adapting
period plus bounded, checksum-validated repairs, reaching 5/6. By the acceptance rule above ("if the
net is still carrying the result, the recovery is not finished"), the recovery is unfinished and the
repairs are nets — better ones, but nets. Burst 2 is still unexplained: it needs at least two
corrections.

## 5ter. Step 1 implemented (03/10, evening) — measured result

The self-adapting period and the bounded repairs are now in the firmware decoder
(`esphome/includes/vevor_protocol.h`), with host tests. What is measured, not claimed:

| what | result |
|---|---|
| period estimator, no station constant | 87.8 / 88.7 / 86.9 / 90.2 µs on synthetic bursts emitted at 88 / 89 / 87 / 90 µs |
| **real captures replayed in the C++ decoder** | **5 of 6 decoded** — criterion met in the code that ships (`tests/data/captures_reelles.txt`, replayed by `test_captures_reelles`) |
| the five decoded captures | all carry the station's measurement (identical 11-byte prefix); periods measured at 88.2-89.1 µs |
| shortened two-bit pulse (the proven mechanism) | repaired to the **identical** frame |
| 200 random payloads with a valid sync + header | **0 published** — the repairs do not fabricate frames |
| firmware test suite | **397 checks, 0 failures** |

Two structural corrections were needed to make the insertion repair work at all, both found by
measurement rather than reasoning: the frame no longer fits in the search window once a bit is
missing (`find_frame_candidate` now accepts a payload one bit short), and the bits between two
boundaries belong to the **previous** segment, not the next one — my first attempt was shifted by a
whole segment, which is why it decoded nothing.

The continuity gate on repaired frames (same station, temperature within 1 °C, humidity within 5 %)
is kept in the component. Measured fabrication rate is 0/200, so it is a **precaution at zero cost**,
not a measured necessity — and it is documented as such.

Still open, unchanged: the sixth capture (needs at least two corrections), and the strict bit-clock
recovery of step 2, which remains research.

## 6. Implementation plan (revised with the 03/10 evening measurements)

**Step 1 — ship what is proven (self-adapting, no station constant):**
* `estimer_periode(timings, count)` — the estimator validated above (windowed median, then
  `d / round(d/T)` consolidation). Replaces the fixed `PERIOD_CANDIDATES` grid as the primary path.
* decode with **per-pulse rounding** on the measured period (proven robust to a ±2 % period error),
  keeping the fixed grid as a last-resort fallback.
* **bounded repairs, all gated by header + checksum + counter + plausibility gate:** the one-bit
  header net (existing), then a **one-bit insertion** search in the payload (~67 k operations worst
  case, under 1 ms). Measured: 5/6 bursts on the dump, all identical payloads.
* add a **counter gate**: the decoded `tx_counter` must be consistent with the previous frame, which
  closes the false-positive door on the repairs and is cheap.

**Step 2 — the actual bit-clock recovery (still open):** the phase-tracked clock described below,
which exists to make step 1's repairs unnecessary. Per the measurements, it needs *true* phase
tracking (a per-edge loop), not a fixed phase search, and it must be shown to beat per-pulse rounding
under a deliberately wrong period before it is allowed on the board. Until then, step 1 is the
product; step 2 is research.

**Step 3 — host tests, before anything touches the board:**
* the six real captures as regression vectors — five must decode, the sixth stays as the counter-example;
* synthetic burst with a known frame and pulse widths jittered ±10 % / ±25 % → decoded;
* synthetic burst with a delayed/advanced period (±1 %, ±2 %) → shows step 1 robust, and would catch a
  regression that reintroduces cumulative rounding;
* synthetic burst with one bit missing inside the payload → the insertion repair must recover it;
* pure noise, and a burst with no preamble → nothing published.

## 7. How to tell a fix from a palliative, for this project

* A fix changes the **rate of decodable bursts**, measured on the same dump, offline, with the same
  script before and after. The number to publish is `decoded / bursts`, never "it works now".
* A palliative raises the rate only where the damage is *predictable* (a constant byte), and leaves
  the rest untouched. Its own counter-example must be stated: here, bursts 12 and 17.
* Every intermediate analysis script must use **the firmware's own arithmetic** (rounding rule
  included) before it accuses the firmware of anything — paid for twice on 03/10.
