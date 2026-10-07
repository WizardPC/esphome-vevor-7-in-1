#pragma once
// Vevor 7-in-1 868/915 MHz frame decoder — port of vevor_7in1.c (rtl_433).
// Frame spec: references/PROTOCOL.md
//
// No hardware access here: this header describes the frame and validates it; the YAML lambda (on_packet) publishes the values.
// Do NOT rename this file to vevor_7in1.h — it would collide with the ESPHome component header of the same name and the `vevor` namespace would vanish.
//
// Log lines parsed by dev/tools/eval_frames.py: V7IN1 RAW <21 hex bytes> | V7IN1 OK {json} | V7IN1 REJ <reason>.

#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

namespace vevor {

static constexpr size_t FRAME_BYTES = 21;
// Sync pattern when decoding a raw (non-packet) stream: AA AA CA CA 54 then 21 payload bytes.
static constexpr uint8_t PREAMBLE[5] = {0xAA, 0xAA, 0xCA, 0xCA, 0x54};

struct Frame {
  uint16_t id = 0;
  uint8_t channel = 0;
  bool battery_low = false;
  float temp_c = 0.0f;
  uint8_t humidity = 0;
  float wind_kmh = 0.0f;
  float gust_kmh = 0.0f;
  uint16_t wind_dir_deg = 0;
  float rain_mm = 0.0f;
  int uv_index = 0;
  uint32_t lux = 0;
  uint8_t tx_counter = 0;
  bool valid = false;
};

inline std::string hex_bytes(const uint8_t *d, size_t n) {
  static const char *H = "0123456789abcdef";
  std::string s;
  s.reserve(n * 3);
  for (size_t i = 0; i < n; i++) {
    if (i) s += ' ';
    s += H[(d[i] >> 4) & 0x0F];
    s += H[d[i] & 0x0F];
  }
  return s;
}

// Checksum and counter are computed on the RAW bytes, before any -1.
inline bool checksum_ok(const uint8_t *b) {
  uint16_t sum = 0;
  for (int i = 0; i < 19; i++) sum += b[i];
  return (sum & 0xFF) == b[19];
}

inline bool counter_ok(const uint8_t *b) { return b[20] == (uint8_t)(b[18] + 1); }

// Continuity guard for REPAIRED frames: same station ID as the last accepted frame, temperature
// within 1 °C and humidity within 5 %. Measured on 200 random payloads: 0 published — a zero-cost
// precaution, not a measured necessity (dev/docs/bit-jitter-analysis.md §5ter).
inline bool continuite_ok(const Frame &f, const Frame &precedente) {
  if (f.id != precedente.id) {
    return false;
  }
  const float dt = f.temp_c > precedente.temp_c ? f.temp_c - precedente.temp_c
                                                : precedente.temp_c - f.temp_c;
  const int dh = f.humidity > precedente.humidity ? f.humidity - precedente.humidity
                                                  : precedente.humidity - f.humidity;
  return dt <= 1.0f && dh <= 5;
}

// Plausibility-gate limit (km/h) plus a margin: the encoder writes 1500 ticks for 180 km/h, and
// 1500 / 8.333f = 180.007 is strictly above 180.0f — without the margin a legitimate 180 km/h gust
// is refused. A bit-shifted frame (≈360 km/h) still far exceeds it.
static constexpr float WIND_LIMIT_KMH = 180.0f;
static constexpr float WIND_LIMIT_MARGE_KMH = 0.01f;

// Rain gate, per the reference decoder: rain only rises, or resets to zero after a battery change;
// any non-zero decrease is corruption even with a valid checksum. Zero is accepted on a single
// frame (the reference asks three). Never bound the decrease instead of this rule.
//
// The rise bound is physical: the gauge tips 0.233 mm, so +5 mm between two 20 s bursts = 21 tips =
// 15 mm/min — beyond any real rain. Do not tighten without a sustained real-rain measurement.
static constexpr float RAIN_MAX_HAUSSE_MM = 5.0f;

// `connue` = a previous accepted frame to compare against. Without a reference, accept: the frame
// already passed the header, checksum, counter and the rest of the plausibility gate.
inline bool rain_plausible(float nouvelle, float precedente, bool connue) {
  if (nouvelle < 0.0f) {
    return false;
  }
  if (!connue) {
    return true;
  }
  if (nouvelle < precedente - 0.01f) {
    // Decrease: legitimate only towards zero (rain-counter reset).
    return nouvelle <= 0.01f;
  }
  return (nouvelle - precedente) <= RAIN_MAX_HAUSSE_MM;
}

// `in`: 21 payload bytes (sync already done by the CC1101 in packet mode).
inline bool decode(const uint8_t *in, Frame &out, const char **reason) {
  // `valid` describes THIS frame, not the previous one: cleared on entry so a REFUSED frame can
  // never come out marked valid (it used to be set before the plausibility gate).
  out.valid = false;
  if (in[0] != 0xAA || in[1] != 0x00) {
    *reason = "header";
    return false;
  }
  if (!checksum_ok(in)) {
    *reason = "checksum";
    return false;
  }
  if (!counter_ok(in)) {
    *reason = "tx_counter";
    return false;
  }

  uint8_t b[FRAME_BYTES];
  for (size_t i = 0; i < FRAME_BYTES; i++) b[i] = in[i];
  // Multi-byte values are transmitted with a -1 offset on each byte.
  const int shift[] = {8, 9, 11, 12, 13, 14, 16, 17};
  for (int i : shift) b[i] = (uint8_t)(b[i] - 1);

  out.id = (uint16_t)((in[2] << 8) | in[3]);
  out.channel = in[1] & 0x0F;
  out.battery_low = (in[4] & 0x80) != 0;
  out.tx_counter = in[18];

  int temp_raw = (in[5] << 8) | in[6];
  out.temp_c = (temp_raw - 500) * 0.1f;
  out.humidity = in[7];

  int wind_raw = (b[8] << 8) | b[9];
  out.wind_kmh = wind_raw / 8.333f;
  out.gust_kmh = in[10] / 1.25f;
  out.wind_dir_deg = (uint16_t)(((b[11] & 0x0F) << 8) | b[12]);
  int rain_raw = (b[13] << 8) | b[14];
  out.rain_mm = rain_raw * 0.233f;
  out.uv_index = (in[15] & 0x1F) - 1;
  uint16_t lux_raw = (uint16_t)((b[16] << 8) | b[17]);
  out.lux = (lux_raw & 0x8000) ? (uint32_t)((lux_raw & 0x7FFF) * 10) : lux_raw;

  // Plausibility gate: a frame can pass header + checksum + counter and still be false. Measured
  // over 1 h: 2 of 181 published frames (1.6 %) carried a one-bit shift, which doubles the value
  // bytes — e.g. direction 779° and 835°, rain 178.2 mm instead of 59.2. Physically impossible.
  if (out.wind_dir_deg > 359) {
    *reason = "direction";
    return false;
  }
  if (out.humidity > 100) {
    *reason = "humidity";
    return false;
  }
  if (out.temp_c < -40.0f || out.temp_c > 60.0f) {
    *reason = "temperature";
    return false;
  }
  // Wide but finite upper bounds: a domestic anemometer does not exceed them, while a bit shift
  // doubles them. Compared at the limit plus the rounding margin (WIND_LIMIT_MARGE_KMH) so a
  // legitimate 180 km/h frame is not refused; see the WIND_LIMIT_KMH comment.
  if (out.wind_kmh > WIND_LIMIT_KMH + WIND_LIMIT_MARGE_KMH ||
      out.gust_kmh > WIND_LIMIT_KMH + WIND_LIMIT_MARGE_KMH) {
    *reason = "wind";
    return false;
  }
  if (out.uv_index < 0 || out.uv_index > 16) {
    *reason = "uv";
    return false;
  }

  // The frame passed the WHOLE gate: valid, and only now. Setting `valid` before the checks let a
  // REFUSED frame come out with `valid == true`.
  out.valid = true;
  return true;
}

inline std::string to_json(const Frame &f) {
  char buf[320];
  snprintf(buf, sizeof(buf),
           "{\"id\":%u,\"channel\":%u,\"battery_low\":%s,\"temp_c\":%.1f,\"humidity\":%u,"
           "\"wind_kmh\":%.1f,\"gust_kmh\":%.1f,\"wind_dir_deg\":%u,\"rain_mm\":%.1f,"
           "\"uv_index\":%d,\"lux\":%u,\"tx_counter\":%u}",
           (unsigned) f.id, (unsigned) f.channel, f.battery_low ? "true" : "false", f.temp_c,
           (unsigned) f.humidity, f.wind_kmh, f.gust_kmh, (unsigned) f.wind_dir_deg, f.rain_mm,
           f.uv_index, (unsigned) f.lux, (unsigned) f.tx_counter);
  return std::string(buf);
}

// ---------------------------------------------------------------------------------------
// Pulses → frame chain (asynchronous path: CC1101 async serial + remote_receiver)
// ---------------------------------------------------------------------------------------
// The CC1101 outputs the demodulated signal on GDO0; `remote_receiver` turns it into signed pulse
// durations (sign = level: positive = mark = 1, negative = space = 0). This block does the rest —
// durations → NRZ bits then sync-word search — with no hardware access (off-board testable).

// End of the sync word: the frame is preceded by AA AA AA then CA CA 54, and the 21 payload bytes
// start right after. Search THIS pattern (not the whole preamble): a capture may start mid-preamble.
static const uint8_t SYNC_WORD[2] = {0xCA, 0x54};
static constexpr size_t SYNC_BYTES = 2;

// A level held longer than this (in bit periods) is not data but a gap between bursts: skip it
// instead of dropping the capture — the useful frame may follow.
static constexpr int32_t MAX_RUN_BITS = 64;

// Capacity of the durations → bits conversion (an RMT capture holds ~200 bits).
static constexpr size_t MAX_BITS = 4096;

// Below this pulse count, no Vevor burst can fit.
static constexpr size_t MIN_TIMINGS = 40;

// Above this length the capture holds a WHOLE burst — measured here: 176-184 pulses (the C3 RMT
// sometimes splits it: 96+82, 94+70…). Only shorter captures are FRAGMENTS to stitch; stitching a
// longer one re-reads the previous burst (measured: 60 frames for 31 distinct measurements).
static constexpr size_t MAX_FRAGMENT_TIMINGS = 160;

// True ONLY for a capture too short to hold a WHOLE burst — the only case where stitching makes
// sense. A complete burst (176-184 pulses) is never stored as a fragment, so never stitched in
// front of the next (the component calls this; the test exercises it at the bounds).
inline bool is_fragment(size_t count) {
  return count >= MIN_TIMINGS && count <= MAX_FRAGMENT_TIMINGS;
}

// Bit periods tried at each capture, in order. The values bracket what is known: 90 µs (published,
// and the witness build's period), 88.3 µs (user measurement → 11 325 baud), 87 µs (rtl_433). The
// period is not assumed: the winner is found at the decoded frame and logged.
static const int32_t PERIOD_CANDIDATES[] = {90, 88, 89, 87};
// Measured: widening this grid (86-90, then 85.0-91.0 µs in 0.1 steps) decodes not one more of the
// six dump captures (1/6 without the net, whatever the grid). The exact bit rate is not the lock;
// do not touch it without a measurement that proves it (dev/docs/bit-jitter-analysis.md §2bis).
static constexpr size_t PERIOD_CANDIDATE_COUNT =
    sizeof(PERIOD_CANDIDATES) / sizeof(PERIOD_CANDIDATES[0]);

// Pulse durations → NRZ bits (round to the nearest period multiple). `invert` swaps levels: the
// GDO0 output polarity depends on the module and must not be assumed.
inline size_t timings_to_bits(const int32_t *timings, size_t count, int32_t period_us, bool invert,
                              uint8_t *bits, size_t max_bits) {
  const int32_t half = period_us / 2;
  size_t n = 0;
  for (size_t i = 0; i < count; i++) {
    const int32_t v = timings[i];
    const uint8_t level = (v > 0) ? 1 : 0;
    const int32_t duration = (v > 0) ? v : -v;
    int32_t run = (duration + half) / period_us;
    if (run < 1) {
      run = 1;
    }
    if (run > MAX_RUN_BITS) {
      continue;
    }
    for (int32_t k = 0; k < run; k++) {
      if (n >= max_bits) {
        return n;
      }
      bits[n++] = invert ? (uint8_t)(1 - level) : level;
    }
  }
  return n;
}

// Same conversion, but the period is in TENTHS of a microsecond: the period measured on a burst is
// 88.5 µs, which an integer cannot represent. Rounding is strictly the same (nearest multiple).
inline size_t timings_to_bits_fin(const int32_t *timings, size_t count, int32_t period_x10,
                                  bool invert, uint8_t *bits, size_t max_bits) {
  const int32_t half = period_x10 / 2;
  size_t n = 0;
  for (size_t i = 0; i < count; i++) {
    const int32_t v = timings[i];
    const uint8_t level = (v > 0) ? 1 : 0;
    const int32_t duration = (v > 0) ? v : -v;
    int32_t run = (duration * 10 + half) / period_x10;
    if (run < 1) {
      run = 1;
    }
    if (run > MAX_RUN_BITS) {
      continue;
    }
    for (int32_t k = 0; k < run; k++) {
      if (n >= max_bits) {
        return n;
      }
      bits[n++] = invert ? (uint8_t)(1 - level) : level;
    }
  }
  return n;
}

// ---------------------------------------------------------------------------------------
// BIT PERIOD MEASURED ON THE BURST (tenths of µs; 0 = estimation refused)
// ---------------------------------------------------------------------------------------
// Measured: this station transmits at 88.5-88.9 µs (the reference project measures 88.3 µs); the
// 90 µs constant inherited from rtl_433 was wrong by 2 %. The rate depends on the transmitter, the
// crystal and the demodulator, so it is MEASURED on each burst — no station constant: flash and go.
//
// Method (validated offline on six real bursts: 88.5-88.9 µs): the starting estimate is the median
// of the 45-115 µs window — a PROTOCOL window (a bit is ~90 µs), not station-specific; widening it
// would let in the 45-50 µs parasite edges and two-bit pulses.
//
// Consolidation, three passes: mean of d / round(d / T) over durations >= 0.55·T. Shorter ones are
// parasites (a bit cannot be shorter than half a period); the division rescales 2-, 3-bit pulses.
// No allocation: the histogram is static (one task, single-threaded host test).
static constexpr int32_t PERIODE_MIN_X10 = 500;    // 50 µs: shorter is not a plausible bit
static constexpr int32_t PERIODE_MAX_X10 = 1500;   // 150 µs: neither is longer
static constexpr int32_t WINDOW_LOW_US = 45;      // low bound of the protocol window
static constexpr int32_t WINDOW_HIGH_US = 115;    // high bound
static constexpr int HIST_MAX_US = 400;

inline int32_t estimer_periode_x10(const int32_t *timings, size_t count) {
  static uint16_t histo[HIST_MAX_US];
  for (int i = 0; i < HIST_MAX_US; i++) {
    histo[i] = 0;
  }
  size_t utiles = 0;
  for (size_t i = 0; i < count; i++) {
    int32_t d = timings[i] > 0 ? timings[i] : -timings[i];
    if (d > 0 && d < HIST_MAX_US) {
      histo[d]++;
      utiles++;
    }
  }
  if (utiles < 20) {
    return 0;
  }
  // Median of the protocol window (fallback: median of everything if the window is empty).
  int64_t base = 0;
  for (int band = 0; band < 2 && base == 0; band++) {
    const int low = band == 0 ? WINDOW_LOW_US : 1;
    const int high = band == 0 ? WINDOW_HIGH_US : HIST_MAX_US - 1;
    size_t total = 0;
    for (int b = low; b <= high; b++) {
      total += histo[b];
    }
    if (total < 10) {
      continue;
    }
    const size_t milieu = total / 2;
    size_t cumul = 0;
    for (int b = low; b <= high; b++) {
      cumul += histo[b];
      if (cumul > milieu) {
        base = b * 10;
        break;
      }
    }
  }
  if (base <= 0) {
    return 0;
  }
  // Consolidation: rescale each pulse to one bit and average.
  int32_t T = (int32_t) base;
  for (int passe = 0; passe < 3; passe++) {
    const int32_t threshold = (T * 55) / 100;
    int64_t somme = 0;
    size_t n = 0;
    for (size_t i = 0; i < count; i++) {
      const int32_t d = timings[i] > 0 ? timings[i] : -timings[i];
      if (d < threshold) {
        continue;
      }
      int32_t k = (d * 10 + T / 2) / T;   // number of bits in this pulse
      if (k < 1) {
        k = 1;
      }
      somme += (int64_t)(d * 10) / k;     // duration rescaled to one bit
      n++;
    }
    if (n < 5) {
      return 0;
    }
    const int32_t nouveau = (int32_t)(somme / (int64_t) n);
    if (nouveau == T) {
      break;
    }
    T = nouveau;
  }
  if (T < PERIODE_MIN_X10 || T > PERIODE_MAX_X10) {
    return 0;   // implausible estimate: prefer the fallback grid
  }
  return T;
}

// Search the NEXT sync word from *from_bit, then rebuild the 21 following bytes. *from_bit is
// advanced past the found candidate so the caller can enumerate them all: decode() decides, a wrong
// alignment must not hide the right one.
inline bool find_frame_candidate(const uint8_t *bits, size_t bit_count, uint8_t *out,
                                 size_t *from_bit, size_t *payload_bit = nullptr,
                                 size_t marge = 0) {
  const size_t sync_bits = SYNC_BYTES * 8;
  const size_t frame_bits = FRAME_BYTES * 8;
  // `marge` = 1 allows a payload ONE BIT SHORT: a pulse that lost a bit makes the stream shorter,
  // and without this margin the frame no longer fits the window, so no candidate is produced and
  // the insertion repair is never reached. Missing bits beyond the stream count as 0 (deterministic).
  for (size_t start = *from_bit; start + sync_bits + frame_bits >= marge &&
                               start + sync_bits + frame_bits - marge <= bit_count;
       start++) {
    bool match = true;
    for (size_t i = 0; i < sync_bits; i++) {
      const uint8_t expected = (uint8_t)((SYNC_WORD[i / 8] >> (7 - (i % 8))) & 0x01);
      if (bits[start + i] != expected) {
        match = false;
        break;
      }
    }
    if (!match) {
      continue;
    }
    const size_t payload = start + sync_bits;
    if (payload_bit != nullptr) {
      *payload_bit = payload;
    }
    for (size_t b = 0; b < FRAME_BYTES; b++) {
      uint8_t byte = 0;
      for (size_t k = 0; k < 8; k++) {
        const size_t i = payload + b * 8 + k;
        byte = (uint8_t)((byte << 1) | (i < bit_count ? bits[i] : 0));
      }
      out[b] = byte;
    }
    *from_bit = start + 1;
    return true;
  }
  return false;
}

// REPAIR BY INSERTING ONE BIT (measured mechanism): a pulse counted as one bit was worth two, so
// everything after shifts by one bit and values double (02 22 → 04 44). Inserting one bit at the
// right position repairs two of six dump bursts; deleting one repaired none.
//
// PHYSICAL CONSTRAINT (added 04/10/2026 after a production defect — dev/docs/zero-wind-fabrication.md):
// a lost bit comes from a pulse whose duration was rounded DOWN, so the recovered bit can only
// EXTEND the run of the preceding bit: same level. The first version searched an insertion of ANY
// value at ANY position, and `decode()` cannot tell a wrong position from the right one when the
// byte sum happens to be preserved — the checksum is a plain sum (professionally: "a frame can
// pass header + checksum + counter and still be WRONG"). Measured on a zero-wind frame
// (b[8..10] = 01 01 00): 14 of the ~168 loss positions produced a checksum-valid, plausible frame
// with wind 46.0 km/h and gust 102.4 km/h (b[8..10] = 02 80 80) — because
// 0x01+0x01+0x00 = 0x02+0x80+0x80 (mod 256), so checksum, counter and the whole plausibility gate
// stay green; the repair published them (141 such frames in production on 04/10). With the
// constraint none of them is published any more (the recovered frame is the true one, or no frame
// at all). The repair still recovers the same share of real bursts.
//
// Bounded: a single insertion, then header + checksum + counter + plausibility must all pass.
inline bool repair_by_insertion(const uint8_t *bits, size_t payload_bit, uint8_t *candidate) {
  const size_t frame_bits = FRAME_BYTES * 8;
  for (size_t q = 0; q <= frame_bits; q++) {
    // The recovered bit continues the preceding pulse: same level as the bit that precedes the
    // insertion point (for q = 0, the last bit transmitted before the payload, i.e. the sync word).
    const size_t precedent = payload_bit + q;
    const uint8_t insere = precedent > 0 ? (uint8_t)(bits[precedent - 1] & 1) : 0;
    uint8_t attempt[FRAME_BYTES];
    for (size_t b = 0; b < FRAME_BYTES; b++) {
      uint8_t octet = 0;
      for (size_t k = 0; k < 8; k++) {
        const size_t i = b * 8 + k;
        const uint8_t bit = (i < q) ? bits[payload_bit + i]
                                     : ((i == q) ? insere : bits[payload_bit + i - 1]);
        octet = (uint8_t)((octet << 1) | bit);
      }
      attempt[b] = octet;
    }
    Frame f;
    const char *raison = "";
    if (decode(attempt, f, &raison)) {
      for (size_t i = 0; i < FRAME_BYTES; i++) {
        candidate[i] = attempt[i];
      }
      return true;
    }
  }
  return false;
}

// Try ONE period (tenths of µs) and both polarities, with the two bounded repairs. `repaired_out`
// flags a frame that came out of a repair: the caller can submit it to an extra check
// (see vevor_7in1.cpp, guard on the TX counter).
inline bool essayer_periode(const int32_t *timings, size_t count, int32_t period_x10,
                            uint8_t *bits, size_t max_bits, uint8_t *raw_out,
                            bool *inverted_used, size_t *rejected_out, bool *repaired_out) {
  const size_t needed = SYNC_BYTES * 8 + FRAME_BYTES * 8;
  for (int polarity = 0; polarity < 2; polarity++) {
    const bool invert = (polarity == 1);
    const size_t n = timings_to_bits_fin(timings, count, period_x10, invert, bits, max_bits);
    // SATURATED conversion (buffer full): the stream is truncated, no longer interpretable. One bit
    // SHORT of a full frame is accepted: exactly the shortened-pulse case that the insertion repair
    // can restore.
    if (n >= max_bits || n + 1 < needed) {
      continue;
    }
    // Two passes: the full payload first; if no frame comes out, search again tolerating one missing
    // bit. Rejects are counted only on the first pass, or the same candidate would be counted twice.
    for (size_t marge = 0; marge < 2; marge++) {
      size_t from = 0;
      size_t payload_bit = 0;
      uint8_t candidate[FRAME_BYTES];
      Frame frame;
      const char *reason = "";
      while (find_frame_candidate(bits, n, candidate, &from, &payload_bit, marge)) {
        bool ok = decode(candidate, frame, &reason);
        bool repaired = false;
        if (!ok) {
          // ONE-BIT TOLERANCE ON THE HEADER BYTE (measured): byte 0 arrives with one wrong bit
          // (0xAB, 0xAE or 0xEA instead of 0xAA) while the next bytes are exact — a mis-timed edge,
          // not the frame. Safe only because checksum + counter + plausibility must then all pass.
          uint8_t corrige[FRAME_BYTES];
          for (uint8_t k = 0; k < 8 && !ok; k++) {
            for (size_t i = 0; i < FRAME_BYTES; i++) {
              corrige[i] = candidate[i];
            }
            corrige[0] = (uint8_t)(corrige[0] ^ (uint8_t)(1u << k));
            if (decode(corrige, frame, &reason)) {
              for (size_t i = 0; i < FRAME_BYTES; i++) {
                candidate[i] = corrige[i];
              }
              ok = true;
              repaired = true;
            }
          }
        }
        if (!ok) {
          // Then the one-bit insertion repair (see repair_by_insertion). Measured cost: 168
          // positions × 21 bytes ≈ 28 000 operations, under 1 ms at 160 MHz, and only when a sync
          // was found but no frame decoded.
          if (repair_by_insertion(bits, payload_bit, candidate)) {
            if (decode(candidate, frame, &reason)) {
              ok = true;
              repaired = true;
            }
          }
        }
        if (ok) {
          for (size_t i = 0; i < FRAME_BYTES; i++) {
            raw_out[i] = candidate[i];
          }
          if (inverted_used != nullptr) {
            *inverted_used = invert;
          }
          if (repaired_out != nullptr) {
            *repaired_out = repaired;
          }
          return true;
        }
        // Sync word found but frame REFUSED: the real decoding-noise counter, distinct from
        // "nothing reaches the chip".
        if (rejected_out != nullptr && marge == 0) {
          (*rejected_out)++;
        }
      }
    }
  }
  return false;
}

// Full chain: measure the bit period ON THE BURST first (no station constant), then, if the estimate
// fails or is wrong, try the fixed fallback grid — each candidate with both polarities and the
// bounded repairs. `period_used` is in TENTHS of µs.
inline bool decode_timings(const int32_t *timings, size_t count, const int32_t *periods,
                           size_t period_count, uint8_t *bits, size_t max_bits, uint8_t *raw_out,
                           int32_t *period_used, bool *inverted_used,
                           size_t *rejected_out = nullptr, bool *repaired_out = nullptr) {
  if (count < MIN_TIMINGS) {
    return false;
  }
  if (repaired_out != nullptr) {
    *repaired_out = false;
  }
  bool repaired = false;

  // 1. MEASURED PERIOD (normal path, and the only one valid for an unknown board).
  const int32_t mesuree = estimer_periode_x10(timings, count);
  if (mesuree != 0 &&
      essayer_periode(timings, count, mesuree, bits, max_bits, raw_out, inverted_used, rejected_out,
                      &repaired)) {
    if (period_used != nullptr) {
      *period_used = mesuree;
    }
    if (repaired_out != nullptr) {
      *repaired_out = repaired;
    }
    return true;
  }

  // 2. FALLBACK: the fixed grid, for when the estimate is refused (noise) or off.
  for (size_t p = 0; p < period_count; p++) {
    if (essayer_periode(timings, count, periods[p] * 10, bits, max_bits, raw_out, inverted_used,
                        rejected_out, &repaired)) {
      if (period_used != nullptr) {
        *period_used = periods[p] * 10;
      }
      if (repaired_out != nullptr) {
        *repaired_out = repaired;
      }
      return true;
    }
  }
  return false;
}

// Stitch two burst FRAGMENTS (see MAX_FRAGMENT_TIMINGS). The RMT cut can fall MID-PULSE: two
// half-pulses then share the same sign and must be added to recover the original pulse, or each
// splice invents an edge and shifts every following bit. `out` holds prev_count + cur_count.
inline size_t stitch_fragments(const int32_t *prev, size_t prev_count, const int32_t *cur,
                               size_t cur_count, int32_t *out, size_t max_out) {
  size_t n = 0;
  for (size_t i = 0; i < prev_count && n < max_out; i++) {
    out[n++] = prev[i];
  }
  size_t first = 0;
  if (n > 0 && cur_count > 0 && ((out[n - 1] >= 0) == (cur[0] >= 0))) {
    out[n - 1] += cur[0];
    first = 1;
  }
  for (size_t i = first; i < cur_count && n < max_out; i++) {
    out[n++] = cur[i];
  }
  return n;
}

}  // namespace vevor