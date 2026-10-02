// Tests unitaires du décodeur Vevor 7-en-1 — tournent SANS matériel.
//
// Compilé par tests/run_tests.sh avec le compilateur embarqué dans .venv-dev (zig c++).
// Les trames de tests viennent de tests/frames.py (encodeur Python indépendant) : le C++ et le
// Python partent de la même spec mais sont écrits séparément, donc un accord entre les deux est
// une vraie vérification, pas une redite.
//
// Usage : tests/test_decoder   (code de sortie 0 = tout est passé)

#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include "vevor_protocol.h"
#include "vectors.h"
#include "pulses.h"

static int g_failures = 0;
static int g_checks = 0;

static const char *CHECK = "\033[32mOK\033[0m";
static const char *FAIL = "\033[31mÉCHEC\033[0m";

static void expect(bool condition, const std::string &label) {
  g_checks++;
  if (!condition) {
    g_failures++;
    printf("  [%s] %s\n", FAIL, label.c_str());
  }
}

static void expect_near(float got, float want, float tol, const std::string &label) {
  g_checks++;
  if (std::fabs(got - want) > tol) {
    g_failures++;
    printf("  [%s] %s : obtenu %.3f, attendu %.3f (±%.3f)\n", FAIL, label.c_str(), got, want, tol);
  }
}

// --- 1. Toutes les trames valides se décodent exactement comme l'encodeur l'annonce ---------
static void test_vectors() {
  printf("Trames valides et invalides (%d scénarios)\n", VEVOR_VECTOR_COUNT);
  for (int i = 0; i < VEVOR_VECTOR_COUNT; i++) {
    const VevorVector &v = VEVOR_VECTORS[i];
    vevor::Frame f;
    const char *reason = "";
    bool ok = vevor::decode(v.raw, f, &reason);

    std::string name(v.name);
    expect(ok == v.valid, name + " : verdict " + (ok ? "valide" : "rejeté") +
                                (v.valid ? " (attendu valide)" : " (attendu rejeté, motif " +
                                                                    std::string(reason) + ")"));
    if (!v.valid) {
      expect(std::strlen(reason) > 0, name + " : un motif de rejet doit être renseigné");
      // Le MOTIF précis compte : attribuer un rejet à la mauvaise branche de la porte de
      // plausibilité (« direction » au lieu de « vent », p. ex.) passerait sinon inaperçu.
      expect(std::strcmp(reason, v.reject_reason) == 0,
             name + " : motif attendu « " + std::string(v.reject_reason) + " », obtenu « " +
                 std::string(reason) + " »");
      continue;
    }

    expect(f.id == v.id, name + " : id");
    expect(f.channel == v.channel, name + " : canal");
    expect(f.battery_low == v.battery_low, name + " : batterie");
    expect_near(f.temp_c, v.temp_c, 0.06f, name + " : température");
    expect(f.humidity == v.humidity, name + " : humidité");
    expect_near(f.wind_kmh, v.wind_kmh, 0.06f, name + " : vent");
    expect_near(f.gust_kmh, v.gust_kmh, 0.06f, name + " : rafale");
    expect(f.wind_dir_deg == v.wind_dir_deg, name + " : direction");
    expect_near(f.rain_mm, v.rain_mm, 0.06f, name + " : pluie");
    expect(f.uv_index == v.uv, name + " : UV");
    expect(f.lux == v.lux, name + " : luminosité");
    expect(f.tx_counter == v.tx_counter, name + " : compteur TX");
  }
}

