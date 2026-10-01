#include "vevor_7in1.h"

namespace esphome {
namespace vevor_7in1 {

// Noms des états MARCSTATE du CC1101. L'ordre suit le champ MARCSTATE du datasheet, tel que
// repris par l'énumération `State` du composant cc1101 d'ESPHome 2026.9.1 (cc1101defs.h) :
// 0x0D = RX, 0x01 = IDLE, etc. Les valeurs non documentées sont marquées « ? » plutôt que
// devinées.
static const char *marcstate_name(uint8_t s) {
  switch (s) {
    case 0x00:
      return "SLEEP";
    case 0x01:
      return "IDLE";
    case 0x02:
      return "XOFF";
    case 0x03:
      return "VCOON_MC";
    case 0x04:
      return "REGON_MC";
    case 0x05:
      return "MANCAL";
    case 0x06:
      return "VCOON";
    case 0x07:
      return "REGON";
    case 0x08:
      return "STARTCAL";
    case 0x09:
      return "BWBOOST";
    case 0x0A:
      return "FS_LOCK";
    case 0x0B:
      return "IFADCON";
    case 0x0C:
      return "ENDCAL";
    case 0x0D:
      return "RX";
    case 0x0E:
      return "RX_END";
    case 0x0F:
      return "RX_RST";
    case 0x10:
      return "TXRX_SWITCH";
    case 0x11:
      return "RXFIFO_OVERFLOW";
    case 0x12:
      return "FSTXON";
    case 0x13:
      return "TX";
    case 0x14:
      return "TX_END";
    case 0x15:
      return "RXTX_SWITCH";
    default:
      return "?";
  }
}

void Vevor7in1::probe_pin_burst_() {
  // Échantillonnage serré de la broche : on compte ses transitions sur une fenêtre courte.
  //   0 transition -> la broche est statique : c'est la puce qui n'émet rien.
  //   >0          -> la broche bouge : c'est donc la chaîne de capture (RMT) qui est en cause.
  // Sans cette mesure, les deux causes donnent le MÊME log (« aucune trame »), et on corrige à
  // l'aveugle.
  const bool start_level = this->probe_pin_->digital_read();
  int transitions = 0;
  bool level = start_level;
  const uint32_t deadline = micros() + PROBE_WINDOW_US;
  while (micros() < deadline) {
    const bool now = this->probe_pin_->digital_read();
    if (now != level) {
      transitions++;
      level = now;
    }
  }
  ESP_LOGI(TAG, "sonde GDO0 : %d transition(s) en %u us — niveau %s, captures RMT=%u", transitions,
           (unsigned) PROBE_WINDOW_US, start_level ? "haut" : "bas", (unsigned) this->captures_);
  this->probe_transitions_ = transitions;
}

uint8_t Vevor7in1::read_register_(uint8_t addr) {
  // Lecture d'un registre d'état : un octet, adresse en rafale (0xC0 | adresse). L'octet de
  // statut renvoyé pendant l'adresse n'est pas récupéré — seules les valeurs nous intéressent.
  this->enable();
  this->write_byte(addr | CC1101_SPI_READ | CC1101_SPI_BURST);
  const uint8_t value = this->transfer_byte(0);
  this->disable();
  return value;
}

void Vevor7in1::read_registers_(uint8_t addr, uint8_t *buffer, size_t length) {
  this->enable();
  this->write_byte(addr | CC1101_SPI_READ | CC1101_SPI_BURST);
  for (size_t i = 0; i < length; i++) {
    buffer[i] = this->transfer_byte(0);
  }
  this->disable();
}

uint8_t Vevor7in1::read_config_register_(uint8_t addr) {
  this->enable();
  this->write_byte(addr | CC1101_SPI_READ);
  const uint8_t value = this->transfer_byte(0);
  this->disable();
  return value;
}

void Vevor7in1::log_register_inventory() {
  // Une seule prise de vue, aucune écriture. Deux usages : (1) savoir si la puce répond encore
  // (PARTNUM/VERSION), (2) voir la configuration RÉELLEMENT active — et non celle qu'on croit
  // avoir écrite. C'est ce qui tranche entre « notre séquence d'écriture est fautive » et « la
  // puce reçoit autre chose » (le débit notamment : nos impulsions sont quantifiées à 11,25 us,
  // soit 1/8 de période bit, signature d'un démodulateur 8x trop rapide).
  if (!this->spi_is_ready()) {
    ESP_LOGW(TAG, "INVENTAIRE impossible : aucun peripherique SPI declare (cs_pin absent)");
    return;
  }
  const uint8_t partnum = this->read_register_(CC1101_REG_PARTNUM);
  const uint8_t version = this->read_register_(CC1101_REG_VERSION);
  const uint8_t rssi_raw = this->read_register_(CC1101_REG_RSSI);
  const uint8_t marcstate = this->read_register_(CC1101_REG_MARCSTATE);
  const uint8_t pktstatus = this->read_register_(CC1101_REG_PKTSTATUS);
  uint8_t cfg[0x2F] = {0};
  for (uint8_t a = 0; a <= 0x2E; a++) {
    cfg[a] = this->read_config_register_(a);
  }
  const uint8_t version2 = this->read_register_(CC1101_REG_VERSION);

  char line[200];
  for (uint8_t base = 0; base <= 0x24; base = (uint8_t) (base + 0x0C)) {
    const uint8_t last = (uint8_t) (base + 0x0B) > 0x2E ? 0x2E : (uint8_t) (base + 0x0B);
    size_t pos = 0;
    pos += (size_t) snprintf(line + pos, sizeof(line) - pos, "INVENTAIRE cfg 0x%02X-0x%02X :", base, last);
    for (uint8_t a = base; a <= last; a++) {
      pos += (size_t) snprintf(line + pos, sizeof(line) - pos, " %02X", cfg[a]);
    }
    ESP_LOGI(TAG, "%s", line);
  }

  const uint8_t mdmcfg4 = cfg[0x10];
  const uint8_t mdmcfg3 = cfg[0x11];
  const uint8_t mdmcfg2 = cfg[0x12];
  const uint8_t deviatn = cfg[0x15];
  const uint8_t pktctrl0 = cfg[0x08];
  const uint8_t iocfg0 = cfg[0x02];
  const uint32_t drate_e = mdmcfg4 & 0x0F;
  const float symbol_rate =
      (CC1101_XTAL_MHZ * 1000000.0f / 268435456.0f) * (256.0f + (float) mdmcfg3) * (float) (1u << drate_e);
  const uint32_t chbw_e = (mdmcfg4 >> 6) & 0x03;
  const uint32_t chbw_m = (mdmcfg4 >> 4) & 0x03;
  const float bw_hz = (CC1101_XTAL_MHZ * 1000000.0f) / (8.0f * (4.0f + (float) chbw_m) * (float) (1u << chbw_e));
  const uint32_t dev_e = (deviatn >> 4) & 0x07;
  const uint32_t dev_m = deviatn & 0x07;
  const float dev_khz = (CC1101_XTAL_MHZ / 131.072f) * (float) (8 + dev_m) * (float) (1u << dev_e);
  const uint32_t freq_word = ((uint32_t) cfg[0x0D] << 16) | ((uint32_t) cfg[0x0E] << 8) | (uint32_t) cfg[0x0F];
  const float freq_mhz = CC1101_XTAL_MHZ * (float) freq_word / 65536.0f;
  const int16_t rssi_dec = (rssi_raw >= 128) ? (int16_t) ((int) rssi_raw - 256) : (int16_t) rssi_raw;

  ESP_LOGI(TAG,
           "INVENTAIRE identite PARTNUM=0x%02X VERSION=0x%02X (relu 0x%02X, attendu 0x14) | "
           "MARCSTATE=0x%02X %s | PKTSTATUS=0x%02X | RSSI brut 0x%02X = %.1f dBm",
           partnum, version, version2, marcstate, marcstate_name(marcstate), pktstatus, rssi_raw,
           (float) rssi_dec * 0.5f - CC1101_RSSI_OFFSET_DBM);
  ESP_LOGI(TAG,
           "INVENTAIRE fonctionnel freq=%.5f MHz debit=%.0f baud (DRATE_E=%u, MDMCFG3=%u) "
           "bande=%.0f Hz deviation=%.1f kHz mod=0x%X sync=0x%X pktctrl0=0x%02X iocfg0=0x%02X",
           freq_mhz, symbol_rate, (unsigned) drate_e, mdmcfg3, bw_hz, dev_khz,
           (unsigned) ((mdmcfg2 >> 4) & 0x07), (unsigned) (mdmcfg2 & 0x07), pktctrl0, iocfg0);
  if (version != 0x14 || version2 != version) {
    ESP_LOGW(TAG, "INVENTAIRE NON FIABLE : VERSION=0x%02X/0x%02X (attendu 0x14) — bus muet ou puce "
                  "absente, les valeurs ci-dessus ne sont pas des mesures",
             version, version2);
  } else if (symbol_rate > 12222.0f || symbol_rate < 10000.0f) {
    ESP_LOGW(TAG, "INVENTAIRE ECART DEBIT : %.0f baud dans la puce pour 11111 demandes (facteur "
                  "%.2f) — la modulation n'est pas au rythme ecrit",
             symbol_rate, symbol_rate / 11111.0f);
  } else {
    ESP_LOGI(TAG, "INVENTAIRE COHERENT : debit et frequence conformes a la configuration ecrite");
  }

  // Publication en entité : la valeur survit à la fenêtre de logs (elle est relue à chaque
  // connexion à l'API), ce qui évite de devoir capturer les logs au démarrage pour l'obtenir.
  if (this->inventory_sensor_ != nullptr) {
    if (version != 0x14 || version2 != version) {
      char broken[160];
      snprintf(broken, sizeof(broken),
               "PUCE MUETTE (bus SPI) : PARTNUM=0x%02X VERSION=0x%02X relu 0x%02X (attendu 0x14) — "
               "aucune lecture n'est une mesure",
               partnum, version, version2);
      this->inventory_sensor_->publish_state(broken);
    } else {
      char summary[255];
      snprintf(summary, sizeof(summary),
               "PARTNUM=0x%02X VERSION=0x%02X | %.0f baud (DRATE_E=%u M=%u) | %.5f MHz | dev "
               "%.1f kHz | BW %.0f Hz | mod 0x%X sync 0x%X | pktctrl0=0x%02X iocfg0=0x%02X | "
               "MDMCFG4..0=%02X %02X %02X %02X %02X | DEVIATN=%02X",
               partnum, version, symbol_rate, (unsigned) drate_e, mdmcfg3, freq_mhz, dev_khz, bw_hz,
               (unsigned) ((mdmcfg2 >> 4) & 0x07), (unsigned) (mdmcfg2 & 0x07), pktctrl0, iocfg0,
               cfg[0x10], cfg[0x11], cfg[0x12], cfg[0x13], cfg[0x14], deviatn);
      this->inventory_sensor_->publish_state(summary);
    }
  }
}

void Vevor7in1::sample_radio_() {
  // Lecture SEULE de registres de diagnostic du CC1101 (aucune écriture, aucun changement
  // d'état) : c'est la seule mesure qui distingue « le signal n'arrive pas » de « le signal
  // arrive mais la démodulation ne sort rien ». Références sur cette même carte, mesurées en
  // mode packet le 30/09 : plancher de bruit −106,2 dBm, RSSI max −95,5 dBm.
  const uint8_t version = this->read_register_(CC1101_REG_VERSION);
  const uint8_t rssi_raw = this->read_register_(CC1101_REG_RSSI);
  const uint8_t marcstate = this->read_register_(CC1101_REG_MARCSTATE);
  const uint8_t pktstatus = this->read_register_(CC1101_REG_PKTSTATUS);
  uint8_t freq_regs[3] = {0, 0, 0};
  this->read_registers_(CC1101_REG_FREQ2, freq_regs, 3);
  // Registres du démodulateur (0x10..0x15 : MDMCFG4, MDMCFG3, MDMCFG2, MDMCFG1, MDMCFG0,
  // DEVIATN). C'est LA mesure décisive quand « le signal arrive mais rien ne se décode » : elle
  // dit à quel débit, dans quelle bande et avec quelle déviation la puce démodule VRAIMENT, au
  // lieu de supposer que la configuration écrite est celle qui est active.
  uint8_t demod[6] = {0, 0, 0, 0, 0, 0};
  this->read_registers_(0x10, demod, 6);
  const uint8_t mdmcfg4 = demod[0];
  const uint8_t mdmcfg3 = demod[1];
  const uint8_t mdmcfg2 = demod[2];
  const uint8_t deviatn = demod[5];
  // Formules du datasheet CC1101 (mêmes constantes que `dump_config()` du composant cc1101).
  const uint32_t drate_e = mdmcfg4 & 0x0F;
  const float symbol_rate =
      (CC1101_XTAL_MHZ * 1000000.0f / 268435456.0f) * (256.0f + (float) mdmcfg3) * (float) (1u << drate_e);
  const uint32_t chbw_e = (mdmcfg4 >> 6) & 0x03;
  const uint32_t chbw_m = (mdmcfg4 >> 4) & 0x03;
  const float bw_hz = (CC1101_XTAL_MHZ * 1000000.0f) /
                      (8.0f * (4.0f + (float) chbw_m) * (float) (1u << chbw_e));
  const uint32_t dev_e = (deviatn >> 4) & 0x07;
  const uint32_t dev_m = deviatn & 0x07;
  const float dev_khz =
      (CC1101_XTAL_MHZ / 131.072f) * (float) (8 + dev_m) * (float) (1u << dev_e);
  const uint32_t modulation = (mdmcfg2 >> 4) & 0x07;  // 0 = 2-FSK, 2 = ASK/OOK, 4 = MSK
  static const char *const MOD_NAMES[] = {"2-FSK", "GFSK", "ASK/OOK", "4-FSK", "MSK", "?", "?", "?"};

  ESP_LOGI(TAG,
           "DEMOD modulation=%s | debit=%.0f baud (DRATE_E=%u M=%u) | bande=%.0f Hz "
           "(CHANBW_E=%u M=%u) | deviation=%.1f kHz (E=%u M=%u) | MDMCFG4..0=%02X %02X %02X %02X %02X "
           "| DEVIATN=%02X",
           MOD_NAMES[modulation], symbol_rate, (unsigned) drate_e, (unsigned) mdmcfg3, bw_hz,
           (unsigned) chbw_e, (unsigned) chbw_m, dev_khz, (unsigned) dev_e, (unsigned) dev_m,
           demod[0], demod[1], demod[2], demod[3], demod[4], deviatn);
  // Le débit attendu vient de la configuration (`symbol_rate` du YAML, 11 111 bauds). Un écart de
  // plus de 10 % signifie que la puce ne démodule PAS ce qu'on croit — la cause la plus probable
  // d'un flux d'impulsions quantifié à ~11 µs (90/8) au lieu de ~90 µs.
  if (symbol_rate > 12222.0f || symbol_rate < 10000.0f) {
    ESP_LOGW(TAG,
             "DEBIT INATTENDU : %.0f baud lus dans la puce au lieu de ~11111 — la démodulation "
             "n'est pas au bon rythme (facteur %.2f)",
             symbol_rate, symbol_rate / 11111.0f);
  }

  const uint32_t freq_word =
      ((uint32_t) freq_regs[0] << 16) | ((uint32_t) freq_regs[1] << 8) | (uint32_t) freq_regs[2];
  const float freq_mhz = CC1101_XTAL_MHZ * (float) freq_word / 65536.0f;
  // RSSI : octet signé, pas de 0,5 dB, décalage 74 dB (mêmes constantes que le composant
  // cc1101 d'ESPHome → nos valeurs sont comparables à la mesure de référence).
  const int16_t rssi_dec = (rssi_raw >= 128) ? (int16_t) ((int) rssi_raw - 256) : (int16_t) rssi_raw;
  const float rssi_dbm = (float) rssi_dec * 0.5f - CC1101_RSSI_OFFSET_DBM;
  const bool carrier_sense = (pktstatus >> 6) & 0x01;  // bit 6 = CS (Carrier Sense)
  const bool sfd = (pktstatus >> 3) & 0x01;            // bit 3 = SFD/HS (préambule + syncword)

  this->last_rssi_dbm_ = rssi_dbm;
  this->rssi_samples_++;
  this->rssi_sum_ += rssi_dbm;
  if (std::isnan(this->rssi_min_) || rssi_dbm < this->rssi_min_) {
    this->rssi_min_ = rssi_dbm;
  }
  if (std::isnan(this->rssi_max_) || rssi_dbm > this->rssi_max_) {
    this->rssi_max_ = rssi_dbm;
  }

  ESP_LOGI(TAG,
           "RADIO RSSI=%.1f dBm (brut 0x%02X) | MARCSTATE=0x%02X %s | PKTSTATUS=0x%02X CS=%u "
           "SFD=%u | FREQ=%.5f MHz (FREQ2:1:0=%02X %02X %02X) | VERSION=0x%02X | plancher n=%u "
           "moy=%.1f min=%.1f max=%.1f | captures RMT=%u",
           rssi_dbm, rssi_raw, marcstate, marcstate_name(marcstate), pktstatus,
           (unsigned) carrier_sense, (unsigned) sfd, freq_mhz, freq_regs[0], freq_regs[1],
           freq_regs[2], version, (unsigned) this->rssi_samples_,
           this->rssi_sum_ / (float) this->rssi_samples_, this->rssi_min_, this->rssi_max_,
           (unsigned) this->captures_);

  // `0x14` est la valeur attendue du registre VERSION du CC1101 (c'est le « Chip ID 0x0014 »
  // journalisé par `configure()`). Autre valeur = la lecture SPI ne va pas jusqu'à la puce :
  // le RSSI publié ci-dessous serait alors un chiffre sans signification, et il faut le dire.
  if (version != 0x14) {
    ESP_LOGW(TAG, "lecture SPI suspecte : VERSION=0x%02X (attendu 0x14) — valeurs ci-dessus non fiables",
             version);
  }

  if (this->rssi_sensor_ != nullptr) {
    this->rssi_sensor_->publish_state(rssi_dbm);
  }
  if (this->radio_sensor_ != nullptr) {
    char text[96];
    snprintf(text, sizeof(text), "%s | CS=%u SFD=%u | %.5f MHz", marcstate_name(marcstate),
             (unsigned) carrier_sense, (unsigned) sfd, freq_mhz);
    this->radio_sensor_->publish_state(text);
  }
}

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
  const uint32_t now = millis();
  // ÉCHANTILLONNAGE RADIO LÉGER (rétabli après le test « plus d'instrumentation » du 30/09
  // 22:52 locales, qui n'a rien changé : la puce restait muette et le compteur de captures
  // inchangé). Il ne lit que des registres d'ÉTAT, 6 octets au total, une fois toutes les 10 s :
  // c'est la seule mesure qui distingue « aucun signal ne parvient à la puce » (RSSI plat,
  // CS=0) de « la porteuse est là mais rien ne sort du démodulateur » (CS qui bascule, plancher
  // qui remonte pendant les rafales). Sans elle, « aucune trame » reste sans explication.
  if (this->spi_is_ready() && (now - this->last_radio_sample_ms_) >= RADIO_SAMPLE_MS) {
    this->last_radio_sample_ms_ = now;
    this->sample_radio_();
  }
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

