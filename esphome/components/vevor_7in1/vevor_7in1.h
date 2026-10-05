#pragma once
// Vevor 7-in-1 frame extractor from the CC1101 demodulated stream.
//
// The packet mode never produced a coherent frame here; the working path is ASYNCHRONOUS. With
// `packet_mode` absent the `cc1101` component uses async serial mode (PKT_FORMAT = 3), outputs the
// demodulated signal on GDO0, and `remote_receiver` turns it into pulse durations (bits -> frames).
//
// This file holds NO protocol logic: pulses -> bytes live in `vevor_protocol.h` (pure C++, testable
// off-hardware) with validation (header, checksum, counter). Here: wire the receiver, stitch burst
// fragments, count, trigger.
//
// HARD RULE — NEVER INSTRUMENT THE CHIP FROM THIS FIRMWARE
//
// A second SPI device on the `cc1101` bus makes the chip mute: 0 RMT captures and 0 frames with it,
// 5 frames/60 s without it. Removed, not disabled (dev/docs/firmware-design-notes.md §4) — the chip
// must stay the only device on its bus.

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include "esphome/core/component.h"
#include "esphome/core/hal.h"
#include "esphome/core/log.h"
#include "esphome/core/application.h"
#include "esphome/core/preferences.h"
#include "esphome/components/cc1101/cc1101.h"
#include "esphome/components/remote_base/remote_base.h"
#include "esphome/components/remote_receiver/remote_receiver.h"

// The pulses -> frame chain lives next to this file (`vevor_protocol.h`): ESPHome copies the WHOLE
// component folder into the build and a quoted include first searches the including file's folder,
// so no `-I` or `esphome: includes:` is needed and the component stays self-contained:
//
//   external_components:
//     - source: github://WizardPC/esphome-vevor-7-in-1@main
//       components: [vevor_7in1, cc1101]
//
// Testable off-hardware: tools/run_tests.sh.
#include "vevor_protocol.h"

namespace esphome {
namespace vevor_7in1 {

static const char *const TAG = "vevor_7in1";

// Dedup window: the RMT can deliver the same burst twice (the C3 hardware buffer holds 96 symbols
// and the driver re-splits chunks). Two frames identical BYTE FOR BYTE within 5 s are a duplicate
// delivery, not a new measurement; beyond 5 s we republish.
static const uint32_t DUP_WINDOW_MS = 5000;

// Heartbeat. Without it, "no frame" cannot say whether the chip emits nothing on GDO0 or whether we
// fail to understand it — two opposite diagnoses.
static const uint32_t HEARTBEAT_MS = 5000;

class Vevor7in1 : public Component, public remote_base::RemoteReceiverDumperBase {
 public:
  void set_receiver(remote_receiver::RemoteReceiverComponent *r) { this->receiver_ = r; }
  // The radio, so the watchdog can re-arm it (a full reset, see design notes §8). Declared here,
  // never driven from the YAML: the policy is code.
  void set_radio(cc1101::CC1101Component *r) { this->radio_ = r; }

  // Reception watchdog settings, changeable from Home Assistant (the `number` entities of the
  // number/ sub-platform). The component owns them; the YAML only names and bounds them.
  float get_parametre(uint8_t p) const;
  void set_parametre(uint8_t p, float valeur);
  // Put the station filter back in learning mode: the station's ID changes at every battery change,
  // so re-learning must never require a reflash.
  void reapprendre_station_id();
  // Initial pin, straight from the YAML (0 = learn). 2 is PARAM_STATION_ID in the .cpp, and the
  // same identifier the number platform uses — the mapping lives in number/__init__.py.
  void set_station_id(uint16_t id) { this->set_parametre(2, static_cast<float>(id)); }

  // On-demand re-arm (the "Re-apply radio config" button): EXACTLY the same gesture as the
  // watchdog, so the two cannot drift apart. It also clears the silence counter: a manual re-arm
  // gives the radio its full delay back.
  void reapply_radio() {
    this->creneaux_muets_ = 0;
    this->rearmements_ = 0;
    if (this->radio_ != nullptr) {
      ESP_LOGW(TAG, "ré-armement radio demandé depuis Home Assistant");
      this->radio_->reset();
    }
  }

