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
static void test_rtl433_reference() {
  printf("Trame de référence rtl_433 (valeurs vérifiables à la main)\n");
  const uint8_t raw[21] = {0xaa, 0x00, 0xf8, 0xf7, 0x9d, 0x02, 0xe3, 0x32, 0x01, 0x0e, 0x03,
                           0x02, 0x0b, 0x01, 0x38, 0x02, 0x39, 0x7a, 0x86, 0xe0, 0x87};
  vevor::Frame f;
  const char *reason = "";
  expect(vevor::decode(raw, f, &reason), "la trame de référence doit être acceptée");
  expect(f.id == 0xf8f7, "id = 0xf8f7");
  expect(f.temp_c > 23.8f && f.temp_c < 24.0f, "température = 23,9 °C");
  expect(f.humidity == 50, "humidité = 50 %");
  expect(f.wind_dir_deg == 266, "direction = 266°");
  expect(f.rain_mm > 12.7f && f.rain_mm < 12.9f, "pluie = 12,8 mm");
  expect(f.uv_index == 1, "UV = 1");
  expect(f.lux == 14457, "luminosité = 14 457 lx");
  expect(f.tx_counter == 0x86, "compteur TX = 0x86");
  expect(f.battery_low, "batterie faible (0x9d)");
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
    printf("    %-30s période retenue %d us, polarité %s\n", s.name, (int) period_used,
           inverted ? "inversée" : "normale");
  }
}

int main() {
  printf("=== Tests du décodeur Vevor 7-en-1 (sans matériel) ===\n\n");
  test_vectors();
  test_rtl433_reference();
  test_robustness();
  test_reasons();
  test_pulse_chain();

  printf("\n%d vérifications, %d échec(s)\n", g_checks, g_failures);
  if (g_failures == 0) {
    printf("%s TOUS LES TESTS PASSENT\n", CHECK);
    return 0;
  }
  printf("%s %d ÉCHEC(S)\n", FAIL, g_failures);
  return 1;
}