// --- 2. La trame de référence de rtl_433, attendue en dur ----------------------------------
// Les valeurs attendues ci-dessous sont calculées À LA MAIN à partir du code de rtl_433
// (src/devices/vevor_7in1.c, fonctions relues le 01/10/2026) et des octets de la trame : c'est
// l'ANCRAGE EXTERNE du décodage. Sans lui, une erreur de formule présente à la fois dans
// l'encodeur Python (tests/frames.py) et dans le C++ passerait toute la suite — mesuré : une
// échelle de vent fausse (8,333 → 3,0) recopiée des deux côtés laissait les 173 vérifications au
// vert. Détail du calcul, octets utiles après les -1 sur les octets 8, 9, 11, 12, 13, 14, 16, 17 :
//   vent   = ((b8<<8)|b9) / 8,333f  = 13 / 8,333   = 1,56 km/h
//   rafale = b10 / 1,25f            = 3 / 1,25     = 2,4 km/h
//   pluie  = ((b13<<8)|b14) * 0,233f = 55 * 0,233  = 12,8 mm
//   lux    = (b16<<8)|b17, ×10 si le bit 15 est posé = 14 457 lx
static void test_rtl433_reference() {
  printf("Trame de référence rtl_433 (valeurs calculées à la main depuis la source rtl_433)\n");
  const uint8_t raw[21] = {0xaa, 0x00, 0xf8, 0xf7, 0x9d, 0x02, 0xe3, 0x32, 0x01, 0x0e, 0x03,
                           0x02, 0x0b, 0x01, 0x38, 0x02, 0x39, 0x7a, 0x86, 0xe0, 0x87};
  vevor::Frame f;
  const char *reason = "";
  expect(vevor::decode(raw, f, &reason), "la trame de référence doit être acceptée");
  expect(f.id == 0xf8f7, "id = 0xf8f7");
  expect(f.temp_c > 23.8f && f.temp_c < 24.0f, "température = 23,9 °C");
  expect(f.humidity == 50, "humidité = 50 %");
  expect_near(f.wind_kmh, 1.6f, 0.06f, "vent = 1,6 km/h (13 ticks / 8,333f)");
  expect_near(f.gust_kmh, 2.4f, 0.06f, "rafale = 2,4 km/h (3 ticks / 1,25f)");
  expect(f.wind_dir_deg == 266, "direction = 266°");
  expect_near(f.rain_mm, 12.8f, 0.06f, "pluie = 12,8 mm (55 ticks × 0,233f)");
  expect(f.uv_index == 1, "UV = 1");
  expect(f.lux == 14457, "luminosité = 14 457 lx");
  expect(f.tx_counter == 0x86, "compteur TX = 0x86");
  expect(f.battery_low, "batterie faible (0x9d)");
}

// --- 2ter. ANCRAGE EXTERNE de la branche « lux ×10 » (bit 15 posé) -------------------------
// La trame de rtl_433 ancrée juste au-dessus a le bit 15 CLAIR (chemin ×1) : la branche ×10
// n'était donc ancrée par AUCUNE source extérieure, et une erreur de facteur commune à l'encodeur
// Python (tests/frames.py) ET au C++ (vevor_protocol.h) passait les 204 vérifications (revue
// round 2, constat BLOQUANT). Ici les 21 octets sont ÉCRITS EN DUR et la valeur attendue est
// CALCULÉE À LA MAIN — sans passer par decode_reference(), donc extérieure au couple
// encodeur/décodeur : une erreur commune aux deux ne peut plus « s'auto-valider ».
//   lux visé = 98 000 lx  (≥ 0x8000 → branche ×10)
//   lux_raw  = 0x8000 | (98 000 / 10) = 0x8000 | 9 800 = 0x8000 | 0x2648 = 0xA648
//   émission : b[16] = ((0xA648 >> 8) + 1) & 0xFF = 0xA6 + 1 = 0xA7
//              b[17] = ((0xA648 & 0xFF) + 1) & 0xFF = 0x48 + 1 = 0x49
//   décodage : 0xA7 - 1 = 0xA6 ; 0x49 - 1 = 0x48  ⇒  (0xA648) ; bit 15 posé
//              ⇒ (0xA648 & 0x7FFF) × 10 = 0x2648 × 10 = 9 800 × 10 = 98 000 lx
static void test_lux_x10_anchor() {
  printf("Ancrage externe de la branche lux ×10 (valeur calculée à la main)\n");
  const uint8_t raw[21] = {0xaa, 0x00, 0x1a, 0x2b, 0x1d, 0x02, 0xac, 0x48, 0x01, 0x1c, 0x07,
                           0x01, 0xd7, 0x01, 0x37, 0x0c, 0xa7, 0x49, 0x40, 0x72, 0x41};
  vevor::Frame f;
  const char *reason = "";
  expect(vevor::decode(raw, f, &reason), "la trame lux ×10 doit être acceptée");
  expect(f.lux == 98000, "lux = 98 000 lx ((0xA648 & 0x7FFF) × 10 = 9 800 × 10, à la main)");
}