  if (this->probe_pin_ != nullptr) {
    this->probe_pin_burst_();
  }
  // INSTRUMENTATION SPI DÉSACTIVÉE (test du 30/09 22:52) : ces lectures partagent le bus SPI et
  // la broche CS avec le composant `cc1101`, elles bloquent la boucle principale et retardent la
  // vidange du tampon RMT — soupçon direct des captures erratiques (trains de 496 impulsions puis
  // miettes de 2 à 7) et des lectures à 0xFF. Le témoin, qui n'a AUCUNE instrumentation SPI, a
  // des captures stables. À réactiver (en la déplaçant hors de la boucle critique) si on en a
  // besoin.
  // if (this->spi_is_ready()) {
  //   this->sample_radio_();
  // }

  if (this->reported_captures_ == this->captures_) {
    // Deux causes très différentes derrière « rien depuis 5 s » :
    //   - la sonde a vu la broche bouger → la chaîne RX vit, il n'y a simplement pas eu de
    //     rafale dans la fenêtre (cadence réelle de la station : ~20 s). Rien à signaler.
    //   - la sonde n'a vu AUCUNE transition → la sortie GDO0 est statique : puce pas en écoute
    //     (ou absente). C'est ÇA qu'il faut alerter, et c'est la seule chose qu'on ne peut pas
    //     deviner sans la sonde.
    if (this->probe_pin_ != nullptr && this->probe_transitions_ <= 0) {
      ESP_LOGW(TAG,
               "rien depuis %u s : GDO0 STATIQUE (0 transition) — puce pas en écoute, mauvais "
               "câblage, ou carte absente (captures=%u, trames=%u)",
               (unsigned) (HEARTBEAT_MS / 1000), (unsigned) this->captures_, (unsigned) this->frames_);
    } else {
      ESP_LOGD(TAG, "aucune rafale depuis %u s (captures=%u, trames=%u) — normal",
               (unsigned) (HEARTBEAT_MS / 1000), (unsigned) this->captures_, (unsigned) this->frames_);
    }
    return;
  }

