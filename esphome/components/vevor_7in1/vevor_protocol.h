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
// AA AA CA CA 54 puis 21 octets utiles.
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

// GARDE-FOU DE CONTINUITÉ, utilisé par le composant pour les trames OBTENUES PAR RÉPARATION : une
// trame réparée n'est publiée que si elle est cohérente avec la dernière trame acceptée — même
// station, et des mesures qui ne sautent pas (la station est stable d'une rafale à l'autre, 20 s
// d'écart). Mesure du 03/10 sur 200 charges utiles aléatoires (synchronisation et en-tête justes) :
// AUCUNE trame publiée, ce qui est cohérent avec le calcul (somme 1/256 × compteur 1/256 × porte de
// plausibilité, sur ~336 positions d'insertion). C'est donc une PRÉCAUTION à coût nul, pas une
// nécessité mesurée — elle ferme le risque résiduel sans rien changer à ce qui passe aujourd'hui.
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

// Limite physique de la porte de plausibilité (km/h) et marge de comparaison. L'encodeur écrit
// 1500 ticks pour 180 km/h ; or 1500 / 8,333f = 180,007 — STRICTEMENT au-dessus de 180,0f. Sans
// marge, une rafale LÉGITIME à 180 km/h était donc refusée (faux rejet mesuré par la revue
// round 2). La marge absorbe l'erreur d'arrondi de cette division ; une trame à décalage de bits
// (≈ 360 km/h) la dépasse de très loin et reste refusée.
static constexpr float WIND_LIMIT_KMH = 180.0f;
static constexpr float WIND_LIMIT_MARGE_KMH = 0.01f;

// BORNE DE PLAUSIBILITÉ DE LA PLUIE (ajoutée après un défaut constaté en production le 03/10).
//
// Home Assistant a enregistré deux pics de pluie à **7 634,5 mm** dans l'après-midi, sous un ciel
// dégagé, alors que la valeur était stable à 59,2 mm avant et après — et une division par deux de la
// même valeur (59,18 → 29,36 mm, soit 254 → 126 ticks, exactement un bit faux) deux minutes avant le
// premier pic. La porte de plausibilité ne contrôlait PAS la pluie : direction, humidité, température,
// vent et UV seulement. Une trame cohérente portant n'importe quelle valeur de pluie passait donc.
//
// Les règles appliquées sont celles du décodeur de RÉFÉRENCE du protocole (references/PROTOCOL.md,
// d'après rtl_433) : « la pluie ne peut que monter, ou repartir à zéro après un changement de pile ;
// une baisse non nulle est une corruption même avec un checksum valide ». C'est ce qui fait refuser
// la division par deux observée — elle n'était pas seulement invraisemblable, elle était impossible.
//
// Le retour à zéro est accepté sur UNE trame (la référence demande trois trames consécutives) : c'est
// un écart assumé, une trame isolée à 0 mm est sans conséquence, alors que le contrôle à trois trames
// exige de mémoriser un état supplémentaire pour un gain nul.
//
// La hausse, elle, est bornée par le physique : au pluviomètre de cette station (0,233 mm par
// bascule), +5 mm entre deux rafales espacées de 20 s représenterait 21 bascules en 20 s, soit
// 15 mm/min — plus qu'aucune pluie réelle, et très loin des 7 634 mm observés. Ne pas resserrer sans
// une mesure de pluie réelle soutenue, et ne JAMAIS borner la baisse à la place de cette règle :
// une borne symétrique rejetterait les trames légitimes qui suivent une remise à zéro.
static constexpr float RAIN_MAX_HAUSSE_MM = 5.0f;

// `connue` = on a une trame précédente acceptée à comparer. Sans référence, on accepte : la trame a
// déjà passé l'en-tête, la somme, le compteur et le reste de la porte de plausibilité.
inline bool pluie_plausible(float nouvelle, float precedente, bool connue) {
  if (nouvelle < 0.0f) {
    return false;
  }
  if (!connue) {
    return true;
  }
  if (nouvelle < precedente - 0.01f) {
    // Baisse : légitime uniquement vers zéro (remise à zéro du compteur de pluie).
    return nouvelle <= 0.01f;
  }
  return (nouvelle - precedente) <= RAIN_MAX_HAUSSE_MM;
}

