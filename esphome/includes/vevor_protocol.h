#pragma once
// Décodeur de trames Vevor 7-en-1 868/915 MHz
// NB : ce fichier s'appelait vevor_7in1.h, comme l'en-tête du composant ESPHome
// du même projet (esphome/components/vevor_7in1/). Les deux entrant en collision
// dans le chemin d'inclusion, le compilateur prenait le mauvais et le namespace
// `vevor` disparaissait. D'où le nom distinct : ne pas le renommer. — portage de vevor_7in1.c (rtl_433).
// Spec de référence : references/PROTOCOL.md
//
// Le header ne fait aucun appel au matériel : il décrit la trame et sa validation.
// La publication des valeurs se fait dans le lambda YAML (on_packet), qui voit les id().
//
// Conventions de log (parsées par tools/eval_frames.py) :
//   V7IN1 RAW <21 octets en hex séparés par des espaces> rssi=.. freq_offset=..
//   V7IN1 OK {"id":..,"temp_c":..,...}      <- uniquement si la trame est valide
//   V7IN1 REJ <raison>                      <- trame rejetée (diagnostic)

#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

namespace vevor {

static constexpr size_t FRAME_BYTES = 21;
// Motif d'accroche au cas où l'on décode depuis un flux brut (mode non-packet) :
// AA AA AA CA CA 54 puis 21 octets utiles.
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

// Le checksum et le compteur se calculent sur les octets BRUTS, avant tout -1.
inline bool checksum_ok(const uint8_t *b) {
  uint16_t sum = 0;
  for (int i = 0; i < 19; i++) sum += b[i];
  return (sum & 0xFF) == b[19];
}

inline bool counter_ok(const uint8_t *b) { return b[20] == (uint8_t)(b[18] + 1); }

// `in` : 21 octets utiles (synchronisation déjà faite par le CC1101 en mode packet).
inline bool decode(const uint8_t *in, Frame &out, const char **reason) {
  if (in[0] != 0xAA || in[1] != 0x00) {
    *reason = "en-tete";
    return false;
  }
  if (!checksum_ok(in)) {
    *reason = "checksum";
    return false;
  }
  if (!counter_ok(in)) {
    *reason = "compteur_tx";
    return false;
  }

  uint8_t b[FRAME_BYTES];
  for (size_t i = 0; i < FRAME_BYTES; i++) b[i] = in[i];
  // Les valeurs multi-octets sont transmises avec un décalage de 1 sur chaque octet.
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

  out.valid = true;
  return true;
}

inline std::string to_json(const Frame &f) {
  char buf[320];
  snprintf(buf, sizeof(buf),
           "{\"id\":%u,\"channel\":%u,\"battery_low\":%s,\"temp_c\":%.1f,\"humidity\":%u,"
           "\"wind_kmh\":%.1f,\"gust_kmh\":%.1f,\"wind_dir_deg\":%u,\"rain_mm\":%.1f,"
           "\"uv_index\":%d,\"lux\":%u,\"tx_counter\":%u}",
           f.id, f.channel, f.battery_low ? "true" : "false", f.temp_c, f.humidity,
           f.wind_kmh, f.gust_kmh, f.wind_dir_deg, f.rain_mm, f.uv_index, f.lux,
           f.tx_counter);
  return std::string(buf);
}

// ---------------------------------------------------------------------------------------
// Chaîne « impulsions → trame » (voie asynchrone : CC1101 en série asynchrone + remote_receiver)
// ---------------------------------------------------------------------------------------
// Le CC1101 sort le signal démodulé sur GDO0 ; `remote_receiver` le convertit en durées
// d'impulsions signées (signe = niveau : positif = mark = 1, négatif = space = 0).
// Ce bloc fait le reste — durées → bits NRZ, puis recherche du mot de synchronisation — et,
// comme le reste de l'en-tête, n'appelle aucun matériel : toute la chaîne est testable hors
// carte (tests/test_decoder.cpp, scénarios d'impulsions générés par tests/frames.py).

// Fin du mot de synchronisation : la trame est précédée de AA AA AA puis CA CA 54, et les
// 21 octets utiles commencent juste après. On cherche donc CE motif-là (et non le préambule
// complet) : une capture peut très bien commencer au milieu du préambule.
static const uint8_t SYNC_WORD[2] = {0xCA, 0x54};
static constexpr size_t SYNC_BYTES = 2;

// Un niveau tenu plus longtemps que ça (en périodes bit) n'est pas de la donnée : c'est un trou
// entre deux rafales. On le SAUTE au lieu d'abandonner la capture — la trame utile peut suivre.
static constexpr int32_t MAX_RUN_BITS = 64;

// Capacité de la conversion durées → bits (une capture RMT en fait ~200 bits).
static constexpr size_t MAX_BITS = 4096;

// En dessous de ce nombre d'impulsions, aucune rafale Vevor ne peut tenir.
static constexpr size_t MIN_TIMINGS = 40;

// Au-dessus de cette longueur, la capture porte une rafale ENTIÈRE — mesuré sur ce montage : 176
// à 184 impulsions pour une rafale utile (le RMT du C3 la coupe parfois en deux : 96 + 82,
// 94 + 70…). Seules les captures plus courtes sont des MORCEAUX qu'il faut recoller ; recoller
// plus large fait relire la rafale PRÉCÉDENTE — mesuré le 01/10 : 60 trames publiées pour
// 31 mesures distinctes, chaque compteur TX exactement deux fois.
static constexpr size_t MAX_FRAGMENT_TIMINGS = 160;

// Périodes bit essayées à chaque capture, dans l'ordre. Les valeurs encadrent tout ce qu'on
// sait du protocole : 90 µs (valeur publiée, et période du montage témoin qui décode cette
// station), 88,3 µs (mesure de l'utilisateur → 11 325 bauds), 87 µs (déduite de rtl_433). La
// bonne période n'est PAS supposée : elle est trouvée à la trame décodée, et le gagnant est
// journalisé — c'est ce qui permet de resserrer ensuite sans deviner.
static const int32_t PERIOD_CANDIDATES[] = {90, 88, 89, 87};
static constexpr size_t PERIOD_CANDIDATE_COUNT =
    sizeof(PERIOD_CANDIDATES) / sizeof(PERIOD_CANDIDATES[0]);

// Durées d'impulsions → bits NRZ (arrondi au multiple de période le plus proche). `invert`
// échange les niveaux : la polarité de la sortie GDO0 dépend du module et ne se présume pas.
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

// Cherche le PROCHAIN mot de synchronisation à partir de *from_bit, puis reconstruit les
// 21 octets qui le suivent. *from_bit est avancé après le candidat trouvé pour que l'appelant
// puisse les énumérer tous : c'est decode() qui tranche, un alignement faux ne doit pas masquer
// le bon.
inline bool find_frame_candidate(const uint8_t *bits, size_t bit_count, uint8_t *out,
                                 size_t *from_bit) {
  const size_t sync_bits = SYNC_BYTES * 8;
  const size_t frame_bits = FRAME_BYTES * 8;
  for (size_t start = *from_bit; start + sync_bits + frame_bits <= bit_count; start++) {
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
    for (size_t b = 0; b < FRAME_BYTES; b++) {
      uint8_t byte = 0;
      for (size_t k = 0; k < 8; k++) {
        byte = (uint8_t)((byte << 1) | bits[payload + b * 8 + k]);
      }
      out[b] = byte;
    }
    *from_bit = start + 1;
    return true;
  }
  return false;
}

// Chaîne complète : essaie plusieurs périodes bit ET les deux polarités, puis renvoie la
// première trame que decode() accepte (en-tête, checksum et compteur vérifiés). `raw_out`
// reçoit les 21 octets validés ; `period_used` / `inverted_used` documentent le réglage gagnant
// (indispensable pour savoir quoi resserrer ensuite).
inline bool decode_timings(const int32_t *timings, size_t count, const int32_t *periods,
                           size_t period_count, uint8_t *bits, size_t max_bits, uint8_t *raw_out,
                           int32_t *period_used, bool *inverted_used,
                           size_t *rejected_out = nullptr) {
  if (count < MIN_TIMINGS) {
    return false;
  }
  const size_t needed = SYNC_BYTES * 8 + FRAME_BYTES * 8;
  for (size_t p = 0; p < period_count; p++) {
    for (int polarity = 0; polarity < 2; polarity++) {
      const bool invert = (polarity == 1);
      const size_t n = timings_to_bits(timings, count, periods[p], invert, bits, max_bits);
      // Conversion SATURÉE (le tampon est plein) : le flux est tronqué, donc plus
      // interprétable. On écarte la tentative au lieu de décoder une suite tronquée qui
      // pourrait passer les contrôles par hasard.
      if (n >= max_bits) {
        continue;
      }
      if (n < needed) {
        continue;
      }
      size_t from = 0;
      uint8_t candidate[FRAME_BYTES];
      Frame frame;
      const char *reason = "";
      while (find_frame_candidate(bits, n, candidate, &from)) {
        if (decode(candidate, frame, &reason)) {
          for (size_t i = 0; i < FRAME_BYTES; i++) {
            raw_out[i] = candidate[i];
          }
          if (period_used != nullptr) {
            *period_used = periods[p];
          }
          if (inverted_used != nullptr) {
            *inverted_used = invert;
          }
          return true;
        }
        // Mot de synchronisation trouvé mais trame REFUSÉE (en-tête, checksum, compteur) :
        // c'est le vrai compteur de bruit du décodage, distinct de « rien n'arrive à la puce ».
        if (rejected_out != nullptr) {
          (*rejected_out)++;
        }
      }
    }
  }
  return false;
}

// Recolle deux MORCEAUX de rafale (voir MAX_FRAGMENT_TIMINGS). La coupure du RMT peut tomber AU
// MILIEU d'une impulsion : les deux demi-impulsions ont alors le même signe et doivent être
// additionnées pour retrouver l'impulsion d'origine — sinon chaque soudure invente un front et
// décale tous les bits suivants (c'est l'« extra = -180 us » que le firmware de référence
// journalise). `out` doit pouvoir contenir prev_count + cur_count éléments ; renvoie la longueur
// écrite. Testé hors matériel (tests/test_decoder.cpp, scénarios _coupe_*).
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