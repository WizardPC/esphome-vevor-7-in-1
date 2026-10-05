#include "vevor_7in1.h"

// This file holds ONLY the receiver wiring, the stitching of cut bursts, the deduplication of
// double deliveries and the heartbeat. All protocol logic (pulses -> bits -> bytes -> values) is in
// includes/vevor_protocol.h (testable off-hardware). No SPI access (see vevor_7in1.h).

namespace esphome {
namespace vevor_7in1 {

void Vevor7in1::dump_receiver_config_() {
  ESP_LOGI(TAG, "=== configuration effective du remote_receiver (re-journalisée) ===");
  this->receiver_->dump_config();
  if (this->receiver_->is_failed()) {
    ESP_LOGE(TAG, "RECEPTEUR EN ECHEC (is_failed) : aucune capture ne peut arriver, quoi qu'on "
                  "fasse côté décodeur — c'est un problème d'allocation/config du RMT");
  } else {
    ESP_LOGI(TAG, "récepteur opérationnel (is_failed=false)");
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
    ESP_LOGD(TAG, "aucune rafale depuis %u s (captures=%u, trames=%u, rejets=%u) — normal",
             (unsigned) (HEARTBEAT_MS / 1000), (unsigned) this->captures_, (unsigned) this->frames_,
             (unsigned) this->rejected_);
    return;
  }

  ESP_LOGI(TAG,
           "captures=%u (+%u), trames=%u, rejets=%u, réparées=%u (dont %u refusées), "
           "pluie_refusee=%u, dernières impulsions=%u, plus longue=%u",
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
  if (timings.size() < this->seuil_impulsions_) {
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
    ESP_LOGI(TAG, "capture #%u : %u impulsions, de %d us à %d us", (unsigned) this->captures_,
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
      ESP_LOGI(TAG, "  impulsions [%u-%u] sur %u : %s", (unsigned) debut, (unsigned) fin,
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

  // RAIN CONTINUITY — state check on ALL frames (see pluie_plausible in vevor_protocol.h): two
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
      if (!vevor::pluie_plausible(f.rain_mm, derniere, connue)) {
        this->rain_rejected_++;
        // The RAW bytes in the message: without them the frame is blocked with no way to know why,
        // which is exactly what we want to understand.
        const std::string octets = vevor::hex_bytes(raw, vevor::FRAME_BYTES);
        ESP_LOGW(TAG,
                 "pluie refusée : %.1f mm alors que la trame précédente en donnait %.1f mm (hausse "
                 "physiquement impossible) — bruts : %s",
                 f.rain_mm, derniere, octets.c_str());
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
               "trame réparée REFUSÉE par le garde-fou de continuité (station ou mesures "
               "incohérentes avec la trame précédente)");
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
    ESP_LOGD(TAG, "doublon ignoré (même trame que la précédente, %u ms avant)",
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
  const uint16_t id_trame = (uint16_t) (((uint16_t) raw[2] << 8) | raw[3]);
  if (this->station_id_ == 0) {
    this->station_id_ = id_trame;
    ESP_LOGI(TAG, "station : ID appris %u (0x%04x) — il change à chaque changement de pile",
             (unsigned) id_trame, (unsigned) id_trame);
  } else if (id_trame != this->station_id_) {
    this->id_etrangere_++;
    if (!this->id_etrangere_signalee_) {
      this->id_etrangere_signalee_ = true;
      ESP_LOGW(TAG, "station : trame d'une AUTRE station (ID %u attendu, %u reçu) — ignorée ; "
                    "mets l'ID à 0 ou appuie sur « Re-learn station ID » pour la réapprendre",
               (unsigned) this->station_id_, (unsigned) id_trame);
    }
    return false;
  }

  this->frames_++;
  // The period is in TENTHS of a microsecond (measured on the burst): we log the value actually
  // kept, not a misleading integer.
  ESP_LOGD(TAG, "trame extraite (période mesurée %d.%d us, polarité %s, %s%s) → %u octets",
           (int) (period_used / 10), (int) (period_used % 10), inverted ? "inversée" : "normale",
           from_stitch ? "en deux morceaux recollés" : "d'un seul bloc",
           repaired ? ", RÉPARÉE" : "", (unsigned) vevor::FRAME_BYTES);

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
static const uint8_t PARAM_CRENEAUX_AVANT_REARMEMENT = 0;
static const uint8_t PARAM_DUREE_MAX_AVANT_REDEMARRAGE = 1;
static const uint8_t PARAM_STATION_ID = 2;
// Below this many pulses, a capture cannot hold a burst: it is a fragment (70-96 pulses, normal) or
// silence (2-7, a deaf chip). 40 sits between the two, measured on this hardware.
static const uint8_t PARAM_SEUIL_IMPULSIONS = 3;
// Watchdog slot duration: the station's transmission period (see setup() in the .h).
static const uint32_t VEILLE_CRENEAU_MS = 20000;

float Vevor7in1::get_parametre(uint8_t p) const {
  if (p == PARAM_DUREE_MAX_AVANT_REDEMARRAGE) {
    return static_cast<float>(this->duree_max_avant_redemarrage_s_);
  }
  if (p == PARAM_STATION_ID) {
    return static_cast<float>(this->station_id_);
  }
  if (p == PARAM_SEUIL_IMPULSIONS) {
    return static_cast<float>(this->seuil_impulsions_);
  }
  return static_cast<float>(this->creneaux_avant_rearmement_);
}

void Vevor7in1::set_parametre(uint8_t p, float valeur) {
  if (p == PARAM_STATION_ID) {
    // 0 is legal here and means "learn": the minimum of 1 used for the duration settings does not
    // apply to an identity. A pinned ID is a filter, not a delay.
    const float arrondi = valeur < 0.0f ? 0.0f : valeur + 0.5f;
    const uint32_t id = arrondi > 65535.0f ? 65535u : static_cast<uint32_t>(arrondi);
    this->station_id_ = static_cast<uint16_t>(id);
    this->id_etrangere_signalee_ = false;  // a new pin deserves its own warning
    ESP_LOGI(TAG, "station : ID %s", id == 0 ? "remis en apprentissage" : "forcé");
    return;
  }
  const uint32_t v = valeur < 1.0f ? 1u : static_cast<uint32_t>(valeur + 0.5f);
  if (p == PARAM_DUREE_MAX_AVANT_REDEMARRAGE) {
    this->duree_max_avant_redemarrage_s_ = v;
  } else if (p == PARAM_SEUIL_IMPULSIONS) {
    this->seuil_impulsions_ = v;
  } else {
    this->creneaux_avant_rearmement_ = v;
  }
  ESP_LOGI(TAG, "veille : paramètre %u = %u", (unsigned) p, (unsigned) v);
}

void Vevor7in1::reapprendre_station_id() {
  this->station_id_ = 0;
  this->id_etrangere_signalee_ = false;
  ESP_LOGI(TAG, "station : ID oublié, la prochaine trame valide fera foi");
}

void Vevor7in1::surveiller_radio_() {
  // --- Re-arm policy, measured 05/10/2026 (dev/state/CAMPAGNE_20261005.md) --------------------
  // A re-arm is a COMPLETE, register-verified re-initialisation whose ANALOG outcome (VCO/PLL
  // calibration) is a coin flip: over five presses, three cured the chip, one left it deaf for two
  // minutes and one degraded a partially working chip — with every key register read back
  // conforming, so the registers are not the problem. Two consequences, both implemented here:
  //   (1) only a chip that delivers NOTHING deserves a re-arm (a chip still producing 70-182 pulses
  //       per fragment can be broken by one, never helped);
  //   (2) after a re-arm, CHECK IT TOOK: only a capture carrying a full burst proves it, otherwise
  //       try again — bounded, since a dead chip loses nothing by it.
  const bool capture_saine = this->last_pulse_count_ >= this->seuil_impulsions_;

  // 1. SLOT BOOKKEEPING, THEN THE RESTART — THE LAST RESORT — BEFORE ANYTHING ELSE.
  //    A re-arm is a cheap lottery, NOT a reboot: on 05/10/2026 a chip that came out of a flash deaf
  //    needed SEVEN successive re-arms before one took (18:30 → 18:34:58). The first version of this
  //    policy returned early from the fast criterion, and so STARVED the restart: a chip no soft
  //    re-arm can wake would have stayed deaf for good. Nothing below may run before this block.
  //    The criterion is the DECODED frame, never a capture: a capture can be pure noise, and it is
  //    deliberately NOT the published frame — a frame dropped by the station filter still proves the
  //    RECEPTION works, and a wrong pin must never send the watchdog hunting a radio fault.
  const bool trame_decodee = (this->decoded_ != this->trames_veille_);
  if (trame_decodee) {
    this->trames_veille_ = this->decoded_;
    this->creneaux_muets_ = 0;
    this->rearmements_ = 0;
    if (this->reboots_veille_ != 0) {
      this->reboots_veille_ = 0;
      this->pref_reboots_.save(&this->reboots_veille_);
    }
  } else {
    this->creneaux_muets_++;
  }
  const uint32_t muettes_s = this->creneaux_muets_ * (VEILLE_CRENEAU_MS / 1000u);
  const bool radio_en_echec = (this->radio_ != nullptr) && this->radio_->is_failed();

  if (muettes_s >= this->duree_max_avant_redemarrage_s_) {
    this->reboots_veille_++;
    this->pref_reboots_.save(&this->reboots_veille_);
    // Brake: past ten restarts, only one slot in 45 (15 min) is used, so a genuinely mute board
    // cannot loop forever.
    if (this->reboots_veille_ > 10 && (this->creneaux_muets_ % 45u) != 0u) {
      return;
    }
    ESP_LOGW(TAG, "aucune trame depuis %u s (radio %s, captures %u) — redémarrage n°%u",
             (unsigned) muettes_s, radio_en_echec ? "EN ECHEC" : "ok", (unsigned) this->captures_,
             (unsigned) this->reboots_veille_);
    App.safe_reboot();
    return;
  }

  // 2. A decoded frame ends the round here: nothing below has anything to fix.
  if (trame_decodee) {
    return;
  }
  ESP_LOGD(TAG, "veille : aucune trame depuis %u s (radio %s, captures %u)", (unsigned) muettes_s,
           radio_en_echec ? "EN ECHEC" : "ok", (unsigned) this->captures_);

  // 3. The fast criterion and its verification (see the policy above).
  if (this->essais_rearmement_ > 0) {
    if (capture_saine) {
      ESP_LOGI(TAG, "ré-armement VÉRIFIÉ après %u essai(s) : capture saine (%u impulsions)",
               (unsigned) this->essais_rearmement_, (unsigned) this->last_pulse_count_);
      this->essais_rearmement_ = 0;
      this->creneaux_depuis_rearmement_ = 0;
    } else if (++this->creneaux_depuis_rearmement_ >= 2) {
      this->creneaux_depuis_rearmement_ = 0;
      if (this->essais_rearmement_ < 3) {
        this->essais_rearmement_++;
        this->rearmements_surdite_++;
        ESP_LOGW(TAG, "ré-armement sans effet (captures creuses) : essai %u sur 3",
                 (unsigned) this->essais_rearmement_);
        if (this->radio_ != nullptr) {
          this->radio_->reset();
        }
      } else {
        ESP_LOGW(TAG, "ré-armement : 3 essais sans capture saine, on rend la main au critère lent");
        this->essais_rearmement_ = 0;
      }
    }
    return;   // one outstanding attempt at a time: no doubling with the slow criterion
  }

  if (this->captures_creuses_ >= 2) {
    this->captures_creuses_ = 0;
    this->essais_rearmement_ = 1;
    this->creneaux_depuis_rearmement_ = 0;
    this->rearmements_surdite_++;
    ESP_LOGW(TAG, "captures creuses (%u impulsions < seuil %u) : ré-armement radio n°%u",
             (unsigned) this->last_pulse_count_, (unsigned) this->seuil_impulsions_,
             (unsigned) this->rearmements_surdite_);
    if (this->radio_ != nullptr) {
      this->radio_->reset();
    }
    return;
  }

  // 4. The slow criterion (a whole silent slot, gated on the chip delivering nothing).

  const uint32_t pas = this->creneaux_avant_rearmement_ > 0 ? this->creneaux_avant_rearmement_ : 1u;
  if (this->creneaux_muets_ >= pas && (this->creneaux_muets_ % pas) == 0u) {
    // GATED (05/10/2026): no decoded frame for a whole slot while the chip still delivers 70-182
    // pulses is the DECODER's problem (duty asymmetry against the period estimate), not the radio's.
    // Re-arming there re-initialises a working chip and can cost two minutes of reception, measured.
    // When the chip is deaf, the fast criterion above has already taken the case.
    if (capture_saine) {
      ESP_LOGD(TAG, "aucune trame depuis %u s mais la puce délivre (%u impulsions) : pas de "
                    "ré-armement (problème de décodage, pas de radio)",
               (unsigned) muettes_s, (unsigned) this->last_pulse_count_);
      return;
    }
    this->rearmements_++;
    ESP_LOGW(TAG, "aucune trame depuis %u s — ré-armement radio %u (un tous les %u créneaux)",
             (unsigned) muettes_s, (unsigned) this->rearmements_, (unsigned) pas);
    if (this->radio_ != nullptr) {
      this->radio_->reset();
    }
  }
}

}  // namespace vevor_7in1
}  // namespace esphome