// `in` : 21 octets utiles (synchronisation déjà faite par le CC1101 en mode packet).
inline bool decode(const uint8_t *in, Frame &out, const char **reason) {
  // `valid` décrit CETTE trame, pas la précédente : remis à faux dès l'entrée, pour qu'une trame
  // REFUSÉE ne puisse jamais ressortir marquée valide (revue round 2 : `out.valid` était posé
  // AVANT la porte de plausibilité).
  out.valid = false;
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

  // PORTE DE PLAUSIBILITÉ — une trame PEUT passer en-tête + checksum + compteur et être fausse.
  // Mesuré le 01/10 sur une fenêtre d'une heure : 2 trames publiées sur 181 (1,6 %) portaient un
  // décalage d'un bit à l'extraction, ce qui DOUBLE tous les octets de valeur (un décalage d'un
  // bit = ×2) — direction 779° et 835°, pluie 178,2 mm au lieu de 59,2, vent 34,2 km/h. Ces
  // valeurs ne sont pas seulement improbables, elles sont PHYSIQUEMENT IMPOSSIBLES : une direction
  // au-delà de 359° n'existe pas. On refuse la trame au lieu de la publier, et le composant la
  // compte dans son compteur de rejets (visible dans Home Assistant).
  if (out.wind_dir_deg > 359) {
    *reason = "direction";
    return false;
  }
  if (out.humidity > 100) {
    *reason = "humidite";
    return false;
  }
  if (out.temp_c < -40.0f || out.temp_c > 60.0f) {
    *reason = "temperature";
    return false;
  }
  // Bornes hautes larges mais finies : un anémomètre de station domestique ne dépasse pas ces
  // valeurs, alors qu'un décalage de bits les double. Comparaison À LA BORNE avec marge d'arrondi
  // (WIND_LIMIT_MARGE_KMH) : 1500 ticks / 8,333f = 180,007 pour un 180 km/h LÉGITIME — sans cette
  // marge, la porte refusait une trame valide (faux rejet de la revue round 2).
  if (out.wind_kmh > WIND_LIMIT_KMH + WIND_LIMIT_MARGE_KMH ||
      out.gust_kmh > WIND_LIMIT_KMH + WIND_LIMIT_MARGE_KMH) {
    *reason = "vent";
    return false;
  }
  if (out.uv_index < 0 || out.uv_index > 16) {
    *reason = "uv";
    return false;
  }

  // La trame a franchi TOUTE la porte : elle est valide, et seulement maintenant. Poser `valid`
  // AVANT les contrôles laissait ressortir une trame REFUSÉE marquée `valid == true` (revue
  // round 2 — le composant ne lit pas ce champ, mais le contrat du décodeur était faux).
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

// Vrai UNIQUEMENT pour une capture trop courte pour porter une rafale ENTIÈRE : c'est la seule
// situation où recoller a un sens. Le composant appelle CE prédicat (vevor_7in1.cpp) et le test
// l'exerce aux bornes. Une rafale complète (mesuré sur ce montage : 176 à 184 impulsions) n'est
// donc jamais mémorisée comme morceau, donc jamais recollée devant la suivante — c'est ce qui a
// supprimé la double publication du 01/10 (60 trames pour 31 mesures distinctes).
inline bool is_fragment(size_t count) {
  return count >= MIN_TIMINGS && count <= MAX_FRAGMENT_TIMINGS;
}

// Périodes bit essayées à chaque capture, dans l'ordre. Les valeurs encadrent tout ce qu'on
// sait du protocole : 90 µs (valeur publiée, et période du montage témoin qui décode cette
// station), 88,3 µs (mesure de l'utilisateur → 11 325 bauds), 87 µs (déduite de rtl_433). La
// bonne période n'est PAS supposée : elle est trouvée à la trame décodée, et le gagnant est
// journalisé — c'est ce qui permet de resserrer ensuite sans deviner.
static const int32_t PERIOD_CANDIDATES[] = {90, 88, 89, 87};
// MESURÉ le 03/10 : élargir cette grille (86-90, puis 85,0-91,0 µs par pas de 0,1) ne décode PAS une
// rafale de plus sur les six captures du dump — 1/6 sans le filet, quelle que soit la grille. La
// valeur exacte du rythme bit n'est donc pas le verrou ; ne pas la retoucher sans une mesure qui le
// démontre. (Le projet de référence mesure la station à 88,3 µs ; notre décodeur y est insensible.)
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

// Même conversion, mais la période est exprimée en DIXIÈMES de microseconde : la période mesurée
// sur une rafale vaut 88,5 µs, qu'un entier ne peut pas représenter. La règle d'arrondi est
// rigoureusement la même (au multiple le plus proche), simplement à cette échelle.
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
// PÉRIODE BIT MESURÉE SUR LA RAFALE (dixièmes de µs ; 0 = estimation refusée)
// ---------------------------------------------------------------------------------------
// Mesuré le 03/10 : cette station émet à 88,5-88,9 µs (le projet de référence la mesure à 88,3 µs).
// La constante 90 µs héritée de rtl_433 était donc FAUSSE de 2 %, et une période fixe ne peut pas
// convenir à la carte d'un utilisateur inconnu : le rythme dépend de l'émetteur, du quartz et du
// démodulateur. On le MESURE donc sur chaque rafale reçue, ce qui supprime toute constante de
// station — contrainte explicite du projet : un nouvel utilisateur ne fait que flasher.
//
// Méthode (validée hors ligne sur six rafales réelles : 88,5 à 88,9 µs) :
//   1. estimation de départ : médiane des durées de la fenêtre 45-115 µs. Cette fenêtre est
//      PROTOCOLAIRE (un bit vaut ~90 µs d'après la spec), pas propre à une station ; l'élargir
//      au-delà ferait entrer les fronts parasites de 45-50 µs et les impulsions de deux bits ;
//   2. consolidation : moyenne de d / round(d / T) sur les durées >= 0,55·T, trois fois. Les
//      durées sous 0,55·T sont des parasites (un bit ne peut pas être plus court que la moitié
//      d'une période) et sont écartées au lieu de fausser la moyenne ; la division par l'arrondi
//      ramène les impulsions de 2, 3… bits à l'échelle d'un bit.
// Aucune allocation : l'histogramme est statique (appelé depuis une seule tâche, la boucle
// principale, et le test hôte est mono-thread).
static constexpr int32_t PERIODE_MIN_X10 = 500;    // 50 µs : plus court n'est pas un bit plausible
static constexpr int32_t PERIODE_MAX_X10 = 1500;   // 150 µs : plus long non plus
static constexpr int32_t FENETRE_BAS_US = 45;      // borne basse de la fenêtre protocolaire
static constexpr int32_t FENETRE_HAUT_US = 115;    // borne haute
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
  // Médiane de la fenêtre protocolaire (repli : médiane de tout, si la fenêtre est vide).
  int64_t base = 0;
  for (int fenetre = 0; fenetre < 2 && base == 0; fenetre++) {
    const int bas = fenetre == 0 ? FENETRE_BAS_US : 1;
    const int haut = fenetre == 0 ? FENETRE_HAUT_US : HIST_MAX_US - 1;
    size_t total = 0;
    for (int b = bas; b <= haut; b++) {
      total += histo[b];
    }
    if (total < 10) {
      continue;
    }
    const size_t milieu = total / 2;
    size_t cumul = 0;
    for (int b = bas; b <= haut; b++) {
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
  // Consolidation : ramène chaque impulsion à l'échelle d'un bit et moyenne.
  int32_t T = (int32_t) base;
  for (int passe = 0; passe < 3; passe++) {
    const int32_t seuil = (T * 55) / 100;
    int64_t somme = 0;
    size_t n = 0;
    for (size_t i = 0; i < count; i++) {
      const int32_t d = timings[i] > 0 ? timings[i] : -timings[i];
      if (d < seuil) {
        continue;
      }
      int32_t k = (d * 10 + T / 2) / T;   // nombre de bits de cette impulsion
      if (k < 1) {
        k = 1;
      }
      somme += (int64_t)(d * 10) / k;     // durée ramenée à un bit
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
    return 0;   // estimation invraisemblable : on préfère la grille de repli
  }
  return T;
}

// Cherche le PROCHAIN mot de synchronisation à partir de *from_bit, puis reconstruit les
// 21 octets qui le suivent. *from_bit est avancé après le candidat trouvé pour que l'appelant
// puisse les énumérer tous : c'est decode() qui tranche, un alignement faux ne doit pas masquer
// le bon.
inline bool find_frame_candidate(const uint8_t *bits, size_t bit_count, uint8_t *out,
                                 size_t *from_bit, size_t *payload_bit = nullptr,
                                 size_t marge = 0) {
  const size_t sync_bits = SYNC_BYTES * 8;
  const size_t frame_bits = FRAME_BYTES * 8;
  // `marge` = 1 autorise une charge utile à UN BIT PRÈS : c'est indispensable, car une impulsion
  // raccourcie d'un bit (le mécanisme mesuré le 03/10) allonge le flux d'un bit en moins, et sans
  // cette marge la trame ne « rentre » plus dans la fenêtre — plus aucun candidat n'est produit, et
  // la réparation par insertion n'est jamais atteinte. Les bits manquants au-delà du flux comptent
  // pour 0 (déterministe) ; c'est la réparation qui rétablit la bonne valeur.
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

// RÉPARATION PAR INSERTION D'UN BIT (mécanisme mesuré le 03/10).
// Sur les rafales réelles du dump, un bit MANQUE dans la charge : une impulsion que l'arrondi a
// comptée pour un bit alors qu'elle en valait deux — tout ce qui suit est décalé d'un bit, et les
// valeurs doublent (02 22 devient 04 44). Le prouver : insérer un bit à la bonne position et
// revérifier répare deux des six rafales du dump, alors qu'en SUPPRIMER un n'en réparait aucune.
// Borné deux fois : une seule insertion, et l'en-tête + la somme + le compteur + la porte de
// plausibilité doivent passer ensuite. C'est ce qui interdit de « réparer » une trame au hasard.
inline bool reparer_par_insertion(const uint8_t *bits, size_t payload_bit, uint8_t *candidate) {
  const size_t frame_bits = FRAME_BYTES * 8;
  for (size_t q = 0; q <= frame_bits; q++) {
    for (uint8_t insere = 0; insere < 2; insere++) {
      uint8_t essai[FRAME_BYTES];
      for (size_t b = 0; b < FRAME_BYTES; b++) {
        uint8_t octet = 0;
        for (size_t k = 0; k < 8; k++) {
          const size_t i = b * 8 + k;
          const uint8_t bit = (i < q) ? bits[payload_bit + i]
                                       : ((i == q) ? insere : bits[payload_bit + i - 1]);
          octet = (uint8_t)((octet << 1) | bit);
        }
        essai[b] = octet;
      }
      Frame f;
      const char *raison = "";
      if (decode(essai, f, &raison)) {
        for (size_t i = 0; i < FRAME_BYTES; i++) {
          candidate[i] = essai[i];
        }
        return true;
      }
    }
  }
  return false;
}

// Essaie UNE période (en dixièmes de µs) et les deux polarités, avec les deux réparations bornées.
// `repaired_out` distingue une trame sortie après réparation : l'appelant peut la soumettre à un
// contrôle supplémentaire (voir vevor_7in1.cpp, garde-fou sur le compteur d'émission).
inline bool essayer_periode(const int32_t *timings, size_t count, int32_t period_x10,
                            uint8_t *bits, size_t max_bits, uint8_t *raw_out,
                            bool *inverted_used, size_t *rejected_out, bool *repaired_out) {
  const size_t needed = SYNC_BYTES * 8 + FRAME_BYTES * 8;
  for (int polarity = 0; polarity < 2; polarity++) {
    const bool invert = (polarity == 1);
    const size_t n = timings_to_bits_fin(timings, count, period_x10, invert, bits, max_bits);
    // Conversion SATURÉE (le tampon est plein) : le flux est tronqué, donc plus interprétable.
    // On accepte UN BIT DE MOINS que la trame complète : c'est exactement le cas d'une impulsion
    // raccourcie d'un bit, que la réparation par insertion sait ensuite rétablir.
    if (n >= max_bits || n + 1 < needed) {
      continue;
    }
    // Deux passes : d'abord la charge utile complète ; si aucune trame n'en sort, on refait la
    // recherche en tolérant un bit manquant. Les rejets ne sont comptés que sur la première passe,
    // sinon le même candidat serait compté deux fois.
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
          // TOLÉRANCE D'UN BIT SUR L'OCTET D'EN-TÊTE (mesuré le 03/10) : sur les rafales du dump,
          // l'octet 0 arrive régulièrement avec UN seul bit faux (0xAB, 0xAE ou 0xEA au lieu de
          // 0xAA) tandis que les 16 octets suivants sont exacts — le front qui porte ce bit est mal
          // daté, pas la trame. Corriger ce bit constant est sûr : la somme, le compteur et la porte
          // de plausibilité doivent ensuite passer tous les trois. Un seul bit, jamais plus.
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
          // Puis la réparation par insertion d'un bit (voir reparer_par_insertion). Coût mesuré :
          // 168 positions × 21 octets ≈ 28 000 opérations, soit moins d'une milliseconde à
          // 160 MHz, et seulement pour une capture où la synchronisation a été trouvée sans trame
          // valide.
          if (reparer_par_insertion(bits, payload_bit, candidate)) {
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
        // Mot de synchronisation trouvé mais trame REFUSÉE : c'est le vrai compteur de bruit du
        // décodage, distinct de « rien n'arrive à la puce ».
        if (rejected_out != nullptr && marge == 0) {
          (*rejected_out)++;
        }
      }
    }
  }
  return false;
}

// Chaîne complète : mesure d'abord la période bit SUR LA RAFALE (aucune constante de station),
// puis, si l'estimation échoue ou se trompe, essaie la grille fixe de repli — chaque candidat avec
// les deux polarités et les réparations bornées. `period_used` est en DIXIÈMES de µs.
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

  // 1. PÉRIODE MESURÉE (chemin normal, et seul chemin valable pour une carte inconnue).
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

  // 2. REPLI : la grille fixe, pour le cas où l'estimation est refusée (bruit) ou tombe à côté.
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