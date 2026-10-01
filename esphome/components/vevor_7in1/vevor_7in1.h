#pragma once
// Extracteur de trames Vevor 7-en-1 depuis le flux démodulé du CC1101.
//
// Pourquoi ce composant : le mode « packet » du CC1101 n'a jamais produit une seule trame
// cohérente sur ce montage (voir state/PROGRESS.md). La voie qui fonctionne est la voie
// ASYNCHRONE : le composant `cc1101` d'ESPHome bascule la puce en mode série asynchrone dès que
// `packet_mode` est absent (PKT_FORMAT = 3) et sort le signal démodulé sur GDO0 ;
// `remote_receiver` le transforme en durées d'impulsions, que nous convertissons en bits puis en
// trames.
//
// Ce fichier ne contient AUCUNE logique de protocole : la conversion impulsions → octets est
// dans `includes/vevor_protocol.h` (C++ pur, testable à froid), et la validation (en-tête,
// checksum, compteur) y est aussi. Ici : brancher le récepteur, recolller les morceaux de
// rafale, compter, déclencher.
//
// ⚠️ RÈGLE DURE, MESURÉE (01/10/2026) — NE PAS INSTRUMENTER LA PUCE DEPUIS CE FIRMWARE
// Ce composant a longtemps déclaré un SECOND périphérique SPI sur le bus du `cc1101`, pour lire
// ses registres de diagnostic (RSSI, MARCSTATE…). Résultat mesuré, en alternance avec un
// firmware de référence sur la même carte dans les mêmes fenêtres d'émission : **0 capture RMT
// et 0 trame avec ce second périphérique, 5 trames/60 s sans lui**. Un second périphérique SPI
// sur le bus suffit donc à rendre la puce muette, même avec une broche CS libre et non câblée.
// L'instrumentation a été SUPPRIMÉE (pas désactivée) : elle rendait la réception impossible et,
// comme `SPIDelegate::is_ready()` renvoie `true` sans condition, elle publiait en plus des
// valeurs fabriquées. La puce doit rester le seul périphérique de son bus.

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include "esphome/core/component.h"
#include "esphome/core/hal.h"
#include "esphome/core/log.h"
#include "esphome/components/remote_base/remote_base.h"
#include "esphome/components/remote_receiver/remote_receiver.h"
#include "esphome/components/text_sensor/text_sensor.h"

// La chaîne impulsions → trame vit dans l'en-tête `includes/` du projet, pour être testable
// hors matériel (tools/run_tests.sh). ESPHome le copie dans src/.
#include "vevor_protocol.h"

namespace esphome {
namespace vevor_7in1 {

static const char *const TAG = "vevor_7in1";

// Fenêtre de déduplication : la même rafale peut être livrée deux fois par le RMT (le tampon
// matériel du C3 fait 96 symboles et le pilote redistribue des morceaux). Deux trames
// identiques OCTET POUR OCTET à moins de 5 s d'écart sont donc un doublon de livraison, pas
// une nouvelle mesure — au-delà, on republie (une station qui répéterait la même trame plus
// tard mérite d'être vue).
static const uint32_t DUP_WINDOW_MS = 5000;

// Battement de cœur. Sans lui, « aucune trame » ne dit pas si la puce n'émet rien sur GDO0 ou
// si c'est nous qui ne comprenons rien — deux diagnostics opposés, et une perte de temps.
static const uint32_t HEARTBEAT_MS = 5000;

class Vevor7in1 : public Component, public remote_base::RemoteReceiverDumperBase {
 public:
  void set_receiver(remote_receiver::RemoteReceiverComponent *r) { this->receiver_ = r; }
  void set_bit_period(uint32_t us) { this->bit_period_us_ = us; }

  void setup() override {
    if (this->receiver_ == nullptr) {
      ESP_LOGE(TAG, "aucun remote_receiver associé : le composant ne peut rien recevoir");
      this->mark_failed();
      return;
    }
    this->receiver_->register_dumper(this);
    this->bits_.resize(vevor::MAX_BITS);
    ESP_LOGI(TAG, "enregistré comme dumper PRIMAIRE (période bit nominale %u us, %u périodes "
                  "essayées, deux polarités testées à chaque capture)",
             (unsigned) this->bit_period_us_, (unsigned) vevor::PERIOD_CANDIDATE_COUNT);
  }

  void loop() override;