  void setup() override {
    if (this->receiver_ == nullptr) {
      ESP_LOGE(TAG, "aucun remote_receiver associé : le composant ne peut rien recevoir");
      this->mark_failed();
      return;
    }
    this->receiver_->register_dumper(this);
    this->bits_.resize(vevor::MAX_BITS);
    // Reception watchdog: the policy lives here (see surveiller_radio_()), never in the YAML.
    // The 20 s slot is the station's transmission period.
    this->pref_reboots_ = global_preferences->make_preference<uint32_t>(0x7A1B5747u, true);
    this->pref_reboots_.load(&this->reboots_veille_);
    this->set_interval("veille", 20000, [this]() { this->surveiller_radio_(); });
    // The bit period is no longer assumed: it is MEASURED on each burst (estimer_periode_x10), so
    // the decoder is independent of station and board. PERIOD_CANDIDATES is only a fallback if the
    // estimate is refused.
    ESP_LOGI(TAG,
             "enregistré comme dumper PRIMAIRE (période bit MESURÉE sur la rafale ; repli : %u "
             "valeurs de %d à %d us ; deux polarités testées à chaque capture)",
             (unsigned) vevor::PERIOD_CANDIDATE_COUNT,
             (int) vevor::PERIOD_CANDIDATES[vevor::PERIOD_CANDIDATE_COUNT - 1],
             (int) vevor::PERIOD_CANDIDATES[0]);
  }

  void loop() override;

  void dump_config() override {
    ESP_LOGCONFIG(TAG, "Extracteur de trames Vevor 7-en-1 :");
    ESP_LOGCONFIG(TAG, "  période bit : MESURÉE sur chaque rafale (repli : %u valeurs de %d à %d us)",
                  (unsigned) vevor::PERIOD_CANDIDATE_COUNT,
                  (int) vevor::PERIOD_CANDIDATES[vevor::PERIOD_CANDIDATE_COUNT - 1],
                  (int) vevor::PERIOD_CANDIDATES[0]);
    ESP_LOGCONFIG(TAG, "  polarité : les deux essayées à chaque capture");
    ESP_LOGCONFIG(TAG, "  réparations bornées : 1 bit d'en-tête, puis 1 bit inséré dans la charge "
                       "(validées par somme + compteur + porte de plausibilité)");
    ESP_LOGCONFIG(TAG, "  recollage : uniquement si la capture est un MORCEAU de rafale "
                       "(< %d impulsions)", (int) vevor::MAX_FRAGMENT_TIMINGS);
    ESP_LOGCONFIG(TAG, "  captures reçues : %u, trames extraites : %u, candidats rejetés : %u, "
                       "doublons ignorés : %u, trames réparées : %u (dont %u refusées par le "
                       "garde-fou de continuité)",
                  (unsigned) this->captures_, (unsigned) this->frames_,
                  (unsigned) this->rejected_, (unsigned) this->duplicates_,
                  (unsigned) this->repairs_, (unsigned) this->repairs_rejetees_);
  }

  // Deliberately PRIMARY: in `remote_base`, secondary dumpers are called only if NO primary dumper
  // "succeeded" (RemoteReceiverBase::call_dumpers_), so as a secondary our extractor could never
  // run depending on config; as primary it is called on every capture, unconditionally.
  bool is_secondary() override { return false; }
  bool dump(remote_base::RemoteReceiveData src) override;

  // Triggers logging of the pulses of the NEXT capture (its first 64 durations), 24 captures in a
  // row. Essential to analyse the real flow from outside: the API only delivers logs, and captures
  // #1-#3 are already past when the API becomes reachable.
  void request_raw_dump() {
    this->dump_requested_ = true;
    this->dump_restants_ = 24;
  }
  // Re-logs the effective `remote_receiver` configuration (filter, idle, RMT symbols, tolerance),
  // once the API is reachable: we cannot verify from outside what the RMT really holds, since its
  // `dump_config()` runs at boot, BEFORE the API accepts a connection.
  void dump_receiver_config_();

  Trigger<std::vector<uint8_t>> *get_frame_trigger() { return &this->frame_trigger_; }
  uint32_t get_frames() const { return this->frames_; }
  uint32_t get_captures() const { return this->captures_; }
  uint32_t get_duplicates() const { return this->duplicates_; }
  // Candidates seen in the stream (sync word found) but REFUSED by validation: checksum, counter,
  // header. The real decoding-noise counter — distinct from "no capture", which means nothing
  // reaches the chip.
  uint32_t get_rejected() const { return this->rejected_; }
  // Frames emitted after a bounded REPAIR (see vevor_protocol.h). Separate counter: a repaired
  // frame is not worth a directly decoded one, and this number must be visible.
  uint32_t get_repairs() const { return this->repairs_; }
  uint32_t get_repairs_rejetees() const { return this->repairs_rejetees_; }
  // Frames refused by the RAIN continuity check (physically impossible rise): the counter to watch
  // for recurrence of the reception fault.
  uint32_t get_rain_rejected() const { return this->rain_rejected_; }
  // Re-arms triggered by the FAST criterion (captures too short to hold anything), as opposed to
  // those triggered by a whole silent slot: telling them apart is what makes the fix measurable.
  uint32_t get_rearmements_surdite() const { return this->rearmements_surdite_; }

 protected:
  // Stitches the end of the previous capture to the start of the current one, merging the two
  // same-sign pulses at the seam (a cut in the middle of a pulse gives two half-pulses of the same
  // sign: the "extra = -180 us" the reference firmware logs). Returns the usable length.
  size_t build_stitched_(const std::vector<int32_t> &timings);