// --- 2bis. Porte de plausibilité : trame « bien formée » mais fausse -------------------------
// Deux trames RÉELLES relevées dans une fenêtre d'une heure le 01/10 (logs/fenetre_1h_cond) :
// elles passaient en-tête + checksum + compteur, et pourtant tous leurs octets de valeur valent
// deux fois la valeur correcte — signature d'un décalage d'un bit à l'extraction. Elles affichaient
// une direction de 779° et 835°, ce qui n'existe pas. Elles doivent donc être REFUSÉES, pas
// publiées : c'est le seul garde-fou qui distingue « trame cohérente » de « trame juste ».
static void test_plausibility() {
  printf("Porte de plausibilité (trames fausses mais bien formées)\n");
  vevor::Frame f;
  const char *reason = "";

  // Trame saine prise dans la même fenêtre, juste avant la première trame fautive.
  const uint8_t bonne[21] = {0xaa, 0x00, 0x84, 0xcb, 0x16, 0x02, 0xb9, 0x38, 0x01, 0x3a, 0x0e,
                             0x02, 0x22, 0x01, 0xff, 0x06, 0x9a, 0x2d, 0x95, 0xd1, 0x96};
  expect(vevor::decode(bonne, f, &reason), "trame saine acceptée");
  expect(f.wind_dir_deg == 289, "trame saine : direction 289°");
  expect_near(f.rain_mm, 59.2f, 0.06f, "trame saine : pluie 59,2 mm");

  // Trame fautive n° 1 : direction 779°, pluie 178,2 mm, vent 34,2 km/h.
  const uint8_t fausse1[21] = {0xaa, 0x00, 0x84, 0xcb, 0x16, 0x02, 0xbb, 0x38, 0x02, 0x1e, 0x10,
                               0x04, 0x44, 0x03, 0xfe, 0x0b, 0x2f, 0x6e, 0x09, 0x2e, 0x0a};
  expect(!vevor::decode(fausse1, f, &reason),
         "trame à décalage de bits n° 1 refusée (direction 779° impossible)");
  expect(std::strcmp(reason, "direction") == 0, "motif de refus = direction, pas un rejet muet");
  // `f` vient d'être rempli par une trame VALIDE juste au-dessus : une trame refusée ne doit PAS
  // rester marquée valide (revue round 2 : `out.valid` était posé AVANT la porte de plausibilité).
  expect(!f.valid, "trame refusée : `valid` reste faux (aucun marquage résiduel)");

  // Trame fautive n° 2 : direction 835°, même signature.
  const uint8_t fausse2[21] = {0xaa, 0x00, 0x84, 0xcb, 0x16, 0x02, 0xba, 0x38, 0x02, 0x62, 0x24,
                               0x04, 0x0c, 0x03, 0xfe, 0x0d, 0x32, 0x3f, 0xad, 0xc7, 0xae};
  expect(!vevor::decode(fausse2, f, &reason), "trame à décalage de bits n° 2 refusée (direction 835°)");
}