  void dump_config() override {
    ESP_LOGCONFIG(TAG, "Extracteur de trames Vevor 7-en-1 :");
    ESP_LOGCONFIG(TAG, "  période bit nominale : %u us", (unsigned) this->bit_period_us_);
    ESP_LOGCONFIG(TAG, "  périodes essayées : %u (de %d à %d us)",
                  (unsigned) vevor::PERIOD_CANDIDATE_COUNT,
                  (int) vevor::PERIOD_CANDIDATES[vevor::PERIOD_CANDIDATE_COUNT - 1],
                  (int) vevor::PERIOD_CANDIDATES[0]);
    ESP_LOGCONFIG(TAG, "  polarité : les deux essayées à chaque capture");
    ESP_LOGCONFIG(TAG, "  recollage : uniquement si la capture est un MORCEAU de rafale "
                       "(< %d impulsions)", (int) vevor::MAX_FRAGMENT_TIMINGS);
    ESP_LOGCONFIG(TAG, "  captures reçues : %u, trames extraites : %u, candidats rejetés : %u, "
                       "doublons ignorés : %u",
                  (unsigned) this->captures_, (unsigned) this->frames_,
                  (unsigned) this->rejected_, (unsigned) this->duplicates_);
  }

  // PRIMAIRE volontairement : dans `remote_base`, les dumpers secondaires ne sont appelés que
  // si AUCUN dumper primaire n'a « réussi » (cf. RemoteReceiverBase::call_dumpers_). En
  // secondaire, notre extracteur pouvait donc ne jamais tourner selon la configuration ; en
  // primaire il est appelé à chaque capture, sans condition.
  bool is_secondary() override { return false; }
  bool dump(remote_base::RemoteReceiveData src) override;

  // Déclenche la journalisation des impulsions de la PROCHAINE capture (les 64 premières
  // durées). Indispensable pour analyser le flux réel depuis l'extérieur : l'API ne livre que
  // des logs, et les captures #1 à #3 sont déjà passées quand l'API devient joignable.
  void request_raw_dump() { this->dump_requested_ = true; }
  // Re-journalise la configuration effective du `remote_receiver` (filtre, idle, symboles RMT,
  // tolérance) et son état, une fois l'API joignable. Sans ça, on ne peut pas vérifier depuis
  // l'extérieur ce que le RMT a réellement en main : son `dump_config()` part au démarrage,
  // AVANT que l'API accepte une connexion.
  void dump_receiver_config_();

  Trigger<std::vector<uint8_t>> *get_frame_trigger() { return &this->frame_trigger_; }
  uint32_t get_frames() const { return this->frames_; }
  uint32_t get_captures() const { return this->captures_; }
  uint32_t get_duplicates() const { return this->duplicates_; }
  // Candidats vus dans le flux (mot de synchronisation trouvé) mais REFUSÉS par la validation :
  // checksum, compteur, en-tête. C'est le vrai compteur de bruit du décodage — distinct de
  // « aucune capture », qui veut dire que rien n'arrive à la puce.
  uint32_t get_rejected() const { return this->rejected_; }

 protected:
  // Recolle la fin de la capture précédente au début de la courante, et fusionne les deux
  // impulsions de même signe à la soudure (une coupure au milieu d'une impulsion donne deux
  // demi-impulsions de même signe : c'est l'« extra = −180 us » que le firmware de référence
  // journalise). Renvoie la longueur utilisable.
  size_t build_stitched_(const std::vector<int32_t> &timings);

  remote_receiver::RemoteReceiverComponent *receiver_{nullptr};
  Trigger<std::vector<uint8_t>> frame_trigger_;
  uint32_t bit_period_us_{90};
  uint32_t frames_{0};
  uint32_t captures_{0};
  uint32_t rejected_{0};
  uint32_t duplicates_{0};
  // Suivi pour le battement de cœur (voir loop()).
  uint32_t last_report_ms_{0};
  uint32_t reported_captures_{0};
  size_t last_pulse_count_{0};
  size_t longest_capture_{0};
  // Déduplication des livraisons en double (voir DUP_WINDOW_MS).
  uint8_t last_frame_[vevor::FRAME_BYTES]{};
  uint32_t last_frame_ms_{0};
  bool has_last_frame_{false};
  // Vrai = journaliser les impulsions de la prochaine capture (voir request_raw_dump()).
  bool dump_requested_{false};
  // Vrai = la configuration du récepteur a déjà été re-journalisée (voir dump_receiver_config_).
  bool receiver_dumped_{false};
  uint32_t heartbeats_{0};
  // Dernière capture reçue : mémorisée SEULEMENT si c'était un morceau (voir dump()), pour ne
  // recoller qu'un morceau à un morceau.
  std::vector<int32_t> prev_fragment_;
  std::vector<int32_t> stitched_;
  // Tampon de travail de la conversion durées → bits (réutilisé à chaque capture).
  std::vector<uint8_t> bits_;
};

}  // namespace vevor_7in1
}  // namespace esphome
