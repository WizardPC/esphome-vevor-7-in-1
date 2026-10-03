#include "vevor_7in1.h"

// Ce fichier ne contient QUE le branchement au récepteur, le recollage des rafales coupées, la
// déduplication des livraisons en double et le battement de cœur. Toute la logique de protocole
// (impulsions → bits → octets → valeurs) est dans includes/vevor_protocol.h, testable hors
// matériel. Voir l'avertissement en tête de vevor_7in1.h : ce composant n'a AUCUN accès SPI, la
// puce CC1101 doit rester le seul périphérique de son bus.

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
  // Garde-fou : si setup() n'a pas trouvé de remote_receiver — ou a marqué le composant en échec —
  // `receiver_` est nul et le battement de cœur (dump_receiver_config_) le déréférencerait. setup()
  // le teste déjà ; loop() doit le tester aussi (revue round 1, S5 — non corrigé jusqu'ici).
  if (this->receiver_ == nullptr || this->is_failed()) {
    return;
  }
  const uint32_t now = millis();
  if (now - this->last_report_ms_ < HEARTBEAT_MS) {
    return;
  }
  this->last_report_ms_ = now;

  if (!this->receiver_dumped_ || (this->heartbeats_ % 12u) == 0u) {
    // Une fois au démarrage, puis toutes les minutes : le premier dump part AVANT que l'API soit
    // joignable, donc une fois ne suffit pas pour le lire depuis l'extérieur.
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

  ESP_LOGI(TAG, "captures=%u (+%u), trames=%u, rejets=%u, dernières impulsions=%u, plus longue=%u",
           (unsigned) this->captures_, (unsigned) (this->captures_ - this->reported_captures_),
           (unsigned) this->frames_, (unsigned) this->rejected_,
           (unsigned) this->last_pulse_count_, (unsigned) this->longest_capture_);
  this->reported_captures_ = this->captures_;
}

size_t Vevor7in1::build_stitched_(const std::vector<int32_t> &timings) {
  // La logique vit dans includes/vevor_protocol.h (stitch_fragments) pour être testable hors
  // matériel : ici on ne fait que lui donner un tampon réutilisable.
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
  if (timings.size() > this->longest_capture_) {
    this->longest_capture_ = timings.size();
  }

  // Les premières captures sont détaillées, et toute capture demandée à la main l'est aussi
  // (bouton « Dump impulsions ») : les durées en clair sont la SEULE façon d'analyser la rafale
  // réelle hors de la carte, l'API ne livrant que des logs.
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

    // MODIFICATION LOCALE (02/10) — 64 durées ne couvrent PAS une rafale Vevor (~176 symboles) :
    // le dump ne permettait donc pas de juger le flux, il s'arrêtait au premier tiers de la rafale.
    // On journalise jusqu'à 512 durées, par tranches de 64 — une ligne unique de plusieurs kilo-octets
    // risquerait d'être tronquée par la couche de journalisation de l'API.
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

  // Une capture est un MORCEAU de rafale si elle est trop courte pour en porter une entière :
  // mesuré sur ce montage, une rafale utile fait 176 à 184 impulsions, et le RMT du C3 la coupe
  // parfois en deux (96 + 82, 94 + 70…). C'est la seule situation où recoller a un sens. Le
  // prédicat vit dans includes/vevor_protocol.h (testable hors matériel) ; le test l'éprouve aux
  // bornes dans test_fragment_policy().
  const bool fragment = vevor::is_fragment(timings.size());

  uint8_t raw[vevor::FRAME_BYTES];
  int32_t period_used = 0;
  bool inverted = false;
  bool repaired = false;
  size_t rejected = 0;

  // 1. DÉCODAGE DIRECT de la capture, sans rien recoller : c'est le cas normal.
  bool ok = vevor::decode_timings(timings.data(), timings.size(), vevor::PERIOD_CANDIDATES,
                                  vevor::PERIOD_CANDIDATE_COUNT, this->bits_.data(),
                                  this->bits_.size(), raw, &period_used, &inverted, &rejected,
                                  &repaired);
  this->rejected_ += rejected;

  bool from_stitch = false;
  if (!ok && fragment && !this->prev_fragment_.empty()) {
    // 2. RECOLLAGE, uniquement entre deux morceaux de rafale. Recoler une capture COMPLÈTE devant
    //    la suivante fait relire la rafale PRÉCÉDENTE : mesuré le 01/10, la version précédente
    //    publiait ainsi 60 trames pour 31 mesures distinctes (chaque compteur TX exactement deux
    //    fois, à 20 s d'écart, donc hors de la fenêtre anti-doublon de 5 s).
    const size_t stitched = this->build_stitched_(timings);
    rejected = 0;
    ok = vevor::decode_timings(this->stitched_.data(), stitched, vevor::PERIOD_CANDIDATES,
                               vevor::PERIOD_CANDIDATE_COUNT, this->bits_.data(),
                               this->bits_.size(), raw, &period_used, &inverted, &rejected,
                               &repaired);
    this->rejected_ += rejected;
    from_stitch = ok;
  }

  // Mémoriser la capture courante comme morceau possible de la suivante — SEULEMENT si c'en est
  // un : une rafale complète ne doit jamais servir de préfixe à la suivante.
  this->prev_fragment_ = fragment ? timings : std::vector<int32_t>();

  if (!ok) {
    return false;
  }

  // GARDE-FOU DE CONTINUITÉ, pour les trames RÉPARÉES seulement : une trame obtenue par réparation
  // n'est publiée que si elle est cohérente avec la dernière trame acceptée (même station, mesures
  // qui ne sautent pas d'une rafale à l'autre). Mesure du 03/10 sur 200 charges utiles aléatoires :
  // aucune fabrication — c'est donc une précaution à coût nul, gardée pour fermer le risque
  // résiduel des réparations. Une trame décodée directement n'est pas soumise à ce contrôle.
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

  // La même rafale est régulièrement livrée deux fois par le RMT : deux trames identiques octet
  // pour octet à quelques dizaines de millisecondes d'écart sont les mêmes mesures relues deux
  // fois. On ne déclenche que la première.
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

  this->frames_++;
  // La période est en DIXIÈMES de microseconde (elle est mesurée sur la rafale) : on journalise la
  // valeur réellement retenue, pas un entier trompeur.
  ESP_LOGD(TAG, "trame extraite (période mesurée %d.%d us, polarité %s, %s%s) → %u octets",
           (int) (period_used / 10), (int) (period_used % 10), inverted ? "inversée" : "normale",
           from_stitch ? "en deux morceaux recollés" : "d'un seul bloc",
           repaired ? ", RÉPARÉE" : "", (unsigned) vevor::FRAME_BYTES);

  // La trame est remise AU YAML, qui publie les capteurs : le composant ne connaît pas les
  // entités, et la logique de protocole reste testable à froid dans includes/vevor_protocol.h.
  std::vector<uint8_t> payload(raw, raw + vevor::FRAME_BYTES);
  this->frame_trigger_.trigger(payload);
  return true;
}

}  // namespace vevor_7in1
}  // namespace esphome