// --- 3. Robustesse : entrées dégénérées ----------------------------------------------------
static void test_robustness() {
  printf("Robustesse\n");
  vevor::Frame f;
  const char *reason = "";

  // Tous les octets à 0xAA : le décodeur ne doit pas accepter n'importe quoi.
  uint8_t garbage[21];
  std::memset(garbage, 0xAA, sizeof(garbage));
  expect(!vevor::decode(garbage, f, &reason), "21 octets 0xAA rejetés");

  std::memset(garbage, 0x00, sizeof(garbage));
  expect(!vevor::decode(garbage, f, &reason), "21 octets 0x00 rejetés");

  // Un seul bit de checksum modifié doit invalider la trame.
  uint8_t raw[21] = {0xaa, 0x00, 0xf8, 0xf7, 0x9d, 0x02, 0xe3, 0x32, 0x01, 0x0e, 0x03,
                     0x02, 0x0b, 0x01, 0x38, 0x02, 0x39, 0x7a, 0x86, 0xe0, 0x87};
  raw[7] ^= 0x01;  // humidité altérée, checksum inchangé
  expect(!vevor::decode(raw, f, &reason), "bit modifié → checksum détecte la corruption");
}

// --- 4. Le motif de rejet doit être exploitable dans les logs ------------------------------
static void test_reasons() {
  printf("Motifs de rejet (exploitables par la boucle et par eval_frames.py)\n");
  vevor::Frame f;
  const char *reason = "";

  uint8_t bad_header[21] = {0};
  std::memset(bad_header, 0, sizeof(bad_header));
  bad_header[0] = 0xAB;
  expect(!vevor::decode(bad_header, f, &reason) && std::strcmp(reason, "en-tete") == 0,
         "en-tête invalide → motif « en-tete »");

  const uint8_t good[21] = {0xaa, 0x00, 0xf8, 0xf7, 0x9d, 0x02, 0xe3, 0x32, 0x01, 0x0e, 0x03,
                            0x02, 0x0b, 0x01, 0x38, 0x02, 0x39, 0x7a, 0x86, 0xe0, 0x87};
  uint8_t broken[21];
  std::memcpy(broken, good, sizeof(good));
  broken[19] ^= 0xFF;
  expect(!vevor::decode(broken, f, &reason) && std::strcmp(reason, "checksum") == 0,
         "checksum invalide → motif « checksum »");

  std::memcpy(broken, good, sizeof(good));
  broken[20] = 0x00;
  expect(!vevor::decode(broken, f, &reason) && std::strcmp(reason, "compteur_tx") == 0,
         "compteur incohérent → motif « compteur_tx »");
}

