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
// checksum, compteur) y est aussi. Ici : brancher le récepteur, instrumenter, déclencher.
//
// INSTRUMENTATION RADIO (itération 9) : ce composant est AUSSI un périphérique SPI du même bus
// que le `cc1101` (même broche CS), uniquement pour LIRE des registres de diagnostic
// (RSSI, MARCSTATE, PKTSTATUS, FREQ2/1/0). Le composant `cc1101` d'ESPHome n'expose pas de
// lecture de registre, et « le RSSI n'est pas publié » en mode asynchrone : sans cette lecture,
// « aucune trame » reste ambigu (pas d'énergie RF du tout ? énergie normale mais démodulation
// cassée ? brouilleur qui sature l'AGC ?). Ces lectures n'écrivent RIEN : elles ne peuvent pas
// modifier l'état de la puce.

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
#include "esphome/components/sensor/sensor.h"
#include "esphome/components/spi/spi.h"
#include "esphome/components/text_sensor/text_sensor.h"

// La chaîne impulsions → trame vit dans l'en-tête `includes/` du projet, pour être testable
// hors matériel (tools/run_tests.sh). ESPHome le copie dans src/.
#include "vevor_protocol.h"

namespace esphome {
namespace vevor_7in1 {

static const char *const TAG = "vevor_7in1";

// Adresses de registres du CC1101 utilisées pour le diagnostic. Valeurs du datasheet
// (section « Register overview »), identiques à celles du fichier `cc1101defs.h` d'ESPHome
// 2026.9.1 : FREQ2=0x0D, VERSION=0x31, RSSI=0x34, MARCSTATE=0x35, PKTSTATUS=0x38.
static const uint8_t CC1101_REG_FREQ2 = 0x0D;
static const uint8_t CC1101_REG_PARTNUM = 0x30;
static const uint8_t CC1101_REG_VERSION = 0x31;
static const uint8_t CC1101_REG_RSSI = 0x34;
static const uint8_t CC1101_REG_MARCSTATE = 0x35;
static const uint8_t CC1101_REG_PKTSTATUS = 0x38;
// Trame SPI : bit 7 = lecture, bit 6 = accès en rafale (obligatoire pour les registres d'état),
// bits 5-0 = adresse. Mêmes constantes que `BUS_READ` / `BUS_BURST` d'ESPHome.
static const uint8_t CC1101_SPI_READ = 0x80;
static const uint8_t CC1101_SPI_BURST = 0x40;
// Conversion RSSI → dBm : valeur signée sur 8 bits, pas de 0,5 dB, décalage 74 dB.
// Mêmes constantes que le composant cc1101 d'ESPHome (RSSI_OFFSET = 74,0 / RSSI_STEP = 0,5) :
// c'est ce qui rend nos lectures comparables au plancher de bruit de −106,2 dBm mesuré en mode
// packet sur cette même carte.
static const float CC1101_RSSI_OFFSET_DBM = 74.0f;
// Quartz de référence de la puce (26 MHz) : fréquence = 26 MHz × (FREQ2:FREQ1:FREQ0) / 2^16.
static const float CC1101_XTAL_MHZ = 26.0f;

// Fenêtre de déduplication : la même rafale peut être livrée deux fois par le RMT (le tampon
// matériel du C3 fait 96 symboles et le pilote redistribue des morceaux). Deux trames
// identiques OCTET POUR OCTET à moins de 5 s d'écart sont donc un doublon de livraison, pas
// une nouvelle mesure — au-delà, on republie (une station qui répéterait la même trame plus
// tard mérite d'être vue).
static const uint32_t DUP_WINDOW_MS = 5000;

// Battement de cœur. Sans lui, « aucune trame » ne dit pas si la puce n'émet rien sur GDO0 ou
// si c'est nous qui ne comprenons rien — deux diagnostics opposés, et une perte de temps.
static const uint32_t HEARTBEAT_MS = 5000;
// Fenêtre d'échantillonnage serré de la broche de sonde (voir probe_pin_burst_).
static const uint32_t PROBE_WINDOW_US = 3000;
// Période d'échantillonnage léger des registres d'état de la puce (voir loop()). Volontairement
// lâche : 6 octets de lecture SPI toutes les 10 s ne peuvent pas perturber une rafale de 160 µs.
static const uint32_t RADIO_SAMPLE_MS = 10000;

class Vevor7in1 : public Component,
                  public remote_base::RemoteReceiverDumperBase,
                  // Même bus, mêmes paramètres de trame SPI que le CC1101 (lutte contre les
                  // différences de mode) : CS géré par ESPHome, la lecture est indépendante de
                  // l'émetteur réseau.
                  public spi::SPIDevice<spi::BIT_ORDER_MSB_FIRST, spi::CLOCK_POLARITY_LOW,
                                        spi::CLOCK_PHASE_LEADING, spi::DATA_RATE_1MHZ> {
 public:
  void set_receiver(remote_receiver::RemoteReceiverComponent *r) { this->receiver_ = r; }
  void set_bit_period(uint32_t us) { this->bit_period_us_ = us; }
  // Broche à sonder directement (en pratique la même que GDO0). Elle tranche entre deux causes
  // qui produisent le même log « aucune trame » : la puce n'émet rien, ou le RMT ne capte pas.
  void set_probe_pin(InternalGPIOPin *pin) { this->probe_pin_ = pin; }
  // Entités de diagnostic alimentées par la lecture SPI (facultatives : sans elles, les valeurs
  // restent dans les logs).
  void set_rssi_sensor(sensor::Sensor *s) { this->rssi_sensor_ = s; }
  void set_radio_sensor(text_sensor::TextSensor *s) { this->radio_sensor_ = s; }
  // Entité qui conserve le dernier inventaire de registres. Elle a une valeur DÈS LE DÉMARRAGE
  // et l'API la relit à chaque connexion : c'est ce qui rend la mesure exploitable sans courir
  // après une ligne de log qui part avant que l'API soit joignable.
  void set_inventory_sensor(text_sensor::TextSensor *s) { this->inventory_sensor_ = s; }

  void setup() override {
    if (this->receiver_ == nullptr) {
      ESP_LOGE(TAG, "aucun remote_receiver associé : le composant ne peut rien recevoir");
      this->mark_failed();
      return;
    }
    this->receiver_->register_dumper(this);
    if (this->probe_pin_ != nullptr) {
      this->probe_pin_->setup();
    }
    // Bus SPI partagé avec le CC1101 : on s'enregistre comme second périphérique (le bus est
    // sérialisé par ESPHome, donc nos lectures ne peuvent pas s'intercaler dans une transaction
    // du composant cc1101).
    this->spi_setup();
    ESP_LOGI(TAG,
             "enregistré comme dumper PRIMAIRE (période bit nominale %u us, %u périodes essayées, "
             "sonde %s, lecture registres SPI %s)",
             (unsigned) this->bit_period_us_, (unsigned) vevor::PERIOD_CANDIDATE_COUNT,
             this->probe_pin_ != nullptr ? "active" : "absente",
             this->spi_is_ready() ? "prête" : "indisponible");
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
    ESP_LOGCONFIG(TAG, "  sonde de broche : %s", YESNO(this->probe_pin_ != nullptr));
    ESP_LOGCONFIG(TAG, "  lecture registres CC1101 (RSSI/MARCSTATE/FREQ) : %s",
                  YESNO(this->spi_is_ready()));
    ESP_LOGCONFIG(TAG, "  captures reçues : %u, trames extraites : %u, doublons ignorés : %u",
                  (unsigned) this->captures_, (unsigned) this->frames_,
                  (unsigned) this->duplicates_);
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
  // Inventaire des registres de la puce : lecture ponctuelle (AUCUNE écriture), journalisée en
  // clair. Sert à voir l'état RÉEL de la configuration (débit, bande, déviation, format de
  // paquet, fonction de GDO0) au lieu de supposer que ce qui a été écrit est ce qui est actif :
  // c'est la seule façon de trancher entre « notre écriture est fausse » et « la puce rend
  // autre chose que ce qu'on lui a demandé ».
  void log_register_inventory();

  Trigger<std::vector<uint8_t>> *get_frame_trigger() { return &this->frame_trigger_; }
  uint32_t get_frames() const { return this->frames_; }
  uint32_t get_captures() const { return this->captures_; }
  uint32_t get_duplicates() const { return this->duplicates_; }
  // Dernier RSSI lu (NAN si aucune lecture n'a encore abouti).
  float get_last_rssi_dbm() const { return this->last_rssi_dbm_; }

 protected:
  // Échantillonne la broche de sonde en rafale serrée et journalise le nombre de transitions.
  void probe_pin_burst_();
  // Recolle la fin de la capture précédente au début de la courante. Ce n'est PAS un luxe :
  // mesuré chez le montage témoin le 30/09 à 22:30 locales, sur cette même carte, **une rafale
  // sur deux arrive coupée** (94 puis 70 impulsions pour une rafale de 164) — le bloc mémoire RMT
  // matériel du C3 ne tient pas une rafale entière. Sans recollage, on perd ces rafales-là, et
  // c'est précisément ce qui nous a fait passer à côté de la moitié des mesures.
  void build_stitched_(const std::vector<int32_t> &timings);
  // Lit les registres de diagnostic du CC1101 par SPI, journalise et publie (voir
  // l'instrumentation expliquée en tête de fichier). N'écrit jamais dans la puce.
  void sample_radio_();
  uint8_t read_register_(uint8_t addr);
  // Lecture d'un registre de CONFIGURATION (0x00..0x2E) : adresse seule, sans le bit de rafale
  // (0x40), qui est réservé aux registres d'état. C'est la différence avec read_register_().
  uint8_t read_config_register_(uint8_t addr);
  void read_registers_(uint8_t addr, uint8_t *buffer, size_t length);

  remote_receiver::RemoteReceiverComponent *receiver_{nullptr};
  InternalGPIOPin *probe_pin_{nullptr};
  Trigger<std::vector<uint8_t>> frame_trigger_;
  uint32_t bit_period_us_{90};
  uint32_t frames_{0};
  uint32_t captures_{0};
  // Suivi pour le battement de cœur (voir loop()).
  uint32_t last_report_ms_{0};
  // Dernier échantillonnage léger des registres radio (voir loop()).
  uint32_t last_radio_sample_ms_{0};
  uint32_t reported_captures_{0};
  size_t last_pulse_count_{0};
  size_t longest_capture_{0};
  // Résultat de la dernière sonde de broche (voir probe_pin_burst_) : il conditionne le message
  // du battement de cœur (« rien depuis 5 s » n'a pas le même sens selon que la broche bouge).
  int probe_transitions_{0};
  // Déduplication des livraisons en double (voir DUP_WINDOW_MS).
  uint8_t last_frame_[vevor::FRAME_BYTES]{};
  uint32_t last_frame_ms_{0};
  bool has_last_frame_{false};
  uint32_t duplicates_{0};
  // Vrai = journaliser les impulsions de la prochaine capture (voir request_raw_dump()).
  bool dump_requested_{false};
  // Vrai = la configuration du récepteur a déjà été re-journalisée (voir dump_receiver_config_).
  bool receiver_dumped_{false};
  uint32_t heartbeats_{0};
  // Recollage inter-captures (voir build_stitched_).
  std::vector<int32_t> tail_;
  std::vector<int32_t> stitched_;
  // Tampon de travail de la conversion durées → bits (réutilisé à chaque capture).
  std::vector<uint8_t> bits_;
  // Instrumentation radio (voir sample_radio_).
  sensor::Sensor *rssi_sensor_{nullptr};
  text_sensor::TextSensor *radio_sensor_{nullptr};
  text_sensor::TextSensor *inventory_sensor_{nullptr};
  float last_rssi_dbm_{NAN};
  // Statistiques cumulées depuis le boot : une valeur isolée de RSSI ne veut rien dire sur un
  // signal qui n'arrive que par rafales de 20 s ; c'est le plancher qui est comparable à la
  // mesure de référence.
  uint32_t rssi_samples_{0};
  float rssi_sum_{0.0f};
  float rssi_min_{NAN};
  float rssi_max_{NAN};
};

}  // namespace vevor_7in1
}  // namespace esphome
