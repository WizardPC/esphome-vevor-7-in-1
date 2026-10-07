#include "vevor_7in1.h"

// This file holds ONLY the receiver wiring, the stitching of cut bursts, the deduplication of
// double deliveries and the heartbeat. All protocol logic (pulses -> bits -> bytes -> values) is in
// includes/vevor_protocol.h (testable off-hardware). No SPI access (see vevor_7in1.h).

namespace esphome {
namespace vevor_7in1 {

void Vevor7in1::dump_receiver_config_() {
  ESP_LOGI(TAG, "=== effective remote_receiver configuration (re-logged) ===");
  this->receiver_->dump_config();
  if (this->receiver_->is_failed()) {
    ESP_LOGE(TAG, "RECEIVER FAILED (is_failed): no capture can arrive, whatever the "
                  "decoder does — this is an RMT allocation/config problem");
  } else {
    ESP_LOGI(TAG, "receiver operational (is_failed=false)");
  }
}

void Vevor7in1::loop() {
  // Guard: if setup() found no remote_receiver — or marked the component failed — `receiver_` is
  // null and the heartbeat (dump_receiver_config_) would dereference it. setup() tests it already;
  // loop() must test it too (see dev/docs/firmware-design-notes.md).
  if (this->receiver_ == nullptr || this->is_failed()) {
    return;
  }
  const uint32_t now = millis();
  if (now - this->last_report_ms_ < HEARTBEAT_MS) {
    return;
  }
  this->last_report_ms_ = now;

  if (!this->receiver_dumped_ || (this->heartbeats_ % 12u) == 0u) {
    // Once at boot, then every minute: the first dump runs BEFORE the API is reachable, so once is
    // not enough to read it from outside.
    this->receiver_dumped_ = true;
    this->dump_receiver_config_();
  }
  this->heartbeats_++;

  if (this->reported_captures_ == this->captures_) {
    ESP_LOGD(TAG, "no burst for %u s (captures=%u, frames=%u, rejects=%u) — normal",
             (unsigned) (HEARTBEAT_MS / 1000), (unsigned) this->captures_, (unsigned) this->frames_,
             (unsigned) this->rejected_);
    return;
  }

  ESP_LOGI(TAG,
           "captures=%u (+%u), frames=%u, rejects=%u, repaired=%u (%u refused), "
           "rain_refused=%u, last pulses=%u, longest=%u",
           (unsigned) this->captures_, (unsigned) (this->captures_ - this->reported_captures_),
           (unsigned) this->frames_, (unsigned) this->rejected_, (unsigned) this->repairs_,
           (unsigned) this->repairs_rejetees_, (unsigned) this->rain_rejected_,
           (unsigned) this->last_pulse_count_, (unsigned) this->longest_capture_);
  this->reported_captures_ = this->captures_;
}

size_t Vevor7in1::build_stitched_(const std::vector<int32_t> &timings) {
  // The logic lives in includes/vevor_protocol.h (stitch_fragments), testable off-hardware: here we
  // only give it a reusable buffer.
  const size_t need = this->prev_fragment_.size() + timings.size();
  if (this->stitched_.size() < need) {
    this->stitched_.resize(need);
  }
  return vevor::stitch_fragments(this->prev_fragment_.data(), this->prev_fragment_.size(),
                                 timings.data(), timings.size(), this->stitched_.data(),
                                 this->stitched_.size());
}

bool Vevor7in1::dump(remote_base::RemoteReceiveData src) {
  const std::vector<int32_t> &timings = src.get_raw_data();
  this->captures_++;
  this->last_pulse_count_ = timings.size();
  // FAST symptom, counted on every capture: a capture too short to hold anything decodable. A
  // fragment (the RMT cuts a burst in two) is 70-96 pulses and perfectly normal; a deaf chip
  // delivers 2-7. The watchdog reads this counter and re-arms the radio at once.
  if (timings.size() < this->pulse_threshold_) {
    this->captures_creuses_++;
  } else {
    this->captures_creuses_ = 0;
  }
  if (timings.size() > this->longest_capture_) {
    this->longest_capture_ = timings.size();
  }

  // The first captures are detailed, and any capture requested by hand too (the "Dump pulses"
  // button): the plain durations are the ONLY way to analyse the real burst off-board, the API
  // only delivering logs.
  if (this->captures_ <= 3 || this->dump_requested_ || this->dump_restants_ > 0) {
    int32_t shortest = 1000000;
    int32_t longest = 0;
    for (int32_t t : timings) {
      const int32_t d = t >= 0 ? t : -t;
      if (d < shortest) {
        shortest = d;
      }
      if (d > longest) {
        longest = d;
      }
    }
    ESP_LOGI(TAG, "capture #%u: %u pulses, from %d us to %d us", (unsigned) this->captures_,
             (unsigned) timings.size(), (int) shortest, (int) longest);

    // 64 durations do NOT cover a Vevor burst (~176 symbols): logging up to 512 durations, in
    // chunks of 64, keeps one multi-kilobyte line from being truncated by the API logging layer.
    const size_t a_dumper = timings.size() < 512 ? timings.size() : 512;
    for (size_t debut = 0; debut < a_dumper; debut += 64) {
      std::string tranche;
      for (size_t i = debut; i < a_dumper && i < debut + 64; i++) {
        if (i != debut) {
          tranche += ' ';
        }
        tranche += std::to_string(timings[i]);
      }
      const size_t fin = (debut + 63 < a_dumper) ? debut + 63 : a_dumper - 1;
      ESP_LOGI(TAG, "  pulses [%u-%u] of %u: %s", (unsigned) debut, (unsigned) fin,
               (unsigned) a_dumper, tranche.c_str());
    }
    if (this->dump_restants_ > 0) {
      this->dump_restants_--;
    }
    this->dump_requested_ = false;
  }

  // A capture is a burst FRAGMENT if too short to carry a whole one: measured, a useful burst is
  // 176-184 pulses and the C3's RMT sometimes cuts it in two (96 + 82, 94 + 70...). Stitching only
  // makes sense then; the predicate lives in includes/vevor_protocol.h (test_fragment_policy()).
  const bool fragment = vevor::is_fragment(timings.size());

  uint8_t raw[vevor::FRAME_BYTES];
  int32_t period_used = 0;
  bool inverted = false;
  bool repaired = false;
  size_t rejected = 0;

  // 1. DIRECT DECODING of the capture, without stitching: the normal case.
  bool ok = vevor::decode_timings(timings.data(), timings.size(), vevor::PERIOD_CANDIDATES,
                                  vevor::PERIOD_CANDIDATE_COUNT, this->bits_.data(),
                                  this->bits_.size(), raw, &period_used, &inverted, &rejected,
                                  &repaired);
  this->rejected_ += rejected;

  bool from_stitch = false;
  if (!ok && fragment && !this->prev_fragment_.empty()) {
    // 2. STITCHING, only between two burst fragments. Stitching a COMPLETE capture in front of the
    //    next one re-reads the PREVIOUS burst (measured: 60 frames for 31 distinct measurements,
    //    each TX counter twice, 20 s apart, hence outside the 5 s anti-duplicate window).
    const size_t stitched = this->build_stitched_(timings);
    rejected = 0;
    ok = vevor::decode_timings(this->stitched_.data(), stitched, vevor::PERIOD_CANDIDATES,
                               vevor::PERIOD_CANDIDATE_COUNT, this->bits_.data(),
                               this->bits_.size(), raw, &period_used, &inverted, &rejected,
                               &repaired);
    this->rejected_ += rejected;
    from_stitch = ok;
  }

  // Remember the current capture as a possible fragment for the next one — ONLY if it is one: a
  // complete burst must never serve as a prefix to the next.
  this->prev_fragment_ = fragment ? timings : std::vector<int32_t>();

  if (!ok) {
    return false;
  }

  // RAIN CONTINUITY — state check on ALL frames (see rain_plausible in vevor_protocol.h): two
  // peaks at 7 634.5 mm under a clear sky went unstopped (the protocol plausibility gate ignores
  // rain). A frame refused here does NOT become the next reference (last_frame_ is updated after).
  {
    vevor::Frame f;
    vevor::Frame precedente;
    const char *raison = "";
    if (vevor::decode(raw, f, &raison)) {
      float derniere = 0.0f;
      bool connue = false;
      if (this->has_last_frame_ && vevor::decode(this->last_frame_, precedente, &raison)) {
        derniere = precedente.rain_mm;
        connue = true;
      }
      if (!vevor::rain_plausible(f.rain_mm, derniere, connue)) {
        this->rain_rejected_++;
        // The RAW bytes in the message: without them the frame is blocked with no way to know why,
        // which is exactly what we want to understand.
        const std::string bytes = vevor::hex_bytes(raw, vevor::FRAME_BYTES);
        ESP_LOGW(TAG,
                 "rain refused: %.1f mm while the previous frame gave %.1f mm (rise "
                 "physiquement impossible) — bruts : %s",
                 f.rain_mm, derniere, bytes.c_str());
        return false;
      }
    }
  }

  // CONTINUITY GUARD, for REPAIRED frames only: published only if consistent with the last accepted
  // frame (same station, measurements that do not jump from burst to burst). On 200 random payloads
  // it fabricated none: a zero-cost precaution; direct frames are exempt.
  if (repaired) {
    vevor::Frame f;
    vevor::Frame precedente;
    const char *raison = "";
    const bool reference =
        this->has_last_frame_ && vevor::decode(this->last_frame_, precedente, &raison);
    if (vevor::decode(raw, f, &raison) && reference && !vevor::continuite_ok(f, precedente)) {
      this->repairs_rejetees_++;
      ESP_LOGD(TAG,
               "repaired frame REFUSED by the continuity guard (station or measurements "
               "inconsistent with the previous frame)");
      return false;
    }
    this->repairs_++;
  }

  // The same burst is regularly delivered twice by the RMT: two frames identical byte for byte a
  // few tens of milliseconds apart are the same measurements read twice. Only the first is
  // triggered.
  if (this->has_last_frame_ && (uint32_t) (millis() - this->last_frame_ms_) < DUP_WINDOW_MS &&
      memcmp(this->last_frame_, raw, vevor::FRAME_BYTES) == 0) {
    this->duplicates_++;
    ESP_LOGD(TAG, "duplicate ignored (same frame as the previous one, %u ms earlier)",
             (unsigned) (millis() - this->last_frame_ms_));
    return false;
  }
  memcpy(this->last_frame_, raw, vevor::FRAME_BYTES);
  this->last_frame_ms_ = millis();
  this->has_last_frame_ = true;

  this->decoded_++;
  // Station identity, THE filter. 0 = learn: the first valid frame is adopted and logged. Any other
  // value PINS a station: every other ID is dropped, which is how a neighbour's station stays out.
  // A dropped frame is warned about ONCE per pin: a wrong ID must never look like a radio fault
  // (the watchdog watches decoded_, not frames_, precisely so this filter cannot trigger it).
  const uint16_t frame_id = (uint16_t) (((uint16_t) raw[2] << 8) | raw[3]);
  if (this->station_id_ == 0) {
    this->station_id_ = frame_id;
    ESP_LOGI(TAG, "station: ID learned %u (0x%04x) — it changes with the batteries",
             (unsigned) frame_id, (unsigned) frame_id);
  } else if (frame_id != this->station_id_) {
    this->foreign_id_++;
    if (!this->foreign_id_warned_) {
      this->foreign_id_warned_ = true;
      ESP_LOGW(TAG, "station: frame from ANOTHER station (ID %u expected, %u received) — ignored; "
                    "set the ID to 0 or press \"Re-learn station ID\" to learn it again",
               (unsigned) this->station_id_, (unsigned) frame_id);
    }
    return false;
  }

  this->frames_++;
  this->update_rate_window_(raw[18]);   // byte 18 = the station's emission counter (protocol.h:129)
  // The period is in TENTHS of a microsecond (measured on the burst): we log the value actually
  // kept, not a misleading integer.
  ESP_LOGD(TAG, "frame extracted (measured period %d.%d us, polarity %s, %s%s) → %u bytes",
           (int) (period_used / 10), (int) (period_used % 10), inverted ? "inverted" : "normal",
           from_stitch ? "stitched from two fragments" : "in one piece",
           repaired ? ", REPAIRED" : "", (unsigned) vevor::FRAME_BYTES);

  // The frame is handed back TO the YAML, which publishes the sensors: the component does not know
  // the entities, and the protocol logic stays testable off-hardware in includes/vevor_protocol.h.
  std::vector<uint8_t> payload(raw, raw + vevor::FRAME_BYTES);
  this->frame_trigger_.trigger(payload);
  return true;
}

// -------------------------------------------------------------------------------------------
// Reception watchdog: THE policy, in one single place (it used to live in a YAML lambda).
//
// Measurements of 05/10/2026 that forced this move:
//   - a SINGLE silent slot (20 s) was enough to reset the chip, while the station transmits every
//     20 s exactly: one jittered emission made the radio re-arm every 20 s;
//   - on a marginal SPI link, every re-arm is a lottery: 2 register writes lost in 4 minutes of
//     measurements, and a lost write leaves the chip misconfigured (a "register not taken" line) —
//     the watchdog then MAINTAINS the fault instead of curing it.
// Hence: SPACED re-arms (never one per slot), then a restart, the only remedy measured so far.
// -------------------------------------------------------------------------------------------

// Setting identifiers; the entities live in number/.
static const uint8_t PARAM_REARM_AFTER_SLOTS = 0;
static const uint8_t PARAM_MAX_RESTART_DELAY = 1;
static const uint8_t PARAM_STATION_ID = 2;
// Below this many pulses, a capture cannot hold a burst: it is a fragment (70-96 pulses, normal) or
// silence (2-7, a deaf chip). 40 sits between the two, measured on this hardware.
static const uint8_t PARAM_PULSE_THRESHOLD = 3;
// Watchdog slot duration: the station's transmission period (see setup() in the .h).
static const uint32_t WATCHDOG_SLOT_MS = 20000;

float Vevor7in1::get_parameter(uint8_t p) const {
  if (p == PARAM_MAX_RESTART_DELAY) {
    return static_cast<float>(this->max_restart_delay_s_);
  }
  if (p == PARAM_STATION_ID) {
    return static_cast<float>(this->station_id_);
  }
  if (p == PARAM_PULSE_THRESHOLD) {
    return static_cast<float>(this->pulse_threshold_);
  }
  return static_cast<float>(this->rearm_after_slots_);
}

void Vevor7in1::set_parameter(uint8_t p, float value) {
  if (p == PARAM_STATION_ID) {
    // 0 is legal here and means "learn": the minimum of 1 used for the duration settings does not
    // apply to an identity. A pinned ID is a filter, not a delay.
    const float arrondi = value < 0.0f ? 0.0f : value + 0.5f;
    const uint32_t id = arrondi > 65535.0f ? 65535u : static_cast<uint32_t>(arrondi);
    this->station_id_ = static_cast<uint16_t>(id);
    this->foreign_id_warned_ = false;  // a new pin deserves its own warning
    ESP_LOGI(TAG, "station: ID %s", id == 0 ? "back to learning" : "forced");
    return;
  }
  const uint32_t v = value < 1.0f ? 1u : static_cast<uint32_t>(value + 0.5f);
  if (p == PARAM_MAX_RESTART_DELAY) {
    this->max_restart_delay_s_ = v;
  } else if (p == PARAM_PULSE_THRESHOLD) {
    this->pulse_threshold_ = v;
  } else {
    this->rearm_after_slots_ = v;
  }
  ESP_LOGI(TAG, "watchdog: parameter %u = %u", (unsigned) p, (unsigned) v);
}

void Vevor7in1::reapprendre_station_id() {
  this->station_id_ = 0;
  this->foreign_id_warned_ = false;
  ESP_LOGI(TAG, "station: ID forgotten, the next valid frame will decide");
}

void Vevor7in1::watch_radio_() {
  // --- Re-arm policy, measured 05/10/2026 (dev/state/CAMPAGNE_20261005.md) --------------------
  // A re-arm is a COMPLETE, register-verified re-initialisation whose ANALOG outcome (VCO/PLL
  // calibration) is a coin flip: over five presses, three cured the chip, one left it deaf for two
  // minutes and one degraded a partially working chip — with every key register read back
  // conforming, so the registers are not the problem. Two consequences, both implemented here:
  //   (1) only a chip that delivers NOTHING deserves a re-arm (a chip still producing 70-182 pulses
  //       per fragment can be broken by one, never helped);
  //   (2) after a re-arm, CHECK IT TOOK: only a capture carrying a full burst proves it, otherwise
  //       try again — bounded, since a dead chip loses nothing by it.
  const bool healthy_capture = this->last_pulse_count_ >= this->pulse_threshold_;

  // 1. SLOT BOOKKEEPING, THEN THE RESTART — THE LAST RESORT — BEFORE ANYTHING ELSE.
  //    A re-arm is a cheap lottery, NOT a reboot: on 05/10/2026 a chip that came out of a flash deaf
  //    needed SEVEN successive re-arms before one took (18:30 → 18:34:58). The first version of this
  //    policy returned early from the fast criterion, and so STARVED the restart: a chip no soft
  //    re-arm can wake would have stayed deaf for good. Nothing below may run before this block.
  //    The criterion is the DECODED frame, never a capture: a capture can be pure noise, and it is
  //    deliberately NOT the published frame — a frame dropped by the station filter still proves the
  //    RECEPTION works, and a wrong pin must never send the watchdog hunting a radio fault.
  const bool frame_decoded = (this->decoded_ != this->watchdog_frames_);
  if (frame_decoded) {
    this->watchdog_frames_ = this->decoded_;
    this->silent_slots_ = 0;
    this->rearms_ = 0;
    if (this->watchdog_reboots_ != 0) {
      this->watchdog_reboots_ = 0;
      this->pref_reboots_.save(&this->watchdog_reboots_);
    }
  } else {
    this->silent_slots_++;
  }
  const uint32_t muettes_s = this->silent_slots_ * (WATCHDOG_SLOT_MS / 1000u);
  const bool radio_en_echec = (this->radio_ != nullptr) && this->radio_->is_failed();

  if (muettes_s >= this->max_restart_delay_s_) {
    this->watchdog_reboots_++;
    this->pref_reboots_.save(&this->watchdog_reboots_);
    // Brake: past ten restarts, only one slot in 45 (15 min) is used, so a genuinely mute board
    // cannot loop forever.
    if (this->watchdog_reboots_ > 10 && (this->silent_slots_ % 45u) != 0u) {
      return;
    }
    ESP_LOGW(TAG, "no frame for %u s (radio %s, captures %u) — restart #%u",
             (unsigned) muettes_s, radio_en_echec ? "EN ECHEC" : "ok", (unsigned) this->captures_,
             (unsigned) this->watchdog_reboots_);
    App.safe_reboot();
    return;
  }

  // 2. A decoded frame ends the round here: nothing below has anything to fix.
  if (frame_decoded) {
    return;
  }
  ESP_LOGD(TAG, "watchdog: no frame for %u s (radio %s, captures %u)", (unsigned) muettes_s,
           radio_en_echec ? "EN ECHEC" : "ok", (unsigned) this->captures_);

  // 3. The fast criterion and its verification (see the policy above).
  if (this->rearm_attempts_ > 0) {
    if (healthy_capture) {
      ESP_LOGI(TAG, "re-arm VERIFIED after %u attempt(s): healthy capture (%u pulses)",
               (unsigned) this->rearm_attempts_, (unsigned) this->last_pulse_count_);
      this->rearm_attempts_ = 0;
      this->slots_since_rearm_ = 0;
    } else if (++this->slots_since_rearm_ >= 2) {
      this->slots_since_rearm_ = 0;
      if (this->rearm_attempts_ < 3) {
        this->rearm_attempts_++;
        this->deaf_rearms_++;
        ESP_LOGW(TAG, "re-arm had no effect (short captures): attempt %u of 3",
                 (unsigned) this->rearm_attempts_);
        if (this->radio_ != nullptr) {
          this->radio_->reset();
        }
      } else {
        ESP_LOGW(TAG, "re-arm: 3 attempts without a healthy capture, back to the slow criterion");
        this->rearm_attempts_ = 0;
      }
    }
    return;   // one outstanding attempt at a time: no doubling with the slow criterion
  }

  if (this->captures_creuses_ >= 2) {
    this->captures_creuses_ = 0;
    this->rearm_attempts_ = 1;
    this->slots_since_rearm_ = 0;
    this->deaf_rearms_++;
    ESP_LOGW(TAG, "short captures (%u pulses < threshold %u): radio re-arm #%u",
             (unsigned) this->last_pulse_count_, (unsigned) this->pulse_threshold_,
             (unsigned) this->deaf_rearms_);
    if (this->radio_ != nullptr) {
      this->radio_->reset();
    }
    return;
  }

  // 4. The slow criterion (a whole silent slot, gated on the chip delivering nothing).

  const uint32_t pas = this->rearm_after_slots_ > 0 ? this->rearm_after_slots_ : 1u;
  if (this->silent_slots_ >= pas && (this->silent_slots_ % pas) == 0u) {
    // GATED (05/10/2026): no decoded frame for a whole slot while the chip still delivers 70-182
    // pulses is the DECODER's problem (duty asymmetry against the period estimate), not the radio's.
    // Re-arming there re-initialises a working chip and can cost two minutes of reception, measured.
    // When the chip is deaf, the fast criterion above has already taken the case.
    if (healthy_capture) {
      ESP_LOGD(TAG, "no frame for %u s but the chip is delivering (%u pulses): no "
                    "re-arm (a decoding problem, not a radio one)",
               (unsigned) muettes_s, (unsigned) this->last_pulse_count_);
      return;
    }
    this->rearms_++;
    ESP_LOGW(TAG, "no frame for %u s — radio re-arm %u (one every %u slots)",
             (unsigned) muettes_s, (unsigned) this->rearms_, (unsigned) pas);
    if (this->radio_ != nullptr) {
      this->radio_->reset();
    }
  }
}

// -------------------------------------------------------------------------------------------
// Conform reception rate (see vevor_7in1.h). The station's counter is the only reliable judge
// of how many emissions have gone by: it advances 39 units every 20 s and never skips a
// value (589 frames verified, including eight hours of reception outage). Elapsed time, by
// contrast, assumes a perfect cadence and is wrong as soon as the station drifts.
//
// Its only flaw is being one byte: it wraps every 256 units, i.e. 131 s. The ambiguity is
// settled by the arrival timestamp — if elapsed time implies more units than the raw gap,
// then one or more wraps have occurred.
// -------------------------------------------------------------------------------------------
void Vevor7in1::update_rate_window_(uint8_t compteur) {
  this->window_counters_[this->window_head_] = compteur;
  this->window_times_[this->window_head_] = millis();
  this->window_head_ = (this->window_head_ + 1) % RATE_WINDOW;
  if (this->window_count_ < RATE_WINDOW) {
    this->window_count_++;
  }
}

float Vevor7in1::get_reception_rate() const {
  uint32_t decoded = 0;
  uint32_t emitted = 0;
  this->compute_rate_window_(decoded, emitted);
  if (emitted == 0u) {
    return NAN;
  }
  return 100.0f * (float) decoded / (float) emitted;
}

uint32_t Vevor7in1::get_window_decoded() const {
  uint32_t decoded = 0;
  uint32_t emitted = 0;
  this->compute_rate_window_(decoded, emitted);
  return decoded;
}

uint32_t Vevor7in1::get_window_emitted() const {
  uint32_t decoded = 0;
  uint32_t emitted = 0;
  this->compute_rate_window_(decoded, emitted);
  return emitted;
}

// The ratio is computed HERE and nowhere else: the percentage and its two terms cannot
// diverge. `decoded` counts the decoded frames that updated the measurements (they are
// filtered upstream on duplicates, then on the station ID), `emitted` those the station
// produced — heard or not: that is the whole point of the on-board counter.
void Vevor7in1::compute_rate_window_(uint32_t &decoded, uint32_t &emitted) const {
  decoded = 0;
  emitted = 0;
  if (this->window_count_ < 2) {
    return;   // not enough to measure yet: at least two frames are needed, i.e. one interval
  }
  const size_t first = (this->window_head_ + RATE_WINDOW - this->window_count_) % RATE_WINDOW;
  for (size_t i = 0; i + 1 < this->window_count_; i++) {
    const size_t a = (first + i) % RATE_WINDOW;
    const size_t b = (first + i + 1) % RATE_WINDOW;
    const uint32_t gap = (uint32_t) ((this->window_counters_[b] - this->window_counters_[a]) & 0xFF);
    if (gap == 0u) {
      continue;   // the same counter twice: a re-log of the same line, not an emission
    }
    const uint32_t dt_ms = this->window_times_[b] - this->window_times_[a];
    const uint32_t time_units = (uint32_t) ((dt_ms + 256u) / 513u);   // 1 unit = 0.513 s
    uint32_t wraps = 0;
    if (time_units > gap) {
      wraps = (time_units - gap + 128u) / 256u;
    }
    const uint32_t delta = gap + 256u * wraps;
    uint32_t n = (delta + 19u) / 39u;   // 39 units = one emission from the station
    if (n == 0u) {
      n = 1u;
    }
    decoded++;          // the arriving frame of this pair was indeed received
    emitted += n;
  }
}

}  // namespace vevor_7in1
}  // namespace esphome