// --- 5. Chaîne complète impulsions → bits → trame (voie asynchrone, sans matériel) ---------
// C'est la chaîne qui tourne réellement sur la carte : `remote_receiver` livre des durées
// d'impulsions signées, le décodeur doit retrouver la trame. Les durées sont fabriquées par
// l'encodeur Python (tests/frames.py --pulses), donc le C++ ne se teste pas contre lui-même.
static void test_pulse_chain() {
  printf("Chaîne impulsions → trame (%d scénarios, périodes essayées par le firmware)\n",
         VEVOR_PULSE_COUNT);
  std::vector<uint8_t> bits(vevor::MAX_BITS);
  for (int i = 0; i < VEVOR_PULSE_COUNT; i++) {
    const VevorPulseScenario &s = VEVOR_PULSE_VECTORS[i];
    uint8_t raw[vevor::FRAME_BYTES];
    int32_t period_used = 0;
    bool inverted = false;
    const bool ok =
        vevor::decode_timings(s.timings, s.count, vevor::PERIOD_CANDIDATES,
                              vevor::PERIOD_CANDIDATE_COUNT, bits.data(), bits.size(), raw,
                              &period_used, &inverted);
    std::string name(s.name);
    expect(ok == s.valid, name + " : extraction " + (ok ? "réussie" : "vide") +
                                (s.valid ? " (attendue réussie)" : " (attendue vide)"));
    if (!ok || !s.valid) {
      continue;
    }
    vevor::Frame f;
    const char *reason = "";
    expect(vevor::decode(raw, f, &reason), name + " : la trame extraite doit être valide");
    expect(f.id == s.id, name + " : id");
    expect_near(f.temp_c, s.temp_c, 0.06f, name + " : température");
    expect_near(f.rain_mm, s.rain_mm, 0.06f, name + " : pluie");
    // Polarité retenue : les AFFICHER ne prouve rien, il faut l'éprouver — le scénario à polarité
    // inversée doit réellement sortir inversé, sinon la bascule de polarité n'est pas testée.
    //
    // Période retenue : on n'exige PAS « == 90 ». Les candidats {90, 88, 89, 87} encadrent la vraie
    // période à ±2 µs et sont indiscernables sur des suites de bits courtes : c'est toujours le
    // PREMIER candidat qui décodable qui gagne, donc exiger 90 ne teste que l'ORDRE de la liste
    // (une simple permutation cassait 7 assertions sans qu'aucun décodage ne soit faux — revue
    // round 2, §2.6). Ce qui doit être vrai ici : un candidat de la liste a été retenu, et la
    // trame est correcte (assertions ci-dessus). La SÉLECTION réelle du bon candidat est éprouvée
    // dans test_period_selection().
    bool period_is_candidate = false;
    for (size_t c = 0; c < vevor::PERIOD_CANDIDATE_COUNT; c++) {
      if (period_used == vevor::PERIOD_CANDIDATES[c]) {
        period_is_candidate = true;
      }
    }
    expect(period_is_candidate, name + " : période retenue membre des candidats");
    const bool want_inverted = name.find("polarite_inversee") != std::string::npos;
    expect(inverted == want_inverted,
           name + " : polarité retenue " + (inverted ? "inversée" : "normale"));
    printf("    %-30s période retenue %d us, polarité %s\n", s.name, (int) period_used,
           inverted ? "inversée" : "normale");
  }
}

// --- 6. Recollage de deux morceaux de rafale -------------------------------------------------
// Ce que le RMT livre réellement quand sa mémoire matérielle (96 symboles) est pleine : DEUX
// morceaux. La coupure tombe à une frontière d'impulsion ou au milieu d'une impulsion — dans ce
// second cas les deux moitiés ont le même signe et doivent être additionnées. Recoller en revanche
// une rafale ENTIÈRE devant la suivante est l'erreur qui a fait publier 60 trames pour 31 mesures
// distinctes le 01/10 (chaque compteur TX deux fois) : d'où le seuil MAX_FRAGMENT_TIMINGS,
// éprouvé ici aussi.
static void test_stitching() {
  printf("Recollage de deux morceaux de rafale (coupure du RMT)\n");
  const VevorPulseScenario *nominal = nullptr;
  for (int i = 0; i < VEVOR_PULSE_COUNT; i++) {
    if (std::strcmp(VEVOR_PULSE_VECTORS[i].name, "impulsions_nominales") == 0) {
      nominal = &VEVOR_PULSE_VECTORS[i];
    }
  }
  expect(nominal != nullptr, "le scénario nominal de référence existe");
  if (nominal == nullptr) {
    return;
  }

  const int32_t *full = nominal->timings;
  const size_t n = nominal->count;
  std::vector<uint8_t> bits(vevor::MAX_BITS);
  int32_t out[512];
  uint8_t raw[vevor::FRAME_BYTES];
  int32_t period_used = 0;
  bool inverted = false;

  // (1) coupure NETTE, à une frontière d'impulsion (signes différents à la soudure)
  size_t k = n / 2;
  while (k > 1 && k + 1 < n && (full[k - 1] >= 0) == (full[k] >= 0)) {
    k++;
  }
  size_t m = vevor::stitch_fragments(full, k, full + k, n - k, out, 512);
  expect(m == n && std::memcmp(out, full, n * sizeof(int32_t)) == 0,
         "coupure nette : le recollage redonne exactement la rafale d'origine");
  expect(vevor::decode_timings(out, m, vevor::PERIOD_CANDIDATES, vevor::PERIOD_CANDIDATE_COUNT,
                               bits.data(), bits.size(), raw, &period_used, &inverted),
         "coupure nette : la trame est retrouvée après recollage");

  // (2) coupure AU MILIEU d'une impulsion : les deux moitiés ont le même signe et sont réunies
  size_t j = 0;
  for (size_t i = n / 3; i < n; i++) {
    if (full[i] > 170 || full[i] < -170) {
      j = i;
      break;
    }
  }
  expect(j != 0, "une impulsion de plusieurs bits a été trouvée pour la couper en deux");
  if (j == 0) {
    return;
  }
  std::vector<int32_t> a(full, full + j + 1);
  std::vector<int32_t> b;
  a[j] = full[j] / 2;              // première moitié
  b.push_back(full[j] - a[j]);     // seconde moitié, MÊME signe
  b.insert(b.end(), full + j + 1, full + n);
  m = vevor::stitch_fragments(a.data(), a.size(), b.data(), b.size(), out, 512);
  expect(m == n && std::memcmp(out, full, n * sizeof(int32_t)) == 0,
         "coupure au milieu d'une impulsion : les deux moitiés sont réunies");
  expect(vevor::decode_timings(out, m, vevor::PERIOD_CANDIDATES, vevor::PERIOD_CANDIDATE_COUNT,
                               bits.data(), bits.size(), raw, &period_used, &inverted),
         "coupure au milieu d'une impulsion : la trame est retrouvée après recollage");

  // (3) un morceau seul (sans son jumeau) ne doit PAS produire de trame — c'est ce que fait le
  //     composant, qui ne tente le recollage que pour une capture COURTE (MAX_FRAGMENT_TIMINGS)
  expect(!vevor::decode_timings(a.data(), a.size(), vevor::PERIOD_CANDIDATES,
                                vevor::PERIOD_CANDIDATE_COUNT, bits.data(), bits.size(), raw,
                                &period_used, &inverted),
         "un morceau seul ne produit pas de trame (d'où le recollage)");
}