  remote_receiver::RemoteReceiverComponent *receiver_{nullptr};
  Trigger<std::vector<uint8_t>> frame_trigger_;
  // No bit-period setting here on purpose: the period is MEASURED on every burst
  // (estimer_periode_x10 in vevor_protocol.h), so a configured constant would be a knob nothing
  // reads — and the value actually used is already logged for every frame.
  uint32_t frames_{0};
  uint32_t captures_{0};
  uint32_t rejected_{0};
  uint32_t duplicates_{0};
  // Frames emitted after a bounded repair, and those the continuity guard refused (see dump()).
  // Deliberately separate: numbers of different quality.
  uint32_t repairs_{0};
  uint32_t repairs_rejetees_{0};
  // Frames refused because rain rose by a physically impossible jump (see pluie_plausible).
  // Separate counter: a reception fault, not a protocol rejection.
  uint32_t rain_rejected_{0};
  // --- Silent captures: the FAST symptom of a chip that stopped delivering --------------------
  // Measured on this hardware: a burst is 176-184 pulses, a FRAGMENT (the C3's RMT cuts a burst in
  // two) is ~70-96, and a DEAF chip delivers 2-7. The threshold therefore separates a fragment
  // (perfectly normal) from silence (nothing decodable is arriving). Counted in dump(), acted on by
  // surveiller_radio_(), which re-arms the radio AT ONCE instead of waiting for a whole 20 s slot
  // (two emissions at the station's real rate of one frame every 20 s).
  uint32_t captures_creuses_{0};
  uint32_t seuil_impulsions_{40};
  uint32_t rearmements_surdite_{0};
  // A re-arm is a coin flip on the chip's ANALOG state (VCO/PLL calibration): measured 05/10/2026,
  // five presses gave three cures, one two-minute deafness and one persistent degradation — with
  // every register read back conforming. So every re-arm is VERIFIED: `essais_rearmement_` counts
  // the outstanding attempt (0 = none), and it is cleared only by a capture carrying a full burst.
  // Bounded at three tries, then the slow criterion and the restart take over.
  uint8_t essais_rearmement_{0};
  uint32_t creneaux_depuis_rearmement_{0};
  // Tracking for the heartbeat (see loop()).
  uint32_t last_report_ms_{0};
  uint32_t reported_captures_{0};
  size_t last_pulse_count_{0};
  size_t longest_capture_{0};
  // Deduplication of double deliveries (see DUP_WINDOW_MS).
  uint8_t last_frame_[vevor::FRAME_BYTES]{};
  uint32_t last_frame_ms_{0};
  bool has_last_frame_{false};
  // True = log the pulses of the next capture (see request_raw_dump()).
  bool dump_requested_{false};
  // Number of captures left to log after the "Dump pulses" button.
  uint16_t dump_restants_{0};
  // True = the receiver configuration has already been re-logged (see dump_receiver_config_).
  bool receiver_dumped_{false};
  uint32_t heartbeats_{0};

  // --- Reception watchdog (policy in code, never in the YAML; design notes §8) ---
  // One single copy of this logic: if you change it here, that is the change.
  cc1101::CC1101Component *radio_{nullptr};
  // Silent slots before a re-arm, and total silence before a restart: the only two settings
  // exposed (`number` entities, number/ sub-platform).
  uint32_t creneaux_avant_rearmement_{3};
  uint32_t duree_max_avant_redemarrage_s_{180};
  uint32_t creneaux_muets_{0};
  uint32_t trames_veille_{0};
  uint32_t rearmements_{0};
  uint32_t reboots_veille_{0};
  ESPPreferenceObject pref_reboots_{};
  void surveiller_radio_();

  // --- Station identity filter -----------------------------------------------------------------
  // 0 = learn: the FIRST valid frame's ID is adopted, then any OTHER ID is dropped (a neighbour's
  // station on the same protocol). decoded_ and frames_ keep the two cases apart: a dropped frame
  // still proves the RECEPTION works, so the watchdog must not fight it. Settable from Home
  // Assistant (number entity) and re-learnable (button) without reflashing — the station's ID
  // changes at every battery change.
  uint16_t station_id_{0};
  uint32_t decoded_{0};          // valid frames DECODED, before the filter: the watchdog criterion
  uint32_t id_etrangere_{0};     // valid frames dropped because they are not the adopted station
  bool id_etrangere_signalee_{false};
  // Last capture received: stored ONLY if it was a fragment (see dump()), so we only stitch a
  // fragment to a fragment.
  std::vector<int32_t> prev_fragment_;
  std::vector<int32_t> stitched_;
  // Working buffer for durations -> bits conversion (reused on every capture).
  std::vector<uint8_t> bits_;
};

}  // namespace vevor_7in1
}  // namespace esphome