  ESP_LOGI(TAG, "captures=%u (+%u), trames=%u, dernières impulsions=%u, plus longue=%u",
           (unsigned) this->captures_, (unsigned) (this->captures_ - this->reported_captures_),
           (unsigned) this->frames_, (unsigned) this->last_pulse_count_,
           (unsigned) this->longest_capture_);
  this->reported_captures_ = this->captures_;
}

void Vevor7in1::build_stitched_(const std::vector<int32_t> &timings) {
  this->stitched_.clear();
  this->stitched_.reserve(this->tail_.size() + timings.size());
  this->stitched_.insert(this->stitched_.end(), this->tail_.begin(), this->tail_.end());
  this->stitched_.insert(this->stitched_.end(), timings.begin(), timings.end());

  // Si la coupure tombe au milieu d'une impulsion, ses deux moitiés ont le même niveau (donc le
  // même signe) : on les additionne pour reconstituer l'impulsion d'origine. Sans ça, chaque
  // frontière s'invente un bit supplémentaire et décale toute la suite — le témoin journalise
  // d'ailleurs ce delta (« extra=-180 us ») dans sa reconstruction.
  if (!this->tail_.empty() && !timings.empty()) {
    const size_t boundary = this->tail_.size();
    const int32_t a = this->stitched_[boundary - 1];
    const int32_t b = this->stitched_[boundary];
    if ((a >= 0) == (b >= 0)) {
      this->stitched_[boundary - 1] = a + b;
      this->stitched_.erase(this->stitched_.begin() + static_cast<long>(boundary));
    }
  }

  // Mémorise la fin de la capture courante pour le recollage suivant. 480 impulsions couvrent
  // largement une rafale (une rafale mesurée fait 161 à 178 impulsions ; la queue la plus utile
  // est la fin du morceau précédent).
  const size_t keep = 480;
  const size_t n = timings.size() < keep ? timings.size() : keep;
  this->tail_.assign(timings.end() - static_cast<long>(n), timings.end());
}

bool Vevor7in1::dump(remote_base::RemoteReceiveData src) {
  const std::vector<int32_t> &timings = src.get_raw_data();
  this->captures_++;
  this->last_pulse_count_ = timings.size();
  if (timings.size() > this->longest_capture_) {
    this->longest_capture_ = timings.size();
  }

  // Les premières captures sont détaillées, et toute capture demandée à la main l'est aussi
  // (bouton « Dump impulsions ») : elles montrent la forme brute du flux et évitent de raisonner
  // à l'aveugle. Les premières durées sont écrites en clair, car l'API ne livre que des logs :
  // c'est la SEULE façon d'analyser la rafale réelle hors de la carte (rythme bit, polarité,
  // biais, bruit) sans instrument supplémentaire.
  if (this->captures_ <= 3 || this->dump_requested_) {
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

    std::string head;
    for (size_t i = 0; i < timings.size() && i < 64; i++) {
      if (i != 0) {
        head += ' ';
      }
      head += std::to_string(timings[i]);
    }
    ESP_LOGI(TAG, "  impulsions (64 premières) : %s", head.c_str());
    this->dump_requested_ = false;
  }

  // La rafale n'arrive PAS toujours entière. Mesuré chez le montage témoin le 30/09 vers
  // 22:30 locales, sur cette même carte et avec les mêmes réglages : environ **une rafale sur
  // deux est livrée en DEUX morceaux** (94 puis 70 impulsions pour une rafale de 164), parce que
  // le bloc mémoire RMT matériel du C3 (~96 symboles) ne tient pas la rafale entière. On recolle
  // donc la fin de la capture précédente au début de la courante AVANT de décoder : sans ça, on
  // perd la moitié des mesures — c'est exactement ce que montraient nos fenêtres « 1 trame
  // toutes les 2 minutes » alors que le témoin, lui, décode une rafale sur une.
  this->build_stitched_(timings);
  const std::vector<int32_t> &source = this->stitched_;
  if (source.size() < vevor::MIN_TIMINGS) {
    return false;  // même recollée, trop courte pour porter une trame
  }

  // Durées → bits → trame, en essayant plusieurs périodes bit ET les deux polarités.
  this->bits_.resize(source.size() * 8 + 256);
  uint8_t raw[vevor::FRAME_BYTES];
  int32_t period_used = 0;
  bool inverted = false;
  if (!vevor::decode_timings(source.data(), source.size(), vevor::PERIOD_CANDIDATES,
                             vevor::PERIOD_CANDIDATE_COUNT, this->bits_.data(),
                             this->bits_.size(), raw, &period_used, &inverted)) {
    return false;
  }

  // La même rafale est régulièrement livrée deux fois par le RMT (tampon matériel de 96
  // symboles + redistribution par le pilote) : deux trames identiques octet pour octet à
  // quelques dizaines de millisecondes d'écart, ce sont bien les mêmes mesures relues deux
  // fois. On ne déclenche que la première — l'entité n'est pas republiée pour rien.
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
  ESP_LOGD(TAG, "trame extraite (%d us, polarité %s, %u impulsions recollées) → %u octets",
           (int) period_used, inverted ? "inversée" : "normale", (unsigned) source.size(),
           (unsigned) vevor::FRAME_BYTES);

  // La trame est remise AU YAML, qui la valide (en-tête, checksum, compteur) et publie les
  // capteurs : le composant ne connaît pas les entités, et la logique de protocole reste
  // testable à froid dans includes/vevor_protocol.h.
  std::vector<uint8_t> payload(raw, raw + vevor::FRAME_BYTES);
  this->frame_trigger_.trigger(payload);
  return true;
}

}  // namespace vevor_7in1
}  // namespace esphome