// --- 7. Trou inter-rafales : le SAUT doit être réellement exercé ----------------------------
// `timings_to_bits` SAUTE une impulsion trop longue (un trou entre deux rafales) au lieu de la
// convertir en bits. Round 2 : le scénario « trou inter-rafales » se décodait IDENTIQUEMENT avec
// MAX_RUN_BITS porté à 100000 — donc le saut n'était pas exercé. On exige ici que le trou n'ajoute
// AUCUN bit : convertir les durées AVEC le trou et SANS lui doit donner le même nombre de bits (et
// les mêmes bits). Si le saut disparaît (seuil ≥ 8000 / 90 ≈ 88), le trou ajoute ~88 bits et
// l'assertion tombe — la contre-épreuve qui manquait.
static void test_hole_skip() {
  printf("Trou inter-rafales : saut réellement exercé\n");
  const VevorPulseScenario *trou = nullptr;
  for (int i = 0; i < VEVOR_PULSE_COUNT; i++) {
    if (std::strcmp(VEVOR_PULSE_VECTORS[i].name, "impulsions_trou_inter_rafales") == 0) {
      trou = &VEVOR_PULSE_VECTORS[i];
    }
  }
  expect(trou != nullptr, "le scénario « trou inter-rafales » existe");
  if (trou == nullptr) {
    return;
  }
  std::vector<int32_t> avec(trou->timings, trou->timings + trou->count);
  std::vector<int32_t> sans;
  for (int32_t t : avec) {
    if (t >= -4000 && t <= 4000) {  // le trou mesure -8000 : on le retire pour la comparaison
      sans.push_back(t);
    }
  }
  expect(sans.size() + 1 == avec.size(), "exactement une impulsion de trou a été retirée");
  std::vector<uint8_t> bits_avec(vevor::MAX_BITS);
  std::vector<uint8_t> bits_sans(vevor::MAX_BITS);
  const size_t n_avec = vevor::timings_to_bits(avec.data(), avec.size(), 90, false,
                                               bits_avec.data(), bits_avec.size());
  const size_t n_sans = vevor::timings_to_bits(sans.data(), sans.size(), 90, false,
                                               bits_sans.data(), bits_sans.size());
  expect(n_avec == n_sans,
         "le trou n'ajoute aucun bit (sauté, et non converti en ~88 bits de zéro)");
  expect(n_avec == n_sans && std::memcmp(bits_avec.data(), bits_sans.data(), n_avec) == 0,
         "les bits obtenus sont identiques avec et sans le trou");
}

// --- 8. Sélection de la période bit : le balayage des candidats continue après un échec -----
// Deux propriétés, indépendantes de l'ORDRE de la liste de candidats :
//  (1) CHAQUE candidat sait décoder une rafale émise à SA période → 88, 89 ET 87 sont réellement
//      exercés (une seule rafale générée à 88 ne suffisait pas : le décodeur retombait sur 90) ;
//  (2) le balayage CONTINUE après un candidat qui échoue : la rafale à longue suite de bits
//      identiques (impulsions_trame_longue) est sensible à la période et n'est PAS décodable à
//      88 µs ; le décodeur doit passer à 90 et réussir.
static void test_period_selection() {
  printf("Sélection de la période bit (balayage des candidats)\n");
  std::vector<uint8_t> bits(vevor::MAX_BITS);
  uint8_t raw[vevor::FRAME_BYTES];
  int32_t period_used = 0;
  bool inverted = false;

  // (1) chaque candidat, SEUL, décode une rafale émise à sa période.
  int exerces = 0;
  for (int i = 0; i < VEVOR_PULSE_COUNT; i++) {
    const VevorPulseScenario &s = VEVOR_PULSE_VECTORS[i];
    if (!s.valid || s.period_us <= 0) {
      continue;
    }
    const int32_t un[1] = {s.period_us};
    period_used = 0;
    const bool ok = vevor::decode_timings(s.timings, s.count, un, 1, bits.data(), bits.size(),
                                          raw, &period_used, &inverted);
    expect(ok && period_used == s.period_us,
           std::string(s.name) + " : décodable avec le SEUL candidat " +
               std::to_string(s.period_us) + " us");
    if (s.period_us == 88 || s.period_us == 89 || s.period_us == 87) {
      exerces++;
    }
  }
  expect(exerces >= 3, "les candidats 88, 89 ET 87 ont tous été réellement exercés");

  // (2) balayage après échec, sur la rafale sensible à la période.
  const VevorPulseScenario *longue = nullptr;
  for (int i = 0; i < VEVOR_PULSE_COUNT; i++) {
    if (std::strcmp(VEVOR_PULSE_VECTORS[i].name, "impulsions_trame_longue") == 0) {
      longue = &VEVOR_PULSE_VECTORS[i];
    }
  }
  expect(longue != nullptr, "le scénario à longue suite de bits existe");
  if (longue == nullptr) {
    return;
  }
  const int32_t seul88[1] = {88};
  const int32_t sans90[2] = {88, 87};
  const int32_t recherche[2] = {88, 90};
  period_used = 0;
  expect(!vevor::decode_timings(longue->timings, longue->count, seul88, 1, bits.data(),
                                bits.size(), raw, &period_used, &inverted),
         "rafale longue : le candidat 88 SEUL échoue (elle est vraiment sensible à la période)");
  expect(!vevor::decode_timings(longue->timings, longue->count, sans90, 2, bits.data(),
                                bits.size(), raw, &period_used, &inverted),
         "rafale longue : sans le candidat 90, aucun candidat ne décode (88 et 87 échouent)");
  period_used = 0;
  expect(vevor::decode_timings(longue->timings, longue->count, recherche, 2, bits.data(),
                               bits.size(), raw, &period_used, &inverted) && period_used == 90,
         "rafale longue : le balayage CONTINUE après l'échec de 88 et atteint 90");
}

// --- 9. Politique de recollage : un MORCEAU se recolle, une rafale COMPLÈTE non -------------
// Le composant ne recolle que si `vevor::is_fragment(taille)` est vrai (prédicat partagé avec le
// test). Les bornes (MIN_TIMINGS = 40, MAX_FRAGMENT_TIMINGS = 160) n'étaient testées nulle part, et
// recoller une rafale COMPLÈTE faisait relire la PRÉCÉDENTE (mesuré le 01/10 : 60 trames pour 31
// mesures distinctes). On éprouve les deux cas : rafale livrée en DEUX morceaux → recollage ;
// capture complète → PAS de recollage.
static void test_fragment_policy() {
  printf("Politique de recollage (morceau vs rafale complète)\n");
  // bornes du prédicat : 40 inclus, 160 inclus, au-delà non.
  expect(!vevor::is_fragment(39), "39 impulsions : trop court, pas un morceau");
  expect(vevor::is_fragment(40), "40 impulsions : morceau (borne basse incluse)");
  expect(vevor::is_fragment(160), "160 impulsions : morceau (borne haute incluse)");
  expect(!vevor::is_fragment(161), "161 impulsions : n'est plus un morceau");
  // tailles RÉELLES mesurées sur ce montage : morceaux 96 et 82 ; rafale complète 176-184.
  expect(vevor::is_fragment(96) && vevor::is_fragment(82),
         "les deux morceaux mesurés (96 + 82) seront recollés");
  expect(!vevor::is_fragment(184),
         "une rafale complète mesurée (184) n'est PAS un morceau : jamais recollée");
  expect(!vevor::is_fragment(204), "204 impulsions : capture complète, jamais recollée");

  // Cas « DEUX MORCEAUX » : la rafale nominale coupée en deux, chaque moitié étant un morceau,
  // puis recollée — c'est exactement la décision du composant (fragment ET morceau précédent).
  const VevorPulseScenario *nominal = nullptr;
  for (int i = 0; i < VEVOR_PULSE_COUNT; i++) {
    if (std::strcmp(VEVOR_PULSE_VECTORS[i].name, "impulsions_nominales") == 0) {
      nominal = &VEVOR_PULSE_VECTORS[i];
    }
  }
  expect(nominal != nullptr, "le scénario nominal de référence existe");
  if (nominal == nullptr) {
    return;
  }
  const size_t n = nominal->count;
  const size_t k = n / 2;
  expect(vevor::is_fragment(k) && vevor::is_fragment(n - k),
         "les deux moitiés de la rafale nominale sont des morceaux");
  std::vector<int32_t> out(n);
  const size_t m = vevor::stitch_fragments(nominal->timings, k, nominal->timings + k, n - k,
                                           out.data(), out.size());
  std::vector<uint8_t> bits(vevor::MAX_BITS);
  uint8_t raw[vevor::FRAME_BYTES];
  int32_t period_used = 0;
  bool inverted = false;
  expect(m == n && vevor::decode_timings(out.data(), m, vevor::PERIOD_CANDIDATES,
                                         vevor::PERIOD_CANDIDATE_COUNT, bits.data(), bits.size(),
                                         raw, &period_used, &inverted),
         "deux morceaux recollés : la trame est retrouvée");
}

int main() {
  printf("=== Tests du décodeur Vevor 7-en-1 (sans matériel) ===\n\n");
  test_vectors();
  test_rtl433_reference();
  test_lux_x10_anchor();
  test_plausibility();
  test_robustness();
  test_reasons();
  test_pulse_chain();
  test_stitching();
  test_period_selection();
  test_hole_skip();
  test_fragment_policy();

  printf("\n%d vérifications, %d échec(s)\n", g_checks, g_failures);
  if (g_failures == 0) {
    printf("%s TOUS LES TESTS PASSENT\n", CHECK);
    return 0;
  }
  printf("%s %d ÉCHEC(S)\n", FAIL, g_failures);
  return 1;
}
